"""Contract and composition checks; these do not execute native skills."""
import unittest

from tools.gameplan.contracts import load_store
from tools.gameplan.modules import player_abilities as abilities
from tools.gameplan.nodes import ON_CREATE, PRINT, Graph


class AbilityContracts(unittest.TestCase):
    def test_roles_match_native_contract_names_and_types(self):
        store = load_store()
        expected = [
            (abilities.SKILL_CALLED, {
                (4, "caster"): ("调用者实体", 1), (4, "caster_guid"): ("调用者GUID", 2),
                (4, "parameter1"): ("参数1", 6), (4, "parameter2"): ("参数2", 6),
                (4, "parameter3"): ("参数3", 6)}),
            (abilities.CREATE_SKILL, {(3, "character"): ("角色实体", 1),
                (3, "skill"): ("技能配置ID", 20), (4, "instance_id"): ("技能实例ID", 3)}),
            (abilities.BIND_SKILL, {(3, "character"): ("目标实体", 1),
                (3, "instance_id"): ("技能实例ID", 3), (3, "skill_slot"): ("技能槽位", 14),
                (3, "replace_policy"): ("原槽位技能处理", 14),
                (4, "previous_instance_id"): ("原槽位技能实例ID", 3)}),
            (abilities.CAST_SKILL, {(3, "character"): ("角色实体", 1),
                (3, "instance_id"): ("技能实例ID", 3), (3, "check_conditions"): ("是否校验按键可用", 4)}),
            (abilities.DESTROY_SKILL, {(3, "character"): ("角色实体", 1),
                (3, "instance_id"): ("技能实例ID", 3)}),
            (abilities.QUERY_SKILL, {(3, "character"): ("角色实体", 1),
                (3, "instance_id"): ("技能实例ID", 3), (4, "skill"): ("技能配置ID", 20)}),
            (abilities.SET_STATE, {(3, "target"): ("目标实体", 1),
                (3, "name"): ("变量名", 6), (3, "value"): ("变量值", 0),
                (3, "is_bp_var"): ("is_bp_var", 4), (3, "emit_event"): ("是否触发事件", 4)}),
            (abilities.GET_STATE, {(3, "target"): ("目标实体", 1),
                (3, "name"): ("变量名", 6), (3, "is_bp_var"): ("is_bp_var", 4),
                (4, "value"): ("变量值", 0)}),
            (abilities.INTEGER, {(3, "minimum"): ("下限", 3),
                (3, "maximum"): ("上限", 3), (4, "value"): ("结果", 3)}),
            (abilities.CHARACTER_PLAYER, {(3, "character"): ("角色实体", 1),
                (4, "player"): ("所属玩家实体", 1)}),
        ]
        for node, pins in expected:
            with self.subTest(node=node.definition_id):
                definition = store.require(node.definition_id)
                self.assertEqual(node.label, definition.name)
                self.assertEqual(len(pins), len(node.ins) + len(node.outs))
                for (kind, role), pair in pins.items():
                    index = (node.ins if kind == 3 else node.outs)[role]
                    port = definition.port(kind, index)
                    self.assertEqual((port.name, port.server_param_type), pair)
                self.assertEqual([p.index for p in definition.exec_inputs],
                                 [] if node.exec_in is None else [node.exec_in])
                self.assertEqual([p.index for p in definition.exec_outputs], list(node.exec_outs.values()))

    def test_create_bind_cast_query_destroy_use_actual_instance_output(self):
        g = Graph("MW_API_ABILITY_TEST")
        event = g.place(ON_CREATE, "created")
        result = abilities.create_and_bind(g, event, character=(event, "entity"),
            skill_id=100, skill_id_slot="int", skill_slot=1, replace_policy=0)
        instance = (result.created, "instance_id")
        cast = abilities.cast_instance(g, result.bound, character=(event, "entity"),
            instance=instance, check_conditions=True, check_slot="bool")
        query = abilities.query_instance(g, character=(event, "entity"), instance=instance)
        abilities.destroy_instance(g, cast, character=(event, "entity"), instance=instance)
        g.validate()
        self.assertEqual(query.ntype.definition_id, 811)
        data = {(e.src, e.src_index, e.dst, e.dst_index) for e in g.plan.edges if e.src_kind == 4}
        for destination in ("ability_bind", "ability_cast", "ability_query", "ability_destroy"):
            self.assertIn(("ability_create", 0, destination, 1), data)
        flow = {(e.src, e.dst) for e in g.plan.edges if e.src_kind == 2}
        self.assertIn(("ability_create", "ability_bind"), flow)
        self.assertIn(("ability_bind", "ability_cast"), flow)
        self.assertIn(("ability_cast", "ability_destroy"), flow)
        self.assertEqual([(c.alias, c.port_index) for c in g.plan.consts if c.value == 100],
                         [("ability_create", 1)])

    def test_skill_parameter_can_select_a_single_action(self):
        g = Graph("MW_API_SKILL_ROUTING")
        called = abilities.on_called(g)
        gate = abilities.route_equal(g, called, selector=(called, "parameter1"),
            expected="harvest", value_slot="string", alias="harvest_gate")
        done = g.place(PRINT, "done")
        gate.flow_to(done, "true")
        done.const("text", "selected", "string")
        g.validate()
        self.assertEqual(len([n for n in g.plan.nodes if n.definition_id == 392]), 1)

    def test_invalid_ids_and_enum_values_do_not_mutate_graph(self):
        for bad in (True, 0, -1, 1.5, "2", 4294967296):
            with self.subTest(bad=bad):
                g = Graph("MW_API_BAD_ABILITY")
                event = g.place(ON_CREATE, "event")
                with self.assertRaises(ValueError):
                    abilities.create_and_bind(g, event, character=(event, "entity"),
                        skill_id=bad, skill_id_slot="int", skill_slot=1, replace_policy=0)
                self.assertEqual(len(g.plan.nodes), 1)
        for bad in (True, -1, 1.5):
            g = Graph("MW_API_BAD_ENUM")
            event = g.place(ON_CREATE, "event")
            with self.assertRaises(ValueError):
                abilities.create_and_bind(g, event, character=(event, "entity"),
                    skill_id=100, skill_id_slot="int", skill_slot=bad, replace_policy=0)
            self.assertEqual(len(g.plan.nodes), 1)

    def test_state_writes_are_anchored_by_concrete_integer_outputs(self):
        g = Graph("MW_API_STATE_TEST")
        event = g.place(ON_CREATE, "event")
        abilities.set_state(g, event, target=(event, "entity"), name="stage", value=2,
            flag_slot="bool", alias="set")
        g.validate()
        self.assertNotIn(("set", 2), {(c.alias, c.port_index) for c in g.plan.consts})
        self.assertIn(("set_value", 0, "set", 2),
                      {(e.src, e.src_index, e.dst, e.dst_index) for e in g.plan.edges})
        bounds = [c.value for c in g.plan.consts if c.alias == "set_value"]
        self.assertEqual(bounds, [2, 2])


if __name__ == "__main__":
    unittest.main()
