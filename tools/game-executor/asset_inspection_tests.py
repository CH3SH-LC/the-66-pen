"""Offline contracts; run only after the unified development gate opens."""
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_inspection as cli
import asset_inspection_common as c
import asset_inspection_receipt as r
import asset_inspection_icons as icons

I=[float(i%5==0) for i in range(16)]

def fixture():
    obj=dict(object=100001,klass=100002,transform=100003,gameObject=100004,mesh=100005,kind=1,enabled=1,active=1,isTrigger=0,isSceneQuery=0,belongs=1,stable=1,geometry=1,
        worldBounds=dict(center=[0.,1.,0.],extents=[1.,1.,2.]),localGeometryBounds=dict(center=[0.,1.,0.],extents=[1.,1.,2.]),localToWorld=I.copy())
    return dict(entityId=1,unity=4,view=5,localToWorld=I.copy(),worldToLocal=I.copy(),objects=[obj],
        pose=dict(localPosition=[0.,0.,0.],worldPosition=[0.,0.,0.],rotationDegrees=[0.,0.,0.],scale=[1.,1.,1.]))

def png():
    def chunk(kind,content):return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\0\0\xff'))+chunk(b'IEND',b'')

class MeasurementTests(unittest.TestCase):
    def test_native_mesh_bounds_and_pivot(self):
        out=c.measure(fixture());self.assertEqual(out['renderDimensionsAtUnitEntityScale'],[2,2,4]);self.assertEqual(out['unitEntityRendererGeometryBounds']['bottomOffset'],0)
    def test_nonuniform_scale_and_translation_removed(self):
        e=fixture();e['localToWorld']=[2.,0,0,0,0,3.,0,0,0,0,4.,0,10.,20.,30.,1.]
        e['worldToLocal']=[.5,0,0,0,0,1/3,0,0,0,0,.25,0,-5.,-20/3,-7.5,1.]
        e['pose'].update(worldPosition=[10.,20.,30.],localPosition=[10.,20.,30.],scale=[2.,3.,4.])
        e['objects'][0]['localToWorld']=e['localToWorld'].copy();out=c.measure(e)
        self.assertTrue(c.close(out['renderDimensionsAtUnitEntityScale'],[2,2,4]));self.assertEqual(out['actualLocalScale'],[2,3,4])
    def test_rotated_nonuniform_entity_uses_matrix(self):
        e=fixture();e['localToWorld']=[0,2.,0,0,-3.,0,0,0,0,0,4.,0,10.,20.,30.,1.]
        e['worldToLocal']=[0,-1/3,0,0,.5,0,0,0,0,0,.25,0,-10.,10/3,-7.5,1.]
        e['pose']['worldPosition']=[10.,20.,30.];e['objects'][0]['localToWorld']=e['localToWorld'].copy()
        self.assertTrue(c.close(c.measure(e)['renderDimensionsAtUnitEntityScale'],[2,2,4]))
    def test_child_scale_is_preserved(self):
        e=fixture();e['objects'][0]['localToWorld'][0]=3
        self.assertEqual(c.measure(e)['renderDimensionsAtUnitEntityScale'],[6,2,4])
    def test_child_offset_preserves_origin_offset(self):
        e=fixture();e['objects'][0]['localToWorld'][13]=5
        self.assertEqual(c.measure(e)['unitEntityRendererGeometryBounds']['bottomOffset'],5)
    def test_world_aabb_does_not_become_mesh_geometry(self):
        e=fixture();e['objects'][0]['geometry']=0;out=c.measure(e)
        self.assertIsNone(out['renderDimensionsAtUnitEntityScale']);self.assertIsNotNone(out['renderers'][0]['normalizedWorldAabbEnvelope'])
    def test_disabled_renderer_excluded_from_aggregate(self):
        e=fixture();e['objects'][0]['enabled']=0;self.assertFalse(c.measure(e)['activeRendererGeometryComplete'])
    def test_collider_never_substitutes_renderer(self):
        e=fixture();e['objects'][0].update(kind=2,geometry=0);out=c.measure(e)
        self.assertEqual(out['rendererCount'],0);self.assertIsNone(out['renderDimensionsAtUnitEntityScale']);self.assertEqual(out['colliderCount'],1)
    def test_partial_renderer_coverage_is_unknown(self):
        e=fixture();x=copy.deepcopy(e['objects'][0]);x['object']=11;x['geometry']=0;e['objects'].append(x)
        self.assertIsNone(c.measure(e)['renderDimensionsAtUnitEntityScale'])
    def test_empty_components_remain_unknown(self):
        e=fixture();e['objects']=[];out=c.measure(e);self.assertIsNone(out['renderDimensionsAtUnitEntityScale'])
    def test_inverse_mismatch_rejected(self):
        e=fixture();e['worldToLocal'][0]=2
        with self.assertRaisesRegex(ValueError,'MATRIX'):c.measure(e)
    def test_matrix_origin_must_match_pose(self):
        e=fixture();e['pose']['worldPosition']=[1,0,0]
        with self.assertRaisesRegex(ValueError,'ORIGIN'):c.measure(e)
    def test_negative_bounds_rejected(self):
        e=fixture();e['objects'][0]['worldBounds']['extents'][0]=-1
        with self.assertRaisesRegex(ValueError,'BOUNDS'):c.measure(e)
    def test_unstable_object_rejected(self):
        e=fixture();e['objects'][0]['stable']=0
        with self.assertRaisesRegex(ValueError,'STABILITY'):c.measure(e)
    def test_no_visual_or_player_claim(self):
        out=c.measure(fixture());self.assertFalse(out['appearanceVerified']);self.assertFalse(out['playerContactVerified']);self.assertIsNone(out['modelResourcePath'])
    def summary_sample(self):
        sample=c.measure(fixture());sample.update(templateId=99,catalog=dict(name='sample',iconPath='a.png',nativeKind=0));return sample
    def test_city_summary_base_origin_and_unknown_category(self):
        out=c.template_summary([self.summary_sample()]);self.assertEqual(out['originConvention'],'base-center');self.assertEqual(out['category'],'unknown');self.assertIsNone(out['assetPath']);self.assertIsNone(out['boundsCollider'])
    def test_conflicting_instance_bounds_block_canonical_size(self):
        a=self.summary_sample();b=copy.deepcopy(a);b['entityId']=2;b['unitEntityRendererGeometryBounds']['max'][0]+=1
        out=c.template_summary([a,b]);self.assertIsNone(out['boundsRenderer']);self.assertTrue(out['blocksSizeBasedPlacement'])
    def test_missing_mesh_bounds_block_city_size(self):
        a=self.summary_sample();a['unitEntityRendererGeometryBounds']=None
        self.assertEqual(c.template_summary([a])['originConvention'],'unknown')

