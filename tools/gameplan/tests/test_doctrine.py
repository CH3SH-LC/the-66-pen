"""Offline tests that hold the CLAUDE.md doctrine to the repository.

Task #9 — 「文档 — 让 CLAUDE.md 的每条主张都能被验证」.

CLAUDE.md carries the doctrine and the mined-interface table.  A doctrine that
cannot be checked rots, so each load-bearing claim below is asserted against the
file that would falsify it.  A claim that is no longer true makes its test FAIL —
that is the point of this file.  Do **not** relax a failing assertion to make the
suite green; either the doc or the code is wrong and the main agent decides
(CLAUDE.md is protected against this test's author).

Files read (each test names its own):

  * ``CLAUDE.md``                                           the doctrine itself
  * ``tools/editor-bridge/ManagedBridge/BridgeServer.cs``   the bridge op switch
  * ``tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj``  the <Compile> set
  * ``tools/editor-bridge/ManagedBridge/bin/…/Miliastra.EditorBridge.Net8R<rev>.dll``
        the built artifact — the revision is resolved from the csproj ``<AssemblyName>``,
        never hardcoded (read only when present; ``…/bin/`` is git-ignored)
  * ``docs/research/beyondeditor-backend/db/backend.db``    ``command_route`` (38 rows)
  * ``docs/research/beyondeditor-backend/db/routes.json``   the same table's source JSON
  * ``tools/beyond-save/gil_container.py``                  the container codec
  * ``tools/beyond-save/terrain.py``                        the field-7 reader
  * ``tools/editor-bridge/elevated-runner.ps1``             helper native-scene actions

Pure reads only: no bridge, no native call, no game/editor contact, and nothing
written anywhere.  The single db access opens ``backend.db`` read-only
(``mode=ro``).

Run::

    python -B -m unittest tools.gameplan.tests.test_doctrine
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

CLAUDE_MD = REPO / "CLAUDE.md"
BRIDGE_SERVER = REPO / "tools" / "editor-bridge" / "ManagedBridge" / "BridgeServer.cs"
CS_PROJ = (REPO / "tools" / "editor-bridge" / "ManagedBridge"
           / "Miliastra.EditorBridge.csproj")
# Build output.  ``tools/editor-bridge/**/bin/`` is git-ignored, so the payload DLL exists
# only in a checkout that has actually built; the test that reads it skips (loudly) when it
# is absent.  Its path is resolved from the csproj ``<AssemblyName>`` by
# ``_current_payload_dll`` below -- never hardcoded to a revision.  The old hardcoded
# ``…Net8R<rev>.dll`` path pinned a DLL the next bump removed, so the check silently stopped
# testing anything.
BACKEND_DB = REPO / "docs" / "research" / "beyondeditor-backend" / "db" / "backend.db"
ROUTES_JSON = REPO / "docs" / "research" / "beyondeditor-backend" / "db" / "routes.json"
GIL_CONTAINER = REPO / "tools" / "beyond-save" / "gil_container.py"
TERRAIN = REPO / "tools" / "beyond-save" / "terrain.py"
ELEVATED_RUNNER = REPO / "tools" / "editor-bridge" / "elevated-runner.ps1"

# ``switch (op) { case "…": … }`` labels — the bridge's whole op surface.
_CASE_RE = re.compile(r'case\s+"([A-Za-z0-9][A-Za-z0-9\-]*)":')
# A command name that would be transform-shaped if it existed.
_TRANSFORMISH_RE = re.compile(
    r"transform|translat|position|rotation|\bscale\b|\bmove\b|\bplace\b|"
    r"location|offset|matrix|euler",
    re.IGNORECASE,
)
# Directories that never hold a first-party schema reader.
_PY_PRUNE = {".git", ".runtime", "__pycache__", ".pytest_cache", "node_modules",
             "vendor", "bin", "obj", ".mypy_cache"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _claude_lines() -> list[str]:
    return _read(CLAUDE_MD).splitlines()


def _line_matching(*needles: str) -> tuple[int, str] | None:
    """First (1-based line number, text) of a CLAUDE.md line containing all needles."""
    for i, line in enumerate(_claude_lines(), start=1):
        if all(n in line for n in needles):
            return i, line
    return None


def _line_re(pattern: str) -> tuple[int, str, "re.Match[str]"] | None:
    """First (1-based line number, text, match) of a CLAUDE.md line matching pattern."""
    rx = re.compile(pattern)
    for i, line in enumerate(_claude_lines(), start=1):
        m = rx.search(line)
        if m:
            return i, line, m
    return None


def _bridge_case_labels() -> list[str]:
    return _CASE_RE.findall(_read(BRIDGE_SERVER))


def _csproj_compiles() -> list[str]:
    """Every ``<Compile Include="…">`` in the csproj — the bridge's whole build input."""
    return re.findall(r'<Compile\s+Include="([^"]+)"', _read(CS_PROJ))


