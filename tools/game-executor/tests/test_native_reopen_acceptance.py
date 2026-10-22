"""Offline fixtures test evidence rejection and roundtrip comparisons, never live success."""
from pathlib import Path
import copy
from datetime import datetime, timezone, timedelta
import json
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_reopen_acceptance as api
import test_native_scheduler_coroutines as scheduler_fixture

FORMAL = api.ROOT / ".runtime/verification/interface-experiments-20260927/p02/scheduler-observation/account-baseline/Beyond_Local_Save_Level/1073741839/1073741839.gil"
#: The recorded account baseline was captured while level 1073741839 was open; the
#: live reopen pin (``api.LEVEL``) has since moved to 1073741840.  The offline tests
#: parse the *recording*, so they declare its own level instead of the live pin.
RECORDED_LEVEL = int(FORMAL.parent.name)
RECORDED_FORMAL_RELATIVE = f"Beyond_Local_Save_Level/{RECORDED_LEVEL}/{RECORDED_LEVEL}.gil"


def raw(value):
    return {"value":value, "read":dict(complete=True,truncated=False,errorCount=0,errors=[],visitedValues=1,payloadBytes=0)}


def editor_fixture(formal):
    entities=[]
    for identity,e in formal["entities"].items():
        entities.append(dict(id=identity,templateId=e.get("configurationReferenceId",e["templateId"]),category=[1,2,3,4],name="fixture",prefabId=0,
            nativeEntityType=1,nativeInstanceKind=1,transform={"unknownRole":e["transform"]},componentPresenceVerified=False,
            componentPresence=None,rawFields=raw({"parameter":"preserved"}),graphBindings=[{"id":g,"category":[1,2,3,4]} for eid,g in formal["bindings"] if eid==identity]))
    graphs=[]
    for gid,g in formal["graphs"].items():
        nodes=[dict(id=nid,definition={"id":definition,"category":[1,2,3,4]},layout={"x":raw(0),"y":raw(0)},rawFields=raw(g["parameters"][nid])) for nid,definition in g["nodes"].items()]
        edges=[dict(from_=dict(nodeId=e[0],kind=e[1],index=e[2]),to=dict(nodeId=e[3],kind=e[4],index=e[5])) for e in g["edges"]]
        for edge in edges:edge["from"]=edge.pop("from_")
        graphs.append(dict(id=gid,category=[1,2,3,4],name="fixture",nodes=nodes,nodeCount=len(nodes),links=edges,linkCount=len(edges),boundEntityIds=[e for e,gid2 in formal["bindings"] if gid2==gid],rawFields=raw({"graphParameter":"x"})))
    return dict(schemaVersion=1,levelId=api.LEVEL,scope="materialized-editor-business-fields-and-retained-initialization",ok=True,complete=True,captureComplete=True,stableReadback=True,truncated=False,errorCount=0,
        arbitraryGettersInvoked=False,nativeSerializerInvoked=False,nativeConstructorsInvoked=False,sentToGame=False,
        content=dict(entities=entities,entityCount=len(entities),graphs=graphs,graphCount=len(graphs),nodeCount=sum(g["nodeCount"] for g in graphs),linkCount=sum(g["linkCount"] for g in graphs),retainedInitialization=raw({"header":"fixture"})))


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.formal=api.formal_content(FORMAL,expected_level=RECORDED_LEVEL)
    def setUp(self):
        self.editor=editor_fixture(self.formal)
        self.native={"entities":[{"id":k,"dictionaryKey":k,"configId":v.get("configurationReferenceId",k)} for k,v in self.formal["entities"].items()],"levelCatalog":{"counts":{"dirtyByte":0}}}
    def compare(self,before=None,after=None,native=None):
        b=api.editor_content(before or self.editor);a=api.editor_content(after or self.editor)
        return api.compare_content(b,a,self.formal,native or self.native,self.native)
    def test_declared_level_still_binds_the_recording(self):
        # Declaring the wrong level for a recording is still refused: the offline
        # level parameter states *which* level the file is, it does not disable the guard.
        with self.assertRaisesRegex(ValueError,"FORMAL_LEVEL"):api.formal_content(FORMAL,expected_level=api.LEVEL)
    def test_real_formal_parser_complete_current_fixture(self):
        self.assertEqual((len(self.formal["entities"]),len(self.formal["graphs"]),len(self.formal["bindings"])),(14,3,2))
        self.assertEqual(sum(len(g["nodes"]) for g in self.formal["graphs"].values()),33)
        self.assertTrue(all(g["parameters"] for g in self.formal["graphs"].values()))
    def test_full_structure_and_roundtrip_do_not_claim_parameter_mapping(self):
        result=self.compare();self.assertTrue(result["editorRoundtripPreserved"])
        self.assertFalse(result["formalParameterMappingVerified"]);self.assertFalse(result["formalGeometryMappingVerified"])
    def test_missing_and_duplicate_entity(self):
        for duplicate in (False,True):
            x=copy.deepcopy(self.editor);rows=x["content"]["entities"]
            if duplicate: rows[1]["id"]=rows[0]["id"]
            else: rows.pop();x["content"]["entityCount"]-=1
            with self.assertRaises(ValueError):self.compare(x,x)
    def test_parameter_roundtrip_change_rejected(self):
        x=copy.deepcopy(self.editor);x["content"]["graphs"][0]["nodes"][0]["rawFields"]["value"]["changedParameter"]=7
        with self.assertRaisesRegex(ValueError,"ROUNDTRIP"):self.compare(after=x)
    def test_matching_changed_parameters_do_not_invent_formal_mapping(self):
        x=copy.deepcopy(self.editor);x["content"]["graphs"][0]["rawFields"]["value"]["graphParameter"]="different"
        self.assertFalse(self.compare(x,x)["formalParameterMappingVerified"])
    def test_edge_mismatch_against_formal(self):
        x=copy.deepcopy(self.editor);g=x["content"]["graphs"][0];g["links"][0]["from"]["index"]+=99
        with self.assertRaisesRegex(ValueError,"FORMAL_EDGES"):self.compare(x,x)
    def test_node_definition_mismatch_against_formal(self):
        x=copy.deepcopy(self.editor);x["content"]["graphs"][0]["nodes"][0]["definition"]["id"]+=1
        with self.assertRaisesRegex(ValueError,"FORMAL_NODES"):self.compare(x,x)
    def test_binding_mismatch_against_formal(self):
        x=copy.deepcopy(self.editor)
        for e in x["content"]["entities"]:e["graphBindings"]=[]
        for g in x["content"]["graphs"]:g["boundEntityIds"]=[]
        with self.assertRaisesRegex(ValueError,"FORMAL_BINDINGS"):self.compare(x,x)
    def test_native_id_or_template_mismatch(self):
        for field in ("id","configId"):
            n=copy.deepcopy(self.native);n["entities"][0][field]+=1
            with self.assertRaises(ValueError):self.compare(native=n)
    def test_dirty_after_is_not_accepted(self):
        self.native["levelCatalog"]["counts"]["dirtyByte"]=1
        with self.assertRaisesRegex(ValueError,"UNSAVED"):self.compare()
    def test_truncated_raw_or_capture_rejected(self):
        for key in ("complete","captureComplete","stableReadback"):
            x=copy.deepcopy(self.editor);x[key]=False
            with self.assertRaises(ValueError):api.editor_content(x)
        x=copy.deepcopy(self.editor);x["content"]["entities"][0]["rawFields"]["read"]["complete"]=False
        with self.assertRaises(ValueError):api.editor_content(x)


