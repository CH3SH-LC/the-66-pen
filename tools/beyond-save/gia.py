"""Decoder for a Miliastra ``.gia`` export -- the graph in a portable file.

What a ``.gia`` is
------------------
The editor's ``beyondExportService`` (``EditorAdapter.cs`` ``ExportResource``,
:914-950) writes one ``.gia`` per exported user resource. The reply carries
``path`` / ``replyPath`` / ``receiptFields``; the file lands under the caller's
``outputDirectory`` (this project uses ``.runtime/editor-bridge/exports/<scope>/``).

Framing
-------
A ``.gia`` is framed **exactly like a ``.gil`` local save**: the same
``gil_container`` container. That is not a guess -- :func:`gil_container.decode_container`
accepts every real ``.gia`` seen and re-encoding is byte-identical. The only new
thing is the subtype:

    u32be  total length  == 20 + inner length
    u32be  version       == 1
    u32be  magic         == 0x326
    u32be  subtype       == 3          (``.gil`` uses 1 = profile, 2 = level)
    u32be  inner length
    bytes  payload       a protobuf message
    u32be  trailer       == 0x679

Payload shapes seen in real files
---------------------------------
Every ``.gia`` seen is subtype 3, but the payload is *not* one shape. Which
resource was exported decides the body field inside the envelope ``field 1``:

  * ``field 13`` -> a **node graph** (this module's primary subject)
  * ``field 35`` -> a **client script** (``client-script-*.gia``)
  * no envelope -- top level is repeated ``field 1``, one per entity, i.e. an
    **entity/scene bundle** (``mvp/build/platformer_min.gia``)

Node graph, as far as it is *observed* (field numbers are evidence, not a vendor
schema -- every one below was read off a real file, and none is invented):

  envelope ``field 1``:
    - ``field 1``  resource header   ``field 2`` == 5 (constant);
                                     ``field 4`` == resource/graph id
    - ``field 3``  resource name (the string the editor shows)
    - ``field 5``  model kind (9 = project-owned user graph)
    - ``field 13`` graph body

  graph body (``envelope.field13 . field1 . field1``):
    - ``field 1``  header ``field 1`` == 10000, ``field 2`` == 20000,
                   ``field 3`` == 21001, ``field 5`` == the graph id again
    - ``field 2``  graph name (same string as the envelope's ``field 3``)
    - ``field 3``  **repeated, one per node** -- and nothing else. Across all 61
                   graph exports in this repo the body's child field numbers are
                   exactly ``{1, 2, 3}``: there is **no separate edge list**.

  node (a body ``field 3``):
    - ``field 1``  node index, 1-based, in insertion order
    - ``field 2``  kind record: ``field 1``/``field 2``/``field 3`` == the node
                   category (10001, 20000, 22000 for every node here) and
                   ``field 5`` == the node's definition id (the small integer the
                   bridge passes to ``add-node``: 71, 73, 14, 2, 252, 1, ...)
    - ``field 3``  a byte-identical duplicate of ``field 2``
    - ``field 4``  repeated: the node's ports (see below)
    - ``field 5``  node editor x, as a **float32** (wire type 5)
    - ``field 6``  node editor y, as a **float32**
                   proto3 omits zeros, so a node at x == 0 has no ``field 5``.

The ``(x, y)`` reading is checkable, not assumed: the six nodes of
``MW_Platform_Calibration_20260916`` decode to
``(0,0) (0,300) (350,250) (700,0) (1050,0) (1450,0)`` and their kinds to
``71 73 14 2 252 1`` -- exactly the ``Add(kind, x, y)`` calls in
``EditorAdapter.cs`` :773.

What this module does NOT establish
-----------------------------------
**Edges.** The graph body carries a header, a name, and the node list -- no
fourth thing -- in every one of the 61 real graph exports (verified by scanning
all of them; see ``tools/beyond-save/test_gia.py``). So there is no separate edge
list to read. Any link information must be inside a node's repeated ``field 4``
(the port records), and that encoding is *not* decoded here: this module exposes
the port records as raw ``Field`` objects and makes **no claim** about which port
connects to which node. Naming those sub-fields would be inventing a schema. The
node count, kinds and positions are established; the edges are not.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gil_container import (  # noqa: E402
    Field,
    WIRE_32BIT,
    WIRE_LENGTH,
    decode_container,
    parse_fields,
)

# The one new constant: a ``.gia`` is a subtype-3 container.
GIA_SUBTYPE = 3

# Payload body field numbers, per resource kind.
GRAPH_BODY_FIELD = 13
CLIENT_SCRIPT_BODY_FIELD = 35

# Graph-body child field numbers.
BODY_HEADER_FIELD = 1
BODY_NAME_FIELD = 2
BODY_NODE_FIELD = 3

# Node child field numbers.
NODE_INDEX_FIELD = 1
NODE_KIND_FIELD = 2
NODE_KIND_MIRROR_FIELD = 3
NODE_PORT_FIELD = 4
NODE_X_FIELD = 5
NODE_Y_FIELD = 6

# The kind record's own field numbers.
KIND_CATEGORY_FIELDS = (1, 2, 3)
KIND_DEFINITION_FIELD = 5

# Envelope child field numbers.
ENVELOPE_HEADER_FIELD = 1
ENVELOPE_NAME_FIELD = 3
ENVELOPE_MODEL_KIND_FIELD = 5
ENVELOPE_RESOURCE_ID_FIELD = 4

# Top-level field numbers.
TOP_ENVELOPE_FIELD = 1
TOP_RECEIPT_FIELD = 3
TOP_VERSION_FIELD = 5


class GiaError(ValueError):
    """The bytes are a container but not the ``.gia`` shape asked for."""


def _first(fields: list[Field], number: int) -> Field | None:
    for f in fields:
        if f.number == number:
            return f
    return None


def _all(fields: list[Field], number: int) -> list[Field]:
    return [f for f in fields if f.number == number]


def _text(f: Field | None) -> str | None:
    if f is None or f.wire_type != WIRE_LENGTH or f.data is None:
        return None
    try:
        return f.data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _float32(f: Field | None) -> float | None:
    """A wire-type-5 field read back as a float32. ``None`` == absent (proto3 zero)."""
    if f is None or f.wire_type != WIRE_32BIT or f.value is None:
        return None
    return struct.unpack("<f", struct.pack("<I", f.value & 0xFFFFFFFF))[0]


@dataclass
class GiaNode:
    """One node of an exported graph."""
    index: int
    kind: int
    category: tuple[int, ...]
    x: float | None
    y: float | None
    fields: list[Field] = field(default_factory=list)

    @property
    def ports(self) -> list[Field]:
        """The node's repeated ``field 4`` records, raw and uninterpreted.

        This module does not decode a link encoding, so these are handed back
        exactly as parsed. See the module docstring, "What this module does NOT
        establish".
        """
        return _all(self.fields, NODE_PORT_FIELD)


@dataclass
class GiaGraph:
    """A decoded node-graph export."""
    resource_id: int
    name: str
    model_kind: int
    nodes: list[GiaNode]
    body: list[Field] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def kinds(self) -> list[int]:
        return [n.kind for n in self.nodes]


@dataclass
class GiaEntity:
    """One entry of an entity/scene ``.gia``."""
    index: int
    entity_id: int | None
    name: str | None
    kind: int | None
    fields: list[Field] = field(default_factory=list)


@dataclass
class GiaFile:
    """A decoded ``.gia``, whatever resource it holds.

    ``kind`` is one of ``"graph"``, ``"client-script"``, ``"entities"`` or
    ``"unknown"``. ``graph`` is set only for ``"graph"``.
    """
    kind: str
    subtype: int
    payload: bytes
    fields: list[Field] = field(default_factory=list)
    resource_id: int | None = None
    name: str | None = None
    model_kind: int | None = None
    version: str | None = None
    receipt: str | None = None
    graph: GiaGraph | None = None
    entities: list[GiaEntity] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return self.graph.node_count if self.graph is not None else 0


def _parse_graph(envelope: Field, body_field: Field) -> GiaGraph:
    header = _first(envelope.children(), ENVELOPE_HEADER_FIELD)
    resource_id = None
    if header is not None and header.wire_type == WIRE_LENGTH:
        id_field = _first(header.children(), ENVELOPE_RESOURCE_ID_FIELD)
        if id_field is not None:
            resource_id = id_field.value
    name = _text(_first(envelope.children(), ENVELOPE_NAME_FIELD))
    model_kind_field = _first(envelope.children(), ENVELOPE_MODEL_KIND_FIELD)
    model_kind = model_kind_field.value if model_kind_field is not None else None

    # body_field -> field 1 -> field 1 -> [header, name, node...]
    outer = body_field.children()
    if len(outer) != 1 or outer[0].number != 1:
        raise GiaError("graph body is not wrapped as field13.field1.field1")
    inner = outer[0].children()
    if len(inner) != 1 or inner[0].number != 1:
        raise GiaError("graph body is not wrapped as field13.field1.field1")
    body = inner[0].children()

    child_numbers = {f.number for f in body}
    if not child_numbers <= {BODY_HEADER_FIELD, BODY_NAME_FIELD, BODY_NODE_FIELD}:
        raise GiaError(f"unexpected graph-body field numbers {sorted(child_numbers)}")

    nodes: list[GiaNode] = []
    for raw in _all(body, BODY_NODE_FIELD):
        kids = raw.children()
        idx_field = _first(kids, NODE_INDEX_FIELD)
        kind_field = _first(kids, NODE_KIND_FIELD)
        if idx_field is None or kind_field is None:
            raise GiaError("a node lacks its field 1 (index) or field 2 (kind)")
        kind_kids = kind_field.children()
        category = tuple(
            _first(kind_kids, n).value
            for n in KIND_CATEGORY_FIELDS
            if _first(kind_kids, n) is not None
        )
        definition = _first(kind_kids, KIND_DEFINITION_FIELD)
        nodes.append(GiaNode(
            index=idx_field.value or 0,
            kind=definition.value if definition is not None else -1,
            category=category,
            x=_float32(_first(kids, NODE_X_FIELD)),
            y=_float32(_first(kids, NODE_Y_FIELD)),
            fields=kids,
        ))

    return GiaGraph(
        resource_id=resource_id if resource_id is not None else -1,
        name=name if name is not None else "",
        model_kind=model_kind if model_kind is not None else -1,
        nodes=nodes,
        body=body,
    )


def _parse_entities(top: list[Field]) -> list[GiaEntity]:
    entities: list[GiaEntity] = []
    for i, entry in enumerate(top):
        kids = entry.children()
        header = _first(kids, 1)
        entity_id = None
        if header is not None and header.wire_type == WIRE_LENGTH:
            id_field = _first(header.children(), 4)
            if id_field is not None:
                entity_id = id_field.value
        kind_field = _first(kids, 5)
        entities.append(GiaEntity(
            index=i,
            entity_id=entity_id,
            name=_text(_first(kids, 3)),
            kind=kind_field.value if kind_field is not None else None,
            fields=kids,
        ))
    return entities


def decode_gia(blob: bytes) -> GiaFile:
    """Decode a ``.gia`` export.

    Raises :class:`gil_container.ContainerError` if the framing is wrong and
    :class:`GiaError` if the payload is a``.gia`` the module cannot classify.
    """
    container = decode_container(blob)
    if container.subtype != GIA_SUBTYPE:
        raise GiaError(
            f"subtype {container.subtype} is not a .gia "
            f"(expected {GIA_SUBTYPE}); a .gil level/profile is not a resource export"
        )
    payload = container.payload
    fields = parse_fields(payload)

    version = _text(_first(fields, TOP_VERSION_FIELD))
    receipt = _text(_first(fields, TOP_RECEIPT_FIELD))

    envelopes = _all(fields, TOP_ENVELOPE_FIELD)

    if len(envelopes) == 1:
        envelope = envelopes[0]
        body_field = _first(envelope.children(), GRAPH_BODY_FIELD)
        if body_field is not None:
            graph = _parse_graph(envelope, body_field)
            return GiaFile(
                kind="graph", subtype=container.subtype, payload=payload,
                fields=fields, resource_id=graph.resource_id, name=graph.name,
                model_kind=graph.model_kind, version=version, receipt=receipt,
                graph=graph,
            )
        if _first(envelope.children(), CLIENT_SCRIPT_BODY_FIELD) is not None:
            return GiaFile(
                kind="client-script", subtype=container.subtype, payload=payload,
                fields=fields, name=_text(_first(envelope.children(), ENVELOPE_NAME_FIELD)),
                version=version, receipt=receipt,
            )
        return GiaFile(
            kind="unknown", subtype=container.subtype, payload=payload,
            fields=fields, version=version, receipt=receipt,
        )

    if envelopes and all(f.number == TOP_ENVELOPE_FIELD for f in fields):
        return GiaFile(
            kind="entities", subtype=container.subtype, payload=payload,
            fields=fields, entities=_parse_entities(envelopes),
        )

    raise GiaError(
        "not a recognizable .gia: top-level fields "
        f"{sorted({f.number for f in fields})}"
    )


def read_gia(path: Path | str) -> GiaFile:
    return decode_gia(Path(path).read_bytes())


def read_graph(path: Path | str) -> GiaGraph:
    """Decode a ``.gia`` and return its graph, or raise :class:`GiaError`.

    The named refusal matters: an entity bundle or a client script is a valid
    ``.gia`` and must not be silently mistaken for a graph.
    """
    gia = read_gia(path)
    if gia.graph is None:
        raise GiaError(f"{Path(path).name} is a {gia.kind} export, not a node graph")
    return gia.graph
