"""Offline tests for the entry→exit module **blocks** (``tools/gameplan/blocks.py``).

Every module function in ``tools/gameplan/modules/`` is a *fragment*: it takes a
caller-supplied execution source, so on its own it cannot be entered.  ``blocks``
turns each into a self-contained ``入口 → … → 出口`` block and refuses, with a
named error, where an obstacle is real.  These tests lock in the four claims a
block asserts:

1. it starts at a real **entry** (a contract with an execution output and no
   execution input);
2. it ends at a real **exit** (an execution tip), and at least one exit is a
   ``打印字符串`` (defId ``1``) — the only observable the project has;
3. every defId it places is in ``data/node-contracts``;
4. each blocked path raises its **named** refusal, and the refusal carries the
   partial graph it reached.

Nothing here talks to the bridge, the game, the editor or a save.

Run::

    python -B -m unittest tools.gameplan.tests.test_module_blocks
"""

import inspect
import unittest

from tools.gameplan import blocks as B
from tools.gameplan.contracts import default_store
from tools.gameplan.nodes import ON_CREATE, PRINT
from tools.gameplan import nodes as N
from tools.gameplan import Graph
from tools.gameplan.modules import shop as m5

_COMPLETE_STATUS = "COMPLETE"


def _attempts():
    return [B.attempt(b) for b in B.MODULE_BLOCKS]


def _complete_blocks():
    return [b for b in B.MODULE_BLOCKS if B.attempt(b).status == _COMPLETE_STATUS]


def _module_surface() -> dict[str, set[str]]:
    """Every public function **defined in** each gameplay module, by short name.

    Enumerated with :func:`inspect.getmembers` over the live module objects -- NOT
    a hand-typed list.  A hand-typed ``expected`` set is exactly what let two
    module functions (``shop.on_shop_bought`` / ``shop.on_sold_bag_item``) go
    silently uncovered in wave 29AM; the fix must never reintroduce one.

    ``obj.__module__`` is compared to the module's own ``__name__`` so a
    re-exported / imported name is not counted as part of that module's surface.
    """
    from tools.gameplan import modules as _modules
    surface: dict[str, set[str]] = {}
    for mod in (_modules.interaction, _modules.currency, _modules.item,
                _modules.inventory, _modules.shop):
        short = mod.__name__.rsplit(".", 1)[-1]
        surface[short] = {
            name for name, obj in inspect.getmembers(mod, inspect.isfunction)
            if not name.startswith("_") and obj.__module__ == mod.__name__
        }
    return surface


def _surface_names() -> set[str]:
    """``<module>.<function>`` for every public module function (mechanical)."""
    return {f"{m}.{n}" for m, names in _module_surface().items() for n in names}


def _covered_names() -> set[str]:
    """``<module>.<function>`` names the block registry claims to make real."""
    return {f for b in B.MODULE_BLOCKS for f in b.functions_made_real}


class EveryBlockIsAnEntryToExitBlock(unittest.TestCase):
    def test_at_least_one_block_is_complete(self):
        """Guard against a vacuous suite: some block must actually build."""
        self.assertTrue(_complete_blocks(), "no block builds — the suite is vacuous")

    def test_complete_blocks_validate_and_are_well_formed(self):
        for block in _complete_blocks():
            with self.subTest(block=block.function):
                graph = block.build()
                graph.validate()  # raises PlanError on a bad pin/edge/const
                shape = B.block_shape(graph.plan)
                self.assertTrue(shape.well_formed, f"{block.function}: {shape}")
                self.assertEqual(len(shape.entry), 1)
                self.assertTrue(shape.exits)
                self.assertTrue(shape.print_exits)
                self.assertEqual(shape.unreachable, ())

    def test_the_entry_is_a_real_event(self):
        # The entry defId must be an event: an execution output, no execution input.
        store = default_store()
        for block in _complete_blocks():
            with self.subTest(block=block.function):
                graph = block.build()
                entry = B.block_shape(graph.plan).entry[0]
                def_id = graph.plan.aliases()[entry].definition_id
                definition = store.require(def_id)
                self.assertTrue(definition.exec_outputs, f"{def_id} has no exec output")
                self.assertFalse(definition.exec_inputs, f"{def_id} has an exec input")

    def test_every_exit_print_is_a_print_node(self):
        for block in _complete_blocks():
            with self.subTest(block=block.function):
                graph = block.build()
                aliases = graph.plan.aliases()
                for alias in B.block_shape(graph.plan).print_exits:
                    self.assertEqual(aliases[alias].definition_id, PRINT.definition_id)