class TreeTests(unittest.TestCase):
    def fixture(self,root_id=1,child_id=2):
        return {"root":{"refId":root_id},"objects":[{"objectId":root_id,"type":"Root","fields":[{"declaringType":"Root","name":"child","value":{"refId":child_id}}]}, {"objectId":child_id,"type":"Child","fields":[{"declaringType":"Child","name":"parent","value":{"refId":root_id}}]}]}
    def test_renumbered_cycle_and_table_order_equal(self):
        a=self.fixture();b=self.fixture(17,29);b["objects"].reverse()
        self.assertEqual(api.canonical_tree(a),api.canonical_tree(b))
    def test_dangling_duplicate_and_unreachable_refused(self):
        cases=[]
        a=self.fixture();a["root"]["refId"]=3;cases.append(a)
        a=self.fixture();a["objects"].append(a["objects"][0]);cases.append(a)
        a=self.fixture();a["objects"].append({"objectId":3,"type":"orphan","fields":[]});cases.append(a)
        for a in cases:
            with self.assertRaises(ValueError):api.canonical_tree(a)
    def test_value_type_null_id_and_float_bits_preserved(self):
        a={"objectId":None,"type":"Vector","fields":[{"declaringType":"Vector","name":"x","value":{"scalarType":"System.Single","bits":"3f800000"}}]}
        self.assertEqual(api.canonical_tree(a),a)
        b=copy.deepcopy(a);b["fields"][0]["value"]["bits"]="40000000"
        self.assertNotEqual(api.canonical_tree(a),api.canonical_tree(b))


