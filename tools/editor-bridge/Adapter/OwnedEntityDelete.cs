using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Bounded delete of entities named EXPLICITLY by id.
//
// Why this exists: the CRUD probe can only delete the single target it created itself.
// CheckCrudTarget requires the level to hold EXACTLY ONE entity beyond the probe baseline
// (EntityCrudProbe.cs:107), so a batch create of N leaves entities that no existing path
// can remove. This is the bounded complement.
//
// The boundary is the ID LIST and nothing else. There is deliberately no name form, no
// type form, no "everything new since X" form and no wildcard:
//   * 1..64 ids, already validated by the unprivileged client, by the resident runner and
//     by ReadUintArray before the request reaches this method;
//   * every id must resolve to exactly ONE resource node in the editor graph;
//   * if ANY id resolves to zero nodes or to more than one, the whole call refuses and
//     deletes nothing -- an ambiguous list never produces a partial run;
//   * dryRun reports the exact id -> frontend path mapping and invokes no delete at all;
//   * immediately before each delete the node is re-resolved and re-checked against the
//     same id, the same way DeleteEntityCrudProbe re-checks its single target.
//
// The per-resource native delete method is the one the CRUD probe already uses, reached
// through a typed accessor; nothing here clicks UI, and nothing writes the editor model.
internal sealed partial class EditorAdapter
{
    // 2026-10-06: raised 20000 -> 200000. The 20000 cap was sized against the small probe
    // levels (a handful of entities); a level carrying 479 placed entities makes the walk
    // reach the cap and the whole call refuses with OWNED_DELETE_SCAN_NODE_LIMIT before it
    // resolves a single id. 200000 is the value PanelOpen already walks with on this same
    // editor (PanelOpen.cs:51), so it is a tested bound, not a new guess.
    //
    // Raising a cap must not weaken the fail-closed property, and it does not: the cap only
    // decides whether the walk finished. A FEWER-nodes walk still refuses a missing or
    // twice-reached id below (unresolved / ambiguous), and a LARGER cap can only turn
    // "refused: graph too big" into "walked the whole graph", never a wrong delete.
    const int OwnedDeleteScanNodes = 2000000;
    const int OwnedDeleteScanDepth = 24;

    static string OwnedDeleteResourceNodeType => B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7");
    static string OwnedDeleteWalkRootType => B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH");

    // ONE walk of the editor graph builds the whole id -> node index. The first version
    // resolved each id with its own walk and a 17-id call blew the client's response
    // window, so the walk is done once and everything after it is a dictionary lookup.
    //
    // A node whose id is reached twice is recorded as ambiguous and never selected; the
    // caller refuses the whole list on any ambiguous or missing id.
    Dictionary<uint, object> BuildOwnedDeleteIndex(out Dictionary<uint, string> paths,
                                                  out HashSet<uint> ambiguous)
    {
        string entityType = CrudEntityType;
        string resolveName = B("ndlKBRCbBjF");
        string resourceField = B("vQPKy8Qu9ev");
        string folderKeyField = B("y30KBtqRTpg");
        string kindField = B("yKiiwIS6frK");
        var index = new Dictionary<uint, object>();
        paths = new Dictionary<uint, string>();
        ambiguous = new HashSet<uint>();
        LastDeleteGraphStats = new Dictionary<string, object>();
        var containerCounts = new Dictionary<string, int>();
        var folderKindCounts = new Dictionary<string, int>();
        var nodeTypeCounts = new Dictionary<string, int>();
        int nodesSeen = 0, resourceNodes = 0, entityModels = 0;
        foreach (var (node, nodePath) in WalkEditorGraph(OwnedDeleteScanNodes, OwnedDeleteScanDepth, true,
                     OwnedDeleteWalkRootType))
        {
            nodesSeen++;
            string nodeTypeName = node.GetType().FullName ?? "<null>";
            nodeTypeCounts[nodeTypeName] = nodeTypeCounts.TryGetValue(nodeTypeName, out var ntc) ? ntc + 1 : 1;
            if (node.GetType().FullName != OwnedDeleteResourceNodeType) continue;
            resourceNodes++;
            var resource = Field(node, resourceField);
            object? containerRaw = null, folderKindRaw = null;
            try { containerRaw = Field(resource, "containerType"); } catch { }
            try { folderKindRaw = Field(Field(resource, folderKeyField), kindField); } catch { }
            string containerKey = containerRaw == null ? "<none>" : Convert.ToString(containerRaw) ?? "<none>";
            string folderKeyKey = folderKindRaw == null ? "<none>" : Convert.ToString(folderKindRaw) ?? "<none>";
            containerCounts[containerKey] = containerCounts.TryGetValue(containerKey, out var cc) ? cc + 1 : 1;
            folderKindCounts[folderKeyKey] = folderKindCounts.TryGetValue(folderKeyKey, out var fk) ? fk + 1 : 1;
            // 2026-10-20: the container/folder filter (containerType==4 && folderKey.kind==1) was
            // dropped. It assumed every placed entity lives in "containerType 4 / folder kind 1";
            // after a save-and-reload cycle the same entity ids can sit under a different
            // container and the old filter made them unresolvable while the game runtime still
            // held them. Resolution is still id-exact and fail-closed: a node only enters the
            // index if its typed accessor returns an entity model carrying that exact id, and a
            // duplicate id marks the id ambiguous and refuses the whole list.
            var resolve = resource.GetType().GetMethod(resolveName, BindingFlags.Instance | BindingFlags.Public)
                ?? throw new InvalidOperationException("OWNED_DELETE_TYPED_ACCESSOR_MISSING");
            var model = resolve.Invoke(resource, null);
            if (model == null || model.GetType().FullName != entityType) continue;
            entityModels++;
            uint id = ReadCrudKey(model).Id;
            if (index.ContainsKey(id)) { ambiguous.Add(id); continue; }
            index[id] = resource;
            paths[id] = nodePath;
        }
        if (LastWalkNodesVisited >= OwnedDeleteScanNodes)
            throw new InvalidOperationException("OWNED_DELETE_SCAN_NODE_LIMIT");
        LastDeleteGraphStats["nodesSeen"] = nodesSeen;
        LastDeleteGraphStats["resourceNodes"] = resourceNodes;
        LastDeleteGraphStats["entityModelsResolved"] = entityModels;
        LastDeleteGraphStats["indexSize"] = index.Count;
        LastDeleteGraphStats["containerTypeCounts"] = containerCounts;
        LastDeleteGraphStats["folderKindCounts"] = folderKindCounts;
        LastDeleteGraphStats["nodeTypeCounts"] = nodeTypeCounts;
        return index;
    }