class EveryNodeIdIsInTheContractStore(unittest.TestCase):
    def test_placed_definition_ids_are_all_contract_backed(self):
        store = default_store()
        seen: set[int] = set()
        for block in _complete_blocks():
            graph = block.build()
            for node in graph.plan.nodes:
                seen.add(node.definition_id)
                self.assertIsNotNone(
                    store.get(node.definition_id),
                    f"{block.function}: defId {node.definition_id} is not in the store",
                )
        self.assertTrue(seen, "no definitionId was checked — the walk is empty")

    def test_the_store_lookup_is_not_vacuous(self):
        # A negative control: an id that is not in the store must NOT pass the check.
        store = default_store()
        self.assertIsNone(store.get(4294967290))

    def test_dict_accessor_is_declared_and_matches_its_contract(self):
        # 1158 is the accessor a *block* can opt into; its roles must be contract-true.
        store = default_store()
        definition = store.get(N.DICT_LOOKUP.definition_id)
        self.assertIsNotNone(definition, "1158 以键查询字典值 is missing from the store")
        self.assertEqual(definition.name, "以键查询字典值")
        self.assertEqual(N.DICT_LOOKUP.ins, {"dict": 0, "key": 1})
        self.assertEqual(N.DICT_LOOKUP.outs, {"value": 0})
        # The whole point of the refusal: its pins are generic, not concrete.
        for port in definition.ports:
            self.assertEqual(port.server_param_type, 0, f"1158 {port.key} is not generic")


class NamedRefusalsFireOnTheBlockedPaths(unittest.TestCase):
    def test_dict_queries_refuse_with_dict_access_unproven(self):
        for builder in (B.inventory_all_items_block, B.inventory_all_currencies_block):
            with self.subTest(builder=builder.__name__):
                with self.assertRaises(B.DictAccessUnproven) as ctx:
                    builder()
                self.assertEqual(ctx.exception.code, "DICT_ACCESS_UNPROVEN")
                # The partial block (entry + the query node) is carried along.
                self.assertIsNotNone(ctx.exception.graph)
                self.assertIn(ON_CREATE.definition_id, ctx.exception.nodes)

    def test_shop_queries_refuse_with_aggregate_unreadable(self):
        cases = (("bag", 715, 22), ("custom", 714, 8))
        for kind, node_id, out_type in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(B.ShopAggregateUnreadable) as ctx:
                    B.shop_query_block(kind)
                self.assertEqual(ctx.exception.code, "SHOP_AGGREGATE_UNREADABLE")
                self.assertEqual(ctx.exception.node_id, node_id)
                self.assertEqual(ctx.exception.server_param_type, out_type)

    def test_terrain_refuses_with_no_node_block(self):
        with self.assertRaises(B.TerrainHasNoNodeBlock) as ctx:
            B.terrain_block()
        self.assertEqual(ctx.exception.code, "TERRAIN_HAS_NO_NODE_BLOCK")

    def test_custom_store_requires_row_and_price_but_accepts_typed_dictionary(self):
        with self.assertRaises(ValueError):
            B.shop_list_item_block(store=m5.STORE_CUSTOM)
        with self.assertRaises(ValueError):
            B.shop_list_item_block(price=99)
        graph = B.shop_list_item_block(store=m5.STORE_CUSTOM, item_index=0,
                                      price={B.CURRENCY_ID: 5})
        graph.validate()
        price = next(c for c in graph.plan.consts if c.alias == "list" and c.port_index == 4)
        self.assertEqual(price.value, {"dict": [{"key": {"uint": B.CURRENCY_ID},
                                                "value": {"int": 5}}]})

    def test_trade_event_blocks_never_settle_the_engine_transaction_twice(self):
        for build in (B.shop_sold_event_block, B.shop_bought_event_block):
            graph = build()
            self.assertNotIn(688, [n.definition_id for n in graph.plan.nodes])
            self.assertTrue(B.block_shape(graph.plan).well_formed)

    def test_the_refusal_is_a_same_run_positive_control(self):
        """The refusal search is not vacuous: the unblocked path does NOT fire it."""
        graph = B.inventory_all_items_block(assume_generic_accessor=True)
        graph.validate()  # must not raise the refusal it raises without the opt-in

    def test_every_refusal_class_appears_in_the_registry_and_has_a_location(self):
        for block in B.MODULE_BLOCKS:
            if block.refusal is not None:
                with self.subTest(block=block.function):
                    location = B.refusal_location(block.refusal)
                    self.assertRegex(location, r".+\.py:\d+$")


