"""Offline tests for the manual-step oracle -- no bridge, no game, no editor.

The point under test is the three-way judgment over an ``inspect-entity-components``
reply: a non-empty entity-local component set is PRESENT (a human did a step the
project cannot do), an empty one is ABSENT, and a refusal or a malformed reply is
INDETERMINATE -- and is NEVER read as ABSENT.
"""

import json
import unittest

from tools.gameplan.manual_step_oracle import (
    ABSENT,
    INDETERMINATE,
    OUTCOMES,
    PRESENT,
    ComponentReadVerdict,
    judge_component_read,
)


def ok_reply(entity_id, rows):
    """A byte-for-byte-shaped success reply (EntityComponentProbe.cs:158-173)."""
    return {
        "ok": True,
        "status": "entity-components-editor-model-read-only",
        "entityId": entity_id,
        "entityName": "probe",
        "componentType": "tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq",
        "componentCount": len(rows),
        "components": rows,
        "componentIdSpace": "editor-enum-value-or-native-index-UNVERIFIED",
        "nativeMutationInvoked": False,
        "localModelWritten": False,
        "sentToGame": False,
        "gameEffectVerified": False,
        "persistentSaveVerified": False,
    }


def row(component_id, enabled=True, x=0.0, y=0.0):
    return {"id": component_id, "enabled": enabled, "x": x, "y": y}


class OutcomesAreDistinct(unittest.TestCase):
    def test_three_outcomes_distinct_by_name(self):
        # The three answers must be three different strings, so a caller can never
        # confuse "the human did it" with "the human did not" with "we do not know".
        self.assertEqual({PRESENT, ABSENT, INDETERMINATE}, set(OUTCOMES))
        self.assertEqual(len({PRESENT, ABSENT, INDETERMINATE}), 3)
        self.assertEqual(len(OUTCOMES), 3)
        self.assertEqual(len(set(OUTCOMES)), 3)

    def test_live_verdicts_use_the_distinct_outcomes(self):
        # A real reply for each case lands on a different outcome string.
        got = {
            judge_component_read(ok_reply(1, [row(5)])).outcome,
            judge_component_read(ok_reply(1, [])).outcome,
            judge_component_read({"ok": False, "error": "X"}).outcome,
        }
        self.assertEqual(got, {PRESENT, ABSENT, INDETERMINATE})


class Present(unittest.TestCase):
    def test_one_component_is_present(self):
        verdict = judge_component_read(ok_reply(1077936129, [row(8, enabled=True)]))
        self.assertIsInstance(verdict, ComponentReadVerdict)
        self.assertEqual(verdict.outcome, PRESENT)
        self.assertTrue(verdict.present)
        self.assertFalse(verdict.absent)
        self.assertFalse(verdict.indeterminate)
        self.assertIsNone(verdict.code)
        self.assertEqual(verdict.entity_id, 1077936129)
        self.assertEqual(verdict.component_count, 1)
        self.assertEqual(verdict.present_ids, (8,))
        self.assertIn("non-empty", verdict.reason)

    def test_many_components_are_present(self):
        verdict = judge_component_read(ok_reply(42, [row(1), row(2, enabled=False)]))
        self.assertEqual(verdict.outcome, PRESENT)
        self.assertEqual(verdict.component_count, 2)
        self.assertEqual(verdict.present_ids, (1, 2))

    def test_reason_names_the_project_cannot_add(self):
        # PRESENT is only meaningful because the project has no add-component command.
        verdict = judge_component_read(ok_reply(7, [row(3)]))
        self.assertIn("no add-component command", verdict.reason)


class Absent(unittest.TestCase):
    def test_empty_list_is_absent(self):
        verdict = judge_component_read(ok_reply(1077936129, []))
        self.assertEqual(verdict.outcome, ABSENT)
        self.assertTrue(verdict.absent)
        self.assertFalse(verdict.present)
        self.assertFalse(verdict.indeterminate)
        self.assertIsNone(verdict.code)
        self.assertEqual(verdict.component_count, 0)
        self.assertEqual(verdict.present_ids, ())

    def test_absent_reason_flags_the_invisibility_caveat(self):
        # ABSENT must not be read as "the entity has no components at all": a
        # template-carried component is invisible to this read (ZERO-COMPONENTS.md §4).
        verdict = judge_component_read(ok_reply(7, []))
        self.assertIn("template-carried components are invisible", verdict.reason)


class RefusedIsIndeterminate(unittest.TestCase):
    def test_bridge_refusal_carries_the_code(self):
        reply = {"ok": False, "error": "COMPONENT_ENTITY_NOT_FOUND"}
        verdict = judge_component_read(reply)
        self.assertEqual(verdict.outcome, INDETERMINATE)
        self.assertTrue(verdict.indeterminate)
        self.assertEqual(verdict.code, "COMPONENT_ENTITY_NOT_FOUND")
        self.assertIn("COMPONENT_ENTITY_NOT_FOUND", verdict.reason)
        # The trap: a refusal must never be collapsed into a clean negative.
        self.assertNotEqual(verdict.outcome, ABSENT)
        self.assertFalse(verdict.absent)
        self.assertIsNone(verdict.component_count)

    def test_refusal_without_a_named_code_still_indeterminate(self):
        verdict = judge_component_read({"ok": False})
        self.assertEqual(verdict.outcome, INDETERMINATE)
        self.assertEqual(verdict.code, "UNNAMED")
        self.assertNotEqual(verdict.outcome, ABSENT)

    def test_other_refusal_codes_survive(self):
        for code in (
            "COMPONENT_ENTITY_ID_NOT_UNIQUE",
            "COMPONENT_COLLECTION_NOT_MATERIALIZED",
            "CALL_FIELD_NOT_ALLOWED:nameContains",
        ):
            verdict = judge_component_read({"ok": False, "error": code})
            self.assertEqual(verdict.outcome, INDETERMINATE)
            self.assertEqual(verdict.code, code)
            self.assertIn(code, verdict.reason)


