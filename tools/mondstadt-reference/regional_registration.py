"""Independent regional HLOD/official-map calibration; source-only, immutable.

prepare acquires/decodes bounded reference data. calibrate consumes explicit
semantic correspondences. No desktop, game process, or terrain writer is used.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import urllib.request
import urllib.parse

import numpy as np

from reference_cli import PROJECT, digest, project_path, write_json
from shoreline_registration import contour_segments

ROOT = PROJECT/'data/mondstadt/reference3d'
SOURCE = PROJECT/'.runtime/mondstadt/rework-20261017/reference3d'
PREPARE = SOURCE/'regional-v4'
EXTRACTED = ROOT/'extracted-final-v1'
OFFICIAL = PROJECT/'.runtime/mondstadt/rework-20261017/reference-source'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def relative(path):
    return Path(path).resolve().relative_to(PROJECT).as_posix()


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme != 'https' or u.hostname != 'act-webstatic.hoyoverse.com':
            raise ValueError('Official tile redirect leaves fixed public host')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def acquire_tiles(args):
    out = project_path(args.work)
    if not out.is_relative_to(SOURCE):
        raise ValueError('Work directory must stay inside owned source directory')
    tile_dir = out/'official-tiles'; tile_dir.mkdir(parents=True, exist_ok=True)
    original = read(OFFICIAL/'mondstadt-tiles-manifest.json')
    old = {(r['x'], r['y']): r for r in original['tiles']}
    scope = read(ROOT/'consumer-all-regions-v3/region-scope.json')
    reg = read(ROOT/'registration.json')
    b = scope['sourceBoundsWithOneSamplePadding']
    corners = np.array([[b['xmin'], b['zmin']], [b['xmin'], b['zmax']],
                        [b['xmax'], b['zmin']], [b['xmax'], b['zmax']]])
    pixels = corners @ np.asarray(reg['matrix2x2']) + np.asarray(reg['offsetPixels'])
    lo = np.floor(pixels.min(0)/256).astype(int); hi = np.floor(pixels.max(0)/256).astype(int)
    requested = [(x, y) for x in range(lo[0], hi[0]+1) for y in range(lo[1], hi[1]+1)]
    if len(requested) > 100:
        raise ValueError('Fixed 100-tile/25MiB acquisition bound exceeded')

    def get(pair):
        x, y = map(int, pair); name = f'{x}_{y}_P0.png'
        url = f'https://act-webstatic.hoyoverse.com/map_manage/map/2/{original["mapVersion"]}/{name}'
        target = tile_dir/name
        if pair in old:
            data = (OFFICIAL/old[pair]['file']).read_bytes()
            if hashlib.sha256(data).hexdigest() != old[pair]['sha256']:
                raise ValueError('Existing official tile hash changed')
            reused = True
        elif target.exists():
            data = target.read_bytes(); reused = False
        else:
            opener = urllib.request.build_opener(OfficialRedirect())
            with opener.open(url, timeout=30) as response:
                data = response.read(256*1024+1)
            if len(data) > 256*1024:
                raise ValueError('Official PNG exceeds per-tile bound')
            reused = False
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Official tile is not a PNG')
        if not target.exists():
            target.write_bytes(data)
        return {'x': x, 'y': y, 'url': url, 'path': relative(target),
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                'reusedExistingOfficialOriginal': reused}

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(get, requested))
    write_json(out/'official-tiles-lock.json', {'schema': 1, 'mapVersion': original['mapVersion'],
        'sourceManifest': relative(OFFICIAL/'mondstadt-tiles-manifest.json'),
        'sourceManifestSha256': digest(OFFICIAL/'mondstadt-tiles-manifest.json'),
        'sourceScopeSha256': digest(ROOT/'consumer-all-regions-v3/region-scope.json'),
        'tileRange': {'xmin': int(lo[0]), 'xmax': int(hi[0]), 'ymin': int(lo[1]), 'ymax': int(hi[1])},
        'requestedFromActualSourceROI': True, 'tiles': rows})
    print(json.dumps({'tiles': len(rows), 'reused': sum(r['reusedExistingOfficialOriginal'] for r in rows),
                      'bytes': sum(r['bytes'] for r in rows)}))


def mosaic(work):
    from PIL import Image
    lock = read(work/'official-tiles-lock.json'); b = lock['tileRange']
    image = np.zeros(((b['ymax']-b['ymin']+1)*256, (b['xmax']-b['xmin']+1)*256, 3), np.uint8)
    for row in lock['tiles']:
        path = PROJECT/row['path']
        if digest(path) != row['sha256']:
            raise ValueError('Changed official reference tile')
        pixels = np.asarray(Image.open(path).convert('RGB'))
        if pixels.shape != (256, 256, 3):
            raise ValueError('Unexpected official tile dimensions')
        x, y = (row['x']-b['xmin'])*256, (row['y']-b['ymin'])*256
        image[y:y+256, x:x+256] = pixels
    return image, [b['xmin']*256, (b['xmax']+1)*256, (b['ymax']+1)*256, b['ymin']*256]


def visible_contour_segments(vertices, faces, segments, height):
    from full_region_reference import direct_heights
    split = []
    for segment in segments:
        n = max(1, math.ceil(np.linalg.norm(segment[1]-segment[0])/5))
        points = segment[0]+np.arange(n+1)[:, None]/n*(segment[1]-segment[0])
        split.extend(np.stack([points[:-1], points[1:]], axis=1))
    if not split:
        return np.empty((0, 2, 2)), 0
    split = np.array(split)
    top, _ = direct_heights(vertices, faces, split.mean(1))
    keep = np.isfinite(top) & (np.abs(top-height) <= .1)
    return split[keep], int((~keep).sum())


def prepare(args):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    work = project_path(args.work)
    if (work/'contours.json').exists():
        raise ValueError('Prepared reference data are immutable; choose another work dir')
    image, extent = mosaic(work)
    index = read(EXTRACTED/'index.json'); selection = read(ROOT/'surface-selection.json')
    registration = read(ROOT/'registration.json')
    matrix, offset = np.array(registration['matrix2x2']), np.array(registration['offsetPixels'])
    result = []
    for record in index['meshSources']:
        mid = record['id']
        if record['role'] != 'regional-hlod-geometry':
            continue
        with np.load(EXTRACTED/record['geometryNpz'], allow_pickle=False) as archive:
            vertices, faces = archive['vertices'], archive['faces']
        components = {r['candidateId']: r for r in read(EXTRACTED/(mid+'-components.json'))['candidates']}
        rule = selection['meshes'][mid]['selection']
        ground_ids = [f for cid in rule['base-terrain']+rule.get('geological-overlay', [])
                      for f in components[cid]['faceIds']]
        ground_faces = faces[ground_ids]
        layers = []
        for cid in rule['water-candidate']:
            component = components[cid]
            ymin, ymax = component['heightRange']
            triangle = vertices[faces[component['faceIds']]]
            area = np.linalg.norm(np.cross(triangle[:, 1]-triangle[:, 0], triangle[:, 2]-triangle[:, 0]), axis=1)/2
            flat = np.ptp(triangle[:, :, 1], axis=1) <= .01
            plane_codes = np.round(triangle[:, :, 1].mean(1), 2)
            planes = []
            for plane in sorted(set(plane_codes[flat])):
                choose = flat & (plane_codes == plane)
                if area[choose].sum() >= 1000:
                    planes.append((float(np.average(triangle[choose, :, 1].mean(1), weights=area[choose])),
                                   triangle[choose].reshape(-1, 3), int(choose.sum())))
            if not planes:
                layers.append({'componentId': cid, 'heightRange': [ymin, ymax], 'planeAvailable': False,
                               'reason': 'no horizontal water-candidate triangle cluster with area at least 1000; no invented plane'})
                continue
            for height, plane_vertices, plane_faces in planes:
                segments = contour_segments(vertices, ground_faces, height)
                low, high = plane_vertices.min(0)[[0, 2]], plane_vertices.max(0)[[0, 2]]
                # Broad AABB filter only; individual curves remain shoreline candidates.
                if len(segments):
                    keep = np.all(segments.max(1) >= low-15, axis=1) & np.all(segments.min(1) <= high+15, axis=1)
                    segments = segments[keep]
                hidden = 0
                if args.visible_top_only:
                    segments, hidden = visible_contour_segments(vertices, ground_faces, segments, height)
                layers.append({'componentId': cid, 'heightRange': [ymin, ymax], 'planeAvailable': True,
                               'planeY': height, 'sourcePlaneFaceCount': plane_faces,
                               'segmentsXZ': segments.tolist(), 'segmentCount': len(segments),
                               'visibleTopOnly': args.visible_top_only, 'hiddenSubsegmentsExcluded': hidden,
                               'sourceWaterAabbXZ': [low.tolist(), high.tolist()]})
        result.append({'mesh': mid, 'sourceSha256': record['sourceSha256'], 'waterContours': layers})
        lo, hi = np.array(record['aabbMin'])[[0, 2]], np.array(record['aabbMax'])[[0, 2]]
        pts = np.array([[lo[0], lo[1]], [lo[0], hi[1]], [hi[0], lo[1]], [hi[0], hi[1]]]) @ matrix+offset
        xmin, ymin = np.maximum(pts.min(0)-30, [extent[0], extent[3]])
        xmax, ymax = np.minimum(pts.max(0)+30, [extent[1], extent[2]])
        fig, axes = plt.subplots(1, 2, figsize=(19, 10), constrained_layout=True)
        axes[0].imshow(image, extent=extent)
        axes[1].set_facecolor('#eee9dd')
        for layer in layers:
            if not layer.get('segmentCount'):
                continue
            pixel = np.array(layer['segmentsXZ']) @ matrix+offset
            label = f"water {layer['componentId']} Y={layer['planeY']:.2f}"
            for ax in axes:
                ax.add_collection(LineCollection(pixel, linewidths=1, label=label))
            center = pixel.reshape(-1, 2).mean(0)
            axes[1].text(*center, str(layer['componentId']), fontsize=9)
        for ax in axes:
            ax.set_xlim(xmin, xmax); ax.set_ylim(ymax, ymin); ax.set_aspect('equal')
            ax.set_xticks(np.arange(math.ceil(xmin/100)*100, xmax, 100))
            ax.set_yticks(np.arange(math.ceil(ymin/100)*100, ymax, 100))
            ax.tick_params(axis='x', labelrotation=90); ax.grid(alpha=.3)
        axes[0].set_title(mid+' official original + upstream-position candidate contours')
        axes[1].set_title('Source geometry alone; no fit applied'); axes[1].legend(fontsize=8)
        fig.savefig(work/(mid+'-before.png'), dpi=150); plt.close(fig)
    write_json(work/'contours.json', {'schema': 1, 'sourceRegistrationSha256': digest(ROOT/'registration.json'),
        'selectionSha256': digest(ROOT/'surface-selection.json'), 'officialTileLockSha256': digest(work/'official-tiles-lock.json'),
        'meshes': result, 'meaning': 'Real ground/real flat-water-height intersections; semantic shoreline identification is still required.'})
    print(json.dumps({'meshes': len(result), 'work': relative(work)}))


def water_edge(image):
    """Declared color rule for this official raster, not a semantic game mask."""
    from scipy.ndimage import binary_erosion, distance_transform_edt, label
    r, g, b = np.moveaxis(image.astype(float), -1, 0)
    mask = (g > r*1.2+8) & (b > r*1.25+8) & (b > g*.93) & (b < g*1.6) & (b > 75) & (g < 210)
    labels, _ = label(mask)
    sizes = np.bincount(labels.ravel()); sizes[0] = 0
    mask &= sizes[labels] >= 30
    edge = mask ^ binary_erosion(mask)
    distance = distance_transform_edt(~edge)
    # Cyan map-extent borders and black unrevealed map are not coastline evidence.
    dark_labels, _ = label(image.max(2) < 55)
    dark_sizes = np.bincount(dark_labels.ravel()); dark_sizes[0] = 0
    unknown = (dark_sizes[dark_labels] >= 10000) | ((g > 200) & (b > 200) & (r < 100))
    known_distance = distance_transform_edt(~unknown)
    return mask, edge, distance, known_distance


def contour_points(layers, matrix, offset, spacing=8):
    points, groups = [], []
    for layer_index, layer in enumerate(layers):
        if not layer.get('segmentCount'):
            continue
        segments = np.array(layer['segmentsXZ']) @ matrix+offset
        for segment in segments:
            length = np.linalg.norm(segment[1]-segment[0])
            n = max(1, math.ceil(length/spacing))
            for t in (np.arange(n)+.5)/n:
                points.append(segment[0]+t*(segment[1]-segment[0])); groups.append(layer_index)
    return np.array(points), np.array(groups)


def optimize_translation(points, distance, search=120):
    """Trimmed shoreline distance proposal; no acceptance or grade promotion."""
    if len(points) < 15:
        return None
    def loss(delta):
        query = np.rint(points+delta).astype(int)
        values = distance[query[:, 1], query[:, 0]]
        # Coarse HLOD exposes false contours and map artwork moves some banks.
        # Keep the worst tails visible in output, never call trimmed fit proof.
        order = np.sort(values)
        return float(np.mean(order[:max(1, int(len(order)*.7))]))
    candidates = [(loss(np.array([x, y])), x, y) for x in range(-search, search+1, 8)
                  for y in range(-search, search+1, 8)]
    best = min(candidates)
    fine = [(loss(np.array([x, y])), x, y) for x in range(best[1]-8, best[1]+9)
            for y in range(best[2]-8, best[2]+9)]
    score, x, y = min(fine)
    def stats(delta):
        q = np.rint(points+delta).astype(int); values = distance[q[:, 1], q[:, 0]]
        return {'median': float(np.median(values)), 'p90': float(np.percentile(values, 90)),
                'mean': float(np.mean(values)), 'within5px': int((values <= 5).sum()), 'samples': len(values)}
    return {'pixelTranslationCandidate': [x, y], 'trimmedLoss': score,
            'before': stats([0, 0]), 'after': stats([x, y]), 'gradePromotion': False}


def proposals(args):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    work = project_path(args.work)
    target = work/args.proposals_name
    if target.exists():
        raise ValueError('Use a new immutable work/proposal directory')
    target.mkdir()
    image, extent = mosaic(work)
    mask, edge, distance, known = water_edge(image)
    reg = read(ROOT/'registration.json'); matrix, offset = np.array(reg['matrix2x2']), np.array(reg['offsetPixels'])
    origin = np.array([extent[0], extent[3]])
    results = []
    data = read(work/'contours.json')
    for row in data['meshes']:
        points, groups = contour_points(row['waterContours'], matrix, offset)
        local = points-origin
        safe = (local[:, 0] >= 140) & (local[:, 1] >= 140) & (local[:, 0] < image.shape[1]-140) & (local[:, 1] < image.shape[0]-140)
        eligible = np.nonzero(safe)[0]
        integer = np.rint(local[eligible]).astype(int)
        # At least 130px clear of unknown artwork prevents optimizer exploiting
        # unavailable map pixels. This can correctly leave a block underconstrained.
        eligible = eligible[known[integer[:, 1], integer[:, 0]] > 130]
        fit = optimize_translation(local[eligible], distance)
        results.append({'mesh': row['mesh'], 'totalSourceContourSamples': len(points),
                        'eligibleIndependentMapSamples': len(eligible), 'proposal': fit})
        if fit is None:
            continue
        delta = np.array(fit['pixelTranslationCandidate'])
        fig, axes = plt.subplots(1, 2, figsize=(18, 10), constrained_layout=True)
        p = points[eligible]
        low, high = p.min(0)-30, p.max(0)+30
        for ax, move in zip(axes, (np.zeros(2), delta)):
            ax.imshow(image, extent=extent)
            for layer in row['waterContours']:
                if layer.get('segmentCount'):
                    pixel = np.array(layer['segmentsXZ']) @ matrix+offset+move
                    ax.add_collection(LineCollection(pixel, colors='#ff341c', linewidths=.8))
            ax.set_xlim(low[0]+min(0, delta[0]), high[0]+max(0, delta[0]))
            ax.set_ylim(high[1]+max(0, delta[1]), low[1]+min(0, delta[1]))
            ax.set_aspect('equal'); ax.grid(alpha=.2); ax.tick_params(axis='x', labelrotation=90)
        axes[0].set_title(row['mesh']+' upstream placement')
        axes[1].set_title(f'UNACCEPTED shoreline proposal {delta.tolist()} px')
        fig.savefig(target/(row['mesh']+'.png'), dpi=160); plt.close(fig)
    write_json(target/'proposals.json', {'schema': 1, 'algorithm': 'Trimmed source shore to official color-mask boundary translation; candidate only',
        'oldRegistrationUnchanged': True, 'noGradePromoted': True, 'rows': results})
    print(json.dumps(results))


def stitched_features(segments, matrix, tolerance=5):
    """Original contour endpoints retained after connected-line simplification."""
    points = np.asarray(segments).reshape(-1, 2)
    _, first, inverse = np.unique(np.round(points, 4), axis=0, return_index=True, return_inverse=True)
    graph = {i: set() for i in range(len(first))}
    edges = set()
    for a, b in inverse.reshape(-1, 2):
        if a != b:
            graph[a].add(b); graph[b].add(a); edges.add(tuple(sorted((int(a), int(b)))))
    chains = []
    starts = sorted(graph, key=lambda i: len(graph[i]) == 2)
    for start in starts:
        while any(tuple(sorted((start, n))) in edges for n in graph[start]):
            chain = [start]; current = start
            while True:
                choices = [n for n in graph[current] if tuple(sorted((current, n))) in edges]
                if not choices:
                    break
                nxt = min(choices); edges.remove(tuple(sorted((current, nxt)))); chain.append(nxt); current = nxt
                if current == start or len(graph[current]) != 2:
                    break
            chains.append(chain)
    pixel = points[first] @ matrix
    def simplify(ids):
        if len(ids) <= 2:
            return ids
        p = pixel[ids]; a, b = p[0], p[-1]; delta = b-a; length = np.linalg.norm(delta)
        distances = np.linalg.norm(p-a, axis=1) if length < 1e-9 else np.abs(delta[0]*(p[:, 1]-a[1])-delta[1]*(p[:, 0]-a[0]))/length
        i = int(np.argmax(distances))
        if distances[i] <= tolerance:
            return [ids[0], ids[-1]]
        return simplify(ids[:i+1])[:-1]+simplify(ids[i:])
    retained = sorted({int(first[i]) for chain in chains for i in simplify(chain)})
    return retained


def feature_panels(args):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    work = project_path(args.work); target = work/'feature-panels'
    if target.exists():
        raise ValueError('Feature panels already exist')
    target.mkdir()
    image, extent = mosaic(work)
    reg = read(ROOT/'registration.json'); m, o = np.array(reg['matrix2x2']), np.array(reg['offsetPixels'])
    windows = {'hlod-1_-1': [23400, 23950, 9290, 9720],
               'hlod-1_-2': [24900, 25550, 9280, 9820],
               'hlod-2_-2': [24450, 25380, 8480, 9220],
               'hlod-1_0': [23040, 23500, 9340, 10230],
               'hlod-2_0': [23100, 23550, 8640, 8870]}
    rows = []
    for row in read(work/'contours.json')['meshes']:
        if row['mesh'] not in windows:
            continue
        window = windows[row['mesh']]; features = []
        for layer_index, layer in enumerate(row['waterContours']):
            if not layer.get('segmentCount'):
                continue
            segments = np.array(layer['segmentsXZ']); points = segments.reshape(-1, 2)
            for endpoint in stitched_features(segments, m):
                pixel = points[endpoint] @ m+o
                if window[0] <= pixel[0] <= window[1] and window[2] <= pixel[1] <= window[3]:
                    features.append({'featureId': len(features), 'layerIndex': layer_index,
                                     'waterComponentId': layer['componentId'], 'endpointIndex': endpoint,
                                     'sourceXZ': points[endpoint].tolist(), 'predictedPixel': pixel.tolist()})
        fig, axes = plt.subplots(1, 2, figsize=(19, 13), constrained_layout=True)
        axes[0].imshow(image, extent=extent)
        axes[1].set_facecolor('#eee9dd')
        for layer in row['waterContours']:
            if layer.get('segmentCount'):
                pixel = np.array(layer['segmentsXZ']) @ m+o
                axes[1].add_collection(LineCollection(pixel, colors='#146a9e', linewidths=1))
        for feature in features:
            point = feature['predictedPixel']
            axes[1].plot(*point, '.', color='red', markersize=3)
            axes[1].annotate(str(feature['featureId']), point, xytext=(2, 2), textcoords='offset points', fontsize=7)
        for ax in axes:
            ax.set_xlim(window[:2]); ax.set_ylim(window[3], window[2]); ax.set_aspect('equal')
            ax.set_xticks(np.arange(math.ceil(window[0]/50)*50, window[1], 50))
            ax.set_yticks(np.arange(math.ceil(window[2]/50)*50, window[3], 50))
            ax.tick_params(axis='x', labelrotation=90); ax.grid(alpha=.3)
        axes[0].set_title(row['mesh']+' official map only; independent target observations')
        axes[1].set_title('Original source endpoint IDs (no fitting, simplified for labels)')
        fig.savefig(target/(row['mesh']+'.png'), dpi=170); plt.close(fig)
        rows.append({'mesh': row['mesh'], 'window': window, 'features': features})
    write_json(target/'features.json', {'schema': 1, 'rows': rows, 'simplificationPixelTolerance': 5,
                                      'selectedCoordinatesRemainOriginalContourEndpoints': True})
    print(json.dumps({'panels': len(rows), 'features': [len(r['features']) for r in rows]}))


def fit_translation(source, target, matrix, offset, uncertainty, minimum_controls=4):
    """Independent named correspondences; never optimize away bad observations."""
    from geometry import convex_hull, fit_registration
    source, target = np.asarray(source, float).reshape(-1, 2), np.asarray(target, float).reshape(-1, 2)
    if len(source) != len(target) or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError('Invalid correspondence coordinates')
    if len(source) < 2:
        return {'accepted': False, 'rejectionReasons': ['insufficient-independent-controls'], 'controlCount': len(source)}
    predicted = source @ matrix+offset
    differences = target-predicted
    translation = differences.mean(0)
    residual = np.linalg.norm(predicted+translation-target, axis=1)
    before = np.linalg.norm(predicted-target, axis=1)
    loo = [float(np.linalg.norm(predicted[i]+np.delete(differences, i, axis=0).mean(0)-target[i])) for i in range(len(source))]
    hull = np.asarray(convex_hull(predicted))
    area = abs(float(np.dot(hull[:, 0], np.roll(hull[:, 1], 1))-np.dot(hull[:, 1], np.roll(hull[:, 0], 1))))/2 if len(hull) >= 3 else 0
    rmse = float(np.sqrt(np.mean(residual**2)))
    reasons = []
    if len(source) < minimum_controls: reasons.append('fewer-than-four-independent-controls')
    if area < 5000: reasons.append('control-hull-too-narrow')
    if max(uncertainty) > 5: reasons.append('feature-identification-uncertainty-over-5px')
    if rmse > 5: reasons.append('translation-rmse-over-5px')
    if residual.max() > 8: reasons.append('translation-max-residual-over-8px')
    if max(loo) > 10: reasons.append('leave-one-out-over-10px')
    similarity = None
    if len(source) >= 3 and area > 1:
        similarity = fit_registration([{'id': str(i), 'sourceXZ': s.tolist(), 'officialGlobalPixel': t.tolist()}
                                       for i, (s, t) in enumerate(zip(source, target))])
    return {'model': 'translation on frozen city similarity (scale/rotation not refitted)', 'controlCount': len(source),
            'pixelTranslationCandidate': translation.tolist(), 'sourceTranslationCandidateXZ': (translation @ np.linalg.inv(matrix)).tolist(),
            'matrix2x2': matrix.tolist(), 'candidateOffsetPixels': (offset+translation).tolist(),
            'beforeResidualPixels': before.tolist(), 'residualPixels': residual.tolist(),
            'rmsePixels': rmse, 'maxResidualPixels': float(residual.max()), 'leaveOneOutPixels': loo,
            'maxLeaveOneOutPixels': max(loo), 'controlHullAreaPixels2': area,
            'estimatedIdentificationUncertaintyPixels': list(uncertainty),
            'unconstrainedSimilarityDiagnosticOnly': similarity,
            'accepted': not reasons, 'rejectionReasons': reasons,
            'nativeCoordinateSurvey': False}


def overlap_report(index, selections, matrix, offset, candidate_shifts):
    """Actual selected-mesh vertical overlap, before and after candidate shifts.

    Different HLOD cuts can create gaps even after sound registration. Report the
    empty samples and distributions; this is not a walkability or collision test.
    """
    from full_region_reference import direct_heights
    meshes = {}
    for record in index['meshSources']:
        mid = record['id']
        if record['role'] != 'regional-hlod-geometry': continue
        archive = np.load(EXTRACTED/record['geometryNpz'], allow_pickle=False)
        cs = {r['candidateId']: r for r in read(EXTRACTED/(mid+'-components.json'))['candidates']}
        faces = [f for cid in selections['meshes'][mid]['selection']['base-terrain'] for f in cs[cid]['faceIds']]
        vertices = archive['vertices'].copy(); pixels = vertices[:, [0, 2]] @ matrix+offset
        vertices[:, 0], vertices[:, 2] = pixels[:, 0], pixels[:, 1]
        used = vertices[np.unique(archive['faces'][faces])][:, [0, 2]]
        meshes[mid] = (vertices, archive['faces'][faces], used.min(0), used.max(0))
    rows = []
    for a in sorted(meshes):
        for b in sorted(meshes):
            if a >= b: continue
            first, second = tuple(map(int, a.removeprefix('hlod-').split('_'))), tuple(map(int, b.removeprefix('hlod-').split('_')))
            if abs(first[0]-second[0])+abs(first[1]-second[1]) != 1: continue
            results = {}
            for state in ('before', 'candidate'):
                shifts = [np.zeros(2), np.zeros(2)] if state == 'before' else [np.asarray(candidate_shifts.get(a, [0, 0])), np.asarray(candidate_shifts.get(b, [0, 0]))]
                va, fa, loa, hia = meshes[a]; vb, fb, lob, hib = meshes[b]
                low, high = np.maximum(loa+shifts[0], lob+shifts[1]), np.minimum(hia+shifts[0], hib+shifts[1])
                if np.any(high <= low):
                    results[state] = {'bboxOverlap': False, 'commonVerticalSamples': 0, 'axisGapPixels': np.maximum(0, low-high).tolist()}; continue
                x, y = np.arange(low[0]+2, high[0], 16), np.arange(low[1]+2, high[1], 16)
                points = np.stack(np.meshgrid(x, y), axis=-1).reshape(-1, 2)
                ha, _ = direct_heights(va, fa, points-shifts[0]); hb, _ = direct_heights(vb, fb, points-shifts[1])
                both = np.isfinite(ha) & np.isfinite(hb)
                delta = np.abs(ha[both]-hb[both])
                results[state] = {'bboxOverlap': True, 'gridSpacingPixels': 16, 'queried': len(points),
                                  'commonVerticalSamples': int(both.sum()), 'neitherHasSource': int((~np.isfinite(ha) & ~np.isfinite(hb)).sum()),
                                  'heightDifferenceSourceUnits': None if not len(delta) else {
                                      'median': float(np.median(delta)), 'p95': float(np.percentile(delta, 95)), 'max': float(delta.max())}}
            rows.append({'meshes': [a, b], **results})
    return {'schema': 1, 'pairs': rows, 'candidateShiftsAreNotApplied': True,
            'heightDatum': 'raw source Y; only base-terrain components, no smoothing or infill'}


def calibrate(args):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    out = project_path(args.out); work = project_path(args.work)
    if not out.is_relative_to(ROOT) or out.exists():
        raise ValueError('Calibration output must be a new immutable reference directory')
    observations_path = project_path(args.observations)
    observations = read(observations_path)
    feature_path = project_path(observations['featureSource'])
    features = {r['mesh']: {p['featureId']: p for p in r['features']} for r in read(feature_path)['rows']}
    reg = read(ROOT/'registration.json'); matrix, offset = np.asarray(reg['matrix2x2']), np.asarray(reg['offsetPixels'])
    index = read(EXTRACTED/'index.json'); selection = read(ROOT/'surface-selection.json')
    image, extent = mosaic(work); rows = []; shifts = {}
    contours = {r['mesh']: r for r in read(work/'contours.json')['meshes']}
    out.mkdir()
    for region in observations['regions']:
        mid = region['mesh']; controls = []
        for observation in region['controls']:
            feature = features[mid][observation['featureId']]
            target = observation['officialGlobalPixel']
            if not (extent[0] <= target[0] < extent[1] and extent[3] <= target[1] < extent[2]):
                raise ValueError('Control target is outside acquired official originals')
            controls.append(dict(feature, **observation))
        usable = [c for c in controls if c['correspondenceStatus'] == 'identified-coarse-feature']
        fitted = fit_translation([c['sourceXZ'] for c in usable], [c['officialGlobalPixel'] for c in usable],
                                 matrix, offset, [c['estimatedPixelUncertainty'] for c in usable])
        # Unknown semantic matches are retained for review, never silently included.
        if 'pixelTranslationCandidate' in fitted:
            shifts[mid] = fitted['pixelTranslationCandidate']
        rows.append({'mesh': mid, 'previousAlignmentGrade': 3, 'recommendedAlignmentGrade': 4 if fitted['accepted'] else 3,
                     'controls': controls, 'excludedAmbiguousControls': len(controls)-len(usable),
                     'fit': fitted, 'specificLimitations': region['specificLimitations'],
                     'sourceGeometryChanged': False})
        fig, axes = plt.subplots(1, 2, figsize=(18, 10), constrained_layout=True)
        plot_points = np.array([c['predictedPixel'] for c in controls]+[c['officialGlobalPixel'] for c in controls])
        lo, hi = plot_points.min(0)-50, plot_points.max(0)+50
        delta = np.array(fitted.get('pixelTranslationCandidate', [0, 0]))
        for ax, move in zip(axes, (np.zeros(2), delta)):
            ax.imshow(image, extent=extent)
            for layer in contours[mid]['waterContours']:
                if layer.get('segmentCount'):
                    pix = np.array(layer['segmentsXZ']) @ matrix+offset+move
                    ax.add_collection(LineCollection(pix, colors='red', linewidths=.7))
            for i, c in enumerate(controls):
                src = np.array(c['predictedPixel'])+move; dst = c['officialGlobalPixel']
                ax.plot([src[0], dst[0]], [src[1], dst[1]], color='black', linewidth=.6)
                ax.plot(*dst, 'o', markersize=4, markerfacecolor='none', markeredgecolor='blue')
                ax.annotate(str(i), dst, xytext=(3, 3), textcoords='offset points', fontsize=8)
            ax.set_xlim(lo[0]+min(0, delta[0]), hi[0]+max(0, delta[0])); ax.set_ylim(hi[1]+max(0, delta[1]), lo[1]+min(0, delta[1]))
            ax.set_aspect('equal'); ax.tick_params(axis='x', labelrotation=90); ax.grid(alpha=.2)
        axes[0].set_title(mid+' old placement / independently named observations')
        axes[1].set_title('Candidate translation; '+('eligible map reference' if fitted['accepted'] else 'REJECTED for precise registration'))
        fig.savefig(out/(mid+'-control-review.png'), dpi=160); plt.close(fig)
    overlaps = overlap_report(index, selection, matrix, offset, shifts)
    write_json(out/'overlap-report.json', overlaps)
    accepted = [r['mesh'] for r in rows if r['fit']['accepted']]
    report = {'schema': 1, 'scope': 'five regional blocks lacking independent map control evidence',
              'oldGlobalRegistrationSha256': digest(ROOT/'registration.json'), 'oldV3PackageSha256': digest(ROOT/'consumer-all-regions-v3/PACKAGE.json'),
              'oldRegistrationUnchanged': True, 'cityAndBlock2minus1Preserved': True,
              'thresholdsPixels': {'minimumControls': 4, 'maximumIdentificationUncertainty': 5, 'rmse': 5, 'maxResidual': 8, 'leaveOneOutMax': 10},
              'method': 'Named original-geometry endpoint to independently visually read original map; all discrepancies retained. Translation preserves global scale/rotation.',
              'rows': rows, 'acceptedBlocks': accepted,
              'recommendation': 'Only acceptedBlocks eligible for owner review and whole-map rebuild; candidate corrections are not silently applied.',
              'actualNativeRegistrationVerified': False, 'gameWrites': False, 'sourceToolComplete': True}
    write_json(out/'regional-registration.json', report)
    write_json(out/'delta-manifest.json', {'schema': 1, 'oldPackage': relative(ROOT/'consumer-all-regions-v3/PACKAGE.json'),
        'adoptedChanges': [{'mesh': r['mesh'], 'sourceTranslationXZ': r['fit']['sourceTranslationCandidateXZ'],
                           'pixelTranslation': r['fit']['pixelTranslationCandidate']} for r in rows if r['fit']['accepted']],
        'rejectedCandidates': [{'mesh': r['mesh'], 'fit': r['fit']} for r in rows if not r['fit']['accepted']],
        'ownerRebuildRequiredIfAdopted': bool(accepted), 'existingTerrainAndEntityPositionsModified': False,
        'unchangedRecommendedSourceEntry': None if accepted else relative(ROOT/'consumer-all-regions-v3/consumer-index.json')})
    # Fixed upstream source inventory is evidence of what is actually present,
    # not a claim that some undiscovered full-resolution asset cannot exist.
    manifest_path = SOURCE/'source/all_hlod_manifest.json'; manifest = read(manifest_path)
    inventory = []
    for category, entries in manifest.items():
        for entry in entries:
            name = entry['name'].lower()
            if any(word in name for word in ('mengde', 'bridge', 'church', 'cathedral')):
                inventory.append({'category': category, **entry})
    write_json(out/'fidelity-and-source-gaps.json', {'schema': 1, 'fixedManifest': relative(manifest_path),
        'fixedManifestSha256': digest(manifest_path), 'matchingEntries': inventory,
        'sixRegionalTerrainEntriesInAndroidManifest': {r['id']: read(SOURCE/'source/android_manifest.json')['terrain'].get(r['id'].removeprefix('hlod-')) for r in index['meshSources'] if r['role'] == 'regional-hlod-geometry'},
        'fullResolutionBridgeOrCathedralEstablished': False,
        'gapMeaning': 'Pinned inventory contains merged Mondstadt HLOD LOD0/1/2 only for named Mondstadt; no independent full-resolution bridge/cathedral or terrain entry established.',
        'sourceUnitsAreNotNativeMeters': True, 'HLODGeometryNotCollisionGeometry': True,
        'roadControls': 'Not fabricated: original base-terrain UVs inspected for 1_-1 were all zero, so the separate terrain texture is not a verified UV-to-mesh road-coordinate source.',
        'automaticFalseMatchRetained': relative(PREPARE/'coast-proposals-v2/proposals.json'),
        'automaticFalseMatchExample': '2_0 shoreline-distance optimizer [-66,-123] px moves a pond onto the Stormterror central tower. Low image-distance score is not a valid landmark correspondence.',
        'additionalEvidenceNeeded': ['higher-detail independently positioned terrain mesh or surveyed per-block transforms', 'at least four semantically unambiguous source/map features per block with <=5px identification uncertainty', 'independent source road UV mapping or named landmark coordinates, not just AABB centering']})
    (out/'control-observations.json').write_bytes(observations_path.read_bytes())
    write_json(out/'PACKAGE.json', {'schema': 1, 'entry': relative(out/'regional-registration.json'),
        'inputs': {relative(p): digest(p) for p in [observations_path, feature_path, ROOT/'registration.json', ROOT/'surface-selection.json', work/'contours.json', work/'official-tiles-lock.json']},
        'files': {relative(p): {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()},
        'moduleDevelopmentComplete': True, 'offlineBatchNotYetRunAtFreeze': True, 'gameWrites': False, 'desktopAccess': False})
    print(json.dumps({'out': relative(out), 'accepted': accepted, 'rows': [{k: r['fit'].get(k) for k in ('accepted', 'controlCount', 'rmsePixels', 'maxResidualPixels', 'maxLeaveOneOutPixels', 'rejectionReasons')} | {'mesh': r['mesh']} for r in rows]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['acquire-tiles', 'prepare', 'proposals', 'feature-panels', 'calibrate'])
    parser.add_argument('--work', default=str(PREPARE))
    parser.add_argument('--proposals-name', default='coast-proposals-v2')
    parser.add_argument('--visible-top-only', action='store_true')
    parser.add_argument('--observations', default=str(PREPARE/'control-observations.json'))
    parser.add_argument('--out', default=str(ROOT/'regional-calibration-v4'))
    args = parser.parse_args()
    {'acquire-tiles': acquire_tiles, 'prepare': prepare, 'proposals': proposals, 'feature-panels': feature_panels, 'calibrate': calibrate}[args.command](args)
