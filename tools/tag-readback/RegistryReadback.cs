using Microsoft.Diagnostics.Runtime;
using System.Diagnostics;

// Read-only registry membership readback.
//
// Claim under test: the tag object whose own fields carry the expected name, id and registration
// category path is THE SAME OBJECT REFERENCE that the active registry stores under that category
// path and id. Finding an object with the same name and id somewhere in the heap does NOT prove
// that (see docs/offline-research/TAG-DIAGNOSTIC.md:45 and TAG-CATEGORY-FIX.md:94).
//
// The walk mirrors the real read path (all read-only static evidence, this repository):
//   ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre.F4yixx2sq3y()
//       => yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt<Lpts7HiY2aTvYryR0pre>.pZgi3PiTIE8()
//       => static Lazy<T> rZmi38av5uw . Value            (registry-annotated.cs:1592-1596, singleton.cs:29-32)
//   registry.bwbixDw3yob                                 (registry-annotated.cs:1589)
//   node.pIxYiE5REC8[path_0] ... [path_n]                (registry-annotated.cs:397, 514-521, 1600-1618)
//       where path = the Fevvc category quad truncated at the first zero component
//       (key-registration.cs:554-615: Fevvc.ygbiwaVVVFV rebuilds the Ixx by appending each non-zero
//        component and returning at the first zero; so (10003,50013,0,0) -> [10003,50013])
//   leaf.JkmYibSuDZr[id]                                 (registry-annotated.cs:393, 720-733)
//
// No method, property getter or constructor of the target is ever invoked. Every value is read
// straight out of the object graph with ClrMD; the Lazy value is taken from its storage field and
// the Lazy getter is never called. All walks are bounded.
//
// SINGLETON STORAGE ROUTE -- a MEASURED limitation, not an assumption. Measured with ClrMD
// 3.1.512801 against the synthetic fixture (see .runtime/verification/tag-readback-registry/):
//   * ClrModule.GetTypeByName does NOT resolve generic types at all: it returns null for the
//     constructed spelling "Ns.Type<Arg>" AND for the definition spelling "Ns.Type`1". It only
//     searches type definitions.
//   * ClrModule.EnumerateTypeDefToMethodTableMap + ClrRuntime.GetTypeByMethodTable exposes only the
//     generic type DEFINITION's MethodTable, which ClrMD names "Ns.Type<T1>". Its static storage is
//     empty: measured IsInitialized=false, GetAddress=0, ReadObject=null even for the fixture case
//     in which the singleton IS initialised. Reading it would answer "uninitialized" for an
//     initialised registry -- a WRONG answer -- so it is never used as the source of truth.
//   * ClrMD 3.1 exposes no API to obtain a ClrType for a generic instantiation (no Instantiate, no
//     GetTypeByHandle; EnumerateGenericParameters only lists the formal parameters).
//   Therefore the storage object is located as the unique Lazy-shaped heap instance whose type name
//   carries the registry type name, and its value is read from the storage field. The direct
//   static-field route is still executed on every walk and reported per run (staticField* fields)
//   so the limitation stays auditable rather than hidden; StorageProvenanceTarget records the
//   compiler-generated closure of the singleton generic's own initialiser when the factory delegate
//   is still present (i.e. before the value has been produced).
internal sealed record RegistryQuery(
    string ModelTypeName,
    string SingletonTypeName,
    uint[] CategoryPath,
    string[] CategoryFieldNames,
    string IdFieldName,
    string ExpectedName,
    uint ExpectedId,
    bool SyntheticFixture)
{
    internal int DictNodeLimit { get; init; } = RegistryReadback.DefaultDictNodeLimit;
    internal int DictEntryLimit { get; init; } = RegistryReadback.DefaultDictEntryLimit;
    internal int TotalNodeLimit { get; init; } = RegistryReadback.DefaultTotalNodeLimit;
    internal int PathDepthLimit { get; init; } = RegistryReadback.DefaultPathDepthLimit;
    internal int StorageCandidateLimit { get; init; } = RegistryReadback.DefaultStorageCandidateLimit;
    internal TimeSpan TimeLimit { get; init; } = TimeSpan.FromSeconds(20);
}

