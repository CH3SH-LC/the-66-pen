"""Private synthetic GIL/native receipts only. Never opens a game process.

All binary success responses below are explicit stubs, not game acceptance.
Production decoders, catalog authority, batch chain and save-content validation
remain unmocked. Only batch candidate compilation is replaced with the stub.
"""
import argparse,copy,json,struct,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import water_model as model
import water_catalog as catalog
import water_native as native
import water_geometry as geometry
import water_batch as batch
from gil_container import Field,Container,encode_fields,encode_container

LEVEL=1073741843
MATRIX=[0.,0.,-2.,0.,0.,3.,0.,0.,4.,0.,0.,0.,100.,200.,300.,1.]
TYPES=[dict(materialId=0,typeId=i,scaleY=2.,renderable=True) for i in (1,3)]
def vi(n,v):return Field(n,0,value=v)
def msg(n,fields):return Field(n,2,data=encode_fields(fields))
def cell(x,z,h=5,m=0,extra=(0,0,0),unknown=False):
    f=[vi(1,model.key(x,z)),vi(2,h),vi(3,m),vi(4,extra[0]),vi(5,extra[1]),vi(6,extra[2])]
    if unknown:f.append(vi(77,8))
    return msg(4,f)
def save(cells,level=LEVEL,second=None,stamp=100,opaque=7):
    entries=[msg(1,[vi(1,1001),msg(2,[Field(1,2,data=b'fixture water')]),*cells])]
    if second is not None:entries.append(msg(1,[vi(1,1002),*second]))
    roots=[vi(1,level),vi(40,stamp),vi(44,opaque),msg(7,entries)]
    roots.extend(msg(n,[vi(1,n)]) for n in (5,6,10))
    return encode_container(Container(2,encode_fields(roots)))
def put(path,value):path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
def ns(**kwargs):return argparse.Namespace(**kwargs)

def catalog_bytes():
    data=bytearray(catalog.SIZE);h={n:0 for n in catalog.HEADER}
    h.update(size=len(data),version=1,stage=4,root=0x1000,styleDictionary=0x2000,styleCount=2,styleVersion=7,materialCount=1,waterTypeCount=2,stable=1)
    struct.pack_into('<16Q',data,0,*[h[n] for n in catalog.HEADER])
    struct.pack_into('<16f4f',data,128,*MATRIX,5.,2.5,5.,0.)
    for i,ident in enumerate((1,3)):
        prefab=0x6000+i*256;raw=struct.pack('<IIQfI',ident,0,prefab,2.,0)
        catalog.ROW.pack_into(data,208+i*catalog.ROW.size,0x3000,0x4000,0x5000,0x7000+i*256,prefab,0x8000+i*256,0,ident,i,2,4,0,2.,0,raw)
    return bytes(data)