def _ends_with(paths: list[str], name: str) -> bool:
    return any(p.replace("\\", "/").endswith(name) for p in paths)


def _delete_component_cases(labels: list[str]) -> list[str]:
    """Switch labels that would dispatch a component DELETE (``delete`` + ``component``)."""
    return [lab for lab in labels
            if "delete" in lab.split("-")
            and any(seg.startswith("component") for seg in lab.split("-"))]


def _in_metadata(blob: bytes, s: str) -> bool:
    """True if ``s`` sits in a .NET metadata heap (ASCII ``#Strings`` or UTF-16 ``#US``)."""
    return s.encode("ascii") in blob or s.encode("utf-16-le") in blob


def _current_payload_dll() -> Path | None:
    """The payload DLL the CURRENT build names, resolved from the csproj AssemblyName.

    Reading the revision out of the csproj (rather than hardcoding a revision) keeps the
    positive artifact assertion pointed at whatever revision is actually built, so a
    bump does not silently leave the check reading a stale, pre-change DLL.
    """
    match = re.search(r"<AssemblyName>\s*(Miliastra\.EditorBridge\.Net8R\d+)\s*</AssemblyName>",
                      _read(CS_PROJ))
    if match is None:
        return None
    return (REPO / "tools" / "editor-bridge" / "ManagedBridge" / "bin" / "Release"
            / "net8.0-windows" / (match.group(1) + ".dll"))


def _iter_py() -> list[Path]:
    """Every ``*.py`` under the repo, minus the pruned/generated directories."""
    found: list[Path] = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _PY_PRUNE]
        for name in files:
            if name.endswith(".py"):
                found.append(Path(root) / name)
    return found


def _field7_modules() -> set[str]:
    """Repo modules that name (and therefore read/write) top-level field 7."""
    holders: set[str] = set()
    for path in _iter_py():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "FIELD_TERRAIN_LIST" in text:
            holders.add(path.relative_to(REPO).as_posix())
    return holders


def _field7_modules_non_test() -> set[str]:
    """Same, but only real modules (tests legitimately mention the constant)."""
    return {m for m in _field7_modules() if "test" not in Path(m).name}


def _command_route_names() -> list[str]:
    """The ``command_route`` table (38 rows) from the repo's read-only export."""
    uri = "file:" + BACKEND_DB.as_posix() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute("select command from command_route order by id").fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# A — "136 ops": the number in CLAUDE.md must equal the switch's case labels.
# --------------------------------------------------------------------------- #