internal sealed record RegistryLayout(
    string SingletonTypeNameExpected, string SingletonTypeMatchMode, string SingletonTypeNameResolved, string SingletonTypeModule, bool SingletonFound,
    string StaticFieldName, bool StaticFieldFound, string StaticFieldDeclaredType, string StaticFieldDomainUsed, bool StaticFieldReportsInitialized, bool StaticFieldReadable, bool? StaticFieldAgreesWithStorage,
    string StorageRoute, int StorageInstanceCount, string StorageObjectTypeName, string StorageLayoutKind, string StateFieldName, string ValueFieldName, bool StorageInitialized, string StorageInitReason, string StorageProvenanceTarget,
    string RegistryObjectTypeName, string RootFieldName, string NodeTypeName,
    string SubMapFieldName, string SubMapDeclaredType, string ModelMapFieldName, string ModelMapDeclaredType,
    string DictSetFieldName, string DictCountFieldName, string DictRootFieldName, string DictItemFieldName,
    string DictLeftFieldName, string DictRightFieldName, string DictPairKeyFieldName, string DictPairValueFieldName, string DictPairOffsets);

internal sealed record RegistryResult(
    string Status, string StatusDetail,
    bool RegistryMembershipVerified, bool ModelObjectMatch, bool GameVerified, bool EditorAttached, bool SyntheticFixture,
    uint[] CategoryPathExpected, uint[] WalkPathUsed, int PathResolvedDepth, string[] PathTrace,
    int DictNodesVisited, int DictEntriesVisited, int TotalNodesVisited, bool BudgetExceeded, string ScanStopReason, string BudgetLimitHit,
    long ElapsedMs,
    int HeapModelObjects, int HeapUnreadableObjects, int HeapCandidatesSameObject, bool HeapScanComplete, string HeapScanStopReason, long HeapObjectsVisited,
    string RegistryObjectTypeName, bool RegistryObjectIsModelType,
    bool RegistryObjectNameMatches, bool RegistryObjectIdMatches, bool RegistryObjectCategoryMatches, uint[] RegistryObjectCategoryValuesRead,
    bool RegistryReferenceEqualsHeapCandidate,
    RegistryLayout Layout);

internal static class RegistryReadback
{
    internal const int DefaultDictNodeLimit = 4096;
    internal const int DefaultDictEntryLimit = 4096;
    internal const int DefaultTotalNodeLimit = 16384;
    internal const int DefaultPathDepthLimit = 8;
    internal const int DefaultStorageCandidateLimit = 32;
    internal const string SingletonStaticField = "rZmi38av5uw";
    internal const string RootNodeField = "bwbixDw3yob";
    internal const string SubMapField = "pIxYiE5REC8";
    internal const string ModelMapField = "JkmYibSuDZr";
    internal const string StorageRoute = "heap-lazy-instance";

    // Every status the walk can end in, in one place, so the fixture matrix and the report cannot
    // drift apart: 根未初始化 / 布局不支持 / 读取失败 / 对象不存在 / 字段不符 / 路径不符 / 预算超限
    // plus reference-mismatch (entry points at a different object) and the only positive verdict.
    internal static readonly string[] Statuses =
    {
        "root-uninitialized", "layout-unsupported", "read-failed", "path-mismatch",
        "object-not-found", "field-mismatch", "budget-exceeded", "reference-mismatch", "confirmed-registered"
    };

    static (ClrInstanceField F, string Owner, string Name)? Resolve(ClrType? type, params string[] candidates)
    {
        for (ClrType? t = type; t != null; t = t.BaseType)
            foreach (string n in candidates)
            {
                var f = t.Fields.FirstOrDefault(x => x.Name == n);
                if (f != null) return (f, t.Name ?? "?", n);
            }
        return null;
    }

    static ClrObject ReadObj(ClrInstanceField f, ulong address) { try { return f.ReadObject(address, false); } catch { return default; } }

    // ---- SortedDictionary<K,V> layout. Field names differ between runtimes; every resolved name is
    // ---- reported so a silent fallback to a different name is visible in the evidence.
    internal sealed record DictLayout(string SetFieldName, string CountFieldName, string RootFieldName,
        string ItemFieldName, string LeftFieldName, string RightFieldName, string PairKeyFieldName, string PairValueFieldName);

