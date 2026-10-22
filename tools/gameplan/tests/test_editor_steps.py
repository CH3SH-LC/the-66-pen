"""Offline tests for ``tools.gameplan.editor_steps`` -- the component-step verdict.

The module answers, from a component READ reply alone, "is the required editor
step present?".  Its whole purpose is one distinction: a **broken** reply must be
REFUSED by name, never reported as "absent".  These tests pin that distinction
against the shape the real adapter produces
(``tools/editor-bridge/Adapter/EntityComponentProbe.cs:150-156,158-173``) using
**synthetic** replies -- no bridge, no native call, no request sent, nothing
written.

Cases required of the task: present / absent / present-but-disabled / empty list
/ malformed (refuse by name).  Every one of them is exercised below, plus the
shape-mirroring guards and the non-vacuity guard that the module's own docstring
still records the UNVERIFIED id mapping.

Run::

    python -B -m unittest tools.gameplan.tests.test_editor_steps
"""

from __future__ import annotations

import unittest

from tools.gameplan import editor_steps as E
from tools.gameplan.editor_steps import Status

# The one entity the runbook names, and the reply's immutable envelope fields.
ENTITY = 1077936129
ENTITY_NAME = "岩石"


def row(
    component_id: int,
    enabled: bool = True,
    x: float = 0.0,
    y: float = 0.0,
) -> dict:
    """One component row in the probe's exact shape (``EntityComponentProbe.cs:150-156``)."""
    return {"id": component_id, "enabled": enabled, "x": x, "y": y}


def reply(
    rows: list,
    *,
    ok: bool = True,
    entity_id: int = ENTITY,
    name: str | None = ENTITY_NAME,
    count: int | None = None,
) -> dict:
    """A synthetic ``inspect-entity-components`` reply, envelope identical to the op's.

    ``count`` overrides the computed ``componentCount`` so a count/rows mismatch
    can be built on purpose.
    """
    return {
        "ok": ok,
        "status": "entity-components-editor-model-read-only",
        "entityId": entity_id,
        "entityName": name,
        "componentType": "tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq",
        "componentCount": len(rows) if count is None else count,
        "components": rows,
        "componentIdSpace": "editor-enum-value-or-native-index-UNVERIFIED",
        "nativeMutationInvoked": False,
        "localModelWritten": False,
        "sentToGame": False,
        "gameEffectVerified": False,
        "persistentSaveVerified": False,
    }


# --------------------------------------------------------------------------- #
# present
# --------------------------------------------------------------------------- #

class TestPresent(unittest.TestCase):
    def test_required_component_is_present(self):
        v = E.check_component(reply([row(1), row(8), row(33)]), required_id=8)
        self.assertIs(v.status, Status.PRESENT)
        self.assertTrue(v.satisfied)
        self.assertFalse(v.is_refusal)
        self.assertEqual(v.matched_id, 8)
        self.assertIs(v.matched_enabled, True)
        self.assertEqual(v.entity_id, ENTITY)
        self.assertEqual(v.entity_name, ENTITY_NAME)
        self.assertEqual(v.component_count, 3)
        self.assertEqual(v.present_ids, (1, 8, 33))

    def test_present_message_names_entity_and_step(self):
        line = E.describe(E.check_component(reply([row(8)]), required_id=8))
        self.assertIn(f"entity {ENTITY}", line)
        self.assertIn(ENTITY_NAME, line)
        self.assertIn("component 8", line)
        self.assertIn("present", line)

    def test_present_enabled_is_ignored_when_not_required(self):
        # required_enabled defaults to None -> presence only, either enabled state.
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                v = E.check_component(reply([row(8, enabled=enabled)]), required_id=8)
                self.assertIs(v.status, Status.PRESENT)
                self.assertIs(v.matched_enabled, enabled)

    def test_present_requires_matching_enabled_state(self):
        # required_enabled=False with an actually-disabled row is satisfied.
        v = E.check_component(reply([row(8, enabled=False)]), required_id=8, required_enabled=False)
        self.assertIs(v.status, Status.PRESENT)

    def test_present_step_among_a_duplicate_id_pair_is_satisfied_by_one(self):
        # Defensive: two rows share the id, only one is enabled.  "Any row that
        # meets the requirement" wins.
        v = E.check_component(
            reply([row(8, enabled=False), row(8, enabled=True)]),
            required_id=8,
            required_enabled=True,
        )
        self.assertIs(v.status, Status.PRESENT)


