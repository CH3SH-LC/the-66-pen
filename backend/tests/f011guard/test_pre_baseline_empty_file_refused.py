"""An EMPTY pre-create baseline must be refused in BOTH forms, not just the inline one.

WHY THIS EXISTS
===============
``load_pre_baseline`` accepts two shapes. The inline one -- ``{"ids": [...]}`` -- has
refused an empty set since 2026-10-04, and its comment says exactly why:

    "an empty pre-create baseline makes every id look new this round, so leg B would
     grant ownership to anything"

The file one -- ``{"path": ...}`` -- did NOT. It parsed the document, built the id set,
and returned it, empty or not. A document that exists, parses, has the right shape and
simply lists nothing is exactly as much of a rubber stamp as an inline empty list: leg B
asks "is this id new against the pre-create baseline?", and against nothing every id is
new.

That asymmetry was live, not theoretical. MEASURED 2026-10-06 over the 1185 native
context documents on this machine: 1174 carry a non-empty entity list and **11 carry an
empty one**. Pointing leg B at any of those 11 would have granted ownership of any id.

The two forms are asserted equal here so the hole cannot reopen in either direction.

Run:
    python -m unittest discover -s backend/tests/f011guard -p "test_*.py" -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE
while not (REPO / "backend/cleanup_ownership_legs.py").is_file():
    if REPO.parent == REPO:
        raise SystemExit("REPO_ROOT_NOT_FOUND from %s" % HERE)
    REPO = REPO.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class EmptyPreBaselineIsRefusedInBothForms(unittest.TestCase):
    """leg B must never be handed a baseline that makes every id look new."""

    @classmethod
    def setUpClass(cls):
        if str(REPO / "backend") not in sys.path:
            sys.path.insert(0, str(REPO / "backend"))
        cls.legs = _load("_f011_pb_legs", REPO / "backend/cleanup_ownership_legs.py")

    def _document(self, entities):
        tmp = Path(tempfile.mkdtemp(prefix="f011-emptybaseline-"))
        target = tmp / "readonly-snapshot.json"
        target.write_text(json.dumps({"entities": entities}), encoding="utf-8")
        return target

    def test_inline_empty_is_refused(self):
        _ids, refusals = self.legs.load_pre_baseline({"ids": []})
        self.assertIn("PRE_BASELINE_EMPTY", [r.code for r in refusals])

    def test_file_with_no_entities_is_refused(self):
        target = self._document([])
        _ids, refusals = self.legs.load_pre_baseline({"path": str(target)})
        self.assertIn("PRE_BASELINE_EMPTY", [r.code for r in refusals],
                      "an empty file-form baseline was accepted, so leg B would treat "
                      "every id as new this round")

    def test_file_with_entities_is_accepted(self):
        """The control: the same shape, one entity, must still be usable."""
        target = self._document([{"id": 1, "templateId": 100}])
        ids, refusals = self.legs.load_pre_baseline({"path": str(target)})
        self.assertEqual([r.code for r in refusals], [])
        self.assertEqual(ids, {1})


if __name__ == "__main__":
    unittest.main()
