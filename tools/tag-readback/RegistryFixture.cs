// Synthetic registry fixture. BeyondEditor.dll is NEVER loaded and no editor process is used.
//
// Mirror of the read-only static evidence (all paths under this repository):
//   .runtime/verification/tag-readback/singleton.cs:6-58
//       yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<T>:
//         private static readonly Lazy<T> rZmi38av5uw;       // singleton storage
//         public static T pZgi3PiTIE8() => rZmi38av5uw.Value; // getter (never called by the reader)
//   .runtime/verification/tag-readback/registry-annotated.cs:20-22,393,397,1589,1592-1596,1600-1618,2479-2531
//       ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre:
//         private Lpts7HiY2aTvYryR0pre.cwS4IdY3T3bVCku4mc2X bwbixDw3yob;   // :1589 root node
//         public static Lpts7HiY2aTvYryR0pre F4yixx2sq3y()                 // :1592-1596
//             => vSwq2Ui3deULA6AUjQxt<Lpts7HiY2aTvYryR0pre>.pZgi3PiTIE8();
//         rrcix0ow2Fi(path,id) = n1iiYBlh6Ql(path) -> node.biEY3R0K3ka(id)   // :2479-2531
//         nested class cwS4IdY3T3bVCku4mc2X:
//           private SortedDictionary<uint, HjteTyiYhKgSp79CEtgX> JkmYibSuDZr; // :393 model dictionary
//           private SortedDictionary<uint, cwS4IdY3T3bVCku4mc2X> pIxYiE5REC8; // :397 sub-category dictionary
//           EG7Y390WpYF(key) = pIxYiE5REC8.TryGetValue(key)                   // :514-521 READ-only
//           biEY3R0K3ka(id)  = JkmYibSuDZr.TryGetValue(id)                    // :720-733 model lookup
//           WJOY3NjZoMg      = JkmYibSuDZr[num] = P_0                         // :912 insert
//   .runtime/verification/tag-readback-diagnostic/tag-category-factory.cs:1079-1082 + resource-sync-payload/tag-handler.cs
//       registration path = [10003, 50013]
//   .runtime/verification/resource-sync-payload/key-registration.cs:215-267
//       Fevvc(Ixx,uint): four category uints = path[0..3], id in namiwGPRyPS
//
// Types declared here use the SAME fully-qualified names and the SAME field names as the real
// assemblies, and use the real System.Collections.Generic.SortedDictionary<,> so the reader
// exercises the genuine runtime layout rather than a hand-rolled shape.
//
// The registered model type is NOT nhvlt3i2jU53g9xeFtUu.mha7Cmi2N9yPWiDcXdhA. Reason: that type
// (tools/tag-readback/Fixture.cs) is `sealed` and does not implement the registry model interface
// HjteTyiYhKgSp79CEtgX, and Fixture.cs is an input file of this task and must not be modified.
// FixtureRegisteredModel instead derives from the same FixtureBase, which supplies the identical
// name/identity field chain, so the reader uses the exact same field-read function. When reading a
// real editor the model type name is a parameter and is the real tag type name.
using System.Collections.Generic;
using nhvlt3i2jU53g9xeFtUu;
using ACE1cmiYtEdXg5frDhMg;
using yT2GjCi3sEnq3X39OnMH;

namespace O9VDNyiYLlVysNPoLllk
{
    // The real HjteTyiYhKgSp79CEtgX is the value type of the registry's model dictionary. Whether
    // the real declaration is an interface or a class is NOT established by this task's evidence;
    // the structural walk is unaffected, and the observed declared type name is reported.
    public interface HjteTyiYhKgSp79CEtgX { }
}

namespace nhvlt3i2jU53g9xeFtUu
{
    public sealed class FixtureRegisteredModel : FixtureBase, O9VDNyiYLlVysNPoLllk.HjteTyiYhKgSp79CEtgX
    {
        public FixtureRegisteredModel(string? name, uint id) : base(name, id) { }
        public FixtureRegisteredModel(string? name, uint id, uint c0, uint c1, uint c2, uint c3) : base(name, id, c0, c1, c2, c3) { }
    }

    // Same field chain, different CLR type: used as "the registry entry points at some other object".
    public sealed class FixtureDecoyModel : FixtureBase, O9VDNyiYLlVysNPoLllk.HjteTyiYhKgSp79CEtgX
    {
        public FixtureDecoyModel(string? name, uint id) : base(name, id) { }
    }
}

