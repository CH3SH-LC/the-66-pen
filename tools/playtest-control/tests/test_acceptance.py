"""Independent byte fixtures; no game or desktop access. Unified gate only."""
import binascii,hashlib,json,struct,sys,tempfile,unittest,zlib
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import acceptance_contract as c
import acceptance_build as build
import acceptance_receipt as receipt
import contract
import test_observation as old_tests
class Fixture:
    @staticmethod
    def png(width=1,height=1,extra=b''):
        def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',binascii.crc32(k+v)&0xffffffff)
        return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\x10\x20\xff'*height+extra))+chunk(b'IEND',b'')
    @staticmethod
    def raw(operation=1):
        result=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=1,stage=3,operation=operation,resourcesReleased=1,dictionaryStable=1)
        h.update(pageEnd=1,count=1,entryCapacity=1) if operation==1 else h.update(width=1,height=1,pngBytes=len(Fixture.png()))
        struct.pack_into('<24I',result,0,*(h[k] for k in c.HEADER));old=old_tests.ObservationTests();result[96:432]=old.raw(old.evidence())
        for offset in (432,512):struct.pack_into('<6Q8I',result,offset,1,2,3,4,0x10000,0x20000,7,1,1,1,0,1,9,0)
        if operation==1:struct.pack_into('<4Q14I9fI',result,592,0x30000,0x40000,0x50000,0x60000,7,0,0,0,1,1,0x13a39720,0,2001,2,1,1,1,0,1,2,3,10,20,30,11,22,33,0)
        else:result[c.PNG_OFFSET:c.PNG_OFFSET+h['pngBytes']]=Fixture.png()
        return result
class RuntimeTests(unittest.TestCase):
    def test_actual_entity_fields(self):
        e=c.parse(Fixture.raw());x=c.interpret(e,1843,0);self.assertEqual(x['entities'][0]['configId'],2001);self.assertEqual(x['entities'][0]['actualWorldPosition'],[11,22,33]);self.assertIsNone(x['entities'][0]['health'])
    def test_editor_avatar_no_trial_attribution(self):
        x=c.interpret(c.parse(Fixture.raw()),1843,0);self.assertFalse(x['playerBelongsToTargetLevel']);self.assertFalse(x['runtimeTrialAttributionProven']);self.assertFalse(x['entities'][0]['belongsToTargetTrial'])
    def test_runtime_scene_guid_not_level_proof(self):
        x=c.interpret(c.parse(Fixture.raw()),1843,0);self.assertEqual(x['runtimeLevelContext']['levelGuid'],3);self.assertFalse(x['playStateProven'])
    def test_unknown_health_and_ai(self):
        x=c.interpret(c.parse(Fixture.raw()),1843,0);self.assertFalse(x['monsterHealthVerified']);self.assertFalse(x['monsterAiVerified'])
    def test_page_complete(self):self.assertTrue(c.interpret(c.parse(Fixture.raw()),1843,0)['allEntriesCovered'])
    def test_more_pages_explicit(self):
        r=Fixture.raw();struct.pack_into('<I',r,80,2)
        for at in (432,512):struct.pack_into('<I',r,at+68,2)
        x=c.interpret(c.parse(r),1843,0);self.assertEqual(x['nextPageStart'],1);self.assertFalse(x['allEntriesCovered']);self.assertFalse(x['snapshotAcrossPages'])
    def test_count_over_capacity(self):
        r=Fixture.raw();struct.pack_into('<I',r,72,129)
        with self.assertRaisesRegex(ValueError,'CAPACITY'):c.parse(r)
    def test_wrong_page_binding(self):
        with self.assertRaisesRegex(ValueError,'PAGE_BOUNDS'):c.interpret(c.parse(Fixture.raw()),1843,2)
    def test_changed_context_rejected(self):
        r=Fixture.raw();struct.pack_into('<I',r,512+72,10)
        with self.assertRaisesRegex(ValueError,'STABILITY'):c.interpret(c.parse(r),1843,0)
    def test_unknown_position_not_zero_position(self):
        r=Fixture.raw();struct.pack_into('<I',r,592+40,1);x=c.interpret(c.parse(r),1843,0);self.assertIsNone(x['entities'][0]['actualWorldPosition'])
    def test_wrong_origin_rejected(self):
        r=Fixture.raw();struct.pack_into('<f',r,592+112,900)
        with self.assertRaisesRegex(ValueError,'ORIGIN'):c.parse(r)
    def test_padding_rejected(self):
        r=Fixture.raw();r[592+124]=1
        with self.assertRaisesRegex(ValueError,'RESERVED'):c.parse(r)
    def test_unused_record_rejected(self):
        r=Fixture.raw();r[592+128]=1
        with self.assertRaisesRegex(ValueError,'UNUSED_ENTITY'):c.parse(r)
    def test_native_boolean_rejected(self):
        r=Fixture.raw();struct.pack_into('<I',r,592+72,2)
        with self.assertRaisesRegex(ValueError,'RUNTIME_STATE'):c.parse(r)
    def test_runtime_frame_smuggling(self):
        r=Fixture.raw();struct.pack_into('<I',r,56,1);r[c.PNG_OFFSET]=1
        with self.assertRaisesRegex(ValueError,'RUNTIME_CONTAINS_FRAME'):c.parse(r)
