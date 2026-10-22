using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Selects the graph(s) the caller wants logged into the native log-listener
// payload (inner message only). Source evidence: .runtime/editor-bridge/
// control-research/log-selection-annotated.cs:277-342 shows I0au4eD9h3w taking
// server (P0) and client (P1) graph IDs, limited to 10 and 99 respectively. Our
// payload fills the server list and leaves the client list empty.
//
// THE IDENTITY COMES FROM THE REQUEST, NEVER FROM THIS FILE. The old code named
// the stale course set (MW_Platform_Calibration_20260916 / MW_Route_Tiled_20260916)
// as REQUIRED -- those graphs do not exist in the live level, so the op refused
// with LOG_SELECTION_GRAPH_IDENTITY_NOT_UNIQUE:MW_Platform_Calibration_20260916:0
// (the trailing 0 is the MATCH COUNT, i.e. "found none"). That hard requirement is
// removed. The request may instead carry:
//   * `ids`       exact graph resource ids. This is the ONLY extra field the bridge
//                 queue can carry on a `call` (elevated-runner.ps1 closed allowlist
//                 kind/runId/op/ids) and call-bridge.ps1 forwards `-Ids` verbatim.
//   * `graphName` a stored graph name (accepted for a richer caller; never invented).
//   * neither    -> every graph of THIS PROJECT present in the LIVE level is
//                 selected, "own" being the same MW_ name-prefix rule the bounded
//                 graph-delete already uses.
// Every branch reads the LIVE level and refuses BY NAME. Nothing is ever selected
// silently and no id is hardcoded.
//
// Scope limit: this partial only builds and reads back the payload. It never
// sends (no PHCi086M7o5), never sets the enable bool (no XwtaSuJH9gv), and
// never touches outer/UI wiring (no h0UaSTjlMFm). The caller composes and sends.
internal sealed partial class EditorAdapter
{
    // Exact inner payload type used by the native log-enable path.
    static string LogSelectionInnerType => B("TCeimgaSv8HFWBZL2Emr.bNf3IEaS4GdguXca3eut");
    static string LogSelectionProtoType => B("uBi4l34XLv2OekpES2JT.auKUt14Xhrb73Hx3I35G");
    static string LogSelectionValueEnumType => B("WCR0NQ0CswmIYSaAlNFd.O64cM60CDshW0fYqf34D");
    static string LogSelectionServerGetter => B("S7iaSYGRaMA");
    static string LogSelectionClientGetter => B("IPXaSdaM4sT");
    static string LogSelectionValueSetter => B("Y1D4XTEyyiM");
    static string LogSelectionGraphIdSetter => B("dXk4XUyFwMq");
    static string LogSelectionValueField => B("mQ44XjcStXy");
    static string LogSelectionGraphIdField => B("SK14XFvgrVC");
    const uint LogSelectionValue=1u;          // native path writes the literal value 1
    const int LogSelectionServerMax=10;       // P0 limit, server graphs
    const int LogSelectionClientMax=99;       // P1 limit, client graphs
    // This project's own graph namespace. The SAME rule the bounded graph-delete
    // uses (OwnedGraphDelete.cs OwnedGraphDeleteNamePrefix) -- a live name test,
    // not a pinned id or an exact name.
    const string OwnGraphLogNamePrefix="MW_";
    // The request fields this op owns, on top of the queue envelope {id,op,nonce}.
    static readonly string[] OwnGraphLogRequestFields={"ids","graphName"};

    // What was selected and why, for the reply. Never dropped: the caller must be
    // able to see exactly which live graphs entered the payload.
    internal sealed record LogSelectionPlan(uint[] Ids,string Identity,object[] Graphs);

    // Strict, closed validation of the enable-own-graph-logging request. Unknown or
    // duplicate fields are refused by name so an untrusted queue entry cannot smuggle
    // a field a later branch is meant to consume. Zero ids and an empty name are not
    // "names nothing" -- they are malformed and refused here.
    internal static void ValidateOwnGraphLogging(JsonElement request)
    {
        if(request.ValueKind!=JsonValueKind.Object)
            throw new InvalidOperationException("LOG_SELECTION_REQUEST_NOT_OBJECT");
        var allowed=new HashSet<string>{"id","op","nonce"};
        foreach(var field in OwnGraphLogRequestFields)allowed.Add(field);
        var seen=new HashSet<string>();
        foreach(var property in request.EnumerateObject())
            if(!allowed.Contains(property.Name)||!seen.Add(property.Name))
                throw new InvalidOperationException("LOG_SELECTION_UNKNOWN_OR_DUPLICATE_FIELD:"+property.Name);
        if(request.TryGetProperty("ids",out var ids)&&ids.ValueKind!=JsonValueKind.Null)
        {
            if(ids.ValueKind!=JsonValueKind.Array)
                throw new InvalidOperationException("LOG_SELECTION_IDS_NOT_ARRAY");
            if(ids.GetArrayLength()<1||ids.GetArrayLength()>LogSelectionServerMax)
                throw new InvalidOperationException("LOG_SELECTION_ID_COUNT_OUT_OF_RANGE:"+ids.GetArrayLength());
            foreach(var element in ids.EnumerateArray())
                if(element.ValueKind!=JsonValueKind.Number||!element.TryGetUInt32(out var id)||id==0u)
                    throw new InvalidOperationException("LOG_SELECTION_ID_INVALID");
        }
        if(request.TryGetProperty("graphName",out var name)&&name.ValueKind!=JsonValueKind.Null)
            if(name.ValueKind!=JsonValueKind.String||string.IsNullOrEmpty(name.GetString()))
                throw new InvalidOperationException("LOG_SELECTION_GRAPH_NAME_INVALID");
    }

