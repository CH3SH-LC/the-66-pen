#!/usr/bin/env python3
"""Offline compatibility gate for the editor bridge.

Python equivalent of ``tools/editor-bridge/compatibility-guard.ps1`` (201 lines,
8 functions).  Written because this machine refuses to run ``.ps1`` scripts:

  * ``pwsh`` (PowerShell 7) is not installed;
  * Windows PowerShell 5.1 is blocked by execution policy -- measured
    "cannot load file ... because running scripts is disabled on this system".

``docs/CONTRIBUTING.md`` Sec.6 and ``scripts/check-goal.py`` record the project rule:
a policy-blocked ``.ps1`` gets a Python equivalent and is **not** routed around with
``-ExecutionPolicy Bypass`` (changing execution policy is the user's decision, not an
agent's).  This module is that equivalent for the guard; ``new-scope.py`` and
``load-bridge.py`` sit beside it.

WHY THE GATE EXISTS (unchanged from the .ps1)
---------------------------------------------
The bridge reflects into the loaded BeyondEditor assembly; this gate checks its disk
build.  The 2026-09-24 game update replaced that file and the obfuscated core
type/field names the Adapter depends on are gone from the new binary, so loading the
bridge into the updated editor resolves nothing and used to report success on zero
invocations.  The gate makes the version boundary explicit and is checked BEFORE any
scope artifact is created or any injector is launched.

WHAT IT KNOWS
-------------
Exactly one supported fingerprint: the 7.1 ported BeyondEditor.dll at the exact
editor install path.  Everything else is refused.  There is deliberately **no**
parameter that accepts a caller-supplied hash and no bypass switch: the only inputs
are the process identity the caller already observed.  The offline tests substitute
the two file probes (:func:`file_sha256`, :func:`is_leaf_file`) exactly the way the
.ps1 test substituted ``Get-FileHash`` / ``Test-Path`` -- never by relaxing the gate.

WHAT IT DOES NOT DO
-------------------
It only reads files.  It never starts the game, the editor, an injector or a process;
it never writes, moves or deletes anything.

FIDELITY NOTES (see mapping.md for the full table)
--------------------------------------------------
* PowerShell's ``-eq``/``-ne``/``-ine``/``-contains`` are **case-insensitive** by
  default.  Every comparison here is case-folded to match.
* ``[IO.Path]::IsPathFullyQualified`` does not exist in Windows PowerShell 5.1, so the
  .ps1 keeps its own "rooted AND drive-qualified" test; :func:`test_fully_qualified_path`
  ports that predicate literally (UNC and ``C:foo`` are both refused, as in the .ps1).
* ``[DateTimeOffset]::UtcNow.ToString('o')`` emits **seven** fractional digits;
  :func:`ps_roundtrip_iso` reproduces that shape rather than Python's six.
"""
from __future__ import annotations

import ntpath
import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Policy.  Editing this block is the only way to change what is accepted; nothing
# reads an allowlist from disk at run time.  Mirrors $script:MiliastraCompatibility.
# ---------------------------------------------------------------------------

#: The one adapted editor assembly this project's reflection mappings were built
#: against.  7.1 static mapping and 256 metadata contracts independently validated;
#: the loaded module MVID and signatures are also checked by EditorBindingProfile.
SUPPORTED_EDITOR_DLL_SHA256 = "565DDA11883F0220BAE050438FCF52B2288F26B61ED656E2B4CD6D69B41A678A"

#: The editor executable the Adapter was verified against.  Pinned as a full literal
#: path, never derived from caller input, so a relocated copy is refused.
EDITOR_EXE_PATH = r"C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.exe"

EDITOR_DLL_NAME = "BeyondEditor.dll"

#: Project-owned test double.  Not an editor build, so the editor DLL gate cannot
#: apply to it; its identity is still pinned to this exact path.
TESTHOST_RELATIVE_PATH = "tools/editor-bridge/TestHost/bin/Release/net8.0-windows/TestHost.exe"

ALLOWED_PROCESS_NAMES = ("TestHost", "BeyondEditor")

