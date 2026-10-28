"""One final offline native-source package batch; never accesses game processes."""
import json,os,unittest
from pathlib import Path
import numpy as np
from reference_cli import project_path,digest
from regional_registration import ROOT,read
from native_ground_reference import GroundReference,interpolate,interpolation_diagonal_bound,product_to_native_xz,native_to_product_xz
from native_product_frame import transform_xyz
from native_terrain_binding import terrain_bindings
from native_terrain_reference import heightmap_candidates
from native_mesh_reference import read_mesh
from native_mesh_surface import SelectedMeshSurface


class NativeSourcePackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package=project_path(os.environ.get('MONDSTADT_NATIVE_PACKAGE','data/mondstadt/reference3d/native-world-source-v5-final'))
        cls.manifest=read(cls.package/'PACKAGE.json');cls.index=read(cls.package/'source-index.json');cls.ground=GroundReference(cls.package/'source-index.json');cls.mapping=cls.index['declaredProductTransform']

    def test_all_frozen_files_match(self):
        for name,record in self.manifest['files'].items():
            with self.subTest(file=name):
                path=(self.package/name).resolve();self.assertTrue(path.is_relative_to(self.package));self.assertEqual(path.stat().st_size,record['bytes']);self.assertEqual(digest(path),record['sha256'])

    def test_tools_match_frozen_source(self):
        for path,sha in self.manifest['tools'].items():
            with self.subTest(tool=path):self.assertEqual(digest(project_path(path)),sha)

    def test_six_real_height_arrays_and_provenance(self):
        self.assertEqual({t['id'] for t in self.index['terrainTiles']},{'1_-1','1_-2','1_0','2_-1','2_-2','2_0'})
        for tile in self.index['terrainTiles']:
            with self.subTest(tile=tile['id']):
                a=np.load(self.package/tile['heightFile'],allow_pickle=False);raw=a['rawHeights'];self.assertEqual(raw.shape,(513,513));self.assertEqual(raw.dtype,np.dtype('int16'))
                self.assertGreaterEqual(int(raw.min()),0);self.assertLessEqual(int(raw.max()),32766);self.assertEqual(tile['storageRowAxis'],'X');self.assertEqual(tile['storageColumnAxis'],'Z')
                self.assertAlmostEqual(tile['quantizationY'],1024/32766,14);self.assertEqual(tile['scaleXYZ'],[2.,1024.,2.]);self.assertFalse(tile['registration']['absoluteSceneParentResolved'])
                self.assertEqual(tile['nativeBounds']['xmax']-tile['nativeBounds']['xmin'],1024);self.assertEqual(tile['nativeBounds']['zmax']-tile['nativeBounds']['zmin'],1024)

    def test_exact_terrain_component_and_collider_links(self):
        for tile in self.index['terrainTiles']:
            with self.subTest(tile=tile['id']):
                b=tile['terrainBinding'];rows=terrain_bindings(project_path(b['sourceNode']));self.assertEqual(rows,[b]);self.assertEqual(b['terrainDataPPtr']['pathId'],tile['sourceTerrainDataPathId'])
                self.assertTrue(b['prefabRootIsIdentity']);self.assertFalse(b['runtimeScenePlacementResolved']);self.assertEqual(len(b['colliders'][0]['matchingTerrainDataPPtrByteOffsets']),1)

    def test_height_grammar_redecodes_identically(self):
        for tile in self.index['terrainTiles']:
            with self.subTest(tile=tile['id']):
                record=next(r for r in read(project_path(tile['sourceTerrainRecord']))['terrains'] if r['pathId']==tile['sourceTerrainDataPathId']);node=project_path(record['sourceNode']);m=read(node/'metadata.json');obj=next(o for o in m['objects'] if o['pathId']==record['pathId']);payload=(node/'node.bin').read_bytes()[obj['offset']:obj['offset']+obj['size']]
                found=heightmap_candidates(payload);self.assertEqual(len(found),1);stored=np.load(self.package/tile['heightFile'],allow_pickle=False);np.testing.assert_array_equal(found[0][1]['rawHeights'],stored['rawHeights']);self.assertLess(found[0][0]['storedPatchExtremaResidualNormalized'],1e-6)

    def test_frame_is_explicit_design_choice(self):
        self.assertEqual(self.mapping['scaleStatus'],'ASSUMED-SCALE');self.assertFalse(self.mapping['nativeToEditorMetricCalibrationEstablished']);self.assertFalse(self.mapping['editorOffsetApplied']);self.assertEqual(self.mapping['nativeYReference'],0)
        self.assertEqual(digest(self.package/'inputs/shared-transform.json'),self.mapping['sharedTransformSha256']);self.assertEqual(digest(self.package/'inputs/coordinate-evidence.json'),self.mapping['coordinateEvidenceSha256'])

    def test_composed_matrices_and_inverse(self):
        m=self.mapping;native=np.asarray(m['nativeToProductMatrixColumnVector']);inverse=np.asarray(m['productToNativeMatrixColumnVector']);np.testing.assert_allclose(native@inverse,np.eye(4),atol=1e-10)
        np.testing.assert_allclose(np.asarray(m['officialPixelWithHeightToProductMatrixColumnVector'])@np.asarray(m['nativeToOfficialPixelWithHeightMatrixColumnVector']),native,atol=1e-10)
        points=np.array([[1993.73,212.17,-874.22],[2275,263,-783],[2048,0,-1024],[0,0,0]],float);p=transform_xyz(points,m);np.testing.assert_allclose(p@inverse[:3,:3].T+inverse[:3,3],points,atol=1e-9)
        np.testing.assert_allclose(p[:,1],points[:,1]*m['scale'],atol=1e-10);np.testing.assert_allclose(product_to_native_xz(p[:,[0,2]],m),points[:,[0,2]],atol=1e-9)

    def test_orientation_is_quantified_without_accuracy_overclaim(self):
        axis=read(self.package/'axis-evidence.json')['comparisons'];self.assertEqual(len(axis),2)
        for row in axis:
            self.assertLess(row['comparisons']['rowX']['median']*4,row['comparisons']['rowZ']['median']);self.assertTrue(row['notAnAbsoluteTerrainAccuracyMeasurement'])
        for t in self.index['terrainTiles']:self.assertIsNone(t['registration']['coordinateErrorBoundNativeUnits'])

    def test_boundary_conflicts_are_not_averaged(self):
        boundary=read(self.package/'boundary-evidence.json')['pairs'];self.assertGreaterEqual(len(boundary),7)
        for pair in boundary:
            self.assertEqual(pair['samples'],513);self.assertFalse(pair['smoothedOrFilled'])
            for band in pair['excludedBands']:
                x=(band['xmin']+band['xmax'])/2;z=(band['zmin']+band['zmax'])/2;r=self.ground.query_native([[x,z]])[0];self.assertIn(r['status'],['source-boundary-uncertain','source-cell-semantics-uncertain']);self.assertIsNone(r['nativeY'])

    def test_missing_native_region_is_null(self):
        r=self.ground.query_native([[1e7,1e7]])[0];self.assertEqual(r['status'],'missing-source');self.assertIsNone(r['nativeY']);self.assertEqual(r['candidates'],[])

    def test_exact_grid_queries_retain_integer_heights(self):
        for tile,raw in self.ground.tiles:
            b=tile['nativeBounds']
            for i,j in ((15,29),(250,370),(400,100)):
                with self.subTest(tile=tile['id'],row=i,col=j):
                    row=self.ground.query_native([[b['xmin']+2*i,b['zmin']+2*j]])[0];candidate=next(c for c in row['candidates'] if c['tileId']==tile['id']);self.assertAlmostEqual(candidate['nativeY'],int(raw[i,j])*1024/32766,10);self.assertEqual(candidate['bilinearVsEitherCellDiagonalMaxDifferenceY'],0)

    def test_custom_nonzero_cells_remain_uncertain(self):
        tile=next(t for t in self.index['terrainTiles'] if t['id']=='2_-1');custom=self.ground.cell_flags['2_-1'];self.assertEqual(int(np.count_nonzero(custom)),1357)
        i,j=np.argwhere(custom!=0)[0];b=tile['nativeBounds'];r=self.ground.query_native([[b['xmin']+2*i+.5,b['zmin']+2*j+.5]])[0]
        self.assertEqual(r['status'],'source-cell-semantics-uncertain');self.assertIsNone(r['nativeY'])

    def test_product_height_is_scaled_once(self):
        native=np.array([[1993.73,-874.22]]);product=native_to_product_xz(native,self.mapping);a=self.ground.query_native(native)[0];b=self.ground.query_product(product)[0]
        self.assertAlmostEqual(a['nativeY'],b['nativeY'],9);self.assertAlmostEqual(b['productY'],b['nativeY']*self.mapping['scale'],9);self.assertFalse(b['editorVerticalOffsetApplied']);self.assertTrue(b['verticalEditorConversionRequired'])

    def test_mesh_provenance_and_normals(self):
        meshes=read(self.package/'mesh-index.json')['placedMeshes'];self.assertGreaterEqual(len(meshes),5)
        for mesh in meshes:
            with self.subTest(mesh=mesh['name']):
                a=np.load(self.package/mesh['geometry'],allow_pickle=False);p=np.load(self.package/mesh['productGeometry'],allow_pickle=False);n=np.load(self.package/mesh['faceAttributes'],allow_pickle=False)
                self.assertEqual(len(a['vertices']),mesh['vertexCount']);self.assertEqual(len(a['triangles']),mesh['triangleCount']);np.testing.assert_array_equal(a['triangles'],p['triangles']);np.testing.assert_allclose(transform_xyz(a['vertices'],self.mapping),p['vertices'],atol=1e-9)
                self.assertTrue(np.isfinite(n['nativeWindingNormals']).all());np.testing.assert_allclose(np.linalg.norm(n['nativeWindingNormals'][~n['degenerate']],axis=1),1,atol=1e-8)

    def test_mesh_bytes_decode_to_frozen_world_geometry(self):
        meshes=read(self.package/'mesh-index.json')['placedMeshes'];sources={}
        for mesh in meshes:
            assembly=read(project_path(mesh['sourceAssembly']))
            for batch_ref in assembly['sourceBatches']:
                for item in read(project_path(batch_ref['path']))['items']:
                    if 'acquired' not in item:continue
                    node=project_path(item['acquired']['output']);source=read(node/'source.json');sources[source['nodePath'].lower()]=node
        for mesh in meshes:
            with self.subTest(mesh=mesh['name']):
                node=sources[mesh['meshCab']];self.assertEqual(digest(node/'node.bin'),mesh['meshNodeSha256']);meta=read(node/'metadata.json');obj=next(o for o in meta['objects'] if o['pathId']==mesh['meshPathId']);raw=(node/'node.bin').read_bytes()[obj['offset']:obj['offset']+obj['size']];info,a=read_mesh(raw);self.assertEqual(info['fullyParsedBytes'],len(raw))
                m=np.asarray(mesh['nativeMatrixColumnVector']);world=np.load(self.package/mesh['geometry'],allow_pickle=False);np.testing.assert_allclose(a['vertices']@m[:3,:3].T+m[:3,3],world['vertices'],atol=1e-10)

    def test_codec_is_audited_local_build(self):
        receipt=read(self.package/'provenance/build-receipt.json');self.assertEqual(receipt['exitCode'],0);self.assertFalse(receipt['gameDllLoaded']);self.assertFalse(receipt['gameProcessAccess']);self.assertIn('proprietary DLL loading',receipt['removedCapabilities'])
        dll=project_path('.runtime/mondstadt/rework-20261017/reference3d/source-chain-v5/ooz-build-v2/reference_codec.dll');self.assertEqual(digest(dll),receipt['files']['reference_codec.dll'])

    def test_city_source_has_true_parent_but_stays_hlod(self):
        city=next(r for r in read(self.package/'mesh-index.json')['placedMeshes'] if r['name']=='Area_Mengde_City_Constant_HLOD_Lod0')
        self.assertEqual(city['vertexCount'],17158);self.assertEqual(city['triangleCount'],10277);np.testing.assert_allclose(np.asarray(city['nativeMatrixColumnVector'])[:3,3],[2275,263,-783]);self.assertIn('not a full-detail claim',city['resolutionClass'])

    def test_semantic_transfer_requires_correspondence(self):
        rows=read(self.package/'mesh-correspondence.json')['rows'];self.assertEqual(len(rows),3)
        for row in rows:
            self.assertTrue(row['semanticTransferAccepted']);self.assertTrue(row['allFaceIndicesAgreeIgnoringWinding']);self.assertLess(row['maxVertexCoordinateDifference'],.001)
        city=next(r for r in rows if r['mesh']=='mondstadt-city-lod0');surf=SelectedMeshSurface.from_semantic_file(self.package,city['semanticFaces'],'city-paved');self.assertFalse(surf.semantic['verifiedInGame'])
        with self.assertRaises(ValueError):SelectedMeshSurface.from_semantic_file(self.package,city['semanticFaces'],'all-roofs-as-ground')

    def test_probe_coverage_and_height_labels_consistent(self):
        probes=read(self.package/'world-probe-reference.json')['probes'];coverage=read(self.package/'coverage-report.json');self.assertEqual(len(probes),coverage['probeCount']);self.assertEqual(len(probes),28419)
        for row in probes:
            if row['status']=='sampled':self.assertIsNotNone(row['nativeY']);self.assertAlmostEqual(row['productY'],row['nativeY']*self.mapping['scale'],9)
            else:self.assertIsNone(row['nativeY']);self.assertIsNone(row['productY'])
            self.assertFalse(row['buildingsAndBridgesIncluded'])

    def test_old_immutable_deliveries_preserved(self):
        self.assertEqual(digest(ROOT/'delivery-all-regions-v3/DELIVERY.json'),'2bdb76f33f060506b342a7af480e684fce102b4ca08d4a631dc69bd928f7014d')
        self.assertEqual(digest(ROOT/'delivery-regional-calibration-v4/DELIVERY.json'),'4798fdced0da52f800247b4a9a2b37cddf1ddfec4292af268fbaaf7ed1b3b7d2')


