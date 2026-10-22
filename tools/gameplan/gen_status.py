"""gen_status — one authoritative status block, DERIVED from the tree at run time.

Why this file exists
--------------------
The project kept *hand-writing* status tables that assert facts by hand —
"the bridge has 138 ops", "the READ half is compiled, the DELETE half is not",
"field 7 has exactly one reader".  Every time the build moved, a fresh batch of
documents silently became false (the op count alone went 136 -> 137 -> 138 in one
night, and the same number had been copied into roughly two dozen files).  Patching
the number is not a fix; it guarantees the next round.  The fix is to make the
number **derived**, so a document can embed a block that regenerates itself.

This module emits exactly that block.  Every fact in it is read off the tree at
run time, never copied from a document:

  * the bridge op count — the ``switch (op)`` case labels in ``BridgeServer.cs``;
  * the two component-op names present in the current build, and for each whether
    it is in the switch / the ``ValidateSet`` / the current DLL's metadata heaps;
  * the csproj ``<Compile>`` count (and the payload assembly name);
  * the ``.gil`` field-7 reader module set (the non-test modules that use the
    terrain field-7 constant as code — the constant's name is itself discovered
    from the tree, not written down here);
  * the count of test files per suite, discovered the same way
    ``scripts/run-tests.ps1`` discovers them (a directory that directly holds test
    files is a suite), so the two agree by construction.

**A fact that cannot be derived is ``UNKNOWN``, never a silent default.**  A
generator earns its keep only if a number it prints was actually read off the
tree; printing ``0`` (or an empty list) when the source file is missing, has
zero parseable entries, or is malformed is the *same* bug class this module was
built to kill, just moved one level up.  So a missing ``BridgeServer.cs``, a
``case`` label the strict pattern cannot parse, a csproj with no
``<AssemblyName>``, no discoverable suites, and an unbuilt payload DLL all emit
an explicit ``UNKNOWN`` (with a ``notes`` line naming the cause), not a value.

Two renderings come out of the same collected dict: **markdown** (to embed) and
**JSON** (to diff).  Both are deterministic — no timestamps unless ``--timestamp``
is passed.

Read-only, and offline: this module opens files for reading only.  It never
touches the bridge, the game, the editor, or the elevated helper, and it sends no
request.

Usage::

    python -m tools.gameplan.gen_status                  # the markdown block
    python -m tools.gameplan.gen_status --format json    # the JSON
    python -m tools.gameplan.gen_status --format both    # both, labelled
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

BRIDGE_SERVER_REL = "tools/editor-bridge/ManagedBridge/BridgeServer.cs"
CS_PROJ_REL = "tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj"
CALL_BRIDGE_REL = "tools/editor-bridge/call-bridge.ps1"
DLL_DIR_REL = "tools/editor-bridge/ManagedBridge/bin/Release/net8.0-windows"

#: What a fact renders as when it could not be *derived* from the tree.  A
#: generator that prints a number it did not read is the bug this module exists
#: to kill, so an underivable fact is ``UNKNOWN`` — never a silent 0 / None / [].
UNKNOWN = "UNKNOWN"

# ``switch (op) { case "…": … }`` labels — the bridge's whole op surface.
_CASE_RE = re.compile(r'case\s+"([A-Za-z0-9][A-Za-z0-9\-]*)"\s*:')
# Any quoted ``case "…":`` label, however shaped.  Used only to DETECT a label
# the strict pattern above cannot parse: a malformed label must make the op
# count UNKNOWN, not silently shrink it by one.
_LOOSE_CASE_RE = re.compile(r'case\s+"([^"]*)"\s*:')
_LABEL_OK_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*\Z")
_CS_PROJ_COMPILE_RE = re.compile(r'<Compile\s+Include="([^"]+)"')
_ASSEMBLY_NAME_RE = re.compile(r"<AssemblyName>\s*([^<\s]+)\s*</AssemblyName>")
# The PowerShell op surface: the ``[ValidateSet('a','b',…)]`` that decorates the
# ``$Operation`` parameter of ``call-bridge.ps1``.  Anchored to ``$Operation`` on
# purpose — the file holds a *second* ValidateSet (``'inspect','set'`` for
# ``$TagAction``), so "the first ValidateSet in the file" would silently read the
# wrong one if the op param were renamed, yielding a confidently-wrong op
# surface.  No match -> the fact is UNKNOWN, never a wrong list.
_VALIDATESET_RE = re.compile(
    r"\[ValidateSet\(([^)]*)\)\]\s*\[string\]\s*\$Operation\b")
_VALIDATESET_ITEM_RE = re.compile(r"'([A-Za-z0-9][A-Za-z0-9\-]*)'")

# The field-7 terrain-list constant is *discovered*, not spelled out here.  The
# repo's own field-7 guard flags any non-test module whose source *contains* the
# constant name, so a tool that merely talks *about* the constant must not embed
# the literal — it would be misread as a second field-7 reader.  Instead we look
# for a module-scope assignment of a ``FIELD_*TERRAIN*`` name to ``7``; that name
# is then the witness used to find the readers.  If the name ever moves, this
# follows it without an edit.
_FIELD7_DEFINE_RE = re.compile(r"^(FIELD_[A-Z0-9_]*TERRAIN[A-Z0-9_]*)\s*=\s*7\b", re.M)

# Suite discovery mirrors scripts/run-tests.ps1's name patterns, so "test files
# per suite" here and "suites" there can never disagree.
_PY_TEST_RE = re.compile(r"^(test[-_].*|.*_test)\.py$")
_PS_TEST_RE = re.compile(r"^(test[-_].*|.*[-_]test)\.ps1$")

# Directories suite discovery never descends into.  This is exactly the set
# ``scripts/run-tests.ps1`` prunes, so a suite listed here is a suite it runs.
_SUITE_PRUNE = {".git", ".runtime", "vendor", "node_modules", "__pycache__",
                ".pytest_cache", ".venv", "venv", "dist", "build", ".idea", ".vscode"}
# Directories a first-party ``*.py`` module never lives in (adds build output).
_PY_PRUNE = _SUITE_PRUNE | {"bin", "obj"}


# --------------------------------------------------------------------------- #
# Small readers.
# --------------------------------------------------------------------------- #

def _read(path: Path) -> str | None:
    """File text, or ``None`` when it is absent / undecodable.

    ``None`` is the *could-not-derive* signal (-> UNKNOWN); it is deliberately
    distinct from ``""`` (a file that exists and is genuinely empty), so the
    callers can tell "missing" from "empty".
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _in_metadata(blob: bytes, s: str) -> bool:
    """True if ``s`` sits in a .NET metadata heap (ASCII ``#Strings`` or UTF-16 ``#US``)."""
    return s.encode("ascii") in blob or s.encode("utf-16-le") in blob


