"""Offline tests for the component sweep — fake runner, no bridge, no game.

The point under test is the failure/empty distinction: a refused, malformed, timed-out
or runner-errored entity must NOT be reported as "zero components".  Every fake here
feeds canned ``(returncode, output)`` pairs so the classification is checked exactly.
"""

import json
import unittest

from tools.gameplan.component_sweep import (
    COMPONENT_OP,
    DISPATCH_SECONDS,
    EntityResult,
    KIND_COMPONENTS,
    KIND_MALFORMED,
    KIND_REFUSED,
    KIND_RUNNER_ERROR,
    KIND_TIMEOUT,
    LEASE_SECONDS,
    chunk_entities,
    dispatches_per_lease,
    interpret_reply,
    plan_commands,
    probe_argv,
    render_command,
    render_commands,
    render_chunked_plan,
    report_document,
    summarize,
    sweep,
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


class FakeRunner:
    """Maps entityId -> (returncode, output) or a callable argv -> (code, output)."""

    def __init__(self, replies):
        self.replies = replies
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        entity_id = int(argv[argv.index("--entity-id") + 1])
        answer = self.replies[entity_id]
        if callable(answer):
            return answer(argv)
        return answer


def success_runner(mapping):
    """mapping: entityId -> list of rows."""
    return FakeRunner({eid: (0, json.dumps(ok_reply(eid, rows))) for eid, rows in mapping.items()})


class TestCleanSweep(unittest.TestCase):
    def test_reads_every_entity_and_keeps_rows(self):
        runner = success_runner({
            11: [row(5, True, 1.0, 2.0), row(6, False, 3.0, 4.0)],
            22: [],                       # genuinely zero components
            33: [row(7, True, -1.5, 0.25)],
        })
        report = sweep([11, 22, 33], runner=runner, run_id="RUN", queue_dir="Q")

        self.assertEqual(list(report), [11, 22, 33])
        self.assertEqual(report[11].rows[0].id, 5)
        self.assertTrue(report[11].rows[0].enabled)
        self.assertEqual(report[11].rows[1].enabled, False)
        self.assertEqual((report[11].rows[1].x, report[11].rows[1].y), (3.0, 4.0))
        self.assertEqual(report[33].rows[0].x, -1.5)

        # The zero-component entity is a SUCCESS with an empty tuple, not an error.
        self.assertTrue(report[22].ok)
        self.assertEqual(report[22].rows, ())
        self.assertIsNone(report[22].error)
        self.assertTrue(report[22].zero_components)

    def test_summary_counts(self):
        runner = success_runner({1: [row(9)], 2: [], 3: [row(4), row(5)]})
        summary = summarize(sweep([1, 2, 3], runner=runner, run_id="RUN"))
        self.assertEqual(summary["entities"], 3)
        self.assertEqual(summary["withComponents"], 2)
        self.assertEqual(summary["zeroComponents"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["failedEntityIds"], [])

    def test_one_dispatch_per_entity_in_order(self):
        runner = success_runner({1: [], 2: [], 3: []})
        sweep([3, 1, 2], runner=runner, run_id="RUN")
        self.assertEqual(len(runner.calls), 3)
        # entities were read in the order given, each with the exact op
        seen = [int(c[c.index("--entity-id") + 1]) for c in runner.calls]
        self.assertEqual(seen, [3, 1, 2])
        self.assertTrue(all(COMPONENT_OP in c for c in runner.calls))

    def test_duplicates_are_dispatched_once(self):
        runner = success_runner({7: [row(1)]})
        report = sweep([7, 7, 7], runner=runner, run_id="RUN")
        self.assertEqual(list(report), [7])
        self.assertEqual(len(runner.calls), 1)


class TestRefusal(unittest.TestCase):
    def test_refusal_is_an_error_not_zero_components(self):
        runner = FakeRunner({
            11: (0, json.dumps(ok_reply(11, [row(5)]))),
            22: (1, json.dumps({"ok": False, "error": "COMPONENT_ENTITY_NOT_FOUND"})),
            33: (0, json.dumps(ok_reply(33, []))),
        })
        report = sweep([11, 22, 33], runner=runner, run_id="RUN")

        self.assertEqual(report[22].kind, KIND_REFUSED)
        self.assertIsNone(report[22].rows)
        self.assertIn("COMPONENT_ENTITY_NOT_FOUND", report[22].error)
        self.assertFalse(report[22].zero_components)

        summary = summarize(report)
        self.assertEqual(summary["refused"], 1)
        self.assertEqual(summary["zeroComponents"], 1)     # ONLY the real empty entity
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["failedEntityIds"], [22])

    def test_refused_entity_is_never_counted_as_empty(self):
        runner = FakeRunner({5: (1, json.dumps({"ok": False, "error": "CRUD_READ_REFUSED"}))})
        report = sweep([5], runner=runner, run_id="RUN")
        self.assertIsNone(report[5].rows)
        self.assertNotIn("zeroComponents", report[5].as_document())
        self.assertEqual(summarize(report)["zeroComponents"], 0)


class TestMalformed(unittest.TestCase):
    def test_non_json_is_malformed_not_empty(self):
        runner = FakeRunner({5: (0, "totally not json")})
        report = sweep([5], runner=runner, run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)
        self.assertIsNone(report[5].rows)
        self.assertFalse(report[5].zero_components)

    def test_components_not_a_list_is_malformed(self):
        reply = ok_reply(5, [])
        reply["components"] = {"oops": True}
        report = sweep([5], runner=FakeRunner({5: (0, json.dumps(reply))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)
        self.assertIsNone(report[5].rows)

    def test_count_mismatch_is_malformed(self):
        reply = ok_reply(5, [row(1), row(2)])
        reply["componentCount"] = 1                      # truncated list demoted to lie
        report = sweep([5], runner=FakeRunner({5: (0, json.dumps(reply))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)
        self.assertIsNone(report[5].rows)

    def test_bad_element_is_malformed(self):
        reply = ok_reply(5, [row(1)])
        reply["components"][0]["enabled"] = "yes"        # a string is not a bool
        report = sweep([5], runner=FakeRunner({5: (0, json.dumps(reply))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)

    def test_entity_id_mismatch_is_malformed(self):
        report = sweep([5], runner=FakeRunner({5: (0, json.dumps(ok_reply(6, [])))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)

    def test_ok_true_with_nonzero_exit_is_malformed(self):
        report = sweep([5], runner=FakeRunner({5: (1, json.dumps(ok_reply(5, [row(1)])))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)
        self.assertIsNone(report[5].rows)

    def test_ok_not_boolean_is_malformed(self):
        report = sweep([5], runner=FakeRunner({5: (0, json.dumps({"ok": "true", "entityId": 5, "componentCount": 0, "components": []}))}),
                       run_id="RUN")
        self.assertEqual(report[5].kind, KIND_MALFORMED)


class TestRunnerErrorsAndTimeout(unittest.TestCase):
    def test_runner_exit_without_json_is_runner_error(self):
        runner = FakeRunner({5: (1, "runner error: SCOPE_EXPIRED\n")})
        report = sweep([5], runner=runner, run_id="RUN")
        self.assertEqual(report[5].kind, KIND_RUNNER_ERROR)
        self.assertIn("SCOPE_EXPIRED", report[5].error)
        self.assertIsNone(report[5].rows)

    def test_pending_reply_is_timeout(self):
        reply = {"ok": False, "pending": True, "outcomeUncertain": True, "requestId": "a" * 32}
        report = sweep([5], runner=FakeRunner({5: (1, json.dumps(reply))}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_TIMEOUT)
        self.assertIsNone(report[5].rows)

    def test_leading_noise_tolerated(self):
        output = "log line\n" + json.dumps(ok_reply(5, [row(3)])) + "\ntrailing"
        report = sweep([5], runner=FakeRunner({5: (0, output)}), run_id="RUN")
        self.assertEqual(report[5].kind, KIND_COMPONENTS)
        self.assertEqual(report[5].rows[0].id, 3)


class TestDeterminismAndInvariants(unittest.TestCase):
    def test_repeated_sweeps_are_identical(self):
        def build():
            return FakeRunner({
                11: (0, json.dumps(ok_reply(11, [row(1)]))),
                22: (1, json.dumps({"ok": False, "error": "COMPONENT_ENTITY_NOT_FOUND"})),
                33: (0, "nonsense"),
            })
        first = sweep([11, 22, 33], runner=build(), run_id="RUN", queue_dir="Q")
        second = sweep([11, 22, 33], runner=build(), run_id="RUN", queue_dir="Q")
        self.assertEqual(first, second)
        self.assertEqual(report_document(first), report_document(second))

    def test_entity_result_cannot_be_built_inconsistent(self):
        with self.assertRaises(ValueError):
            EntityResult(entity_id=1, kind=KIND_COMPONENTS, rows=None, error=None)
        with self.assertRaises(ValueError):
            EntityResult(entity_id=1, kind=KIND_REFUSED, rows=(), error="x")
        with self.assertRaises(ValueError):
            EntityResult(entity_id=1, kind=KIND_REFUSED, rows=None, error=None)
        with self.assertRaises(ValueError):
            EntityResult(entity_id=1, kind="bogus", rows=None, error="x")

    def test_bad_entity_id_refuses_before_dispatch(self):
        runner = success_runner({5: []})
        for bad in (0, -1, 4294967296, True, "5", 1.0):
            with self.assertRaises(ValueError):
                sweep([bad], runner=runner, run_id="RUN")
        self.assertEqual(runner.calls, [])

    def test_missing_run_id_refuses(self):
        with self.assertRaises(ValueError):
            sweep([5], runner=success_runner({5: []}), run_id="")


class TestPlanning(unittest.TestCase):
    def test_probe_argv_shape(self):
        argv = probe_argv(1077936129, run_id="RUN-GUID", queue_dir="Q")
        self.assertEqual(argv[0], "python")
        self.assertIn("elevated-request.py", argv[2])
        # --queue-dir is a TOP-LEVEL flag: it must precede the `call` subcommand.
        self.assertLess(argv.index("--queue-dir"), argv.index("call"))
        self.assertIn(COMPONENT_OP, argv)
        self.assertEqual(argv[argv.index("--entity-id") + 1], "1077936129")
        self.assertEqual(argv[argv.index("--run-id") + 1], "RUN-GUID")

    def test_plan_commands_one_per_unique_entity(self):
        commands = plan_commands([3, 3, 1], run_id="RUN")
        self.assertEqual(len(commands), 2)
        self.assertEqual([c[c.index("--entity-id") + 1] for c in commands], ["3", "1"])

    def test_render_command_quotes_spaces(self):
        line = render_command(["python", "-B", "C:/Program Files/x.py", "call"])
        self.assertIn('"C:/Program Files/x.py"', line)

    def test_render_commands_len(self):
        self.assertEqual(len(render_commands([1, 2, 3], run_id="RUN")), 3)

    def test_dispatches_per_lease_math(self):
        self.assertEqual(dispatches_per_lease(), 15)                       # (300-60)/16
        self.assertEqual(dispatches_per_lease(lease_seconds=100, reserve_seconds=40,
                                              dispatch_seconds=20), 3)      # (100-40)/20
        self.assertEqual(dispatches_per_lease(lease_seconds=20, reserve_seconds=60,
                                              dispatch_seconds=16), 1)      # floored at 1
        self.assertEqual(dispatches_per_lease(dispatch_seconds=0), 1)

    def test_chunk_entities_sizes(self):
        chunks = chunk_entities(list(range(1, 32)), max_per_chunk=15)
        self.assertEqual([len(c) for c in chunks], [15, 15, 1])
        self.assertEqual(chunks[0][0], 1)
        self.assertEqual(chunks[2], [31])

    def test_chunk_entities_dedupes_and_preserves_order(self):
        chunks = chunk_entities([9, 9, 8, 7], max_per_chunk=2)
        self.assertEqual(chunks, [[9, 8], [7]])

    def test_render_chunked_plan_has_lease_note_and_one_line_per_entity(self):
        text = render_chunked_plan([1, 2, 3], max_per_chunk=2, queue_dir="Q")
        self.assertIn("5-minute lease", text)
        self.assertEqual(text.count("inspect-entity-components"), 3)
        self.assertIn("chunk 1/2", text)
        self.assertIn("chunk 2/2", text)

    def test_render_chunked_plan_rejects_bad_run_ids(self):
        with self.assertRaises(ValueError):
            render_chunked_plan([1, 2, 3], run_ids=["only-one"], max_per_chunk=2)


class TestConstants(unittest.TestCase):
    def test_measured_defaults_are_the_documented_ones(self):
        self.assertEqual(DISPATCH_SECONDS, 16.0)
        self.assertEqual(LEASE_SECONDS, 300.0)


if __name__ == "__main__":
    unittest.main()