    // Read the requested identity out of the wire request. Validates first, so a
    // malformed field is a named refusal rather than a silent fall-through.
    static (string? Name,uint[] Ids) OwnGraphLogSelectionRequest(JsonElement request)
    {
        ValidateOwnGraphLogging(request);
        string? name=request.TryGetProperty("graphName",out var nameElement)&&nameElement.ValueKind==JsonValueKind.String
            ? nameElement.GetString() : null;
        var ids=new List<uint>();
        if(request.TryGetProperty("ids",out var idsElement)&&idsElement.ValueKind==JsonValueKind.Array)
            foreach(var element in idsElement.EnumerateArray()){element.TryGetUInt32(out var id);ids.Add(id);}
        return (name,ids.ToArray());
    }

    // Resolve the requested graph(s) from the LIVE level and hand their ids to the
    // payload builder. Selection only: nothing is sent. Returns the plan so the
    // caller can report exactly which live graphs entered the payload.
    LogSelectionPlan ConfigureOwnGraphLogSelection(object inner,string? requestedName,uint[] requestedIds)
    {
        var plan=PlanOwnGraphLogSelection(Resources(),requestedName,requestedIds);
        BuildGraphLogSelection(inner,plan.Ids);
        return plan;
    }

    // Pure selection over an already-read resource list. Every path reads the live
    // level; every failure is named. `identity` records WHICH request named the set.
    // Private: its parameter is the private nested Resource model (live-editor state).
    LogSelectionPlan PlanOwnGraphLogSelection(IEnumerable<Resource> resources,string? requestedName,uint[] requestedIds)
    {
        // One live graph resource per id: registry aliases can expose the same graph twice.
        var live=resources.Where(r=>r.Kind==9).GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        string Name(Resource r)=>Stored(r.Model,B("c1pKbESgr8S")) as string ?? "";
        Resource[] matches;
        string identity;
        if(requestedIds!=null && requestedIds.Length>0)
        {
            identity="ids="+string.Join(",",requestedIds);
            matches=live.Where(r=>requestedIds.Contains(r.Id)).ToArray();
            // The request named ids; every one of them must resolve in the LIVE level.
            var missing=requestedIds.Distinct().Where(id=>matches.All(m=>m.Id!=id)).ToArray();
            if(missing.Length>0)
                throw new InvalidOperationException("LOG_SELECTION_GRAPH_NOT_FOUND_IN_LEVEL:"+identity+":missing="+string.Join(",",missing));
        }
        else if(!string.IsNullOrEmpty(requestedName))
        {
            identity="name="+requestedName;
            matches=live.Where(r=>Name(r)==requestedName).ToArray();
        }
        else
        {
            identity="own-graphs-live:name-prefix="+OwnGraphLogNamePrefix;
            matches=live.Where(r=>Name(r).StartsWith(OwnGraphLogNamePrefix,StringComparison.Ordinal)).ToArray();
        }
        if(matches.Length==0)
            throw new InvalidOperationException("LOG_SELECTION_GRAPH_NOT_FOUND:"+identity);
        var selected=matches.Select(r=>r.Id).ToArray();
        if(selected.Distinct().Count()!=selected.Length)
            throw new InvalidOperationException("LOG_SELECTION_IDS_NOT_UNIQUE:"+identity);
        if(selected.Length>LogSelectionServerMax)
            throw new InvalidOperationException("LOG_SELECTION_ID_COUNT_OUT_OF_RANGE:"+selected.Length);
        var graphs=matches.Select(r=>new
        {
            id=r.Id,
            name=Name(r),
            category=r.Category,
            nodeCount=GraphNodes(r.Model).Count,
        }).ToArray();
        return new LogSelectionPlan(selected,identity,graphs);
    }

