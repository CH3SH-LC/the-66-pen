using System;
using System.IO;
using System.Security.Cryptography;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Bounded delete of GRAPH resources named explicitly by id.
//
// Why this exists: tools/editor-bridge/Adapter/GameLoopGraph.cs:195 states it outright --
// "There is no delete-graph operation in this project's surface". Earlier campaigns created
// graphs in the test level and had no way to remove them, so the level permanently carries
// MW_API_Update71_20260926, MW_Bridge_Import_20260916 and MW_MVP_Course_20260922. Any new
// graph work needs a way back out first, or it repeats that cost.
//
// The boundary is deliberately the narrowest one that solves the problem:
//   * The entry must be a Kind-9 resource, decided by the SAME Resources() walk the rest of
//     the bridge uses, so this operation cannot disagree with it about what a graph is.
//   * Its stored NAME must start with "MW_" -- this project's own naming for graphs it
//     created. A graph someone else made cannot be deleted even if its id is supplied.
//   * 1..64 distinct non-zero uint32 ids, validated upstream by the client, the runner and
//     ReadUintArray before the request arrives.
//   * EVERY id must resolve to exactly one matching graph; one unresolved or ambiguous id
//     refuses the WHOLE list and deletes nothing.
//   * dry-run reports the id -> name mapping and invokes no delete.
//   * immediately before each delete, the graph is re-read and must still carry the same id
//     AND the same name.
internal sealed partial class EditorAdapter
{
    // 2026-10-06: raised 20000 -> 200000, the same change and for the same reason as the
    // sibling entity deleter (OwnedEntityDelete.cs). A level carrying 479 placed entities
    // makes the walk reach 20000 nodes, and the whole call refuses with
    // OWNED_GRAPH_SCAN_NODE_LIMIT before it resolves a single graph id. 200000 is the bound
    // PanelOpen already walks with on this editor, so it is tested, not guessed.
    //
    // Raising a cap does not weaken the fail-closed property, and the reason is the same
    // here: the cap only decides whether the walk finished. A missing or twice-reached id
    // still refuses below, and a larger cap can only turn "refused: graph too big" into
    // "walked the whole graph", never into a wrong delete.
    const int OwnedGraphDeleteScanNodes = 200000;
    const int OwnedGraphDeleteScanDepth = 14;
    const string OwnedGraphDeleteNamePrefix = "MW_";

    // Filled by BuildOwnedGraphIndex and returned with a refusal, so an empty index can be
    // diagnosed without another round trip. "It found nothing" is not a useful report; WHERE
    // it stopped finding things is.
    string ownedGraphDiagnostics = "";

    // Diagnostic only; it never decides whether a delete happens. Filled by
    // BuildOwnedGraphIndex and returned with a refusal so that ONE live dry-run answers
    // "why did the identity match fail" instead of another round of guessing.
    //
    // WHY IT IS NEEDED AND WHY IT IS NOT A FIX. Every recorded attempt to resolve an
    // owned graph id -- 2026-10-06 11:24, 2026-10-06 13:12 and 2026-10-09 01:23 -- came
    // back modelMatched=0, across candidate sets of 48, 499 and 31. The operation has
    // never once succeeded, and the shape of the counters (resourceRead == accessorFound
    // == hasDeleteMethod, with modelMatched stuck at zero) localises the failure to the
    // step that matches a node-resolved model against a Resources() Kind-9 model by
    // reference identity. The comment above asserts those are "the same model objects,
    // not copies"; four measurements say that assertion does not hold for graphs.
    //
    // The reason it is a DIAGNOSTIC and not a rewrite: the replacement predicate has to
    // be chosen from evidence. Three extractions could each plausibly carry the id on the
    // node side -- the entity key reader, the two-level wrapper key path ResourcesCore
    // itself uses for Kind 9, or the flat id field -- and none of them has ever been
    // exercised on a graph model. (The re-check further down calls ReadCrudKey on the
    // node-resolved model, but it sits AFTER the match, so it has never run.) This records
    // which extraction is readable and which one actually reaches the id, so the fix is
    // read off a receipt rather than assumed.
    Dictionary<string, object> ownedGraphMatchDiagnostics = new();