class BridgeOpCount(unittest.TestCase):
    def test_bridge_op_count_is_what_claude_md_states(self):
        """Reads CLAUDE.md ('139 个 op') and BridgeServer.cs."""
        hit = _line_re(r"(\d+)\s*个 op")
        self.assertIsNotNone(hit, "CLAUDE.md no longer contains a '<n> 个 op' claim")
        line_no, _, m = hit
        stated = int(m.group(1))

        labels = _bridge_case_labels()
        self.assertEqual(
            len(labels), stated,
            f"CLAUDE.md:{line_no} says {stated} ops but BridgeServer.cs "
            f"({BRIDGE_SERVER.name}) has {len(labels)} 'case' labels",
        )
        # Pin today's value too, so a doc+code change that agrees with itself is
        # still visible: bumping the op count must be a deliberate edit here.
        # 136 -> 137 on 2026-10-10: EntityComponentProbe.cs added the dispatch case
        # 'inspect-entity-components'.  137 -> 138 on 2026-10-10: the sibling DELETE op
        # (EntityComponentDelete.cs) was wired — csproj <Compile>, the dispatch case
        # 'delete-entity-component', and the wire/queue plumbing.  BOTH halves are now
        # compiled; NEITHER has run on the real machine, and the DELETE op additionally
        # fails closed at its unbound component reader (see ComponentOpCompileStatus).
        # 138 -> 139 on 2026-10-10: the read-only ReflectionProbe.cs was wired — csproj
        # <Compile>, the dispatch case 'reflection-probe', the call-bridge ValidateSet and
        # the nameContains/memberContains wire/queue plumbing. It enumerates the LIVE
        # assembly (GetTypes + GetMethods only) so it is immune to a gap in the static corpus.
        # 139 -> 142 on 2026-10-10: the three fixed-needle siblings 'reflection-probe-component'
        # /-template/-service' were added to the switch and the ValidateSet but CLAUDE.md was
        # left at 139 (a drift this pin now corrects). 142 -> 146 on 2026-10-10: the four
        # assembly-scoped, member-name-filtered ops 'reflection-editor-add'/'‑create'/'-services'
        # /'-types' were wired (ReflectionProbe.RunEditorProbe) — they scope to the one assembly
        # whose simple name is "BeyondEditor" and filter by METHOD name, because the editor's
        # TYPE names are obfuscated. The count moving is the point of this pin.
        # 146 -> 148 on 2026-10-11 (correcting a +1 drift first): 'mine-process-strings'
        # (ProcessStringMine.cs) had been wired earlier without being added to the CLAUDE.md
        # tally (it silently made the real label count 147, not 146). This session wired
        # 'add-entity-component' (EntityComponentAdd.cs) -- the LOCAL-MODEL component ADD,
        # riding the editor's own entity-model loader path and dispatching NO native command
        # (nativeMutationInvoked=false, localModelWritten=true, persistentSaveVerified=false).
        # Both are now in the tally, so the label count and CLAUDE.md agree at 148.
        # 148 -> 151 on 2026-10-11: the bounded instruction-graph delete family
        # 'delete-instruction-graph' / '-force' / '-dry-run' was wired
        # (InstructionGraphDelete.cs -- csproj <Compile>, three dispatch cases, the
        # call-bridge ValidateSet and the ids/entityId wire branch). It dispatches the
        # native DeleteInstructionGraphForEditObj, whose NAME is a tier-2 FNV preimage
        # (0x2c4eda76) and whose PAYLOAD SHAPE is unrecovered, so the edit-object id is
        # required and its absence fails closed by name. It is NOT invokeable today: the
        # PINNED runner refuses both payload fields (entityId -> ENTITY_COMPONENT_ID_NOT_ALLOWED
        # / CALL_FIELD_NOT_ALLOWED:entityId; ids -> IDS_NOT_ALLOWED) and admits only the
        # bare kind/runId/op body, which call-bridge.ps1 then refuses. The count moving is
        # the point of this pin.
        self.assertEqual(stated, 151, "CLAUDE.md op count drifted from the pinned 151")

    def test_op_labels_are_unique(self):
        """A duplicated case label would silently merge two ops (reads BridgeServer.cs)."""
        labels = _bridge_case_labels()
        self.assertEqual(len(labels), len(set(labels)), "duplicate case labels in BridgeServer.cs")


# --------------------------------------------------------------------------- #
# B — no bridge op for the excluded categories (ui/component/property/...).
# --------------------------------------------------------------------------- #

