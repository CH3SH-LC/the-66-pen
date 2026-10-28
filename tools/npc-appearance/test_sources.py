"""One complete offline suite; run only when root opens the batch gate."""
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from official_models import (Catalog, ROOT, indexed_records, nested_id, unique)
from gadget_catalog import decode_beyond_gadgets
from native_catalog import beyond_monsters, Reader
from monster_catalog import decode_monsters, native_string
from primary_index import decode as decode_index
from saved_readback import spans, one, records, inspect


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number, value):
    if isinstance(value, bytes):
        return varint(number * 8 + 2) + varint(len(value)) + value
    return varint(number * 8) + varint(value)


def doc(template_id, kind, base_id):
    return [{'f':1,'w':0,'v':template_id}, {'f':2,'w':2,'m':[
        {'f':1,'w':0,'v':kind}, {'f':kind-1380,'w':2,'m':[
            {'f':1,'w':2,'m':[{'f':1,'w':0,'v':base_id}]}]}]}]


class CapturedSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Catalog()

    def test_all_native_counts(self):
        self.assertEqual([len(x) for x in (self.c.beyond_gadgets,self.c.gadgets,
            self.c.beyond_monsters,self.c.monsters,self.c.npcs)], [3705,30599,115,3408,14444])

    def test_exact_city_template_ids(self):
        out = self.c.resolve([20002108,20002098,20002373,20002067])
        self.assertEqual([r['templateId'] for r in out['rows']], [20002108,20002098,20002373,20002067])
        self.assertTrue(all(r['modelIdentityVerified'] for r in out['rows']))
        self.assertTrue(all(r['nativeType'] == 1402 and not r['identityUsesNames'] for r in out['rows']))

    def test_player_avatar_not_npc(self):
        out = self.c.resolve([1000000,1000001])
        self.assertEqual([r['nativeType'] for r in out['rows']], [1403,1404])
        self.assertTrue(all(not r['ordinaryResidentVerified'] and not r['savedAppearanceSetterAvailable'] for r in out['rows']))

    def test_native_handles_do_not_claim_appearance(self):
        out = self.c.resolve([20002108])['rows'][0]
        self.assertFalse(out['modelAppearanceVerified'])
        self.assertFalse(out['resourceObjectResolved'])
        self.assertIsInstance(out['modelResourceHandle'], str)

    def test_base_is_independent_of_template_id(self):
        base = next(x for x in self.c.beyond_gadgets.values() if x['gadgetConfigId'])
        r = self.c.resolve_fields(123456,doc(123456,1402,base['beyondGadgetBaseId']),{})
        self.assertEqual(r['configId'],base['gadgetConfigId'])
        self.assertNotEqual(r['configId'],r['templateId'])

    def test_monster_join(self):
        base = next(iter(self.c.beyond_monsters.values()))
        r = self.c.resolve_fields(999,doc(999,1405,base['beyondMonsterBaseId']),{})
        self.assertEqual(r['configId'],base['monsterConfigId'])

    def test_empty_native_model(self):
        r = self.c.resolve_fields(999,doc(999,1402,1),{})
        self.assertEqual(r['modelResourceHandle'],'0')
        self.assertFalse(r['modelIdentityVerified'])

    def test_duplicate_selection_rejected(self):
        with self.assertRaisesRegex(ValueError,'TEMPLATE_SELECTION_INVALID'):
            self.c.resolve([20002108,20002108])

    def test_unknown_official_id_rejected(self):
        with self.assertRaisesRegex(ValueError,'OFFICIAL_TEMPLATE_NOT_FOUND'):
            self.c.resolve([4294967295])

    def test_template_id_not_name(self):
        with self.assertRaisesRegex(ValueError,'OFFICIAL_TEMPLATE_ID_MISMATCH'):
            self.c.resolve_fields(1,doc(2,1402,1),{})

    def test_wrong_native_type_oneof_rejected(self):
        value = doc(1,1402,1);value[1]['m'][0]['v'] = 1405
        with self.assertRaisesRegex(ValueError,'TYPE_ONEOF_MISMATCH'):
            self.c.resolve_fields(1,value,{})

    def test_multiple_oneofs_rejected(self):
        value = doc(1,1402,1);value[1]['m'].append({'f':25,'w':2,'m':[]})
        with self.assertRaisesRegex(ValueError,'ONEOF_AMBIGUOUS'):
            self.c.resolve_fields(1,value,{})

    def test_unknown_beyond_key_rejected(self):
        with self.assertRaisesRegex(ValueError,'BEYOND_GADGET_ID_MISSING'):
            self.c.resolve_fields(1,doc(1,1402,4294967295),{})

    def test_coverage_is_bounded(self):
        out = self.c.npc_coverage()
        self.assertEqual(out['npcUniqueHandleCount'],6728)
        self.assertEqual(out['npcHandlesInBeyondGadgets'],[])
        self.assertEqual(out['npcHandlesInBeyondMonsters'],[])
        self.assertFalse(out['globalPlatformImpossibilityProven'])
        self.assertFalse(out['fullNpcRecordDecoded'])

    def test_raw_gadget_capture_truncation(self):
        p = ROOT / self.c.contract['captures']['beyondGadgets']['path']
        with self.assertRaises(ValueError): decode_beyond_gadgets(p.read_bytes()[:-1])

    def test_raw_monster_capture_trailing(self):
        p = ROOT / self.c.contract['captures']['monsters']['path']
        with self.assertRaisesRegex(ValueError,'MONSTER_TRAILING_BYTES'):
            decode_monsters(p.read_bytes()+b'\0')

    def test_raw_beyond_monster_truncation(self):
        p = ROOT / self.c.contract['captures']['beyondMonsters']['path']
        with self.assertRaises(ValueError): beyond_monsters(p.read_bytes()[:-1])


