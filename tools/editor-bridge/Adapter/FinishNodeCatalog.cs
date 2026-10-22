using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

// Read-only finish-node catalogue (Kind 6, exact category {10001,20000,22000,0}).
// Must be called after Resources() has materialized the registry models; the root
// integration owns that call order. Field reads plus the proven l6uKazVUo9s getter
// and the wrapper's public Value only: no native constructor, no lazy graph edit,
// no send and no file write. Native field names are reported verbatim and the
// numeric type values are given no semantic meaning here.
internal sealed partial class EditorAdapter
{
    const int FinishPinLimit = 64;
    static readonly uint[] FinishCategory = {10001,20000,22000,0};
    static readonly uint[] FinishNodeIds =
        {1,2,9,14,71,73,77,79,82,83,99,128,142,180,225,226,230,231,232,233,244,248,258,259,260,509,652,804};

    object FinishNodeCatalog(List<Resource> resources)
    {
        var byId = resources.Where(r => r.Kind == 6 && r.Category.SequenceEqual(FinishCategory))
            .GroupBy(r => r.Id).ToDictionary(g => g.Key, g => g.First());
        var missing = FinishNodeIds.Where(id => !byId.ContainsKey(id)).ToArray();
        if (missing.Length != 0)
            throw new InvalidOperationException("FINISH_NODE_DEFINITION_MISSING:" + string.Join(",", missing));
        return new {ok=true,status="finish-node-catalog-read-only",requestedIds=FinishNodeIds,
            nodeCount=FinishNodeIds.Length,
            nodes=FinishNodeIds.Select(id => FinishNodeSnapshot(byId[id])).ToArray(),
            nativeConstructorsInvoked=false,graphModified=false,sentToGame=false,
            persistentSaveVerified=false,playtestVerified=false};
    }

    object FinishNodeSnapshot(Resource r, int pinLimit = FinishPinLimit)
    {
        var pins = ((IEnumerable)r.Model).Cast<object>().ToArray();
        return new {id=r.Id,name=Stored(r.Model,B("DsBKEwvlwAl")),description=Stored(r.Model,B("HM9KEypghgm")),
            pinCount=pins.Length,pinsTruncated=pins.Length>pinLimit,
            pins=pins.Take(pinLimit).Select(FinishPinSnapshot).ToArray()};
    }

    object FinishPinSnapshot(object pin)
    {
        var key = Stored(pin,B("quGKmYyTPnA"));
        var kernel = Stored(pin,B("ruBKmDeUkU7"));
        var definition = FinishPinDefinition(pin);
        var valueType = definition == null ? null : Stored(definition,B("O2EKYx5c6Xs"));
        return new {name=Stored(pin,B("T5GKmPxKaWk")),
            kind=NativeKeyPart(key,B("TqBK5Pk3Cw2")),index=NativeKeyPart(key,B("hWTK5MSRidQ")),
            kernelKind=NativeKeyPart(kernel,B("TqBK5Pk3Cw2")),kernelIndex=NativeKeyPart(kernel,B("hWTK5MSRidQ")),
            valueTypeName=valueType?.ToString(),
            valueTypeValue=valueType == null ? null : (object)Convert.ToInt32(valueType),
            serverParamType=definition == null ? null : Stored(definition,B("pR9KY126SEr")),
            eOjKYPILbRH=definition == null ? null : Stored(definition,B("eOjKYPILbRH")),
            fbGKY8GZn68=definition == null ? null : Stored(definition,B("fbGKY8GZn68"))};
    }

    // Definition wrapper read through the getter already proven in AuditGraph.cs.
    // A null Value is expected for flow pins and is reported as absent, not coerced.
    object? FinishPinDefinition(object pin)
    {
        var getter=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)
            ?? throw new MissingMethodException("FINISH_PIN_DEFINITION_GETTER");
        var wrapper=getter.Invoke(pin,null)
            ?? throw new InvalidOperationException("FINISH_PIN_DEFINITION_WRAPPER");
        var value=wrapper.GetType().GetProperty("Value")
            ?? throw new MissingMemberException("FINISH_PIN_DEFINITION_VALUE");
        return value.GetValue(wrapper);
    }

    object? NativeKeyPart(object? key,string field)
        => key == null ? null : Convert.ToInt32(Field(key,field));
}
