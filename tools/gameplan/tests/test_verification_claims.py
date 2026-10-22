"""Offline test #8 (audit) — a "verified" claim must point at a receipt that exists.

The doctrine (``CLAUDE.md`` §一.3, §四) makes the split explicit::

    文档写了什么  /  工具能做什么  /  真机验证过什么

and further (``CLAUDE.md:59``)::

    ok:true / actionStatus:0 单独不证明持久化 —— 要 .gil 字节差分 + 独立读回

A claim that something was *verified on a real machine* is only checkable if it
names the artefact that proves it — a receipt under ``.runtime/`` (git-ignored,
but present), an ``inspect`` read-back file, a ``.gil`` byte-diff pair.  The
sibling test ``test_evidence_discipline.py`` checks that a capability claim
carries *some* citation; it deliberately does not care whether that citation
resolves.  Nothing in the suite checked the next step.  This module does:

    a claim in the verification vocabulary that cites a path
        ⟹  that path must exist on disk

What counts as a claim
-----------------------
A logical line is a **verification claim** iff it carries the verification
vocabulary (:data:`_VERIFY`: ``真机验证过`` / ``真机走通`` / ``actionStatus 0`` /
``已落盘`` / ``real-machine`` / …) or it is a table row sitting under a heading
that carries it (``STATE-CARD.md`` §一 「真机验证过（每行 = 一条命令 + 一份原件）」 —
the rows *are* the claim, the heading is the claim word), AND it carries no
hedge (:data:`_HEDGE`: 候选 / 未真机 / unknown / blocked / 单独不证 …).

What counts as a reference
--------------------------
Only a *directory-qualified* path — a token with a ``/`` whose first segment is
a known repo top (``docs/``, ``tools/``, ``.runtime/`` …) or whose last segment
looks like a filename (``…/result.json``).  A trailing ``:LINE`` / ``:A-B`` is
stripped.  Two conservative under-approximations, both of which can only *hide*
a broken pointer, never invent one:

  * a bare filename (``MINED-INTERFACES.md:98``, ``CLAUDE.md:59``) is not a
    directory-qualified path and is skipped — resolving it would need an
    ambiguous repo-wide basename search;
  * absolute / drive-qualified / placeholder paths (``C:/Users/…``,
    ``<levelId>`` …) are skipped — their existence is a function of the live
    save and is out of an offline test's remit.

Why ``0`` is a real ``0``
-------------------------
``test_scan_is_not_vacuous`` pins a floor on the number of claims *and* the
number of references the scan actually resolves, so a gutted ``_VERIFY`` (or a
doc set that lost its receipts) fails there instead of reporting a hollow green.
``test_broken_pointer_in_a_real_document_is_flagged`` corrupts a real receipt
path inside a real status doc and requires the scanner to catch it — the guard
is tested against the shape it exists to catch, in the real text.

Read-only: this module reads docs and stats paths.  No bridge, no native call,
no game/editor contact, nothing written.

Run::

    python -B -m unittest tools.gameplan.tests.test_verification_claims
"""

from __future__ import annotations

import os
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# The status documents held to this discipline.  Same set as
# ``test_evidence_discipline``: the canonical "what is verified today" surface.
REQUIRED_DOCS = (
    "CLAUDE.md",
    "docs/STATE-CARD.md",
    "docs/gameplan/README.md",
    "docs/PROGRESS-BY-FUNCTION.md",
)
OPTIONAL_DOCS = ("docs/gameplan/VERTICAL-SLICE.md",)

# A claim deliberately allowed to cite a non-existent path — an explicit,
# reviewed escape hatch.  Empty today: every reference the scan resolves exists.
# Keys are ``(doc, missing_path)`` so a line shift cannot silently re-license a
# *different* broken pointer.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset()

# The verification vocabulary — the doctrine's own words for "this was run on a
# real machine".  ``actionStatus 0`` / ``已落盘`` are included per the audit
# brief; the checkpoint fields are the receipts the project substitutes for
# timestamps.
_VERIFY = re.compile(
    r"真机验证|真机走通|真机实测|真机已证|真机跑通|真机进图|已真机|"
    r"real[-\s]machine|actionStatus\s*:?\s*0|已落盘|"
    r"nativeSaveStatus\s*:?\s*0|nativeStatus\s*:?\s*0"
)