def raw_receipt(run,before,after,plan=None,source=None,water_catalog=False,when=None,pins=None):
    """Explicit synthetic response; no native call is used to produce it."""
    run.mkdir(parents=True,exist_ok=False);profile=native.profiles.load_profile()
    session=dict(schemaVersion=1,pid=1234,tid=2345,processCreation=12345678,threadCreation=87654321,image='fixture.invalid',window='0x1234',windowClass='fixture-class')
    baseline=bytearray(33208);base=0x140000000
    struct.pack_into('<4I',baseline,0,33208,1,0,1951)
    struct.pack_into('<11Q',baseline,16,base,*[0x20000000+i*0x1000 for i in range(10)])
    stack=profile['callbackStackRvas'];counts=[profile['image']['timestamp'],profile['image']['sizeOfImage'],0,1,1,1,1,0,0,0,100,10,len(stack),0,0,0]
    struct.pack_into('<16I',baseline,104,*counts);struct.pack_into('<I',baseline,180,LEVEL)
    for i,rva in enumerate(stack):struct.pack_into('<Q',baseline,184+i*8,base+int(rva,16))
    inspect=plan is None
    request=plan or dict(terrainId=1001,before=[],expected=[],changes=[])
    header={n:0 for n in native.HEADER_NAMES};header.update(size=native.RECEIPT_BASE_SIZE+len(baseline)+(catalog.SIZE if water_catalog else 0),version=3 if water_catalog else 1,
        terrainId=1001,beforeCount=len(before),afterCount=len(after),stage=3 if inspect else 9,sceneUnchanged=1,captureStable=1,constantsValid=1)
    if not inspect:
        header.update(mutationCalls=len(plan['changes']),completed=len(plan['changes']),openCalled=1,snapshotCalled=1,notifyCalled=1,closeCalled=1,snapshotVerified=1,notificationVerified=1,closeVerified=1,reserved=31)
    data=bytearray(header['size']);struct.pack_into('<32Q',data,0,*[header[n] for n in native.HEADER_NAMES])
    for offset,rows in ((256,before),(256+24*model.MAX_CELLS,after)):
        for i,row in enumerate(rows):struct.pack_into('<6I',data,offset+24*i,*row)
    data[native.RECEIPT_BASE_SIZE:native.RECEIPT_BASE_SIZE+len(baseline)]=baseline
    if water_catalog:data[native.RECEIPT_BASE_SIZE+len(baseline):]=catalog_bytes()
    prefix=struct.pack('<IIQQII8i',0x31524847,29,123,456,1234,2345,2,1234,2345,1,0,0,0,0)
    record=dict(ok=True,scope='FIXED_TERRAIN_WATER_ACTION',selfTestOnly=False,probeElevatedHigh=True,pid=1234,tid=2345,callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,
        snapshotStatus=0,snapshotBytes=len(baseline),snapshotHex=baseline.hex(),receiptPrefixHex=prefix.hex(),processCreation=12345678,threadCreation=87654321,terrainBytes=len(data),terrainHex=data.hex())
    built=dict(kind='native-terrain-water-build-v1',run=str(run),launchable=True,nativeSnapshotVersion=1,actionCode=23,receiptVersion=29,nonce=123,deadlineTick=456,
        session=session,terrainId=1001,levelId=LEVEL,inspectOnly=inspect,pins=pins or {},catalogProbe=water_catalog,catalogKind='native-terrain-water-catalog-v1' if water_catalog else None,
        catalogGuard=bool(request.get('materialSource')),materialSource=request.get('materialSource'),batch=request.get('batch'),requiresRenderRebuild=not inspect,renderRebuildEvidenceVersion=1 if not inspect else None)
    put(run/'request.json',request);put(run/'stdout.jsonl',record);put(run/'build-result.json',built)
    put(run/'prepared.json',dict(kind='native-terrain-water-prepared-v1',run=str(run),buildResultSha256=native.profiles.sha256(run/'build-result.json')))
    put(run/'baseline-prepared.json',dict(launchable=True,compileOnly=False,profileSha256=native.profiles.PROFILE_SHA256,session=session,nativeSnapshotVersion=1))
    (run/'baseline-snapshot.bin').write_bytes(baseline)
    if source is not None:(run/'before.gil').write_bytes(source)
    when=when or datetime.now(timezone.utc)-timedelta(seconds=90)
    put(run/'exit.json',dict(executed=True,exitCode=0,stdoutSha256=native.profiles.sha256(run/'stdout.jsonl'),startedUtc=when.isoformat(),finishedUtc=(when+timedelta(seconds=1)).isoformat()))
    for name in ('launch.claim','attempt.used'):(run/name).write_bytes(b'explicit private stub')
    return run

@contextmanager
def fixture():
    root=model.ROOT/'.runtime/terrain-water-20261017/fixtures';root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stub-',dir=root) as directory:
        root=Path(directory);prepared=root/'prepared';prepared.mkdir();home=root/'home'
        with patch.object(native,'OUT',prepared),patch.object(batch,'OUT',root/'batches'),patch.object(Path,'home',return_value=home):
            catalog_run=raw_receipt(prepared/'catalog',[[model.key(1,2),5,0,0,0,0]],[[model.key(1,2),5,0,0,0,0]],water_catalog=True)
            yield root,catalog_run

