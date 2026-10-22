"""Tests for the Beyond local save container codec.

The load-bearing test is ``test_roundtrip_is_byte_identical``: if decoding and
re-encoding a real file does not reproduce it exactly, then editing one field
would silently rewrite the parts the codec did not understand, and no amount of
schema work would make it safe to write back.

Real files are read from the live game directory but never written to. Each is
copied into ``.runtime/beyond-save/fixtures/`` first, and every test works on the
copy.
"""
from __future__ import annotations

import shutil
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    MAGIC,
    TRAILER,
    VERSION,
    Container,
    ContainerError,
    Field,
    add_level_to_profile,
    build_level,
    build_level_ref,
    build_profile,
    decode_container,
    encode_container,
    encode_fields,
    next_level_id,
    parse_fields,
    parse_level,
    parse_profile,
    read_level,
    write_varint,
)

GAME_DATA = (
    Path.home() / "AppData" / "LocalLow" / "miHoYo" / "原神" / "BeyondLocal"
)
UID_DIR = GAME_DATA / "100000001"
PROFILE_SRC = UID_DIR / "Beyond_Local_Save_Player.gip"
LEVEL_DIR = UID_DIR / "Beyond_Local_Save_Level"
FIXTURES = Path(__file__).resolve().parents[2] / ".runtime" / "beyond-save" / "fixtures"

pytestmark = pytest.mark.skipif(
    not PROFILE_SRC.exists(), reason="no live Miliastra save on this machine"
)


@pytest.fixture(scope="module")
def fixtures() -> dict[str, Path]:
    """Copies of the real files, inside the project tree.

    The game changed the level layout on 2026-09-23 (same-day install: YuanShen.exe
    mtime Sep 23; the first ``<id>/`` directory is timestamped Sep 23 18:15). A
    level with no external script is still a flat ``<id>.gil``, but a level that
    carries external Lua is now a directory ``<id>/`` holding ``<id>.gil`` (and
    ``external_lua_file/``). The live level directory holds BOTH at once -- ids
    1073741825..1834 are files, 1073741835..1842 are directories -- and the player
    profile lists all eighteen. The fixture must therefore carry both shapes; no
    test here may assume a level is always a top-level ``.gil``.
    """
    if FIXTURES.exists():
        shutil.rmtree(FIXTURES)
    FIXTURES.mkdir(parents=True)
    copies = {"profile": FIXTURES / PROFILE_SRC.name}
    shutil.copy2(PROFILE_SRC, copies["profile"])
    # Old shape: a flat <id>.gil directly under Beyond_Local_Save_Level.
    for src in sorted(LEVEL_DIR.glob("*.gil")):
        dst = FIXTURES / src.name
        shutil.copy2(src, dst)
        copies[src.stem] = dst
    # New shape: <id>/<id>.gil. Only numeric directories are levels; the game also
    # keeps its own UpgradeBackup/ here, which is not one.
    for src in sorted(p for p in LEVEL_DIR.iterdir() if p.is_dir()):
        nested = src / f"{src.name}.gil"
        if not src.name.isdigit() or not nested.is_file():
            continue
        dst = FIXTURES / src.name / nested.name
        dst.parent.mkdir()
        shutil.copy2(nested, dst)
        copies[src.name] = dst
    return copies


# --------------------------------------------------------------------------- #
# protobuf walker
# --------------------------------------------------------------------------- #

def test_varint_roundtrip_for_known_values():
    for value in (0, 1, 127, 128, 300, 0x40000001, 100000001, 2 ** 63 - 1):
        encoded = write_varint(value)
        parsed = parse_fields(write_varint(1 << 3) + encoded)
        assert parsed[0].value == value


def test_fields_roundtrip_preserves_all_wire_types():
    original = [
        Field(1, 0, value=300),
        Field(2, 2, data=b"hello"),
        Field(3, 1, value=0xDEADBEEFCAFEBABE),
        Field(4, 5, value=0x12345678),
        Field(5, 2, data=b""),
    ]
    assert encode_fields(parse_fields(encode_fields(original))) == encode_fields(original)