namespace ACE1cmiYtEdXg5frDhMg
{
    public class Lpts7HiY2aTvYryR0pre
    {
        public class cwS4IdY3T3bVCku4mc2X
        {
            // Only the fields the read path actually touches are mirrored. The real type declares
            // more (registry-annotated.cs:380-398); their absence does not affect this walk and is
            // recorded in the evidence index.
            private SortedDictionary<uint, O9VDNyiYLlVysNPoLllk.HjteTyiYhKgSp79CEtgX> JkmYibSuDZr;
            private SortedDictionary<uint, cwS4IdY3T3bVCku4mc2X> pIxYiE5REC8;
#pragma warning disable CS0169 // mirrored from the real type; the read path does not touch it
            private cwS4IdY3T3bVCku4mc2X? hvbYiO6KeIC;
#pragma warning restore CS0169

            public cwS4IdY3T3bVCku4mc2X()
            {
                JkmYibSuDZr = new SortedDictionary<uint, O9VDNyiYLlVysNPoLllk.HjteTyiYhKgSp79CEtgX>();
                pIxYiE5REC8 = new SortedDictionary<uint, cwS4IdY3T3bVCku4mc2X>();
            }
            public cwS4IdY3T3bVCku4mc2X Sub(uint key)
            {
                if (!pIxYiE5REC8.TryGetValue(key, out var node)) { node = new cwS4IdY3T3bVCku4mc2X(); pIxYiE5REC8[key] = node; }
                return node;
            }
            public void AddModel(uint id, O9VDNyiYLlVysNPoLllk.HjteTyiYhKgSp79CEtgX model) => JkmYibSuDZr[id] = model;
            public int ModelCount => JkmYibSuDZr.Count;
            public int SubCount => pIxYiE5REC8.Count;
        }

        private cwS4IdY3T3bVCku4mc2X bwbixDw3yob;
#pragma warning disable CS0169 // mirrored from the real type; the read path does not touch it
        private cwS4IdY3T3bVCku4mc2X? Ucdixs7Y5bC;
#pragma warning restore CS0169

        public Lpts7HiY2aTvYryR0pre() { bwbixDw3yob = new cwS4IdY3T3bVCku4mc2X(); }

        // Mirrors registry-annotated.cs:1592-1596. Called only by the fixture process itself to
        // bring its own singleton into existence, exactly as the editor would. The readback tool
        // never calls this or any other method on the target.
        public static Lpts7HiY2aTvYryR0pre F4yixx2sq3y() => yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<Lpts7HiY2aTvYryR0pre>.pZgi3PiTIE8();

        public cwS4IdY3T3bVCku4mc2X Root => bwbixDw3yob;
    }
}

namespace yT2GjCi3sEnq3X39OnMH
{
    public class vSwq2Ui3deULA6AUjQxt<T> where T : new()
    {
        private static readonly Lazy<T> rZmi38av5uw;
#pragma warning disable CS0649 // mirrored from the real type; stays null in the fixture
        internal static object? l03Ac3gzlWGxqiGE0Rbq;
#pragma warning restore CS0649

        private vSwq2Ui3deULA6AUjQxt() { }

        [System.Runtime.CompilerServices.SpecialName]
        public static T pZgi3PiTIE8() => rZmi38av5uw.Value;

        static vSwq2Ui3deULA6AUjQxt() { rZmi38av5uw = new Lazy<T>(() => new T(), isThreadSafe: true); }

        internal static bool cRb12Dgzhur5WXcmgiof() => l03Ac3gzlWGxqiGE0Rbq == null;
        internal static object? MiFcB0gzLb3tMlrGrWkt() => l03Ac3gzlWGxqiGE0Rbq;
    }

    // "Layout not supported" scenario: same field name, but the storage object is NOT a
    // System.Lazy<T> and therefore has neither _state nor _value / m_boxed.
    public sealed class FixtureFakeLazy<T>
    {
        private readonly Func<T> factory;
        public FixtureFakeLazy(Func<T> f) { factory = f; }
        public T Value => factory();
    }

    public class vSwq2Ui3deULA6AUjQxtFake<T> where T : new()
    {
        private static readonly FixtureFakeLazy<T> rZmi38av5uw;
        public static T pZgi3PiTIE8() => rZmi38av5uw.Value;
        static vSwq2Ui3deULA6AUjQxtFake() { rZmi38av5uw = new FixtureFakeLazy<T>(() => new T()); }
    }
}

