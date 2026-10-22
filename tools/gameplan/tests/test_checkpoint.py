"""Offline tests for :mod:`tools.gameplan.checkpoint` -- every source injected.

Nothing here contacts the bridge, the editor, or the game.  The live runner, the
editor-graph runner, the ``.gil`` verifier module and the directory reader are
all fakes, so the whole file runs on a machine with nothing installed and no
helper running.

The three behaviours this pins, each named in the task:

* a **clean collect** -- all four sections available and ok, the stage flags all
  true;
* a collect where a source is **unavailable**, and the report says *which* and
  *why* -- it never drops the section;
* two checkpoints differing in **exactly one field** diff to that field.
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:  # runnable as a script, not only under pytest
    sys.path.insert(0, str(_REPO))

from tools.gameplan import checkpoint as cp  # noqa: E402
from tools.gameplan.live import LiveState  # noqa: E402

NAME = "MW_API_FARM_DEMO"
GRAPH_ID = 1073741829
ENTITY_ID = 1077936129
RUN_ID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
FIXED_NOW = datetime(2026, 10, 10, 1, 35, 0, tzinfo=timezone.utc)

STATUS_JSON = """
{"pid": 176324, "elevated": true, "deadlineUtc": "2026-10-10T15:28:41Z", "handled": 6,
 "nativeScene": {"blocked": false, "actions": ["inspect","create","save"],
                 "pinsDigest": "ab162618", "pinCount": 2082}}
"""

LEVEL_JSON = """
{"ok": true, "kind": "current-level-observation", "levelId": 1073741842,
 "levelObservation": {"verified": true, "levelId": 1073741842},
 "entities": 11, "handle": "20261009-233002-eee2beb544", "run": "X:/run"}