# --------------------------------------------------------------------------- #
# absent
# --------------------------------------------------------------------------- #

class TestAbsent(unittest.TestCase):
    def test_required_component_absent(self):
        v = E.check_component(reply([row(1), row(33)]), required_id=8)
        self.assertIs(v.status, Status.ABSENT)
        self.assertFalse(v.satisfied)
        self.assertIsNone(v.matched_id)
        self.assertIsNone(v.refusal)
        self.assertEqual(v.present_ids, (1, 33))

    def test_absent_message_says_missing_and_names_what_was_there(self):
        line = E.describe(E.check_component(reply([row(1), row(33)]), required_id=8))
        self.assertIn("MISSING", line)
        self.assertIn("component 8", line)
        self.assertIn("1, 33", line)
        self.assertIn(f"entity {ENTITY}", line)

    def test_absence_is_not_a_refusal(self):
        v = E.check_component(reply([]), required_id=8)
        self.assertIsNot(v.status, Status.REFUSED)
        self.assertFalse(v.is_refusal)


# --------------------------------------------------------------------------- #
# present-but-disabled (the case the check exists to separate from absent)
# --------------------------------------------------------------------------- #

class TestPresentButDisabled(unittest.TestCase):
    def test_present_but_disabled_is_distinct_from_absent(self):
        v = E.check_component(reply([row(8, enabled=False)]), required_id=8, required_enabled=True)
        self.assertIs(v.status, Status.PRESENT_DISABLED)
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertIsNot(v.status, Status.PRESENT)
        self.assertFalse(v.satisfied)
        self.assertEqual(v.matched_id, 8)
        self.assertIs(v.matched_enabled, False)
        self.assertIs(v.required_enabled, True)

    def test_present_but_disabled_message_states_both_states(self):
        line = E.describe(
            E.check_component(reply([row(8, enabled=False)]), required_id=8, required_enabled=True)
        )
        self.assertIn("DISABLED", line)
        self.assertIn("enabled=False", line)
        self.assertIn("required enabled=True", line)
        self.assertIn(f"entity {ENTITY}", line)

    def test_enabled_where_disabled_required_is_also_a_mismatch(self):
        # The mirror case: a caller that requires enabled=False getting True.
        v = E.check_component(reply([row(8, enabled=True)]), required_id=8, required_enabled=False)
        self.assertIs(v.status, Status.PRESENT_DISABLED)
        self.assertIs(v.matched_enabled, True)


# --------------------------------------------------------------------------- #
# empty list -- a legal POSITIVE read, not a failure and not a refusal
# --------------------------------------------------------------------------- #

class TestEmptyList(unittest.TestCase):
    def test_empty_components_is_a_well_formed_absent(self):
        v = E.check_component(reply([]), required_id=8)
        self.assertIs(v.status, Status.ABSENT)
        self.assertEqual(v.component_count, 0)
        self.assertEqual(v.present_ids, ())
        self.assertIsNone(v.refusal)

    def test_empty_components_is_never_refused(self):
        # The runbook's point: count==0 with ok:true is a legal empty read.
        for checker in (
            E.check_component(reply([]), required_id=8),
            E.check_any_of(reply([]), [5, 8]),
        ):
            with self.subTest(status=checker.status):
                self.assertIsNot(checker.status, Status.REFUSED)

    def test_empty_list_message_lists_no_ids(self):
        line = E.describe(E.check_component(reply([]), required_id=8))
        self.assertIn("MISSING", line)
        self.assertIn("ids present: none", line)


# --------------------------------------------------------------------------- #
# malformed -- must REFUSE by name, never report "absent"
# --------------------------------------------------------------------------- #