// ---------------------------------------------------------------------------------------------
// Scenario matrix. Expectations are hardcoded literals: they are NOT produced by the walker, so a
// change in the walker cannot silently rewrite what is expected of it.
// ---------------------------------------------------------------------------------------------
internal sealed record RegistryCase(
    string Name,
    string ModelTypeName,
    string SingletonTypeName,
    string ExpectStatus,
    string ExpectDetailPrefix,
    bool ExpectMembership,
    bool ExpectModelObjectMatch,
    bool ExpectHeapCandidate,
    string ExpectStopReason,
    bool ExpectHeapScanComplete,
    bool ExpectCategoryFieldsApplied,
    bool ExpectModelMapReached,
    bool ExpectObjectNotModelType,
    bool ExpectReferenceEquals,
    string? ExpectRegistryObjectTypeName,
    string ConstructedBy);

internal static class RegistryFixture
{
    internal const string RegisteredModelType = "nhvlt3i2jU53g9xeFtUu.FixtureRegisteredModel";
    internal const string DecoyModelType = "nhvlt3i2jU53g9xeFtUu.FixtureDecoyModel";
    internal const string RealSingletonType = Program.SingletonTypeOuter + "<" + Program.RegistryType + ">";
    internal const string FakeSingletonType = "yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxtFake<" + Program.RegistryType + ">";
    internal const string OtherName = "MW_SYNTHETIC_TAG_PROBE_OTHER_ID";
    internal const string MismatchName = "MW_SYNTHETIC_TAG_PROBE_MISMATCH";

    internal static readonly List<object> Keep = new();

    internal static RegistryQuery QueryFor(RegistryCase c) => new(c.ModelTypeName, c.SingletonTypeName,
        Program.CategoryPath, Program.CategoryFields, Program.IdField, Program.Name, Program.FixtureId, true);

    internal static readonly RegistryCase[] Cases =
    {
        // 1. Correctly registered: the leaf under [10003,50013] stores the very object whose own
        //    name+id+category match. The ONLY case where membership may be reported.
        new("registered",RegisteredModelType,RealSingletonType,"confirmed-registered","path-resolved",true,true,true,"completed",true,true,true,false,true,RegisteredModelType,
            "leaf [10003,50013].JkmYibSuDZr[FixtureId] = new FixtureRegisteredModel(Name, FixtureId)"),
        // 2. Same name + same id object exists in the heap, but the registry holds no entry for that
        //    id. This is exactly the V02 situation: heap presence is not registration.
        new("heap-only",RegisteredModelType,RealSingletonType,"object-not-found","model-key-absent",false,true,true,"completed",true,true,true,false,false,null,
            "leaf [10003,50013] created empty; matching model kept alive only by the fixture's keep-list"),
        // 3. The category path itself does not exist (only [10003,50014] was ever created).
        new("path-mismatch",RegisteredModelType,RealSingletonType,"path-mismatch","path-key-absent",false,true,true,"completed",true,true,false,false,false,null,
            "only leaf [10003,50014] created; matching model kept alive in the heap"),
        // 4. Registered under the WRONG category: the object's own category quad is (10003,50014,0,0).
        new("wrong-category",RegisteredModelType,RealSingletonType,"object-not-found","model-key-absent",false,false,false,"completed",true,true,true,false,false,null,
            "model registered under leaf [10003,50014]; the reader looks at [10003,50013]"),
        // 5. Registered under a DIFFERENT id; the expected id has no entry.
        new("wrong-id",RegisteredModelType,RealSingletonType,"object-not-found","model-key-absent",false,true,true,"completed",true,true,true,false,false,null,
            "leaf stores FixtureRegisteredModel(OtherName, FixtureId+1) at key FixtureId+1"),
        // 6. The registry entry points at a DIFFERENT object (different CLR type, same identity fields).
        new("different-object",RegisteredModelType,RealSingletonType,"reference-mismatch","registry-object-type-is-not-the-model-type",false,true,true,"completed",true,true,true,true,false,DecoyModelType,
            "leaf.add(FixtureId, new FixtureDecoyModel(Name, FixtureId)); matching registered model kept in heap"),
        // 7. The registry entry exists at the right path and id but carries a different name.
        new("field-mismatch",RegisteredModelType,RealSingletonType,"field-mismatch","registry-object-field-mismatch",false,true,true,"completed",true,true,true,false,false,RegisteredModelType,
            "leaf.add(FixtureId, new FixtureRegisteredModel(MismatchName, FixtureId)); matching model kept in heap"),
        // 8. The entry exists but its name wrapper field is null, so its fields cannot be read.
        new("unreadable",RegisteredModelType,RealSingletonType,"read-failed","registry-object-fields-unreadable",false,false,false,"completed",true,true,true,false,false,RegisteredModelType,
            "leaf.add(FixtureId, new FixtureRegisteredModel(null, FixtureId))"),
        // 9. The model dictionary holds more entries than the per-dictionary budget allows.
        new("budget-exceeded",RegisteredModelType,RealSingletonType,"budget-exceeded","dict-entry-limit",false,false,false,"dict-entry-limit",true,true,true,false,false,null,
            "leaf filled with DefaultDictEntryLimit+1 decoy entries"),
        // 10. The singleton Lazy was never evaluated: its static storage exists but holds no value.
        new("root-uninitialized",RegisteredModelType,RealSingletonType,"root-uninitialized","lazy-not-initialized",false,true,true,"completed",true,false,false,false,false,null,
            "generic static ctor forced through an unrelated static member; the Lazy getter is never read"),
        // 11. The static storage field exists but is not a System.Lazy<T> at all.
        new("layout-unsupported",RegisteredModelType,FakeSingletonType,"layout-unsupported","lazy-value-field-missing",false,true,true,"completed",true,false,false,false,false,null,
            "second synthetic singleton whose rZmi38av5uw is a FixtureFakeLazy<T>"),
    };

