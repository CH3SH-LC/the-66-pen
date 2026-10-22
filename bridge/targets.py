"""Frozen install target allowlist.

These frozen paths are the *only* executables this bridge will ever start. The original two
exist on disk as of 2026-09-14 (see ``docs/research/miliastra-survey.md``
"本机安装记录" and ``PROGRESS.md``). The game path was relocated by the user on
that date -- see ``GAME_DIR`` and ``bridge/README.md`` for what is and is not
verified about the new location.

There is deliberately no configuration knob, no environment override and no
"custom path" parameter. A caller cannot name an executable; it can only name a
target *key* from this table. That is the whole point: the interface accepts a
closed vocabulary, not a path.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

#: Launcher install root. Still the original launcher path; unchanged by the
#: user's 2026-09-14 game migration.
INSTALL_ROOT = r"D:\Program Files\miHoYo Launcher"

#: Game install directory, relocated by the user on 2026-09-14. The previous
#: value was ``<INSTALL_ROOT>\games\Genshin Impact Game``, where the survey and
#: all 740 evidence were recorded. The new path was verified by the main agent
#: to contain ``YuanShen.exe``, ``BeyondAssets`` and a ``config.ini`` declaring
#: 7.0.0 -- but that verification is **file presence only**: no live launch has
#: been attempted from this path, so its elevation/permission behaviour is still
#: unverified.
GAME_DIR = r"C:\Games\Genshin Impact Game"
EDITOR_DIR = os.path.join(GAME_DIR, 'BeyondAssets', 'BeyondAssistEditor')

#: Official Start Menu shortcut, read read-only on 2026-09-14:
#:   TargetPath  D:\Program Files\miHoYo Launcher\launcher.exe
#:   Arguments   --game=hk4e_cn
#: It points at the *same* frozen launcher.exe already in the allowlist -- it is
#: a second way to ask for the same program, not a third program.
SHORTCUT_PATH = os.path.join(
    os.path.expandvars(r"%APPDATA%"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "米哈游启动器",
    "原神.lnk",
)

#: The only argv this bridge will ever pass. Fixed here, never from a request.
SHORTCUT_ARGV = ("--game=hk4e_cn",)

FROZEN_TARGETS: dict[str, dict[str, Any]] = {
    "editor-context": {
        "displayName": "BeyondEditor with fixed Genshin application context",
        "executablePath": os.path.join(EDITOR_DIR, "BeyondEditor.exe"),
        "argv": ["-sourceapp", "genshin"],
        "launchedVia": "direct",
        "dedupeOnRunning": True,
        "note": (
            "Starts only BeyondEditor with fixed application context; no source PID or "
            "auto-connect argument. Existing same-executable processes are reused without "
            "claiming their context matches. No game launch or editing-readiness claim."
        ),
    },
    "editor": {
        "displayName": "BeyondEditor standalone",
        "executablePath": os.path.join(EDITOR_DIR, "BeyondEditor.exe"),
        "argv": [],
        "launchedVia": "direct",
        "dedupeOnRunning": True,
        "note": "Starts the editor executable only, without game launch or session-readiness claims.",
    },
    "launcher": {
        "displayName": "miHoYo Launcher",
        "executablePath": os.path.join(INSTALL_ROOT, "launcher.exe"),
        "argv": [],
        "launchedVia": "direct",
        # A running launcher satisfies a plain `launcher` request.
        "dedupeOnRunning": True,
    },
    "game": {
        "displayName": "Genshin Impact (YuanShen.exe)",
        "executablePath": os.path.join(GAME_DIR, "YuanShen.exe"),
        "argv": [],
        "launchedVia": "direct",
        "dedupeOnRunning": True,
    },
    "game-shortcut": {
        "displayName": "Genshin Impact via official shortcut (launcher.exe --game=hk4e_cn)",
        "executablePath": os.path.join(INSTALL_ROOT, "launcher.exe"),
        "argv": list(SHORTCUT_ARGV),
        "launchedVia": "official-start-menu-shortcut",
        # A launcher that is already running does NOT mean this shortcut's
        # game-selection request was ever delivered, so the request is always
        # sent for a new idempotency key. Deduplication still applies to a
        # *replay of the same key* (handled by the journal), not to a running
        # process.
        "dedupeOnRunning": False,
        "shortcutPath": SHORTCUT_PATH,
        "shortcutArguments": " ".join(SHORTCUT_ARGV),
        "note": (
            "Reproduces the official shortcut's launch request. It asks the launcher "
            "for the hk4e_cn game; this bridge does not and cannot observe whether the "
            "game then starts."
        ),
    },
}

DEFAULT_TARGET = "launcher"
TARGET_KEYS = frozenset(FROZEN_TARGETS)

#: Lower-cased executable paths accepted from OS observation results.
ALLOWLISTED_EXECUTABLES = frozenset(
    os.path.normcase(t["executablePath"]) for t in FROZEN_TARGETS.values()
)


#: ``launcher.exe`` is a bootstrap: it hands off and exits. The process that
#: actually stays resident is ``HYP.exe`` under a version-numbered subdirectory
#: of the install root. Verified read-only on 2026-09-14 at
#: ``D:\Program Files\miHoYo Launcher\1.18.0.380\HYP.exe``.
#:
#: This alias is **observation only** -- ``mw.runtime.start`` still starts
#: exactly the frozen executables and nothing else. Without it, a launcher
#: that is genuinely running would be reported as not running, and a second
#: start request would launch a duplicate.
#:
#: The evidence is weaker than a path match: the running ``HYP.exe`` reports
#: ``ExecutablePath: None`` through CIM (the launcher protects its own path), so
#: the match is by process name and by the fact that the path is unreadable. A
#: name match whose path *is* readable is only accepted when it falls under the
#: install root.
VERSION_DIR_PATTERN = re.compile(r"^\d+(\.\d+)*$")

_HYP_ALIAS: dict[str, str] = {
    "kind": "process-name",
    "value": "HYP.exe",
    "scope": INSTALL_ROOT,
    "strength": "weak",
    "rationale": (
        "launcher.exe hands off to HYP.exe and exits; HYP.exe is the resident "
        "process. Matched by name because its ExecutablePath is unreadable "
        "through CIM."
    ),
}

OBSERVATION_ALIASES: dict[str, list[dict[str, str]]] = {
    "editor": [],
    "launcher": [dict(_HYP_ALIAS)],
    # Same executable as `launcher`, so the same handoff applies.
    "game-shortcut": [dict(_HYP_ALIAS)],
    "game": [],
}


def find_launcher_version_dirs() -> dict[str, Any]:
    """Read-only enumeration of fixed-format version directories under the install root.

    This exists so the alias does not have to hard-code ``1.18.0.380`` and then
    silently misreport every target as "not running" after the launcher updates.
    Only direct children of the frozen root whose name looks like a version are
    considered, and only the presence of the alias binary is checked.
    """
    root = Path(INSTALL_ROOT)
    found: list[dict[str, Any]] = []
    error: str | None = None
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        children = []
        error = f"{type(exc).__name__}: {exc}"
    for child in children:
        if not child.is_dir() or not VERSION_DIR_PATTERN.match(child.name):
            continue
        alias_path = child / "HYP.exe"
        found.append(
            {
                "versionDir": child.name,
                "hypExe": str(alias_path),
                "hypExePresent": alias_path.is_file(),
            }
        )
    return {"installRoot": INSTALL_ROOT, "versionDirs": found, "error": error}


def is_allowlisted_executable(path: str | None) -> bool:
    """True only for an exact (case-insensitive) match against the frozen table."""
    if not path:
        return False
    return os.path.normcase(path) in ALLOWLISTED_EXECUTABLES


def resolve_target(key: str) -> dict[str, Any]:
    """Map a target key to its frozen record. Raises ``KeyError`` if unknown."""
    return FROZEN_TARGETS[key]


def target_exists(key: str) -> bool:
    return os.path.isfile(FROZEN_TARGETS[key]["executablePath"])


#: Keys surfaced from the game's ``config.ini``. Everything else in that file is
#: left unread into the response -- it can carry channel/account-adjacent values
#: that the bridge has no business echoing (contract: privacy section).
_CONFIG_INI_WHITELIST = ("game_version", "wpf_version")


def read_install_fingerprint() -> dict[str, Any]:
    """Read-only fingerprint of the verified installation.

    Returns declared version strings from the game's own ``config.ini``. These
    are *installation declarations*, not proof that the running client matches
    -- the survey document already records that caveat and it is repeated in
    the capability report.
    """
    ini_path = Path(GAME_DIR) / "config.ini"
    declared: dict[str, str] = {}
    read_error: str | None = None
    try:
        text = ini_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        read_error = f"{type(exc).__name__}: {exc}"
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line[0] in ";#[":
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in _CONFIG_INI_WHITELIST:
                declared[key] = value.strip()

    return {
        "installRoot": INSTALL_ROOT,
        "configIni": str(ini_path),
        "configIniRead": read_error is None,
        "configIniError": read_error,
        "declaredVersions": declared,
        "declaredVersionsNote": (
            "Values come from the installation's own config.ini. They are "
            "declarations on disk, not an observation of a running client."
        ),
    }