class TheAssumedAccessorPathIsOptInAndMarked(unittest.TestCase):
    def test_opt_in_builds_and_places_the_generic_accessor(self):
        graph = B.inventory_all_items_block(assume_generic_accessor=True)
        graph.validate()
        self.assertTrue(B.block_shape(graph.plan).well_formed)
        ids = [n.definition_id for n in graph.plan.nodes]
        self.assertIn(N.DICT_LOOKUP.definition_id, ids)  # 1158, the ASSUMED hop
        self.assertIn(721, ids)

    def test_default_refuses_rather_than_assuming(self):
        with self.assertRaises(B.DictAccessUnproven):
            B.inventory_all_items_block()


class TheShapeDetectorIsNotVacuous(unittest.TestCase):
    def test_a_lone_entry_has_no_exit(self):
        g = Graph("MW_API_BLK_VACUITY")
        g.place(ON_CREATE, "on_create")
        shape = B.block_shape(g.plan)
        self.assertEqual(len(shape.entry), 1)
        self.assertEqual(shape.exits, ())
        self.assertFalse(shape.well_formed)

    def test_a_non_print_tip_is_not_a_print_exit(self):
        # entry -> 685 (增加背包最大容量), its `then` left unwired: an exit, but not
        # a print, so the block is not well-formed.
        g = Graph("MW_API_BLK_NONPRINT")
        create = g.place(ON_CREATE, "on_create")
        node = g.place(N.ADD_BAG_CAPACITY, "grow")
        create.flow_to(node)
        node.data_from(create, "entity", "holder")
        node.const("delta", 1, "int")
        shape = B.block_shape(g.plan)
        self.assertEqual(shape.exits, ("grow",))
        self.assertEqual(shape.print_exits, ())
        self.assertFalse(shape.well_formed)

    def test_a_dead_module_leg_is_not_well_formed(self):
        # entry.then -> print  AND  entry.then -> module-node (its exec-out left
        # unwired).  The module leg is dead, so the print proves only that the
        # *entry* fired, not that the module node ran.  Ledger counterexample (a):
        # this used to judge well_formed=True because the rule wanted only *one*
        # print exit, not that *every* exit is a print.
        g = Graph("MW_API_BLK_DEADLEG")
        create = g.place(ON_CREATE, "on_create")
        p = g.place(PRINT, "exit")
        create.flow_to(p)
        p.const("text", "x", "string")
        node = g.place(N.ADD_BAG_ITEM, "grant")  # 686: exec-in + exec-out
        create.flow_to(node)
        node.data_from(create, "entity", "holder")
        node.const("item", 1, "int")
        node.const("delta", 1, "int")
        shape = B.block_shape(g.plan)
        self.assertIn("grant", shape.exits)          # the dead leg IS a tip...
        self.assertNotIn("grant", shape.print_exits)  # ...but not a print
        self.assertFalse(shape.well_formed)

    def test_two_entries_are_not_a_single_entry_block(self):
        g = Graph("MW_API_BLK_TWOENTRY")
        a = g.place(ON_CREATE, "on_create")
        b = g.place(N.PROXIMITY_ENTER, "enter")
        for src in (a, b):
            node = g.place(PRINT, f"exit_{src.alias}")
            src.flow_to(node)
            node.const("text", "x", "string")
        shape = B.block_shape(g.plan)
        self.assertEqual(len(shape.entry), 2)
        self.assertFalse(shape.well_formed)


class TheUnwiredInputReporterNamesTheGap(unittest.TestCase):
    """Ledger gap (c): a COMPLETE block may leave a concrete input unwired.

    This cannot be made fail-closed without a ``required`` predicate the contract
    does not carry (every port's ``required`` is ``unknown``) and without
    flipping three currently-COMPLETE blocks whose comparison-``op`` pins are
    left deliberately unwritten.  So the gap is *reported*, not guessed at.
    """

    def test_the_type27_shop_price_is_reported_unwired(self):
        # 709 3:3 出售货币字典 (spt 27) is left unwired by the bag-listing block.
        rows = B.unwired_concrete_inputs(B.shop_list_item_block().plan)
        self.assertTrue(rows, "the reporter found nothing — it is vacuous")
        self.assertTrue(any("spt27" in r for r in rows), rows)

    def test_a_fully_wired_block_reports_nothing(self):
        # Positive control on the same instrument: 688's holder/currency/delta
        # are all fed, so a clean block reports an empty tuple.
        self.assertEqual(B.unwired_concrete_inputs(B.currency_grant_block().plan), ())

    def test_the_table_surfaces_the_gap_per_module(self):
        table = {row["module"]: row for row in B.completion_table()}
        self.assertTrue(table["M5-shop"]["unwiredConcreteInputs"])
        self.assertTrue(
            any("spt27" in u for u in table["M5-shop"]["unwiredConcreteInputs"])
        )


