"""One check that holds the load-bearing invariants whose drift bit this session.

Task #8 — 「让 doc/dist-code 漂移变成一条检查」.

Tonight a document claimed something the code no longer did, more than once, and
each time it was caught by hand.  The drift guards already in the tree are split
across ``test_doctrine.py`` (CLAUDE.md vs the bridge build) and
``test_no_false_uniqueness.py`` (refuted "only one such value" prose).  This file
is the *single* consistency check the task asked for: it pins the four invariants
below, each **derived from the real file** wherever a derivation is possible, so
the assertion cannot silently drift with a hand-edited copy of the fact.

The four facts, and why each one bit:

  (a) **No doc calls the READ op uncompiled while the payload DLL carries it.**
      ``inspect-entity-components`` (the READ half of the component op) *is* in the
      CURRENT payload DLL, whose revision is resolved from the csproj ``<AssemblyName>``
      (the read half landed first; on 2026-10-10 the sibling DELETE half
      ``EntityComponentDelete.cs`` was wired and compiled into the same revision).  A
      hardcoded ``…Net8R<rev>.dll`` path used to point at a revision a later bump removed,
      so this test skipped silently; the path is now derived.  Several docs quote the
      split, and one of them (``docs/gameplan/DEMO-GAP.md:166``) went stale by reporting
      ``CLAUDE.md:77`` as still saying 「未编译未真机」 after CLAUDE.md had been
      corrected.  We do **not** re-check CLAUDE.md's own count here (that is
      ``test_doctrine.BridgeOpCount``'s job); we assert that no doc *asserts the
      READ op is uncompiled* while the DLL plainly carries it.  Attribute-only
      mentions (a quoted stale citation, or a sentence about the DELETE half) are
      not assertions about the READ op and are excluded — see
      :func:`_line_is_offending`.

  (b) **``.gil`` field 7 has exactly one non-test reader.**
      ``FIELD_TERRAIN_LIST = 7`` is defined only in
      ``tools/beyond-save/terrain.py``; a second module defining it would mean a
      divergent field-7 reader (the exact shape of the round-3 / round-4 lies the
      sibling guard hunts).

  (c) **The save facts a doc quotes were true of a REAL save.**
      A save fact is a "N entries, M defect(s)" pair — the level-directory tool's
      own output signature.  It is a property of THE SAVE IT WAS WRITTEN ABOUT,
      not of the code: the live save drifts (the game autosaves; the owner swaps
      saves between sessions).  So a fact is verified against a *real* save — the
      live file when it still reads that way, else a byte-exact in-repo copy of
      the save the doc was written about — never against the drifting live file
      alone.  It must also be internally consistent (never more defects than
      entries, no ``[entry K]`` past the quoted count).

      **The claim is identified by its INTRINSIC shape, never by a nearby marker**
      — :func:`_save_facts_in` is the detection key, and a save-fact line is checked
      whether or not it sits near a path fragment (the earlier design dropped an
      *unattributed* fact silently, so a fabricated ``999 entries, 1 defect(s)``
      passed; that is the L7 marker-keyed defect).  A fact is then either
      *attributed* — checked against the pool of the save KIND it names — or
      *unattributed*, checked against the union of every held save.  A fact true of
      no save we can read FAILS (that is what stops the guard being switched off),
      unless its exact line is on the checked-in, fail-closed allowlist
      (:data:`_ALLOWLIST_PATH`), whose every entry is re-verified against a real
      line so it cannot rot.  When no save at all is present (another machine / a
      fresh checkout) the test SKIPS with the reason — it must never fail merely
      because the file is not there.

  (d) **Every golden file under ``tools/gameplan/golden/`` is read by a test.**
      ``golden.py``'s whole reason to exist is that a committed snapshot nobody
      checks is a trap: it looks like a baseline but catches nothing.  A golden
      file named by no test is that trap, so the set of expected stems is derived
      from the directory listing and each must be referenced by a test source.

Read-only throughout: the only file opens are reads (the live save is opened
read-only by ``level_directory``), and nothing is written anywhere.  Nothing here
touches the bridge, the game, the editor, or the helper.

Run::

    python -B -m unittest tools.gameplan.tests.test_repo_consistency
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# (a) — the READ op's presence in the CURRENT payload DLL.  The path is resolved from the
# csproj ``<AssemblyName>`` by ``_current_payload_dll`` below, never hardcoded to a
# revision: a hardcoded ``…Net8R<rev>.dll`` outlived its revision (the next bump removed the
# file), so the partition test skipped silently instead of checking anything.
CS_PROJ = (REPO / "tools" / "editor-bridge" / "ManagedBridge"
           / "Miliastra.EditorBridge.csproj")
_READ_OP = "inspect-entity-components"
#: Markers that a sentence is about the DELETE half, not the READ op.  A line
#: carrying one of these is *not* an assertion about the READ op's compile status.
_DELETE_TOKENS = ("EntityComponentDelete", "delete-entity-component",
                  "delete-entity-components")

# (b) — the sole field-7 reader.
TERRAIN = REPO / "tools" / "beyond-save" / "terrain.py"
#: A module-scope assignment.  ``re.M`` so ``^`` is a line start, not the
#: string start -- without it ``search`` only ever inspects byte 0.
_FIELD7_DEFINE_RE = re.compile(r"^\s*FIELD_TERRAIN_LIST\s*=", re.M)

# (c) — the live save and the docs that quote a fresh read of it.
LIVE_SAVE = Path("C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal"
                 "/100000001/Beyond_Local_Save_Level/1073741842/1073741842.gil")
LEVEL_DIR_PY = REPO / "tools" / "beyond-save" / "level_directory.py"
#: A save fact is the CONJUNCTION of two bindings on ONE line: a NUMBER bound to an
#: ENTRY-COUNT word AND a NUMBER bound to a DEFECT-COUNT word.  Each binding is
#: either order -- the word after the number (whitespace-separated) or before it,
#: then an optional ``[:=#]`` and the number (``999 entries`` / ``entries: 999``).
#: There is no separator BETWEEN the two bindings: they are formed independently on
#: the line and paired by position, so ``;`` / ``/`` / ``(`` / ``with`` between them
#: are all invisible to the key.  One number is claimed once: a token already bound
#: as an entry count is not re-bound as a defect count, so the space-separated
#: reversed form ``entries: 42 defects: 1`` reads ``(42, 1)``, not ``(42, 42)``.
#: That conjunction -- NOT a literal
#: sentence -- is the claim's intrinsic shape: it is the level-directory tool's own
#: output signature (``<file>.gil: N entries, M defect(s)``).  Neither binding alone
#: is the key, so no SEPARATOR or WORD-ORDER is hard-coded: the earlier literal key
#: ``(\d+)\s+entries\b\s*,?\s*(\d+)\s+defect`` bound only the comma form, and 8 of 10
#: spellings -- ``;`` / ``/`` / ``(`` / ``with`` / the reversed ``entries: … defects:``
#: -- were invisible by construction.  Two things the WORDS alone cannot produce, so
#: the conjunction excludes them: the digitless placeholder ``.gil: N entries, M
#: defect`` (``GEN-STATUS-AUDIT.md:194``), ``+0x28 entries`` (no defect count),
#: ``2 defects: […]`` (no entry count).  A save-fact line is checked whether or not a
#: nearby marker sits on it: attribution (below) CLASSIFIES a claim, it is never the
#: gate that decides whether the claim is checked -- keying detection on a marker is
#: the L7 defect this guard was rebuilt to remove.
#:
#: A NUMBER bound to an ENTRY-COUNT word, either order (``999 entries`` /
#: ``entries: 999``).  The word is the plural ``entries`` -- the tool's own output
#: word.  The singular ``entry`` is deliberately NOT bound: ``[entry 41]`` is an entry
#: POSITION cited by a defect, not a count, and binding it would forge a phantom
#: ``(41, M)`` pair on every defect line that also names the position.
_ENTRY_BOUND_RE = re.compile(
    r"(?:\b(\d+(?:,\d{3})*)\s*entries\b|\bentries\b\s*[:=#]?\s*(\d+(?:,\d{3})*))", re.I)

#: A NUMBER bound to a DEFECT-COUNT word, either order (``1 defect`` / ``defects: 1``).
#: ``defect`` / ``defects`` / the tool's ``defect(s)`` all bind (``\bdefects?\b``
#: matches the ``defect`` in ``defect(s)``).  The number-before arm stops at the
#: number (``(?=defects?\b)``), it does NOT eat the word: a binding that
#: ``_save_facts_in`` discards must not consume the word that the word-first arm
#: needs (``entries: 42 defects: 1`` -- the ``42`` is entry-claimed and dropped,
#: and the ``1`` after ``defects:`` must still bind).
_DEFECT_BOUND_RE = re.compile(
    r"(?:\b(\d+(?:,\d{3})*)\s*(?=defects?\b)|\bdefects?\b\s*[:=#]?\s*(\d+(?:,\d{3})*))", re.I)

#: Markers that CLASSIFY (never gate) a claim: which save it was written about.
_LIVE_MARK = "Beyond_Local_Save_Level"
_BACKUP_MARKS = ("formal-save-backups", "user-original-before-postsave-test")
_LOOK_BACK = 12  # the classification window; the marker is NOT the detection gate

#: Byte-exact in-repo copies of the saves the docs quote, each tagged by the KIND
#: of save it is.  A quoted "N entries, M defect(s)" is a property of THE SAVE IT
#: WAS WRITTEN ABOUT -- the live save drifts (the game autosaves and the owner
#: swaps saves between sessions), so its numbers are not a property of the code.
#: These frozen copies ARE those saves, so a fact is checked against them.  A short
#: explicit list on purpose: ``.runtime`` holds >22k ``.gil`` and a fresh checkout
#: holds none, so a walk would be both slow and empty.  The KIND makes attribution
#: load-bearing: an ATTRIBUTED fact is checked against its own kind's pool (a
#: 'backup' fact cannot be rescued by a live reading); an UNATTRIBUTED fact is
#: checked against the union of every held save.
_FROZEN_DOC_SAVES = (
    # the demo "after" save (28383 B) == the file README §5 and
    # SAVE-WRITE-ATTRIBUTION read as the live save when they were written
    # (42 entries / 1 defect).  It is a copy of the LIVE save, hence kind 'live'.
    (".runtime/game-executor/scene-cli/20261010-004106-save-640895e1"
     "/after-1073741842.gil", "live"),
    # the user-original before the post-save test (21872 B) == the "backup" file
    # those docs quote (40 entries / 0 defect(s)).
    (".runtime/formal-save-backups"
     "/20261008T0930-1073741842-user-original-before-postsave-test/1073741842.gil",
     "backup"),
    # a real 2026-09-19 upload-audit "before" save (51273 B) == the 1073741830 file
    # SAVE-WRITER-FINAL.md quotes (34 entries / 1 defect(s)).  A different level, so
    # not 'live'/'backup' -- kind 'other', reachable only via an unattributed fact's
    # union.  Verified: this reader reads it 34/1.
    (".runtime/verification/upload-audit-20260919/1073741830-before.gil", "other"),
)

#: The fail-closed allowlist: exact (file, whitespace-normalised line) entries for
#: the rare doc line that is a save fact but that no held save can corroborate.  A
#: fact not explained by a held save FAILS unless its exact line is here, so a NEW
#: unverifiable fact fires until a human deliberately adds it with a reason.  Matches
#: the sibling guard's pattern (``dict_claim_allowlist.json``): exact line, sha256
#: keyed, re-verified against the repo so the list cannot rot.
_ALLOWLIST_PATH = Path(__file__).with_name("save_fact_allowlist.json")
_ALLOWLIST_CACHE: dict | None = None

# (d) — the committed golden snapshots.
GOLDEN_DIR = REPO / "tools" / "gameplan" / "golden"
TESTS_DIR = REPO / "tools" / "gameplan" / "tests"

# Directories that never hold a first-party module or a test we scan.
_PRUNE = {".git", ".runtime", "__pycache__", ".pytest_cache", "node_modules",
          "vendor", "bin", "obj", ".mypy_cache"}


# --------------------------------------------------------------------------- #
# readers — each derived from the file it names
# --------------------------------------------------------------------------- #

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _in_metadata(blob: bytes, s: str) -> bool:
    """True if ``s`` sits in a .NET metadata heap (ASCII ``#Strings`` or UTF-16 ``#US``)."""
    return s.encode("ascii") in blob or s.encode("utf-16-le") in blob


def _current_payload_dll() -> Path | None:
    """The payload DLL the CURRENT build names, resolved from the csproj AssemblyName.

    Reading the revision out of the csproj (rather than hardcoding a revision) keeps the
    artifact assertion pointed at whatever revision is actually built, so a bump does
    not leave this check reading a stale, already-removed DLL.
    """
    match = re.search(
        r"<AssemblyName>\s*(Miliastra\.EditorBridge\.Net8R\d+)\s*</AssemblyName>",
        _read(CS_PROJ))
    if match is None:
        return None
    return (REPO / "tools" / "editor-bridge" / "ManagedBridge" / "bin" / "Release"
            / "net8.0-windows" / (match.group(1) + ".dll"))


def _iter_py() -> list[Path]:
    """Every ``*.py`` under the repo, minus the pruned/generated directories."""
    found: list[Path] = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _PRUNE]
        for name in files:
            if name.endswith(".py"):
                found.append(Path(root) / name)
    return found