class ModelTests(unittest.TestCase):
    def test_five_operations_and_unknown_preservation(self):
        dry=[model.key(1,2),5,0,0,0,0];other=[model.key(4,8),9,12,17,19,21]
        _,rows=model.apply_edits([dry,other],[dict(op='replace-top',x=1,z=2,waterType=1)],TYPES)
        self.assertEqual(rows,[dry[:1]+[4,0,1,0,0],other])
        _,rows=model.apply_edits(rows,[dict(op='change-water-type',x=1,z=2,waterType=3)],TYPES)
        self.assertEqual(rows[0][1:],[4,0,3,0,0])
        _,restored=model.apply_edits(rows,[dict(op='restore-top',x=1,z=2)],TYPES);self.assertEqual(restored,[dry,other])
        _,removed=model.apply_edits(rows,[dict(op='remove-water',x=1,z=2)],TYPES);self.assertEqual(removed[0],[dry[0],4,0,0,0,0])
        _,water=model.apply_edits([],[dict(op='create-water-only',x=9,z=3,material=0,waterType=1)],TYPES)
        self.assertEqual(water,[[model.key(9,3),0,0,1,0,0]])
        changes,empty=model.apply_edits(water,[dict(op='remove-water',x=9,z=3)],TYPES)
        self.assertEqual(empty,[]);self.assertEqual(changes[0]['op'],'delete')

    def test_refuses_zero_unknown_pair_opaque_and_invalid_cells(self):
        for row,edit in [([model.key(1,2),5,0,0,0,0],dict(op='replace-top',x=1,z=2,waterType=n)) for n in (0,2,-1,True)]+[
            ([model.key(1,2),5,0,0,7,0],dict(op='replace-top',x=1,z=2,waterType=1)),
            ([model.key(1,2),9998,0,1,0,0],dict(op='restore-top',x=1,z=2)),
            ([model.key(1,2),5,0,1,0,0],dict(op='replace-top',x=1,z=2,waterType=3)),
            ([model.key(1,2),5,0,0,0,0],dict(op='change-water-type',x=1,z=2,waterType=1))]:
            with self.subTest(edit=edit,row=row),self.assertRaises(ValueError):model.apply_edits([row],[edit],TYPES)
        with self.assertRaises(ValueError):model.apply_edits([],[dict(op='create-water-only',x=9999,z=1,material=0,waterType=1)],TYPES)
        with self.assertRaises(ValueError):model.apply_edits([],[dict(op='create-water-only',x=1,z=1,material=0,waterType=0)],TYPES)

    def test_plan_bound_to_original_catalog_level_and_source(self):
        with fixture() as (root,run):
            authority=catalog.authority(run,1001);blob=save([cell(1,2)])
            plan=model.make_plan(blob,1001,[dict(op='replace-top',x=1,z=2,waterType=1)],'fixture.gil',authority)
            self.assertEqual(model.validate_plan(plan,blob),plan)
            changed=copy.deepcopy(plan);changed['expected'][0][1]=4+1
            with self.assertRaises(ValueError):model.validate_plan(changed,blob)
            for forbidden in (save([cell(1,2)],level=1073741842),save([cell(1,2,unknown=True)])):
                with self.assertRaises(ValueError):model.make_plan(forbidden,1001,plan['edits'],'fixture.gil',authority)
            changed=copy.deepcopy(authority);changed['waterTypes'][0]['typeId']=99
            with self.assertRaises(ValueError):model.make_plan(blob,1001,plan['edits'],'fixture.gil',changed)

    def test_save_preserves_other_terrain_entity_directory_graph_and_opaque_roots(self):
        with fixture() as (root,run):
            source=catalog.authority(run);before=save([cell(1,2),cell(7,8,9,2,(5,6,7))],second=[cell(9,9)])
            plan=model.make_plan(before,1001,[dict(op='replace-top',x=1,z=2,waterType=1)],'fixture.gil',source)
            after=save([cell(1,2,4,0,(1,0,0)),cell(7,8,9,2,(5,6,7))],second=[cell(9,9)],stamp=101)
            result=model.verify_save(before,after,plan);self.assertTrue(result['fileContentVerified']);self.assertFalse(result['nativeSaveVerified'])
            for bad in (save([cell(1,2,4,0,(1,0,0))],second=[cell(9,9)]),save([cell(1,2,4,0,(1,0,0)),cell(7,8,9,2,(5,6,7))],second=[cell(9,9)],opaque=8)):
                self.assertFalse(model.verify_save(before,bad,plan)['ok'])

    def test_twenty_thousand_cells_chain_without_fake_save(self):
        with fixture() as (root,run):
            source=catalog.authority(run);blob=save([cell(1,2)])
            edits=[dict(op='create-water-only',x=i%200,z=10+i//200,waterType=1,material=0) for i in range(20000)]
            result=batch.compile_plan(blob,1001,edits,'fixture.gil',LEVEL,material_source=source)
            self.assertEqual(len(result['steps']),5);self.assertEqual(len(result['expected']),20001)
            for left,right in zip(result['steps'],result['steps'][1:]):self.assertEqual(left['expected'],right['before'])
            self.assertTrue(all(len(s['changes'])<=4096 for s in result['steps']))
            with self.assertRaises(ValueError):batch.compile_plan(blob,1001,edits,'fixture.gil',1073741842,material_source=source)
            with self.assertRaises(ValueError):batch.compile_plan(blob,1001,edits,'fixture.gil',LEVEL,chunk_size=4097,material_source=source)

class CatalogTests(unittest.TestCase):
    def test_binary_catalog_complete_and_does_not_claim_pixels_or_depth(self):
        result=catalog.decode(catalog_bytes());self.assertTrue(result['ok'],result)
        self.assertEqual([r['typeId'] for r in result['types']],[1,3]);self.assertFalse(result['surfaceElevationVerified']);self.assertFalse(result['playerSwimmingVerified'])

    def test_corrupt_counts_fields_matrix_and_unused_bytes_refused(self):
        for offset,fmt,value in ((16,'Q',1),(9*8,'Q',513),(208+52,'I',0),(208+72,'f',float('nan')),(128,'f',0.),(catalog.SIZE-1,'B',1),(208+104+56,'I',0)):
            data=bytearray(catalog_bytes());struct.pack_into('<'+fmt,data,offset,value)
            if offset==128:struct.pack_into('<f',data,128+8,0.)
            with self.subTest(offset=offset):self.assertFalse(catalog.decode(bytes(data))['ok'])

    def test_world_base_uses_rotated_scaled_matrix_without_surface_claim(self):
        source=dict(schema='native-water-source-v1',matrix=MATRIX,cellSize=[5,2.5,5])
        result=geometry.locate(source,[[140,200,290],[160,230,280]])
        self.assertEqual([(r['x'],r['z'],r['heightCode']) for r in result['points']],[(1,2,0),(2,3,4)])
        self.assertTrue(result['points'][0]['emptyCellWaterOnlyPossible']);self.assertFalse(result['points'][1]['emptyCellWaterOnlyPossible'])
        self.assertFalse(result['surfaceElevationVerified'])
        with self.assertRaises(ValueError):geometry.locate(source,[[140.1,200,290]])

class ReceiptTests(unittest.TestCase):
    def result(self,mutation=None):
        with fixture() as (root,run):
            source=save([cell(1,2)]);authority=catalog.authority(run)
            plan=model.make_plan(source,1001,[dict(op='replace-top',x=1,z=2,waterType=1)],'fixture.gil',authority)
            target=raw_receipt(native.OUT/'write',plan['before'],plan['expected'],plan,source)
            if mutation:
                record=json.loads((target/'stdout.jsonl').read_text());mutation(record);put(target/'stdout.jsonl',record)
                exit=json.loads((target/'exit.json').read_text());exit['stdoutSha256']=native.profiles.sha256(target/'stdout.jsonl');put(target/'exit.json',exit)
            return native.decode(target)

    def test_native_binary_write_and_rebuild_complete(self):
        result=self.result();self.assertTrue(result['ok'],result);self.assertTrue(result['nativeRenderRebuildVerified']);self.assertTrue(result['safeToRelease'])
        self.assertFalse(result['nativeSaveVerified']);self.assertFalse(result['surfaceElevationVerified'])

    def test_cross_module_protocol_scope_nonce_and_birth_refused(self):
        def field(offset,fmt,value):
            def mutate(r):
                p=bytearray.fromhex(r['receiptPrefixHex']);struct.pack_into(fmt,p,offset,value);r['receiptPrefixHex']=p.hex()
            return mutate
        for mutation in (field(4,'<I',28),field(8,'<Q',124),lambda r:r.update(scope='FIXED_TERRAIN_ACTION'),lambda r:r.update(threadCreation=1),lambda r:r.update(unhooked=False)):
            with self.subTest(mutation=mutation):
                result=self.result(mutation);self.assertFalse(result['ok']);self.assertTrue(result['outcomeUncertain'])

    def test_false_after_water_type_and_missing_context_refused(self):
        def badtype(r):
            data=bytearray.fromhex(r['terrainHex']);struct.pack_into('<I',data,256+24*model.MAX_CELLS+12,3);r['terrainHex']=data.hex()
        def missing(r):
            data=bytearray.fromhex(r['terrainHex']);data[native.RECEIPT_BASE_SIZE:]=bytes(33208);r['terrainHex']=data.hex()
        for mutation in (badtype,missing):
            result=self.result(mutation);self.assertFalse(result['ok']);self.assertTrue(result['outcomeUncertain']);self.assertFalse(result['safeToRelease'])

class BatchTests(unittest.TestCase):
    def test_real_decoder_two_card_chain_accepts_and_blocks_replay(self):
        with fixture() as (root,catalog_run):
            home=root/'home';folder=home/'AppData/LocalLow/miHoYo/原神/BeyondLocal/123/Beyond_Local_Save_Level'
            source=folder/str(LEVEL)/f'{LEVEL}.gil';source.parent.mkdir(parents=True);source.write_bytes(save([cell(1,2)]))
            sibling=folder/'1073741842/1073741842.gil';sibling.parent.mkdir();sibling.write_bytes(b'protected private stub')
            edits=root/'edits.json';put(edits,[dict(op='replace-top',x=1,z=2,waterType=1),dict(op='change-water-type',x=1,z=2,waterType=3)])
            created=batch.create(ns(save=str(source),terrain_id=1001,edits=str(edits),chunk_size=1,catalog_run=str(catalog_run)))
            directory=Path(created['batch']);plan=batch.load(directory)[1];last=None
            for index,step in enumerate(plan['steps']):
                when=datetime.now(timezone.utc)-timedelta(seconds=60-index*10)
                inspection=raw_receipt(native.OUT/f'inspect-{index}',step['before'],step['before'],when=when)
                observed=batch.original(inspection);baseline=root/f'baseline-{index}';baseline.mkdir();put(baseline/'exit.json',dict(finishedUtc=(when+timedelta(seconds=2)).isoformat()))
                args=ns(batch=str(directory),inspection=str(inspection),baseline=str(baseline))
                def private_compile_stub(request):
                    card=batch.plan_for_prepare(request,observed['built']['session'],observed['scene'])
                    run=native.OUT/f'card-{index}';request._run_started(run)
                    raw_receipt(run,card['before'],card['expected'],card,source.read_bytes(),when=when+timedelta(seconds=3),pins=request._batch_pins)
                    return dict(ok=True,run=str(run),called=False,explicitPrivateNativeStub=True)
                with patch.object(native,'prepare',side_effect=private_compile_stub):prepared=batch.prepare(args)
                last=Path(prepared['run'])
                with self.assertRaises(ValueError):batch.abandon(ns(batch=str(directory)))
                accepted=batch.accept(ns(batch=str(directory),run=str(last)))
                self.assertEqual(accepted['acceptedCards'],index+1)
                self.assertTrue(batch.accept(ns(batch=str(directory),run=str(last)))['alreadyAccepted'])
                with self.assertRaises(ValueError):
                    with batch.dispatch_guard(batch.read(last/'request.json')):pass
            self.assertTrue(batch.status(ns(batch=str(directory)))['complete'])
            after=save([cell(1,2,4,0,(3,0,0))],stamp=101)
            verified=batch.saved_content(batch.read(last/'request.json'),source.read_bytes(),after)
            self.assertTrue(verified['completeChainVerified']);self.assertFalse(verified['nativeSaveVerified'])
            self.assertEqual(sibling.read_bytes(),b'protected private stub')
            original=Path(batch.read(last/'request.json')['batch']['inspectionRun'])/'stdout.jsonl'
            original.write_bytes(original.read_bytes()+b' ')
            with self.assertRaises(ValueError):batch.saved_content(batch.read(last/'request.json'),source.read_bytes(),after)

if __name__=='__main__':unittest.main()
