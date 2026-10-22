"""Full original-format catalog fixtures; no game/process access."""
import json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path[:0]=[str(HERE),str(HERE/'tests')]
import terrain_catalog as catalog
import terrain_calibration as calibration
import terrain_native as native
import terrain_model as model
import terrain_batch as batch
import test_receipt_binding as receipts
from test_terrain_model import save,cell

MATRIX=[1.,0,0,0,0,1.,0,0,0,0,1.,0,-547.5,-2.5,-547.5,1.]

def payload():
    raw=bytearray(catalog.SIZE);h=dict.fromkeys(catalog.HEADER,0)
    h.update(size=catalog.SIZE,version=1,stage=4,root=1000,configDictionary=2000,configCount=3,configVersion=8,
             styleDictionary=3000,styleCount=2,styleVersion=5,materialCount=2,decoderTable=4000,decoderKey=0x12345678,stable=1)
    struct.pack_into('<16Q',raw,0,*[h[n] for n in catalog.HEADER]);struct.pack_into('<20f',raw,128,*MATRIX,5.,2.5,5.,0.)
    raw[208:2256]=bytes(range(256))*8
    for i,ident in enumerate((0,3)):
        fields=bytearray(48);encoded=ident^h['decoderKey'];name=100+i
        struct.pack_into('<I',fields,0x14,encoded);struct.pack_into('<I',fields,0x1c,name);struct.pack_into('<I',fields,0x24,2)
        catalog.ROW.pack_into(raw,2256+i*catalog.ROW.size,10000+i,20000+i,500+i,encoded,ident,name,2,0,fields)
    return bytes(raw)

def rewrite(path,obj):path.write_text(json.dumps(obj),encoding='utf-8')

def original_fixture(run):
    receipts.ReceiptTests().fixture(run)
    plan={'terrainId':1001,'before':[],'expected':[],'changes':[]};rewrite(run/'request.json',plan)
    built=native.ro.read_json(run/'build-result.json');built.update(inspectOnly=True,catalogProbe=True,catalogKind='native-terrain-catalog-calibration-v1',levelId=1073741900)
    built['session'].update(schemaVersion=1,window='0x1234',windowClass='fixture-class')
    baseline=native.ro.read_json(run/'baseline-prepared.json');baseline['session']=built['session'];rewrite(run/'baseline-prepared.json',baseline)
    rewrite(run/'build-result.json',built);rewrite(run/'prepared.json',{'kind':'native-terrain-prepared-v1','run':str(run),'buildResultSha256':native.profiles.sha256(run/'build-result.json')})
    record=native.ro.read_json(run/'stdout.jsonl');raw=bytearray.fromhex(record['terrainHex']);head=dict(zip(native.HEADER_NAMES,struct.unpack_from('<32Q',raw)))
    head.update(size=len(raw)+catalog.SIZE,version=3,stage=3)
    for n in ('mutationCalls','completed','openCalled','snapshotCalled','notifyCalled','closeCalled','snapshotVerified','notificationVerified','closeVerified'):head[n]=0
    struct.pack_into('<32Q',raw,0,*[head[n] for n in native.HEADER_NAMES]);raw[256+24*model.MAX_CELLS:256+24*model.MAX_CELLS+24]=raw[256:280]
    raw.extend(payload());prefix=bytearray.fromhex(record['receiptPrefixHex']);struct.pack_into('<I',prefix,4,27)
    record.update(terrainBytes=len(raw),terrainHex=raw.hex(),receiptPrefixHex=prefix.hex());rewrite(run/'stdout.jsonl',record)
    exit_record=native.ro.read_json(run/'exit.json');exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl');rewrite(run/'exit.json',exit_record)

