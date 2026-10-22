#!/usr/bin/env python
"""Record (or re-derive) the content-interpreter pin -- the producer W12 adds.

Before W12 nothing in the repository *produced* the interpreter the save-format
content verifier runs under; three call sites each guessed it from
``%LOCALAPPDATA%`` and nothing recorded which one was meant.  This script is the
missing producer: it reads one explicitly named interpreter, records its
``path``/``sha256``/``version`` together with the dependency versions and the
decoder digest, and writes them as the pin consumed by
``backend/content_interpreter_pin.py``.

It never guesses.  ``--python`` is required; if you do not say which interpreter
to pin, this refuses rather than searching.  Nothing is installed, downloaded,
or modified except the single output file (and nothing at all under
``--dry-run``).

    python -B tools/game-executor/record-content-interpreter-pin.py \
        --python "$LOCALAPPDATA/Programs/Python/Python313/python.exe" --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUT = 'config/save-content-interpreter.lock.json'
DEFAULT_DECODER = 'tools/game-executor/verify-created-save.py'
DEFAULT_DEP_SOURCE = 'third_party/auto-miliastra/src'

#: Asked of the interpreter being pinned; it must answer for itself.
VERSION_PROBE = (
    "import json,sys\n"
    "out={'python_version':sys.version.split()[0],'executable':sys.executable}\n"
    "try:\n"
    "    import google.protobuf as p\n"
    "    out['protobuf_version']=getattr(p,'__version__',None)\n"
    "except Exception as e:\n"
    "    out['protobuf_version']=None;out['protobuf_error']='%s: %s'%(type(e).__name__,e)\n"
    "sys.stdout.write(json.dumps(out))\n"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def probe(python: Path) -> dict:
    proc = subprocess.run([str(python), '-B', '-c', VERSION_PROBE],
                          capture_output=True)
    if proc.returncode != 0:
        raise SystemExit('refusing to pin: the interpreter did not answer the '
                         'version probe (rc=%d):\n%s'
                         % (proc.returncode, proc.stderr.decode('utf-8', 'replace')))
    return json.loads(proc.stdout.decode('utf-8'))


def build_document(python: Path, decoder: Path, dep_source: str) -> dict:
    if not python.is_file():
        raise SystemExit('refusing to pin: no interpreter at %s' % python)
    if not decoder.is_file():
        raise SystemExit('refusing to pin: no decoder at %s' % decoder)
    facts = probe(python)
    if not facts.get('protobuf_version'):
        raise SystemExit(
            'refusing to pin %s: it cannot import google.protobuf (%s). A pin that '
            'records an interpreter which cannot run the decoder would only move the '
            'silent failure.' % (python, facts.get('protobuf_error')))
    return {
        '$comment': ('Pinned provenance of the interpreter the save-format content verifier '
                     'runs under. Re-derived by tools/game-executor/record-content-interpreter-pin.py '
                     '- offline, read-only. Do not hand-edit; re-derive and review the diff.'),
        'kind': 'ds-save-content-interpreter-pin',
        'recordedBy': 'tools/game-executor/record-content-interpreter-pin.py',
        'recordedFrom': 'local interpreter queried directly; no network, nothing installed',
        'interpreter': {
            'path': str(python),
            'sha256': sha256_file(python),
            'version': facts['python_version'],
        },
        'dependencies': {
            'protobuf': {'module': 'google.protobuf', 'version': facts['protobuf_version']},
            'miliastraAgent': {'module': 'miliastra_agent.parsers.entities',
                               'sourceRel': dep_source.replace('\\', '/'),
                               'tracked': False},
        },
        'decoder': {
            'path': str(decoder.relative_to(ROOT)).replace('\\', '/'),
            'sha256': sha256_file(decoder),
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True,
                        help='the interpreter to pin (explicit; this tool never searches)')
    parser.add_argument('--decoder', default=DEFAULT_DECODER,
                        help='decoder to pin, repo-relative (default: %s)' % DEFAULT_DECODER)
    parser.add_argument('--dep-source', default=DEFAULT_DEP_SOURCE,
                        help='git-ignored dependency source recorded alongside (default: %s)'
                             % DEFAULT_DEP_SOURCE)
    parser.add_argument('--out', default=DEFAULT_OUT,
                        help='where to write the pin, repo-relative (default: %s)' % DEFAULT_OUT)
    parser.add_argument('--dry-run', action='store_true',
                        help='print the pin to stdout and write nothing')
    args = parser.parse_args(argv)

    python = Path(args.python)
    if not python.is_absolute():
        python = (Path.cwd() / python).resolve()
    decoder = ROOT / args.decoder
    doc = build_document(python, decoder, args.dep_source)
    blob = json.dumps(doc, indent=2, ensure_ascii=False) + '\n'
    if args.dry_run:
        sys.stdout.write(blob)
        return 0
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding='utf-8')
    sys.stdout.write('wrote %s\n' % out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
