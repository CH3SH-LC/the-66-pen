"""Current-build shape semantics, original binary receipts and save protection.

Fixtures are synthetic local files. No game process, native terrain, queue or
desktop is accessed. Run with the full completed-module offline batch only.
"""
from contextlib import redirect_stdout
import io,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path[:0]=[str(HERE),str(HERE/'tests')]
import terrain_model as model
import terrain_shapes_v3 as shapes
import terrain_native as native
import terrain_batch as batch
import terrain_cli as cli
import terrain_guard_profile as guards
import test_receipt_binding as receipts
import test_save_proof as saving
import test_batch as batches
from test_terrain_model import cell,save

def edit(**values):return dict(x=1,z=2,op='surface',**values)
def slope(kind=1,direction='z+'):return dict(type=kind,direction=direction)
def put(path,value):path.write_text(json.dumps(value),encoding='utf-8')

def bind_surface(run,plan,word=31|shapes.MASK):
    put(run/'request.json',plan)
    built=native.ro.read_json(run/'build-result.json')
    built.update(shapeSemantics=plan['shapeSemantics'],shapeGuardVersion=1,requiresRenderRebuild=True,renderRebuildEvidenceVersion=1)
    record=native.ro.read_json(run/'stdout.jsonl');raw=bytearray.fromhex(record['terrainHex'])
    struct.pack_into('<Q',raw,native.HEADER_NAMES.index('reserved')*8,word)
    for offset,row in ((256,plan['before'][0]),(256+24*model.MAX_CELLS,plan['expected'][0])):struct.pack_into('<6I',raw,offset,*row)
    record['terrainHex']=raw.hex();put(run/'stdout.jsonl',record)
    exit_record=native.ro.read_json(run/'exit.json');exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl');put(run/'exit.json',exit_record)
    saving.repin_terrain(run,built)

class SurfaceFixture(batches.Fixture):
    def raw(self,*args,**kwargs):
        run=super().raw(*args,**kwargs);card=kwargs.get('card')
        if card and card.get('shapeSemantics'):bind_surface(run,card)
        return run