class BridgeHasNoUiComponentPropertyOps(unittest.TestCase):
    def test_excluded_category_tokens_hit_no_bridge_op(self):
        """Reads the token list from CLAUDE.md:74 and the labels from BridgeServer.cs.

        CLAUDE.md claims the tokens ``ui/component/property/item/shop/currency/
        terrain`` are '全 0 命中' among the 136 ops.  An op is a hyphen-delimited
        name (``build-…``), so the tokens are matched per *segment*: ``ui`` is a
        segment of nothing here, whereas a raw substring search would wrongly flag
        ``build-*`` (the letters ``ui`` inside ``build``).  Matching on segments is
        what the doctrine means by a hit.
        """
        hit = _line_matching("全 0 命中")
        self.assertIsNotNone(hit, "CLAUDE.md no longer states the '全 0 命中' token claim")
        line_no, line = hit
        m = re.search(r"`([a-z/]+)`", line)
        self.assertIsNotNone(m, f"CLAUDE.md:{line_no} token list not parseable")
        tokens = m.group(1).split("/")

        labels = _bridge_case_labels()
        offenders: dict[str, list[str]] = {}
        for token in tokens:
            seg_hits = [lab for lab in labels if token in lab.split("-")]
            if seg_hits:
                offenders[token] = seg_hits

        self.assertEqual(
            offenders, {},
            f"CLAUDE.md:{line_no} claims tokens {tokens} are 全 0 命中, but "
            f"BridgeServer.cs has ops {offenders}",
        )


# --------------------------------------------------------------------------- #
# C — no transform command in the frontend command route table.
# --------------------------------------------------------------------------- #

class CommandRouteHasNoTransform(unittest.TestCase):
    def test_command_route_is_38_rows(self):
        """Reads backend.db (table ``command_route``, read-only)."""
        names = _command_route_names()
        self.assertEqual(
            len(names), 38,
            f"backend.db command_route has {len(names)} rows, CLAUDE.md says 38",
        )

    def test_modify_family_is_only_name_tag_faction_suite(self):
        """Reads backend.db; CLAUDE.md:26 says the Modify* family is Name/Tag/Faction/Suite."""
        names = _command_route_names()
        family = [n for n in names if n.startswith("Modify")]
        self.assertTrue(family, "no Modify* command found in command_route")

        kinds = {k for n in family for k in ("Name", "Tag", "Faction", "Suite") if k in n}
        self.assertEqual(
            kinds, {"Name", "Tag", "Faction", "Suite"},
            f"Modify* family spans {sorted(kinds)}, not the four kinds CLAUDE.md names",
        )
        # Every member must be one of the four (no silently-added 5th kind).
        for n in family:
            self.assertTrue(
                any(k in n for k in ("Name", "Tag", "Faction", "Suite")),
                f"Modify* member {n} is not Name/Tag/Faction/Suite",
            )

    def test_no_transform_command_in_command_route(self):
        """Reads backend.db and routes.json; CLAUDE.md:70 says there is no transform command."""
        names = _command_route_names()
        bad = [n for n in names if _TRANSFORMISH_RE.search(n)]
        self.assertEqual(
            bad, [],
            f"a transform-shaped command name exists in command_route: {bad}",
        )

        # The hand-written export that feeds the table must agree.
        routed = json.loads(_read(ROUTES_JSON))["commands"]
        routed_bad = [c["command"] for c in routed if _TRANSFORMISH_RE.search(c["command"])]
        self.assertEqual(
            routed_bad, [],
            f"a transform-shaped command name exists in routes.json: {routed_bad}",
        )


# --------------------------------------------------------------------------- #
# D — field 7 is terrain; the container codec keeps it opaque.
# --------------------------------------------------------------------------- #

