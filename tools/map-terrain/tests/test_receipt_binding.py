"""Independent binary receipt fixtures; zero process/native calls."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(Path(__file__).resolve().parent))
import terrain_native as native
import terrain_model as model
from test_terrain_model import save,cell

class ReceiptTests(unittest.TestCase):
    def fixture(self,run,change=None):
        profile=native.profiles.load_profile()
        session={'pid':1234,'tid':2345,'processCreation':12345678,'threadCreation':87654321,'image':'fixture.invalid'}
        source=save([cell(1,2,1)])
        plan=model.make_plan(source,1001,[{'x':1,'z':2,'height':2}],str(run/'1073741900.gil'))
        baseline=bytearray(33208);base=0x140000000
        struct.pack_into('<4I',baseline,0,33208,1,0,1951)
        struct.pack_into('<11Q',baseline,16,base,*[0x20000000+i*0x1000 for i in range(10)])
        stack=profile['callbackStackRvas']
        counts=[profile['image']['timestamp'],profile['image']['sizeOfImage'],0,1,1,1,1,0,0,0,100,10,len(stack),0,0,0]
        struct.pack_into('<16I',baseline,104,*counts);struct.pack_into('<I',baseline,180,1073741900)
        for i,rva in enumerate(stack):struct.pack_into('<Q',baseline,184+8*i,base+int(rva,16))
        h={name:0 for name in native.HEADER_NAMES}
        h.update(size=native.RECEIPT_BASE_SIZE+len(baseline),version=1,terrainId=1001,beforeCount=1,afterCount=1,
                 mutationCalls=1,completed=1,stage=9,openCalled=1,snapshotCalled=1,notifyCalled=1,closeCalled=1,
                 snapshotVerified=1,notificationVerified=1,closeVerified=1,sceneUnchanged=1,captureStable=1,constantsValid=1)
        terrain=bytearray(h['size']);struct.pack_into('<32Q',terrain,0,*[h[n] for n in native.HEADER_NAMES])
        struct.pack_into('<6I',terrain,256,*plan['before'][0])
        struct.pack_into('<6I',terrain,256+24*model.MAX_CELLS,*plan['expected'][0])
        terrain[native.RECEIPT_BASE_SIZE:]=baseline
        prefix=struct.pack('<IIQQII8i',0x31524847,18,123,456,1234,2345,2,1234,2345,1,0,0,0,0)
        record={'ok':True,'scope':'FIXED_TERRAIN_ACTION','selfTestOnly':False,'probeElevatedHigh':True,
                'pid':1234,'tid':2345,'callbackCount':1,'activeCallbacks':0,'unhooked':True,'transportOk':True,
                'snapshotStatus':0,'snapshotBytes':len(baseline),'snapshotHex':baseline.hex(),
                'receiptPrefixHex':prefix.hex(),'processCreation':12345678,'threadCreation':87654321,
                'terrainBytes':len(terrain),'terrainHex':terrain.hex()}
        if change:change(record)
        native.write(run/'request.json',plan);(run/'before.gil').write_bytes(source)
        (run/'baseline-snapshot.bin').write_bytes(baseline)
        original={'launchable':True,'compileOnly':False,'profileSha256':native.profiles.PROFILE_SHA256,'session':session,'nativeSnapshotVersion':1}
        native.write(run/'baseline-prepared.json',original)
        built={'kind':'native-terrain-build-v1','run':str(run),'launchable':True,'nativeSnapshotVersion':1,
               'nonce':123,'deadlineTick':456,'session':session,'terrainId':1001,'inspectOnly':False,'pins':{}}
        native.write(run/'build-result.json',built)
        native.write(run/'prepared.json',{'kind':'native-terrain-prepared-v1','run':str(run),'buildResultSha256':native.profiles.sha256(run/'build-result.json')})
        native.write(run/'stdout.jsonl',record)
        native.write(run/'exit.json',{'executed':True,'exitCode':0,'stdoutSha256':native.profiles.sha256(run/'stdout.jsonl')})
        (run/'launch.claim').write_bytes(b'fixture');(run/'attempt.used').write_bytes(b'fixture')

    def run_fixture(self,change=None):
        native.OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='fixture-',dir=native.OUT) as directory:
            run=Path(directory).resolve();self.fixture(run,change)
            return native.decode(run)

    def test_complete_fixture_accepts_independent_scene_and_cells(self):
        result=self.run_fixture()
        self.assertTrue(result['ok'],result)
        self.assertTrue(result['safeToRelease'])
        self.assertFalse(result['nativeSaveVerified'])

    def test_other_card_nonce_rejected(self):
        def change(r):
            prefix=bytearray.fromhex(r['receiptPrefixHex']);struct.pack_into('<Q',prefix,8,124);r['receiptPrefixHex']=prefix.hex()
        result=self.run_fixture(change)
        self.assertIn('CARD_PREFIX_OR_SESSION_BINDING',result['reasons']);self.assertFalse(result['safeToRelease'])

    def test_wrong_protocol_rejected(self):
        def change(r):
            prefix=bytearray.fromhex(r['receiptPrefixHex']);struct.pack_into('<I',prefix,4,17);r['receiptPrefixHex']=prefix.hex()
        result=self.run_fixture(change)
        self.assertFalse(result['ok']);self.assertFalse(result['cleanupVerified'])

    def test_self_reported_success_does_not_replace_cleanup(self):
        result=self.run_fixture(lambda r:r.update(unhooked=False))
        self.assertFalse(result['ok']);self.assertFalse(result['safeToRelease'])

    def test_wrong_cell_with_success_header_rejected(self):
        def change(r):
            terrain=bytearray.fromhex(r['terrainHex']);struct.pack_into('<I',terrain,256+24*model.MAX_CELLS+4,9);r['terrainHex']=terrain.hex()
        result=self.run_fixture(change)
        self.assertIn('INDEPENDENT_CELL_COMPARISON',result['reasons']);self.assertTrue(result['outcomeUncertain']);self.assertFalse(result['safeToRelease'])

    def test_wrong_thread_birth_rejected(self):
        result=self.run_fixture(lambda r:r.update(threadCreation=1))
        self.assertFalse(result['ok']);self.assertFalse(result['cleanupVerified'])

    def test_native_stage1_refusal_is_explicit_missing_after_context(self):
        native.OUT.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='fixture-',dir=native.OUT) as directory:
            run=Path(directory).resolve()
            def refused(record):
                terrain=bytearray(record['terrainBytes']);head={name:0 for name in native.HEADER_NAMES}
                head.update(size=len(terrain),version=1,status=1,stage=1,terrainId=1001,
                            failedRva=0x5a9359e,failedValue=1)
                struct.pack_into('<32Q',terrain,0,*[head[name] for name in native.HEADER_NAMES])
                record.update(ok=False,terrainHex=terrain.hex())
            self.fixture(run,refused)
            built=native.ro.read_json(run/'build-result.json');built['inspectOnly']=True
            (run/'build-result.json').write_text(json.dumps(built),encoding='utf-8')
            marker=native.ro.read_json(run/'prepared.json');marker['buildResultSha256']=native.profiles.sha256(run/'build-result.json')
            (run/'prepared.json').write_text(json.dumps(marker),encoding='utf-8')
            exit_record=native.ro.read_json(run/'exit.json');exit_record['exitCode']=1
            (run/'exit.json').write_text(json.dumps(exit_record),encoding='utf-8')
            result=native.decode(run)
            self.assertFalse(result['ok']);self.assertTrue(result['contextNotCaptured'])
            self.assertFalse(result['afterContextVerified']);self.assertFalse(result['called'])
            self.assertFalse(result['outcomeUncertain']);self.assertTrue(result['cleanupVerified'])
            self.assertTrue(result['safeToRelease'])
            self.assertIn('AFTER_CONTEXT_NOT_CAPTURED',result['reasons'])
            self.assertFalse(any(reason.startswith('CONTEXT_DECODE:') for reason in result['reasons']))
            self.assertEqual(len(result['contextValidation']),1)

    def test_missing_after_context_never_validates_reported_success(self):
        def missing(record):
            terrain=bytearray.fromhex(record['terrainHex']);terrain[native.RECEIPT_BASE_SIZE:]=bytes(33208)
            record['terrainHex']=terrain.hex()
        result=self.run_fixture(missing)
        self.assertFalse(result['ok']);self.assertTrue(result['contextNotCaptured'])
        self.assertFalse(result['afterContextVerified']);self.assertTrue(result['outcomeUncertain'])
        self.assertFalse(result['safeToRelease'])

if __name__=='__main__':unittest.main()
