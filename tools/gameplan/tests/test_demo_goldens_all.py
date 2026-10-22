"""Golden guard for **every** demo graph under ``tools/gameplan/demo/``.

Why this file exists
--------------------
``tests/test_demo_golden.py`` pins the four modules that expose ``build_plan``
(``farming``, ``farming_full``, ``farming_loop``, ``farming_m4``) into one
aggregate file.  But four more demo modules build a real node graph through a
differently-named entry point — ``plan_of`` (:mod:`~tools.gameplan.demo.farming_all`,
:mod:`~tools.gameplan.demo.farming_autoloop`, :mod:`~tools.gameplan.demo.farming_minimal`,
:mod:`~tools.gameplan.demo.minimal_playable`).  Nothing froze *their* shape, so an
agent could retype a node in the autoloop or the M4/ALL demos and the whole suite
would stay green.  A silently different graph is the worst kind of bug here:
every node and wire is a native call and a wrong graph is expensive to delete.

This file closes that gap with **one committed golden per demo module**, named
after the module stem (``tools/gameplan/golden/<stem>.json``), each frozen at the
module's default config.  It reconciles with the snapshots that already exist
(``farming.json``, ``farming_full.json``, ``farming_loop.json``,
``farming_all.json``) rather than forking copies: for the four graphs the
aggregate ``demo-graphs.json`` also carries, the two payloads are asserted
byte-equal, so they can never drift apart.

Where a golden lives
--------------------
* ``tools/gameplan/golden/<stem>.json`` — the reviewed baseline, exactly
  ``dumps(freeze(plan))`` for a fresh default-config build.
* ``.runtime/scratch/...`` — never used for the checked-in baseline.

These tests only *read* the committed files; they never call the bridge.
"""

from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path
from typing import Callable

from tools.gameplan import golden
from tools.gameplan.golden import (
    COMMITTED_DIR,
    DEMO_GOLDEN_NAME,
    compare,
    dumps,
    freeze,
    read_golden,
)
from tools.gameplan.plan import GraphPlan, NodeSpec

# ---------------------------------------------------------------------------
# The demo directory and the editor-asset ids the default configs use.
# ---------------------------------------------------------------------------

#: ``tools/gameplan/golden.py`` -> ``tools/gameplan/`` -> ``demo/``.
DEMO_DIR = Path(golden.__file__).resolve().parent / "demo"

#: The one canonical set of editor-asset ids the sibling goldens were frozen
#: with (``tools/gameplan/golden.py``, ``_DEMO_IDS``), reused here so every
#: snapshot in this repo is built from the same editor assets.
_DEMO_IDS: dict[str, int] = dict(golden._DEMO_IDS)
_CROP_ID = _DEMO_IDS["crop_id"]

#: The keys :func:`tools.gameplan.golden.freeze` emits for one graph.
_GRAPH_KEYS = {"name", "graphKind", "nodes", "edges", "consts"}
_NODE_KEYS = {"alias", "definitionId", "x", "y"}
_EDGE_KEYS = {"from", "to", "fromKind", "fromIndex", "toKind", "toIndex"}
_CONST_KEYS = {"alias", "portIndex", "slot", "value"}

#: The plan-builder attributes a demo module may expose.  A module that exports
#: *either* is "graph bearing" and must have a golden; the two names exist
#: because several demos deliberately avoid ``build_plan`` so the older
#: aggregate guard (``tests/test_demo_golden.py``) leaves them alone.
_PLAN_BUILDER_ATTRS = ("build_plan", "plan_of")


# ---------------------------------------------------------------------------
# The registry: stem -> a zero-arg builder at that module's DEFAULT config.
#
# Every ``demo/`` module that can produce a GraphPlan appears here exactly once,
# keyed by its module stem (which is also its golden filename).  The lambdas
# pin the *default* configuration: the shared demo ids for the economy demos,
# the dataclass defaults for everything a module leaves optional.
# ---------------------------------------------------------------------------


def _farming() -> GraphPlan:
    from tools.gameplan.demo import farming

    return farming.build_plan(farming.FarmConfig(**_DEMO_IDS))


def _farming_full() -> GraphPlan:
    from tools.gameplan.demo import farming_full

    return farming_full.build_plan(farming_full.FarmFullConfig(**_DEMO_IDS))


def _farming_loop() -> GraphPlan:
    from tools.gameplan.demo import farming_loop

    return farming_loop.build_plan(farming_loop.LoopConfig(**_DEMO_IDS))


