"""Card binding and cleanup semantics against saved synthetic raw receipts."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import receipt
import test_observation as fixtures
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        out=ROOT/'.runtime/playtest-control-20261016/tests';out.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=out);self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name)
        self.prepared=dict(kind='playtest-control-prepared-v1',action=17,launchable=True,compileOnly=False,session=dict(pid=123,tid=456),targetLevelId=1843,nonce='987',deadlineTick=321)
        self.e=fixtures.ObservationTests().evidence()
        self.record=dict(ok=True,scope='FIXED_PLAYTEST_OBSERVATION',selfTestOnly=False,pid=123,tid=456,receiptNonce='987',receiptDeadline='321',receiptProtocol=21,observationBytes=336,callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True)
        self.exit=dict(scope='FIXED_PLAYTEST_OBSERVATION',executed=True,exitCode=0,error=None)
        self.mock=patch.object(receipt,'manifest',return_value=(self.run,self.prepared,{}));self.mock.start();self.addCleanup(self.mock.stop)
    def decode(self):
        self.record['observationHex']=fixtures.ObservationTests().raw(self.e).hex()
        (self.run/'stdout.jsonl').write_text(json.dumps(self.record),encoding='utf-8');(self.run/'exit.json').write_text(json.dumps(self.exit),encoding='utf-8')
        return receipt.decode(self.run)
    def test_valid(self):
        x=self.decode();self.assertTrue(x['ok']);self.assertTrue(x['safeToRelease']);self.assertFalse(x['playerBelongsToTargetLevel'])
    def test_nonce(self):
        self.record['receiptNonce']='999'
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode()
    def test_deadline(self):
        self.record['receiptDeadline']='999'
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode()
    def test_protocol(self):
        self.record['receiptProtocol']=20
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode()
    def test_pid(self):
        self.record['pid']=124
        with self.assertRaisesRegex(ValueError,'RECEIPT_TARGET'):self.decode()
    def test_scope(self):
        self.record['scope']='IDENTITY_RECEIPT_ONLY'
        with self.assertRaisesRegex(ValueError,'RECEIPT_SCOPE'):self.decode()
    def test_selftest_not_live(self):
        self.record['selfTestOnly']=True
        with self.assertRaisesRegex(ValueError,'RECEIPT_SCOPE'):self.decode()
    def test_target_binding(self):
        self.e['targetLevel']=1842
        with self.assertRaisesRegex(ValueError,'LEVEL_BINDING'):self.decode()
    def test_size_binding(self):
        self.record['observationBytes']=337
        with self.assertRaisesRegex(ValueError,'RECEIPT_BYTES'):self.decode()
    def test_seh_not_safe(self):
        self.e['seh']=0xc0000005;x=self.decode();self.assertFalse(x['ok']);self.assertFalse(x['safeToRelease']);self.assertTrue(x['outcomeUncertain'])
    def test_active_callback(self):
        self.record['activeCallbacks']=1;x=self.decode();self.assertFalse(x['safeToRelease'])
    def test_unhook_required(self):
        self.record['unhooked']=False;x=self.decode();self.assertFalse(x['safeToRelease'])
    def test_callback_count(self):
        self.record['callbackCount']=2;self.assertFalse(self.decode()['safeToRelease'])
    def test_exit_failed(self):
        self.exit['exitCode']=1;x=self.decode();self.assertFalse(x['ok']);self.assertTrue(x['safeToRelease'])
    def test_native_refusal_retains_cleanup(self):
        self.e.update(status=1,stage=1,nativeCalls=0);self.record['ok']=False;x=self.decode();self.assertFalse(x['ok']);self.assertTrue(x['safeToRelease']);self.assertFalse(x['called'])
    def test_wrapper_no_execution(self):
        self.exit.update(executed=False,error='EXPIRED');x=self.decode();self.assertFalse(x['nativeStarted']);self.assertTrue(x['safeToRelease'])
    def test_wrapper_false_but_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('claimed')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()
    def test_compile_only(self):
        self.prepared['compileOnly']=True
        with self.assertRaisesRegex(ValueError,'NONLAUNCHABLE'):self.decode()
if __name__=='__main__':unittest.main()
