using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// A single, short-lived experiment over one entity observed AFTER the baseline.
// No caller-supplied ids, names, RPCs, transforms, or save operations are accepted.
internal sealed partial class EditorAdapter
{
    static string CrudEntityType => B("Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr");
    const string CrudProbeName = "MW_CRUD_Probe";
    const int CrudProbeSeconds = 180;
    sealed record CrudKey(uint Category0, uint Category1, uint Category2, uint Category3, uint Id);
    sealed record CrudEntity(CrudKey Key, object Model, string Name, uint PrefabId, uint TemplateId, int EntityType, int InstanceKind);
    sealed class CrudExperiment
    {
        public required object Context;
        public required int ContextState;
        public required Dictionary<uint, CrudEntity> Baseline;
        public readonly string Id = Guid.NewGuid().ToString("N");
        public readonly DateTime BeganUtc = DateTime.UtcNow;
        public readonly Stopwatch Clock = Stopwatch.StartNew();
        public CrudEntity? Target;
        public DateTime? RegisteredUtc;
        public bool RenameSpent, RestoreSpent, DeleteSpent, AddSpent;
    }
    CrudExperiment? crudExperiment;

    CrudKey ReadCrudKey(object model)
    {
        var key = Stored(model, B("Qi8iCzKCkTt")) ?? throw new InvalidOperationException("CRUD_ENTITY_KEY_MISSING");
        return new CrudKey((uint)Field(key,B("oLyiwZX255H")), (uint)Field(key,B("AwbiwrjxUDX")),
            (uint)Field(key,B("UFWiwJNegmh")), (uint)Field(key,B("RBTiwn649Hy")), (uint)Field(key,B("namiwGPRyPS")));
    }

    Dictionary<uint, CrudEntity> ReadCrudEntities()
    {
        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");
        var result = new Dictionary<uint, CrudEntity>();
        int nodes = 0, slots = 0;
        void Visit(object node, int depth)
        {
            if (++nodes > 4096 || depth > 6) throw new InvalidOperationException("CRUD_REGISTRY_LIMIT");
            foreach (DictionaryEntry entry in (IDictionary)Field(node,B("JkmYibSuDZr")))
            {
                if (++slots > 50000) throw new InvalidOperationException("CRUD_REGISTRY_SLOT_LIMIT");
                var model = entry.Value!;
                if (model.GetType().FullName != CrudEntityType) continue;
                var key = ReadCrudKey(model);
                if (key.Id == 0 || entry.Key is not uint registryId || registryId != key.Id)
                    throw new InvalidOperationException("CRUD_REGISTRY_ID_MISMATCH");
                var item = new CrudEntity(key, model,
                    Stored(model,B("WAAiS5WkxlA")) as string ?? throw new InvalidOperationException("CRUD_ENTITY_NAME_MISSING"),
                    Convert.ToUInt32(Stored(model,B("TuuiS94iUgu")) ?? throw new InvalidOperationException("CRUD_PREFAB_ID_MISSING")),
                    ReadSceneTemplateId(model),
                    Convert.ToInt32(Stored(model,B("yEpiSj6okKa")) ?? throw new InvalidOperationException("CRUD_ENTITY_TYPE_MISSING")),
                    Convert.ToInt32(Stored(model,B("d4siSoaFICf")) ?? throw new InvalidOperationException("CRUD_INSTANCE_KIND_MISSING")));
                if (result.TryGetValue(key.Id, out var other))
                {
                    if (other.Key != key || !ReferenceEquals(other.Model, model))
                        throw new InvalidOperationException("CRUD_DUPLICATE_ENTITY_ID_CONFLICT");
                }
                else result.Add(key.Id, item);
            }
            foreach (DictionaryEntry child in (IDictionary)Field(node,B("pIxYiE5REC8"))) Visit(child.Value!, depth + 1);
        }
        Visit(Field(ExistingSingleton(Editor(), Registry),B("bwbixDw3yob")), 0);
        return result;
    }

