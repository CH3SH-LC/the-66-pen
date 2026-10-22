"""Offline evidence-gate tests; synthetic files only, no game access or UAC."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import copy,json,os,subprocess,sys,tempfile,unittest,uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_scene_profile as builder
import native_profiles as profiles
import native_write_review as gate
import test_native_profiles as fixtures

class WriteReviewTests(unittest.TestCase):
    def setUp(self):
        parent=profiles.ROOT/'.runtime/verification/update-repair-20260925/native-write/test-fixtures'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.run=self.base/'baseline';self.run.mkdir()
        self.session=dict(schemaVersion=1,pid=9,tid=8,window=7,windowClass='UnityWndClass',processCreation=6,threadCreation=5,image='synthetic.invalid')
        fixture=fixtures.NativeProfileTests();fixture.setUp();record,self.snapshot,prepared=fixture.fixture_receipt()
        prepared['session']=self.session
        prepared['levelObservationProfileSha256']=gate.level_api.LEVEL_PROFILE_SHA256
        raw=bytearray.fromhex(record['snapshotHex']);raw[12:16]=(1951).to_bytes(4,'little');raw[180:184]=(99).to_bytes(4,'little');record['snapshotHex']=raw.hex()
        for name,value in [('prepared.json',prepared),('build-result.json',{'hashes':{}}),('stdout.jsonl',record),('exit.json',dict(executed=True,exitCode=0,error=None))]:self.write(self.run/name,value)
        self.user=self.base/'user';target=self.user/'AppData/LocalLow/miHoYo/原神/BeyondLocal/12345/Beyond_Local_Save_Level/99/99.gil';target.parent.mkdir(parents=True);target.write_bytes(b'PRIVATE_TEST_FIXTURE_NOT_A_GIL')
        backup=self.base/'backup.gil';backup.write_bytes(target.read_bytes())
        self.request={'action':'save','levelId':99};self.now=datetime.now(timezone.utc)
        self.review={'schemaVersion':1,'kind':'native-write-review-v1','state':'reviewed','reviewedBy':'coordinator','reviewId':str(uuid.uuid4()),'profileId':gate.load_write_profile()['profileId'],'writeProfileSha256':gate.WRITE_PROFILE_SHA256,'readonlyProfileSha256':profiles.PROFILE_SHA256,'levelId':99,'requestSha256':gate.canonical_hash(self.request),'session':self.session,'reviewedAtUtc':self.now.isoformat(),'expiresUtc':(self.now+timedelta(minutes=5)).isoformat(),'baselineRun':str(self.run),'baselineKind':'readonly','evidenceHashes':{name:profiles.sha256(self.run/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')},'recovery':{'source':str(target),'backup':str(backup),'sha256':profiles.sha256(backup)},'protectedGils':[]}
        self.path=self.base/'review.json'
    def write(self,path,value):path.write_text(json.dumps(value),encoding='utf-8')
    def validate(self):
        self.write(self.path,self.review)
        with patch.dict(os.environ,{'USERPROFILE':str(self.user)}):return gate.validate_review(self.path,self.session,99,self.request,now=self.now)
    def test_missing_review_rejects_before_session_or_compile(self):
        for action in ('create','create-batch','save'):
            with self.subTest(action=action),patch.object(builder,'resolve_session',side_effect=AssertionError('must not query')),self.assertRaisesRegex(ValueError,'NATIVE_WRITE_REVIEW_REQUIRED'):
                builder.build_profile(action,level_id=99)
    def test_explicit_level_or_environment_required(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaisesRegex(ValueError,'Explicit'):builder.resolve_level()
        with patch.dict(os.environ,{'MILIASTRA_LEVEL':'99'}):self.assertEqual(builder.resolve_level(),99)
    def test_current_session_reference_revalidated(self):
        self.write(self.path,self.session)
        with patch.object(builder,'CURRENT_SESSION',self.path),patch.object(profiles,'validate_session',side_effect=profiles.ProfileError('SESSION_CHANGED:tid')),self.assertRaisesRegex(profiles.ProfileError,'SESSION_CHANGED'):
            builder.resolve_session()
    def test_synthetic_complete_evidence_accepted(self):
        result=self.validate();self.assertEqual(result['baseline']['entities'][0]['configId'],20001034)
    def test_review_identity_request_level_expiry_reject(self):
        original=copy.deepcopy(self.review)
        for key,value,reason in [('requestSha256','bad','REQUEST'),('levelId',100,'LEVEL'),('writeProfileSha256','bad','PROFILE'),('state','draft','REVIEW'),('expiresUtc',(self.now-timedelta(seconds=1)).isoformat(),'EXPIRED')]:
            self.review=copy.deepcopy(original);self.review[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,reason):self.validate()
        self.review=copy.deepcopy(original);self.review['session']['threadCreation']+=1
        with self.assertRaisesRegex(profiles.ProfileError,'SESSION'):self.validate()
    def test_partial_raw_snapshot_rejects_even_if_hashes_refreshed(self):
        record=gate.read_json(self.run/'stdout.jsonl');raw=bytearray.fromhex(record['snapshotHex']);raw[8:12]=(4).to_bytes(4,'little');record['snapshotHex']=raw.hex();self.write(self.run/'stdout.jsonl',record)
        self.review['evidenceHashes']['stdout.jsonl']=profiles.sha256(self.run/'stdout.jsonl')
        with self.assertRaisesRegex(profiles.ProfileError,'COMPLETE_RUNTIME_BASELINE_REQUIRED'):self.validate()
    def test_missing_or_different_observed_level_rejects(self):
        record=gate.read_json(self.run/'stdout.jsonl')
        for level,flags in ((100,1951),(0,927)):
            raw=bytearray.fromhex(record['snapshotHex']);raw[12:16]=flags.to_bytes(4,'little');raw[180:184]=level.to_bytes(4,'little');record['snapshotHex']=raw.hex();self.write(self.run/'stdout.jsonl',record)
            self.review['evidenceHashes']['stdout.jsonl']=profiles.sha256(self.run/'stdout.jsonl')
            with self.subTest(level=level),self.assertRaises(profiles.ProfileError):self.validate()
    def test_evidence_mutation_rejects(self):
        (self.run/'stdout.jsonl').write_text('{}')
        with self.assertRaisesRegex(profiles.ProfileError,'EVIDENCE_CHANGED'):self.validate()
    def test_formal_or_recovery_change_rejects(self):
        for key in ('source','backup'):
            target=Path(self.review['recovery'][key]);previous=target.read_bytes();target.write_bytes(b'changed')
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,'RECOVERY'):self.validate()
            target.write_bytes(previous)
    def test_temporary_or_other_account_gil_rejected(self):
        original=self.review['recovery']['source']
        formal=Path(original)
        for invalid in (formal.parent.parent/'Temp'/'99.gil',formal.parent.parent/'99.gil'):
            self.review['recovery']['source']=str(invalid)
            with self.subTest(path=str(invalid)),self.assertRaisesRegex(profiles.ProfileError,'TARGET_GIL_PATH'):self.validate()
        self.review['recovery']['source']=original
        self.review['protectedGils']=[str(self.user/'AppData/LocalLow/miHoYo/原神/BeyondLocal/54321/Beyond_Local_Save_Level/98/98.gil')]
        with self.assertRaisesRegex(profiles.ProfileError,'PROTECTED_GIL_PATH'):self.validate()
        self.review['protectedGils']=[str(formal.parent.parent/'98'/'98.gil')]
        self.assertEqual(len(self.validate()['protectedGils']),1)
    def test_failed_real_readonly_run_cannot_be_baseline(self):
        failed=profiles.ROOT/'.runtime/verification/update-repair-20260925/native-live/20260925-130734-299fa4df9e'
        if not failed.is_dir():self.skipTest('historical live failure evidence absent')
        with self.assertRaisesRegex(profiles.ProfileError,'BASELINE_EXECUTION_REJECTED'):gate.load_baseline(failed,'readonly',99)
    def test_inspect_uses_complete_receipt_and_requested_level(self):
        import scene_cli
        record=gate.read_json(self.run/'stdout.jsonl')
        snapshot=gate.readonly.load_decoder().decode_snapshot(record)
        profile=dict(run=str(self.run),action='inspect',expectedLevelId=99)
        cases=[('valid',None),('wrong_level',100),('absent_level',None),('bad_transport',None),('bad_identity',None),('missing_anchor_evidence',None),('unstable_dict',None)]
        for name,level in cases:
            rec=copy.deepcopy(record);snap=copy.deepcopy(snapshot);prof=copy.deepcopy(profile)
            if name=='wrong_level':prof['expectedLevelId']=level
            elif name=='absent_level':snap['levelObservation']['verified']=False
            elif name=='bad_transport':rec['transportOk']=False
            elif name=='bad_identity':rec['pid']+=1
            elif name=='missing_anchor_evidence':snap['flags']['value']&=~1
            elif name=='unstable_dict':snap['counts']['entityVersionAfter']+=1
            with self.subTest(case=name),patch.object(scene_cli,'execute_profile',return_value=dict(record=rec,before=snap,after=None)),patch.object(scene_cli,'write_json'),patch.object(scene_cli,'preserve_gils',side_effect=AssertionError('inspect cannot preserve/write GIL')):
                result=scene_cli.run_profile(prof)
                self.assertEqual(result['ok'],name=='valid');self.assertEqual(result['levelId'],99);self.assertFalse(result['mutationAttempted']);self.assertEqual(result['called'],0)
    def test_cli_prepare_refusal_has_no_run(self):
        commands=[['scene_cli.py','create','--template-id','20001034','--position','0','0','0'],['scene_cli.py','save'],['scene_chain.py',str(profiles.ROOT/'tools/game-executor/plans/mw-mvp-decor-200.json')]]
        for args in commands:
            result=subprocess.run([sys.executable,str(profiles.ROOT/'tools/game-executor'/args[0]),*args[1:],'--level-id','99','--prepare-only'],capture_output=True,text=True,encoding='utf-8')
            with self.subTest(command=args[0:2]):
                self.assertEqual(result.returncode,2);data=json.loads(result.stdout);self.assertFalse(data['ok']);self.assertIn('NATIVE_WRITE_REVIEW_REQUIRED',data['error']);self.assertIsNone(data.get('run'))

if __name__=='__main__':unittest.main(verbosity=2)