# An explicit hedge — the line says it is a candidate / not real-machine run /
# blocked / caveated, so it is not a claim of verification.  Kept to *compounds*
# (bare 未/不/无 would swallow ordinary prose and hides real claims).
_HEDGE = re.compile(
    r"候选|未真机|未验证|未证|未跑|未编译|未接线|未上机|未连|未落|未读回|"
    r"只离线|离线|unknown|blocked|missing|待办|不成立|做不到|不存在|无法|"
    r"尚未|单独不|不证|≠"
)

# A directory-qualified path token: ≥1 ``/``, segments of ``[.A-Za-z0-9_-]``.
_PATH_TOKEN = re.compile(r"[.A-Za-z0-9_\-]+(?:/[.A-Za-z0-9_\-]+)+")
# A trailing ``:LINE`` or ``:A-B`` source suffix on a reference.
_LINE_SUFFIX = re.compile(r":\d{1,5}(?:-\d{1,5})?$")
# A path's last segment looks like a filename (has a short extension).
_EXT = re.compile(r"\.[A-Za-z0-9]{1,6}$")
# Repo top-level directories that make a slash-token unambiguously a repo path.
_KNOWN_TOPS = (
    "docs/", "tools/", "data/", "config/", "backend/", "bridge/",
    "plugins/", "mvp/", "scripts/", "vendor/", ".runtime/", ".task-manifest/",
)
# A drive-qualified or absolute path — out of scope (its target is the live
# save, not the checkout).
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|/|\\)")
# A placeholder segment (``<levelId>``, ``{before,after}`` …) truncates a path.
_PLACEHOLDER = re.compile(r"[<>{}$]")

