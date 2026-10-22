using System;
using System.Collections;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    sealed class FinishSettlementDiagnosticState
    {
        public object Graph = null!, Node = null!, Edge = null!, Definition = null!, Before = null!, Isolated = null!;
        public uint GraphId;
        public double X, Y;
    }
    FinishSettlementDiagnosticState? finishSettlementDiagnostic;

    void SyncFinishDiagnosticModel()
    {
        var state = finishSettlementDiagnostic ?? throw new InvalidOperationException("FINISH_DIAGNOSTIC_SYNC_WITHOUT_STATE");
        var current = FinishDiagnosticProto(state.Graph);
        if (!FinishDiagnosticSame(state.Before, current) && !FinishDiagnosticSame(state.Isolated, current))
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_SYNC_UNEXPECTED_GRAPH");
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if (!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields)!.Invoke(manager, new object[] { false })!)
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_EDITOR_NOT_READY_TO_SYNC");
        manager.GetType().GetMethod(B("fIviJCKIQSe"), Fields)!.Invoke(manager, null);
    }

    object FinishDiagnosticProto(object model) => Editor()
        .GetType(B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"), true)!
        .GetMethod(B("oGZiJdFmLSF"), BindingFlags.Static | BindingFlags.NonPublic)!
        .Invoke(null, new object?[] { model, null, false })!;
    bool FinishDiagnosticSame(object a, object b) => (bool)a.GetType()
        .GetMethod("Equals", new[] { a.GetType() })!.Invoke(a, new[] { b })!;
    object[] FinishDiagnosticEdges(object graph)
    {
        var map = graph.GetType().GetMethod(B("yKHKOFfNm2M"), Fields)!.Invoke(graph, null)!;
        return ((IDictionary)Field(map, B("cHuiFsU5V56"))).Keys.Cast<object>().ToArray();
    }
    string FinishDiagnosticAddress(object address)
    {
        var pin = Field(address, B("Ds3K5LVxwhM"));
        return Convert.ToUInt32(Field(address, B("iihK5hUQPDy"))) + ":" +
            Convert.ToInt32(Field(pin, B("TqBK5Pk3Cw2"))) + ":" + Convert.ToInt32(Field(pin, B("hWTK5MSRidQ")));
    }
    string FinishDiagnosticEdge(object edge) => FinishDiagnosticAddress(Field(edge, B("fH0izeMOw73"))) + ">" +
        FinishDiagnosticAddress(Field(edge, B("ABfizkqh4mD")));
    void FinishDiagnosticDelete(object graph)
    {
        if (!(bool)graph.GetType().GetMethod(B("zbUKmIZoGMn"), Fields)!.Invoke(graph, new object?[] { 23u, null, false, false, false })! ||
            GraphNodes(graph).Count != 22 || GraphNodes(graph).Contains(23u) || FinishDiagnosticEdges(graph).Length != 26)
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_DELETE_FAILED");
    }
    void FinishDiagnosticRestoreInto(object graph, FinishSettlementDiagnosticState state)
    {
        var nodes = GraphNodes(graph);
        if (!nodes.Contains(23u))
        {
            if (nodes.Count != 22) throw new InvalidOperationException("FINISH_DIAGNOSTIC_RESTORE_SHAPE_CHANGED");
            _ = graph.GetType().GetMethod(B("lLEKmep2RXi"), Fields)!.Invoke(graph,
                new object?[] { 23u, state.Definition, state.X, state.Y, null, state.Node })
                ?? throw new InvalidOperationException("FINISH_DIAGNOSTIC_RESTORE_CREATE_FAILED");
        }
        else if (Convert.ToUInt32(Field(Stored(nodes[23u]!, B("tLtKHleyQAZ"))!, B("namiwGPRyPS"))) != 77u)
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_RESTORE_NODE_CONFLICT");
        if (!FinishDiagnosticEdges(graph).Any(e => FinishDiagnosticEdge(e) == "22:2:0>23:1:0"))
            if (!(bool)graph.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(graph, new object?[] { state.Edge, null, -1 })!)
                throw new InvalidOperationException("FINISH_DIAGNOSTIC_RESTORE_LINK_FAILED");
        if (!FinishDiagnosticSame(state.Before, FinishDiagnosticProto(graph)))
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_RESTORE_PROTO_MISMATCH");
    }

    public object BeginFinishSettlementDiagnostic()
    {
        if (finishMinimalDiagnostic != null) throw new InvalidOperationException("FINISH_DIAGNOSTIC_OTHER_DIAGNOSTIC_ACTIVE");
        if (finishSettlementDiagnostic != null)
        {
            if (!FinishDiagnosticSame(finishSettlementDiagnostic.Isolated, FinishDiagnosticProto(finishSettlementDiagnostic.Graph)))
                throw new InvalidOperationException("FINISH_DIAGNOSTIC_ACTIVE_STATE_CHANGED");
            return new { ok = true, changed = false, active = true, graphId = finishSettlementDiagnostic.GraphId };
        }
        var resources = Resources();
        var matches = resources.Where(r => r.Kind == 9 &&
            (Stored(r.Model, B("c1pKbESgr8S")) as string) == "MW_Course_Finish_20260916")
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("FINISH_DIAGNOSTIC_GRAPH_AMBIGUOUS");
        var graph = matches[0];
        var nodes = GraphNodes(graph.Model);
        if (nodes.Count != 23 || !Enumerable.Range(1, 23).All(i => nodes.Contains((uint)i)))
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_GRAPH_SHAPE_CHANGED");
        var node = nodes[23u]!;
        if (Convert.ToUInt32(Field(Stored(node, B("tLtKHleyQAZ"))!, B("namiwGPRyPS"))) != 77u ||
            Convert.ToUInt32(Field(Stored(nodes[22u]!, B("tLtKHleyQAZ"))!, B("namiwGPRyPS"))) != 1u)
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_NODE_CHANGED");
        var edges = FinishDiagnosticEdges(graph.Model);
        var touching = edges.Where(e => Convert.ToUInt32(Field(Field(e, B("fH0izeMOw73")), B("iihK5hUQPDy"))) == 23u ||
            Convert.ToUInt32(Field(Field(e, B("ABfizkqh4mD")), B("iihK5hUQPDy"))) == 23u).ToArray();
        if (edges.Length != 27 || touching.Length != 1 || FinishDiagnosticEdge(touching[0]) != "22:2:0>23:1:0")
            throw new InvalidOperationException("FINISH_DIAGNOSTIC_EDGE_CHANGED");
        var definition = resources.First(r => r.Kind == 6 && r.Id == 77u && r.Category.SequenceEqual(FinishCategory));
        var state = new FinishSettlementDiagnosticState { Graph = graph.Model, GraphId = graph.Id,
            Before = FinishDiagnosticProto(graph.Model), Edge = touching[0], Definition = Stored(definition.Model, B("U0oKESVcL9L"))!,
            X = Convert.ToDouble(Stored(node, B("OpoKHL2l9bW"))), Y = Convert.ToDouble(Stored(node, B("Ft9KHqmCANf"))) };
        var copy = node.GetType().GetMethod("DeepCopy", Fields)!;
        state.Node = copy.Invoke(node, new[] { Activator.CreateInstance(copy.GetParameters()[0].ParameterType) })!;
        object? rehearsal = null;
        try
        {
            rehearsal = Editor().GetType(B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"), true)!
                .GetMethod(B("WnqiJxnOpxs"), BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, new[] { state.Before })!;
            if (!FinishDiagnosticSame(state.Before, FinishDiagnosticProto(rehearsal)))
                throw new InvalidOperationException("FINISH_DIAGNOSTIC_CLONE_NOT_LOSSLESS");
            FinishDiagnosticDelete(rehearsal);
            state.Isolated = FinishDiagnosticProto(rehearsal);
            FinishDiagnosticRestoreInto(rehearsal, state);
            // Publish recovery state before the first live mutation, including partial failures.
            finishSettlementDiagnostic = state;
            try
            {
                FinishDiagnosticDelete(graph.Model);
                if (!FinishDiagnosticSame(state.Isolated, FinishDiagnosticProto(graph.Model)))
                    throw new InvalidOperationException("FINISH_DIAGNOSTIC_LIVE_PROTO_MISMATCH");
                SyncFinishDiagnosticModel();
            }
            catch (Exception error)
            {
                RestoreFinishSettlementDiagnostic();
                throw new InvalidOperationException("FINISH_DIAGNOSTIC_ABORTED_AND_RESTORED", error);
            }
            return new { ok = true, changed = true, active = true, graphId = graph.Id, nodeCount = 22, edgeCount = 26,
                restorationRequired = true, persistentSaveVerified = false, playtestVerified = false };
        }
        finally
        {
            if (rehearsal != null) rehearsal.GetType().GetMethod("Recycle", Fields)!.Invoke(rehearsal, null);
            if (!ReferenceEquals(finishSettlementDiagnostic, state) && state.Node != null)
            {
                state.Node.GetType().GetMethod("Recycle", Fields)!.Invoke(state.Node, null);
                state.Node = null!;
            }
        }
    }

    // Call on the existing dispatcher before lease cleanup/disposal. A failed restore
    // retains its backup for retry and must be surfaced instead of claiming cleanup.
    public object RestoreFinishSettlementDiagnostic()
    {
        var state = finishSettlementDiagnostic;
        if (state == null) return new { ok = true, changed = false, active = false };
        FinishDiagnosticRestoreInto(state.Graph, state);
        SyncFinishDiagnosticModel();
        finishSettlementDiagnostic = null;
        state.Node.GetType().GetMethod("Recycle", Fields)!.Invoke(state.Node, null);
        state.Node = null!;
        return new { ok = true, changed = true, active = false, graphId = state.GraphId, nodeCount = 23, edgeCount = 27,
            nativeProtoRestoredExactly = true, persistentSaveVerified = false };
    }
}
