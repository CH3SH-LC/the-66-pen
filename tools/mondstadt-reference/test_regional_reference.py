"""Deferred complete-batch checks for independent regional calibration."""
import unittest

import numpy as np

from reference_cli import digest, project_path
from regional_registration import (PREPARE, ROOT, fit_translation, read,
                                   stitched_features, visible_contour_segments, water_edge)


class RegionalRegistrationChecks(unittest.TestCase):
    def test_exact_well_spread_independent_controls_recover_translation(self):
        source = np.array([[0, 0], [200, 0], [0, 200], [200, 200]], float)
        m, o = np.array([[0, 1], [-1, 0]], float), np.array([24000, 9000], float)
        target = source @ m+o+[17, -21]
        fitted = fit_translation(source, target, m, o, [2]*4)
        self.assertTrue(fitted['accepted'])
        np.testing.assert_allclose(fitted['pixelTranslationCandidate'], [17, -21])
        self.assertLess(fitted['maxLeaveOneOutPixels'], 1e-10)

    def test_small_numerical_error_does_not_upgrade_ambiguous_identification(self):
        source = np.array([[0, 0], [200, 0], [0, 200], [200, 200]], float)
        fitted = fit_translation(source, source+[5, 8], np.eye(2), np.zeros(2), [25]*4)
        self.assertEqual(fitted['rmsePixels'], 0)
        self.assertFalse(fitted['accepted'])
        self.assertIn('feature-identification-uncertainty-over-5px', fitted['rejectionReasons'])

    def test_one_bad_landmark_retained_and_rejected_by_leave_one_out(self):
        source = np.array([[0, 0], [200, 0], [0, 200], [200, 200]], float)
        target = source.copy(); target[-1] += [50, -30]
        fitted = fit_translation(source, target, np.eye(2), np.zeros(2), [2]*4)
        self.assertFalse(fitted['accepted'])
        self.assertEqual(len(fitted['residualPixels']), 4)
        self.assertGreater(fitted['maxLeaveOneOutPixels'], 50)

    def test_collinear_and_too_few_controls_never_promoted(self):
        source = np.array([[0, 0], [200, 0], [400, 0]], float)
        fitted = fit_translation(source, source, np.eye(2), np.zeros(2), [2]*3)
        self.assertFalse(fitted['accepted'])
        self.assertIn('control-hull-too-narrow', fitted['rejectionReasons'])
        empty = fit_translation([], [], np.eye(2), np.zeros(2), [])
        self.assertFalse(empty['accepted']); self.assertEqual(empty['controlCount'], 0)

    def test_hidden_lower_terrain_contour_is_excluded(self):
        vertices = np.array([[0, 0, 0], [20, 0, 0], [0, 0, 20],
                             [0, 8, 0], [20, 8, 0], [0, 8, 20]], float)
        segments = np.array([[[2, 2], [10, 2]]], float)
        visible, hidden = visible_contour_segments(vertices, np.array([[0, 1, 2], [3, 4, 5]]), segments, 0)
        self.assertEqual(len(visible), 0); self.assertGreater(hidden, 0)

    def test_simplified_feature_coordinates_are_original_endpoints(self):
        segments = np.array([[[0, 0], [10, 0]], [[10, 0], [20, 0]],
                             [[20, 0], [20, 20]], [[20, 20], [0, 20]]], float)
        ids = stitched_features(segments, np.eye(2), tolerance=1)
        points = segments.reshape(-1, 2)[ids]
        self.assertFalse(any(np.array_equal(p, [10, 0]) for p in points))
        self.assertTrue(any(np.array_equal(p, [20, 0]) for p in points))

    def test_map_lines_not_mistaken_for_large_unknown_map_zone(self):
        image = np.full((240, 240, 3), [130, 150, 70], np.uint8)
        image[:, 119:121] = [20, 30, 20]
        _, _, _, known = water_edge(image)
        self.assertGreater(known[120, 120], 100)
        image[:120, :] = [10, 10, 10]
        _, _, _, known = water_edge(image)
        self.assertEqual(known[20, 20], 0)


class RegionalPackageChecks(unittest.TestCase):
    def test_locked_package_and_original_map_tiles(self):
        output = ROOT/'regional-calibration-v4'
        package = read(output/'PACKAGE.json')
        for path, info in package['files'].items():
            self.assertEqual(digest(project_path(path)), info['sha256'], path)
        for path, sha in package['inputs'].items():
            self.assertEqual(digest(project_path(path)), sha, path)
        for row in read(PREPARE/'official-tiles-lock.json')['tiles']:
            self.assertEqual(digest(project_path(row['path'])), row['sha256'])

    def test_no_false_promotion_or_existing_registration_change(self):
        output = ROOT/'regional-calibration-v4'
        registration = read(output/'regional-registration.json')
        self.assertEqual(len(registration['rows']), 5)
        self.assertEqual(digest(ROOT/'registration.json'), registration['oldGlobalRegistrationSha256'])
        self.assertEqual(digest(ROOT/'consumer-all-regions-v3/PACKAGE.json'), registration['oldV3PackageSha256'])
        ambiguous = next(r for r in registration['rows'] if r['mesh'] == 'hlod-2_0')
        self.assertEqual(ambiguous['fit']['controlCount'], 0)
        self.assertEqual(ambiguous['excludedAmbiguousControls'], 5)
        self.assertEqual(ambiguous['recommendedAlignmentGrade'], 3)
        self.assertFalse(ambiguous['fit']['accepted'])
        for row in registration['rows']:
            if not row['fit']['accepted']:
                self.assertEqual(row['recommendedAlignmentGrade'], 3)
            self.assertFalse(row['sourceGeometryChanged'])
        self.assertFalse(registration['gameWrites'])

    def test_real_geometry_control_trace_and_neighbor_checks(self):
        registration = read(ROOT/'regional-calibration-v4/regional-registration.json')
        contours = {r['mesh']: r for r in read(PREPARE/'contours.json')['meshes']}
        for row in registration['rows']:
            for control in row['controls']:
                layer = contours[row['mesh']]['waterContours'][control['layerIndex']]
                original = np.array(layer['segmentsXZ']).reshape(-1, 2)[control['endpointIndex']]
                np.testing.assert_allclose(original, control['sourceXZ'], rtol=0, atol=0)
        overlap = read(ROOT/'regional-calibration-v4/overlap-report.json')
        self.assertEqual(len(overlap['pairs']), 7)
        self.assertTrue(overlap['candidateShiftsAreNotApplied'])
        for pair in overlap['pairs']:
            self.assertIn('before', pair); self.assertIn('candidate', pair)


if __name__ == '__main__': unittest.main()