def _farming_m4() -> GraphPlan:
    from tools.gameplan.demo import farming_m4

    return farming_m4.build_plan(farming_m4.FarmM4Config())


def _farming_interactive() -> GraphPlan:
    from tools.gameplan.demo import farming_interactive

    return farming_interactive.build_plan(farming_interactive.FarmInteractiveConfig(
        seed_id=1120000003,
        crop_id=_DEMO_IDS["crop_id"],
        currency_id=_DEMO_IDS["currency_id"],
        item_slot="int",
        currency_slot="int",
        variable_flag_slot="bool",
        sale_mode="direct",
    ))


def _farming_all() -> GraphPlan:
    from tools.gameplan.demo import farming_all

    return farming_all.plan_of(farming_all.FarmAllConfig(**_DEMO_IDS))


def _farming_autoloop() -> GraphPlan:
    from tools.gameplan.demo import farming_autoloop

    return farming_autoloop.plan_of(farming_autoloop.AutoLoopConfig(**_DEMO_IDS))


def _farming_minimal() -> GraphPlan:
    from tools.gameplan.demo import farming_minimal

    return farming_minimal.plan_of(farming_minimal.MinimalFarmConfig(crop_id=_CROP_ID))


def _farming_module_probe() -> GraphPlan:
    from tools.gameplan.demo import farming_module_probe

    return farming_module_probe.plan_of(
        farming_module_probe.ProbeConfig(currency_id=_DEMO_IDS["currency_id"], crop_id=_CROP_ID)
    )


def _farming_runnable() -> GraphPlan:
    from tools.gameplan.demo import farming_runnable

    return farming_runnable.plan_of(
        farming_runnable.RunnableConfig(currency_id=_DEMO_IDS["currency_id"], crop_id=_CROP_ID)
    )


def _farming_six() -> GraphPlan:
    from tools.gameplan.demo import farming_six

    return farming_six.plan_of(
        farming_six.SixConfig(currency_id=_DEMO_IDS["currency_id"], crop_id=_CROP_ID)
    )


def _minimal_playable() -> GraphPlan:
    from tools.gameplan.demo import minimal_playable

    return minimal_playable.plan_of(minimal_playable.MinimalConfig(crop_id=_CROP_ID))


#: ``stem -> builder()`` for **every** graph-bearing demo module, in stable
#: (alphabetical) order so any aggregate produced from it is byte-stable.
DEFAULT_PLANS: dict[str, Callable[[], GraphPlan]] = {
    "farming": _farming,
    "farming_all": _farming_all,
    "farming_autoloop": _farming_autoloop,
    "farming_full": _farming_full,
    "farming_loop": _farming_loop,
    "farming_m4": _farming_m4,
    "farming_interactive": _farming_interactive,
    "farming_minimal": _farming_minimal,
    "farming_module_probe": _farming_module_probe,
    "farming_runnable": _farming_runnable,
    "farming_six": _farming_six,
    "minimal_playable": _minimal_playable,
}

#: ``demo/`` modules that are deliberately **not** graph demos, each with the
#: reason it is exempt.  A module named here must genuinely expose no plan
#: builder; the test asserts that, so this table cannot silently smother a new
#: graph (give it a builder and the exemption fails).
NON_GRAPH_MODULES: dict[str, str] = {
    "layout_field": (
        "placement-plan document module: it emits a 3x3 field placement "
        "(tools/gameplan/demo/field-grid-3x3.json) via field_plan()/demo_plan(), "
        "not a node-graph GraphPlan; it exposes neither build_plan nor plan_of"
    ),
    "run_demo": (
        "demo RUNNER, not a graph builder: it emits the ordered argv of the whole "
        "#7 pipeline (create-batch -> build-plan -> inspect -> bind -> export -> "
        "save -> verify -> component-read) and dispatches nothing by itself. It "
        "imports farming_full's builder under the alias build_full_plan, so it "
        "exposes neither build_plan nor plan_of of its own"
    ),
}


def build_default_plans() -> dict[str, GraphPlan]:
    """Build every demo plan at its default config, keyed by module stem."""
    return {name: builder() for name, builder in DEFAULT_PLANS.items()}


def write_all_goldens(directory: Path | str | None = None) -> dict[str, Path]:
    """(Re)generate every per-stem golden.  Defaults to the committed directory.

    Run this after a *reviewed* shape change: the resulting diff to
    ``tools/gameplan/golden/<stem>.json`` is the visible change, not a silent
    rebuild.  Pass ``directory=golden.SCRATCH_DIR`` to preview without touching
    the baselines.
    """
    target = COMMITTED_DIR if directory is None else Path(directory)
    return {
        name: golden.write_golden(name, freeze(plan), directory=target)
        for name, plan in build_default_plans().items()
    }


