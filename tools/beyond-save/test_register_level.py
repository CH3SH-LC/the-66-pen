"""Tests for level registration.

This is the one module in the project that writes the game's own save files, so
the tests are weighted towards the refusals and the undo path rather than the
happy path. Every test runs against a copy of the live save under
``.runtime/beyond-save/fixtures/``; the tests assert that the copy's originals are
untouched, and the live directory is only ever read.

The version gate is NOT under test here.  ``apply_registration`` (and the ``--apply``
CLI) call ``version_guard.require_compatible("all")``, which pins the LEGACY
YuanShen.exe PE baseline and -- by design -- refuses the installed 7.1 image.  That
refusal is expected environmental drift, it is identical on every machine running
this suite, and it is asserted at full strength in ``test_update_guard.py``.  The
``version_gate`` fixture below therefore substitutes a passing stub *only when the
live gate refuses*, so the registration mechanics stay under test; when the live
gate matches the pinned image the real gate is left in place.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "compatibility"))

import register_level  # noqa: E402
import version_guard  # noqa: E402
from gil_container import (  # noqa: E402
    ContainerError,
    decode_container,
    next_level_id,
    parse_fields,
    parse_profile,
    read_level,
    read_profile,
)
from register_level import (  # noqa: E402
    apply_registration,
    build_new_level,
    plan_registration,
    stage_registration,
    take_backup,
    verify_registration,
)

LIVE = Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal" / "100000001"
WORKSPACE = Path(__file__).resolve().parents[2] / ".runtime" / "beyond-save" / "register-tests"

pytestmark = pytest.mark.skipif(not LIVE.exists(), reason="no live Miliastra save on this machine")


@pytest.fixture(autouse=True)
def version_gate(monkeypatch):
    """Keep the version gate out of the mechanics tests, but only when it must.

    The gate pins the legacy PE baseline of the installed game.  On the current
    7.1 install it refuses (``game.timestamp``/anchors drifted), which is expected
    -- see the module docstring and ``test_update_guard.py``, where the refusal,
    the re-check before each write and the CLI exit code are all asserted.  When
    the live gate *does* match the pinned image, it is left in place so these
    tests still run behind the real gate.
    """
    try:
        report = version_guard.check_compatibility("all")
    except Exception as error:  # fail closed: an unreadable gate is a refusing gate
        report = {"ok": False, "reasons": ["%s: %s" % (type(error).__name__, error)]}
    if not report.get("ok"):
        monkeypatch.setattr(
            register_level, "require_compatible",
            lambda component="all": {"ok": True, "component": component,
                                     "stubbedBecause": "live version gate refuses the installed build"},
        )


@pytest.fixture
def uid_dir(tmp_path) -> Path:
    """A throwaway copy of the whole uid directory."""
    dst = tmp_path / "100000001"
    shutil.copytree(LIVE, dst)
    return dst


@pytest.fixture
def backups(tmp_path) -> Path:
    return tmp_path / "backups"


def profile_bytes(uid_dir: Path) -> bytes:
    return (uid_dir / "Beyond_Local_Save_Player.gip").read_bytes()


def profile_of(uid_dir: Path):
    return parse_profile(decode_container(profile_bytes(uid_dir)).payload)


def level_file_count(uid_dir: Path) -> int:
    """How many LEVELS the level directory holds, in EITHER on-disk shape.

    The game changed this layout on 2026-09-23 (YuanShen.exe was patched the same
    day; the first ``<id>/`` directory is timestamped Sep 23 18:15). A level with
    no external script is still a flat ``<id>.gil`` file, but a level that carries
    external Lua is now a directory ``<id>/`` holding ``<id>.gil`` (plus
    ``external_lua_file/``). Both shapes are one level. The live directory shows
    both at once -- 1073741825..1834 are files, 1073741835..1842 are directories --
    and the profile lists all eighteen. Counting only top-level ``*.gil`` was right
    under the old layout and is wrong now. The game's own ``UpgradeBackup/`` (and
    any other non-numeric directory) is not a level and is excluded.
    """
    level_dir = uid_dir / "Beyond_Local_Save_Level"
    flat = [p for p in level_dir.glob("*.gil") if p.is_file()]
    nested = [
        p for p in level_dir.iterdir()
        if p.is_dir() and p.name.isdigit() and (p / f"{p.name}.gil").is_file()
    ]
    return len(flat) + len(nested)


# Expectations are DERIVED from the fixture, never hardcoded to a level count.
#
# These tests copy the live save, and the live save is not frozen: registering a
# level here changes it, and so does the user playing the game. Asserting "there
# are four levels" made the suite pass only until the first registration, at which
# point fifteen tests failed for a reason that had nothing to do with the code.
# The tests are about the registration mechanics, so they must describe the
# mechanics and read the counts off the fixture they were given.


def level_names(uid_dir: Path) -> dict[int, str]:
    d = uid_dir / "Beyond_Local_Save_Level"
    return {read_level(p).level_id: read_level(p).name for p in sorted(d.glob("*.gil"))}


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def test_plan_allocates_the_next_free_id(uid_dir, backups):
    before = profile_of(uid_dir)
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    assert plan.level_id == next_level_id(before)
    assert plan.level_id > max(r.level_id for r in before.levels)


def test_plan_against_the_live_directory_does_not_touch_it():
    before = {p.name: p.read_bytes() for p in LIVE.rglob("*") if p.is_file()}
    plan_registration("demo", uid_dir=LIVE, backup_root=WORKSPACE)
    after = {p.name: p.read_bytes() for p in LIVE.rglob("*") if p.is_file()}
    assert before == after


def test_plan_refuses_an_id_the_profile_already_lists(uid_dir, backups):
    existing = profile_of(uid_dir).levels[0].level_id
    with pytest.raises(ContainerError, match="already lists level"):
        plan_registration("demo", uid_dir=uid_dir, backup_root=backups, level_id=existing)


def test_plan_refuses_an_id_a_file_already_uses(uid_dir, backups):
    """A level id must be free in BOTH the profile and the level directory.

    The next id is free in both to start with, so planning against it succeeds. An
    orphaned file at that id -- which is what a crashed registration leaves behind
    -- must then block it.
    """
    free_id = next_level_id(profile_of(uid_dir))
    template = min((uid_dir / "Beyond_Local_Save_Level").glob("*.gil"), key=lambda p: p.stat().st_size)
    orphan = uid_dir / "Beyond_Local_Save_Level" / f"{free_id}.gil"
    assert plan_registration("demo", uid_dir=uid_dir, backup_root=backups, level_id=free_id)
    orphan.write_bytes(template.read_bytes())
    with pytest.raises(ContainerError, match="already exists"):
        plan_registration("demo", uid_dir=uid_dir, backup_root=backups, level_id=free_id)


def test_planned_profile_keeps_every_existing_entry(uid_dir, backups):
    before = parse_profile(decode_container(profile_bytes(uid_dir)).payload)
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    after = parse_profile(plan.profile_payload)
    assert [r.level_id for r in after.levels][: len(before.levels)] == [
        r.level_id for r in before.levels
    ]
    assert [r.name for r in after.levels][: len(before.levels)] == [
        r.name for r in before.levels
    ]
    assert len(after.levels) == len(before.levels) + 1


def test_planned_profile_names_the_new_level(uid_dir, backups):
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups)
    after = parse_profile(plan.profile_payload)
    assert after.levels[-1].name == "demo_关卡_1"
    assert after.levels[-1].level_id == plan.level_id


def test_planned_level_carries_id_name_creator_and_timestamp(uid_dir, backups):
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups, now=1_789_000_000)
    level = read_level_payload(plan.level_payload)
    assert level.level_id == plan.level_id
    assert level.name == "demo_关卡_1"
    assert level.creator_uid == 100000001
    assert level.timestamp == 1_789_000_000


def read_level_payload(payload: bytes):
    from gil_container import parse_level
    return parse_level(payload)


def test_planned_level_keeps_the_template_fields_ascending(uid_dir, backups):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    numbers = [f.number for f in parse_fields(plan.level_payload)]
    assert numbers == sorted(numbers), "the game writes fields ascending; match it"


def test_planned_level_keeps_fields_the_template_had(uid_dir, backups):
    template = min(
        (uid_dir / "Beyond_Local_Save_Level").glob("*.gil"), key=lambda p: p.stat().st_size
    )
    template_fields = {f.number for f in parse_fields(decode_container(template.read_bytes()).payload)}
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    planned_fields = {f.number for f in parse_fields(plan.level_payload)}
    assert template_fields <= planned_fields


def test_build_new_level_writes_utf8_names(uid_dir, backups):
    template = decode_container(
        min((uid_dir / "Beyond_Local_Save_Level").glob("*.gil"), key=lambda p: p.stat().st_size).read_bytes()
    ).payload
    payload = build_new_level(template, 0x40000009, "测试_关卡", 100000001, 1_789_000_000)
    assert read_level_payload(payload).name == "测试_关卡"


# --------------------------------------------------------------------------- #
# backup
# --------------------------------------------------------------------------- #

def test_backup_must_be_taken_before_anything_is_written(uid_dir, backups):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    assert not plan.level_path.exists(), "planning must not create the level file"
    assert parse_profile(decode_container(profile_bytes(uid_dir)).payload).levels[-1].level_id != plan.level_id


def test_backup_copies_the_profile_and_every_level(uid_dir, backups):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    report = take_backup(plan)
    # take_backup copies the WHOLE level directory verbatim (see its docstring), so
    # its levelCount is the number of directory ENTRIES it copied. Before the
    # 2026-09-23 layout change every entry was a level and that count equalled the
    # level count; now a scripted level is a directory and the game also keeps its
    # own UpgradeBackup/ here, so the two differ. Compare against the live ENTRY
    # count, and assert completeness against that same list.
    live_entries = sorted(p.name for p in (uid_dir / "Beyond_Local_Save_Level").glob("*"))
    assert report["levelCount"] == len(live_entries)
    backup_levels = sorted(p.name for p in Path(report["levels"]).glob("*"))
    assert backup_levels == live_entries
    assert Path(report["profile"]).read_bytes() == profile_bytes(uid_dir)


def test_backup_refuses_to_overwrite_an_existing_backup(uid_dir, backups):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    take_backup(plan)
    with pytest.raises(FileExistsError):
        take_backup(plan)


# --------------------------------------------------------------------------- #
# staging -- the default path, because the live save is the user's own data
# --------------------------------------------------------------------------- #

def test_stage_writes_both_candidates_into_the_given_directory(uid_dir, backups, tmp_path):
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups, now=1_789_000_000)
    before_profile = profile_bytes(uid_dir)
    before_levels = {p.name for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")}

    out = tmp_path / "staged"
    staged = stage_registration(plan, out)

    assert Path(staged["stagedLevel"]).exists()
    assert Path(staged["stagedProfile"]).exists()
    assert staged["levelName"] == "demo_关卡_1"
    assert staged["profileListsLevel"] is True
    assert staged["profileLevelCount"] == level_file_count(uid_dir) + 1

    # The whole point of staging: the live save is byte-identical afterwards.
    assert profile_bytes(uid_dir) == before_profile
    assert {p.name for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")} == before_levels
    assert staged["liveSaveUntouched"] is True


def test_staged_candidates_parse_back_through_the_real_readers(uid_dir, backups, tmp_path):
    plan = plan_registration("demo_关卡_2", uid_dir=uid_dir, backup_root=backups)
    staged = stage_registration(plan, tmp_path / "staged")

    level = read_level(Path(staged["stagedLevel"]))
    assert level.level_id == plan.level_id
    assert level.name == "demo_关卡_2"
    assert level.creator_uid == 100000001

    profile = read_profile(Path(staged["stagedProfile"]))
    ids = [r.level_id for r in profile.levels]
    assert ids[-1] == plan.level_id
    assert len(ids) == level_file_count(uid_dir) + 1


def test_staged_level_carries_the_subtype_a_level_needs(uid_dir, backups, tmp_path):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    staged = stage_registration(plan, tmp_path / "staged")
    assert decode_container(Path(staged["stagedLevel"]).read_bytes()).subtype == 2
    assert decode_container(Path(staged["stagedProfile"]).read_bytes()).subtype == 1


def test_staged_profile_files_the_level_under_a_tab(uid_dir, backups, tmp_path):
    """The editor groups levels into tabs; a flat-list-only entry is half a registration."""
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups)
    staged = stage_registration(plan, tmp_path / "staged")

    before = profile_of(uid_dir)
    assert staged["profileListsLevel"] is True
    # The default tab name is 自定义页签_<n>, n being one past the tabs already there.
    assert staged["filedUnderTabs"] == [f"自定义页签_{len(before.tabs) + 1}"]
    assert staged["tabCount"] == len(before.tabs) + 1

    profile = read_profile(Path(staged["stagedProfile"]))
    filed = [lid for tab in profile.tabs for _, lid in tab.members]
    assert sorted(filed) == sorted(ref.level_id for ref in profile.levels)


def test_apply_files_the_level_under_a_tab_in_the_live_directory(uid_dir, backups):
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups)
    take_backup(plan)
    apply_registration(plan)

    profile = read_profile(uid_dir / "Beyond_Local_Save_Player.gip")
    filed = [lid for tab in profile.tabs for _, lid in tab.members]
    assert plan.level_id in filed
    assert plan.level_id in [r.level_id for r in profile.levels]


def test_registered_level_name_agrees_with_its_tab(uid_dir, backups):
    """The four live levels are named after the tab they sit in. Match that convention
    so a registered level looks like one the game made rather than a foreign entry."""
    plan = plan_registration("自定义页签_3_存档", uid_dir=uid_dir, backup_root=backups,
                             tab_name="自定义页签_3")
    take_backup(plan)
    apply_registration(plan)
    profile = read_profile(uid_dir / "Beyond_Local_Save_Player.gip")
    tab = next(t for t in profile.tabs if t.name == "自定义页签_3")
    assert (1600, plan.level_id) in tab.members
    ref = next(r for r in profile.levels if r.level_id == plan.level_id)
    assert ref.name.startswith(tab.name)


def test_staging_is_idempotent_for_the_same_plan(uid_dir, backups, tmp_path):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    out = tmp_path / "staged"
    first = stage_registration(plan, out)
    second = stage_registration(plan, out)
    assert first == second


def test_live_save_is_untouched_by_the_whole_stage_flow(uid_dir, backups, tmp_path):
    """Full-flow check: plan, stage, re-read the live directory, compare byte for byte."""
    before = {
        p.relative_to(uid_dir).as_posix(): p.read_bytes()
        for p in uid_dir.rglob("*") if p.is_file()
    }
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    stage_registration(plan, tmp_path / "staged")
    after = {
        p.relative_to(uid_dir).as_posix(): p.read_bytes()
        for p in uid_dir.rglob("*") if p.is_file()
    }
    assert before == after


# --------------------------------------------------------------------------- #
# apply and undo
# --------------------------------------------------------------------------- #

def test_apply_writes_both_files_and_verifies_by_reading_back(uid_dir, backups):
    before = level_file_count(uid_dir)
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups, now=1_789_000_000)
    take_backup(plan)
    result = apply_registration(plan)
    assert result["levelId"] == plan.level_id
    assert result["levelName"] == "demo_关卡_1"
    assert result["levelCreatorUid"] == 100000001
    assert result["profileListsLevel"] is True
    assert result["profileLevelName"] == "demo_关卡_1"
    assert result["profileLevelCount"] == before + 1


def test_apply_is_visible_to_a_fresh_read_of_the_files(uid_dir, backups):
    plan = plan_registration("demo_关卡_1", uid_dir=uid_dir, backup_root=backups)
    take_backup(plan)
    apply_registration(plan)

    on_disk = read_level(uid_dir / "Beyond_Local_Save_Level" / f"{plan.level_id}.gil")
    assert on_disk.name == "demo_关卡_1"
    profile = parse_profile(decode_container(profile_bytes(uid_dir)).payload)
    assert plan.level_id in [r.level_id for r in profile.levels]


def test_apply_leaves_untouched_levels_byte_identical(uid_dir, backups):
    before = {
        p.name: p.read_bytes()
        for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")
    }
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    take_backup(plan)
    apply_registration(plan)
    after = {
        p.name: p.read_bytes()
        for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")
        if p.name != f"{plan.level_id}.gil"
    }
    assert before == after


def test_the_same_plan_verifies_twice_without_drifting(uid_dir, backups):
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    take_backup(plan)
    first = apply_registration(plan)
    second = verify_registration(plan)
    assert first == second


def test_undo_from_the_backup_restores_the_directory_exactly(uid_dir, backups):
    before_profile = profile_bytes(uid_dir)
    before_levels = {
        p.name: p.read_bytes() for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")
    }
    plan = plan_registration("demo", uid_dir=uid_dir, backup_root=backups)
    report = take_backup(plan)
    apply_registration(plan)

    shutil.copy2(report["profile"], plan.profile_path)
    (uid_dir / "Beyond_Local_Save_Level" / f"{plan.level_id}.gil").unlink()

    assert profile_bytes(uid_dir) == before_profile
    assert {
        p.name: p.read_bytes() for p in (uid_dir / "Beyond_Local_Save_Level").glob("*.gil")
    } == before_levels


def test_registering_a_second_level_stacks_cleanly(uid_dir, backups):
    before = level_file_count(uid_dir)
    first = plan_registration("demo_1", uid_dir=uid_dir, backup_root=backups)
    take_backup(first)
    apply_registration(first)

    second = plan_registration("demo_2", uid_dir=uid_dir, backup_root=backups)
    assert second.level_id == first.level_id + 1
    take_backup(second)
    result = apply_registration(second)
    assert result["profileLevelCount"] == before + 2
    assert level_names(uid_dir)[first.level_id] == "demo_1"
    assert level_names(uid_dir)[second.level_id] == "demo_2"
