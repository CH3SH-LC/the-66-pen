"""Pure fixture checks. Run only after the root opens the unified test gate."""
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import terrain_model as tm
from gil_container import Field, Container, encode_fields, encode_container

def vi(n,v):return Field(n,0,value=v)
def msg(n,fields):return Field(n,2,data=encode_fields(fields))
def cell(x,z,h=1,m=0,extra=(0,0,0),unknown=False):
    fields=[vi(1,tm.key(x,z)),vi(2,h),vi(3,m),vi(4,extra[0]),vi(5,extra[1]),vi(6,extra[2])]
    if unknown:fields.append(vi(77,8))
    return msg(4,fields)
def save(cells,second=None,stamp=100,name=b'Terrain',root_extra=7):
    first=msg(1,[vi(1,1001),msg(2,[Field(1,2,data=name)]),*cells])
    entries=[first]
    if second is not None:entries.append(msg(1,[vi(1,1002),*second]))
    return encode_container(Container(2,encode_fields([vi(1,1073741900),vi(40,stamp),vi(44,root_extra),msg(7,entries)])))

class ModelTests(unittest.TestCase):
    def test_asymmetric_native_coordinates(self):
        source=save([cell(121,93,4)])
        row=tm.decode_save(source)['terrains'][0]['cells'][0]
        self.assertEqual(row[0],121|(93<<16))
        plan=tm.make_plan(source,1001,[{'x':121,'z':93,'height':5}])
        self.assertEqual(plan['expected'][0][1],5)

    def test_preserves_all_unspecified_values(self):
        source=save([cell(8,10,7,2,(19,27,33)),cell(9,10,1,3)])
        plan=tm.make_plan(source,1001,[{'x':8,'z':10,'height':9}])
        self.assertEqual(plan['expected'][0],[tm.key(8,10),9,2,19,27,33])
        material=tm.make_plan(source,1001,[{'x':8,'z':10,'material':3}])
        self.assertEqual(material['expected'][0],[tm.key(8,10),7,3,19,27,33])

    def test_add_delete_and_height_zero_with_extra_are_distinct(self):
        source=save([cell(1,2,4,2,(1,2,3)),cell(5,7,1,3)])
        edits=[{'op':'delete','x':1,'z':2},{'x':6,'z':7,'height':8,'material':3}]
        plan=tm.make_plan(source,1001,edits)
        self.assertEqual([r[0] for r in plan['expected']],[tm.key(5,7),tm.key(6,7)])
        self.assertEqual(plan['changes'][0]['after'],[tm.key(1,2),0,2,0,0,0])
        zero=tm.make_plan(source,1001,[{'x':1,'z':2,'height':0}])
        self.assertEqual(zero['expected'][0][3:],[1,2,3])

    def test_no_default_grid_limit(self):
        source=save([cell(3,9998)])
        plan=tm.make_plan(source,1001,[{'x':9998,'z':3,'height':9998,'material':0}])
        self.assertEqual(len(plan['expected']),2)

    def test_validation_precedes_any_change(self):
        source=save([cell(1,2)])
        bad=[{'x':True,'z':2,'height':4},{'x':9999,'z':2,'height':4},
             {'x':1,'z':2,'height':1.5},{'x':1,'z':2,'height':-1},
             {'x':1,'z':2,'height':9999},{'x':1,'z':2,'slope':3},
             {'x':1,'z':2,'height':0},{'x':1,'z':2,'material':666},
             {'x':2,'z':2,'material':0},{'x':2,'z':2,'op':'delete'},
             {'x':1,'z':2,'op':'delete','height':0}]
        for edit in bad:
            with self.subTest(edit=edit),self.assertRaises(ValueError):tm.make_plan(source,1001,[edit])
        self.assertEqual(tm.decode_save(source)['terrains'][0]['cells'][0][1],1)

    def test_reject_duplicate_and_unknown_cells(self):
        for blob in [save([cell(1,2),cell(1,2)]),save([cell(1,2,unknown=True)])]:
            with self.assertRaises(ValueError):tm.make_plan(blob,1001,[{'x':1,'z':2,'height':4}])
        with self.assertRaises(ValueError):
            tm.make_plan(save([cell(1,2)]),1001,[{'x':1,'z':2,'height':3},{'x':1,'z':2,'height':4}])

    def test_reject_plan_tampering_and_stale_source(self):
        blob=save([cell(1,2)])
        plan=tm.make_plan(blob,1001,[{'x':1,'z':2,'height':3}])
        changed=json.loads(json.dumps(plan));changed['expected'][0][1]=4
        with self.assertRaises(ValueError):tm.validate_plan(changed,blob)
        with self.assertRaises(ValueError):tm.validate_plan(plan,save([cell(1,2,2)]))

    def test_native_save_verifier_checks_other_content(self):
        extra=(3,4,5)
        blob=save([cell(1,2,1,0,extra),cell(4,9)],second=[cell(5,6)])
        plan=tm.make_plan(blob,1001,[{'x':1,'z':2,'height':7}])
        after=save([cell(1,2,7,0,extra),cell(4,9)],second=[cell(5,6)],stamp=101)
        result=tm.verify_save(blob,after,plan)
        self.assertTrue(result['ok']);self.assertFalse(result['reopenVerified'])
        self.assertTrue(result['fileContentVerified']);self.assertFalse(result['nativeSaveVerified'])
        self.assertFalse(result['persistentSaveVerified'])
        wrong=[save([cell(1,2,7),cell(4,9)],second=[cell(5,6)]),
               save([cell(1,2,7,0,extra),cell(4,9,3)],second=[cell(5,6)]),
               save([cell(1,2,7,0,extra),cell(4,9)],second=[cell(5,6,2)]),
               save([cell(1,2,7,0,extra),cell(4,9)],second=[cell(5,6)],root_extra=8)]
        for other in wrong:
            with self.subTest(other=tm.digest(other)):
                self.assertFalse(tm.verify_save(blob,other,plan)['ok'])

    def test_legacy_explicit_deletion_does_not_resurrect(self):
        import terrain
        blob=save([cell(100,101),cell(101,101)])
        level=terrain._level_from_blob(blob);model=terrain.terrain_fields_of(level)
        target=model.terrains[0];old_key=next(iter(target.cells));del target.cells[old_key]
        terrain.apply_terrain_fields(level,model)
        self.assertEqual(len(tm.decode_save(terrain.to_level_bytes(level))['terrains'][0]['cells']),1)

if __name__=='__main__':unittest.main()