    // Fixed payload construction for the verified inner message. Preconditions,
    // bounds and readback are all asserted here; no send and no enable bool.
    internal object BuildGraphLogSelection(object inner,uint[] ids)
    {
        if(inner==null)throw new ArgumentNullException(nameof(inner));
        var editor=Editor();
        var innerType=editor.GetType(LogSelectionInnerType,true)
            ?? throw new MissingFieldException(LogSelectionInnerType);
        if(!innerType.IsInstanceOfType(inner))
            throw new InvalidOperationException("LOG_SELECTION_INNER_TYPE_MISMATCH:"+inner.GetType().FullName);
        if(ids==null || ids.Length<1 || ids.Length>LogSelectionServerMax)
            throw new InvalidOperationException("LOG_SELECTION_ID_COUNT_OUT_OF_RANGE:"+(ids==null?0:ids.Length));
        if(ids.Any(id=>id==0u) || ids.Distinct().Count()!=ids.Length)
            throw new InvalidOperationException("LOG_SELECTION_IDS_NOT_NONZERO_DISTINCT");

        var server=LogSelectionList(inner,LogSelectionServerGetter);
        var client=LogSelectionList(inner,LogSelectionClientGetter);
        // Both lists are expected virgin: the native writer starts from empty
        // lists and appends, so a pre-populated list means foreign state.
        if(server.Count!=0 || client.Count!=0)
            throw new InvalidOperationException("LOG_SELECTION_LISTS_NOT_EMPTY:"+server.Count+":"+client.Count);

        var protoType=editor.GetType(LogSelectionProtoType,true)
            ?? throw new MissingFieldException(LogSelectionProtoType);
        var valueEnum=editor.GetType(LogSelectionValueEnumType,true)
            ?? throw new MissingFieldException(LogSelectionValueEnumType);
        var setValue=protoType.GetMethod(LogSelectionValueSetter,Fields)
            ?? throw new MissingMethodException("LOG_SELECTION_SET_VALUE");
        var setGraphId=protoType.GetMethod(LogSelectionGraphIdSetter,Fields)
            ?? throw new MissingMethodException("LOG_SELECTION_SET_GRAPH_ID");
        var add=LogSelectionAdd(server,protoType);

        foreach(var id in ids)
        {
            var proto=Activator.CreateInstance(protoType)
                ?? throw new InvalidOperationException("LOG_SELECTION_PROTO_NOT_CREATED");
            setValue.Invoke(proto,new object?[]{Enum.ToObject(valueEnum,LogSelectionValue)});
            setGraphId.Invoke(proto,new object?[]{id});
            add.Invoke(server,new[]{proto});
        }

        // Server only: the client collection must stay untouched.
        if(client.Count!=0)
            throw new InvalidOperationException("LOG_SELECTION_CLIENT_NOT_EMPTY:"+client.Count);
        if(server.Count!=ids.Length)
            throw new InvalidOperationException("LOG_SELECTION_SERVER_COUNT_MISMATCH:"+server.Count+":"+ids.Length);

        var readback=server.Cast<object>().Select(entry=>new
        {
            type=entry.GetType().FullName,
            value=Convert.ToInt32(Field(entry,LogSelectionValueField)),
            graphId=(uint)Field(entry,LogSelectionGraphIdField),
        }).ToArray();
        for(var index=0;index<ids.Length;index++)
        {
            if(readback[index].type!=LogSelectionProtoType || readback[index].graphId!=ids[index] || readback[index].value!=(int)LogSelectionValue)
                throw new InvalidOperationException("LOG_SELECTION_READBACK_MISMATCH:"+index+":"+readback[index].type+":"+readback[index].graphId+":"+readback[index].value);
        }

        return new
        {
            ok=true,
            status="log-selection-payload-built-not-sent",
            selectedGraphIds=ids,
            graphValue=(int)LogSelectionValue,
            serverCount=server.Count,
            clientCount=client.Count,
            serverMax=LogSelectionServerMax,
            clientMax=LogSelectionClientMax,
            serverListField=LogSelectionServerGetter,
            clientListField=LogSelectionClientGetter,
            readback,
            enableFlagUnchanged=true,
            sent=false,
            notice="Payload readback only; the caller composes the outer message and sends. No enable bool and no UI action was performed.",
        };
    }

    // S7iaSYGRaMA()/IPXaSdaM4sT() are the native server/client collection accessors.
    IList LogSelectionList(object inner,string name)
    {
        var type=inner.GetType();
        object? value;
        var property=type.GetProperty(name,Fields);
        if(property!=null)value=property.GetValue(inner);
        else
        {
            var method=type.GetMethod(name,Fields) ?? throw new MissingMethodException("LOG_SELECTION_LIST_ACCESSOR:"+name);
            value=method.Invoke(inner,null);
        }
        if(value is IList list)return list;
        throw new InvalidOperationException("LOG_SELECTION_LIST_NOT_MUTABLE:"+name+":"+(value?.GetType().FullName??"null"));
    }

    // Typed Add(elementType): the native list is generic over the proto type.
    MethodInfo LogSelectionAdd(IList list,Type protoType)
    {
        var add=list.GetType().GetMethod("Add",new[]{protoType});
        if(add!=null)return add;
        // Only reached if the collection exposes Add through a different signature.
        return list.GetType().GetMethod("Add",new[]{typeof(object)})
            ?? throw new MissingMethodException("LOG_SELECTION_ADD:"+list.GetType().FullName);
    }
}
