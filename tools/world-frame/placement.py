"""One common XYZ translation for a complete map, without changing terrain owners.

Pure offline compilation. Production input is the existing independently verified
catalog receipt. No game access, dispatch, save, or edits to source artifacts.
The v1 compiler remains unchanged. Both use the same production native converter.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

import world_frame as wf

SCHEMA = 'world-placement-compilation-v2'
POLICY = 'nearest-preferred-translation-in-native-code-coordinates'
DEPENDENCIES = (
    Path(__file__), wf.HERE / 'world_frame.py',
    wf.TERRAIN / 'terrain_calibration.py', wf.TERRAIN / 'terrain_model.py',
)


def source_hashes():
    return {str(p.relative_to(wf.ROOT)).replace('\\', '/'): wf.sha_bytes(p.read_bytes())
            for p in DEPENDENCIES}


def _delta_codes(matrix, translation):
    # Invert only the linear part: large matrix origins must not cancel small deltas.
    linear = list(matrix)
    linear[12:15] = [0., 0., 0.]
    local = wf.tc.inverse_transform(linear, translation)
    result = [local[i] / wf.STEPS[i] for i in range(3)]
    wf.require(all(math.isfinite(v) for v in result), 'PLACEMENT_DELTA_NONFINITE')
    return result


def _world_delta(matrix, codes):
    local = [codes[i] * wf.STEPS[i] for i in range(3)]
    return [sum(matrix[4 * j + i] * local[j] for j in range(3)) for i in range(3)]


def _solve(frame, points, preferred, requested):
    limits, matrix = frame['limits'], frame['matrix']
    lower, upper = [-math.inf] * 3, [math.inf] * 3
    lower_by, upper_by, before = [None] * 3, [None] * 3, []
    roundtrips = []
    for point in points:
        local = wf.tc.inverse_transform(matrix, point['worldTop'])
        codes = [local[i] / wf.STEPS[i] for i in range(3)]
        wf.require(all(math.isfinite(v) for v in codes), 'CONTINUOUS_CODE_NONFINITE',
                   sourceId=point['sourceId'])
        before.append(codes)
        roundtrips.append(wf._roundtrip_evidence(frame, point))
        for i, bounds in enumerate(limits):
            lo, hi = bounds[0] - codes[i], bounds[1] - codes[i]
            if lo > lower[i]:
                lower[i], lower_by[i] = lo, point['sourceId']
            if hi < upper[i]:
                upper[i], upper_by[i] = hi, point['sourceId']
    intervals = [dict(axis=wf.AXES[i], minimum=lower[i], maximum=upper[i],
                      lowerSourceId=lower_by[i], upperSourceId=upper_by[i]) for i in range(3)]
    wf.require(all(lower[i] <= upper[i] for i in range(3)), 'NO_COMMON_MAP_TRANSLATION',
               intervals=intervals,
               requiredAction='The complete source span exceeds the native domain; no source was cropped or scaled.')
    preference = _delta_codes(matrix, preferred)
    chosen = (_delta_codes(matrix, requested) if requested is not None else
              [max(lower[i], min(upper[i], preference[i])) for i in range(3)])
    # A supplied translation is never silently adjusted. The tiny allowance is
    # solely inverse-matrix roundoff at an already selected interval endpoint.
    excess = []
    for i in range(3):
        amount = max(0., lower[i] - chosen[i], chosen[i] - upper[i])
        allowance = 32 * math.ulp(max(1., abs(lower[i]), abs(upper[i])))
        wf.require(amount <= allowance, 'REQUESTED_MAP_TRANSLATION_OUTSIDE_DOMAIN',
                   axis=wf.AXES[i], requestedCodeDelta=chosen[i], interval=intervals[i])
        excess.append(amount)
    translation = list(requested) if requested is not None else _world_delta(matrix, chosen)
    wf.vector(translation, 'worldTranslation')
    return dict(policy=POLICY, preferredWorldTranslation=preferred,
                preferredNativeCodeDelta=preference, selectedNativeCodeDelta=chosen,
                intervals=intervals, requestedBoundaryArithmeticExcess=excess,
                worldTranslation=translation), before, roundtrips


def _compile(frame, document, quantization, preferred_translation, world_translation):
    wf.require(quantization in ('exact', 'nearest'), 'EXPLICIT_QUANTIZATION_EXACT_OR_NEAREST')
    wf.require(type(document) is dict, 'WORLD_POINT_DOCUMENT_SCHEMA')
    wf.canonical(document)
    original = copy.deepcopy(document)
    sources = wf._source_bindings(original)
    points = wf._points(original, sources)
    preferred = wf.vector(preferred_translation, 'preferredTranslation')
    requested = None if world_translation is None else wf.vector(world_translation, 'worldTranslation')
    hashes = source_hashes()
    solution, before, roundtrips = _solve(frame, points, preferred, requested)
    translation = solution['worldTranslation']

    # Use the same production converter, without invoking v1's Y-only interval
    # solver a second time. A shear can turn a few ULP of inverse roundoff at an
    # exact boundary into contradictory Y intervals. Validate the final 3D domain
    # directly and retain the bounded arithmetic excess; never adjust points.
    mapped, columns, maxima = [], {}, [0., 0., 0.]
    for index, point in enumerate(points):
        after = [point['worldTop'][i] + translation[i] for i in range(3)]
        wf.require(all(math.isfinite(v) for v in after), 'SHIFTED_WORLD_POINT_NONFINITE',
                   sourceId=point['sourceId'])
        try:
            converted = wf.tc.world_to_cell(frame['source'], after, quantization)
        except (ValueError, KeyError, OverflowError) as error:
            raise wf.FrameError('POINT_QUANTIZATION_REJECTED', sourceId=point['sourceId'],
                                quantization=quantization, afterWorld=after, error=str(error)) from error
        cell = {axis: converted[axis] for axis in wf.AXES}
        slop = []
        for i, (axis, bounds) in enumerate(zip(wf.AXES, frame['limits'])):
            code = converted['continuousCodes'][i]
            wf.require(bounds[0] <= cell[axis] <= bounds[1], 'QUANTIZED_CELL_OUT_OF_RANGE',
                       sourceId=point['sourceId'], axis=axis)
            noise = max(0., bounds[0] - code, code - bounds[1])
            allowed = 32 * math.ulp(max(1., abs(code), float(bounds[1])))
            wf.require(noise <= allowed, 'NUMERIC_PLACEMENT_DOMAIN_VIOLATION',
                       sourceId=point['sourceId'], axis=axis, amount=noise)
            slop.append(noise)
        key = (cell['x'], cell['z'])
        columns.setdefault(key, []).append(dict(sourceId=point['sourceId'], height=cell['height'],
                                                provenance=point['provenance'], sourceWorld=point['worldTop']))
        maxima = [max(maxima[i], abs(converted['residualWorld'][i])) for i in range(3)]
        mapped.append(dict(sourceId=point['sourceId'], sourceWorld=point['worldTop'], afterWorld=after,
            provenance=point['provenance'], sourceArtifactSha256=sources[point['provenance']['artifactId']]['sha256'],
            beforeContinuousCodes=before[index], afterContinuousCodes=converted['continuousCodes'],
            cell=cell, reconstructedWorldTop=converted['worldTop'], residualWorld=converted['residualWorld'],
            inputKind=point['inputKind'], originalGridRoundtrip=roundtrips[index],
            boundaryArithmeticExcess=slop, residualMeaning=('native grid re-encoding' if roundtrips[index] else
                                                          'source-world to native-grid quantization')))
    conflicts = [dict(cell=dict(x=key[0], z=key[1]), sources=rows)
                 for key, rows in sorted(columns.items()) if len(rows) > 1]
    wf.require(not conflicts, 'SOURCE_POINTS_COLLAPSE_TO_NATIVE_COLUMN', conflicts=conflicts)
    wf.require(len(columns) <= wf.tm.MAX_CELLS, 'NEW_COLUMN_COUNT_EXCEEDS_NATIVE_CAPACITY',
               columns=len(columns), nativeCapacity=wf.tm.MAX_CELLS)
    wf.require(wf._source_bindings(original) == sources and hashes == source_hashes(),
               'PLACEMENT_SOURCE_CHANGED_DURING_COMPILATION')
    result = dict(schema=SCHEMA, ok=True, mode=frame['mode'],
                  nativeCalled=False, nativeExecuted=False, nativeSaveVerified=False, gameAccepted=False,
                  nativeCatalogVerified=frame['mode'] == 'verified-catalog-offline',
                  sourceHashes=hashes, sourceDocumentSha256=wf.object_sha(original),
                  inputDocument=original, sourceArtifacts=list(sources.values()),
                  sourceToWorldContract=original['sourceToWorldContract'],
                  sourceToWorldTransformVerified=False,
                  worldMatrix=frame['matrix'], matrixSha256=frame['matrixSha256'],
                  catalogIdentity=frame['identity'], catalogIdentitySha256=frame['identitySha256'],
                  nativeCodeRange=dict(zip(wf.AXES, frame['limits'])), quantization=quantization,
                  halfwayRule='floor(code+0.5), towards positive code',
                  preferredWorldTranslation=preferred, translationWasRequested=requested is not None,
                  worldTranslation=translation, solution=solution,
                  pointCount=len(mapped), columnCount=len(columns), conflicts=[], points=mapped,
                  maxAbsoluteResidualWorld=maxima,
                  quantizationMappingSha256=wf.object_sha(mapped),
                  terrainOwnerTransformChanged=False, existingNativeCellsReindexed=False,
                  consumerContract=dict(schema='world-placement-consumer-contract-v2',
                      coordinateSpace='world-metres', translation=translation,
                      appliesExactlyOnce=True, coverageVerified=False,
                      catalogIdentitySha256=frame['identitySha256'], matrixSha256=frame['matrixSha256'],
                      sourceDocumentSha256=wf.object_sha(original),
                      rule='Apply this one world XYZ translation to every new product entity, terrain source, water, spawn and return anchor. Do not translate directions, local child offsets, native codes, existing unrelated objects or the terrain matrix.'))
    result['compilationSha256'] = wf.object_sha(result)
    return result


def compile_points(catalog_run, document, *, quantization, preferred_translation=(0., 0., 0.),
                   world_translation=None, expected_identity_sha256=None):
    """Compile against actual original catalog receipts; never acquire live state."""
    frame = wf.load_catalog_frame(catalog_run, expected_identity_sha256=expected_identity_sha256)
    result = _compile(frame, document, quantization, preferred_translation, world_translation)
    wf.load_catalog_frame(catalog_run, expected_identity_sha256=frame['identitySha256'])
    return result


def compile_fixture(fixture, document, *, quantization, preferred_translation=(0., 0., 0.),
                    world_translation=None):
    """Explicitly synthetic calibration. Never usable as native catalog evidence."""
    return _compile(wf._fixture_frame(fixture), document, quantization,
                    preferred_translation, world_translation)


def _integrity(result):
    wf.require(type(result) is dict and result.get('schema') == SCHEMA and result.get('ok') is True,
               'PLACEMENT_COMPILATION_SCHEMA')
    clean = copy.deepcopy(result)
    digest = clean.pop('compilationSha256', None)
    wf.require(digest == wf.object_sha(clean), 'PLACEMENT_COMPILATION_CHANGED')
    wf.require(result['sourceHashes'] == source_hashes(), 'PLACEMENT_COMPILER_SOURCE_CHANGED')
    return digest


def verify_compilation(result):
    digest = _integrity(result)
    arguments = dict(quantization=result['quantization'],
                     preferred_translation=result['preferredWorldTranslation'],
                     world_translation=(result['worldTranslation'] if result['translationWasRequested'] else None))
    if result['mode'] == 'verified-catalog-offline':
        current = compile_points(result['catalogIdentity']['run'], result['inputDocument'],
                                 expected_identity_sha256=result['catalogIdentitySha256'], **arguments)
    elif result['mode'] == 'offline-fixture':
        current = compile_fixture(result['catalogIdentity']['fixture'], result['inputDocument'], **arguments)
    else:
        raise wf.FrameError('PLACEMENT_MODE_INVALID')
    wf.require(current == result, 'PLACEMENT_RECOMPUTATION_MISMATCH')
    return dict(ok=True, schema='world-placement-verification-v2', mode=result['mode'],
                compilationSha256=digest, sourceOriginalsRevalidated=True,
                nativeCatalogVerified=result['nativeCatalogVerified'], nativeCalled=False,
                nativeExecuted=False, gameAccepted=False)


def apply_world_translation(result, world_point, *, source_id, already_applied_identity=None):
    """World positions only; caller must enumerate all consumers and persist marker."""
    wf.require(already_applied_identity is None, 'WORLD_TRANSLATION_ALREADY_APPLIED', sourceId=source_id)
    wf.require(type(source_id) is str and source_id.strip(), 'STABLE_SOURCE_ID_REQUIRED')
    digest = _integrity(result)
    point = wf.vector(world_point, 'worldPoint')
    shifted = [point[i] + result['worldTranslation'][i] for i in range(3)]
    wf.require(all(math.isfinite(v) for v in shifted), 'SHIFTED_WORLD_POINT_NONFINITE')
    return dict(sourceId=source_id, sourceWorld=point, worldPosition=shifted,
                appliedCompilationSha256=digest, worldTranslation=result['worldTranslation'], nativeCalled=False)
