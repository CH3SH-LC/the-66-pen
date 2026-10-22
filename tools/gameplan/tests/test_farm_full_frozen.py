"""Freeze the default-config farming demo graph as ONE machine-checked artefact.

``tools/gameplan/golden/FARM_FULL.json`` pins the *shape* of the consolidated
six-module demo (``tools/gameplan/demo/farming_full.py``, ``MW_API_FARM_FULL``,
graph kind 20000): the ordered node list, every edge and every const, for the
default config ``FarmFullConfig(currency_id=1115684864, crop_id=1120000001,
food_id=1120000002)`` at ``harvest_bonus=0``.  The demo has been rebuilt several
times and its shape otherwise lives only in prose across several docs; this file
is the single place a reviewer (or a machine) can diff.

What this file checks
---------------------
* **Agreement** — a fresh build of the default config equals the committed
  FARM_FULL.json, node for node and wire for wire.
* **No silent duplicate** — FARM_FULL.json's graph payload is proven equal to the
  sibling snapshot ``tools/gameplan/golden/farming_full.json``.  FARM_FULL.json
  is the same frozen graph *carrying a ``$comment`` docstring*; the two files
  cannot drift apart without this test failing.
* **Alias-exact failure** — when the build drifts, the failure message names the
  EXACT node alias (and definitionIds) that changed, not just "not equal".  A
  negative control proves the message actually discriminates.
* **Canonical bytes** — the file is the canonical :func:`tools.gameplan.golden.dumps`
  serialisation (sorted keys, fixed indent, trailing newline) so a change is a
  clean one-line diff, never key-order noise.
* **Self-describing** — the ``$comment`` states what the file is and what to do
  when it legitimately changes (re-derive and re-commit, with the reason).

Read-only: these tests never touch the bridge, the game or the editor.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.gameplan import golden
from tools.gameplan.demo.farming_full import FarmFullConfig, build_plan
from tools.gameplan.golden import COMMITTED_DIR, compare, dumps, freeze
from tools.gameplan.plan import ConstSpec, NodeSpec

#: The canonical file this test guards.
GOLDEN_PATH = COMMITTED_DIR / "FARM_FULL.json"

#: The sibling per-plan snapshot it must agree with (no divergent duplicate).
SIBLING_PATH = COMMITTED_DIR / "farming_full.json"

#: The default config: exactly the ids :data:`tools.gameplan.golden._DEMO_IDS`
#: carries, so this test and ``golden.build_demo_plans()`` pin the same graph.
DEFAULT_CONFIG = FarmFullConfig(
    currency_id=1115684864, crop_id=1120000001, food_id=1120000002
)

#: The keys :func:`tools.gameplan.golden.freeze` emits for one graph, plus the
#: human-facing ``$comment`` docstring this file adds.
_GRAPH_KEYS = ("name", "graphKind", "nodes", "edges", "consts")
_DOC_KEY = "$comment"


def _default_plan():
    """The default-config ``farming_full`` plan (freshly built, validated)."""
    return build_plan(DEFAULT_CONFIG)


def _raw() -> dict:
    """The committed FARM_FULL.json decoded as plain JSON."""
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _golden() -> dict:
    """The committed FARM_FULL.json through the golden reader."""
    return golden.read_golden("FARM_FULL", directory=COMMITTED_DIR)


def _payload(data: dict) -> dict:
    """Just the frozen graph, without the ``$comment`` docstring."""
    return {k: data[k] for k in _GRAPH_KEYS if k in data}


def _diff_message(report, source: str) -> str:
    """Render a :class:`~tools.gameplan.golden.DiffReport`, naming each node alias.

    Node-level changes carry their ``alias`` structurally; this puts it on the
    front of the line so a reader sees *which node* moved before *how*.
    """
    lines = [f"farming_full drifted from {source}:"]
    for change in report.changes:
        if change.alias is not None:
            lines.append(f"  NODE {change.alias!r}: {change.summary}")
        else:
            lines.append(f"  {change.summary}")
    return "\n".join(lines)


def _assert_matches(plan, data: dict, source: str) -> None:
    """Assert ``plan`` equals the frozen ``data``; fail naming the exact alias."""
    report = compare(plan, data)
    if not report.ok:
        raise AssertionError(_diff_message(report, source))


class TestFARM_FULLFileIsWellFormed(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(GOLDEN_PATH.exists(), f"missing {GOLDEN_PATH}")

    def test_parses_as_an_object_with_the_graph_keys_and_the_doc(self):
        data = _raw()
        self.assertIsInstance(data, dict)
        self.assertEqual(set(data), set(_GRAPH_KEYS) | {_DOC_KEY})
        self.assertIsInstance(data["name"], str)
        self.assertIsInstance(data["graphKind"], int)
        for node in data["nodes"]:
            self.assertEqual(set(node), {"alias", "definitionId", "x", "y"})
        for edge in data["edges"]:
            self.assertEqual(
                set(edge),
                {"from", "to", "fromKind", "fromIndex", "toKind", "toIndex"},
            )
        for const in data["consts"]:
            self.assertEqual(set(const), {"alias", "portIndex", "slot", "value"})

    def test_committed_bytes_are_the_canonical_serialisation(self):
        text = GOLDEN_PATH.read_text(encoding="utf-8")
        self.assertEqual(text, dumps(_raw()))
        self.assertTrue(text.endswith("\n"))
        self.assertTrue(text.startswith("{\n"))  # a pretty-printed object

    def test_keys_are_sorted_at_every_level(self):
        def assert_sorted(obj, where):
            if isinstance(obj, dict):
                self.assertEqual(list(obj), sorted(obj), f"keys unsorted at {where}")
                for key, value in obj.items():
                    assert_sorted(value, f"{where}.{key}")
            elif isinstance(obj, list):
                for i, value in enumerate(obj):
                    assert_sorted(value, f"{where}[{i}]")

        assert_sorted(_raw(), "FARM_FULL")

    def test_doc_comment_explains_purpose_and_change_procedure(self):
        doc = _raw().get(_DOC_KEY)
        self.assertIsInstance(doc, str)
        self.assertGreater(len(doc), 200, "the docstring is too thin to help a reader")
        lowered = doc.lower()
        # What it is for...
        self.assertIn("shape", lowered)
        self.assertIn("machine-checked", lowered)
        # ...and what to do when it legitimately changes.
        self.assertIn("re-derive", lowered)
        self.assertIn("reason", lowered)


class TestFARM_FULLCounts(unittest.TestCase):
    """The counts are facts, so they are derived from the file, not asserted blind."""

    def test_counts_match_the_fresh_build(self):
        data = _raw()
        plan = _default_plan()
        self.assertEqual(
            (len(data["nodes"]), len(data["edges"]), len(data["consts"])),
            (len(plan.nodes), len(plan.edges), len(plan.consts)),
        )

    def test_ordered_node_aliases_match_the_fresh_build(self):
        expected = [n["alias"] for n in _raw()["nodes"]]
        actual = [n.alias for n in _default_plan().nodes]
        self.assertEqual(expected, actual)


class TestFARM_FULLMatchesTheBuild(unittest.TestCase):
    """The guard: a fresh default-config build must equal the committed shape."""

    def test_live_plan_matches_the_committed_golden(self):
        _assert_matches(_default_plan(), _golden(), "tools/gameplan/golden/FARM_FULL.json")

    def test_compare_reports_no_changes(self):
        report = compare(_default_plan(), _golden())
        self.assertTrue(report.ok, _diff_message(report, "FARM_FULL.json"))
        self.assertEqual(report.changes, ())

    def test_payload_is_a_fresh_freeze(self):
        # No silent reformatting: the payload IS freeze(build(default)).
        self.assertEqual(_payload(_raw()), freeze(_default_plan()))

    def test_golden_module_default_config_is_the_same_graph(self):
        # The project's canonical default (golden.build_demo_plans) is this graph.
        self.assertEqual(
            freeze(golden.build_demo_plans()["farming_full"]), freeze(_default_plan())
        )


class TestNoDivergentDuplicate(unittest.TestCase):
    """Reconciled, not duplicated: FARM_FULL.json == the sibling snapshot's payload."""

    def test_sibling_snapshot_exists(self):
        self.assertTrue(SIBLING_PATH.exists(), f"missing {SIBLING_PATH}")

    def test_payload_equals_the_sibling_farming_full_snapshot(self):
        sibling = golden.read_golden("farming_full", directory=COMMITTED_DIR)
        self.assertEqual(
            _payload(_raw()),
            sibling,
            "FARM_FULL.json and farming_full.json describe different graphs — "
            "two snapshots of one graph have silently diverged",
        )

    def test_payload_without_the_doc_is_byte_equal_to_the_sibling_file(self):
        # The only difference between the two committed files is the $comment.
        self.assertEqual(
            dumps(_payload(_raw())),
            SIBLING_PATH.read_text(encoding="utf-8"),
        )

    def test_a_plan_matching_one_snapshot_matches_the_other(self):
        plan = _default_plan()
        self.assertTrue(compare(plan, _golden()).ok)
        self.assertTrue(compare(plan, golden.read_golden("farming_full", directory=COMMITTED_DIR)).ok)


