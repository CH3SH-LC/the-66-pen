"""Offline fixtures for backend/cleanup_service.py.

Everything here is a fixture: no queue, no helper, no bridge, no game, no editor.  The
fake bridge records every call, so "nothing was dispatched" is asserted on the transport
itself rather than on a status field.

Run:
    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.tests.test_cleanup_service
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import backend.cleanup_service as cs                                    # noqa: E402

co = cs.co
TASK_ROOT = REPO / ".runtime/cordis-plan-work/DS-04-parallel-20261002"

LEVEL = 1073741839
OTHER_LEVEL = 1073741834
T_A, T_B = 20001034, 20001035

#: F-011, 2026-10-06. An EMPTY pre-create baseline is now refused by ``load_pre_baseline`` in
#: BOTH forms -- the file form used to accept one (``{"entities": []}``) while the inline form
#: already refused it, and against an empty baseline every id looks new, so leg B became a
#: rubber stamp that granted ownership of anything. MEASURED over the 1185 native context
#: documents on this machine: 11 of them carry an empty entity list.
#:
#: Every ``pre_pairs=[]`` below meant "the ids under test are new this round", NOT "nothing
#: existed before". Those two readings were the same thing only while the rubber stamp was in
#: place. This constant is the smallest baseline that expresses the intended reading: one
#: pre-existing entity that is in no test's id set, so every id under test is still new
#: relative to it, without the baseline being empty.
PRE_EXISTING_UNRELATED = (1,)

#: The round the fixtures live in.  F-011 made the round window, the pre-create baseline,
#: the pre-cleanup complete read-back and the receipt provenance REQUIRED inputs
#: (``OwnershipMaterials.roundMaterials``): the three-way proof proves consistency of the
#: materials it is handed, but only these four can show that an object was added by THIS
#: round.  Every fixture below therefore builds a real round, not just a consistent set.
ROUND_ID = "round-fixture-20260930"
ROUND_START, ROUND_STOP = "2026-09-30T02:12:16Z", "2026-09-30T03:17:24Z"
CREATED_AT, READ_AT = "2026-09-30T02:30:00Z", "2026-09-30T03:00:00Z"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def round_window(round_id=ROUND_ID, start=ROUND_START, stop=ROUND_STOP):
    return {"roundId": round_id, "startUtc": start, "stopUtc": stop}


def readback_document(pairs, *, level=LEVEL, read_at=READ_AT, complete=True):
    """A complete pre-cleanup read-back.

    The entity set plus the four things that make it usable (``complete``/``levelId``/
    ``readAtUtc``/``entityCount``).  One document serves both roles the service now reads
    it in: ``OwnershipMaterials.currentBaseline`` and the legs' ``freshReadback``.
    """
    entities = [{"id": entity_id, "templateId": template} for entity_id, template in pairs]
    return {"entities": entities, "levelId": level, "readAtUtc": read_at,
            "complete": bool(complete), "entityCount": len(entities)}


def tampered_readback_document(pairs, *, level=LEVEL, read_at=READ_AT):
    """A read-back whose entity list names the same object twice.

    ``entityCount`` is the number of DISTINCT ids -- which is what a tamperer would write,
    because that keeps the read-back's own truncation check satisfied.  Only a
    duplicate-id check can catch this document.
    """
    entities = [{"id": entity_id, "templateId": template} for entity_id, template in pairs]
    entities = entities + [dict(entities[0])]
    return {"entities": entities, "levelId": level, "readAtUtc": read_at,
            "complete": True, "entityCount": len(pairs)}


def write_receipt(path: Path, entity_id, level=LEVEL, template=T_A, *,
                  created=CREATED_AT, request_id=None):
    """One create receipt on disk, plus the provenance index entry for it.

    The entry -- not the body -- is what the round recorded: ``recordedSha256`` is the
    hash the provenance leg checks the file against, and ``startedUtc`` is the round's own
    clock for the create, which is what the time-window leg reads.
    """
    request_id = request_id or ("create-%s" % Path(path).stem)
    write_json(path, {"action": "create", "startedUtc": created,
                      "backend": {"entityId": entity_id, "levelId": level,
                                  "templateId": template},
                      "command": {"levelId": level, "templateId": template}})
    return {"requestId": request_id, "action": "create", "entityId": entity_id,
            "levelId": level, "templateId": template, "startedUtc": created,
            "path": str(path), "recordedSha256": sha256_file(path)}


def with_round_materials(materials, round_materials):
    """Attach execution-layer round materials to materials built by hand.

    ``OwnershipMaterials`` is frozen; ``materials_from_ownership_query`` (the DS-08
    adapter) has no round-materials parameter to widen, so a fixture that must exercise
    that adapter supplies them here rather than by changing the interface.
    """
    return dataclasses.replace(materials, roundMaterials=round_materials)


class FakeOwnership:
    """The DS-08 seam.  Returns exactly what the test hands it."""

    def __init__(self, materials):
        self.materials = materials
        self.calls = 0

    def materials_for_round(self, session, request_ids):
        self.calls += 1
        return self.materials


class FakeBridge:
    """The execution-layer seam, modelling a level rather than a canned reply.

    ``existing`` is the set of entity ids currently in the level.  A dry-run maps only
    what is there; when part of the list is gone the adapter refuses the whole call with
    ``refused-unresolved-ids``, exactly as ``OwnedEntityDelete.cs`` does.  A delete removes
    the ids it was allowed to invoke.  Recording every call makes "nothing was dispatched"
    an assertion about the transport, not about a status field.
    """

    def __init__(self, *, existing=None, level=LEVEL,
                 bridge_run="11111111-2222-3333-4444-555555555555", available=True,
                 status_level=None, dry=None, delete=None, remove_on_invoke=True):
        self.calls = []
        self.existing = set(existing) if existing is not None else None
        self.removed = set()
        self.remove_on_invoke = remove_on_invoke
        self.level = level
        self.status_level = status_level if status_level is not None else level
        self.bridge_run = bridge_run
        self.available = available
        self.dry = dry or self._level_dry
        self.delete = delete or self._level_delete

    def status(self):
        return cs.BridgeStatus(available=self.available, levelId=self.status_level,
                               bridgeRunId=self.bridge_run,
                               reason=None if self.available else "the helper is gone")

    def dispatch(self, op, ids):
        ids = list(ids)
        self.calls.append((op, ids))
        handler = self.dry if op == cs.DRY_OP else self.delete
        reply = handler(op, ids)
        if isinstance(reply, co.DispatchResult):
            return reply
        if op == cs.DELETE_OP and self.remove_on_invoke:
            for row in reply.get("results") or []:
                if isinstance(row, dict) and row.get("invoked") is True:
                    self.removed.add(row.get("id"))
        return co.DispatchResult(0, ["call", "--op", op], json.dumps(reply), "", reply)

    # -- level-modelling handlers ------------------------------------------ #

    def present(self, entity_id):
        if entity_id in self.removed:
            return False
        return self.existing is None or entity_id in self.existing

    def _level_dry(self, op, ids):
        missing = [value for value in ids if not self.present(value)]
        if missing:
            return {"ok": False, "status": "refused-unresolved-ids", "dryRun": True,
                    "requested": len(ids), "resolvedCount": len(ids) - len(missing),
                    "unresolved": [{"id": value, "matches": 0, "frontendPath": "<none>"}
                                   for value in missing],
                    "invoked": False, "sentToGame": False}
        return dry_reply(ids)

    def _level_delete(self, op, ids):
        return delete_reply(ids, set(ids))

    # -- assertions helpers ------------------------------------------------- #

    def ops(self):
        return [op for op, _ in self.calls]

    def delete_calls(self):
        return [ids for op, ids in self.calls if op == cs.DELETE_OP]

    def seen_ids(self):
        return sorted({entity_id for _, ids in self.calls for entity_id in ids})


def dry_reply(ids, **extra):
    body = {"ok": True, "status": "dry-run-mapping-only", "dryRun": True,
            "requested": len(ids), "resolvedCount": len(ids),
            "mapping": [{"id": value, "frontendPath": "/root/%d" % value} for value in ids],
            "invoked": False, "gameEffectVerified": False, "persistentSaveVerified": False}
    body.update(extra)
    return body


def delete_reply(ids, invoked_ids, broken_at=None):
    rows = []
    for value in ids:
        if broken_at is not None and value == broken_at:
            rows.append({"id": value, "frontendPath": "/root/%d" % value, "invoked": False,
                         "error": "OWNED_DELETE_TARGET_CHANGED_DURING_PREPARATION"})
            break
        if value in invoked_ids:
            rows.append({"id": value, "frontendPath": "/root/%d" % value,
                         "invoked": True, "nativeResult": True})
    return {"ok": True, "status": "delete-requested-readback-pending", "dryRun": False,
            "requested": len(ids),
            "invokedCount": len(rows) - (1 if broken_at is not None else 0),
            "results": rows, "retryAllowed": False, "gameEffectVerified": False,
            "persistentSaveVerified": False}


def unreadable_reply(op, ids):
    """A mutating reply that cannot be read: the outcome is unknown for the batch."""
    return co.DispatchResult(1, ["call", "--op", op], "not json at all", "", None)


class CleanupFixtureCase(unittest.TestCase):
    """Base: a temporary directory INSIDE this worker's task run root."""

    @classmethod
    def setUpClass(cls):
        TASK_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=TASK_ROOT, prefix="test-")
        self.tmp = Path(self._tmp.name)
        self.evidence = self.tmp / "evidence"
        self.evidence.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._tmp.cleanup)

    # -- builders ---------------------------------------------------------- #

    def materials(self, receipts_ids, current_pairs, pre_pairs=None, *, level=LEVEL,
                  template=T_A, name="m1", receipt_level=None, created=CREATED_AT,
                  read_at=READ_AT, round_id=ROUND_ID,
                  window=(ROUND_START, ROUND_STOP)):
        base = self.tmp / name
        claim_level = receipt_level if receipt_level is not None else level
        provenance = [write_receipt(base / "receipts" / ("%d-%d.json" % (entity_id, index)),
                                    entity_id, claim_level, template, created=created)
                      for index, entity_id in enumerate(receipts_ids)]
        receipts = tuple(Path(entry["path"]) for entry in provenance)
        current = write_json(base / "current.json",
                             readback_document(current_pairs, level=level, read_at=read_at))
        pre = None
        if pre_pairs is not None:
            # An empty ``pre_pairs`` used to mean "nothing pre-existed", which is a baseline
            # the legs now refuse. See PRE_EXISTING_UNRELATED: the callers' intent is "the
            # ids under test are new", so that is what an empty request is translated to.
            pairs = PRE_EXISTING_UNRELATED if len(pre_pairs) == 0 else pre_pairs
            pre = write_json(base / "pre.json",
                             {"entities": [{"id": entity_id} for entity_id in pairs]})
        round_materials = {
            "levelId": level,
            "window": {"roundId": round_id, "startUtc": window[0], "stopUtc": window[1]},
            "freshReadback": {"path": str(current)},
            "receipts": provenance,
        }
        if pre is not None:
            round_materials["preBaseline"] = {"path": str(pre)}
        return cs.OwnershipMaterials(levelId=level, receipts=receipts, preBaseline=pre,
                                     currentBaseline=current, source="fixture",
                                     digest="fixture-digest", roundMaterials=round_materials)

    def session(self, level=LEVEL, round_id="round-1", run_id=None):
        return cs.CleanupSession(levelId=level, levelHandleDigest="digest",
                                 bridgeRunId="11111111-2222-3333-4444-555555555555",
                                 sessionIdentity="fixture-session", roundId=round_id)

    def service(self, materials, bridge, **kwargs):
        return cs.CleanupService(ownership=FakeOwnership(materials), bridge=bridge,
                                 evidence_root=self.evidence, **kwargs)