class ShapeModelTests(unittest.TestCase):
    def test_all_twelve_native_slope_encodings(self):
        for t in (1,2,3):
            for name,d in shapes.DIRECTIONS.items():
                with self.subTest(type=t,direction=name):
                    code=shapes.encode_slope(slope(t,name));self.assertEqual(code,(t<<4)|d)
                    self.assertEqual(shapes.decode_slope(code)['direction'],name)
                    self.assertEqual(shapes.decode_slope(code)['type'],t)
                    self.assertFalse(shapes.decode_slope(code)['uiLabelVerified'])

    def test_invalid_type_direction_and_raw_encoding_rejected(self):
        for value in (0,16,{'type':0,'direction':'z+'},{'type':4,'direction':'z+'},
                      {'type':True,'direction':'z+'},{'type':1,'direction':0},{'type':1,'direction':'world-front'},
                      {'type':1,'direction':'z+','extra':0},{'variant':'front','direction':'z+'}):
            with self.subTest(value=value),self.assertRaises(ValueError):shapes.encode_slope(value)

    def test_unknown_existing_codes_are_reported_without_normalization(self):
        description=shapes.describe([[model.key(1,2),4,7,2,99,5]])['cells'][0]
        self.assertFalse(description['path']['known']);self.assertFalse(description['slope']['known'])
        self.assertEqual(description['waterType'],2);self.assertEqual(description['slope']['raw'],5)

    def test_set_slope_retains_height_material_and_other_cells(self):
        blob=save([cell(1,2,4,7),cell(7,9,3,8,(12,99,123))])
        plan=model.make_plan(blob,1001,[edit(slope=slope(2,'x-'))])
        self.assertEqual(plan['schema'],shapes.SCHEMA);self.assertEqual(plan['expected'][0],[model.key(1,2),4,7,0,0,35])
        self.assertEqual(plan['before'][1],plan['expected'][1]);self.assertEqual(model.validate_plan(plan,blob),plan)

    def test_slope_remove_and_rotate_preserve_column(self):
        blob=save([cell(1,2,8,4,(0,0,16))])
        removed=model.make_plan(blob,1001,[edit(slope=None)])
        self.assertEqual(removed['expected'][0],[model.key(1,2),8,4,0,0,0])
        rotated=model.make_plan(blob,1001,[edit(slope=slope(1,'x+'))])
        self.assertEqual(rotated['expected'][0][5],17)

    def test_water_never_silently_cleared(self):
        blob=save([cell(1,2,2,0,(7,0,0))])
        for operation in (edit(slope=slope()),edit(path=True)):
            with self.assertRaisesRegex(ValueError,'WATER'):model.make_plan(blob,1001,[operation])
        self.assertEqual(model.select(model.decode_save(blob),1001)['cells'][0][3],7)

    def test_path_remove_retains_water_and_slope_exactly(self):
        blob=save([cell(1,2,2,0,(7,1,17))])
        plan=model.make_plan(blob,1001,[edit(path=False)])
        self.assertEqual(plan['expected'][0][1:],[2,0,7,0,17])

    def test_path_set_on_existing_slope_preserves_it(self):
        blob=save([cell(1,2,3,0,(0,0,34))])
        plan=model.make_plan(blob,1001,[edit(path=True)])
        self.assertEqual(plan['expected'][0][1:],[3,0,0,1,34])

    def test_slope_change_on_path_requires_explicit_removal(self):
        blob=save([cell(1,2,3,0,(0,1,16))])
        for operation in (edit(slope=None),edit(slope=slope(2))):
            with self.assertRaisesRegex(ValueError,'EXPLICIT_PATH'):model.make_plan(blob,1001,[operation])
        plan=model.make_plan(blob,1001,[edit(slope=slope(2),path=False)])
        self.assertEqual(plan['expected'][0][3:],[0,0,32])

    def test_new_slope_and_path_in_same_card_rejected(self):
        with self.assertRaisesRegex(ValueError,'SEPARATE_ACCEPTED_CARD'):
            model.make_plan(save([cell(1,2)]),1001,[edit(slope=slope(),path=True)])

    def test_unknown_surface_fields_and_non_boolean_path_rejected(self):
        blob=save([cell(1,2)])
        for operation in (edit(path=1),edit(path='true'),edit(path=True,extraB=1),edit(),edit(slope=16)):
            with self.subTest(operation=operation),self.assertRaises(ValueError):model.make_plan(blob,1001,[operation])

    def test_unknown_existing_extra_fields_not_rewritten(self):
        for extras in ((0,2,0),(0,0,4),(0,0,64),(0,0,20)):
            with self.subTest(extras=extras),self.assertRaisesRegex(ValueError,'UNKNOWN_EXISTING'):
                model.make_plan(save([cell(1,2,1,0,extras)]),1001,[edit(path=True)])

    def test_zero_height_or_missing_base_refused_without_explicit_creation(self):
        for blob,operation in ((save([cell(1,2,0,0,(1,0,0))]),edit(path=False)),
                               (save([cell(5,5)]),edit(slope=slope())),
                               (save([cell(1,2)]),edit(slope=slope(),height=0))):
            with self.assertRaises(ValueError):model.make_plan(blob,1001,[operation])

    def test_new_surface_with_explicit_observed_height_and_material(self):
        plan=model.make_plan(save([cell(5,5,1,3)]),1001,[edit(height=2,material=3,slope=slope(3,'z-'))])
        self.assertEqual(plan['expected'][0],[model.key(1,2),2,3,0,0,50])
        with self.assertRaisesRegex(ValueError,'MATERIAL_NOT_OBSERVED'):
            model.make_plan(save([cell(5,5)]),1001,[edit(height=2,material=3,path=True)])

    def test_material_change_affects_base_and_slope_via_same_native_field(self):
        blob=save([cell(1,2,2,0,(0,0,16)),cell(5,5,1,3)])
        plan=model.make_plan(blob,1001,[edit(slope=slope(1),material=3)])
        self.assertEqual(plan['expected'][0][1:],[2,3,0,0,16])

    def test_noop_and_duplicate_cell_do_not_make_native_card(self):
        blob=save([cell(1,2,2,0,(0,0,16))])
        with self.assertRaisesRegex(ValueError,'NO_OP'):model.make_plan(blob,1001,[edit(slope=slope())])
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):model.make_plan(blob,1001,[edit(path=True),edit(path=False)])

    def test_semantics_and_expected_tampering_rejected(self):
        blob=save([cell(1,2)]);plan=model.make_plan(blob,1001,[edit(slope=slope())])
        for key in ('shapeSemantics','expected'):
            modified=json.loads(json.dumps(plan));modified[key]={}
            with self.assertRaises(ValueError):model.validate_plan(modified,blob)

    def test_save_content_checks_slope_path_and_unrelated_opaque_fields(self):
        blob=save([cell(1,2),cell(6,7,2,3,(99,7,888))],second=[cell(9,9)])
        plan=model.make_plan(blob,1001,[edit(slope=slope(2))])
        correct=save([cell(1,2,1,0,(0,0,32)),cell(6,7,2,3,(99,7,888))],second=[cell(9,9)],stamp=101)
        result=model.verify_save(blob,correct,plan)
        self.assertTrue(result['surfaceDataContentVerified']);self.assertFalse(result['nativeSurfaceSaveVerified'])
        for extras in ((0,0,33),(0,1,32),(1,0,32)):
            wrong=save([cell(1,2,1,0,extras),cell(6,7,2,3,(99,7,888))],second=[cell(9,9)])
            self.assertFalse(model.verify_save(blob,wrong,plan)['ok'])

    def test_generator_retains_explicit_values_and_rejects_alias_guessing(self):
        spec={'cells':[dict(x=1,z=2,slope=slope(3,'x-')),dict(x=2,z=2,path=True)]}
        edits=shapes.generate(spec);self.assertEqual(edits,[edit(slope=slope(3,'x-')),dict(x=2,z=2,path=True,op='surface')])
        for bad in ({'cells':[dict(x=1,z=2,slope={'type':'front','direction':'z+'})]},
                    {'cells':[dict(x=1,z=2,path=True),dict(x=1,z=2,path=False)]},
                    {'cells':[dict(x=1,z=2,extraC=16)]}):
            with self.assertRaises(ValueError):shapes.generate(bad)

    def test_multi_card_slope_then_path_uses_accepted_expected_rows(self):
        plan=batch.compile_plan(save([cell(1,2)]),1001,[edit(slope=slope()),edit(path=True)],'source.gil',1073741900,1)
        self.assertEqual(plan['shapeSemantics'],shapes.binding());self.assertEqual(plan['steps'][1]['before'],plan['steps'][0]['expected'])
        self.assertEqual(plan['expected'][0][3:],[0,1,16])

    def test_resource_requirements_deduplicate_actual_material_and_types(self):
        plan=model.make_plan(save([cell(1,2),cell(2,2,1,0,(0,0,32))]),1001,
                             [edit(slope=slope()),dict(x=2,z=2,op='surface',path=True)])
        self.assertEqual(shapes.requirements(plan),[dict(material=0,slopeTypeMask=6,path=True)])

