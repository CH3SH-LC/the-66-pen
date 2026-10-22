using System;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    sealed class FinishMinimalNodeBackup
    {
        public uint Id;
        public object Node = null!, Definition = null!;
        public double X, Y;
    }
    sealed class FinishMinimalDiagnosticState
    {
        public object Graph = null!, Before = null!, Minimal = null!;
        public uint GraphId;
        public FinishMinimalNodeBackup[] Nodes = Array.Empty<FinishMinimalNodeBackup>();
        public object[] Edges = Array.Empty<object>();
    }
    FinishMinimalDiagnosticState? finishMinimalDiagnostic;

    void SyncFinishMinimalDiagnosticModel()
    {
        var state = finishMinimalDiagnostic ?? throw new InvalidOperationException("FINISH_MINIMAL_SYNC_WITHOUT_STATE");
        var proto = FinishDiagnosticProto(state.Graph);
        if (!FinishDiagnosticSame(state.Before, proto) && !FinishDiagnosticSame(state.Minimal, proto))
            throw new InvalidOperationException("FINISH_MINIMAL_SYNC_UNEXPECTED_GRAPH");
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if (!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields)!.Invoke(manager, new object[] { false })!)
            throw new InvalidOperationException("FINISH_MINIMAL_EDITOR_NOT_READY_TO_SYNC");
        manager.GetType().GetMethod(B("fIviJCKIQSe"), Fields)!.Invoke(manager, null);
    }
    void DeleteFinishMinimalNodes(object graph)
    {
        for (uint id = 23; id >= 2; id--)
            if (!(bool)graph.GetType().GetMethod(B("zbUKmIZoGMn"), Fields)!.Invoke(graph, new object?[] { id, null, false, false, false })!)
                throw new InvalidOperationException("FINISH_MINIMAL_DELETE_FAILED:" + id);
        if (GraphNodes(graph).Count != 1 || !GraphNodes(graph).Contains(1u) || FinishDiagnosticEdges(graph).Length != 0)
            throw new InvalidOperationException("FINISH_MINIMAL_DELETE_READBACK_FAILED");
    }
    void RestoreFinishMinimalInto(object graph, FinishMinimalDiagnosticState state)
    {
        var nodes = GraphNodes(graph);
        if (!nodes.Contains(1u) || nodes.Keys.Cast<object>().Any(k => Convert.ToUInt32(k) < 1u || Convert.ToUInt32(k) > 23u))
            throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_SHAPE_CONFLICT");
        foreach (var backup in state.Nodes)
        {
            if (nodes.Contains(backup.Id))
            {
                if (!Equals(Stored(nodes[backup.Id]!, B("tLtKHleyQAZ")), backup.Definition))
                    throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_NODE_CONFLICT:" + backup.Id);
                continue;
            }
            _ = graph.GetType().GetMethod(B("lLEKmep2RXi"), Fields)!.Invoke(graph,
                new object?[] { backup.Id, backup.Definition, backup.X, backup.Y, null, backup.Node })
                ?? throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_CREATE_FAILED:" + backup.Id);
        }
        var existing = FinishDiagnosticEdges(graph).Select(FinishDiagnosticEdge).ToHashSet(StringComparer.Ordinal);
        var expected = state.Edges.Select(FinishDiagnosticEdge).ToHashSet(StringComparer.Ordinal);
        if (existing.Any(e => !expected.Contains(e))) throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_EDGE_CONFLICT");
        foreach (var edge in state.Edges)
            if (!existing.Contains(FinishDiagnosticEdge(edge)))
                if (!(bool)graph.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(graph, new object?[] { edge, null, -1 })!)
                    throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_LINK_FAILED");
        if (!FinishDiagnosticSame(state.Before, FinishDiagnosticProto(graph)))
            throw new InvalidOperationException("FINISH_MINIMAL_RESTORE_PROTO_MISMATCH");
    }
    void RecycleFinishMinimalBackups(FinishMinimalDiagnosticState state)
    {
        foreach (var backup in state.Nodes)
            if (backup.Node != null)
            {
                backup.Node.GetType().GetMethod("Recycle", Fields)!.Invoke(backup.Node, null);
                backup.Node = null!;
            }
    }

    public object BeginFinishMinimalDiagnostic()
    {
        if (finishSettlementDiagnostic != null) throw new InvalidOperationException("FINISH_MINIMAL_OTHER_DIAGNOSTIC_ACTIVE");
        if (finishMinimalDiagnostic != null)
        {
            if (!FinishDiagnosticSame(finishMinimalDiagnostic.Minimal, FinishDiagnosticProto(finishMinimalDiagnostic.Graph)))
                throw new InvalidOperationException("FINISH_MINIMAL_ACTIVE_STATE_CHANGED");
            return new { ok = true, changed = false, active = true, graphId = finishMinimalDiagnostic.GraphId };
        }
        var resources = Resources();
        var matches = resources.Where(r => r.Kind == 9 &&
            (Stored(r.Model, B("c1pKbESgr8S")) as string) == "MW_Course_Finish_20260916")
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("FINISH_MINIMAL_GRAPH_AMBIGUOUS");
        var graph = matches[0];
        var nodes = GraphNodes(graph.Model);
        var edges = FinishDiagnosticEdges(graph.Model);
        if (nodes.Count != 23 || edges.Length != 27 || !Enumerable.Range(1, 23).All(i => nodes.Contains((uint)i)))
            throw new InvalidOperationException("FINISH_MINIMAL_GRAPH_SHAPE_CHANGED");
        var definitions = new uint[] { 71, 73, 14, 2, 1, 79, 83, 14, 2, 248, 509, 804, 99, 225, 244, 231, 9, 233, 226, 2, 82, 1, 77 };
        for (uint id = 1; id <= 23; id++)
            if (Convert.ToUInt32(Field(Stored(nodes[id]!, B("tLtKHleyQAZ"))!, B("namiwGPRyPS"))) != definitions[id - 1])
                throw new InvalidOperationException("FINISH_MINIMAL_NODE_DEFINITION_CHANGED:" + id);
        var state = new FinishMinimalDiagnosticState { Graph = graph.Model, GraphId = graph.Id,
            Before = FinishDiagnosticProto(graph.Model), Edges = edges };
        var backups = new System.Collections.Generic.List<FinishMinimalNodeBackup>();
        object? rehearsal = null;
        try
        {
            for (uint id = 2; id <= 23; id++)
            {
                var node = nodes[id]!;
                var definition = resources.First(r => r.Kind == 6 && r.Id == definitions[id - 1] && r.Category.SequenceEqual(FinishCategory));
                var copy = node.GetType().GetMethod("DeepCopy", Fields)!;
                backups.Add(new FinishMinimalNodeBackup { Id = id, Definition = Stored(definition.Model, B("U0oKESVcL9L"))!,
                    X = Convert.ToDouble(Stored(node, B("OpoKHL2l9bW"))), Y = Convert.ToDouble(Stored(node, B("Ft9KHqmCANf"))),
                    Node = copy.Invoke(node, new[] { Activator.CreateInstance(copy.GetParameters()[0].ParameterType) })! });
                state.Nodes = backups.ToArray();
            }
            rehearsal = Editor().GetType(B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"), true)!
                .GetMethod(B("WnqiJxnOpxs"), BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, new[] { state.Before })!;
            if (!FinishDiagnosticSame(state.Before, FinishDiagnosticProto(rehearsal)))
                throw new InvalidOperationException("FINISH_MINIMAL_CLONE_NOT_LOSSLESS");
            DeleteFinishMinimalNodes(rehearsal);
            state.Minimal = FinishDiagnosticProto(rehearsal);
            RestoreFinishMinimalInto(rehearsal, state);
            finishMinimalDiagnostic = state;
            try
            {
                DeleteFinishMinimalNodes(graph.Model);
                if (!FinishDiagnosticSame(state.Minimal, FinishDiagnosticProto(graph.Model)))
                    throw new InvalidOperationException("FINISH_MINIMAL_LIVE_PROTO_MISMATCH");
                SyncFinishMinimalDiagnosticModel();
            }
            catch (Exception error)
            {
                RestoreFinishMinimalDiagnostic();
                throw new InvalidOperationException("FINISH_MINIMAL_ABORTED_AND_RESTORED", error);
            }
            return new { ok = true, changed = true, active = true, graphId = graph.Id, nodeCount = 1, edgeCount = 0,
                restorationRequired = true, persistentSaveVerified = false, playtestVerified = false };
        }
        finally
        {
            if (rehearsal != null) rehearsal.GetType().GetMethod("Recycle", Fields)!.Invoke(rehearsal, null);
            if (!ReferenceEquals(finishMinimalDiagnostic, state)) RecycleFinishMinimalBackups(state);
        }
    }

    public object RestoreFinishMinimalDiagnostic()
    {
        var state = finishMinimalDiagnostic;
        if (state == null) return new { ok = true, changed = false, active = false };
        RestoreFinishMinimalInto(state.Graph, state);
        SyncFinishMinimalDiagnosticModel();
        finishMinimalDiagnostic = null;
        RecycleFinishMinimalBackups(state);
        return new { ok = true, changed = true, active = false, graphId = state.GraphId, nodeCount = 23, edgeCount = 27,
            nativeProtoRestoredExactly = true, persistentSaveVerified = false };
    }
}