# --------------------------------------------------------------------------- #
# refusal semantics: no ids -> refusal, never an empty list
# --------------------------------------------------------------------------- #

class RefusalSemantics(CleanupFixtureCase):

    def test_empty_target_list_is_refused_and_nothing_is_dispatched(self):
        bridge = FakeBridge()
        service = self.service(self.materials([], []), bridge)
        report = service.cleanup_owned(self.session(), [], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("CLEANUP_IDS_EMPTY", [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [], "an empty list must never reach the route")
        self.assertEqual(report["batches"], [])

    def test_ownership_materials_unavailable_refuses_and_sends_no_empty_list(self):
        bridge = FakeBridge()
        provider = FakeOwnership(cs.OwnershipUnavailable("OWNERSHIP_LEDGER_DOWN",
                                                         "the ledger has no answer"))
        service = cs.CleanupService(ownership=provider, bridge=bridge,
                                    evidence_root=self.evidence)
        report = service.cleanup_owned(self.session(), [9001, 9002], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("OWNERSHIP_LEDGER_DOWN", [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [], "no ids obtained must not become an empty dispatch")
        self.assertEqual(report["batches"], [])
        self.assertTrue(all(row["state"] == cs.STATE_REFUSED
                            for row in report["perId"].values()))

    def test_missing_ownership_provider_is_a_refusal_not_a_pass(self):
        bridge = FakeBridge()
        service = cs.CleanupService(ownership=None, bridge=bridge,
                                    evidence_root=self.evidence)
        report = service.cleanup_owned(self.session(), [9001], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("OWNERSHIP_MATERIALS_UNAVAILABLE",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])

    def test_bridge_unavailable_refuses_and_dispatches_nothing(self):
        bridge = FakeBridge(available=False)
        service = self.service(self.materials([9001], [(9001, T_A)], []), bridge)
        report = service.cleanup_owned(self.session(), [9001], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("CLEANUP_BRIDGE_UNAVAILABLE",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])

    def test_bridge_bound_to_another_level_refuses(self):
        bridge = FakeBridge(status_level=OTHER_LEVEL)
        service = self.service(self.materials([9001], [(9001, T_A)], []), bridge)
        report = service.cleanup_owned(self.session(), [9001], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("CLEANUP_BRIDGE_WRONG_LEVEL",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])

    def test_invalid_request_id_is_refused_before_anything(self):
        bridge = FakeBridge()
        service = self.service(self.materials([9001], [(9001, T_A)], []), bridge)
        report = service.cleanup_owned(self.session(), [9001], "bad id!", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("REQUEST_ID_INVALID", [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])


# --------------------------------------------------------------------------- #
# ownership: external objects, cross-level ids, the three frozen ids
# --------------------------------------------------------------------------- #

class OwnershipProof(CleanupFixtureCase):

    def test_external_object_is_refused_by_name_and_never_dispatched(self):
        materials = self.materials([9001], [(9001, T_A), (8000, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 8000], "req-1", dry_run=False)
        codes = {row["entityId"]: row["code"] for row in report["refusals"]
                 if row["entityId"] is not None}
        self.assertEqual(codes.get(8000), "CLEANUP_ID_NOT_OWNED_BY_THIS_RUN")
        self.assertEqual(report["ownedIds"], [9001])
        self.assertNotIn(8000, bridge.seen_ids(),
                         "an id with no create receipt must never be sent to the route")
        self.assertEqual(report["perId"]["%d:8000" % LEVEL]["state"], cs.STATE_REFUSED)
        self.assertEqual(report["perId"]["%d:9001" % LEVEL]["state"], cs.STATE_DELETED)

    def test_pre_existing_id_is_refused_even_with_a_receipt_that_claims_it(self):
        # The receipt claims 8000, but 8000 was already in the pre-create baseline.
        materials = self.materials([8000], [(8000, T_A)], pre_pairs=[8000])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [8000], "req-1", dry_run=False)
        codes = [row["code"] for row in report["refusals"]]
        self.assertIn("NOT_NEWLY_ADDED", codes)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertEqual(bridge.calls, [])

    def test_same_id_in_another_level_is_refused(self):
        # 1077936135 really does exist in level 1073741834 and in 1073741839.  Here the
        # receipt is for the OTHER level while the session targets this one, and the id is
        # present in this level's current baseline too -- presence alone proves nothing.
        materials = self.materials([1077936135], [(1077936135, T_A)], pre_pairs=[],
                                   receipt_level=OTHER_LEVEL)
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(level=LEVEL), [1077936135], "req-1", dry_run=False)
        codes = [row["code"] for row in report["refusals"]]
        self.assertIn("LEVEL_MISMATCH", codes)
        self.assertEqual(report["ownedIds"], [])
        self.assertEqual(bridge.calls, [], "a cross-level id must never be deleted here")

    def test_materials_for_another_level_are_refused_wholesale(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[], level=OTHER_LEVEL)
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(level=LEVEL), [9001], "req-1", dry_run=False)
        self.assertIn("OWNERSHIP_MATERIALS_WRONG_LEVEL",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])

    def test_one_id_bound_to_two_levels_is_refused_as_ambiguous(self):
        base = self.tmp / "ambiguous"
        here = write_receipt(base / "receipts" / "9001-here.json", 9001, LEVEL, T_A)
        there = write_receipt(base / "receipts" / "9001-there.json", 9001, OTHER_LEVEL, T_B)
        current = write_json(base / "current.json", readback_document([(9001, T_A)]))
        pre = write_json(base / "pre.json", {"entities": [{"id": entity_id} for entity_id in PRE_EXISTING_UNRELATED]})
        materials = cs.OwnershipMaterials(
            levelId=LEVEL, receipts=(Path(here["path"]), Path(there["path"])),
            preBaseline=pre, currentBaseline=current, source="fixture",
            roundMaterials={"levelId": LEVEL, "window": round_window(),
                            "freshReadback": {"path": str(current)},
                            "preBaseline": {"path": str(pre)},
                            "receipts": [here, there]})
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False)
        self.assertIn("RECEIPT_AMBIGUOUS_CLAIM",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])

    def test_the_three_unattributable_ids_stay_untouched(self):
        frozen = sorted(cs.protected_ids_for(LEVEL))
        self.assertEqual(frozen, [1077936129, 1077936130, 1077936131])
        # Even a forged receipt claiming them must not get them deleted.
        materials = self.materials(frozen, [(value, T_A) for value in frozen], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), frozen, "req-1", dry_run=False)
        codes = {row["entityId"]: row["code"] for row in report["refusals"]
                 if row["entityId"] is not None}
        for value in frozen:
            self.assertEqual(codes.get(value), "CLEANUP_TARGET_UNATTRIBUTABLE")
        self.assertEqual(bridge.calls, [],
                         "the frozen ids must not reach the route under any argument")
        self.assertEqual(report["ownedIds"], [])

    def test_the_same_ids_are_not_frozen_on_another_level(self):
        # THE 2026-10-08 FIX, at the service layer.  Those three ids were observed in ONE
        # level; an entity id is not a property of an object (1077936135 has been recorded
        # in two levels under two templates).  MEASURED consequence of the flat set: the
        # live parameter driver created entity 1077936130 in level 1073741842 and the guard
        # then refused to let it delete the object it had just created and held a receipt
        # for, so the run left an orphan it could not remove.
        self.assertEqual(cs.protected_ids_for(OTHER_LEVEL), frozenset())
        self.assertEqual(cs.protected_ids_for(None), frozenset())
        self.assertEqual(cs.protected_ids_for("not-a-level"), frozenset())
        # A caller's own extra set still applies on every level: protection can only be
        # added by a caller, never removed.
        svc = cs.CleanupService(protected_ids=[1077936130])
        self.assertEqual(svc._protected_for(OTHER_LEVEL), frozenset({1077936130}))
        self.assertEqual(svc._protected_for(LEVEL),
                         frozenset({1077936129, 1077936130, 1077936131}))

    def test_tampered_baseline_duplicate_id_refuses_the_document(self):
        # The pre-cleanup read-back names the same object twice, so it is not a set and is
        # refused BY NAME.  The normaliser the F-011 legs read this document with is keyed
        # by id and would collapse the duplicate silently, so this is the reused producer's
        # own duplicate check being kept alive (it is recorded, not round-blocking -- the
        # same shape the pre-F-011 ``co.load_baseline`` call had).
        base = self.tmp / "dup"
        entry = write_receipt(base / "receipts" / "9001.json", 9001, LEVEL, T_A)
        current = write_json(base / "current.json",
                             tampered_readback_document([(9001, T_A)]))
        pre = write_json(base / "pre.json", {"entities": [{"id": entity_id} for entity_id in PRE_EXISTING_UNRELATED]})
        materials = cs.OwnershipMaterials(
            levelId=LEVEL, receipts=(Path(entry["path"]),), preBaseline=pre,
            currentBaseline=current, source="fixture",
            roundMaterials={"levelId": LEVEL, "window": round_window(),
                            "freshReadback": {"path": str(current)},
                            "preBaseline": {"path": str(pre)},
                            "receipts": [entry]})
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False)
        self.assertIn("BASELINE_DUPLICATE_ID",
                      [row["code"] for row in report["refusals"]])