ERROR_DLL_MISSING = "EDITOR_DLL_MISSING"
ERROR_VERSION_UNSUPPORTED = "EDITOR_VERSION_UNSUPPORTED"


class BridgeGuardError(RuntimeError):
    """Refusal raised by this gate.

    The message always *starts with* the machine-readable refusal code, which is how
    the .ps1 signalled refusals too (``throw 'SCOPE_EXPIRED'`` etc.).  Callers that
    only need the code can read :attr:`code`.
    """

    #: The code is the leading ``A-Z0-9_-`` run of the message (``TARGET_NOT_ALLOWED``
    #: style codes carry a colon-separated detail after the code).
    @property
    def code(self) -> str:
        return str(self).split(":", 1)[0]


# ---------------------------------------------------------------------------
# Small PowerShell-semantics helpers
# ---------------------------------------------------------------------------

def ps_str(value) -> str:
    """``[string]$value`` -- ``$null`` stringifies to the empty string."""
    return "" if value is None else str(value)


def ps_eq(left, right) -> bool:
    """``-eq`` / ``-ine``: compare as strings, case-insensitively, null-safe."""
    return ps_str(left).casefold() == ps_str(right).casefold()


def ps_in(value, collection) -> bool:
    """``-contains`` / ``-in``: case-insensitive membership."""
    wanted = ps_str(value).casefold()
    return any(ps_str(item).casefold() == wanted for item in collection)


def ps_like(value, pattern: str) -> bool:
    """The slice of ``-like`` this project uses: a single leading ``*`` wildcard."""
    text = ps_str(value).casefold()
    pat = ps_str(pattern).casefold()
    if pat.startswith("*"):
        return text.endswith(pat[1:])
    return text == pat


def is_null_or_whitespace(value) -> bool:
    """``[string]::IsNullOrWhiteSpace([string]$value)``."""
    return ps_str(value).strip() == ""


def ps_roundtrip_iso(moment: datetime) -> str:
    """``[DateTimeOffset]::ToString('o')`` -- seven fractional digits + explicit offset."""
    moment = moment.astimezone(timezone.utc)
    return "%s.%07d+00:00" % (moment.strftime("%Y-%m-%dT%H:%M:%S"),
                              moment.microsecond * 10)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_path_rooted(literal_path: str) -> bool:
    """``[IO.Path]::IsPathRooted`` for Windows (drive, UNC or rooted separator)."""
    if not literal_path:
        return False
    if literal_path[0] in ("\\", "/", ":"):
        return True
    return len(literal_path) >= 2 and literal_path[1] == ":"


# ---------------------------------------------------------------------------
# File probes.  Each is its own thin function so the offline tests can substitute
# it, exactly as the .ps1 tests substituted Get-FileHash / Test-Path.  No hash is
# ever parsed inline and no path is ever accepted from a caller as a hash.
# ---------------------------------------------------------------------------

def is_leaf_file(literal_path) -> bool:
    """``Test-Path -LiteralPath <p> -PathType Leaf``."""
    if literal_path is None:
        return False
    try:
        return os.path.isfile(literal_path)
    except OSError:
        return False