class FrameTests(unittest.TestCase):
    def test_png_native_bytes(self):self.assertEqual(c.png_info(Fixture.png(),1,1)['width'],1)
    def test_frame_capture_not_visual_pass(self):
        x=c.interpret(c.parse(Fixture.raw(2)),1843,0);self.assertTrue(x['renderFrameCaptured']);self.assertFalse(x['visualAcceptanceVerified']);self.assertIn('not-guaranteed',x['frameFreshness'])
    def test_target_mismatch(self):
        with self.assertRaisesRegex(ValueError,'FRAME_TARGET'):c.interpret(c.parse(Fixture.raw(2)),1842,0)
    def test_resource_not_released(self):
        r=Fixture.raw(2);struct.pack_into('<I',r,28,0)
        with self.assertRaisesRegex(ValueError,'RESOURCE'):c.interpret(c.parse(r),1843,0)
    def test_png_crc(self):
        r=bytearray(Fixture.png());r[-1]^=1
        with self.assertRaisesRegex(ValueError,'CRC'):c.png_info(r,1,1)
    def test_png_dimension_mismatch(self):
        with self.assertRaisesRegex(ValueError,'DIMENSIONS'):c.png_info(Fixture.png(),2,1)
    def test_png_trailing_bytes(self):
        with self.assertRaisesRegex(ValueError,'IEND'):c.png_info(Fixture.png()+b'x',1,1)
    def test_decompression_bound(self):
        with self.assertRaisesRegex(ValueError,'DEFLATE_SIZE'):c.png_info(Fixture.png(extra=b'X'*10000),1,1)
    def test_unfinished_png(self):
        with self.assertRaisesRegex(ValueError,'MISSING_IEND'):c.png_info(Fixture.png()[:-12],1,1)
    def test_unused_png(self):
        r=Fixture.raw(2);r[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED_PNG'):c.parse(r)
    def test_invalid_deflate_is_structured_error(self):
        data=bytearray(Fixture.png());size=struct.unpack_from('>I',data,33)[0];data[41:41+size]=b'x'*size
        struct.pack_into('>I',data,41+size,binascii.crc32(data[37:41+size])&0xffffffff)
        with self.assertRaisesRegex(ValueError,'PNG_DEFLATE_INVALID'):c.png_info(data,1,1)
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        out=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/tests';out.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=out);self.addCleanup(self.temp.cleanup);self.run=Path(self.temp.name)
        self.prepared=dict(session=dict(pid=123,tid=456),targetLevelId=1843,mode='runtime-state',nonce='12345',deadlineTick=67890,pageStart=0)
        self.raw=Fixture.raw();self.exit=dict(scope='FIXED_PLAYTEST_ACCEPTANCE',executed=True,exitCode=0,error=None)
        self.record=dict(scope='FIXED_PLAYTEST_ACCEPTANCE',ok=True,selfTestOnly=False,pid=123,tid=456,receiptNonce='12345',receiptDeadline='67890',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True)
    def decode(self,overrides=None):
        record=dict(self.record,acceptanceHeaderHex=self.raw[:96].hex(),acceptanceSha256=hashlib.sha256(self.raw).hexdigest());record.update(overrides or {})
        (self.run/'acceptance.bin').write_bytes(self.raw);(self.run/'stdout.jsonl').write_text(json.dumps(record),encoding='utf-8');(self.run/'exit.json').write_text(json.dumps(self.exit),encoding='utf-8')
        return receipt.decode_bound(self.run,self.prepared)
    def test_valid_runtime_receipt(self):
        x=self.decode();self.assertTrue(x['ok']);self.assertTrue(x['readOnly']);self.assertTrue(x['cleanupVerified']);self.assertFalse(x['playStateProven'])
    def test_nonce_binding(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(dict(receiptNonce='54321'))
    def test_deadline_binding(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(dict(receiptDeadline='98765'))
    def test_protocol_binding(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(dict(receiptProtocol=21))
    def test_pid_binding(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_TARGET'):self.decode(dict(pid=124))
    def test_header_binding(self):
        with self.assertRaisesRegex(ValueError,'HEADER_BINDING'):self.decode(dict(acceptanceHeaderHex='00'*96))
    def test_full_binary_hash_binding(self):
        digest=hashlib.sha256(self.raw).hexdigest();self.raw[592+64]^=1
        with self.assertRaisesRegex(ValueError,'SHA256_BINDING'):self.decode(dict(acceptanceSha256=digest))
    def test_operation_binding(self):
        self.prepared['mode']='render-frame'
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_target_binding(self):
        self.prepared['targetLevelId']=1842
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_page_binding(self):
        self.prepared['pageStart']=128
        with self.assertRaisesRegex(ValueError,'PAGE_BOUNDS'):self.decode()
    def test_seh_keeps_uncertainty(self):
        struct.pack_into('<I',self.raw,12,0xc0000005);x=self.decode();self.assertFalse(x['ok']);self.assertFalse(x['safeToRelease']);self.assertTrue(x['outcomeUncertain'])
    def test_embedded_observer_seh_keeps_uncertainty(self):
        struct.pack_into('<I',self.raw,96+12,0xc0000005);self.assertFalse(self.decode()['safeToRelease'])
    def test_live_callback_keeps_uncertainty(self):self.assertFalse(self.decode(dict(activeCallbacks=1))['safeToRelease'])
    def test_failed_native_can_prove_cleanup(self):
        struct.pack_into('<I',self.raw,8,2);x=self.decode(dict(ok=False));self.assertFalse(x['ok']);self.assertTrue(x['safeToRelease'])
    def test_resources_unreleased_keeps_uncertainty(self):
        struct.pack_into('<I',self.raw,28,0);self.assertFalse(self.decode()['safeToRelease'])
    def test_exit_failure_retains_binary_evidence(self):
        self.exit['exitCode']=1;x=self.decode();self.assertFalse(x['ok']);self.assertIn('binaryReceiptSha256',x);self.assertTrue(x['safeToRelease'])
    def test_wrapper_refusal_without_attempt(self):
        self.exit.update(executed=False,error='PREPARATION_EXPIRED');x=self.decode();self.assertFalse(x['nativeStarted']);self.assertTrue(x['safeToRelease'])
    def test_wrapper_refusal_cannot_hide_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('claimed')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_frame_extract_and_explicit_side_effect(self):
        self.prepared['mode']='render-frame';self.raw=Fixture.raw(2);x=self.decode();self.assertTrue(x['ok']);self.assertFalse(x['readOnly']);self.assertTrue(x['mutatesTemporaryRenderResources']);self.assertIsNone(x['mutatedGameState']);self.assertEqual((self.run/'frame.png').read_bytes(),Fixture.png());self.assertTrue(self.decode()['ok'])
    def test_never_replace_existing_different_frame(self):
        self.prepared['mode']='render-frame';self.raw=Fixture.raw(2);(self.run/'frame.png').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError,'FRAME_EXTRACTION_CHANGED'):self.decode()
        self.assertEqual((self.run/'frame.png').read_bytes(),b'preserve')
class BuildTests(unittest.TestCase):
    def test_enter_refused_before_disk_or_game(self):
        from types import SimpleNamespace
        with patch.object(build.p,'verify_disk',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError,'UNPROVEN_CONTROL'):build.prepare(SimpleNamespace(operation='enter'))
    def test_exit_refused_before_disk_or_game(self):
        from types import SimpleNamespace
        with patch.object(build.p,'verify_disk',side_effect=AssertionError('must not run')):
            with self.assertRaisesRegex(ValueError,'UNPROVEN_CONTROL'):build.prepare(SimpleNamespace(operation='exit'))
    def test_candidate_raw_binary_and_abi(self):
        root=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/tests';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            run=Path(temp);build.copy_sources(run);header=(run/'candidate-source/native/hook_receipt_protocol.h').read_text();probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
            self.assertIn('kReceiptVersion=24',header);self.assertIn('AcceptanceReceipt acceptance;',header);self.assertIn('acceptanceHeaderHex',probe);self.assertIn('acceptanceSha256',probe);self.assertIn('CALG_SHA_256',probe);self.assertIn('CREATE_NEW',probe);self.assertIn('std::memset(receipt, 0, sizeof(*receipt));',probe)
    def test_no_target_access_in_prepare(self):
        text=(HERE/'acceptance_build.py').read_text();self.assertNotIn('p.validate_session(',text);self.assertNotIn('p.discover(',text)
if __name__=='__main__':unittest.main()
