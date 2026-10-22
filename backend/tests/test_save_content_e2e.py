"""End-to-end check that the PINNED interpreter really runs the real decoder.

The full ``test_save_verification`` suite needs the deep
``Beyond_Local_Save_Level/<id>/<id>.gil`` fixtures, whose absolute paths exceed
Windows' 260-character MAX_PATH once the tree is assembled anywhere under a
worker output directory -- so that suite cannot be run from here.  This test
proves the part W12 is responsible for, with the shallow fixtures it *can* read:

* the pin resolves to the real CPython install,
* the content verifier is actually launched under that interpreter (a real
  subprocess, real protobuf, real ``miliastra_agent`` from the git-ignored
  tree), and
* the decoder's report is the real one for the recorded save bytes.

The decoder writes its report under ``.runtime/game-executor/cordis-plan/``; in
the assembled copy that is this test's own directory, never the real tree.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend import save_verification as sv  # noqa: E402

RUN = ROOT / '.runtime/game-executor/scene-cli/20260929-153705-save-fe06e18c'
LEVEL = 1073741839
ADDED_ID = 1077936132
INTENT = {'entityId': ADDED_ID, 'templateId': 20001034, 'name': '石质元素立方体',
          'position': [-10.0, 0.0, -20.0], 'rotation': [0.0, 0.0, 0.0],
          'scale': [1.25, 1.0, 1.0]}


def sha256_file(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


class ContentDecoderEndToEndTest(unittest.TestCase):
    def setUp(self):
        if not RUN.is_dir():
            self.skipTest(f'missing shallow fixture {RUN}')
        # Clear any report this case may have produced on a previous run.
        out = ROOT / sv.CONTENT_OUT_ROOT / f'e2e-{LEVEL}-e2e' / 'DS-05'
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)

    def test_pinned_interpreter_runs_the_real_decoder(self):
        before = RUN / f'before-{LEVEL}.gil'
        after = RUN / f'after-{LEVEL}.gil'
        manifest = {
            'caseId': 'e2e', 'runId': f'e2e-{LEVEL}', 'levelId': LEVEL,
            'files': {'gilBefore': {'path': str(before), 'sha256': sha256_file(before)},
                      'gilAfter': {'path': str(after), 'sha256': sha256_file(after)}},
            'intent': INTENT,
        }
        findings = []
        report = sv._content_report_from_run(manifest, findings, 300, sv._run)
        by_id = {f['id']: f for f in findings}
        # The pin resolved and the interpreter/dependency facts are all PASS.
        self.assertIn('content.interpreterPinned', by_id)
        self.assertEqual(by_id['content.interpreterPinned']['status'], sv.PASS,
                         json.dumps(by_id.get('content.interpreterPinned'), default=str))
        if 'content.dependenciesImportable' in by_id:
            self.assertEqual(by_id['content.dependenciesImportable']['status'], sv.PASS,
                             json.dumps(by_id['content.dependenciesImportable'], default=str))
        self.assertIsNotNone(report, 'the decoder produced no report: '
                             + json.dumps({k: v.get('detail') for k, v in by_id.items()},
                                          ensure_ascii=False, default=str)[:800])
        # The real decoder accepted the recorded save bytes and found the entity.
        self.assertTrue(report.get('ok'), json.dumps(report, ensure_ascii=False)[:800])
        self.assertEqual(report.get('entity_id'), ADDED_ID)
        self.assertEqual(report.get('exactly_one_new_entity'), True)
        # Recorded provenance is present and names the real interpreter.
        recorded = by_id['content.interpreterRecorded']['detail']
        self.assertEqual(recorded['interpreterActual']['version'], '3.13.13')
        self.assertEqual(recorded['protobufActual'], '7.34.1')


if __name__ == '__main__':
    unittest.main()