def file_sha256(literal_path) -> str:
    """``(Get-FileHash -LiteralPath <p> -Algorithm SHA256).Hash``, upper-cased.

    The .ps1 maps a whitespace result to ``HASH_UNREADABLE:<path>``; this port maps
    the unreadable-file OSError to the same code (PowerShell would surface its own
    ``Get-FileHash`` error text there -- both refuse, only the message text differs).
    """
    if is_null_or_whitespace(literal_path):
        raise BridgeGuardError("HASH_PATH_EMPTY")
    digest = hashlib.sha256()
    try:
        with open(literal_path, "rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        raise BridgeGuardError("HASH_UNREADABLE:" + ps_str(literal_path))
    return digest.hexdigest().upper()


# ---------------------------------------------------------------------------
# The guard (one function per .ps1 function)
# ---------------------------------------------------------------------------

def get_compatibility_policy() -> dict:
    """A copy, so a caller cannot mutate the policy through the returned object."""
    return {
        "supportedEditorDllSha256": SUPPORTED_EDITOR_DLL_SHA256,
        "editorExePath": EDITOR_EXE_PATH,
        "editorDllPath": get_editor_dll_path(),
        "allowedProcessNames": list(ALLOWED_PROCESS_NAMES),
    }


def test_fully_qualified_path(literal_path) -> bool:
    """Rooted AND carrying a drive-qualified prefix, which excludes ``C:foo``."""
    text = ps_str(literal_path)
    if is_null_or_whitespace(text):
        return False
    if not _is_path_rooted(text):
        return False
    return len(text) >= 3 and text[1] == ":" and text[2] in ("\\", "/")


def get_editor_dll_path() -> str:
    return ntpath.join(ntpath.dirname(EDITOR_EXE_PATH), EDITOR_DLL_NAME)


def get_testhost_path(project_root) -> str:
    return ntpath.normpath(ntpath.join(str(project_root), TESTHOST_RELATIVE_PATH))


def assert_target_identity(project_root, process_name, image_path, start_utc_ticks=0) -> str:
    """Identity of the target process, as the caller observed it.

    Name / path / ticks only: nothing here touches the process or the game.
    Returns the expected image path.
    """
    if not ps_in(process_name, ALLOWED_PROCESS_NAMES):
        raise BridgeGuardError("TARGET_NOT_ALLOWED:process-name:" + ps_str(process_name))
    if not test_fully_qualified_path(image_path):
        raise BridgeGuardError("TARGET_IMAGE_MISSING")
    if ps_eq(process_name, "BeyondEditor"):
        expected = EDITOR_EXE_PATH
    else:
        expected = get_testhost_path(project_root)
    if not ps_eq(image_path, expected):
        raise BridgeGuardError("TARGET_NOT_ALLOWED:image-path:" + ps_str(image_path))
    if int(start_utc_ticks) <= 0:
        raise BridgeGuardError("START_TICKS_MISSING")
    return expected


def get_compatibility_pin(project_root, process_name, image_path, start_utc_ticks=0) -> dict:
    """The gate itself.  Returns a pin describing what was verified, or raises.

    For the game editor the pin is only produced when the disk assembly is the one
    supported hash; an unknown or missing assembly is refused here, before the caller
    has created any run directory or touched an injector.
    """
    expected = assert_target_identity(project_root, process_name, image_path, start_utc_ticks)

    pin = {
        "kind": process_name,
        "imagePath": image_path,
        "expectedImagePath": expected,
        "startUtcTicks": ps_str(start_utc_ticks),
        "supportedDllSha256": SUPPORTED_EDITOR_DLL_SHA256,
        "dllPath": None,
        "dllSha256": None,
        "editorDllGateApplied": False,
        "verdict": "testhost-compatibility-gate-not-applicable",
        "checkedUtc": ps_roundtrip_iso(utc_now()),
    }

    if ps_eq(process_name, "TestHost"):
        # Project-owned test double, pinned to its exact path above.  It does not load
        # the editor assembly, so applying the editor DLL gate to it would block the
        # only offline target this project has.
        return pin

    dll_path = get_editor_dll_path()
    pin["editorDllGateApplied"] = True
    pin["dllPath"] = dll_path
    if not is_leaf_file(dll_path):
        raise BridgeGuardError(ERROR_DLL_MISSING + ":" + dll_path)
    actual = file_sha256(dll_path)
    pin["dllSha256"] = actual
    if not ps_eq(actual, SUPPORTED_EDITOR_DLL_SHA256):
        raise BridgeGuardError(ERROR_VERSION_UNSUPPORTED + ":disk=" + actual +
                               ":supported=" + SUPPORTED_EDITOR_DLL_SHA256)
    pin["verdict"] = "editor-assembly-supported"
    return pin


def _pin_get(pin, name):
    """PowerShell property access: a missing member (or a $null object) reads as $null."""
    if isinstance(pin, dict):
        return pin.get(name)
    return None


def assert_compatibility_pin(pin, project_root, process_name, image_path, start_utc_ticks) -> dict:
    """Re-check for the load step.

    The editor may have been updated (or the file swapped) between scope creation and
    injection.  Re-reads the disk assembly and compares it to both the supported hash
    and the hash pinned at scope time.  Note the .ps1 compares *before* the null check,
    so a $null pin reads as "identity-or-build-mismatch"; that order is preserved.
    """
    current = get_compatibility_pin(project_root, process_name, image_path, start_utc_ticks)
    if (not ps_eq(_pin_get(pin, "kind"), current["kind"]) or
            not ps_eq(_pin_get(pin, "imagePath"), current["imagePath"]) or
            not ps_eq(_pin_get(pin, "startUtcTicks"), current["startUtcTicks"]) or
            not ps_eq(_pin_get(pin, "dllPath"), current["dllPath"]) or
            not ps_eq(_pin_get(pin, "dllSha256"), current["dllSha256"])):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:identity-or-build-mismatch")
    if pin is None:
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:missing")
    if is_null_or_whitespace(_pin_get(pin, "kind")):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:kind")
    if is_null_or_whitespace(_pin_get(pin, "imagePath")):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:imagePath")
    if is_null_or_whitespace(_pin_get(pin, "startUtcTicks")):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:startUtcTicks")

    if ps_eq(_pin_get(pin, "kind"), "TestHost"):
        if _pin_get(pin, "editorDllGateApplied") is True:
            raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:testhost-gate")
        if not ps_like(_pin_get(pin, "imagePath"), "*\\TestHost.exe"):
            raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:testhost-image")
        return {"ok": True, "kind": "TestHost",
                "check": "editor-dll-gate-not-applicable", "dllSha256": None}

    if _pin_get(pin, "editorDllGateApplied") is not True:
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:editor-gate-skipped")
    if is_null_or_whitespace(_pin_get(pin, "dllPath")):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:dllPath")
    if is_null_or_whitespace(_pin_get(pin, "dllSha256")):
        raise BridgeGuardError("COMPATIBILITY_PIN_INVALID:dllSha256")
    pinned_dll_path = ps_str(_pin_get(pin, "dllPath"))
    if not is_leaf_file(pinned_dll_path):
        raise BridgeGuardError(ERROR_DLL_MISSING + ":" + pinned_dll_path)
    actual = file_sha256(pinned_dll_path)
    if not ps_eq(actual, _pin_get(pin, "dllSha256")):
        raise BridgeGuardError(ERROR_VERSION_UNSUPPORTED +
                               ":editor-changed-since-scope:disk=" + actual +
                               ":pinned=" + ps_str(_pin_get(pin, "dllSha256")))
    if not ps_eq(actual, SUPPORTED_EDITOR_DLL_SHA256):
        raise BridgeGuardError(ERROR_VERSION_UNSUPPORTED + ":disk=" + actual)
    return {"ok": True, "kind": "BeyondEditor",
            "check": "editor-assembly-supported", "dllSha256": actual}


__all__ = [
    "SUPPORTED_EDITOR_DLL_SHA256", "EDITOR_EXE_PATH", "EDITOR_DLL_NAME",
    "TESTHOST_RELATIVE_PATH", "ALLOWED_PROCESS_NAMES",
    "ERROR_DLL_MISSING", "ERROR_VERSION_UNSUPPORTED",
    "BridgeGuardError",
    "ps_str", "ps_eq", "ps_in", "ps_like", "is_null_or_whitespace",
    "ps_roundtrip_iso", "utc_now",
    "is_leaf_file", "file_sha256",
    "get_compatibility_policy", "test_fully_qualified_path", "get_editor_dll_path",
    "get_testhost_path", "assert_target_identity", "get_compatibility_pin",
    "assert_compatibility_pin",
]


if __name__ == "__main__":  # pragma: no cover - inspection only, reads nothing
    import json
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(get_compatibility_policy(), ensure_ascii=False, indent=2))
