"""Offline test #8 — a capability claimed in a status doc must carry evidence.

CLAUDE.md §五 lists what is proven and what is blocked; §一.3 makes the
three-layer split a rule (``文档写了什么`` / ``工具能做什么`` / ``真机验证过什么``).
Nothing in the suite, though, checks that a *new* capability claim added to a
status doc arrives with the evidence that makes it checkable.  This module is
that check.

A logical line is flagged iff it

  1. asserts a capability — matches :data:`_ASSERT`, the doctrine's own
     "this works / is compiled / can do X" vocabulary, AND
  2. carries no citation — no ``file:line``, artefact path, ``sha256``, byte
     count, ``§`` section ref, ``原件``/``回执``/``证据`` (:data:`_EVID`), AND
  3. carries no hedge — no 候选 / 未真机 / unknown / blocked / 不 / 无 / 未 …
     (:data:`_HEDGE`).

Conservative by construction
----------------------------
A regex that fires on ordinary prose is worse than no test, so the detector is
tuned *against these five files*: as of 2026-10-10 it flags **0** lines, while
:data:`_ASSERT` still matches **39** distinct claim-bearing units across the
docs.  ``test_assertion_detector_is_not_vacuous`` pins that floor, so the 0 is a
real 0 and not a pattern that matches nothing.  Two deliberate
under-approximations keep it quiet:

  * markdown headings (``#…``) are structural labels; the claims live in the
    bodies they head, so headings are not scanned;
  * an assertion inside an inline code span (`` `真机验证过` ``) is a *mention* of
    the vocabulary — a definition — not a claim about this repo.

Both are conservative: they can hide a claim, never invent one.  A single
logical line is a markdown table row on its own, or a paragraph/bullet with its
wrapped continuation lines joined (a claim and its citation often straddle a
wrap — CLAUDE.md:66-67 is exactly that shape).

Failure shape it is built for
-----------------------------
``test_new_claim_in_a_real_document_is_flagged`` splices a synthetic claim into
a copy of the real CLAUDE.md and requires the scanner to flag it: the guard is
tested against the shape it exists to catch, in the real text, not a toy string.

Read-only: this module only reads the docs.  No bridge, no native call, no
game/editor contact, nothing written.

Run::

    python -B -m unittest tools.gameplan.tests.test_evidence_discipline
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# The status documents this test holds to the discipline.  Order is the order
# they are reported in.  VERTICAL-SLICE is scanned only when present.
REQUIRED_DOCS = (
    "CLAUDE.md",
    "docs/STATE-CARD.md",
    "docs/gameplan/README.md",
    "docs/PROGRESS-BY-FUNCTION.md",
)
OPTIONAL_DOCS = ("docs/gameplan/VERTICAL-SLICE.md",)

# A logical line deliberately allowed to assert a capability without a citation
# or a hedge — an explicit, reviewed escape hatch.  Empty today: the five docs
# currently carry no such line.  Keys are ``(doc, first line, stripped)`` so a
# line-number shift does not silently re-license a different claim.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# A capability-asserting tic in the doctrine's own vocabulary.  Claim-shaped on
# purpose: bare ``能`` / ``存在`` are absent so that ordinary prose
# (``"能读" 不等于 "能改"``, ``工具能做 ≠ 真机通了``) cannot fire it.
_ASSERT = re.compile(
    r"真机验证|真机走通|真机实测|真机已证|已真机|真机跑通|已走通|走通了|"
    r"闭环达成|已编译|已接线|已落地|已实现|可实现|已支持|已验证|已证|"
    r"能加|能改|能读|能写|能做|可以做|\bworks\b"
)

# A citation: a real pointer a reader can follow to the evidence.  Value tokens
# (sha256, byte counts, passed counts) count too — they are the receipts this
# project substitutes for timestamps.
_EVID = re.compile(
    r"[\w.\-]*\.(?:py|cs|md|json|ps1|db|gil|txt|jsonl|cmd|h|cpp|dll)\b"
    r"|:\d{1,5}\b"
    r"|§\s*[0-9一二三四五六七八九十]+"
    r"|同上"
    r"|\.runtime"
    r"|\b(?:docs|tools|data|config|backend|bridge|plugins|mvp|scripts|vendor)/"
    r"|sha256|[0-9a-f]{16,}|\d+\s*B\b|\d+\s*(?:文件|passed|tests?)\b"
    r"|原件|回执|证据"
)

# An explicit hedge: the line says it is a candidate / not real-machine run /
# blocked / unknown / simply negated.  ``≠`` is included because
# ``工具能做 ≠ 真机通了`` is a warning, not a claim.
_HEDGE = re.compile(
    r"候选|未真机|未验证|未证|未跑|未编译|未接线|未上机|未连|未落|未读回|"
    r"只离线|离线|unknown|blocked|missing|research|待办|不成立|做不到|"
    r"不存在|不能|没有|无|非|未|不|没|缺|待|无法|阻塞|failure|fail|stale|"
    r"悬空|过度概括|伪|尚未|≠"
)

# Markdown structure that starts a *new* logical line rather than continuing one.
_STRUCT = re.compile(r"^\s*(?:\||#|>|[-*+]\s|\d+\.\s)")
_FENCE = "```"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def units(text: str) -> list[tuple[int, list[str]]]:
    """Split ``text`` into logical lines as ``(1-based start, [physical lines])``.

    A fenced code block is emitted as its own units (commands are not claims).  A
    table row (``|…``), heading (``#…``), blockquote (``>…``) or bullet is its own
    unit; any other non-blank line continues the unit above it, so a claim and
    its wrapped citation stay together.
    """
    out: list[tuple[int, list[str]]] = []
    cur: list[str] = []
    start: int | None = None
    fence = False

    def flush() -> None:
        nonlocal cur, start
        if cur:
            assert start is not None
            out.append((start, cur))
            cur = []
            start = None

    for i, raw in enumerate(text.splitlines(), start=1):
        s = raw.rstrip()
        if s.lstrip().startswith(_FENCE):
            flush()
            fence = not fence
            out.append((i, [s]))
            continue
        if fence:
            out.append((i, [s]))
            continue
        if not s.strip():
            flush()
            continue
        if _STRUCT.match(s):
            flush()
            out.append((i, [s]))
            continue
        if not cur:
            start = i
        cur.append(s)
    flush()
    return out


def _in_code_span(blob: str, pos: int) -> bool:
    """True when ``pos`` sits inside an inline code span (odd backticks on the line)."""
    line_start = blob.rfind("\n", 0, pos) + 1
    return blob.count("`", line_start, pos) % 2 == 1


def _asserts_capability(blob: str) -> bool:
    """True if some :data:`_ASSERT` hit is a *claim*, not a quoted mention."""
    return any(not _in_code_span(blob, m.start()) for m in _ASSERT.finditer(blob))


def _is_claim_unit(blob: str, lines: list[str]) -> bool:
    """The full predicate: capability asserted, unquoted, no citation, no hedge."""
    if lines[0].lstrip().startswith("#"):
        return False
    if not _asserts_capability(blob):
        return False
    if _EVID.search(blob):
        return False
    if _HEDGE.search(blob):
        return False
    return True


def offenders(doc: str, text: str) -> list[tuple[int, str]]:
    """``(line number, first physical line)`` for every uncited capability claim."""
    found: list[tuple[int, str]] = []
    for line_no, lines in units(text):
        blob = "\n".join(lines)
        if _is_claim_unit(blob, lines):
            key = (doc, lines[0].strip())
            if key not in ALLOWLIST:
                found.append((line_no, lines[0].strip()))
    return found


def _count_assert_units(text: str) -> int:
    """Claim-bearing units before the citation/hedge filter — the non-vacuity floor."""
    return sum(
        1
        for _, lines in units(text)
        if not lines[0].lstrip().startswith("#")
        and _asserts_capability("\n".join(lines))
    )


def _scan_doc(rel: str) -> list[tuple[int, str]]:
    return offenders(rel, _read(REPO / rel))


# --------------------------------------------------------------------------- #
# The check itself, plus the guards that make its green meaningful.
# --------------------------------------------------------------------------- #

class StatusDocsHaveNoUncitedCapabilityClaims(unittest.TestCase):
    def test_scanned_docs_exist(self):
        """A missing doc must not be a silent pass — the scan would have nothing."""
        missing = [d for d in REQUIRED_DOCS if not (REPO / d).is_file()]
        self.assertEqual(missing, [], f"status docs named in the task are absent: {missing}")

    def test_no_status_doc_asserts_a_capability_without_evidence(self):
        """DRIFT DETECTOR — the real check over CLAUDE.md + the four status docs.

        Flags a logical line that claims a capability while giving neither a
        citation nor a hedge.  Today it flags 0; a *new* uncited claim makes this
        fail, and the message names the doc and line.  Fix by adding the evidence
        (the doctrine's own rule) or the hedge — not by widening ALLOWLIST.
        """
        docs = [d for d in REQUIRED_DOCS if (REPO / d).is_file()]
        docs += [d for d in OPTIONAL_DOCS if (REPO / d).is_file()]

        report: list[str] = []
        total = 0
        for doc in docs:
            hits = _scan_doc(doc)
            total += len(hits)
            report += [f"{doc}:{ln}: {text}" for ln, text in hits]

        self.assertEqual(
            report, [],
            "capability asserted with neither a citation (file:line / artefact "
            "path) nor a hedge (候选/未真机/unknown/blocked):\n  "
            + "\n  ".join(report),
        )
        # The scan really ran over at least the required docs.
        self.assertEqual(total, len(report))
        self.assertGreaterEqual(len(docs), len(REQUIRED_DOCS), "too few docs scanned")

    def test_assertion_detector_is_not_vacuous(self):
        """DRIFT DETECTOR — the 0 above must not be an empty pattern.

        Counts claim-bearing units across the docs *before* the citation/hedge
        filter.  Today that is 39; the floor is 25 so ordinary editing leaves
        headroom, but a gutted _ASSERT (or a doc set that lost all its claims)
        fails here instead of reporting a hollow green.
        """
        docs = [d for d in REQUIRED_DOCS + OPTIONAL_DOCS if (REPO / d).is_file()]
        counts = {d: _count_assert_units(_read(REPO / d)) for d in docs}
        total = sum(counts.values())
        self.assertGreaterEqual(
            total, 25,
            f"only {total} claim-bearing units found across {counts} — the "
            f"detector has gone blind (over-tight _ASSERT or truncated docs)",
        )


class ScannerFlagsTheRealFailureShape(unittest.TestCase):
    """The guard, tested against what it must catch and what it must let pass."""

    def test_synthetic_uncited_claim_is_flagged(self):
        """Negative control: a plain capability claim, no citation, no hedge."""
        text = "能力 `foo.transform` 已真机验证走通。\n"
        hits = offenders("(synthetic)", text)
        self.assertEqual(
            [(ln, t) for ln, t in hits], [(1, "能力 `foo.transform` 已真机验证走通。")],
            "an uncited capability claim was NOT flagged",
        )

    def test_new_claim_in_a_real_document_is_flagged(self):
        """The actual failure shape: a new uncited claim spliced into CLAUDE.md.

        The doctrine's §一.3 warns that a claim without evidence rots.  This
        splices the *pre-citation* wording of CLAUDE.md:66 — which is legal only
        because :67 carries the bytes — into the real document and requires the
        scanner to catch it.
        """
        real = _read(REPO / "CLAUDE.md")
        claim = "**已经真机走通**（一次完整闭环）：建图 → 绑定 → 保存。"
        spliced = real + "\n" + claim + "\n"
        flagged = [t for _, t in offenders("CLAUDE.md", spliced)]
        self.assertIn(
            claim, flagged,
            "a new uncited real-machine claim spliced into CLAUDE.md went unflagged",
        )

    def test_cited_lines_are_not_flagged(self):
        """Positive control — a citation must suppress, or the check is noise."""
        for text in (
            "能力 `foo` 已真机验证（`tools/x.py:12`）。",
            "已真机走通，原件 `.runtime/authoring/requests/abc/result.json`。",
            "已编译进 R269（`BridgeServer.cs:306`）。",
        ):
            with self.subTest(text=text):
                self.assertEqual(offenders("(synthetic)", text), [],
                                 f"a cited line was wrongly flagged: {text}")

    def test_hedged_lines_are_not_flagged(self):
        """Positive control — a hedge must suppress."""
        for text in (
            "`foo` 尚未真机验证。",
            "`foo` 是候选能力，未编译未真机。",
            "工具能做 ≠ 真机通了。",
            "闭环尚未达成。",
        ):
            with self.subTest(text=text):
                self.assertEqual(offenders("(synthetic)", text), [],
                                 f"a hedged line was wrongly flagged: {text}")

    def test_definition_mentions_inside_code_spans_are_not_claims(self):
        """A backticked term is the vocabulary being *named*, not a claim about it.

        This is the shape of CLAUDE.md:25 and README.md:148; without the
        code-span rule this line would fire on the definition itself.
        """
        text = "- **`已真机走通`** ＝ 指在运行的编辑器/游戏上跑过。"
        self.assertEqual(offenders("(synthetic)", text), [],
                         "a code-span definition was treated as a capability claim")

    def test_plain_prose_is_not_flagged(self):
        """No capability tic, no flag — the detector must stay off ordinary text."""
        for text in (
            "The editor is open and idle.",
            "本文记录这一步今天停在哪里。",
            "请求 id 必须写成请求本身的函数。",
        ):
            with self.subTest(text=text):
                self.assertEqual(offenders("(synthetic)", text), [],
                                 f"ordinary prose was flagged: {text}")

    def test_claim_and_citation_across_a_wrap_stay_together(self):
        """A wrap must not split a claim from the citation on the next line.

        CLAUDE.md:66-67 is the real instance: the claim is line 66, the bytes
        (``21872 B``/``.gil``) are on line 67.  Treated line-by-line the claim
        would be a false positive; as one logical line it is not.
        """
        text = (
            "**已经真机走通**（一次完整闭环）：建图 → 绑定 → 原生 save →\n"
            "`.gil` 21872→28383 B、载荷含 entityId/graphId/templateId。\n"
        )
        self.assertEqual(offenders("(synthetic)", text), [],
                         "a claim was split from its wrapped citation")


if __name__ == "__main__":
    unittest.main()
