"""Guard: the six-module ledger's headline counts equal what the code derives.

Task — E4 — "our own module ledger's headline counts are stale".

``docs/gameplan/SIX-MODULE-FUNCTION-LEDGER.md`` is the artefact handed to the
owner as proof of progress, so a stale number in it is a **correctness bug in
the deliverable**, not a cosmetic one.  It had drifted (32/28/29/23) behind the
code (34/30/31/25) because the module surface grew (``interaction.event`` and
``interaction.switch_text_bubble``) and two blocks were added.

Re-copying the numbers is not a fix — that guarantees a next round.  The fix is
that the document carries **one** machine-checkable line and this test pins it
to the code:

    <!-- ledger-counts: blocks=<N> surface=<N> covered=<N> complete=<N> refused=<N> -->

Every field is compared to a value *derived here* from ``tools/gameplan``; none
is a hand-typed expectation.  If the code moves and the doc does not, this test
goes red — which is the point.

Read-only: opens the markdown for reading only.

Run::

    python -B -m unittest tools.gameplan.tests.test_module_ledger_counts
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools.gameplan import blocks as B
from tools.gameplan.tests import test_module_blocks as TMB

REPO = Path(__file__).resolve().parents[3]
LEDGER = REPO / "docs" / "gameplan" / "SIX-MODULE-FUNCTION-LEDGER.md"

#: The one declared line.  Keyed on the literal field names, not on prose.
_LINE_RE = re.compile(
    r"<!--\s*ledger-counts:"
    r"\s*blocks=(\d+)"
    r"\s*surface=(\d+)"
    r"\s*covered=(\d+)"
    r"\s*complete=(\d+)"
    r"\s*refused=(\d+)"
    r"\s*-->"
)


def _code_counts() -> dict[str, int]:
    """Every headline number, **derived from the code** in this checkout."""
    attempts = [B.attempt(b) for b in B.MODULE_BLOCKS]
    return {
        "blocks": len(B.MODULE_BLOCKS),
        "surface": len(TMB._surface_names()),
        "covered": len({
            f for b in B.MODULE_BLOCKS
            if B.attempt(b).status == "COMPLETE" for f in b.functions_made_real
        }),
        "complete": sum(1 for a in attempts if a.status == "COMPLETE"),
        "refused": sum(1 for a in attempts if a.status == "REFUSED"),
    }


def _declared_counts(text: str) -> dict[str, int] | None:
    match = _LINE_RE.search(text)
    if match is None:
        return None
    keys = ("blocks", "surface", "covered", "complete", "refused")
    return {k: int(v) for k, v in zip(keys, match.groups())}


class TheLedgerCountsMatchTheCode(unittest.TestCase):
    def test_the_ledger_declares_its_counts(self):
        """Fail-closed: no declared line is a failure, not a skip."""
        text = LEDGER.read_text(encoding="utf-8")
        self.assertIsNotNone(
            _declared_counts(text),
            f"{LEDGER.name} has no `<!-- ledger-counts: ... -->` line; the "
            "headline counts cannot be pinned",
        )

    def test_the_declared_counts_equal_the_code(self):
        declared = _declared_counts(LEDGER.read_text(encoding="utf-8"))
        self.assertIsNotNone(declared)
        code = _code_counts()
        self.assertEqual(declared, code, "the ledger's headline counts are stale")

    def test_the_guard_catches_a_stale_line(self):
        """Positive control: the same instrument flags a drifted line."""
        text = LEDGER.read_text(encoding="utf-8")
        drifted = _LINE_RE.sub(
            "<!-- ledger-counts: blocks=29 surface=32 covered=28 complete=23 "
            "refused=6 -->",
            text,
        )
        self.assertNotEqual(drifted, text, "test setup failed: no line was replaced")
        self.assertNotEqual(_declared_counts(drifted), _code_counts())

    def test_the_guard_catches_a_missing_line(self):
        """Negative control: deleting the line does not silently pass."""
        text = LEDGER.read_text(encoding="utf-8")
        self.assertIsNone(_declared_counts(_LINE_RE.sub("", text)))


if __name__ == "__main__":
    unittest.main()
