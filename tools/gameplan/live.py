"""Read the CURRENTLY-OPEN sandbox, live, instead of relying on a recorded id.

The project has two very different ways to answer "what's open right now?":

* ``tools/game-executor/current-save.py`` reads the **disk** and reports what was
  last *written* plus what a previous native read *saw* (often STALE).  It is a
  record, not an observation.
* ``tools/game-executor/discover_current_level.py`` runs a native read-only probe
  through the resident helper and reports the level id **out of that run's own
  native receipt** — never from a caller, a config file, or a wire placeholder.

This module makes the second one a first-class, callable capability so nobody has
to reach for the recorded id: :func:`read_live` returns the live helper state and
the live level/entity count, and refuses (rather than guessing) when the helper is
not up.

:func:`read_scene` extends that into the **whole scene in one call**: the helper
state, the live level + entity count, the demo graph's status in the editor (read
through the SAME ``author.py graph inspect`` contract ``cli.cmd_graph_status``
uses, sharing :func:`tools.gameplan.builder.request_id`), and -- when a ``.gil``
is named -- the root-field-6 directory health.  Every part degrades to its own
**named state** (never a crash, never a false success); see ``HELPER_DOWN``,
``BRIDGE_NOT_LOADED``, ``GRAPH_ABSENT`` and friends.

Nothing here writes.  Every call is the project's existing read-only path: a
``status`` read, a native ``discover`` read, one ``graph inspect`` read, and at
most one ``.gil`` read.  No create/add/wire/value/bind/save is ever emitted.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_QUEUE = _REPO_ROOT / ".runtime" / "editor-bridge" / "elevated-queue"
_ELEVATED_REQUEST = _REPO_ROOT / "tools" / "editor-bridge" / "elevated-request.py"
_DISCOVER = _REPO_ROOT / "tools" / "game-executor" / "discover_current_level.py"
_AUTHOR_PY = _REPO_ROOT / "tools" / "authoring" / "author.py"
_BRIDGE_READY = "bridge-ready.json"

# ``level_directory`` sits beside ``gil_container`` under tools/beyond-save and is
# reached as a sibling module, exactly as ``checkpoint.py:76-77`` reaches it.
_BEYOND_SAVE = _REPO_ROOT / "tools" / "beyond-save"

#: A runner takes a full argv and returns (returncode, stdout).  Injected so the
#: whole thing is testable offline; the production runner shells out.
Runner = Callable[[list[str]], tuple[int, str]]

#: A graph runner takes a full argv and returns the PARSED JSON object (the same
#: contract :class:`tools.gameplan.builder.GraphBuilder` uses for ``author.py``).
GraphRunner = Callable[[list[str]], dict]

#: Is the bridge loaded for this run?  ``(loaded, reason)``; never raises.
BridgeProbe = Callable[[object], "tuple[bool, str]"]

# --------------------------------------------------------------------------- #
# named states -- every part of the scene reports one of these, never a bare bool
# --------------------------------------------------------------------------- #

HELPER_ACTIVE = "active"
HELPER_NOT_ELEVATED = "not-elevated"
HELPER_DOWN = "down"

LEVEL_VERIFIED = "verified"
LEVEL_UNVERIFIED = "unverified"
LEVEL_UNAVAILABLE = "unavailable"

BRIDGE_LOADED = "loaded"
BRIDGE_NOT_LOADED = "not-loaded"

GRAPH_PRESENT = "present"
GRAPH_ABSENT = "absent"
GRAPH_NOT_CHECKED = "not-checked"

DIRECTORY_CLEAN = "clean"
DIRECTORY_DEFECTIVE = "defective"
DIRECTORY_NOT_CHECKED = "not-checked"


@dataclass
class LiveState:
    """The live sandbox, as read this instant."""

    ok: bool
    reason: str | None = None
    source: str = "native-read"          # never "recorded" by accident
    helper_pid: int | None = None
    helper_deadline_utc: str | None = None
    helper_actions: tuple[str, ...] = ()
    helper_blocked: bool | None = None
    pins_digest: str | None = None
    level_id: int | None = None
    entities: int | None = None
    level_verified: bool = False
    handle: str | None = None
    run_dir: str | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "source": self.source,
            "reason": self.reason,
            "helper": {
                "pid": self.helper_pid,
                "deadlineUtc": self.helper_deadline_utc,
                "blocked": self.helper_blocked,
                "actions": list(self.helper_actions),
                "pinsDigest": self.pins_digest,
            },
            "level": {
                "levelId": self.level_id,
                "entities": self.entities,
                "verified": self.level_verified,
                "handle": self.handle,
                "runDir": self.run_dir,
            },
            "errors": list(self.errors),
        }


def _parse_status(stdout: str) -> dict:
    """The status receipt is JSON; tolerate leading noise from the console."""
    text = stdout.strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in status output")
    return json.loads(text[start:])


def helper_status(queue_dir: Path, runner: Runner) -> tuple[dict | None, list[str]]:
    """Authoritative helper state via ``elevated-request.py status`` (read-only)."""
    argv = ["python", "-B", str(_ELEVATED_REQUEST), "--queue-dir", str(queue_dir), "status"]
    code, out = runner(argv)
    if code != 0 and not out.strip().startswith("{"):
        return None, [f"status command failed (exit {code})"]
    try:
        receipt = _parse_status(out)
    except (ValueError, json.JSONDecodeError) as error:
        return None, [f"status receipt unparseable: {error}"]
    return receipt, []


def current_level(queue_dir: Path, runner: Runner, *, timeout_s: int = 300) -> tuple[dict | None, list[str]]:
    """The live level id + entity count from a native read-only probe."""
    argv = ["python", "-B", str(_DISCOVER), "--queue-dir", str(queue_dir),
            "--queue-timeout", str(timeout_s)]
    code, out = runner(argv)
    text = out.strip()
    start = text.find("{")
    if start < 0:
        return None, [f"discover produced no JSON (exit {code})"]
    try:
        observation = json.loads(text[start:])
    except json.JSONDecodeError as error:
        return None, [f"discover JSON unparseable: {error}"]
    if observation.get("ok") is not True:
        return None, [f"discover refused: {observation.get('error') or observation}"]
    return observation, []


def read_live(queue_dir: Path | str | None = None, *, runner: Runner | None = None) -> LiveState:
    """Read the live sandbox: helper state and the currently-open level."""
    directory = Path(queue_dir) if queue_dir is not None else _DEFAULT_QUEUE
    run = runner or subprocess_runner()

    state = LiveState(ok=False)
    status, errors = helper_status(directory, run)
    state.errors.extend(errors)
    if status is None:
        state.reason = "helper-status-unavailable"
        return state

    state.helper_pid = status.get("pid")
    state.helper_deadline_utc = status.get("deadlineUtc")
    native = status.get("nativeScene") or {}
    state.helper_blocked = native.get("blocked")
    state.helper_actions = tuple(native.get("actions") or ())
    state.pins_digest = native.get("pinsDigest")

    if status.get("elevated") is not True:
        state.reason = "helper-not-elevated"
        return state

    observation, errors = current_level(directory, run)
    state.errors.extend(errors)
    if observation is None:
        state.reason = "live-level-read-failed"
        return state

    state.level_id = observation.get("levelId")
    state.entities = observation.get("entities")
    state.level_verified = bool((observation.get("levelObservation") or {}).get("verified"))
    state.handle = observation.get("handle")
    state.run_dir = observation.get("run")
    state.ok = state.level_id is not None and state.level_verified
    if not state.ok:
        state.reason = "level-identity-unverified"
    return state


def subprocess_runner() -> Runner:
    def run(argv: list[str]) -> tuple[int, str]:
        completed = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8")
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")

    return run


# --------------------------------------------------------------------------- #
# the whole scene in one read-only call
# --------------------------------------------------------------------------- #

@dataclass
class Part:
    """One named piece of the scene.

    ``state`` is always one of the ``*_*`` constants above; a part that could not
    reach its good state carries a ``reason`` and ``ok is False`` -- never a bare
    crash and never a silent default.  ``requested`` is ``False`` only when the
    caller supplied no input for it (e.g. no ``.gil`` for the directory): such a
    part is still reported, but it does not make the scene *incomplete*.
    """

    name: str
    state: str
    ok: bool
    reason: str | None = None
    data: dict = field(default_factory=dict)
    requested: bool = True

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "ok": self.ok,
            "reason": self.reason,
            "requested": self.requested,
            "data": dict(self.data),
        }


@dataclass
class SceneSummary:
    """The live sandbox as seen this instant: helper, level, demo graph, directory."""

    helper: Part
    level: Part
    bridge: Part
    graph: Part
    directory: Part
    errors: list[str] = field(default_factory=list)
    source: str = "native-read"          # never "recorded"

    @property
    def parts(self) -> tuple[Part, ...]:
        return (self.helper, self.level, self.bridge, self.graph, self.directory)

    @property
    def ok(self) -> bool:
        """The scene's primary anchor: the helper is up and the level is verified.

        Matches :attr:`LiveState.ok` -- it says the *live level was read*, not that
        the whole demo is good.  Use :attr:`complete` for that.
        """
        return self.helper.ok and self.level.ok

    @property
    def complete(self) -> bool:
        """Every REQUESTED part reached its good state -- no false success."""
        return all(p.ok for p in self.parts if p.requested)

    @property
    def degraded(self) -> list[str]:
        """Names of the requested parts that are not in their good state."""
        return [p.name for p in self.parts if p.requested and not p.ok]

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "source": self.source,
            "complete": self.complete,
            "degraded": self.degraded,
            "helper": self.helper.as_dict(),
            "level": self.level.as_dict(),
            "bridge": self.bridge.as_dict(),
            "graph": self.graph.as_dict(),
            "directory": self.directory.as_dict(),
            "errors": list(self.errors),
        }


def _valid_run_id(value) -> bool:
    """A bridge run id is a UUID (``author.py`` parses it with ``uuid.UUID``)."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _helper_part(state: LiveState) -> Part:
    data = {
        "pid": state.helper_pid,
        "deadlineUtc": state.helper_deadline_utc,
        "blocked": state.helper_blocked,
        "actions": list(state.helper_actions),
        "pinsDigest": state.pins_digest,
    }
    if state.helper_pid is None:
        return Part("helper", HELPER_DOWN, False,
                    reason=state.reason or "helper status unavailable", data=data)
    if state.reason == "helper-not-elevated":
        return Part("helper", HELPER_NOT_ELEVATED, False,
                    reason="helper is up but not elevated", data=data)
    return Part("helper", HELPER_ACTIVE, True, data=data)


