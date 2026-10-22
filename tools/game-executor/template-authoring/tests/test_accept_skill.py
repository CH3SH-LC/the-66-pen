"""Synthetic skill envelopes exercise acceptance without launching native code."""
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import accept_skill as accept
import prepare_skill as prepare
from test_skill_review import ReviewFixture
from test_currency_receipt import encode


class AcceptSkillTests(unittest.TestCase):
    def setUp(self):
        direct=accept.requests.read_json(accept.candidate.DEFAULT_RUNTIME_PROFILE)
        service=accept.requests.read_json(accept.candidate.DEFAULT_SERVICE_PROFILE)
        self.data=ReviewFixture();self.data.initialize(self)
        self.output=self.data.base/'prepared-skill'
        self.enterContext(patch.object(prepare,'OUTPUT',self.output))
        self.enterContext(patch.object(accept,'PREPARED_ROOT',self.output))
        self.data.write(self.data.runtime_path,direct);self.data.write(self.data.service_path,service)
        self.data.session['image']=str(accept.profiles.TARGET_IMAGE.resolve())
        self.data.request['session']=dict(self.data.session)
        self.data.request_path.write_bytes(accept.requests.canonical_bytes(self.data.request))
        baseline=accept.requests.read_json(self.data.baseline/'prepared.json')
        baseline['session']=dict(self.data.session);self.data.write(self.data.baseline/'prepared.json',baseline)
        self.data.review.update(session=dict(self.data.session),requestSha256=accept.profiles.sha256(self.data.request_path),
            evidenceHashes=accept.requests._baseline_hashes(self.data.baseline,'readonly'),
            runtimeProfileSha256=accept.profiles.sha256(self.data.runtime_path),
            transitiveCurrencyProfile={'path':str(self.data.service_path),'sha256':accept.profiles.sha256(self.data.service_path)},
            sourceHashes=accept.reviews.source_hashes())
        self.data.save()
        self.old_record=accept.requests.read_json(self.data.baseline/'stdout.jsonl')
        self.scene=bytes.fromhex(self.old_record['snapshotHex'])
        profile=accept.profiles.load_profile()
        inputs={'runtimeProfilePath':str(self.data.runtime_path),'runtimeProfileSha256':self.data.review['runtimeProfileSha256'],
                'serviceProfilePath':str(self.data.service_path),'serviceProfileSha256':self.data.review['transitiveCurrencyProfile']['sha256']}
        kernel,user=Mock(),Mock();kernel.GetTickCount64.return_value=1000;user.RegisterWindowMessageW.return_value=0xc456
        def fake_compile(run):
            for name in ('hook_receipt.dll','hook_receipt_probe.exe'):(run/name).write_bytes(b'SYNTHETIC NONEXECUTABLE TEST DATA')
            return 'compiler mock'
        with patch.object(prepare.candidate,'load_inputs',return_value=(self.data.request,self.scene,direct,profile,{'sha256':profile['image']['sha256']},inputs)), \
             patch.object(prepare.profiles,'validate_session',return_value=self.data.session), \
             patch.object(prepare.profiles,'windows_api',return_value=(kernel,user)), \
             patch.object(prepare.candidate,'compile_sources',side_effect=fake_compile):
            self.built=prepare.prepare(self.data.review_path)
        self.run=Path(self.built['run'])
        self.old=(0x42000009,9,0x50000,0x60000);self.added=(0x41800001,6,0x70000,0x80000)
        self.old_c=(self.old[0],self.old[0],0x42000099,0,1,4,0x90000,0xa0000)
        self.new_c=(self.added[0],self.added[0],0x41800044,0,1,4,0xb0000,0xc0000)
        self.raw=bytearray(894392)
        struct.pack_into('<4I',self.raw,0,len(self.raw),1,0,1)
        accept.native.ACTION.pack_into(self.raw,16,0,0,0,0,
            0xd0000,0xe0000,0x70000,0x80000,0xc0000,0xb0000,
            2,5,0x41800001,0x41800044,1,1,2,2,*([1]*7))
        self.raw[120:33328]=self.scene;self.raw[33328:66536]=self.scene
        self.raw[369784:632088]=self.catalog([self.old],[self.old_c])
        self.raw[632088:]=self.catalog([self.old,self.added],[self.old_c,self.new_c])
        self.record=dict(self.old_record,scope='FIXED_TEMPLATE_SKILL_ACTION',selfTestOnly=False,ok=True,
            transportOk=True,probeElevatedHigh=True,pid=9,tid=8,callbackCount=1,activeCallbacks=0,
            unhooked=True,hostPostUnhookPings=0,snapshotStatus=0)
        self.sync()
        for name in ('launch.claim','attempt.used','stderr.txt'):(self.run/name).write_bytes(b'')
        now=datetime.now(timezone.utc)
        self.data.write(self.run/'exit.json',{'executed':True,'exitCode':0,'error':None,'scope':'FIXED_TEMPLATE_SKILL_ACTION',
            'startedUtc':now.isoformat(),'finishedUtc':(now+timedelta(seconds=1)).isoformat(),'wrapperPid':234})

    def catalog(self,rows,companions):
        raw=bytearray.fromhex(encode(rows,companions,level=99))
        struct.pack_into('<Q',raw,16,struct.unpack_from('<Q',self.scene,24)[0])
        return raw

    def sync(self):
        action=accept.native.decode(bytes(self.raw))
        for key in ('defaultTable','defaultRecord','returnedResource','companionResource','observedMainClass','observedCompanionClass'):
            action[key]=hex(action[key])
        self.record.update(observedMainClass=action.pop('observedMainClass'),observedCompanionClass=action.pop('observedCompanionClass'),
                           skillResult=action,skillResultBytes=len(self.raw),skillResultHex=self.raw.hex())
        for key,at,size in (('beforeCatalog',369784,262304),('afterCatalog',632088,262304),('afterSnapshot',33328,33208)):
            self.record[key+'Bytes']=size;self.record[key+'Hex']=self.raw[at:at+size].hex()
        self.save()

    def save(self):self.data.write(self.run/'stdout.jsonl',self.record)

    def test_full_envelope_and_both_raw_registrations(self):
        with patch.object(accept.profiles,'windows_api',side_effect=AssertionError('no Windows calls')):
            result=accept.validate_run(self.run)
        self.assertTrue(result['catalogRegisteredVerified'])
        self.assertEqual((result['createdId'],result['companionOwnId']),(0x41800001,0x41800044))
        self.assertTrue(result['createCalled']);self.assertTrue(result['outcomeUncertain'])
        for key in ('persistentSaveVerified','nameVerified','defaultsVerified','gameplayVerified'):self.assertFalse(result[key])

    def test_transport_and_missing_attempt_fail(self):
        original=copy.deepcopy(self.record)
        for key,value in (('selfTestOnly',True),('scope','FIXED_TEMPLATE_ITEM_ACTION'),('pid',1),('callbackCount',2)):
            with self.subTest(key=key):
                self.record=copy.deepcopy(original);self.record[key]=value;self.save()
                with self.assertRaisesRegex(ValueError,'SKILL_NATIVE_TRANSPORT'):accept.validate_run(self.run)
        self.record=original;self.save();(self.run/'attempt.used').unlink()
        with self.assertRaisesRegex(ValueError,'SKILL_ATTEMPT_REQUIRED'):accept.validate_run(self.run)

    def test_raw_summary_and_duplicate_catalog_must_agree(self):
        self.record['skillResult']['defaultType']=1;self.save()
        with self.assertRaisesRegex(ValueError,'SKILL_RAW_SUMMARY_MISMATCH'):accept.validate_run(self.run)
        self.sync();self.record['afterCatalogHex']=self.record['beforeCatalogHex'];self.save()
        with self.assertRaisesRegex(ValueError,'SKILL_RAW_DUPLICATE_MISMATCH'):accept.validate_run(self.run)

    def test_summary_success_cannot_mask_bad_companion_or_energy_type(self):
        original=bytes(self.raw)
        mutations=((632088+160+24+4,7),(632088+160+4096*24+40+20,5))
        for at,value in mutations:
            with self.subTest(at=at):
                self.raw=bytearray(original);struct.pack_into('<I',self.raw,at,value);self.sync()
                with self.assertRaises(ValueError):accept.validate_run(self.run)

    def test_changed_compiled_profile_is_rejected(self):
        path=self.run/'target_config.h';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'SKILL_ARTIFACT_CHANGED'):accept.validate_run(self.run)

    def test_failed_attempt_preserves_create_and_partial_metadata_markers(self):
        struct.pack_into('<I',self.raw,8,0xc0000005);struct.pack_into('<I',self.raw,16,16)
        struct.pack_into('<I',self.raw,20,4);self.sync();self.record['ok']=False;self.save()
        result=accept.accept_run(self.run)
        self.assertFalse(result['ok']);self.assertTrue(result['reportedCreateCalled']);self.assertTrue(result['outcomeUncertain'])
        self.assertEqual(result['reportedActionStage'],4)
        with self.assertRaisesRegex(ValueError,'ALREADY_EXISTS'):accept.accept_run(self.run)


if __name__=='__main__':unittest.main()