# --------------------------------------------------------------------------- #
# dry-run / per-id states / partial results
# --------------------------------------------------------------------------- #

class DryRunAndStates(CleanupFixtureCase):

    def test_dry_run_never_dispatches_a_delete(self):
        materials = self.materials([9001, 9002], [(9001, T_A), (9002, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 9002], "req-1", dry_run=True)
        self.assertEqual(bridge.ops(), [cs.DRY_OP, cs.DRY_OP][:len(bridge.ops())])
        self.assertNotIn(cs.DELETE_OP, bridge.ops())
        self.assertEqual(report["exitCode"], cs.EXIT_CLEAN)
        self.assertTrue(report["dryRunDetail"]["mappingVerified"])
        self.assertEqual(report["stages"]["cleanup"]["status"], cs.STAGE_NOT_RUN)
        self.assertFalse(report["deletionReadback"]["performed"])

    def test_a_verified_dry_run_is_not_a_deletion_readback(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=True)
        self.assertFalse(report["deletionReadback"]["performed"])
        self.assertNotEqual(report["stages"]["cleanup"]["status"], cs.STAGE_PASS)
        per_id = report["perId"]["%d:9001" % LEVEL]
        self.assertEqual(per_id["state"], cs.STATE_NOT_ATTEMPTED)

    def test_dry_run_mapping_mismatch_refuses_before_the_delete(self):
        materials = self.materials([9001, 9002, 9003],
                                   [(9001, T_A), (9002, T_A), (9003, T_A)], pre_pairs=[])
        partial = {"ok": True, "status": "dry-run-mapping-only", "dryRun": True,
                   "requested": 3, "resolvedCount": 2,
                   "mapping": [{"id": 9001, "frontendPath": "/root/9001"},
                               {"id": 9002, "frontendPath": "/root/9002"}],
                   "invoked": False}
        bridge = FakeBridge(dry=lambda op, ids: partial)
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 9002, 9003], "req-1", dry_run=False)
        self.assertIn("DRY_RUN_MAPPING_MISMATCH",
                      [row["code"] for row in report["refusals"]])
        self.assertNotIn(cs.DELETE_OP, bridge.ops(),
                         "no verified mapping, no delete")

    def test_partial_batch_reconciles_per_id_and_keeps_untouched_ids(self):
        ids = [9001, 9002, 9003, 9004, 9005]
        materials = self.materials(ids, [(value, T_A) for value in ids], pre_pairs=[])
        bridge = FakeBridge(delete=lambda op, batch: delete_reply(
            batch, invoked_ids={9001, 9002}, broken_at=9003))
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), ids, "req-1", dry_run=False)
        per_id = {value: report["perId"]["%d:%d" % (LEVEL, value)]["state"] for value in ids}
        self.assertEqual(per_id[9001], cs.STATE_DELETED)
        self.assertEqual(per_id[9002], cs.STATE_DELETED)
        self.assertEqual(per_id[9003], cs.STATE_REFUSED)
        self.assertEqual(per_id[9004], cs.STATE_NOT_ATTEMPTED)
        self.assertEqual(per_id[9005], cs.STATE_NOT_ATTEMPTED)
        self.assertEqual(report["exitCode"], cs.EXIT_PARTIAL)
        self.assertEqual(report["residual"]["ids"], [9003, 9004, 9005])
        self.assertFalse(report["newOperation"]["automaticDispatch"])
        self.assertEqual(len(bridge.delete_calls()), 1, "one batch, one dispatch")

    def test_dispatched_but_still_present_is_unknown_not_deleted(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        # The reply says a delete was dispatched, but the object is still there.
        bridge = FakeBridge(delete=lambda op, ids: delete_reply(ids, set(ids)),
                            remove_on_invoke=False)
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False)
        per_id = report["perId"]["%d:9001" % LEVEL]
        self.assertEqual(per_id["state"], cs.STATE_UNKNOWN)
        self.assertEqual(per_id["subState"], "dispatched:still-present")
        self.assertEqual(report["exitCode"], cs.EXIT_UNKNOWN)
        self.assertEqual(len(bridge.delete_calls()), 1, "not re-sent after the read-back")

    def test_unreadable_reply_makes_the_batch_unknown_and_stops_the_rest(self):
        ids = list(range(9001, 9001 + 130))
        materials = self.materials(ids, [(value, T_A) for value in ids], pre_pairs=[])
        bridge = FakeBridge(delete=unreadable_reply)
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), ids, "req-1", dry_run=False)
        self.assertEqual([len(batch) for batch in report["batches"]], [64, 64, 2])
        self.assertEqual(report["exitCode"], cs.EXIT_UNKNOWN)
        self.assertEqual(len(bridge.delete_calls()), 1, "the unknown batch is not resent")
        self.assertEqual(report["perId"]["%d:9001" % LEVEL]["state"], cs.STATE_UNKNOWN)
        self.assertEqual(report["perId"]["%d:9130" % LEVEL]["state"],
                         cs.STATE_NOT_ATTEMPTED)

    def test_batches_never_exceed_sixty_four(self):
        ids = list(range(9001, 9001 + 130))
        materials = self.materials(ids, [(value, T_A) for value in ids], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), ids, "req-1", dry_run=False)
        self.assertTrue(all(len(batch) <= 64 for batch in report["batches"]))
        self.assertEqual([len(batch) for batch in bridge.delete_calls()], [64, 64, 2])

    def test_names_are_keyed_by_level_and_id(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=True)
        self.assertIn("%d:9001" % LEVEL, report["perId"])
        self.assertNotIn("9001", report["perId"], "an id alone is not a key")