def _has_plan_builder(module) -> bool:
    """True when ``module`` exports a callable ``build_plan`` or ``plan_of``."""
    return any(callable(getattr(module, attr, None)) for attr in _PLAN_BUILDER_ATTRS)


def _all_demo_module_stems() -> set[str]:
    """Every importable module stem under ``demo/`` (``__init__`` excluded)."""
    return {
        path.stem
        for path in sorted(DEMO_DIR.glob("*.py"))
        if not path.stem.startswith("_")
    }


def _graph_bearing_modules() -> set[str]:
    """Every ``demo/`` module that defines ``build_plan`` or ``plan_of``."""
    found: set[str] = set()
    for stem in _all_demo_module_stems():
        module = importlib.import_module(f"tools.gameplan.demo.{stem}")
        if _has_plan_builder(module):
            found.add(stem)
    return found


def _golden_path(name: str) -> Path:
    return COMMITTED_DIR / f"{name}.json"


def _drift_message(name: str, report) -> str:
    """A failure message naming the exact alias(es) that changed."""
    aliases = sorted({change.alias for change in report.changes if change.alias})
    return (
        f"demo graph {name!r} drifted from tools/gameplan/golden/{name}.json "
        f"(changed aliases: {aliases}); rebuild and, if the change is intended, "
        f"run write_all_goldens() to re-freeze.\n{report}"
    )


class TestDiscoveryCoversEveryDemoModule(unittest.TestCase):
    """The guard that makes "EVERY demo graph" true, not aspirational."""

    def test_registry_matches_the_graph_bearing_modules(self):
        discovered = _graph_bearing_modules()
        self.assertEqual(
            discovered,
            set(DEFAULT_PLANS),
            f"graph-bearing demo modules {sorted(discovered)} != registry "
            f"{sorted(DEFAULT_PLANS)}; a demo graph was added without a golden, "
            f"or a registry entry names no module",
        )

    def test_every_demo_module_is_either_graphed_or_explicitly_exempt(self):
        accounted = set(DEFAULT_PLANS) | set(NON_GRAPH_MODULES)
        unaccounted = _all_demo_module_stems() - accounted
        self.assertEqual(
            unaccounted,
            set(),
            f"demo module(s) {sorted(unaccounted)} have no golden and no exemption; "
            f"freeze them (add to DEFAULT_PLANS) or document why they are not graphs",
        )

    def test_exempt_modules_really_expose_no_plan_builder(self):
        for stem, reason in NON_GRAPH_MODULES.items():
            with self.subTest(module=stem):
                module = importlib.import_module(f"tools.gameplan.demo.{stem}")
                self.assertFalse(
                    _has_plan_builder(module),
                    f"{stem} is exempt as '{reason}' but now exposes a plan "
                    f"builder — freeze it instead of exempting it",
                )

    def test_registry_is_not_empty_and_names_real_modules(self):
        self.assertTrue(DEFAULT_PLANS)
        for stem in DEFAULT_PLANS:
            with self.subTest(module=stem):
                self.assertIn(stem, _all_demo_module_stems())


class TestEveryDemoGraphHasAGoldenFile(unittest.TestCase):
    """A new demo module without a golden fails here."""

    def test_every_registry_name_has_a_committed_file(self):
        for name in sorted(DEFAULT_PLANS):
            with self.subTest(golden=name):
                path = _golden_path(name)
                self.assertTrue(path.exists(), f"missing golden file {path}")

    def test_every_golden_file_is_a_json_object_with_the_frozen_keys(self):
        for name in sorted(DEFAULT_PLANS):
            with self.subTest(golden=name):
                data = json.loads(_golden_path(name).read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)
                self.assertEqual(set(data), _GRAPH_KEYS)
                self.assertIsInstance(data["name"], str)
                self.assertIsInstance(data["graphKind"], int)
                for node in data["nodes"]:
                    self.assertEqual(set(node), _NODE_KEYS)
                for edge in data["edges"]:
                    self.assertEqual(set(edge), _EDGE_KEYS)
                for const in data["consts"]:
                    self.assertEqual(set(const), _CONST_KEYS)

    def test_every_golden_file_is_the_canonical_fresh_build(self):
        # Byte-exact: a real shape change is a clean diff, never key-order noise.
        for name, plan in build_default_plans().items():
            with self.subTest(golden=name):
                text = _golden_path(name).read_text(encoding="utf-8")
                self.assertEqual(
                    text,
                    dumps(freeze(plan)),
                    f"tools/gameplan/golden/{name}.json is not the canonical build; "
                    f"regenerate with write_all_goldens()",
                )
                self.assertTrue(text.endswith("\n"))