    static DictLayout? ResolveDict(ClrType? dictType)
    {
        var set = Resolve(dictType, "_set");
        if (set == null) return null;
        ClrType? setType = set.Value.F.Type;
        var count = Resolve(setType, "count", "_count");
        var root = Resolve(setType, "root", "_root");
        if (count == null || root == null) return null;
        ClrType? nodeType = root.Value.F.Type;
        var item = Resolve(nodeType, "<Item>k__BackingField", "Item");
        var left = Resolve(nodeType, "<Left>k__BackingField", "Left");
        var right = Resolve(nodeType, "<Right>k__BackingField", "Right");
        if (item == null || left == null || right == null) return null;
        ClrType? pairType = item.Value.F.Type;
        var key = Resolve(pairType, "key", "_key");
        var value = Resolve(pairType, "value", "_value");
        if (key == null || value == null) return null;
        return new(set.Value.Name, count.Value.Name, root.Value.Name, item.Value.Name,
            left.Value.Name, right.Value.Name, key.Value.Name, value.Value.Name);
    }

    // Bounded key lookup. Returns (found, value, exceeded, stopReason, error). Never sorts and never
    // assumes ordering: a plain bounded traversal of the internal tree.
    //
    // The pair is read at EXPLICIT offsets through raw memory rather than as a struct-typed read.
    // Measured reason: for shared generic instantiations of
    // SortedDictionary<uint, T>, ClrMD reports the Node's item field as
    // "System.Collections.Generic.KeyValuePair<System.UInt32, System.__Canon>" -- the CLR's canonical
    // form -- and a struct-typed read of that pair returned key=0 / value=null for a dictionary that
    // provably holds one entry whose key is 10003. The offsets are taken from ClrMD's own field
    // metadata and validated structurally (key first, reference value at exactly one pointer size);
    // if that shape does not hold the lookup reports dict-pair-offset-implausible instead of
    // answering, so an unreadable layout can never be mistaken for "the key is absent".
    static (bool Found, ClrObject Value, bool Exceeded, string Stop, string? Error) DictLookup(
        ClrRuntime runtime, ClrObject dict, uint key, DictLayout lay, RegistryQuery q, ref int nodes, ref int total, Stopwatch watch, out string pairOffsets)
    {
        pairOffsets = "n/a";
        var heap = runtime.Heap;
        IMemoryReader mem = runtime.DataTarget.DataReader;
        int ptr = mem.PointerSize;
        if (!dict.IsValid || dict.IsNull) return (false, default, false, "completed", null);
        var setF = Resolve(dict.Type, lay.SetFieldName)?.F;
        if (setF == null) return (false, default, false, "completed", "dict-set-field-missing");
        var set = ReadObj(setF, dict.Address);
        if (!set.IsValid || set.IsNull) return (false, default, false, "completed", null); // empty dictionary
        var countF = Resolve(set.Type, lay.CountFieldName)?.F;
        var rootF = Resolve(set.Type, lay.RootFieldName)?.F;
        if (countF == null || rootF == null) return (false, default, false, "completed", "dict-set-layout-missing");
        if (countF.Read<int>(set.Address, false) > q.DictEntryLimit) return (false, default, true, "dict-entry-limit", null);
        var root = ObjAt(heap, mem, mem.ReadPointer(FieldAddr(rootF, set.Address)));
        if (!root.IsValid || root.IsNull) return (false, default, false, "completed", null); // empty dictionary
        var itemF = Resolve(root.Type, lay.ItemFieldName)?.F;
        var leftF = Resolve(root.Type, lay.LeftFieldName)?.F;
        var rightF = Resolve(root.Type, lay.RightFieldName)?.F;
        if (itemF == null || leftF == null || rightF == null) return (false, default, false, "completed", "dict-node-layout-missing");
        var keyF = Resolve(itemF.Type, lay.PairKeyFieldName)?.F;
        var valueF = Resolve(itemF.Type, lay.PairValueFieldName)?.F;
        if (keyF == null || valueF == null) return (false, default, false, "completed", "dict-pair-layout-missing");
        int keyOff = keyF.Offset, valOff = valueF.Offset;
        // Structural gate, not the read path: the pair must be one uint key plus one pointer-sized
        // reference value. Two orders are accepted and reported, because the CLR lays shared generic
        // instantiations out in canonical form, where the GC reference is placed FIRST -- measured
        // for KeyValuePair<UInt32, System.__Canon>: value=0, key=8. Anything else is refused instead
        // of answered, so a misunderstood layout can never be reported as "the key is absent".
        bool keyFirst = keyOff == 0 && valOff == ptr;
        bool valueFirst = valOff == 0 && keyOff == ptr;
        pairOffsets = $"key={keyOff},value={valOff},pointerSize={ptr},shape={(keyFirst ? "key-first" : valueFirst ? "value-first" : "unrecognized")},itemDeclaredType={itemF.Type?.Name ?? "?"}";
        if (!keyFirst && !valueFirst) return (false, default, false, "completed", "dict-pair-offset-implausible");
        var stack = new Stack<ClrObject>();
        stack.Push(root);
        while (stack.Count > 0)
        {
            if (++nodes > q.DictNodeLimit) return (false, default, true, "dict-node-limit", null);
            if (++total > q.TotalNodeLimit) return (false, default, true, "total-node-limit", null);
            if (watch.Elapsed > q.TimeLimit) return (false, default, true, "elapsed-time-limit", null);
            var n = stack.Pop();
            if (!n.IsValid || n.IsNull) continue;
            ulong itemAddr = FieldAddr(itemF, n.Address);
            if (itemAddr == 0) continue;
            // Inside a struct there is no object header, so the pair fields are addressed by their
            // plain Offset. (ClrField.GetAddress adds the pointer size because it treats the address
            // as an object address -- correct for Item/Left/Right/root, wrong for the pair.)
            if (mem.Read<uint>(itemAddr + (ulong)keyOff) == key) return (true, ObjAt(heap, mem, mem.ReadPointer(itemAddr + (ulong)valOff)), false, "completed", null);
            var l = ObjAt(heap, mem, mem.ReadPointer(FieldAddr(leftF, n.Address))); if (l.IsValid && !l.IsNull) stack.Push(l);
            var r = ObjAt(heap, mem, mem.ReadPointer(FieldAddr(rightF, n.Address))); if (r.IsValid && !r.IsNull) stack.Push(r);
        }
        return (false, default, false, "completed", null);
    }

