"""Source-locked public-city/native-city correspondence, without fitting a datum.

The transform comes from the public OBJ export convention and the actual native
prefab Transform. Independent native vertex bytes are the comparison target.
No game/desktop access, ground-layer choice, or city product generation occurs.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import numpy as np
from reference_cli import PROJECT, digest, project_path, write_json

BASE = PROJECT / 'data/mondstadt/reference3d'
FROZEN = BASE / 'native-world-source-v5-final'
CHAIN = PROJECT / '.runtime/mondstadt/rework-20261017/reference3d/source-chain-v5'
EXPECTED_PACKAGE = '05c00364b32db6d2510999f0a78ed58930f9d79111ab0db48986afe07cd662e6'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def rel(path):
    return path.resolve().relative_to(PROJECT).as_posix()


def apply_matrix(points, matrix):
    points = np.asarray(points, dtype=np.float64)
    if points.shape[-1] != 3 or not np.isfinite(points).all():
        raise ValueError('Finite XYZ points required')
    m = np.asarray(matrix, dtype=np.float64)
    return points @ m[:3, :3].T + m[:3, 3]


def distribution(values):
    v = np.asarray(values, dtype=np.float64).reshape(-1)
    return {'count': len(v), 'minimum': float(v.min()), 'maximum': float(v.max()),
            'maxAbs': float(np.abs(v).max()), 'mean': float(v.mean()),
            'rms': float(np.sqrt(np.mean(v*v))),
            'p95Abs': float(np.quantile(np.abs(v), .95))}


def face_record(face_id, vertices, faces, native_vertices, native_faces, product_matrix):
    """Same vertex IDs on both sides, including reversed native face winding."""
    ids = faces[face_id]
    v, n = vertices[ids], native_vertices[ids]
    normal = np.cross(n[1]-n[0], n[2]-n[0])
    size = np.linalg.norm(normal)
    product = apply_matrix(n, product_matrix)
    return {'sourceFaceId': int(face_id), 'sourceVertexIds': ids.tolist(),
            'nativeTriangleVertexIds': native_faces[face_id].tolist(),
            'correspondence': 'identical vertex IDs; native winding may be reversed',
            'viewerVerticesXYZ': v.tolist(), 'nativeVerticesXYZInSourceOrder': n.tolist(),
            'productVerticesXYZInSourceOrder': product.tolist(),
            'barycentricInSourceVertexOrder': [1/3, 1/3, 1/3],
            'viewerXYZ': v.mean(axis=0).tolist(), 'nativeXYZ': n.mean(axis=0).tolist(),
            'productXYZ': product.mean(axis=0).tolist(),
            'normalNativeXYZInSourceOrder': (normal/size).tolist() if size else None,
            'surfaceAreaNativeUnitsSquared': float(size/2),
            'sampleMeaning': 'same indexed triangle centroid, not selected walkable layer'}


def hits_at_xz(vertices, faces, face_ids, xz):
    out = []
    for fid in face_ids:
        t = vertices[faces[fid]]
        a, b, c = t[:, [0, 2]]
        matrix = np.column_stack((b-a, c-a))
        if abs(np.linalg.det(matrix)) < 1e-10:
            continue
        u, v = np.linalg.solve(matrix, np.asarray(xz)-a)
        weights = np.array([1-u-v, u, v])
        if weights.min() >= -1e-8:
            out.append({'sourceFaceId': int(fid), 'barycentricNativeTriangleOrder': weights.tolist(),
                        'nativeY': float(weights @ t[:, 1])})
    return out


def build(out, sidecar):
    if out.exists() or not out.is_relative_to(BASE):
        raise ValueError('A new owned immutable output directory is required')
    if digest(FROZEN/'PACKAGE.json') != EXPECTED_PACKAGE:
        raise ValueError('Frozen v5 package changed')
    out.mkdir(parents=True)
    (out/'inputs').mkdir()
    # Snapshot the old emitted frame; active city work may subsequently replace it.
    sources = {
        'legacy-region-frame.json': sidecar,
        'public-extraction-index.json': BASE/'extracted-final-v1/index.json',
        'public-registration.json': BASE/'registration.json',
        'native-city-placement.json': CHAIN/'native-world-city-e/native-world-index.json',
        'named-landmarks.json': BASE/'named-landmarks.json',
        'legacy-generator.py': PROJECT/'tools/mondstadt/city/regions/cathedral_plaza.py',
    }
    inputs = []
    for name, path in sources.items():
        payload = path.read_bytes()
        dst = out/'inputs'/name
        dst.write_bytes(payload)
        inputs.append({'originalPath': rel(path), 'snapshot': 'inputs/'+name,
                       'sha256': digest(dst), 'bytes': len(payload)})
    legacy = read(out/'inputs/legacy-region-frame.json')
    public_index = read(out/'inputs/public-extraction-index.json')
    source = next(x for x in public_index['meshSources'] if x['id']=='mondstadt-city-lod0')
    native_index = read(out/'inputs/native-city-placement.json')
    native_row = next(x for x in native_index['placedMeshes'] if x['name']=='Area_Mengde_City_Constant_HLOD_Lod0')
    native_frame = np.asarray(native_row['nativeMatrixColumnVector'])
    raw_to_viewer = np.asarray(source['rawToFrame'])
    obj_to_native_local = np.diag([-1., 1., 1., 1.])
    viewer_to_native = native_frame @ obj_to_native_local @ np.linalg.inv(raw_to_viewer)
    native_source = read(FROZEN/'source-index.json')
    mapping = native_source['declaredProductTransform']
    native_to_product = np.asarray(mapping['nativeToProductMatrixColumnVector'])
    viewer_to_product = native_to_product @ viewer_to_native
    old_path = BASE/'extracted-final-v1/mondstadt-city-lod0.npz'
    new_path = FROZEN/'meshes/native-5.npz'
    old = np.load(old_path, allow_pickle=False)
    new = np.load(new_path, allow_pickle=False)
    vertices, faces = old['vertices'].astype(float), old['faces'].astype(np.int64)
    native_vertices, native_faces = new['vertices'].astype(float), new['triangles'].astype(np.int64)
    if vertices.shape != native_vertices.shape or faces.shape != native_faces.shape:
        raise ValueError('Correspondence dimensions changed')
    if not np.array_equal(np.sort(faces, axis=1), np.sort(native_faces, axis=1)):
        raise ValueError('Same-index faces are no longer the same vertex sets')
    predicted = apply_matrix(vertices, viewer_to_native)
    errors = predicted-native_vertices
    # This is an independent decoding comparison, not a least-squares fit.
    if np.abs(errors).max() > 2e-5:
        raise ValueError('Public/native correspondence exceeds locked extraction precision')
    components = read(FROZEN/'city-native-components.json')['components']
    by_component = {x['componentId']: x for x in components}
    sem = read(FROZEN/'meshes/mondstadt-city-lod0-semantic-faces.json')
    paved = next(x for x in sem['classifications'] if x['classification']=='city-paved')
    paved_faces = set(paved['faceIds'])
    reg = read(out/'inputs/public-registration.json')
    regions = {k: v for k, v in legacy['regions'].items()
               if v.get('emittedYFrame')=='source-datum-minus-datumViewerY'}
    if not regions:
        raise ValueError('No explicitly declared legacy source-datum regions')
    declarations = {(r['datumViewerY'], r['unitToMetre'], r['datumCandidateId']) for r in regions.values()}
    if len(declarations) != 1:
        raise ValueError('Different legacy datums need separate explicit conversions')
    datum, factor, component = next(iter(declarations))
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError('Invalid declared legacy factor')
    s = float(mapping['scale'])
    yref = float(mapping['nativeYReference'])
    datum_faces = by_component[component]['faceIds']
    # Trace the already emitted scalar to concrete source geometry. This does NOT
    # choose a new datum or assert the highest surface is the road at the origin.
    matching = [int(f) for f in datum_faces if np.abs(vertices[faces[f], 1]-datum).max() < 1e-7]
    if not matching:
        raise ValueError('Declared legacy datum has no fully corresponding source face')
    datum_rows = [face_record(f, vertices, faces, native_vertices, native_faces, native_to_product) for f in matching]
    for row in datum_rows:
        row.update(componentId=component, sourceSemantic='city-paved' if row['sourceFaceId'] in paved_faces else 'unclassified',
                   semanticEvidence='frozen v5 semantic face set, inherited analyst classification; not game collision')
    selected_ids = set(paved['components'])
    selected_ids.update(int(c['sourceComponent']) for c in reg['controls'])
    controls = []
    for cid in sorted(selected_ids):
        c = by_component[cid]
        fs = np.array(c['faceIds'])
        tri = native_vertices[native_faces[fs]]
        area = np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1)
        fid = int(fs[np.argmax(area)])
        row = face_record(fid, vertices, faces, native_vertices, native_faces, native_to_product)
        row['componentId'] = cid
        row['selectionMethod'] = 'largest-area face of pre-existing control/paved component; correspondence probe only'
        row['original2dControls'] = [c for c in reg['controls'] if c['sourceComponent']==cid]
        row['existingClassification'] = 'city-paved' if fid in paved_faces else 'unclassified'
        pp = apply_matrix([row['viewerXYZ']], viewer_to_native)[0]
        row['residualNativeXYZ'] = (pp-np.asarray(row['nativeXYZ'])).tolist()
        controls.append(row)
    datum_y_native = float(viewer_to_native[1, 1]*datum+viewer_to_native[1, 3])
    if np.count_nonzero(viewer_to_native[1, [0, 2]]) or viewer_to_native[1, 1] != 1:
        raise ValueError('This legacy Y-only API requires source vertical axes to agree')
    slope = s/factor
    intercept = s*(datum_y_native-yref)
    old_local_y = (vertices[:, 1]-datum)*factor
    target_product_y = apply_matrix(native_vertices, native_to_product)[:, 1]
    transformed_local = slope*old_local_y+intercept
    additive_only = old_local_y+intercept
    # Reconstruct the old registered XYZ transform explicitly. Applies ONLY to
    # positions actually derived from this source transform, never arbitrary regions.
    reg_matrix = np.asarray(reg['matrix2x2'])
    origin = read(FROZEN/'inputs/shared-transform.json')['originPx']
    old_matrix = np.eye(4)
    old_matrix[0] = [s*reg_matrix[0, 0], 0., s*reg_matrix[1, 0], s*(reg['offsetPixels'][0]-origin['x'])]
    old_matrix[1] = [0., factor, 0., -factor*datum]
    old_matrix[2] = [-s*reg_matrix[0, 1], 0., -s*reg_matrix[1, 1], -s*(reg['offsetPixels'][1]-origin['y'])]
    legacy_to_product = viewer_to_product @ np.linalg.inv(old_matrix)
    origin_native_xz = apply_matrix([[0., 0., 0.]], mapping['productToNativeMatrixColumnVector'])[0, [0, 2]]
    origin_hits = hits_at_xz(native_vertices, native_faces, sorted(paved_faces), origin_native_xz)
    for row in origin_hits:
        row['productY'] = s*(row['nativeY']-yref)
    anchors = {'schema': 1, 'datumMeaning': 'legacy emitted scalar traced to matching source faces; not a newly chosen ground datum',
               'legacyDatumViewerY': datum, 'legacyDatumComponentId': component,
               'matchingHorizontalFaceAnchors': datum_rows,
               'legacyAabbMaxWasNotAnOriginSurfaceMeasurement': True,
               'productOriginNativeXZ': origin_native_xz.tolist(), 'allSelectedPavedHitsAtProductOrigin': origin_hits,
               'originHitRule': 'all hits preserved; none selected as walking surface',
               'componentNativeEvidence': by_component[component]}
    write_json(out/'datum-face-anchors.json', anchors)
    write_json(out/'control-faces.json', {'rows': controls, 'fittedParameters': 0,
               'meaning': 'independent native bytes compared with source/parent-derived transform; no fitting on these probes'})
    np.savez_compressed(out/'all-vertex-correspondence.npz', sourceVertexId=np.arange(len(vertices)),
                        residualNativeXYZ=errors, legacyLocalY=old_local_y,
                        actualNativeProductY=target_product_y, recoveredProductY=transformed_local)
    report = {'schema': 1, 'status': 'source-correspondence-established', 'inputs': inputs,
        'frozenNativePackage': rel(FROZEN/'PACKAGE.json'), 'frozenNativePackageSha256': EXPECTED_PACKAGE,
        'sourceFiles': [{'path': rel(p), 'sha256': digest(p)} for p in
            [old_path, new_path, FROZEN/'source-index.json', FROZEN/'city-native-components.json',
             FROZEN/'meshes/mondstadt-city-lod0-semantic-faces.json']],
        'transformDerivation': {'method': 'nativePrefabMatrix * objExportXReflection * inverse(publicRawToViewer)',
            'nativePrefabMatrixColumnVector': native_frame.tolist(), 'objExportXReflection': obj_to_native_local.tolist(),
            'publicRawToViewerColumnVector': raw_to_viewer.tolist(),
            'nativePrefabCab': native_row['prefabCab'], 'meshCab': native_row['meshCab'],
            'meshPathId': native_row['meshPathId'], 'meshNodeSha256': native_row['meshNodeSha256'],
            'prefabNodeSha256': native_row['prefabNodeSha256'],
            'objConventionEvidence': rel(CHAIN/'AnimeStudio.CLI_Exporter.cs'),
            'objConventionEvidenceSha256': digest(CHAIN/'AnimeStudio.CLI_Exporter.cs'),
            'viewerToNativeFormula': ['nativeX = 1024 - viewerX', 'nativeY = viewerY', 'nativeZ = viewerZ'],
            'fittedParameters': 0, 'usesCentroidMinOrMaxHitAsCalibration': False},
        'viewerToNativeMatrixColumnVector': viewer_to_native.tolist(),
        'viewerToProductMatrixColumnVector': viewer_to_product.tolist(),
        'nativeToProductMatrixColumnVector': native_to_product.tolist(),
        'declaredProductTransform': mapping,
        'legacyConversion': {'eligibleDeclaredRegionsAtSnapshot': sorted(regions),
            'eligibility': 'caller must declare the SAME source-datum frame; no whole-city blanket conversion',
            'datumViewerY': datum, 'datumCandidateId': component,
            'declaredLegacySourceUnitToLocalUnit': factor,
            'factorFromOriginalRegistration': s/reg['unitsPerPixel'],
            'factorDeclarationRoundingDifference': factor-s/reg['unitsPerPixel'],
            'productYMultiplier': slope, 'productYAddend': intercept,
            'formula': 'productY = s * (legacyLocalY / legacyFactor + datumViewerY - nativeYReference)',
            'heightDifferenceFormula': 'productDeltaY = legacySourceDerivedDeltaY * s / legacyFactor',
            'positionScope': 'source-derived origins/pivots only; authored offsets and prefab design dimensions need owner intent, not indiscriminate rescaling',
            'editorFormula': 'editorY = productY + one shared owner-selected editorYOffset',
            'legacyViewerToXYZMatrixColumnVector': old_matrix.tolist(),
            'legacySourceXYZToProductMatrixColumnVector': legacy_to_product.tolist(),
            'oldGeneratorLocalYRoundStep': .001,
            'roundingOnlyProductYErrorBound': .0005*abs(slope),
            'singleAdditiveCorrectionExact': False},
        'independentResiduals': {'vertexCount': len(vertices), 'faceCount': len(faces),
            'sameFaceIndexSameVertexSet': True,
            'nativeXYZEuclidean': distribution(np.linalg.norm(errors, axis=1)),
            'nativeY': distribution(errors[:, 1]),
            'recoveredLegacyProductY': distribution(transformed_local-target_product_y),
            'additiveOnlyAtCorrectDatumProductY': distribution(additive_only-target_product_y),
            'controlFaceCount': len(controls), 'fitSamplesUsed': 0,
            'independence': 'public OBJ decoded separately from local installed mesh + prefab parent; native target arrays do not participate in transform fitting',
            'notGlobalAccuracy': 'same city HLOD geometry correspondence, not high-detail model accuracy, editor metric calibration, collision or gameplay'},
        'datumEvidence': 'datum-face-anchors.json', 'controlEvidence': 'control-faces.json',
        'limitations': ['HLOD Lod0 is the asset name, not a full-resolution claim.',
            'Semantic paved classifications are inherited analyst evidence, not runtime walkability.',
            'Current product scale remains a declared design scale, not editor metre measurement.',
            'The source correspondence does not pick buildings, standing layers, pivots, or city content.',
            'Non-source-derived and already-product coordinates must not receive the legacy conversion.'],
        'gameProcessAccess': False, 'desktopAccess': False, 'installationWrites': False}
    write_json(out/'correspondence.json', report)
    documentation = '''# City source correspondence\n\nRead correspondence.json before applying any legacy conversion. The public city and\nnative city are the same indexed HLOD geometry, separately decoded. The transform\nis derived from the OBJ X reflection plus real native prefab root [2275,263,-783].\nIt is not fitted to the samples in this package.\n\nviewer -> native: [1024-viewerX, viewerY, viewerZ].\nviewer -> v5 product: [-0.5*(749.75+viewerZ), 0.5*viewerY, -0.5*(viewerX+1298)].\n\nThe old source-datum height is y=(viewerY-253.580176)*legacyFactor. Recover the\nsource Y FIRST, then apply the v5 product matrix. This yields a multiplier plus\nan addend; adding a city-wide constant is insufficient. The scalar 253.580176\nis traced to source faces 9051..9054 of component 481. It is not a measurement of\nthe surface at the map origin; all origin face hits are separately retained.\n\nOnly the explicitly declared old source-datum frame is eligible. Source heights\nand source-derived vertical differences can be converted. Arbitrarily authored\nprefab offsets/scales, already-product data, and regions merely labelled world\nmust be reviewed by their owner. No city generator is changed here.\n\nPython:\n    import sys\n    sys.path.insert(0, 'tools/mondstadt-reference')\n    from city_source_correspondence import CityCorrespondence\n    c = CityCorrespondence('data/mondstadt/reference3d/city-source-correspondence-v1/correspondence.json')\n    c.viewer_to_product([[-1298, 253.580176, -749.75]])\n    c.legacy_y_to_product([0], frame='source-datum-minus-datumViewerY')\n\nThe returned product Y is already scaled. The integrator adds the one shared\neditor Y offset exactly once. Do not add a terrain datum or multiply again.\nThis source-module package and its offline tests are not live game acceptance.\n'''
    (out/'README.md').write_text(documentation, encoding='utf8')
    write_json(out/'PACKAGE.json', {'schema': 1, 'entry': 'correspondence.json', 'immutable': True,
        'files': {p.relative_to(out).as_posix(): {'sha256': digest(p), 'bytes': p.stat().st_size}
                  for p in sorted(out.rglob('*')) if p.is_file()},
        'tools': {rel(p): digest(p) for p in [Path(__file__),
            Path(__file__).with_name('asset_index_completion.py'),
            Path(__file__).with_name('test_city_source_correspondence.py'),
            Path(__file__).with_name('run_city_source_batch.py')]}})
    return {'entry': rel(out/'correspondence.json'), 'packageSha256': digest(out/'PACKAGE.json'),
            'legacyConversion': report['legacyConversion'], 'independentResiduals': report['independentResiduals']}


class CityCorrespondence:
    def __init__(self, path):
        self.path = project_path(path)
        package = read(self.path.parent/'PACKAGE.json')
        entry = package['files'][self.path.name]
        if digest(self.path) != entry['sha256']:
            raise ValueError('Correspondence entry SHA mismatch')
        self.report = read(self.path)
        if self.report['status'] != 'source-correspondence-established':
            raise ValueError('Unestablished source correspondence')
        for row in self.report['sourceFiles']:
            if digest(project_path(row['path'])) != row['sha256']:
                raise ValueError('Source SHA mismatch: '+row['path'])
        for row in self.report['inputs']:
            if digest(self.path.parent/row['snapshot']) != row['sha256']:
                raise ValueError('Frozen input snapshot changed')

    def viewer_to_native(self, xyz):
        return apply_matrix(xyz, self.report['viewerToNativeMatrixColumnVector'])

    def viewer_to_product(self, xyz):
        return apply_matrix(xyz, self.report['viewerToProductMatrixColumnVector'])

    def legacy_y_to_product(self, y, *, frame, declared_factor=None, declared_datum=None):
        if frame != 'source-datum-minus-datumViewerY':
            raise ValueError('Explicit source-datum frame required; no automatic region guessing')
        cfg = self.report['legacyConversion']
        if declared_factor is not None and abs(declared_factor-cfg['declaredLegacySourceUnitToLocalUnit']) > 1e-10:
            raise ValueError('Caller legacy factor differs from the locked frame')
        if declared_datum is not None and abs(declared_datum-cfg['datumViewerY']) > 1e-7:
            raise ValueError('Caller datum differs from the locked frame')
        y = np.asarray(y, float)
        if not np.isfinite(y).all():
            raise ValueError('Finite height required')
        return y*cfg['productYMultiplier']+cfg['productYAddend']

    def source_derived_legacy_delta_y_to_product(self, delta):
        delta = np.asarray(delta, float)
        if not np.isfinite(delta).all():
            raise ValueError('Finite source-derived height difference required')
        return delta*self.report['legacyConversion']['productYMultiplier']


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    p.add_argument('--legacy-frame', default='.city-out/data/mondstadt/city/region-frame-sidecar.json')
    a = p.parse_args()
    print(json.dumps(build(project_path(a.out), project_path(a.legacy_frame)), ensure_ascii=False))
