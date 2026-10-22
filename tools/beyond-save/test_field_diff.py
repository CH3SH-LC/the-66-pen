"""Tests for the ``.gil`` field differ.

Four properties the task calls for, plus two more that pin the classification
edges:

  * the real graph-build save pair reports exactly the five fields that moved,
    with the classifications the module docstring documents;
  * the same file diffed against itself reports nothing;
  * a synthetically appended field is classified ``appended-tail``;
  * the report is deterministic.

The pinned ``REAL_EXPECTED`` facts are split by SUBJECT, the same way
``tools/gameplan/tests/test_verify_graph_on_disk.py`` splits its real pair:

  * the pinned pair is **BEFORE x a FROZEN in-repo held save** (``FROZEN_AFTER``,
    taken in the same wave as BEFORE).  Both sides are immutable artefacts, so the
    exact numbers are honest and those tests run unconditionally -- the claim is
    asserted to be true of SOME real held save;
  * the **LIVE** save (the game autosaves and the owner swaps saves) is a separate
    subject.  While it still equals the recorded demo snapshot its diff is the same
    five fields; once it drifts, those pins SKIP with a named reason instead of
    failing (a live ``.gil`` is not a constant -- field 5 was 3181 B at demo time
    and is larger now).

Skipping is distinct from failing on purpose: a fabricated expectation still FAILS
(the frozen held save is the gate), while honest drift of a live file only skips.
Both files may be absent on another machine, in which case those tests skip.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from field_diff import (  # noqa: E402
    APPENDED_TAIL,
    IN_PLACE_REWRITE,
    REPLACED,
    FieldDiff,
    classify,
    diff_gils,
    diff_payloads,
    render,
)
from gil_container import (  # noqa: E402
    SUBTYPE_LEVEL,
    Container,
    Field,
    WIRE_LENGTH,
    WIRE_VARINT,
    encode_container,
    encode_fields,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# BEFORE: our in-repo pre-save backup -- an immutable artefact, so an exact byte
# count here is honest (not a property of the machine's current state).
BEFORE = (
    PROJECT_ROOT / ".runtime" / "editor-bridge" / "backups"
    / "20261009T163136Z-pre-graph-demo-save-20261010" / "files"
    / "Beyond_Local_Save_Level" / "1073741842" / "1073741842.gil"
)

# The frozen, in-repo AFTER: the post-save .gil taken in the SAME wave as BEFORE
# (its ``before-1073741842.gil`` is byte-identical to BEFORE).  It IS the
# demo-time live save (28383 B), now an immutable held save -- so the pinned
# REAL_EXPECTED facts are a claim about SOME real held save, which is the
# disposition the sibling guard (``DocSaveFactsMatchDisk``) applies.  Pinning the
# pair here makes the diff deterministic instead of keyed to a drifting live file.
FROZEN_AFTER = (
    PROJECT_ROOT / ".runtime" / "game-executor" / "scene-cli"
    / "20261010-004106-save-640895e1" / "after-1073741842.gil"
)

# The LIVE save the game keeps autosaving -- NOT a constant (the owner also swaps
# saves between sessions).  Read only; never written.
GAME_DATA = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
LIVE_AFTER = (
    GAME_DATA / "100000001" / "Beyond_Local_Save_Level" / "1073741842" / "1073741842.gil"
)

#: The pair the pinned tests run against: BEFORE x the FROZEN held save.
AFTER = FROZEN_AFTER

real_pair = pytest.mark.skipif(
    not (BEFORE.exists() and AFTER.exists()),
    reason="real graph-build save pair (backup + frozen after) not present on this machine",
)

live_pair = pytest.mark.skipif(
    not (BEFORE.exists() and LIVE_AFTER.exists()),
    reason="live 1073741842 save not present on this machine",
)

#: The frozen demo-time save's identity -- an immutable in-repo artefact, safe to
#: pin.  It is a property of THAT save, not of our decoder or the current machine.
DEMO_SNAPSHOT_SIZE = 28383
DEMO_SNAPSHOT_SHA = "56feb97d916d903789cc47028bb47028ab2f587501f978e28daabb36dc919164"


def _live_matches_demo_snapshot() -> tuple[bool, str]:
    """True iff the LIVE save is still the byte-exact demo snapshot."""
    if not LIVE_AFTER.exists():
        return False, "live 1073741842.gil not present"
    size = LIVE_AFTER.stat().st_size
    if size != DEMO_SNAPSHOT_SIZE:
        return False, (
            f"live save is {size} B, not the recorded {DEMO_SNAPSHOT_SIZE} B demo "
            "snapshot -- the game autosaved and the .gil drifted; pinned-diff tests "
            "skipped (the frozen held save still pins them)")
    if hashlib.sha256(LIVE_AFTER.read_bytes()).hexdigest() != DEMO_SNAPSHOT_SHA:
        return False, ("live save sha256 differs from the recorded demo snapshot; "
                       "pinned-diff tests skipped")
    return True, ""


LIVE_SNAPSHOT_OK, LIVE_SNAPSHOT_REASON = _live_matches_demo_snapshot()

#: Guard for the tests that pin the diff of the LIVE save: they keep their exact
#: bodies and run while the live file still equals the snapshot, else they SKIP
#: with a named reason -- a live save is not a constant.  The frozen held save is
#: what actually pins the claim, and those tests never skip on drift.
requires_live_snapshot = pytest.mark.skipif(
    not LIVE_SNAPSHOT_OK,
    reason=LIVE_SNAPSHOT_REASON or "live save drifted from the recorded demo snapshot")


def write_gil(path: Path, payload: bytes) -> Path:
    """A minimal valid level container around a raw payload."""
    path.write_bytes(encode_container(Container(subtype=SUBTYPE_LEVEL, payload=payload)))
    return path


# --------------------------------------------------------------------------- #
# the real graph-build save pair -- BEFORE x the FROZEN held save
# --------------------------------------------------------------------------- #

# number -> (classification, old_size, first_differing_offset,
#            old_is_prefix_of_new, new_is_prefix_of_old)
# Both sides are frozen in-repo artefacts (BEFORE is the pre-save backup,
# AFTER is the frozen post-save held save taken in the same wave), so every
# literal here is a fact about THOSE bytes -- a claim true of a real held save,
# not a pin on the machine's current state.  ``new_size`` is deliberately absent:
# the classification already encodes the size RELATIONSHIP, and the exact new
# sizes are readable from the frozen file at run time.
REAL_EXPECTED = {
    5: (APPENDED_TAIL, 3181, 3181, True, False),
    6: (REPLACED, 1450, 589, False, False),
    10: (REPLACED, 2, 0, False, False),
    29: (IN_PLACE_REWRITE, 55, 29, False, False),
    46: (REPLACED, 22, 3, False, False),
}


@real_pair
def test_frozen_after_is_the_recorded_demo_save():
    # the pinned pair's AFTER is the demo-time live save, kept immutable in-repo.
    assert len(AFTER.read_bytes()) == DEMO_SNAPSHOT_SIZE
    assert hashlib.sha256(AFTER.read_bytes()).hexdigest() == DEMO_SNAPSHOT_SHA


@real_pair
def test_real_pair_sizes():
    report = diff_gils(BEFORE, AFTER)
    # both sides are frozen in-repo artefacts -> exact byte counts are honest
    assert report.before_size == 21872
    assert report.after_size == AFTER.stat().st_size
    assert report.after_size >= report.before_size


@real_pair
def test_real_pair_changed_fields_are_exactly_the_five():
    report = diff_gils(BEFORE, AFTER)
    assert set(report.changed_numbers) == set(REAL_EXPECTED)


@real_pair
def test_real_pair_classifications_and_offsets():
    report = diff_gils(BEFORE, AFTER)
    got = {
        d.number: (
            d.classification, d.old_size, d.first_differing_offset,
            d.old_is_prefix_of_new, d.new_is_prefix_of_old,
        )
        for d in report.changed
    }
    assert got == REAL_EXPECTED
    # the size RELATIONSHIP the classification encodes, checked without a literal
    for d in report.changed:
        if d.classification == IN_PLACE_REWRITE:
            assert d.old_size == d.new_size


@real_pair
def test_the_pinned_diff_is_not_vacuous():
    """Negative control: a FABRICATED expectation is caught (fails), never quietly
    satisfied -- so the pins above are load-bearing, not tautologies.  This is the
    frozen held save, which is always compared (no skip), so it is the gate."""
    fabricated = dict(REAL_EXPECTED)
    fabricated[5] = (REPLACED, 3181, 1, False, False)   # truth: appended-tail
    fabricated[99] = (REPLACED, 1, 0, False, False)     # field 99 never changed
    report = diff_gils(BEFORE, AFTER)
    got = {
        d.number: (
            d.classification, d.old_size, d.first_differing_offset,
            d.old_is_prefix_of_new, d.new_is_prefix_of_old,
        )
        for d in report.changed
    }
    assert got == REAL_EXPECTED
    assert got != fabricated


@real_pair
def test_real_pair_has_no_top_level_field_added_or_removed():
    report = diff_gils(BEFORE, AFTER)
    # A field present in only one file would show as a zero-length side; none do.
    for d in report.changed:
        assert d.old_size > 0 and d.new_size > 0


@real_pair
def test_real_pair_report_is_ordered_by_field_number():
    report = diff_gils(BEFORE, AFTER)
    assert list(report.changed_numbers) == sorted(report.changed_numbers)


# --------------------------------------------------------------------------- #
# the LIVE save -- a separate subject that drifts
# --------------------------------------------------------------------------- #
# The live 1073741842.gil is the very file the frozen AFTER was copied from, but
# the game keeps autosaving it (and the owner swaps saves between sessions), so its
# bytes are a property of the machine, not of our code.  What is TRUE regardless of
# how it grows is asserted unconditionally; the pinned DEMO diff is asserted only
# WHILE the live file still equals the recorded snapshot, and otherwise SKIPS with
# a named reason -- it never fails on honest drift.  (The frozen held save above is
# what unconditionally pins the claim.)

@live_pair
def test_live_pair_is_self_consistent_about_the_frozen_before():
    """BEFORE is immutable; AFTER is whatever the live file now is."""
    report = diff_gils(BEFORE, LIVE_AFTER)
    assert report.before_size == 21872
    assert report.after_size == LIVE_AFTER.stat().st_size
    assert report.after_size >= report.before_size
    assert list(report.changed_numbers) == sorted(report.changed_numbers)


@live_pair
@requires_live_snapshot
def test_live_pair_still_shows_the_demo_five_fields():
    """While the live save still equals the recorded snapshot its diff is the same
    five fields; on drift this SKIPS with a named reason (it does not fail, and its
    assertion is not weakened -- the frozen held-save tests above keep it exact)."""
    report = diff_gils(BEFORE, LIVE_AFTER)
    got = {
        d.number: (
            d.classification, d.old_size, d.first_differing_offset,
            d.old_is_prefix_of_new, d.new_is_prefix_of_old,
        )
        for d in report.changed
    }
    assert got == REAL_EXPECTED


@live_pair
@requires_live_snapshot
def test_live_pair_still_has_no_top_level_field_added_or_removed():
    report = diff_gils(BEFORE, LIVE_AFTER)
    for d in report.changed:
        assert d.old_size > 0 and d.new_size > 0


# --------------------------------------------------------------------------- #
# a no-change pair reports nothing
# --------------------------------------------------------------------------- #

@real_pair
def test_same_file_twice_reports_nothing():
    report = diff_gils(BEFORE, BEFORE)
    assert report.changed == ()
    assert report.is_identical
    assert "no top-level field changed" in render(report)


# --------------------------------------------------------------------------- #
# synthetic pairs -- one per classification
# --------------------------------------------------------------------------- #

def test_synthetic_appended_field_is_appended_tail(tmp_path: Path):
    base = encode_fields([
        Field(1, WIRE_VARINT, value=1073741825),
        Field(2, WIRE_LENGTH, data=b"level"),
    ])
    # A whole new top-level field, field 60, appended after the existing ones.
    grown = base + encode_fields([Field(60, WIRE_LENGTH, data=b"appended")])

    before = write_gil(tmp_path / "before.gil", base)
    after = write_gil(tmp_path / "after.gil", grown)

    report = diff_gils(before, after)
    assert report.changed_numbers == (60,)
    d = report.changed[0]
    assert d.classification == APPENDED_TAIL
    assert d.old_size == 0 and d.new_size == len(b"appended")
    assert d.first_differing_offset == 0
    assert d.old_is_prefix_of_new  # the empty string is a prefix of anything


def test_synthetic_tail_appended_to_existing_field_is_appended_tail():
    old = encode_fields([Field(2, WIRE_LENGTH, data=b"abc")])
    new = encode_fields([Field(2, WIRE_LENGTH, data=b"abcdef")])
    (d,) = diff_payloads(old, new)
    assert d.classification == APPENDED_TAIL
    assert (d.old_size, d.new_size, d.first_differing_offset) == (3, 6, 3)
    assert d.old_is_prefix_of_new


def test_synthetic_same_length_change_is_in_place_rewrite():
    old = encode_fields([Field(2, WIRE_LENGTH, data=b"abc")])
    new = encode_fields([Field(2, WIRE_LENGTH, data=b"abd")])
    (d,) = diff_payloads(old, new)
    assert d.classification == IN_PLACE_REWRITE
    assert (d.old_size, d.new_size, d.first_differing_offset) == (3, 3, 2)


def test_synthetic_unrelated_lengths_is_replaced():
    old = encode_fields([Field(2, WIRE_LENGTH, data=b"abc")])
    new = encode_fields([Field(2, WIRE_LENGTH, data=b"xyzjkl")])
    (d,) = diff_payloads(old, new)
    assert d.classification == REPLACED
    assert (d.old_size, d.new_size, d.first_differing_offset) == (3, 6, 0)


def test_classify_covers_every_branch():
    assert classify(b"a", b"a") == "unchanged"
    assert classify(b"a", b"ab") == APPENDED_TAIL
    assert classify(b"ab", b"a") == APPENDED_TAIL
    assert classify(b"ab", b"ax") == IN_PLACE_REWRITE
    assert classify(b"ab", b"xyz") == REPLACED


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #

def test_report_is_deterministic_on_synthetic(tmp_path: Path):
    before = write_gil(tmp_path / "b.gil", encode_fields([
        Field(1, WIRE_VARINT, value=1),
        Field(2, WIRE_LENGTH, data=b"aa"),
        Field(3, WIRE_LENGTH, data=b"bb"),
    ]))
    after = write_gil(tmp_path / "a.gil", encode_fields([
        Field(1, WIRE_VARINT, value=1),
        Field(2, WIRE_LENGTH, data=b"aax"),
        Field(3, WIRE_LENGTH, data=b"cc"),
    ]))
    assert diff_gils(before, after) == diff_gils(before, after)


@real_pair
def test_report_is_deterministic_on_real_pair():
    assert diff_gils(BEFORE, AFTER) == diff_gils(BEFORE, AFTER)


def test_render_is_stable_text():
    before = encode_fields([Field(2, WIRE_LENGTH, data=b"abc")])
    after = encode_fields([Field(2, WIRE_LENGTH, data=b"abcdef")])
    report = diff_payloads(before, after)
    # FieldDiff rows come back as a tuple, so rendering is pure text -- same input,
    # same output, no set/dict ordering anywhere.
    from field_diff import SaveDiff
    wrapper = SaveDiff("b", "a", 10, 13, report)
    assert render(wrapper) == render(wrapper)
    assert render(wrapper).splitlines()[-1].split()[-1] == APPENDED_TAIL


def test_field_diff_is_frozen():
    d = FieldDiff(1, WIRE_VARINT, 1, 2, 1, True, False, APPENDED_TAIL)
    with pytest.raises(Exception):
        d.number = 9  # type: ignore[misc]