class Field7Terrain(unittest.TestCase):
    def test_gil_container_defines_no_field7_constant(self):
        """Reads tools/beyond-save/gil_container.py.

        The container codec understands only fields 1/2/39/40 and keeps field 7
        (the terrain list) as opaque bytes in ``Level.raw``.  That is *why* a
        dedicated module had to exist to read field 7 at all.
        """
        src = _read(GIL_CONTAINER)
        consts = dict(re.findall(r"^(LEVEL_FIELD_[A-Z_]+)\s*=\s*(\d+)", src, re.M))
        self.assertEqual(
            set(consts), {"LEVEL_FIELD_ID", "LEVEL_FIELD_NAME",
                          "LEVEL_FIELD_CREATOR_UID", "LEVEL_FIELD_TIMESTAMP"},
            f"gil_container.py level-field constants changed: {sorted(consts)}",
        )
        self.assertEqual(
            set(consts.values()), {"1", "2", "39", "40"},
            f"gil_container.py now names a field number outside 1/2/39/40: {consts}",
        )
        self.assertNotIn("7", consts.values(), "gil_container.py now defines a field-7 constant")

    def test_field7_sole_reader_is_terrain_module(self):
        """Reads tools/beyond-save/terrain.py and scans every repo ``*.py``.

        CLAUDE.md:17 says 'field 7＝地形'; the only module that reads it today is
        ``terrain.py`` (the field-7 name constant ``FIELD_TERRAIN_LIST`` lives only
        there among non-test modules).
        """
        self.assertRegex(
            _read(TERRAIN), r"FIELD_TERRAIN_LIST\s*=\s*7",
            "terrain.py no longer pins FIELD_TERRAIN_LIST = 7",
        )
        modules = _field7_modules_non_test()
        self.assertEqual(
            modules, {"tools/beyond-save/terrain.py"},
            f"field 7 is read by modules other than terrain.py: {sorted(modules)}",
        )

    def test_claude_md_field7_claim_holds_today(self):
        """DRIFT DETECTOR — reads CLAUDE.md and the whole repo.

        CLAUDE.md used to assert, under 「已确证做不到」, that ``.gil`` field 7 has
        '**全仓 0 读写者**'.  That became false on 2026-10-10 when
        ``tools/beyond-save/terrain.py`` landed (``FIELD_TERRAIN_LIST = 7`` plus a
        read-only reader and an in-memory-only writer).

        The main agent corrected the line to: one read-only reader exists, and there
        is **no persisting writer**.  This test now guards THAT claim instead of the
        old one, and keeps the same teeth: it forces the doctrine to keep saying
        "there is a reader" only while a reader really exists, and to never claim a
        persisting writer.  If terrain.py is deleted, the "reader exists" half fails;
        if someone adds a persisting field-7 writer, the "no persisting writer" half
        fails.
        """
        hit = _line_matching("field 7", "读写者")
        self.assertIsNotNone(
            hit, "CLAUDE.md no longer carries a field-7 读写者 claim")
        line_no, _ = hit

        # The claim is a wrapped paragraph, so judge it over the paragraph window
        # (the matched line and the lines it continues onto), not a single line.
        lines = _claude_lines()
        window = "\n".join(lines[line_no - 1: line_no + 5])

        # Half 1 — the doctrine must not repeat the old "0 读写者" claim.
        self.assertNotIn(
            "**全仓 0 读写者**", window,
            f"CLAUDE.md:{line_no} still asserts field 7 has 全仓 0 读写者")
        self.assertIn(
            "持久化写回", window,
            f"CLAUDE.md:{line_no} must say plainly that there is no PERSISTING writer")

        # Half 2 — the reader it now names must really exist, and be the only one.
        readers = _field7_modules_non_test()
        self.assertEqual(
            readers, {"tools/beyond-save/terrain.py"},
            f"CLAUDE.md:{line_no} names a field-7 reader; the modules that actually "
            f"touch field 7 are {sorted(readers)}")


# --------------------------------------------------------------------------- #
# E — the elevated helper exposes exactly 6 native-scene actions.
# --------------------------------------------------------------------------- #

class HelperActions(unittest.TestCase):
    _EXPECTED = ["inspect", "create", "save", "create-batch", "reopen-current",
                 "creature-create"]

    def test_helper_action_list_is_six_fixed_actions(self):
        """Reads tools/editor-bridge/elevated-runner.ps1."""
        src = _read(ELEVATED_RUNNER)

        m = re.search(r"actions=@\(([^)]*)\)", src)
        self.assertIsNotNone(m, "elevated-runner.ps1 no longer declares actions=@(...)")
        actions = re.findall(r"'([a-z][a-z\-]*)'", m.group(1))
        self.assertEqual(
            actions, self._EXPECTED,
            f"elevated-runner.ps1 actions={actions}, expected the 6 fixed actions",
        )
        self.assertEqual(len(actions), 6, "helper action count is not 6")

        # The closed per-action field schema must key on the same six actions.
        map_keys = re.findall(r"^\s*'([a-z][a-z\-]*)'\s*=\s*@\(", src, re.M)
        self.assertEqual(
            sorted(map_keys), sorted(self._EXPECTED),
            f"elevated-runner.ps1 action-field map keys {sorted(map_keys)} != the 6 actions",
        )


