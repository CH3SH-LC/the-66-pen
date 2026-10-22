"""Whole-module private geometry/consumer batch; never a game acceptance run."""
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import placement as p
wf = p.wf
I = [1., 0, 0, 0, 0, 1., 0, 0, 0, 0, 1., 0, 0, 0, 0, 1.]
RUNTIME = wf.ROOT / '.runtime/world-frame-20261017'


def fixture(matrix=None, high=9998):
    return dict(schema=wf.FIXTURE_SCHEMA, fixtureId='private-placement-only', matrix=matrix or I,
                coordinateRange=[0, high], heightCodeRange=[0, high])


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.directory = RUNTIME / ('placement-fixture-' + uuid.uuid4().hex)
        self.directory.mkdir(parents=True)
        self.source = self.directory / 'original.json'
        self.source.write_text('{"privateFixture":true}', encoding='utf-8')

    def document(self, points):
        return dict(schema=wf.INPUT_SCHEMA, coordinateSpace='world-metres',
                    sources=[dict(artifactId='original', path=str(self.source), sha256=wf.sha_bytes(self.source.read_bytes()))],
                    sourceToWorldContract=dict(artifactId='original', selector='/', description='Private geometry fixture'),
                    points=[dict(sourceId='p' + str(i), worldTop=point,
                                 provenance=dict(artifactId='original', selector='/points/' + str(i)))
                            for i, point in enumerate(points)])

    def compile(self, points, matrix=None, high=9998, **options):
        return p.compile_fixture(fixture(matrix, high), self.document(points),
                                 quantization=options.pop('quantization', 'nearest'), **options)

    def code(self, expected, operation):
        with self.assertRaises(wf.FrameError) as context:
            operation()
        self.assertEqual(context.exception.code, expected, context.exception.details)

    def test_common_translation_preserves_negative_map_edges(self):
        points = [[-20., 100., -10.], [0., 105., 0.], [10., 90., 5.]]
        r = self.compile(points, preferred_translation=[0, 2000, 0], quantization='exact')
        self.assertEqual(r['worldTranslation'], [20., 2000., 10.])
        self.assertEqual(r['pointCount'], 3)
        self.assertEqual(r['points'][0]['cell'], dict(x=0, height=840, z=0))
        self.assertEqual(r['worldMatrix'], I)
        for original, row in zip(points, r['points']):
            self.assertEqual(row['sourceWorld'], original)
            self.assertEqual([row['afterWorld'][i] - original[i] for i in range(3)], [20, 2000, 10])
        self.assertTrue(p.verify_compilation(r)['ok'])

    def test_valid_preference_is_unchanged(self):
        r = self.compile([[10, 5, 10]], preferred_translation=[5, 100, 15], quantization='exact')
        self.assertEqual(r['worldTranslation'], [5, 100, 15])

    def test_zero_preference_for_valid_map(self):
        self.assertEqual(self.compile([[5, 2.5, 5]])['worldTranslation'], [0, 0, 0])

    def test_preference_moves_back_from_high_boundary_without_clipping_points(self):
        r = self.compile([[100, 10, 100], [110, 15, 110]], high=10)
        self.assertEqual(r['worldTranslation'], [-60, 0, -60])
        self.assertEqual(r['points'][1]['cell'], dict(x=10, height=6, z=10))
        self.assertEqual(r['points'][0]['sourceWorld'], [100, 10, 100])

    def test_nonzero_height_and_limited_span(self):
        r = self.compile([[0, -10, 0], [5, 0, 5]], high=10, quantization='exact')
        self.assertEqual(r['worldTranslation'], [0, 12.5, 0])
        self.assertEqual(r['points'][0]['cell']['height'], 1)

    def test_too_wide_map_refused_without_cropping(self):
        self.code('NO_COMMON_MAP_TRANSLATION', lambda: self.compile([[0, 5, 0], [55, 5, 5]], high=10))

    def test_too_tall_map_refused_without_clamping(self):
        self.code('NO_COMMON_MAP_TRANSLATION', lambda: self.compile([[0, 0, 0], [5, 25, 5]], high=10))

    def test_shear_rotation_nonuniform_translation_exact_geometry(self):
        angle = math.radians(37)
        c, s = math.cos(angle), math.sin(angle)
        matrices = [
            [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 100, 2000, -300, 1],
            [0, 0, -2, 0, 0, 3, 0, 0, 4, 0, 0, 0, 20, 7, 30, 1],
            [1, .1, 0, 0, 2, 1, 3, 0, .3, 0, 1, 0, 10, -4, 20, 1],
        ]
        for matrix in matrices:
            with self.subTest(matrix=matrix):
                local = [[-10, -5, -15], [5, 5, 0], [15, 10, 20]]
                points = [wf.tc.transform(matrix, row) for row in local]
                r = self.compile(points, matrix=matrix, high=100, quantization='exact')
                self.assertEqual(r['worldMatrix'], matrix)
                for i in range(3):
                    for j in range(3):
                        self.assertAlmostEqual(r['points'][i]['afterWorld'][j] - r['points'][0]['afterWorld'][j],
                                               points[i][j] - points[0][j], places=8)
                self.assertLess(max(r['maxAbsoluteResidualWorld']), 1e-8)
                self.assertTrue(p.verify_compilation(r)['ok'])

    def test_requested_translation_does_not_get_reselected(self):
        r = self.compile([[-5, 2.5, -10]], preferred_translation=[0, 2000, 0],
                         world_translation=[10, 100, 20], quantization='exact')
        self.assertEqual(r['worldTranslation'], [10, 100, 20])
        self.assertTrue(r['translationWasRequested'])
        self.assertTrue(p.verify_compilation(r)['ok'])

    def test_invalid_requested_translation_is_rejected(self):
        self.code('REQUESTED_MAP_TRANSLATION_OUTSIDE_DOMAIN',
                  lambda: self.compile([[-10, 5, -5]], world_translation=[0, 2000, 0]))

    def test_matrix_translation_does_not_pollute_linear_delta(self):
        matrix = I.copy(); matrix[12:15] = [1e6, 1e6, -1e6]
        r = self.compile([[1e6 - 10, 1e6 + 2.5, -1e6 - 5]], matrix=matrix,
                         preferred_translation=[0, 2.5, 0], quantization='exact')
        self.assertEqual(r['worldTranslation'], [10, 2.5, 5])

    def test_nearest_residual_retains_full_3d_error(self):
        r = self.compile([[12.5, 6.25, 17.5]])
        self.assertEqual(r['points'][0]['residualWorld'], [2.5, 1.25, 2.5])
        self.code('POINT_QUANTIZATION_REJECTED', lambda: self.compile([[12.5, 6.25, 17.5]], quantization='exact'))

    def test_duplicate_columns_remain_rejected(self):
        self.code('SOURCE_POINTS_COLLAPSE_TO_NATIVE_COLUMN',
                  lambda: self.compile([[-5, 0, -5], [-5, 2.5, -5]]))

    def test_duplicate_source_id_rejected(self):
        d = self.document([[0, 5, 0], [5, 5, 0]])
        d['points'][1]['sourceId'] = 'p0'
        with self.assertRaises(wf.FrameError):
            p.compile_fixture(fixture(), d, quantization='nearest')

    def test_all_entity_water_and_spawn_consumers_share_xyz_and_marker(self):
        r = self.compile([[-20, 10, -10], [0, 15, 5]], preferred_translation=[0, 2000, 0])
        for kind in ('building', 'npc', 'monster', 'fruit', 'water', 'spawn', 'return'):
            result = p.apply_world_translation(r, [2, 7, 9], source_id=kind)
            self.assertEqual(result['worldPosition'], [22, 2007, 19])
            self.code('WORLD_TRANSLATION_ALREADY_APPLIED', lambda: p.apply_world_translation(
                r, result['worldPosition'], source_id=kind,
                already_applied_identity=result['appliedCompilationSha256']))
        self.assertFalse(r['terrainOwnerTransformChanged'])
        self.assertFalse(r['existingNativeCellsReindexed'])
        self.assertFalse(r['consumerContract']['coverageVerified'])

    def test_source_mutation_refuses_reverification(self):
        r = self.compile([[0, 5, 0]])
        self.source.write_text('{"changed":true}', encoding='utf-8')
        self.code('SOURCE_ARTIFACT_CHANGED', lambda: p.verify_compilation(r))

    def test_result_mutation_refuses_apply(self):
        r = self.compile([[0, 5, 0]])
        r['worldTranslation'][0] = 500
        self.code('PLACEMENT_COMPILATION_CHANGED',
                  lambda: p.apply_world_translation(r, [0, 5, 0], source_id='npc'))

    def test_rehashed_false_translation_refuses_recomputation(self):
        r = self.compile([[0, 5, 0]])
        r['worldTranslation'][0] = 5
        del r['compilationSha256']; r['compilationSha256'] = wf.object_sha(r)
        self.code('PLACEMENT_RECOMPUTATION_MISMATCH', lambda: p.verify_compilation(r))

    def test_compiler_change_is_not_accepted(self):
        r = self.compile([[0, 5, 0]])
        with patch.object(p, 'source_hashes', return_value={'changed': '0' * 64}):
            self.code('PLACEMENT_COMPILER_SOURCE_CHANGED', lambda: p.verify_compilation(r))

    def test_input_is_not_modified(self):
        d = self.document([[-20, -10, -10]])
        before = copy.deepcopy(d)
        p.compile_fixture(fixture(), d, quantization='nearest')
        self.assertEqual(d, before)

    def test_nonfinite_and_bool_translation_rejected(self):
        for vector in ([True, 0, 0], [float('inf'), 0, 0], [float('nan'), 0, 0], [0, 0]):
            self.code('FINITE_VECTOR_REQUIRED', lambda: self.compile([[0, 5, 0]], preferred_translation=vector))

    def test_native_grid_provenance_checked_before_shift(self):
        f = fixture(); frame = wf._fixture_frame(f)
        d = self.document([[10, 5, 15]])
        d['points'][0].update(inputKind='native-grid-roundtrip', nativeGrid=dict(
            cell=dict(x=2, height=2, z=3), matrixSha256=frame['matrixSha256'],
            catalogIdentitySha256=frame['identitySha256']))
        r = p.compile_fixture(f, d, quantization='exact', world_translation=[5, 10, 15])
        self.assertEqual(r['points'][0]['originalGridRoundtrip']['cell'], dict(x=2, height=2, z=3))
        self.assertEqual(r['points'][0]['cell'], dict(x=3, height=6, z=6))
        self.assertTrue(p.verify_compilation(r)['ok'])
        d['points'][0]['nativeGrid']['cell']['x'] = 3
        self.code('ROUNDTRIP_INPUT_DOES_NOT_MATCH_CELL', lambda: p.compile_fixture(f, d, quantization='nearest'))

    def test_fixture_never_claims_real_catalog_or_game(self):
        r = self.compile([[0, 5, 0]])
        for key in ('nativeCatalogVerified', 'nativeCalled', 'nativeExecuted', 'nativeSaveVerified', 'gameAccepted'):
            self.assertFalse(r[key])
        self.code('COMPILATION_SCHEMA_INVALID', lambda: wf.apply_world_translation(r, [0, 5, 0], source_id='old'))

    def test_production_entry_rechecks_same_original_catalog_identity(self):
        # Explicit private stub only; no installed or running game input.
        frame = wf._fixture_frame(fixture())
        frame['mode'] = 'verified-catalog-offline'
        frame['identity']['run'] = 'private-not-a-real-catalog'
        with patch.object(wf, 'load_catalog_frame', return_value=frame) as loader:
            r = p.compile_points('private-not-a-real-catalog', self.document([[-5, 5, -5]]), quantization='exact')
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(loader.call_args.kwargs['expected_identity_sha256'], frame['identitySha256'])
            self.assertFalse(r['nativeCalled'])

    def test_production_missing_catalog_refused(self):
        with self.assertRaises((wf.FrameError, OSError, ValueError)):
            p.compile_points(self.directory / 'no-catalog', self.document([[0, 5, 0]]), quantization='nearest')

    def test_large_complete_map_preserves_25000_columns(self):
        points = [[5 * x - 600, 2.5 * (1 + (x + z) % 40) - 25, 5 * z - 700]
                  for x in range(200) for z in range(125)]
        r = self.compile(points, preferred_translation=[0, 2000, 0], quantization='exact')
        self.assertEqual(r['pointCount'], 25000)
        self.assertEqual(r['columnCount'], 25000)
        self.assertEqual(r['worldTranslation'], [600, 2000, 700])
        self.assertEqual(r['maxAbsoluteResidualWorld'], [0, 0, 0])

    def test_cli_isolated_compile_verify_and_exclusive_output(self):
        d, f = self.directory / 'points.json', self.directory / 'fixture.json'
        d.write_text(json.dumps(self.document([[-10, 5, -5]])), encoding='utf-8')
        f.write_text(json.dumps(fixture()), encoding='utf-8')
        output = self.directory / 'compiled.json'
        base = [sys.executable, '-B', '-I', '-S', str(HERE / 'placement_cli.py')]
        args = ['compile-fixture', '--fixture', str(f), '--points', str(d), '--quantization', 'exact',
                '--preferred-translation', '0', '2000', '0', '--out', str(output)]
        result = subprocess.run(base + args, cwd=self.directory, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['worldTranslation'], [10, 2000, 5])
        original = output.read_bytes()
        duplicate = subprocess.run(base + args, cwd=self.directory, capture_output=True, text=True, timeout=60)
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual(output.read_bytes(), original)
        verified = subprocess.run(base + ['verify', '--compiled', str(output)], cwd=self.directory,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertTrue(json.loads(verified.stdout)['sourceOriginalsRevalidated'])


if __name__ == '__main__':
    unittest.main()