class TestEveryDemoGraphMatchesItsGolden(unittest.TestCase):
    """The one test that rebuilds every demo graph and diffs it against its golden."""

    def test_every_live_plan_matches_the_committed_golden(self):
        for name, plan in build_default_plans().items():
            with self.subTest(plan=name):
                self.assertIsInstance(plan, GraphPlan)
                plan.validate()
                report = compare(plan, read_golden(name, directory=COMMITTED_DIR))
                self.assertTrue(report.ok, _drift_message(name, report))
                self.assertEqual(report.changes, ())

    def test_a_fresh_build_is_ok_when_compared_to_itself(self):
        for name, plan in build_default_plans().items():
            with self.subTest(plan=name):
                self.assertTrue(compare(plan, freeze(plan)))


class TestReconciledWithTheExistingAggregate(unittest.TestCase):
    """No silent duplicate: shared graphs agree with the aggregate snapshot."""

    def _aggregate_graphs(self) -> dict:
        return read_golden(DEMO_GOLDEN_NAME, directory=COMMITTED_DIR)["graphs"]

    def test_every_aggregate_graph_has_a_matching_per_stem_golden(self):
        aggregate = self._aggregate_graphs()
        self.assertTrue(aggregate, "the aggregate snapshot is empty")
        for name, frozen in aggregate.items():
            with self.subTest(golden=name):
                self.assertIn(
                    name,
                    DEFAULT_PLANS,
                    f"aggregate graph {name!r} has no per-stem golden in this registry",
                )
                self.assertEqual(
                    read_golden(name, directory=COMMITTED_DIR),
                    frozen,
                    f"tools/gameplan/golden/{name}.json and "
                    f"{DEMO_GOLDEN_NAME}.json describe different graphs — the "
                    f"snapshots have drifted apart",
                )


class TestMutationIsReportedWithTheNodeAlias(unittest.TestCase):
    """The negative control: a mutated graph names the alias that changed."""

    @staticmethod
    def _replace_node(plan: GraphPlan, alias: str, *, definition_id=None, x=None, y=None) -> None:
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

    def test_retyped_autoloop_node_reports_alias_and_both_ids(self):
        plan = build_default_plans()["farming_autoloop"]
        self._replace_node(plan, "tick", definition_id=999)
        report = compare(plan, read_golden("farming_autoloop", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_definition_changed")
        self.assertEqual(change.alias, "tick")
        self.assertEqual(change.definition_id, 999)   # the mutated (live) value
        self.assertEqual(change.was_definition_id, 83)  # the committed value (83 定时器触发时)
        self.assertIn("tick", _drift_message("farming_autoloop", report))

    def test_moved_minimal_node_reports_the_exact_alias(self):
        plan = build_default_plans()["farming_minimal"]
        self._replace_node(plan, "harvest", x=9999, y=-64)
        report = compare(plan, read_golden("farming_minimal", directory=COMMITTED_DIR))
        self.assertFalse(report.ok)
        change = next(c for c in report.changes if c.kind == "node_position_changed")
        self.assertEqual(change.alias, "harvest")
        self.assertIn("9999", str(change))

    def test_removed_minimal_playable_node_reports_alias_and_definition_id(self):
        plan = build_default_plans()["minimal_playable"]
        plan.nodes[:] = [n for n in plan.nodes if n.alias != "regrow"]
        report = compare(plan, read_golden("minimal_playable", directory=COMMITTED_DIR))
        change = next(c for c in report.changes if c.kind == "node_removed")
        self.assertEqual(change.alias, "regrow")
        self.assertEqual(change.definition_id, 686)

    def test_an_untouched_sibling_graph_is_unaffected(self):
        plan = build_default_plans()["farming_autoloop"]
        self._replace_node(plan, "tick", definition_id=999)
        other = build_default_plans()["farming_m4"]
        self.assertFalse(
            compare(plan, read_golden("farming_autoloop", directory=COMMITTED_DIR)).ok
        )
        self.assertTrue(
            compare(other, read_golden("farming_m4", directory=COMMITTED_DIR)).ok
        )


if __name__ == "__main__":  # pragma: no cover - manual regeneration entry point
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--write":
        for path in write_all_goldens().values():
            print(f"wrote {path}")
    else:
        unittest.main()