# --------------------------------------------------------------------------- #
# checkpoint / resume
# --------------------------------------------------------------------------- #

class Resume(CleanupFixtureCase):

    def _completed_run(self, checkpoint):
        materials = self.materials([9001, 9002], [(9001, T_A), (9002, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 9002], "req-1", dry_run=False,
            checkpoint_path=checkpoint)
        return materials, bridge, report

    def test_resuming_a_completed_run_dispatches_nothing(self):
        checkpoint = self.tmp / "state" / "checkpoint.json"
        materials, bridge, first = self._completed_run(checkpoint)
        self.assertEqual(first["exitCode"], cs.EXIT_CLEAN)
        self.assertTrue(checkpoint.is_file())
        bridge.calls.clear()
        second = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 9002], "req-2", dry_run=False,
            checkpoint_path=self.tmp / "state" / "checkpoint-2.json",
            resume_from=checkpoint)
        self.assertEqual(bridge.calls, [], "a completed run resumed is a no-op")
        self.assertEqual(second["exitCode"], cs.EXIT_CLEAN)
        self.assertEqual(sorted(second["resume"]["settledSkipped"]), [9001, 9002])

    def test_unknown_outcome_is_never_resent_on_resume(self):
        checkpoint = self.tmp / "u" / "checkpoint.json"
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        first_bridge = FakeBridge(delete=unreadable_reply)
        first = self.service(materials, first_bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False, checkpoint_path=checkpoint)
        self.assertEqual(first["exitCode"], cs.EXIT_UNKNOWN)
        self.assertTrue(checkpoint.is_file())

        second_bridge = FakeBridge()          # would succeed if it were allowed to run
        second = self.service(materials, second_bridge).cleanup_owned(
            self.session(), [9001], "req-2", dry_run=False,
            checkpoint_path=self.tmp / "u" / "checkpoint-2.json", resume_from=checkpoint)
        self.assertEqual(second_bridge.calls, [],
                         "an unknown outcome must never be re-sent")
        self.assertEqual(second["exitCode"], cs.EXIT_UNKNOWN)
        self.assertIn("RESUME_UNKNOWN_NOT_RESENT",
                      [row["code"] for row in second["refusals"]])
        self.assertEqual(second["resume"]["unknownNotResent"], [9001])

    def test_not_attempted_ids_may_be_retried_under_a_new_request(self):
        checkpoint = self.tmp / "p" / "checkpoint.json"
        ids = [9001, 9002, 9003]
        materials = self.materials(ids, [(value, T_A) for value in ids], pre_pairs=[])
        first_bridge = FakeBridge(delete=lambda op, batch: delete_reply(
            batch, invoked_ids=set(), broken_at=9001))
        first = self.service(materials, first_bridge).cleanup_owned(
            self.session(), ids, "req-1", dry_run=False, checkpoint_path=checkpoint)
        self.assertEqual(first["perId"]["%d:9002" % LEVEL]["state"], cs.STATE_NOT_ATTEMPTED)

        second_bridge = FakeBridge()
        second = self.service(materials, second_bridge).cleanup_owned(
            self.session(), ids, "req-2", dry_run=False,
            checkpoint_path=self.tmp / "p" / "checkpoint-2.json", resume_from=checkpoint)
        sent = set(second_bridge.delete_calls()[0]) if second_bridge.delete_calls() else set()
        self.assertEqual(sent, {9002, 9003},
                         "only the never-sent ids are retried, under a new request id")
        # The refused id stays refused and stays in the residual: a resume does not
        # silently retry what the adapter already refused.
        self.assertEqual(second["exitCode"], cs.EXIT_PARTIAL)
        self.assertEqual(second["residual"]["ids"], [9001])
        self.assertEqual(second["checkpoint"]["written"], True)
        self.assertIn("req-2", cs.Checkpoint.load(
            self.tmp / "p" / "checkpoint-2.json").usedRequestIds)

    def test_checkpoint_for_another_level_is_refused(self):
        checkpoint_path = self.tmp / "x" / "checkpoint.json"
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        self.service(materials, FakeBridge()).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=True, checkpoint_path=checkpoint_path)
        other = self.session(level=OTHER_LEVEL)
        bridge = FakeBridge(level=OTHER_LEVEL)
        report = self.service(materials, bridge).cleanup_owned(
            other, [9001], "req-2", dry_run=False, resume_from=checkpoint_path)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("CHECKPOINT_WRONG_LEVEL",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [])