def test_walker_rejects_truncated_field_rather_than_resynchronising():
    # field 1, wire type 2, claims 8 bytes but only 2 follow
    with pytest.raises(ContainerError):
        parse_fields(bytes([0x0A, 0x08, 0x41, 0x42]))


def test_walker_rejects_field_number_zero():
    with pytest.raises(ContainerError):
        parse_fields(bytes([0x00, 0x01]))


# --------------------------------------------------------------------------- #
# container framing
# --------------------------------------------------------------------------- #

def test_container_roundtrip(fixtures):
    blob = fixtures["profile"].read_bytes()
    assert encode_container(decode_container(blob)) == blob


def test_container_rejects_a_flipped_magic(fixtures):
    blob = bytearray(fixtures["profile"].read_bytes())
    struct.pack_into(">I", blob, 8, 0x999)
    with pytest.raises(ContainerError, match="magic"):
        decode_container(bytes(blob))


def test_container_rejects_a_wrong_declared_length(fixtures):
    blob = bytearray(fixtures["profile"].read_bytes())
    struct.pack_into(">I", blob, 0, len(blob))
    with pytest.raises(ContainerError, match="declared length"):
        decode_container(bytes(blob))


def test_container_rejects_truncation(fixtures):
    blob = fixtures["profile"].read_bytes()
    with pytest.raises(ContainerError):
        decode_container(blob[:-1])


def test_trailer_and_magic_are_what_the_header_claims(fixtures):
    for path in fixtures.values():
        container = decode_container(path.read_bytes())
        assert container.magic == MAGIC
        assert container.trailer == TRAILER
        assert container.version == VERSION
        assert container.subtype == (1 if path.suffix == ".gip" else 2)


# --------------------------------------------------------------------------- #
# the load-bearing property
# --------------------------------------------------------------------------- #

def test_roundtrip_is_byte_identical(fixtures):
    """Decode -> re-encode must return the original bytes for every real file."""
    checked = 0
    for name, path in fixtures.items():
        blob = path.read_bytes()
        assert encode_container(decode_container(blob)) == blob, f"container framing drifted for {name}"
        payload = decode_container(blob).payload
        assert encode_fields(parse_fields(payload)) == payload, f"payload fields drifted for {name}"
        checked += 1
    # Every file in the fixture, whatever the live save currently holds.
    assert checked == len(fixtures) >= 5, f"expected the profile and its levels, saw {checked}"


def test_high_level_roundtrip_is_byte_identical(fixtures):
    """The schema layer must be as lossless as the raw walker."""
    profile_path = fixtures["profile"]
    profile = parse_profile(decode_container(profile_path.read_bytes()).payload)
    assert build_profile(profile) == decode_container(profile_path.read_bytes()).payload

    for path in fixtures.values():
        if path.name == PROFILE_SRC.name:
            continue
        assert build_level(read_level(path)) == decode_container(path.read_bytes()).payload


# --------------------------------------------------------------------------- #
# the observed schema
# --------------------------------------------------------------------------- #

def level_files(fixtures) -> list[Path]:
    return sorted(p for p in fixtures.values() if p.suffix == ".gil")


def test_level_id_matches_its_filename(fixtures):
    for path in level_files(fixtures):
        assert read_level(path).level_id == int(path.stem)


def test_level_ids_are_the_documented_base_plus_n(fixtures):
    ids = [read_level(p).level_id for p in level_files(fixtures)]
    assert ids == sorted(ids), "level ids increase with the file names"
    assert all(i > 0x40000000 for i in ids), "every level id sits above the 0x40000000 base"
    assert ids[:4] == [0x40000001, 0x40000002, 0x40000003, 0x40000004]


def test_level_names_decode_as_the_editor_shows_them(fixtures):
    """The four live names as of 2026-09-18. Spelled out rather than pattern-matched:
    a wrong decode that still 'looks like a name' is the failure mode to catch."""
    names = {read_level(p).level_id: read_level(p).name for p in level_files(fixtures)}
    assert {k: names[k] for k in (0x40000001, 0x40000002, 0x40000003, 0x40000004)} == {
        0x40000001: "自定义页签_1_存档",
        0x40000002: "自定义页签_2_存档",
        0x40000003: "自定义页签_2_存档_1",
        0x40000004: "自定义页签_1_存档_1",
    }, "the four original levels decode to the names the editor shows"