class TestMalformed(unittest.TestCase):
    """Every broken reply refuses with a named code and is NOT Status.ABSENT."""

    def _assert_refused(self, bad_reply, code: str):
        v = E.check_component(bad_reply, required_id=8)
        self.assertIs(v.status, Status.REFUSED, f"{code}: expected REFUSED, got {v.status}")
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertTrue(v.is_refusal)
        self.assertEqual(v.refusal, code)
        self.assertIsNone(v.component_count)
        return v

    def test_not_an_object(self):
        self._assert_refused(["not", "a", "reply"], "REPLY_NOT_AN_OBJECT")

    def test_ok_false_is_the_bridge_error_envelope(self):
        # An error reply is a refusal, NOT evidence the component is absent.
        self._assert_refused(reply([row(8)], ok=False), "REPLY_OK_NOT_TRUE")

    def test_ok_missing(self):
        bad = reply([row(8)])
        del bad["ok"]
        self._assert_refused(bad, "REPLY_OK_NOT_TRUE")

    def test_entity_id_invalid(self):
        self._assert_refused(reply([row(8)], entity_id=0), "REPLY_ENTITY_ID_INVALID")

    def test_entity_id_is_a_bool_is_invalid(self):
        # bool is an int subclass -- a naive check would accept it.
        self._assert_refused(reply([row(8)], entity_id=True), "REPLY_ENTITY_ID_INVALID")

    def test_components_missing(self):
        bad = reply([row(8)])
        del bad["components"]
        self._assert_refused(bad, "REPLY_COMPONENTS_MISSING")

    def test_components_not_a_list(self):
        bad = reply([])
        bad["components"] = {"id": 8}
        self._assert_refused(bad, "REPLY_COMPONENTS_NOT_A_LIST")

    def test_component_count_mismatch(self):
        # 2 rows but componentCount says 1 -> internally inconsistent reply.
        self._assert_refused(reply([row(1), row(8)], count=1), "REPLY_COMPONENT_COUNT_INVALID")

    def test_component_count_missing(self):
        bad = reply([row(8)])
        del bad["componentCount"]
        self._assert_refused(bad, "REPLY_COMPONENT_COUNT_INVALID")

    def test_row_not_an_object(self):
        self._assert_refused(reply([8]), "REPLY_ROW_NOT_AN_OBJECT:0")

    def test_row_id_is_a_string(self):
        self._assert_refused(reply([{"id": "8", "enabled": True, "x": 0.0, "y": 0.0}]),
                             "REPLY_ROW_ID_INVALID:0")

    def test_row_id_is_a_bool(self):
        self._assert_refused(reply([{"id": True, "enabled": True, "x": 0.0, "y": 0.0}]),
                             "REPLY_ROW_ID_INVALID:0")

    def test_row_id_missing(self):
        self._assert_refused(reply([{"enabled": True, "x": 0.0, "y": 0.0}]),
                             "REPLY_ROW_ID_INVALID:0")

    def test_row_enabled_missing(self):
        self._assert_refused(reply([{"id": 8, "x": 0.0, "y": 0.0}]),
                             "REPLY_ROW_ENABLED_INVALID:0")

    def test_row_enabled_not_a_bool(self):
        self._assert_refused(reply([{"id": 8, "enabled": 1, "x": 0.0, "y": 0.0}]),
                             "REPLY_ROW_ENABLED_INVALID:0")

    def test_row_truncated_missing_x(self):
        self._assert_refused(reply([{"id": 8, "enabled": True, "y": 0.0}]),
                             "REPLY_ROW_X_INVALID:0")

    def test_row_truncated_missing_y(self):
        self._assert_refused(reply([{"id": 8, "enabled": True, "x": 0.0}]),
                             "REPLY_ROW_Y_INVALID:0")

    def test_row_index_is_named_for_a_later_bad_row(self):
        self._assert_refused(
            reply([row(1), {"id": 8, "enabled": True, "x": 0.0}]),
            "REPLY_ROW_Y_INVALID:1",
        )

    def test_refusal_message_names_code_and_says_not_absence(self):
        line = E.describe(self._assert_refused(reply([row(8)], ok=False), "REPLY_OK_NOT_TRUE"))
        self.assertIn("REPLY_OK_NOT_TRUE", line)
        self.assertIn("not evidence of absence", line)
        self.assertNotIn("MISSING", line)

    def test_refusal_can_still_name_the_entity_when_present(self):
        # entityId is readable even though components are broken -> describe names it.
        line = E.describe(self._assert_refused(reply([8]), "REPLY_ROW_NOT_AN_OBJECT:0"))
        self.assertIn(f"entity {ENTITY}", line)
        self.assertIn(ENTITY_NAME, line)

    def test_any_of_refuses_a_broken_reply_too(self):
        v = E.check_any_of(reply([row(1)], ok=False), [5, 8])
        self.assertIs(v.status, Status.REFUSED)
        self.assertEqual(v.refusal, "REPLY_OK_NOT_TRUE")