    // Every probe is individually contained: a field path that does not apply to this
    // model throws, and that is an expected outcome to record, not a failure to raise.
    uint? ProbeEntityKeyId(object model)
    {
        try { return ReadCrudKey(model).Id; } catch (Exception) { return null; }
    }
    uint? ProbeWrapperKeyId(object model)
    {
        try { return (uint)Field(Field(Field(model, B("fLGKbbHeoYG")), B("VpIiRZgdEln")), B("namiwGPRyPS")); }
        catch (Exception) { return null; }
    }
    uint? ProbeFlatId(object model)
    {
        try { return (uint)Field(model, B("namiwGPRyPS")); } catch (Exception) { return null; }
    }
    string? SafeGraphName(object model, string field)
    {
        try { return Stored(model, field) as string; } catch (Exception) { return null; }
    }

    Dictionary<uint, object> BuildOwnedGraphIndex(out Dictionary<uint, string> names,
                                                  Dictionary<uint, string>? paths, out HashSet<uint> ambiguous)
    {
        // The resource-manager item carries the same wrapper its delete menu invokes.
        // SRFKBNXKB02 returns a graph; ndlKBRCbBjF is the entity-only accessor.
        string resolveName = B("SRFKBNXKB02");
        string resourceField = B("nDdKtzI6RIf");
        string graphNameField = B("c1pKbESgr8S");
        string deleteName = B("zgVKB6OS1MZ");
        var graphResourceNodeType = Editor().GetType(B("kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0"), true)!;

        // Step 1: ask the RESOURCE WALK what the graphs are. Resources() is the single
        // authority the rest of the bridge uses to decide Kind 9. Reference identity is the
        // key: the walk and the node scan hand back the same model objects, not copies.
        var graphModels = new Dictionary<object, uint>(ReferenceEqualityComparer.Instance);
        foreach (var r in Resources())
            if (r.Kind == 9) graphModels[r.Model] = r.Id;
        if (graphModels.Count == 0)
            throw new InvalidOperationException("OWNED_GRAPH_NO_GRAPHS_VISIBLE");

        var index = new Dictionary<uint, object>();
        names = new Dictionary<uint, string>();
        if (paths != null) paths.Clear();
        ambiguous = new HashSet<uint>();

        int nodes = 0, resourceRead = 0, accessorFound = 0, hasDeleteMethod = 0, modelMatched = 0, threw = 0;

        // Diagnostic counters; none of them feeds a delete decision.
        var kind9Ids = new HashSet<uint>(graphModels.Values);
        var candidateTypes = new Dictionary<string, int>();
        var candidateIds = new List<uint>();
        int entityKeyReadable = 0, entityKeyMatched = 0;
        int wrapperKeyReadable = 0, wrapperKeyMatched = 0;
        int flatReadable = 0, flatMatched = 0;

        // Graph resources are in the resource-manager panel, not the scene VM subtree.
        // Walk the existing bounded window roots and select the registered resource-item
        // type (including derived items); the graph model must still match by identity.
        foreach (var (node, nodePath) in WalkEditorGraph(OwnedGraphDeleteScanNodes, OwnedGraphDeleteScanDepth, true))
        {
            nodes++;
            if (!graphResourceNodeType.IsInstanceOfType(node)) continue;
            object model, resource;
            try
            {
                resource = Field(node, resourceField);
                resourceRead++;
                var resolve = resource.GetType().GetMethod(resolveName, BindingFlags.Instance | BindingFlags.Public);
                if (resolve == null) continue;
                accessorFound++;
                // This is the native resource menu delete, whose Kind-9 branch handles graphs.
                if (resource.GetType().GetMethod(deleteName, BindingFlags.Instance | BindingFlags.Public) == null)
                    continue;
                hasDeleteMethod++;
                model = resolve.Invoke(resource, null);
            }
            catch (Exception) { threw++; continue; }
            if (model == null) continue;

            // Record what this candidate actually is, and which id extraction reaches it.
            var candidateType = model.GetType().FullName ?? "(no-full-name)";
            candidateTypes[candidateType] = candidateTypes.GetValueOrDefault(candidateType) + 1;
            var entityKeyId = ProbeEntityKeyId(model);
            if (entityKeyId.HasValue)
            {
                entityKeyReadable++;
                if (candidateIds.Count < 40) candidateIds.Add(entityKeyId.Value);
                if (kind9Ids.Contains(entityKeyId.Value)) entityKeyMatched++;
            }
            var wrapperKeyId = ProbeWrapperKeyId(model);
            if (wrapperKeyId.HasValue)
            {
                wrapperKeyReadable++;
                if (candidateIds.Count < 40) candidateIds.Add(wrapperKeyId.Value);
                if (kind9Ids.Contains(wrapperKeyId.Value)) wrapperKeyMatched++;
            }
            var flatId = ProbeFlatId(model);
            if (flatId.HasValue)
            {
                flatReadable++;
                if (candidateIds.Count < 40) candidateIds.Add(flatId.Value);
                if (kind9Ids.Contains(flatId.Value)) flatMatched++;
            }

            if (!graphModels.TryGetValue(model, out uint id)) continue;
            modelMatched++;
            string? storedName;
            try { storedName = Stored(model, graphNameField) as string; }
            catch (Exception) { continue; }
            if (storedName == null || !storedName.StartsWith(OwnedGraphDeleteNamePrefix, StringComparison.Ordinal))
                continue;
            if (index.ContainsKey(id)) { ambiguous.Add(id); continue; }
            index[id] = resource;
            names[id] = storedName;
            if (paths != null) paths[id] = nodePath;
        }
        if (LastWalkNodesVisited >= OwnedGraphDeleteScanNodes)
            throw new InvalidOperationException("OWNED_GRAPH_SCAN_NODE_LIMIT");
        ownedGraphDiagnostics = string.Format(
            "graphModelsVisible={0} nodes={1} resourceRead={2} accessorFound={3} hasDeleteMethod={4} modelMatched={5} accessorThrew={6}",
            graphModels.Count, nodes, resourceRead, accessorFound, hasDeleteMethod, modelMatched, threw);

        // What the Kind-9 side believes the graphs are, what the node-walk side actually
        // yielded, and which id extraction (if any) bridges the two. A single line here
        // decides whether the fix is "match by id via probe X" or "the walk root is wrong".
        ownedGraphMatchDiagnostics = new Dictionary<string, object> {
            ["kind9Count"] = graphModels.Count,
            ["kind9Visible"] = graphModels.Select(kv => new {
                id = kv.Value, name = SafeGraphName(kv.Key, graphNameField) }).Take(20).ToArray(),
            ["candidateModelTypes"] = candidateTypes.OrderByDescending(kv => kv.Value).Take(6)
                .Select(kv => new { type = kv.Key, count = kv.Value }).ToArray(),
            ["candidateIdExtraction"] = new {
                entityKey = new { readable = entityKeyReadable, matchesKind9 = entityKeyMatched },
                wrapperKey = new { readable = wrapperKeyReadable, matchesKind9 = wrapperKeyMatched },
                flat = new { readable = flatReadable, matchesKind9 = flatMatched },
            },
            ["candidateIdsSample"] = candidateIds.Distinct().Take(24).ToArray(),
        };
        return index;
    }