class TheCompletionTableIsDerived(unittest.TestCase):
    def test_verdicts(self):
        table = {row["module"]: row for row in B.completion_table()}
        self.assertEqual(table["M1-interaction"]["verdict"], "COMPLETE")
        self.assertEqual(table["M2-currency"]["verdict"], "COMPLETE")
        self.assertEqual(table["M3-item"]["verdict"], "COMPLETE")
        self.assertEqual(table["M4-inventory"]["verdict"], "PARTIAL")
        self.assertEqual(table["M5-shop"]["verdict"], "PARTIAL")
        self.assertEqual(table["M6-level-terrain"]["verdict"], "BLOCKED")

    def test_no_module_is_unaccounted_for(self):
        modules = {b.module for b in B.MODULE_BLOCKS}
        self.assertEqual(modules, set(B.MODULE_ORDER))
        table = B.completion_table()
        self.assertEqual([row["module"] for row in table], list(B.MODULE_ORDER))

    def test_the_table_has_both_outcomes(self):
        verdicts = {row["verdict"] for row in B.completion_table()}
        self.assertTrue({"COMPLETE", "PARTIAL", "BLOCKED"} <= verdicts)

    def test_module_functions_covered(self):
        """Kept for compatibility: the real check moved to the derived class below.

        This used to assert a hand-typed 30-name ``expected`` set.  That list was
        the defect: it omitted ``shop.on_shop_bought`` / ``shop.on_sold_bag_item``,
        so both fragments were silently uncovered while the suite stayed green.
        The surface guard now lives in
        :class:`EveryModuleFunctionIsCoveredOrNamedImpossible`.
        """
        self.assertEqual(_surface_names() - _covered_names(), set(),
                         "module functions with no block and no stated impossibility")


class EveryModuleFunctionIsCoveredOrNamedImpossible(unittest.TestCase):
    """The coverage guard is **derived from the live module surface**, not typed.

    Wave 29AM's guard asserted a hand-typed 30-name set and stayed green while two
    real module functions went uncovered.  Every assertion here is computed from
    ``inspect.getmembers`` over ``tools/gameplan/modules/*`` and the block registry,
    so adding a module function with no block fails the suite automatically.
    """

    def test_the_enumerated_surface_is_non_empty_and_plausible(self):
        # Positive control: the instrument (inspect.getmembers) DOES see functions.
        surface = _surface_names()
        self.assertGreaterEqual(len(surface), 25, f"surface enumeration broke: {surface}")
        for expected in ("interaction.event", "currency.grant", "item.grant",
                         "inventory.grow", "shop.open_", "shop.on_shop_bought",
                         "shop.on_sold_bag_item"):
            self.assertIn(expected, surface, f"{expected} missing from the live surface")

    def test_no_module_function_is_silently_uncovered(self):
        uncovered = _surface_names() - _covered_names()
        self.assertEqual(
            uncovered, set(),
            "module functions with no block and no stated impossibility",
        )

    def test_no_covered_name_is_a_phantom_module_function(self):
        # The reverse direction: a ``functions_made_real`` entry that names no real
        # module function (e.g. a block-local helper) inflates coverage and must fail.
        phantom = _covered_names() - _surface_names()
        self.assertEqual(
            phantom, set(),
            "functions_made_real names that are not module functions",
        )

    def test_the_guard_fails_when_a_coverage_name_is_removed(self):
        # A live mutation: dropping one covered name must make the derived check red.
        covered = _covered_names()
        dropped = covered - {"shop.on_shop_bought"}
        self.assertNotEqual(
            _surface_names() - dropped, set(),
            "removing a covered name did not surface an uncovered function",
        )


class TheBlockRegistryIsConsistent(unittest.TestCase):
    def test_function_keys_are_unique(self):
        keys = [b.function for b in B.MODULE_BLOCKS]
        self.assertEqual(len(keys), len(set(keys)), "duplicate block function key")

    def test_every_block_attempt_terminates_in_a_known_status(self):
        for attempt in _attempts():
            with self.subTest(block=attempt.function):
                self.assertIn(attempt.status, {"COMPLETE", "REFUSED", "MALFORMED", "ERROR"})

    def test_graph_names_match_the_adapter_regex(self):
        from tools.gameplan.plan import GRAPH_NAME_RE
        for block in _complete_blocks():
            with self.subTest(block=block.function):
                self.assertRegex(block.build().name, GRAPH_NAME_RE)


if __name__ == "__main__":
    unittest.main()
