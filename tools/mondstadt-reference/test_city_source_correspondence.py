"""Offline checks run once after the source module and immutable outputs exist."""
import json
import os
import unittest
from pathlib import Path
import numpy as np
from city_source_correspondence import CityCorrespondence, apply_matrix, read, BASE, FROZEN, EXPECTED_PACKAGE
from reference_cli import digest, project_path


class CitySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = project_path(os.environ['CITY_SOURCE_PACKAGE'])
        cls.c = CityCorrespondence(cls.directory/'correspondence.json')
        cls.r = cls.c.report
        cls.vertices = np.load(BASE/'extracted-final-v1/mondstadt-city-lod0.npz')['vertices']
        cls.native = np.load(FROZEN/'meshes/native-5.npz')['vertices']

    def test_frozen_v5_unchanged(self):
        self.assertEqual(digest(FROZEN/'PACKAGE.json'), EXPECTED_PACKAGE)
        for name, row in read(FROZEN/'PACKAGE.json')['files'].items():
            self.assertEqual(digest(FROZEN/name), row['sha256'], name)

    def test_package_files(self):
        for name, row in read(self.directory/'PACKAGE.json')['files'].items():
            self.assertEqual(digest(self.directory/name), row['sha256'], name)

    def test_all_vertices_against_independent_native_bytes(self):
        residual = self.c.viewer_to_native(self.vertices)-self.native
        self.assertLess(np.max(np.abs(residual)), 2e-5)
        self.assertEqual(len(residual), 17158)

    def test_face_index_correspondence_independent(self):
        public = np.load(BASE/'extracted-final-v1/mondstadt-city-lod0.npz')['faces']
        native = np.load(FROZEN/'meshes/native-5.npz')['triangles']
        np.testing.assert_array_equal(np.sort(public, axis=1), np.sort(native, axis=1))
        self.assertEqual(len(native), 10277)

    def test_matrix_not_fitted(self):
        d = self.r['transformDerivation']
        m = np.array(d['nativePrefabMatrixColumnVector']) @ np.array(d['objExportXReflection']) @ np.linalg.inv(d['publicRawToViewerColumnVector'])
        np.testing.assert_array_equal(m, self.r['viewerToNativeMatrixColumnVector'])
        self.assertEqual(d['fittedParameters'], 0)
        self.assertFalse(d['usesCentroidMinOrMaxHitAsCalibration'])

    def test_datum_specific_faces_same_geometry(self):
        anchors = read(self.directory/'datum-face-anchors.json')
        self.assertEqual([x['sourceFaceId'] for x in anchors['matchingHorizontalFaceAnchors']], [9051,9052,9053,9054])
        for row in anchors['matchingHorizontalFaceAnchors']:
            self.assertEqual(row['sourceSemantic'], 'city-paved')
            np.testing.assert_allclose(np.array(row['viewerVerticesXYZ'])[:,1], 253.580176, atol=1e-8, rtol=0)
            np.testing.assert_allclose(self.c.viewer_to_native(row['viewerXYZ']), row['nativeXYZ'], atol=2e-5, rtol=0)

    def test_controls_are_independent_native_faces(self):
        rows = read(self.directory/'control-faces.json')['rows']
        self.assertGreater(len(rows), 25)
        for row in rows:
            ids = row['sourceVertexIds']
            np.testing.assert_array_equal(self.native[ids], row['nativeVerticesXYZInSourceOrder'])
            np.testing.assert_allclose(self.c.viewer_to_native(row['viewerXYZ']), self.native[ids].mean(axis=0), atol=2e-5, rtol=0)

    def test_legacy_y_matches_all_native_vertices(self):
        cfg = self.r['legacyConversion']
        y = (self.vertices[:,1]-cfg['datumViewerY'])*cfg['declaredLegacySourceUnitToLocalUnit']
        result = self.c.legacy_y_to_product(y, frame='source-datum-minus-datumViewerY')
        expected = apply_matrix(self.native, self.r['nativeToProductMatrixColumnVector'])[:,1]
        np.testing.assert_allclose(result, expected, atol=4e-6, rtol=0)

    def test_non_additive_error_is_real(self):
        stats = self.r['independentResiduals']['additiveOnlyAtCorrectDatumProductY']
        self.assertGreater(stats['maxAbs'], .1)
        self.assertLess(self.r['independentResiduals']['recoveredLegacyProductY']['maxAbs'], 4e-6)

    def test_reject_other_frames_and_mismatched_declarations(self):
        for frame in ('world','native','product',''):
            with self.assertRaises(ValueError): self.c.legacy_y_to_product([0], frame=frame)
        with self.assertRaises(ValueError):
            self.c.legacy_y_to_product([0], frame='source-datum-minus-datumViewerY', declared_factor=.5)
        with self.assertRaises(ValueError):
            self.c.legacy_y_to_product([0], frame='source-datum-minus-datumViewerY', declared_datum=0)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError): self.c.viewer_to_native([[0,np.nan,0]])
        with self.assertRaises(ValueError): self.c.legacy_y_to_product([np.inf], frame='source-datum-minus-datumViewerY')
        with self.assertRaises(ValueError): self.c.source_derived_legacy_delta_y_to_product([np.nan])

    def test_scale_difference_and_no_added_datum_on_deltas(self):
        cfg = self.r['legacyConversion']
        result = self.c.source_derived_legacy_delta_y_to_product([0,10])
        self.assertEqual(result[0], 0)
        self.assertAlmostEqual(result[1], 10*cfg['productYMultiplier'])
        self.assertNotAlmostEqual(result[1], 10)

    def test_old_xyz_composition(self):
        cfg = self.r['legacyConversion']
        old = apply_matrix(self.vertices, cfg['legacyViewerToXYZMatrixColumnVector'])
        result = apply_matrix(old, cfg['legacySourceXYZToProductMatrixColumnVector'])
        np.testing.assert_allclose(result, self.c.viewer_to_product(self.vertices), atol=1e-10, rtol=0)

    def test_rounding_error_bound(self):
        cfg = self.r['legacyConversion']
        local = (self.vertices[:,1]-cfg['datumViewerY'])*cfg['declaredLegacySourceUnitToLocalUnit']
        exact = self.c.legacy_y_to_product(local, frame='source-datum-minus-datumViewerY')
        rounded = self.c.legacy_y_to_product(np.round(local,3), frame='source-datum-minus-datumViewerY')
        self.assertLessEqual(np.abs(rounded-exact).max(), cfg['roundingOnlyProductYErrorBound']+1e-12)


class IndexCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = project_path(os.environ['CITY_INDEX_AUDIT'])
        cls.r = read(cls.directory/'completion.json')

    def test_all_inventory_files_and_catalog_receipts(self):
        self.assertEqual(self.r['inventoryFiles'], 1985)
        self.assertEqual(self.r['completedSummaryFiles'], 1985)
        self.assertEqual(self.r['pendingFiles'],0)
        self.assertEqual(self.r['catalogMissingFileKeys'], [])
        self.assertEqual(self.r['catalogReceiptMismatchKeys'], [])

    def test_error_ranges_are_explicit(self):
        errors = read(self.directory/'errors.json')['errors']
        self.assertEqual(len(errors), self.r['parseErrors'])
        for row in errors:
            self.assertIn('error', row)
            if row['stage']=='serialized':
                self.assertIsNotNone(row['affectedNodeMetadata'])
                a,b = row['containingBundleByteRangeHalfOpen']
                self.assertLess(a,b)
                self.assertLessEqual(b,row['sourceBytes'])
            elif row['stage']=='header':
                a,b = row['untraversedSourceByteRangeHalfOpen']
                self.assertLess(a,b)

    def test_scope_does_not_claim_nonserialized_coverage(self):
        self.assertIn('nonserialized', ' '.join(self.r['notIndexed']))
        self.assertFalse(self.r['currentReportReopenedInstalledFiles'])
        self.assertFalse(self.r['gameProcessAccess'])

    def test_index_report_sha(self):
        for name,row in read(self.directory/'PACKAGE.json')['files'].items():
            self.assertEqual(digest(self.directory/name),row['sha256'])
