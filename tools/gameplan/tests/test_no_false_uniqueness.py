"""Guard rails: refuted "uniqueness" claims must never come back.

Two rounds of refutation are pinned here.

Round 1 -- three factual claims that had crept into the terrain / bounds work as
"there is only ONE such value" statements.  Each was false:

  * ``tools/gameplan/bounds.py`` said the only vector-shaped value in ``.gil``
    field 11 is ``field 11 > 1 > 1``;
  * ``tools/beyond-save/level_settings.py`` said the preset/spawn records hold
    **no coordinate**;
  * ``tools/beyond-save/terrain.py`` said no function in the module takes a save
    path.

Round 2 -- the *fix* for round 1 wrote a NEW lie: it said the preset-point field
``field 11 > 5 > 1 > 2`` is set on exactly ONE level ("the one file here that
sets it; it is empty, 0 bytes, in every other file").  That is false too.

The truth, re-derived read-only from the real bytes on this machine (2026-10-10):

  * level 1073741840 carries a 3-component vector at ``field 11 > 5 > 1 > 2`` -- a
    preset-point *coordinate* ``(-0.29665565, 0.12, -10.40005016)`` beside the name
    ``新建预设点1``;
  * level 1073741835 carries the SAME field with a single fixed32 only:
    ``0d0000c0c0`` = -6.0, beside the name ``新建预设点`` (sibling ``field 11 > 5 >
    1 > 501``).  Same bytes in ``100000001/Temp/1073741835.gil``.

So the FIELD is set on TWO levels; only the 3-COMPONENT form is unique to 840.  A
statement that the field is "set on exactly one level" / "empty on the others" is
the round-2 lie and must never return.  It is a POINT, not a box, so the bounds
conclusion itself is unchanged -- but "one level" was false.
  * ``terrain.read_terrain_fields(gil_path)`` plainly takes a path (it opens it
    read-only; the *writer* half is the one that takes no path).

Round 3 -- the round-2 *fix* itself had a copy in a file the round-2 guard did not
cover: ``tools/entity-create/run_parameter_matrix.py`` still called the vector at
``field 11 > 1 > 1`` "the ONLY numeric-range-shaped value ... under field 11" in four
places, one of them a runtime ``reason`` string shown to users.  Re-derived read-only
2026-10-10: 29 of the 37 ``.gil`` files under this machine's uid dir carry field 11,
all 29 hold the constant ``(100, 100, 100)`` triple at ``11 > 1 > 1``, and a SECOND
three-fixed32 vector lives at ``11 > 5 > 1 > 2`` on ``1073741840`` -- so "the only
such value in field 11" is false there exactly as it was in bounds.py.

Round 4 (2026-10-10) -- two further cousins of the same SHAPE.  In
``run_parameter_matrix.py`` the ordinal tab-order evidence still cited a stale
sample ("on 15 real containers"); the real sample is the 29 of 37 ``.gil`` on this
machine that carry field 11.  In ``level_settings.py`` the basic-block docstring and
the ``PART_BASIC`` comment called field 1 "the only ... child ... a float vector" --
true only when scoped to the DIRECT children 1..10 that DIRECTLY contain the vector
(direct child 5 holds the preset vector two levels down, at ``11 > 5 > 1 > 2``), and
an over-read as written.  The wording now says "among the direct children 1..10" and
both old phrasings join ``_BANNED_ABSOLUTES``.

Normalisation -- why it strips comment markers, not just whitespace
-------------------------------------------------------------------
An earlier cut of this guard claimed a re-wrap could not defeat it.  It could.  The
normaliser collapsed whitespace but kept the comment marker, so a lie written

    # MEASURED 2026-10-02 (W24-FIELD11): the container DOES carry one
    # numeric-range-shaped value, and this walk records it verbatim.

flattened to ``... carry one # numeric-range-shaped value ...`` -- the ``#`` sat
between the two words and the banned literal ``does carry one numeric-range-shaped
value`` no longer matched.  What made it worse is that the negative control "proved"
the guard only by splicing a flattened SINGLE line that never existed in the file.

:func:`_norm` therefore (a) case-folds, and (b) deletes every non-word run, so ``#``,
``-``, ``/``, ``:``, ``_`` and newlines alike become a single space.  A re-wrapped or
re-punctuated re-write now normalises onto the same string as the literal it hides.
Where the pre-fix wording survives, the splice-back control splices the wording AS IT
ACTUALLY APPEARED in the real file (recovered from the archive -- see
:data:`_ARCHIVED_PRE_FIX`).  Where it does NOT survive, the control is explicitly
labelled ``SELF-SPLICE`` -- a weaker check that splices the literal into itself -- and
:data:`_CONTROL_SOURCE` records why no real text exists, rather than faking a
recovery (see :meth:`NoFalseUniqueness.test_control_source_classification_is_honest`
and :meth:`NoFalseUniqueness.test_archive_labelled_controls_are_the_real_archive_text`).

The corrected prose is still pinned four ways so a lie cannot return:

  * a **naive search for the old sentence FAILS** -- the exact retired wording is
    gone from each owned file;
  * the corrected markers are **present** -- each file now says a second vector
    exists and that it is a POINT, not a box (or, for terrain, that the reader
    takes a path);
  * the **round-2 absolutes are searched by their own list** (``_BANNED_ABSOLUTES``)
    in bounds.py, level_settings.py and test_level_settings.py, with a per-literal
    negative control that splices each string back in and proves the search fires;
    and
  * the **round-3 / round-4 phrasings join the same list** and
    ``run_parameter_matrix.py`` joins ``_BANNED_FILES``, matched over a normalised
    (case-folded, marker-stripped) copy so a re-cased or re-wrapped re-write cannot
    slip past.

Scope of this guard -- and what is OUTSIDE it
---------------------------------------------
This guard searches exactly five source files, all in the live tree.  It does NOT
sweep the tree, and it does NOT search the historical, git-ignored snapshots under
``.runtime/`` (e.g. ``.runtime/purged-20261008/``).  Those copies are frozen
evidence: this test COPIES a verbatim pre-fix snippet out of one of them (see
:data:`_ARCHIVED_PRE_FIX` / :data:`_ARCHIVE_SNAPSHOT`), but the guard never treats an
archive as in-scope.  A refuted sentence sitting in a git-ignored archive is the
*record* of a lie, not a live one, and searching the archive would make the guard
fail on its own history.  The corollary is a real blind spot, stated so nobody
mistakes this guard for a whole-tree sweep: a lie that lives ONLY in an archive (or
in any other git-ignored snapshot) is beyond this guard's reach by design.

Nothing here touches the bridge, the game, or a save: the test only reads five
source files.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]

_BOUNDS = _REPO / "tools" / "gameplan" / "bounds.py"
_LEVEL_SETTINGS = _REPO / "tools" / "beyond-save" / "level_settings.py"
_TEST_LEVEL_SETTINGS = _REPO / "tools" / "beyond-save" / "test_level_settings.py"
_TERRAIN = _REPO / "tools" / "beyond-save" / "terrain.py"
_RUN_PARAMETER_MATRIX = _REPO / "tools" / "entity-create" / "run_parameter_matrix.py"


# Any run of characters that is neither a word char nor an underscore.  ``\w`` in a
# Python 3 ``str`` pattern is Unicode-aware, so CJK text is a word char and is left
# alone; ``#``, ``-``, ``/``, ``:``, ``>``, ``.``, backtick, ``*``, newline and space
# all collapse.  ``_`` is itself a word char, so the class adds it back explicitly --
# a lie glued together with underscores must be caught too.
_NON_WORD_RUN = re.compile(r"[\W_]+")


def _norm(text: str) -> str:
    """Case-fold AND collapse every non-word run (comment markers included).

    ``"# a-b/c_d"`` and ``"a b c d"`` normalise to the same string, so neither a
    re-wrap (a newline inside a sentence), a re-case ("The ONLY" -> "the only") nor a
    comment marker spliced between two words can hide a sentence from the search.
    Both the haystack and every needle go through the SAME function, so a literal and
    its re-wrapped re-write land on the same bytes.
    """
    return _NON_WORD_RUN.sub(" ", text.lower()).strip()


def _norm_file(path: Path) -> str:
    return _norm(path.read_text(encoding="utf-8"))


# The exact sentences the verifier refuted.  Each was present in the file before
# the fix and MUST be absent now.  Written whole (not as fragments) so the
# corrected text -- which deliberately says "NOT the only ..." -- cannot trip it.
_RETIRED = {
    _BOUNDS: (
        "the only vector / extent-shaped value anywhere inside it is",
        "its only vector-shaped value (field 11 > 1 > 1) is the constant",
        "is the sole float vector in field 11",
    ),
    _LEVEL_SETTINGS: (
        "the **only** vector/extent-shaped value anywhere inside field 11 is",
        "There is **no coordinate** in these records.",
        "The sole float vector in field 11",
        "these carry no coordinate",
    ),
    _TERRAIN: (
        "no function here takes a save path",
    ),
}

# What the corrected text must carry: the truth about the second vector (a POINT,
# not a box) and about the terrain reader taking a path.
_REQUIRED = {
    _BOUNDS: (
        "NOT the only vector-shaped value in field 11",
        "field 11 > 5 > 1 > 2",
        "-0.29665565",
    ),
    _LEVEL_SETTINGS: (
        "NOT the only vector-shaped value in field 11",
        "field 11 > 5 > 1 > 2",
        "not coordinate-free",
        "Among the direct children 1..10 of field 11",
    ),
    _TERRAIN: (
        "*does* take a save path",
        "read-only",
    ),
    _RUN_PARAMETER_MATRIX: (
        "NOT the only range-shaped value in field 11",
        "root/11/5/1/2",
        "1073741840",
        "on 29 real containers",
    ),
}

# The round-2 lie and its family: claiming ``field 11 > 5 > 1 > 2`` is set on a
# SINGLE level.  Each literal below is a fragment of the false wording; none is a
# substring of the corrected prose (which says the field is set on TWO levels and
# that only the 3-component form is unique), so the guard cannot fire on the fix.
_BANNED_ABSOLUTES = (
    "empty on the others",
    "empty, 0 bytes, in every other file",
    "set on exactly one",
    "the one file here that sets it",
    "the only file that sets it",
    "the only float vector in field 11",
    "the sole float vector",
    # Round 3 (2026-10-10) -- the round-2 lie re-worded, found alive in
    # tools/entity-create/run_parameter_matrix.py: the second vector in field 11
    # (at 11 > 5 > 1 > 2) was denied.  All lowercase; the search case-folds.
    "only numeric-range-shaped value anywhere under root/field 11",
    "the only float vector under field 11",
    "does carry one numeric-range-shaped value",
    "the only numeric-range-shaped value in it",
    # Round 4 (2026-10-10) -- two more cousins of the same absolute shape.  (a) the
    # stale measurement base "on 15 real containers" in run_parameter_matrix.py (the
    # real sample is the 29 of 37 .gil that carry field 11); (b) "the only field-11
    # child that holds a float vector" / "the only child carrying a float vector",
    # which over-read the basic block as the sole vector holder -- the preset vector
    # at 11 > 5 > 1 > 2 sits two levels under direct child 5, not directly in it.
    # All lowercase; the search case-folds.
    "on 15 real containers",
    "the only field-11 child that holds a float vector",
    "the only child carrying a float vector",
)

# The files that carry field-11 prose.  The guard file itself is excluded -- it
# holds the banned strings as data, so searching it would be self-refuting.
_BANNED_FILES = (_BOUNDS, _LEVEL_SETTINGS, _TEST_LEVEL_SETTINGS, _RUN_PARAMETER_MATRIX)

# The archived tree snapshot the round-3 pre-fix wording was recovered from.  It is
# historical, git-ignored and READ-ONLY here, and the guard does not search it (see
# the scope note in this module's docstring).  One test reads it -- only to prove the
# constants below are that file's bytes and not an invented convenience form -- and
# skips itself if the archive has been purged.
_ARCHIVE_SNAPSHOT = (
    _REPO / ".runtime" / "purged-20261008" / ".runtime" / "cordis-plan-work"
    / "DS-COVERAGE-20261006" / "_reconstruct" / "tools" / "entity-create"
    / "run_parameter_matrix.py"
)

# The round-2 lie, exactly as this module's round-2 note (above) records it.  The
# pre-fix bounds.py / level_settings.py were NOT captured by the archive: its
# tools/beyond-save snapshots hold only gil_container.py and the save-writers, and it
# has no tools/gameplan tree at all, so this recorded sentence is the best surviving
# verbatim copy of the round-2 wording.
_ROUND_TWO_QUOTE = (
    "``field 11 > 5 > 1 > 2`` is set on exactly ONE level (the one file here "
    "that sets it; it is empty, 0 bytes, in every other file)"
)

# The wording each banned literal wore IN THE REAL FILE, spliced back verbatim by the
# controls below.  The values keep the comment markers, the indentation and -- for the
# third entry -- the LINE BREAK exactly as they sat in the source.  Splicing a
# flattened single line is precisely what let the round-3 lie slip the old control.
#
# Provenance: run_parameter_matrix.py as it sat in _ARCHIVE_SNAPSHOT.  The four
# round-3 entries sit at lines 330, 335, 1667-1668 and 1686-1687; the round-4 entry
# ("on 15 real containers") sits at line 318.  ONLY literals the guard classifies as
# ``archive`` (:data:`_CONTROL_SOURCE`) may appear here -- a self-splicing literal has
# no recovered wording, so inventing one would be the very fake this guard forbids.
_ARCHIVED_PRE_FIX = {
    "only numeric-range-shaped value anywhere under root/field 11":
        "#: The ONLY numeric-range-shaped value anywhere under root/field 11:"
        " a nested message",
    "the only float vector under field 11":
        "#: the 15 real containers on this machine, and the only float vector"
        " under field 11.",
    # WRAPPED across two comment lines -- the exact shape a whitespace-only
    # normaliser loses the "#" to.  Do not flatten this.
    "does carry one numeric-range-shaped value":
        "    # MEASURED 2026-10-02 (W24-FIELD11): the container DOES carry one\n"
        "    # numeric-range-shaped value, and this walk records it verbatim."
        "  It is still",
    "the only numeric-range-shaped value in it":
        "            \"field %d (关卡设置) was located and recorded verbatim;"
        " its sub-field %s is \"\n"
        "            \"the ONLY numeric-range-shaped value in it and reads %s,"
        " but no source says \"",
    # Round 4 -- the stale sample base in run_parameter_matrix.py ("on 15 real
    # containers").  Recovered verbatim from the SAME archived snapshot, line 318, so
    # it is a REAL pre-fix recovery, not a self-splice.
    "on 15 real containers":
        "#: MEASURED 2026-10-02 (W24-FIELD11) on 15 real containers."
        "  field 11's children are",
}

# ---- the control's source, stated honestly ------------------------------------
#
# A negative control is only as strong as the text it splices.  This map is the
# single, auditable declaration of where each banned literal's splice comes from, and
# :meth:`NoFalseUniqueness.test_control_source_classification_is_honest` refuses any
# label that does not match the splice actually performed.
#
#   * ``archive`` -- the splice is verbatim bytes of the git-ignored snapshot
#     (_ARCHIVE_SNAPSHOT), recovered in :data:`_ARCHIVED_PRE_FIX` above.  The
#     strongest control: it reproduces the real punctuation, wrapping and casing.
#   * ``quote``   -- the splice is the recorded round-2 sentence (_ROUND_TWO_QUOTE),
#     which survives only as a quote because the pre-fix files are not in the archive.
#   * ``self``    -- SELF-SPLICE, a deliberately WEAKER check: the literal is spliced
#     into itself, so the control proves only that the search machinery fires on the
#     exact string, never that it would catch the string's real pre-fix punctuation,
#     wrapping or casing.  It is used ONLY where no pre-fix text survives -- see the
#     per-entry notes -- and is never disguised as a recovery.
_CTRL_ARCHIVE = "archive"
_CTRL_QUOTE = "quote"
_CTRL_SELF = "self"

_CONTROL_SOURCE = {
    # ---- archive -- verbatim in _ARCHIVE_SNAPSHOT (see _ARCHIVED_PRE_FIX) ----
    "only numeric-range-shaped value anywhere under root/field 11": _CTRL_ARCHIVE,
    "the only float vector under field 11": _CTRL_ARCHIVE,
    "does carry one numeric-range-shaped value": _CTRL_ARCHIVE,
    "the only numeric-range-shaped value in it": _CTRL_ARCHIVE,
    "on 15 real containers": _CTRL_ARCHIVE,
    # ---- quote -- inside the recorded round-2 sentence (_ROUND_TWO_QUOTE) ----
    "empty, 0 bytes, in every other file": _CTRL_QUOTE,
    "set on exactly one": _CTRL_QUOTE,
    "the one file here that sets it": _CTRL_QUOTE,
    # ---- SELF-SPLICE (weak) -- no pre-fix text survives ----------------------
    # These four are round-2 absolutes from tools/gameplan/bounds.py and
    # tools/beyond-save/level_settings.py.  Neither file survives in the archive: it
    # has ZERO paths under tools/gameplan, ZERO files named bounds.py, and no
    # level_settings.py (the only level_settings* names in it are two unrelated
    # candidates under dynamic-243-20261006).  A full search of every .py AND every
    # .md/.txt/.json file in the archive returns ZERO hits for these fragments -- so
    # there is genuinely no real wording to recover, and faking one is forbidden.
    "empty on the others": _CTRL_SELF,
    "the only file that sets it": _CTRL_SELF,
    "the only float vector in field 11": _CTRL_SELF,
    "the sole float vector": _CTRL_SELF,
    # Two round-4 over-reads, likewise from level_settings.py (absent from the
    # archive; zero hits for their fragments anywhere in it) -- SELF-SPLICE for the
    # same reason.
    "the only field-11 child that holds a float vector": _CTRL_SELF,
    "the only child carrying a float vector": _CTRL_SELF,
}


def _pre_fix_wording(literal: str) -> str:
    """The real-file wording a banned literal is spliced back as.

    Dispatches on :data:`_CONTROL_SOURCE`: an ``archive`` literal splices its verbatim
    archived wording (:data:`_ARCHIVED_PRE_FIX`); a ``quote`` literal splices the
    recorded round-2 sentence (:data:`_ROUND_TWO_QUOTE`); a ``self`` literal -- the
    explicit SELF-SPLICE case, used only where no pre-fix text survives -- splices
    itself, so the spliced text is the literal and never a flat, invented lookalike.
    """
    source = _CONTROL_SOURCE[literal]
    if source == _CTRL_ARCHIVE:
        return _ARCHIVED_PRE_FIX[literal]
    if source == _CTRL_QUOTE:
        return _ROUND_TWO_QUOTE
    return literal


def _absolutes_in(text: str) -> list[str]:
    """Which banned literals *text* carries, over a normalised (case-folded) copy.

    One function used by both the guard test and its negative control, so the
    control proves the *same* search fires on a spliced literal -- not a lookalike.
    """
    flat = _norm(text)
    return [lit for lit in _BANNED_ABSOLUTES if _norm(lit) in flat]


class NoFalseUniqueness(unittest.TestCase):
    def test_retired_sentences_are_gone(self):
        for path, sentences in _RETIRED.items():
            text = _norm_file(path)
            for sentence in sentences:
                with self.subTest(file=path.name, sentence=sentence):
                    self.assertNotIn(
                        _norm(sentence), text,
                        f"{path.name} still carries the refuted sentence {sentence!r}",
                    )

    def test_corrected_text_is_present(self):
        for path, markers in _REQUIRED.items():
            text = _norm_file(path)
            for marker in markers:
                with self.subTest(file=path.name, marker=marker):
                    self.assertIn(
                        _norm(marker), text,
                        f"{path.name} is missing the corrected text {marker!r}",
                    )

    def test_the_absence_search_is_not_vacuous(self):
        """Negative control: the retired-sentence search DOES fire on each lie.

        Without this, a typo in a retired literal would make every ``assertNotIn``
        pass for the wrong reason.  Each retired sentence, spliced back into its own
        file, must trip the same ``assertNotIn`` the guard test runs.
        """
        for path, sentences in _RETIRED.items():
            base = _norm_file(path)
            for sentence in sentences:
                with self.subTest(file=path.name, sentence=sentence):
                    needle = _norm(sentence)
                    self.assertTrue(
                        needle,
                        f"the retired literal {sentence!r} normalises to empty -- "
                        f"every assertNotIn on it would be vacuous",
                    )
                    planted = base + " " + needle
                    with self.assertRaises(AssertionError):
                        self.assertNotIn(
                            needle, planted,
                            f"the retired-sentence search would not see {sentence!r}",
                        )

    def test_round_two_absolutes_are_absent(self):
        """No owned file claims ``field 11 > 5 > 1 > 2`` is set on a single level."""
        for path in _BANNED_FILES:
            hits = _absolutes_in(path.read_text(encoding="utf-8"))
            with self.subTest(file=path.name):
                self.assertEqual(
                    hits, [],
                    f"{path.name} still carries the refuted round-2 absolute(s) {hits}",
                )

    def test_every_banned_literal_would_be_caught(self):
        """Per-literal negative control: splice each literal AS THE REAL FILE WROTE IT.

        For EVERY literal in ``_BANNED_ABSOLUTES`` the guard must fire.  The splice is
        :func:`_pre_fix_wording` -- the verbatim archived wording for the round-3
        literals (comment markers and line break intact), the recorded round-2 sentence
        for the three that sit inside it, and the literal itself otherwise.  The splice
        is fed to the same ``_absolutes_in`` the guard test uses, so the control proves
        the *same* search fires.
        """
        for literal in _BANNED_ABSOLUTES:
            with self.subTest(literal=literal):
                planted = _norm_file(_BOUNDS) + " " + _pre_fix_wording(literal)
                self.assertIn(
                    literal, _absolutes_in(planted),
                    f"the guard missed the banned literal {literal!r} after splicing "
                    f"the real-file wording {_pre_fix_wording(literal)!r}",
                )

    def test_control_source_classification_is_honest(self):
        """The declared control source must match the splice actually performed.

        ``_CONTROL_SOURCE`` labels every banned literal ``archive`` / ``quote`` /
        ``self``.  This test refuses a mislabel: a literal called ``archive`` must
        splice wording drawn from :data:`_ARCHIVED_PRE_FIX`, one called ``quote`` must
        sit inside the recorded :data:`_ROUND_TWO_QUOTE`, and one called ``self`` must
        splice itself and carry NO recovered text -- so a SELF-SPLICE can never
        masquerade as a real recovery, and a real recovery can never be written off as
        a self-splice.  The map and the banned-literal list must also name exactly the
        same literals, so no literal escapes with an unstated (default) source.
        """
        self.assertEqual(
            set(_CONTROL_SOURCE), set(_BANNED_ABSOLUTES),
            "the control-source map and the banned-literal list must name exactly "
            "the same literals",
        )
        for literal, source in _CONTROL_SOURCE.items():
            with self.subTest(literal=literal, source=source):
                self.assertIn(
                    source, (_CTRL_ARCHIVE, _CTRL_QUOTE, _CTRL_SELF),
                    f"{literal!r} carries the unknown control source {source!r}",
                )
                wording = _pre_fix_wording(literal)
                if source == _CTRL_ARCHIVE:
                    self.assertIn(
                        literal, _ARCHIVED_PRE_FIX,
                        f"{literal!r} is labelled 'archive' but has no archived wording",
                    )
                    self.assertIn(
                        _norm(literal), _norm(wording),
                        f"the 'archive' splice for {literal!r} does not carry the "
                        f"literal at all -- the control would not fire on it",
                    )
                elif source == _CTRL_QUOTE:
                    self.assertEqual(
                        wording, _ROUND_TWO_QUOTE,
                        f"{literal!r} is labelled 'quote' but does not splice the "
                        f"recorded round-2 sentence",
                    )
                    self.assertIn(
                        _norm(literal), _norm(_ROUND_TWO_QUOTE),
                        f"{literal!r} is labelled 'quote' but is not inside the "
                        f"recorded round-2 sentence",
                    )
                else:  # _CTRL_SELF -- SELF-SPLICE
                    self.assertEqual(
                        wording, literal,
                        f"{literal!r} is labelled 'self' but splices recovered text",
                    )
                    self.assertNotIn(
                        literal, _ARCHIVED_PRE_FIX,
                        f"{literal!r} is labelled 'self' yet HAS archived wording -- "
                        f"it should be classified 'archive', not self-spliced",
                    )
                    self.assertNotIn(
                        _norm(literal), _norm(_ROUND_TWO_QUOTE),
                        f"{literal!r} is labelled 'self' yet sits in the recorded "
                        f"round-2 sentence -- it should be classified 'quote'",
                    )

    @unittest.skipUnless(_ARCHIVE_SNAPSHOT.exists(),
                         "archived snapshot purged; cannot verify provenance")
    def test_archive_labelled_controls_are_the_real_archive_text(self):
        """Every control labelled ``archive`` splices bytes really in the archive.

        The honesty half that needs the file: a literal :data:`_CONTROL_SOURCE` calls
        ``archive`` must have its splice wording present byte-for-byte in the ignored
        snapshot -- and must NOT be its own literal -- so the ``archive`` label cannot
        be a convenience pasted over a self-splice.
        """
        archived = _ARCHIVE_SNAPSHOT.read_text(encoding="utf-8")
        archive_literals = [
            lit for lit, src in _CONTROL_SOURCE.items() if src == _CTRL_ARCHIVE
        ]
        self.assertTrue(
            archive_literals,
            "no literal is labelled 'archive' -- every control is a weaker check",
        )
        for literal in archive_literals:
            with self.subTest(literal=literal):
                wording = _pre_fix_wording(literal)
                self.assertNotEqual(
                    wording, literal,
                    f"{literal!r} is labelled 'archive' but still splices itself",
                )
                self.assertIn(
                    wording, archived,
                    f"the 'archive' splice for {literal!r} is not verbatim in the "
                    f"archived snapshot -- it was invented, not recovered",
                )

    def test_round_three_lie_is_caught_in_the_matrix_file(self):
        """File-faithful control: splice the REAL pre-fix wording into the matrix file.

        Each of the archived phrasings -- the four round-3 lies plus the round-4 stale
        sample base "on 15 real containers" -- is spliced into run_parameter_matrix.py's
        own text exactly as it sat in the archived file, including the ``does carry one``
        entry, whose comment marker and line break are load-bearing.  The search
        case-folds, so an all-lowercase or all-caps re-write of the SAME lie is caught
        too, not only the casing that happened to be in the archive.
        """
        base = _norm_file(_RUN_PARAMETER_MATRIX)
        for literal, wording in _ARCHIVED_PRE_FIX.items():
            for variant in (wording, wording.lower(), wording.upper()):
                with self.subTest(literal=literal, variant=variant[:24]):
                    hits = _absolutes_in(base + " " + variant)
                    self.assertIn(
                        literal, hits,
                        f"the guard missed the round-3 lie {literal!r} spliced back "
                        f"into run_parameter_matrix.py as {variant!r}",
                    )

    def test_normaliser_strips_comment_markers(self):
        """Guard-machinery test: the normaliser must delete ``#`` / newline / runs.

        This fails -- deliberately -- if ``_norm`` is ever loosened back to a
        whitespace-only collapse.  It pins the machinery, not just the data: the REAL
        re-wrapped round-3 lie (two comment lines) must normalise onto the banned
        literal, while a whitespace-only normaliser (the exact shape that was refuted)
        must MISS it.
        """
        literal = "does carry one numeric-range-shaped value"
        wrapped = _ARCHIVED_PRE_FIX[literal]

        # The machinery: every non-word run -- the two "#" markers and the line break
        # between them included -- vanishes.
        normalised = _norm(wrapped)
        for residue in ("#", "\n", "  "):
            self.assertNotIn(
                residue, normalised,
                f"_norm kept {residue!r}: markers are not being stripped",
            )
        self.assertIn(
            _norm(literal), normalised,
            "the re-wrapped real wording does not normalise onto the banned literal",
        )

        # And the guard sees it end-to-end, not just in isolation.
        planted = _norm_file(_BOUNDS) + "\n" + wrapped
        self.assertIn(
            literal, _absolutes_in(planted),
            "the guard missed the REAL two-comment-line lie",
        )

        # Proof the strip is load-bearing: the whitespace-only normaliser this guard
        # replaced keeps the "#" and would miss the same lie.  If that ever becomes
        # false, this test stops guarding anything and must be revisited.
        legacy = " ".join(wrapped.lower().split())
        self.assertNotIn(
            " ".join(literal.lower().split()), legacy,
            "the refuted whitespace-only normaliser already catches this -- the "
            "marker-stripping being claimed is therefore untested",
        )

    @unittest.skipUnless(_ARCHIVE_SNAPSHOT.exists(),
                         "archived snapshot purged; cannot verify provenance")
    def test_archived_snippets_are_the_real_archive_text(self):
        """The round-3 splices are the archive's bytes, not an invented form.

        Reads the read-only archive (never searched by the guard) and asserts each
        :data:`_ARCHIVED_PRE_FIX` value appears in it verbatim -- so a future edit that
        "tidies" the wrapped entry into a single line is caught here.
        """
        archived = _ARCHIVE_SNAPSHOT.read_text(encoding="utf-8")
        for literal, wording in _ARCHIVED_PRE_FIX.items():
            with self.subTest(literal=literal):
                self.assertIn(
                    wording, archived,
                    f"the spliced wording for {literal!r} is not verbatim in the "
                    f"archived snapshot -- it was invented, not recovered",
                )


if __name__ == "__main__":
    unittest.main()