    const uint UnsavedProbeGraphId = 1073741834u;
    const uint UnsavedProbeLevelId = 1073741842u;
    const string UnsavedProbeGraphName = "MW_API_DICTKIND_PROBE";
    const string UnsavedProbeFormalPath = @"C:\Users\PUBLIC_USER\AppData\LocalLow\miHoYo\原神\BeyondLocal\100000001\Beyond_Local_Save_Level\1073741842\1073741842.gil";
    // Parent read-only evidence: probe-absent-from-save.json, unchanged initial backup.
    // Root10 excludes this graph id and name; known saved graph is a positive control.
    // This hash pins that absence evidence; a hash alone would not prove absence.
    const string UnsavedProbeApprovedFormalSha256 = "f32fc618d4c88cce48bd784e5dad786fd60d4c7c05fd01f8a0aba0233b575142";
    bool unsavedProbeDeleteAttempted;

    void RequireUnsavedProbeFormalEvidence()
    {
        if (UnsavedProbeApprovedFormalSha256.Length != 64 ||
            !UnsavedProbeApprovedFormalSha256.All(Uri.IsHexDigit))
            throw new InvalidOperationException("UNSAVED_PROBE_FORMAL_ABSENCE_NOT_APPROVED");
        using var sha = SHA256.Create();
        using var file = File.OpenRead(UnsavedProbeFormalPath);
        var actual = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "");
        if (!string.Equals(actual, UnsavedProbeApprovedFormalSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("UNSAVED_PROBE_FORMAL_FILE_CHANGED");
    }

    (object Category, uint Id) UnsavedProbeKey(object model)
    {
        // Exact getter used by native Kind-9 menu. Preserve its boxed editor enum;
        // Resource.Category is a uint[] and is NEVER passed as this argument.
        var category = model.GetType().GetMethod(B("xkKXuat764s"), Fields, null, Type.EmptyTypes, null);
        var id = model.GetType().GetMethod(B("MexKm2jjjVm"), Fields, null, Type.EmptyTypes, null);
        if (category == null || category.IsStatic || !category.ReturnType.IsEnum ||
            id == null || id.IsStatic || id.ReturnType != typeof(uint))
            throw new InvalidOperationException("UNSAVED_PROBE_KEY_CONTRACT");
        return (category.Invoke(model, null)!, (uint)id.Invoke(model, null)!);
    }

    object DeleteSingleUnsavedProbe(uint[] ids, bool dryRun)
    {
        RequireInitDispatcher();
        if (ids == null || ids.Length != 1 || ids[0] != UnsavedProbeGraphId)
            throw new InvalidOperationException("UNSAVED_PROBE_ONLY_SINGLE_APPROVED_ID");
        if (unsavedProbeDeleteAttempted)
            throw new InvalidOperationException("UNSAVED_PROBE_DELETE_ALREADY_ATTEMPTED");

        // Retained initialization identity is a guard, not proof of a fresh load.
        // Parent must independently confirm the current level before authorization.
        var identity = ContentIdentity();
        if (identity.Id != UnsavedProbeLevelId)
            throw new InvalidOperationException("UNSAVED_PROBE_WRONG_LEVEL");
        var matches = Resources().Where(r => r.Kind == 9 && r.Id == UnsavedProbeGraphId).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("UNSAVED_PROBE_MISSING_OR_AMBIGUOUS");
        var target = matches[0];
        var name = Stored(target.Model, B("c1pKbESgr8S")) as string;
        if (name != UnsavedProbeGraphName || !name.StartsWith(OwnedGraphDeleteNamePrefix, StringComparison.Ordinal))
            throw new InvalidOperationException("UNSAVED_PROBE_NAME_CHANGED");
        var key = UnsavedProbeKey(target.Model);
        if (key.Id != UnsavedProbeGraphId || InstructionGraphBoundEntities(UnsavedProbeGraphId).Count != 0)
            throw new InvalidOperationException("UNSAVED_PROBE_ID_CHANGED_OR_BOUND");

        if (dryRun)
            return new { ok = true, status = "dry-run-mapping-only", dryRun = true,
                requested = 1, resolvedCount = 1,
                mapping = new[] { new { id = UnsavedProbeGraphId, name, levelId = identity.Id } },
                source = "current-kind9-registry", formalAbsenceApproved = false,
                invoked = false, localModelWritten = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false };

        RequireUnsavedProbeFormalEvidence();
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var delete = manager.GetType().GetMethod(B("ullXqoLREqk"), Fields, null,
            new[] { key.Category.GetType(), typeof(uint) }, null);
        var ready = manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields, null,
            new[] { typeof(bool) }, null);
        if (delete == null || delete.IsStatic || delete.ReturnType != typeof(void) ||
            ready == null || ready.IsStatic || ready.ReturnType != typeof(bool))
            throw new InvalidOperationException("UNSAVED_PROBE_NATIVE_CONTRACT");
        if (!(bool)ready.Invoke(manager, new object[] { true })!)
            throw new InvalidOperationException("EDITOR_NOT_READY_TO_DELETE");

        // No save, graph creation or retry between these checks and the one call.
        RequireUnsavedProbeFormalEvidence();
        var freshIdentity = ContentIdentity();
        if (freshIdentity.Id != UnsavedProbeLevelId || !ReferenceEquals(identity.Payload, freshIdentity.Payload))
            throw new InvalidOperationException("UNSAVED_PROBE_LEVEL_CHANGED");
        var current = Resources().Where(r => r.Kind == 9 && r.Id == UnsavedProbeGraphId).ToArray();
        if (current.Length != 1 || !ReferenceEquals(current[0].Model, target.Model) ||
            !current[0].Category.SequenceEqual(target.Category))
            throw new InvalidOperationException("UNSAVED_PROBE_TARGET_CHANGED");
        var freshName = Stored(current[0].Model, B("c1pKbESgr8S")) as string;
        var freshKey = UnsavedProbeKey(current[0].Model);
        if (freshName != UnsavedProbeGraphName || freshKey.Id != UnsavedProbeGraphId ||
            !Equals(freshKey.Category, key.Category) ||
            InstructionGraphBoundEntities(UnsavedProbeGraphId).Count != 0)
            throw new InvalidOperationException("UNSAVED_PROBE_TARGET_CHANGED_OR_BOUND");

        unsavedProbeDeleteAttempted = true;
        // Native instance method includes graph lookup and service/delete dispatch.
        // Attempt remains spent even when native invocation throws.
        delete.Invoke(manager, new object[] { freshKey.Category, freshKey.Id });
        return new { ok = true, status = "delete-requested-readback-pending", dryRun = false,
            requested = 1, invokedCount = 1, retryAllowed = false,
            graphId = UnsavedProbeGraphId, levelId = UnsavedProbeLevelId,
            localModelWritten = false, gameEffectVerified = false, persistentSaveVerified = false,
            notice = "One native dispatch only. Resource disappearance and persistence require independent readback." };
    }