def _level_part(state: LiveState) -> Part:
    data = {
        "levelId": state.level_id,
        "entities": state.entities,
        "verified": state.level_verified,
        "handle": state.handle,
        "runDir": state.run_dir,
    }
    if state.level_verified and state.level_id is not None:
        return Part("level", LEVEL_VERIFIED, True, data=data)
    if state.level_id is not None:
        return Part("level", LEVEL_UNVERIFIED, False,
                    reason=state.reason or "level identity unverified", data=data)
    return Part("level", LEVEL_UNAVAILABLE, False,
                reason=state.reason or "no live level was read", data=data)


def _graph_status_argv(*, python: str, queue_dir: Path, name, graph_id, run_id) -> tuple[list[str], str]:
    """The one ``graph inspect`` dispatch, built exactly as the read ops do.

    This is the graph-status contract shared with ``cli.py:232-240``
    (``cmd_graph_status``) and ``checkpoint.py:191-202``; the request id is a pure
    function of the request (:func:`tools.gameplan.builder.request_id`), so the
    same inputs address the same graph read.  ``test_live`` proves the argv is
    byte-identical to what ``cli.cmd_graph_status`` builds.
    """
    from .builder import request_id

    request = request_id("graph-status", "inspect", name, graph_id, run_id)
    argv = [
        python, "-B", str(_AUTHOR_PY),
        "--elevated-queue", str(queue_dir),
        "graph", "inspect",
        "--request-id", request,
        "--run-id", str(run_id),
        "--name", str(name),
        "--graph-id", str(graph_id),
    ]
    # Structural guarantee: this path can only ever dispatch `inspect`.
    if argv[argv.index("graph") + 1] != "inspect":
        raise AssertionError("the scene graph read must only ever dispatch `graph inspect`")
    return argv, request


