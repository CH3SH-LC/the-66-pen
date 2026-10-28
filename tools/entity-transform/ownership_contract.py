"""Portable, saved-file-bound ownership selection. No process or game calls."""
from pathlib import Path
from contract import read, sha, require
import build as b

PROTECTED = set(range(1073741835, 1073741845))


def validate_selection(document, level, digest, hosts, children=(), pairs=(), operation=None):
    require(type(document) is dict and document.get("schemaVersion") == 1 and
            document.get("kind") == "miliastra-ownership-v1", "OWNERSHIP_SCHEMA")
    require(type(level) is int and 0 < level <= 0xffffffff and level not in PROTECTED,
            "OWNERSHIP_PROTECTED_OR_INVALID_LEVEL")
    require(document.get("levelId") == level and document.get("saveSha256") == digest,
            "OWNERSHIP_SAVE_OR_LEVEL_DRIFT")
    for field in ("entityIds", "accessoryIds"):
        values = document.get(field)
        require(type(values) is list and all(type(x) is int and 0 < x <= 0xffffffff for x in values)
                and len(values) == len(set(values)), "OWNERSHIP_IDS")
    require(set(hosts) <= set(document["entityIds"]) and
            set(children) <= set(document["accessoryIds"]), "OWNERSHIP_SELECTION")
    expected = document.get("operations", {}).get(operation, [])
    require(type(expected) is list and all(type(p) is dict for p in expected), "OWNERSHIP_OPERATIONS")
    require(all(p in expected for p in pairs), "OWNERSHIP_PAIR_NOT_SELECTED")


def check(path, level, save, hosts, children=(), pairs=(), operation=None):
    path, save = Path(path).resolve(), Path(save).resolve()
    require(path.is_file() and path.stat().st_size <= 4*1024*1024, "OWNERSHIP_FILE")
    # Independently verify the embedded identity. A renamed save is not a new level.
    import sys
    sys.path.insert(0, str(b.ROOT / "tools/beyond-save"))
    from gil_container import decode_container, parse_level
    raw = save.read_bytes()
    require(len(raw) <= 256*1024*1024, "OWNERSHIP_SAVE_SIZE")
    container = decode_container(raw)
    require(container.subtype == 2, "OWNERSHIP_LEVEL_SAVE_ONLY")
    from gil_container import parse_fields, LEVEL_FIELD_ID
    declared = next((f.value for f in parse_fields(container.payload) if f.number == LEVEL_FIELD_ID), None)
    if declared is None:
        import re
        match = re.fullmatch(r"(?:save)?(\d+)\.gil", save.name, re.I)
        require(match is not None and int(match[1]) == level, "OWNERSHIP_FORMAL_FILENAME")
    parsed = parse_level(container.payload, level)
    require(parsed.level_id == level, "OWNERSHIP_EMBEDDED_LEVEL")
    digest = sha(save)
    validate_selection(read(path), level, digest, hosts, children, pairs, operation)
    require(save.read_bytes() == raw, "OWNERSHIP_SAVE_CHANGED")
    return digest