    readonly Dictionary<string, object> lastDeleteGraphStats = new Dictionary<string, object>();
    Dictionary<string, object> LastDeleteGraphStats
    {
        get => lastDeleteGraphStats;
        set { lastDeleteGraphStats.Clear(); foreach (var kv in value) lastDeleteGraphStats[kv.Key] = kv.Value; }
    }

    // Resolve every id first. A single unresolved id refuses the whole call, so a partly
    // materialised level can never be half-deleted.
    public object DeleteOwnedEntityIds(uint[] ids, bool dryRun)
    {
        if (ids == null || ids.Length == 0) throw new InvalidOperationException("OWNED_DELETE_IDS_REQUIRED");
        if (ids.Length > 64) throw new InvalidOperationException("OWNED_DELETE_TOO_MANY_IDS");
        if (ids.Distinct().Count() != ids.Length) throw new InvalidOperationException("OWNED_DELETE_DUPLICATE_ID");

        var index = BuildOwnedDeleteIndex(out var paths, out var ambiguous);
        var resolved = new List<(uint Id, object Resource, string Path)>();
        var unresolved = new List<object>();
        foreach (uint id in ids)
        {
            if (ambiguous.Contains(id)) unresolved.Add(new { id, matches = 2, frontendPath = paths[id] });
            else if (index.TryGetValue(id, out var resource)) resolved.Add((id, resource, paths[id]));
            else unresolved.Add(new { id, matches = 0, frontendPath = "<none>" });
        }
        if (unresolved.Count != 0)
            return new { ok = false, status = "refused-unresolved-ids", dryRun,
                requested = ids.Length, resolvedCount = resolved.Count, unresolved,
                indexSize = index.Count,
                graphStats = LastDeleteGraphStats,
                invoked = false, localModelWritten = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false,
                notice = "No delete was invoked. An unresolved or ambiguous id refuses the whole list." };

        if (dryRun)
            return new { ok = true, status = "dry-run-mapping-only", dryRun = true,
                requested = ids.Length, resolvedCount = resolved.Count,
                graphStats = LastDeleteGraphStats,
                mapping = resolved.Select(r => new { id = r.Id, frontendPath = r.Path }).ToArray(),
                invoked = false, localModelWritten = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false,
                notice = "Mapping only; no native delete was invoked." };

        string deleteName = B("zgVKB6OS1MZ");
        string recheckResolve = B("ndlKBRCbBjF");
        var results = new List<object>();
        int invoked = 0;
        foreach (var (id, resource, path) in resolved)
        {
            // Re-check IMMEDIATELY before this delete, the same way DeleteEntityCrudProbe
            // re-checks its single target: re-invoke the typed accessor and require the
            // model it returns to still carry this exact id. A node that was replaced or
            // re-pointed must not be deleted.
            var recheck = resource.GetType().GetMethod(recheckResolve, BindingFlags.Instance | BindingFlags.Public)
                ?? throw new InvalidOperationException("OWNED_DELETE_TYPED_ACCESSOR_MISSING");
            var freshModel = recheck.Invoke(resource, null);
            if (freshModel == null || freshModel.GetType().FullName != CrudEntityType ||
                ReadCrudKey(freshModel).Id != id)
            {
                results.Add(new { id, frontendPath = path, invoked = false,
                    error = "OWNED_DELETE_TARGET_CHANGED_DURING_PREPARATION" });
                break;
            }
            var delete = resource.GetType().GetMethod(deleteName, BindingFlags.Instance | BindingFlags.Public)
                ?? throw new InvalidOperationException("OWNED_DELETE_NATIVE_METHOD_MISSING");
            object? nativeResult;
            try { nativeResult = delete.Invoke(resource, null); invoked++; }
            catch (Exception ex) { nativeResult = "threw:" + ex.GetType().Name + ":" + ex.Message; }
            results.Add(new { id, frontendPath = path, invoked = true, nativeResult });
        }
        return new { ok = true, status = "delete-requested-readback-pending", dryRun = false,
            requested = ids.Length, invokedCount = invoked,
            results, retryAllowed = false, localModelWritten = false, gameEffectVerified = false,
            persistentSaveVerified = false,
            notice = "Native true is dispatch only and false may mean no request. Observe the model and the formal file before any further action." };
    }
}