# --------------------------------------------------------------------------- #
# check_any_of -- the "exact id uncertain" path
# --------------------------------------------------------------------------- #

class TestAnyOf(unittest.TestCase):
    def test_present_when_a_later_candidate_matches(self):
        v = E.check_any_of(reply([row(1), row(8)]), [5, 8, 40])
        self.assertIs(v.status, Status.PRESENT)
        self.assertEqual(v.matched_id, 8)
        self.assertEqual(v.required_ids, (5, 8, 40))

    def test_no_candidate_below_a_proven_mapping_is_absent(self):
        # A proven id mapping turns a no-match into a real negative.
        v = E.check_any_of(reply([row(1), row(33)]), [5, 8], meaning_proven=True)
        self.assertIs(v.status, Status.ABSENT)
        self.assertIsNone(v.matched_id)
        self.assertIsNone(v.indeterminate_reason)

    def test_no_candidate_is_indeterminate_without_a_proven_mapping(self):
        # Default (unproven): "none of {5, 8}" is not evidence of absence -- the true
        # id may lie outside the set.  This is the check_any_of uncertainty path.
        v = E.check_any_of(reply([row(1), row(33)]), [5, 8])
        self.assertIs(v.status, Status.INDETERMINATE)
        self.assertTrue(v.is_indeterminate)
        self.assertFalse(v.satisfied)
        self.assertIsNone(v.matched_id)
        self.assertEqual(v.indeterminate_reason, E.ID_MEANING_UNPROVEN)
        self.assertIsNone(v.refusal)

    def test_message_names_the_candidate_set(self):
        line = E.describe(E.check_any_of(reply([row(1)]), [5, 8], meaning_proven=True))
        self.assertIn("one of {5, 8}", line)
        self.assertIn("MISSING", line)

    def test_any_of_accepts_any_iterable(self):
        v = E.check_any_of(reply([row(40, enabled=False)]), (5, 40))
        # enabled is not part of an any-of check: matched row is present regardless.
        self.assertIs(v.status, Status.PRESENT)
        self.assertEqual(v.matched_id, 40)

    def test_empty_candidate_set_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            E.check_any_of(reply([row(8)]), [])

    def test_non_int_candidate_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            E.check_any_of(reply([row(8)]), [8, "5"])


# --------------------------------------------------------------------------- #
# the uncertainty API: check_component_by_id / check_any_of / by-predicate
# --------------------------------------------------------------------------- #
#
# The module may rely on the id's *shape* (a kind, not an instance index) but the
# id-to-meaning mapping is UNPROVEN (``COLLISION-COMPONENT-ID.md`` §3).  So a check
# that is not told the mapping is proven must return INDETERMINATE -- not ABSENT --
# when the required row is missing.  These tests pin all three outcomes plus the
# refusal, on synthetic replies only.

