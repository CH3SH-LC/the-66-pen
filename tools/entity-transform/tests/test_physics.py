"""Offline physics evidence checks, to be run only after the unified gate."""
import copy
import math
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import physics_receipt as p

I=[float(i%5==0) for i in range(16)]

def matrices(angle=0,scale=(1,1,1),position=(0,0,0)):
    c,s=math.cos(angle),math.sin(angle);x,y,z=scale
    m=[c*x,0,-s*x,0, 0,y,0,0, s*z,0,c*z,0, *position,1]
    inv=[c/x,0,s/z,0, 0,1/y,0,0, -s/x,0,c/z,0, 0,0,0,1]
    inv[12:15]=[-sum(inv[k*4+r]*position[k] for k in range(3)) for r in range(3)]
    return m,inv

def entity(angle=0,scale=(1,1,1),position=(0,0,0)):
    m,inv=matrices(angle,scale,position);rays=[]
    for index in range(6):
        axis=index//2;sign=-1 if index%2 else 1
        local=[0.,0.,0.];local[axis]=sign*.5
        hit=p.point(m,local);v=[m[axis*4+r] for r in range(3)];length=p.distance(v,[0,0,0]);normal=[sign*x/length for x in v]
        origin=[x+n*2 for x,n in zip(hit,normal)]
        rays.append(dict(origin=origin,direction=[-n for n in normal],maxDistance=4.,hit=1,collider=100,point=hit,normal=normal,distance=2.))
    q=[0,math.sin(angle/2),0,math.cos(angle/2)]
    return dict(localToWorld=m,worldToLocal=inv,actualLocalRotation=q,expectedLocalRotation=q,
        colliders=[dict(collider=100,klass=500,belongs=1,stable=1,enabled=1,active=1,isTrigger=0,isSceneQuery=1,localToWorld=m,rays=rays)])

class PhysicsTests(unittest.TestCase):
    def test_nonuniform_rotation_translation_matches_reference(self):
        ref=entity(scale=(.25,.25,.25),position=(200,15,200))
        target=entity(math.pi/3,(1,1.25,.75),(6,1,5))
        self.assertTrue(p.compare(p.samples(ref),p.samples(target)))
    def test_inverse_matrix_layout(self):
        a,b=matrices(.8,(2,3,4),(5,6,7));self.assertTrue(p.close(p.matmul(a,b),I,1e-6))
    def test_quaternion_sign_equivalence(self):self.assertTrue(p.quaternion_equal([0,0,0,1],[0,0,0,-1]))
    def test_unity_rotation_must_match_native_euler_conversion(self):
        e=entity();e['expectedLocalRotation']=[1,0,0,0]
        with self.assertRaisesRegex(ValueError,'ROTATION_DIFFERS'):p.samples(e)
    def test_stale_physics_translation_rejected(self):
        e=entity(position=(3,1,5));e['localToWorld'],e['worldToLocal']=matrices(position=(4,1,5))
        with self.assertRaisesRegex(ValueError,'MATCH_NOT_UNIQUE|POSITION_DIFFERS'):p.compare(p.samples(entity()),p.samples(e))
    def test_stale_shape_scale_rejected(self):
        e=entity();e['localToWorld'],e['worldToLocal']=matrices(scale=(2,1,1));e['colliders'][0]['localToWorld']=e['localToWorld']
        with self.assertRaisesRegex(ValueError,'POSITION_DIFFERS'):p.compare(p.samples(entity()),p.samples(e))
    def test_wrong_collider_hit_rejected(self):
        e=entity();e['colliders'][0]['rays'][0]['collider']=101
        with self.assertRaisesRegex(ValueError,'DIFFERENT_COLLIDER'):p.samples(e)
    def test_miss_rejected(self):
        e=entity();e['colliders'][0]['rays'][0]['hit']=0
        with self.assertRaisesRegex(ValueError,'MISSED'):p.samples(e)
    def test_trigger_not_solid(self):
        e=entity();e['colliders'][0]['isTrigger']=1
        with self.assertRaisesRegex(ValueError,'NO_ACTIVE'):p.samples(e)
    def test_disabled_not_solid(self):
        e=entity();e['colliders'][0]['enabled']=0
        with self.assertRaisesRegex(ValueError,'NO_ACTIVE'):p.samples(e)
    def test_non_query_shape_not_solid(self):
        e=entity();e['colliders'][0]['isSceneQuery']=0
        with self.assertRaisesRegex(ValueError,'NO_ACTIVE'):p.samples(e)
    def test_unstable_collider_refused(self):
        e=entity();e['colliders'][0]['stable']=0
        with self.assertRaisesRegex(ValueError,'STATE_CHANGED'):p.samples(e)
    def test_wrong_ray_distance_rejected(self):
        e=entity();e['colliders'][0]['rays'][0]['distance']=3.
        with self.assertRaisesRegex(ValueError,'POINT_NOT_ON_RAY'):p.samples(e)
    def test_wrong_normal_rejected(self):
        a=p.samples(entity());b=copy.deepcopy(a);b[0]['samples'][0]['normal']=[0,1,0]
        with self.assertRaisesRegex(ValueError,'NORMAL_DIFFERS'):p.compare(a,b)
    def test_duplicate_colliders_ambiguous(self):
        a=p.samples(entity());a*=2
        with self.assertRaisesRegex(ValueError,'MATCH_NOT_UNIQUE'):p.compare(a,a)
    def test_nonfinite_raw_rejected(self):
        with self.assertRaisesRegex(ValueError,'NONFINITE'):p.numbers(struct.pack('<f',float('nan')),0,1)
    def test_empty_preflight_receipt_both_abis(self):
        for size in (33208,262584):
            raw=bytearray(48+48+128*280+size+8*p.ENTITY_SIZE)
            struct.pack_into('<12I',raw,0,len(raw),1,1,1,0,8,0,0,0,0,0,0)
            report,after=p.extension(raw,size)
            self.assertEqual(report['completed'],0);self.assertEqual(after,bytes(size))
    def test_unused_entity_bytes_rejected(self):
        size=33208;raw=bytearray(48+48+128*280+size+8*p.ENTITY_SIZE)
        struct.pack_into('<12I',raw,0,len(raw),1,1,1,0,0,0,0,0,0,0,0);raw[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED_ENTITIES'):p.extension(raw,size)
    def test_raw_hit_build_specific_offsets(self):
        size=33208;tr_size=48+128*280+size;raw=bytearray(48+tr_size+8*p.ENTITY_SIZE)
        struct.pack_into('<12I',raw,0,len(raw),1,1,2,0,1,0,0,0,0,0,0)
        at=48+tr_size;struct.pack_into('<6I',raw,at,9,1,1,1,0,0)
        hit=at+200+144+32;struct.pack_into('<Q',raw,hit,0x12340000);struct.pack_into('<3f',raw,hit+8,1,2,3);struct.pack_into('<f',raw,hit+40,7)
        result,_=p.extension(raw,size);r=result['entities'][0]['colliders'][0]['rays'][0]
        self.assertEqual(r['collider'],0x12340000);self.assertEqual(r['point'],[1,2,3]);self.assertEqual(r['distance'],7)
        self.assertFalse(r['tagAndLayerPopulated'])

if __name__=='__main__':unittest.main()