# --------------------------------------------------------------------------- #
# evidence paths
# --------------------------------------------------------------------------- #

class EvidencePaths(CleanupFixtureCase):

    def test_output_outside_the_task_root_is_refused_before_anything(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False,
            output_path=REPO / "outside-task-root.json", task_root=self.tmp)
        self.assertEqual(report["exitCode"], cs.EXIT_REFUSED)
        self.assertIn("OUTPUT_OUTSIDE_TASK_ROOT",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(bridge.calls, [], "a refused output path blocks the dispatch")

    def test_existing_output_is_never_overwritten(self):
        existing = write_json(self.tmp / "already.json", {"keep": True})
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False,
            output_path=existing, task_root=self.tmp)
        self.assertIn("OUTPUT_ALREADY_EXISTS",
                      [row["code"] for row in report["refusals"]])
        self.assertEqual(json.loads(existing.read_text(encoding="utf-8")), {"keep": True})
        self.assertEqual(bridge.calls, [])

    def test_a_failed_write_after_the_run_is_not_the_usage_code(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        service = self.service(materials, bridge)
        target = self.tmp / "will-fail.json"

        real = cs.exclusive_write_json
        calls = {"n": 0}

        def flaky(path, payload):
            calls["n"] += 1
            if Path(path) == target:
                raise OSError("simulated full disk")
            return real(path, payload)

        cs.exclusive_write_json = flaky
        try:
            report = service.cleanup_owned(self.session(), [9001], "req-1", dry_run=False,
                                           output_path=target, task_root=self.tmp)
        finally:
            cs.exclusive_write_json = real
        self.assertEqual(report["exitCode"], cs.EXIT_EVIDENCE_UNWRITTEN)
        self.assertFalse(report["outputPersisted"])
        self.assertFalse(target.exists())
        self.assertIn(cs.DELETE_OP, bridge.ops(), "the run itself did happen")

    def test_a_pass_stage_without_resolvable_evidence_is_downgraded(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        # No evidence root: the run is real, but no pointer can be written, so the tool
        # must not publish a bare ``pass``.
        service = cs.CleanupService(ownership=FakeOwnership(materials), bridge=bridge,
                                    evidence_root=None)
        report = service.cleanup_owned(self.session(), [9001], "req-1", dry_run=False)
        self.assertEqual(report["exitCode"], cs.EXIT_CLEAN)
        self.assertEqual(report["stages"]["cleanup"]["status"], cs.STAGE_BLOCKED)
        self.assertIn("evidence", report["stages"]["cleanup"]["reason"])

    def test_report_speaks_save_diff_not_persistence(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        report = self.service(materials, FakeBridge()).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=True)
        self.assertIn("saveDiff", report["stages"])
        self.assertNotIn("persistence", report["stages"])

    def test_the_reused_producer_is_the_one_hashed(self):
        hashes = cs.producer_hashes()
        self.assertIn("tools/game-executor/cleanup_owned_entities.py", hashes)
        self.assertIn("backend/cleanup_service.py", hashes)
        self.assertEqual(len(hashes["backend/cleanup_service.py"]), 64)


# --------------------------------------------------------------------------- #
# S12 orchestration
# --------------------------------------------------------------------------- #

class S12Orchestration(CleanupFixtureCase):

    def _clean_report(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        bridge = FakeBridge()
        return self.service(materials, bridge).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False), materials, bridge

    def test_reopen_is_never_pass_and_names_the_call_site(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge())
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-reopen"]
        self.assertEqual(doc["status"], cs.STAGE_NOT_RUN)
        self.assertEqual(doc["delegatedTo"], "T11")
        self.assertEqual(doc["synthetic"], False)
        self.assertTrue(any("reopen-current" in step for step in doc["request"]["callSite"]))

    def test_save_diff_is_blocked_without_an_independent_verifier(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge())
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertIn("SAVE_DIFF_VERIFIER_UNAVAILABLE",
                      json.dumps(doc["criteria"]))
        self.assertEqual(doc["synthetic"], False)

    def test_save_diff_fails_when_the_cleanup_left_owned_ids_behind(self):
        ids = [9001, 9002]
        materials = self.materials(ids, [(value, T_A) for value in ids], pre_pairs=[])
        bridge = FakeBridge(delete=lambda op, batch: delete_reply(batch, {9001}))
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), ids, "req-1", dry_run=False)
        service = self.service(materials, FakeBridge(), save_diff=_Verifier(root=self.tmp))
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertFalse(doc["criteria"]["allOwnedIdsGone"]["met"])
        self.assertNotEqual(doc["criteria"].get("saveDiff", {}).get("met"), True)

    def test_save_diff_requires_criteria_evidence_that_resolves(self):
        report, materials, _ = self._clean_report()
        # Every axis claims proven, but the pointers are fabricated.
        service = self.service(materials, FakeBridge(),
                               save_diff=_Verifier(root=self.tmp, points_resolve=False, layer="live"))
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertIn("evidence pointer", doc["statusBasis"])

    def test_save_diff_is_blocked_when_the_verifier_is_offline(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge(),
                               save_diff=_Verifier(root=self.tmp, points_resolve=True, layer="offline"))
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertIn("offline", doc["statusBasis"])

    def test_save_diff_passes_only_with_live_verification_and_resolving_evidence(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge(),
                               save_diff=_Verifier(root=self.tmp, points_resolve=True, layer="live"))
        doc = service.orchestrate_s12(self.session(), report)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_PASS)
        self.assertEqual(doc["verifiedLayer"], "live")
        axes = {name: entry for name, entry in doc["criteria"].items()
                if name != "allOwnedIdsGone"}
        self.assertEqual(len(axes), 5)
        self.assertTrue(all(entry["evidenceRefResolves"] for entry in axes.values()))

    def test_gate_status_needs_all_three_documents(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge(),
                               save_diff=_Verifier(root=self.tmp, points_resolve=True, layer="live"))
        bundle = service.orchestrate_s12(self.session(), report)
        self.assertEqual(bundle["gateStatus"], cs.STAGE_BLOCKED)
        self.assertEqual(bundle["statuses"]["cleanup-reopen"], cs.STAGE_NOT_RUN)

    def test_documents_are_written_exclusively_under_the_output_root(self):
        report, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge())
        out = self.tmp / "gate"
        bundle = service.orchestrate_s12(self.session(), report, output_root=out)
        written = bundle["written"]
        self.assertTrue(all(entry["written"] for entry in written.values()))
        for entry in written.values():
            self.assertTrue(Path(entry["path"]).is_file())
        again = service.orchestrate_s12(self.session(), report, output_root=out)
        self.assertTrue(all(entry["written"] is False for entry in again["written"].values()),
                        "existing evidence is never overwritten")

    # -- resource cleanup -------------------------------------------------- #

    def test_foreign_resources_are_refused_and_never_released(self):
        report, materials, _ = self._clean_report()
        releaser = FakeReleaser()
        own = write_json(self.tmp / "own-proof.json", {"round": "round-1"})
        foreign = write_json(self.tmp / "foreign-proof.json", {"round": "round-9"})
        ledger = FakeResources([
            cs.OwnedResource("res-own", "temp-dir", str(self.tmp / "own-dir"), "round-1",
                             cs.evidence_ref(own)),
            cs.OwnedResource("res-foreign-round", "temp-dir", str(self.tmp / "other"),
                             "round-9", cs.evidence_ref(foreign)),
            cs.OwnedResource("res-no-proof", "temp-dir", str(self.tmp / "x"), "round-1",
                             {"path": str(self.tmp / "missing.json"), "sha256": "0" * 64}),
            cs.OwnedResource("res-outside", "temp-dir", str(REPO / "backend"), "round-1",
                             cs.evidence_ref(own)),
        ])
        service = self.service(materials, FakeBridge(), resources=ledger, releaser=releaser,
                               allowed_material_roots=(self.tmp,))
        result = service.release_own_resources(self.session())
        self.assertEqual(result["perResource"]["res-own"]["state"], "released")
        self.assertEqual(result["perResource"]["res-foreign-round"]["state"], "refused")
        self.assertEqual(result["perResource"]["res-no-proof"]["state"], "refused")
        self.assertEqual(result["perResource"]["res-outside"]["state"], "refused")
        self.assertEqual(releaser.released, ["res-own"],
                         "the releaser is never called for a refused resource")

    def test_resource_cleanup_document_is_blocked_when_something_was_refused(self):
        report, materials, _ = self._clean_report()
        ledger = FakeResources([
            cs.OwnedResource("res-1", "temp", str(self.tmp / "a"), "round-9", None)])
        service = self.service(materials, FakeBridge(), resources=ledger,
                               releaser=FakeReleaser(),
                               allowed_material_roots=(self.tmp,))
        result = service.release_own_resources(self.session())
        doc = result["gateDocument"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertIn("res-1", doc["statusBasis"])

    def test_empty_resource_ledger_is_not_evidence_of_nothing(self):
        _, materials, _ = self._clean_report()
        service = self.service(materials, FakeBridge(), resources=FakeResources([]),
                               releaser=FakeReleaser())
        result = service.release_own_resources(self.session())
        self.assertEqual(result["gateDocument"]["status"], cs.STAGE_BLOCKED)
        self.assertIn("empty ledger", result["gateDocument"]["statusBasis"])

    def test_a_release_without_resolvable_evidence_is_unknown(self):
        _, materials, _ = self._clean_report()
        own = write_json(self.tmp / "proof2.json", {"round": "round-1"})
        ledger = FakeResources([cs.OwnedResource("res-1", "temp", str(self.tmp / "a"),
                                                 "round-1", cs.evidence_ref(own))])
        service = self.service(materials, FakeBridge(), resources=ledger,
                               releaser=FakeReleaser(evidence=False),
                               allowed_material_roots=(self.tmp,))
        result = service.release_own_resources(self.session())
        self.assertEqual(result["perResource"]["res-1"]["state"], "unknown")
        self.assertEqual(result["perResource"]["res-1"]["reason"],
                         "a release without an evidence pointer is not proven")


class DeliveredInterfaceAdapters(CleanupFixtureCase):
    """The DS-05 / DS-08 interfaces had NOT landed when this module was designed; they
    landed while it was being tested, so the seams are exercised against their real
    shapes rather than against a guess."""

    def test_ds08_ownership_query_is_adopted_without_widening_it(self):
        # Shape of backend.operation_state.OperationLedger.ownership(...)
        query = {
            "levelId": LEVEL,
            "owned": [{"entityId": 9001, "operationId": "op-1",
                       "journalRef": str(self.tmp / "op-1" / "receipt.json")}],
            "refused": [{"entityId": 8000, "code": "CLEANUP_ID_NOT_OWNED_BY_THIS_RUN",
                         "reason": "no create receipt of this run produced this id"}],
            "unknown": [{"entityId": 7000, "code": "TARGET_HANDLE_UNVERIFIED",
                         "reason": "the create receipt names no level"}],
        }
        receipt = write_receipt(Path(query["owned"][0]["journalRef"]), 9001, LEVEL, T_A,
                                request_id="op-1")
        # The ledger alone cannot prove "new this round", so a pre-baseline is required;
        # F-011 also requires the round's window, read-back and receipt provenance.
        pre = write_json(self.tmp / "ad" / "pre.json", {"entities": [{"id": entity_id} for entity_id in PRE_EXISTING_UNRELATED]})
        current = write_json(self.tmp / "ad" / "current.json",
                             readback_document([(9001, T_A), (8000, T_A), (7000, T_A)]))
        round_materials = {"levelId": LEVEL, "window": round_window(),
                           "freshReadback": {"path": str(current)},
                           "preBaseline": {"path": str(pre)},
                           "receipts": [receipt]}
        materials = with_round_materials(
            cs.materials_from_ownership_query(
                query, pre_baseline=pre, current_baseline=current,
                source="operation-ledger"),
            round_materials)
        self.assertIsInstance(materials, cs.OwnershipMaterials)
        bridge = FakeBridge()
        report = self.service(materials, bridge).cleanup_owned(
            self.session(), [9001, 8000, 7000], "req-1", dry_run=False)
        codes = {row["entityId"]: row["code"] for row in report["refusals"]
                 if row["entityId"] is not None}
        self.assertEqual(codes.get(8000), "CLEANUP_ID_NOT_OWNED_BY_THIS_RUN")
        self.assertEqual(codes.get(7000), "TARGET_HANDLE_UNVERIFIED")
        self.assertEqual(report["ownedIds"], [9001])
        self.assertNotIn(8000, bridge.seen_ids())
        self.assertNotIn(7000, bridge.seen_ids())

    def test_an_empty_ds08_query_is_unavailable_not_a_clean_result(self):
        query = {"levelId": LEVEL, "owned": [], "refused": [], "unknown": []}
        result = cs.materials_from_ownership_query(
            query, pre_baseline=None, current_baseline=self.tmp / "nope.json",
            source="operation-ledger")
        self.assertIsInstance(result, cs.OwnershipUnavailable)
        self.assertEqual(result.code, "OWNERSHIP_QUERY_EMPTY")

    def test_ds05_report_is_carried_over_without_being_upgraded(self):
        report_shape = {"stages": {
            "saveInvocation": {"status": "pass"},
            "savedContent": {"status": "pass"},
            "allowedDelta": {"status": "pass"},
            "unrelatedUnchanged": {"status": "blocked"},
            "saveDiff": {"status": "blocked"}}}
        verdict = cs.adapt_save_verification(report_shape, manifest={"files": {}})
        self.assertIsInstance(verdict, cs.SaveDiffVerdict)
        self.assertTrue(verdict.saveInvocation.proven)
        self.assertFalse(verdict.unrelatedUnchanged.proven)
        self.assertEqual(verdict.layer, "offline",
                         "no resolving bound file means not live")

    def test_ds05_report_without_stages_is_unavailable(self):
        verdict = cs.adapt_save_verification({"ok": True}, manifest={})
        self.assertIsInstance(verdict, cs.VerificationUnavailable)

    def test_a_ds05_shaped_verifier_reaches_pass_only_with_real_bound_files(self):
        report, materials, _ = self._clean_report()
        bound = self.tmp / "bound"
        gil_after = write_json(bound / "after.gil", {"bytes": 1})
        files = {"gilAfter": cs.evidence_ref(gil_after)}

        class Ds05Shaped:
            def __init__(self, files):
                self.files = files

            def verify_cleanup_save(self, manifest):
                self.manifest = manifest
                return {"stages": {
                    "saveInvocation": {"status": "pass"},
                    "savedContent": {"status": "pass"},
                    "allowedDelta": {"status": "pass"},
                    "unrelatedUnchanged": {"status": "pass"},
                    "saveDiff": {"status": "pass"}}}

        service = self.service(materials, FakeBridge(), save_diff=Ds05Shaped(files))
        doc = service.orchestrate_s12(self.session(), report,
                                      save_case_files=files)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_PASS)
        self.assertEqual(doc["verifiedLayer"], "live")

        # The same report with a bound file that does not resolve is NOT live evidence.
        del files["gilAfter"]
        broken = {"gilAfter": {"path": str(self.tmp / "gone.gil"), "sha256": "0" * 64}}
        doc = service.orchestrate_s12(self.session(), report,
                                      save_case_files=broken)["documents"]["cleanup-save-diff"]
        self.assertEqual(doc["status"], cs.STAGE_BLOCKED)
        self.assertEqual(doc["verifiedLayer"], "offline")

    def _clean_report(self):
        materials = self.materials([9001], [(9001, T_A)], pre_pairs=[])
        account = FakeBridge()
        report = self.service(materials, account).cleanup_owned(
            self.session(), [9001], "req-1", dry_run=False)
        return report, materials, account


