#!/usr/bin/env python3
"""A save manifest with NO ``operation`` key must behave as ``operation='save'``.

MEASURED 2026-10-04: ``backend/save_verification.py`` read the operation two different
ways.  Four sites used ``manifest.get('operation', 'save')`` -- an absent key means save.
One site, the guard in ``_stage_saved_content``, used ``manifest.get('operation')`` with
NO default, so an absent key read as "not a save" and the guard did not fire: omitting one
key was a one-token bypass of a guard whose whole job is to refuse an unjudgeable case
rather than pass it.

THE PROPERTY THIS ASSERTS
    The set of finding codes from ``_stage_saved_content`` is IDENTICAL whether the key is
    absent or explicitly 'save'.  If someone restores the missing default, the two diverge
    and this goes red -- which is the point.

UPDATED 2026-10-06 (leaf D23.01.02): the guard no longer merely refuses a delta-less save.
It routes it to ``_stage_noop_content``, which judges a save that declares nothing by the
level's SEMANTIC content instead of the create-shaped decoder -- so that a LEGAL NO-OP can
be admitted rather than folded to ``evidence-insufficient``.  The guard still fires, and
still fires identically whether the operation key is present or absent; the finding that
names "the guard took the delta-less path" is now ``content.noOpSnapshotStable``.

Offline.  No game, no helper, no queue, no real evidence file: the manifests below name
files that do not exist, so every stage fails at the same place in both runs and the only
thing that can differ is the guard.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "_t_op_default", ROOT / "backend/save_verification.py")
MODULE = importlib.util.module_from_spec(spec)
sys.modules["_t_op_default"] = MODULE
spec.loader.exec_module(MODULE)


def _manifest(with_operation):
    """A save-shaped manifest with no entity delta, and deliberately absent files."""
    manifest = {
        "caseId": "op-default-probe",
        "runId": "0" * 32,
        "levelId": 1073741839,
        "requestId": "1" * 32,
        "files": {"gilBefore": str(ROOT / ".runtime/nonexistent-before.gil"),
                  "gilAfter": str(ROOT / ".runtime/nonexistent-after.gil")},
    }
    if with_operation:
        manifest["operation"] = "save"
    return manifest


def _codes(manifest):
    # findings are {'id': ..., 'status': ..., 'detail': ...} -- the check id is the key.
    report = MODULE._stage_saved_content(manifest)
    return sorted(f["id"] for f in report["findings"])


class OperationDefault(unittest.TestCase):
    def test_absent_operation_behaves_as_save(self):
        absent = _codes(_manifest(with_operation=False))
        present = _codes(_manifest(with_operation=True))
        self.assertEqual(
            absent, present,
            "omitting the operation key changed the verdict, so the guard that refuses a "
            "delta-less save can be bypassed by deleting one key")

    def test_the_guard_actually_fires_in_both_cases(self):
        # Without this, a change that made BOTH runs crash identically would satisfy the
        # equality above while proving nothing.
        #
        # ``content.noOpSnapshotStable`` is emitted only by ``_stage_noop_content``, i.e.
        # only when the guard routed the delta-less save to the no-op content judge.  It is
        # therefore the marker that the guard fired; the create-shaped decoder path would
        # instead have emitted ``content.snapshotStable`` (asserted absent below), so this
        # pins both "the guard fired" and "the decoder path was not walked".
        for with_operation in (False, True):
            codes = _codes(_manifest(with_operation=with_operation))
            self.assertIn(
                "content.noOpSnapshotStable", codes,
                "the delta-less-save guard did not fire (operation present=%r): %r"
                % (with_operation, codes))
            self.assertNotIn(
                "content.snapshotStable", codes,
                "the create-shaped decoder path was walked for a delta-less save "
                "(operation present=%r): %r" % (with_operation, codes))


if __name__ == "__main__":
    unittest.main(verbosity=2)
