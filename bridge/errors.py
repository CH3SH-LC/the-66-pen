"""Structured error vocabulary.

The contract (``60-interface-contracts.md``) fixes one error table. Codes from
that table are reused verbatim. Anything this bridge needs beyond it lives in
``BRIDGE_CODES`` and is clearly marked as an extension -- so a reader can tell
which codes are contract vocabulary and which are bridge-local inventions.
"""

from __future__ import annotations

from typing import Any


# --- verbatim from the contract's error table --------------------------------
CONTRACT_CODES = frozenset(
    {
        "CAPABILITY_UNAVAILABLE",
        "VERSION_UNSUPPORTED",
        "STALE_REVISION",
        "AMBIGUOUS_TARGET",
        "REFERENCE_UNRESOLVED",
        "LOSSY_ROUNDTRIP",
        "LIMIT_EXCEEDED",
        "COMPILER_FAILED",
        "EDITOR_MODE_CONFLICT",
        "UI_STATE_UNCERTAIN",
        "EFFECT_INDETERMINATE",
        "VALIDATION_FAILED",
        "CANCELLED_AFTER_EFFECT",
    }
)

# --- bridge-local extensions; NOT part of the contract table ------------------
BRIDGE_CODES = frozenset(
    {
        "PROTOCOL_VERSION_UNSUPPORTED",
        "METHOD_UNKNOWN",
        "PROJECT_SCOPE_MISMATCH",
        "PARAM_FORBIDDEN",
        "TARGET_NOT_ALLOWED",
        "TARGET_UNAVAILABLE",
        "LAUNCH_FAILED",
        "IDEMPOTENCY_CONFLICT",
        "STATE_MODE_MISMATCH",
        "LOCK_HELD",
        "BACKEND_UNAVAILABLE",
        "JOURNAL_CORRUPT",
    }
)

ALL_CODES = CONTRACT_CODES | BRIDGE_CODES

PHASES = frozenset({"validate", "authorize", "preflight", "effect", "observe", "report"})


class BridgeError(Exception):
    """A failure with a machine-readable code, never a bare string."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        phase: str = "validate",
        retryable: bool = False,
        effect_state: str = "none",
        details: dict[str, Any] | None = None,
        code_origin: str | None = None,
    ) -> None:
        if code not in ALL_CODES and code_origin is None:
            raise AssertionError(f"undeclared bridge error code: {code}")
        if phase not in PHASES:
            raise AssertionError(f"unknown phase: {phase}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.phase = phase
        self.retryable = retryable
        self.effect_state = effect_state
        self.details = details or {}
        self.code_origin = code_origin

    def to_dict(self) -> dict[str, Any]:
        if self.code_origin:
            origin = self.code_origin
        elif self.code in CONTRACT_CODES:
            origin = "contract"
        elif self.code in BRIDGE_CODES:
            origin = "bridge-extension"
        else:
            origin = "external"
        return {
            "code": self.code,
            "message": self.message,
            "phase": self.phase,
            "retryable": self.retryable,
            "effectState": self.effect_state,
            "details": self.details,
            "codeOrigin": origin,
        }