    (object Manager, object Context, int State) CrudContext()
    {
        var manager = ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var context = Field(manager,B("Ke9indRyUDY"));
        return (manager, context, Convert.ToInt32(Field(context,B("JkFiGb7j1JI"))));
    }

    static bool SameCrudIdentity(CrudEntity expected, CrudEntity actual) => expected.Key == actual.Key &&
        ReferenceEquals(expected.Model, actual.Model) && expected.PrefabId == actual.PrefabId &&
        expected.TemplateId == actual.TemplateId &&
        expected.EntityType == actual.EntityType && expected.InstanceKind == actual.InstanceKind;

    (CrudExperiment Probe, Dictionary<uint, CrudEntity> Current) CheckCrudBaseline()
    {
        var probe = crudExperiment ?? throw new InvalidOperationException("CRUD_PROBE_NOT_BEGUN");
        if (probe.Clock.Elapsed.TotalSeconds >= CrudProbeSeconds) throw new InvalidOperationException("CRUD_PROBE_EXPIRED");
        var context = CrudContext();
        if (!ReferenceEquals(context.Context, probe.Context) || context.State != probe.ContextState)
            throw new InvalidOperationException("CRUD_CONTEXT_CHANGED");
        var current = ReadCrudEntities();
        foreach (var old in probe.Baseline.Values)
            if (!current.TryGetValue(old.Key.Id, out var now) || !SameCrudIdentity(old, now))
                throw new InvalidOperationException("CRUD_BASELINE_ENTITY_REMOVED_OR_REPLACED");
        return (probe, current);
    }

    (CrudExperiment Probe, CrudEntity Target) CheckCrudTarget()
    {
        var (probe, current) = CheckCrudBaseline();
        var target = probe.Target ?? throw new InvalidOperationException("CRUD_TARGET_NOT_REGISTERED");
        var added = current.Values.Where(e => !probe.Baseline.ContainsKey(e.Key.Id)).ToArray();
        if (added.Length != 1 || !SameCrudIdentity(target, added[0]) || added[0].EntityType != 1402 || added[0].InstanceKind != 0)
            throw new InvalidOperationException("CRUD_TARGET_IDENTITY_OR_NEW_ENTITY_SET_CHANGED");
        if (current.Values.Any(e => e.Key.Id != target.Key.Id && e.Name == CrudProbeName))
            throw new InvalidOperationException("CRUD_PROBE_NAME_CONFLICT");
        if (added[0].Name != target.Name && added[0].Name != CrudProbeName)
            throw new InvalidOperationException("CRUD_TARGET_NAME_CHANGED_EXTERNALLY");
        return (probe, added[0]);
    }

    object CrudEntityEvidence(CrudEntity entity) => new { identity = entity.Key, name = entity.Name,
        prefabId = entity.PrefabId, prefabIdSource = "editor-prefab-association-cache", prefabIdIsTemplateId = false,
        templateId = entity.TemplateId, templateIdSource = "editor-entity-config-reference",
        nativeEntityType = entity.EntityType, nativeInstanceKind = entity.InstanceKind,
        transform = TransformSnapshot(Field(entity.Model, SceneTransformField)) };