class TestCheckById(unittest.TestCase):
    """check_component_by_id: the exact id, with the mapping uncertainty made explicit."""

    def test_present_is_a_positive_sighting(self):
        v = E.check_component_by_id(reply([row(1), row(8)]), required_id=8)
        self.assertIs(v.status, Status.PRESENT)
        self.assertEqual(v.matched_id, 8)
        self.assertIsNone(v.indeterminate_reason)

    def test_missing_row_is_indeterminate_by_default(self):
        v = E.check_component_by_id(reply([row(1), row(33)]), required_id=8)
        self.assertIs(v.status, Status.INDETERMINATE)
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertTrue(v.is_indeterminate)
        self.assertFalse(v.satisfied)
        self.assertEqual(v.indeterminate_reason, E.ID_MEANING_UNPROVEN)
        self.assertIsNone(v.refusal)
        self.assertEqual(v.present_ids, (1, 33))

    def test_missing_row_is_absent_only_when_mapping_is_proven(self):
        v = E.check_component_by_id(reply([row(1), row(33)]), required_id=8, meaning_proven=True)
        self.assertIs(v.status, Status.ABSENT)
        self.assertIsNone(v.indeterminate_reason)

    def test_present_but_disabled_is_not_indeterminate(self):
        # A sighting of the id is determinate regardless of the mapping.
        v = E.check_component_by_id(reply([row(8, enabled=False)]), required_id=8, required_enabled=True)
        self.assertIs(v.status, Status.PRESENT_DISABLED)

    def test_malformed_reply_refuses_never_absent(self):
        v = E.check_component_by_id(reply([row(8)], ok=False), required_id=8)
        self.assertIs(v.status, Status.REFUSED)
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertIsNot(v.status, Status.INDETERMINATE)
        self.assertEqual(v.refusal, "REPLY_OK_NOT_TRUE")

    def test_bad_id_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            E.check_component_by_id(reply([row(8)]), required_id="8")


class TestCheckByPredicate(unittest.TestCase):
    """check_component_by_predicate: the caller decides a row without naming one id."""

    def test_predicate_match_is_present(self):
        v = E.check_component_by_predicate(
            reply([row(1), row(8, enabled=False)]),
            lambda r: r["id"] in {5, 8, 40},
        )
        self.assertIs(v.status, Status.PRESENT)
        self.assertEqual(v.matched_id, 8)
        self.assertIs(v.matched_enabled, False)

    def test_predicate_sees_every_field_of_the_raw_row(self):
        # The predicate is handed the row exactly as the reply carried it.
        v = E.check_component_by_predicate(reply([row(33, x=4.5, y=-1.0)]), lambda r: r["x"] > 4)
        self.assertIs(v.status, Status.PRESENT)
        self.assertEqual(v.matched_id, 33)

    def test_no_match_is_indeterminate_by_default(self):
        v = E.check_component_by_predicate(reply([row(1)]), lambda r: r["id"] == 8)
        self.assertIs(v.status, Status.INDETERMINATE)
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertEqual(v.indeterminate_reason, E.PREDICATE_MEANING_UNPROVEN)

    def test_no_match_is_absent_when_mapping_is_proven(self):
        v = E.check_component_by_predicate(
            reply([row(1)]), lambda r: r["id"] == 8, meaning_proven=True
        )
        self.assertIs(v.status, Status.ABSENT)

    def test_predicate_that_raises_refuses_and_is_never_absent(self):
        def boom(_row):
            raise KeyError("nope")

        v = E.check_component_by_predicate(reply([row(8)]), boom)
        self.assertIs(v.status, Status.REFUSED)
        self.assertIsNot(v.status, Status.ABSENT)
        self.assertEqual(v.refusal, "REPLY_PREDICATE_RAISED:0")

    def test_malformed_reply_refuses(self):
        v = E.check_component_by_predicate(["not", "a", "reply"], lambda r: True)
        self.assertIs(v.status, Status.REFUSED)
        self.assertEqual(v.refusal, "REPLY_NOT_AN_OBJECT")

    def test_non_callable_predicate_is_a_caller_error(self):
        with self.assertRaises(ValueError):
            E.check_component_by_predicate(reply([row(8)]), 8)  # type: ignore[arg-type]