class CatalogTests(unittest.TestCase):
    def temporary(self):
        native.OUT.mkdir(parents=True,exist_ok=True);return tempfile.TemporaryDirectory(prefix='catalog-fixture-',dir=native.OUT)

    def test_binary_decode_proves_id_table_and_loaded_styles(self):
        result=catalog.decode(payload());self.assertTrue(result['ok'],result);self.assertEqual([x['id'] for x in result['materials']],[0,3]);self.assertIsNone(result['materials'][0]['semanticLabel'])
        self.assertFalse(result['materialNamesVerified']);self.assertEqual(result['matrix'],MATRIX)

    def test_tampered_encoded_id_record_and_unused_tail_refused(self):
        for offset in (2256+24,2256+40+0x14,catalog.SIZE-1):
            data=bytearray(payload());data[offset]^=1;self.assertFalse(catalog.decode(data)['ok'])

    def test_bad_capacity_and_nonfinite_matrix_refused(self):
        for offset,value,fmt in ((11*8,513,'Q'),(128,float('nan'),'f'),(192,10.,'f')):
            data=bytearray(payload());struct.pack_into('<'+fmt,data,offset,value);self.assertFalse(catalog.decode(data)['ok'])

    def test_original_receipt_protocol_and_authority(self):
        with self.temporary() as directory:
            run=Path(directory).resolve();original_fixture(run);result=native.decode(run)
            self.assertTrue(result['ok'],result);self.assertTrue(result['materialCatalogVerified']);self.assertFalse(result['called'])
            source=catalog.authority(run,1001);self.assertEqual(source['materialIds'],[0,3]);self.assertEqual(catalog.validate_authority(source),source)
            source['materialIds'].append(99)
            with self.assertRaisesRegex(ValueError,'MATERIAL_SOURCE_CHANGED'):catalog.validate_authority(source)

    def test_old_protocol_cannot_impersonate_catalog(self):
        with self.temporary() as directory:
            run=Path(directory).resolve();original_fixture(run);r=native.ro.read_json(run/'stdout.jsonl');p=bytearray.fromhex(r['receiptPrefixHex']);struct.pack_into('<I',p,4,18);r['receiptPrefixHex']=p.hex();rewrite(run/'stdout.jsonl',r)
            e=native.ro.read_json(run/'exit.json');e['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl');rewrite(run/'exit.json',e)
            self.assertFalse(native.decode(run)['cleanupVerified'])

    def test_unknown_label_and_unloaded_style_never_accepted(self):
        result=catalog.decode(payload());result['materials'][0].update(semanticLabel='草地',labelHashMatched=True)
        self.assertEqual(catalog.resolve_material(result,'草地')['id'],0)
        with self.assertRaisesRegex(ValueError,'NOT_UNIQUE'):catalog.resolve_material(result,'岩石')
        result['materials'][0]['renderStyleLoaded']=False
        with self.assertRaisesRegex(ValueError,'NOT_UNIQUE'):catalog.resolve_material(result,0)

    def test_catalog_material_plan_retains_other_fields_and_write_guard(self):
        with self.temporary() as directory:
            run=Path(directory).resolve();original_fixture(run);source=catalog.authority(run,1001)
            blob=save([cell(1,2,1,0,(7,8,9))])
            p=model.make_plan(blob,1001,[dict(x=1,z=2,material=3)],material_source=source)
            self.assertEqual(p['expected'][0][1:],[1,3,7,8,9]);self.assertEqual(model.validate_plan(p,blob),p)
            with self.assertRaisesRegex(ValueError,'MATERIAL_NOT_IN_NATIVE'):model.make_plan(blob,1001,[dict(x=1,z=2,material=9)],material_source=source)
            built=native.ro.read_json(run/'build-result.json');pins,data=catalog.preparation(p,built['session'],1073741900)
            self.assertEqual(data,payload());self.assertIn(str(run/'stdout.jsonl'),pins)
            with self.assertRaises(ValueError):catalog.preparation(p,built['session'],999)

    def test_wrong_terrain_and_stale_original_refused(self):
        with self.temporary() as directory:
            run=Path(directory).resolve();original_fixture(run)
            with self.assertRaisesRegex(ValueError,'TERRAIN_MISMATCH'):catalog.authority(run,1002)
            source=catalog.authority(run);r=native.ro.read_json(run/'stdout.jsonl');r['transportOk']=False;rewrite(run/'stdout.jsonl',r)
            with self.assertRaises(ValueError):catalog.validate_authority(source)

    def test_native_read_capture_does_not_invoke_lazy_or_setter(self):
        text=(HERE/'terrain_catalog.inc').read_text();self.assertNotIn('base+0xe4d4c80',text)
        for setter in ('ba53650','ba539a0','1436de0','ba50e20'):self.assertNotIn(setter,text)
        core=(HERE/'native_terrain.cpp').read_text();self.assertLess(core.index('catalogGuard(*scene'),core.index('o->openCalled=1'))
        self.assertIn('HeapAlloc',text);self.assertNotIn('TerrainCatalogReceipt actual{}',text)

    def test_private_candidate_receipt27_and_guard_bytes(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as directory:
            run=Path(directory);native.sources(run,catalog_probe=True)
            self.assertIn('HR_ACTION == 14 ? 27',(run/'candidate-source/native/hook_receipt_protocol.h').read_text())
            native.request_header(run,dict(terrainId=1001,before=[],expected=[],changes=[]),bytes(33208),1073741900,False,payload())
            self.assertIn('kTerrainExpectedCatalog',(run/'candidate-source/map-terrain/terrain_request.h').read_text())

    def test_source_bound_batch_accepts_both_cards_from_original_receipts(self):
        import test_batch as batching
        with tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as directory:
            root=Path(directory);(root/'prepared').mkdir()
            with patch.object(Path,'home',return_value=root/'home'),patch.object(batch,'OUT',root/'batches'),patch.object(native,'OUT',root/'prepared'):
                origin=root/'prepared/catalog';origin.mkdir();original_fixture(origin)
                f=batching.Fixture(root,edits=[dict(x=1,z=2,material=3),dict(x=2,z=2,height=2,material=3)],catalog_run=str(origin))
                for expected in (1,2):
                    run=f.next();card=batch.read(run/'request.json');self.assertEqual(card['materialSource'],f.plan['materialSource'])
                    result=batch.accept(batching.ns(batch=f.directory,run=run));self.assertEqual(result['acceptedCards'],expected)
                self.assertTrue(result['complete']);self.assertEqual(batch.status(batching.ns(batch=f.directory))['acceptedCards'],2)

    def test_save_proof_retains_source_catalog_originals(self):
        import test_save_proof as saving
        with saving.complete_fixture() as (run,saved,built,*_):
            origin=run.parent/'catalog';origin.mkdir();original_fixture(origin);source=catalog.authority(origin)
            p=model.make_plan((run/'before.gil').read_bytes(),1001,[dict(x=1,z=2,height=2)],built['sourceSave'],source)
            rewrite(run/'request.json',p);built.update(materialSource=source,catalogGuard=True);saving.repin_terrain(run,built)
            result=saving.proof.verify(run,saved)
            self.assertTrue(result['nativeSaveVerified']);self.assertIn(str(origin/'stdout.jsonl'),result['evidence']['artifactSha256'])

class CalibrationTests(unittest.TestCase):
    def source(self,matrix=None):return dict(schema='native-terrain-material-source-v1',cellSize=[5.,2.5,5.],matrix=matrix or MATRIX)

    def test_native_historical_coordinates_and_vertical_code(self):
        result=calibration.cell_to_world(self.source(),118,117,1);self.assertEqual(result['worldTop'],[42.5,0.,37.5])
        self.assertEqual(calibration.cell_to_world(self.source(),118,117,2)['worldTop'],[42.5,2.5,37.5])
        self.assertEqual(calibration.world_to_cell(self.source(),[42.5,0.,37.5])['height'],1)

    def test_rotated_scaled_parent_is_used_not_old_origin(self):
        m=[0,0,-2,0,0,3,0,0,4,0,0,0,20,7,30,1]
        p=calibration.cell_to_world(self.source(m),8,11,4)
        self.assertEqual(p['worldTop'],[240.,37.,-50.]);q=calibration.world_to_cell(self.source(m),p['worldTop']);self.assertEqual((q['x'],q['z'],q['height']),(8,11,4))

    def test_non_grid_height_not_silently_rounded(self):
        with self.assertRaisesRegex(ValueError,'NOT_ON_NATIVE'):calibration.world_to_cell(self.source(),[42.5,.1,37.5])
        p=calibration.world_to_cell(self.source(),[42.6,.1,37.4],'nearest');self.assertEqual(p['height'],1);self.assertAlmostEqual(p['residualWorld'][1],-.1)

    def test_invalid_matrix_and_negative_codes_refused(self):
        m=list(MATRIX);m[0]=0
        with self.assertRaisesRegex(ValueError,'NONINVERTIBLE'):calibration.world_to_cell(self.source(m),[0,0,0])
        with self.assertRaises(ValueError):calibration.world_to_cell(self.source(),[-9999.,0,0])
        with self.assertRaises(ValueError):calibration.cell_to_world(self.source(),True,0,1)

    def test_world_consumer_requires_explicit_native_material(self):
        c=catalog.decode(payload());c['materialSource']=self.source();c['materials'][1].update(semanticLabel='岩土',labelHashMatched=True)
        p=calibration.world_edits(c,[dict(worldTop=[42.5,0,37.5],material='岩土')]);self.assertEqual(p['edits'],[dict(x=118,z=117,height=1,material=3)])
        with self.assertRaisesRegex(ValueError,'COLLAPSE'):calibration.world_edits(c,[dict(worldTop=[42.5,0,37.5],material=0)]*2)

    def test_batch_can_choose_new_catalog_material_in_first_card(self):
        source=self.source();source.update(terrainId=1001,levelId=1073741900,materialIds=[0,3])
        blob=save([cell(1,2,1)])
        with patch.object(catalog,'validate_authority',return_value=source):
            result=batch.compile_plan(blob,1001,[dict(x=1,z=2,material=3),dict(x=2,z=2,height=2,material=3)],'fixture',1073741900,1,source)
        self.assertEqual(result['steps'][1]['before'],result['steps'][0]['expected']);self.assertEqual(result['materialSource'],source)

if __name__=='__main__':unittest.main()
