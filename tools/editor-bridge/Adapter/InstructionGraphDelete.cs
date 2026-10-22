using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Bounded DELETE of exactly ONE instruction graph, over the beyondEditObjService command
// "DeleteInstructionGraphForEditObj" -- the symmetric sibling of the command the bridge
// ALREADY dispatches to BIND a graph (AddInstructionGraphForEditObj).
//
// ============================== EVIDENCE TIERS ==============================
// This is the third tier of a three-tier chain, and the tiers must not be confused:
//
//  (1) ATTESTED. "AddInstructionGraphForEditObj" is a literal in the editor's own
//      front end and the bridge fires it live today:
//        * front end  .runtime/editor-catalog/resolved/VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf.cs:2118
//        * bridge     Adapter/AuthoringGraph.cs:317  and  Adapter/EditorAdapter.cs:664
//      The producer call -- ExistingSingleton(Editor(),Producer).Ikci0qkvMZX(
//      "beyondEditObjService", <name>, null, List<Param>) -- is copied from there
//      EXACTLY, as is the four-slot argument list (bool, uint, uint, uint).
//
//  (2) PREIMAGE. "DeleteInstructionGraphForEditObj" is NOT a front-end literal anywhere
//      in the 12,375-file decompiled corpus or the string table. It is the FNV-1a-32
//      preimage of the dispatcher key 0x2c4eda76, which IS present as a `cmp ecx,imm32`
//      site (0xcba3410, 0xcba372d) in the editor command dispatcher
//      (docs/research/reverse-eng-20261011/COMMAND-SURFACE-FNV.md:89,152). A preimage
//      proves "this string hashes to this key" -- exactly the engine's dispatch
//      criterion -- but NOT that the engine was compiled with this spelling rather than
//      another preimage. Tier (2), not tier (1).
//
//  (3) UNRECOVERED. The command's PARAMETER SHAPE is unknown. There is no
//      `DeleteInstructionGraphForEditObj` row in backend.db command_route (38 rows; only
//      AddInstructionGraphForEditObj has one). The only reading is the dispatcher-side
//      note "bool + two scalars" (docs/gameplay/FRONTEND-BACKEND-TRACE-20260920.md:163), and
//      the DeleteInstructionGraphForPrefab sibling "resolves a component to the actual entity id first" before it
//      tail-jumps into this handler -- both of which point at an EDIT-OBJECT id being an
//      argument. This file therefore REQUIRES an edit-object id and REFUSES with a named
//      code when none is supplied, rather than inventing one:
//
//          INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED
//
//      That refusal is the honest state of tier (3). It is not a placeholder for a
//      success: it says the payload is not recovered, and it fails BEFORE any dispatch.
// ===========================================================================
//
// ---------------------------------------------------------------------------
// THE SAFETY GATE IS OWNERSHIP-SCOPED, AND EVERY REFUSAL IS NAMED
//
// The graph that may be deleted must be proven to be THIS PROJECT'S, by identity:
//   * it must be a Kind-9 resource decided by the SAME Resources() walk the rest of the
//     bridge uses (never a second, private notion of "graph");
//   * its id must resolve to exactly ONE Kind-9 row -- zero or two+ refuses the request;
//   * its stored name must start with "MW_" -- this project's own graph-naming prefix,
//     the SAME constant the sibling OwnedGraphDelete uses. A graph someone else made
//     cannot be deleted even if its id is supplied and its name is known;
//   * its node table must be EMPTY (GraphNodes(model).Count == 0) -- unless the caller
//     explicitly asks for the wider form by naming the -force op. An override is
//     deliberately an OP NAME and not a request field, because a field cannot ride the
//     pinned runner (see the note above the two op constants below);
//   * it must carry NO entity bindings -- this one is NOT overridable even by -force:
//     a bound graph is live gameplay, and no path in this project deletes live gameplay.
//
// Named refusals (all fail-closed, all before any native call):
//   INSTRUCTION_GRAPH_UNKNOWN_OR_DUPLICATE_FIELD:<name>
//   INSTRUCTION_GRAPH_IDS_REQUIRED
//   INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED
//   INSTRUCTION_GRAPH_ID_INVALID
//   INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED
//   INSTRUCTION_GRAPH_NO_GRAPHS_VISIBLE
//   INSTRUCTION_GRAPH_NOT_FOUND
//   INSTRUCTION_GRAPH_ID_AMBIGUOUS
//   INSTRUCTION_GRAPH_NAME_UNAVAILABLE
//   INSTRUCTION_GRAPH_FOREIGN_NOT_OWNED
//   INSTRUCTION_GRAPH_NOT_EMPTY
//   INSTRUCTION_GRAPH_BOUND
//   INSTRUCTION_GRAPH_ALREADY_ATTEMPTED
//   INSTRUCTION_GRAPH_LEASE_MUTATION_LIMIT
//   INSTRUCTION_GRAPH_TARGET_CHANGED_DURING_PREPARATION
//   EDITOR_NOT_READY
// ---------------------------------------------------------------------------
internal sealed partial class EditorAdapter
{
    // Command/service pair. The service is the one the Add sibling uses
    // (AuthoringGraph.cs:317); the command is the tier-(2) preimage above.
    const string InstructionGraphDeleteService = "beyondEditObjService";
    const string InstructionGraphDeleteCommand = "DeleteInstructionGraphForEditObj";