class ReceiptTests(unittest.TestCase):
    def raw(self,version=1):
        n=33208 if version==1 else 262584;total=48+48+128*280+n+8*c.ENTITY_SIZE
        raw=bytearray(total);struct.pack_into('<12I',raw,0,total,1,1,1,0,8,0,0,0,0,0,0);return raw,n
    def test_v1_early_refusal_zero_transform(self):
        raw,n=self.raw();result,_=r.extension(raw,n);self.assertEqual(result['count'],8);self.assertEqual(result['transform']['count'],0)
    def test_v2_early_refusal_zero_transform(self):
        raw,n=self.raw(2);result,_=r.extension(raw,n);self.assertEqual(result['count'],8)
    def test_wrong_receipt_length_rejected(self):
        raw,n=self.raw()
        with self.assertRaisesRegex(ValueError,'SIZE'):r.extension(raw[:-1],n)
    def test_object_capacity_rejected(self):
        raw,n=self.raw();at=48+48+128*280+n;struct.pack_into('<I',raw,at+8,65)
        with self.assertRaisesRegex(ValueError,'CAPACITY'):r.extension(raw,n)
    def test_unused_object_bytes_rejected(self):
        raw,n=self.raw();raw[-1]=1
        with self.assertRaisesRegex(ValueError,'UNUSED'):r.extension(raw,n)
    def test_unknown_snapshot_abi_rejected(self):
        with self.assertRaisesRegex(ValueError,'ABI'):r.extension(b'',123)
    def test_unicode_name_raw_preserved(self):
        raw='风车'.encode('utf-16-le');out=r.text_field(raw,0,2,1)
        self.assertEqual(out['value'],'风车');self.assertEqual(out['rawUtf16Hex'],raw.hex());self.assertFalse(out['isResourcePath'])
    def test_truncated_surrogate_explicit(self):
        out=r.text_field(b'\x00\xd8',0,1,3);self.assertFalse(out['lossless']);self.assertEqual(out['status'],'truncated')
    def test_name_capacity_rejected(self):
        with self.assertRaisesRegex(ValueError,'RANGE'):r.text_field(b'',0,97,1)