def test_creator_uid_is_the_directory_the_file_lives_in(fixtures):
    for path in level_files(fixtures):
        assert read_level(path).creator_uid == 100000001


def test_timestamps_are_plausible_unix_seconds(fixtures):
    # 2024-01-01 .. 2030-01-01; a field that decoded wrongly would not land here.
    for path in level_files(fixtures):
        stamp = read_level(path).timestamp
        assert stamp is not None
        assert 1_704_067_200 < stamp < 1_893_456_000


def test_both_level_shapes_exist_and_only_one_carries_field_one(fixtures):
    """Neither shape may be normalised into the other -- they have different writers."""
    with_id, without_id = [], []
    for path in level_files(fixtures):
        payload = decode_container(path.read_bytes()).payload
        numbers = {f.number for f in parse_fields(payload)}
        (with_id if 1 in numbers else without_id).append(path.stem)
    assert with_id and without_id, "expected both shapes among the four live levels"
    assert sorted(with_id + without_id) == sorted(p.stem for p in level_files(fixtures))


def test_field_one_contradicting_the_filename_is_an_error(fixtures):
    path = next(p for p in level_files(fixtures) if 1 in {
        f.number for f in parse_fields(decode_container(p.read_bytes()).payload)
    })
    payload = decode_container(path.read_bytes()).payload
    with pytest.raises(ContainerError, match="field 1 says level"):
        parse_level(payload, level_id=int(path.stem) + 1)


def test_a_level_without_field_one_needs_a_filename_to_supply_the_id(fixtures):
    path = next(p for p in level_files(fixtures) if 1 not in {
        f.number for f in parse_fields(decode_container(p.read_bytes()).payload)
    })
    payload = decode_container(path.read_bytes()).payload
    with pytest.raises(ContainerError, match="file name must supply the id"):
        parse_level(payload)


def test_build_level_does_not_add_field_one_to_a_file_that_lacked_it(fixtures):
    for path in level_files(fixtures):
        payload = decode_container(path.read_bytes()).payload
        original_numbers = {f.number for f in parse_fields(payload)}
        rebuilt = build_level(read_level(path))
        assert {f.number for f in parse_fields(rebuilt)} == original_numbers


def test_profile_lists_every_level_file_present(fixtures):
    # The level id is the path stem in BOTH on-disk shapes: ``1073741834.gil`` ->
    # 1073741834, and ``1073741835/1073741835.gil`` -> 1073741835. Both shapes are
    # in the fixture (see the fixture docstring for the 2026-09-23 layout change),
    # so this asserts the profile lists every level, whatever its shape.
    profile = parse_profile(decode_container(fixtures["profile"].read_bytes()).payload)
    listed = sorted(ref.level_id for ref in profile.levels)
    on_disk = sorted(int(p.stem) for p in fixtures.values() if p.suffix == ".gil")
    assert listed == on_disk


def test_profile_root_name_is_readable(fixtures):
    profile = parse_profile(decode_container(fixtures["profile"].read_bytes()).payload)
    assert profile.root_name == "root"


def test_profile_tabs_are_parsed(fixtures):
    """The levels are filed under tabs; the flat list alone is not the whole story."""
    profile = parse_profile(decode_container(fixtures["profile"].read_bytes()).payload)
    by_name = {t.name: t for t in profile.tabs}
    assert "自定义页签_1" in by_name and "自定义页签_2" in by_name
    assert by_name["自定义页签_1"].kind == 3
    assert by_name["自定义页签_2"].kind == 4
    assert by_name["自定义页签_2"].members == [(1600, 0x40000002), (1600, 0x40000003)]
    # Subset, not equality: the live profile gains members whenever an archive is
    # created -- by this project, or by the user in the editor. The four original
    # memberships are what this test is about.
    members = by_name["自定义页签_1"].members
    assert (1600, 0x40000001) in members
    assert (1600, 0x40000004) in members


