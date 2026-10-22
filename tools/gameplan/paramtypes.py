"""Server parameter-type codes, and how each maps to a ``graph value`` slot.

The codes are observed in ``data/node-contracts`` (``ports[].serverParamType``).
The project has one historical inference table
(``data/node-contracts/shared/value-type-codes.json``) and it is explicitly
marked *inference*, so names here are marked **provisional** where the contract
does not state them outright.

The slot mapping is the part that matters for writing constants: ``author.py
graph value --slot`` accepts ``{auto,int,uint,enum,float,bool,string,vector3}``.
Vector server type 12 uses native editable-value storage 7; those domains must
not be interchanged. ``int``/``bool``/``float``/``string``/``enum`` also have
confident mappings; a
``configID`` (20) is a plain integer on the wire but the *slot* the adapter
expects for it is **not yet proven on the machine** — see ``CONFIG_ID_SLOT``.
"""

from __future__ import annotations

GENERIC = 0
ENTITY = 1
GUID = 2
INT = 3
BOOL = 4
FLOAT = 5
STRING = 6
VECTOR3 = 12
POSITION = VECTOR3  # Compatibility alias: positions/rotations use the same server vector type.
VECTOR3_STORAGE = 7  # Editable-value/widget code; NOT a serverParamType.
ENUM = 14
FACTION = 17
CONFIG_ID = 20
DICT = 27
SNAPSHOT = 28

#: Provisional names, per the observed codes.  ``unknown`` where the historical
#: table carried no name.
NAMES: dict[int, str] = {
    0: "generic",
    1: "entity",
    2: "guid",
    3: "int",
    4: "bool",
    5: "float",
    6: "string",
    7: "unknown-7",
    8: "unknown-8",
    10: "unknown-10",
    12: "vector3",
    14: "enum",
    17: "faction",
    20: "config-id",
    27: "dict",
    28: "snapshot",
}

#: ``serverParamType`` -> the ``--slot`` value to write a concrete constant.
#: ``None`` means the mapping is not established; callers must pass ``slot=``
#: explicitly and the run must be observed before trusting it.
#:
#: ``CONFIG_ID_SLOT`` is deliberately ``None``: a configID is written as some
#: integer slot, but which one the adapter wants for ``serverParamType == 20``
#: has not been exercised on the machine.  Treat it as an open question, not as
#: ``int`` by default.
CONFIG_ID_SLOT: str | None = None

SLOT_FOR_TYPE: dict[int, str | None] = {
    INT: "int",
    BOOL: "bool",
    FLOAT: "float",
    STRING: "string",
    ENUM: "enum",
    CONFIG_ID: CONFIG_ID_SLOT,
    ENTITY: None,
    GUID: None,
    VECTOR3: "vector3",
    7: None,
    FACTION: None,
    DICT: None,
    SNAPSHOT: None,
    GENERIC: None,
}


#: ``--slot`` values whose wire type is *unambiguous* — each is 1:1 with exactly
#: one code in :data:`SLOT_FOR_TYPE`.  A **concrete** pin of any other declared
#: type can therefore be rejected outright when one of these slots is written
#: into it (e.g. slot ``"string"`` into a config-id pin, code 20).
#:
#: ``int`` / ``uint`` / ``enum`` are **deliberately excluded**: they all encode
#: into the integer family, and it is exactly that family whose slot↔type
#: mapping is unproven (:data:`CONFIG_ID_SLOT` is ``None``).  Constraining them
#: here would fail-closed on the unproven-but-necessary ``slot="int"`` writes
#: every config-id constant needs, so they are left to the caller.
CONFIDENT_SLOT_TYPE: dict[str, int] = {
    "bool": BOOL,
    "float": FLOAT,
    "string": STRING,
    "vector3": VECTOR3,
}


#: The wire storage kinds of a dict (contract ``serverParamType 27``), OBSERVED live
#: 2026-10-12: a concrete-27 pin's value object reads kind **10003** and its kv-pair entry
#: kind **10007** (``.runtime/scratch/DICT-LIVE-STORAGEKIND-OBSERVED.md``).
#:
#: These are FACTS about the container, **not** a scalar slot: ``slot_for(DICT)`` stays
#: ``None``.  A dict is written through a container branch, exactly like ``List`` -- which
#: is likewise absent from this table and from ``SLOT_FOR_TYPE``, yet writable.
DICT_CONTAINER_STORAGE = 10003
DICT_ENTRY_STORAGE = 10007


def name_of(code: int) -> str:
    return NAMES.get(int(code), f"type-{code}")


def slot_for(code: int) -> str | None:
    """The ``--slot`` for a concrete constant of this type, or ``None``."""
    return SLOT_FOR_TYPE.get(int(code))