class MalformedIsIndeterminate(unittest.TestCase):
    def assert_indeterminate(self, reply, *, expect_absent_distinct=True):
        verdict = judge_component_read(reply)
        self.assertEqual(verdict.outcome, INDETERMINATE)
        self.assertTrue(verdict.indeterminate)
        self.assertTrue(verdict.code)
        if expect_absent_distinct:
            self.assertNotEqual(verdict.outcome, ABSENT)
            self.assertFalse(verdict.absent)
        return verdict

    def test_missing_components_field(self):
        self.assert_indeterminate({"ok": True, "entityId": 5, "componentCount": 0})

    def test_components_not_a_list(self):
        self.assert_indeterminate(
            {"ok": True, "entityId": 5, "components": "nope", "componentCount": 1}
        )

    def test_component_count_disagrees_with_rows(self):
        # A truncated/partial reply is not a shorter entity; refuse rather than trust
        # either number.
        reply = ok_reply(5, [row(1)])
        reply["componentCount"] = 0
        verdict = self.assert_indeterminate(reply)
        self.assertEqual(verdict.code, "REPLY_COMPONENT_COUNT_INVALID")

    def test_ok_not_true(self):
        self.assert_indeterminate({"entityId": 5, "components": [], "componentCount": 0})

    def test_entity_id_invalid(self):
        self.assert_indeterminate(
            {"ok": True, "entityId": 0, "components": [], "componentCount": 0}
        )

    def test_row_id_invalid(self):
        reply = ok_reply(5, [row("abc")])
        self.assert_indeterminate(reply)

    def test_not_a_json_object(self):
        # A raw non-JSON reply is a broken read, not an empty component set.
        verdict = self.assert_indeterminate("this is not json at all")
        self.assertEqual(verdict.code, "REPLY_NOT_JSON")

    def test_json_array_is_not_an_object(self):
        self.assert_indeterminate(json.dumps([1, 2, 3]))

    def test_none_is_not_an_object(self):
        self.assert_indeterminate(None)

    def test_python_list_is_not_an_object(self):
        self.assert_indeterminate([1, 2, 3])


class StringReplies(unittest.TestCase):
    def test_present_from_raw_text_with_log_noise(self):
        text = "INFO connecting...\n" + json.dumps(ok_reply(9, [row(4)]))
        verdict = judge_component_read(text)
        self.assertEqual(verdict.outcome, PRESENT)

    def test_absent_from_raw_text(self):
        verdict = judge_component_read(json.dumps(ok_reply(9, [])))
        self.assertEqual(verdict.outcome, ABSENT)

    def test_refusal_from_raw_text(self):
        verdict = judge_component_read('{"ok": false, "error": "COMPONENT_ENTITY_NOT_FOUND"}')
        self.assertEqual(verdict.outcome, INDETERMINATE)
        self.assertEqual(verdict.code, "COMPONENT_ENTITY_NOT_FOUND")


class VerdictInvariants(unittest.TestCase):
    def test_indeterminate_without_a_code_is_rejected(self):
        with self.assertRaises(ValueError):
            ComponentReadVerdict(
                outcome=INDETERMINATE,
                reason="no code",
                code=None,
                entity_id=None,
                component_count=None,
                present_ids=(),
            )

    def test_determinate_with_a_code_is_rejected(self):
        # A code on a determinate answer would let a caller read it as a refusal.
        with self.assertRaises(ValueError):
            ComponentReadVerdict(
                outcome=PRESENT,
                reason="present",
                code="REFUSED:X",
                entity_id=1,
                component_count=1,
                present_ids=(1,),
            )

    def test_empty_reason_is_rejected(self):
        with self.assertRaises(ValueError):
            ComponentReadVerdict(
                outcome=ABSENT,
                reason="",
                code=None,
                entity_id=1,
                component_count=0,
                present_ids=(),
            )

    def test_unknown_outcome_is_rejected(self):
        with self.assertRaises(ValueError):
            ComponentReadVerdict(
                outcome="MAYBE",
                reason="?",
                code=None,
                entity_id=None,
                component_count=None,
                present_ids=(),
            )

    def test_as_document_round_trips_the_distinct_outcome(self):
        for outcome, reply in (
            (PRESENT, ok_reply(1, [row(5)])),
            (ABSENT, ok_reply(1, [])),
            (INDETERMINATE, {"ok": False, "error": "COMPONENT_ENTITY_NOT_FOUND"}),
        ):
            doc = judge_component_read(reply).as_document()
            self.assertEqual(doc["outcome"], outcome)
            self.assertIsInstance(doc["reason"], str)


if __name__ == "__main__":
    unittest.main()
