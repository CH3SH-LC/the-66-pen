"""Static scope checks for the approved one-probe deletion path.

These checks do not build a bridge, load an editor, read the live save, or dispatch
deletion. The fixed SHA pins separately reviewed absence evidence; these tests
cannot establish freshness, native success, resource disappearance or persistence.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "tools/editor-bridge/Adapter"
FORMAL_SHA = "f32fc618d4c88cce48bd784e5dad786fd60d4c7c05fd01f8a0aba0233b575142"


def method_body(text: str, declaration: str) -> str:
    return text.split(declaration, 1)[1].split("\n    }", 1)[0]


class TestSingleUnsavedProbeDeleteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ADAPTER / "OwnedGraphDelete.cs").read_text(encoding="utf-8-sig")
        cls.profile = (ADAPTER / "EditorBindingProfile.Generated.cs").read_text(encoding="utf-8-sig")
        cls.delete = method_body(cls.source, "object DeleteSingleUnsavedProbe(uint[] ids, bool dryRun)")
        cls.router = method_body(cls.source, "public object DeleteOwnedGraphIds(uint[] ids, bool dryRun)")
        cls.key = method_body(cls.source, "(object Category, uint Id) UnsavedProbeKey(object model)")
        cls.formal = method_body(cls.source, "void RequireUnsavedProbeFormalEvidence()")

    def test_fixed_target_cannot_escape_to_legacy_path_in_a_mixed_batch(self):
        self.assertIn("const uint UnsavedProbeGraphId = 1073741834u;", self.source)
        self.assertIn("const uint UnsavedProbeLevelId = 1073741842u;", self.source)
        self.assertIn('const string UnsavedProbeGraphName = "MW_API_DICTKIND_PROBE";', self.source)
        self.assertRegex(self.router, r"if\s*\(ids != null && ids\.Contains\(UnsavedProbeGraphId\)\)\s*return DeleteSingleUnsavedProbe\(ids, dryRun\);")
        self.assertIn("ids == null || ids.Length != 1 || ids[0] != UnsavedProbeGraphId", self.delete)
        self.assertLess(self.delete.index("UNSAVED_PROBE_ONLY_SINGLE_APPROVED_ID"), self.delete.index("Resources()"))

    def test_exact_formal_file_is_read_only_and_hash_mismatch_refuses(self):
        self.assertIn('const string UnsavedProbeApprovedFormalSha256 = "' + FORMAL_SHA + '";', self.source)
        self.assertIn(r"Beyond_Local_Save_Level\1073741842\1073741842.gil", self.source)
        self.assertIn("SHA256.Create()", self.formal)
        self.assertIn("File.OpenRead(UnsavedProbeFormalPath)", self.formal)
        self.assertIn("sha.ComputeHash(file)", self.formal)
        self.assertIn("StringComparison.OrdinalIgnoreCase", self.formal)
        self.assertIn('throw new InvalidOperationException("UNSAVED_PROBE_FORMAL_FILE_CHANGED")', self.formal)
        self.assertNotIn("File.Write", self.source)
        self.assertEqual(self.delete.count("RequireUnsavedProbeFormalEvidence();"), 2)

    def test_unique_registered_identity_name_and_binding_rechecked(self):
        self.assertEqual(self.delete.count("r.Kind == 9 && r.Id == UnsavedProbeGraphId"), 2)
        self.assertIn("matches.Length != 1", self.delete)
        self.assertIn("current.Length != 1", self.delete)
        self.assertIn("ReferenceEquals(current[0].Model, target.Model)", self.delete)
        self.assertIn("current[0].Category.SequenceEqual(target.Category)", self.delete)
        self.assertIn("name != UnsavedProbeGraphName", self.delete)
        self.assertIn("freshName != UnsavedProbeGraphName", self.delete)
        self.assertEqual(self.delete.count("InstructionGraphBoundEntities(UnsavedProbeGraphId).Count != 0"), 2)
        self.assertLess(self.delete.index("UNSAVED_PROBE_TARGET_CHANGED_OR_BOUND"), self.delete.index("delete.Invoke"))

    def test_level_id_and_retained_payload_reference_guard_both_reads(self):
        self.assertIn("RequireInitDispatcher();", self.delete)
        self.assertIn("identity.Id != UnsavedProbeLevelId", self.delete)
        self.assertIn("freshIdentity.Id != UnsavedProbeLevelId", self.delete)
        self.assertIn("ReferenceEquals(identity.Payload, freshIdentity.Payload)", self.delete)
        self.assertLess(self.delete.index("UNSAVED_PROBE_LEVEL_CHANGED"), self.delete.index("delete.Invoke"))
        self.assertNotIn("freshnessVerified = true", self.delete)

    def test_dry_run_returns_before_formal_and_native_operations(self):
        dry = self.delete.index("if (dryRun)")
        formal = self.delete.index("RequireUnsavedProbeFormalEvidence();")
        self.assertIn("return new", self.delete[dry:formal])
        self.assertIn("invoked = false", self.delete[dry:formal])
        self.assertNotIn(".Invoke(", self.delete[dry:formal])
        self.assertLess(formal, self.delete.index("ready.Invoke"))

    def test_original_editor_enum_getter_object_is_native_argument(self):
        self.assertIn('GetMethod(B("xkKXuat764s"), Fields, null, Type.EmptyTypes, null)', self.key)
        self.assertIn("category.ReturnType.IsEnum", self.key)
        self.assertIn("return (category.Invoke(model, null)!, (uint)id.Invoke(model, null)!)", self.key)
        self.assertIn("new[] { key.Category.GetType(), typeof(uint) }", self.delete)
        self.assertIn("delete.Invoke(manager, new object[] { freshKey.Category, freshKey.Id })", self.delete)
        self.assertNotIn("Enum.ToObject", self.delete + self.key)
        self.assertNotIn("Convert.ToUInt32", self.delete + self.key)
        enum = "z0qVmDEbTPwniZwd1du3.RChZIbEbUBNkFZEH9EjF"
        self.assertIn('"ullXqoLREqk", BindingKind.Method, "(' + enum + ',System.UInt32):System.Void", false)', self.profile)
        self.assertIn('"xkKXuat764s", BindingKind.Method, "():' + enum + '", false)', self.profile)

    def test_ready_true_precedes_final_reads_and_single_spent_attempt(self):
        self.assertIn("delete.IsStatic || delete.ReturnType != typeof(void)", self.delete)
        self.assertIn("ready.IsStatic || ready.ReturnType != typeof(bool)", self.delete)
        self.assertIn("ready.Invoke(manager, new object[] { true })", self.delete)
        ready = self.delete.index("ready.Invoke")
        self.assertLess(ready, self.delete.rindex("RequireUnsavedProbeFormalEvidence();"))
        self.assertLess(self.delete.index("unsavedProbeDeleteAttempted = true;"), self.delete.index("delete.Invoke"))
        self.assertIn("if (unsavedProbeDeleteAttempted)", self.delete)
        self.assertEqual(self.delete.count("delete.Invoke("), 1)
        self.assertNotIn("unsavedProbeDeleteAttempted = false", self.source)
        self.assertIn("retryAllowed = false", self.delete)
        self.assertIn("gameEffectVerified = false, persistentSaveVerified = false", self.delete)

    def test_new_route_has_no_tree_expansion_or_registry_removal(self):
        self.assertNotIn("WalkEditorGraph", self.delete)
        self.assertNotIn(".Remove(", self.delete)
        self.assertNotIn(".Clear(", self.delete)
        self.assertIn("const int OwnedGraphDeleteScanNodes = 200000;", self.source)
        self.assertIn("const int OwnedGraphDeleteScanDepth = 14;", self.source)


if __name__ == "__main__":
    unittest.main()
