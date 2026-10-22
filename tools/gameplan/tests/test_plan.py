"""Offline tests for the gameplan graph-plan layer.  No bridge, no game."""

import unittest

from tools.gameplan.nodes import ALL_NODE_TYPES
from tools.gameplan.contracts import (
    DATA_INPUT,
    DATA_OUTPUT,
    EXEC_INPUT,
    EXEC_OUTPUT,
    default_store,
)
from tools.gameplan.plan import GraphPlan, PlanError
from tools.gameplan import Graph
from tools.gameplan import nodes as N


class TestContractStore(unittest.TestCase):
    def test_store_loads_server_definitions(self):
        store = default_store()
        self.assertGreater(len(store), 400)
        # The three ids the 2026-10-09 session proved addable, plus the two
        # long-proven ones.
        for did in (1, 2, 71, 688, 691):
            with self.subTest(definition_id=did):
                self.assertIn(did, store)

    def test_known_definitions_have_expected_names(self):
        store = default_store()
        self.assertEqual(store.require(1).name, "打印字符串")
        self.assertEqual(store.require(71).name, "实体创建时")
        self.assertEqual(store.require(688).name, "增加背包货币数量")
        self.assertEqual(store.require(691).name, "获取背包货币数量")

    def test_every_definition_is_the_server_kind(self):
        store = default_store()
        kinds = {store.require(d).graph_kind for d in store}
        self.assertEqual(kinds, {20000})


class TestNodeTypesMatchContracts(unittest.TestCase):
    """The role table in nodes.py must agree with data/node-contracts exactly."""

    def test_every_node_type_definition_exists(self):
        store = default_store()
        for nt in ALL_NODE_TYPES:
            with self.subTest(node=nt.label):
                self.assertIsNotNone(
                    store.get(nt.definition_id),
                    f"{nt.label} ({nt.definition_id}) is not in the contract store",
                )

    def test_declared_roles_match_contract_ports_exactly(self):
        store = default_store()
        for nt in ALL_NODE_TYPES:
            definition = store.require(nt.definition_id)
            with self.subTest(node=nt.label):
                # Execution input.
                declared_exec_in = nt.exec_in
                contract_exec_in = sorted(p.index for p in definition.exec_inputs)
                if declared_exec_in is None:
                    self.assertEqual(
                        contract_exec_in, [],
                        f"{nt.label}: contract has exec inputs {contract_exec_in} "
                        f"but none are declared",
                    )
                else:
                    self.assertEqual(contract_exec_in, [declared_exec_in])

                # Execution outputs.
                self.assertEqual(
                    sorted(nt.exec_outs.values()),
                    sorted(p.index for p in definition.exec_outputs),
                    f"{nt.label}: exec-output roles disagree with the contract",
                )
                for index in nt.exec_outs.values():
                    self.assertIsNotNone(
                        definition.port(EXEC_OUTPUT, index),
                        f"{nt.label}: no execution output pin {index}",
                    )

                # Data inputs / outputs: every contract pin must be named once.
                self.assertEqual(
                    sorted(nt.ins.values()),
                    sorted(p.index for p in definition.ports if p.kind == DATA_INPUT),
                    f"{nt.label}: data-input roles disagree with the contract",
                )
                self.assertEqual(
                    sorted(nt.outs.values()),
                    sorted(p.index for p in definition.ports if p.kind == DATA_OUTPUT),
                    f"{nt.label}: data-output roles disagree with the contract",
                )
                # Role indices must be unique within a group.
                self.assertEqual(len(set(nt.ins.values())), len(nt.ins))
                self.assertEqual(len(set(nt.outs.values())), len(nt.outs))
                self.assertEqual(len(set(nt.exec_outs.values())), len(nt.exec_outs))

    def test_definition_ids_are_unique_in_the_table(self):
        ids = [nt.definition_id for nt in ALL_NODE_TYPES]
        self.assertEqual(len(ids), len(set(ids)), "duplicate definitionId in table")