    public object DeleteOwnedGraphIds(uint[] ids, bool dryRun)
    {
        if (ids != null && ids.Contains(UnsavedProbeGraphId))
            return DeleteSingleUnsavedProbe(ids, dryRun);
        if (ids == null || ids.Length == 0) throw new InvalidOperationException("OWNED_GRAPH_IDS_REQUIRED");
        if (ids.Length > 64) throw new InvalidOperationException("OWNED_GRAPH_TOO_MANY_IDS");
        if (ids.Distinct().Count() != ids.Length) throw new InvalidOperationException("OWNED_GRAPH_DUPLICATE_ID");

        var paths = new Dictionary<uint, string>();
        var index = BuildOwnedGraphIndex(out var names, paths, out var ambiguous);
        var resolved = new List<(uint Id, object Resource, string Name)>();
        var unresolved = new List<object>();
        foreach (uint id in ids)
        {
            if (ambiguous.Contains(id)) unresolved.Add(new { id, reason = "ambiguous", matches = 2 });
            else if (index.TryGetValue(id, out var resource)) resolved.Add((id, resource, names[id]));
            else unresolved.Add(new { id, reason = "not-a-project-named-graph-visible-to-this-scan", matches = 0 });
        }
        if (unresolved.Count != 0)
            return new { ok = false, status = "refused-unresolved-ids", dryRun,
                requested = ids.Length, resolvedCount = resolved.Count, unresolved,
                indexSize = index.Count, diagnostics = ownedGraphDiagnostics,
                matchDiagnostics = ownedGraphMatchDiagnostics,
                invoked = false, localModelWritten = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false,
                notice = "No delete was invoked. An id that is not a MW_-named graph refuses the whole list." };

