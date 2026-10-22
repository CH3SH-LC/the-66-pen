"""Offline, provenance-bound world-Y translation and terrain quantization.

Production accepts only a run revalidated by terrain_calibration.calibrate.
This module never prepares, dispatches, edits, saves, or contacts a process.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TERRAIN = ROOT / "tools/map-terrain"
if str(TERRAIN) not in sys.path:
    sys.path.insert(0, str(TERRAIN))
import terrain_calibration as tc
import terrain_model as tm

INPUT_SCHEMA = "world-frame-points-v1"
OUTPUT_SCHEMA = "world-frame-compilation-v1"
FIXTURE_SCHEMA = "world-frame-offline-calibration-v1"
MAX_POINTS = 131072
AXES = ("x", "height", "z")
STEPS = (5.0, 2.5, 5.0)
SHA = re.compile(r"^[0-9a-f]{64}$")


class FrameError(ValueError):
    def __init__(self, code, **details):
        self.code, self.details = code, details
        super().__init__(code)

    def result(self):
        return dict(ok=False, code=self.code, details=self.details,
                    nativeCalled=False, nativeExecuted=False,
                    nativeSaveVerified=False, gameAccepted=False)


def require(condition, code, **details):
    if not condition:
        raise FrameError(code, **details)


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FrameError("NON_JSON_OR_NONFINITE_INPUT", error=str(exc)) from exc


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def object_sha(value):
    return sha_bytes(canonical(value))


def checked_sha(value, name):
    require(type(value) is str and SHA.fullmatch(value) is not None,
            "SHA256_REQUIRED", field=name)
    return value


def vector(value, name, size=3):
    require(type(value) in (list, tuple) and len(value) == size,
            "FINITE_VECTOR_REQUIRED", field=name, length=size)
    require(all(type(v) in (int, float) and math.isfinite(v) for v in value),
            "FINITE_VECTOR_REQUIRED", field=name)
    return [float(v) for v in value]


def project_path(value, label):
    require(type(value) is str and value, "PATH_REQUIRED", field=label)
    p = Path(value)
    p = (ROOT / p if not p.is_absolute() else p).resolve()
    require(p.is_relative_to(ROOT), "SOURCE_OUTSIDE_PROJECT", field=label)
    return p


def read_json(path):
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8-sig"),
                           parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (OSError, UnicodeError, ValueError) as exc:
        raise FrameError("JSON_SOURCE_UNREADABLE", path=str(path), error=str(exc)) from exc
    canonical(value)
    return value, sha_bytes(raw)


def _source_bindings(document):
    sources = document.get("sources")
    require(type(sources) is list and sources, "SOURCE_ARTIFACTS_REQUIRED")
    records = {}
    for row in sources:
        require(type(row) is dict and set(row) == {"artifactId", "path", "sha256"},
                "SOURCE_ARTIFACT_SCHEMA")
        ident = row["artifactId"]
        require(type(ident) is str and ident.strip(), "ARTIFACT_ID_REQUIRED")
        require(ident not in records, "DUPLICATE_ARTIFACT_ID", artifactId=ident)
        path = project_path(row["path"], "source.path")
        expected = checked_sha(row["sha256"], "source.sha256")
        try:
            actual = sha_bytes(path.read_bytes())
        except OSError as exc:
            raise FrameError("SOURCE_ARTIFACT_UNREADABLE", artifactId=ident, path=str(path)) from exc
        require(actual == expected, "SOURCE_ARTIFACT_CHANGED", artifactId=ident,
                expected=expected, actual=actual)
        records[ident] = dict(artifactId=ident, path=str(path), sha256=actual)
    return records


def _points(document, sources):
    require(type(document) is dict and document.get("schema") == INPUT_SCHEMA,
            "WORLD_POINT_DOCUMENT_SCHEMA")
    require(document.get("coordinateSpace") == "world-metres",
            "EXPLICIT_WORLD_METRES_REQUIRED")
    require(set(document) <= {"schema", "coordinateSpace", "sources", "points", "sourceToWorldContract"},
            "UNKNOWN_POINT_DOCUMENT_FIELD")
    contract = document.get("sourceToWorldContract")
    require(type(contract) is dict and set(contract) == {"artifactId", "selector", "description"},
            "SOURCE_TO_WORLD_CONTRACT_REQUIRED")
    require(type(contract["artifactId"]) is str and contract["artifactId"] in sources and all(type(contract[n]) is str and contract[n].strip()
            for n in ("selector", "description")), "SOURCE_TO_WORLD_CONTRACT_PROVENANCE")
    values = document.get("points")
    require(type(values) is list and 0 < len(values) <= MAX_POINTS,
            "POINT_COUNT_1_TO_131072_REQUIRED")
    seen, points = {}, []
    for raw in values:
        require(type(raw) is dict and set(raw) <= {"sourceId", "worldTop", "provenance", "inputKind", "nativeGrid"},
                "POINT_SCHEMA")
        ident = raw.get("sourceId")
        require(type(ident) is str and ident.strip(), "STABLE_SOURCE_ID_REQUIRED")
        if ident in seen:
            require(raw == seen[ident], "SOURCE_ID_CONFLICT", sourceId=ident,
                    first=seen[ident], second=raw)
            raise FrameError("DUPLICATE_SOURCE_ID", sourceId=ident)
        seen[ident] = raw
        provenance = raw.get("provenance")
        require(type(provenance) is dict and set(provenance) == {"artifactId", "selector"},
                "POINT_PROVENANCE_REQUIRED", sourceId=ident)
        require(type(provenance["artifactId"]) is str and provenance["artifactId"] in sources and type(provenance["selector"]) is str
                and provenance["selector"].strip(), "POINT_PROVENANCE_INVALID", sourceId=ident)
        kind = raw.get("inputKind", "source-world")
        require(kind in ("source-world", "native-grid-roundtrip"), "INPUT_KIND_INVALID", sourceId=ident)
        require(("nativeGrid" in raw) == (kind == "native-grid-roundtrip"),
                "NATIVE_GRID_EVIDENCE_REQUIRED_ONLY_FOR_ROUNDTRIP", sourceId=ident)
        point = dict(sourceId=ident, worldTop=vector(raw.get("worldTop"), ident + ".worldTop"),
                     provenance=copy.deepcopy(provenance), inputKind=kind)
        if kind == "native-grid-roundtrip":
            point["nativeGrid"] = copy.deepcopy(raw["nativeGrid"])
        points.append(point)
    return points


def _limits(calibration):
    result = []
    for name, key in (("x", "coordinateRange"), ("height", "heightCodeRange"), ("z", "coordinateRange")):
        value = calibration.get(key)
        require(type(value) is list and len(value) == 2 and all(type(x) is int for x in value)
                and 0 <= value[0] <= value[1] <= 65535, "CALIBRATION_RANGE_INVALID", axis=name)
        low, high = max(value[0], 1 if name == "height" else 0), value[1]
        require(low <= high, "CALIBRATION_HAS_NO_NONZERO_HEIGHT", axis=name)
        # The existing production converter is authoritative; no enlarged fixture bypass.
        require(high < tm.LIMIT, "CALIBRATION_EXCEEDS_PRODUCTION_CONVERTER", axis=name)
        result.append([low, high])
    return result


def _frame(calibration, identity, mode):
    require(type(calibration) is dict and calibration.get("ok") is True,
            "CALIBRATION_NOT_ACCEPTED")
    source = calibration.get("materialSource")
    require(type(source) is dict, "CALIBRATION_SOURCE_REQUIRED")
    matrix = vector(calibration.get("worldMatrix"), "worldMatrix", 16)
    require(source.get("matrix") == matrix and source.get("cellSize") == list(STEPS),
            "CALIBRATION_MATRIX_OR_CELL_SIZE_MISMATCH")
    try:
        tc.geometry(source)
    except (ValueError, KeyError) as exc:
        raise FrameError("CALIBRATION_MATRIX_INVALID", error=str(exc)) from exc
    limits = _limits(calibration)
    # Invert the actual linear transform; translating the origin by world unit Y
    # cancels the affine translation without subtracting two large inverse points.
    local_delta = tc.inverse_transform(matrix, [matrix[12], matrix[13] + 1.0, matrix[14]])
    coefficients = [local_delta[i] / STEPS[i] for i in range(3)]
    require(all(math.isfinite(x) for x in coefficients), "WORLD_Y_COEFFICIENT_NONFINITE")
    return dict(calibration=calibration, source=source, matrix=matrix, limits=limits,
                coefficients=coefficients, localDelta=local_delta, identity=identity,
                matrixSha256=object_sha(matrix), mode=mode)


def load_catalog_frame(catalog_run, *, expected_identity_sha256=None):
    """Read existing original receipts only; never captures a new catalog."""
    path = project_path(str(catalog_run), "catalogRun")
    try:
        cal = tc.calibrate(str(path))
        import terrain_catalog
        catalog = terrain_catalog.catalog(str(path))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise FrameError("CATALOG_VALIDATION_FAILED", run=str(path), error=str(exc)) from exc
    source = cal["materialSource"]
    require(source == catalog["materialSource"], "CATALOG_CHANGED_DURING_CALIBRATION")
    original_names = ("prepared.json", "build-result.json", "request.json", "stdout.jsonl", "exit.json",
                      "launch.claim", "attempt.used", "baseline-prepared.json", "baseline-snapshot.bin")
    originals = {}
    for name in original_names:
        try:
            originals[name] = sha_bytes((path / name).read_bytes())
        except OSError as exc:
            raise FrameError("CATALOG_ORIGINAL_UNREADABLE", name=name) from exc
    identity = dict(schema="world-frame-catalog-identity-v1", run=str(path),
                    levelId=source["levelId"], terrainId=source["terrainId"],
                    session=catalog["session"], rawReceiptSha256=source["rawReceiptSha256"],
                    catalogSha256=source["catalogSha256"], materialSource=copy.deepcopy(source),
                    textMap=catalog["textMap"], originalsSha256=originals,
                    coordinateRange=cal["coordinateRange"], heightCodeRange=cal["heightCodeRange"],
                    calibrationDependencies={str(TERRAIN / n): sha_bytes((TERRAIN / n).read_bytes())
                                             for n in ("terrain_calibration.py", "terrain_catalog.py", "terrain_model.py")})
    digest = object_sha(identity)
    if expected_identity_sha256 is not None:
        require(digest == checked_sha(expected_identity_sha256, "expectedIdentitySha256"),
                "CATALOG_IDENTITY_CHANGED", expected=expected_identity_sha256, actual=digest)
    frame = _frame(cal, identity, "verified-catalog-offline")
    frame["identitySha256"] = digest
    return frame


def _fixture_frame(fixture):
    require(type(fixture) is dict and set(fixture) == {"schema", "fixtureId", "matrix", "coordinateRange", "heightCodeRange"}
            and fixture.get("schema") == FIXTURE_SCHEMA, "EXPLICIT_OFFLINE_FIXTURE_REQUIRED")
    require(type(fixture["fixtureId"]) is str and fixture["fixtureId"].strip(), "FIXTURE_ID_REQUIRED")
    matrix = vector(fixture["matrix"], "fixture.matrix", 16)
    cal = dict(ok=True, worldMatrix=matrix, coordinateRange=fixture["coordinateRange"],
               heightCodeRange=fixture["heightCodeRange"],
               materialSource=dict(schema="native-terrain-material-source-v1", matrix=matrix, cellSize=list(STEPS)))
    identity = dict(schema="world-frame-offline-fixture-identity-v1", fixture=copy.deepcopy(fixture),
                    nativeCatalogVerified=False)
    frame = _frame(cal, identity, "offline-fixture")
    frame["identitySha256"] = object_sha(identity)
    return frame


def _roundtrip_evidence(frame, point):
    if point["inputKind"] != "native-grid-roundtrip":
        return None
    grid = point["nativeGrid"]
    require(type(grid) is dict and set(grid) == {"cell", "matrixSha256", "catalogIdentitySha256"},
            "ROUNDTRIP_EVIDENCE_SCHEMA", sourceId=point["sourceId"])
    require(grid["matrixSha256"] == frame["matrixSha256"] and grid["catalogIdentitySha256"] == frame["identitySha256"],
            "ROUNDTRIP_IDENTITY_MISMATCH", sourceId=point["sourceId"])
    cell = grid["cell"]
    require(type(cell) is dict and set(cell) == {"x", "height", "z"}, "ROUNDTRIP_CELL_SCHEMA")
    for axis, bounds in zip(AXES, frame["limits"]):
        require(type(cell[axis]) is int and bounds[0] <= cell[axis] <= bounds[1],
                "ROUNDTRIP_CELL_OUT_OF_RANGE", axis=axis, sourceId=point["sourceId"])
    original = tc.cell_to_world(frame["source"], cell["x"], cell["z"], cell["height"])["worldTop"]
    residual = [original[i] - point["worldTop"][i] for i in range(3)]
    require(max(abs(v) for v in residual) <= 1e-7, "ROUNDTRIP_INPUT_DOES_NOT_MATCH_CELL", sourceId=point["sourceId"])
    return dict(cell=copy.deepcopy(cell), reconstructedWorldTop=original, residualWorld=residual)


def _interval(frame, points):
    lower, upper = 0.0, math.inf
    lower_by, upper_by = {"constraint": "worldYOffset >= 0"}, None
    rows = []
    for p in points:
        local = tc.inverse_transform(frame["matrix"], p["worldTop"])
        base = [local[i] / STEPS[i] for i in range(3)]
        require(all(math.isfinite(v) for v in base), "CONTINUOUS_CODE_NONFINITE", sourceId=p["sourceId"])
        for i, (axis, bounds) in enumerate(zip(AXES, frame["limits"])):
            a, b = frame["coefficients"][i], base[i]
            reason = dict(sourceId=p["sourceId"], axis=axis, inputCode=b,
                          worldYOffsetCoefficient=a, validRange=bounds)
            if a == 0.0:
                # Inverse affine cancellation at a native domain corner can
                # leave a few ULP outside. Keep b unchanged and use the same
                # bounded arithmetic policy as the final native conversion.
                excess = max(0.0, bounds[0] - b, b - bounds[1])
                allowed = 32 * math.ulp(max(1.0, abs(b), float(bounds[1])))
                require(excess <= allowed, "NO_FEASIBLE_WORLD_Y_OFFSET",
                        cause="world-Y cannot change this native axis", constraint=reason)
                continue
            first, second = (bounds[0] - b) / a, (bounds[1] - b) / a
            lo, hi = min(first, second), max(first, second)
            require(math.isfinite(lo) and math.isfinite(hi), "OFFSET_BOUND_NONFINITE", constraint=reason)
            if lo > lower:
                lower, lower_by = lo, reason
            if hi < upper:
                upper, upper_by = hi, reason
        rows.append(dict(point=p, beforeContinuousCodes=base,
                         roundtripEvidence=_roundtrip_evidence(frame, p)))
    require(lower <= upper, "NO_FEASIBLE_WORLD_Y_OFFSET", lower=lower,
            upper=upper, lowerConstraint=lower_by, upperConstraint=upper_by)
    return rows, dict(minimum=lower, maximum=None if math.isinf(upper) else upper,
                      lowerConstraint=lower_by, upperConstraint=upper_by,
                      policy="closed native code-center domain; never rely on rounding an out-of-domain point",
                      nonnegative=True)


def _compile(frame, document, quantization, world_y_offset=None):
    require(quantization in ("exact", "nearest"), "EXPLICIT_QUANTIZATION_EXACT_OR_NEAREST")
    require(type(document) is dict, "WORLD_POINT_DOCUMENT_SCHEMA")
    canonical(document)
    document = copy.deepcopy(document)
    sources = _source_bindings(document)
    points = _points(document, sources)
    rows, interval = _interval(frame, points)
    if world_y_offset is None:
        offset = interval["minimum"]
    else:
        require(type(world_y_offset) in (int, float) and math.isfinite(world_y_offset), "FINITE_OFFSET_REQUIRED")
        offset = float(world_y_offset)
        require(offset >= interval["minimum"] and (interval["maximum"] is None or offset <= interval["maximum"]),
                "REQUESTED_OFFSET_OUTSIDE_FEASIBLE_INTERVAL", requested=offset, interval=interval)
    mapped, cells = [], {}
    maxima = [0.0, 0.0, 0.0]
    for item in rows:
        p = item["point"]
        after = [p["worldTop"][0], p["worldTop"][1] + offset, p["worldTop"][2]]
        require(all(math.isfinite(v) for v in after), "SHIFTED_WORLD_POINT_NONFINITE", sourceId=p["sourceId"])
        try:
            converted = tc.world_to_cell(frame["source"], after, quantization)
        except (ValueError, KeyError, OverflowError) as exc:
            raise FrameError("POINT_QUANTIZATION_REJECTED", sourceId=p["sourceId"],
                             quantization=quantization, afterWorld=after, error=str(exc)) from exc
        cell = {axis: converted[axis] for axis in AXES}
        boundary_slop = []
        for i, (axis, bounds) in enumerate(zip(AXES, frame["limits"])):
            code = converted["continuousCodes"][i]
            require(bounds[0] <= cell[axis] <= bounds[1], "QUANTIZED_CELL_OUT_OF_RANGE", sourceId=p["sourceId"], axis=axis)
            # Record float arithmetic noise at exact interval endpoints. This does
            # not alter world points, native integers, the matrix, or the offset.
            noise = max(0.0, bounds[0] - code, code - bounds[1])
            allowed = 32 * math.ulp(max(1.0, abs(code), float(bounds[1])))
            require(noise <= allowed, "NUMERIC_OFFSET_DOMAIN_VIOLATION", sourceId=p["sourceId"], axis=axis, amount=noise)
            boundary_slop.append(noise)
        key = (cell["x"], cell["z"])
        cells.setdefault(key, []).append(dict(sourceId=p["sourceId"], height=cell["height"],
                                             provenance=p["provenance"], sourceWorld=p["worldTop"]))
        residual = converted["residualWorld"]
        maxima = [max(maxima[i], abs(residual[i])) for i in range(3)]
        mapped.append(dict(sourceId=p["sourceId"], sourceWorld=p["worldTop"], afterWorld=after,
                           provenance=p["provenance"], sourceArtifactSha256=sources[p["provenance"]["artifactId"]]["sha256"],
                           inputKind=p["inputKind"], beforeContinuousCodes=item["beforeContinuousCodes"],
                           afterContinuousCodes=converted["continuousCodes"], cell=cell,
                           reconstructedWorldTop=converted["worldTop"], residualWorld=residual,
                           residualMeaning="native grid re-encoding" if p["inputKind"] == "native-grid-roundtrip" else "source-world to native-grid quantization",
                           originalGridRoundtrip=item["roundtripEvidence"],
                           boundaryArithmeticExcess=boundary_slop))
    conflicts = [dict(cell={"x": key[0], "z": key[1]}, sources=values)
                 for key, values in sorted(cells.items()) if len(values) > 1]
    require(not conflicts, "SOURCE_POINTS_COLLAPSE_TO_NATIVE_COLUMN", conflicts=conflicts,
            requiredAction="Owner must explicitly resample or select source points; no average, overwrite, deduplication or slope adjustment was performed.")
    require(len(cells) <= tm.MAX_CELLS, "NEW_COLUMN_COUNT_EXCEEDS_NATIVE_CAPACITY",
            columns=len(cells), nativeCapacity=tm.MAX_CELLS)
    # Detect source replacement during compilation, not just at entry.
    require(_source_bindings(document) == sources, "SOURCE_CHANGED_DURING_COMPILATION")
    payload = dict(schema=OUTPUT_SCHEMA, ok=True, mode=frame["mode"], nativeCalled=False,
                   compilerSha256=sha_bytes(Path(__file__).read_bytes()),
                   nativeExecuted=False, nativeSaveVerified=False, gameAccepted=False,
                   nativeCatalogVerified=frame["mode"] == "verified-catalog-offline",
                   matrixSha256=frame["matrixSha256"], catalogIdentitySha256=frame["identitySha256"],
                   catalogIdentity=frame["identity"], worldMatrix=frame["matrix"],
                   sourceDocumentSha256=object_sha(document), inputDocument=copy.deepcopy(document),
                   sourceArtifacts=list(sources.values()), sourceToWorldContract=document["sourceToWorldContract"],
                   sourceToWorldTransformVerified=False,
                   sourceToWorldResponsibility="Product owner supplies and independently validates source-unit/XZ/datum conversion; this compiler does not infer it.",
                   quantization=quantization, halfwayRule="floor(code+0.5), towards positive code",
                   worldYOffset=offset, offsetWasRequested=world_y_offset is not None,
                   feasibleWorldYOffset=interval, nativeCodeRange=dict(zip(AXES, frame["limits"])),
                   worldYToNativeLocal=frame["localDelta"], worldYToContinuousCodes=frame["coefficients"],
                   pointCount=len(mapped), columnCount=len(cells), conflicts=[], points=mapped,
                   maxAbsoluteResidualWorld=maxima,
                   consumerContract=dict(schema="world-frame-consumer-contract-v1", coordinateSpace="world-metres",
                                         translation=[0.0, offset, 0.0], appliesExactlyOnce=True,
                                         catalogIdentitySha256=frame["identitySha256"], matrixSha256=frame["matrixSha256"],
                                         sourceDocumentSha256=object_sha(document),
                                         rule="Apply this same world-Y translation to all source-world entities, terrain points, water, spawn and return anchors; never add it to native codes or change the terrain matrix.",
                                         coverageVerified=False))
    payload["compilationSha256"] = object_sha(payload)
    return payload


def compile_points(catalog_run, document, *, quantization, expected_identity_sha256=None, world_y_offset=None):
    """Production API. document is a complete provenance-bound world-metres set.

    The optional explicit offset supports adding another consumer to a previously
    selected global offset; callers must compile the union to obtain the global
    minimum. Every source still has to fit all native axes at that chosen offset.
    """
    frame = load_catalog_frame(catalog_run, expected_identity_sha256=expected_identity_sha256)
    result = _compile(frame, document, quantization, world_y_offset)
    load_catalog_frame(catalog_run, expected_identity_sha256=frame["identitySha256"])
    return result


def compile_fixture(fixture, document, *, quantization, world_y_offset=None):
    """Explicit offline fixture interface. Its result cannot claim a native catalog."""
    return _compile(_fixture_frame(fixture), document, quantization, world_y_offset)


def verify_compilation(result):
    """Revalidate originals and recompute the entire result, without native calls."""
    require(type(result) is dict and result.get("schema") == OUTPUT_SCHEMA and result.get("ok") is True,
            "COMPILATION_SCHEMA_INVALID")
    copy_result = copy.deepcopy(result)
    expected = copy_result.pop("compilationSha256", None)
    require(expected == object_sha(copy_result), "COMPILATION_CONTENT_CHANGED")
    requested = result["worldYOffset"] if result["offsetWasRequested"] else None
    if result["mode"] == "verified-catalog-offline":
        current = compile_points(result["catalogIdentity"]["run"], result["inputDocument"],
                                 quantization=result["quantization"], world_y_offset=requested,
                                 expected_identity_sha256=result["catalogIdentitySha256"])
    elif result["mode"] == "offline-fixture":
        current = compile_fixture(result["catalogIdentity"]["fixture"], result["inputDocument"],
                                  quantization=result["quantization"], world_y_offset=requested)
    else:
        raise FrameError("COMPILATION_MODE_INVALID")
    require(current == result, "COMPILATION_RECOMPUTATION_MISMATCH")
    return dict(ok=True, schema="world-frame-verification-v1", mode=result["mode"],
                compilationSha256=expected, sourceOriginalsRevalidated=True,
                nativeCatalogVerified=result["nativeCatalogVerified"], nativeCalled=False,
                nativeExecuted=False, gameAccepted=False)


def apply_world_translation(result, world_point, *, source_id, already_applied_identity=None):
    """Entity/anchor helper; no integer terrain conversion and no game mutation.

    Returns a binding marker so a consumer can reject accidental double use.
    The helper does not prove that the caller enumerated every product consumer.
    """
    require(already_applied_identity is None, "WORLD_TRANSLATION_ALREADY_APPLIED", sourceId=source_id)
    require(type(source_id) is str and source_id.strip(), "STABLE_SOURCE_ID_REQUIRED")
    require(result.get("schema") == OUTPUT_SCHEMA and result.get("ok") is True, "COMPILATION_SCHEMA_INVALID")
    clean = dict(result)
    expected = clean.pop("compilationSha256", None)
    require(expected == object_sha(clean), "COMPILATION_CONTENT_CHANGED")
    point = vector(world_point, "worldPoint")
    shifted = [point[0], point[1] + result["worldYOffset"], point[2]]
    require(all(math.isfinite(v) for v in shifted), "SHIFTED_WORLD_POINT_NONFINITE")
    return dict(sourceId=source_id, sourceWorld=point, worldPosition=shifted,
                appliedCompilationSha256=expected, worldYOffset=result["worldYOffset"],
                nativeCalled=False)