    // ClrField.GetAddress is the only correct way to turn an object address plus a field into an
    // absolute address: ClrMD's Offset convention is internal to ClrMD, and doing obj.Address+Offset
    // by hand silently reads the wrong slot.
    // For an OBJECT field only. ClrField.GetAddress encodes ClrMD's internal Offset convention
    // (offset relative to the object data, i.e. after the method table pointer), which is why the
    // pointer size is added here and must NOT be added for fields inside a struct.
    static ulong FieldAddr(ClrInstanceField f, ulong parentAddress)
    {
        try { return (ulong)f.GetAddress(parentAddress, false); } catch { return 0; }
    }

    static ClrObject ObjAt(ClrHeap heap, IMemoryReader mem, ulong addr)
    {
        if (addr == 0) return default;
        try
        {
            var o = heap.GetObject(addr);
            return o.IsValid ? o : default;
        }
        catch { return default; }
    }

    internal sealed record StorageCandidate(string TypeName, ClrObject Object);
    internal sealed record HeapScan(int ModelObjects, int Unreadable, HashSet<ulong> Addresses, bool Complete, string Stop, long Visited, List<StorageCandidate> Storages, bool StorageTruncated);

    // One bounded heap pass produces both bodies of evidence: the independent "same name + same id +
    // same category object exists in the heap" candidates (addresses only, never emitted) and the
    // Lazy-shaped storage candidates for the singleton.
    static HeapScan ScanHeap(ClrRuntime runtime, RegistryQuery q, string registryTypeName, Stopwatch watch)
    {
        int modelObjects = 0, unreadable = 0; long visited = 0;
        bool complete = true; string stop = "completed"; bool truncated = false;
        var addresses = new HashSet<ulong>();
        var storages = new List<StorageCandidate>();
        foreach (var obj in runtime.Heap.EnumerateObjects())
        {
            if (++visited > Program.VisitedLimit) { complete = false; stop = "visited-object-limit"; break; }
            if (watch.Elapsed > q.TimeLimit) { complete = false; stop = "elapsed-time-limit"; break; }
            string tn = obj.Type?.Name ?? "";
            if (tn.Contains("Lazy") && tn.Contains(registryTypeName))
            {
                if (storages.Count < q.StorageCandidateLimit) storages.Add(new(tn, obj));
                else truncated = true;
            }
            if (tn != q.ModelTypeName) continue;
            if (++modelObjects > Program.TargetObjectLimit) { complete = false; stop = "target-object-limit"; break; }
            try
            {
                var r = TagFields.Read(obj, q.CategoryFieldNames, q.CategoryPath, q.IdFieldName, q.ExpectedName, q.ExpectedId);
                if (r.SameObjectMatches) addresses.Add(obj.Address);
            }
            catch { unreadable++; }
        }
        return new(modelObjects, unreadable, addresses, complete, stop, visited, storages, truncated);
    }

