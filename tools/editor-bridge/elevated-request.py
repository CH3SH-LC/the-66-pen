#!/usr/bin/env python3
"""Send a request to the resident elevated runner and wait for its reply.

The runner (elevated-runner.ps1) is the only elevated component; this script runs
unprivileged and merely drops a request file into its queue directory. It can only
ask for the fixed request kinds the runner accepts, and it never runs anything itself.

    python elevated-request.py status
    python elevated-request.py load --target-pid 39372
    python elevated-request.py call --op verify-interfaces [--run-id GUID]
    python elevated-request.py call --op inspect-entity-components --entity-id 1077936129 [--run-id GUID]
    python elevated-request.py call --op add-entity-component --component-action add --component-probe-id <32hex> --entity-id N --component-id 704 [--run-id GUID]
    python elevated-request.py call --op delete-instruction-graph --ids 1073741830 --entity-id 7 [--run-id GUID]
    python elevated-request.py call --op reflection-probe --name-contains Component [--member-contains Add] [--run-id GUID]
    python elevated-request.py call --op node-definitions --ids 1 71 [--run-id GUID]
    python elevated-request.py fs --op list --path "C:\\Games\\Genshin Impact Game"
    python elevated-request.py fs --op read --path <file> --out local-copy.bin
    python elevated-request.py fs --op write --path <file> --data-file payload.bin

Exits non-zero if the runner reports an error, does not answer in time, or replies
with anything other than an explicit success: ``load`` needs ``accepted`` to be
literal ``true`` and ``call`` needs ``ok`` to be literal ``true``. Absent, false,
string ("true"/"false") and non-boolean values are all failures, so a reply whose
shape changed stops the caller instead of passing as success. ``fs`` operations
carry no ``ok`` field in elevated-fs-ops.ps1, where failures arrive as errors
instead; if a future reply does carry ``ok``, it is obeyed the same way.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import math
import re
import struct
import stat
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / ".runtime/editor-bridge/elevated-queue"
RUNS = ROOT / ".runtime/editor-bridge/runs"


def is_literal_true(value) -> bool:
    """JSON ``true`` and nothing else.

    ``"false"``, ``"true"``, ``0``, ``1``, ``null`` and an absent field are all
    failures: reading a changed reply as success is how a caller ends up acting
    on a request the runner or bridge did not accept.
    """
    return value is True


def reported_not_ok(payload) -> bool:
    """True when a reply carries an ``ok`` field that is not literal ``true``.

    The current ``fs`` schema (elevated-fs-ops.ps1) has no ``ok`` field at all --
    it signals failure by throwing, which the runner writes to ``<id>.error.txt``
    and :func:`send` raises on. So absence is not a failure here; only an
    explicit non-true ``ok`` is.
    """
    return isinstance(payload, dict) and "ok" in payload and not is_literal_true(payload["ok"])


def _request_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("QUEUE_REQUEST_ID_INVALID")
    return value


def poll_request(request_id: str, timeout: float = 300.0) -> dict:
    """Poll one persisted queue identity; never enqueue or retry its operation."""
    rid = _request_id(request_id)
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 1800:
        raise ValueError("QUEUE_TIMEOUT_INVALID")
    resp, err = QUEUE / f"{rid}.response.json", QUEUE / f"{rid}.error.txt"
    deadline = time.monotonic() + timeout
    while True:
        if resp.exists():
            try:
                value = json.loads(resp.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                value = None  # A partially written response is not a terminal failure.
            if isinstance(value, dict):
                return value
            if value is not None:
                return {"ok": False, "error": "QUEUE_RESPONSE_NOT_OBJECT", "requestId": rid,
                        "outcomeUncertain": True, "retryAttempted": False}
        if err.exists():
            return {"ok": False, "error": err.read_text(encoding="utf-8-sig").strip(),
                    "requestId": rid, "outcomeUncertain": True, "retryAttempted": False}
        if time.monotonic() >= deadline:
            return {"ok": False, "pending": True, "outcomeUncertain": True,
                    "requestId": rid, "queue": str(QUEUE), "retryAttempted": False}
        time.sleep(min(0.3, max(0, deadline - time.monotonic())))


def send(payload: dict, timeout: float = 300.0, request_id: str | None = None) -> dict:
    """Enqueue once; an explicitly reused ID only polls its original operation."""
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 <= timeout <= 1800:
        raise ValueError("QUEUE_TIMEOUT_INVALID")
    rid = _request_id(request_id) if request_id is not None else uuid.uuid4().hex
    QUEUE.mkdir(parents=True, exist_ok=True)
    claim = QUEUE / f"{rid}.submission.json"
    # A permanent exclusive submission marker survives the runner deleting a request.
    # Reusing an ID with different contents is an error, never a second dispatch.
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    try:
        with claim.open("x", encoding="utf-8") as stream:
            stream.write(canonical)
    except FileExistsError:
        if claim.read_text(encoding="utf-8") != canonical:
            raise ValueError("QUEUE_REQUEST_ID_PAYLOAD_MISMATCH")
    else:
        req = QUEUE / f"{rid}.request.json"
        pending = QUEUE / f"{rid}.request.pending"
        if any((QUEUE / f"{rid}.{suffix}").exists() for suffix in ("request.json", "response.json", "error.txt")):
            raise ValueError("QUEUE_REQUEST_ID_ALREADY_EXISTS")
        with pending.open("x", encoding="utf-8") as stream:
            stream.write(canonical)
        pending.rename(req)  # Windows rename is atomic and refuses an existing file.
    result = poll_request(rid, timeout)
    if request_id is None and result.get("pending") is True:
        raise SystemExit("timeout waiting for the elevated runner; outcome pending; poll request " + rid)
    if request_id is None and (QUEUE / f"{rid}.error.txt").exists():
        raise SystemExit("runner error: " + str(result.get("error")))
    return result


def latest_run_id() -> str | None:
    """The newest run whose lease is still open.

    Not simply "the newest directory": a run writes lease-closed.json when its
    lease ends, which bumps the directory mtime and promotes a dead run to the
    front of an mtime sort. That is how a call ends up talking to a listener that
    shut down five minutes ago and fails with SCOPE_EXPIRED. Filter on the lease
    deadline, then pick the newest survivor.
    """
    if not RUNS.exists():
        return None
    now = datetime.now(timezone.utc)
    live = []
    for d in RUNS.iterdir():
        settings = d / "bridge-settings.json"
        if not settings.exists():
            continue
        try:
            data = json.loads(settings.read_text(encoding="utf-8-sig"))
            expires = datetime.fromisoformat(data["expiresUtc"])
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        if expires > now:
            live.append((expires, d.name))
    if not live:
        return None
    return max(live)[1]


#: The bounded instruction-graph delete family (InstructionGraphDelete.cs). Its adapter
#: reads `ids` (exactly ONE graph id) plus `entityId`; the read-only form is the separate
#: -dry-run op NAME, not an `action` field. Kept beside ``validate_call_ids`` because it is
#: the ops' `ids` scope, exactly like ``query_ops`` is the node-query ops'.
INSTRUCTION_GRAPH_DELETE_OPS = ("delete-instruction-graph", "delete-instruction-graph-force",
                                "delete-instruction-graph-dry-run")


def validate_call_ids(op: str, ids: list[int] | None) -> list[int] | None:
    """Only node-definition queries and the instruction-graph delete family accept IDs."""
    query_ops = ("delete-owned-graph-ids-dry-run", "delete-owned-graph-ids",
                 "delete-owned-entity-ids-dry-run", "delete-owned-entity-ids",
                 "node-definitions", "node-definition-variants")
    if op in INSTRUCTION_GRAPH_DELETE_OPS:
        # Exactly ONE nonzero uint32 -- the same shape the adapter's ValidateInstructionGraphDelete
        # enforces, refused here with the adapter's own named codes.
        if ids is None:
            raise SystemExit("INSTRUCTION_GRAPH_IDS_REQUIRED: pass --ids with one nonzero uint32 id")
        if not isinstance(ids, list) or len(ids) != 1:
            raise SystemExit("INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED: require exactly one id")
        if type(ids[0]) is not int or not 1 <= ids[0] <= 4294967295:
            raise SystemExit("INSTRUCTION_GRAPH_ID_INVALID: require a nonzero uint32 id")
        return list(ids)
    if op not in query_ops:
        if ids is not None or op.casefold() in query_ops:
            raise SystemExit("IDS_NOT_ALLOWED: ids require an exact node query op")
        return None
    if ids is None:
        raise SystemExit("NODE_QUERY_IDS_REQUIRED: pass --ids with 1..64 nonzero uint32 IDs")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 64 or
            any(type(value) is not int or not 1 <= value <= 4294967295 for value in ids)):
        raise SystemExit("NODE_QUERY_IDS_INVALID: require 1..64 nonzero uint32 IDs")
    return list(ids)


def validate_call_relative_path(args) -> dict:
    """Same basename-only contract as ClientScriptFileProbe; omission keeps defaults."""
    value = args.relative_path
    if value is None:
        return {}
    if args.op not in ("create-client-script-file-probe", "set-client-script-file-probe-path"):
        raise SystemExit("SCRIPT_FILE_PROBE_PATH_NOT_ALLOWED")
    if (not isinstance(value, str) or not 5 <= len(value) <= 128 or not value.endswith(".lua") or
            value.startswith(".") or ".." in value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or
            re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", value.split(".")[0])):
        raise SystemExit("SCRIPT_FILE_PROBE_PATH_INVALID")
    return {"relativePath": value}


def validate_call_tags(args) -> dict:
    """Fixed entity-tag fields only; validate before scope lookup or queue writes."""
    fields = ("tag_action", "tag_probe_id", "tag_entity_id", "tag_id", "tag_selected", "expected_tags_sha256")
    present = any(getattr(args, field) is not None for field in fields)
    if args.op != "author-entity-tag":
        if present or args.op.casefold() == "author-entity-tag":
            raise SystemExit("ENTITY_TAG_FIELDS_NOT_ALLOWED")
        return {}
    action = args.tag_action or "inspect"
    if not isinstance(args.tag_probe_id, str) or not re.fullmatch(r"[0-9a-f]{32}", args.tag_probe_id):
        raise SystemExit("ENTITY_TAG_PROBE_ID_INVALID")
    if type(args.tag_entity_id) is not int or not 1 <= args.tag_entity_id <= 4294967295:
        raise SystemExit("ENTITY_TAG_ENTITY_ID_INVALID")
    result = {"tagAction": action, "tagProbeId": args.tag_probe_id, "tagEntityId": args.tag_entity_id}
    if action == "inspect":
        if any(getattr(args, field) is not None for field in ("tag_id", "tag_selected", "expected_tags_sha256")):
            raise SystemExit("ENTITY_TAG_SET_FIELDS_NOT_ALLOWED")
        return result
    if action != "set" or type(args.tag_id) is not int or not 1 <= args.tag_id <= 2147483647:
        raise SystemExit("ENTITY_TAG_ID_INVALID")
    if args.tag_selected not in ("true", "false"):
        raise SystemExit("ENTITY_TAG_SELECTED_REQUIRED")
    if not isinstance(args.expected_tags_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", args.expected_tags_sha256):
        raise SystemExit("ENTITY_TAG_BASELINE_HASH_INVALID")
    result.update(tagId=args.tag_id, tagSelected=args.tag_selected == "true", expectedTagsSha256=args.expected_tags_sha256)
    return result


def validate_call_entity_id(args) -> dict:
    """Fixed ``entityId`` field, valid only for op ``inspect-entity-components``.

    Mirrors the tag helpers' integer rule (a real ``int`` in 1..4294967295) and the
    ``relative-path`` helper's optional shape: omitting the flag leaves every other
    call byte-for-byte unchanged, while a value on any other op is refused here rather
    than reaching the runner's closed allowlist.  ``call-bridge.ps1`` still enforces its
    own non-zero requirement (``ENTITY_COMPONENT_ID_REQUIRED``) when the field is absent.
    """
    value = args.entity_id
    if value is None:
        return {}
    if args.op in ("delete-entity-component", "add-entity-component"):
        # The two component mutation ops own their own entityId
        # (validate_call_component_delete / validate_call_component_add), so the field is not
        # double-validated here and no other op may carry it.
        return {}
    if args.op in INSTRUCTION_GRAPH_DELETE_OPS:
        # The instruction-graph family REQUIRES entityId (its edit-object id); it is validated
        # by validate_call_instruction_graph_entity, not here.
        return {}
    if args.op != "inspect-entity-components":
        raise SystemExit("ENTITY_COMPONENT_FIELDS_NOT_ALLOWED")
    if type(value) is not int or not 1 <= value <= 4294967295:
        raise SystemExit("ENTITY_COMPONENT_ID_INVALID")
    return {"entityId": value}


def validate_call_component_add(args) -> dict:
    """Fixed fields for the bounded component ADD op ``add-entity-component``.

    The mirror of ``validate_call_component_delete``: the SAME four op-owned fields
    (``action`` + ``probeId`` + ``entityId`` + ``componentId``), with the action vocabulary
    ``('inspect','add')`` instead of ``('inspect','delete')``. Omitting every flag leaves
    every other call byte-for-byte unchanged, while a value on any other op is refused here
    rather than reaching the runner's closed allowlist. ``componentId`` is the backend int32
    and is carried only for ``action='add'`` -- the adapter refuses it on an inspect body.
    Each refusal code is the adapter's own (EntityComponentAdd.cs / ValidateEntityComponentAdd).
    """
    fields = ("component_action", "component_probe_id", "component_id")
    present = any(getattr(args, field) is not None for field in fields)
    if args.op == "delete-entity-component":
        # The DELETE sibling owns these same three flags (validate_call_component_delete);
        # they must not be refused here as foreign.
        return {}
    if args.op != "add-entity-component":
        if present:
            raise SystemExit("ENTITY_COMPONENT_FIELDS_NOT_ALLOWED")
        return {}
    action = args.component_action
    if action not in ("inspect", "add"):
        raise SystemExit("COMPONENT_ACTION_INVALID")
    if not isinstance(args.component_probe_id, str) or not re.fullmatch(r"[0-9a-f]{32}", args.component_probe_id):
        raise SystemExit("COMPONENT_PROBE_ID_INVALID")
    if type(args.entity_id) is not int or not 1 <= args.entity_id <= 4294967295:
        raise SystemExit("ENTITY_COMPONENT_ID_INVALID")
    result = {"action": action, "probeId": args.component_probe_id, "entityId": args.entity_id}
    if action == "inspect":
        if args.component_id is not None:
            raise SystemExit("COMPONENT_DELETE_FIELDS_NOT_ALLOWED")
        return result
    if type(args.component_id) is not int or not 1 <= args.component_id <= 2147483647:
        raise SystemExit("COMPONENT_ID_INVALID")
    result["componentId"] = args.component_id
    return result


def validate_call_instruction_graph_entity(args) -> dict:
    """The instruction-graph family's required ``entityId`` (its edit-object id).

    A value on any other op is ignored (every op that legitimately carries ``--entity-id``
    reaches its own helper); for the family itself the field is REQUIRED and must be a real
    ``int`` in 1..4294967295, refused with the adapter's own ``INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED``.
    The graph id rides ``--ids`` and is validated by ``validate_call_ids``.
    """
    if args.op not in INSTRUCTION_GRAPH_DELETE_OPS:
        return {}
    value = args.entity_id
    if type(value) is not int or not 1 <= value <= 4294967295:
        raise SystemExit("INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED")
    return {"entityId": value}


def validate_call_component_delete(args) -> dict:
    """Fixed fields for the bounded component DELETE op ``delete-entity-component``.

    The sibling of ``validate_call_entity_id``: omitting every flag leaves every other
    call byte-for-byte unchanged, while a value on any other op is refused here rather
    than reaching the runner's closed allowlist. The op carries exactly the four op-owned
    fields the adapter validates (``action`` + ``probeId`` + ``entityId`` + ``componentId``),
    the same shape the tag op uses. ``action`` selects the adapter's self-owned
    inspect read from the delete; the non-zero entityId rule mirrors ``call-bridge.ps1``
    (``ENTITY_COMPONENT_ID_REQUIRED``) and ``componentId`` is a backend int32.
    """
    fields = ("component_action", "component_probe_id", "component_id")
    present = any(getattr(args, field) is not None for field in fields)
    if args.op == "add-entity-component":
        # The ADD sibling owns these same three flags (validate_call_component_add); they
        # must not be refused here as foreign.
        return {}
    if args.op != "delete-entity-component":
        if present:
            raise SystemExit("ENTITY_COMPONENT_FIELDS_NOT_ALLOWED")
        return {}
    action = args.component_action
    if action not in ("inspect", "delete"):
        raise SystemExit("COMPONENT_ACTION_INVALID")
    if not isinstance(args.component_probe_id, str) or not re.fullmatch(r"[0-9a-f]{32}", args.component_probe_id):
        raise SystemExit("COMPONENT_PROBE_ID_INVALID")
    if type(args.entity_id) is not int or not 1 <= args.entity_id <= 4294967295:
        raise SystemExit("ENTITY_COMPONENT_ID_INVALID")
    result = {"action": action, "probeId": args.component_probe_id, "entityId": args.entity_id}
    if action == "inspect":
        if args.component_id is not None:
            raise SystemExit("COMPONENT_DELETE_FIELDS_NOT_ALLOWED")
        return result
    if type(args.component_id) is not int or not 1 <= args.component_id <= 2147483647:
        raise SystemExit("COMPONENT_ID_INVALID")
    result["componentId"] = args.component_id
    return result


def validate_call_reflection(args) -> dict:
    """Fixed name needles for the read-only op ``reflection-probe``.

    The sibling of ``validate_call_entity_id`` / ``validate_call_component_delete``:
    omitting both flags leaves every other call byte-for-byte unchanged, while either flag
    on any other op is refused here rather than reaching the runner's closed allowlist.
    ``--name-contains`` is REQUIRED (the op answers "what methods does the live assembly
    have for names containing X" -- there is no sensible default), and the same 4-char
    floor the runner and the adapter enforce is applied here so a wildcard-everything scan
    never leaves the client. ``--member-contains`` is optional and omitted when empty.
    """
    fields = ("name_contains", "member_contains")
    present = any(getattr(args, field) is not None for field in fields)
    if args.op != "reflection-probe":
        if present:
            raise SystemExit("REFLECTION_PROBE_FIELDS_NOT_ALLOWED")
        return {}
    name = args.name_contains
    if not isinstance(name, str) or not name:
        raise SystemExit("REFLECTION_NAME_CONTAINS_REQUIRED")
    if not 4 <= len(name) <= 200:
        raise SystemExit("REFLECTION_NAME_CONTAINS_INVALID")
    result = {"nameContains": name}
    member = args.member_contains
    if member is not None:
        if not isinstance(member, str) or len(member) > 200:
            raise SystemExit("REFLECTION_MEMBER_CONTAINS_INVALID")
        if member:
            result["memberContains"] = member
    return result


def guarded_read_output(raw_path: str | Path) -> Path:
    """Permit only a new, plain file below this project's .runtime tree.

    The caller is unprivileged, but --out must not bypass the runner's protected
    save-file rules. Check lexical containment before inspecting links; resolving
    a symlink first would hide the path component that caused the escape.
    """
    lexical = Path(raw_path)
    # Windows abspath normalizes trailing spaces/dots, so reject aliases before
    # that normalization as well as checking the normalized components below.
    if (getattr(os.path, "isreserved", lambda _: False)(lexical) or
            any(part not in (lexical.anchor, ".", "..") and
                (part.rstrip(" .") != part or ":" in part)
                for part in lexical.parts)):
        raise SystemExit("READ_OUT_UNSAFE_PATH_COMPONENT")
    target = Path(os.path.abspath(lexical))
    allowed = Path(os.path.abspath(ROOT / ".runtime"))
    try:
        relative = target.relative_to(allowed)
    except ValueError:
        raise SystemExit("READ_OUT_OUTSIDE_RUNTIME") from None
    if not relative.parts:
        raise SystemExit("READ_OUT_MUST_BE_NEW_FILE")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    # Walk from the volume root, including ancestors of the allowed directory.
    current = Path(target.anchor)
    for index, part in enumerate(target.parts[1:]):
        if (":" in part or part.rstrip(" .") != part or
                part.split(".", 1)[0].upper() in reserved):
            raise SystemExit("READ_OUT_UNSAFE_PATH_COMPONENT")
        current /= part
        last = index == len(target.parts[1:]) - 1
        try:
            info = current.lstat()
        except FileNotFoundError:
            if last:
                return target
            raise SystemExit("READ_OUT_PARENT_MISSING") from None
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, "st_file_attributes", 0) & 0x400):
            raise SystemExit("READ_OUT_REPARSE_POINT")
        if last:
            raise SystemExit("READ_OUT_ALREADY_EXISTS")
        if not stat.S_ISDIR(info.st_mode):
            raise SystemExit("READ_OUT_PARENT_NOT_DIRECTORY")
    raise SystemExit("READ_OUT_MUST_BE_NEW_FILE")


def write_read_output(raw_path: str | Path, raw: bytes) -> Path:
    target = guarded_read_output(raw_path)
    # Exclusive creation also refuses a final file/link that appeared after the
    # check, so an existing output can never be overwritten by --out.
    try:
        with target.open("xb") as output:
            output.write(raw)
    except FileExistsError:
        raise SystemExit("READ_OUT_ALREADY_EXISTS") from None
    return target


NATIVE_ACTIONS = ("inspect", "create", "save", "create-batch", "reopen-current", "creature-create")
# 2026-10-09: the three-copy template whitelist (NATIVE_TEMPLATES / NATIVE_CREATURE_TEMPLATES
# here, TEMPLATES in tools/game-executor/build_scene_profile.py, $templateWhitelist in
# tools/editor-bridge/elevated-runner.ps1) is REMOVED by user directive. A create accepts
# any uint32 templateId; the native layer decides what is real. Do not reintroduce one.))


def _native_json_path(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("NATIVE_SCENE_EVIDENCE_PATH_INVALID")
    path = Path(value)
    if not path.is_absolute() or path.suffix.lower() != ".json":
        raise ValueError("NATIVE_SCENE_EVIDENCE_PATH_INVALID")
    if (getattr(os.path, "isreserved", lambda _: False)(path) or
            any(part not in (path.anchor, ".", "..") and
                (":" in part or part.rstrip(" .") != part) for part in path.parts)):
        raise ValueError("NATIVE_SCENE_EVIDENCE_PATH_INVALID")
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(Path(os.path.abspath(ROOT / ".runtime")))
    except ValueError:
        raise ValueError("NATIVE_SCENE_EVIDENCE_OUTSIDE_RUNTIME") from None
    for current in (path, *path.parents):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("NATIVE_SCENE_EVIDENCE_REPARSE")
    if not path.is_file():
        raise ValueError("NATIVE_SCENE_EVIDENCE_NOT_FILE")
    return str(path)


def validate_native_scene_request(payload: dict) -> dict:
    if not isinstance(payload, dict) or payload.get("kind") != "native-scene":
        raise ValueError("NATIVE_SCENE_REQUEST_INVALID")
    action = payload.get("action")
    if type(action) is not str or action not in NATIVE_ACTIONS:
        raise ValueError("NATIVE_SCENE_ACTION_INVALID")
    fields = {"kind", "action", "sessionPath", "levelId"}
    if action != "inspect": fields.add("reviewPath")
    if action in ("create", "creature-create"): fields.update(("templateId", "position", "rotation", "scale"))
    if action == "create-batch": fields.add("placements")
    if 'largeScene' in payload:
        if action != 'inspect' or payload['largeScene'] is not True:
            raise ValueError('LARGE_SCENE_INSPECT_TRUE_ONLY')
        if payload.get('reopenPrerequisites') is True:
            raise ValueError('LARGE_SCENE_REOPEN_NOT_SUPPORTED')
        fields.add('largeScene')
    if 'reopenPrerequisites' in payload:
        if action != 'inspect' or payload['reopenPrerequisites'] is not True:
            raise ValueError('REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY')
        fields.add('reopenPrerequisites')
    if set(payload) != fields:
        raise ValueError("NATIVE_SCENE_FIELDS_INVALID")
    def integer(value):
        if type(value) is not int or not 0 < value < 2**32:
            raise ValueError("NATIVE_SCENE_UINT32_INVALID")
        return value
    def vector(value, positive=False):
        if type(value) is not list or len(value) != 3:
            raise ValueError("NATIVE_SCENE_VECTOR_INVALID")
        result=[]
        for component in value:
            if type(component) not in (int,float) or not math.isfinite(component):
                raise ValueError("NATIVE_SCENE_VECTOR_INVALID")
            try: number=struct.unpack("<f",struct.pack("<f",component))[0]
            except (OverflowError,struct.error): raise ValueError("NATIVE_SCENE_VECTOR_INVALID") from None
            if not math.isfinite(number) or positive and number <= 0:
                raise ValueError("NATIVE_SCENE_VECTOR_INVALID")
            result.append(number)
        return result
    def placement(value, template_key):
        # 2026-10-09: no membership test. Any uint32 templateId is accepted here; the native
        # layer is the authority on what the catalog actually holds.
        if type(value) is not dict or set(value) != {template_key,"position","rotation","scale"}:
            raise ValueError("NATIVE_SCENE_PLACEMENT_INVALID")
        template=integer(value[template_key])
        return {template_key:template,"position":vector(value["position"]),
                "rotation":vector(value["rotation"]),"scale":vector(value["scale"],True)}
    result={"kind":"native-scene","action":action,"sessionPath":_native_json_path(payload["sessionPath"]),
            "levelId":integer(payload["levelId"])}
    if "reopenPrerequisites" in payload: result["reopenPrerequisites"] = True
    if "largeScene" in payload: result["largeScene"] = True
    if action != "inspect": result["reviewPath"]=_native_json_path(payload["reviewPath"])
    if action in ("create", "creature-create"):
        result.update(placement({key:payload[key] for key in ("templateId","position","rotation","scale")},"templateId"))
    if action == "create-batch":
        rows=payload["placements"]
        if type(rows) is not list or not 1 <= len(rows) <= 256:
            raise ValueError("NATIVE_SCENE_PLACEMENTS_INVALID")
        result["placements"]=[placement(row,"template_id") for row in rows]
    return result



def pending_reopen_inspect_allowed(canonical, capability):
    # Fixed pure helper shared with the scene result layer; no caller-selected module.
    import importlib.util
    if not isinstance(capability.get('pendingReopen'),dict):return False
    path=Path(__file__).resolve().parents[1]/'game-executor/native_reopen_result.py'
    spec=importlib.util.spec_from_file_location('_fixed_reopen_result',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Validate the optional selector before the shared identity-only precheck.
    # Keep the actual submitted request intact; helper checks its full schema.
    if 'reopenPrerequisites' in canonical:
        if canonical.get('action') != 'inspect' or canonical['reopenPrerequisites'] is not True: return False
        canonical = {k:v for k,v in canonical.items() if k != 'reopenPrerequisites'}
    return module.helper_pending_inspect_allowed(canonical,capability.get('pendingReopen'))


def reconcile_native_reopen(original_request_id: str, acceptance_sha256: str, timeout: float=30.0) -> dict:
    rid=_request_id(original_request_id)
    if type(acceptance_sha256) is not str or not re.fullmatch('[0-9a-f]{64}',acceptance_sha256):
        raise ValueError('REOPEN_ACCEPTANCE_HASH_INVALID')
    # A new queue envelope asks to reconcile the original immutable claim; never reenqueues it.
    return send({'kind':'native-reopen-reconcile','requestId':rid,'acceptanceSha256':acceptance_sha256},
                timeout=timeout,request_id=uuid.uuid4().hex)


def send_native_scene(payload: dict, timeout: float = 300.0, *, queue_dir: Path | None = None) -> dict:
    global QUEUE
    if queue_dir is not None: QUEUE = Path(queue_dir)
    canonical = validate_native_scene_request(payload)
    # The native queue must be explicitly selected under this project's bridge tree.
    queue = Path(os.path.abspath(QUEUE))
    try: queue.relative_to(Path(os.path.abspath(ROOT / ".runtime/editor-bridge")))
    except ValueError: raise ValueError("NATIVE_SCENE_QUEUE_OUTSIDE_PROJECT") from None
    for current in (queue,*queue.parents):
        info=current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400:
            raise ValueError("NATIVE_SCENE_QUEUE_REPARSE")
    heartbeat=(queue/"runner.heartbeat").read_text(encoding="utf-8-sig").strip()
    matched=re.fullmatch(r"([^ ]+) pid=([0-9]+) handled=([0-9]+)",heartbeat)
    if not matched: raise ValueError("NATIVE_SCENE_HELPER_HEARTBEAT_INVALID")
    stamp=datetime.fromisoformat(matched[1].replace("Z","+00:00"))
    age=(datetime.now(timezone.utc)-stamp).total_seconds()
    if not -5 <= age <= 30: raise ValueError("NATIVE_SCENE_HELPER_HEARTBEAT_STALE")
    health=send({"kind":"status"},timeout=30.0)
    if not isinstance(health,dict): raise ValueError("NATIVE_SCENE_HELPER_RESPONSE_INVALID")
    capability=health.get("nativeScene",{})
    if not isinstance(capability,dict): raise ValueError("NATIVE_SCENE_HELPER_CAPABILITY_INVALID")
    if (health.get("kind")!="status" or health.get("elevated") is not True or
            type(health.get("pid")) is not int or health["pid"]!=int(matched[2]) or
            capability.get("schema")!=1 or capability.get("enabled") is not True or
            (capability.get("blocked") is not False and not pending_reopen_inspect_allowed(canonical,capability)) or
            set(capability.get("actions",[]))!=set(NATIVE_ACTIONS) or
            not re.fullmatch(r"[0-9a-f]{64}",str(capability.get("pinsDigest",""))) or
            os.path.normcase(str(capability.get("projectRoot","")))!=os.path.normcase(str(ROOT))):
        raise ValueError("NATIVE_SCENE_HELPER_CAPABILITY_OR_IDENTITY_MISMATCH")
    expires=datetime.fromisoformat(health["deadlineUtc"].replace("Z","+00:00"))
    if expires <= datetime.now(timezone.utc): raise ValueError("NATIVE_SCENE_HELPER_EXPIRED")
    rid=uuid.uuid4().hex
    if canonical['action']=='reopen-current':
        if canonical['levelId']!=1073741840:raise ValueError('REOPEN_FIXED_LEVEL_REQUIRED')
        review=json.loads(Path(canonical['reviewPath']).read_text(encoding='utf-8-sig'))
        rid=_request_id(review['requestId'])
    return send(canonical,timeout=timeout,request_id=rid)


def poll_native_scene(request_id: str, timeout: float = 300.0) -> dict:
    return poll_request(request_id,timeout=timeout)


NATIVE_MAP_TOOLS = ('entity-transform', 'terrain', 'playtest-control', 'asset-inspection',
                    'template-item', 'template-currency', 'generalized-tabs',
                    'mondstadt-dropstuff', 'mondstadt-combat', 'entity-material', 'terrain-water',
                    'template-properties', 'role-template-bag')
NATIVE_MAP_ROOTS = {
    'entity-transform': ROOT / '.runtime/map-foundation-20261015/transform/prepared',
    'terrain': ROOT / '.runtime/map-foundation-20261015/terrain/prepared',
    'playtest-control': ROOT / '.runtime/playtest-control-20261016/prepared',
    'asset-inspection': ROOT / '.runtime/asset-inspection-20261017/prepared',
    'template-item': ROOT / '.runtime/native-card-20261017/prepared/template-item',
    'template-currency': ROOT / '.runtime/native-card-20261017/prepared/template-currency',
    'generalized-tabs': ROOT / '.runtime/native-card-20261017/prepared/generalized-tabs',
    'mondstadt-dropstuff': ROOT / '.runtime/native-card-20261017/prepared/mondstadt-dropstuff',
    'mondstadt-combat': ROOT / '.runtime/native-card-20261017/prepared/mondstadt-combat',
    'entity-material': ROOT / '.runtime/entity-material-20261017/prepared',
    'terrain-water': ROOT / '.runtime/terrain-water-20261017/prepared',
    'template-properties': ROOT / '.runtime/template-properties-20261017/v2-prepared',
    'role-template-bag': ROOT / '.runtime/native-card-20261017/prepared/role-template-bag',
}


def validate_native_map_request(payload: dict) -> dict:
    """A prepared map operation, never a caller-selected executable or script."""
    if (type(payload) is not dict or set(payload) != {'kind', 'tool', 'runPath', 'preparedSha256'} or
            payload.get('kind') != 'native-map' or payload.get('tool') not in NATIVE_MAP_TOOLS):
        raise ValueError('NATIVE_MAP_REQUEST_INVALID')
    raw = payload.get('runPath')
    if not isinstance(raw, str) or not raw or len(raw) > 2048:
        raise ValueError('NATIVE_MAP_RUN_INVALID')
    run = Path(raw)
    if not run.is_absolute():
        raise ValueError('NATIVE_MAP_RUN_NOT_ABSOLUTE')
    # Reuse the ordinary-file and reparse checks. The fixed tool revalidates its
    # own manifest kind, request, binaries and session before any native launch.
    manifest = _native_json_path(str(run / 'prepared.json'))
    run = Path(manifest).parent
    boundary = NATIVE_MAP_ROOTS[payload['tool']]
    if run == boundary or not run.is_relative_to(boundary):
        raise ValueError('NATIVE_MAP_RUN_WRONG_TOOL_ROOT')
    expected = payload.get('preparedSha256')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('NATIVE_MAP_PREPARED_HASH_INVALID')
    with Path(manifest).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise ValueError('NATIVE_MAP_PREPARED_CHANGED')
    return {'kind': 'native-map', 'tool': payload['tool'], 'runPath': str(run), 'preparedSha256': expected}


def send_native_map(tool: str, run: str | Path, timeout: float = 300.0, *, queue_dir: Path | None = None) -> dict:
    """Dispatch one fixed map card through the resident helper, or poll its receipt.

    The card carries one immutable queue identity. Repeating a call never changes
    transport or asks a new helper to replay it, even after a timeout or restart.
    """
    global QUEUE
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= 1800:
        raise ValueError('QUEUE_TIMEOUT_INVALID')
    if queue_dir is not None:
        QUEUE = Path(queue_dir)
    manifest = _native_json_path(str(Path(run).absolute() / 'prepared.json'))
    with Path(manifest).open('rb') as stream:
        prepared_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    canonical = validate_native_map_request({'kind': 'native-map', 'tool': tool,
        'runPath': str(Path(run).absolute()), 'preparedSha256': prepared_sha})
    queue = Path(os.path.abspath(QUEUE))
    boundary = Path(os.path.abspath(ROOT / '.runtime/editor-bridge'))
    if queue == boundary or not queue.is_relative_to(boundary):
        raise ValueError('NATIVE_MAP_QUEUE_OUTSIDE_PROJECT')
    for current in (queue, *queue.parents):
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('NATIVE_MAP_QUEUE_REPARSE')
    QUEUE = queue
    marker = Path(canonical['runPath']) / 'map-queue-claim.json'
    if marker.exists():
        original = json.loads(marker.read_text(encoding='utf-8'))
        if original.get('request') != canonical or original.get('queueDir') != str(queue):
            raise ValueError('NATIVE_MAP_QUEUE_CLAIM_CONFLICT')
        rid = _request_id(original['requestId'])
        result = poll_request(rid, timeout)
        return dict(result, queueRequestId=rid, queueDir=str(queue), retryAttempted=False)
    heartbeat = (queue / 'runner.heartbeat').read_text(encoding='utf-8-sig').strip()
    matched = re.fullmatch(r'([^ ]+) pid=([0-9]+) handled=([0-9]+)', heartbeat)
    if not matched:
        raise ValueError('NATIVE_MAP_HELPER_HEARTBEAT_INVALID')
    stamp = datetime.fromisoformat(matched[1].replace('Z', '+00:00'))
    if not -5 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 30:
        raise ValueError('NATIVE_MAP_HELPER_HEARTBEAT_STALE')
    health = send({'kind': 'status'}, timeout=30.0)
    if not isinstance(health, dict):
        raise ValueError('NATIVE_MAP_HELPER_RESPONSE_INVALID')
    capability, native = health.get('nativeMap', {}), health.get('nativeScene', {})
    if not isinstance(capability, dict) or not isinstance(native, dict):
        raise ValueError('NATIVE_MAP_HELPER_CAPABILITY_INVALID')
    if (health.get('kind') != 'status' or health.get('elevated') is not True or
            type(health.get('pid')) is not int or health['pid'] != int(matched[2]) or
            capability.get('schema') != 1 or capability.get('enabled') is not True or
            set(capability.get('tools', [])) != set(NATIVE_MAP_TOOLS) or
            native.get('blocked') is not False or
            not re.fullmatch(r'[0-9a-f]{64}', str(capability.get('pinsDigest', ''))) or
            capability.get('pinsDigest') != native.get('pinsDigest') or
            os.path.normcase(str(capability.get('projectRoot', ''))) != os.path.normcase(str(ROOT))):
        raise ValueError('NATIVE_MAP_HELPER_CAPABILITY_OR_IDENTITY_MISMATCH')
    if datetime.fromisoformat(health['deadlineUtc'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise ValueError('NATIVE_MAP_HELPER_EXPIRED')
    rid = uuid.uuid4().hex
    # Exclusive intent is deliberately before enqueue. A crash between those
    # writes leaves a pending card to reconcile; it cannot cause a second call.
    with marker.open('x', encoding='utf-8') as stream:
        json.dump({'schema': 1, 'requestId': rid, 'request': canonical, 'queueDir': str(queue)},
                  stream, ensure_ascii=True, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    result = send(canonical, timeout=timeout, request_id=rid)
    return dict(result, queueRequestId=rid, queueDir=str(queue), retryAttempted=False)


def build_fs_request(args) -> dict:
    req: dict = {"kind": "fs", "op": args.op, "path": args.path}
    if args.dest is not None:
        req["dest"] = args.dest
    if args.confirm is not None:
        req["confirm"] = args.confirm
    if args.label is not None:
        req["label"] = args.label
    if args.algorithm is not None:
        req["algorithm"] = args.algorithm
    if args.max_entries is not None:
        req["max"] = args.max_entries
    if args.recurse:
        req["recurse"] = True
    if args.overwrite:
        req["overwrite"] = True
    if args.no_create_parents:
        req["createParents"] = False

    if args.op == "read":
        req["encoding"] = args.encoding
    if args.op == "write":
        req["encoding"] = args.encoding
        if args.data_file is not None:
            raw = Path(args.data_file).read_bytes()
            req["data"] = base64.b64encode(raw).decode("ascii")
            req["encoding"] = "base64"
        elif args.data is not None:
            req["data"] = args.data
        else:
            raise SystemExit("fs --op write needs --data or --data-file")
    return req


def main() -> int:
    global QUEUE
    # Replies carry Chinese names and paths. On Windows the default console encoding
    # is the ANSI code page, so printing them raises UnicodeEncodeError partway
    # through the document and the caller receives a truncated stream it cannot
    # parse. Done here rather than at import time so importing this module stays
    # free of side effects (tests import it) while every CLI print is still covered.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--queue-dir', type=Path, help='Use an isolated queue under .runtime/editor-bridge')
    sub = ap.add_subparsers(dest="kind", required=True)

    sub.add_parser("status")

    p_load = sub.add_parser("load")
    p_load.add_argument("--target-pid", type=int, required=True)

    p_call = sub.add_parser("call")
    p_call.add_argument("--op", required=True)
    p_call.add_argument("--run-id", default=None)
    p_call.add_argument("--timeout", type=float, default=300.0)
    # An explicit queue identity for a bridge ``call``.  Default None keeps the old
    # behaviour (a fresh uuid per call) for every existing caller.
    #
    # WHY IT EXISTS: the scene path already carries its own id (``--request-id`` on the
    # scene CLI, threaded into ``send``), but ``call`` did not, so a bridge op always
    # landed under a freshly minted uuid.  The run records a DERIVED id for its cleanup
    # step (run_parameter_matrix.live_request_id), so for a bridge delete the id on the
    # wire and the id in the run's own records were two different strings.  MEASURED
    # 2026-10-03 across three runs: every provenance target that stayed unbound was a
    # ``case:*/cleanup`` target, and each needed a run-internal id that appears nowhere
    # under the producer roots -- so the authenticity layer could never reach zero
    # defects for any run that cleans up.
    #
    # CAUTION for the caller: reusing an id is a POLL, not a second dispatch
    # (``send`` opens the submission marker exclusively), and reusing one with
    # DIFFERENT contents is an error.  A dry-run and its real delete must therefore
    # carry DIFFERENT ids.
    p_call.add_argument("--request-id", default=None,
                        help="32-hex queue identity for this call; omit for a fresh uuid")
    p_call.add_argument("--ids", nargs="+", type=int, default=None,
                        help="node-definitions / node-definition-variants only: 1..64 IDs in 1..4294967295")

    p_call.add_argument("--relative-path", default=None)
    p_call.add_argument("--tag-action", choices=("inspect", "set"), default=None)
    p_call.add_argument("--tag-probe-id", default=None)
    p_call.add_argument("--tag-entity-id", type=int, default=None)
    p_call.add_argument("--tag-id", type=int, default=None)
    p_call.add_argument("--tag-selected", choices=("true", "false"), default=None)
    p_call.add_argument("--expected-tags-sha256", default=None)
    # The single entity id the compiled ``inspect-entity-components`` probe takes.  Optional
    # like every other call flag; only accepted for that one op (see validate_call_entity_id).
    p_call.add_argument("--entity-id", type=int, default=None,
                        help="inspect-entity-components / delete-entity-component: the nonzero uint32 entityId")
    # The bounded component DELETE / ADD ops' own op-scoped fields (see
    # validate_call_component_delete / validate_call_component_add). Optional like every other
    # call flag; each flag is only accepted for the op that owns it, and `--component-id` is
    # carried only for the mutating action of that op ('delete' for the delete op, 'add' for
    # the add op). The two ops share the three flags.
    p_call.add_argument("--component-action", choices=("inspect", "add", "delete"), default=None,
                        help="delete-entity-component / add-entity-component only: 'inspect' (read-only), or 'delete'/'add'")
    p_call.add_argument("--component-probe-id", default=None,
                        help="delete-entity-component / add-entity-component only: the 32-hex CRUD probe window id")
    p_call.add_argument("--component-id", type=int, default=None,
                        help="delete-entity-component (action=delete) / add-entity-component (action=add): the uint31 componentId")
    # The read-only reflection probe's two name needles (see validate_call_reflection). Both
    # are optional flags; only accepted for the one op, and --name-contains must be 4..200 chars.
    p_call.add_argument("--name-contains", default=None,
                        help="reflection-probe only: 4..200 char case-insensitive type-name substring")
    p_call.add_argument("--member-contains", default=None,
                        help="reflection-probe only: optional case-insensitive method-name substring")

    p_fs = sub.add_parser("fs")
    p_fs.add_argument("--op", required=True)
    p_fs.add_argument("--path", required=True)
    p_fs.add_argument("--dest", default=None)
    p_fs.add_argument("--confirm", default=None)
    p_fs.add_argument("--encoding", choices=["utf8", "base64"], default="base64")
    p_fs.add_argument("--data", default=None)
    p_fs.add_argument("--data-file", default=None)
    p_fs.add_argument("--out", default=None, help="read only: create a new output file under this project .runtime")
    p_fs.add_argument("--label", default=None)
    p_fs.add_argument("--algorithm", default=None)
    p_fs.add_argument("--max-entries", type=int, default=None, dest="max_entries")
    p_fs.add_argument("--recurse", action="store_true")
    p_fs.add_argument("--overwrite", action="store_true")
    p_fs.add_argument("--no-create-parents", action="store_true")
    p_fs.add_argument("--timeout", type=float, default=300.0)

    args = ap.parse_args()
    if args.queue_dir is not None:
        candidate = args.queue_dir.resolve()
        candidate.relative_to((ROOT / '.runtime/editor-bridge').resolve())
        QUEUE = candidate

    if args.kind == "status":
        out = send({"kind": "status"}, timeout=30.0)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if args.kind == "load":
        out = send({"kind": "load", "targetPid": args.target_pid})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if isinstance(out, dict) and is_literal_true(out.get("accepted")) else 1

    if args.kind == "fs":
        if args.out is not None and args.op != "read":
            raise SystemExit("READ_OUT_REQUIRES_READ_OP")
        output_path = guarded_read_output(args.out) if args.out is not None else None
        request = build_fs_request(args)
        out = send(request, timeout=args.timeout)
        if not isinstance(out, dict) or out.get("op") != args.op or reported_not_ok(out):
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 1
        if out.get("op") == "read" and output_path is not None:
            payload = out.pop("data", "")
            raw = (
                base64.b64decode(payload)
                if out.get("encoding") == "base64"
                else payload.encode("utf-8")
            )
            written = write_read_output(output_path, raw)
            out["writtenTo"] = str(written)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1 if reported_not_ok(out) else 0

    # Reject malformed query arguments before searching scopes or touching the queue.
    ids = validate_call_ids(args.op, args.ids)
    tag_fields = validate_call_tags(args)
    path_fields = validate_call_relative_path(args)
    entity_fields = validate_call_entity_id(args)
    component_delete_fields = validate_call_component_delete(args)
    component_add_fields = validate_call_component_add(args)
    instruction_graph_fields = validate_call_instruction_graph_entity(args)
    reflection_fields = validate_call_reflection(args)
    run_id = args.run_id or latest_run_id()
    if run_id is None:
        raise SystemExit("no runId found; run the load step first or pass --run-id")
    request = {"kind": "call", "runId": run_id, "op": args.op}
    request.update(tag_fields)
    request.update(path_fields)
    request.update(entity_fields)
    request.update(component_delete_fields)
    request.update(component_add_fields)
    request.update(instruction_graph_fields)
    request.update(reflection_fields)
    if ids is not None:
        request["ids"] = ids
    # ``_request_id`` validates the 32-hex shape and raises before anything is sent, so
    # a malformed --request-id is a refusal, not a dispatch under some other identity.
    out = send(request, timeout=args.timeout,
               request_id=_request_id(args.request_id) if args.request_id is not None else None)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if isinstance(out, dict) and is_literal_true(out.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