class TestPlanValidation(unittest.TestCase):
    def _valid(self) -> GraphPlan:
        g = Graph("MW_API_test_plan")
        on_create = g.place(N.ON_CREATE, "on_create")
        add = g.place(N.ADD_BAG_CURRENCY, "add_coin")
        on_create.flow_to(add)
        add.data_from(on_create, "entity", "holder")
        add.const("delta", 10, "int")
        return g.plan

    def test_valid_plan_passes(self):
        self._valid().validate()

    def test_bad_name_rejected(self):
        plan = self._valid()
        plan.name = "not_a_mw_name"
        with self.assertRaises(PlanError) as ctx:
            plan.validate()
        self.assertTrue(any("graph name" in p for p in ctx.exception.problems))

    def test_duplicate_alias_rejected(self):
        plan = self._valid()
        plan.nodes.append(plan.nodes[0])
        with self.assertRaises(PlanError) as ctx:
            plan.validate()
        self.assertTrue(any("duplicate node alias" in p for p in ctx.exception.problems))

    def test_unknown_definition_rejected(self):
        plan = self._valid()
        plan.nodes[0].__dict__  # frozen; rebuild instead
        plan2 = GraphPlan(name="MW_API_test_x")
        plan2.add("ghost", 4294967290)
        with self.assertRaises(PlanError) as ctx:
            plan2.validate()
        self.assertTrue(any("not in the server contract store" in p for p in ctx.exception.problems))

    def test_wrong_direction_pair_rejected(self):
        plan = self._valid()
        plan.edges = [plan.edges[0].__class__(plan.edges[0].src, 4, 0, plan.edges[0].dst, 3, 0)]
        plan.edges[0] = plan.edges[0].__class__("on_create", 3, 0, "add_coin", 1, 0)
        with self.assertRaises(PlanError) as ctx:
            plan.validate()
        self.assertTrue(any("kind pair" in p for p in ctx.exception.problems))

    def test_bad_exec_index_rejected(self):
        g = Graph("MW_API_test_badidx")
        a = g.place(N.ON_CREATE, "a")
        b = g.place(N.BRANCH, "b")
        g.plan.wire("a", EXEC_OUTPUT, 2, "b", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as ctx:
            g.plan.validate()
        self.assertTrue(any("is not 0 or 1" in p for p in ctx.exception.problems))

    def test_self_link_rejected(self):
        g = Graph("MW_API_test_self")
        a = g.place(N.BRANCH, "a")
        g.plan.wire("a", EXEC_OUTPUT, 0, "a", EXEC_INPUT, 0)
        with self.assertRaises(PlanError) as ctx:
            g.plan.validate()
        self.assertTrue(any("links a node to itself" in p for p in ctx.exception.problems))

    def test_data_type_mismatch_rejected(self):
        # 71.entity is an entity (type 1); 688.delta is an int (type 3).
        g = Graph("MW_API_test_mismatch")
        a = g.place(N.ON_CREATE, "a")
        b = g.place(N.ADD_BAG_CURRENCY, "b")
        g.plan.wire("a", DATA_OUTPUT, 0, "b", DATA_INPUT, 2)
        with self.assertRaises(PlanError) as ctx:
            g.plan.validate()
        self.assertTrue(any("data type mismatch" in p for p in ctx.exception.problems))

    def test_generic_end_skips_type_check(self):
        # A generic target pin (type 0) accepts a concrete source.
        g = Graph("MW_API_test_generic")
        tick = g.place(N.TIMER_TICK, "tick")
        less = g.place(N.LT, "less")
        g.plan.wire("tick", DATA_OUTPUT, 4, "less", DATA_INPUT, 0)
        g.plan.validate()  # must not raise

    def test_double_const_rejected(self):
        plan = self._valid()
        plan.consts.append(plan.consts[0])
        with self.assertRaises(PlanError) as ctx:
            plan.validate()
        self.assertTrue(any("set twice" in p for p in ctx.exception.problems))

    def test_wrong_slot_on_a_concrete_pin_rejected(self):
        # 686 3:1 道具配置ID is a concrete config-id (serverParamType 20); a
        # string slot is a type-6 write into an integer-coded pin.  This is the
        # ledger's counterexample (b) — a plan that used to slip through because
        # ``slot`` was never compared to the declared pin type.
        g = Graph("MW_API_test_slottype")
        a = g.place(N.ON_CREATE, "a")
        b = g.place(N.ADD_BAG_ITEM, "b")
        a.flow_to(b)
        b.data_from(a, "entity", "holder")
        b.const("item", 2001, "string")   # wrong: must be an integer slot
        b.const("delta", 1, "int")
        with self.assertRaises(PlanError) as ctx:
            g.plan.validate()
        self.assertTrue(
            any("writes a type-6 value" in p for p in ctx.exception.problems),
            ctx.exception.problems,
        )

    def test_the_same_concrete_pin_accepts_the_integer_slot(self):
        # Positive control: the guard rejects only the *provably* wrong slot.
        # A config-id constant is still allowed to say slot="int" (its exact
        # slot is unproven — paramtypes.CONFIG_ID_SLOT is None).
        g = Graph("MW_API_test_slottype_ok")
        a = g.place(N.ON_CREATE, "a")
        b = g.place(N.ADD_BAG_ITEM, "b")
        a.flow_to(b)
        b.data_from(a, "entity", "holder")
        b.const("item", 2001, "int")
        b.const("delta", 1, "int")
        g.plan.validate()  # must not raise

    def test_a_string_pin_still_takes_a_string_slot(self):
        # Second positive control: the guard is not over-broad.
        g = Graph("MW_API_test_slotstr")
        a = g.place(N.ON_CREATE, "a")
        p = g.place(N.PRINT, "p")
        a.flow_to(p)
        p.const("text", "hello", "string")  # 打印字符串 text is type 6
        g.plan.validate()

    def test_const_on_missing_pin_rejected(self):
        g = Graph("MW_API_test_constpin")
        a = g.place(N.ON_CREATE, "a")
        g.plan.const("a", 9, 1, "int")
        with self.assertRaises(PlanError) as ctx:
            g.plan.validate()
        self.assertTrue(any("no data input index 9" in p for p in ctx.exception.problems))

    def test_unknown_role_raises_keyerror(self):
        g = Graph("MW_API_test_role")
        a = g.place(N.ON_CREATE, "a")
        with self.assertRaises(KeyError):
            a.out("nonexistent")
        with self.assertRaises(KeyError):
            a.const("nonexistent", 1, "int")

    def test_flow_to_event_node_without_exec_in_rejected(self):
        g = Graph("MW_API_test_noexexin")
        a = g.place(N.ON_CREATE, "a")
        b = g.place(N.BAG_ITEM_ADDED, "b")
        with self.assertRaises(KeyError):
            a.flow_to(b)


if __name__ == "__main__":
    unittest.main()