def _doc_files() -> list[Path]:
    """The documentation the drift guards scan: ``docs/**/*.md`` plus the root ``*.md``."""
    docs = sorted((REPO / "docs").rglob("*.md"))
    root = sorted(REPO.glob("*.md"))
    return docs + root


# --------------------------------------------------------------------------- #
# (a) helpers
# --------------------------------------------------------------------------- #

# Chinese 「…」 / 『…』 and ASCII "…" quoted spans.  A status word *inside* quotes
# is a citation of some other document's wording, not this document's assertion.
_QUOTED_RE = re.compile(r"「[^」]*」|『[^』]*』|\"[^\"]*\"")
_EN_UNCOMPILED_RE = re.compile(r"\bnot\s+(?:yet\s+)?compiled\b|\buncompiled\b", re.I)


def _uncompiled_claim(line: str) -> bool:
    """True if *line* asserts (outside a quoted citation) that something is uncompiled."""
    stripped = _QUOTED_RE.sub(" ", line)
    return "未编译" in stripped or bool(_EN_UNCOMPILED_RE.search(stripped))


def _mentions_delete(line: str) -> bool:
    return any(tok in line for tok in _DELETE_TOKENS)


def _line_is_offending(line: str) -> bool:
    """A line that names the READ op and calls it uncompiled, honestly attributed.

    A line is an offender only if it (1) names the READ op, (2) does **not** name
    the DELETE half (so an uncompiled word on it belongs to the DELETE op, not the
    READ op), and (3) carries an *unquoted* uncompiled word.  A quoted word is a
    citation — ``docs/gameplan/DEMO-GAP.md:166`` quotes CLAUDE.md's retired
    wording in 「未编译未真机」, which is exactly the stale citation this file
    documents rather than a fresh assertion.
    """
    if _READ_OP not in line:
        return False
    if _mentions_delete(line):
        return False
    return _uncompiled_claim(line)


