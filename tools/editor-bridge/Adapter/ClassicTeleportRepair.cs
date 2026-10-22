using System;
using System.Collections;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    // Native delete/recreate, rehearsed on an unregistered deserialized graph first.
    // Only the known final node of our 29-node graph is eligible. No save/upload call.
    public object RepairGameLoopClassicTeleport()
    {
        var resources = Resources();
        var matches = resources.Where(r => r.Kind == 9 &&
            (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("CLASSIC_TELEPORT_GRAPH_AMBIGUOUS");
        var graph = matches[0];
        var nodes = GraphNodes(graph.Model);
        if (nodes.Count != 29 || !Enumerable.Range(1, 29).All(i => nodes.Contains((uint)i)))
            throw new InvalidOperationException("CLASSIC_TELEPORT_GRAPH_SHAPE_CHANGED");
        uint Definition(object n) => Convert.ToUInt32(Field(Stored(n, B("tLtKHleyQAZ"))!, B("namiwGPRyPS")));
        var original = nodes[29u]!;
        var beforeId = Definition(original);
        if (beforeId != 288u && beforeId != 805u)
            throw new InvalidOperationException("CLASSIC_TELEPORT_UNEXPECTED_DEFINITION");
        if (Definition(nodes[27u]!) != 2u || Definition(nodes[11u]!) != 509u || Definition(nodes[28u]!) != 225u)
            throw new InvalidOperationException("CLASSIC_TELEPORT_SOURCE_NODES_CHANGED");
        var x = Convert.ToDouble(Stored(original, B("OpoKHL2l9bW")));
        var y = Convert.ToDouble(Stored(original, B("Ft9KHqmCANf")));
        if (x != 1200d || y != 2000d) throw new InvalidOperationException("CLASSIC_TELEPORT_POSITION_CHANGED");
        var oldDef = resources.First(r => r.Kind == 6 && r.Id == 288u && r.Category.SequenceEqual(FinishCategory));
        var newDef = resources.First(r => r.Kind == 6 && r.Id == 805u && r.Category.SequenceEqual(FinishCategory));
        foreach (var def in new[] { oldDef, newDef })
        {
            var pins = ((IEnumerable)def.Model).Cast<object>().ToArray();
            var parameters = pins.Where(p => DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) == 3)
                .OrderBy(p => DefinitionPinKeyPart(p, B("hWTK5MSRidQ"))).ToArray();
            if (parameters.Length != 3 || !parameters.Select(p => DefinitionPinKeyPart(p, B("hWTK5MSRidQ"))).SequenceEqual(new int?[] { 0, 1, 2 }) ||
                !parameters.Select(p => Convert.ToUInt32(Stored(FinishPinDefinition(p)!, B("pR9KY126SEr")))).SequenceEqual(new uint[] { 1, 12, 12 }))
                throw new InvalidOperationException("CLASSIC_TELEPORT_NATIVE_SIGNATURE_CHANGED");
        }
        string Address(object a)
        {
            var pin = Field(a, B("Ds3K5LVxwhM"));
            return Convert.ToUInt32(Field(a, B("iihK5hUQPDy"))) + ":" +
                Convert.ToInt32(Field(pin, B("TqBK5Pk3Cw2"))) + ":" + Convert.ToInt32(Field(pin, B("hWTK5MSRidQ")));
        }
        object[] Links(object model)
        {
            var map = model.GetType().GetMethod(B("yKHKOFfNm2M"), Fields)!.Invoke(model, null)!;
            return ((IDictionary)Field(map, B("cHuiFsU5V56"))).Keys.Cast<object>().ToArray();
        }
        string Edge(object e) => Address(Field(e, B("fH0izeMOw73"))) + ">" + Address(Field(e, B("ABfizkqh4mD")));
        var edges = Links(graph.Model);
        var touching = edges.Where(e => Convert.ToUInt32(Field(Field(e, B("fH0izeMOw73")), B("iihK5hUQPDy"))) == 29u ||
            Convert.ToUInt32(Field(Field(e, B("ABfizkqh4mD")), B("iihK5hUQPDy"))) == 29u).ToArray();
        var expectedEdges = new[] { "11:4:0>29:3:0", "27:2:0>29:1:0", "28:4:0>29:3:1" };
        if (edges.Length != 38 || !touching.Select(Edge).OrderBy(s => s, StringComparer.Ordinal).SequenceEqual(expectedEdges))
            throw new InvalidOperationException("CLASSIC_TELEPORT_CONNECTIONS_CHANGED");
        if (beforeId == 805u)
            return new { ok = true, graphId = graph.Id, changed = false, definition = 805u, persistentSaveVerified = false, playtestVerified = false };

        var manager = Editor().GetType(B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"), true)!;
        var serialize = manager.GetMethod(B("oGZiJdFmLSF"), BindingFlags.Static | BindingFlags.NonPublic)!;
        var deserialize = manager.GetMethod(B("WnqiJxnOpxs"), BindingFlags.Static | BindingFlags.NonPublic)!;
        object Serialize(object model) => serialize.Invoke(null, new object?[] { model, null, false })!;
        bool Same(object a, object b) => (bool)a.GetType().GetMethod("Equals", new[] { a.GetType() })!.Invoke(a, new[] { b })!;
        var before = Serialize(graph.Model);
        var rehearsal = deserialize.Invoke(null, new[] { before }) ?? throw new InvalidOperationException("CLASSIC_TELEPORT_CLONE_FAILED");
        var backupNode = GraphNodes(rehearsal)[29u]!;
        var copy = backupNode.GetType().GetMethod("DeepCopy", Fields)!;
        var backup = copy.Invoke(backupNode, new[] { Activator.CreateInstance(copy.GetParameters()[0].ParameterType) })!;
        object Value(object n, int index)
        {
            var wrapper = Pin(n, 3, index).GetType().GetProperty("value")!.GetValue(Pin(n, 3, index))!;
            return wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        }
        void Replace(object model, object definition, bool restore)
        {
            var map = GraphNodes(model);
            if (map.Contains(29u) && !(bool)model.GetType().GetMethod(B("zbUKmIZoGMn"), Fields)!.Invoke(model, new object?[] { 29u, null, false, false, false })!)
                throw new InvalidOperationException("CLASSIC_TELEPORT_DELETE_REJECTED");
            var replacement = model.GetType().GetMethod(B("lLEKmep2RXi"), Fields)!.Invoke(model,
                new object?[] { 29u, Stored(definition, B("U0oKESVcL9L")), x, y, null, restore ? backup : null })
                ?? throw new InvalidOperationException("CLASSIC_TELEPORT_CREATE_REJECTED");
            if (!restore)
                for (var i = 0; i < 3; i++)
                {
                    var targetValue = Value(replacement, i);
                    var copyValue = targetValue.GetType().GetMethod("CopyValue", Fields)!;
                    if (!(bool)copyValue.Invoke(targetValue, new[] { Value(backup, i), Activator.CreateInstance(copyValue.GetParameters()[1].ParameterType) })!)
                        throw new InvalidOperationException("CLASSIC_TELEPORT_VALUE_COPY_FAILED");
                }
            foreach (var edge in touching)
                if (!(bool)model.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(model, new object?[] { edge, null, -1 })!)
                    throw new InvalidOperationException("CLASSIC_TELEPORT_LINK_REJECTED");
            if (GraphNodes(model).Count != 29 || !Links(model).Select(Edge).OrderBy(s => s, StringComparer.Ordinal)
                .SequenceEqual(edges.Select(Edge).OrderBy(s => s, StringComparer.Ordinal)))
                throw new InvalidOperationException("CLASSIC_TELEPORT_READBACK_MISMATCH");
        }
        try
        {
            if (!Same(before, Serialize(rehearsal))) throw new InvalidOperationException("CLASSIC_TELEPORT_CLONE_NOT_LOSSLESS");
            Replace(rehearsal, newDef.Model, false);
            var expected = Serialize(rehearsal);
            Replace(rehearsal, oldDef.Model, true);
            if (!Same(before, Serialize(rehearsal))) throw new InvalidOperationException("CLASSIC_TELEPORT_ROLLBACK_REHEARSAL_FAILED");
            try
            {
                Replace(graph.Model, newDef.Model, false);
                if (!Same(expected, Serialize(graph.Model))) throw new InvalidOperationException("CLASSIC_TELEPORT_NATIVE_POSTCHECK_FAILED");
            }
            catch (Exception error)
            {
                Replace(graph.Model, oldDef.Model, true);
                if (!Same(before, Serialize(graph.Model))) throw new InvalidOperationException("CLASSIC_TELEPORT_ROLLBACK_FAILED", error);
                throw new InvalidOperationException("CLASSIC_TELEPORT_REPAIR_ABORTED_AND_ROLLED_BACK", error);
            }
            return new { ok = true, graphId = graph.Id, nodeIndex = 29, changed = true, before = 288u, after = 805u,
                nodeCount = 29, edgeCount = 38, nativeRehearsalMatched = true, persistentSaveVerified = false, playtestVerified = false };
        }
        finally
        {
            backup.GetType().GetMethod("Recycle", Fields)!.Invoke(backup, null);
            rehearsal.GetType().GetMethod("Recycle", Fields)!.Invoke(rehearsal, null);
        }
    }
}