# --------------------------------------------------------------------------- #
# Derivations.
# --------------------------------------------------------------------------- #

def _switch_labels(bridge_server: Path) -> list[str] | None:
    """Strictly-parsed ``case "…":`` labels, or ``None`` if the file is unreadable."""
    text = _read(bridge_server)
    return None if text is None else _CASE_RE.findall(text)


def _malformed_case_labels(bridge_server: Path) -> list[str]:
    """Quoted ``case "…":`` labels that the strict pattern cannot parse.

    A label like ``"Op.WithDot"`` or ``"delete_entity"`` (a dot / underscore)
    does not match ``_CASE_RE`` and would otherwise vanish silently, shrinking
    the op count.  Detecting it lets ``collect`` raise UNKNOWN instead.
    """
    text = _read(bridge_server)
    if text is None:
        return []
    return [lab for lab in _LOOSE_CASE_RE.findall(text)
            if not _LABEL_OK_RE.match(lab)]


def _component_ops(labels: list[str]) -> list[str]:
    """The ops whose name carries a ``component`` hyphen-segment.

    Derived, not hardcoded: if the build grows a third component op it shows up
    here without a code change, and if one is un-wired it drops out.
    """
    return sorted(lab for lab in labels
                  if any(seg.startswith("component") for seg in lab.split("-")))


def _csproj_compiles(csproj: Path) -> list[str] | None:
    """``<Compile Include="…">`` targets, or ``None`` if the csproj is unreadable."""
    text = _read(csproj)
    return None if text is None else _CS_PROJ_COMPILE_RE.findall(text)


def _assembly_name(csproj: Path) -> str | None:
    text = _read(csproj)
    if text is None:
        return None
    m = _ASSEMBLY_NAME_RE.search(text)
    return m.group(1) if m else None


def _validateset_ops(call_bridge: Path) -> list[str] | None:
    """The op ``[ValidateSet(…)]`` items, or ``None`` when they cannot be derived.

    ``None`` (unreadable file, or no ``ValidateSet`` at all) is UNKNOWN — NOT an
    empty list.  An empty list would be indistinguishable from "no validated
    ops" and would make *every* switch label look switch-only, a loud wrong
    answer rather than a quiet one.
    """
    text = _read(call_bridge)
    if text is None:
        return None
    m = _VALIDATESET_RE.search(text)
    if m is None:
        return None
    items = _VALIDATESET_ITEM_RE.findall(m.group(1))
    return items or None