    static ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre Reg()
    {
        var r = ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre.F4yixx2sq3y();
        Keep.Add(r);
        return r;
    }
    static ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre.cwS4IdY3T3bVCku4mc2X Leaf(uint a, uint b)
    {
        var n = Reg().Root.Sub(a).Sub(b);
        Keep.Add(n);
        return n;
    }
    static void Model(object o) => Keep.Add(o);

    // The fixture process plays the editor: it builds its own object graph and brings its own
    // singleton into existence. The readback tool never calls any of this on the target.
    internal static void Run(string mode)
    {
        switch (mode)
        {
            case "registered":
            {
                var m = new FixtureRegisteredModel(Program.Name, Program.FixtureId);
                Model(m);
                Leaf(10003u, 50013u).AddModel(Program.FixtureId, m);
                break;
            }
            case "heap-only":
                Leaf(10003u, 50013u);
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "path-mismatch":
                Leaf(10003u, 50014u);
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "wrong-category":
                Leaf(10003u, 50013u);
                Leaf(10003u, 50014u).AddModel(Program.FixtureId, new FixtureRegisteredModel(Program.Name, Program.FixtureId, 10003u, 50014u, 0u, 0u));
                break;
            case "wrong-id":
                Leaf(10003u, 50013u).AddModel(Program.FixtureId + 1, new FixtureRegisteredModel(OtherName, Program.FixtureId + 1));
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "different-object":
                Leaf(10003u, 50013u).AddModel(Program.FixtureId, new FixtureDecoyModel(Program.Name, Program.FixtureId));
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "field-mismatch":
                Leaf(10003u, 50013u).AddModel(Program.FixtureId, new FixtureRegisteredModel(MismatchName, Program.FixtureId));
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "unreadable":
                Leaf(10003u, 50013u).AddModel(Program.FixtureId, new FixtureRegisteredModel(null, Program.FixtureId));
                break;
            case "budget-exceeded":
            {
                var leaf = Leaf(10003u, 50013u);
                for (uint i = 0; i <= RegistryReadback.DefaultDictEntryLimit; i++) leaf.AddModel(900000u + i, new FixtureDecoyModel("bulk", 900000u + i));
                break;
            }
            case "root-uninitialized":
                // Forces the closed generic's static constructor (which creates the Lazy) without
                // ever reading its value. l03Ac3gzlWGxqiGE0Rbq is a plain unrelated static field.
                _ = yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre>.cRb12Dgzhur5WXcmgiof();
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            case "layout-unsupported":
                _ = yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxtFake<ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre>.pZgi3PiTIE8();
                Model(new FixtureRegisteredModel(Program.Name, Program.FixtureId));
                break;
            default: throw new ScopeError("UNKNOWN_REGISTRY_FIXTURE_MODE");
        }
        Console.WriteLine("registry-fixture-ready");
        Console.In.ReadLine();
        GC.KeepAlive(Keep);
    }
}