class ShapeEvidenceTests(unittest.TestCase):
    def temporary(self):
        native.OUT.mkdir(parents=True,exist_ok=True);return tempfile.TemporaryDirectory(prefix='shapes-fixture-',dir=native.OUT)

    def fixture(self,run,word=31|shapes.MASK):
        receipts.ReceiptTests().fixture(run)
        blob=(run/'before.gil').read_bytes();plan=model.make_plan(blob,1001,[edit(slope=slope())],str(run/'1073741900.gil'))
        bind_surface(run,plan,word);return plan

    def test_full_original_receipt_proves_data_and_resources_not_visuals(self):
        with self.temporary() as tmp:
            run=Path(tmp).resolve();self.fixture(run);result=native.decode(run)
            self.assertTrue(result['ok'],result);self.assertTrue(result['nativeSurfaceDataVerified']);self.assertTrue(result['nativeSurfaceResourcesVerified'])
            self.assertTrue(result['nativeRenderRebuildVerified']);self.assertFalse(result['shapeVisualVerified']);self.assertFalse(result['playerTraversalVerified'])

    def test_pre_or_post_guard_missing_cannot_be_reported_success(self):
        for word in (31,31|shapes.PRE,31|shapes.POST):
            with self.subTest(word=word),self.temporary() as tmp:
                run=Path(tmp).resolve();self.fixture(run,word);result=native.decode(run)
                self.assertFalse(result['ok']);self.assertTrue(result['outcomeUncertain']);self.assertFalse(result['safeToRelease'])

    def test_shape_binding_cannot_be_dropped_from_build(self):
        with self.temporary() as tmp:
            run=Path(tmp).resolve();self.fixture(run);built=native.ro.read_json(run/'build-result.json');built.pop('shapeSemantics')
            saving.repin_terrain(run,built);self.assertIn('SHAPE_GUARD_REQUEST_BINDING',native.decode(run)['reasons'])

    def test_unassigned_receipt_bits_remain_rejected(self):
        with self.temporary() as tmp:
            run=Path(tmp).resolve();self.fixture(run,31|shapes.MASK|128)
            self.assertIn('NATIVE_RENDER_REBUILD_NOT_VERIFIED',native.decode(run)['reasons'])

    def test_wrong_slope_in_raw_receipt_rejected_despite_guard_flags(self):
        with self.temporary() as tmp:
            run=Path(tmp).resolve();self.fixture(run);record=native.ro.read_json(run/'stdout.jsonl');raw=bytearray.fromhex(record['terrainHex'])
            struct.pack_into('<I',raw,256+24*model.MAX_CELLS+20,17);record['terrainHex']=raw.hex();put(run/'stdout.jsonl',record)
            exit_record=native.ro.read_json(run/'exit.json');exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl');put(run/'exit.json',exit_record)
            self.assertIn('INDEPENDENT_CELL_COMPARISON',native.decode(run)['reasons'])

    def test_native_save_chain_binds_surface_content_and_other_domains(self):
        with saving.complete_fixture() as (run,saved,built,profile,reply):
            before=(run/'before.gil').read_bytes();plan=model.make_plan(before,1001,[edit(height=2,slope=slope(3,'x+'))],built['sourceSave'])
            bind_surface(run,plan)
            after=saving.with_roots(save([cell(1,2,2,0,(0,0,49))],stamp=101))
            saving.update_copy(saved,reply,'after',saving.LEVEL,after)
            result=saving.proof.verify(run,saved)
            self.assertTrue(result['nativeSurfaceSaveVerified']);self.assertTrue(result['entityRootPreserved']);self.assertFalse(result['shapeVisualVerified'])

    def test_two_surface_cards_chain_original_after_and_preserve_disk(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as tmp:
            root=Path(tmp);(root/'prepared').mkdir()
            with patch.object(Path,'home',return_value=root/'home'),patch.object(batch,'OUT',root/'batches'),patch.object(native,'OUT',root/'prepared'):
                f=SurfaceFixture(root,edits=[edit(slope=slope()),edit(path=True)])
                original=f.source.read_bytes();first=f.next();batch.accept(batches.ns(batch=f.directory,run=first))
                second=f.next();card=batch.read(second/'request.json');self.assertEqual(card['before'][0][5],16)
                self.assertTrue(batch.accept(batches.ns(batch=f.directory,run=second))['complete']);self.assertEqual(f.source.read_bytes(),original)
                content=batch.saved_content(card,original,save([cell(1,2,1,0,(0,1,16))],stamp=101))
                self.assertTrue(content['surfaceDataContentVerified']);self.assertFalse(content['nativeSurfaceSaveVerified'])

    def test_private_candidate_keeps_protocol_and_includes_exact_resource_requirements(self):
        for size in (33208,262584):
            with self.subTest(size=size),tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as tmp:
                run=Path(tmp);native.sources(run);plan=model.make_plan(save([cell(1,2)]),1001,[edit(slope=slope(2,'x-'))])
                native.request_header(run,plan,bytes(size),1073741900,False)
                text=(run/'candidate-source/map-terrain/terrain_request.h').read_text()
                self.assertIn('{0U,4U,false}',text);self.assertIn('TERRAIN_SHAPE_MATERIAL_COUNT 1U',text)
                self.assertIn('HR_ACTION == 14 ? 18',(run/'candidate-source/native/hook_receipt_protocol.h').read_text())

    def test_profile_covers_real_setter_and_renderer_guards(self):
        profile=json.loads(shapes.PROFILE.read_text());fixture=json.loads((HERE/'tests/fixtures/shapes-guards-v3.json').read_text())
        actual=guards.classify_profile(fixture['functions'])
        self.assertEqual(actual['hotfixZeroRvas'],profile['hotfixZeroRvas']);self.assertEqual(actual['initializationBooleanRvas'],profile['initializationBooleanRvas'])
        functions={row['rva']:row['assembly'] for row in fixture['functions']}
        self.assertIn('shl edi, 4',functions['0xba56790']);self.assertIn('mov dword ptr [rsp + 0x20], 1',functions['0xf5c8b60'])
        self.assertIn('mov rdi, qword ptr [rax + 0x10]',functions['0xba4c850'])
        self.assertTrue(all(model.digest((model.ROOT/f['evidence']).read_bytes())==f['sha256'] for f in profile['functions']))

    def test_guard_is_before_transaction_and_after_rebuild_without_abi_growth(self):
        source=(HERE/'native_terrain.cpp').read_text()
        self.assertLess(source.index('shapeResources(*scene,o,scratch,shapeResourcesBefore)'),source.index('o->openCalled=1'))
        self.assertLess(source.index('rebuild(*scene,o,scratch,kTerrainAfter'),source.index('shapeResources(*scene,o,scratch,shapeResourcesAfter)'))
        self.assertIn('shapeResourcesBefore!=shapeResourcesAfter',source)
        self.assertNotIn('TerrainShape',(HERE/'native_terrain.h').read_text())

    def test_cli_generator_and_reader_emit_single_json_and_project_output(self):
        with tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as tmp:
            root=Path(tmp);spec=root/'spec.json';put(spec,{'cells':[dict(x=1,z=2,slope=slope())]});output=root/'edits.json'
            capture=io.StringIO()
            with redirect_stdout(capture):code=cli.main(['surface-edits','--spec',str(spec),'--output',str(output)])
            self.assertEqual(code,0,capture.getvalue());self.assertTrue(json.loads(capture.getvalue())['ok']);self.assertEqual(json.loads(output.read_text()),[edit(slope=slope())])
            capture=io.StringIO()
            with redirect_stdout(capture):code=cli.main(['surfaces'])
            result=json.loads(capture.getvalue());self.assertEqual(code,0);self.assertFalse(result['nativeCellsVerified']);self.assertFalse(result['semantics']['symbolicTypeLabelsVerified'])

    def test_cli_original_receipt_surface_read_does_not_trust_sidecar(self):
        with self.temporary() as tmp:
            run=Path(tmp).resolve();self.fixture(run);capture=io.StringIO()
            with redirect_stdout(capture):code=cli.main(['surfaces','--run',str(run)])
            result=json.loads(capture.getvalue());self.assertEqual(code,0,capture.getvalue());self.assertTrue(result['nativeCellsVerified'])
            self.assertEqual(result['cells'][0]['slope']['type'],1)

if __name__=='__main__':unittest.main()
