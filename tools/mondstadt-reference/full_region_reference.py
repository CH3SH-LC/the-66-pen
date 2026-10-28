"""Immutable source coverage export for every declared Mondstadt region.

This is a reference-source producer, not the DSH terrain producer. World probes
only measure availability on the consumer's existing logical grid. They contain
raw source heights, never native height codes, write cards, or generated objects.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ground_reference import build as build_ground
from reference_cli import PROJECT, DEFAULT_LOCK, digest, project_path, write_json

ROOT = PROJECT / 'data/mondstadt/reference3d'
DEFAULT_OUT = ROOT / 'consumer-all-regions-v3'
PARTITION = PROJECT / 'data/mondstadt/outside/region-partition.json'
CONTRACT = PROJECT / 'data/mondstadt/world-contract.json'
SHARED = PROJECT / 'data/mondstadt/outside/terrain/shared-transform.json'
REGISTRATION = ROOT / 'registration.json'
EXTRACTED = ROOT / 'extracted-final-v1'
STATUS = {'G': 'source ground candidate', 'B': 'source ground below water candidate',
          'W': 'ground and water at same elevation: unresolved water surface',
          'M': 'source mesh selection has no sample here', 'X': 'outside exported source grid'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def relative(path):
    return Path(path).resolve().relative_to(PROJECT).as_posix()


def source_world_matrix(registration, shared):
    """Compose the two authoritative row-vector transforms without refitting."""
    if registration['sourceFrame'] != 'viewer':
        raise ValueError('Only the registered viewer frame is supported')
    scale = float(shared['scale']['value'])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Shared scale must be positive and finite')
    theta = math.radians(float(shared['rotationDeg']))
    c, s = math.cos(theta), math.sin(theta)
    pixel_to_world = scale * np.array([[c, -s], [-s, -c]])
    origin = np.array([shared['originPx']['x'], shared['originPx']['y']], float)
    m = np.asarray(registration['matrix2x2'], float) @ pixel_to_world
    o = (np.asarray(registration['offsetPixels'], float) - origin) @ pixel_to_world
    if not np.isfinite(m).all() or abs(np.linalg.det(m)) < 1e-12:
        raise ValueError('Invalid or singular source/world transformation')
    return m, o


def rect_corners(rect):
    x0, x1 = rect['x']; z0, z1 = rect['z']
    if not (math.isfinite(x0 + x1 + z0 + z1) and x0 < x1 and z0 < z1):
        raise ValueError('Invalid finite rectangle')
    return np.array([[x0, z0], [x1, z0], [x1, z1], [x0, z1]], float)


def collect_regions(partition, contract):
    """Retain partition priority, add current non-retired contract rectangles."""
    result = []
    for row in partition['regions'] + partition['unassignedByThisModule']:
        result.append({'id': row.get('regionId', row.get('id')), 'owner': row['owner'],
                       'rect': row['rect'], 'priority': row['priority'],
                       'source': relative(PARTITION), 'partitionRule': True})
    by_id = {row['id']: row for row in result}
    for row in contract['regions']['v1Bounds']:
        bounds = row.get('bounds', {})
        if row.get('retired') or not ('x' in bounds and 'z' in bounds):
            continue
        rid = row['regionId']
        if rid in by_id:
            if bounds != by_id[rid]['rect']:
                raise ValueError('Current contract/partition bounds disagree: ' + rid)
            continue
        # City subregions may overlap CITY-DOMAIN. Their declared availability is
        # also reported, but no new ownership rule is invented.
        result.append({'id': rid, 'owner': row['owner'], 'rect': bounds,
                       'priority': 90 if row.get('soleTerrainWriter') else 100,
                       'source': relative(CONTRACT), 'partitionRule': False})
    for row in result:
        rect_corners(row['rect'])
    return result


def derive_scope(regions, matrix, offset, spacing=5.0):
    inverse = np.linalg.inv(matrix)
    all_source = []
    result = []
    for region in regions:
        corners = rect_corners(region['rect'])
        source = (corners - offset) @ inverse
        all_source.extend(source.tolist())
        result.append(dict(region, worldCornersXZ=corners.tolist(),
                           sourceCornersXZ=source.tolist(), sourceBounds={
                               'xmin': float(source[:, 0].min()), 'xmax': float(source[:, 0].max()),
                               'zmin': float(source[:, 1].min()), 'zmax': float(source[:, 1].max())}))
    points = np.array(all_source)
    # A full extra source sample on each side includes points sampled nearest to
    # the region boundary. This padding is data scope, not a native write area.
    bounds = [math.floor(points[:, 0].min()/spacing)*spacing-spacing,
              math.ceil(points[:, 0].max()/spacing)*spacing+spacing,
              math.floor(points[:, 1].min()/spacing)*spacing-spacing,
              math.ceil(points[:, 1].max()/spacing)*spacing+spacing]
    return result, bounds


def logical_probes(regions, spacing=5.0):
    """Same (i+.5)*5 world centers as current outside consumer, half-open ROI."""
    pts = []
    lo = np.min(np.vstack([rect_corners(r['rect']) for r in regions]), axis=0)
    hi = np.max(np.vstack([rect_corners(r['rect']) for r in regions]), axis=0)
    for iz in range(math.floor(lo[1]/spacing), math.ceil(hi[1]/spacing)):
        for ix in range(math.floor(lo[0]/spacing), math.ceil(hi[0]/spacing)):
            x, z = (ix+.5)*spacing, (iz+.5)*spacing
            matches = [r for r in regions if r['rect']['x'][0] <= x < r['rect']['x'][1]
                       and r['rect']['z'][0] <= z < r['rect']['z'][1]]
            if matches:
                owner = min(matches, key=lambda r: r['priority'])['id']
                pts.append((ix, iz, x, z, owner, [r['id'] for r in matches]))
    return pts


def direct_heights(vertices, faces, points):
    """Exact vertical intersections at selected source XZ; diagnostic only."""
    top = np.full(len(points), np.nan)
    hits = np.zeros(len(points), dtype=np.int32)
    for ids in faces:
        tri = vertices[ids]
        xz = tri[:, [0, 2]]
        a, b = xz[1]-xz[0], xz[2]-xz[0]
        det = a[0]*b[1]-a[1]*b[0]
        if abs(det) < 1e-12:
            continue
        candidate = np.nonzero(np.all(points >= xz.min(0)-1e-9, axis=1)
                               & np.all(points <= xz.max(0)+1e-9, axis=1))[0]
        if not len(candidate):
            continue
        q = points[candidate]-xz[0]
        u = (q[:, 0]*b[1]-q[:, 1]*b[0])/det
        v = (a[0]*q[:, 1]-a[1]*q[:, 0])/det
        inside = (u >= -1e-9) & (v >= -1e-9) & (u+v <= 1+1e-9)
        take = candidate[inside]
        y = tri[0, 1]+u[inside]*(tri[1, 1]-tri[0, 1])+v[inside]*(tri[2, 1]-tri[0, 1])
        top[take] = np.fmax(top[take], y)
        hits[take] += 1
    return top, hits


def availability(package, probes, matrix, offset):
    # NPZ indexing decompresses a whole member each time. Materialize once
    # before tens of thousands of point queries, keeping this source tool bound.
    with np.load(package/'ground-height.npz', allow_pickle=False) as archive:
        grid = {key: archive[key] for key in archive.files}
    world = np.array([[p[2], p[3]] for p in probes])
    source = (world-offset) @ np.linalg.inv(matrix)
    columns = np.floor((source[:, 0]-grid['x'][0])/(grid['x'][1]-grid['x'][0])+.5).astype(int)
    rows = np.floor((source[:, 1]-grid['z'][0])/(grid['z'][1]-grid['z'][0])+.5).astype(int)
    result = []
    for i, (r, c) in enumerate(zip(rows, columns)):
        record = {'logicalCell': list(probes[i][:2]), 'worldXZ': world[i].tolist(),
                  'sourceXZ': source[i].tolist(), 'resolvedRegion': probes[i][4],
                  'declaredRegions': probes[i][5]}
        if not (0 <= r < len(grid['z']) and 0 <= c < len(grid['x'])):
            record.update(status='X', sourceNode=None, sourceY=None, meshCode=0, alignmentGrade=0)
        else:
            gy, wy = float(grid['ground_y'][r, c]), float(grid['water_y'][r, c])
            status = ('M' if not math.isfinite(gy) else 'W' if math.isfinite(wy) and abs(gy-wy) <= .25
                      else 'B' if grid['underwater_mask'][r, c] else 'G')
            node_world = np.array([grid['x'][c], grid['z'][r]]) @ matrix+offset
            record.update(status=status, sourceNode=[int(r), int(c)],
                          sourceY=gy if math.isfinite(gy) else None,
                          waterCandidateY=wy if math.isfinite(wy) else None,
                          meshCode=int(grid['source_mesh_code'][r, c]),
                          alignmentGrade=int(grid['alignment_grade'][r, c]),
                          sourceClass=int(grid['source_class'][r, c]),
                          grade=int(grid['grade'][r, c]),
                          sourceSampleOffsetWorld=float(np.linalg.norm(node_world-world[i])),
                          excludedStaticAbove=bool(grid['excluded_static_above_mask'][r, c]),
                          primaryMultilayer=bool(grid['primary_multilayer_mask'][r, c]),
                          geologicalOverlay=bool(grid['geological_overlay_mask'][r, c]))
        result.append(record)
    return result


def summarize(rows):
    return {'probes': len(rows), 'statusCounts': dict(Counter(r['status'] for r in rows)),
            'sourceGeometrySamples': sum(r['status'] in ('G', 'B', 'W') for r in rows),
            'usableCandidateSamples': sum(r['status'] in ('G', 'B') for r in rows),
            'meshCodeCounts': dict(Counter(str(r['meshCode']) for r in rows)),
            'alignmentGradeCounts': dict(Counter(str(r['alignmentGrade']) for r in rows))}


def evidence_audit(index):
    shoreline = ROOT/'shoreline-review/shoreline-controls.json'
    controls = read(shoreline) if shoreline.exists() else None
    rows = []
    for mesh in index['meshSources']:
        mid = mesh['id']
        level = 1 if mid == 'mondstadt-city-lod0' else 2 if mid == 'hlod-2_-1' else 3
        rows.append({'id': mid, 'sourceSha256': mesh['sourceSha256'],
                     'rawToViewerMatrix4x4': mesh['rawToFrame'],
                     'rawBoundsXYZ': {'min': mesh['rawAabbMin'], 'max': mesh['rawAabbMax']},
                     'viewerBoundsXYZ': {'min': mesh['aabbMin'], 'max': mesh['aabbMax']},
                     'alignmentGrade': level,
                     'independentEvidence': ('8 city visual control correspondences in registration.json' if level == 1
                                             else '3 distinct shoreline capes; ambiguous controls retained, no per-block fit' if level == 2
                                             else 'none: only pinned upstream manifest/AABB-centering placement'),
                     'nativeAbsolutePositionVerified': False, 'automaticRegistrationClaimed': False})
    return {'meshes': rows, 'shorelineControlsPath': relative(shoreline) if controls else None,
            'shorelineControlsSha256': digest(shoreline) if controls else None,
            'rule': 'No existing matrix or alignment grade changed. Bounding-box overlap does not establish georegistration.',
            'nativeY': 'Not converted. Source Y stays raw; DSH owns its existing datum and terrain quantization.',
            'sourceLOD': 'Android HLOD LOD0, not full original render or collision geometry',
            'sourceGameVersion': 'unknown', 'syntheticOceanIncluded': False}


def draw_coverage(out, rows, regions):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(17, 9), constrained_layout=True)
    height = [r for r in rows if r['sourceY'] is not None]
    scatter = axes[0].scatter([r['worldXZ'][0] for r in height], [r['worldXZ'][1] for r in height],
                              c=[r['sourceY'] for r in height], s=5, cmap='terrain', marker='s')
    fig.colorbar(scatter, ax=axes[0], label='Raw source Y (not editor height)')
    colors = {'G': '#5f8c53', 'B': '#447fb0', 'W': '#8b48a9', 'M': '#e02d26', 'X': '#151515'}
    for status, color in colors.items():
        points = [r['worldXZ'] for r in rows if r['status'] == status]
        if points:
            points = np.asarray(points)
            axes[1].scatter(points[:, 0], points[:, 1], s=6, c=color, marker='s', label=f'{status}: {len(points)}')
    axes[1].legend()
    for ax in axes:
        for region in regions:
            if not region.get('partitionRule'):
                continue
            corners = rect_corners(region['rect'])
            closed = np.vstack([corners, corners[0]])
            ax.plot(closed[:, 0], closed[:, 1], linewidth=.5, color='black', alpha=.4)
            center = corners.mean(0)
            ax.text(*center, region['id'].replace('R-OUT-', ''), fontsize=7, ha='center')
        ax.set_aspect('equal'); ax.set_xlabel('Shared world X (ASSUMED-SCALE)'); ax.set_ylabel('Shared world Z')
    axes[0].set_title('True geometry candidates, source heights retained')
    axes[1].set_title('Availability only: unknowns preserved, no game writes')
    fig.savefig(out/'coverage-overview.png', dpi=140); plt.close(fig)


def build(args):
    out = project_path(args.out)
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError('Output must be a new immutable directory below reference3d')
    if args.spacing <= 0 or not math.isfinite(args.spacing):
        raise ValueError('Spacing must be finite and positive')
    inputs = [PARTITION, CONTRACT, SHARED, REGISTRATION, DEFAULT_LOCK,
              ROOT/'surface-selection.json', EXTRACTED/'index.json',
              PROJECT/'tools/mondstadt/outside/terrain/terrain_source.py',
              PROJECT/'tools/mondstadt/integration/ground_sampler.py']
    original_hashes = {relative(p): digest(p) for p in inputs}
    partition, contract, reg, shared = read(PARTITION), read(CONTRACT), read(REGISTRATION), read(SHARED)
    regions = collect_regions(partition, contract)
    matrix, offset = source_world_matrix(reg, shared)
    region_scope, bounds = derive_scope(regions, matrix, offset, args.spacing)
    out.mkdir(parents=True)
    for source in inputs[:7]:
        (out/'input-snapshot').mkdir(exist_ok=True)
        (out/'input-snapshot'/source.name).write_bytes(source.read_bytes())
    build_ground(SimpleNamespace(extracted=str(EXTRACTED), selection=str(ROOT/'surface-selection.json'),
                                 registration=str(REGISTRATION), out=str(out), bounds=bounds,
                                 spacing=args.spacing, native_cell_budget=None))
    scope = {'schema': 1, 'regions': region_scope, 'sourceBoundsWithOneSamplePadding':
             dict(zip(['xmin', 'xmax', 'zmin', 'zmax'], bounds)), 'sourceSpacing': args.spacing,
             'sourceToWorld': {'rowVector': 'worldXZ = sourceXZ @ matrix2x2 + offsetXZ',
                               'matrix2x2': matrix.tolist(), 'offsetXZ': offset.tolist(),
                               'sharedTransformSha256': digest(SHARED), 'registrationSha256': digest(REGISTRATION),
                               'scaleStatus': shared['scale']['status'], 'refitted': False},
             'currentPartitionVersion': partition['partitionVersion'], 'currentContractVersion': contract['contractVersion'],
             'inputHashes': original_hashes,
             'scopeRule': 'All non-retired declared rectangles plus CITY-DOMAIN; no ownership boundary expanded.',
             'probeGrid': {'spacingWorld': 5, 'centerFormula': '(logicalIndex + 0.5) * 5',
                           'source': relative(inputs[-2]), 'actualNativeTerrainMatrixRead': False,
                           'onlyAvailabilityDiagnostic': True}}
    write_json(out/'region-scope.json', scope)
    probes = logical_probes(regions)
    new = availability(out, probes, matrix, offset)
    old = availability(ROOT/'consumer-outside-expanded-v2', probes, matrix, offset)
    index = read(out/'consumer-index.json')
    regional = []
    for region in regions:
        rid = region['id']
        regional.append({'id': rid, 'declaredRect': region['rect'],
                         'declaredNew': summarize([r for r in new if rid in r['declaredRegions']]),
                         'resolvedNew': summarize([r for r in new if rid == r['resolvedRegion']]),
                         'resolvedOldV2': summarize([r for r in old if rid == r['resolvedRegion']])})
    missing = [r for r in new if r['status'] == 'M']
    if missing:
        points = np.asarray([r['sourceXZ'] for r in missing])
        archive = np.load(out/'selected-ground-geometry.npz', allow_pickle=False)
        for category in ('base_terrain', 'geological_overlay', 'city_paved'):
            height, hits = direct_heights(archive[category+'_vertices'], archive[category+'_faces'], points)
            for i, row in enumerate(missing):
                row.setdefault('directSourceIntersection', {})[category] = {
                    'height': float(height[i]) if math.isfinite(height[i]) else None,
                    'triangleHitCount': int(hits[i])}
    report = {'schema': 1, 'statusLegend': STATUS, 'allDeclaredRegionUnion': summarize(new),
              'previousV2AtSameQueries': summarize(old), 'regions': regional,
              'sourceGrid': index['grid'], 'sourceGridStats': index['stats'],
              'missingPolicy': 'Preserve missing; exact intersections are evidence only, not filled into exported grid.',
              'newNativeTerrainPlan': False, 'heightsUnit': 'source Y, no native datum conversion',
              'nativeCapacity': {'diagnosticUnionCenters': len(new), 'limit65536': 65536,
                                 'existingNativeCellsIncluded': False,
                                 'instruction': 'DSH owner selects owned cells and applies real terrain matrix/capacity; do not import source grid as native cells.'}}
    write_json(out/'coverage-report.json', report)
    write_json(out/'world-probe-reference.json', {'schema': 1, 'statusLegend': STATUS, 'probes': new,
                                               'notTerrainCards': True, 'noSyntheticFill': True})
    write_json(out/'missing-source-evidence.json', {'schema': 1, 'samples': missing,
                                                  'zeroReplacementHeights': True})
    write_json(out/'regional-placement-evidence.json', evidence_audit(read(EXTRACTED/'index.json')))
    draw_coverage(out, new, regions)
    # Keep the consumer schema compatible; supplement rather than replace fields.
    index['completeDeclaredScope'] = {'regionScope': 'region-scope.json', 'coverageReport': 'coverage-report.json',
                                      'placementEvidence': 'regional-placement-evidence.json',
                                      'worldProbes': 'world-probe-reference.json'}
    write_json(out/'consumer-index.json', index)
    write_json(out/'PACKAGE.json', {'schema': 1, 'entry': relative(out/'consumer-index.json'),
                                   'inputsAtStart': original_hashes,
                                   'inputsAtEnd': {relative(p): digest(p) for p in inputs},
                                   'files': {relative(p): {'sha256': digest(p), 'bytes': p.stat().st_size}
                                             for p in sorted(out.rglob('*')) if p.is_file()},
                                   'scopeDevelopmentComplete': True, 'offlineBatchExecuted': False,
                                   'gameWrites': False, 'gameProcessAccess': False, 'desktopAccess': False,
                                   'terrainProducerOwner': 'original DSH outside-world',
                                   'sourceModuleOnly': True})
    print(json.dumps({'out': relative(out), 'coverage': report['allDeclaredRegionUnion'],
                      'old': report['previousV2AtSameQueries']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    parser.add_argument('--spacing', type=float, default=5.0)
    build(parser.parse_args())
