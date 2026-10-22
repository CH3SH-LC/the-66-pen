"""Explicit render rebuild, no configuration edits or live calls in fixtures."""
import copy,io,json,struct,sys,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import terrain_native as native
import terrain_refresh as refresh
from test_terrain_model import cell,save
import test_receipt_binding as receipt_fixtures

class RefreshTests(unittest.TestCase):
    def test_plan_preserves_all_rows_and_fields_without_noop_edits(self):
        blob=save([cell(118,117,2,3,(7,8,9)),cell(119,118)],second=[cell(4,5)])
        plan=refresh.make_plan(blob,1001,'source.gil')
        self.assertEqual(plan['before'],plan['expected']);self.assertEqual(plan['changes'],[]);self.assertEqual(plan['edits'],[])
        self.assertEqual(plan['before'][0][1:],[2,3,7,8,9]);self.assertTrue(plan['refreshOnly'])
        self.assertEqual(refresh.validate(plan,blob),plan)

    def test_plan_rejects_unknown_fields_tampering_and_stale_source(self):
        with self.assertRaises(ValueError):refresh.make_plan(save([cell(1,2,unknown=True)]),1001,'source.gil')
        blob=save([cell(1,2)]);plan=refresh.make_plan(blob,1001,'source.gil')
        for key,value in [('changes',[{}]),('refreshOnly',False),('sourceSha256','fake'),('before',[])]:
            changed=copy.deepcopy(plan);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):refresh.validate(changed,blob)
        with self.assertRaises(ValueError):refresh.validate(plan,save([cell(1,2,2)]))

    def test_evidence_requires_actual_call_return_clean_rows_and_unchanged_gate(self):
        for gate in (0,1):
            word=(400<<32)|31|(gate<<5)|(gate<<6)
            proof=refresh.evidence(word)
            self.assertTrue(proof['verified']);self.assertEqual(proof['dirtyBeforeCount'],400)
            self.assertEqual(proof['tickGateBefore'],bool(gate))
            for bit in range(5):self.assertFalse(refresh.evidence(word&~(1<<bit))['verified'])
            self.assertFalse(refresh.evidence(word^32)['verified'])
            self.assertFalse(refresh.evidence(word|128)['verified'])

    def fixture(self,run,refresh_only=True,word=(400<<32)|31):
        receipt_fixtures.ReceiptTests().fixture(run)
        built=native.ro.read_json(run/'build-result.json');built.update(refreshOnly=refresh_only,requiresRenderRebuild=True,renderRebuildEvidenceVersion=1)
        record=native.ro.read_json(run/'stdout.jsonl');data=bytearray.fromhex(record['terrainHex'])
        head=dict(zip(native.HEADER_NAMES,struct.unpack_from('<32Q',data)));head['reserved']=word
        if refresh_only:
            plan=refresh.make_plan((run/'before.gil').read_bytes(),1001,str(run/'1073741900.gil'))
            (run/'request.json').write_text(json.dumps(plan))
            for key in ('mutationCalls','completed','openCalled','snapshotCalled','notifyCalled','closeCalled','snapshotVerified','notificationVerified','closeVerified'):head[key]=0
            head['stage']=11;data[256+24*65536:280+24*65536]=data[256:280]
        struct.pack_into('<32Q',data,0,*[head[n] for n in native.HEADER_NAMES]);record['terrainHex']=data.hex()
        self.bind(run,built,record)
        return built,record

    def bind(self,run,built,record):
        (run/'build-result.json').write_text(json.dumps(built));(run/'stdout.jsonl').write_text(json.dumps(record))
        (run/'prepared.json').write_text(json.dumps({'kind':'native-terrain-prepared-v1','run':str(run),'buildResultSha256':native.profiles.sha256(run/'build-result.json')}))
        exit_record=native.ro.read_json(run/'exit.json');exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl')
        (run/'exit.json').write_text(json.dumps(exit_record))

    def test_refresh_receipt_is_called_without_cell_mutation(self):
        with tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
            run=Path(tmp);self.fixture(run);result=native.decode(run)
            self.assertTrue(result['ok'],result['reasons']);self.assertTrue(result['called']);self.assertTrue(result['nativeRenderRebuildVerified'])
            self.assertTrue(result['logicalTerrainPreserved']);self.assertTrue(result['safeToRelease'])
            self.assertFalse(result['nativeSaveVerified']);self.assertFalse(result['visualRebuildVerified'])
            self.assertEqual(result['header']['mutationCalls'],0)

    def test_write_requires_rebuild_after_transaction(self):
        with tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
            run=Path(tmp);self.fixture(run,False);result=native.decode(run)
            self.assertTrue(result['ok'],result['reasons']);self.assertTrue(result['nativeRenderRebuildVerified'])
            self.assertFalse(result['logicalTerrainPreserved'])

    def test_missing_rebuild_proof_is_uncertain_after_call(self):
        for word in ((400<<32)|17,(400<<32)|27,(400<<32)|63):
            with self.subTest(word=word),tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
                run=Path(tmp);self.fixture(run,word=word);result=native.decode(run)
                self.assertFalse(result['ok']);self.assertTrue(result['called']);self.assertTrue(result['outcomeUncertain'])
                self.assertFalse(result['safeToRelease']);self.assertIn('NATIVE_RENDER_REBUILD_NOT_VERIFIED',result['reasons'])

    def test_refresh_cannot_claim_logical_mutation_or_scene_change(self):
        for mode in ('cell','transaction','scene'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
                run=Path(tmp);built,record=self.fixture(run);data=bytearray.fromhex(record['terrainHex'])
                if mode=='cell':struct.pack_into('<I',data,256+24*65536+4,2)
                elif mode=='transaction':struct.pack_into('<Q',data,native.HEADER_NAMES.index('openCalled')*8,1)
                else:struct.pack_into('<Q',data,native.RECEIPT_BASE_SIZE+24,0x12345678)
                record['terrainHex']=data.hex();self.bind(run,built,record);result=native.decode(run)
                self.assertFalse(result['ok']);self.assertTrue(result['outcomeUncertain']);self.assertFalse(result['safeToRelease'])

    def test_refresh_is_not_an_apply_or_native_save_proof(self):
        import terrain_cli,terrain_save_verify
        with tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
            run=Path(tmp);self.fixture(run)
            with self.assertRaisesRegex(ValueError,'SUCCESSFUL_TERRAIN_WRITE_REQUIRED'):
                terrain_save_verify.verify(run,run/'nonexistent-save')
            output=io.StringIO()
            with redirect_stdout(output):code=terrain_cli.main(['verify-save','--run',str(run),'--after',str(run/'before.gil')])
            result=json.loads(output.getvalue());self.assertEqual(code,1);self.assertFalse(result['ok'])
            self.assertIn('SUCCESSFUL_APPLY_RECEIPT_REQUIRED',result['error'])

    def test_refresh_native_candidate_calls_original_builder_without_flag_writes(self):
        source=(HERE/'terrain_rebuild.inc').read_text();main=(HERE/'native_terrain.cpp').read_text()
        self.assertIn('scene.moduleBase+0xba50e20',source);self.assertIn('read(render+0x38,dirty)',source)
        self.assertNotIn('WriteProcessMemory',source);self.assertNotIn('reinterpret_cast<unsigned char*>',source)
        self.assertLess(main.index('o->closeVerified=1'),main.index('rebuild(*scene,o,scratch,kTerrainAfter'))
        self.assertLess(main.index('if(TERRAIN_REFRESH_ONLY)'),main.index('o->openCalled=1'))
        with tempfile.TemporaryDirectory(dir=native.ROOT/'.runtime') as tmp:
            run=Path(tmp);native.sources(run)
            plan=refresh.make_plan(save([cell(1,2)]),1001,'source.gil')
            native.request_header(run,plan,bytes(33208),1073741900,False)
            header=(run/'candidate-source/map-terrain/terrain_request.h').read_text()
            self.assertIn('#define TERRAIN_REFRESH_ONLY 1',header);self.assertIn('#define TERRAIN_INSPECT_ONLY 0',header)
            self.assertIn('#define TERRAIN_EDIT_COUNT 0ULL',header)
            self.assertTrue((run/'candidate-source/map-terrain/terrain_rebuild.inc').is_file())

if __name__=='__main__':unittest.main()
