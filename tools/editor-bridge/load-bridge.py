#!/usr/bin/env python3
"""Inject the bridge into an already-scoped editor process.

Python equivalent of ``tools/editor-bridge/load-bridge.ps1`` (45 lines).  Written
because this machine refuses to run ``.ps1`` scripts (see ``compatibility_guard.py``).

This is the **effectful** half: without ``--dry-run`` it starts
``Snoop.InjectorLauncher.x64.exe`` against the live target process, which loads
``Miliastra.Bootstrap.Entry.Start`` inside the editor, which loads the bridge payload.
It is the only step in the chain that touches another process.

Guards, in the .ps1's order (each one refuses; none is optional)
---------------------------------------------------------------
  1. ``bridge-settings.json`` and ``frozen.json`` readable;
  2. ``compatibility.json`` present -- else ``COMPATIBILITY_PIN_INVALID:missing-file``;
  3. the lease has not expired -- else ``SCOPE_EXPIRED``;
  4. the target pid still exists;
  5. its start ticks equal the scope's -- else ``START_TIME_MISMATCH``  (**pid reuse**);
  6. start ticks positive -- else ``START_TICKS_MISSING``;
  7. its image path readable, and name/path/ticks pass ``Assert-MiliastraTargetIdentity``
     (allow-list, exact image path, positive ticks);
  8. the live image path equals ``scope.expectedExe`` -- else
     ``TARGET_NOT_ALLOWED:scope-image-path``;
  9. the live process name equals ``pin.kind`` -- else ``TARGET_NOT_ALLOWED:pin-kind``;
 10. the compatibility pin is re-derived and re-compared -- the editor may have been
     updated between the two steps.  Runs **before** the claim, so a refused version
     cannot consume the single injection attempt;
 11. all four artifact SHA-256 values match ``frozen.json``;
 12. launcher and native carry a valid Authenticode signature;
 13. a single-use ``loader.claim`` is created with O_EXCL semantics; a second run of
     the same scope cannot inject again;
 14. the launcher runs, stdout/stderr are redirected, ``loader-result.json`` is written.

``--dry-run`` performs 1-12, prints the exact launcher command line, and **writes
nothing**: no claim, no output files, no result.  That is the review gate the main
session asked for, because steps 13-14 cannot be undone for the process being injected.

Usage
-----
    python load-bridge.py --run-id 0a6d5af9-be81-47bb-9000-b5ad81285da3 --dry-run
    python load-bridge.py --run-id 0a6d5af9-be81-47bb-9000-b5ad81285da3

Exit codes
----------
    0  the loader ran (its own exit code is in ``loader-result.json``), or --dry-run
       validated everything and printed the command
    2  refused or failed, matching the .ps1's explicit ``exit 2``.  ``loader-result.json``
       carries ``phase='loader-refused-or-failed'`` and the message.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_host                                          # noqa: E402
import compatibility_guard as guard                         # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 2

BOOTSTRAP_CLASS = "Miliastra.Bootstrap.Entry"
BOOTSTRAP_METHOD = "Start"

SUCCESS_PHASES = ("dry-run-validated", "loader-returned")


def default_project_root() -> Path:
    """``[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))``, sanity-checked."""
    return bridge_host.assert_project_root(Path(__file__).resolve().parents[2])


def parse_expires_utc(text) -> datetime:
    """``[DateTimeOffset]::Parse($scope.expiresUtc)``.

    Accepts the seven-fraction-digit ISO the .ps1 writes and the six-digit ISO this
    port writes.  A stamp with no explicit offset is read as local time, which is what
    ``DateTimeOffset.Parse`` does.
    """
    moment = datetime.fromisoformat(guard.ps_str(text).strip())
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment


def _launch_loader(command: list, run_dir: Path) -> int:
    """Run the injector and capture its output the way ``1>``/``2>`` redirects do.

    The single effectful seam of this script.  The offline tests substitute it, the
    same way the .ps1 regression suite substituted ``New-Item`` -- so every guard path
    can be exercised without ever starting the injector.

    No shell re-parses the arguments: the launcher path and each argument travel as a
    list through ``subprocess``, not through a command string.
    """
    completed = subprocess.run(command, capture_output=True)
    bridge_host.write_captured_output(run_dir / "loader.stdout.txt", completed.stdout)
    bridge_host.write_captured_output(run_dir / "loader.stderr.txt", completed.stderr)
    return completed.returncode


def guard_scope(scope, frozen, pin, project_root, settings_path):
    """Steps 3-12.  Returns ``(pid, process_name, image_path, start_ticks, command)``."""
    if guard.utc_now() >= parse_expires_utc(scope.get("expiresUtc")):
        raise guard.BridgeGuardError("SCOPE_EXPIRED")

    pid = int(scope["pid"])
    process_name = bridge_host.process_name(pid)
    start_ticks = bridge_host.process_start_utc_ticks(pid)

    if start_ticks != int(scope["startUtcTicks"]):
        raise guard.BridgeGuardError("START_TIME_MISMATCH")
    if start_ticks <= 0:
        raise guard.BridgeGuardError("START_TICKS_MISSING")

    try:
        image_path = bridge_host.process_image_path(pid)
    except bridge_host.ImageUnreadableError:
        raise guard.BridgeGuardError("TARGET_IMAGE_UNREADABLE:" + process_name)

    # Same identity policy as new-scope: name, exact image path, positive start ticks.
    guard.assert_target_identity(str(project_root), process_name, image_path, start_ticks)
    if not guard.ps_eq(image_path, scope.get("expectedExe")):
        raise guard.BridgeGuardError("TARGET_NOT_ALLOWED:scope-image-path")
    if not guard.ps_eq(process_name, pin.get("kind") if isinstance(pin, dict) else None):
        raise guard.BridgeGuardError("TARGET_NOT_ALLOWED:pin-kind")

    # Re-checked here, not only at scope creation: an editor update that lands between
    # the two steps must stop the loader.  Runs BEFORE loader.claim, so a refused
    # version cannot consume the single injection attempt for this scope.
    guard.assert_compatibility_pin(pin, str(project_root), process_name, image_path, start_ticks)

    artifacts = bridge_host.artifact_paths(project_root)
    for name in ("bridge", "bootstrap", "launcher", "native"):   # the .ps1's own order
        if not guard.ps_eq(guard.file_sha256(artifacts[name]), frozen.get(name)):
            raise guard.BridgeGuardError(
                "ARTIFACT_HASH_MISMATCH:" + name + ":" + guard.ps_str(artifacts[name]))

    for which in ("launcher", "native"):
        status, detail = bridge_host.authenticode_status(artifacts[which])
        if not guard.ps_eq(status, "Valid"):
            # The .ps1's message is the bare code; the file, status and method are
            # appended here (the project's own "CODE:detail" convention) because an
            # otherwise identical signature refusal would be unattributable.
            raise guard.BridgeGuardError(
                "UPSTREAM_SIGNATURE_INVALID:" + which + ":" + guard.ps_str(status) + ":" + detail)

    command = bridge_host.launcher_command(
        artifacts["launcher"], artifacts["bootstrap"], settings_path, scope["pid"])
    return pid, process_name, image_path, start_ticks, command


def _refusal_payload(message: str) -> dict:
    return {"phase": "loader-refused-or-failed", "error": message}


def _finish_refusal(payload: dict, result_path: Path, record: dict, dry_run: bool) -> dict:
    record.update(payload)
    record["exitCode"] = EXIT_REFUSED
    if dry_run:
        return record
    # Mirrors the .ps1 catch block.  Two deliberate differences: (a) the file is only
    # written when its directory exists, so an unknown run id reports a clean
    # RUN_ARTIFACT_UNREADABLE instead of the .ps1's raw terminating error; (b) the
    # record is also printed, so a refusal is never silent.
    if result_path.parent.is_dir():
        bridge_host.write_result_file(result_path, payload)
    else:
        record["resultFileWritten"] = False
    return record


def run_load(run_id, *, project_root=None, dry_run=False) -> dict:
    """Everything the .ps1 does, returning a structured record instead of exiting."""
    root = Path(project_root).resolve() if project_root else default_project_root()
    run_dir = bridge_host.run_directory(root, run_id)
    settings_path = run_dir / "bridge-settings.json"
    result_path = run_dir / "loader-result.json"

    record = {"runId": str(run_id), "runDir": str(run_dir), "dryRun": bool(dry_run)}
    try:
        scope = bridge_host.read_json_file(settings_path)
        frozen = bridge_host.read_json_file(run_dir / "frozen.json")
        pin_path = run_dir / "compatibility.json"
        if not guard.is_leaf_file(pin_path):
            raise guard.BridgeGuardError("COMPATIBILITY_PIN_INVALID:missing-file")
        pin = bridge_host.read_json_file(pin_path)

        pid, process_name, image_path, start_ticks, command = guard_scope(
            scope, frozen, pin, root, settings_path)

        if dry_run:
            record.update({
                "phase": "dry-run-validated",
                "note": "nothing was written; no claim was taken and nothing was launched",
                "targetPid": pid,
                "processName": process_name,
                "imagePath": image_path,
                "startUtcTicks": str(start_ticks),
                "settingsFile": str(settings_path),
                "commandLine": bridge_host.quote_command_line(command),
                "argv": command,
                "compatibilityVerdict": pin.get("verdict") if isinstance(pin, dict) else None,
            })
            return record

        # A single launch attempt per scope.  CreateNew == O_CREAT|O_EXCL: a second
        # attempt for this scope fails rather than injecting twice.  In the .ps1 this
        # surfaced as an IOException through the bare ``catch``; it is given its own
        # code here so "this scope is already spent" is distinguishable from "something
        # else went wrong".
        claim_path = run_dir / "loader.claim"
        try:
            handle = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise guard.BridgeGuardError("LOADER_CLAIM_ALREADY_TAKEN:" + str(claim_path))
        os.close(handle)

        loader_exit = _launch_loader(command, run_dir)
        payload = {
            "phase": "loader-returned",
            "exitCode": loader_exit,
            "pid": pid,
            "startUtcTicks": str(scope["startUtcTicks"]),
            "readyFilePresent": guard.is_leaf_file(run_dir / "bridge-ready.json"),
            "compatibilityVerdict": pin.get("verdict") if isinstance(pin, dict) else None,
        }
        bridge_host.write_result_file(result_path, payload)
        record.update(payload)
        record["claimCreated"] = str(claim_path)
        return record
    except guard.BridgeGuardError as refusal:
        record["code"] = refusal.code
        return _finish_refusal(_refusal_payload(str(refusal)), result_path, record, dry_run)
    except (bridge_host.ProcessQueryError, bridge_host.ImageUnreadableError) as error:
        record["code"] = "TARGET_PROCESS_MISSING"
        return _finish_refusal(_refusal_payload("TARGET_PROCESS_MISSING:" + str(error)),
                               result_path, record, dry_run)
    except OSError as error:
        # The scope directory or one of its three files could not be read.
        record["code"] = "RUN_ARTIFACT_UNREADABLE"
        return _finish_refusal(_refusal_payload("RUN_ARTIFACT_UNREADABLE:" + str(error)),
                               result_path, record, dry_run)
    except Exception as error:                                # noqa: BLE001
        # The .ps1's ``catch`` is bare: it catches everything and records it.  Keeping
        # that breadth matters -- a refused injection must always leave a result file
        # rather than a traceback.  The offline suite is what stops a port bug hiding
        # here: every case that must pass asserts ``refused is False``.
        record["code"] = type(error).__name__
        return _finish_refusal(
            _refusal_payload("%s: %s" % (type(error).__name__, error)),
            result_path, record, dry_run)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", "--runId", dest="run_id", required=True,
                        help="the guid of the scope directory under .runtime/editor-bridge/runs")
    parser.add_argument("--dry-run", "--dryRun", dest="dry_run", action="store_true",
                        help="validate everything and print the launcher command line, "
                             "but take no claim, launch nothing and write nothing")
    parser.add_argument("--project-root", dest="project_root", default=None,
                        help="override the derived project root (offline tests only; it "
                             "selects WHERE files are read, never WHAT is accepted)")
    args = parser.parse_args(argv)

    try:
        record = run_load(args.run_id, project_root=args.project_root, dry_run=args.dry_run)
    except RuntimeError as error:
        # e.g. PROJECT_ROOT_NOT_RECOGNISED: this file is not next to the project.
        print(bridge_host.ps_convert_to_json(
            {"phase": "loader-refused-or-failed", "code": str(error).split(":", 1)[0],
             "error": str(error)}))
        return EXIT_REFUSED
    print(bridge_host.ps_convert_to_json(record))
    return EXIT_OK if record.get("phase") in SUCCESS_PHASES else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