    // ---- Direct static-field route. Executed on every walk so the measured limitation is visible
    // ---- per run: ClrMD 3.1 exposes only the generic type DEFINITION's MethodTable, whose static
    // ---- storage is empty. The result is reported, never used as the source of truth.
    internal static (bool Found, string MatchMode, string ResolvedName, string Module, string DeclaredType, bool ReportsInitialized, bool Readable, ClrObject Value) StaticFieldProbe(ClrRuntime runtime, RegistryQuery q)
    {
        int lt = q.SingletonTypeName.IndexOf('<');
        string prefix = (lt > 0 ? q.SingletonTypeName[..lt] : q.SingletonTypeName) + "<";
        foreach (var module in runtime.EnumerateModules())
        {
            try
            {
                foreach (var pair in module.EnumerateTypeDefToMethodTableMap())
                {
                    ClrType? t;
                    try { t = runtime.GetTypeByMethodTable(pair.MethodTable); } catch { continue; }
                    string n = t?.Name ?? "";
                    if (!n.StartsWith(prefix, StringComparison.Ordinal)) continue;
                    var sf = t!.GetStaticFieldByName(SingletonStaticField);
                    if (sf == null) return (true, "open-generic-typedef-mt", n, module.Name ?? "?", "", false, false, default);
                    bool ini = false; ClrObject value = default;
                    foreach (var d in Domains(runtime))
                    {
                        try { ini = sf.IsInitialized(d); var o = sf.ReadObject(d); if (o.IsValid && !o.IsNull) value = o; } catch { }
                    }
                    return (true, "open-generic-typedef-mt", n, module.Name ?? "?", sf.Type?.Name ?? "?", ini, value.IsValid && !value.IsNull, value);
                }
            }
            catch { }
        }
        return (false, "not-found", "", "", "", false, false, default);
    }