class QueryAlgorithms(unittest.TestCase):
    def test_row_axis_and_bilinear(self):
        raw=np.array([[0,20],[100,200]],dtype=np.int16);self.assertEqual(float(interpolate(raw,.5,.25,1,1,'X')),65.);self.assertEqual(float(interpolate(raw,.5,.25,1,1,'Z')),45.)
        with self.assertRaises(ValueError):interpolate(raw,-.1,0,1,1,'X')

    def test_diagonal_difference_has_real_saddle_case(self):
        raw=np.array([[0,0],[0,100]],dtype=np.int16);self.assertEqual(interpolation_diagonal_bound(raw,.5,.5,1,1,'X'),25);self.assertEqual(interpolation_diagonal_bound(raw,0,0,1,1,'X'),0)

    def test_architecture_query_never_auto_selects_roof(self):
        vertices=np.array([[0,10,0],[2,10,0],[0,10,2],[0,20,0],[2,20,0],[0,20,2]],float);tri=np.array([[0,1,2],[3,4,5]])
        explicit=SelectedMeshSurface(vertices,tri,[0,1]);r=explicit.query_native([[.25,.25]])[0];self.assertEqual([h['nativeY'] for h in r['hits']],[10,20]);self.assertFalse(r['automaticGroundSelection'])
        ground=SelectedMeshSurface(vertices,tri,[0]);self.assertEqual([h['nativeY'] for h in ground.query_native([[.25,.25]])[0]['hits']],[10]);self.assertEqual(ground.query_native([[10,10]])[0]['hits'],[])


if __name__=='__main__':unittest.main()
