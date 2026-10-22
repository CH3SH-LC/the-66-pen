"""Offline regression cases. Run only after the map-foundation development gate."""
from pathlib import Path
import copy
import math
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import contract as c
from save_verify import reader_module, verify_payloads

def request(**fields):
    return dict(schemaVersion=1,levelId=123,positionSpace='world',rotationUnit='degrees',
                entities=[dict(entityId=7,**fields)])

POSE = dict(localPosition=[1.,2.,3.],rotationDegrees=[10.,20.,30.],scale=[1.,2.,3.],worldPosition=[101.,202.,303.])

def varint(n):
    result = bytearray()
    while n > 127:
        result.append((n & 127)|128);n >>= 7
    result.append(n)
    return bytes(result)

def scalar(field,n):
    return varint(field<<3)+varint(n)

def message(field,data):
    return varint((field<<3)|2)+varint(len(data))+data

def vec(field,values):
    return message(field,b''.join(varint((i<<3)|5)+struct.pack('<f',v) for i,v in enumerate(values,1)))

def saved(pose, *, graph=b'keep-me',other_name=b'protected'):
    transform = b''.join(vec(i,pose[k]) for i,k in enumerate(('localPosition','rotationDegrees','scale'),1))+scalar(4,42)
    wrapper = scalar(1,1)+message(11,transform)+scalar(501,17)
    entity = scalar(1,7)+message(4,b'changed-target')+message(6,wrapper)
    other = scalar(1,8)+message(4,other_name)
    return scalar(1,123)+message(5,message(1,entity)+message(1,other)+scalar(11,55))+message(10,graph)

class TransformContractTests(unittest.TestCase):
    def test_world_partial_axis_preserves_rotation_scale_and_axes(self):
        row = c.merge(request(position=[105,None,None]),{7:POSE},[100,200,300])[0]
        self.assertEqual(row['mask'],1)
        self.assertEqual(row['desired']['localPosition'],[5,2,3])
        self.assertEqual(row['desired']['worldPosition'],[105,202,303])
        self.assertEqual(row['desired']['rotationDegrees'],POSE['rotationDegrees'])
        self.assertEqual(row['desired']['scale'],POSE['scale'])
        self.assertEqual(row['expected'],POSE)

    def test_local_input_and_radians_become_native_degrees(self):
        value = request(position=[4,5,6],rotation=[None,math.pi/2,None])
        value.update(positionSpace='local',rotationUnit='radians')
        row = c.merge(value,{7:POSE},[100,200,300])[0]
        self.assertEqual(row['desired']['worldPosition'],[104,205,306])
        self.assertAlmostEqual(row['desired']['rotationDegrees'][1],90,places=4)
        self.assertEqual(row['desired']['rotationDegrees'][::2],[10,30])

    def test_all_field_forms_and_mask(self):
        row = c.merge(request(position=[1,2,3],rotation=[0,90,0],scale=[2,2,2]),{7:POSE},[100,200,300])[0]
        self.assertEqual(row['mask'],7)

    def test_nested_local_edit_pins_parent_without_predicting_world(self):
        value = request(position=[4,None,6],rotation=[0,90,0],scale=[2,2,2])
        value['positionSpace']='local'
        row = c.merge(value,{7:POSE},[100,200,300],{7:dict(frameKind=2,parent=0x123456)})[0]
        self.assertEqual(row['expectedParent'],0x123456)
        self.assertEqual(row['expectedFrame'],2)
        self.assertFalse(row['worldPositionPredicted'])
        self.assertEqual(row['desired']['localPosition'],[4,2,6])
        self.assertEqual(row['desired']['worldPosition'],POSE['worldPosition'])
        self.assertEqual(row['requireRoot'],0)

    def test_nested_world_position_is_rejected_but_local_rotation_is_allowed(self):
        frames={7:dict(frameKind=2,parent=0x123456)}
        with self.assertRaisesRegex(ValueError,'PARENT_MATRIX'):
            c.merge(request(position=[101,202,303]),{7:POSE},[100,200,300],frames)
        row = c.merge(request(rotation=[0,90,0]),{7:POSE},[100,200,300],frames)[0]
        self.assertEqual(row['mask'],2)
        self.assertEqual(row['requireRoot'],0)

    def test_nested_readback_checks_local_pose_while_world_is_observation(self):
        after=copy.deepcopy(POSE);after['worldPosition']=[901,902,903]
        self.assertTrue(c.same_pose(POSE,after,world=False))
        self.assertFalse(c.same_pose(POSE,after))
        after['localPosition'][0]=7
        self.assertFalse(c.same_pose(POSE,after,world=False))

    def test_duplicate_target_and_empty_change_are_rejected(self):
        value = request(scale=[1,1,1]);value['entities'] *= 2
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ENTITY'):
            c.normalize(value)
        with self.assertRaisesRegex(ValueError,'EMPTY_ENTITY'):
            c.normalize(request())

    def test_malformed_or_nonfinite_vectors_fail_before_preparation(self):
        for vector in ([None,None,None],[1,2],[True,2,3],[float('inf'),2,3],[1e50,2,3]):
            with self.subTest(vector=vector),self.assertRaises(ValueError):
                c.normalize(request(position=vector))
        for vector in ([0,1,1],[-1,1,1]):
            with self.assertRaisesRegex(ValueError,'POSITIVE_SCALE'):
                c.normalize(request(scale=vector))

    def test_units_and_unknown_fields_are_not_guessed(self):
        value = request(position=[1,2,3]);del value['positionSpace']
        with self.assertRaisesRegex(ValueError,'REQUEST_FIELDS'):
            c.normalize(value)
        value = request(scale=[1,1,1]);value['entities'][0]['world']=True
        with self.assertRaisesRegex(ValueError,'ENTITY_FIELDS'):
            c.normalize(value)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON'):
            c.unique([('position',[1,2,3]),('position',[4,5,6])])

    def test_receipt_abi_supports_both_snapshot_sizes_and_rejects_dirty_unused_rows(self):
        for size in (33208,262584):
            raw = bytearray(48+128*280+size)
            struct.pack_into('<12I',raw,0,len(raw),1,1,1,0,0,0,0,0,0,0,0)
            result,after = c.decode_extension(bytes(raw),size)
            self.assertEqual(len(after),size)
            self.assertEqual(result['count'],0)
            raw[48]=1
            with self.assertRaisesRegex(ValueError,'UNUSED_RECEIPT'):
                c.decode_extension(bytes(raw),size)

class SavedTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader = reader_module()

    def changed(self):
        desired = copy.deepcopy(POSE)
        desired['localPosition']=[8.,9.,10.]
        desired['worldPosition']=[108.,209.,310.]
        return dict(entityId=7,mask=1,before=POSE,after=desired)

    def test_native_local_position_and_degree_storage(self):
        row = self.changed()
        checks = verify_payloads(self.reader,saved(POSE),saved(row['after']),[row],123)
        self.assertEqual(checks[0]['entityId'],7)
        self.assertEqual(checks[0]['fields']['rotation'][1]['actual'],20.)

    def test_other_entity_and_graph_changes_are_rejected(self):
        row = self.changed()
        for body in (saved(row['after'],graph=b'broken'),saved(row['after'],other_name=b'broken')):
            with self.assertRaises(ValueError):
                verify_payloads(self.reader,saved(POSE),body,[row],123)

    def test_omitted_scale_mutation_is_rejected(self):
        row = self.changed();mutated=copy.deepcopy(row['after']);mutated['scale']=[4.,4.,4.]
        with self.assertRaisesRegex(ValueError,'UNREQUESTED_TRANSFORM'):
            verify_payloads(self.reader,saved(POSE),saved(mutated),[row],123)

    def test_unsaved_original_is_not_accepted_as_recovery(self):
        row = self.changed();other=copy.deepcopy(POSE);other['localPosition']=[7.,7.,7.]
        with self.assertRaisesRegex(ValueError,'UNSAVED_BASELINE'):
            verify_payloads(self.reader,saved(other),saved(row['after']),[row],123)

    def test_opaque_root46_changes_are_reported_without_domain_claim(self):
        row=self.changed();differences=[]
        opaque=lambda a,b:message(46,message(1,scalar(1,a)+scalar(2,b)))
        checks=verify_payloads(self.reader,saved(POSE)+opaque(7,8),saved(row['after'])+opaque(9,10),[row],123,
                               unclassified_differences=differences)
        self.assertEqual(len(checks),1)
        self.assertEqual(len(differences),1)
        self.assertEqual(differences[0]['root'],46)
        self.assertFalse(differences[0]['meaningVerified'])
        self.assertFalse(differences[0]['preserved'])
        self.assertEqual(differences[0]['after']['opaqueUInt64'],[9,10])

    def test_root46_unknown_shape_is_not_silently_accepted(self):
        row=self.changed()
        with self.assertRaisesRegex(ValueError,'UNCLASSIFIED_ROOT46_SHAPE'):
            verify_payloads(self.reader,saved(POSE),saved(row['after'])+message(46,scalar(99,2)),[row],123,
                            unclassified_differences=[])

    def test_other_root_change_still_rejected_when_reporting_root46(self):
        row=self.changed()
        with self.assertRaisesRegex(ValueError,'OTHER_SAVE_ROOT_CHANGED:47'):
            verify_payloads(self.reader,saved(POSE),saved(row['after'])+scalar(47,1),[row],123,
                            unclassified_differences=[])

if __name__ == '__main__':
    unittest.main()
