"""Offline tests for the W12 content-interpreter pin.

Two things are proved here:

* ``GuessControlTest`` encodes the PRE-W12 behaviour on purpose: it asserts that
  a bare ``_discover_content_python({})`` returns the ``%LOCALAPPDATA%``-derived
  python.exe.  Run against the pre-patch module it is GREEN; run against the
  patched module it is RED, because the guess is gone.  That is the control that
  shows the patch actually changed the behaviour rather than merely adding code.
* ``InterpreterPinTest`` proves the patched behaviour: a pin that holds resolves,
  and every way it can fail has its own name.

Everything is hermetic: the pin, the interpreter, the decoder and the probe
output are all fakes built under a temp directory, so nothing here touches the
live machine, the game, or the real interpreter.  The real interpreter is only
exercised by the separate, read-only ``record`` evidence run.

    <python> -B -m unittest backend.tests.test_content_interpreter_pin
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import save_verification as sv  # noqa: E402

try:
    from backend import content_interpreter_pin as pin
except ImportError:  # pragma: no cover - the pre-patch tree has no pin module
    pin = None


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


REAL_DECODER_REL = 'tools/game-executor/verify-created-save.py'
REAL_DECODER = ROOT / REAL_DECODER_REL


def probe_runner(python_version='3.13.13', protobuf='7.34.1',
                 decoder_deps=True, decoder_deps_error=None, error=None):
    """A stand-in for the pinned-interpreter probe; records whether it was run."""
    calls = []

    def run(argv, timeout):
        calls.append(list(argv))
        if error is not None:
            raise OSError(error)
        payload = {'python_version': python_version,
                   'executable': argv[0] if argv else None,
                   'protobuf_version': protobuf}
        if protobuf is None:
            payload['protobuf_error'] = 'ModuleNotFoundError: No module named \'google\''
        payload['decoder_deps'] = decoder_deps
        if decoder_deps_error:
            payload['decoder_deps_error'] = decoder_deps_error
        return {'argv': list(argv), 'returncode': 0,
                'stdout': json.dumps(payload), 'stderr': ''}

    run.calls = calls
    return run


class GuessControlTest(unittest.TestCase):
    """CONTROL: the exact behaviour the patch removes.

    Green against the pre-patch module, RED against the patched one.  The
    assertion is deliberately written against the OLD contract (no ``runner``
    argument, a plain string return) so it exercises both modules unchanged.
    """

    # EXPECTED FAILURE IN A MERGED TREE -- and that is the control working.
    #
    # Measured by the main line 2026-10-05, in the tree where the W12 patch IS applied:
    # this control is red, exactly as its docstring says it must be.  Two details worth
    # recording, because the red is not the obvious one:
    #
    #   (a) the test binds ``from backend import save_verification as sv`` -- the LIVE
    #       module, not a pristine copy -- so its expectation ("returns the LOCALAPPDATA
    #       guess") only ever held in a PRE-patch tree.  It was green where W12 ran it
    #       because that tree was unpatched; merging the patch is what turns it red.
    #   (b) on THIS machine the value it returns is unchanged, because the pinned
    #       interpreter path happens to be byte-identical to the old guess.  So the
    #       control's *value* assertion cannot separate pin from guess here; only the
    #       sha256/version pinning in the pin module can, and that is what the tests in
    #       InterpreterPinTest exercise.
    #
    # Marked expectedFailure rather than deleted, following the project's own idiom for a
    # recorded deviation (backend/tests/f011guard/test_f011guard.py).  The control keeps
    # its teeth: revert the W12 patch and this becomes an unexpected SUCCESS, which fails
    # the suite loudly -- which is the signal that the guess is back.
    @unittest.expectedFailure
    def test_control_bare_discovery_returns_the_localappdata_guess(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='w12-control-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        exe = tmp / 'Local' / 'Programs' / 'Python' / 'Python313' / 'python.exe'
        exe.parent.mkdir(parents=True)
        # Deliberately not a real interpreter: the old code only checked is_file().
        exe.write_bytes(b'MZ this is not really an interpreter\n')

        saved = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = str(tmp / 'Local')
        try:
            found = sv._discover_content_python({})
        finally:
            if saved is None:
                os.environ.pop('LOCALAPPDATA', None)
            else:
                os.environ['LOCALAPPDATA'] = saved

        self.assertEqual(
            found, str(exe),
            'CONTROL: the pre-W12 module guessed %LOCALAPPDATA%/Programs/Python/'
            'Python313/python.exe and returned it without checking anything. After the '
            'W12 patch this must fail, because that guess is gone.')


@unittest.skipIf(pin is None, 'pre-patch tree: no content_interpreter_pin module')
class InterpreterPinTest(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='w12-pin-'))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / 'repo'
        (self.root / 'config').mkdir(parents=True)
        # A decoder whose bytes we control, at the real relative path.
        self.decoder = self.root / REAL_DECODER_REL
        self.decoder.parent.mkdir(parents=True)
        self.decoder_bytes = b'# stand-in content verifier\n'
        self.decoder.write_bytes(self.decoder_bytes)
        # A stand-in interpreter whose bytes we control.
        self.exe = self.root / 'Python313' / 'python.exe'
        self.exe.parent.mkdir(parents=True)
        self.exe_bytes = b'MZ stand-in interpreter\n'
        self.exe.write_bytes(self.exe_bytes)
        self.pin_file = self.root / pin.DEFAULT_PIN_REL

    def write_pin(self, **overrides):
        doc = {
            'kind': pin.PIN_KIND,
            'interpreter': {'path': str(self.exe),
                            'sha256': overrides.pop('exe_sha', sha256(self.exe_bytes)),
                            'version': overrides.pop('version', '3.13.13')},
            'dependencies': {'protobuf': {'version': overrides.pop('protobuf', '7.34.1')},
                             'miliastraAgent': {'sourceRel': '.runtime/research-sources/x'}},
            'decoder': {'path': REAL_DECODER_REL,
                        'sha256': overrides.pop('decoder_sha', sha256(self.decoder_bytes))},
        }
        doc.update(overrides)
        self.pin_file.write_text(json.dumps(doc), encoding='utf-8')
        return self.pin_file

    def verify(self, run=None, pin_path=None, **overrides):
        if overrides:
            self.write_pin(**overrides)
        elif not self.pin_file.exists() and pin_path is None:
            self.write_pin()
        return pin.verify(pin_path=pin_path or self.pin_file,
                          project_root=self.root, run=run or probe_runner())

    # -- the happy path --------------------------------------------------- #
    def test_pin_that_holds_resolves_and_records(self):
        facts = self.verify()
        self.assertIsNone(facts['reason'], json.dumps(facts, default=str)[:600])
        self.assertTrue(facts['pinLoaded'])
        self.assertEqual(facts['interpreterPath'], str(self.exe))
        self.assertEqual(facts['sha256Matches'], True)
        self.assertEqual(facts['versionMatches'], True)
        self.assertEqual(facts['protobufMatches'], True)
        self.assertEqual(facts['decoderShaMatches'], True)
        recorded = facts['recorded']
        self.assertEqual(recorded['interpreterActual']['version'], '3.13.13')
        self.assertEqual(recorded['protobufActual'], '7.34.1')
        self.assertEqual(recorded['decoderActualSha256'], sha256(self.decoder_bytes))

    # -- every refusal by name -------------------------------------------- #
    def test_absent_pin_is_refused_by_name(self):
        facts = self.verify(pin_path=self.root / 'config' / 'nope.json')
        self.assertEqual(facts['reason'], 'pin-missing')
        self.assertFalse(facts['pinLoaded'])

    def test_ill_typed_pin_is_refused_by_name(self):
        self.pin_file.write_text(json.dumps({'kind': 'something-else'}), encoding='utf-8')
        facts = pin.verify(pin_path=self.pin_file, project_root=self.root, run=probe_runner())
        self.assertEqual(facts['reason'], 'pin-ill-typed')

    def test_missing_interpreter_is_refused_by_name(self):
        facts = self.verify()
        self.exe.unlink()
        facts = self.verify()
        self.assertEqual(facts['reason'], 'interpreter-missing')

    def test_replaced_interpreter_is_refused_and_never_executed(self):
        run = probe_runner()
        # Pin a digest the file does NOT have: the interpreter was replaced.
        self.write_pin(exe_sha='ab' * 32)
        facts = pin.verify(pin_path=self.pin_file, project_root=self.root, run=run)
        self.assertEqual(facts['reason'], 'interpreter-replaced')
        self.assertFalse(facts['sha256Matches'])
        self.assertEqual(run.calls, [],
                         'a replaced interpreter must be refused BEFORE it is executed')

    def test_version_mismatch_is_refused_by_name(self):
        facts = self.verify(run=probe_runner(python_version='3.12.9'))
        self.assertEqual(facts['reason'], 'interpreter-version-mismatch')
        self.assertEqual(facts['versionActual'], '3.12.9')

    def test_missing_dependency_is_refused_by_name(self):
        facts = self.verify(run=probe_runner(
            decoder_deps=False,
            decoder_deps_error="ModuleNotFoundError: No module named 'miliastra_agent'"))
        self.assertEqual(facts['reason'], 'dependency-missing')
        self.assertIn('miliastra_agent', facts['decoderDepsError'])

    def test_protobuf_version_drift_is_refused_by_name(self):
        facts = self.verify(run=probe_runner(protobuf='6.0.0'))
        self.assertEqual(facts['reason'], 'dependency-version-mismatch')
        self.assertEqual(facts['protobufActual'], '6.0.0')

    def test_changed_decoder_is_refused_by_name(self):
        self.decoder.write_bytes(b'# a looser content verifier\n')
        facts = self.verify()
        self.assertEqual(facts['reason'], 'decoder-changed')

    # -- the stage surface ------------------------------------------------ #
    def test_stage_emits_one_named_finding_per_fact(self):
        self.write_pin(decoder_sha='cd' * 32)   # decoder drifted
        manifest = {'contentPythonPin': str(self.pin_file)}
        resolution = sv._resolve_content_python(manifest, runner=probe_runner())
        self.assertIsNone(resolution['python'])
        by_id = {f['id']: f for f in resolution['findings']}
        self.assertEqual(by_id['content.decoderDigest']['status'], sv.FAIL)
        self.assertEqual(by_id['content.interpreterPinned']['status'], sv.PASS)
        self.assertIn('decoderActualSha256', json.dumps(by_id['content.interpreterRecorded']['detail']))
        self.assertIsNone(sv._discover_content_python(manifest, runner=probe_runner()))

    def test_unpinned_manifest_override_is_refused_not_trusted(self):
        self.write_pin()
        manifest = {'contentPythonPin': str(self.pin_file),
                    'contentPython': 'C:/somewhere/else/python.exe'}
        resolution = sv._resolve_content_python(manifest, runner=probe_runner())
        refused = [f for f in resolution['findings'] if f['id'] == 'content.unpinnedOverrideRefused']
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]['status'], sv.BLOCKED)
        self.assertIsNone(resolution['python'],
                          'an unpinned override must not resolve to an interpreter')


if __name__ == '__main__':
    unittest.main()
