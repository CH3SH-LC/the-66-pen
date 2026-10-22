"""Complete module batch. All geometry/catalog sources below are private fixtures."""
from contextlib import contextmanager
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import world_frame as wf

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SHEAR = [1, 0, 0, 0, 2, 1, 3, 0, 0, 0, 1, 0, 10, -4, 20, 1]
ROTATED = [0, 0, -2, 0, 0, 3, 0, 0, 4, 0, 0, 0, 20, 7, 30, 1]
RUNTIME = wf.ROOT / ".runtime/world-frame-20261017"


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def fixture(matrix=None, high=100):
    return dict(schema=wf.FIXTURE_SCHEMA, fixtureId="private-test-only",
                matrix=matrix or IDENTITY, coordinateRange=[0, high], heightCodeRange=[0, high])


class FrameTests(unittest.TestCase):
    def setUp(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="unit-", dir=RUNTIME)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.json"
        dump(self.source, {"fixture": True, "description": "synthetic source; not the game"})

    def tearDown(self):
        self.temp.cleanup()

    def document(self, points):
        return dict(schema=wf.INPUT_SCHEMA, coordinateSpace="world-metres",
                    sources=[dict(artifactId="source", path=str(self.source), sha256=wf.sha_bytes(self.source.read_bytes()))],
                    sourceToWorldContract=dict(artifactId="source", selector="/fixture", description="Explicit private world metre inputs"),
                    points=[dict(sourceId="p" + str(i), worldTop=p,
                                 provenance=dict(artifactId="source", selector="/points/" + str(i))) for i, p in enumerate(points)])

    def compile(self, points, matrix=None, high=100, quantization="nearest", **kwargs):
        return wf.compile_fixture(fixture(matrix, high), self.document(points), quantization=quantization, **kwargs)

    def assertCode(self, code, fn):
        with self.assertRaises(wf.FrameError) as ctx:
            fn()
        self.assertEqual(ctx.exception.code, code, ctx.exception.details)
        return ctx.exception.details

    def test_negative_source_height_receives_one_global_offset_without_clamp(self):
        r = self.compile([[0, -7.5, 0], [5, 2.5, 0]], quantization="exact")
        self.assertEqual(r["worldYOffset"], 10.0)
        self.assertEqual([p["cell"]["height"] for p in r["points"]], [1, 5])
        self.assertEqual(r["points"][0]["sourceWorld"], [0, -7.5, 0])
        self.assertEqual(r["worldMatrix"], IDENTITY)
        self.assertFalse(r["nativeCatalogVerified"])

    def test_already_valid_source_keeps_zero_offset(self):
        r = self.compile([[5, 2.5, 5]])
        self.assertEqual(r["worldYOffset"], 0.0)
        self.assertEqual(r["points"][0]["cell"], dict(x=1, height=1, z=1))

    def test_rotation_nonuniform_scale_translation_consumed(self):
        r = self.compile([[240, -8, -50]], ROTATED, quantization="exact")
        self.assertEqual(r["worldYOffset"], 22.5)
        self.assertEqual(r["points"][0]["cell"], dict(x=8, height=1, z=11))
        self.assertEqual(r["points"][0]["reconstructedWorldTop"], [240.0, 14.5, -50.0])

    def test_world_y_changes_native_x_height_and_z(self):
        r = self.compile([[50, -9, 67.5]], SHEAR, quantization="exact")
        self.assertEqual(r["worldYToNativeLocal"], [-2.0, 1.0, -3.0])
        self.assertEqual(r["worldYToContinuousCodes"], [-0.4, 0.4, -0.6])
        self.assertEqual(r["worldYOffset"], 7.5)
        self.assertEqual(r["points"][0]["cell"], dict(x=7, height=1, z=8))
        self.assertEqual(r["points"][0]["afterWorld"], [50.0, -1.5, 67.5])

    def test_incompatible_axes_have_empty_global_interval(self):
        self.assertCode("NO_FEASIBLE_WORLD_Y_OFFSET", lambda: self.compile([[5, -9, 10]], SHEAR))

    def test_multiple_points_have_empty_global_interval(self):
        details = self.assertCode("NO_FEASIBLE_WORLD_Y_OFFSET", lambda: self.compile([[0, -10, 0], [5, 250, 0]], high=100))
        self.assertEqual(details["lowerConstraint"]["sourceId"], "p0")
        self.assertEqual(details["upperConstraint"]["sourceId"], "p1")

    def test_y_cannot_repair_native_horizontal_underflow(self):
        d = self.assertCode("NO_FEASIBLE_WORLD_Y_OFFSET", lambda: self.compile([[-0.001, 2.5, 0]]))
        self.assertEqual(d["constraint"]["axis"], "x")

    def test_native_business_range_not_uint16_width(self):
        self.assertCode("NO_FEASIBLE_WORLD_Y_OFFSET", lambda: self.compile([[505, 2.5, 0]], high=100))
        f = fixture(high=65535)
        self.assertCode("CALIBRATION_EXCEEDS_PRODUCTION_CONVERTER", lambda: wf.compile_fixture(f, self.document([[0, 2.5, 0]]), quantization="nearest"))

    def test_high_endpoint_is_inclusive(self):
        r = self.compile([[500, 250, 500]], high=100, quantization="exact")
        self.assertEqual(r["points"][0]["cell"], dict(x=100, height=100, z=100))

    def test_zero_height_range_is_not_new_terrain(self):
        f = fixture(); f["heightCodeRange"] = [0, 0]
        self.assertCode("CALIBRATION_HAS_NO_NONZERO_HEIGHT", lambda: wf.compile_fixture(f, self.document([[0, 0, 0]]), quantization="nearest"))

    def test_halfway_tie_and_three_dimensional_residual(self):
        r = self.compile([[12.5, 6.25, 17.5]])
        p = r["points"][0]
        self.assertEqual(p["cell"], dict(x=3, height=3, z=4))
        self.assertEqual(p["residualWorld"], [2.5, 1.25, 2.5])
        self.assertEqual(p["reconstructedWorldTop"], [15.0, 7.5, 20.0])

    def test_just_below_tie_rounds_lower(self):
        r = self.compile([[12.5 - 1e-7, 6.25 - 1e-7, 17.5 - 1e-7]])
        self.assertEqual(r["points"][0]["cell"], dict(x=2, height=2, z=3))

    def test_exact_mode_rejects_source_float_off_grid(self):
        d = self.assertCode("POINT_QUANTIZATION_REJECTED", lambda: self.compile([[12.5, 6.25, 17.5]], quantization="exact"))
        self.assertIn("NOT_ON_NATIVE_GRID", d["error"])

    def test_explicit_quantization_required(self):
        self.assertCode("EXPLICIT_QUANTIZATION_EXACT_OR_NEAREST", lambda: self.compile([[0, 2.5, 0]], quantization="auto"))

    def test_requested_global_offset_reused_without_reselection(self):
        r = self.compile([[0, 2.5, 0]], world_y_offset=10)
        self.assertEqual(r["worldYOffset"], 10)
        self.assertTrue(r["offsetWasRequested"])
        self.assertEqual(r["points"][0]["cell"]["height"], 5)

    def test_requested_offset_outside_interval_is_rejected(self):
        self.assertCode("REQUESTED_OFFSET_OUTSIDE_FEASIBLE_INTERVAL", lambda: self.compile([[0, -7.5, 0]], world_y_offset=5))

    def test_duplicate_native_columns_retain_all_conflicting_sources(self):
        d = self.assertCode("SOURCE_POINTS_COLLAPSE_TO_NATIVE_COLUMN", lambda: self.compile([[1, 5, 1], [2, 15, 2]]))
        self.assertEqual(d["conflicts"][0]["cell"], {"x": 0, "z": 0})
        self.assertEqual([r["sourceId"] for r in d["conflicts"][0]["sources"]], ["p0", "p1"])
        self.assertEqual([r["height"] for r in d["conflicts"][0]["sources"]], [2, 6])

    def test_same_id_different_point_is_named_conflict(self):
        doc = self.document([[0, 2.5, 0], [5, 2.5, 0]])
        doc["points"][1]["sourceId"] = "p0"
        self.assertCode("SOURCE_ID_CONFLICT", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_equal_duplicate_id_is_not_silently_deduplicated(self):
        doc = self.document([[0, 2.5, 0]])
        doc["points"].append(copy.deepcopy(doc["points"][0]))
        self.assertCode("DUPLICATE_SOURCE_ID", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_missing_or_nonfinite_world_points_rejected(self):
        for val in (None, [1, 2], [0, float("nan"), 0], [0, float("inf"), 0], [False, 2.5, 0]):
            with self.subTest(val=val):
                with self.assertRaises(wf.FrameError):
                    self.compile([val])

    def test_singular_or_projective_matrix_rejected(self):
        for index, value in ((0, 0), (3, 1), (15, 0)):
            m = list(IDENTITY); m[index] = value
            self.assertCode("CALIBRATION_MATRIX_INVALID", lambda: self.compile([[0, 2.5, 0]], m))

    def test_missing_source_or_changed_original_rejected(self):
        doc = self.document([[0, 2.5, 0]])
        self.source.write_bytes(b"changed")
        self.assertCode("SOURCE_ARTIFACT_CHANGED", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))
        self.source.unlink()
        self.assertCode("SOURCE_ARTIFACT_UNREADABLE", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_source_mutation_during_mapping_rejected(self):
        doc = self.document([[0, 2.5, 0]])
        original = wf.tc.world_to_cell
        def change(*args, **kwargs):
            answer = original(*args, **kwargs)
            self.source.write_bytes(b"changed during mapping")
            return answer
        with patch.object(wf.tc, "world_to_cell", side_effect=change):
            self.assertCode("SOURCE_ARTIFACT_CHANGED", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_source_units_are_not_implicitly_treated_as_world(self):
        doc = self.document([[0, 2.5, 0]]); doc["coordinateSpace"] = "reference-model-units"
        self.assertCode("EXPLICIT_WORLD_METRES_REQUIRED", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_source_to_world_contract_missing_rejected(self):
        doc = self.document([[0, 2.5, 0]]); del doc["sourceToWorldContract"]
        self.assertCode("SOURCE_TO_WORLD_CONTRACT_REQUIRED", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_unbound_source_selector_and_unknown_field_rejected(self):
        doc = self.document([[0, 2.5, 0]]); doc["points"][0]["provenance"]["artifactId"] = "missing"
        self.assertCode("POINT_PROVENANCE_INVALID", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))
        doc = self.document([[0, 2.5, 0]]); doc["points"][0]["clamp"] = True
        self.assertCode("POINT_SCHEMA", lambda: wf.compile_fixture(fixture(), doc, quantization="nearest"))

    def test_grid_roundtrip_is_separate_from_source_accuracy(self):
        f = fixture(); frame = wf._fixture_frame(f)
        doc = self.document([[10, 7.5, 15]])
        doc["points"][0].update(inputKind="native-grid-roundtrip", nativeGrid=dict(
            cell=dict(x=2, height=3, z=3), matrixSha256=frame["matrixSha256"], catalogIdentitySha256=frame["identitySha256"]))
        r = wf.compile_fixture(f, doc, quantization="exact")
        self.assertEqual(r["points"][0]["residualMeaning"], "native grid re-encoding")
        self.assertEqual(r["points"][0]["originalGridRoundtrip"]["residualWorld"], [0, 0, 0])
        self.assertFalse(r["sourceToWorldTransformVerified"])
        self.assertFalse(r["consumerContract"]["coverageVerified"])

    def test_grid_roundtrip_wrong_matrix_identity_rejected(self):
        f = fixture(); frame = wf._fixture_frame(f); doc = self.document([[10, 7.5, 15]])
        doc["points"][0].update(inputKind="native-grid-roundtrip", nativeGrid=dict(
            cell=dict(x=2, height=3, z=3), matrixSha256="0" * 64, catalogIdentitySha256=frame["identitySha256"]))
        self.assertCode("ROUNDTRIP_IDENTITY_MISMATCH", lambda: wf.compile_fixture(f, doc, quantization="exact"))

    def test_grid_roundtrip_wrong_claimed_point_rejected(self):
        f = fixture(); frame = wf._fixture_frame(f); doc = self.document([[10, 7.6, 15]])
        doc["points"][0].update(inputKind="native-grid-roundtrip", nativeGrid=dict(
            cell=dict(x=2, height=3, z=3), matrixSha256=frame["matrixSha256"], catalogIdentitySha256=frame["identitySha256"]))
        self.assertCode("ROUNDTRIP_INPUT_DOES_NOT_MATCH_CELL", lambda: wf.compile_fixture(f, doc, quantization="nearest"))

    def test_full_result_recomputes_and_tampering_rejected(self):
        r = self.compile([[0, -7.5, 0], [5, 2.5, 0]])
        self.assertTrue(wf.verify_compilation(r)["ok"])
        r["points"][0]["cell"]["height"] = 99
        self.assertCode("COMPILATION_CONTENT_CHANGED", lambda: wf.verify_compilation(r))

    def test_rehashed_forged_mapping_rejected_by_recomputation(self):
        r = self.compile([[0, 2.5, 0]])
        r["points"][0]["cell"]["height"] = 99
        del r["compilationSha256"]; r["compilationSha256"] = wf.object_sha(r)
        self.assertCode("COMPILATION_RECOMPUTATION_MISMATCH", lambda: wf.verify_compilation(r))

    def test_entity_anchor_translation_same_offset_and_double_use_guard(self):
        r = self.compile([[0, -7.5, 0]])
        shifted = wf.apply_world_translation(r, [100, -15, 200], source_id="return-anchor")
        self.assertEqual(shifted["worldPosition"], [100, -5, 200])
        self.assertCode("WORLD_TRANSLATION_ALREADY_APPLIED", lambda: wf.apply_world_translation(
            r, shifted["worldPosition"], source_id="return-anchor", already_applied_identity=shifted["appliedCompilationSha256"]))

    def test_input_retained_and_source_document_hash_changes(self):
        doc = self.document([[0, 2.5, 0]])
        r = wf.compile_fixture(fixture(), doc, quantization="nearest")
        self.assertEqual(r["inputDocument"], doc)
        doc["points"][0]["worldTop"][1] = 5.0
        self.assertNotEqual(wf.object_sha(doc), r["sourceDocumentSha256"])

    def test_unhashable_provenance_is_named_schema_rejection(self):
        for target in ("sourceToWorldContract", "point"):
            doc = self.document([[0, 2.5, 0]])
            if target == "point":
                doc["points"][0]["provenance"]["artifactId"] = []
            else:
                doc["sourceToWorldContract"]["artifactId"] = []
            with self.assertRaises(wf.FrameError):
                wf.compile_fixture(fixture(), doc, quantization="nearest")

    def test_native_domain_corners_with_non_cardinal_rotation(self):
        # These are explicitly fixture grid roundtrips, not source-accuracy data.
        for degrees in (13, 29, 47, 71):
            c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
            matrix = [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 13.1, -4.7, 2.9, 1]
            for x, h, z in ((0, 1, 0), (0, 1, 100), (100, 100, 0), (100, 1, 100)):
                point = [c*x*5+s*z*5+13.1, h*2.5-4.7, -s*x*5+c*z*5+2.9]
                f = fixture(matrix); frame = wf._fixture_frame(f); doc = self.document([point])
                doc["points"][0].update(inputKind="native-grid-roundtrip", nativeGrid=dict(
                    cell=dict(x=x, height=h, z=z), matrixSha256=frame["matrixSha256"], catalogIdentitySha256=frame["identitySha256"]))
                with self.subTest(degrees=degrees, cell=(x, h, z)):
                    r = wf.compile_fixture(f, doc, quantization="exact")
                    self.assertEqual(r["worldYOffset"], 0)
                    self.assertEqual(r["points"][0]["cell"], dict(x=x, height=h, z=z))

    def test_twenty_thousand_points_complete_mapping_not_summary_only(self):
        r = self.compile([[x * 5.0, 2.5 + (x % 3) * 2.5, z * 5.0]
                          for z in range(100) for x in range(200)], high=250, quantization="exact")
        self.assertEqual(r["pointCount"], 20000)
        self.assertEqual(r["columnCount"], 20000)
        self.assertEqual(len(r["points"]), 20000)
        self.assertEqual(r["maxAbsoluteResidualWorld"], [0, 0, 0])

    def test_cli_isolated_interpreter_compile_verify_and_no_overwrite(self):
        fp, pp, out = self.root / "fixture.json", self.root / "points.json", self.root / "result.json"
        dump(fp, fixture(SHEAR)); dump(pp, self.document([[50, -9, 67.5]]))
        cmd = [sys.executable, "-B", "-I", "-S", str(HERE / "cli.py"), "compile-fixture", "--fixture", str(fp),
               "--points", str(pp), "--out", str(out), "--quantization", "exact"]
        completed = subprocess.run(cmd, cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        response = json.loads(completed.stdout)
        self.assertEqual(response["worldYOffset"], 7.5)
        check = subprocess.run([sys.executable, "-B", "-I", "-S", str(HERE / "cli.py"), "verify", "--compiled", str(out)],
                               capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        old = out.read_bytes()
        again = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(again.returncode, 2)
        self.assertEqual(out.read_bytes(), old)

    def test_production_cli_refuses_fixture_path_as_catalog(self):
        pp = self.root / "points.json"; dump(pp, self.document([[0, 2.5, 0]]))
        cmd = [sys.executable, "-B", "-I", "-S", str(HERE / "cli.py"), "compile", "--catalog-run", str(self.root),
               "--points", str(pp), "--out", str(self.root / "refused.json"), "--quantization", "exact"]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(json.loads(p.stdout)["code"], "CATALOG_VALIDATION_FAILED")
        self.assertFalse((self.root / "refused.json").exists())

    @contextmanager
    def private_catalog(self):
        # Full original-format synthetic catalog, never a real game run.
        sys.path.insert(0, str(wf.TERRAIN / "tests"))
        import terrain_native as native
        import terrain_catalog as catalog
        import test_catalog_calibration as originals
        run = self.root / "private-catalog"; run.mkdir()
        originals.original_fixture(run)
        textmap = self.root / "fixture-textmap.bin"; textmap.write_bytes(b"private test labels")
        labels = ({100: "fixture grass", 101: "fixture stone"},
                  dict(path=str(textmap), sha256=wf.sha_bytes(textmap.read_bytes()), decodedSha256="0" * 64, source="PRIVATE TEST FIXTURE"))
        with patch.object(native, "OUT", self.root), patch.object(catalog, "installed_labels", return_value=labels):
            yield run, originals

    def test_actual_calibrate_and_original_receipt_validation_path(self):
        with self.private_catalog() as (run, _):
            r = wf.compile_points(str(run), self.document([[42.5, 0.0, 37.5]]), quantization="exact")
            self.assertEqual(r["points"][0]["cell"], dict(x=118, z=117, height=1))
            self.assertEqual(r["catalogIdentity"]["levelId"], 1073741900)
            self.assertEqual(len(r["catalogIdentity"]["originalsSha256"]), 9)
            self.assertTrue(wf.verify_compilation(r)["ok"])
            # This validates a private binary fixture path only, not game evidence.
            self.assertFalse(r["nativeCalled"])

    def test_expected_catalog_identity_rejects_another_identity(self):
        with self.private_catalog() as (run, _):
            self.assertCode("CATALOG_IDENTITY_CHANGED", lambda: wf.compile_points(str(run), self.document([[42.5, 0, 37.5]]),
                            quantization="nearest", expected_identity_sha256="0" * 64))

    def test_changed_original_receipt_rejects_previously_compiled_result(self):
        with self.private_catalog() as (run, _):
            r = wf.compile_points(str(run), self.document([[42.5, 0, 37.5]]), quantization="exact")
            record, _ = wf.read_json(run / "stdout.jsonl"); record["transportOk"] = False
            dump(run / "stdout.jsonl", record)
            self.assertCode("CATALOG_VALIDATION_FAILED", lambda: wf.verify_compilation(r))

    def test_changed_original_claim_even_if_decoder_ignores_bytes_is_identity_change(self):
        with self.private_catalog() as (run, _):
            frame = wf.load_catalog_frame(run)
            (run / "launch.claim").write_bytes(b"another-private-claim")
            self.assertCode("CATALOG_IDENTITY_CHANGED", lambda: wf.load_catalog_frame(run, expected_identity_sha256=frame["identitySha256"]))


if __name__ == "__main__":
    unittest.main()