    // Registry-backed typed accessors only; no UI clicks or arbitrary getters.
    (object? Resource, string? Path, int Matches) FindCrudFrontend(CrudEntity target)
    {
        object? chosen = null; string? chosenPath = null; int matches = 0;
        var clock = Stopwatch.StartNew();
        foreach (var (node, path) in WalkEditorGraph(20000, 14, true,
                     B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH")))
        {
            if (clock.ElapsedMilliseconds > 2500) throw new InvalidOperationException("CRUD_FRONTEND_SCAN_TIME_LIMIT");
            if (node.GetType().FullName != B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7")) continue;
            var resource = Field(node,B("vQPKy8Qu9ev"));
            var folderKey = Field(resource,B("y30KBtqRTpg"));
            if (Convert.ToInt32(Field(resource,"containerType")) != 4 ||
                Convert.ToInt32(Field(folderKey,B("yKiiwIS6frK"))) != 1) continue;
            var resolve = resource.GetType().GetMethod(B("ndlKBRCbBjF"), BindingFlags.Instance | BindingFlags.Public)
                ?? throw new InvalidOperationException("CRUD_FRONTEND_TYPED_ACCESSOR_MISSING");
            var model = resolve.Invoke(resource, null);
            if (model == null || model.GetType().FullName != CrudEntityType || ReadCrudKey(model).Id != target.Key.Id) continue;
            if (!ReferenceEquals(model, target.Model) || ReadCrudKey(model) != target.Key)
                throw new InvalidOperationException("CRUD_FRONTEND_ENTITY_ID_CONFLICT");
            chosen = resource; chosenPath = path; matches++;
        }
        if (LastWalkNodesVisited >= 20000) throw new InvalidOperationException("CRUD_FRONTEND_SCAN_NODE_LIMIT");
        if (matches > 1) throw new InvalidOperationException("CRUD_FRONTEND_ENTITY_NOT_UNIQUE");
        return (chosen, chosenPath, matches);
    }

    public object BeginEntityCrudProbe()
    {
        if (crudExperiment != null) throw new InvalidOperationException("CRUD_PROBE_ALREADY_BEGUN");
        var context = CrudContext();
        var baseline = ReadCrudEntities();
        if (baseline.Count == 0) throw new InvalidOperationException("CRUD_EMPTY_BASELINE_REFUSED");
        if (baseline.Values.Any(e => e.Name == CrudProbeName)) throw new InvalidOperationException("CRUD_PROBE_NAME_CONFLICT");
        crudExperiment = new CrudExperiment { Context = context.Context, ContextState = context.State, Baseline = baseline };
        return new { ok = true, status = "entity-crud-probe-baseline-read-only", probeId = crudExperiment.Id,
            observedUtc = crudExperiment.BeganUtc, expiresUtc = crudExperiment.BeganUtc.AddSeconds(CrudProbeSeconds),
            contextState = context.State, levelIdentityVerified = false,
            baseline = baseline.Values.Select(CrudEntityEvidence).ToArray(),
            invoked = false, sentToGame = false, gameEffectVerified = false, persistentSaveVerified = false };
    }

    public object InspectEntityCrudProbe()
    {
        var (probe, current) = CheckCrudBaseline();
        var added = current.Values.Where(e => !probe.Baseline.ContainsKey(e.Key.Id)).ToArray();
        if (probe.DeleteSpent)
            return new { ok = true, status = "delete-requested-observation-only", probeId = probe.Id,
                targetAbsentFromAuxiliaryRegistry = probe.Target != null && !current.ContainsKey(probe.Target.Key.Id),
                newEntityCount = added.Length, gameEffectVerified = false, persistentSaveVerified = false };
        if (added.Length == 0 && probe.Target == null)
            return new { ok = true, status = "awaiting-one-new-test-entity", probeId = probe.Id,
                invoked = false, sentToGame = false, gameEffectVerified = false, persistentSaveVerified = false };
        if (added.Length != 1 || added[0].EntityType != 1402 || added[0].InstanceKind != 0)
            throw new InvalidOperationException("CRUD_EXPECTED_EXACTLY_ONE_NEW_1402_KIND0_ENTITY");
        if (probe.Target == null)
        {
            if (string.IsNullOrWhiteSpace(added[0].Name) || added[0].Name == CrudProbeName)
                throw new InvalidOperationException("CRUD_ORIGINAL_NAME_INVALID");
            probe.Target = added[0]; probe.RegisteredUtc = DateTime.UtcNow;
        }
        var checkedTarget = CheckCrudTarget().Target;
        var front = FindCrudFrontend(checkedTarget);
        return new { ok = true, status = front.Resource == null ? "test-entity-registered-expand-scene-folder" : "test-entity-registered-read-only",
            probeId = probe.Id, registeredUtc = probe.RegisteredUtc, expiresUtc = probe.BeganUtc.AddSeconds(CrudProbeSeconds),
            originalName = probe.Target.Name, entity = CrudEntityEvidence(checkedTarget),
            frontendMaterialized = front.Resource != null, frontendPath = front.Path,
            levelIdentityVerified = false, invoked = false, sentToGame = false,
            gameEffectVerified = false, persistentSaveVerified = false };
    }

    public object RenameEntityCrudProbe(bool restore)
    {
        var (probe, target) = CheckCrudTarget();
        if (probe.DeleteSpent) throw new InvalidOperationException("CRUD_DELETE_ALREADY_REQUESTED");
        if (restore ? probe.RestoreSpent : probe.RenameSpent) throw new InvalidOperationException("CRUD_RENAME_ALREADY_ATTEMPTED_OBSERVE_BEFORE_RETRY");
        if (restore && !probe.RenameSpent) throw new InvalidOperationException("CRUD_RENAME_NOT_REQUESTED");
        var requestedName = restore ? probe.Target!.Name : CrudProbeName;
        var expectedName = restore ? CrudProbeName : probe.Target!.Name;
        if (target.Name != expectedName) throw new InvalidOperationException("CRUD_RENAME_SOURCE_NAME_NOT_OBSERVED");
        var manager = CrudContext().Manager;
        if (!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields)!.Invoke(manager,new object[]{false})!)
            throw new InvalidOperationException("EDITOR_NOT_READY");
        CheckCrudTarget();
        // Same fixed native method as RenameRealtimeLabTree; never write model fields.
        var rename = manager.GetType().GetMethod("ModifyEditObjName", Fields)
            ?? throw new InvalidOperationException("CRUD_NATIVE_RENAME_METHOD_MISSING");
        if (restore) probe.RestoreSpent = true; else probe.RenameSpent = true;
        rename.Invoke(manager, new object[]{target.Key.Id, requestedName});
        return new { ok = true, status = restore ? "restore-name-requested-readback-pending" : "rename-requested-readback-pending",
            probeId = probe.Id, identity = target.Key, originalName = probe.Target!.Name,
            before = target.Name, requestedName, invokedUtc = DateTime.UtcNow,
            localModelWritten = false, retryAllowed = false, gameEffectVerified = false, persistentSaveVerified = false };
    }

    public object DeleteEntityCrudProbe()
    {
        var (probe, target) = CheckCrudTarget();
        if (probe.DeleteSpent) throw new InvalidOperationException("CRUD_DELETE_ALREADY_ATTEMPTED_OBSERVE_BEFORE_RETRY");
        var front = FindCrudFrontend(target);
        if (front.Resource == null)
            return new { ok = false, status = "expand-scene-folder-to-materialize-test-entity", probeId = probe.Id,
                identity = target.Key, invoked = false, sentToGame = false, gameEffectVerified = false, persistentSaveVerified = false };
        // Recheck immediately before executing the exact resource-menu method.
        var fresh = CheckCrudTarget();
        if (!SameCrudIdentity(target, fresh.Target)) throw new InvalidOperationException("CRUD_TARGET_CHANGED_DURING_PREPARATION");
        var resolve = front.Resource.GetType().GetMethod(B("ndlKBRCbBjF"), BindingFlags.Instance | BindingFlags.Public)!;
        if (!ReferenceEquals(resolve.Invoke(front.Resource,null), target.Model))
            throw new InvalidOperationException("CRUD_FRONTEND_TARGET_CHANGED");
        var delete = front.Resource.GetType().GetMethod(B("zgVKB6OS1MZ"), BindingFlags.Instance | BindingFlags.Public)
            ?? throw new InvalidOperationException("CRUD_NATIVE_DELETE_METHOD_MISSING");
        probe.DeleteSpent = true; // also spent on timeout, exception, or a native false result
        var nativeResult = delete.Invoke(front.Resource, null);
        return new { ok = true, status = "delete-path-requested-readback-pending", probeId = probe.Id,
            identity = target.Key, nativeResult, frontendPath = front.Path, invokedUtc = DateTime.UtcNow,
            retryAllowed = false, localModelWritten = false, gameEffectVerified = false, persistentSaveVerified = false,
            notice = "Native true is dispatch only; false may mean no request. Observe before further action." };
    }
}