class FakeReleaser:
    def __init__(self, evidence=True):
        self.released = []
        self.evidence = evidence

    def release(self, resource):
        self.released.append(resource.resourceId)
        if self.evidence:
            return cs.ReleaseOutcome("released", evidenceRef=resource.ownershipProof)
        return cs.ReleaseOutcome("released")


class FakeResources:
    def __init__(self, resources):
        self._resources = resources

    def own_resources(self, session):
        return list(self._resources)


class _Verifier:
    """A conforming DS-05 seam fixture: the four axes plus preservation.

    The stand-in files live in the test's own temporary directory, so the fixture writes
    inside the test task run root and nothing survives the case.
    """

    def __init__(self, *, root, points_resolve=False, layer="offline"):
        self.root = Path(root)
        self.points_resolve = points_resolve
        self.layer = layer

    def _ref(self, name):
        if not self.points_resolve:
            return {"path": str(REPO / ".runtime" / "does-not-exist" / name),
                    "sha256": "0" * 64}
        target = self.root / "verifier" / name
        write_json(target, {"axis": name})
        return cs.evidence_ref(target)

    def verify_cleanup_save(self, manifest):
        return cs.SaveDiffVerdict(
            saveInvocation=cs.Judgment(True, self._ref("save-invocation.json")),
            savedContent=cs.Judgment(True, self._ref("saved-content.json")),
            allowedDelta=cs.Judgment(True, self._ref("allowed-delta.json")),
            unrelatedUnchanged=cs.Judgment(True, self._ref("unrelated.json")),
            unrelatedObjectsPreserved=cs.Judgment(True, self._ref("preserved.json")),
            layer=self.layer,
            # A real file, really hashed: this module's own source stands in for the
            # verifier identity, so producerRef resolves instead of being a placeholder.
            producerRef=cs.evidence_ref(Path(__file__)),
            detail="fixture")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