# --------------------------------------------------------------------------- #
# F — the component op's two halves are NOT symmetric: READ compiled/wired,
#     DELETE neither.  (CLAUDE.md §五, the note under 「桥写 UI / 属性 / 模板」.)
# --------------------------------------------------------------------------- #

class ComponentOpCompileStatus(unittest.TestCase):
    """DRIFT DETECTOR — reads CLAUDE.md §五, the csproj, BridgeServer.cs, the current DLL.

    On 2026-10-10 the note under 「桥写 UI / 属性 / 模板」 lumped the two component-op
    halves together as 「候选，未编译未真机」.  Both halves are now COMPILED:

      * READ ``inspect-entity-components`` — ``Adapter/EntityComponentProbe.cs`` is in
        the csproj ``<Compile>`` set, ``BridgeServer.cs:306`` dispatches the case, and
        the build carries the op literal in its metadata heap.  COMPILED, but the
        real-machine run has not happened — NOT yet run on the real machine.
      * DELETE ``EntityComponentDelete.cs`` (command ``DeleteComponentForEditObj``) —
        now in the csproj ``<Compile>`` set, dispatched by case
        ``delete-entity-component``, and present in the current DLL.  WIRED and
        COMPILED, but also NOT yet run on the real machine; it additionally fails
        closed at its unbound component reader (``COMPONENT_MODEL_READER_UNBOUND``).

    Teeth, same in kind as Field7Terrain.test_claude_md_field7_claim_holds_today: the
    sentence the doctrine carries must agree with what the build inputs actually hold,
    so restoring the stale flat claim fails, claiming either half's status wrongly
    fails, and compiling/wiring (or unwiring) either half without editing CLAUDE.md
    fails.  The DLL read is a bonus: when the (git-ignored) build output is on disk it
    is checked for the op literals; when it is not, that one test skips.
    """

    _READ_STRINGS = ("inspect-entity-components",
                     "entity-components-editor-model-read-only",
                     "COMPONENT_PROBE_UNKNOWN_OR_DUPLICATE_FIELD")
    #: Real literals that must be present in a build that wires the DELETE op.  Only
    #: strings the compiler actually emits are listed -- no file-name or hyphen-plural
    #: variants that never reach the metadata heaps.
    _DELETE_STRINGS = ("EntityComponentDelete", "delete-entity-component")

    def test_claude_md_splits_the_two_halves_like_the_build_does(self):
        """DRIFT DETECTOR — reads CLAUDE.md §五, the csproj and BridgeServer.cs.

        The paragraph window must NOT still carry the old blanket 「未编译未真机」, and
        each half's status sentence must be present iff the build inputs make it true.
        """
        hit = _line_matching("inspect-entity-components")
        self.assertIsNotNone(
            hit, "CLAUDE.md no longer names 'inspect-entity-components' in its op note")
        line_no, _ = hit
        window = "\n".join(_claude_lines()[line_no - 1: line_no + 6])

        compiles = _csproj_compiles()
        labels = _bridge_case_labels()
        probe_in_build = _ends_with(compiles, "EntityComponentProbe.cs") and \
            "inspect-entity-components" in labels
        delete_in_build = (_ends_with(compiles, "EntityComponentDelete.cs")
                           or bool(_delete_component_cases(labels)))

        # (a) the stale blanket claim is gone.
        self.assertNotIn(
            "未编译未真机", window,
            f"CLAUDE.md:{line_no} still carries the stale flat 「未编译未真机」 claim")
        # (b) the READ half's 'compiled' sentence is present iff it really is compiled.
        #     The sentence must NOT pin a revision literal: resolving the payload DLL
        #     from the csproj is the whole point, and a hardcoded revision literal in
        #     the doc is exactly the stale pin this wave removed.  (The DLL path is
        #     resolved, so a bump cannot leave this assertion reading a removed artifact.)
        self.assertEqual(
            "已编译进" in window, probe_in_build,
            f"CLAUDE.md:{line_no} READ-half compile claim disagrees with the build: "
            f"EntityComponentProbe.cs in csproj="
            f"{_ends_with(compiles, 'EntityComponentProbe.cs')}, dispatch case="
            f"{'inspect-entity-components' in labels}")
        self.assertIsNone(
            re.search(r"Net8R\d+|(?<![A-Za-z0-9])R\d{2,3}(?![A-Za-z0-9])", window),
            f"CLAUDE.md:{line_no} pins a revision literal in the READ-half claim; it "
            "must say '当前 payload dll' so a revision bump cannot leave it stale")
        # (c) the DELETE half's 'un-built' sentence is present iff it really is un-built.
        self.assertEqual(
            "未编译、未接线" in window, not delete_in_build,
            f"CLAUDE.md:{line_no} DELETE-half claim disagrees with the build: "
            f"EntityComponentDelete.cs in csproj="
            f"{_ends_with(compiles, 'EntityComponentDelete.cs')}, delete cases="
            f"{_delete_component_cases(labels)}")

    def test_read_half_is_in_the_compile_set_and_the_switch(self):
        """Reads the csproj and BridgeServer.cs; CLAUDE.md:77 claims READ is wired."""
        compiles = _csproj_compiles()
        self.assertTrue(
            _ends_with(compiles, "EntityComponentProbe.cs"),
            "EntityComponentProbe.cs left the csproj <Compile> set, but CLAUDE.md "
            "claims the READ op is compiled into the current payload DLL")
        self.assertIn(
            "inspect-entity-components", _bridge_case_labels(),
            "BridgeServer.cs no longer dispatches 'inspect-entity-components', but "
            "CLAUDE.md claims the READ op is wired")

    def test_delete_half_is_in_the_compile_set_and_the_switch(self):
        """Reads the csproj and BridgeServer.cs; CLAUDE.md:77 claims DELETE is now wired."""
        compiles = _csproj_compiles()
        self.assertTrue(
            _ends_with(compiles, "EntityComponentDelete.cs"),
            "EntityComponentDelete.cs left the csproj <Compile> set, but CLAUDE.md:77 "
            "claims the DELETE op is wired")
        self.assertIn(
            "delete-entity-component", _bridge_case_labels(),
            "BridgeServer.cs no longer dispatches 'delete-entity-component', but "
            "CLAUDE.md:77 claims the DELETE op is wired")

    def test_built_artifact_carries_both_component_ops(self):
        """Reads the CURRENT payload DLL's metadata heaps; both component ops are compiled.

        Resolved from the csproj AssemblyName, so after a revision bump this checks the
        NEW artifact rather than a stale pre-change DLL left on disk.
        """
        dll = _current_payload_dll()
        if dll is None or not dll.exists():
            named = dll if dll is not None else "(csproj names no payload <AssemblyName>)"
            self.skipTest(
                f"{named} is not built in this checkout "
                "(tools/editor-bridge/**/bin/ is git-ignored). Build it with: "
                "dotnet build tools/editor-bridge/ManagedBridge/"
                "Miliastra.EditorBridge.csproj -c Release "
                "(or bump+rebuild with: pwsh -NoProfile -File "
                "tools/editor-bridge/next-revision.ps1). The path is resolved from the "
                "csproj AssemblyName, so a revision bump cannot leave this check "
                "pointing at a stale, already-removed DLL.")
        blob = dll.read_bytes()
        for s in self._READ_STRINGS:
            self.assertTrue(
                _in_metadata(blob, s),
                f"{dll.name} lacks the READ half's string {s!r}, but CLAUDE.md:77 "
                f"claims the READ op is compiled into it")
        for s in self._DELETE_STRINGS:
            self.assertTrue(
                _in_metadata(blob, s),
                f"{dll.name} lacks the DELETE half's string {s!r} -- the DELETE op is "
                f"wired (csproj + switch) but did not compile into the current revision")


if __name__ == "__main__":
    unittest.main()
