#!/usr/bin/env python3
"""Mint one bridge scope -- Python equivalent of ``tools/editor-bridge/new-scope.ps1``.

The .ps1 cannot run on this machine (execution policy refuses script files; ``pwsh`` is
not installed).  ``docs/CONTRIBUTING.md`` Sec.6 makes the Python equivalent the sanctioned
route, and forbids ``-ExecutionPolicy Bypass``.

What a scope is
---------------
``.runtime/editor-bridge/runs/<guid>/`` holding exactly three files:

  ``bridge-settings.json``  the six-member lease the bridge parses strictly
                            (pid, startUtcTicks, nonce, pipeName, expiresUtc, expectedExe);
  ``frozen.json``           the SHA-256 of the four artifacts the loader must find
                            unchanged (bootstrap, bridge, launcher, native);
  ``compatibility.json``    the compatibility pin, re-verified by ``load-bridge.py``
                            before the injector is invoked.

The scope is a *lease* (5 minutes) plus a *frozen-artifact receipt*.  It is not a
permission to inject: ``load-bridge.py`` re-checks the process identity, the editor
assembly and all four hashes against the live disk, then consumes a single-use claim.

Order matters and is preserved from the .ps1
--------------------------------------------
The version gate runs **before** the run directory is created.  An updated or missing
editor assembly is refused with ``EDITOR_VERSION_UNSUPPORTED`` / ``EDITOR_DLL_MISSING``
and leaves no scope artifact behind.  The offline regression suite asserts exactly that
(a refused target must not create a run directory).

Usage
-----
    python new-scope.py --target-pid 12345
    python new-scope.py --target-pid 12345 --dry-run     # print the artifacts, write nothing

Exit codes
----------
    0  scope created (or, with --dry-run, the plan printed)
    1  refused.  The .ps1 has no try/catch, so an uncaught ``throw`` leaves PowerShell's
       ``-File`` host with exit code 1; this port matches that.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bridge_host                                          # noqa: E402
import compatibility_guard as guard                         # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 1

SCOPE_MINUTES = 60


def default_project_root() -> Path:
    """``[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))``, sanity-checked."""
    return bridge_host.assert_project_root(Path(__file__).resolve().parents[2])


def _observe_target(target_pid: int):
    """``Get-Process -Id $TargetPid`` plus the three facts new-scope reads from it."""
    process_name = bridge_host.process_name(target_pid)
    if not guard.ps_in(process_name, guard.ALLOWED_PROCESS_NAMES):
        raise guard.BridgeGuardError("TARGET_NOT_ALLOWED:process-name:" + process_name)
    start_ticks = bridge_host.process_start_utc_ticks(target_pid)
    if start_ticks <= 0:
        raise guard.BridgeGuardError("START_TICKS_MISSING")
    try:
        image_path = bridge_host.process_image_path(target_pid)
    except bridge_host.ImageUnreadableError:
        # Matches the .ps1's ``catch { throw 'TARGET_IMAGE_UNREADABLE:' + $proc.ProcessName }``.
        raise guard.BridgeGuardError("TARGET_IMAGE_UNREADABLE:" + process_name)
    return process_name, image_path, start_ticks


def build_scope(target_pid: int, project_root: Path, *, run_id: str | None = None) -> dict:
    """Everything that must be checked, plus the three artifact documents.

    Returns a plan dict; nothing is written.  Raises :class:`BridgeGuardError` on any
    refusal.  The version gate runs inside :func:`guard.get_compatibility_pin`, before
    the caller ever touches the run directory.
    """
    process_name, image_path, start_ticks = _observe_target(target_pid)

    # Version gate, before ANY run-directory or scope artifact exists.
    pin = guard.get_compatibility_pin(str(project_root), process_name, image_path, start_ticks)

    run_id = run_id or str(uuid.uuid4())
    run_dir = bridge_host.run_directory(project_root, run_id)

    # 32 CSPRNG bytes, hex-encoded upper-case without separators:
    #   [BitConverter]::ToString($bytes).Replace('-','')
    nonce = secrets.token_bytes(32).hex().upper()

    scope = {
        "pid": int(target_pid),
        "startUtcTicks": str(start_ticks),
        "nonce": nonce,
        "pipeName": "miliastra-bridge-" + run_id,
        "expiresUtc": guard.ps_roundtrip_iso(guard.utc_now() + timedelta(minutes=SCOPE_MINUTES)),
        "expectedExe": pin["expectedImagePath"],
    }
    frozen = {name: guard.file_sha256(path)
              for name, path in bridge_host.artifact_paths(project_root).items()}

    return {
        "runId": run_id,
        "runDir": str(run_dir),
        "bridgeSettings": scope,
        "frozen": frozen,
        "compatibility": pin,
    }


def commit_scope(plan: dict) -> dict:
    """Write the three artifacts.  ``New-Item -ItemType Directory`` then three writes."""
    run_dir = Path(plan["runDir"])
    # ``New-Item -ItemType Directory`` creates parents and fails when the leaf exists.
    os.makedirs(run_dir, exist_ok=False)
    bridge_host.write_json_file(run_dir / "bridge-settings.json", plan["bridgeSettings"])
    bridge_host.write_json_file(run_dir / "frozen.json", plan["frozen"])
    bridge_host.write_json_file(run_dir / "compatibility.json", plan["compatibility"])
    return plan


def summary(plan: dict) -> dict:
    """The object the .ps1 prints: runId, pid, expiresUtc, verdict, gate flag."""
    return {
        "runId": plan["runId"],
        "pid": plan["bridgeSettings"]["pid"],
        "expiresUtc": plan["bridgeSettings"]["expiresUtc"],
        "compatibilityVerdict": plan["compatibility"]["verdict"],
        "editorDllGateApplied": plan["compatibility"]["editorDllGateApplied"],
    }


def dry_run_report(plan: dict) -> dict:
    """Everything the run would contain -- for review before anything is written."""
    return {
        "dryRun": True,
        "note": "nothing was written; no run directory was created",
        "runDir": plan["runDir"],
        "files": {
            "bridge-settings.json": plan["bridgeSettings"],
            "frozen.json": plan["frozen"],
            "compatibility.json": plan["compatibility"],
        },
        "wouldPrint": summary(plan),
    }


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-pid", "--targetPid", dest="target_pid", type=int, required=True,
                        help="pid of the editor (or TestHost) process to scope against")
    parser.add_argument("--dry-run", "--dryRun", dest="dry_run", action="store_true",
                        help="print the artifacts that would be written and write nothing")
    parser.add_argument("--project-root", dest="project_root", default=None,
                        help="override the derived project root (offline tests only; it "
                             "selects WHERE files are read, never WHAT is accepted)")
    args = parser.parse_args(argv)

    project_root = None
    try:
        project_root = (Path(args.project_root).resolve() if args.project_root
                        else default_project_root())
        plan = build_scope(args.target_pid, project_root)
    except guard.BridgeGuardError as refusal:
        print(bridge_host.ps_convert_to_json({"ok": False, "code": refusal.code,
                                              "error": str(refusal)}))
        return EXIT_REFUSED
    except (bridge_host.ProcessQueryError, bridge_host.ImageUnreadableError) as error:
        # ``Get-Process -Id`` threw: no such pid, or the process could not be queried.
        print(bridge_host.ps_convert_to_json({"ok": False, "code": "TARGET_PROCESS_MISSING",
                                              "error": str(error)}))
        return EXIT_REFUSED
    except RuntimeError as error:
        # e.g. PROJECT_ROOT_NOT_RECOGNISED: this file is not next to the project.
        print(bridge_host.ps_convert_to_json({"ok": False,
                                              "code": str(error).split(":", 1)[0],
                                              "error": str(error)}))
        return EXIT_REFUSED

    if args.dry_run:
        print(bridge_host.ps_convert_to_json(dry_run_report(plan)))
        return EXIT_OK

    commit_scope(plan)
    print(bridge_host.ps_convert_to_json(summary(plan)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
