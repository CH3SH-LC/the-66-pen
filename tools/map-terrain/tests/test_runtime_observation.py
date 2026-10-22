"""Actual wire fixtures for complete geometry enumeration and bound physical hits."""
import json,struct,sys,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import terrain_runtime as runtime
import terrain_native as native

KEY=1|(2<<16)
START=208+2*runtime.CAPACITY*runtime.COMPONENT.size

def fixture(hit=True,present=True):
    data=bytearray(runtime.SIZE)
    head=dict.fromkeys(runtime.HEADER,0)
    head.update(size=runtime.SIZE,version=1,status=0,stage=4,readCalls=13,root=100,colliderClass=200,rendererClass=300,
                colliderArray=400,rendererArray=500,colliderCount=1,rendererCount=1,scannedColliders=1,scannedRenderers=1,targetCount=1)
    struct.pack_into('<16Q',data,0,*[head[n] for n in runtime.HEADER])
    matrix=[1.,0,0,0,0,1.,0,0,0,0,1.,0,-5.,0,-10.,1.]
    struct.pack_into('<20f',data,128,*matrix,5.,2.5,5.,0)
    for i in range(2):runtime.COMPONENT.pack_into(data,208+i*runtime.CAPACITY*runtime.COMPONENT.size,1000+i,2000+i,1,1,0,0,0,0,0,2.5,1.,2.5)
    struct.pack_into('<8Q12f',data,START,KEY,600 if present else 0,700 if present else 0,800 if present else 0,0,int(present),1,int(hit),
                     0.,0.,0.,0., 0.,2.,0.,4., 0.,-1.,0.,0.)
    if hit:
        struct.pack_into('<2Q',data,START+112,1000,0)
        offset=START+128;struct.pack_into('<Q',data,offset,1000)
        struct.pack_into('<3f',data,offset+8,0.,1.,0.)
        struct.pack_into('<3f',data,offset+20,0.,1.,0.)
        struct.pack_into('<f',data,offset+40,1.)
        struct.pack_into('<i',data,offset+52,123)
    return data

