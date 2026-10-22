"""Pin, never guess, the interpreter that can deserialise the save format.

The content verifier (``tools/game-executor/verify-created-save.py``) cannot run
under the MCP venv: it needs ``google.protobuf`` and the ``miliastra_agent``
package that lives under the git-ignored ``.runtime/research-sources`` tree, so
the project runs it under a separate, full CPython installation.

Until W12 (2026-10-05) the call sites *guessed* that installation::

    Path(os.environ.get('LOCALAPPDATA', ...)) / 'Programs/Python/Python313/python.exe'

A guess that happens to be right on one machine is the worst kind of correct.
It is silent; it stops being right without saying so; and a *different*
interpreter dropped at the same path is accepted without a murmur.  Three
modules guessed independently (``backend/save_verification.py``,
``backend/entity_server.py``, ``tools/entity-create/run_parameter_matrix.py``)
and nothing in the repository recorded which interpreter was meant.

This module replaces the guess with an explicit pin.  The pin file
(``config/save-content-interpreter.lock.json``) records:

* the interpreter *path*, its ``sha256`` and its ``version`` -- so "the file
  moved", "the bytes were replaced" and "the version drifted" are three
  different, nameable facts;
* the dependency versions the decoder needs (``protobuf``), because "the
  interpreter is present" is not the same as "the interpreter can run the
  decoder";
* the decoder itself as ``{path, sha256}``, so substituting a looser verifier is
  refused the same way ``_discover_gate`` refuses a different gate.

Nothing here installs, downloads, edits, or runs anything on its own.  It reads
the machine and reports facts; the caller decides how to weigh them.  Two
properties matter and are enforced by construction:

* ``verify`` never *returns* an interpreter it could not confirm.  A path is
  returned only when the pin loaded, the path exists, the ``sha256`` matches, the
  version matches, the declared dependency imports with the recorded version, and
  the decoder bytes match.
* ``verify`` never *executes* an interpreter whose bytes do not match the pin.
  The version/dependency probe is only launched after the ``sha256`` check
  passes, so a replaced binary is refused before it is run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

DEFAULT_PIN_REL = 'config/save-content-interpreter.lock.json'
PIN_KIND = 'ds-save-content-interpreter-pin'
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Named refusal codes, in the order they outrank one another.  The first fact
#: that does not hold becomes ``reason``.
REFUSAL_ORDER = (
    'pin-missing',
    'pin-ill-typed',
    'interpreter-missing',
    'interpreter-replaced',
    'interpreter-version-mismatch',
    'dependency-missing',
    'dependency-version-mismatch',
    'decoder-missing',
    'decoder-changed',
)

#: Runs *under the pinned interpreter* and reports the facts only that
#: interpreter can report: its own version, and whether the decoder's own import
#: chain resolves.  ``-B`` means no bytecode is written; stdout only; nothing on
#: the machine is touched.  The decoder's dependency chain is imported the same
#: way the verifier imports it (through ``build-newdemo-static.py``, which is
#: what puts the git-ignored ``auto-miliastra/src`` root on ``sys.path``), so a
#: missing dependency fails here for the same reason it would fail in the
#: verifier -- but with a name attached.
PROBE_SOURCE = r'''
import json, sys, pathlib, importlib.util
out = {"python_version": sys.version.split()[0], "executable": sys.executable}
try:
    import google.protobuf as _p
    out["protobuf_version"] = getattr(_p, "__version__", None)
except Exception as exc:  # noqa: BLE001 - the failure is the datum
    out["protobuf_version"] = None
    out["protobuf_error"] = "%s: %s" % (type(exc).__name__, exc)
try:
    root = pathlib.Path(sys.argv[1])
    spec = importlib.util.spec_from_file_location(
        "csp_decoder_builder", root / "tools/editor-bridge/build-newdemo-static.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from miliastra_agent.parsers.entities import parse_payload  # noqa: F401
    out["decoder_deps"] = True
except Exception as exc:  # noqa: BLE001
    out["decoder_deps"] = False
    out["decoder_deps_error"] = "%s: %s" % (type(exc).__name__, exc)
sys.stdout.write(json.dumps(out))
'''

_MISSING_MODULE_RE = re.compile(r"No module named '([^']+)'")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _as_text(blob):
    if isinstance(blob, bytes):
        return blob.decode('utf-8', 'replace')
    return blob or ''


def _default_run(argv, timeout):
    """Same contract as ``save_verification._run`` -- so a caller can inject one."""
    proc = subprocess.run(argv, capture_output=True, timeout=timeout)
    return {'argv': argv, 'returncode': proc.returncode,
            'stdout': _as_text(proc.stdout), 'stderr': _as_text(proc.stderr)}


def pin_file_path(project_root=None, override=None, env=None):
    """Where the pin lives.  An override names another *pin file*, never an
    interpreter: relocating the pin is allowed, relocating the interpreter
    without recording its digest is not."""
    env = os.environ if env is None else env
    if override:
        return Path(override)
    chosen = env.get('DS_SAVE_CONTENT_PYTHON_PIN')
    if chosen:
        return Path(chosen)
    root = Path(project_root) if project_root else REPO_ROOT
    return root / DEFAULT_PIN_REL


def _blank_result(path):
    return {
        'pinPath': str(path),
        'pinLoaded': False, 'pinError': None,
        'interpreterPath': None, 'pathExists': False,
        'sha256Expected': None, 'sha256Actual': None, 'sha256Matches': False,
        'versionExpected': None, 'versionActual': None, 'versionMatches': False,
        'protobufExpected': None, 'protobufActual': None, 'protobufMatches': False,
        'protobufImportable': False, 'protobufError': None,
        'decoderDeps': None, 'decoderDepsError': None,
        'dependencySourceRel': None, 'dependencySourceExists': None,
        'decoderPath': None, 'decoderShaExpected': None, 'decoderShaActual': None,
        'decoderShaMatches': False,
        'probeRan': False, 'probeError': None,
        'recorded': {},
    }


def _load_pin(path, result):
    try:
        blob = Path(path).read_text(encoding='utf-8')
    except OSError as exc:
        result['pinError'] = 'pin-missing: %s' % exc
        return None
    try:
        pin = json.loads(blob)
    except ValueError as exc:
        result['pinError'] = 'pin-ill-typed: not JSON: %s' % exc
        return None
    if not isinstance(pin, dict):
        result['pinError'] = 'pin-ill-typed: top level is %s, not an object' % type(pin).__name__
        return None
    if pin.get('kind') != PIN_KIND:
        result['pinError'] = ("pin-ill-typed: kind is %r, expected %r"
                              % (pin.get('kind'), PIN_KIND))
        return None
    interp = pin.get('interpreter')
    decoder = pin.get('decoder')
    if not isinstance(interp, dict) or not isinstance(decoder, dict):
        result['pinError'] = 'pin-ill-typed: interpreter/decoder must be objects'
        return None
    for key in ('path', 'sha256', 'version'):
        if not isinstance(interp.get(key), str) or not interp.get(key):
            result['pinError'] = 'pin-ill-typed: interpreter.%s missing' % key
            return None
    for key in ('path', 'sha256'):
        if not isinstance(decoder.get(key), str) or not decoder.get(key):
            result['pinError'] = 'pin-ill-typed: decoder.%s missing' % key
            return None
    return pin


def _first_reason(result):
    """The first refusal the facts justify, or None when every fact holds."""
    if not result['pinLoaded']:
        return 'pin-missing' if 'pin-missing' in (result['pinError'] or '') else 'pin-ill-typed'
    if not result['pathExists']:
        return 'interpreter-missing'
    if not result['sha256Matches']:
        return 'interpreter-replaced'
    if not result['versionMatches']:
        return 'interpreter-version-mismatch'
    if not result['protobufImportable'] or result['decoderDeps'] is False:
        return 'dependency-missing'
    if not result['protobufMatches']:
        return 'dependency-version-mismatch'
    if not result['decoderShaMatches']:
        return 'decoder-missing' if not result['decoderShaActual'] else 'decoder-changed'
    return None


def verify(pin_path=None, project_root=None, run=None, timeout=60):
    """Read the machine and report every pin fact.  Nothing is repaired.

    ``run`` has the ``(argv, timeout) -> {'returncode', 'stdout', 'stderr'}``
    contract of ``save_verification._run`` so a caller (or a test) can inject it.
    """
    run = run or _default_run
    root = Path(project_root) if project_root else REPO_ROOT
    path = Path(pin_path) if pin_path else pin_file_path(root)
    result = _blank_result(path)

    pin = _load_pin(path, result)
    if pin is None:
        result['reason'] = _first_reason(result)
        result['recorded'] = {}
        return result
    result['pinLoaded'] = True

    interp = pin['interpreter']
    python = interp['path']
    result['interpreterPath'] = python
    result['sha256Expected'] = interp['sha256'].lower()
    result['versionExpected'] = interp['version']
    deps = pin.get('dependencies') or {}
    proto = deps.get('protobuf') or {}
    result['protobufExpected'] = proto.get('version')
    result['dependencySourceRel'] = (deps.get('miliastraAgent') or {}).get('sourceRel')

    decoder = pin['decoder']
    decoder_file = root / decoder['path']
    result['decoderPath'] = str(decoder_file)
    result['decoderShaExpected'] = decoder['sha256'].lower()

    exe = Path(python)
    result['pathExists'] = exe.is_file()
    if result['pathExists']:
        try:
            result['sha256Actual'] = _sha256_file(exe)
        except OSError as exc:
            result['probeError'] = 'cannot hash interpreter: %s' % exc
        else:
            result['sha256Matches'] = result['sha256Actual'] == result['sha256Expected']

    # Only run the pinned interpreter once its bytes are known to match.  A
    # replaced binary is refused before it is executed.
    if result['pathExists'] and result['sha256Matches']:
        try:
            probe = run([python, '-B', '-c', PROBE_SOURCE, str(root)], timeout)
        except Exception as exc:  # noqa: BLE001 - a failed probe is a datum
            result['probeError'] = '%s: %s' % (type(exc).__name__, exc)
        else:
            result['probeRan'] = True
            payload = None
            try:
                payload = json.loads(_as_text(probe.get('stdout')))
            except (ValueError, TypeError):
                result['probeError'] = ('probe returned no JSON (rc=%s): %s'
                                        % (probe.get('returncode'),
                                           _as_text(probe.get('stderr'))[-400:]))
            if isinstance(payload, dict):
                result['versionActual'] = payload.get('python_version')
                result['versionMatches'] = result['versionActual'] == result['versionExpected']
                result['protobufActual'] = payload.get('protobuf_version')
                result['protobufError'] = payload.get('protobuf_error')
                result['protobufImportable'] = bool(result['protobufActual'])
                result['protobufMatches'] = (
                    result['protobufImportable']
                    and result['protobufActual'] == result['protobufExpected'])
                result['decoderDeps'] = payload.get('decoder_deps')
                result['decoderDepsError'] = payload.get('decoder_deps_error')
            else:
                err = result['probeError'] or ''
                miss = _MISSING_MODULE_RE.search(err)
                if miss:
                    result['decoderDeps'] = False
                    result['decoderDepsError'] = 'No module named %r' % miss.group(1)

    if result['dependencySourceRel']:
        result['dependencySourceExists'] = (root / result['dependencySourceRel']).is_dir()

    if decoder_file.is_file():
        try:
            result['decoderShaActual'] = _sha256_file(decoder_file)
        except OSError:
            result['decoderShaActual'] = None
        result['decoderShaMatches'] = result['decoderShaActual'] == result['decoderShaExpected']

    result['reason'] = _first_reason(result)
    result['recorded'] = {
        'interpreterExpected': {'path': result['interpreterPath'],
                                'version': result['versionExpected'],
                                'sha256': result['sha256Expected']},
        'interpreterActual': {'path': result['interpreterPath'],
                              'version': result['versionActual'],
                              'sha256': result['sha256Actual']},
        'protobufExpected': result['protobufExpected'],
        'protobufActual': result['protobufActual'],
        'decoderExpectedSha256': result['decoderShaExpected'],
        'decoderActualSha256': result['decoderShaActual'],
    }
    return result


def resolved_interpreter(pin_path=None, project_root=None, run=None, timeout=60):
    """The pinned interpreter path, or None.  Never a guess.

    This is the whole public contract the call sites need; use ``verify`` when
    the named reason matters.
    """
    facts = verify(pin_path=pin_path, project_root=project_root, run=run, timeout=timeout)
    return facts['interpreterPath'] if facts.get('reason') is None else None
