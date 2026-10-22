"""R19-A2-F011GUARD -- adversarial regression for the F-011 production protection.

WHERE THIS LIVES, AND WHY
=========================
This suite was written under ``.runtime/cordis-plan-work/R19-A2-F011GUARD-20261002/``,
and ``/.runtime/`` is in ``.gitignore``.  So the ownership-legs protection -- one of the
two load-bearing authenticity gates behind C1/C6 -- had no test in the repository at all,
and a ``.runtime`` clean would have deleted the only one.  It was vendored verbatim into
``backend/tests/f011guard/`` for that reason (same fix as the F-010 layer's controls in
``tools/game-executor/tests/test_verify_run_provenance.py``).  The five modules and the
``fixtures/`` tree are byte-identical copies of the originals.

Residual ``.runtime`` input dependency, NAMED RATHER THAN HIDDEN: ``harness.py`` reads
``REAL_MATERIALS`` from
``.runtime/game-executor/mcp-business/cleanup/f7755123978a1d8c29d42a94cf710a5b/round-materials.json``.
``fixtures/route-evidence/`` holds a second copy of that file which is NOT byte-identical
(it differs in ``candidates``), so it is deliberately NOT used as a silent fallback --
swapping test inputs without a measurement would be a behaviour change dressed as a
convenience.  With ``.runtime`` wiped, the tests that build manifests from the real
round materials fail to read their input; that is a fixture-regeneration job, not a
protection regression.

Run:
    python -m unittest discover -s backend/tests/f011guard -p "test_*.py" -v

Every case imports the REAL production modules by path.  Every "dispatch" is a recording
stub; ``subprocess.run`` inside the imported server is replaced by a function that raises,
so a real child process cannot start even by accident.  No queue, no helper, no bridge, no
game, no editor, no delete.

The four cases that assert a protection the code does NOT currently have are collected in
the two ``KnownDeviation`` classes and marked ``expectedFailure``: they are red today
(recorded as defects) and will turn into ``unexpectedSuccess`` -- a failing run -- the day
someone fixes the code, which is the signal to move them into the main class.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harness as H                                                     # noqa: E402
import probes as P                                                      # noqa: E402


LEGS = H.load_legs()
SERVER = H.load_server(legs=LEGS)


class LegsProtection(unittest.TestCase):
    """The ownership judgement itself (backend/cleanup_ownership_legs.py)."""

    maxDiff = None

    def _check(self, name):
        self.assertIs(P.LEG_PROBES[name](LEGS), True, "probe %s failed" % name)

    def test_a_frozen_ids_refused(self):
        self._check("a-frozen-ids-refused")

    def test_a_frozen_id_with_a_full_receipt_refused(self):
        self._check("a-frozen-id-with-full-receipt-refused")

    def test_b_id_already_in_the_pre_create_baseline_refused(self):
        self._check("b-pre-baseline-member-refused")

    def test_c_no_pre_create_baseline_refuses_the_round(self):
        self._check("c-pre-baseline-absent-refused")

    def test_c_missing_pre_create_baseline_file_refuses_the_round(self):
        self._check("c-pre-baseline-missing-file-refused")

    def test_c_swapped_baseline_content_is_not_trusted(self):
        self._check("c-pre-baseline-undeclared-extra-refused")

    def test_d_missing_readback_refuses_the_round(self):
        self._check("d-readback-absent-refused")

    def test_d_truncated_readback_refuses_the_round(self):
        self._check("d-readback-truncated-refused")

    def test_d_incomplete_readback_refuses_the_round(self):
        self._check("d-readback-incomplete-refused")

    def test_d_readback_refused_by_its_own_run_record(self):
        self._check("d-readback-unaccepted-refused")

    def test_d_readback_of_another_level_refuses_the_round(self):
        self._check("d-readback-level-mismatch-refused")

    def test_d_readback_from_before_the_window_refuses_the_round(self):
        self._check("d-readback-not-fresh-refused")

    def test_e_receipt_outside_the_round_window_refused(self):
        self._check("e-receipt-outside-window-refused")

    def test_e_invalid_window_refuses_the_round(self):
        self._check("e-window-invalid-refused")

    def test_f_ids_created_in_another_level_refused(self):
        self._check("f-cross-level-refused")

    def test_f_dual_level_id_1077936135_refused_by_level(self):
        self._check("f-cross-level-dual-id-refused")

    def test_f_tampered_receipt_refused(self):
        self._check("f-receipt-tampered-refused")

    def test_a_receipt_that_is_not_a_create_refused(self):
        self._check("a-receipt-not-a-create-refused")

    def test_h_real_round_owns_exactly_its_51_creates(self):
        self._check("h-legit-round-owned-51")


class RouteProtection(unittest.TestCase):
    """The production tool route (backend/entity_server.py) -- refusal implies NO dispatch."""

    def _sentinel(self):
        return H.DispatchSentinel()

    def test_a_frozen_ids_are_refused_without_resolving_the_queue(self):
        sentinel = self._sentinel()
        manifest = H.base_manifest()
        self.assertTrue(P.p_route_frozen_no_dispatch(SERVER, sentinel),
                        "frozen ids reached the transport: %s" % sentinel.summary())

    def test_unowned_id_is_refused_without_any_dispatch(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_unowned_no_dispatch(SERVER, sentinel),
                        "an unowned id reached the transport: %s" % sentinel.summary())

    def test_run_level_refusal_happens_before_the_queue_is_resolved(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_run_refused_no_dispatch(SERVER, sentinel),
                        "an undecidable round reached the transport: %s" % sentinel.summary())

    def test_missing_round_materials_refuses_without_dispatch(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_no_materials_no_dispatch(SERVER, sentinel),
                        "a round with no materials reached the transport: %s"
                        % sentinel.summary())

    def test_unknown_bridge_run_refuses_without_dispatch(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_unknown_bridge_no_dispatch(SERVER, sentinel),
                        "a made-up bridge run reached the transport: %s" % sentinel.summary())

    def test_round_materials_for_another_level_refuse_without_dispatch(self):
        """The handle's level and the materials' level must agree.

        This is the refusal that did NOT exist before 2026-10-06: the route judged the
        materials but never compared their level to the handle's, so evidence owned on one
        level could authorise a delete on another. The positive control is the neighbouring
        `test_h_legit_round_dispatches_exactly_one_stubbed_dry_run`, which uses the same
        manifest with a MATCHING handle and does dispatch.
        """
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_materials_wrong_level_no_dispatch(SERVER, sentinel),
                        "a cross-level cleanup reached the transport: %s"
                        % sentinel.summary())

    def test_round_materials_naming_a_path_outside_runtime_refuse_without_dispatch(self):
        """Every path the materials name must stay inside the project runtime.

        The legs contain a material path nowhere, so without this the entry would read an
        arbitrary file as "what existed before"; the independent service already refused it
        (MATERIAL_PATH_NOT_ALLOWED) and the entry did not.
        """
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_material_path_outside_runtime_no_dispatch(SERVER, sentinel),
                        "a materials document naming a path outside .runtime reached the "
                        "transport: %s" % sentinel.summary())

    def test_id_attempted_by_an_earlier_request_with_no_outcome_is_not_resent(self):
        """An unobserved write is never re-sent -- and that rule is about the ID.

        The journal's re-entry guard is per (roundId, cleanupRequestId); a different id set
        is a different request by design. Without a cross-request overlap check an id whose
        dispatch was attempted and never resolved could be re-cited in a smaller batch and
        sent to the native delete a second time.
        """
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_overlapping_unknown_outcome_no_dispatch(SERVER, sentinel),
                        "an id with an unknown outcome from an earlier request was "
                        "re-dispatched: %s" % sentinel.summary())

    def test_an_invalid_round_selector_refuses_by_name_without_dispatch(self):
        """createdByRequestIds is the round selector and must be refused by NAME.

        Empty, non-list, and non-string versions all reached `_cleanup_round_id` before this
        check: the empty list hashed to the fixed digest of the empty string and a non-string
        element raised a bare TypeError. The sibling route has refused the same shapes by name
        all along.
        """
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_round_selector_unvalidated_no_dispatch(SERVER, sentinel),
                        "an invalid round selector was not refused by name: %s"
                        % sentinel.summary())

    def test_illegal_bridge_run_shapes_refuse_without_dispatch(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_shape_invalid_run_id(SERVER, sentinel),
                        "an illegal bridge run id reached the transport: %s"
                        % sentinel.summary())

    def test_h_legit_round_dispatches_exactly_one_stubbed_dry_run(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_legit_dispatches_once(SERVER, sentinel),
                        "the legit round did not dispatch as expected: %s"
                        % sentinel.summary())

    def test_the_transport_stub_is_the_only_thing_that_ran(self):
        """Belt and braces: the sentinel must be the sole dispatch path."""
        sentinel = self._sentinel()
        manifest = H.base_manifest()
        P._route(SERVER, sentinel, H.real_receipt_ids(manifest), manifest["roundRequestIds"])
        self.assertEqual(sentinel.summary()["runCalls"], 1)
        self.assertEqual(sentinel.summary()["queueResolutions"], 1)
        self.assertEqual(sentinel.summary()["handleResolutions"], 1)

    # NO LONGER AN EXPECTED FAILURE.  The deviation was "mw_scene_cleanup_owned has no
    # replay branch, so a repeated identical call re-dispatches the whole delete table".
    # Fixed 2026-10-05 in backend/entity_server.py: the route writes a claim BEFORE the
    # dispatch and its outcome after, under
    # ``<EVIDENCE_ROOT>/cleanup/<round_id>/dispatch-journal/<requestId>/`` (a
    # claim/outcome pair per REQUEST -- see backend/cleanup_dispatch_journal.py), keyed on
    # (owned ids, dryRun, bridge run id).  An exact repeat replays the recorded reply and
    # sends nothing; an exact repeat whose outcome was never recorded is refused with
    # CLEANUP_DISPATCH_OUTCOME_UNKNOWN rather than re-sent; the same request with a
    # different command is refused with CLEANUP_REQUEST_ID_CONFLICT.  A different request,
    # or a dry-run followed by a real delete, still dispatches -- each is a different call.
    # The four protections have their own probes and their own mutation controls in
    # ``test_cleanup_journal.py``.
    #
    # Order matters here: this probe must run AFTER any probe that dispatches with the same
    # (ids, dryRun) key, so it reads a clean record rather than one built by its own first
    # call.  It names its own request, so no other probe can share it.
    def test_route_reentry_does_not_replay_the_delete(self):
        sentinel = self._sentinel()
        self.assertTrue(P.p_route_reentry_does_not_replay(SERVER, sentinel),
                        "the second identical call re-dispatched: %s" % sentinel.summary())


class LegsKnownDeviations(unittest.TestCase):
    """Protections the discipline requires and the code does NOT have (recorded defects)."""

    # NO LONGER AN EXPECTED FAILURE.  The deviation was "an empty inline pre-create
    # baseline is accepted, and against an empty baseline every id is new, so leg B
    # grants ownership to anything".  Fixed 2026-10-04 in backend/cleanup_ownership_legs.py:
    # load_pre_baseline now refuses an empty id set with PRE_BASELINE_EMPTY.
    def test_c_pre_baseline_empty_inline_refused(self):
        self.assertIs(P.LEG_PROBES["c-pre-baseline-empty-inline-refused"](LEGS), True)

    # NO LONGER AN EXPECTED FAILURE.  The deviation this documented was "leg D reads a
    # read-back without ever checking it against the sha256 the round recorded".  Fixed
    # 2026-10-04 in backend/cleanup_ownership_legs.py: load_fresh_readback now takes
    # ``sha256=`` and refuses READBACK_HASH_MISMATCH; load_pre_baseline does the same for
    # PRE_BASELINE_HASH_MISMATCH.  The probe passes, so the assertion is enforced now
    # rather than tolerated.
    def test_d_readback_declared_sha256_verified(self):
        self.assertIs(P.LEG_PROBES["d-readback-sha256-verified"](LEGS), True)

    # NO LONGER AN EXPECTED FAILURE.  The deviation was "the manifest's declared readAtUtc
    # silently outranks the read-back's own record, so a round can ASSERT when it read the
    # level".  Fixed 2026-10-04 in backend/cleanup_ownership_legs.py: the declared time must
    # agree with the artifact's own stamp (exit.json startedUtc / the document / the run
    # dir name) within 2 s, else READBACK_TIME_NOT_BOUND.
    def test_d_readback_time_is_bound_to_the_artifact(self):
        self.assertIs(P.LEG_PROBES["d-readback-time-bound-to-artifact"](LEGS), True)


class RouteKnownDeviations(unittest.TestCase):
    """Route protections the discipline requires and the code does NOT have.

    EMPTY as of 2026-10-05: its one member, ``test_repeated_cleanup_call_does_not_replay_
    the_delete``, was an @expectedFailure and has been FIXED (see the comment on that test,
    now enforced in ``RouteProtection``).  The class is left standing so the next route
    deviation has a declared home rather than being smuggled into the enforced classes;
    it carries no tests, and an empty class here is the good outcome, not a gap.
    """


if __name__ == "__main__":
    unittest.main(verbosity=2)