def _payload_dll(csproj: Path, repo_root: Path) -> Path | None:
    name = _assembly_name(csproj)
    if name is None:
        return None
    return repo_root / DLL_DIR_REL / (name + ".dll")


def _field7_constants(repo_root: Path) -> list[str]:
    """Module-scope ``FIELD_*TERRAIN* = 7`` names defined by non-test modules."""
    names: set[str] = set()
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(d for d in dirs if d not in _PY_PRUNE)
        for name in sorted(files):
            if not name.endswith(".py") or _PY_TEST_RE.match(name):
                continue
            path = Path(root) / name
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            names.update(_FIELD7_DEFINE_RE.findall(text))
    return sorted(names)


def _field7_reader_modules(repo_root: Path) -> list[str]:
    """Non-test repo ``*.py`` modules that use a field-7 constant *as code*.

    "As code" = the name appears where a quote/backtick does not immediately
    precede it, so a module that only mentions the constant in a string (as this
    file's discovery regex does) is not miscounted as a reader.
    """
    constants = _field7_constants(repo_root)
    if not constants:
        return []
    use_re = re.compile(r"(?<![\"'`])(?:" +
                        "|".join(re.escape(c) for c in constants) + ")")
    holders: list[str] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(d for d in dirs if d not in _PY_PRUNE)
        for name in sorted(files):
            if not name.endswith(".py") or _PY_TEST_RE.match(name):
                continue
            path = Path(root) / name
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if use_re.search(text):
                holders.append(_repo_rel(path, repo_root))
    return sorted(set(holders))


def _test_suites(repo_root: Path) -> list[dict]:
    """Every suite = a directory that directly holds test files (run-tests.ps1's rule)."""
    suites: list[dict] = []
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = sorted(d for d in dirs if d not in _SUITE_PRUNE)
        py = sorted(n for n in files if _PY_TEST_RE.match(n))
        ps = sorted(n for n in files if _PS_TEST_RE.match(n))
        if not py and not ps:
            continue
        path = Path(root)
        rel = _repo_rel(path, repo_root) or "."
        if py:
            suites.append({"path": rel, "kind": "python", "count": len(py)})
        if ps:
            suites.append({"path": rel, "kind": "powershell", "count": len(ps)})
    return sorted(suites, key=lambda s: (s["path"], s["kind"]))


# --------------------------------------------------------------------------- #
# The collected fact set.
# --------------------------------------------------------------------------- #