"""


# --------------------------------------------------------------------------- #
# injected fakes -- one per source
# --------------------------------------------------------------------------- #

class FakeLiveRunner:
    """The live.Runner shape: argv -> (returncode, stdout)."""

    def __init__(self, status=STATUS_JSON, level=LEVEL_JSON):
        self.status, self.level = status, level
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        if "discover_current_level.py" in " ".join(argv):
            return (0, self.level)
        return (0, self.status)


def fake_graph_runner(argv, *, node_count=3, bound=(ENTITY_ID,)):
    """The builder.Runner shape: argv -> parsed receipt dict."""
    return {
        "ok": True,
        "backend": {
            "status": "OK",
            "nodeCount": node_count,
            "nodes": [{"definitionId": 100 + i} for i in range(node_count)],
            "boundEntityIds": list(bound),
        },
    }


class FakeReport:
    """The subset of GraphOnDiskReport the checkpoint reads."""

    def __init__(self, *, graph_found=True, path="X:/level/1073741842.gil"):
        self.path = Path(path)
        self.file_size = 28383
        self.payload_size = 28000
        self.subtype = 1
        self.sha256 = "ab" * 32
        self.graph_id = GRAPH_ID
        self.graph_occurrences = 1 if graph_found else 0
        self.graph_occurrences_by_root_field = {10: 1} if graph_found else {}
        self.entity_id = ENTITY_ID
        self.entity_occurrences = 1 if graph_found else 0
        self.size_delta = 6511
        self.payload_delta = 6400
        self.changed_root_fields = ()
        self.notes = ()
        self._graph_found = graph_found

    @property
    def graph_found(self):
        return self._graph_found


def fake_verify_module(*, graph_found=True):
    def verify(gil_path, *, graph_id, entity_id, baseline, expected_size):
        report = FakeReport(graph_found=graph_found, path=gil_path)
        report.graph_id = graph_id
        report.entity_id = entity_id
        return report

    return SimpleNamespace(verify=verify, DOES_NOT_PROVE=("presence is not proof",))


def fake_directory_reader(defects=()):
    def read(path):
        return list(defects)
    return read


def clean_collect(**overrides):
    """A collect where every source is injected and every source is ok."""
    kwargs = dict(
        live_reader=lambda: LiveState(ok=True, level_id=1073741842, entities=11,
                                      level_verified=True, helper_pid=176324,
                                      pins_digest="ab162618"),
        live_enabled=True,
        graph_runner=fake_graph_runner,
        graph_name=NAME,
        graph_id=GRAPH_ID,
        run_id=RUN_ID,
        gil_path="X:/level/1073741842.gil",
        entity_id=ENTITY_ID,
        verify_module=fake_verify_module(),
        directory_path="X:/level/1073741842.gil",
        directory_reader_fn=fake_directory_reader(),
        now=FIXED_NOW,
    )
    kwargs.update(overrides)
    return cp.collect(**kwargs)


# --------------------------------------------------------------------------- #
# a clean collect
# --------------------------------------------------------------------------- #

class TestCleanCollect(unittest.TestCase):
    def setUp(self):
        self.checkpoint = clean_collect()

    def test_all_four_sections_present(self):
        self.assertEqual(set(self.checkpoint["sections"]), set(cp.SECTION_NAMES))

    def test_ok_and_no_unavailable(self):
        self.assertTrue(self.checkpoint["ok"])
        self.assertEqual(self.checkpoint["unavailable"], [])
        self.assertEqual(self.checkpoint["notOk"], [])

    def test_every_section_available_and_ok(self):
        for name in cp.SECTION_NAMES:
            section = self.checkpoint["sections"][name]
            self.assertTrue(section["available"], name)
            self.assertTrue(section["ok"], name)
            self.assertIsNone(section["reason"], name)

    def test_stage_flags_all_true(self):
        self.assertEqual(self.checkpoint["stages"], {
            "levelKnown": True,
            "graphInEditor": True,
            "graphBound": True,
            "graphOnDisk": True,
            "directoryClean": True,
        })

    def test_live_section_carries_the_reading(self):
        data = self.checkpoint["sections"]["liveLevel"]["data"]
        self.assertEqual(data["level"]["levelId"], 1073741842)
        self.assertEqual(data["level"]["entities"], 11)
        self.assertEqual(data["helper"]["pinsDigest"], "ab162618")
        self.assertEqual(data["source"], "native-read")

    def test_editor_graph_section(self):
        data = self.checkpoint["sections"]["editorGraph"]["data"]
        self.assertEqual(data["nodeCount"], 3)
        self.assertEqual(data["nodeDefinitionIds"], [100, 101, 102])
        self.assertEqual(data["boundEntityIds"], [ENTITY_ID])

    def test_graph_request_id_is_a_function_of_the_request(self):
        data = self.checkpoint["sections"]["editorGraph"]["data"]
        self.assertEqual(
            data["requestId"],
            cp.request_id("graph-status", "inspect", NAME, GRAPH_ID, RUN_ID))

    def test_gil_section_carries_the_ids_and_caveats(self):
        data = self.checkpoint["sections"]["graphOnDisk"]["data"]
        self.assertEqual(data["graphId"], GRAPH_ID)
        self.assertTrue(data["graphFound"])
        self.assertEqual(data["sha256"], "ab" * 32)
        self.assertEqual(data["doesNotProve"], ["presence is not proof"])

    def test_timestamp_is_recorded(self):
        self.assertEqual(self.checkpoint["createdUtc"], "2026-10-10T01:35:00Z")

    def test_kind_and_version(self):
        self.assertEqual(self.checkpoint["kind"], "gameplan-checkpoint")
        self.assertEqual(self.checkpoint["version"], 1)


# --------------------------------------------------------------------------- #
# a source that is unavailable is NAMED, never omitted
# --------------------------------------------------------------------------- #

class TestUnavailableSources(unittest.TestCase):
    def test_missing_graph_request_names_editor_graph(self):
        checkpoint = clean_collect(graph_runner=None, graph_name=None,
                                   graph_id=None, run_id=None)
        section = checkpoint["sections"]["editorGraph"]
        self.assertFalse(section["available"])
        self.assertIn("editorGraph", section["reason"])
        self.assertIn("editorGraph", checkpoint["unavailable"])
        # ...and the section is still there, with a name.
        self.assertEqual(set(checkpoint["sections"]), set(cp.SECTION_NAMES))
        self.assertEqual(section["name"], "editorGraph")

    def test_missing_gil_path_names_graph_on_disk(self):
        checkpoint = clean_collect(gil_path=None, verify_module=None)
        section = checkpoint["sections"]["graphOnDisk"]
        self.assertFalse(section["available"])
        self.assertIn(".gil", section["reason"])
        self.assertIn("graphOnDisk", checkpoint["unavailable"])

    def test_missing_directory_path_names_directory_defects(self):
        checkpoint = clean_collect(directory_path=None, directory_reader_fn=None)
        section = checkpoint["sections"]["directoryDefects"]
        self.assertFalse(section["available"])
        self.assertIn(".gil", section["reason"])
        self.assertIn("directoryDefects", checkpoint["unavailable"])

    def test_a_raising_reader_becomes_a_named_reason(self):
        def boom():
            raise RuntimeError("helper not up")

        checkpoint = clean_collect(live_reader=boom)
        section = checkpoint["sections"]["liveLevel"]
        self.assertFalse(section["available"])
        self.assertIn("liveLevel", section["reason"])
        self.assertIn("RuntimeError", section["reason"])
        self.assertIn("helper not up", section["reason"])
        self.assertIn("liveLevel", checkpoint["unavailable"])

    def test_live_disabled_is_unavailable_not_a_silent_skip(self):
        class NeverCall:
            def __call__(self, argv):
                raise AssertionError("live runner must not be called when disabled")

        checkpoint = clean_collect(live_reader=None, live_runner=NeverCall(),
                                   live_enabled=False)
        section = checkpoint["sections"]["liveLevel"]
        self.assertFalse(section["available"])
        self.assertIn("disabled", section["reason"])
        self.assertIn("liveLevel", checkpoint["unavailable"])

    def test_read_but_not_ok_is_available_and_not_ok(self):
        state = LiveState(ok=False, reason="helper-not-elevated", source="native-read")
        checkpoint = clean_collect(live_reader=lambda: state)
        section = checkpoint["sections"]["liveLevel"]
        self.assertTrue(section["available"])
        self.assertFalse(section["ok"])
        self.assertEqual(section["reason"], "helper-not-elevated")
        self.assertNotIn("liveLevel", checkpoint["unavailable"])
        self.assertIn("liveLevel", checkpoint["notOk"])

    def test_overall_ok_is_false_when_anything_is_unavailable(self):
        checkpoint = clean_collect(gil_path=None, verify_module=None)
        self.assertFalse(checkpoint["ok"])


# --------------------------------------------------------------------------- #
# the optional verify module degrades with a NAMED reason
# --------------------------------------------------------------------------- #

class TestOptionalModuleDegrades(unittest.TestCase):
    NAMED = "graphOnDisk: verify_graph_on_disk unavailable (ImportError: not in this checkout)"

    def test_verify_module_absent(self):
        checkpoint = clean_collect(verify_module=None, verify_loader=lambda: (None, self.NAMED))
        section = checkpoint["sections"]["graphOnDisk"]
        self.assertFalse(section["available"])
        self.assertEqual(section["reason"], self.NAMED)
        self.assertIsNone(section["data"])

    def test_directory_module_absent(self):
        named = "directoryDefects: tools/beyond-save/level_directory unavailable (ImportError: x)"
        checkpoint = clean_collect(directory_module=None,
                                   directory_reader_fn=None,
                                   directory_loader=lambda: (None, named))
        section = checkpoint["sections"]["directoryDefects"]
        self.assertFalse(section["available"])
        self.assertEqual(section["reason"], named)

    def test_real_verify_module_is_resolvable_offline(self):
        # The module IS in this checkout, so the production loader must find it.
        module, reason = cp.load_verify_module()
        self.assertIsNotNone(module, reason)
        self.assertTrue(hasattr(module, "verify"))

    def test_real_directory_module_is_resolvable_offline(self):
        module, reason = cp.load_directory_module()
        self.assertIsNotNone(module, reason)
        self.assertTrue(hasattr(module, "check_directory"))


# --------------------------------------------------------------------------- #
# diff -- two checkpoints to the field
# --------------------------------------------------------------------------- #

class TestDiff(unittest.TestCase):
    def test_one_changed_field_diffs_to_that_field(self):
        before = clean_collect()
        after = copy.deepcopy(before)
        after["sections"]["editorGraph"]["data"]["nodeCount"] = 4

        report = cp.diff(before, after)
        self.assertFalse(report["clean"])
        self.assertEqual(report["changedCount"], 1)
        self.assertEqual(list(report["changed"]), ["sections.editorGraph.data.nodeCount"])
        self.assertEqual(report["changed"]["sections.editorGraph.data.nodeCount"],
                         {"before": 3, "after": 4})
        self.assertEqual(report["added"], {})
        self.assertEqual(report["removed"], {})

    def test_identical_checkpoints_are_clean(self):
        before = clean_collect()
        self.assertTrue(cp.diff(before, copy.deepcopy(before))["clean"])

    def test_timestamp_is_ignored_by_default(self):
        first = clean_collect(now=datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc))
        second = clean_collect(now=datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc))
        self.assertNotEqual(first["createdUtc"], second["createdUtc"])
        self.assertTrue(cp.diff(first, second)["clean"])

    def test_a_section_flipping_to_unavailable_shows_as_changes(self):
        before = clean_collect()
        after = clean_collect(live_reader=lambda: LiveState(ok=False, reason="helper-not-elevated"))
        report = cp.diff(before, after)
        self.assertIn("sections.liveLevel.ok", report["changed"])
        self.assertIn("sections.liveLevel.reason", report["changed"])
        self.assertIn("stages.levelKnown", report["changed"])

    def test_added_and_removed_leaves_are_reported(self):
        report = cp.diff({"a": {"b": 1, "c": 2}}, {"a": {"b": 1, "d": 3}})
        self.assertEqual(report["removed"], {"a.c": 2})
        self.assertEqual(report["added"], {"a.d": 3})
        self.assertEqual(report["changed"], {})


# --------------------------------------------------------------------------- #
# persistence under .runtime/scratch/checkpoints
# --------------------------------------------------------------------------- #

class TestPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_write_read_roundtrip(self):
        checkpoint = clean_collect()
        path = cp.write_checkpoint(checkpoint, directory=self.dir, now=FIXED_NOW)
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "20261010T013500Z.json")
        self.assertEqual(cp.read_checkpoint(path), checkpoint)

    def test_second_write_gets_a_distinct_name(self):
        first = cp.write_checkpoint(clean_collect(), directory=self.dir, now=FIXED_NOW)
        second = cp.write_checkpoint(clean_collect(), directory=self.dir, now=FIXED_NOW)
        self.assertNotEqual(first, second)

    def test_latest_and_list(self):
        self.assertIsNone(cp.latest_checkpoint(self.dir))
        early = cp.write_checkpoint(
            clean_collect(now=datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)),
            directory=self.dir, now=datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc))
        late = cp.write_checkpoint(
            clean_collect(now=datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc)),
            directory=self.dir, now=datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc))
        self.assertEqual(cp.latest_checkpoint(self.dir), late)
        self.assertEqual(cp.list_checkpoints(self.dir), [early, late])

    def test_collect_alone_writes_nothing(self):
        clean_collect()
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_stamp_is_utc_and_sortable(self):
        self.assertEqual(cp.stamp(datetime(2026, 10, 10, 1, 35, 0, tzinfo=timezone.utc)),
                         "20261010T013500Z")


# --------------------------------------------------------------------------- #
# the CLI -- still offline when the sources are
# --------------------------------------------------------------------------- #

class TestCLI(unittest.TestCase):
    def run_cli(self, argv):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cp.main(argv)
        return code, buffer.getvalue()

    def test_collect_no_sources_is_offline_and_reports_all_four(self):
        code, out = self.run_cli(["collect", "--no-live", "--no-write"])
        checkpoint = json.loads(out)
        self.assertEqual(code, 1)  # not ok, but it ran
        self.assertEqual(set(checkpoint["sections"]), set(cp.SECTION_NAMES))
        self.assertEqual(set(checkpoint["unavailable"]), set(cp.SECTION_NAMES))

    def test_diff_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            before = cp.write_checkpoint(clean_collect(), directory=directory,
                                         path=directory / "a.json")
            after = copy.deepcopy(clean_collect())
            after["sections"]["directoryDefects"]["data"]["defectCount"] = 1
            after_path = cp.write_checkpoint(after, directory=directory,
                                             path=directory / "b.json")
            code, out = self.run_cli(["diff", str(before), str(after_path)])
            report = json.loads(out)
            self.assertEqual(code, 4)
            self.assertEqual(list(report["changed"]),
                             ["sections.directoryDefects.data.defectCount"])

    def test_diff_cli_clean_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            one = cp.write_checkpoint(clean_collect(), directory=directory,
                                      path=directory / "a.json")
            two = cp.write_checkpoint(clean_collect(), directory=directory,
                                      path=directory / "b.json")
            code, _ = self.run_cli(["diff", str(one), str(two)])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
