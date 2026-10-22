"""Method implementations.

Runtime, implemented here:

``mw.capabilities.get``  what exists, with an honest label on each entry
``mw.runtime.status``    read-only observation of the frozen targets
``mw.runtime.start``     launch one allowlisted executable, then look

Asset domain, delegated to ``mvp/asset_api.py``:

``mw.scene.build``       locked, idempotent, revision-checked; in-project only
``mw.catalog.search``    read-only
``mw.asset.inspect``     read-only
``mw.build.validate``    read-only

Import, save and playtest remain ``implemented: false`` /
``availability: "unavailable"``. Nothing here pretends to touch the sandbox,
import into the game, save a project or run a playtest.
"""

from __future__ import annotations

import os
import time
from typing import Any

from . import BRIDGE_VERSION
from .errors import PHASES, BridgeError
from .journal import FoldedState, JournalCorrupt, read_records
from .launcher import Launcher
from .osbackend import ProcessBackend
from .protocol import (
    ASSET_METHODS,
    ASSET_READ_METHODS,
    PROJECT_ID,
    SNAPSHOT_TARGET,
    make_response,
    parse_params,
)
from .state import BridgeStore, Session
from .elevation import (
    ELEVATION_ERROR_KINDS,
    ELEVATION_NONE,
    ELEVATION_REQUEST,
    ELEVATION_TARGETS,
    ELEVATION_VALUES,
)
from .targets import (
    DEFAULT_TARGET,
    FROZEN_TARGETS,
    OBSERVATION_ALIASES,
    TARGET_KEYS,
    find_launcher_version_dirs,
    read_install_fingerprint,
    resolve_target,
    target_exists,
)
from .util import canonical_json, sha256_hex, utc_now

CAPABILITIES_PARAMS = frozenset({"refresh"})
STATUS_PARAMS = frozenset({"refresh"})
START_PARAMS = frozenset({"target", "observeTimeoutMs", "elevation"})
#: No `hwnd`, no `pid`, no `path`, no `rect`, no `format`. The only parameter is
#: a target *key*, and only one value of it is accepted.
SNAPSHOT_PARAMS = frozenset({"target"})

#: Derived from ``__file__``, never from cwd: the evidence path in a response must
#: describe a fixed location, not wherever the process happened to be started.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: How the captured window was tied to a process. Two sources, and the response
#: always says which one was used -- they are not interchangeable.
BINDING_EXECUTABLE_PATH = "executable-path"
BINDING_LAUNCH_JOURNAL = "launch-journal"

#: ``elevation`` chooses between two fixed ways of starting the *same* allowlisted
#: executable. It is not a general "run this as administrator" switch: only the
#: frozen targets in ``ELEVATION_TARGETS`` accept it, and the path and argv still
#: come from ``bridge.targets``.
ELEVATION_DEFAULT = ELEVATION_NONE

REFRESH_VALUES = frozenset({"default", "force"})

MAX_OBSERVE_MS = 10_000
DEFAULT_OBSERVE_MS = 3_000
POLL_INTERVAL_S = 0.15

#: The bridge has no way to tell whether the sandbox loaded. It therefore never
#: reports readiness at all -- this constant exists so that "not verified" is a
#: value in the response rather than an omission a reader could fill in.
SANDBOX_READINESS: dict[str, Any] = {
    "state": "not-verified",
    "note": (
        "A running process is not a ready sandbox. This bridge can observe that "
        "an executable is running; it cannot observe that a project loaded, that "
        "the editor is in a usable mode, or that any Miliastra capability is "
        "available. No method here reports readiness, and none returns "
        "'succeeded' for a launch."
    ),
}

UNIMPLEMENTED_DOMAINS: dict[str, str] = {
    "import": (
        "Deploying assets into the game via the official external-asset import path "
        "is not implemented."
    ),
    "save": "Saving a project and reading back post-save state is not implemented.",
    "playtest": (
        "Starting a playtest run, collecting assertions and producing a report is "
        "not implemented."
    ),
}

#: Contract methods this bridge knowingly does not implement. Listed so that
#: "not implemented" is exhaustive rather than a short list that looks complete.
UNIMPLEMENTED_CONTRACT_METHODS = (
    "mw.project.inspect",
    "mw.project.validate",
    "mw.project.save",
    "mw.object.get",
    "mw.logs.read",
    "mw.evidence.read",
    "mw.logic.compile",
    "mw.asset.patch",
    "mw.change.plan",
    "mw.change.apply",
    "mw.change.restore",
    "mw.operation.get",
    "mw.operation.cancel",
    "mw.operation.reconcile",
    "mw.test.start",
    "mw.test.report",
    "mw.test.stop",
)

#: What a window capture does and does not establish. Repeated in the response
#: so no reader has to infer it from a field name.
SNAPSHOT_MEANING = (
    "CAPTURE ONLY. This is a picture of one top-level window of the frozen game "
    "process, produced by PrintWindow. The bridge does not interpret it. It is "
    "returned so the main agent can look at it -- nothing here recognizes the "
    "Miliastra editor, a project, a mode, an account or a scene, and no image, "
    "title or size is evidence that the sandbox is ready. The window title is "
    "reported as the OS gave it and proves nothing about 千星; it is never used to "
    "infer what the game is showing. No desktop BitBlt is performed, so no other "
    "application can appear in this image."
)

UNOBSERVABLE_DOMAINS = (
    "editor-mode",
    "project-identity",
    "project-revision",
    "sandbox-readiness",
    "scene",
    "build",
    "import",
    "save",
    "playtest",
)


def _is_under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))]
        ) == os.path.normcase(os.path.abspath(root))
    except ValueError:
        # Different drives or an empty path: not under the root.
        return False


