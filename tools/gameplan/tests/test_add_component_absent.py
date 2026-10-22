"""PIN the "add-component is absent" NEGATIVE so it is not re-searched every session.

Two waves independently re-ran the same add-component hunt and reached the same answer.
This file encodes that answer as a runnable check: a future session runs *this test* in
a second instead of spending an hour re-deriving it.  It is a **drift alarm**, not an
ability -- it adds no capability, it only keeps the recorded conclusion honest.

The recorded conclusion, verbatim-ish (``docs/research/reverse-eng-20261010/``):

  * ``ADD-COMPONENT-TRACE.md`` -- the command face of ``Add/Create/Attach/Insert
    ``Component`` is empty across BOTH builds (legacy ``editor-legacy`` 2830-literal
    table and the installed ``editor-7.1`` 2985-literal table); only the two
    ``DeleteComponentFor*`` commands exist.
  * ``COMPONENT-WRITER-MINE.md`` §5 -- no component-add row in ``backend.db``
    ``command_route`` (38 rows) nor ``frontend.db`` ``operation`` (44 rows).
  * ``CHANNEL-2001.md`` -- the single 2001 sender lives behind a compile-time literal
    ``if (false)`` (``IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs:432``), so it never
    fires; 2001 is a field-update of an EXISTING component, not an add.

THE CAVEAT THIS FILE EXISTS TO PROTECT
--------------------------------------
"Absent from the decompiled corpus + the command tables" is NOT "does not exist".  The
component-panel list view models are literally present
(``LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.RqDuurAmdYi`` and
``yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.EFou75eU8IC``) but their static factories have
**zero callers** anywhere in the 12,375 decompiled ``.cs`` files -- the panel WIRING is
*outside* the decompiled set, not absent from the product.  This test asserts that zero
still holds, so the recorded verdict can never silently drift from "absent from the
corpus + command tables" into the stronger (and false) "does not exist".

Reads only, offline: the two decompiled string tables, the two command-table SQLite dbs,
the 12,375-file decompiled corpus, and the one 2001-sender source file.  No bridge, no
native call, no game/editor contact, nothing written.  The dbs are opened ``mode=ro``.
Artifacts under ``.runtime/`` (git-ignored) are absent on a fresh checkout: each test
SKIPS LOUDLY (never silently passes) when the file it reads is missing.

Run::

    python -B -m unittest tools.gameplan.tests.test_add_component_absent
"""

from __future__ import annotations

import json
import re
import sqlite3
import unittest
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

# --- decompiled string tables (offset -> literal); each is a whole-build literal set ---
LEGACY_STRING_TABLE = REPO / ".runtime" / "editor-catalog" / "string-table.json"
EDITOR71_STRING_TABLES = (
    # The decisive one (installed 7.1 BeyondEditor.dll, 2985 literals).  Two independent
    # extractions exist; both are checked when present.
    REPO / ".runtime" / "scratch" / "editor71-string-table.json",
    REPO / ".runtime" / "verification" / "update-repair-20260925" / "strings"
    / "string-table-7.1.json",
)

# --- the two command tables ---
BACKEND_DB = REPO / "docs" / "research" / "beyondeditor-backend" / "db" / "backend.db"
FRONTEND_DB = REPO / "docs" / "research" / "beyondeditor-frontend" / "db" / "frontend.db"

# --- decompiled corpus ---
RESOLVED = REPO / ".runtime" / "editor-catalog" / "resolved"

# --- the ONE 2001 sender file ---
SENDER = RESOLVED / "IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs"
SENDER_PAYLOAD_CTOR = "new gcxejEBKDw4nOrlXagP()"   # the 2001 payload class
SENDER_MSG_ID = "2001"

# The four literal spellings the hunt searched for and found zero of.
ADD_COMPONENT_LITERALS = ("AddComponent", "CreateComponent", "AttachComponent",
                          "InsertComponent")
# Positive control: the ONLY component commands that do exist, in both builds/tables.
EXISTING_COMPONENT_COMMANDS = ("DeleteComponentForEditObj", "DeleteComponentForPrefab")

