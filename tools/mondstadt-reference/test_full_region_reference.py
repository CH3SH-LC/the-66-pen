"""One deferred offline batch for the complete full-region reference module."""
import json
import math
import unittest

import numpy as np

from geometry import read_obj, transform
from reference_cli import DEFAULT_LOCK, digest, frame_matrix, project_path
from full_region_reference import (DEFAULT_OUT, EXTRACTED, ROOT, collect_regions,
                                   derive_scope, direct_heights, logical_probes,
                                   read, source_world_matrix)


class ScopeMathChecks(unittest.TestCase):
    def test_composition_uses_existing_scale_rotation_and_row_vectors(self):
        reg = {'sourceFrame': 'viewer', 'matrix2x2': [[0, 2], [-2, 0]], 'offsetPixels': [100, 200]}
        shared = {'scale': {'value': .5}, 'rotationDeg': 30, 'originPx': {'x': 80, 'y': 240}}
        matrix, offset = source_world_matrix(reg, shared)
        point = np.array([5, 8.])
        pixel = point @ np.array(reg['matrix2x2']) + reg['offsetPixels']
        dx, dy = pixel-np.array([80, 240])
        angle = math.radians(30)
        expected = [.5*(dx*math.cos(angle)-dy*math.sin(angle)),
                    -.5*(dx*math.sin(angle)+dy*math.cos(angle))]
        np.testing.assert_allclose(point @ matrix+offset, expected)
        np.testing.assert_allclose((np.array(expected)-offset) @ np.linalg.inv(matrix), point)

    def test_never_treats_units_per_pixel_as_forward_matrix_scale(self):
        reg = {'sourceFrame': 'viewer', 'matrix2x2': [[0, 2], [-2, 0]],
               'offsetPixels': [0, 0], 'unitsPerPixel': .5}
        shared = {'scale': {'value': .5}, 'rotationDeg': 0, 'originPx': {'x': 0, 'y': 0}}
        matrix, _ = source_world_matrix(reg, shared)
        self.assertAlmostEqual(np.linalg.norm(matrix[0]), 1)

    def test_half_open_regions_and_priority_union(self):
        regions = [{'id': 'city', 'rect': {'x': [0, 10], 'z': [0, 10]}, 'priority': 0},
                   {'id': 'outside', 'rect': {'x': [5, 15], 'z': [0, 10]}, 'priority': 10}]
        probes = logical_probes(regions)
        self.assertEqual(len(probes), 6)
        self.assertEqual(sum(p[4] == 'city' for p in probes), 4)
        self.assertEqual(sum(p[4] == 'outside' for p in probes), 2)
        self.assertFalse(any(p[2] >= 15 for p in probes))

    def test_scope_axis_swap_preserves_all_corners_and_padding(self):
        regions = [{'id': 'east', 'rect': {'x': [200, 600], 'z': [-200, 200]}}]
        matrix = np.array([[0, -.5], [-.5, 0]])
        offset = np.array([-300, -650])
        rows, bounds = derive_scope(regions, matrix, offset)
        points = np.array(rows[0]['sourceCornersXZ'])
        self.assertTrue(np.all(points[:, 0] >= bounds[0]+5))
        self.assertTrue(np.all(points[:, 0] <= bounds[1]-5))
        self.assertTrue(np.all(points[:, 1] >= bounds[2]+5))
        self.assertTrue(np.all(points[:, 1] <= bounds[3]-5))
        np.testing.assert_allclose(points @ matrix+offset, rows[0]['worldCornersXZ'])

    def test_disagreement_in_contract_does_not_silently_reassign(self):
        partition = {'regions': [{'regionId': 'a', 'owner': 'o', 'priority': 1,
                                 'rect': {'x': [0, 10], 'z': [0, 10]}}],
                     'unassignedByThisModule': []}
        contract = {'regions': {'v1Bounds': [{'regionId': 'a', 'owner': 'o',
                                             'bounds': {'x': [0, 20], 'z': [0, 10]}}]}}
        with self.assertRaisesRegex(ValueError, 'disagree'):
            collect_regions(partition, contract)

    def test_missing_diagnostic_uses_real_triangles_and_keeps_holes(self):
        vertices = np.array([[0, 0, 0], [10, 10, 0], [0, 0, 10]], float)
        top, hits = direct_heights(vertices, np.array([[0, 1, 2]]), np.array([[2, 2], [9, 9]], float))
        self.assertAlmostEqual(top[0], 2)
        self.assertTrue(np.isnan(top[1]))
        self.assertEqual(hits.tolist(), [1, 0])