class CatalogAndIconTests(unittest.TestCase):
    def test_duplicate_names_do_not_select_lowest_id(self):
        data=dict(ok=True,truncated=False,prefabs=[dict(registryId=9,name='same',iconPath='a.png'),dict(registryId=2,name='same',iconPath='b.png')])
        with patch.object(c,'sha',return_value=c.CATALOG_SHA),patch.object(c,'read',return_value=data):
            out=c.catalog_evidence([9]);self.assertEqual(out['9']['iconPath'],'a.png');self.assertEqual(set(out['9']['sameNameTemplateIds']),{2,9})
    def test_duplicate_catalog_id_rejected(self):
        data=dict(ok=True,truncated=False,prefabs=[dict(registryId=9),dict(registryId=9)])
        with patch.object(c,'sha',return_value=c.CATALOG_SHA),patch.object(c,'read',return_value=data),self.assertRaisesRegex(ValueError,'DUPLICATE'):c.catalog_evidence([9])
    def test_catalog_hash_drift_rejected(self):
        with patch.object(c,'sha',return_value='changed'),self.assertRaisesRegex(ValueError,'CHANGED'):c.catalog_evidence([9])
    def test_missing_catalog_entry_remains_unknown(self):
        data=dict(ok=True,truncated=False,prefabs=[])
        with patch.object(c,'sha',return_value=c.CATALOG_SHA),patch.object(c,'read',return_value=data):
            out=c.catalog_evidence([9])['9'];self.assertFalse(out['found']);self.assertIsNone(out['iconPath'])
    def test_roles_preview_keeps_explicit_id_and_all_alternatives(self):
        data=dict(schema='mw-role-catalog',roles=[dict(role='wall',templateId=9,alternativeIds=[2,3])])
        with patch.object(icons,'sha',return_value='fixed'),patch.object(icons,'read',return_value=data):
            ids,evidence=icons.ids_from_role_catalog(c.ROOT/'data/fake.json',True)
        self.assertEqual(ids,[9,2,3]);self.assertFalse(evidence['associations'][0]['roleChoiceVerified'])
    def test_roles_preview_does_not_resolve_names(self):
        data=dict(schema='mw-role-catalog',roles=[dict(role='wall',name='wall')])
        with patch.object(icons,'sha',return_value='fixed'),patch.object(icons,'read',return_value=data),self.assertRaises(ValueError):
            icons.ids_from_role_catalog(c.ROOT/'data/fake.json')
    def test_valid_png_decoded(self):self.assertEqual(icons.png_info(png())['decodedScanlineBytes'],5)
    def test_png_crc_rejected(self):
        raw=bytearray(png());raw[20]^=1
        with self.assertRaisesRegex(ValueError,'CRC'):icons.png_info(raw)
    def test_png_trailing_data_rejected(self):
        with self.assertRaisesRegex(ValueError,'TRAILING'):icons.png_info(png()+b'bad')
    def test_arbitrary_file_is_not_image(self):
        with self.assertRaisesRegex(ValueError,'PNG'):icons.png_info(b'not a png')

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        c.OUTPUT.mkdir(parents=True,exist_ok=True);self.run=Path(tempfile.mkdtemp(prefix='asset-contract-',dir=c.OUTPUT)).resolve()
    def tearDown(self):
        if not self.run.is_relative_to(c.OUTPUT.resolve()):raise RuntimeError('Unsafe test cleanup target')
        shutil.rmtree(self.run)
    def manifest(self):
        p=dict(kind=c.KIND,action=18,receiptVersion=23,run=str(self.run),artifacts={},launchable=False)
        c.write(self.run/'prepared.json',p);c.write(self.run/'build-result.json',dict(kind=c.BUILD_KIND,preparedSha256=c.sha(self.run/'prepared.json')))
    def test_manifest_binding(self):self.manifest();self.assertEqual(r.manifest(self.run)[1]['action'],18)
    def test_manifest_tamper_rejected(self):
        self.manifest();(self.run/'prepared.json').write_text('{}',encoding='utf-8')
        with self.assertRaises(ValueError):r.manifest(self.run)
    def test_outside_prepared_root_rejected(self):
        with self.assertRaisesRegex(ValueError,'ROOT'):r.manifest(c.ROOT/'tools')
    def test_outputs_never_follow_cwd(self):
        self.assertEqual(c.ROOT,Path(__file__).resolve().parents[2]);self.assertTrue(c.OUTPUT.is_relative_to(c.ROOT))
    def test_queue_claim_is_uncertain_without_receipt(self):
        (self.run/'map-queue-claim.json').write_text('{}',encoding='utf-8');out=cli.uncertainty(self.run)
        self.assertTrue(out['outcomeUncertain']);self.assertFalse(out['safeToRelease'])
    def test_no_attempt_preflight_failure_is_safe(self):self.assertTrue(cli.uncertainty(self.run)['safeToRelease'])
    def test_nonlaunchable_dispatch_rejected_before_admin(self):
        self.manifest()
        p=c.read(self.run/'prepared.json');p['compileOnly']=True
        with patch.object(cli,'manifest',return_value=(self.run,p,{})),self.assertRaisesRegex(ValueError,'NONLAUNCHABLE'):cli.dispatch(self.run,direct=True)
    def test_unknown_action_refused(self):
        with patch('sys.stdout') as stdout:self.assertEqual(cli.main(['set']),2)
        self.assertTrue(stdout.write.called)

if __name__=='__main__':unittest.main()