class LoadProofTests(unittest.TestCase):
    def setUp(self):
        self.fixture=scheduler_fixture.SchedulerTests();self.fixture.setUp()
        self.before=self.fixture.decode(self.fixture.fixture(kind=0))
        self.post=self.fixture.decode(self.fixture.fixture(state=4))
    def test_new_same_callback_target_state4_7_is_load_not_completion(self):
        for state in (4,5,6,7):
            self.post["rows"][0]["state"]=state
            result=api.load_progress(self.before,self.post)
            self.assertTrue(result["loadOccurred"]);self.assertFalse(result["completionVerified"])
    def test_state0_3_negative_or_missing_does_not_prove_load(self):
        for state in (-1,0,1,2,3,8):
            self.post["rows"][0]["state"]=state
            with self.assertRaises(ValueError):api.load_progress(self.before,self.post)
        with self.assertRaises(ValueError):api.load_progress(self.before,self.before)
    def test_preexisting_target_and_recycled_reference_refused(self):
        with self.assertRaises(ValueError):api.load_progress(self.post,self.post)
        b=self.fixture.decode(self.fixture.fixture(kind=2))
        with self.assertRaisesRegex(ValueError,"PREEXISTING"):api.load_progress(b,self.post)
    def test_unknown_before_or_root_change_or_partial_rejected(self):
        b=self.fixture.decode(self.fixture.fixture(kind=1))
        with self.assertRaises(ValueError):api.load_progress(b,self.post)
        self.post["pointers"]["lifecycleOwner"]="0x9990"
        with self.assertRaises(ValueError):api.load_progress(self.before,self.post)
        self.post["ok"]=False
        with self.assertRaises(ValueError):api.load_progress(self.before,self.post)


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.base=0x140000000
        self.prepared={"nativeDefinitions":{"HR_NONCE":123},"session":{"pid":10,"tid":20}}
        self.context={"pointers":{"moduleBase":hex(self.base)},"levelCatalog":{"pointers":{"levelManager":"0x50000"},"levels":[{"id":api.LEVEL,"record":0x60000}]}}
        raw=struct.pack("<4I4Q4I9II",104,1,4,7,123,self.base+0x13564e90,0x50000,0x60000,api.LEVEL,1,1,1,36,1,2,1,1,0,1,0,0,0)
        self.record=dict(scope="REVIEWED_REOPEN_ACTION",transportOk=True,reopenActionHex=raw.hex(),reopenActionBytes=104,reopenActionStatus=7,pid=10,tid=20,callbackCount=1,activeCallbacks=0,unhooked=True,businessPending=True,reopenVerified=False,persistenceVerified=False)
    def test_action_raw_does_not_claim_business_success(self):
        result=api.decode_action(self.record,self.prepared,self.context)
        self.assertTrue(result["callReturned"]);self.assertNotIn("businessVerified",result)
    def test_nonce_wrong_record_wrong_entry_or_retry_rejected(self):
        for offset,value in ((16,999),(24,self.base+0x135665f0),(40,0x60008)):
            r=dict(self.record);data=bytearray.fromhex(r["reopenActionHex"]);struct.pack_into("<Q",data,offset,value);r["reopenActionHex"]=data.hex()
            with self.assertRaises(ValueError):api.decode_action(r,self.prepared,self.context)
        r=dict(self.record,callbackCount=2)
        with self.assertRaises(ValueError):api.decode_action(r,self.prepared,self.context)
    def test_exception_pending_or_premature_verified_rejected(self):
        for offset,value in ((12,8),(72,3),(84,5),(92,1),(96,1)):
            r=dict(self.record);data=bytearray.fromhex(r["reopenActionHex"]);struct.pack_into("<I",data,offset,value);r["reopenActionHex"]=data.hex()
            with self.assertRaises(ValueError):api.decode_action(r,self.prepared,self.context)


class MissingEvidenceTests(unittest.TestCase):
    def test_missing_or_handwritten_success_cannot_pass(self):
        for index in ({},{"schemaVersion":1,"requestId":"a"*32,"businessVerified":True,"checks":{"all":True}}, {"schemaVersion":1,"requestId":"a"*32,"files":{},"runs":{}}):
            result=api.validate(index);self.assertFalse(result["reopenRoundtripVerified"]);self.assertFalse(result["businessVerified"]);self.assertFalse(result["safeToRelease"]);self.assertTrue(result["reasons"])
    def test_json_duplicate_key_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.json";p.write_text('{"ok":false,"ok":true}',encoding="utf-8")
            with self.assertRaises(ValueError):api.json_read(p)

