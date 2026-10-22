"""Prepare-only request tests with synthetic native baseline bytes; no game."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1]
EXECUTOR = DIRECTORY.parent
sys.path.insert(0, str(EXECUTOR / "tests"))
spec = importlib.util.spec_from_file_location("template_authoring_request", DIRECTORY / "request.py")
request_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(request_api)
import test_native_profiles as fixtures


class RequestTests(unittest.TestCase):
    def setUp(self):
        parent = request_api.OUTPUT / "tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.run = self.base / "fixture-baseline"
        self.run.mkdir()
        self.output = self.base / "output"
        self.session = dict(schemaVersion=1,pid=9,tid=8,window=7,windowClass="UnityWndClass",
                            processCreation=6,threadCreation=5,image="synthetic.invalid")
        fixture = fixtures.NativeProfileTests()
        fixture.setUp()
        record, _, prepared = fixture.fixture_receipt()
        raw = bytearray.fromhex(record["snapshotHex"])
        raw[12:16] = (1951).to_bytes(4,"little")
        raw[180:184] = (99).to_bytes(4,"little")
        record["snapshotHex"] = raw.hex()
        prepared["session"] = self.session
        prepared["levelObservationProfileSha256"] = request_api.review_api.level_api.LEVEL_PROFILE_SHA256
        for name, data in (("prepared.json",prepared),("build-result.json",{"hashes":{}}),
                           ("stdout.jsonl",record),("exit.json",{"executed":True,"exitCode":0,"error":None})):
            self.write(self.run / name, data)
        self.session_path = self.base / "session.json"
        self.write(self.session_path,self.session)
        self.output_patch = patch.object(request_api,"OUTPUT",self.output)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    @staticmethod
    def write(path,data):
        path.write_text(json.dumps(data),encoding="utf-8")

    def request(self, action="create-currency", **parameters):
        if not parameters:
            parameters = {"name":"农场金币"} if action.startswith("create-") else {"entityId":123,"templateId":1119879169}
        return request_api.make_request(action=action,run_id=self.run.name,level_id=99,
                                         session=self.session,parameters=parameters)

    def test_all_actions_prepare_canonical_evidence_without_live_identity_query(self):
        with patch.object(request_api.review_api.profiles,"query_identity",side_effect=AssertionError("no live query")), \
             patch.object(request_api.review_api.profiles,"validate_session",side_effect=AssertionError("no live validation")):
            for action in request_api.ACTIONS:
                with self.subTest(action=action):
                    request = self.request(action)
                    result = request_api.prepare(request,baseline_run=self.run)
                    data = Path(result["requestPath"]).read_bytes()
                    self.assertEqual(data,request_api.canonical_bytes(request))
                    self.assertEqual(request_api.sha256(result["requestPath"]),result["requestSha256"])
                    evidence = request_api.read_json(result["reviewEvidencePath"])
                    self.assertEqual(result["state"],"prepared-not-dispatchable")
                    self.assertFalse(any(result[k] for k in ("reviewed","dispatchable","compiled","nativeCalled")))
                    self.assertEqual(evidence["state"],"unreviewed")
                    self.assertEqual(evidence["baselineEntityCount"],1)
                    self.assertFalse(evidence["liveSessionRevalidated"])
                    self.assertIn("stdout.jsonl",evidence["baselineEvidenceHashes"])
                    if action.startswith("bind-"):
                        self.assertEqual(evidence["targetEntityFromBaseline"]["id"],123)
                        self.assertFalse(evidence["templateIdentity"]["existenceVerified"])
                        self.assertFalse(evidence["templateIdentity"]["kindVerified"])
                    else:
                        self.assertNotIn("templateId",request["parameters"])
                    if action == "create-skill":
                        self.assertNotIn("native-template-count-below-ui-limit",evidence["requiredRuntimeChecks"])
                        self.assertIn("skill-companion-registration",evidence["requiredRuntimeChecks"])

    def test_skill_default_name_and_closed_create_schema(self):
        args = request_api.parser().parse_args(["create-skill","--run-id",self.run.name,"--level-id","99",
            "--session",str(self.session_path),"--baseline-run",str(self.run)])
        self.assertEqual(args.name,"MW_FARM_PLANT")
        for key in ("source", "requestedId", "rva", "callback", "nativeLimit"):
            raw=self.request("create-skill")
            raw["parameters"][key]=123
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"CLOSED_SCHEMA"):
                request_api.validate_request(raw)

    def test_schema_rejects_arbitrary_address_kind_and_preassigned_new_id(self):
        mutations = [lambda r:r.update(rva="0xb0a90c0"),
                     lambda r:r["parameters"].update(requestedId=123),
                     lambda r:r["parameters"].update(callback=123),
                     lambda r:r["parameters"].update(subtype=11),
                     lambda r:r["session"].update(functionPointer=123),
                     lambda r:r.update(action="save")]
        for mutate in mutations:
            raw = self.request()
            mutate(raw)
            with self.subTest(value=raw),self.assertRaises(ValueError):
                request_api.prepare(raw,baseline_run=self.run)
        self.assertFalse(self.output.exists())

    def test_utf8_names_uint_ids_and_uuid_boundaries(self):
        for name in ("", "x\0y", "x"*129, "币"*43, "\ud800"):
            with self.subTest(name=repr(name)),self.assertRaises(ValueError):
                self.request(name=name)
        self.assertEqual(self.request(name="x"*128)["parameters"]["name"],"x"*128)
        self.assertEqual(self.request(name="金币🌾")["parameters"]["name"],"金币🌾")
        for value in (0,-1,True,1.5,2**32):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.request("bind-shop",entityId=123,templateId=value)
        for identifier in ("",str(uuid.UUID(int=0)),"not-uuid"):
            raw = self.request()
            raw["requestId"] = identifier
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):
                request_api.validate_request(raw)

    def test_entity_level_run_and_session_mismatches_cannot_prepare(self):
        for change in ("entity","level","run","session"):
            raw = self.request("bind-bag")
            if change == "entity":raw["parameters"]["entityId"] = 124
            elif change == "level":raw["levelId"] = 100
            elif change == "run":raw["runId"] = "different-run"
            else:raw["session"]["threadCreation"] += 1
            with self.subTest(change=change),self.assertRaises(ValueError):
                request_api.prepare(raw,baseline_run=self.run)
        self.assertFalse(self.output.exists())

    def test_partial_or_failed_baseline_not_promoted_to_ready(self):
        original = request_api.read_json(self.run/"stdout.jsonl")
        record = copy.deepcopy(original)
        raw = bytearray.fromhex(record["snapshotHex"])
        raw[8:12] = (4).to_bytes(4,"little")
        record["snapshotHex"] = raw.hex()
        self.write(self.run/"stdout.jsonl",record)
        with self.assertRaisesRegex(ValueError,"COMPLETE_RUNTIME_BASELINE_REQUIRED"):
            request_api.prepare(self.request(),baseline_run=self.run)
        self.write(self.run/"stdout.jsonl",original)
        self.write(self.run/"exit.json",{"executed":False,"exitCode":0})
        with self.assertRaisesRegex(ValueError,"BASELINE_EXECUTION_REJECTED"):
            request_api.prepare(self.request(),baseline_run=self.run)

    def test_repeated_request_never_overwrites_existing_package(self):
        raw = self.request()
        result = request_api.prepare(raw,baseline_run=self.run)
        directory = Path(result["requestPath"]).parent
        before = {p.name:p.read_bytes() for p in directory.iterdir()}
        raw["parameters"]["name"] = "changed"
        with self.assertRaisesRegex(ValueError,"REQUEST_ALREADY_PREPARED"):
            request_api.prepare(raw,baseline_run=self.run)
        self.assertEqual({p.name:p.read_bytes() for p in directory.iterdir()},before)

    def test_cli_has_no_execute_or_address_exit_and_prepares_only(self):
        argv = ["create-item","--run-id",self.run.name,"--level-id","99",
                "--session",str(self.session_path),"--baseline-run",str(self.run),"--name","种子"]
        for forbidden in ("--execute","--rva","--resource-id"):
            with self.subTest(forbidden=forbidden),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                request_api.parser().parse_args(argv+[forbidden])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = request_api.main(argv)
        result = json.loads(output.getvalue())
        self.assertEqual(code,0)
        self.assertFalse(result["nativeCalled"])
        self.assertTrue(Path(result["requestPath"]).is_relative_to(request_api.ROOT/".runtime/template-authoring"))

    def test_relative_evidence_is_repository_relative_and_duplicate_json_refused(self):
        relative = self.session_path.relative_to(request_api.ROOT)
        self.assertEqual(request_api.runtime_path(relative),self.session_path.resolve())
        self.assertEqual(request_api.ROOT,Path(__file__).resolve().parents[4])
        with self.assertRaisesRegex(ValueError,"EVIDENCE_OUTSIDE_PROJECT_RUNTIME"):
            request_api.runtime_path("GOAL.md")
        duplicated = self.base/"duplicate.json"
        duplicated.write_text('{"name":"one","name":"two"}',encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"DUPLICATE_JSON_KEY"):
            request_api.read_json(duplicated)


if __name__ == "__main__":
    unittest.main()