class TestIndeterminateIsHonest(unittest.TestCase):
    """The INDETERMINATE verdict must read as "unknown", never as a clean negative."""

    def test_indeterminate_message_states_reason_and_denies_absence(self):
        line = E.describe(E.check_component_by_id(reply([row(1), row(33)]), required_id=8))
        self.assertIn("INDETERMINATE", line)
        self.assertIn(E.ID_MEANING_UNPROVEN, line)
        self.assertIn("not evidence of absence", line)
        self.assertNotIn("MISSING", line)
        self.assertIn(f"entity {ENTITY}", line)
        self.assertIn("component 8", line)

    def test_predicate_indeterminate_message_carries_its_own_reason(self):
        line = E.describe(
            E.check_component_by_predicate(reply([row(1)]), lambda r: r["id"] == 8)
        )
        self.assertIn(E.PREDICATE_MEANING_UNPROVEN, line)
        self.assertIn("INDETERMINATE", line)

    def test_all_three_outcomes_are_reachable_on_well_formed_replies(self):
        present = E.check_component_by_id(reply([row(8)]), required_id=8)
        absent = E.check_component_by_id(reply([row(1)]), required_id=8, meaning_proven=True)
        unknown = E.check_component_by_id(reply([row(1)]), required_id=8)
        self.assertIs(present.status, Status.PRESENT)
        self.assertIs(absent.status, Status.ABSENT)
        self.assertIs(unknown.status, Status.INDETERMINATE)

    def test_describe_never_raises_for_the_uncertainty_statuses(self):
        for v in (
            E.check_component_by_id(reply([row(1)]), required_id=8),
            E.check_component_by_predicate(reply([row(1)]), lambda r: r["id"] == 8),
            E.check_component_by_id(reply([row(8)], ok=False), required_id=8),
        ):
            self.assertIsInstance(E.describe(v), str)


# --------------------------------------------------------------------------- #
# caller-supplied id -- this module assigns no meaning to any id
# --------------------------------------------------------------------------- #

class TestCallerSuppliesTheId(unittest.TestCase):
    def test_required_id_must_be_a_non_negative_int(self):
        for bad in ("8", None, True, -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    E.check_component(reply([row(8)]), required_id=bad)

    def test_any_id_can_be_required_that_the_reply_carries(self):
        # The tool has no notion of "the collision id" -- it checks whatever it is
        # asked for.  Here a caller requires 33 and gets a PRESENT.
        v = E.check_component(reply([row(33)]), required_id=33)
        self.assertIs(v.status, Status.PRESENT)


# --------------------------------------------------------------------------- #
# guards: the docstring keeps its honesty, and the verdict is immutable
# --------------------------------------------------------------------------- #

class TestModuleDiscipline(unittest.TestCase):
    def test_docstring_records_the_unverified_id_mapping(self):
        doc = E.__doc__ or ""
        self.assertIn("UNVERIFIED", doc)
        self.assertIn("COLLISION-COMPONENT-ID.md", doc)

    def test_docstring_states_the_uncertainty_is_unproven_with_a_citation(self):
        # The task's item 4: the docstring must state the current uncertainty level
        # and cite it.  The mapping is UNPROVEN (§3), not merely "unverified".
        doc = E.__doc__ or ""
        self.assertIn("UNPROVEN", doc)
        self.assertIn("HYPOTHESIS", doc)
        self.assertIn("§3", doc)
        self.assertIn("COLLISION-COMPONENT-ID.md", doc)

    def test_docstring_cites_the_real_adapter(self):
        doc = E.__doc__ or ""
        self.assertIn("EntityComponentProbe.cs", doc)

    def test_verdict_is_frozen(self):
        v = E.check_component(reply([row(8)]), required_id=8)
        with self.assertRaises(Exception):
            v.status = Status.ABSENT  # type: ignore[misc]

    def test_describe_never_raises_for_any_status(self):
        verdicts = [
            E.check_component(reply([row(8)]), required_id=8),
            E.check_component(reply([row(1)]), required_id=8),
            E.check_component(reply([row(8, enabled=False)]), required_id=8, required_enabled=True),
            E.check_component(reply([row(8)], ok=False), required_id=8),
        ]
        seen = set()
        for v in verdicts:
            seen.add(v.status)
            self.assertIsInstance(E.describe(v), str)
        self.assertEqual(seen, {Status.PRESENT, Status.ABSENT, Status.PRESENT_DISABLED, Status.REFUSED})

    def test_status_values_are_the_named_strings(self):
        # Five, not four: INDETERMINATE was added so an unproven id cannot pass for a
        # clean absence (module docstring; COLLISION-COMPONENT-ID.md §3).
        self.assertEqual(
            {s.value for s in Status},
            {"present", "absent", "present-disabled", "refused", "indeterminate"},
        )


if __name__ == "__main__":
    unittest.main()
