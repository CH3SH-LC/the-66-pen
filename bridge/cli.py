"""Single-shot stdin JSON -> stdout JSON bridge.

    python bridge/cli.py < request.json
    echo '{"protocolVersion":"0.1", ...}' | python bridge/cli.py

One process, one request, one response. Nothing is written to stdout except the
response object; diagnostics, if any, go to stderr.

Exit codes:

``0``  a well-formed response was produced, whatever its ``status``. A ``failed``
       or ``indeterminate`` status is a normal outcome, not a crash.
``2``  the bridge could not produce a response at all (stdin unreadable, or the
       response could not be serialised).

Backend mode comes from ``MW_BRIDGE_BACKEND_MODE``: unset or ``real`` uses the
Windows CIM query and a real ``subprocess`` launch; ``mock`` swaps in simulated
observation and a launcher that starts nothing. Anything else is refused rather
than silently treated as real.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # allow `python bridge/cli.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bridge.errors import BridgeError
    from bridge.launcher import build_launcher
    from bridge.methods import Bridge
    from bridge.osbackend import build_backend
    from bridge.protocol import error_response, validate_request
    from bridge.state import BridgeStore
    from bridge.window import build_window_backend
else:
    from .errors import BridgeError
    from .launcher import build_launcher
    from .methods import Bridge
    from .osbackend import build_backend
    from .protocol import error_response, validate_request
    from .state import BridgeStore
    from .window import build_window_backend

#: The project is this directory. Derived from the file location, never from cwd,
#: so `cd` anywhere and the bridge still operates on the same project.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_ROOT = PROJECT_ROOT / ".runtime" / "bridge"

BACKEND_MODE_ENV = "MW_BRIDGE_BACKEND_MODE"
VALID_MODES = ("real", "mock")


def backend_mode() -> str:
    raw = (os.environ.get(BACKEND_MODE_ENV) or "real").strip().lower()
    if raw not in VALID_MODES:
        raise BridgeError(
            "VALIDATION_FAILED",
            f"{BACKEND_MODE_ENV} must be one of {list(VALID_MODES)}",
            details={"received": raw},
        )
    return raw


def load_asset_api():
    """Import the delegated asset module. Absence is a capability gap, not a crash."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from mvp import asset_api  # noqa: PLC0415 - optional dependency by design
    except Exception as exc:  # noqa: BLE001 - any import failure means "unavailable"
        sys.stderr.write(f"bridge: mvp.asset_api unavailable: {type(exc).__name__}: {exc}\n")
        return None
    return asset_api


def build_bridge(mode: str) -> Bridge:
    store = BridgeStore(STATE_ROOT, mode=mode)
    store.ensure_dirs()
    backend = build_backend(mode, mock_state_path=store.paths.mock_processes)
    launcher = build_launcher(mode, store.paths.mock_processes)
    return Bridge(
        store=store,
        backend=backend,
        launcher=launcher,
        asset_api=load_asset_api(),
        # The evidence directory is fixed and project-local; a real capture
        # enumerates in a child process, a mock one touches no window at all.
        window_backend=build_window_backend(mode, PROJECT_ROOT / ".runtime" / "bridge" / "evidence"),
    )


def read_request() -> Any:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        raise BridgeError("VALIDATION_FAILED", "stdin was empty; expected one JSON request")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BridgeError("VALIDATION_FAILED", f"stdin is not valid UTF-8: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise BridgeError("VALIDATION_FAILED", f"stdin is not valid JSON: {exc}") from exc


def handle(payload: Any) -> dict[str, Any]:
    """Validate, dispatch and return an envelope. Errors become envelopes too."""
    request_id: str | None = None
    try:
        request = validate_request(payload)
        request_id = request["requestId"]
        mode = backend_mode()
        bridge = build_bridge(mode)
        return bridge.dispatch(request)
    except BridgeError as exc:
        return error_response(request_id, exc)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(__doc__ or "")
        return 0
    try:
        payload = read_request()
    except BridgeError as exc:
        payload = None
        response = error_response(None, exc)
    else:
        response = handle(payload)
    try:
        sys.stdout.write(json.dumps(response, ensure_ascii=False, sort_keys=False) + "\n")
        sys.stdout.flush()
    except (OSError, TypeError, ValueError) as exc:  # pragma: no cover - defensive
        sys.stderr.write(f"bridge: failed to serialise response: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