class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,9,26,23,30,tzinfo=timezone.utc)
        self.end=self.start+timedelta(seconds=10)
        x=dict(started=True,active=True,managerSameReference=True,originalReceiverOrderPreserved=True,builtinBeforeOwnObserver=True,ownReceiverCount=1,source="received-1022-packet-observer",overflow=False,parseErrors=0,evidenceErrors=0,threadErrors=0,droppedEvents=0,currentPayloadPresent=True,currentLevelId=api.LEVEL,baselineLevelId=api.LEVEL,retainedEvents=0,sequence=0,events=[],observationId="a"*32,initStartedUtc=(self.start-timedelta(seconds=5)).isoformat(),currentPayloadSameReference=True)
        self.before=dict(ok=True,active=True,observerRegistered=True,originalReceiversPreserved=True,callbackErrors=0,contractRejectedCallbacks=0,observerCleanupError=None,levelInitialization=x)
        self.after=copy.deepcopy(self.before);a=self.after["levelInitialization"]
        a.update(retainedEvents=1,sequence=1,currentPayloadSameReference=False,events=[dict(sequence=1,parsed=True,error=None,levelId=api.LEVEL,receivedUtc=(self.start+timedelta(seconds=1)).isoformat())])
    def validate(self):return api.observer_evidence(self.before,self.after,self.start,self.end)
    def test_fresh_init_is_auxiliary_not_load_proof(self):
        self.assertTrue(self.validate()["freshInitializationBound"]);self.assertFalse(self.validate()["loadProof"])
    def test_old_cache_or_history_cannot_pass(self):
        self.after["levelInitialization"]["currentPayloadSameReference"]=True
        with self.assertRaises(ValueError):self.validate()
    def test_old_event_wrong_level_multiple_event_refused(self):
        for key,value in (("receivedUtc",(self.start-timedelta(seconds=1)).isoformat()),("levelId",1073741838),("parsed",False)):
            current=copy.deepcopy(self.after);self.after["levelInitialization"]["events"][0][key]=value
            with self.assertRaises(ValueError):self.validate()
            self.after=current
        a=self.after["levelInitialization"];a["events"].append(dict(a["events"][0],sequence=2));a.update(sequence=2,retainedEvents=2)
        with self.assertRaises(ValueError):self.validate()
    def test_overflow_and_error_count_cannot_be_asserted_away(self):
        for key,value in (("overflow",True),("parseErrors",1),("evidenceErrors",1),("threadErrors",1)):
            current=copy.deepcopy(self.after);self.after["levelInitialization"][key]=value
            with self.assertRaises(ValueError):self.validate()
            self.after=current


class IpcTests(unittest.TestCase):
    def fixture(self):
        rows=[dict(OwningProcess=10,State="Established",LocalAddress="127.0.0.1",LocalPort=100,RemoteAddress="127.0.0.1",RemotePort=200),dict(OwningProcess=20,State="Established",LocalAddress="127.0.0.1",LocalPort=200,RemoteAddress="127.0.0.1",RemotePort=100)]
        return dict(endpoints=rows,processes=[dict(pid=10,creationFileTime=1000),dict(pid=20,creationFileTime=2000)])
    def test_reciprocal_same_connection(self):
        self.assertTrue(api.ipc_evidence(self.fixture(),self.fixture(),20,10)["ipcIdentityPreserved"])
    def test_pid_reuse_or_missing_peer_rejected(self):
        a=self.fixture();a["processes"][0]["creationFileTime"]+=1
        with self.assertRaises(ValueError):api.ipc_evidence(self.fixture(),a,20,10)
        a=self.fixture();a["endpoints"].pop()
        with self.assertRaises(ValueError):api.ipc_evidence(self.fixture(),a,20,10)


class AccountTests(unittest.TestCase):
    def test_actual_immutable_backup_is_complete(self):
        p=FORMAL.parents[2].parent / "account-baseline-manifest.json"
        result=api.read_account(p,formal_relative=RECORDED_FORMAL_RELATIVE)
        self.assertEqual(len(result["rows"]),38)
        self.assertEqual(result["rows"][RECORDED_FORMAL_RELATIVE.casefold()][1],api.sha(FORMAL))
    def test_omitted_or_changed_account_file_refused(self):
        p=FORMAL.parents[2].parent / "account-baseline-manifest.json"
        source=api.json_read(p)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"manifest.json"
            bad=copy.deepcopy(source);bad["files"].pop();out.write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):api.read_account(out,formal_relative=RECORDED_FORMAL_RELATIVE)
            bad=copy.deepcopy(source);bad["files"][0]["sha256"]="0"*64;out.write_text(json.dumps(bad),encoding="utf-8")
            with self.assertRaises(ValueError):api.read_account(out,formal_relative=RECORDED_FORMAL_RELATIVE)

if __name__=="__main__":unittest.main(verbosity=2)