class Boundaries(unittest.TestCase):
    def test_unique_id_collision(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ID'):
            unique([{'id':1},{'id':1}],'id')

    def test_bool_id_refused(self):
        with self.assertRaisesRegex(ValueError,'ID_DOMAIN'): unique([{'id':True}],'id')

    def test_primary_trailing(self):
        with self.assertRaisesRegex(ValueError,'INDEX_TRAILING'): decode_index(bytes([2,1,4,1,0]))

    def test_primary_truncation(self):
        with self.assertRaisesRegex(ValueError,'TRUNCATED'): decode_index(bytes([2,1,4]))

    def test_primary_id_mismatch(self):
        with self.assertRaisesRegex(ValueError,'ID_MISMATCH'):
            indexed_records(b'xxxxa',bytes([2,1,4,1]),lambda a,b:{'id':2},'id')

    def test_primary_span_mismatch(self):
        with self.assertRaisesRegex(ValueError,'SPAN_MISMATCH'):
            indexed_records(b'xxa',bytes([2,1,2,1]),lambda a,b:{'id':1},'id')

    def test_u64_addition_cipher_carries(self):
        plain=b'abcdefgZ';key=0x12345678abcdefab
        encoded=((int.from_bytes(plain,'little')-key)&((1<<64)-1)).to_bytes(8,'little')
        self.assertEqual(native_string(Reader(struct.pack('<H',8)+encoded),key,lambda x:x,'add'),'abcdefgZ')

    def test_string_budget(self):
        with self.assertRaises(ValueError): native_string(Reader(b'\xff\xff'),1,lambda x:x)

    def test_wire_truncation(self):
        with self.assertRaises(ValueError): spans(b'\x0a\x05a')

    def test_wire_zero_field(self):
        with self.assertRaisesRegex(ValueError,'FIELD_NUMBER'): spans(b'\x00\x01')

    def test_wire_duplicate_scalar(self):
        with self.assertRaisesRegex(ValueError,'NOT_UNIQUE'): one(b'\x08\x01\x08\x02',1,0)

    def test_wire_unknown_type(self):
        with self.assertRaisesRegex(ValueError,'TYPE_UNSUPPORTED'): spans(b'\x0b')

    def test_nested_id_duplicate(self):
        f=doc(1,1402,1)[1]['m'];f[1]['m'][0]['m'].append({'f':1,'w':0,'v':2})
        with self.assertRaises(ValueError): nested_id(f,22)

    def test_duplicate_saved_record(self):
        record=field(1,9);root=field(5,field(1,record)+field(1,record))
        with self.assertRaisesRegex(ValueError,'DUPLICATE'): records(root,5)


class SavedReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.catalog=Catalog()

    def setUp(self):
        root=ROOT/'.runtime/npc-appearance-20261017/tests';root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='readback-',dir=root)
        self.path=Path(self.temp.name)/'fixture.gil'
        entity=field(1,900)+field(2,field(1,800))+field(6,field(1,111)+field(121,field(1,2)))
        template=field(1,800)+field(2,20002108)+field(6,field(1,22))
        payload=field(4,field(1,template))+field(5,field(1,entity))
        self.raw=struct.pack('>5I',20+len(payload),1,0x326,2,len(payload))+payload+struct.pack('>I',0x679)
        self.path.write_bytes(self.raw);self.sha=hashlib.sha256(self.raw).hexdigest()

    def tearDown(self): self.temp.cleanup()

    def test_saved_association_and_raw_override_boundary(self):
        r=inspect(self.path,self.sha,[900],self.catalog)['rows'][0]
        self.assertEqual(r['officialTemplateId'],20002108)
        self.assertEqual(r['savedTemplate']['components'][0]['kind'],22)
        self.assertEqual(r['instanceComponents'][0]['kind'],111)
        self.assertFalse(r['effectiveAppearanceVerified'])
        self.assertTrue(r['uninterpretedAppearanceOverridesPossible'])

    def test_saved_sha_required(self):
        with self.assertRaisesRegex(ValueError,'SHA_MISMATCH'): inspect(self.path,'0'*64,[900],self.catalog)

    def test_saved_missing_entity(self):
        with self.assertRaisesRegex(ValueError,'ENTITY_NOT_FOUND'): inspect(self.path,self.sha,[901],self.catalog)

    def test_saved_invalid_tail(self):
        raw=self.raw[:-1]+b'X';self.path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'GIL_CONTAINER'):
            inspect(self.path,hashlib.sha256(raw).hexdigest(),[900],self.catalog)

    def test_saved_duplicate_request(self):
        with self.assertRaisesRegex(ValueError,'SELECTION_INVALID'):
            inspect(self.path,self.sha,[900,900],self.catalog)


if __name__ == '__main__': unittest.main()