class OfflineCli(CleanupFixtureCase):

    @staticmethod
    def _main(argv):
        """Run the CLI with its report capture swallowed: it prints by design."""
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cs.main(argv)
        return code, buffer.getvalue()

    def test_plan_manifest_produces_an_offline_ownership_plan(self):
        base = self.tmp / "cli"
        receipt = write_receipt(base / "receipts" / "9001.json", 9001, LEVEL, T_A)
        current = write_json(base / "current.json", readback_document([(9001, T_A)]))
        pre = write_json(base / "pre.json", {"entities": [{"id": entity_id} for entity_id in PRE_EXISTING_UNRELATED]})
        manifest = write_json(base / "manifest.json", {
            "levelId": LEVEL, "runId": ROUND_ID, "requestId": "req-cli",
            "targets": [9001], "output": str(base / "plan.json"),
            "ownership": {"receipts": [receipt["path"]], "preBaseline": str(pre),
                          "currentBaseline": str(current), "source": "fixture",
                          "roundMaterials": {"levelId": LEVEL, "window": round_window(),
                                             "freshReadback": {"path": str(current)},
                                             "preBaseline": {"path": str(pre)},
                                             "receipts": [receipt]}}})
        code, _ = self._main(["--plan-manifest", str(manifest), "--task-root", str(self.tmp)])
        self.assertEqual(code, cs.EXIT_CLEAN)
        report = json.loads((self.tmp / "cli" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual(report["ownedIds"], [9001])
        self.assertFalse(report["dryRunDetail"]["mappingVerified"],
                         "an offline plan must not claim a verified mapping")
        self.assertFalse(report["deletionReadback"]["performed"])

    def test_cli_refuses_an_execute_manifest(self):
        manifest = write_json(self.tmp / "cli2.json", {"levelId": LEVEL, "execute": True})
        self.assertEqual(self._main(["--plan-manifest", str(manifest),
                                     "--task-root", str(self.tmp)])[0], cs.EXIT_USAGE)

    def test_cli_refuses_a_missing_manifest(self):
        self.assertEqual(self._main([])[0], cs.EXIT_USAGE)

    def test_cli_never_claims_a_pass_for_the_frozen_ids(self):
        base = self.tmp / "cli3"
        frozen = sorted(cs.protected_ids_for(LEVEL))
        provenance = [write_receipt(base / "receipts" / ("%d.json" % value), value,
                                    LEVEL, T_A)
                      for value in frozen]
        current = write_json(base / "current.json",
                             readback_document([(value, T_A) for value in frozen]))
        pre = write_json(base / "pre.json", {"entities": [{"id": entity_id} for entity_id in PRE_EXISTING_UNRELATED]})
        manifest = write_json(base / "manifest.json", {
            "levelId": LEVEL, "runId": ROUND_ID, "requestId": "req-frozen",
            "targets": frozen,
            "ownership": {"receipts": [entry["path"] for entry in provenance],
                          "preBaseline": str(pre), "currentBaseline": str(current),
                          "roundMaterials": {"levelId": LEVEL, "window": round_window(),
                                             "freshReadback": {"path": str(current)},
                                             "preBaseline": {"path": str(pre)},
                                             "receipts": provenance}}})
        code, output = self._main(["--plan-manifest", str(manifest),
                                   "--task-root", str(self.tmp)])
        self.assertEqual(code, cs.EXIT_REFUSED)
        # Refused BY NAME: a forged receipt set may satisfy the three-way proof, so the
        # freeze has to be visible as its own code, not implied by a generic refusal.
        self.assertIn("CLEANUP_TARGET_UNATTRIBUTABLE", output)


if __name__ == "__main__":
    unittest.main()
