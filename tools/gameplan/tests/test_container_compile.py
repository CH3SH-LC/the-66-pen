"""Containers must reach both compiler paths intact before any live dispatch."""
import json
import unittest

from tools.gameplan.builder import GraphBuilder, _tagged
from tools.gameplan.plan import GraphPlan, PlanError


class ContainerCompileTests(unittest.TestCase):
    def price_plan(self):
        plan = GraphPlan("MW_API_container_compile")
        plan.add("price", 704)
        entries = [{"key": {"int": 1115684864}, "value": {"int": 10}}]
        plan.dict_const("price", 4, entries)
        return plan, entries

    def test_integer_currency_keys_survive_batch_and_single_value_paths(self):
        plan, entries = self.price_plan()
        plan.validate()
        calls = []
        builder = GraphBuilder(plan, lambda argv: calls.append(argv) or {"ok": True}, run_id="offline")
        expected = {"dict": entries}
        self.assertEqual(builder.batch_plan_json()["values"][0]["value"], expected)
        builder._write_const(plan.consts[0], 1, {"price": 1})
        argv = calls[0]
        self.assertEqual(json.loads(argv[argv.index("--value-json") + 1]), expected)
        self.assertEqual(argv[argv.index("--slot") + 1], "auto")

    def test_caller_edits_do_not_change_the_declared_price(self):
        plan, entries = self.price_plan()
        entries[0]["value"]["int"] = 999
        self.assertEqual(plan.consts[0].value["dict"][0]["value"], {"int": 10})

    def test_timer_sequence_keeps_float_elements(self):
        plan = GraphPlan("MW_API_timer_container")
        plan.add("timer", 79)
        plan.list_const("timer", 3, [{"float": 5.0}])
        plan.validate()
        payload = GraphBuilder(plan, lambda argv: self.fail("no dispatch expected"), run_id="offline").batch_plan_json()
        self.assertEqual(payload["values"][0]["value"], {"list": [{"float": 5.0}]})

    def test_malformed_or_ambiguous_containers_never_stringify(self):
        bad = [[], {1: 10}, {"dict": [
            {"key": {"int": 1}, "value": {"int": 10}},
            {"key": {"int": 1}, "value": {"int": 20}},
        ]}, {"dict": [{"key": {"int": 1}, "value": {"dict": []}}]}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                _tagged("auto", value)

    def test_dict_cannot_target_an_integer_or_text_pin(self):
        plan = GraphPlan("MW_API_bad_container_pin")
        plan.add("print", 1)
        plan.dict_const("print", 0, [])
        with self.assertRaises(PlanError):
            plan.validate()


if __name__ == "__main__":
    unittest.main()