def collect(repo_root: Path = REPO, *, bridge_server: Path | None = None,
            csproj: Path | None = None, call_bridge: Path | None = None,
            dll: Path | None = None) -> dict:
    """Derive every fact from the tree.  Path overrides exist only for tests.

    When an override is ``None`` the file is resolved under ``repo_root``.  The
    ``dll`` default is resolved from the csproj's ``<AssemblyName>`` (so a
    revision bump follows the new artifact instead of reading a stale one).
    """
    repo_root = Path(repo_root)
    bridge_server = bridge_server or repo_root / BRIDGE_SERVER_REL
    csproj = csproj or repo_root / CS_PROJ_REL
    call_bridge = call_bridge or repo_root / CALL_BRIDGE_REL

    notes: list[str] = []

    # --- bridge op surface ------------------------------------------------ #
    labels_opt = _switch_labels(bridge_server)
    malformed = _malformed_case_labels(bridge_server)
    # Non-empty is the "we actually read a switch" signal; 0 labels means the
    # parse failed (a dispatch switch is never empty), and a malformed label
    # means the strict parse silently dropped a case — both are UNKNOWN.
    bridge_known = bool(labels_opt) and not malformed
    labels = labels_opt or []
    if labels_opt is None:
        notes.append(f"bridge op count UNKNOWN: `{BRIDGE_SERVER_REL}` is missing/unreadable")
    elif not labels_opt:
        notes.append(f"bridge op count UNKNOWN: `{BRIDGE_SERVER_REL}` parsed 0 `case` labels")
    elif malformed:
        notes.append("bridge op count UNKNOWN: `" + BRIDGE_SERVER_REL +
                     "` has `case` label(s) the strict pattern cannot parse: "
                     + _code_list(malformed))
    comp_ops = _component_ops(labels) if bridge_known else []

    # --- csproj ----------------------------------------------------------- #
    compiles_opt = _csproj_compiles(csproj)
    compiles_known = bool(compiles_opt)
    compiles = compiles_opt or []
    if compiles_opt is None:
        notes.append(f"csproj `<Compile>` count UNKNOWN: `{CS_PROJ_REL}` is missing/unreadable")
    elif not compiles_opt:
        notes.append(f"csproj `<Compile>` count UNKNOWN: `{CS_PROJ_REL}` parsed 0 items")

    assembly = _assembly_name(csproj)
    if not assembly:
        notes.append(f"payload assembly name UNKNOWN: no `<AssemblyName>` in `{CS_PROJ_REL}`")

    # --- call-bridge ValidateSet ------------------------------------------ #
    vs_ops_opt = _validateset_ops(call_bridge)
    validateset_known = vs_ops_opt is not None
    vs_ops = set(vs_ops_opt or [])
    if not validateset_known:
        notes.append(f"op ValidateSet UNKNOWN: no `[ValidateSet(…)]` read from `{CALL_BRIDGE_REL}`")

    # --- payload DLL ------------------------------------------------------ #
    dll = dll if dll is not None else _payload_dll(csproj, repo_root)
    dll_present = bool(dll and dll.exists())
    # Lazily read the DLL only when a component op must be checked against it.
    blob = dll.read_bytes() if dll_present else None
    if dll is None:
        notes.append("payload DLL UNKNOWN: no assembly name to resolve it from")
    elif not dll_present:
        notes.append(f"payload DLL not built at `{DLL_DIR_REL}` -> per-op DLL membership UNKNOWN")

    component_ops: list[dict] = []
    for op in comp_ops:
        in_dll: bool | None
        if blob is None:
            in_dll = None
        else:
            in_dll = _in_metadata(blob, op)
        component_ops.append({
            "op": op,
            "in_switch": op in labels,
            # Only a *derived* ValidateSet can decide membership; otherwise unknown.
            "in_validateset": (op in vs_ops) if validateset_known else None,
            "in_dll": in_dll,
        })

    # An op-set diff needs both sides; an UNKNOWN side makes the diff UNKNOWN.
    if bridge_known and validateset_known:
        switch_only: object = sorted(set(labels) - vs_ops)
        validateset_only: object = sorted(vs_ops - set(labels))
    else:
        switch_only = UNKNOWN
        validateset_only = UNKNOWN

    # --- field-7 readers -------------------------------------------------- #
    f7_constants = _field7_constants(repo_root)
    if f7_constants:
        f7_readers: object = _field7_reader_modules(repo_root)
    else:
        f7_readers = UNKNOWN
        notes.append("`.gil` field-7 reader set UNKNOWN: no `FIELD_*TERRAIN* = 7` constant found")

    # --- test suites ------------------------------------------------------ #
    suites = _test_suites(repo_root)
    if not suites:
        notes.append("test-suite discovery UNKNOWN: the walk found no suites")
        suites_fact: object = UNKNOWN
    else:
        suites_fact = suites

    return {
        "bridge": {
            "op_count": len(labels) if bridge_known else UNKNOWN,
            "switch_labels_unique": (len(labels) == len(set(labels))) if bridge_known else None,
            "component_ops": component_ops if bridge_known else UNKNOWN,
            "switch_only_ops": switch_only,
            "validateset_only_ops": validateset_only,
        },
        "csproj": {
            "assembly_name": assembly if assembly else UNKNOWN,
            "compile_count": len(compiles) if compiles_known else UNKNOWN,
        },
        "dll": {
            "name": (dll.name if dll is not None else UNKNOWN),
            # present is a real tri-state: True / False / None(=UNKNOWN, name unresolved).
            "present": dll_present if dll is not None else None,
        },
        "field7": {
            "constants": f7_constants,
            "reader_modules": f7_readers,
        },
        "tests": {
            "suites": suites_fact,
        },
        "notes": notes,
    }


# --------------------------------------------------------------------------- #
# Renderings.
# --------------------------------------------------------------------------- #

def _yesno(v: bool | None) -> str:
    return "yes" if v is True else "no" if v is False else "unknown"


def _code_list(items) -> str:
    """Render a list of code spans, or the UNKNOWN sentinel, or ``none``."""
    if isinstance(items, str) and items == UNKNOWN:
        return UNKNOWN
    return ", ".join(f"`{i}`" for i in items) if items else "none"


def _tri_state(v: bool | None, yes: str, no: str) -> str:
    """Render a real tri-state: True -> *yes*, False -> *no*, None -> UNKNOWN."""
    return yes if v is True else no if v is False else UNKNOWN