class RuntimeTests(unittest.TestCase):
    def result(self,data=None,present=True):return runtime.decode(bytes(fixture() if data is None else data),[KEY],[[KEY,1,0,0,0,0]] if present else [])
    def test_full_physical_hit_and_renderer_state_are_independent(self):
        r=self.result();self.assertTrue(r['ok'],r['reasons']);self.assertEqual(r['targets'][0]['nearestHit']['point'],[0.,1.,0.])
        self.assertFalse(r['pixelAppearanceVerified']);self.assertFalse(r['playerBlockingVerified'])
        self.assertFalse(r['renderers'][0]['isVisible']) # Camera visibility is not a failure.
        self.assertTrue(r['targets'][0]['anchorInteriorVerified'])
    def test_deleted_cell_still_has_real_ray_query(self):
        r=self.result(fixture(hit=False,present=False),False)
        self.assertTrue(r['ok'],r['reasons']);self.assertEqual(r['targets'][0]['rayTests'],1);self.assertIsNone(r['targets'][0]['nearestHit'])
    def test_deleted_cell_residual_collider_hit_remains_reported(self):
        r=self.result(fixture(hit=True,present=False),False)
        self.assertTrue(r['ok'],r['reasons']);self.assertIsNotNone(r['targets'][0]['nearestHit'])
    def test_wrong_hit_identity_rejected(self):
        d=fixture();struct.pack_into('<Q',d,START+128,999);self.assertIn('RUNTIME_HIT_OBJECT_BINDING',self.result(d)['reasons'])
    def test_short_ray_cannot_prove_no_collision(self):
        d=fixture(False);struct.pack_into('<f',d,START+92,1.);self.assertIn('RUNTIME_RAY_RANGE',self.result(d)['reasons'])
    def test_truncated_components_rejected(self):
        d=fixture();struct.pack_into('<Q',d,12*8,0);self.assertIn('RUNTIME_INCOMPLETE_ENUMERATION',self.result(d)['reasons'])
    def test_unqueried_candidate_rejected(self):
        d=fixture(False);struct.pack_into('<Q',d,START+48,0);self.assertIn('RUNTIME_RAY_ENUMERATION',self.result(d)['reasons'])
    def test_dirty_rebuild_not_accepted(self):
        d=fixture();struct.pack_into('<Q',d,START+32,1);self.assertIn('RUNTIME_CELL_NOT_REBUILT',self.result(d)['reasons'])
    def test_hit_point_must_match_ray_and_bounds(self):
        d=fixture();struct.pack_into('<f',d,START+128+8,100.);r=self.result(d)
        self.assertIn('RUNTIME_HIT_POINT',r['reasons']);self.assertIn('RUNTIME_HIT_BOUNDS',r['reasons'])
    def test_nonfinite_bounds_rejected(self):
        d=fixture();struct.pack_into('<f',d,208+32,float('nan'));self.assertIn('RUNTIME_BOUNDS',self.result(d)['reasons'])
    def test_pivot_on_collider_boundary_is_not_proven_interior(self):
        d=fixture();struct.pack_into('<f',d,208+32,2.5)
        r=self.result(d);self.assertTrue(r['ok'],r['reasons']);self.assertFalse(r['targets'][0]['anchorInteriorVerified'])
    def test_unsupported_hit_tail_rejected(self):
        d=fixture();d[START+128+56]=1;self.assertIn('RUNTIME_HIT_LAYOUT_DRIFT',self.result(d)['reasons'])
    def test_request_is_bounded_unique_and_has_only_coordinates(self):
        self.assertEqual(runtime.cells([{'x':1,'z':2}]),[KEY])
        for value in ([],[{'x':True,'z':2}],[{'x':1,'z':2}]*2,[{'x':1,'z':2,'height':1}],[{'x':9999,'z':0}]):
            with self.subTest(value=value),self.assertRaises(ValueError):runtime.cells(value)
    def test_runtime_candidate_preserves_ordinary_receipt_protocol(self):
        for observation,version in ((False,18),(True,20)):
            with tempfile.TemporaryDirectory(dir=native.ROOT/'.runtime') as tmp:
                run=Path(tmp);native.sources(run,observation)
                protocol=(run/'candidate-source/native/hook_receipt_protocol.h').read_text()
                self.assertIn('HR_ACTION == 14 ? '+str(version),protocol)
                self.assertTrue((run/'candidate-source/map-terrain/terrain_runtime.inc').is_file())
    def test_runtime_receipt_requires_its_own_protocol(self):
        # Reuse the fully valid ordinary transport/session fixture, then change
        # only the precise readonly/runtime payload and card authority.
        import test_receipt_binding
        with tempfile.TemporaryDirectory(dir=native.OUT) as tmp:
            run=Path(tmp);test_receipt_binding.ReceiptTests().fixture(run)
            built=native.ro.read_json(run/'build-result.json');built.update(inspectOnly=True,runtimeProbe=True,runtimeKeys=[KEY],receiptVersion=20)
            plan=native.ro.read_json(run/'request.json');plan['runtimeKeys']=[KEY]
            record=native.ro.read_json(run/'stdout.jsonl');data=bytearray.fromhex(record['terrainHex'])
            head=dict(zip(native.HEADER_NAMES,struct.unpack_from('<32Q',data)))
            head.update(size=len(data)+runtime.SIZE,version=2,mutationCalls=0,completed=0,openCalled=0,snapshotCalled=0,notifyCalled=0,closeCalled=0)
            struct.pack_into('<32Q',data,0,*[head[n] for n in native.HEADER_NAMES])
            data[256+24*65536:256+24*65536+24]=data[256:280]
            data.extend(fixture());record.update(terrainBytes=len(data),terrainHex=data.hex())
            prefix=bytearray.fromhex(record['receiptPrefixHex']);struct.pack_into('<I',prefix,4,20);record['receiptPrefixHex']=prefix.hex()
            for path,value in [('build-result.json',built),('request.json',plan),('stdout.jsonl',record)]:
                (run/path).write_text(json.dumps(value),encoding='utf-8')
            (run/'prepared.json').write_text(json.dumps({'kind':'native-terrain-prepared-v1','run':str(run),'buildResultSha256':native.profiles.sha256(run/'build-result.json')}))
            exit_record=native.ro.read_json(run/'exit.json');exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl')
            (run/'exit.json').write_text(json.dumps(exit_record))
            r=native.decode(run);self.assertTrue(r['ok'],r['reasons']);self.assertTrue(r['physicalQueryVerified'])
            struct.pack_into('<I',prefix,4,18);record['receiptPrefixHex']=prefix.hex();(run/'stdout.jsonl').write_text(json.dumps(record))
            exit_record['stdoutSha256']=native.profiles.sha256(run/'stdout.jsonl');(run/'exit.json').write_text(json.dumps(exit_record))
            r=native.decode(run);self.assertFalse(r['ok']);self.assertIn('CARD_PREFIX_OR_SESSION_BINDING',r['reasons'])

    def version2(self,data=None,gate=0):
        data=fixture() if data is None else data
        struct.pack_into('<Q',data,8,2);struct.pack_into('<Q',data,15*8,1|(gate<<1))
        struct.pack_into('<f',data,START+76,1.)
        return data

    def test_v2_records_actual_tool_tick_gate_without_changing_it(self):
        for gate in (0,1):
            r=runtime.decode(self.version2(gate=gate),[KEY],[[KEY,1,0,0,0,0]],2)
            self.assertTrue(r['ok'],r['reasons']);self.assertTrue(r['tickGateKnown']);self.assertEqual(r['tickGateActive'],bool(gate))
            self.assertTrue(r['targets'][0]['captured'])

    def test_v2_partial_target_is_missing_evidence_not_absent_cell(self):
        data=self.version2();struct.pack_into('<Q',data,14*8,2);struct.pack_into('<Q',data,3*8,3)
        r=runtime.decode(data,[KEY,KEY+1],[[KEY,1,0,0,0,0],[KEY+1,1,0,0,0,0]],2)
        self.assertFalse(r['ok']);self.assertIn('RUNTIME_TARGET_NOT_CAPTURED',r['reasons'])
        self.assertTrue(r['targets'][0]['captured']);self.assertEqual(r['targets'][1],dict(x=2,z=2,key=KEY+1,captured=False))
        self.assertNotIn('logicalPresent',r['targets'][1]);self.assertFalse(r['physicalQueryVerified'])

    def test_v2_dirty_preserves_physical_hits_but_cannot_pass(self):
        data=self.version2();struct.pack_into('<Q',data,START+32,1);struct.pack_into('<Q',data,2*8,1)
        r=runtime.decode(data,[KEY],[[KEY,1,0,0,0,0]],2)
        self.assertFalse(r['ok']);self.assertIn('RUNTIME_CELL_NOT_REBUILT',r['reasons'])
        self.assertTrue(r['targets'][0]['captured']);self.assertIsNotNone(r['targets'][0]['nearestHit'])

    def test_v2_zero_gate_evidence_and_wrong_version_fail(self):
        data=self.version2();struct.pack_into('<Q',data,15*8,0)
        self.assertIn('RUNTIME_RESERVED',runtime.decode(data,[KEY],[[KEY,1,0,0,0,0]],2)['reasons'])
        self.assertIn('RUNTIME_STATUS',runtime.decode(data,[KEY],[[KEY,1,0,0,0,0]],1)['reasons'])

    def test_coheight_core_hit_proves_interior_when_nearest_quadrant_is_on_edge(self):
        data=self.version2()
        # First hit: a quadrant ending at x=0. Second hit: the full cell core.
        struct.pack_into('<f',data,208+32,-2.5)
        struct.pack_into('<Q',data,10*8,2);struct.pack_into('<Q',data,12*8,2)
        runtime.COMPONENT.pack_into(data,208+runtime.COMPONENT.size,1002,2002,1,1,0,0,0,0,0,2.5,1.,2.5)
        struct.pack_into('<2Q',data,START+48,2,2)
        data[START+112+96:START+112+192]=data[START+112:START+112+96]
        struct.pack_into('<3Q',data,START+112+96,1002,1,1002)
        r=runtime.decode(data,[KEY],[[KEY,1,0,0,0,0]],2)
        self.assertTrue(r['ok'],r['reasons']);self.assertEqual(r['targets'][0]['nearestHit']['collider'],1000)
        self.assertTrue(r['targets'][0]['anchorInteriorVerified']);self.assertEqual(r['targets'][0]['interiorHitColliders'],[1002])

    def test_runtime_still_readonly_and_dirty_rejects_only_after_all_queries(self):
        source=(HERE/'terrain_runtime.inc').read_text()
        self.assertNotIn('0xba50e20',source);self.assertNotIn('WriteProcessMemory',source)
        self.assertLess(source.index('runtimeTarget(base,o,r.targets[i],i)'),source.index('if(r.targets[i].dirty)return false'))
        self.assertIn('t.worldCenter[3]=1',source)

if __name__=='__main__':unittest.main()