def _graph_data(result: dict, *, graph_id, name, run_id, request) -> dict:
    backend = result.get("backend") if isinstance(result.get("backend"), dict) else {}
    nodes = [n for n in (backend.get("nodes") or []) if isinstance(n, dict)]
    return {
        "graphId": graph_id,
        "name": name,
        "runId": str(run_id),
        "requestId": request,
        "status": backend.get("status"),
        "nodeCount": backend.get("nodeCount", len(nodes)),
        "nodeDefinitionIds": [n.get("definitionId") for n in nodes],
        "boundEntityIds": [int(e) for e in (backend.get("boundEntityIds") or [])],
    }


def default_bridge_probe(queue_dir: Path | str) -> BridgeProbe:
    """Is the bridge loaded for a run?  Read-only: the run's ``bridge-ready.json``.

    The bridge writes ``bridge-ready.json`` into its run directory at load time and
    ``accepted`` must be the literal ``true`` (``elevated-request.py:578-579``).  A
    missing or non-``true`` ready file is reported as NOT loaded with a named
    reason -- the probe never raises, and never reads anything but that one file.
    """
    runs = Path(queue_dir).parent / "runs"

    def probe(run_id) -> tuple[bool, str]:
        if run_id is None:
            return False, "no bridge run id supplied (it is never inferred)"
        if not _valid_run_id(run_id):
            return False, f"bridge run id is not a UUID: {run_id!r}"
        ready = runs / str(run_id) / _BRIDGE_READY
        try:
            receipt = json.loads(ready.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return False, f"no {_BRIDGE_READY} for run {run_id}"
        except (OSError, json.JSONDecodeError) as error:
            return False, f"{_BRIDGE_READY} unreadable: {type(error).__name__}: {error}"
        if receipt.get("accepted") is True:
            return True, ""
        return False, f"{_BRIDGE_READY} accepted is {receipt.get('accepted')!r}, not true"

    return probe


def _graph_parts(state: LiveState, *, queue_dir: Path, graph_runner: GraphRunner | None,
                 bridge_probe: BridgeProbe | None, graph_name, graph_id, run_id,
                 python: str) -> tuple[Part, Part]:
    """(bridge, graph) -- the demo graph's status, read only when the bridge is loaded."""
    if not _helper_part(state).ok:
        why = "helper cannot route a graph read"
        return (Part("bridge", BRIDGE_NOT_LOADED, False, reason=why),
                Part("graph", GRAPH_NOT_CHECKED, False, reason=why))

    probe = bridge_probe or default_bridge_probe(queue_dir)
    try:
        loaded, reason = probe(run_id)
    except Exception as error:  # noqa: BLE001 -- a probe must never take the scene down
        loaded, reason = False, f"bridge probe raised {type(error).__name__}: {error}"
    if not loaded:
        return (Part("bridge", BRIDGE_NOT_LOADED, False, reason=reason or "bridge not loaded"),
                Part("graph", GRAPH_NOT_CHECKED, False, reason=reason or "bridge not loaded"))

    bridge = Part("bridge", BRIDGE_LOADED, True, data={"runId": str(run_id)})

    if not graph_name or graph_id is None:
        return bridge, Part("graph", GRAPH_NOT_CHECKED, False,
                            reason="bridge loaded but no graph name/id supplied")
    if graph_runner is None:
        return bridge, Part("graph", GRAPH_NOT_CHECKED, False,
                            reason="bridge loaded but no inspect runner supplied")

    argv, request = _graph_status_argv(python=python, queue_dir=queue_dir, name=graph_name,
                                       graph_id=graph_id, run_id=run_id)
    try:
        result = graph_runner(argv)
    except Exception as error:  # noqa: BLE001 -- a failed read is a named state, not a crash
        return bridge, Part("graph", GRAPH_ABSENT, False,
                            reason=f"graph inspect raised {type(error).__name__}: {error}",
                            data={"graphId": graph_id, "name": graph_name,
                                  "runId": str(run_id), "requestId": request})
    if not isinstance(result, dict):
        return bridge, Part("graph", GRAPH_ABSENT, False,
                            reason=f"graph inspect runner returned {type(result).__name__}",
                            data={"graphId": graph_id, "name": graph_name,
                                  "runId": str(run_id), "requestId": request})

    data = _graph_data(result, graph_id=graph_id, name=graph_name, run_id=run_id, request=request)
    if result.get("ok") is True:
        return bridge, Part("graph", GRAPH_PRESENT, True, data=data)
    return bridge, Part("graph", GRAPH_ABSENT, False,
                        reason=f"graph inspect refused: {result.get('error') or result}",
                        data=data)


def default_directory_reader():
    """Resolve :func:`level_directory.check_directory` lazily, or ``None`` if absent."""
    import sys

    if str(_BEYOND_SAVE) not in sys.path:
        sys.path.insert(0, str(_BEYOND_SAVE))
    try:
        import level_directory  # type: ignore
    except Exception:  # noqa: BLE001 -- an absent module is a named state, not a crash
        return None
    return level_directory.check_directory


def _directory_part(gil_path, directory_reader) -> Part:
    if gil_path is None:
        return Part("directory", DIRECTORY_NOT_CHECKED, False,
                    reason="no .gil path supplied to check the directory", requested=False)

    reader = directory_reader if directory_reader is not None else default_directory_reader()
    if reader is None:
        return Part("directory", DIRECTORY_NOT_CHECKED, False,
                    reason="level_directory.check_directory unavailable")

    try:
        defects = list(reader(gil_path))
    except Exception as error:  # noqa: BLE001 -- a failed read is a named state, not a crash
        return Part("directory", DIRECTORY_NOT_CHECKED, False,
                    reason=f"directory read failed: {type(error).__name__}: {error}",
                    data={"path": str(gil_path)})

    data = {
        "path": str(gil_path),
        "defectCount": len(defects),
        "defects": [{"code": getattr(d, "code", None),
                     "index": getattr(d, "index", None),
                     "detail": getattr(d, "detail", str(d))} for d in defects],
    }
    if defects:
        return Part("directory", DIRECTORY_DEFECTIVE, False,
                    reason=f"{len(defects)} defect(s) in the root-field-6 directory", data=data)
    return Part("directory", DIRECTORY_CLEAN, True, data=data)


def read_scene(queue_dir: Path | str | None = None, *,
               runner: Runner | None = None,
               graph_runner: GraphRunner | None = None,
               bridge_probe: BridgeProbe | None = None,
               directory_reader=None,
               graph_name: str | None = None,
               graph_id: int | None = None,
               run_id: str | None = None,
               python: str = "python",
               gil_path: Path | str | None = None) -> SceneSummary:
    """Read the WHOLE scene in one call: helper, level, demo graph, directory.

    Every reader is injectable (``runner`` for the native reads, ``graph_runner``
    for the ``graph inspect`` read, ``bridge_probe`` for the bridge's ready file,
    ``directory_reader`` for the ``.gil`` directory) so the composition is fully
    testable offline, and every path degrades to a named state -- an injected
    reader that raises becomes a ``reason``, never a traceback.
    """
    directory = Path(queue_dir) if queue_dir is not None else _DEFAULT_QUEUE
    live_run = runner or subprocess_runner()

    state = read_live(directory, runner=live_run)
    helper = _helper_part(state)
    level = _level_part(state)
    bridge, graph = _graph_parts(state, queue_dir=directory, graph_runner=graph_runner,
                                 bridge_probe=bridge_probe, graph_name=graph_name,
                                 graph_id=graph_id, run_id=run_id, python=python)
    directory_part = _directory_part(gil_path, directory_reader)

    return SceneSummary(helper=helper, level=level, bridge=bridge, graph=graph,
                        directory=directory_part, errors=list(state.errors))


def main(argv=None) -> int:
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="gameplan live",
        description="Read the currently-open sandbox (native read-only), never a recorded id.")
    parser.add_argument("--queue-dir", default=str(_DEFAULT_QUEUE))
    parser.add_argument("--scene", action="store_true",
                        help="compose the WHOLE scene in one read-only call: helper state, "
                             "live level + entity count, the demo graph, and (with --gil) the "
                             "root-field-6 directory health")
    parser.add_argument("--run-id", default=None,
                        help="live bridge run id (a UUID); the bridge is read for THIS run and "
                             "nothing is inferred (a graph id is a function of the save)")
    parser.add_argument("--graph-name", default=None, help="MW_API_… graph name (needed to inspect)")
    parser.add_argument("--graph-id", type=int, default=None, help="uint32 graph id")
    parser.add_argument("--gil", default=None, help="a .gil whose root-field-6 directory to check")
    parser.add_argument("--python", default="python")
    args = parser.parse_args(argv)

    if args.scene:
        scene = read_scene(args.queue_dir, run_id=args.run_id, graph_name=args.graph_name,
                           graph_id=args.graph_id, gil_path=args.gil, python=args.python)
        print(json.dumps(scene.summary(), ensure_ascii=False, indent=2))
        return 0 if scene.ok else 1

    state = read_live(args.queue_dir)
    print(json.dumps(state.summary(), ensure_ascii=False, indent=2))
    return 0 if state.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