class FrozenSourcePackageChecks(unittest.TestCase):
    def test_fixed_locked_sources_and_extracted_meshes_match(self):
        lock = read(DEFAULT_LOCK)
        sources = {r['id']: r for r in lock['files']}
        for source in lock['files']:
            path = project_path(source['path'])
            self.assertEqual(path.stat().st_size, source['bytes'], source['id'])
            self.assertEqual(digest(path), source['sha256'], source['id'])
        index = read(EXTRACTED/'index.json')
        self.assertEqual(len(index['meshSources']), 7)
        for record in index['meshSources']:
            source = sources[record['id']]
            mesh = read_obj(project_path(source['path']))
            expected = transform(mesh, frame_matrix(source, mesh, 'viewer'))
            actual = np.load(EXTRACTED/record['geometryNpz'], allow_pickle=False)
            np.testing.assert_allclose(actual['vertices'], expected.vertices, atol=1e-10)
            np.testing.assert_array_equal(actual['faces'], expected.faces)

    def test_package_hashes_and_frozen_input_snapshots(self):
        package = read(DEFAULT_OUT/'PACKAGE.json')
        for path, row in package['files'].items():
            self.assertEqual(digest(project_path(path)), row['sha256'], path)
            self.assertEqual(project_path(path).stat().st_size, row['bytes'], path)
        for path in (DEFAULT_OUT/'input-snapshot').iterdir():
            matching = [(k, v) for k, v in package['inputsAtStart'].items() if k.endswith('/'+path.name)]
            self.assertEqual(len(matching), 1, path.name)
            self.assertEqual(digest(path), matching[0][1], path.name)
        self.assertFalse(package['gameWrites'])
        self.assertFalse(package['desktopAccess'])

    def test_every_required_region_is_exported_and_covered_in_source_grid(self):
        scope = read(DEFAULT_OUT/'region-scope.json')
        coverage = read(DEFAULT_OUT/'coverage-report.json')
        self.assertEqual(set(r['id'] for r in scope['regions']), set(r['id'] for r in coverage['regions']))
        self.assertEqual(coverage['allDeclaredRegionUnion']['statusCounts'].get('X', 0), 0)
        by_region = {r['id']: r for r in coverage['regions']}
        for name in ('R-OUT-HILL-E', 'R-OUT-GRASS-SE', 'R-OUT-FOREST-S', 'CITY-DOMAIN'):
            region = by_region[name]
            self.assertGreater(region['resolvedNew']['sourceGeometrySamples'], 100, name)
            self.assertGreater(region['resolvedNew']['sourceGeometrySamples'],
                               region['resolvedOldV2']['sourceGeometrySamples'], name)

    def test_overlap_with_old_v2_retains_identical_heights_and_masks(self):
        before = np.load(ROOT/'consumer-outside-expanded-v2/ground-height.npz', allow_pickle=False)
        after = np.load(DEFAULT_OUT/'ground-height.npz', allow_pickle=False)
        ix = np.round((before['x']-after['x'][0])/5).astype(int)
        iz = np.round((before['z']-after['z'][0])/5).astype(int)
        for name in ('ground_y', 'water_y', 'source_class', 'grade', 'source_mesh_code',
                     'alignment_grade', 'underwater_mask', 'excluded_static_above_mask',
                     'primary_multilayer_mask', 'geological_overlay_mask'):
            np.testing.assert_allclose(after[name][np.ix_(iz, ix)], before[name], atol=0, rtol=0, equal_nan=True, err_msg=name)

    def test_unknowns_and_water_remain_separate_from_ground_candidates(self):
        probes = read(DEFAULT_OUT/'world-probe-reference.json')['probes']
        report = read(DEFAULT_OUT/'coverage-report.json')
        missing = read(DEFAULT_OUT/'missing-source-evidence.json')['samples']
        self.assertEqual(len(probes), report['allDeclaredRegionUnion']['probes'])
        self.assertEqual(len(missing), sum(p['status'] == 'M' for p in probes))
        for row in probes:
            if row['status'] in ('X', 'M'):
                self.assertIsNone(row['sourceY'])
            if row['status'] == 'W':
                self.assertLessEqual(abs(row['sourceY']-row['waterCandidateY']), .25)
        self.assertFalse(report['newNativeTerrainPlan'])

    def test_source_coordinate_mapping_matches_pinned_registration(self):
        scope = read(DEFAULT_OUT/'region-scope.json')
        original = read(DEFAULT_OUT/'input-snapshot/registration.json')
        shared = read(DEFAULT_OUT/'input-snapshot/shared-transform.json')
        matrix, offset = source_world_matrix(original, shared)
        np.testing.assert_allclose(matrix, scope['sourceToWorld']['matrix2x2'])
        np.testing.assert_allclose(offset, scope['sourceToWorld']['offsetXZ'])
        grid = np.load(DEFAULT_OUT/'ground-height.npz', allow_pickle=False)
        xz = np.stack(np.meshgrid(grid['x'], grid['z']), axis=-1)
        expected_pixel = xz @ np.array(original['matrix2x2']) + original['offsetPixels']
        np.testing.assert_allclose(expected_pixel[:, :, 0], grid['official_pixel_x'], rtol=0, atol=1e-9)
        np.testing.assert_allclose(expected_pixel[:, :, 1], grid['official_pixel_y'], rtol=0, atol=1e-9)


if __name__ == '__main__':
    unittest.main()
