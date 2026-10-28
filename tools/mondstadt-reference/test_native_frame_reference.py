"""Deferred native-map derivation and evidence-boundary checks."""
import unittest
import numpy as np

from reference_cli import digest, project_path
from regional_registration import ROOT, read
from native_frame_evidence import native_to_pixel, common_to_pixel, frame_shift


class NativeFrameEvidenceChecks(unittest.TestCase):
    def test_sourced_origin_and_native_axis_order(self):
        # Converter's 2D origin is (native Z=-749.75,native X=2322).
        np.testing.assert_allclose(native_to_pixel([2322,999,-749.75]),[24206,8918])
        p=native_to_pixel([[2322,0,-749.75],[2323,0,-747.75],[2322,1,-749.75]])
        np.testing.assert_allclose(p[1]-p[0],[-2,-1])
        np.testing.assert_allclose(p[2],p[0])

    def test_common_frame_equivalence_is_explicit(self):
        xz=np.array([[-1348.94906,-649.90985],[-1700,300],[0,0]])
        xyz=np.stack((1024-xz[:,0],np.zeros(3),xz[:,1]),axis=-1)
        np.testing.assert_allclose(common_to_pixel(xz),native_to_pixel(xyz))
        with self.assertRaises(ValueError): native_to_pixel([1,float('nan'),3])

    def test_nontranslation_is_never_silently_recentered(self):
        m=np.eye(4);m[0,0]=2
        with self.assertRaises(ValueError):frame_shift({'id':'hlod-1_-1','rawToFrame':m.tolist()})
        m=np.eye(4);m[0,3]=-1025.376087;m[2,3]=-84.853233
        np.testing.assert_allclose(frame_shift({'id':'hlod-2_0','rawToFrame':m.tolist()}),[1.376087,84.853233])

    def test_derivation_and_native_point_source_integrity(self):
        p=ROOT/'native-frame-audit-v4'
        package=read(p/'PACKAGE.json')
        for path,row in package['files'].items():self.assertEqual(digest(project_path(path)),row['sha256'],path)
        for path,sha in package['inputs'].items():self.assertEqual(digest(project_path(path)),sha,path)
        for row in read(p/'coordinate-derivation.json')['sources']:
            self.assertEqual(digest(project_path(row['path'])),row['sha256'],row['path'])
        points=read(p/'native-point-cross-reference.json')['points']
        self.assertEqual(len(points),9)
        self.assertTrue(all(not row['usedAsFitControl'] and not row['matchingHlodLandmarkEstablished'] for row in points))

    def test_coordinate_formula_does_not_promote_baked_mesh_or_editor_scale(self):
        p=ROOT/'native-frame-audit-v4'
        decision=read(p/'registration-decision.json')
        self.assertEqual(decision['acceptedChanges'],[])
        self.assertEqual(decision['adoptedGradeChanges'],[])
        self.assertTrue(all(row['grade']==3 for row in decision['regionalRows']))
        self.assertEqual(len(decision['regionalRows']),5)
        self.assertFalse(decision['nativeScaleVerified'])
        self.assertEqual(decision['oldRegistrationSha256'],digest(ROOT/'registration.json'))
        self.assertEqual(decision['oldV3PackageSha256'],digest(ROOT/'consumer-all-regions-v3/PACKAGE.json'))
        features=read(p/'feature-comparison.json')
        self.assertEqual(len(features['city']),8)
        self.assertTrue(features['noControlWasFittedToAnalyticFormula'])
        seams=read(p/'seam-evidence.json')
        self.assertEqual(len(seams['pairs']),7)
        for pair in seams['pairs']:
            for key in ('viewer','raw-baked-candidate'):
                self.assertFalse(pair[key]['absoluteMapRegistrationEstablished'])

    def test_complete_region_impact_and_exact_official_code_trace(self):
        p=ROOT/'delivery-regional-calibration-v4';delivery=read(p/'DELIVERY.json')
        for group in ('packages','files'):
            for path,sha in delivery[group].items():self.assertEqual(digest(project_path(path)),sha,path)
        impact=read(p/'v3-region-impact.json')
        original=read(ROOT/'consumer-all-regions-v3/coverage-report.json')
        self.assertEqual({r['region'] for r in impact['regions']},{r['id'] for r in original['regions']})
        self.assertTrue(all(not r['highPrecisionTerrainSourceEstablished'] for r in impact['regions']))
        self.assertTrue(impact['meshEvidence']['mondstadt-city-lod0']['cityLayoutReferenceRetained'])
        self.assertEqual(len(impact['sourceOverlapDisagreements']),7)
        code=read(p/'coordinate-source-evidence.json')['officialCodeContexts']
        self.assertTrue(any('r.Transformation(1,0,1,0)' in r['snippet'] for r in code))
        self.assertTrue(any('initTileLayer:function' in r['snippet'] for r in code))


if __name__=='__main__':unittest.main()
