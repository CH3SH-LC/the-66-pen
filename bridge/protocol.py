"""Request validation and response envelope.

Wire shape follows ``60-interface-contracts.md``: one JSON object in, one JSON
object out, with the same ``requestId`` echoed back.

One deliberate deviation, documented in ``README.md``: this bridge **rejects
unknown keys** at the top level and inside ``params``. The contract allows a
minor version to add optional fields, which argues for leniency -- but a
component whose job is to start a process should not silently ignore an
argument it did not understand. A caller that sends ``"executablePath"`` must
get an error, not a shrug.
"""

from __future__ import annotations

from typing import Any

from . import BRIDGE_VERSION
from .errors import BridgeError
from .util import utc_now

PROTOCOL_VERSION = "0.1"

#: The project is fixed to the directory that contains this package. It is
#: derived from ``__file__`` so that it cannot be redirected by cwd or by a
#: request parameter.
PROJECT_ID = "genshin-impact-miliastra-wonderland-editor"

REQUEST_KEYS = frozenset(
    {
        "protocolVersion",
        "requestId",
        "projectId",
        "method",
        "params",
        "idempotencyKey",
        "expectedRevision",
    }
)

#: Asset-domain methods, delegated to ``mvp/asset_api.py``. ``scene.build``
#: writes content-addressed artifacts inside the project, so it is a mutation
#: here; the other three only read.
ASSET_READ_METHODS = frozenset(
    {"mw.catalog.search", "mw.asset.inspect", "mw.build.validate"}
)

#: The only target ``mw.snapshot.capture`` accepts. Spelled here rather than
#: imported so that ``protocol`` stays free of the window module.
SNAPSHOT_TARGET = "game"
ASSET_MUTATING_METHODS = frozenset({"mw.scene.build"})
ASSET_METHODS = ASSET_READ_METHODS | ASSET_MUTATING_METHODS

#: Methods that mutate state and therefore require an idempotency key and a
#: matching ``expectedRevision``.
#: ``mw.window.restore`` asks a window to un-minimize. That is an effect on
#: something outside this process, so it takes the same key + revision discipline
#: as a launch -- even though un-minimizing an already-un-minimized window is a
#: no-op, which is why a repeat under the same key replays instead of re-asking.
MUTATING_METHODS = (
    frozenset({"mw.runtime.start", "mw.window.restore"}) | ASSET_MUTATING_METHODS
)

#: ``mw.snapshot.capture`` writes exactly one BMP under ``.runtime/`` and mutates
#: no project state, so it stays a read method: no idempotency key, no revision
#: fence. What it reads is a window; what it produces is evidence.
READ_METHODS = (
    frozenset({"mw.capabilities.get", "mw.runtime.status", "mw.snapshot.capture"})
    | ASSET_READ_METHODS
)

KNOWN_METHODS = READ_METHODS | MUTATING_METHODS

_MAX_STRING = 256


def _require(condition: bool, message: str, **details: Any) -> None:
    if not condition:
        raise BridgeError("VALIDATION_FAILED", message, details=details)


def _bounded_string(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise BridgeError("VALIDATION_FAILED", f"{field} is required")
        return None
    _require(isinstance(value, str), f"{field} must be a string", field=field)
    _require(0 < len(value) <= _MAX_STRING, f"{field} must be 1..{_MAX_STRING} characters")
    _require(
        all(0x20 <= ord(ch) < 0x7F for ch in value),
        f"{field} must be printable ASCII",
        field=field,
    )
    return value


def validate_request(raw: Any) -> dict[str, Any]:
    """Validate an already-decoded JSON value and normalise it."""
    _require(isinstance(raw, dict), "request must be a JSON object")

    unknown = sorted(set(raw) - REQUEST_KEYS)
    if unknown:
        raise BridgeError(
            "VALIDATION_FAILED",
            f"unknown top-level field(s): {', '.join(unknown)}",
            details={"unknownFields": unknown, "allowedFields": sorted(REQUEST_KEYS)},
        )

    protocol_version = raw.get("protocolVersion")
    if protocol_version != PROTOCOL_VERSION:
        raise BridgeError(
            "PROTOCOL_VERSION_UNSUPPORTED",
            f"protocolVersion must be {PROTOCOL_VERSION!r}, got {protocol_version!r}",
            details={"supported": [PROTOCOL_VERSION]},
        )

    request_id = _bounded_string(raw.get("requestId"), "requestId")

    project_id = raw.get("projectId")
    if project_id != PROJECT_ID:
        raise BridgeError(
            "PROJECT_SCOPE_MISMATCH",
            f"this bridge serves exactly one project: {PROJECT_ID!r}",
            phase="authorize",
            details={"expected": PROJECT_ID, "received": project_id},
        )

    method = raw.get("method")
    _require(isinstance(method, str), "method must be a string", method=method)
    if method not in KNOWN_METHODS:
        raise BridgeError(
            "METHOD_UNKNOWN",
            f"method {method!r} is not implemented by this bridge",
            details={"knownMethods": sorted(KNOWN_METHODS)},
        )

    params = raw.get("params", {})
    _require(isinstance(params, dict), "params must be a JSON object")

    idempotency_key = _bounded_string(raw.get("idempotencyKey"), "idempotencyKey", required=False)
    expected_revision = _bounded_string(
        raw.get("expectedRevision"), "expectedRevision", required=False
    )

    if method in MUTATING_METHODS:
        if idempotency_key is None:
            raise BridgeError(
                "VALIDATION_FAILED",
                "idempotencyKey is required for mutating methods",
                details={"method": method},
            )
        if expected_revision is None:
            raise BridgeError(
                "VALIDATION_FAILED",
                "expectedRevision is required for mutating methods",
                details={"method": method},
            )
        if not expected_revision.isdigit():
            raise BridgeError(
                "VALIDATION_FAILED",
                "expectedRevision must be a non-negative decimal string",
                details={"received": expected_revision},
            )

    return {
        "protocolVersion": protocol_version,
        "requestId": request_id,
        "projectId": project_id,
        "method": method,
        "params": params,
        "idempotencyKey": idempotency_key,
        "expectedRevision": expected_revision,
    }


def parse_params(params: dict[str, Any], allowed: frozenset[str], method: str) -> dict[str, Any]:
    """Reject any parameter the method does not declare.

    This is the choke point that makes ``{"executablePath": "..."}``,
    ``{"command": "..."}`` and ``{"args": [...]}`` impossible rather than merely
    discouraged: they are not in ``allowed``, so they never reach a launcher.
    """
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise BridgeError(
            "PARAM_FORBIDDEN",
            f"{method} does not accept parameter(s): {', '.join(unknown)}",
            details={
                "unknownParams": unknown,
                "allowedParams": sorted(allowed),
                "note": (
                    "This bridge accepts a closed parameter vocabulary. "
                    "It cannot be given an executable path, command line, shell "
                    "string or arbitrary arguments."
                ),
            },
        )
    return dict(params)


def make_response(
    request_id: str | None,
    status: str,
    *,
    data: dict[str, Any] | None = None,
    observation: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "bridgeVersion": BRIDGE_VERSION,
        "requestId": request_id,
        "status": status,
        "data": data,
        "observation": observation,
        "evidence": evidence or [],
        "warnings": warnings or [],
        "error": error,
        "respondedAt": utc_now(),
    }


def error_response(request_id: str | None, exc: BridgeError, *, warnings=None) -> dict[str, Any]:
    status = "indeterminate" if exc.code == "EFFECT_INDETERMINATE" else "failed"
    return make_response(
        request_id,
        status,
        error=exc.to_dict(),
        warnings=warnings,
    )
