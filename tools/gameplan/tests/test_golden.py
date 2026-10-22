"""Tests for :mod:`tools.gameplan.golden` — the plan-shape guard.

The point of this file is the first three tests: if the six-module demo graph
changes shape (a node added, removed, re-typed, re-wired) the committed snapshot
stops matching and the failure prints the *exact* diff, in the commit, before the
change can be lost to memory.  The rest prove the diff actually discriminates —
that a mutation is reported with the node's alias and definitionId, not just a
truthy boolean.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tools.gameplan import golden
from tools.gameplan.demo.farming_full import FarmFullConfig, build_plan as build_farming_full
from tools.gameplan.plan import ConstSpec, NodeSpec

# The committed `farming_full` snapshot is frozen at harvest_bonus=0; this config
# turns on the #13 bonus leg so the two plans differ by exactly one node.
BONUS_CONFIG = FarmFullConfig(
    currency_id=1115684864, crop_id=1120000001, food_id=1120000002, harvest_bonus=7
)
from tools.gameplan.golden import (
    COMMITTED_DIR,
    SCRATCH_DIR,
    GoldenError,
    GoldenMissingError,
    compare,
    compare_file,
    dumps,
    freeze,
    read_golden,
    write_golden,
)


class TestCommittedGoldenMatchesFreshBuild(unittest.TestCase):
    """The guard: a live build must equal the committed snapshot, byte for byte."""

    def test_every_demo_plan_matches_its_committed_golden(self):
        for name, plan in golden.build_demo_plans().items():
            with self.subTest(plan=name):
                report = compare_file(plan, name, directory=COMMITTED_DIR)
                self.assertTrue(
                    report.ok,
                    f"plan {name!r} drifted from tools/gameplan/golden/{name}.json:\n{report}",
                )

    def test_committed_files_are_canonical_bytes(self):
        # Re-freezing a fresh build must reproduce the file exactly, so a change
        # is a clean one-line diff and never pure key-order noise.
        for name, plan in golden.build_demo_plans().items():
            with self.subTest(plan=name):
                path = COMMITTED_DIR / f"{name}.json"
                self.assertEqual(path.read_text(encoding="utf-8"), dumps(freeze(plan)))
                self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_golden_files_are_sorted_json_objects(self):
        for name in golden.build_demo_plans():
            with self.subTest(plan=name):
                raw = (COMMITTED_DIR / f"{name}.json").read_text(encoding="utf-8")
                data = json.loads(raw)
                self.assertEqual(list(data), sorted(data))
                # Canonical re-serialisation is a fixed point.
                self.assertEqual(raw, dumps(data))


class TestMutationIsReported(unittest.TestCase):
    """A deliberately mutated plan must be reported, with alias + definitionId.

    Every mutation here edits the *live plan* and diffs it against the committed
    ``farming`` snapshot — the direction a real drift travels.
    """

    def _farming(self):
        return golden.build_demo_plans()["farming"]

    @staticmethod
    def _replace_node(plan, alias, *, definition_id=None, x=None, y=None):
        for i, node in enumerate(plan.nodes):
            if node.alias == alias:
                plan.nodes[i] = NodeSpec(
                    alias=node.alias,
                    definition_id=node.definition_id if definition_id is None else definition_id,
                    x=node.x if x is None else x,
                    y=node.y if y is None else y,
                )
                return
        raise KeyError(alias)

    def test_node_retyped_reports_alias_and_both_definition_ids(self):
        plan = self._farming()
        self._replace_node(plan, "gate", definition_id=999)  # 双分支 2 -> 999
        report = compare(plan, read_golden("farming", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_definition_changed")
        self.assertEqual(change.alias, "gate")
        self.assertEqual(change.definition_id, 999)      # the mutated (live) value
        self.assertEqual(change.was_definition_id, 2)     # the committed value
        self.assertIn("gate", str(change))
        self.assertIn("999", str(change))

    def test_node_moved_reports_position(self):
        plan = self._farming()
        self._replace_node(plan, "harvest", x=320, y=-64)
        report = compare(plan, read_golden("farming", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_position_changed")
        self.assertEqual(change.alias, "harvest")
        self.assertIn("320", str(change))

    def test_removed_node_reports_alias_and_definition_id(self):
        plan = self._farming()
        plan.nodes[:] = [n for n in plan.nodes if n.alias != "money_note"]
        report = compare(plan, read_golden("farming", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_removed")
        self.assertEqual(change.alias, "money_note")
        self.assertEqual(change.definition_id, 1)

    def test_real_added_node_is_reported_with_alias_and_definition_id(self):
        # A genuine plan mutation: the #13 bonus leg adds `harvest_bonus` (688).
        mutated_plan = build_farming_full(BONUS_CONFIG)
        report = compare(mutated_plan, read_golden("farming_full", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_added")
        self.assertEqual(change.alias, "harvest_bonus")
        self.assertEqual(change.definition_id, 688)
        self.assertIn("harvest_bonus", str(change))

    def test_edge_and_const_changes_are_reported(self):
        plan = self._farming()
        plan.edges.pop()                                   # drop one wire
        first = plan.consts[0]
        plan.consts[0] = ConstSpec(
            alias=first.alias, port_index=first.port_index, value=123456789,
            slot=first.slot,
        )
        report = compare(plan, read_golden("farming", directory=COMMITTED_DIR))
        kinds = {c.kind for c in report.changes}
        self.assertIn("edge_removed", kinds)
        self.assertIn("const_changed", kinds)

    def test_identical_plan_is_ok(self):
        report = compare_file(
            golden.build_demo_plans()["farming"], "farming", directory=COMMITTED_DIR
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.changes, ())
        self.assertEqual(str(report), "identical")
        self.assertTrue(bool(report))


class TestMissingGolden(unittest.TestCase):
    def test_missing_golden_raises_named_error(self):
        with self.assertRaises(GoldenMissingError) as caught:
            read_golden("this-golden-does-not-exist", directory=COMMITTED_DIR)
        message = str(caught.exception)
        self.assertIn("this-golden-does-not-exist", message)

    def test_named_error_is_also_a_file_not_found_and_a_golden_error(self):
        self.assertTrue(issubclass(GoldenMissingError, FileNotFoundError))
        self.assertTrue(issubclass(GoldenMissingError, GoldenError))
        with self.assertRaises(FileNotFoundError):
            read_golden("still-missing", directory=COMMITTED_DIR)

    def test_default_directory_is_the_scratch_dir(self):
        # The default write/read channel is .runtime/scratch/golden, in-project.
        self.assertEqual(SCRATCH_DIR.name, "golden")
        self.assertEqual(SCRATCH_DIR.parent.name, "scratch")
        self.assertIn(".runtime", SCRATCH_DIR.parts)

    def test_non_object_golden_raises_golden_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(GoldenError):
                read_golden("list", directory=tmp)

    def test_malformed_golden_raises_golden_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "bad.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(GoldenError):
                read_golden("bad", directory=tmp)


class TestRoundTripAndStability(unittest.TestCase):
    def test_write_read_roundtrip_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "a" / "b"
            plan = golden.build_demo_plans()["farming"]
            frozen = freeze(plan)
            path = write_golden("farming", frozen, directory=nested)
            self.assertTrue(path.exists())
            self.assertEqual(read_golden("farming", directory=nested), frozen)

    def test_write_all_writes_both_demo_plans(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = golden.write_all(tmp)
            self.assertEqual(set(written), {"farming", "farming_full"})
            for name in written:
                self.assertTrue((Path(tmp) / f"{name}.json").exists())
                # A write must round-trip back to an identical report.
                report = compare_file(
                    golden.build_demo_plans()[name], name, directory=tmp
                )
                self.assertTrue(report.ok)

    def test_freeze_is_stable(self):
        plan = golden.build_demo_plans()["farming_full"]
        first = freeze(plan)
        second = freeze(plan)
        self.assertEqual(first, second)
        self.assertEqual(dumps(first), dumps(second))
        # Two independent builds of the same config freeze to equal dicts.
        self.assertEqual(
            freeze(build_farming_full(BONUS_CONFIG)),
            freeze(build_farming_full(BONUS_CONFIG)),
        )

    def test_freeze_rejects_non_primitive_const_values(self):
        plan = golden.build_demo_plans()["farming"]
        plan.consts.append(plan.consts[0].__class__(
            alias="harvest", port_index=1, value=object(), slot="string"
        ))
        with self.assertRaises(GoldenError):
            freeze(plan)

    def test_freeze_preserves_nested_dict_and_list_const_values(self):
        plan = golden.build_demo_plans()["farming"]
        payload = {"dict": {"products": [{"id": 7, "prices": [2, 5]}]}}
        plan.consts.append(plan.consts[0].__class__(
            alias="harvest", port_index=99, value=payload, slot="auto"
        ))
        frozen = freeze(plan)["consts"][-1]["value"]
        self.assertEqual(frozen, payload)
        self.assertIsInstance(frozen, dict)
        self.assertIsInstance(frozen["dict"]["products"], list)

    def test_freeze_rejects_non_string_dict_keys(self):
        plan = golden.build_demo_plans()["farming"]
        plan.consts.append(plan.consts[0].__class__(
            alias="harvest", port_index=99, value={"dict": {1: "value"}}, slot="auto"
        ))
        with self.assertRaises(GoldenError):
            freeze(plan)


if __name__ == "__main__":
    unittest.main()