        // Resources() populated entityModels during indexing. Refuse the whole batch
        // before any dispatch if a requested graph is still attached to gameplay.
        foreach (var target in resolved)
            if (InstructionGraphBoundEntities(target.Id).Count != 0)
                throw new InvalidOperationException("OWNED_GRAPH_BOUND:" + target.Id);

        if (dryRun)
            return new { ok = true, status = "dry-run-mapping-only", dryRun = true,
                requested = ids.Length, resolvedCount = resolved.Count,
                mapping = resolved.Select(r => new { id = r.Id, name = r.Name, frontendPath = paths[r.Id] }).ToArray(),
                diagnostics = ownedGraphDiagnostics,
                invoked = false, localModelWritten = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false,
                notice = "Mapping only; no native delete was invoked." };

        string deleteName = B("zgVKB6OS1MZ");
        string recheckResolve = B("SRFKBNXKB02");
        string graphNameField2 = B("c1pKbESgr8S");
        var results = new List<object>();
        int invoked = 0;
        foreach (var (id, resource, name) in resolved)
        {
            // Re-check immediately before this delete: same id AND same name on the model the
            // typed accessor returns right now.
            var recheck = resource.GetType().GetMethod(recheckResolve, BindingFlags.Instance | BindingFlags.Public);
            string? freshName = null;
            uint freshId = 0;
            bool ok = false;
            try
            {
                var freshModel = recheck == null ? null : recheck.Invoke(resource, null);
                if (freshModel != null)
                {
                    var currentGraphs = Resources().Where(r => r.Kind == 9 && r.Id == id).ToArray();
                    freshName = Stored(freshModel, graphNameField2) as string;
                    var graphKey = Stored(freshModel, B("fLGKbbHeoYG"));
                    freshId = (uint)Field(graphKey!, B("namiwGPRyPS"));
                    ok = currentGraphs.Length == 1 && ReferenceEquals(currentGraphs[0].Model, freshModel)
                        && InstructionGraphBoundEntities(id).Count == 0;
                }
            }
            catch (Exception) { ok = false; }
            if (!ok || freshId != id || freshName != name ||
                !(freshName ?? "").StartsWith(OwnedGraphDeleteNamePrefix, StringComparison.Ordinal))
            {
                results.Add(new { id, name, invoked = false,
                    error = "OWNED_GRAPH_TARGET_CHANGED_DURING_PREPARATION" });
                break;
            }
            var delete = resource.GetType().GetMethod(deleteName, BindingFlags.Instance | BindingFlags.Public);
            if (delete == null)
            {
                results.Add(new { id, name, invoked = false, error = "OWNED_GRAPH_NATIVE_METHOD_MISSING" });
                break;
            }
            object? nativeResult;
            try { nativeResult = delete.Invoke(resource, null); invoked++; }
            catch (Exception ex) { nativeResult = "threw:" + ex.GetType().Name + ":" + ex.Message; }
            results.Add(new { id, name, invoked = true, nativeResult });
        }
        return new { ok = true, status = "delete-requested-readback-pending", dryRun = false,
            requested = ids.Length, invokedCount = invoked, results, retryAllowed = false,
            localModelWritten = false, gameEffectVerified = false, persistentSaveVerified = false,
            notice = "Native true is dispatch only and false may mean no request. Observe the model and the formal file before any further action." };
    }
}