# The two component-panel list-VM factories that must still have ZERO callers.
LIST_VM_FACTORIES = (
    ("RqDuurAmdYi", "LyiKwiuuZOXPIU5ItQge.UY3FwAuuVnr6w8n0v5kN.cs"),
    ("EFou75eU8IC", "yOsfpwuuzUC3h2nZXoV9.TDKVvfuuIslakGU226IJ.cs"),
)


def _rel(path: Path) -> str:
    """Repo-relative posix path for a message (fallback to str for out-of-tree paths)."""
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def _load_string_table(path: Path) -> list[str] | None:
    """The literal values of a decompiled string table, or ``None`` if it is absent."""
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [str(v) for v in data.values()]
    return [str(v) for v in data]


@lru_cache(maxsize=1)
def _corpus_texts() -> tuple[tuple[str, str], ...]:
    """(filename, text) for every ``.cs`` in the decompiled corpus, read once.

    The corpus is ~72 MB across 12,375 files; two callers read it, so it is cached for
    the run rather than decoded twice.
    """
    out: list[tuple[str, str]] = []
    for path in sorted(RESOLVED.glob("*.cs")):
        try:
            out.append((path.name, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return tuple(out)


class StringTableNegative(unittest.TestCase):
    """(a) The decompiled string table carries no add-component literal."""

    def _check(self, path: Path) -> None:
        values = _load_string_table(path)
        rel = _rel(path)
        self.assertIsNotNone(values, f"{rel} vanished between listing and read")
        for literal in ADD_COMPONENT_LITERALS:
            hits = [v for v in values if literal in v]
            self.assertEqual(
                hits, [],
                f"ADD-COMPONENT NEGATIVE IS BROKEN: {rel} now contains {literal!r} "
                f"(hits={hits[:5]}). The 'no add-component literal in the decompiled "
                "string table' claim is no longer true for this build -- the negative "
                "must be re-derived, not re-asserted.")
        # Positive control: the table really is the component-bearing one.
        joined = "\n".join(values)
        for command in EXISTING_COMPONENT_COMMANDS:
            self.assertIn(
                command, joined,
                f"{rel} does not contain the known-existing {command!r}: this looks "
                "like the wrong / truncated table, which would make the negative above "
                "vacuous.")

    def test_legacy_string_table_has_no_add_component_literal(self):
        """Reads ``.runtime/editor-catalog/string-table.json`` (editor-legacy, 2830)."""
        if not LEGACY_STRING_TABLE.exists():
            self.skipTest(
                f"{LEGACY_STRING_TABLE.relative_to(REPO).as_posix()} is not in this "
                "checkout (.runtime/ is git-ignored). The negative is pinned when the "
                "artifact is present.")
        self._check(LEGACY_STRING_TABLE)

    def test_editor71_string_tables_have_no_add_component_literal(self):
        """Reads the installed 7.1 tables (see EDITOR71_STRING_TABLES)."""
        present = [p for p in EDITOR71_STRING_TABLES if p.exists()]
        if not present:
            self.skipTest(
                "no editor-7.1 string table in this checkout (expected one of "
                + ", ".join(p.relative_to(REPO).as_posix() for p in EDITOR71_STRING_TABLES)
                + "); .runtime/ is git-ignored. TASK-PIN: regenerate with "
                  "'python tools/editor-catalog/string_table.py extract' before "
                  "trusting this skip.")
        for path in present:
            self._check(path)


class CommandTableNegative(unittest.TestCase):
    """(b) backend ``command_route`` and frontend ``operation`` have no add-component row."""

    _QUERY = ("select {col} from {table} where lower({col}) like '%component%'")

    def _component_commands(self, db: Path, table: str, col: str) -> list[str]:
        uri = "file:" + db.as_posix() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        try:
            rows = con.execute(self._QUERY.format(col=col, table=table)).fetchall()
        finally:
            con.close()
        return [r[0] for r in rows]

    def _check(self, db: Path, table: str, col: str) -> None:
        rel = _rel(db)
        commands = self._component_commands(db, table, col)
        lowers = {c.lower() for c in commands}
        for literal in ADD_COMPONENT_LITERALS:
            offender = sorted(c for c in commands if literal.lower() in c.lower())
            self.assertEqual(
                offender, [],
                f"ADD-COMPONENT NEGATIVE IS BROKEN: {rel}->{table} now has an "
                f"add-component command {offender} (matched {literal!r}). The "
                "'no add-component row in the command table' claim no longer holds.")
        # Positive control: the table really is the component-bearing one.
        joined = " ".join(lowers)
        for command in EXISTING_COMPONENT_COMMANDS:
            self.assertIn(
                command.lower(), joined,
                f"{rel}->{table} does not contain the known-existing component command "
                f"{command!r}; the negative above would be vacuous on a wrong table.")

    def test_backend_command_route_has_no_component_add_row(self):
        """Reads ``docs/research/beyondeditor-backend/db/backend.db`` -> command_route."""
        if not BACKEND_DB.exists():
            self.skipTest(f"{BACKEND_DB.relative_to(REPO).as_posix()} is not in this "
                          "checkout.")
        self._check(BACKEND_DB, "command_route", "command")

    def test_frontend_operation_has_no_component_add_row(self):
        """Reads ``docs/research/beyondeditor-frontend/db/frontend.db`` -> operation."""
        if not FRONTEND_DB.exists():
            self.skipTest(f"{FRONTEND_DB.relative_to(REPO).as_posix()} is not in this "
                          "checkout.")
        self._check(FRONTEND_DB, "operation", "op_name")


class Sender2001IsBehindLiteralFalse(unittest.TestCase):
    """(c) the single 2001 sender sits behind a compile-time literal ``if (false)``.

    Reads ``.runtime/editor-catalog/resolved/IYgPyZKp4YZMa8AR81SZ.YWlUeFKpEU3Lh8YnZ6Mj.cs``.
    """

    def _read_sender(self) -> str:
        if not SENDER.exists():
            self.skipTest(
                f"{SENDER.relative_to(REPO).as_posix()} is not in this checkout "
                "(.runtime/ is git-ignored).")
        return SENDER.read_text(encoding="utf-8", errors="ignore")

    @staticmethod
    def _block_body(text: str, start: int) -> str | None:
        """The brace body of the first ``{...}`` at/after ``start`` (brace-matched)."""
        brace = text.find("{", start)
        if brace < 0:
            return None
        depth = 0
        j = brace
        while j < len(text):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[brace + 1:j]
            j += 1
        return None

    def test_2001_send_exists_in_the_named_file(self):
        """Positive control: the file really owns the one 2001 send."""
        text = self._read_sender()
        self.assertIn(SENDER_PAYLOAD_CTOR, text,
                      f"{SENDER.name} no longer constructs the gcxejEBKDw4nOrlXagP "
                      "2001 payload; the sender was relocated and this pin is stale.")
        send_lines = [ln for ln in text.splitlines()
                      if SENDER_MSG_ID in ln and SENDER_PAYLOAD_CTOR.replace("new ", "")
                      .rstrip("()") in ln]
        self.assertTrue(
            send_lines,
            f"{SENDER.name} no longer contains a send of {SENDER_MSG_ID} carrying the "
            "gcxejEBKDw4nOrlXagP payload; the channel-2001 finding must be re-derived.")

    def test_payload_construction_is_gated_by_a_literal_if_false(self):
        """The 2001 sender sits behind a compile-time literal ``if (false)``."""
        text = self._read_sender()
        gated = False
        for match in re.finditer(r"if\s*\(\s*false\s*\)", text):
            body = self._block_body(text, match.end())
            if body and SENDER_PAYLOAD_CTOR in body and "num2 = 10" in body:
                gated = True
                break
        self.assertTrue(
            gated,
            f"ADD-COMPONENT NEGATIVE IS BROKEN / STALE: no literal 'if (false)' block in "
            f"{SENDER.name} gates the 2001 payload construction "
            f"({SENDER_PAYLOAD_CTOR} -> num2 = 10). Either the dead branch was removed "
            "(the sender may now be live -- CHANNEL-2001.md must be re-derived) or the "
            "file moved.")

    def test_no_dispatcher_receiver_for_2001_in_the_corpus(self):
        """No ``case 2001`` anywhere: 2001's receiver is not in the decompiled set."""
        if not RESOLVED.exists():
            self.skipTest(f"{RESOLVED.relative_to(REPO).as_posix()} is not in this "
                          "checkout; .runtime/ is git-ignored.")
        offenders = []
        for name, txt in _corpus_texts():
            if re.search(r"case\s+2001\b", txt):
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            f"CHANNEL-2001 NEGATIVE IS BROKEN: a 'case 2001' dispatch arm now exists in "
            f"{offenders[:5]}: the receiver the channel lacked has appeared, so the "
            "'registered-but-unrouted' verdict must be re-derived.")


class CorpusCoverageCaveat(unittest.TestCase):
    """The caveat: absent-from-corpus is NOT does-not-exist.

    Both component-panel list-VM factories have ZERO callers in the 12,375 decompiled
    ``.cs`` files -- the panel wiring is *outside* the decompiled set.  This test fails if
    a caller appears, because then the corpus is no longer partial and the recorded
    "absent from the decompiled corpus" conclusion changed meaning.
    """

    @unittest.skipUnless(RESOLVED.exists(), "decompiled corpus not in this checkout")
    def test_list_vm_factories_have_zero_callers(self):
        """Reads every ``*.cs`` in ``.runtime/editor-catalog/resolved/``."""
        counts = {name: 0 for name, _ in LIST_VM_FACTORIES}
        definition_files = {}
        for fname, txt in _corpus_texts():
            for name, owning in LIST_VM_FACTORIES:
                n = txt.count(name)
                if n:
                    counts[name] += n
                    if owning == fname:
                        definition_files[name] = (fname, txt)
        for name, owning in LIST_VM_FACTORIES:
            with self.subTest(factory=name):
                # Exactly one occurrence = the declaration, and nothing else: zero callers.
                self.assertEqual(
                    counts[name], 1,
                    f"CORPUS-COVERAGE CAVEAT BROKEN: {name} occurs {counts[name]} times "
                    f"across {RESOLVED.relative_to(REPO).as_posix()}/*.cs, not 1 (the "
                    "declaration only). A caller appeared in the decompiled corpus, so "
                    "the panel wiring is no longer 'outside the decompiled set' and the "
                    "recorded 'absent from the decompiled corpus' caveat has changed "
                    "meaning -- re-derive ADD-COMPONENT-TRACE.md §7.")
                # And the lone occurrence is the static factory declaration itself.
                self.assertIn(
                    name, definition_files,
                    f"{name}'s single occurrence is not its declaration in {owning}; the "
                    "corpus-coverage assumption (declaration present, no callers) no "
                    "longer holds.")
                decl_line = next(ln for ln in definition_files[name][1].splitlines()
                                 if name in ln)
                self.assertIn(
                    "static", decl_line,
                    f"{name}'s only occurrence is not a static factory declaration: "
                    f"{decl_line.strip()!r} -- the corpus-coverage caveat must be "
                    "re-derived.")

    def test_corpus_coverage_search_is_not_vacuous(self):
        """The corpus is really there (the previous test is not passing on an empty dir)."""
        if not RESOLVED.exists():
            self.skipTest(f"{RESOLVED.relative_to(REPO).as_posix()} is not in this "
                          "checkout.")
        self.assertTrue(
            list(RESOLVED.glob("*.cs")),
            f"{RESOLVED.relative_to(REPO).as_posix()} holds no .cs files; the "
            "zero-callers assertion would be vacuously true.")


if __name__ == "__main__":
    unittest.main()