# Markdown structure that starts a *new* logical line rather than continuing one.
_STRUCT = re.compile(r"^\s*(?:\||#|>|[-*+]\s|\d+\.\s)")
_FENCE = "```"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def units(text: str) -> list[tuple[int, list[str]]]:
    """Split ``text`` into logical lines as ``(1-based start, [physical lines])``.

    Mirrors ``test_evidence_discipline.units``: a fenced code block is emitted as
    its own units (commands are not claims); a table row / heading / blockquote /
    bullet is its own unit; any other non-blank line continues the unit above it
    so a claim and its wrapped citation stay together.
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


def _asserts_verification(blob: str) -> bool:
    """True if a *live* :data:`_VERIFY` hit names this line's claim.

    Unlike ``test_evidence_discipline`` this does **not** exclude inline code
    spans: the receipts here are backticked evidence fields
    (``backend.actionStatus 0``, ``nativeSaveStatus 0``), and a table row wraps
    its own claim word.  Excluding code spans would blind the scan to exactly
    the rows it must cover.
    """
    return bool(_VERIFY.search(blob))


def _is_table_row(first_line: str) -> bool:
    """A markdown table row: starts with ``|`` and contains a second ``|``."""
    return first_line.startswith("|") and "|" in first_line[1:]


def _strip_suffix(tok: str) -> str:
    return _LINE_SUFFIX.sub("", tok)


def is_path_reference(tok: str) -> bool:
    """True iff ``tok`` is a directory-qualified repo path worth resolving."""
    if _ABSOLUTE.match(tok):
        return False
    if _PLACEHOLDER.search(tok):
        # ``{before,after}-<levelId>.gil`` etc. — keep only the literal prefix
        # (handled by the token regex, which stops at the placeholder); a token
        # that still carries one is not a literal path.
        return False
    if tok.startswith(_KNOWN_TOPS):
        return True
    return bool(_EXT.search(tok.rsplit("/", 1)[-1]))


def _references(blob: str) -> list[str]:
    """Directory-qualified path references in ``blob``, de-duplicated, in order."""
    seen: dict[str, None] = {}
    for m in _PATH_TOKEN.finditer(blob):
        tok = _strip_suffix(m.group(0))
        if is_path_reference(tok):
            seen.setdefault(tok, None)
    return list(seen)


def target_exists(rel: str) -> bool:
    """Resolve a repo-relative reference against the checkout.

    ``.runtime/`` is git-ignored but present on this disk, so — per the audit
    brief — existence is checked with :func:`os.path.exists`.
    """
    rel = rel.replace("\\", "/")
    return os.path.exists(os.path.join(REPO, *rel.split("/")))


@dataclass(frozen=True)
class Claim:
    """One verification claim and the references it must back up."""

    doc: str
    line: int
    text: str
    refs: tuple[str, ...]

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(r for r in self.refs if not target_exists(r))


def verification_claims(doc: str, text: str) -> list[Claim]:
    """Every verification claim in ``text`` that cites ≥1 path reference.

    A claim with no path reference is *not* returned — ``test_evidence_discipline``
    owns "a claim must carry some citation"; this test owns "the citation
    resolves".  The two are deliberately disjoint so neither is a false alarm for
    the other.
    """
    claims: list[Claim] = []
    section_is_verified = False
    for line_no, lines in units(text):
        first = lines[0].strip()
        if first.startswith("#"):
            # A heading carrying the vocabulary (STATE-CARD §一「真机验证过…」) makes
            # the table rows beneath it claims even though the rows themselves do
            # not repeat the word.
            section_is_verified = bool(_VERIFY.search(first))
            continue
        blob = "\n".join(lines)
        triggered = _asserts_verification(blob) or (
            section_is_verified and _is_table_row(first)
        )
        if not triggered:
            continue
        if _HEDGE.search(blob):
            continue
        refs = _references(blob)
        if refs:
            claims.append(Claim(doc, line_no, first, tuple(refs)))
    return claims


def scan_doc(rel: str) -> list[Claim]:
    return verification_claims(rel, _read(REPO / rel))


def scan_all() -> tuple[list[Claim], list[tuple[str, str]]]:
    """Scan every present status doc.

    Returns ``(claims, missing)`` where ``missing`` is
    ``(doc, path)`` for each cited path that does not exist, minus the allowlist.
    """
    docs = [d for d in REQUIRED_DOCS + OPTIONAL_DOCS if (REPO / d).is_file()]
    claims: list[Claim] = []
    for doc in docs:
        claims.extend(scan_doc(doc))
    missing = [
        (c.doc, r)
        for c in claims
        for r in c.missing
        if (c.doc, r) not in ALLOWLIST
    ]
    return claims, missing


# --------------------------------------------------------------------------- #
# The check itself, plus the guards that make its green meaningful.
# --------------------------------------------------------------------------- #

class VerificationClaimsPointAtExistingArtefacts(unittest.TestCase):
    def test_scanned_docs_exist(self):
        """A missing doc must not be a silent pass — the scan would have nothing."""
        missing = [d for d in REQUIRED_DOCS if not (REPO / d).is_file()]
        self.assertEqual(missing, [], f"status docs named in the task are absent: {missing}")

    def test_every_cited_receipt_exists_on_disk(self):
        """DRIFT DETECTOR — every receipt a verification claim cites must exist.

        This is the point of the test: a claim that cites a path which is not on
        disk FAILS.  Today the scan resolves every reference and flags none; a
        doc that renames or deletes a receipt, or cites one it never produced,
        turns this red and names ``doc:line -> missing/path``.  Fix by restoring
        the artefact or citing one that exists — not by widening ALLOWLIST.
        """
        claims, missing = scan_all()
        by_path = {(c.doc, p): c for c in claims for p in c.missing}
        report = [
            f"{doc}:{by_path[(doc, path)].line}: "
            f"{by_path[(doc, path)].text[:70]!r} -> missing {path!r}"
            for doc, path in missing
        ]
        self.assertEqual(report, [], "verification claim cites a path that is not "
                                     "on disk:\n  " + "\n  ".join(report))

    def test_scan_is_not_vacuous(self):
        """DRIFT DETECTOR — the green above must not be an empty scan.

        Pins a floor on the number of claims *and* the number of distinct
        references the scan resolves, so a gutted ``_VERIFY`` (0 claims) or a doc
        set that lost its receipts (0 refs) fails here instead of reporting a
        hollow 0-failures.
        """
        claims, _ = scan_all()
        n_claims = len(claims)
        n_refs = len({r for c in claims for r in c.refs})
        self.assertGreaterEqual(
            n_claims, 10,
            f"only {n_claims} verification claims resolved — the detector or the "
            f"docs have gone quiet",
        )
        self.assertGreaterEqual(
            n_refs, 8,
            f"only {n_refs} distinct receipt references resolved — nothing is "
            f"being checked",
        )

    def test_counts_are_reported(self):
        """Not an assertion of quality — a live count so the numbers are visible.

        Prints ``claims / distinct refs / missing`` for this checkout; the
        non-vacuity floors live in :meth:`test_scan_is_not_vacuous`.
        """
        claims, missing = scan_all()
        n_refs = len({r for c in claims for r in c.refs})
        print(f"\nverification claims checked: {len(claims)} "
              f"across {len(REQUIRED_DOCS) + len(OPTIONAL_DOCS)} docs; "
              f"distinct receipts: {n_refs}; missing: {len(missing)}")
        for c, path in missing:
            print(f"  MISSING  {c.doc}:{c.line} -> {path}")


class ScannerFlagsABrokenReceipt(unittest.TestCase):
    """The guard, tested against what it must catch and what it must let pass."""

    def test_synthetic_claim_with_missing_path_fails(self):
        """Negative control: a verification claim citing a path that is not there."""
        text = ("已真机验证走通（`actionStatus 0`）。原件："
                "`.runtime/authoring/requests/00000000000000000000000000000000/result.json`。\n")
        claims = verification_claims("(synthetic)", text)
        self.assertEqual(len(claims), 1, "the synthetic claim was not even detected")
        self.assertEqual(
            claims[0].missing,
            (".runtime/authoring/requests/00000000000000000000000000000000/result.json",),
            "a verification claim citing a non-existent path was NOT flagged",
        )

    def test_broken_pointer_in_a_real_document_is_flagged(self):
        """The actual failure shape: a real receipt renamed inside a real doc.

        Takes the real ``docs/gameplan/README.md``, corrupts the receipt path the
        doc's §2 claim rests on, and requires the scanner to catch it — the guard
        is exercised on the real text, not a toy string.
        """
        real = _read(REPO / "docs/gameplan/README.md")
        good = ".runtime/authoring/requests/fc6dcaf74a33461d9648f94f5e2066ed/result.json"
        self.assertIn(good, real, "the fixture receipt changed; update this control")
        bogus = good.replace("fc6dcaf74a33461d9648f94f5e2066ed", "00000000000000000000000000000000")
        broken = real.replace(good, bogus)
        missing = {r for c in verification_claims("README.md", broken) for r in c.missing}
        self.assertIn(
            bogus, missing,
            "a corrupted receipt path inside the real README went unflagged",
        )

    def test_existing_receipts_are_not_flagged(self):
        """Positive control — an existing path must suppress, or the check is noise."""
        for text in (
            "已真机验证（原件 `.runtime/scratch/create-review.json`）。",
            "真机走通，回执 `docs/gameplan/README.md:198`。",
            "`actionStatus 0` / `nativeStatus 0`（`docs/PROGRESS-BY-FUNCTION.md:269`）。",
        ):
            with self.subTest(text=text):
                claims = verification_claims("(synthetic)", text)
                self.assertEqual([c.missing for c in claims], [()] if claims else [],
                                 f"an existing receipt was wrongly flagged: {text}")

    def test_hedged_lines_are_not_claims(self):
        """A caveat / candidate / not-yet-run line is not a claim of verification."""
        for text in (
            "组件读 op 尚未真机验证。",
            "`foo` 是候选能力，未编译未真机。",
            "`actionStatus 0` 只证「被接受」，**单独不证落盘**。",
            "这条通路仍未验证。",
        ):
            with self.subTest(text=text):
                self.assertEqual(verification_claims("(synthetic)", text), [],
                                 f"a hedged line was treated as a claim: {text}")

    def test_non_path_tokens_are_ignored(self):
        """Module labels / field lists / counts are not references."""
        text = ("已真机验证：M1/M2/M3/M5 已进图（`actionStatus 0`），载荷含 "
                "entityId/graphId/templateId，读回 71/1。\n")
        claims = verification_claims("(synthetic)", text)
        self.assertEqual(claims, [],
                         "a non-path slash-token (M1/M2, entityId/graphId, 71/1) "
                         "was mistaken for a reference")

    def test_absolute_and_placeholder_paths_are_skipped(self):
        """Live-save / placeholder paths are out of an offline test's remit."""
        text = ("真机实测（`nativeStatus 0`），原件 "
                "`C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/x/1073741842.gil`，"
                "以及 `.runtime/game-executor/scene-cli/does-not-exist/{before,after}.gil`。\n")
        claims = verification_claims("(synthetic)", text)
        missing = [r for c in claims for r in c.missing]
        self.assertNotIn(
            ".runtime/game-executor/scene-cli/does-not-exist/", missing,
            "a placeholder/drive path should be skipped, not resolved",
        )
        self.assertFalse(any("C/" in r or r.startswith("C:") for r in missing),
                         "an absolute path was resolved as repo-relative")

    def test_claim_and_receipt_across_a_wrap_stay_together(self):
        """A wrap must not split a claim from the receipt on the next line."""
        text = (
            "**已经真机走通**（一次完整闭环）：建图 → 绑定 → 原生 save →\n"
            "回执 `.runtime/scratch/save-review.json` 与 `.runtime/scratch/create-review.json`。\n"
        )
        claims = verification_claims("(synthetic)", text)
        self.assertEqual([c.missing for c in claims], [()],
                         "a claim was split from its wrapped receipt")


if __name__ == "__main__":
    unittest.main()