def test_every_flat_level_belongs_to_exactly_one_tab(fixtures):
    profile = parse_profile(decode_container(fixtures["profile"].read_bytes()).payload)
    filed = [level_id for tab in profile.tabs for _, level_id in tab.members]
    assert sorted(filed) == sorted(ref.level_id for ref in profile.levels)


def test_adding_a_level_files_it_under_a_tab_as_well(fixtures):
    payload = decode_container(fixtures["profile"].read_bytes()).payload
    profile = parse_profile(payload)
    before_tabs = len(profile.tabs)

    tab = add_level_to_profile(profile, 0x40000005, "demo", 1_789_000_000)
    assert tab.name == f"自定义页签_{before_tabs + 1}"
    assert len(profile.tabs) == before_tabs + 1
    assert (1600, 0x40000005) in tab.members

    reparsed = parse_profile(build_profile(profile))
    assert 0x40000005 in [r.level_id for r in reparsed.levels]
    assert 0x40000005 in [lid for t in reparsed.tabs for _, lid in t.members]
    assert len(reparsed.tabs) == before_tabs + 1


def test_adding_to_an_existing_tab_by_name_reuses_it(fixtures):
    payload = decode_container(fixtures["profile"].read_bytes()).payload
    profile = parse_profile(payload)
    before_tabs = len(profile.tabs)
    tab = add_level_to_profile(profile, 0x40000005, "demo", 1_789_000_000, tab_name="自定义页签_1")
    assert tab.name == "自定义页签_1"
    assert len(profile.tabs) == before_tabs, "an existing tab is reused, not duplicated"
    assert tab.members[-1] == (1600, 0x40000005)

    reparsed = parse_profile(build_profile(profile))
    assert len(reparsed.tabs) == before_tabs
    assert (1600, 0x40000005) in next(t for t in reparsed.tabs if t.name == "自定义页签_1").members


def test_a_new_tab_takes_the_next_kind(fixtures):
    payload = decode_container(fixtures["profile"].read_bytes()).payload
    profile = parse_profile(payload)
    highest = max(t.kind for t in profile.tabs)
    tab = add_level_to_profile(profile, 0x40000005, "demo", 1_789_000_000)
    assert tab.kind == highest + 1, "a new tab continues the kind sequence rather than reusing one"


# --------------------------------------------------------------------------- #
# editing
# --------------------------------------------------------------------------- #

def test_next_level_id_is_one_past_the_highest(fixtures):
    profile = parse_profile(decode_container(fixtures["profile"].read_bytes()).payload)
    assert next_level_id(profile) == max(r.level_id for r in profile.levels) + 1


def test_adding_a_level_entry_produces_a_reparseable_profile(fixtures):
    payload = decode_container(fixtures["profile"].read_bytes()).payload
    profile = parse_profile(payload)
    before = len(profile.levels)

    profile.levels.append(build_level_ref(0x40000005, "demo_关卡_1", 1_789_380_585))
    rebuilt = build_profile(profile)
    reparsed = parse_profile(rebuilt)
    assert len(reparsed.levels) == before + 1
    assert reparsed.levels[-1].level_id == 0x40000005
    assert reparsed.levels[-1].name == "demo_关卡_1"


def test_renaming_a_level_changes_only_the_name_bytes(fixtures):
    payload = decode_container(fixtures["profile"].read_bytes()).payload
    profile = parse_profile(payload)
    profile.levels[0].name = "renamed"
    profile.levels[0].raw = [
        f if f.number != 2 else Field(2, 2, data=b"renamed") for f in profile.levels[0].raw
    ]
    rebuilt = build_profile(profile)
    assert len(rebuilt) < len(payload) + 64
    assert parse_profile(rebuilt).levels[0].name == "renamed"
    assert parse_profile(rebuilt).levels[1].name == parse_profile(payload).levels[1].name


def test_level_container_encodes_with_the_level_subtype(fixtures):
    path = level_files(fixtures)[0]
    blob = encode_container(Container(subtype=2, payload=build_level(read_level(path))))
    assert decode_container(blob).subtype == 2
    assert encode_container(decode_container(path.read_bytes())) == path.read_bytes()
