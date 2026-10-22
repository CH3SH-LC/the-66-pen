#!/usr/bin/env python3
"""Disk-only version gates for legacy writers and the reviewed 7.1 adapters.

``game`` retains the legacy PE/anchor baseline. It refuses the installed 7.1
image, protecting old fixed-offset and file writers. ``editor`` checks the
current 7.1 assembly SHA; the Adapter separately checks the loaded MVID and all
binding contracts. ``all`` requires both, so legacy writers remain blocked.

``native-scene`` lazily loads the separately hash-pinned readonly 7.1 profile
and calls only load_profile/verify_disk. It checks disk bytes, not a session,
memory, subprocess, UAC or game method. No gate grants runtime acceptance or
write permission. Native writes additionally require a complete same-session
snapshot, observed level, single-request coordinator review and recovery copy.

Unknown, unreadable or altered files fail closed. There is no override or
runtime allowlist from audit output. ``runtimeCompatible``/``runtimeVerified``
remain false or unknown. A disk match is never game acceptance.

CLI: --component game|editor|all|native-scene; exit 0 for a disk match only,
exit 2 for incompatible/unreadable evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import mmap
import struct
import sys
from pathlib import Path

CODE = "incompatible-version"
NATIVE_SCENE = "native-scene"
LEGACY_COMPONENTS = ("game", "editor", "all")

#: The fixed, versioned supported baseline.  Editing this file is the only way to
#: change what is accepted; nothing reads an allowlist from disk at run time.
GAME_IMAGE = Path(r"C:\Games\Genshin Impact Game\YuanShen.exe")
EDITOR_DLL = Path(r"C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.dll")
GAME_CONFIG = Path(r"C:\Games\Genshin Impact Game\config.ini")

#: Lazily imported disk-profile module for the native scene path.  It is reached
#: only when the ``native-scene`` component is asked for, and then only its
#: ``load_profile`` and ``verify_disk`` are called.
NATIVE_TOOLS = Path(__file__).resolve().parents[1] / "game-executor"
NATIVE_MODULE = "native_profiles"

BASELINE = {
    "game": {
        "label": "legacy-pe-1785321476",
        "machine": 0x8664,             # AMD64, from build_scene_profile.py
        "timestamp": 1785321476,
        "imageSize": 439631872,
        # name -> (RVA, expected instruction bytes), identical to
        # tools/game-executor/build_scene_profile.py ANCHORS.
        "anchors": {
            "CONTEXT": (0xDA508A0, "56574883ec284889ce803df95de2f7007445803d2aeeb0f7"),
            "LEVEL": (0xE920A70, "56574883ec284889ce803d426ec3f600488b0541f0c3f675"),
            "PLACE": (0xB7A1AA0, "41574156565755534881ecc80000004c89cf4489c389d048"),
            "SAVE": (0xDDBFE60, "555657534883ec68488d6c246048c745f8feffffff4889cb"),
        },
    },
    "editor": {
        "label": "beyondeditor-7.1-565dda11",
        # docs/editor-catalog/CODE-SURFACE.md:22 (measured).
        "sha256": "565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a",
    },
}


class IncompatibleVersion(RuntimeError):
    """Raised by :func:`require_compatible`; ``.report`` holds the full refusal."""

    code = CODE

    def __init__(self, report: dict):
        self.report = report
        reasons = report.get("reasons") or ["unsupported baseline"]
        super().__init__(CODE + ": " + "; ".join(str(r) for r in reasons))


def digest_file(path: Path, chunk: int = 1 << 20) -> str:
    """Streaming SHA-256; never reads the whole file into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def declared_game_version(path: Path) -> str | None:
    """``game_version`` from the installation's own ``config.ini``, or None."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or line.startswith("["):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() == "game_version":
            return value.strip().strip('"') or None
    return None


def _field(data, offset: int, fmt: str):
    """Bounds-checked ``struct.unpack_from``; raises ValueError when truncated."""
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ValueError("out-of-range PE field at 0x%x (+%d, buffer %d)" % (offset, size, len(data)))
    return struct.unpack_from(fmt, data, offset)[0]


def inspect_image(data, baseline: dict) -> dict:
    """Parse PE identity + anchors out of a bytes-like buffer.

    ``data`` may be ``mmap`` or ``bytes``; only small windows are read.  Pure
    with respect to ``baseline``, which lets the offline tests inject a tiny
    synthetic PE with small RVAs instead of touching an installation.
    """
    checks: list[dict] = []
    reasons: list[str] = []

    def record(name: str, ok: bool, expected, actual) -> None:
        checks.append({"check": name, "match": bool(ok), "expected": expected, "actual": actual})
        if not ok:
            reasons.append("%s: expected %r, got %r" % (name, expected, actual))

    def report() -> dict:
        return {"kind": "pe-image", "supportedBaseline": baseline["label"],
                "matched": not reasons, "checks": checks, "reasons": reasons}

    try:
        size = len(data)
        if size < 64:
            reasons.append("pe-header: image shorter than a DOS header (%d bytes)" % size)
            return report()
        record("dosSignature", bytes(data[:2]) == b"MZ", "4d5a", bytes(data[:2]).hex())

        pe_offset = _field(data, 60, "<I")
        signature = bytes(data[pe_offset:pe_offset + 4]) if 0 <= pe_offset <= size - 4 else b""
        record("peSignature", signature == b"PE\0\0", "50450000", signature.hex())

        record("machine", _field(data, pe_offset + 4, "<H") == baseline["machine"],
               "0x%04x" % baseline["machine"], "0x%04x" % _field(data, pe_offset + 4, "<H"))
        record("timestamp", _field(data, pe_offset + 8, "<I") == baseline["timestamp"],
               baseline["timestamp"], _field(data, pe_offset + 8, "<I"))

        section_count = _field(data, pe_offset + 6, "<H")
        optional_size = _field(data, pe_offset + 20, "<H")
        optional = pe_offset + 24
        if optional_size < 60:
            reasons.append("optionalHeader: too small for an image size (%d bytes)" % optional_size)
            return report()
        record("optionalMagic", _field(data, optional, "<H") == 0x20B,
               "0x020b", "0x%04x" % _field(data, optional, "<H"))
        record("imageSize", _field(data, optional + 56, "<I") == baseline["imageSize"],
               baseline["imageSize"], _field(data, optional + 56, "<I"))

        table = optional + optional_size
        if table + section_count * 40 > size:
            reasons.append("sectionTable: %d sections do not fit in %d bytes" % (section_count, size))
            return report()
        # (virtual size, virtual address, raw size, raw pointer) -- the same
        # unpack build_scene_profile.py uses at optional+size+i*40+8.
        sections = [struct.unpack_from("<IIII", data, table + index * 40 + 8)
                    for index in range(section_count)]
    except (ValueError, struct.error) as error:
        reasons.append("malformed-pe: %s" % error)
        return report()

    for name, (rva, encoded) in baseline["anchors"].items():
        expected = bytes.fromhex(encoded)
        mapped = next((section for section in sections
                       if section[1] <= rva and rva + len(expected) <= section[1] + section[0]), None)
        if mapped is None:
            record(name, False, encoded, "no section maps RVA 0x%x" % rva)
            continue
        raw = mapped[3] + (rva - mapped[1])
        if raw + len(expected) > size or raw + len(expected) > mapped[3] + mapped[2]:
            record(name, False, encoded, "anchor window outside raw section data")
            continue
        actual = bytes(data[raw:raw + len(expected)])
        record(name, actual == expected, encoded, actual.hex())
    return report()


def _unreadable(component: str, path: Path, error: Exception) -> dict:
    return {"component": component, "path": str(path), "matched": False, "checks": [],
            "reasons": ["%s unreadable: %s" % (component, type(error).__name__)]}


def check_game(image: Path | None = None, config: Path | None = None) -> dict:
    """Read-only game image identity check. Never executes game code."""
    image = Path(image) if image else GAME_IMAGE
    config = Path(config) if config else GAME_CONFIG
    baseline = BASELINE["game"]
    entry = {"component": "game", "path": str(image), "evidence": "read-only disk bytes",
             "runtimeCompatible": False, "declaredVersionPath": str(config)}
    try:
        entry["fileBytes"] = image.stat().st_size
        with image.open("rb") as stream:
            # ACCESS_READ only; the 445 MB image is mapped, never loaded.
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                entry.update(inspect_image(data, baseline))
    except (OSError, ValueError) as error:
        return _unreadable("game", image, error)

    version = declared_game_version(config)
    entry["declaredVersion"] = version
    entry["declaredVersionEvidence"] = "supplemental config declaration only; not an acceptance condition"
    entry["matched"] = not entry["reasons"]
    return entry


def check_editor(dll: Path | None = None) -> dict:
    """Read-only assembly hash check. Does not load or probe the assembly."""
    dll = Path(dll) if dll else EDITOR_DLL
    baseline = BASELINE["editor"]
    entry = {"component": "editor", "path": str(dll), "evidence": "read-only disk bytes; assembly not loaded",
             "runtimeCompatible": "unknown", "runtimeVerified": False}
    try:
        entry["fileBytes"] = dll.stat().st_size
        digest = digest_file(dll)
    except OSError as error:
        return _unreadable("editor", dll, error)
    entry["sha256"] = digest
    ok = digest.lower() == baseline["sha256"].lower()
    entry["checks"] = [{"check": "sha256", "match": ok, "expected": baseline["sha256"], "actual": digest}]
    entry["reasons"] = [] if ok else ["sha256: expected %s, got %s" % (baseline["sha256"], digest)]
    entry["matched"] = ok
    return entry


def native_profiles_module():
    """Lazy import of ``tools/game-executor/native_profiles.py``.

    Importing that module performs no memory read, hook, game call, process
    launch or elevation.  This function is the only place it is reached, so the
    legacy components never depend on it and importing this guard stays cheap.
    """
    directory = str(NATIVE_TOOLS)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module(NATIVE_MODULE)


def check_native_scene(profile_path: Path | None = None, image: Path | None = None) -> dict:
    """Read-only disk check of the pinned read-only 7.1 profile against ``image``.

    Exactly two functions of the lazily imported module are called:
    ``load_profile()`` -- which hash-pins the profile source itself -- and
    ``verify_disk(profile, image=...)``.  No session is queried, no memory is
    read, no process is opened and no subprocess or elevation is requested.

    A match is disk evidence only.  ``runtimeCompatible`` and
    ``runtimeVerified`` stay false, ``diskEvidenceOnly`` is true and
    ``writePermission`` is false: the runtime review record, same-session
    validation, the complete snapshot and the explicit level check all remain
    with the native scene path downstream.

    ``profile_path`` selects *what is read*, never *what is accepted* -- the
    profile is still pinned to ``native_profiles.PROFILE_SHA256`` when loaded.
    Every failure, including an unimportable module, reports ``matched: false``.
    """
    image = Path(image) if image else GAME_IMAGE
    entry = {
        "component": NATIVE_SCENE, "path": str(image),
        "evidence": "read-only disk bytes; pinned read-only profile; no session query, no process access",
        "diskEvidenceOnly": True, "runtimeCompatible": False, "runtimeVerified": False,
        "writePermission": False, "sessionQueried": False, "processAccess": False,
        "profilePath": str(profile_path) if profile_path else "default pinned read-only profile",
        "downstreamChecks": "runtime review record, same-session validation, complete snapshot and explicit "
                            "level check remain with the native scene path; this check accepts none of them",
    }
    try:
        module = native_profiles_module()
        profile = module.load_profile() if profile_path is None else module.load_profile(Path(profile_path))
        observed = module.verify_disk(profile, image=image)
    except Exception as error:  # fail closed: "could not tell" is never compatible
        entry["checks"] = []
        entry["reasons"] = ["disk verification did not complete: %s: %s"
                            % (type(error).__name__, str(error)[:200])]
        entry["matched"] = False
        return entry

    # verify_disk raises instead of returning a mismatch, so every check listed
    # here passed; they echo the profile values that were actually enforced.
    declared = profile.get("image", {}) if isinstance(profile, dict) else {}
    entry["profileId"] = observed.get("profileId")
    entry["profileSha256Pin"] = getattr(module, "PROFILE_SHA256", None)
    entry["sha256"] = observed.get("sha256")
    entry["declaredFileBytes"] = declared.get("fileBytes")
    entry["timestamp"] = observed.get("timestamp")
    entry["sizeOfImage"] = observed.get("sizeOfImage")
    entry["checks"] = [
        {"check": "profileSourceHash", "match": True, "expected": entry["profileSha256Pin"],
         "actual": entry["profileSha256Pin"]},
        {"check": "imageFileBytes", "match": True, "expected": declared.get("fileBytes"),
         "actual": declared.get("fileBytes")},
        {"check": "imageSha256", "match": True, "expected": declared.get("sha256"),
         "actual": observed.get("sha256")},
        {"check": "imageTimestamp", "match": True, "expected": declared.get("timestamp"),
         "actual": observed.get("timestamp")},
        {"check": "imageSizeOfImage", "match": True, "expected": declared.get("sizeOfImage"),
         "actual": observed.get("sizeOfImage")},
        {"check": "anchors", "match": True, "expected": sorted(getattr(module, "ANCHOR_NAMES", ()) or []),
         "actual": sorted(observed.get("anchorNames") or [])},
        {"check": "allowWrites", "match": observed.get("allowWrites") is False, "expected": False,
         "actual": observed.get("allowWrites")},
    ]
    entry["reasons"] = [] if observed.get("allowWrites") is False else [
        "allowWrites: expected False, got %r" % observed.get("allowWrites")]
    entry["matched"] = not entry["reasons"]
    return entry


def check_compatibility(component: str = "all", *, game_image=None, editor_dll=None, config_ini=None,
                        native_profile=None, native_image=None) -> dict:
    """Report whether the requested components still match their pinned baseline.

    ``component`` is ``'game'``, ``'editor'``, ``'all'`` or ``'native-scene'``.
    ``'all'`` deliberately stays the legacy pair -- it never includes the
    native-scene profile, so a 7.1 disk match cannot widen the legacy gate.  The
    optional path arguments exist for offline synthetic-fixture inspection in
    tests; they select *what is read*, never *what is accepted* -- the baselines
    remain the fixed constants in this file (and in the lazily imported profile
    module, which hash-pins its own source).
    """
    if component not in LEGACY_COMPONENTS + (NATIVE_SCENE,):
        raise ValueError("component must be 'game', 'editor', 'all' or 'native-scene'")
    result = {
        "ok": False, "code": CODE, "component": component,
        "supportedBaselines": {name: value["label"] for name, value in BASELINE.items()},
        "runtimeCompatible": False, "runtimeVerified": False, "diskEvidenceOnly": True,
        "note": "The installed 7.1 build is not adapted for the legacy fixed-offset game writers, so 'game', "
                "'game' and 'all' still refuse it for legacy file writes; editor uses its 7.1 mapping profile. The separate 'native-scene' component verifies a pinned "
                "read-only 7.1 disk profile instead; a disk match there is neither runtime acceptance nor "
                "write permission.",
        "components": {}, "reasons": [],
    }
    if component in ("game", "all"):
        entry = check_game(game_image, config_ini)
        result["components"]["game"] = entry
        result["reasons"] += ["game." + reason for reason in entry["reasons"]]
    if component in ("editor", "all"):
        entry = check_editor(editor_dll)
        result["components"]["editor"] = entry
        result["reasons"] += ["editor." + reason for reason in entry["reasons"]]
    if component == NATIVE_SCENE:
        entry = check_native_scene(native_profile, native_image)
        result["components"][NATIVE_SCENE] = entry
        result["reasons"] += [NATIVE_SCENE + "." + reason for reason in entry["reasons"]]
    result["ok"] = not result["reasons"]
    result["code"] = "compatible" if result["ok"] else CODE
    return result


def require_compatible(component: str = "all") -> dict:
    """Raise :class:`IncompatibleVersion` unless the requested baselines match.

    ``'native-scene'`` passes only on verified disk evidence for the pinned
    read-only profile -- it grants no write permission; the native scene path
    still requires its own runtime review, same-session, snapshot and level
    checks.  Uses the fixed installation paths above. There is deliberately no
    environment, CLI or audit-file allowlist: the refusal can only be changed by
    editing the versioned constants in this file (or the pinned profile module).
    """
    report = check_compatibility(component)
    if not report["ok"]:
        raise IncompatibleVersion(report)
    return report


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--component", choices=LEGACY_COMPONENTS + (NATIVE_SCENE,), default="all")
    args = ap.parse_args(argv)
    try:
        report = check_compatibility(args.component)
    except Exception as error:  # never traceback at the CLI boundary
        report = {"ok": False, "code": CODE, "component": args.component,
                  "reasons": ["guard failure: %s" % type(error).__name__],
                  "runtimeCompatible": "unknown", "runtimeVerified": False}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