def _docs_calling_read_op_uncompiled() -> list[str]:
    offenders: list[str] = []
    for path in _doc_files():
        try:
            text = _read(path)
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _line_is_offending(line):
                rel = path.relative_to(REPO).as_posix()
                offenders.append(f"{rel}:{i}: {line.strip()[:160]}")
    return offenders


# --------------------------------------------------------------------------- #
# (b) helpers
# --------------------------------------------------------------------------- #

def _field7_defining_modules() -> set[str]:
    """Non-test repo modules that *define* (assign) ``FIELD_TERRAIN_LIST``."""
    holders: set[str] = set()
    for path in _iter_py():
        if "test" in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _FIELD7_DEFINE_RE.search(text):
            holders.add(path.relative_to(REPO).as_posix())
    return holders


# --------------------------------------------------------------------------- #
# (c) helpers
# --------------------------------------------------------------------------- #

def _bound_numbers(regex: "re.Pattern[str]", line: str) -> list[tuple[int, tuple[int, int]]]:
    """The integers *regex* binds on *line*, in reading order, each with its SPAN.

    Each match contributes whichever of the two alternation groups fired.  The span
    is that of the group: two regexes binding the SAME token report the same span, so
    a token one regex has claimed can be recognised and not re-claimed by the other.
    """
    out: list[tuple[int, tuple[int, int]]] = []
    for m in regex.finditer(line):
        group = 1 if m.group(1) is not None else 2
        out.append((int(m.group(group).replace(",", "")), m.span(group)))
    return out


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True iff the two character spans share a character."""
    return a[0] < b[1] and b[0] < a[1]


def _save_facts_in(line: str) -> list[tuple[int, int]]:
    """Every ``(entries, defects)`` claim *line* asserts by its INTRINSIC shape.

    A claim exists iff the line binds BOTH a number to an entry-count word
    (:data:`_ENTRY_BOUND_RE`) and a number to a defect-count word
    (:data:`_DEFECT_BOUND_RE`).  The k-th entry binding pairs with the k-th defect
    binding, so a two-save diff written on one line (``40 entries,0 defect / 42
    entries,1 defect``) yields two claims in order; if the two counts differ the
    surplus is left unpaired (a line with 2 entry numbers and 1 defect number yields
    one claim, not two).

    A NUMBER already bound as an entry count is NEVER re-bound as a defect count:
    the defect arm drops any binding whose token an entry arm has claimed (the two
    arms would otherwise read the single ``42`` of ``entries: 42 defects: 1`` as
    both counts, forging the impossible ``(42, 42)`` and losing the true ``(42, 1)``).

    **DOMAIN -- exactly this, no more**: ``{ lines on which BOTH bindings succeed }``.
    A spelling this predicate cannot BIND is invisible to it *by construction*: a
    count word outside ``entries`` / ``defect(s)`` (the Chinese ``40 条 / 0 缺陷`` of
    ``STATUS-AUDIT.md:122`` -- which survives only because that same row also prints
    the English ``40 entries, 0 defect(s)``), a count carried with no digit (the
    placeholder ``N entries, M defect``), a pair split across two lines, a
    mixed-language pair (``42 entries / 0 缺陷``), or a table whose pairing is
    implied by its column headers (``SAVE-WRITER-FINAL.md:34/58``) is OUT of domain.
    In the other direction the key is deliberately broad: any two number-bound words
    on one line fire -- a coincidental prose sentence (``5 entries and 2 defects``)
    is indistinguishable from a fact BY SHAPE, and that is the accepted domain edge
    that buys the separator/order insensitivity above.
    """
    entries = _bound_numbers(_ENTRY_BOUND_RE, line)
    entry_spans = [span for _value, span in entries]
    defects = [value for value, span in _bound_numbers(_DEFECT_BOUND_RE, line)
               if not any(_spans_overlap(span, e) for e in entry_spans)]
    if not entries or not defects:
        return []
    return list(zip([value for value, _span in entries], defects))


def _claim_lines() -> list[tuple[Path, int, int, int, str | None]]:
    """Every save fact in the docs, one tuple per pair, with its classification.

    Detection is by INTRINSIC shape (:func:`_save_facts_in`), NOT by a marker: a
    line binding an entry count to a defect count is a fact whether or not a path
    fragment sits near it.  The 4th element (the classification) may be ``None`` --
    an *unattributed* fact is RETURNED, not dropped: the caller checks it against the
    union of held saves.  Dropping it here (the earlier behaviour, keyed on a marker
    within ``_LOOK_BACK`` lines) is the L7 defect this fixes.  A line with two pairs
    (a live-vs-backup diff written on one line) yields one fact each.
    """
    claims: list[tuple[Path, int, int, int, str | None]] = []
    for path in _doc_files():
        try:
            lines = _read(path).splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for idx, line in enumerate(lines):
            pairs = _save_facts_in(line)
            if not pairs:
                continue
            # A line with >1 pair is a diff of several saves written on one line;
            # no single kind can own it, so it is left UNATTRIBUTED and checked
            # against the union (attribution is a 1:1 pairing by construction).
            target = _claim_target(lines, idx) if len(pairs) == 1 else None
            for n, d in pairs:
                claims.append((path, idx, int(n), int(d), target))
    return claims


def _claim_target(lines: list[str], i: int) -> str | None:
    """``'live'`` / ``'backup'`` / ``None`` — what CLASS the fact belongs to.

    The line itself wins if it names a path fragment; otherwise we walk up to the
    command block that produced the fact (the tool is run on a path, then its
    output is quoted below).  Walking is stopped by a nearer save-fact line so a
    fact is never classified across another one.  ``None`` means *unattributed* and
    is a legitimate classification (checked against the union), never a drop.
    """
    for j in range(i, max(-1, i - _LOOK_BACK) - 1, -1):
        line = lines[j]
        if _LIVE_MARK in line:
            return "live"
        if any(mark in line for mark in _BACKUP_MARKS):
            return "backup"
        if j != i and _save_facts_in(line):
            break
    return None


def _level_directory():
    """Import ``tools/beyond-save/level_directory.py`` (read-only reader)."""
    if str(LEVEL_DIR_PY.parent) not in sys.path:
        sys.path.insert(0, str(LEVEL_DIR_PY.parent))
    import level_directory  # noqa: PLC0415 — path-dependent import
    return level_directory


def _save_reading(path: Path) -> tuple[int, int] | None:
    """``(entries, defects)`` for *path* via the level-directory reader, else None."""
    if not path.is_file():
        return None
    ld = _level_directory()
    try:
        return (len(ld.read_directory(path)), len(ld.check_directory(path)))
    except (OSError, ValueError):
        return None


def _verifiable_readings() -> dict[tuple[int, int], list[str]]:
    """Map every ``(entries, defects)`` a REAL save reads to the saves giving it.

    The corpus is the live save (if present) plus the frozen in-repo copies.  A
    doc claim is *explained* iff its pair is a key here -- some save we can read
    actually reads that way.  That is the whole point: the number is a property
    of the save, so it is checked against a save, never against a literal.
    """
    out: dict[tuple[int, int], list[str]] = {}
    for path in (LIVE_SAVE, *[REPO / rel for rel, _kind in _FROZEN_DOC_SAVES]):
        reading = _save_reading(path)
        if reading is None:
            continue
        try:
            label = path.relative_to(REPO).as_posix()
        except ValueError:
            label = str(path)
        out.setdefault(reading, []).append(label)
    return out


def _readings_by_kind() -> dict[str, set[tuple[int, int]]]:
    """``(entries, defects)`` pairs each KIND of held save produces.

    'live' = the live file plus every frozen copy tagged 'live'; 'backup' = the
    frozen snapshots tagged 'backup'.  An ATTRIBUTED fact is checked against its
    own kind's pool, so a fact stamped 'backup' cannot be rescued by a live
    reading.  (Frozen copies tagged 'other' are reachable only via the union.)
    """
    pools: dict[str, set[tuple[int, int]]] = {"live": set(), "backup": set()}
    live = _save_reading(LIVE_SAVE)
    if live is not None:
        pools["live"].add(live)
    for rel, kind in _FROZEN_DOC_SAVES:
        reading = _save_reading(REPO / rel)
        if reading is not None and kind in pools:
            pools[kind].add(reading)
    return pools


def _unexplained_claims(
        claims: list[tuple[Path, int, int, int, str | None]],
        readings: dict[tuple[int, int], list[str]],
        by_kind: dict[str, set[tuple[int, int]]] | None = None,
) -> list[tuple[Path, int, int, int, str | None]]:
    """Claims whose ``(entries, defects)`` no save actually produces.

    With ``by_kind`` given, an attributed fact is held only to its own kind's
    pool; an unattributed fact (``target is None``) or an unclassified kind falls
    back to ``readings`` -- the union of every held save.  This is the fail-closed
    rule: an unattributed fact is checked against SOME held save, never dropped.
    """
    out: list[tuple[Path, int, int, int, str | None]] = []
    for c in claims:
        n, d, tgt = c[2], c[3], c[4]
        if by_kind is not None and tgt in by_kind:
            pool = by_kind[tgt]
        else:
            pool = set(readings)
        if (n, d) not in pool:
            out.append(c)
    return out


#: A defect's own text cites the entry it is about: ``missing-entry-id [entry K]``.
_ENTRY_REF_RE = re.compile(r"\[entry\s+(\d+)\]")


def _internally_inconsistent(n: int, d: int, line: str) -> list[str]:
    """Ways a quoted ``N entries, M defect(s)`` sentence cannot describe ANY save.

    Drift cannot excuse these: no save ever reports more defects than entries, and
    no defect cites an entry position at or past the entry count.  Only the
    claim's OWN line is inspected for ``[entry K]`` -- the block may share one
    defect listing between a backup and a live claim, so a wider window would
    blame the wrong count.
    """
    reasons: list[str] = []
    if d > n:
        reasons.append(f"quotes {d} defect(s) for only {n} entries")
    for k in _ENTRY_REF_RE.findall(line):
        if int(k) >= n:
            reasons.append(f"cites [entry {k}] but quotes only {n} entries")
    return reasons


# --------------------------------------------------------------------------- #
# (c) allowlist helpers -- the fail-closed waiver
# --------------------------------------------------------------------------- #

def _line_digest(line: str) -> str:
    """sha256 of *line* with runs of whitespace collapsed and ends stripped.

    The unit the allowlist hashes: stable against column re-padding, sensitive
    to any content change (including a changed number).
    """
    import hashlib
    return hashlib.sha256(
        re.sub(r"\s+", " ", line).strip().encode("utf-8")).hexdigest()


def _load_allowlist() -> dict[tuple[str, str], dict]:
    """Parse ``save_fact_allowlist.json`` -> ``{(rel, digest): entry}``."""
    import json
    if not _ALLOWLIST_PATH.is_file():
        return {}
    raw = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], dict] = {}
    for entry in raw.get("allow", []):
        out[(entry["file"], entry["sha256"])] = entry
    return out


def _allowlist() -> dict[tuple[str, str], dict]:
    """The allowlist, parsed once per process."""
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is None:
        _ALLOWLIST_CACHE = _load_allowlist()
    return _ALLOWLIST_CACHE


def _is_allowlisted(rel: str, line: str,
                    table: dict[tuple[str, str], dict] | None = None) -> bool:
    """True iff this EXACT ``(rel, normalised line)`` is on the allowlist.

    Exact-line keyed on purpose: proximity to an allowlisted line must never
    waive a bare claim, and any change to the line (a different number) makes
    the entry an assertion that FIRES again.
    """
    table = _allowlist() if table is None else table
    return (rel, _line_digest(line)) in table


# --------------------------------------------------------------------------- #
# (d) helpers
# --------------------------------------------------------------------------- #

def _test_sources() -> list[str]:
    """Every ``test_*.py`` in the gameplan suite, **except this guard file**.

    This file is excluded because it holds the invented negative-control stem as
    a literal; scanning itself would make every "is it read" answer ``True``.
    """
    me = Path(__file__).resolve()
    return [p.read_text(encoding="utf-8")
            for p in sorted(TESTS_DIR.glob("test_*.py"))
            if p.resolve() != me]


def _string_constants() -> dict[str, str]:
    """Module-level ``NAME = "value"`` string constants from non-test modules.

    Lets a test that reads a golden through a named constant (``DEMO_GOLDEN_NAME``)
    count as reading the golden that constant names, instead of only matching a
    bare string literal.
    """
    out: dict[str, str] = {}
    for path in _iter_py():
        if "test" in path.name:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out.update(dict(re.findall(r"^([A-Z_][A-Z0-9_]*)\s*=\s*\"([^\"]+)\"", text, re.M)))
    return out


def _golden_needles(stem: str, consts: dict[str, str]) -> set[str]:
    needles = {f'"{stem}"', f"'{stem}'", f"{stem}.json"}
    needles |= {name for name, value in consts.items() if value == stem}
    return needles


def _read_by_a_test(stem: str, test_texts: list[str], consts: dict[str, str]) -> bool:
    needles = _golden_needles(stem, consts)
    return any(needle in text for text in test_texts for needle in needles)


# --------------------------------------------------------------------------- #
# (a) — docs agree with the compiled/uncompiled split
# --------------------------------------------------------------------------- #

class BridgeDocPartitionAgreement(unittest.TestCase):
    """DRIFT DETECTOR — reads the CURRENT payload DLL and every ``docs/**/*.md`` / root ``*.md``.

    The invariant the task names: **no doc says the READ op is uncompiled while
    the DLL contains it.**  A doc that merely quotes the retired wording (in
    quotes) or a sentence about the DELETE half is not such an assertion and is
    excluded by :func:`_line_is_offending`.

    The DLL path is resolved from the csproj ``<AssemblyName>`` — a hardcoded
    revision literal is what let this check skip silently once before.
    """

    def _dll_carries_read_op(self, dll: Path) -> bool:
        return dll.exists() and _in_metadata(dll.read_bytes(), _READ_OP)

    def test_no_doc_calls_the_read_op_uncompiled_while_the_dll_has_it(self):
        """Reads the current payload DLL and the docs."""
        dll = _current_payload_dll()
        self.assertIsNotNone(
            dll, "the csproj no longer names a payload <AssemblyName>; cannot resolve "
            "the built artifact to check the docs against")
        if not dll.exists():
            self.skipTest(
                f"{dll} is not built in this checkout "
                "(tools/editor-bridge/**/bin/ is git-ignored). Build it with: "
                "dotnet build tools/editor-bridge/ManagedBridge/"
                "Miliastra.EditorBridge.csproj -c Release "
                "(or bump+rebuild with: pwsh -NoProfile -File "
                "tools/editor-bridge/next-revision.ps1). The path is resolved from the "
                "csproj AssemblyName, so a revision bump cannot leave this check "
                "pointing at a stale, already-removed DLL.")
        if not self._dll_carries_read_op(dll):
            self.skipTest(
                f"{dll.name} is present but does not carry '{_READ_OP}'; "
                "the compiled/uncompiled split claimed by the docs is inverted")
        offenders = _docs_calling_read_op_uncompiled()
        self.assertEqual(
            offenders, [],
            "the DLL '" + dll.name + "' contains '" + _READ_OP + "' (compiled), "
            "yet these doc lines call it uncompiled:\n" + "\n".join(offenders),
        )

    def test_the_uncompiled_detector_is_not_vacuous(self):
        """Negative control — the offending test fires on an unquoted assertion.

        Without this, a typo in the token list would make every ``assertEqual``
        pass for the wrong reason.  Proves (i) the search sees an unquoted
        assertion, (ii) a quoted citation is *not* an assertion (this is the exact
        shape of ``DEMO-GAP.md:166``), and (iii) a DELETE-half line is excluded.
        """
        self.assertTrue(
            _line_is_offending("`inspect-entity-components` 未编译"),
            "the search misses an unquoted READ-op-uncompiled assertion")
        self.assertFalse(
            _line_is_offending("`inspect-entity-components`「未编译未真机」"),
            "a cited (quoted) status word must not count as this doc's assertion")
        self.assertFalse(
            _line_is_offending(
                "`inspect-entity-components` 已编译；删的 `EntityComponentDelete.cs` 未编译"),
            "an uncompiled word on a DELETE-half sentence must not be blamed on the READ op")


# --------------------------------------------------------------------------- #
# (b) — exactly one non-test field-7 reader
# --------------------------------------------------------------------------- #

class Field7ReaderIsUnique(unittest.TestCase):
    def test_exactly_one_non_test_module_defines_field_terrain_list(self):
        """Reads ``tools/beyond-save/terrain.py`` and scans every repo ``*.py``."""
        self.assertRegex(
            _read(TERRAIN), r"(?m)^FIELD_TERRAIN_LIST\s*=\s*7",
            "terrain.py no longer pins FIELD_TERRAIN_LIST = 7 at module scope")
        modules = _field7_defining_modules()
        self.assertEqual(
            modules, {"tools/beyond-save/terrain.py"},
            f"field 7 has more (or fewer) than one non-test defining module: "
            f"{sorted(modules)}")

    def test_the_uniqueness_search_is_not_vacuous(self):
        """Negative control — the scan would see a second defining module.

        Splices a ``FIELD_TERRAIN_LIST = 7`` line into the terrain source and
        asserts the defining-module predicate fires, so the ``assertEqual`` above
        is not passing because the search matches nothing at all.
        """
        planted = _read(TERRAIN) + "\nFIELD_TERRAIN_LIST = 7\n"
        self.assertTrue(
            _FIELD7_DEFINE_RE.search(planted),
            "the field-7 define search misses an obvious assignment")


# --------------------------------------------------------------------------- #
# (c) — doc-quoted save facts match a fresh read
# --------------------------------------------------------------------------- #

class DocSaveFactsMatchDisk(unittest.TestCase):
    """DRIFT DETECTOR — reads the docs and re-reads the save each fact describes.

    A "N entries, M defect(s)" pair is a property of THE SAVE IT WAS WRITTEN
    ABOUT, not of the code: the live save drifts (the game autosaves; the owner
    swaps saves between sessions).  So a fact is verified against a REAL save —
    the live file when it still reads that way, else a byte-exact in-repo copy of
    the save the doc was written about — never against the drifting live file
    alone.  It is also checked for internal consistency.

    The fact is detected by its INTRINSIC shape (:func:`_save_facts_in`), NEVER by
    a nearby marker: an UNATTRIBUTED fact is checked (against the union of every
    held save), not silently dropped — that silent drop is HOLE 1, the L7
    marker-keyed defect this rewrite removes.  An ATTRIBUTED fact is checked
    against the pool of the save KIND it names.  A fact no held save can produce
    FAILS unless its exact line is on the fail-closed allowlist, and when no save
    at all is present the test SKIPS with the reason.
    """

    def _claims(self) -> list[tuple[Path, int, int, int, str | None]]:
        claims = _claim_lines()
        self.assertTrue(
            claims,
            "no doc quotes a save's entry count; the claim scan found nothing "
            "to check (the tool output shape may have changed)")
        return claims

    def _unexplained_outside_allowlist(self, claims, readings, by_kind):
        """Unexplained facts, minus the exact lines the allowlist waives."""
        unexplained = _unexplained_claims(claims, readings, by_kind)
        out = []
        for c in unexplained:
            rel = c[0].relative_to(REPO).as_posix()
            if not _is_allowlisted(rel, _read(c[0]).splitlines()[c[1]]):
                out.append(c)
        return out

    def test_live_save_matches_every_doc_claim_about_it(self):
        claims = self._claims()
        readings = _verifiable_readings()
        if not readings:
            self.skipTest(
                "no readable save in this checkout (live save and every frozen "
                "copy absent); cannot check the doc claims against a real save")

        # (1) internally consistent: a fact no save can ever produce FAILS here,
        #     no matter how the live file has drifted.
        bad: list[str] = []
        for path, idx, n, d, _tgt in claims:
            line = _read(path).splitlines()[idx]
            for why in _internally_inconsistent(n, d, line):
                bad.append(f"{path.relative_to(REPO).as_posix()}:{idx + 1}: {why}")
        self.assertEqual(
            bad, [],
            "doc(s) assert a save fact no save can have:\n" + "\n".join(bad))

        # (2) true of a real save: every quoted pair must be one a readable save
        #     actually produces -- an attributed fact against the pool of the save
        #     KIND it names, an unattributed fact against the union of all held
        #     saves.  Neither is ever dropped: the pair's SHAPE is the gate.
        by_kind = _readings_by_kind()
        unexplained = self._unexplained_outside_allowlist(
            claims, readings, by_kind)
        if unexplained:
            lines = []
            for p, i, n, d, tgt in unexplained:
                kind = ('unattributed' if tgt is None
                        else f"attributed to the {tgt!r} save")
                lines.append(
                    f"  {p.relative_to(REPO).as_posix()}:{i + 1} quotes "
                    f"{n} entries / {d} defects ({kind})")
            self.fail(
                "these doc save facts are true of NO save this repo can read; a "
                "quoted count is a property of the save it was written about, so "
                "either fix the number, add a byte-exact copy to "
                "_FROZEN_DOC_SAVES, or (if it truly cannot be corroborated) add "
                "the exact line to save_fact_allowlist.json with a reason:\n"
                + "\n".join(lines)
                + f"\n  readable saves read: {dict(sorted(readings.items()))}"
                + f"\n  kind pools: "
                  f"{ {k: sorted(v) for k, v in by_kind.items()} }")

    def test_the_live_claim_scan_is_not_vacuous(self):
        """Negative control — the comparison and the classification both bite.

        Proves (i) a wrong count would be caught (a fresh read is not equal to a
        deliberately wrong pair) and (ii) the classification predicate really finds
        a live-save fact, so the assertion above is not passing on an empty list.
        """
        if not LIVE_SAVE.is_file():
            self.skipTest(f"live save absent: {LIVE_SAVE}")
        ld = _level_directory()
        fresh = (len(ld.read_directory(LIVE_SAVE)),
                 len(ld.check_directory(LIVE_SAVE)))
        self.assertNotEqual(
            fresh, (fresh[0] + 999, fresh[1] + 999),
            "the fresh-read comparison is vacuous")
        live_claims = [(p, i, n, d) for (p, i, n, d, tgt) in _claim_lines()
                       if tgt == "live"]
        self.assertTrue(
            live_claims,
            "the claim scan found no live-save claim to attribute")

    def test_the_key_binds_every_spelling_of_the_pair_and_nothing_else(self):
        """The key's own predicate, both ways: it binds the PAIR in any spelling and
        refuses a line that carries only ONE kind of word.

        (i) The two spellings the retired LITERAL key
            ``(\\d+)\\s+entries\\b\\s*,?\\s*(\\d+)\\s+defect`` bound still bind.
        (ii) The five spellings that widening was needed for -- each a genuine
             numeric pair the literal key could not bind (``;`` / ``/`` / ``(`` /
             ``with``, and the reversed ``entries: … defects:``) -- now bind.  (These
             are the exact five the adversary planted; before this change each PASSED
             the guard invisibly.)
        (ii′) The reversed form with a SPACE between the two bindings
             (``entries: 42 defects: 1``) reads ``(42, 1)``: the defect binding must
             not re-claim the entry-claimed number and forge the impossible
             ``(42, 42)`` (the false positive a fresh adversary found).
        (iii) Sentences that carry one kind of word, or the digitless placeholder, do
              NOT fire -- the conjunction is not vacuous in the other direction.
        """
        bound: dict[str, list[tuple[int, int]]] = {
            # (i) caught by the old key, still caught
            "10.gil: 999 entries, 1 defect(s)": [(999, 1)],
            "10.gil: 999 entries, 1 defect": [(999, 1)],
            # (ii) the five the old key dropped -- now bound
            "10.gil: 999 entries; 1 defect(s)": [(999, 1)],
            "10.gil: 999 entries / 1 defect": [(999, 1)],
            "10.gil: 999 entries (1 defect)": [(999, 1)],
            "10.gil: 999 entries with 1 defect": [(999, 1)],
            "save entries: 999, defects: 1": [(999, 1)],
            # the reversed form with a SPACE (not ``,``) between the two bindings --
            # the defect arm must not re-claim the entry-claimed ``42`` and forge the
            # impossible (42, 42); the true reading is (42, 1)
            "save entries: 42 defects: 1": [(42, 1)],
            "save entries: 42, defects: 1": [(42, 1)],
            # a real doc line: the count AND the cited [entry 41] on one line -- the
            # singular ``entry`` in the citation must NOT forge a second pair
            ("…1073741842.gil: 42 entries, 1 defect(s)` ＋ `missing-entry-id "
             "[entry 41]: …"): [(42, 1)],
            # a two-save diff on one line: two pairs, in order
            "#   → 40 entries,0 defect / 42 entries,1 defect": [(40, 0), (42, 1)],
        }
        for line, want in bound.items():
            with self.subTest(line=line):
                self.assertEqual(
                    _save_facts_in(line), want,
                    f"the key misses or mispairs a save fact: {line!r}")
        # (iii) negative controls -- one kind of word (or no digit) must stay OUT.
        for line in (
            # the digitless placeholder (GEN-STATUS-AUDIT.md:194; GUARD-INVENTORY.md:26)
            "`gen_status` 不产任何 `.gil: N entries, M defect` 形状的句子",
            # ``entries`` bound, no defect word (SWEEP-REPAIR-REVIEW.md:180)
            "txt L26–56: exactly 16 entries, several not switches (镜头水平速度)",
            # ``defect`` bound, NO entries word (SUITE-RESULT-20261010.md:194)
            "'…GameNodeCatalog.cs'] : 2 defects: ['SOURCE-SHA256-MISMATCH']",
            # "entries" as a memory offset, not a count (NATIVE-ADD-COMPONENT.md:231)
            "map+0x28=entries, +0x18=count",
            # a defect named, no count word pair (TAB-DIRECTORY-MINE.md:250)
            "给 `level_directory.py` 的一条提示：`missing-entry-id` 这个 defect 名可能是假阳性",
        ):
            with self.subTest(line=line):
                self.assertEqual(
                    _save_facts_in(line), [],
                    f"the key fires on a line that is not a save fact: {line!r}")

    def test_the_guard_fires_on_a_fabricated_claim(self):
        """Negative control — a fact true of no real save is REJECTED.

        A guard whose disposition is "skip when the live save drifts" can rot into
        an inert guard that only ever skips.  This proves the opposite, on the
        SAME anchor readings the real test uses: a fabricated pair -- attributed
        OR unattributed (the HOLE 1 shape) -- is reported unexplained, an
        internally impossible pair is reported inconsistent, and a genuine
        reading is accepted (positive control on the same instrument).
        """
        readings = _verifiable_readings()
        if not readings:
            self.skipTest("no readable save in this checkout; nothing to anchor "
                          "the guard on")
        by_kind = _readings_by_kind()
        reals = sorted(readings)
        # a fabricated pair that is none of the real readings
        n0, d0 = reals[-1]
        fabricated = (n0 + 7, d0 + 3)
        self.assertNotIn(fabricated, readings)
        fake = (Path("docs/FAKE.md"), 0, fabricated[0], fabricated[1], "live")
        self.assertTrue(
            _unexplained_claims([fake], readings, by_kind),
            "the guard accepted a claim true of no real save (inert guard)")
        # HOLE 1: an UNATTRIBUTED fabricated fact must be rejected too -- shape
        # alone gates, never the nearby marker.
        fake_unatt = (Path("docs/FAKE.md"), 0, fabricated[0], fabricated[1], None)
        self.assertTrue(
            _unexplained_claims([fake_unatt], readings, by_kind),
            "the guard accepted an UNATTRIBUTED claim true of no real save")
        # positive control: a genuine UNATTRIBUTED reading IS accepted
        good = reals[0]
        ok = (Path("docs/FAKE.md"), 0, good[0], good[1], None)
        self.assertEqual(
            _unexplained_claims([ok], readings, by_kind), [],
            "the guard rejected a pair that IS a real reading")
        # kind-awareness: a fact stamped 'backup' must NOT be rescued by a live
        # reading (attribution is load-bearing, not decorative).
        live_pool = by_kind.get("live", set())
        backup_pool = by_kind.get("backup", set())
        live_only = sorted(live_pool - backup_pool)
        if live_only:
            ln, ld_ = live_only[0]
            wrong = (Path("docs/FAKE.md"), 0, ln, ld_, "backup")
            self.assertTrue(
                _unexplained_claims([wrong], readings, by_kind),
                "a 'backup' fact was rescued by a live-only reading")
        # internally impossible pairs, rejected by shape alone
        self.assertTrue(_internally_inconsistent(5, 9, "x: 5 entries, 9 defect(s)"),
                        "the guard accepted more defects than entries")
        self.assertTrue(
            _internally_inconsistent(5, 1, "x: 5 entries, 1 defect(s) `[entry 9]`"),
            "the guard accepted an [entry 9] under a 5-entry claim")
        self.assertEqual(
            _internally_inconsistent(42, 1, "x: 42 entries, 1 defect(s) `[entry 41]`"),
            [], "the guard flagged the real, consistent claim")


class SaveFactAllowlistIntegrity(unittest.TestCase):
    """The fail-closed waiver: exact-line, sha256-keyed, and rot-proof.

    A save fact no held save corroborates FAILS unless its exact normalised
    line is on the allowlist, and every entry must still match exactly one real
    line -- so the list cannot rot into rows that waive nothing.  The sibling
    guard (``test_dict_nodes_not_absent``) is built the same way.
    """

    def test_the_allowlist_file_parses(self):
        self.assertTrue(_ALLOWLIST_PATH.is_file(),
                        f"allowlist missing: {_ALLOWLIST_PATH}")
        parsed = _load_allowlist()
        self.assertIsInstance(parsed, dict)

    def test_every_allowlist_entry_still_matches_one_real_line(self):
        """(a) The anti-rot check: a stale entry FIRES."""
        for (rel, digest), entry in _load_allowlist().items():
            path = REPO / rel
            self.assertTrue(path.is_file(),
                            f"allowlist names a missing file: {rel}")
            matches = [ln for ln in _read(path).splitlines()
                       if _line_digest(ln) == digest]
            self.assertEqual(
                len(matches), 1,
                f"allowlist entry {rel}:{entry.get('line')} "
                f"({entry.get('reason')!r}) no longer matches exactly one line "
                "-- update or remove it")
            self.assertIn(
                entry["excerpt"][:12], matches[0],
                f"allowlist excerpt for {rel}:{entry.get('line')} no longer "
                "matches the allowlisted line")

    def test_the_rot_detector_fires_on_a_stale_entry(self):
        """(b) Positive control -- a hash that matches no line is CAUGHT.

        Without this, an empty allowlist would let the rot check pass vacuously;
        this proves the detector is a real per-line hash lookup.
        """
        rel = "docs/gameplan/README.md"
        lines = _read(REPO / rel).splitlines()
        stale = "0" * 64
        self.assertFalse(
            any(_line_digest(ln) == stale for ln in lines),
            "the rot detector failed to flag a hash matching no line")

    def test_the_waiver_is_exact_line_keyed(self):
        """(c) Proximity never waives: a bare claim is not rescued."""
        rel = "PROGRESS.md"
        lines = _read(REPO / rel).splitlines()
        allowed = next(ln for ln in lines if ln.strip())
        table = {(rel, _line_digest(allowed)):
                 {"line": 1, "reason": "planted"}}
        self.assertTrue(
            _is_allowlisted(rel, allowed, table),
            "an exact allowlisted line was not waived")
        self.assertFalse(
            _is_allowlisted(rel, "1073741842.gil: 999 entries, 1 defect(s)",
                            table),
            "a bare claim was waived by proximity to an allowed line")


# --------------------------------------------------------------------------- #
# (d) — every golden file is read by a test
# --------------------------------------------------------------------------- #

class GoldenFilesAreAllRead(unittest.TestCase):
    """DRIFT DETECTOR — reads ``tools/gameplan/golden/`` and the test sources.

    A committed golden that no test opens is a trap: it looks like a baseline but
    guards nothing.  The expected set is derived from the directory listing, not
    hardcoded, so a newly committed golden with no reader fails here.
    """

    def _golden_stems(self) -> list[str]:
        return sorted(p.stem for p in GOLDEN_DIR.glob("*.json"))

    def _unread_goldens(self) -> list[str]:
        stems = self._golden_stems()
        texts = _test_sources()
        consts = _string_constants()
        return [stem for stem in stems if not _read_by_a_test(stem, texts, consts)]

    def test_every_committed_golden_is_read_by_some_test(self):
        stems = self._golden_stems()
        self.assertTrue(stems, f"no golden files under {GOLDEN_DIR}")
        unread = self._unread_goldens()
        self.assertEqual(
            unread, [],
            f"golden file(s) {GOLDEN_DIR.name}/{unread}.json read by no test — "
            "a snapshot nothing checks is a trap (add a reader or delete it)")

    def test_the_golden_read_search_is_not_vacuous(self):
        """Negative control — an invented stem is *not* reported as read.

        Proves the search is a real per-stem lookup rather than an unconditional
        ``True``: a stem that no test and no constant names must come back False.
        """
        texts = _test_sources()
        consts = _string_constants()
        self.assertTrue(texts, "no test sources found to scan")
        self.assertFalse(
            _read_by_a_test("zzz-unread-golden-fixture", texts, consts),
            "the golden-read search reports an invented stem as read")
        for stem in self._golden_stems():
            with self.subTest(stem=stem):
                self.assertTrue(
                    _read_by_a_test(stem, texts, consts),
                    f"real golden {stem!r} is not reported as read")


class PlaytestSupervisorKnowsTheProbeStrings(unittest.TestCase):
    """DRIFT DETECTOR — the playtest supervisor's module-probe profile vs the demo.

    ``tools/editor-bridge/playtest_one_click.py`` carries a LITERAL mirror of the module
    probe's expected output (``MODPROBE_PRINTS``) so the supervisor stays standalone.
    A mirror that drifts is not cosmetic: the 2026-10-12 defect was exactly a supervisor
    hardwired to the OLD demo's four literals while the graph that makes one click
    maximally informative (``MW_API_MODPROBE``) prints seven different ``W29AI`` lines --
    so a real capture of that graph classified ``FOREIGN_PRINT`` and the click said
    nothing.  This pins the mirror EQUAL to the demo's own predicted set, derived from
    the PLAN (not from a constant), so the drift cannot come back silently.
    """

    @classmethod
    def setUpClass(cls):
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        cls.supervisor = _load_supervisor()
        from tools.gameplan.demo import farming_module_probe as fp
        from tools.gameplan import runtime_prediction as rp
        cls.fp = fp
        cls.pred = rp.predict(fp.demo_plan())

    def test_the_supervisor_declares_exactly_the_plan_predicted_lines(self):
        self.assertEqual(
            self.supervisor.MODPROBE_PRINTS, tuple(self.pred.prints),
            "the supervisor's module-probe string set drifted from the plan the demo builds")

    def test_the_demo_declared_set_also_matches_the_plan(self):
        """Positive control through the SAME derivation: the demo's constant is the plan's."""
        self.assertEqual(tuple(self.fp.PREDICTED_PRINTS), tuple(self.pred.prints))

    def test_the_supervisor_targets_the_demos_graph_name(self):
        self.assertEqual(self.supervisor.MODPROBE_GRAPH_NAME, self.fp.DEFAULT_NAME)

    def test_the_mirror_is_one_line_per_module_with_no_duplicate_text(self):
        texts = list(self.supervisor.MODPROBE_PRINTS)
        self.assertEqual(len(texts), len(set(texts)),
                         "a duplicated line could not attribute a capture to one module")
        self.assertEqual(
            dict(self.supervisor.MODPROBE_MODULE_PRINTS),
            dict(self.fp.MODULE_PRINT_TEXT) | {"entry": self.fp.ENTRY_PROBE_TEXT,
                                              "end": self.fp.END_TEXT},
        )

    def test_only_the_probe_profile_classifies_a_probe_capture(self):
        """The WHY of the profile, at the classifier boundary, on one real capture.

        The demo-profile classifier is BLIND to a probe line (``FOREIGN_PRINT`` -- the exact
        defect: the click ran the probe and the tool said "not ours"); the probe-profile
        classifier reads it as our capture. Same bytes, two profiles, opposite verdicts --
        which is why the run must select the profile its graph belongs to.
        """
        rows = [{"observedUtc": "2026-10-12T00:00:00.0000000Z", "graphName": "g",
                 "bodyType": "T.Text", "bodyText": self.supervisor.MODPROBE_PRINTS[0]}]
        evidence = {"ok": True, "active": True, "observedPackets": 1, "observedLogPackets": 1,
                    "runLogSample": {"recordsSeen": 1, "sample": rows}}
        self.assertEqual(self.supervisor.classify_module_probe(evidence),
                         self.supervisor.OUT_MODPROBE)
        self.assertEqual(self.supervisor.classify_outcome(evidence),
                         self.supervisor.OUT_FOREIGN)


def _load_supervisor():
    """Load ``tools/editor-bridge/playtest_one_click.py`` by path (it is not a package)."""
    import importlib.util

    path = REPO / "tools" / "editor-bridge" / "playtest_one_click.py"
    spec = importlib.util.spec_from_file_location("playtest_one_click_repo_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