def _match_processes(
    target: str, spec: dict[str, str], processes: list[Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify each process against the target's frozen path and its aliases.

    Returns ``(matched, unverified)``. Only allowlisted executables (and their
    declared aliases) are ever returned, so a response cannot leak an inventory of
    what else the user is running.

    Strength is distinguished because the kinds of evidence are not equal: an
    exact executable path is proof, a declared alias whose path *is* readable and
    falls inside the install root is still proof, and an alias matched by name
    alone (path unreadable) is a declared, documented inference.

    The second list is a different thing entirely. A process whose *name* equals
    the frozen executable's basename but whose path cannot be read is **not a
    match** -- it is an open question. It goes in ``unverified`` and never in
    ``matched``, so nothing downstream can mistake it for confirmation.
    """
    primary = os.path.normcase(spec["executablePath"])
    primary_name = os.path.basename(spec["executablePath"]).casefold()
    aliases = OBSERVATION_ALIASES.get(target, ())
    matched: list[dict[str, Any]] = []
    claimed: set[int] = set()

    for info in processes:
        path = info.executable_path
        if path and os.path.normcase(path) == primary:
            entry = info.to_dict()
            entry.update({"matchKind": "executable-path", "matchStrength": "strong"})
            matched.append(entry)
            claimed.add(info.pid)
            continue
        for alias in aliases:
            if (info.name or "").casefold() != alias["value"].casefold():
                continue
            if path:
                # A readable path must be inside the frozen install root, or this
                # is somebody else's copy of the binary and none of our business.
                if not _is_under(path, alias["scope"]):
                    continue
                entry = info.to_dict()
                entry.update(
                    {"matchKind": f"{alias['kind']}:path-in-install-root", "matchStrength": "strong"}
                )
            else:
                entry = info.to_dict()
                entry.update(
                    {"matchKind": f"{alias['kind']}:path-unreadable", "matchStrength": "weak"}
                )
            matched.append(entry)
            claimed.add(info.pid)

    unverified: list[dict[str, Any]] = []
    for info in processes:
        if info.pid in claimed or info.executable_path:
            continue
        if (info.name or "").casefold() != primary_name:
            continue
        entry = info.to_dict()
        entry.update(
            {
                "matchKind": "executable-name:path-unreadable",
                "reason": "path-unreadable",
                "verified": False,
                "matchStrength": None,
            }
        )
        unverified.append(entry)

    matched.sort(key=lambda item: (item["matchStrength"] != "strong", item["pid"]))
    unverified.sort(key=lambda item: item["pid"])
    return matched, unverified


def observe_targets(
    processes: list[Any], *, simulated: bool, known: bool
) -> dict[str, dict[str, Any]]:
    """Map the process table onto the frozen targets.

    ``running`` is three-valued on purpose. An unreadable-path candidate makes it
    ``None`` with ``runningKnown`` false: we cannot say the target is running and
    we must not say it is not.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, spec in FROZEN_TARGETS.items():
        matched, unverified = _match_processes(key, spec, processes) if known else ([], [])
        has_strong = any(m["matchStrength"] == "strong" for m in matched)
        if not known or unverified:
            running: bool | None = None
        else:
            running = bool(matched)
        out[key] = {
            "target": key,
            "displayName": spec["displayName"],
            "executablePath": spec["executablePath"],
            "exists": target_exists(key),
            "runningKnown": running is not None,
            "running": running,
            "matchStrength": ("strong" if has_strong else "weak") if matched else None,
            "processes": matched,
            # Same-named processes whose path could not be read. Never counted as
            # matches, never promoted to `running`.
            "unverifiedCandidates": unverified,
            "observationAliases": [
                {k: v for k, v in alias.items()} for alias in OBSERVATION_ALIASES.get(key, ())
            ],
            "simulated": simulated,
        }
    return out


def weak_match_warning(target: str, info: dict[str, Any]) -> str | None:
    """Explain an inference that is not a proof, rather than letting it pass silently."""
    if info.get("matchStrength") != "weak":
        return None
    return (
        f"WEAK_PROCESS_MATCH[{target}]: reported as running from a process-name alias "
        f"only, because the process's ExecutablePath is unreadable. This shows a "
        f"process of that name exists; it does not prove which installation it "
        f"belongs to."
    )


def unverified_warning(target: str, info: dict[str, Any]) -> str | None:
    """Say out loud that a same-named process is an open question, not a match."""
    candidates = info.get("unverifiedCandidates") or []
    if not candidates:
        return None
    pids = ", ".join(str(c.get("pid")) for c in candidates)
    name = os.path.basename(info["executablePath"])
    return (
        f"UNVERIFIED_PROCESS_CANDIDATE[{target}]: {len(candidates)} process(es) named "
        f"{name} exist whose ExecutablePath is unreadable (pid {pids}). 'running' is "
        f"null (unknown), not false: this shows a process of that name exists but "
        f"does not prove which installation it belongs to."
    )


def find_launch_journal_binding(
    journal_path: Any,
    *,
    pid: Any,
    name: Any,
    creation_date: Any,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    """Bind one path-unreadable candidate to a launch *this project* recorded.

    An elevated process's ``ExecutablePath`` is unreadable through CIM, so the
    live process table alone can never confirm it. But when this project started
    that process, it wrote down which pid it got back and later observed that pid
    with its creation date. That record, matched against the **live** process on
    pid *and* creation date *and* name, is evidence -- and it is the only thing
    accepted here.

    Three narrowings, each of which is a way this could lie:

    ``real only``   A mock journal proves nothing about this machine. Only the
                    real journal is read, only records stamped ``mode: real``
                    are considered, and any record marked ``simulated`` is
                    skipped. A simulated launch is not a launch.
    ``creation date``  A pid alone is a shared resource: Windows reuses them.
                    Requiring the creation date to equal the one recorded for
                    that pid is what separates "the process we started" from
                    "some later process that happened to land on the same pid".
    ``returned=true``  A terminal record whose launch did not return a process
                    is not evidence that a process exists.

    Returns ``(record, reason, detail)``. ``record`` is ``None`` unless every
    check passed, and ``reason`` names the closest miss so a refusal is
    diagnosable rather than mysterious.
    """
    if not pid:
        return None, "candidate-has-no-pid", {}
    if not creation_date:
        # Without a creation date there is no way to tell this process from a
        # later one that reuses the pid, so there is nothing to match on.
        return None, "candidate-has-no-creation-date", {}

    try:
        records, _issues = read_records(journal_path)
    except JournalCorrupt as exc:
        return None, "journal-corrupt", {"error": str(exc)}

    nearest: str | None = None
    nearest_detail: dict[str, Any] = {}
    match: dict[str, Any] | None = None
    for record in records:
        if record.get("kind") != "terminal" or record.get("mode") != "real":
            continue
        payload = record.get("data") or {}
        if payload.get("simulated"):
            continue
        terminal = (payload.get("envelope") or {}).get("data") or {}
        if terminal.get("target") != SNAPSHOT_TARGET or terminal.get("simulated"):
            continue
        launch = terminal.get("launch") or {}
        if launch.get("simulated") or not launch.get("returned"):
            continue
        if int(launch.get("pid") or 0) != int(pid):
            continue

        observed = terminal.get("observedProcess") or {}
        if int(observed.get("pid") or 0) != int(pid):
            continue

        found = {
            "journalPath": str(journal_path),
            "journalSeq": record.get("seq"),
            "recordedAt": record.get("ts"),
            "operationId": payload.get("operationId"),
            "effectState": payload.get("effectState"),
            "launchPid": launch.get("pid"),
            "launchElevation": launch.get("elevation"),
            "pidOnlyMatch": bool(terminal.get("pidOnlyMatch")),
            "observedCreationDate": observed.get("creationDate"),
            "observedName": observed.get("name"),
            "observedMatchKind": observed.get("matchKind"),
            # What this project asked to start. Recorded by us, not read from
            # the live process -- which is exactly why the live path stays null.
            "launchedExecutablePath": (terminal.get("request") or {}).get("executablePath"),
        }

        if observed.get("creationDate") != creation_date:
            nearest, nearest_detail = "creation-date-mismatch", found
            continue
        if name and observed.get("name") and observed["name"].casefold() != str(name).casefold():
            nearest, nearest_detail = "name-mismatch", found
            continue
        match = found
        break

    if match is None:
        return None, nearest or "no-real-launch-record-for-pid", nearest_detail
    return match, "matched", match


def poll_target(
    backend: ProcessBackend, target: str, want_pid: int | None, timeout_ms: int
) -> tuple[dict[str, Any] | None, bool, bool]:
    """Look for the target process, preferring the PID we just created.

    Returns ``(observation, pid_matched, query_ok)``. A PID that never appears
    is not proof of failure -- the process may have exited after handing off --
    so this reports what it saw rather than a verdict.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    saw_any: dict[str, Any] | None = None
    query_ok = True
    while True:
        query_ok, processes = backend.query()
        if query_ok:
            info = observe_targets(processes, simulated=backend.simulated, known=True)[target]
            if info["running"]:
                saw_any = info
                # Only a strong (path) match can confirm the PID we just created.
                # A name-only alias match is not evidence about *our* process.
                if want_pid is not None and any(
                    p["pid"] == want_pid and p["matchStrength"] == "strong"
                    for p in info["processes"]
                ):
                    return info, True, True
        if time.monotonic() >= deadline:
            return saw_any, False, query_ok
        time.sleep(POLL_INTERVAL_S)


class Bridge:
    """Method dispatcher. Deterministic given its store, backend and launcher."""

    def __init__(
        self,
        store: BridgeStore,
        backend: ProcessBackend,
        launcher: Launcher,
        asset_api: Any | None = None,
        window_backend: Any | None = None,
    ) -> None:
        self.store = store
        self.backend = backend
        self.launcher = launcher
        self.asset_api = asset_api
        self._asset_params: dict[str, Any] | None = None
        if window_backend is None:
            from .window import RealWindowBackend  # local: keeps import cost off unrelated calls

            window_backend = RealWindowBackend()
        self.window_backend = window_backend

    # ------------------------------------------------------------------ shared

    def _warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.backend.simulated:
            warnings.append(
                "OS_BACKEND_IS_MOCK: process observations are simulated and are not "
                "evidence about this machine."
            )
        if self.launcher.simulated:
            warnings.append("LAUNCHER_IS_MOCK: no process was or will be started.")
        if self.window_backend.simulated:
            warnings.append(
                "WINDOW_BACKEND_IS_MOCK: no window was enumerated and no screen was "
                "read; the capture is simulated and is not evidence about this machine."
            )
        return warnings

    def _backend_info(self) -> dict[str, Any]:
        info = self.backend.probe().to_dict()
        error = getattr(self.backend, "last_error", None)
        if error:
            info["lastError"] = error
        return info

    def _observation(
        self,
        revision: int,
        *,
        source: str,
        coverage: list[str],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "revision": str(revision),
            "source": source,
            "coverage": coverage,
            "unknownDomains": list(UNOBSERVABLE_DOMAINS),
            "observedAt": utc_now(),
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def _check_refresh(params: dict[str, Any], method: str) -> str:
        refresh = params.get("refresh", "default")
        if refresh not in REFRESH_VALUES:
            raise BridgeError(
                "VALIDATION_FAILED",
                f"refresh must be one of {sorted(REFRESH_VALUES)}",
                details={"method": method, "received": refresh},
            )
        return refresh

    @staticmethod
    def _respond(
        request: dict[str, Any],
        status: str,
        envelope: dict[str, Any],
        error: BridgeError | None = None,
    ) -> dict[str, Any]:
        return make_response(
            request["requestId"],
            status,
            data=envelope["data"],
            observation=envelope["observation"],
            evidence=envelope["evidence"],
            warnings=envelope["warnings"],
            error=error.to_dict() if error else None,
        )

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request["method"]
        if method == "mw.capabilities.get":
            return self.capabilities(request)
        if method == "mw.runtime.status":
            return self.status(request)
        if method == "mw.runtime.start":
            return self.start(request)
        if method == "mw.snapshot.capture":
            return self.snapshot_capture(request)
        if method == "mw.window.restore":
            return self.window_restore(request)
        if method in ASSET_READ_METHODS:
            return self.asset_read(request)
        if method in ASSET_METHODS:
            return self.asset_build(request)
        raise BridgeError("METHOD_UNKNOWN", f"method {method!r} is not implemented")

    # ------------------------------------------------------------ capabilities

    def capabilities(self, request: dict[str, Any]) -> dict[str, Any]:
        params = parse_params(request["params"], CAPABILITIES_PARAMS, request["method"])
        self._check_refresh(params, request["method"])

        state, _ = self.store.read_state()
        backend = self._backend_info()
        query_ok, processes = self.backend.query() if backend["available"] else (False, [])
        targets = observe_targets(processes, simulated=self.backend.simulated, known=query_ok)

        any_target_present = any(t["exists"] for t in targets.values())
        observe_available = bool(backend["available"] and query_ok)
        launch_available = bool(observe_available and any_target_present)

        if self.backend.simulated:
            observe_level = "offline-tested"
        elif observe_available:
            observe_level = "live-read-tested"
        else:
            observe_level = "offline-tested"

        capabilities: dict[str, Any] = {
            "runtime.observe": {
                "implemented": True,
                "availability": "available" if observe_available else "unavailable",
                "evidenceLevel": observe_level,
                "verifiedLive": observe_available and not self.backend.simulated,
                "method": "mw.runtime.status",
                "summary": "Read-only observation of the two frozen executables.",
                "limitations": [
                    "Sees an executable path in the process table. Cannot see which "
                    "project, account, mode or window state it is in.",
                    "A failed query is reported as unknown, never as 'not running'.",
                ],
            },
            "runtime.launch": {
                "implemented": True,
                "availability": "available" if launch_available else "unavailable",
                "evidenceLevel": "offline-tested",
                "verifiedLive": False,
                "method": "mw.runtime.start",
                "summary": (
                    "Starts one of the two allowlisted executables and then observes "
                    "the process table. Never claims readiness."
                ),
                "limitations": [
                    "No live launch has been performed as part of this deliverable; "
                    "the transition from 'offline-tested' to 'live-write-tested' is "
                    "deliberately not claimed.",
                    "Accepts no executable path, no command line, no arguments and no "
                    "shell. Only target keys 'launcher' and 'game' are accepted.",
                    "Launching is not importing, saving or testing. Sandbox readiness "
                    "is never reported.",
                ],
            },
        }

        capabilities["snapshot"] = {
            "implemented": True,
            # A capture needs something to capture; with no target process there is
            # no window to bind to, so the method reports itself unavailable rather
            # than failing at call time for a reason the caller could have read.
            "availability": "available" if launch_available else "unavailable",
            "evidenceLevel": "offline-tested",
            "verifiedLive": False,
            "method": "mw.snapshot.capture",
            "summary": (
                "Captures one visible top-level window with "
                "PrintWindow(PW_RENDERFULLCONTENT) and writes it to a unique BMP under "
                ".runtime/bridge/evidence/: either the running frozen game process, or "
                "the editor session the user opened and confirmed (target 'editor')."
            ),
            "limitations": [
                "Read-only, and capture only: the image is for the main agent to look "
                "at. Nothing here interprets it, and neither the image nor the window "
                "title is evidence of sandbox readiness, editor mode or project identity.",
                "Accepts only params {} or {\"target\": \"game\" | \"editor\"}. No hwnd, "
                "pid, path, rectangle or format can be supplied, and the output path is "
                "fixed.",
                "'target': 'editor' observes a session the *user* opened -- this bridge "
                "never starts the editor, has no method that does, and issues no window "
                "command for it. Its process is matched by name only (no install path is "
                "frozen for the editor), so installationVerified stays false and the "
                "observation strength is 'candidate'; the window is the one whose title "
                "is exactly 千星沙箱 and whose class carries the WPF prefix "
                "HwndWrapper[BeyondEditor;. Two such windows are refused, not guessed at.",
                "An elevated game process has no readable ExecutablePath, so it is "
                "bound through this project's real launch journal instead: pid, "
                "creation date and name must all match a terminal launch record. "
                "pathKnown stays false and the live path is reported as null. Mock "
                "journals are never accepted as evidence.",
                "No desktop BitBlt fallback exists: if PrintWindow draws nothing, the "
                "result is 'partial' or 'unavailable', never a screenshot of the screen.",
                "'verifiedLive' stays false: no live capture has been performed as part "
                "of this deliverable, so this is offline-tested only.",
            ],
        }

        capabilities["window"] = {
            "implemented": True,
            "availability": "available" if launch_available else "unavailable",
            "evidenceLevel": "offline-tested",
            "verifiedLive": False,
            "method": "mw.window.restore",
            "summary": (
                "Asks the one bound game window to un-minimize with "
                "ShowWindowAsync(hwnd, SW_RESTORE). Sends no input, takes no focus and "
                "starts nothing."
            ),
            "limitations": [
                "'restore-requested' means the request was queued, not that the window "
                "is restored. The response carries IsIconic and GetWindowRect read back "
                "after a bounded wait, and reports 'restore-requested-still-minimized' "
                "when the owning thread had not applied it.",
                "A window state is not sandbox readiness. Nothing here reports readiness "
                "or interprets what the window shows.",
                "Accepts only params {} or {\"target\": \"game\"}. No hwnd, pid, rect, "
                "command or output path can be supplied.",
                "No keyboard or mouse input, no SetForegroundWindow, no elevation, no "
                "process started, no game or system setting changed.",
            ],
        }

        # --- asset domain (delegated to mvp/asset_api.py) --------------------
        if self.asset_api is not None:
            limits_common = [
                "Produces content-addressed artifacts inside this project only. "
                "Nothing is imported into, rendered by or accepted by the game.",
                "gameAccepted is reported as 'unknown' and is not a claim of game "
                "compatibility.",
            ]
            capabilities["scene"] = {
                "implemented": True,
                "availability": "available",
                "evidenceLevel": "offline-tested",
                "verifiedLive": False,
                "method": "mw.scene.build",
                "summary": "Builds a scene document into an in-project artifact.",
                "limitations": limits_common,
            }
            capabilities["build"] = {
                "implemented": True,
                "availability": "available",
                "evidenceLevel": "offline-tested",
                "verifiedLive": False,
                "method": "mw.build.validate",
                "summary": "Statically validates a build artifact against its scene.",
                "limitations": limits_common
                + ["Compilation succeeding is not evidence of game compatibility."],
            }
            capabilities["catalog"] = {
                "implemented": True,
                "availability": "available",
                "evidenceLevel": "offline-tested",
                "verifiedLive": False,
                "method": "mw.catalog.search",
                "summary": "Read-only search over the project's asset catalog.",
                "limitations": limits_common,
            }
            capabilities["asset"] = {
                "implemented": True,
                "availability": "available",
                "evidenceLevel": "offline-tested",
                "verifiedLive": False,
                "method": "mw.asset.inspect",
                "summary": "Read-only container inspection of a build artifact.",
                "limitations": limits_common,
            }
        else:
            for domain in ("scene", "build", "catalog", "asset"):
                capabilities[domain] = {
                    "implemented": False,
                    "availability": "unavailable",
                    "evidenceLevel": "none",
                    "verifiedLive": False,
                    "method": None,
                    "summary": "mvp/asset_api.py could not be imported.",
                    "limitations": ["The delegated asset module is not importable."],
                }

        for domain, reason in UNIMPLEMENTED_DOMAINS.items():
            capabilities[domain] = {
                "implemented": False,
                "availability": "unavailable",
                "evidenceLevel": "none",
                "verifiedLive": False,
                "method": None,
                "summary": reason,
                "limitations": ["No implementation exists. Do not treat this as a gap "
                                "in search results; it is a missing capability."],
            }

        data = {
            "projectId": PROJECT_ID,
            "bridgeVersion": BRIDGE_VERSION,
            "capabilities": capabilities,
            "unimplemented": {
                "domains": sorted(UNIMPLEMENTED_DOMAINS),
                "contractMethods": list(UNIMPLEMENTED_CONTRACT_METHODS),
                "note": (
                    "scene, build, import, save and playtest are not implemented and "
                    "report availability 'unavailable'. The remaining contract methods "
                    "listed here are likewise absent."
                ),
            },
            "backend": backend,
            "launcher": self.launcher.describe(),
            "assetApi": (self.asset_api.describe() if self.asset_api is not None else None),
            "fingerprint": read_install_fingerprint(),
            "targets": targets,
            "observationAliasEvidence": find_launcher_version_dirs(),
            "stateRoot": str(self.store.paths.root),
            "stateRootInUse": str(self.store.paths.base),
            "stateMode": self.store.mode,
            "revision": str(state.revision),
            "protocol": {
                "protocolVersion": request["protocolVersion"],
                "strictParams": True,
                "note": (
                    "Unknown top-level fields and unknown params are rejected. "
                    "JSON is one request in on stdin, one response out on stdout."
                ),
            },
        }
        return make_response(
            request["requestId"],
            "succeeded",
            data=data,
            observation=self._observation(
                state.revision,
                source="bridge-capability-report",
                coverage=["runtime-observe", "runtime-launch", "installation-files"],
                extra={"targetsKnown": query_ok},
            ),
            evidence=[
                {
                    "artifactId": f"install-root:{os.path.normcase(FROZEN_TARGETS['launcher']['executablePath'])}",
                    "kind": "installation-fingerprint",
                    "simulated": False,
                }
            ],
            warnings=self._warnings(),
        )

    # ------------------------------------------------------------------ status

    def status(self, request: dict[str, Any]) -> dict[str, Any]:
        params = parse_params(request["params"], STATUS_PARAMS, request["method"])
        self._check_refresh(params, request["method"])

        state, issues = self.store.read_state()
        backend = self._backend_info()
        query_ok, processes = self.backend.query() if backend["available"] else (False, [])
        targets = observe_targets(processes, simulated=self.backend.simulated, known=query_ok)

        warnings = self._warnings()
        if not query_ok:
            warnings.append(
                "PROCESS_QUERY_FAILED: the process table could not be read; 'running' "
                "is null (unknown) rather than false."
            )
        for key, info in targets.items():
            for note in (weak_match_warning(key, info), unverified_warning(key, info)):
                if note:
                    warnings.append(note)

        expected = request.get("expectedRevision")
        if expected is not None and expected != str(state.revision):
            warnings.append(
                f"STALE_OBSERVATION: caller expected revision {expected}, current is "
                f"{state.revision}. Read-only calls do not fail on a stale revision; "
                f"the fresh value is returned below."
            )

        data = {
            "projectId": PROJECT_ID,
            "bridgeVersion": BRIDGE_VERSION,
            "sandboxReadiness": SANDBOX_READINESS,
            "backend": backend,
            "launcher": self.launcher.describe(),
            "targets": targets,
            "observationAliasEvidence": find_launcher_version_dirs(),
            "stateRoot": str(self.store.paths.root),
            "stateRootInUse": str(self.store.paths.base),
            "stateMode": self.store.mode,
            "journalMode": state.mode,
            "processQuery": {
                "ok": query_ok,
                "backendKind": backend["kind"],
                "simulated": self.backend.simulated,
                "observedAt": utc_now(),
            },
            "revision": str(state.revision),
            "unresolvedOperations": state.unresolved_operations,
            "journal": {
                "path": str(self.store.paths.journal),
                "records": state.record_count,
                "lastFence": state.last_fence,
                "skippedLines": issues,
            },
            "idempotencyKeys": [
                {"method": method, "key": key, "state": entry["state"]}
                for (method, key), entry in sorted(state.idempotency.items())
            ][:50],
        }
        return make_response(
            request["requestId"],
            "succeeded",
            data=data,
            observation=self._observation(
                state.revision,
                source="os-process-query" if not self.backend.simulated else "mock-process-query",
                coverage=["process-table"] if query_ok else [],
                extra={"queryOk": query_ok, "simulated": self.backend.simulated},
            ),
            warnings=warnings,
        )

    # ------------------------------------------------------------------- start

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        method = request["method"]
        params = parse_params(request["params"], START_PARAMS, method)

        target = params.get("target", DEFAULT_TARGET)
        if target not in TARGET_KEYS:
            raise BridgeError(
                "TARGET_NOT_ALLOWED",
                f"target must be one of {sorted(TARGET_KEYS)}; free-form executable "
                f"paths are not accepted",
                phase="validate",
                details={"allowedTargets": sorted(TARGET_KEYS), "received": target},
            )

        elevation = params.get("elevation", ELEVATION_DEFAULT)
        if elevation not in ELEVATION_VALUES:
            raise BridgeError(
                "VALIDATION_FAILED",
                f"elevation must be one of {sorted(ELEVATION_VALUES)}",
                details={"received": elevation, "allowedValues": sorted(ELEVATION_VALUES)},
            )
        if elevation == ELEVATION_REQUEST and target not in ELEVATION_TARGETS:
            raise BridgeError(
                "TARGET_NOT_ALLOWED",
                "explicit elevation is available only for the frozen target(s) "
                f"{sorted(ELEVATION_TARGETS)}; it is not a general way to start another "
                "program as administrator",
                phase="authorize",
                details={
                    "target": target,
                    "elevationTargets": sorted(ELEVATION_TARGETS),
                    "note": "The caller still supplies no path, argv or shell command.",
                },
            )

        observe_ms = params.get("observeTimeoutMs", DEFAULT_OBSERVE_MS)
        if isinstance(observe_ms, bool) or not isinstance(observe_ms, int):
            raise BridgeError(
                "VALIDATION_FAILED",
                "observeTimeoutMs must be an integer",
                details={"received": observe_ms},
            )
        if not 0 <= observe_ms <= MAX_OBSERVE_MS:
            raise BridgeError(
                "VALIDATION_FAILED",
                f"observeTimeoutMs must be within 0..{MAX_OBSERVE_MS}",
                details={"received": observe_ms},
            )

        spec = resolve_target(target)
        key = request["idempotencyKey"]
        request_hash = sha256_hex(
            canonical_json({"method": method, "projectId": PROJECT_ID, "params": params})
        )

        with self.store.locked() as session:
            existing = session.state.idempotency.get((method, key))
            if existing is not None:
                return self._replay(request, session, existing, key, request_hash)

            expected = request["expectedRevision"]
            current = str(session.state.revision)
            if expected != current:
                raise BridgeError(
                    "STALE_REVISION",
                    f"expectedRevision {expected} does not match current revision {current}",
                    phase="authorize",
                    retryable=True,
                    details={"expected": expected, "current": current},
                )

            return self._perform_start(request, session, target, spec, observe_ms, key, request_hash)

    def _replay(
        self,
        request: dict[str, Any],
        session: Session,
        existing: dict[str, Any],
        key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        """Same key, same request: return the recorded outcome, never re-run it."""
        if existing.get("requestHash") != request_hash:
            raise BridgeError(
                "IDEMPOTENCY_CONFLICT",
                "this idempotencyKey was already used with different parameters",
                phase="authorize",
                details={
                    "idempotencyKey": key,
                    "existingState": existing.get("state"),
                    "existingOperationId": existing.get("operationId"),
                    "existingRequestHash": existing.get("requestHash"),
                    "submittedRequestHash": request_hash,
                    "note": "Use a new key only if you intend a genuinely new operation.",
                },
            )

        if existing.get("state") == "completed":
            envelope = existing.get("envelope") or {}
            data = dict(envelope.get("data") or {})
            data["replayed"] = True
            data["replayedFromOperationId"] = existing.get("operationId")
            return make_response(
                request["requestId"],
                existing.get("status", "accepted"),
                data=data,
                observation=envelope.get("observation"),
                evidence=envelope.get("evidence"),
                warnings=list(envelope.get("warnings") or [])
                + ["REPLAYED_FROM_JOURNAL: no new effect was produced."],
                error=envelope.get("error"),
            )

        # in-progress or interrupted: the key was consumed but no outcome exists.
        raise BridgeError(
            "EFFECT_INDETERMINATE",
            "this idempotencyKey was consumed by an attempt that has no recorded "
            "outcome; the effect is unknown and will not be repeated automatically",
            phase="observe",
            effect_state="unknown",
            details={
                "idempotencyKey": key,
                "operationId": existing.get("operationId"),
                "recordedState": existing.get("state"),
                "nextStep": "Inspect mw.runtime.status, then retry with a new key "
                "only after establishing what actually happened.",
            },
        )

    # --------------------------------------------------------------- snapshot

    def _snapshot_capture_editor(self, request: dict[str, Any]) -> dict[str, Any]:
        """``mw.snapshot.capture`` with ``target="editor"``: the *user's* editor.

        Read-only, capture only, and pointed at a session the user opened. This
        bridge starts the editor nowhere -- no method here does -- so this path
        never demands a launch record of its own. It also never claims what it
        did not check: the process is matched by *name* alone, so
        ``installationVerified`` is false and the observation strength is
        reported as ``candidate``.

        The window is the single visible one whose title is *exactly*
        ``千星沙箱`` **and** whose class carries the WPF ``HwndWrapper[BeyondEditor;``
        prefix. Both halves are required: a title alone is a string any window
        can carry, and the class alone covers every window the editor's WPF
        process owns. Requiring both is why this does not go ambiguous the moment
        another window, or another application, happens to be around -- only the
        candidate pids are enumerated at all.
        """
        from .editorwindow import (
            EDITOR_BINDING_SOURCE,
            EDITOR_MEANING,
            EDITOR_PROCESS_NAME,
            EDITOR_TARGET_KEY,
            EDITOR_TARGET_LABEL,
            EDITOR_WINDOW_CLASS_PREFIX,
            EDITOR_WINDOW_TITLE,
            MockEditorWindowBackend,
            RealEditorWindowBackend,
            editor_process_candidates,
        )

        state, _ = self.store.read_state()
        warnings = self._warnings()
        backend = self._backend_info()
        query_ok, processes = self.backend.query() if backend["available"] else (False, [])
        if not query_ok:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                "the process table could not be read, so no running editor process "
                "could be found",
                phase="preflight",
                details={**backend, "reason": "process-query-failed"},
            )

        candidates = editor_process_candidates(processes)
        if not candidates:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                f"no running {EDITOR_PROCESS_NAME} process was found, so there is no "
                f"editor window to capture",
                phase="preflight",
                details={
                    "target": EDITOR_TARGET_KEY,
                    "processName": EDITOR_PROCESS_NAME,
                    "reason": "no-editor-process",
                    "note": (
                        "This bridge does not start the editor and has no method that "
                        "does. Open the editor yourself, check that the session is the "
                        "one you mean, and call this again."
                    ),
                },
            )

        # A pid is a shared resource and Windows reuses them. Both the pid *and*
        # its creation date are therefore looked for once more, immediately before
        # anything is drawn: a window found a moment ago is not evidence about
        # whatever process holds that pid now.
        def identity(rows: list[dict[str, Any]]) -> list[Any]:
            return sorted((row.get("pid"), row.get("creationDate")) for row in rows)

        recheck_ok, fresh = self.backend.query()
        if not recheck_ok:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                "the process table could not be read a second time, so the running "
                "editor process could not be re-confirmed; no capture was attempted",
                phase="preflight",
                details={**self._backend_info(), "reason": "process-query-failed-on-recheck"},
            )
        if identity(editor_process_candidates(fresh)) != identity(candidates):
            raise BridgeError(
                "AMBIGUOUS_TARGET",
                "the running editor processes, or their creation dates, changed between "
                "two observations, so which process owns the window is not established; "
                "no capture was attempted",
                phase="preflight",
                details={
                    "target": EDITOR_TARGET_KEY,
                    "firstObservation": identity(candidates),
                    "secondObservation": identity(editor_process_candidates(fresh)),
                    "matchedOn": ["pid", "creationDate"],
                    "note": "Pids are reused by Windows; a stale observation is not a binding.",
                },
            )

        pids = sorted({int(c["pid"]) for c in candidates})
        editor_backend = getattr(self, "editor_window_backend", None)
        if editor_backend is None:
            editor_backend = (
                MockEditorWindowBackend()
                if self.window_backend.simulated
                else RealEditorWindowBackend()
            )
        outcome = editor_backend.capture_editor_target(pids)
        chosen_pid = (outcome.window or {}).get("pid")
        chosen = next((c for c in candidates if c.get("pid") == chosen_pid), candidates[0])

        if not outcome.ok:
            ambiguous = outcome.reason == "ambiguous-main-window-count"
            if ambiguous:
                message = (
                    f"more than one visible window of the running {EDITOR_PROCESS_NAME} "
                    f"process(es) has the exact title {EDITOR_WINDOW_TITLE!r} and the WPF "
                    f"editor class prefix, so which one is the editor window cannot be "
                    f"determined; no capture was taken"
                )
            elif outcome.reason == "window-minimized":
                message = (
                    "the editor window is minimized, so PrintWindow cannot draw it; no "
                    "capture was attempted. Restore it in the editor itself -- this "
                    "bridge issues no window commands for the editor -- then capture again."
                )
            elif outcome.reason == "no-editor-main-window":
                message = (
                    f"the running {EDITOR_PROCESS_NAME} process(es) own no visible window "
                    f"whose title is exactly {EDITOR_WINDOW_TITLE!r} and whose class "
                    f"carries the WPF editor prefix, so there is no editor window to "
                    f"capture"
                )
            else:
                message = f"no editor window capture was produced: {outcome.reason}"
            raise BridgeError(
                "AMBIGUOUS_TARGET" if ambiguous else "CAPABILITY_UNAVAILABLE",
                message,
                phase="observe",
                effect_state="none",
                details={
                    "target": EDITOR_TARGET_KEY,
                    "pids": pids,
                    "reason": outcome.reason,
                    # Kept on purpose: a refused capture still reports the windows it
                    # saw, so the refusal is diagnosable instead of blank.
                    "window": outcome.window,
                    "selection": (outcome.detail or {}).get("selection"),
                    "printWindowError": (outcome.detail or {}).get("printWindowError"),
                    "hint": (outcome.detail or {}).get("hint"),
                    "captureMethod": outcome.capture_method,
                    "bitbltFallbackUsed": False,
                    "ambiguous": ambiguous,
                    "note": (
                        "Reported as a failure rather than guessed at or substituted "
                        "with a desktop capture."
                    ),
                },
            )

        captured = outcome.to_dict()
        if outcome.status == "partial":
            warnings.append(
                "PRINTWINDOW_BLANK_OR_PARTIAL: PrintWindow drew the window but the "
                "result is essentially a single flat colour. The image was still "
                "written and is reported as 'partial'."
            )
        warnings.append(
            f"EDITOR_WINDOW_SELECTED_BY_TITLE: the window was identified by an exact "
            f"title ({EDITOR_WINDOW_TITLE}) plus the WPF class prefix "
            f"({EDITOR_WINDOW_CLASS_PREFIX}). That identifies which window the user "
            f"means; it is not evidence that the editor is in any mode, that a project "
            f"is loaded, or that any 千星 capability is available."
        )
        warnings.append(
            "EDITOR_SESSION_IS_USER_CONFIRMED: no install path is frozen for the "
            f"editor, so its process was matched by name ({EDITOR_PROCESS_NAME}) and "
            "installationVerified is false. The binding rests on the user's own "
            "confirmation that this is the session they opened, not on an observation "
            "made here."
        )
        if outcome.simulated:
            warnings.append(
                "CAPTURE_IS_SIMULATED: no window was enumerated; the image is a mock."
            )

        data = {
            "projectId": PROJECT_ID,
            "bridgeVersion": BRIDGE_VERSION,
            "target": EDITOR_TARGET_KEY,
            "targetDisplayName": EDITOR_TARGET_LABEL,
            "boundProcess": {
                "pid": chosen_pid,
                "name": EDITOR_PROCESS_NAME,
                "executablePath": chosen.get("executablePath"),
                "executablePathReadable": chosen.get("executablePath") is not None,
                "creationDate": chosen.get("creationDate"),
                "matchKind": "process-name:editor",
                "observationStrength": "candidate",
                "bindingSource": EDITOR_BINDING_SOURCE,
                "installationVerified": False,
            },
            "bindingEvidence": {
                "source": EDITOR_BINDING_SOURCE,
                "strength": "candidate",
                "observationStrength": "candidate",
                "installationVerified": False,
                "pathKnown": chosen.get("executablePath") is not None,
                "matchedOn": [
                    "process-name",
                    "pid+creationDate-recheck",
                    "window-title-exact",
                    "window-class-prefix",
                ],
                "windowCount": 1,
                # Unlike the game path, the title *is* the selector here. Said out
                # loud rather than left for a reader to notice.
                "titleUsedToChoose": True,
                "candidateProcesses": [
                    {
                        "pid": c.get("pid"),
                        "name": c.get("name"),
                        "creationDate": c.get("creationDate"),
                        "executablePathReadable": c.get("executablePath") is not None,
                    }
                    for c in candidates
                ],
                "how": (
                    "Every running process named BeyondEditor.exe is a candidate: the "
                    "editor has no frozen install path, so nothing here proves which "
                    "installation it is. The window is the single visible one whose "
                    "title is exactly 千星沙箱 and whose class carries the WPF prefix "
                    "HwndWrapper[BeyondEditor;. The chosen pid and its creation date "
                    "were re-read from the process table immediately before the "
                    "capture, so a reused pid cannot be mistaken for the one observed."
                ),
            },
            "capture": {
                **captured,
                "path": str(outcome.path),
                "projectRelativePath": (
                    str(outcome.path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                    if outcome.path and _is_under(str(outcome.path), str(PROJECT_ROOT))
                    else None
                ),
                "format": "bmp-32bpp-bi-rgb",
                "readOnly": True,
                "note": EDITOR_MEANING,
            },
            "sandboxReadiness": SANDBOX_READINESS,
            "meaning": EDITOR_MEANING,
            "stateMode": self.store.mode,
            "revision": str(state.revision),
            "windowBackend": (
                editor_backend.describe()
                if hasattr(editor_backend, "describe")
                else {"kind": getattr(editor_backend, "kind", "unknown")}
            ),
        }
        return make_response(
            request["requestId"],
            "succeeded",
            data=data,
            observation=self._observation(
                state.revision,
                source="mock-window-capture" if outcome.simulated else "os-window-capture",
                coverage=["window-capture"],
                extra={
                    "target": EDITOR_TARGET_KEY,
                    "pids": pids,
                    "bindingSource": EDITOR_BINDING_SOURCE,
                    "installationVerified": False,
                    "captureStatus": outcome.status,
                    "simulated": outcome.simulated,
                    "sandboxReadiness": "not-verified",
                },
            ),
            evidence=[
                {
                    "artifactId": f"sha256:{outcome.sha256}",
                    "kind": "window-capture",
                    "path": str(outcome.path),
                    "simulated": outcome.simulated,
                    "note": (
                        "An image of one editor window. It is not evidence of editor "
                        "readiness, editor mode or project identity."
                    ),
                }
            ],
            warnings=warnings,
        )

    def snapshot_capture(self, request: dict[str, Any]) -> dict[str, Any]:
        """``mw.snapshot.capture``: bind one window, draw it, write one BMP.

        Read-only in the sense that matters: no process is started, no input is
        sent, nothing outside ``.runtime/`` is touched. The only write is the
        evidence file itself, which is why this needs no idempotency key.

        Two targets, one window each, and no way for the caller to name one: the
        frozen ``game`` process, or the ``editor`` session the *user* opened
        (``target="editor"``, handled by ``_snapshot_capture_editor``).

        Every refusal below is deliberate. Two candidate windows are not resolved
        by picking one; a blank capture is not dressed up as a capture; a failure
        is not retried against the desktop.
        """
        method = request["method"]
        params = parse_params(request["params"], SNAPSHOT_PARAMS, method)

        from .editorwindow import EDITOR_TARGET_KEY

        target = params.get("target", SNAPSHOT_TARGET)
        if target == EDITOR_TARGET_KEY:
            return self._snapshot_capture_editor(request)
        if target != SNAPSHOT_TARGET:
            raise BridgeError(
                "TARGET_NOT_ALLOWED",
                f"mw.snapshot.capture accepts only target {SNAPSHOT_TARGET!r} or "
                f"{EDITOR_TARGET_KEY!r}; it does not accept a pid, an hwnd or an "
                f"arbitrary executable",
                phase="validate",
                details={
                    "allowedTargets": [EDITOR_TARGET_KEY, SNAPSHOT_TARGET],
                    "received": target,
                    "note": "The window is chosen by the bridge, never by the caller.",
                },
            )

        state, _ = self.store.read_state()
        backend = self._backend_info()
        query_ok, processes = self.backend.query() if backend["available"] else (False, [])
        info = observe_targets(
            processes, simulated=self.backend.simulated, known=query_ok
        )[SNAPSHOT_TARGET]
        warnings = self._warnings()

        if not query_ok:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                "the process table could not be read, so there is no way to bind a "
                "window to the frozen game process",
                phase="preflight",
                details={**backend, "reason": "process-query-failed"},
            )

        for note in (weak_match_warning(SNAPSHOT_TARGET, info), unverified_warning(SNAPSHOT_TARGET, info)):
            if note:
                warnings.append(note)

        # The binding rule lives in one place and is shared with mw.window.restore,
        # so the two methods cannot drift into disagreeing about which process owns
        # the window -- or about what to refuse.
        bound, binding = self._bind_target_window(info, warnings)
        outcome = self.window_backend.capture_target(bound["pid"])

        if not outcome.ok:
            ambiguous = outcome.reason == "ambiguous-window-count"
            minimized = outcome.reason == "window-minimized"
            code = "AMBIGUOUS_TARGET" if ambiguous else "CAPABILITY_UNAVAILABLE"
            if ambiguous:
                message = (
                    "the game process owns more than one visible top-level window, so "
                    "which one is on screen cannot be determined; no capture was taken"
                )
            elif minimized:
                message = (
                    "the game window is minimized, so PrintWindow cannot draw it; no "
                    "capture was attempted. Call mw.window.restore for the same target, "
                    "then capture again."
                )
            else:
                message = f"no window capture was produced: {outcome.reason}"
            raise BridgeError(
                code,
                message,
                phase="observe",
                effect_state="none",
                details={
                    "target": SNAPSHOT_TARGET,
                    "pid": bound["pid"],
                    "reason": outcome.reason,
                    "windowMinimized": minimized,
                    "captureMethod": outcome.capture_method,
                    "bitbltFallbackUsed": False,
                    "printWindowAttempted": (outcome.detail or {}).get("printWindowAttempted"),
                    "hint": (outcome.detail or {}).get("hint"),
                    "printWindowError": (outcome.detail or {}).get("printWindowError"),
                    "selection": (outcome.detail or {}).get("selection"),
                    "ambiguous": ambiguous,
                    "note": (
                        "Reported as a failure rather than guessed at or substituted "
                        "with a desktop capture."
                    ),
                },
            )

        captured = outcome.to_dict()
        if outcome.status == "partial":
            warnings.append(
                "PRINTWINDOW_BLANK_OR_PARTIAL: PrintWindow drew the window but the "
                "result is essentially a single flat colour. The image was still "
                "written and is reported as 'partial'. This is not evidence that the "
                "window is showing anything in particular -- a minimized window, a "
                "loading screen or a protected surface all look like this."
            )
        warnings.append(
            "WINDOW_TITLE_IS_NOT_EVIDENCE: the title below is what the OS handed back. "
            "It must not be read as showing 千星, an editor mode or a project."
        )
        if outcome.simulated:
            warnings.append(
                "CAPTURE_IS_SIMULATED: no window was enumerated; the image is a mock."
            )

        data = {
            "projectId": PROJECT_ID,
            "bridgeVersion": BRIDGE_VERSION,
            "target": SNAPSHOT_TARGET,
            "targetDisplayName": info["displayName"],
            "boundProcess": {
                "pid": bound["pid"],
                "name": bound.get("name"),
                "executablePath": bound.get("executablePath"),
                "executablePathReadable": bound.get("executablePath") is not None,
                "matchKind": bound.get("matchKind"),
                "matchStrength": bound.get("matchStrength"),
                "creationDate": bound.get("creationDate"),
                "bindingSource": binding["source"],
            },
            "bindingEvidence": {
                **binding,
                "windowCount": 1,
                "titleUsedToChoose": False,
            },
            "capture": {
                **captured,
                "path": str(outcome.path),
                "projectRelativePath": (
                    str(outcome.path.relative_to(PROJECT_ROOT)).replace("\\", "/")
                    if outcome.path and _is_under(str(outcome.path), str(PROJECT_ROOT))
                    else None
                ),
                "format": "bmp-32bpp-bi-rgb",
                "readOnly": True,
                "note": SNAPSHOT_MEANING,
            },
            # Present so that "not verified" is a value in the response rather than
            # an omission a reader could fill in. A capture never sets this.
            "sandboxReadiness": SANDBOX_READINESS,
            "meaning": SNAPSHOT_MEANING,
            "stateMode": self.store.mode,
            "revision": str(state.revision),
            "windowBackend": (
                self.window_backend.describe()
                if hasattr(self.window_backend, "describe")
                else {"kind": getattr(self.window_backend, "kind", "unknown")}
            ),
        }
        return make_response(
            request["requestId"],
            "succeeded",
            data=data,
            observation=self._observation(
                state.revision,
                source="mock-window-capture" if outcome.simulated else "os-window-capture",
                coverage=["window-capture"],
                extra={
                    "target": SNAPSHOT_TARGET,
                    "pid": bound["pid"],
                    "bindingSource": binding["source"],
                    "captureStatus": outcome.status,
                    "simulated": outcome.simulated,
                    "sandboxReadiness": "not-verified",
                },
            ),
            evidence=[
                {
                    "artifactId": f"sha256:{outcome.sha256}",
                    "kind": "window-capture",
                    "path": str(outcome.path),
                    "simulated": outcome.simulated,
                    "note": (
                        "An image of one window. It is not evidence of sandbox "
                        "readiness, editor mode or project identity."
                    ),
                }
            ],
            warnings=warnings,
        )

    def _bind_target_window(
        self, info: dict[str, Any], warnings: list[str]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Decide which process owns the window, or refuse.

        Shared by ``mw.snapshot.capture`` and ``mw.window.restore`` so the two can
        never drift: whatever one of them is willing to act on, the other is too,
        and whatever one refuses, the other refuses for the same stated reason.

        Two ways a window can be bound to a process, and only two. A path match is
        direct proof. A launch-journal match is a documented inference about a
        process this project itself started, and it is accepted only when the live
        pid *and* creation date *and* name match the recorded ones. Everything else
        is refused rather than guessed at.

        Returns ``(bound, binding)``. Both are response fragments, so the caller
        reports exactly which of the two kinds of evidence it acted on.
        """
        strong = [p for p in info["processes"] if p.get("matchStrength") == "strong"]
        unverified = info["unverifiedCandidates"]

        if len(strong) > 1:
            raise BridgeError(
                "AMBIGUOUS_TARGET",
                f"{len(strong)} processes match the frozen game executable; which one "
                f"owns the window to capture is not determined",
                phase="preflight",
                details={
                    "target": SNAPSHOT_TARGET,
                    "candidatePids": [p["pid"] for p in strong],
                    "note": "A capture is not attempted when the target is ambiguous.",
                },
            )

        if len(strong) == 1:
            bound: dict[str, Any] = dict(strong[0])
            binding: dict[str, Any] = {
                "source": BINDING_EXECUTABLE_PATH,
                "strength": "strong",
                "pathKnown": True,
                "how": (
                    "The pid comes from a CIM process whose ExecutablePath equals the "
                    "frozen game executable; the window comes from "
                    "GetWindowThreadProcessId on that pid only."
                ),
            }
        elif len(unverified) == 1:
            # Exactly one same-named process whose path cannot be read. That alone
            # proves nothing. It becomes usable only if this project's own real
            # journal records a launch of this target that returned this very pid,
            # carrying this very creation date -- which is what rules out a pid
            # that Windows has since reused.
            candidate = unverified[0]
            record, why, detail = self._launch_journal_binding(candidate)
            if record is None:
                raise BridgeError(
                    "AMBIGUOUS_TARGET",
                    f"a process named {os.path.basename(info['executablePath'])} exists "
                    f"but its ExecutablePath is unreadable, and it could not be bound "
                    f"to a launch this project recorded ({why}), so a window of that "
                    f"process cannot be attributed to the frozen installation",
                    phase="preflight",
                    details={
                        "target": SNAPSHOT_TARGET,
                        "pid": candidate.get("pid"),
                        "creationDate": candidate.get("creationDate"),
                        "unverifiedCandidates": [
                            {"pid": c.get("pid"), "name": c.get("name"),
                             "creationDate": c.get("creationDate"),
                             "reason": c.get("reason", "path-unreadable")}
                            for c in unverified
                        ],
                        "journalBinding": {"attempted": True, "reason": why,
                                           "realJournal": str(self.store.paths.journal),
                                           "closest": detail or None},
                        "note": (
                            "A matching name is not a match. Recording 'which install "
                            "is on screen' would be a guess here."
                        ),
                    },
                )
            bound = {
                "pid": candidate.get("pid"),
                "name": candidate.get("name"),
                "executablePath": None,
                "creationDate": candidate.get("creationDate"),
                "matchKind": candidate.get("matchKind") or "executable-name:path-unreadable",
                "matchStrength": None,
                "bindingSource": BINDING_LAUNCH_JOURNAL,
            }
            binding = {
                "source": BINDING_LAUNCH_JOURNAL,
                "strength": "strong",
                # The live process's path was never readable, and this does not
                # pretend otherwise: it is the *record's* path that is known.
                "pathKnown": False,
                "matchedOn": ["pid", "creationDate", "name"],
                "launchedExecutablePath": record.get("launchedExecutablePath"),
                "how": (
                    "This project's real journal has a terminal record for target "
                    "'game' whose launch returned this pid, whose observedProcess "
                    "carries this same creation date and name, and whose request named "
                    "the frozen executable path. The live process matches that record "
                    "on pid, creation date and name -- so it is the process this "
                    "project started, not a later process on a reused pid."
                ),
                "journal": record,
            }
            warnings.append(
                "WINDOW_BOUND_FROM_LAUNCH_JOURNAL: the game process's ExecutablePath is "
                "still unreadable through CIM, so it is reported as null and "
                "pathKnown is false. The window was bound because this project's real "
                "journal records a launch of target 'game' that returned pid "
                f"{candidate.get('pid')}, and the live process carries the same "
                "creation date and name. This is a documented inference from our own "
                "launch record, not an ExecutablePath read from the running process."
            )
        elif len(unverified) > 1:
            raise BridgeError(
                "AMBIGUOUS_TARGET",
                f"{len(unverified)} processes named "
                f"{os.path.basename(info['executablePath'])} exist with unreadable "
                f"paths, so which one owns the window to capture is not determined",
                phase="preflight",
                details={
                    "target": SNAPSHOT_TARGET,
                    "unverifiedCandidates": [
                        {"pid": c.get("pid"), "creationDate": c.get("creationDate")}
                        for c in unverified
                    ],
                    "note": "A capture is not attempted when the target is ambiguous.",
                },
            )
        else:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                f"no running process is a verified match for the frozen game "
                f"executable {info['executablePath']}, so there is no window to capture",
                phase="preflight",
                details={
                    "target": SNAPSHOT_TARGET,
                    "executablePath": info["executablePath"],
                    "targetExists": info["exists"],
                    "runningKnown": info["runningKnown"],
                    "running": info["running"],
                    "reason": "no-verified-target-process",
                    "journalBinding": {"attempted": False, "reason": "no-candidate-process"},
                    "note": (
                        "This bridge does not start the game. Start it through "
                        "mw.runtime.start and observe it with mw.runtime.status first."
                    ),
                },
            )
        return bound, binding

    def window_restore(self, request: dict[str, Any]) -> dict[str, Any]:
        """``mw.window.restore``: ask the one bound window to un-minimize.

        The entire effect is one ``ShowWindowAsync(hwnd, SW_RESTORE)`` inside a
        child process. No input is synthesised, no focus is stolen, nothing is
        elevated and no process is started -- and only the window bound by the
        shared rule is touched, never the desktop and never a window belonging to
        anything else.

        Idempotent by nature, but it still runs the write path: a key and a
        revision are required, a terminal record is written either way, and a
        repeat under the same key replays instead of asking the window again.
        """
        method = request["method"]
        params = parse_params(request["params"], SNAPSHOT_PARAMS, method)

        target = params.get("target", SNAPSHOT_TARGET)
        if target != SNAPSHOT_TARGET:
            raise BridgeError(
                "TARGET_NOT_ALLOWED",
                f"mw.window.restore accepts only target {SNAPSHOT_TARGET!r}; it does not "
                f"accept a pid, an hwnd or a window handle",
                phase="validate",
                details={
                    "allowedTargets": [SNAPSHOT_TARGET],
                    "received": target,
                    "note": "The window is chosen by the bridge, never by the caller.",
                },
            )

        meaning = (
            "RESTORE ONLY. This asks one window of the frozen game process to "
            "un-minimize, because a minimized window cannot be captured. It is a "
            "window state, not sandbox readiness: no part of this reports that the "
            "sandbox, editor, project or a Miliastra capability is ready, and nothing "
            "here interprets what the window shows. No keyboard or mouse input is "
            "sent, focus is not taken, nothing is elevated and no process is started."
        )
        key = request["idempotencyKey"]
        request_hash = sha256_hex(
            canonical_json({"method": method, "projectId": PROJECT_ID, "params": params})
        )

        with self.store.locked() as session:
            existing = session.state.idempotency.get((method, key))
            if existing is not None:
                return self._replay(request, session, existing, key, request_hash)

            expected = request["expectedRevision"]
            current = str(session.state.revision)
            if expected != current:
                raise BridgeError(
                    "STALE_REVISION",
                    f"expectedRevision {expected} does not match current revision {current}",
                    phase="authorize",
                    retryable=True,
                    details={"expected": expected, "current": current},
                )

            # --- preflight: the same binding rule snapshot uses, before any effect
            backend = self._backend_info()
            query_ok, processes = self.backend.query() if backend["available"] else (False, [])
            info = observe_targets(
                processes, simulated=self.backend.simulated, known=query_ok
            )[SNAPSHOT_TARGET]
            warnings = self._warnings()
            if not query_ok:
                raise BridgeError(
                    "CAPABILITY_UNAVAILABLE",
                    "the process table could not be read, so no window can be bound to "
                    "the frozen game process",
                    phase="preflight",
                    details={**backend, "reason": "process-query-failed"},
                )
            for note in (
                weak_match_warning(SNAPSHOT_TARGET, info),
                unverified_warning(SNAPSHOT_TARGET, info),
            ):
                if note:
                    warnings.append(note)

            # A refusal here happens before the operation id, the fence and the
            # journal record, so it leaves no trace of a restore that never happened.
            bound, binding = self._bind_target_window(info, warnings)

            # --- effect -------------------------------------------------------
            operation_id = session.next_operation_id()
            session.set_fence(session.next_fence())
            outcome = self.window_backend.restore_target(bound["pid"])

            data: dict[str, Any] = {
                "operationId": operation_id,
                "method": method,
                "target": SNAPSHOT_TARGET,
                "targetDisplayName": info["displayName"],
                "boundProcess": {
                    "pid": bound["pid"],
                    "name": bound.get("name"),
                    "executablePath": bound.get("executablePath"),
                    "executablePathReadable": bound.get("executablePath") is not None,
                    "matchKind": bound.get("matchKind"),
                    "matchStrength": bound.get("matchStrength"),
                    "creationDate": bound.get("creationDate"),
                    "bindingSource": binding["source"],
                },
                "bindingEvidence": {**binding, "windowCount": 1, "titleUsedToChoose": False},
                "window": outcome.window,
                # What the window looked like before the request, so the read-back
                # can be compared against a recorded starting point.
                "windowBefore": outcome.window_before,
                "request": {
                    "api": "ShowWindowAsync",
                    "command": "SW_RESTORE",
                    "commandValue": (outcome.detail or {}).get("restoreCommand", 9),
                    "hwnd": (outcome.window or {}).get("hwnd"),
                    "pid": bound["pid"],
                    "keyboardOrMouseInputSent": False,
                    "foregroundForced": False,
                    "elevated": False,
                    "processStarted": False,
                    "systemSettingChanged": False,
                    "shellUsed": False,
                },
                "requested": outcome.requested,
                "readBack": outcome.read_back,
                "sandboxReadiness": SANDBOX_READINESS,
                "meaning": meaning,
                "replayed": False,
                "stateMode": self.store.mode,
                "revision": str(session.state.revision + 1),
                "backend": self._backend_info(),
            }

            if not outcome.ok:
                # Recorded, not swallowed: a refused or failed request is a terminal
                # outcome with its own effectState.
                ambiguous = outcome.reason == "ambiguous-window-count"
                error = BridgeError(
                    "AMBIGUOUS_TARGET" if ambiguous else "CAPABILITY_UNAVAILABLE",
                    (
                        "the game process owns more than one visible top-level window, "
                        "so which one to restore cannot be determined; no window was "
                        "touched"
                        if ambiguous
                        else f"the window restore request could not be made: {outcome.reason}"
                    ),
                    phase="effect",
                    effect_state="not-requested",
                    details={
                        "target": SNAPSHOT_TARGET,
                        "pid": bound["pid"],
                        "reason": outcome.reason,
                        "ambiguous": ambiguous,
                        "selection": (outcome.detail or {}).get("selection"),
                        "inputSent": False,
                        "note": (
                            "No window command was issued. Nothing was restored, and no "
                            "other window was tried."
                        ),
                    },
                )
                data["effectState"] = "not-requested"
                envelope = self._finish(
                    session, operation_id, method, key, request_hash,
                    "failed", "not-requested", data, warnings, error=error,
                    simulated=self.window_backend.simulated,
                )
                return self._respond(request, "failed", envelope, error)

            already = outcome.status == "already-restored"
            still_minimized = bool((outcome.read_back or {}).get("stillMinimized"))
            if already:
                effect_state = "already-restored"
                warnings.append(
                    "ALREADY_RESTORED: the window was not minimized, so nothing was "
                    "requested and the window was not touched."
                )
            elif still_minimized:
                effect_state = "restore-requested-still-minimized"
                warnings.append(
                    "STILL_MINIMIZED_AFTER_REQUEST: ShowWindowAsync queued the restore, "
                    "but IsIconic was still set when the bounded read-back wait expired. "
                    "The window's owning thread had not applied the request yet (or "
                    "refused it). This is reported as requested-and-still-minimized, "
                    "never as restored."
                )
            else:
                effect_state = "restore-requested"
                warnings.append(
                    "RESTORE_IS_NOT_READINESS: the window is no longer minimized. That "
                    "is a window state, not evidence that the sandbox, editor or project "
                    "is ready, and it is not a claim that any Miliastra capability works."
                )
            data["effectState"] = effect_state

            envelope = self._finish(
                session, operation_id, method, key, request_hash,
                "accepted", effect_state, data, warnings, error=None,
                simulated=self.window_backend.simulated,
            )
        return self._respond(request, "accepted", envelope)

    def _launch_journal_binding(
        self, candidate: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """Ask the *real* journal whether this project started this exact process.

        Mock mode never reaches the real journal, and never treats its own
        simulated records as evidence, because a simulated launch is not a launch.
        """
        if self.store.mode != "real":
            return (
                None,
                "journal-not-consulted-in-mock-mode",
                {"stateMode": self.store.mode},
            )
        return find_launch_journal_binding(
            self.store.paths.journal,
            pid=candidate.get("pid"),
            name=candidate.get("name"),
            creation_date=candidate.get("creationDate"),
        )

    # ------------------------------------------------------------ asset domain

    def _asset_result(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.asset_api is None:
            raise BridgeError(
                "CAPABILITY_UNAVAILABLE",
                "mvp.asset_api is not importable, so the asset domain methods are "
                "unavailable",
                phase="preflight",
                details={"method": method},
            )
        allowed = self._asset_allowed_params(method)
        if allowed is not None:
            unknown = sorted(set(params) - set(allowed))
            if unknown:
                raise BridgeError(
                    "PARAM_FORBIDDEN",
                    f"{method} does not accept parameter(s): {', '.join(unknown)}",
                    details={
                        "unknownParams": unknown,
                        "allowedParams": sorted(allowed),
                        "note": "The parameter vocabulary is closed, as everywhere else "
                        "in this bridge.",
                    },
                )
        try:
            return self.asset_api.dispatch(method, params)
        except Exception as exc:  # noqa: BLE001 - re-raised as a structured error
            raise self._asset_error(exc, method) from exc

    def _asset_allowed_params(self, method: str) -> list[str] | None:
        """Ask the asset module which parameters it declares, and cache the answer."""
        if self._asset_params is None:
            try:
                described = self.asset_api.describe() or {}
                self._asset_params = described.get("methods") or {}
            except Exception:  # noqa: BLE001 - an undescribable module still runs
                self._asset_params = {}
        declared = self._asset_params.get(method)
        return list(declared) if isinstance(declared, (list, tuple)) else None

    @staticmethod
    def _asset_error(exc: Exception, method: str) -> BridgeError:
        """Keep an asset failure structured rather than flattening it to a string."""
        to_dict = getattr(exc, "to_dict", None)
        if callable(to_dict):
            payload = to_dict() or {}
            phase = payload.get("phase")
            return BridgeError(
                payload.get("code") or "VALIDATION_FAILED",
                payload.get("message") or str(exc),
                phase=phase if phase in PHASES else "validate",
                details={"method": method, **(payload.get("details") or {})},
                code_origin="mvp.asset_api",
            )
        return BridgeError(
            "VALIDATION_FAILED",
            f"asset api raised {type(exc).__name__}: {exc}",
            details={"method": method},
        )

    def asset_read(self, request: dict[str, Any]) -> dict[str, Any]:
        """Read-only asset methods: no lock, no revision bump, no idempotency key."""
        method = request["method"]
        state, _ = self.store.read_state()
        payload = self._asset_result(method, dict(request["params"]))
        warnings = self._warnings() + list(payload.get("warnings") or [])
        data = {
            "projectId": PROJECT_ID,
            "bridgeVersion": BRIDGE_VERSION,
            "result": payload,
            "gameAccepted": payload.get("gameAccepted", "unknown"),
            "stateMode": self.store.mode,
            "revision": str(state.revision),
            "backend": self._backend_info(),
        }
        return make_response(
            request["requestId"],
            "succeeded",
            data=data,
            observation=self._observation(
                state.revision, source="mvp.asset_api", coverage=[method]
            ),
            warnings=warnings,
        )

    def asset_build(self, request: dict[str, Any]) -> dict[str, Any]:
        """``mw.scene.build``: locked, idempotent and revision-checked."""
        method = request["method"]
        params = dict(request["params"])
        key = request["idempotencyKey"]
        request_hash = sha256_hex(
            canonical_json({"method": method, "projectId": PROJECT_ID, "params": params})
        )

        with self.store.locked() as session:
            existing = session.state.idempotency.get((method, key))
            if existing is not None:
                return self._replay(request, session, existing, key, request_hash)

            expected = request["expectedRevision"]
            current = str(session.state.revision)
            if expected != current:
                raise BridgeError(
                    "STALE_REVISION",
                    f"expectedRevision {expected} does not match current revision {current}",
                    phase="authorize",
                    retryable=True,
                    details={"expected": expected, "current": current},
                )

            # The build is local and content-addressed: the commit into the build
            # directory is atomic, so re-running the same inputs is safe. There is no
            # external effect to fence with a pre-effect intent, and a failure must
            # not consume the idempotency key. Intent and terminal are written
            # together, after the work has succeeded.
            payload = self._asset_result(method, params)

            operation_id = session.next_operation_id()
            session.set_fence(session.next_fence())
            warnings = self._warnings() + list(payload.get("warnings") or [])
            data = {
                "operationId": operation_id,
                "method": method,
                "effectState": "artifact-committed",
                "result": payload,
                "gameAccepted": payload.get("gameAccepted", "unknown"),
                "gameAcceptedNote": (
                    "Whether the game would accept this artifact is not observed by "
                    "this bridge. 'unknown' means unknown."
                ),
                "replayed": False,
                "stateMode": self.store.mode,
                "revision": str(session.state.revision + 1),
                "backend": self._backend_info(),
            }
            envelope = self._finish(
                session,
                operation_id,
                method,
                key,
                request_hash,
                "accepted",
                "artifact-committed",
                data,
                warnings,
                error=None,
                simulated=False,
            )
        return self._respond(request, "accepted", envelope)

    def _perform_start(
        self,
        request: dict[str, Any],
        session: Session,
        target: str,
        spec: dict[str, str],
        observe_ms: int,
        key: str,
        request_hash: str,
    ) -> dict[str, Any]:
        method = request["method"]
        warnings = self._warnings()
        # A "request" target re-sends its fixed request for every new idempotency
        # key; its deduplication lives in the journal, not in a running process.
        request_only = not spec.get("dedupeOnRunning", True)
        if spec.get("launchedVia") == "official-start-menu-shortcut":
            warnings.append(
                "SHORTCUT_LAUNCH_REQUEST_ONLY: this reproduces the official shortcut's "
                "request (launcher.exe --game=hk4e_cn). Whether the game then starts is "
                "not observed by this bridge."
            )

        # --- preflight: fail closed. Never launch without the ability to look. ---
        backend_status = self.backend.probe()
        if not backend_status.available:
            raise BridgeError(
                "BACKEND_UNAVAILABLE",
                "process observation is unavailable, so a launch could not be "
                "confirmed; refusing to start a process blind",
                phase="preflight",
                details=backend_status.to_dict(),
            )
        if not target_exists(target):
            raise BridgeError(
                "TARGET_UNAVAILABLE",
                f"the frozen target's executable is not present on disk: "
                f"{spec['executablePath']}",
                phase="preflight",
                details={"target": target, "executablePath": spec["executablePath"]},
            )
        query_ok, processes = self.backend.query()
        if not query_ok:
            raise BridgeError(
                "BACKEND_UNAVAILABLE",
                "the process query failed, so a launch could not be confirmed; "
                "refusing to start a process blind",
                phase="preflight",
                details=self._backend_info(),
            )

        pre = observe_targets(processes, simulated=self.backend.simulated, known=True)[target]
        for pre_note in (weak_match_warning(target, pre), unverified_warning(target, pre)):
            if pre_note:
                warnings.append(pre_note)

        # Ambiguous: a process carrying the frozen executable's name exists, but its
        # path cannot be read, so whether this target is already running is unknown.
        # Starting a second copy would be a guess, and reporting "already running"
        # would be a claim we cannot support. Refuse -- and refuse here, *before* an
        # operation id, a fence or a journal entry exists, so the request has no
        # effect of any kind and leaves no record of a start that never happened.
        if pre["running"] is None and pre["unverifiedCandidates"]:
            raise BridgeError(
                "EFFECT_INDETERMINATE",
                f"a process named {os.path.basename(spec['executablePath'])} exists but "
                f"its ExecutablePath is unreadable, so it is unknown whether target "
                f"{target!r} is already running; refusing to start a second one",
                phase="preflight",
                details={
                    "target": target,
                    "executablePath": spec["executablePath"],
                    "unverifiedCandidates": [
                        {
                            "pid": candidate.get("pid"),
                            "name": candidate.get("name"),
                            "creationDate": candidate.get("creationDate"),
                            "reason": candidate.get("reason", "path-unreadable"),
                        }
                        for candidate in pre["unverifiedCandidates"]
                    ],
                },
            )

        operation_id = session.next_operation_id()
        fence = session.next_fence()
        session.set_fence(fence)

        # Already running: report it, start nothing, claim nothing.
        #
        # This shortcut is only valid for targets whose request is *satisfied* by
        # an existing process. It is NOT valid for `game-shortcut`: the launcher
        # being up says nothing about whether this shortcut's game-selection
        # request was ever delivered, and treating it as "done" silently drops
        # the request. Deduplication for that target belongs to the idempotency
        # key, not to a process that happens to be alive.
        if pre["running"] and not request_only:
            warnings.append(
                "ALREADY_RUNNING: the target was already observed running, so no new "
                "process was started by this request."
            )
            session.journal.append(
                "intent",
                {
                    "operationId": operation_id,
                    "requestId": request["requestId"],
                    "method": method,
                    "idempotencyKey": key,
                    "requestHash": request_hash,
                    "target": target,
                    "executablePath": spec["executablePath"],
                    "fence": fence,
                    "simulated": self.launcher.simulated,
                    "skippedBecause": "already-running",
                },
            )
            terminal_data = {
                "operationId": operation_id,
                "method": method,
                "target": target,
                "targetDisplayName": spec["displayName"],
                "launchedVia": spec.get("launchedVia", "direct"),
                "shortcut": (
                    {
                        "path": spec["shortcutPath"],
                        "arguments": spec["shortcutArguments"],
                    }
                    if spec.get("shortcutPath")
                    else None
                ),
                "effectState": "already-running",
                "sandboxReadiness": SANDBOX_READINESS,
                "request": {
                    "executablePath": spec["executablePath"],
                    "arguments": list(spec.get("argv") or ()),
                    "shellUsed": False,
                    "launchedVia": spec.get("launchedVia", "direct"),
                },
                "launch": {"returned": False, "pid": None, "simulated": False},
                "observedProcess": pre["processes"][0] if pre["processes"] else None,
                "pidMatched": None,
                "replayed": False,
                "backend": self._backend_info(),
            }
            envelope = self._finish(
                session,
                operation_id,
                method,
                key,
                request_hash,
                "accepted",
                "already-running",
                terminal_data,
                warnings,
                error=None,
                simulated=self.backend.simulated,
            )
            return self._respond(request, "accepted", envelope)

        # --- durable intent, then the effect ---------------------------------
        session.journal.append(
            "intent",
            {
                "operationId": operation_id,
                "requestId": request["requestId"],
                "method": method,
                "idempotencyKey": key,
                "requestHash": request_hash,
                "target": target,
                "executablePath": spec["executablePath"],
                "expectedRevision": request["expectedRevision"],
                "fence": fence,
                "simulated": self.launcher.simulated,
            },
        )

        argv = tuple(spec.get("argv") or ())
        # Opt-in and already validated in `start`. An ordinary request passes no
        # extra argument at all, so the default call is the one it always was.
        elevation = request["params"].get("elevation", ELEVATION_DEFAULT)
        launch_kwargs = {} if elevation == ELEVATION_DEFAULT else {"elevation": elevation}
        launch = self.launcher.launch(
            spec["executablePath"],
            cwd=os.path.dirname(spec["executablePath"]),
            argv=argv,
            **launch_kwargs,
        )

        if launch.returned:
            session.journal.append(
                "launched",
                {
                    "operationId": operation_id,
                    "pid": launch.pid,
                    "simulated": launch.simulated,
                    "executablePath": spec["executablePath"],
                },
            )
        elif launch.error_kind == "oserror" or launch.error_kind in ELEVATION_ERROR_KINDS:
            # No process was created, and that is a known state rather than an
            # unknown one: CreateProcess refused (740 is the unelevated case), or the
            # elevated route was declined (ERROR_CANCELLED 1223), or it produced no
            # usable handle. None of those is a launch.
            declined = launch.error_kind == "user-cancelled"
            error = BridgeError(
                "LAUNCH_FAILED",
                (
                    f"elevation was declined by the user: {launch.error}"
                    if declined
                    else f"the operating system refused to start the process: {launch.error}"
                ),
                phase="effect",
                retryable=declined,
                effect_state="not-started",
                details={
                    "target": target,
                    "executablePath": spec["executablePath"],
                    "elevation": launch.elevation,
                    "launchErrorKind": launch.error_kind,
                    "osError": launch.error,
                    "note": (
                        "A declined prompt is retryable, but only with a new idempotency "
                        "key: this key is recorded and will not re-prompt."
                        if declined
                        else "No process was created."
                    ),
                },
            )
            terminal_data = {
                "operationId": operation_id,
                "method": method,
                "target": target,
                "targetDisplayName": spec["displayName"],
                "launchedVia": spec.get("launchedVia", "direct"),
                "shortcut": (
                    {
                        "path": spec["shortcutPath"],
                        "arguments": spec["shortcutArguments"],
                    }
                    if spec.get("shortcutPath")
                    else None
                ),
                "effectState": "not-started",
                "sandboxReadiness": SANDBOX_READINESS,
                "request": {
                    "executablePath": spec["executablePath"],
                    "arguments": list(spec.get("argv") or ()),
                    "shellUsed": False,
                    "launchedVia": spec.get("launchedVia", "direct"),
                },
                "launch": launch.to_dict(),
                "observedProcess": None,
                "pidMatched": None,
                "replayed": False,
                "backend": self._backend_info(),
            }
            envelope = self._finish(
                session, operation_id, method, key, request_hash,
                "failed", "not-started", terminal_data, warnings, error=error,
                simulated=self.backend.simulated,
            )
            return self._respond(request, "failed", envelope, error)

        # --- observe ---------------------------------------------------------
        observed, pid_matched, observe_query_ok = poll_target(
            self.backend, target, launch.pid, observe_ms
        )
        if not observe_query_ok:
            warnings.append(
                "PROCESS_QUERY_FAILED_AFTER_LAUNCH: the launch was requested but the "
                "process table could not be read afterwards."
            )
        if observed is not None:
            obs_note = weak_match_warning(target, observed)
            if obs_note:
                warnings.append(obs_note)
        if observed is not None and not pid_matched:
            warnings.append(
                f"PID_NOT_OBSERVED: a process for target {target!r} is running, but its "
                f"pid is not the {launch.pid} returned at launch time. The link between "
                f"this request and that process is not established."
            )

        # Only the process we actually created can be evidence about this request.
        launched_process = None
        if observed is not None and pid_matched and launch.pid is not None:
            launched_process = next(
                (p for p in observed["processes"] if p["pid"] == launch.pid), None
            )

        # An elevated process's ExecutablePath is frequently unreadable from a
        # non-elevated observer, so a path match can never be expected for it. A pid
        # match against the live table is the most that can be established, and
        # nothing beyond it is claimed.
        elevated_pid_row = None
        if launch.returned and launch.pid is not None and not pid_matched:
            ok_again, rows = self.backend.query()
            if ok_again:
                elevated_pid_row = next((p for p in rows if p.pid == launch.pid), None)

        if request_only:
            # `shortcut-requested` describes what was done: a process was created
            # with the fixed argv. Whether the launcher then acts on it -- and
            # whether the game starts -- is not observable here.
            if launched_process is not None:
                status, effect_state, error = "accepted", "shortcut-requested", None
            else:
                status, effect_state = "indeterminate", "shortcut-requested"
                if observed is not None:
                    warnings.append(
                        "PREEXISTING_PROCESS_IS_NOT_DELIVERY_EVIDENCE: a process for this "
                        "target is running, but it is not the one created by this request. "
                        "It is therefore not evidence that the shortcut request was "
                        "delivered."
                    )
                error = BridgeError(
                    "EFFECT_INDETERMINATE",
                    "the shortcut request was sent with the fixed arguments, but the "
                    "bootstrap process it created could not be observed afterwards; "
                    "delivery is unconfirmed",
                    phase="observe",
                    effect_state="sent",
                    details={
                        "target": target,
                        "pid": launch.pid,
                        "arguments": list(argv),
                        "observeTimeoutMs": observe_ms,
                        "note": (
                            "The request was issued (subprocess creation returned). What "
                            "is unknown is whether the launcher acted on it. A launcher "
                            "process that was already running is not evidence either way. "
                            "Do not retry with a new key until this is reconciled."
                        ),
                    },
                )
        elif observed is None and elevated_pid_row is not None:
            # Elevated and confirmed by pid only: the process exists, its path does
            # not resolve. Say exactly that, and keep `observed` empty -- a pid is
            # not an executable-path match, and neither is sandbox readiness.
            warnings.append(
                f"PID_CONFIRMED_PATH_UNKNOWN: pid {launch.pid} created by the elevated "
                "launch exists in the process table, but its ExecutablePath could not be "
                "read back, so this request is linked to that process by pid alone. This "
                "is not sandbox readiness."
            )
            launched_process = {
                "pid": launch.pid,
                "name": elevated_pid_row.name,
                "executablePath": None,
                "creationDate": elevated_pid_row.creation_date,
                "simulated": elevated_pid_row.simulated,
                "matchKind": "pid-only:path-unreadable",
                "matchStrength": "weak",
                "note": "pid matched; executable path unknown",
            }
            status, effect_state, error = "accepted", "launched-path-unknown", None
        elif observed is None:
            # Launched, but unconfirmed. Report what is known and stop.
            status, effect_state = "indeterminate", "sent"
            error = BridgeError(
                "EFFECT_INDETERMINATE",
                "a process was created but could not be observed afterwards; the "
                "effect is unknown",
                phase="observe",
                effect_state="sent",
                details={
                    "target": target,
                    "pid": launch.pid,
                    "observeTimeoutMs": observe_ms,
                    "note": "Do not retry with a new key until this is reconciled.",
                },
            )
        else:
            status, effect_state, error = "accepted", "launch-requested", None

        session.journal.append(
            "observed",
            {
                "operationId": operation_id,
                "effectState": effect_state,
                "pidMatched": pid_matched,
                "launchedPid": launch.pid,
                "launchedPidObserved": launched_process is not None,
                "queryOk": observe_query_ok,
                "observed": (observed["processes"][0] if observed and observed["processes"] else None),
                "simulated": self.backend.simulated,
            },
        )

        terminal_data = {
            "operationId": operation_id,
            "method": method,
            "target": target,
            "targetDisplayName": spec["displayName"],
            "launchedVia": spec.get("launchedVia", "direct"),
            "shortcut": (
                {
                    "path": spec["shortcutPath"],
                    "arguments": spec["shortcutArguments"],
                }
                if spec.get("shortcutPath")
                else None
            ),
            "effectState": effect_state,
            "sandboxReadiness": SANDBOX_READINESS,
            "request": {
                    "executablePath": spec["executablePath"],
                    "arguments": list(spec.get("argv") or ()),
                    "shellUsed": False,
                    "elevation": launch.elevation,
                    "launchedVia": spec.get("launchedVia", "direct"),
                },
            "launch": launch.to_dict(),
            "observedProcess": (
                launched_process
                if request_only
                else (
                    observed["processes"][0]
                    if observed and observed["processes"]
                    else launched_process
                )
            ),
            "pidMatched": pid_matched if observed is not None else None,
            "pidOnlyMatch": elevated_pid_row is not None,
            "shortcutRequest": (
                {
                    "sent": launch.returned,
                    "arguments": list(argv),
                    "launchedPid": launch.pid,
                    "launcherProcessObserved": launched_process is not None,
                    "gameStartObserved": False,
                    "note": (
                        "A launcher process already running is NOT evidence that this "
                        "request was delivered, and this bridge never treats it as such. "
                        "Whether the game starts is not observed here."
                    ),
                }
                if request_only
                else None
            ),
            "replayed": False,
            "backend": self._backend_info(),
            "meaning": (
                "effectState 'shortcut-requested' means the fixed shortcut request was "
                "issued and a process was created for it; 'launch-requested' means the "
                "executable was started and the process table confirms it. Neither means "
                "the sandbox is ready or that the game started."
            ),
        }

        envelope = self._finish(
            session, operation_id, method, key, request_hash,
            status, effect_state, terminal_data, warnings, error=error,
            simulated=self.backend.simulated,
        )
        return self._respond(request, status, envelope, error)

    def _finish(
        self,
        session: Session,
        operation_id: str,
        method: str,
        key: str,
        request_hash: str,
        status: str,
        effect_state: str,
        data: dict[str, Any],
        warnings: list[str],
        *,
        error: BridgeError | None,
        simulated: bool,
    ) -> dict[str, Any]:
        """Write the terminal record, then build the envelope it will be replayed as."""
        revision = session.state.revision + 1
        observation = self._observation(
            revision,
            source="mock-process-query" if self.backend.simulated else "os-process-query",
            coverage=["process-table"],
            extra={
                "effectState": effect_state,
                "simulated": self.backend.simulated,
                "target": data.get("target"),
            },
        )
        evidence = [
            {
                "artifactId": f"journal:{session.state.record_count + 1:012d}",
                "kind": "operation-record",
                "simulated": simulated,
                "path": str(self.store.paths.journal),
            }
        ]
        envelope = {
            "data": data,
            "observation": observation,
            "evidence": evidence,
            "warnings": warnings,
            "error": error.to_dict() if error else None,
        }
        session.journal.append(
            "terminal",
            {
                "operationId": operation_id,
                "method": method,
                "status": status,
                "effectState": effect_state,
                "idempotencyKey": key,
                "requestHash": request_hash,
                "revision": revision,
                "simulated": simulated,
                "envelope": envelope,
                "error": error.to_dict() if error else None,
            },
        )
        return envelope


def build_bridge(store: BridgeStore, backend: ProcessBackend, launcher: Launcher) -> Bridge:
    return Bridge(store, backend, launcher)
