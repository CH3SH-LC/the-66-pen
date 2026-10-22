"""Guard: no document may carry a *bare* bridge op count.

Task — 「让 op 面计数由文档派生，而不是照抄」.

The number of ``case "…"`` labels in ``tools/editor-bridge/ManagedBridge/BridgeServer.cs``
moved 136 -> 137 -> 138 in one night, and each move silently falsified a fresh batch
of documents (the same number had been copied into ~25 files).  Re-copying the number
is not a fix — it guarantees a next round.  The fix is that documents must either
*not state* the count, or *point at the one authoritative check*
(``tools/gameplan/tests/test_doctrine.py``, which pins the count against
``BridgeServer.cs``).

This test is the teeth for that rule.  It scans every ``docs/**/*.md`` and root
``*.md`` and fails on any line that states a bridge op-count-shaped number
without a pointer to the authority.

What is deliberately NOT an offender:

  * **The authority and the logs.**  ``CLAUDE.md`` is the value ``test_doctrine.py``
    reads and pins, and ``PROGRESS.md`` / ``PROGRESS-LITE.md`` are chronological
    logs whose history stays as written.  All are exempt.
  * **A quoted citation.**  A number inside 「…」 / 『…』 / "…" is this document
    *quoting another* wording, not asserting the count — the
    ``COMPONENT-DELETE-WIRING.md`` grep pattern and the ``STATUS-AUDIT.md`` audit
    rows are exactly this shape.  A **digit-bearing** inline-code span
    (`` `:123-129` ``, `` `BridgeServer.cs:367-388` ``) is the same thing: a
    citation of a line ref, not an assertion — it is blanked too.
  * **A *name* in inline code is NOT a citation.**  The hole a verifier found was
    that the previous revision blanked *every* `` `…` `` span before matching, so
    the commonest Markdown shape — `` `ValidateSet` = **135** `` — lost the very
    word (``ValidateSet``) the phrase needs and was never examined.  A code span
    with **no digit** in it is the *name* of the thing being counted, so its text
    is kept (only the backticks are dropped).
  * **A revision tag or a longer number.**  ``R137`` and ``1077936138`` are not the
    op count; the number must not be preceded by a word/digit character.
  * **Unrelated 3-digit text.**  ``…233  case 2`` (a line ref), ``单位标签`` /
    ``扫描标签`` (node names) — the number must sit in a *count phrase*
    (``N 个 op`` / ``N 个 case`` / ``case 条数 = N`` …), not merely near the word.
  * **The 62-era two-digit count.**  ``62`` is *the same fact* — the bridge op
    surface — at an older revision (the surface went 62 -> 136 -> 137 -> 138), so
    it is a count token too (see ``_COUNT``).  A *different* two-digit value is a
    genuinely other fact (called-subset ``59 个 op``, per-lease ``18 个 op``,
    fixture coverage ``11 个桥接操作``) and is not.
  * **A dated historical record.**  A line that marks itself old (``（当时）`` /
    ``（当时 …`` / ``… 当时）``) is about a past revision, not the current surface,
    so its then-current number may stay.  This is the historical-statement escape.
  * **A pointer-carrying number.**  A line that names the check
    (``test_doctrine``) is the (b)-form the task allows: a loud value with a pointer.

Read-only throughout: opens are reads; nothing is written anywhere.

Run::

    python -B -m unittest tools.gameplan.tests.test_no_stale_op_count
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

#: The one authoritative check.  Pointers name this file.
AUTHORITY = "tools/gameplan/tests/test_doctrine.py"
POINTER_TOKEN = "test_doctrine"

#: Files that may carry the count: the authority's own value (CLAUDE.md), the
#: logs, and this guard itself.
EXEMPT = {
    "CLAUDE.md",
    "PROGRESS.md",
    "PROGRESS-LITE.md",
}

#: Count token.  The bridge op surface is a 3-digit quantity today (136/137/138),
#: so any 3-digit number in a count phrase is in scope.  ``62`` is added
#: explicitly: it is *the same fact* — the bridge op surface — at an older
#: revision (the surface went 62 -> 136 -> 137 -> 138) and it survives in
#: pre-jump documents, so it must be caught too.  A bare *other* two-digit number
#: is a genuinely different fact (per-lease throughput ``18 个 op``, called-subset
#: ``59 个 op``, fixture coverage ``11 个桥接操作``) and is deliberately NOT a token.
_COUNT = r"(?:\d{3}|62)"

#: Count phrases that assert the bridge op surface.
_COUNT_PHRASES = [
    re.compile(r"\d{3}\s*个\s*(?:桥\s*|bridge\s*)?(?:派发\s*)?op\b"),
    re.compile(r"\d{3}\s*(?:桥\s*|bridge\s*)?op\b"),
    re.compile(r"\d{3}\s*个\s*(?:互不相同的\s*|唯一的\s*)?[`\"]?case"),
    re.compile(r"\d{3}\s*个\s*`?ValidateSet`?"),
    re.compile(r"\d{3}\s*条\s*(?:桥\s*)?op"),
    # ``case`` / ``ValidateSet`` …… ``= 138``  (a shell ``grep -c`` result)
    re.compile(r"(?:`case`|`ValidateSet`|case|ValidateSet)\s*[（(]?\s*"
               r"(?:条数|计数|个数|标签)?[^0-9\n]{0,4}[=＝:：]\s*[`*]{0,2}\d{3}"),
    # The op-*surface* wordings the stale 62 was actually written in — the real
    # failure shape, not a convenient one: ``… 的 62 个固定操作`` /
    # ``62 个桥接 op`` / ``bridge 62 个操作`` / ``| 桥接固定操作 | **62** |`` /
    # ``| 操作数 | **62** |``.
    re.compile(_COUNT + r"\s*个\s*(?:桥接\s*)?固定\s*(?:操作|op)"),
    re.compile(_COUNT + r"\s*个\s*桥接\s*(?:固定\s*)?(?:操作|op)"),
    re.compile(r"(?:桥接|bridge)\s*" + _COUNT + r"\s*个\s*(?:固定\s*)?(?:操作|op)"),
    re.compile(r"(?:桥接\s*)?固定\s*(?:操作|op)\s*[|｜]\s*\*{0,2}\s*" + _COUNT),
    re.compile(r"操作数\s*[|｜]\s*\*{0,2}\s*" + _COUNT),
    # The bare tally reference to that same set (``不计入 62 项`` / ``62 项中`` /
    # ``不在这 62 项里``).  The lookahead spares the unrelated compound noun
    # ``…62项表`` (a save-notification table), which is a different 62.
    re.compile(r"62\s*项(?!表)"),
]
#: Quoted spans are citations, not assertions.
_CITE_RE = re.compile(r"「[^」]*」|『[^』]*』|\"[^\"]*\"")
#: Inline-code spans.  Only their *content* is inspected: blanking the whole span
#: (the old behaviour) hid `` `ValidateSet` = **135** `` from every count phrase,
#: because the phrase is built around the name inside the backticks.
_BTICK_RE = re.compile(r"`([^`]*)`")
#: A line that *says* it is about a past revision (``（当时）`` / ``（当时 …`` /
#: ``… 当时）``) is a dated historical record, not a claim about the current
#: surface — the count may stay there.  This is the historical-statement escape:
#: a stale number is allowed exactly when the sentence marks itself as old.
_HISTORICAL_RE = re.compile(r"[（(]当时|当时[）)]")


def _mask(line: str) -> str:
    """Drop citations, keep the *names* of counted things.

    Quoted spans (「…」 / 『…』 / "…") and **digit-bearing** code spans are
    citations of another wording or of a line ref (`` `:123-129` ``), so they are
    blanked.  A code span with **no digit** is the name the count phrase needs
    (`` `ValidateSet` `` / `` `case` ``) — only its backticks are dropped, the
    text stays, so `` `ValidateSet` = **135** `` is examined like any bare count.
    """
    s = _CITE_RE.sub(" ", line)

    def _keep(match: re.Match[str]) -> str:
        inner = match.group(1)
        return f" {inner} " if not any(ch.isdigit() for ch in inner) else " "

    return _BTICK_RE.sub(_keep, s)


def _bare_op_count(line: str) -> bool:
    """True if *line* asserts a bridge op count with no pointer to the check.

    A pointer anywhere on the line (even inside backticks) makes it the allowed
    (b)-form, and a ``（当时）`` historical marker makes it a dated record rather
    than a current-surface claim (see :data:`_HISTORICAL_RE`).  Citations are
    then masked (see :func:`_mask`) — a citation is not an assertion — and the
    residue must match a count phrase.
    """
    if POINTER_TOKEN in line or _HISTORICAL_RE.search(line):
        return False
    return any(p.search(_mask(line)) for p in _COUNT_PHRASES)


def _doc_files() -> list[Path]:
    """The documentation this guard scans: ``docs/**/*.md`` plus root ``*.md``.

    ``.runtime/`` and ``.task-manifest/`` are never under ``docs/`` or root, so
    they are out of scope by construction.
    """
    return sorted((REPO / "docs").rglob("*.md")) + sorted(REPO.glob("*.md"))


def _offenders() -> list[str]:
    hits: list[str] = []
    for path in _doc_files():
        rel = path.relative_to(REPO).as_posix()
        if rel in EXEMPT or path.name in EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _bare_op_count(line):
                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
    return hits


class NoBareOpCount(unittest.TestCase):
    def test_no_document_states_a_bare_bridge_op_count(self):
        """Reads every ``docs/**/*.md`` and root ``*.md`` (quotes stripped)."""
        hits = _offenders()
        self.assertEqual(
            hits, [],
            "these documents state a bridge op count without pointing at "
            f"{AUTHORITY} (delete the number, or add the pointer):\n"
            + "\n".join(hits),
        )

    def test_the_scan_is_not_vacuous(self):
        """Negative control — the guard sees the failure shape and spares the fixed shapes.

        Every control is text that really occurred in this repo (or the exact
        shape a verifier used to break the previous revision).  Proves (i) the
        search flags a bare count in each count phrase — **including the real
        `` `ValidateSet` = **135** `` shape the old revision blanked away**, (ii) a
        pointer-carrying sentence is allowed, (iii) a quoted citation is allowed,
        (iv) a revision tag / longer number is not mistaken for the count, (v) an
        unrelated 3-digit line ref like ``…233  case 2`` is not flagged, and (vi)
        a digit-bearing code span (a cited line ref) does not leak a false count.
        """
        for line in (
            "桥的 137 个 op 里 ui/component 全 0 命中",
            "`BridgeServer.cs` 的 case 条数 = **138**",
            "136 个互不相同的 case 标签",
            "桥 136 op / CLI / MCP 没有一个能建模板",
            # the shape that broke the first revision of this guard (verifier's repro)
            "`ValidateSet` = 135",
            # ...and it verbatim as it sat in the tree (INTERFACE-INVENTORY.md:13)
            "> `call-bridge.ps1` 的 `ValidateSet` = **135** 项、"
            "helper 的 `NATIVE_ACTIONS` = **6** 项。",
            # The REAL failure shape of the pre-136 surface: the surviving 62
            # lines, each verbatim as it sits in the tree (not a contrived form).
            "`tools/editor-bridge/` 的 62 个固定操作，",
            "| [INTERFACE-INVENTORY.md](…) | … | 62 个桥接操作 |",
            "62 个桥接 op 中无对应项。",
            "| 桥接固定操作 | **62**（59 个有真实调用留证） |",
            "我们的工具（bridge 62 个操作）能不能改到它们？",
            "| 操作数 | **62** | `tools/editor-bridge/` 白名单 |",
            "（62 项中仅 3 项从未调用）",
            "## 4.9 不在这 62 项里的东西",
        ):
            with self.subTest(line=line):
                self.assertTrue(_bare_op_count(line), f"missed: {line!r}")
        for line in (
            f"桥的 op 面（见 {AUTHORITY}）里全 0 命中",
            "凡是写「删半边未编译 / op 面 137」的文档都过期",
            "当前桥R137；R134–R137 实机证据位于 frontend-cube-r137",
            "保存了 **1077936138** 的整条记录",
            "// :233  case 2（一行反编译行引用，非 op 计数）",
            "| 231 | 实体添加单位标签 | 入×1，出×1 |",
            # a cited line ref must not leak a bare count (UNREACHABLE-OPS.md:95)
            "从 `call-bridge.ps1` 的 `ValidateSet` 现读（`:123-129`），"
            "不在即 `OP_NOT_ALLOWED`",
            # ...nor may a digit-bearing code span (GRAPH-DELETE-FIX.md:325)
            "`ManagedBridge/BridgeServer.cs:367-388` op 接线；"
            "`elevated-request.py:163-164,603-615` CLI 形状",
            # the historical-statement escape: a stale 62 that *says* it is old
            "`tools/editor-bridge/` 的 62 个固定操作（当时）",
            "62 个桥接 op 中无对应项（当时）。",
            "在 **62 个桥接 op 中唯三无调用产物**（其余 59 项均有；当时）",
            # ...and the genuinely-different two-digit sub-counts stay out of scope
            "- **59 个 op 有过真实调用**（都有 `<op>-response.json`）。",
            "一次租约 op 数（理论） = 18 × 1 = 18 个 op",
            "**免提权 fixture 已覆盖全部 11 个桥接操作**（20/20 通过）",
            "默认槽和保存通知62项表均为磁盘证据",  # a different 62 (a notification table)
        ):
            with self.subTest(line=line):
                self.assertFalse(_bare_op_count(line), f"false positive: {line!r}")

    def test_backticks_are_not_stripped_away(self):
        """REGRESSION — reintroducing the old ``blank every `…` span`` step goes red.

        The first revision of this guard blanked *every* backticked span before
        matching, so `` `ValidateSet` = **135** `` lost the very keyword the count
        phrase hangs off and was never examined (``_bare_op_count`` returned
        ``False`` for it while returning ``True`` for the bare ``ValidateSet = 135``).
        Two teeth: a decorated keyword must survive masking, and the decorated
        sentence must fire.  Revert ``_mask`` to blank whole code spans and both this
        test and the fired-control above fail.
        """
        for inner in ("ValidateSet", "case"):
            with self.subTest(inner=inner):
                self.assertIn(
                    inner, _mask(f"`{inner}` = 138"),
                    "masking blanked a backticked keyword instead of unwrapping it")
        for line in (
            "`ValidateSet` = **135** 项",
            "`case` = 138",
            "…`ValidateSet` = **135** 项…",
        ):
            with self.subTest(line=line):
                self.assertTrue(
                    _bare_op_count(line),
                    f"backticked form not examined: {line!r}")

    def test_the_authority_pointer_target_really_exists(self):
        """The pointer must name a real file that still pins the count."""
        authority = REPO / AUTHORITY
        self.assertTrue(authority.is_file(), f"{AUTHORITY} is missing")
        self.assertRegex(
            authority.read_text(encoding="utf-8"),
            r"(\d+)\s*个 op",
            f"{AUTHORITY} no longer reads a '<n> 个 op' claim from CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