    internal static RegistryResult Walk(ClrRuntime runtime, RegistryQuery q)
    {
        var watch = Stopwatch.StartNew();
        int nodes = 0, total = 0;
        bool budgetExceeded = false; string stopReason = "completed"; string budgetLimit = "none";
        var pathTrace = new List<string> { "root" };
        int pathResolvedDepth = 0;
        // The registration path is the Fevvc category quad truncated at the FIRST ZERO component.
        // Static evidence: resource-sync-payload/key-registration.cs:554-615 (Fevvc.ygbiwaVVVFV)
        // rebuilds the Ixx used by the lookup by appending each non-zero component and returning at
        // the first zero, so the quad (10003,50013,0,0) rebuilds to the 2-element path [10003,50013].
        // Walking the padded quad would look for sub-collections keyed 0 and would answer
        // "not registered" for a correctly registered tag -- a wrong answer, not a layout problem.
        var walkPath = new List<uint>();
        foreach (uint component in q.CategoryPath) { if (component == 0) break; walkPath.Add(component); }
        int lt = q.SingletonTypeName.IndexOf('<');
        string registryTypeName = lt > 0 ? q.SingletonTypeName[(lt + 1)..].TrimEnd('>') : q.ModelTypeName;
        // Heap evidence first: "the object exists in the heap" must be visible on every failure path.
        var hs = ScanHeap(runtime, q, registryTypeName, watch);
        bool heapComplete = hs.Complete; string heapStop = hs.Stop; long heapVisited = hs.Visited;
        int heapModelObjects = hs.ModelObjects, heapUnreadable = hs.Unreadable, heapCandidates = hs.Addresses.Count;
        var candidateAddresses = hs.Addresses;
        ClrObject regObj = default;
        TagReadResult? regRead = null; bool refEq = false;
        string regObjTypeName = "";
        uint[] regCatRead = Array.Empty<uint>();

        string singletonMode = "none", singletonResolved = "", singletonModule = ""; bool singletonFound = false;
        string staticDeclaredType = "", staticDomain = "none";
        bool staticInit = false, staticReadable = false; bool? staticAgrees = null; ClrObject staticValue = default;
        string storageTypeName = "", storageKind = "none", stateFieldName = "none", valueFieldName = "none", storageReason = "", provenance = "none";
        bool storageInitialized = false; int storageCount = 0;
        string rootFieldName = "none", nodeTypeName = "none";
        string subMapName = "none", subMapDeclared = "none", modelMapName = "none", modelMapDeclared = "none";
        string dictSet = "none", dictCount = "none", dictRoot = "none", dictItem = "none", dictLeft = "none", dictRight = "none", dictKey = "none", dictValue = "none", dictPairOffsets = "n/a";

        RegistryLayout Layout() => new(q.SingletonTypeName, singletonMode, singletonResolved, singletonModule, singletonFound,
            SingletonStaticField, staticDeclaredType.Length > 0, staticDeclaredType, staticDomain, staticInit, staticReadable, staticAgrees,
            StorageRoute, storageCount, storageTypeName, storageKind, stateFieldName, valueFieldName, storageInitialized, storageReason, provenance,
            regObjTypeName, rootFieldName, nodeTypeName, subMapName, subMapDeclared, modelMapName, modelMapDeclared,
            dictSet, dictCount, dictRoot, dictItem, dictLeft, dictRight, dictKey, dictValue, dictPairOffsets);

        RegistryResult Make(string status, string why) => new(
            status, why, status == "confirmed-registered", heapCandidates > 0, false, false, q.SyntheticFixture,
            q.CategoryPath, walkPath.ToArray(), pathResolvedDepth, pathTrace.ToArray(),
            nodes, nodes, total, budgetExceeded, stopReason, budgetLimit, watch.ElapsedMilliseconds,
            heapModelObjects, heapUnreadable, heapCandidates, heapComplete, heapStop, heapVisited,
            regObjTypeName, regObjTypeName == q.ModelTypeName,
            regRead?.NameMatches ?? false, regRead?.IdMatches ?? false, regRead?.CategoryMatches ?? false, regCatRead,
            refEq, Layout());
        // An incomplete heap walk can never be upgraded into a positive membership verdict, even if
        // the registry path itself resolved cleanly.
        RegistryResult Finish(string status, string why) =>
            !heapComplete && status == "confirmed-registered"
                ? Make("budget-exceeded", "heap-scan-incomplete:" + heapStop) with { BudgetExceeded = true, ScanStopReason = heapStop, BudgetLimitHit = "HeapVisitedLimit/HeapTargetObjectLimit/TimeLimit" }
                : Make(status, why);

        // 1. direct static-field route (attempted and reported; see the header for the measurement)
        var sfp = StaticFieldProbe(runtime, q);
        singletonFound = sfp.Found; singletonMode = sfp.MatchMode; singletonResolved = sfp.ResolvedName; singletonModule = sfp.Module;
        staticDeclaredType = sfp.DeclaredType; staticInit = sfp.ReportsInitialized; staticReadable = sfp.Readable; staticValue = sfp.Value;
        if (sfp.Readable) staticDomain = Domains(runtime).Select(d => d.Name ?? "?").FirstOrDefault() ?? "?";

        // 2. singleton storage: the unique Lazy-shaped heap instance carrying the registry type name
        storageCount = hs.Storages.Count;
        if (storageCount == 0) return Finish("layout-unsupported", "singleton-storage-not-found");
        var withValue = new List<(StorageCandidate C, ClrInstanceField F, string Kind, string Name)>();
        foreach (var c in hs.Storages)
        {
            var vf = Resolve(c.Object.Type, "_value", "m_value", "m_boxed");
            if (vf != null) withValue.Add((c, vf.Value.F, vf.Value.Name == "m_boxed" ? "legacy-boxed" : "netcore", vf.Value.Name));
        }
        if (withValue.Count == 0) { storageTypeName = hs.Storages[0].TypeName; return Finish("layout-unsupported", "lazy-value-field-missing"); }
        if (withValue.Count > 1) return Finish("layout-unsupported", $"singleton-storage-ambiguous:{withValue.Count}");
        var (chosen, valueField, kind, vfName) = withValue[0];
        storageTypeName = chosen.TypeName; storageKind = kind; valueFieldName = vfName;
        if (staticValue.IsValid && !staticValue.IsNull) staticAgrees = staticValue.Address == chosen.Object.Address;

        // 3. the Lazy's already-produced value, read from the storage field. The getter is never called.
        if (kind == "netcore")
        {
            var stateField = Resolve(chosen.Object.Type, "_state");
            if (stateField != null)
            {
                stateFieldName = stateField.Value.Name;
                var st = ReadObj(stateField.Value.F, chosen.Object.Address);
                storageInitialized = !(st.IsValid && !st.IsNull);
                storageReason = storageInitialized ? "state-null" : "state-nonnull";
            }
            else { storageInitialized = true; storageReason = "no-state-field"; }
        }
        else
        {
            var initField = Resolve(chosen.Object.Type, "m_initialized");
            if (initField != null) { stateFieldName = initField.Value.Name; storageInitialized = initField.Value.F.Read<int>(chosen.Object.Address, false) != 0; storageReason = "legacy-initialized-flag"; }
            else { storageInitialized = true; storageReason = "no-init-field"; }
        }
        // Provenance: before the value is produced the factory delegate is still present and its
        // target is the compiler-generated closure of the singleton generic's static initialiser.
        // After initialisation the runtime clears the factory, so that case is reported as
        // "unavailable-after-init" rather than guessed.
        var factoryField = Resolve(chosen.Object.Type, "_factory");
        if (factoryField != null)
        {
            var fac = ReadObj(factoryField.Value.F, chosen.Object.Address);
            if (fac.IsValid && !fac.IsNull)
            {
                var targetField = Resolve(fac.Type, "_target");
                var tgt = targetField == null ? default : ReadObj(targetField.Value.F, fac.Address);
                provenance = tgt.IsValid && !tgt.IsNull ? (tgt.Type?.Name ?? "?") : "factory-without-target";
            }
            else provenance = "unavailable-after-init";
        }
        else provenance = "no-factory-field";
        if (!storageInitialized) return Finish("root-uninitialized", "lazy-not-initialized");
        var regCandidate = ReadObj(valueField, chosen.Object.Address);
        if (!regCandidate.IsValid || regCandidate.IsNull) return Finish("root-uninitialized", "registry-object-null");
        regObj = regCandidate; regObjTypeName = regObj.Type?.Name ?? "?";

        // 4. registry root node
        var rootField = Resolve(regObj.Type, RootNodeField);
        if (rootField == null) return Finish("layout-unsupported", "root-field-missing");
        rootFieldName = rootField.Value.Name;
        var node = ReadObj(rootField.Value.F, regObj.Address);
        if (!node.IsValid || node.IsNull) return Finish("root-uninitialized", "root-node-null");
        nodeTypeName = node.Type?.Name ?? "?";

        // 5. category path walk: registry.bwbixDw3yob -> pIxYiE5REC8[..] -> ...
        if (walkPath.Count > q.PathDepthLimit) { budgetExceeded = true; stopReason = "path-depth-limit"; budgetLimit = "PathDepthLimit"; return Finish("budget-exceeded", "path-depth-limit"); }
        if (walkPath.Count == 0) return Finish("path-mismatch", "path-empty:all-category-components-zero");
        for (int i = 0; i < walkPath.Count; i++)
        {
            var subF = Resolve(node.Type, SubMapField);
            if (subF == null) return Finish("layout-unsupported", "sub-map-field-missing");
            subMapName = subF.Value.Name; subMapDeclared = subF.Value.F.Type?.Name ?? "?";
            var subDict = ReadObj(subF.Value.F, node.Address);
            var lay = ResolveDict(subDict.Type ?? node.Type);
            if (lay == null) return Finish("layout-unsupported", "dict-layout-unsupported:sub");
            (dictSet, dictCount, dictRoot, dictItem, dictLeft, dictRight, dictKey, dictValue) =
                (lay.SetFieldName, lay.CountFieldName, lay.RootFieldName, lay.ItemFieldName, lay.LeftFieldName, lay.RightFieldName, lay.PairKeyFieldName, lay.PairValueFieldName);
            var (found, value, exceeded, stop, err) = DictLookup(runtime, subDict, walkPath[i], lay, q, ref nodes, ref total, watch, out dictPairOffsets);
            if (exceeded) { budgetExceeded = true; stopReason = stop; budgetLimit = "DictNodeLimit/DictEntryLimit/TotalNodeLimit/TimeLimit"; return Finish("budget-exceeded", stop); }
            if (err != null) return Finish(err.Contains("unreadable") ? "read-failed" : "layout-unsupported", err);
            if (!found) return Finish("path-mismatch", $"path-key-absent:{walkPath[i]}@depth:{i}");
            if (!value.IsValid || value.IsNull) return Finish("path-mismatch", $"path-node-null:{walkPath[i]}@depth:{i}");
            node = value; pathTrace.Add(walkPath[i].ToString()); pathResolvedDepth = i + 1;
        }

        // 6. model dictionary entry: leaf.JkmYibSuDZr[id]
        var modelF = Resolve(node.Type, ModelMapField);
        if (modelF == null) return Finish("layout-unsupported", "model-map-field-missing");
        modelMapName = modelF.Value.Name; modelMapDeclared = modelF.Value.F.Type?.Name ?? "?";
        var modelDict = ReadObj(modelF.Value.F, node.Address);
        var mlay = ResolveDict(modelDict.Type ?? node.Type);
        if (mlay == null) return Finish("layout-unsupported", "dict-layout-unsupported:model");
        var (mFound, mValue, mExceeded, mStop, mErr) = DictLookup(runtime, modelDict, q.ExpectedId, mlay, q, ref nodes, ref total, watch, out dictPairOffsets);
        if (mExceeded) { budgetExceeded = true; stopReason = mStop; budgetLimit = "DictNodeLimit/DictEntryLimit/TotalNodeLimit/TimeLimit"; return Finish("budget-exceeded", mStop); }
        if (mErr != null) return Finish(mErr.Contains("unreadable") ? "read-failed" : "layout-unsupported", mErr);
        if (!mFound) return Finish("object-not-found", $"model-key-absent:{q.ExpectedId}");
        if (!mValue.IsValid || mValue.IsNull) return Finish("object-not-found", "model-entry-null");
        regObj = mValue; regObjTypeName = regObj.Type?.Name ?? "?";

        // 7. the registry entry's own identity fields, via the SAME reader the heap scan uses
        try { regRead = TagFields.Read(regObj, q.CategoryFieldNames, q.CategoryPath, q.IdFieldName, q.ExpectedName, q.ExpectedId); regCatRead = regRead.CategoryValuesRead; }
        catch (ScopeError) { return Finish("read-failed", "registry-object-fields-unreadable"); }
        if (!regRead.NameMatches || !regRead.IdMatches || !regRead.CategoryMatches)
        {
            var which = new List<string>();
            if (!regRead.NameMatches) which.Add("name");
            if (!regRead.IdMatches) which.Add("id");
            if (!regRead.CategoryMatches) which.Add("category");
            return Finish("field-mismatch", "registry-object-field-mismatch:" + string.Join("+", which));
        }

        // 8. reference identity: is the object the registry stores the very object the heap scan
        //    independently identified by name+id+category? (addresses never leave this method)
        refEq = candidateAddresses.Contains(regObj.Address);
        if (!refEq) return Finish("reference-mismatch", regObjTypeName == q.ModelTypeName ? "no-heap-object-with-same-identity-is-this-reference" : "registry-object-type-is-not-the-model-type");
        return Finish("confirmed-registered", "path-resolved+identity-fields-match+same-reference-as-heap-object");
    }

    static IEnumerable<ClrAppDomain> Domains(ClrRuntime runtime)
    {
        ClrAppDomain? a = null, b = null, c = null;
        try { a = runtime.SharedDomain; } catch { }
        try { b = runtime.SystemDomain; } catch { }
        try { var arr = runtime.AppDomains; if (arr.Length > 0) c = arr[0]; } catch { }
        if (a != null) yield return a;
        if (b != null) yield return b;
        if (c != null) yield return c;
    }
}