class TestDriftNamesTheExactAlias(unittest.TestCase):
    """Negative control: a mutated plan must fail, naming the exact node alias."""

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

    def _assert_failure_names(self, plan, alias: str) -> str:
        with self.assertRaises(AssertionError) as caught:
            _assert_matches(plan, _golden(), "FARM_FULL.json")
        message = str(caught.exception)
        self.assertIn(alias, message, f"the failure did not name {alias!r}:\n{message}")
        return message

    def test_retyped_node_names_the_alias_and_both_definition_ids(self):
        plan = _default_plan()
        self._replace_node(plan, "gate", definition_id=999)  # 双分支 2 -> 999
        message = self._assert_failure_names(plan, "gate")
        self.assertIn("999", message)
        self.assertIn("2", message)
        change = next(
            c for c in compare(plan, _golden()).changes
            if c.kind == "node_definition_changed"
        )
        self.assertEqual(change.alias, "gate")
        self.assertEqual(change.definition_id, 999)       # the mutated (live) value
        self.assertEqual(change.was_definition_id, 2)      # the committed value

    def test_moved_node_names_the_alias_and_new_position(self):
        plan = _default_plan()
        self._replace_node(plan, "harvest", x=320, y=-64)
        message = self._assert_failure_names(plan, "harvest")
        self.assertIn("320", message)

    def test_removed_node_names_the_alias_and_definition_id(self):
        plan = _default_plan()
        plan.nodes[:] = [n for n in plan.nodes if n.alias != "money_note"]
        message = self._assert_failure_names(plan, "money_note")
        self.assertIn(f"node -money_note", message.replace("'", ""))

    def test_added_node_names_the_alias(self):
        # The real #13 bonus leg adds exactly one node (688) at harvest_bonus>0.
        plan = build_plan(
            FarmFullConfig(
                currency_id=DEFAULT_CONFIG.currency_id,
                crop_id=DEFAULT_CONFIG.crop_id,
                food_id=DEFAULT_CONFIG.food_id,
                harvest_bonus=7,
            )
        )
        message = self._assert_failure_names(plan, "harvest_bonus")
        self.assertIn("688", message)

    def test_retyped_const_is_reported(self):
        plan = _default_plan()
        first = plan.consts[0]
        plan.consts[0] = ConstSpec(
            alias=first.alias, port_index=first.port_index, value=123456789, slot=first.slot
        )
        report = compare(plan, _golden())
        self.assertFalse(report.ok)
        self.assertIn("const_changed", {c.kind for c in report.changes})

    def test_an_identical_plan_is_ok(self):
        self.assertTrue(compare(_default_plan(), _golden()).ok)


if __name__ == "__main__":
    unittest.main()