def render_markdown(facts: dict, *, timestamp: bool = False) -> str:
    b, c, d, f, t = (facts["bridge"], facts["csproj"], facts["dll"],
                     facts["field7"], facts["tests"])
    lines: list[str] = []
    lines.append("<!-- BEGIN GENERATED STATUS BLOCK — tools/gameplan/gen_status.py -->")
    lines.append("### Bridge / build status (derived at run time)")
    lines.append("")
    lines.append("| Fact | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Bridge op count (`BridgeServer.cs` switch labels) | {b['op_count']} |")
    lines.append(f"| Switch labels unique | {_yesno(b['switch_labels_unique'])} |")
    comp = b["component_ops"]
    comp_names = [o["op"] for o in comp] if comp != UNKNOWN else UNKNOWN
    lines.append(f"| Component ops in this build | {_code_list(comp_names)} |")
    lines.append(f"| csproj `<Compile>` count | {c['compile_count']} |")
    lines.append(f"| csproj payload assembly | `{c['assembly_name']}` |")
    lines.append(f"| Current DLL | `{d['name']}` "
                 f"({_tri_state(d['present'], 'present', 'absent')}) |")
    lines.append(f"| `.gil` field-7 reader modules | {_code_list(f['reader_modules'])} |")
    suites = t["suites"]
    if suites == UNKNOWN:
        lines.append(f"| Test suites (python) | {UNKNOWN} |")
        lines.append(f"| Test files (python) | {UNKNOWN} |")
        lines.append(f"| Test suites (powershell) | {UNKNOWN} |")
        lines.append(f"| Test files (powershell) | {UNKNOWN} |")
    else:
        py_suites = [s for s in suites if s["kind"] == "python"]
        ps_suites = [s for s in suites if s["kind"] == "powershell"]
        lines.append(f"| Test suites (python) | {len(py_suites)} |")
        lines.append(f"| Test files (python) | {sum(s['count'] for s in py_suites)} |")
        lines.append(f"| Test suites (powershell) | {len(ps_suites)} |")
        lines.append(f"| Test files (powershell) | {sum(s['count'] for s in ps_suites)} |")
    lines.append("")
    lines.append("| Component op | in switch | in ValidateSet | in current DLL |")
    lines.append("| --- | --- | --- | --- |")
    if comp == UNKNOWN:
        lines.append(f"| {UNKNOWN} | unknown | unknown | unknown |")
    else:
        for o in comp:
            lines.append(f"| `{o['op']}` | {_yesno(o['in_switch'])} | "
                         f"{_yesno(o['in_validateset'])} | {_yesno(o['in_dll'])} |")
    if b["switch_only_ops"] or b["validateset_only_ops"]:
        lines.append("")
        lines.append(f"_Switch-only ops (not in ValidateSet): {_code_list(b['switch_only_ops'])}_  ")
        lines.append(f"_ValidateSet-only ops (not in switch): {_code_list(b['validateset_only_ops'])}_")
    lines.append("")
    lines.append("Test files per suite:")
    lines.append("")
    lines.append("| Suite | Kind | Files |")
    lines.append("| --- | --- | --- |")
    if suites == UNKNOWN:
        lines.append(f"| {UNKNOWN} | {UNKNOWN} | {UNKNOWN} |")
    else:
        for s in suites:
            lines.append(f"| `{s['path']}` | {s['kind']} | {s['count']} |")
    notes = facts.get("notes") or []
    if notes:
        lines.append("")
        lines.append("Notes (facts that could not be derived):")
        lines.append("")
        for n in notes:
            lines.append(f"- {n}")
    if timestamp:
        import datetime
        lines.append("")
        lines.append(f"_generated at {datetime.datetime.now().isoformat(timespec='seconds')}_")
    lines.append("<!-- END GENERATED STATUS BLOCK -->")
    return "\n".join(lines) + "\n"


def render_json(facts: dict, *, timestamp: bool = False) -> str:
    payload = dict(facts)
    if timestamp:
        import datetime
        payload = {**payload,
                   "generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit a derived status block.")
    parser.add_argument("--format", choices=("markdown", "json", "both"),
                        default="markdown", help="which rendering to print (default: markdown)")
    parser.add_argument("--timestamp", action="store_true",
                        help="include a generated-at timestamp (default: none)")
    parser.add_argument("--repo-root", default=None,
                        help="override the repo root (defaults to this file's repo)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO
    facts = collect(repo_root)

    out = sys.stdout
    if args.format == "markdown":
        out.write(render_markdown(facts, timestamp=args.timestamp))
    elif args.format == "json":
        out.write(render_json(facts, timestamp=args.timestamp))
    else:
        out.write(render_markdown(facts, timestamp=args.timestamp))
        out.write("\n")
        out.write(render_json(facts, timestamp=args.timestamp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