    // Bounded dispatch. One graph per request (the command deletes ONE), and at most
    // eight attempts per run -- the lease is spent even on a throw, exactly as the
    // component deleter spends its own (EntityComponentDelete.cs:228).
    const int InstructionGraphDeleteLeaseLimit = 8;

    readonly HashSet<string> instructionGraphDeleteAttempts = new(StringComparer.Ordinal);

    // Strict envelope, in the shape of ValidateEntityComponentDelete
    // (EntityComponentDelete.cs:82-100): unknown or duplicate fields, malformed numbers
    // and a malformed id list are refused BEFORE any native call.
    //
    // The field set is {id, op, nonce, ids, entityId}. There is no `action` field: this
    // op's read-only form is a separate OP NAME (-dry-run), not a field, because the
    // resident helper's in-memory field allowlist cannot be widened for this op
    // (elevated-runner.ps1:283 throws CALL_FIELD_NOT_ALLOWED:<name> for every field
    // outside its own per-op lists). An `action` field would therefore be refused by the
    // pin before the adapter ever saw it.
    internal static void ValidateInstructionGraphDelete(JsonElement request)
    {
        uint EditObj() => request.TryGetProperty("entityId", out var v) && v.TryGetUInt32(out var n) && n != 0
            ? n : throw new InvalidOperationException("INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED");
        uint[] Ids()
        {
            if (!request.TryGetProperty("ids", out var v) || v.ValueKind != JsonValueKind.Array)
                throw new InvalidOperationException("INSTRUCTION_GRAPH_IDS_REQUIRED");
            var list = new List<uint>();
            foreach (var item in v.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Number || !item.TryGetUInt32(out var n))
                    throw new InvalidOperationException("INSTRUCTION_GRAPH_ID_INVALID");
                list.Add(n);
            }
            if (list.Count == 0) throw new InvalidOperationException("INSTRUCTION_GRAPH_IDS_REQUIRED");
            if (list.Count != 1) throw new InvalidOperationException("INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED");
            if (list[0] == 0) throw new InvalidOperationException("INSTRUCTION_GRAPH_ID_INVALID");
            return list.ToArray();
        }
        var allowed = new HashSet<string> { "id", "op", "nonce", "ids", "entityId" };
        var seen = new HashSet<string>();
        foreach (var p in request.EnumerateObject())
            if (!allowed.Contains(p.Name) || !seen.Add(p.Name))
                throw new InvalidOperationException("INSTRUCTION_GRAPH_UNKNOWN_OR_DUPLICATE_FIELD:" + p.Name);
        Ids();
        // Tier (3): the edit-object id is REQUIRED because the payload is unrecovered and
        // every reading of it names an edit object. Absence is refused by name, never
        // defaulted to 0 or to the level entity.
        EditObj();
    }

    // The ONE graph this request may delete. Throws a named code for every way the
    // identity can fail; never returns a "closest" graph.
    Resource InstructionGraphOwnedTarget(uint graphId)
    {
        var rows = Resources().Where(r => r.Kind == 9 && r.Id == graphId).ToArray();
        if (rows.Length == 0)
        {
            if (!Resources().Any(r => r.Kind == 9))
                throw new InvalidOperationException("INSTRUCTION_GRAPH_NO_GRAPHS_VISIBLE");
            throw new InvalidOperationException("INSTRUCTION_GRAPH_NOT_FOUND");
        }
        if (rows.Length > 1) throw new InvalidOperationException("INSTRUCTION_GRAPH_ID_AMBIGUOUS");
        var graph = rows[0];
        var name = Stored(graph.Model, B("c1pKbESgr8S")) as string;
        if (name == null) throw new InvalidOperationException("INSTRUCTION_GRAPH_NAME_UNAVAILABLE");
        if (!name.StartsWith(OwnedGraphDeleteNamePrefix, StringComparison.Ordinal))
            throw new InvalidOperationException("INSTRUCTION_GRAPH_FOREIGN_NOT_OWNED:" + name);
        return graph;
    }

    List<uint> InstructionGraphBoundEntities(uint graphId) => entityModels
        .Where(e => EntityBindings(e).Any(k => (uint)Field(k, B("namiwGPRyPS")) == graphId))
        .Select(e => (uint)Field(Stored(e, B("Qi8iCzKCkTt"))!, B("namiwGPRyPS")))
        .Distinct().ToList();

    // The invoke. Copied from AuthoringGraph.cs:317 / EditorAdapter.cs:664 line for line --
    // identical producer, service string, callback null and List<Param> construction; only
    // the command name and the meaning of the first uint differ. Never builds a callback,
    // RPC or reflection argument bag.
    //
    // The four slots mirror the Add sibling's construction EXACTLY (bool true, uint
    // editObjId, uint 1u, uint graphId) because that is the ONLY attested shape for this
    // command family (tier 1). Tier (3) says the Delete sibling is "bool + two scalars"; that
    // reading is NOT applied here -- an unattested shape must not overwrite an attested
    // one. Which slot count the engine actually accepts is the open question this file
    // cannot answer offline.
    void DispatchInstructionGraphDelete(uint editObjId, uint graphId)
    {
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if (!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields)!.Invoke(manager, new object[] { false })!)
            throw new InvalidOperationException("EDITOR_NOT_READY");
        var param = Editor().GetType(Param, true)!;
        var args = (IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        object Wrap(string method, object v) => param.GetMethod(method, BindingFlags.Public | BindingFlags.Static)!.Invoke(null, new[] { v })!;
        args.Add(Wrap(B("h8diA3iOGmJ"), true));
        args.Add(Wrap(B("bKliA0tj1p1"), editObjId));
        args.Add(Wrap(B("qsriAuLLSBe"), 1u));
        args.Add(Wrap(B("bKliA0tj1p1"), graphId));
        var producer = ExistingSingleton(Editor(), Producer);
        producer.GetType().GetMethod(B("Ikci0qkvMZX"), Fields)!.Invoke(
            producer, new object?[] { InstructionGraphDeleteService, InstructionGraphDeleteCommand, null, args });
    }

    // force==true is the "-force" op name: it lifts the EMPTY-graph requirement (a graph
    // with nodes may be deleted). It does NOT lift the binding requirement -- a bound
    // graph is live gameplay. The read-only "-dry-run" name never reaches this method.
    public object DeleteInstructionGraph(JsonElement request, bool force)
    {
        ValidateInstructionGraphDelete(request);
        var graphId = request.GetProperty("ids")[0].GetUInt32();
        var editObjId = request.GetProperty("entityId").GetUInt32();

        var graph = InstructionGraphOwnedTarget(graphId);
        var name = Stored(graph.Model, B("c1pKbESgr8S")) as string;
        var nodeCount = GraphNodes(graph.Model).Count;
        var bound = InstructionGraphBoundEntities(graphId);

        if (bound.Count != 0)
            throw new InvalidOperationException("INSTRUCTION_GRAPH_BOUND");
        if (!force && nodeCount != 0)
            throw new InvalidOperationException("INSTRUCTION_GRAPH_NOT_EMPTY:" + nodeCount);

        var attempt = graphId + ":" + editObjId;
        if (instructionGraphDeleteAttempts.Contains(attempt))
            throw new InvalidOperationException("INSTRUCTION_GRAPH_ALREADY_ATTEMPTED");
        if (instructionGraphDeleteAttempts.Count >= InstructionGraphDeleteLeaseLimit)
            throw new InvalidOperationException("INSTRUCTION_GRAPH_LEASE_MUTATION_LIMIT");

        // Re-check immediately before the dispatch (baseline discipline; mirrors
        // OwnedGraphDelete.cs:250-275 and EntityComponentDelete.cs:224-226). Same id, same
        // name, same node count, still unbound.
        var fresh = InstructionGraphOwnedTarget(graphId);
        if (!ReferenceEquals(fresh.Model, graph.Model)
            || (Stored(fresh.Model, B("c1pKbESgr8S")) as string) != name
            || GraphNodes(fresh.Model).Count != nodeCount
            || InstructionGraphBoundEntities(graphId).Count != 0)
            throw new InvalidOperationException("INSTRUCTION_GRAPH_TARGET_CHANGED_DURING_PREPARATION");

        instructionGraphDeleteAttempts.Add(attempt); // consumed even if the native send throws
        DispatchInstructionGraphDelete(editObjId, graphId);

        // Same-turn re-read of the editor model. The native delete is async, so this is NOT
        // authoritative -- reported only so the caller has a before/after pair. A real
        // decision needs a later inspect of Resources() plus a .gil byte diff (doctrine:
        // ok:true alone does not prove persistence, and this op cannot prove it at all
        // until tier (3) is recovered).
        var after = Resources().Where(r => r.Kind == 9 && r.Id == graphId).ToArray();
        var stillListed = after.Length != 0;
        var afterCount = stillListed ? GraphNodes(after[0].Model).Count : 0;
        return new
        {
            ok = true, status = "instruction-graph-delete-requested-readback-pending",
            graphId, name, editObjId, force,
            beforeNodeCount = nodeCount,
            stillListedSameTurn = stillListed,
            afterNodeCountSameTurn = afterCount,
            afterReadback = "same-turn-reread-non-authoritative; native dispatch is asynchronous",
            invokedUtc = DateTime.UtcNow, retryAllowed = false,
            // Tier flags travel with the receipt so no reader can mistake this for proof.
            commandNameTier = "preimage-not-literal(0x2c4eda76)",
            commandPayloadTier = "unrecovered(bool+two-scalars-reading);mirrors-add-shape",
            nativeMutationInvoked = true, localModelWritten = false,
            gameEffectVerified = false, persistentSaveVerified = false,
            notice = "A dispatch return value is not persistence. Re-run Resources() later and diff the .gil bytes before claiming success."
        };
    }

    // Read-only. Resolves the same ownership identity and reports the mapping, invoking
    // nothing. Mirrors the sibling pair delete-owned-graph-ids / -dry-run.
    public object DeleteInstructionGraphDryRun(JsonElement request)
    {
        ValidateInstructionGraphDelete(request);
        var graphId = request.GetProperty("ids")[0].GetUInt32();
        var editObjId = request.GetProperty("entityId").GetUInt32();
        var graph = InstructionGraphOwnedTarget(graphId);
        var name = Stored(graph.Model, B("c1pKbESgr8S")) as string;
        var nodeCount = GraphNodes(graph.Model).Count;
        var bound = InstructionGraphBoundEntities(graphId);
        var wouldRefuse = bound.Count != 0 ? "INSTRUCTION_GRAPH_BOUND"
            : nodeCount != 0 ? "INSTRUCTION_GRAPH_NOT_EMPTY:" + nodeCount
            : null;
        return new
        {
            ok = true, status = "instruction-graph-delete-dry-run-mapping-only",
            graphId, name, editObjId,
            nodeCount, boundEntityIds = bound.ToArray(), wouldRefuse,
            invoked = false, localModelWritten = false, nativeMutationInvoked = false,
            gameEffectVerified = false, persistentSaveVerified = false,
            notice = "Mapping only; no native delete was invoked."
        };
    }
}
