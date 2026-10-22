using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Fixed, read-only inspection of the native serializer used immediately before the
// outgoing 1014 sync payload. Source evidence in
// .runtime/verification/editor-service-static/Oe5aspiVGooyp47o5s0q.cs:23154 (definition),
// :23401 (WOyaoCY3Fti node collection), :27436/:27476 (call sites).
// This only reads; it never sends to the game and never persists.
internal sealed partial class EditorAdapter
{
    static string SyncManagerType => B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q");
    static string SyncSerializerMethod => B("oGZiJdFmLSF");
    static string SerializedNodesMember => B("WOyaoCY3Fti");
    const int SerializedNodeLimit = 100;
    bool syncInspectionAttempted;

    public object InspectSyncGraphs()
    {
        // Bound native work to one attempt per adapter, including failed attempts.
        if (syncInspectionAttempted) throw new InvalidOperationException("SYNC_INSPECTION_ALREADY_ATTEMPTED");

        var graphs = Resources().Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var calibration = graphs.SingleOrDefault(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == CalibrationGraphName);
        var allowed = new Dictionary<string, int>{{CalibrationGraphName, 7},{RoutePlacementName, 12},{TiledRouteName, 39},{AuditGraphName, 13},{PositionGraphName, 16},{FinishGraphName, 23}};
        if (calibration == null || graphs.Length > 5 ||
            graphs.Any(r => !allowed.TryGetValue(Stored(r.Model, B("c1pKbESgr8S")) as string ?? "", out var count) || GraphNodes(r.Model).Count != count) ||
            graphs.Select(r => Stored(r.Model, B("c1pKbESgr8S")) as string).Distinct().Count() != graphs.Length)
            throw new InvalidOperationException("OWN_CALIBRATION_AND_ROUTE_SESSION_REQUIRED");

        var managerType = Editor().GetType(SyncManagerType, true)!;
        var serializer = managerType.GetMethod(SyncSerializerMethod, BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic, null,
            new[]{Editor().GetType(Model9,true)!, Editor().GetType(Model6,true)!, typeof(bool)}, null)
            ?? throw new InvalidOperationException("SYNC_SERIALIZER_NOT_FOUND");
        if (serializer.ReturnType.FullName != B("dtCyX8ao6wX81LGIyEgY.f4A1VQaoFD29hLxbgRyd"))
            throw new InvalidOperationException("SYNC_SERIALIZER_SIGNATURE_MISMATCH");

        syncInspectionAttempted = true;
        var results = new List<object>();
        var allMatch = true;
        foreach (var graph in graphs)
        {
            var name = Stored(graph.Model, B("c1pKbESgr8S")) as string;
            var proto = serializer.Invoke(null, new object?[]{graph.Model, null, false})
                ?? throw new InvalidOperationException("SYNC_SERIALIZER_NULL_PROTO");
            var serializedIds = ReadSerializedNodeIds(proto);
            var modelIds = GraphNodes(graph.Model).Keys.Cast<uint>().OrderBy(id=>id).ToArray();
            var modelNodes = modelIds.Length;
            var serialized = serializedIds.Length;
            var matches = serializedIds.SequenceEqual(modelIds);
            if (!matches) allMatch = false;
            results.Add(new {graphId = graph.Id, name, modelNodes, serializedNodes = serialized,
                modelNodeIds=modelIds,serializedNodeIds=serializedIds,
                countMatches = serialized==modelNodes,nodeIdsMatch=matches});
        }

        return new {ok = allMatch, status = allMatch ? "native-sync-serialization-matches" : "native-sync-serialization-mismatch",
            scope = "native-sync-serialization-only", graphs = results,
            serializerType = managerType.FullName, serializerMethod = SyncSerializerMethod,
            sentToGame = false, persistentSaveVerified = false, playtestVerified = false};
    }

    // The proto's node collection is the exact set handed to the outgoing 1014 payload.
    uint[] ReadSerializedNodeIds(object proto)
    {
        var type = proto.GetType();
        object? nodes = type.GetMethod(SerializedNodesMember, Fields, null, Type.EmptyTypes, null)?.Invoke(proto,null);
        if (nodes == null) throw new InvalidOperationException("SERIALIZED_NODES_MISSING");
        if (nodes is not IEnumerable enumerable) throw new InvalidOperationException("SERIALIZED_NODES_NOT_ENUMERABLE");
        var ids=new List<uint>();
        foreach (var node in enumerable)
        {
            if(ids.Count>=SerializedNodeLimit)throw new InvalidOperationException("SERIALIZED_NODE_LIMIT");
            if(node?.GetType().FullName!=B("tYcuuNaTSY3wtgYAjxgT.UP9OrIaTCK1yMYEKHVN3"))
                throw new InvalidOperationException("SERIALIZED_NODE_TYPE_MISMATCH");
            // LOZiJsKF0Xv assigns the model's pS7KHbqRAou ID through NCtaTzxqjcV.
            ids.Add((uint)Field(node,B("usLa91tD7Tp")));
        }
        return ids.OrderBy(id=>id).ToArray();
    }
}
