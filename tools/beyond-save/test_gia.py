"""Tests for the ``.gia`` export decoder.

Every test is anchored on a real file. The guaranteed one is
``mvp/build/platformer_min.gia`` -- it ships in the repo and is an **entity**
export. The graph exports live under ``.runtime/editor-bridge/exports/`` and are
skipped if that directory has been pruned.

Two load-bearing claims are tested here:

  * the framing of a ``.gia`` is *identical* to the ``.gil`` container, proven by
    decoding real exports with ``gil_container.decode_container`` and by
    re-encoding them byte-for-byte; and
  * a graph export carries a **header, a name and a node list, and nothing else**
    -- so there is no edge list to decode. That is asserted across *all* real
    graph exports, not one, because it is a negative and negatives need coverage.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gia  # noqa: E402
from gil_container import (  # noqa: E402
    MAGIC,
    TRAILER,
    VERSION,
    Container,
    ContainerError,
    Field,
    WIRE_LENGTH,
    decode_container,
    encode_container,
    encode_fields,
    parse_fields,
)

PROJECT = Path(__file__).resolve().parents[2]
ENTITY_GIA = PROJECT / "mvp" / "build" / "platformer_min.gia"
EXPORTS = PROJECT / ".runtime" / "editor-bridge" / "exports"

CALIBRATION_NAME = "MW_Platform_Calibration_20260916"
FARM_DEMO_NAME = "MW_API_FARM_DEMO"
TILED_ROUTE_NAME = "MW_Route_Tiled_20260916"


def export_files() -> list[Path]:
    return sorted(EXPORTS.glob("*/*.gia")) if EXPORTS.exists() else []


def _kind_safe(path: Path) -> str | None:
    try:
        return gia.read_gia(path).kind
    except (ContainerError, gia.GiaError):
        return None


def export_named(name: str) -> Path | None:
    for path in export_files():
        try:
            f = gia.read_gia(path)
        except (ContainerError, gia.GiaError):
            continue
        if f.name == name:
            return path
    return None


GRAPH_EXPORTS = [p for p in export_files() if _kind_safe(p) == "graph"]


# --------------------------------------------------------------------------- #
# framing: a .gia is the .gil container, subtype 3
# --------------------------------------------------------------------------- #

def test_the_entity_export_is_present_to_anchor_the_suite():
    assert ENTITY_GIA.exists(), "mvp/build/platformer_min.gia ships with the repo"
    blob = ENTITY_GIA.read_bytes()
    assert decode_container(blob).subtype == gia.GIA_SUBTYPE


@pytest.mark.skipif(not EXPORTS.exists(), reason="no export directory on this machine")
def test_real_gia_files_decode_with_the_gil_container_framing():
    """``gil_container.decode_container`` -- the *save* container -- accepts every .gia."""
    files = export_files()
    assert files, "expected at least one exported .gia"
    for path in files:
        container = decode_container(path.read_bytes())
        assert container.subtype == gia.GIA_SUBTYPE, path
        assert container.magic == MAGIC
        assert container.trailer == TRAILER
        assert container.version == VERSION


@pytest.mark.skipif(not EXPORTS.exists(), reason="no export directory on this machine")
def test_gia_container_and_payload_round_trip_is_byte_identical():
    for path in export_files():
        blob = path.read_bytes()
        assert encode_container(decode_container(blob)) == blob, path
        payload = decode_container(blob).payload
        assert encode_fields(parse_fields(payload)) == payload, path


def test_decode_rejects_bytes_that_are_not_a_container():
    with pytest.raises(ContainerError):
        gia.decode_gia(b"not a gia at all")


def test_decode_rejects_a_flipped_magic():
    blob = bytearray(ENTITY_GIA.read_bytes())
    blob[8:12] = (0x999).to_bytes(4, "big")
    with pytest.raises(ContainerError, match="magic"):
        gia.decode_gia(bytes(blob))


def test_decode_rejects_a_truncated_container():
    blob = ENTITY_GIA.read_bytes()
    with pytest.raises(ContainerError):
        gia.decode_gia(blob[:-1])


def test_decode_rejects_a_gil_subtype():
    """A ``.gil`` level is subtype 2; it must not be read as a resource export."""
    real = decode_container(ENTITY_GIA.read_bytes())
    as_level = encode_container(Container(subtype=2, payload=real.payload))
    with pytest.raises(gia.GiaError, match="subtype 2"):
        gia.decode_gia(as_level)


# --------------------------------------------------------------------------- #
# entity-form exports
# --------------------------------------------------------------------------- #

def test_the_platformer_build_is_an_entity_export_not_a_graph():
    f = gia.read_gia(ENTITY_GIA)
    assert f.kind == "entities"
    assert f.graph is None
    assert len(f.entities) == 6


def test_entity_ids_and_names_match_the_manifest():
    f = gia.read_gia(ENTITY_GIA)
    assert [e.entity_id for e in f.entities] == [
        1078000000, 1078000001, 1078000002, 1078000003, 1078000004, 1078000005,
    ]
    names = [e.name for e in f.entities]
    assert names[0] == "MVP_StartPad"
    assert names[-1] == "MVP_GoalPad"
    assert all(n and n.startswith("MVP_") for n in names)


def test_read_graph_refuses_an_entity_export():
    with pytest.raises(gia.GiaError, match="not a node graph"):
        gia.read_graph(ENTITY_GIA)


# --------------------------------------------------------------------------- #
# the node graph
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_graph_node_count_is_visible():
    """The whole point: an offline file tells you how many nodes were built."""
    path = export_named(FARM_DEMO_NAME)
    assert path is not None, f"an export of {FARM_DEMO_NAME} exists"
    graph = gia.read_graph(path)
    assert graph.node_count == 15
    assert graph.resource_id == 1073741829
    assert graph.name == FARM_DEMO_NAME
    assert graph.model_kind == 9


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_every_export_of_a_graph_agrees_on_its_node_count():
    """Level ids are per-level (the graph id moves with the project), so a graph
    can be exported from several levels -- but its node count does not drift."""
    for name, expected in ((TILED_ROUTE_NAME, 39), (FARM_DEMO_NAME, 15)):
        counts = set()
        for path in export_files():
            f = gia.read_gia(path)
            if f.graph is not None and f.name == name:
                counts.add(f.graph.node_count)
        assert counts == {expected}, f"{name} exported with counts {counts}"


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_calibration_graph_decodes_to_the_kinds_and_positions_it_was_built_from():
    """``EditorAdapter.cs`` builds it with Add(71,0,0) Add(73,0,300) Add(14,350,250)
    Add(2,700,0) Add(252,1050,0) Add(1,1450,0). The export reproduces both the
    definition ids and the layout."""
    path = export_named(CALIBRATION_NAME)
    assert path is not None
    graph = gia.read_graph(path)
    assert graph.kinds == [71, 73, 14, 2, 252, 1]
    assert [(n.x, n.y) for n in graph.nodes] == [
        (None, None),        # (0, 0)   -- proto3 omits the zero-valued float
        (None, 300.0),       # (0, 300)
        (350.0, 250.0),      # (350, 250)
        (700.0, None),       # (700, 0)
        (1050.0, None),      # (1050, 0)
        (1450.0, None),      # (1450, 0)
    ]


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_node_indices_are_one_based_and_consecutive():
    for path in GRAPH_EXPORTS:
        graph = gia.read_graph(path)
        assert [n.index for n in graph.nodes] == list(range(1, graph.node_count + 1)), path


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_every_node_carries_the_same_graph_category():
    for path in GRAPH_EXPORTS:
        graph = gia.read_graph(path)
        for node in graph.nodes:
            assert node.category == (10001, 20000, 22000), (path, node.index)


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_a_graph_body_has_no_edge_list():
    """The negative that shapes the whole task.

    Across every real graph export, the body (``field13 . field1 . field1``) has
    only three kinds of child: ``field 1`` (header), ``field 2`` (name) and the
    repeated ``field 3`` nodes. There is no fourth field, so no edge list exists
    to read -- links, if serialized at all, are inside a node's field-4 ports.
    """
    checked = 0
    for path in GRAPH_EXPORTS:
        graph = gia.read_graph(path)
        assert {f.number for f in graph.body} <= {1, 2, 3}, path
        checked += 1
    assert checked == len(GRAPH_EXPORTS) >= 1


@pytest.mark.skipif(not GRAPH_EXPORTS, reason="no graph export on this machine")
def test_ports_are_handed_back_raw_and_uninterpreted():
    """We do not decode the port encoding. The nodes that have ports expose them
    as ``field 4`` records and no node-to-node claim is made about them."""
    path = export_named(CALIBRATION_NAME)
    graph = gia.read_graph(path)
    spawn = next(n for n in graph.nodes if n.kind == 252)
    assert spawn.ports, "the spawn node has port records"
    assert all(p.number == 4 and p.wire_type == WIRE_LENGTH for p in spawn.ports)
    # Nothing on a node exposes a decoded edge -- only the raw port fields.
    assert not hasattr(spawn, "edges")
    assert not hasattr(graph, "edges")


@pytest.mark.skipif(not export_files(), reason="no export on this machine")
def test_read_graph_refuses_a_client_script_export():
    scripts = [p for p in export_files() if _kind_safe(p) == "client-script"]
    if not scripts:
        pytest.skip("no client-script export on this machine")
    with pytest.raises(gia.GiaError, match="not a node graph"):
        gia.read_graph(scripts[0])


# --------------------------------------------------------------------------- #
# synthetic refusal paths for the graph schema
# --------------------------------------------------------------------------- #

def _wrap(payload: bytes) -> bytes:
    return encode_container(Container(subtype=gia.GIA_SUBTYPE, payload=payload))


def test_a_body_that_is_not_double_wrapped_is_a_named_error():
    # envelope.field13 -> [field 2]  (missing the two field-1 wrappers)
    payload = encode_fields([
        Field(1, WIRE_LENGTH, data=encode_fields([
            Field(13, WIRE_LENGTH, data=encode_fields([Field(2, WIRE_LENGTH, data=b"x")])),
        ])),
    ])
    with pytest.raises(gia.GiaError, match="wrapped"):
        gia.decode_gia(_wrap(payload))


def test_a_body_with_an_unexpected_field_number_is_a_named_error():
    body = encode_fields([Field(1, WIRE_LENGTH, data=b"\x08\x01"), Field(9, WIRE_LENGTH, data=b"x")])
    # envelope.field13 -> field1 -> field1 -> body  (the real double wrapping)
    payload = encode_fields([
        Field(1, WIRE_LENGTH, data=encode_fields([
            Field(13, WIRE_LENGTH, data=encode_fields([
                Field(1, WIRE_LENGTH, data=encode_fields([
                    Field(1, WIRE_LENGTH, data=body),
                ])),
            ])),
        ])),
    ])
    with pytest.raises(gia.GiaError, match="unexpected graph-body field"):
        gia.decode_gia(_wrap(payload))


def test_a_payload_with_no_envelope_is_a_named_error():
    payload = encode_fields([Field(2, WIRE_LENGTH, data=b"a"), Field(3, WIRE_LENGTH, data=b"b")])
    with pytest.raises(gia.GiaError, match="not a recognizable"):
        gia.decode_gia(_wrap(payload))


def test_a_single_envelope_without_a_body_is_unknown_not_an_error():
    payload = encode_fields([
        Field(1, WIRE_LENGTH, data=encode_fields([Field(3, WIRE_LENGTH, data=b"name")])),
    ])
    assert gia.decode_gia(_wrap(payload)).kind == "unknown"
