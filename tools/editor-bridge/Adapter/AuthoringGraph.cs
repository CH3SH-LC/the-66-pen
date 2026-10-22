using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Miliastra.EditorBridge;

// Parameterized subset of the existing source-verified graph operations. Dispatcher only.
internal sealed partial class EditorAdapter
{
    // The four graph category kinds the recordings carry (data/node-contracts/shared/graph-kinds.json).
    // Only the server kind is proven creatable; the recorded client kinds stay requestable so
    // the native acceptance boundary is probed per kind instead of hidden behind a hardcode.
    static readonly uint[] AuthorGraphKinds = {20000u,20001u,20002u,20007u};

    // The node-definition category a graph of `graphKind` draws from. The registry carries the
    // four kinds above (data/node-contracts/shared/graph-kinds.json); a node category differs
    // from the server one ONLY in its second element, which IS the graph kind. Measured live by
    // `author graph catalog` on 2026-10-06 (level 1073741840):
    //   [10001,20000,22000,0] x500   [10001,20001,22000,0] x122
    //   [10001,20002,22000,0] x197   [10001,20007,22000,0] x110
    // Until 2026-10-06 every definition lookup in this file demanded the literal server tuple,
    // so a graph created with --graph-kind 20002 could not name ONE node of its own kind. The
    // creature combat nodes (200129 执行技能, 200130 战斗相关·攻击, 200131 战斗相关·追击,
    // 200041 设置自身攻击目标) are exactly the ones that were unreachable for that reason.
    // The tuple is now derived from the graph the caller already named. What must NOT change:
    // still kind==6, still exactly one model behind (category,id), still fail-closed with the
    // offender named by id.
    static uint[] AuthorCategory(uint graphKind) => new uint[]{10001,graphKind,22000,0};

    // Value slots with an in-repo proof, plus "auto". No name here is invented: each one is
    // the slot an existing builder already writes and reads back (see the header of this
    // patch). "bool" and "enum" are two DIFFERENT storage slots behind the SAME declared type
    // tuple (serverParamType,genericId,eOjKYPILbRH) = (4,4,1) at kind 3 -- AuthoringGraph.cs:396
    // writes 启动定时器(79) 3:2 是否循环 through the enum slot (:463-468) while :392 writes
    // 双分支(2) 3:0 条件 through the bool slot (:265) -- so the caller may name the slot, and
    // the write is always read back through the paired getter.
    static readonly string[] AuthorValueSlots = {"auto","int","uint","enum","float","bool","string","vector3"};
    // A scalar payload is exactly one tagged key. `list` carries its own scalars and is
    // bounded so one request cannot compose an unbounded edit.
    const int AuthorListLimit = 64;
    // A dict is a container like a list: bounded, and written per entry, so the same cap
    // applies (one request cannot compose an unbounded edit). Own constant, one place.
    const int AuthorDictLimit = 64;
    const int AuthorValueBatchLimit = 32;

    // Batch entries use actual native IDs, never build-plan array offsets. Validate the
    // entire closed shape before resolving or mutating any editor object.
    static void ValidateAuthorValueBatch(JsonElement values)
    {
        if(values.ValueKind!=JsonValueKind.Array || values.GetArrayLength()<1 || values.GetArrayLength()>AuthorValueBatchLimit)
            throw new InvalidOperationException("AUTHOR_VALUES_COUNT_INVALID");
        var pins=new HashSet<(uint,int)>();
        foreach(var item in values.EnumerateArray()) {
            var fields=new HashSet<string>(new[]{"nodeId","definitionId","portKind","portIndex","expect","value","slot"});
            if(item.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_VALUES_ENTRY_INVALID");
            foreach(var p in item.EnumerateObject())
                if(!fields.Remove(p.Name)) throw new InvalidOperationException("AUTHOR_VALUES_UNKNOWN_OR_DUPLICATE_FIELD:"+p.Name);
            if(fields.Count!=0) throw new InvalidOperationException("AUTHOR_VALUES_ENTRY_INCOMPLETE");
            uint UInt(string key,uint max=uint.MaxValue) => item.GetProperty(key).ValueKind==JsonValueKind.Number &&
                item.GetProperty(key).TryGetUInt32(out var n) && n<=max ? n :
                throw new InvalidOperationException("AUTHOR_VALUES_UINT_INVALID:"+key);
            if(UInt("nodeId")==0 || UInt("definitionId")==0) throw new InvalidOperationException("AUTHOR_VALUES_ID_ZERO");
            if(UInt("portKind")!=3) throw new InvalidOperationException("AUTHOR_VALUE_PORT_KIND_UNSUPPORTED");
            if(!pins.Add((UInt("nodeId"),(int)UInt("portIndex",int.MaxValue))))
                throw new InvalidOperationException("AUTHOR_VALUES_DUPLICATE_PIN");
            var expect=item.GetProperty("expect");
            var expectedFields=new HashSet<string>(new[]{"serverParamType","genericId"});
            if(expect.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_EXPECT_INVALID");
            foreach(var p in expect.EnumerateObject())
                if(!expectedFields.Remove(p.Name) || p.Value.ValueKind!=JsonValueKind.Number ||
                   !p.Value.TryGetUInt32(out var n) || n>int.MaxValue)
                    throw new InvalidOperationException("AUTHOR_EXPECT_INVALID:"+p.Name);
            if(expectedFields.Count!=0) throw new InvalidOperationException("AUTHOR_EXPECT_INCOMPLETE");
            var slot=item.GetProperty("slot");
            if(slot.ValueKind!=JsonValueKind.String || Array.IndexOf(AuthorValueSlots,slot.GetString()!)<0)
                throw new InvalidOperationException("AUTHOR_VALUE_SLOT_UNSUPPORTED");
            ValidateAuthorScalar(item.GetProperty("value"));
        }
    }
    static void ValidateAuthorScalar(JsonElement value)
    {
        if(value.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_VALUE_SHAPE_INVALID");
        var names=value.EnumerateObject().Select(p=>p.Name).ToArray();
        if(names.Length!=1) throw new InvalidOperationException("AUTHOR_VALUE_SHAPE_INVALID");
        var inner=value.GetProperty(names[0]);
        switch(names[0]) {
            case "int":
                if(!inner.TryGetInt32(out _)) throw new InvalidOperationException("AUTHOR_VALUE_INT_INVALID");
                return;
            case "uint":
                if(!inner.TryGetUInt32(out _)) throw new InvalidOperationException("AUTHOR_VALUE_UINT_INVALID");
                return;
            case "bool":
                if(inner.ValueKind!=JsonValueKind.True && inner.ValueKind!=JsonValueKind.False)
                    throw new InvalidOperationException("AUTHOR_VALUE_BOOL_INVALID");
                return;
            case "float":
                if(!inner.TryGetDouble(out var f) || !double.IsFinite(f) || Math.Abs(f)>1e9)
                    throw new InvalidOperationException("AUTHOR_VALUE_FLOAT_INVALID");
                return;
            case "string":
                if(inner.ValueKind!=JsonValueKind.String || inner.GetString()!.Length>1024)
                    throw new InvalidOperationException("AUTHOR_VALUE_STRING_INVALID");
                return;
            case "vector3":
                AuthorVectorPayload(value);
                return;
            case "list":
                if(inner.ValueKind!=JsonValueKind.Array || inner.GetArrayLength()>AuthorListLimit)
                    throw new InvalidOperationException("AUTHOR_VALUE_LIST_INVALID");
                foreach(var element in inner.EnumerateArray()) {
                    if(element.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_VALUE_LIST_INVALID");
                    var keys=element.EnumerateObject().Select(p=>p.Name).ToArray();
                    // A list element is a scalar of a shape the scalar path can already write.
                    // entity/vector/dict element types are NOT accepted, because no setter for
                    // them has an in-repo proof (see header note 3).
                    if(keys.Length!=1 || (keys[0]!="int" && keys[0]!="uint" && keys[0]!="float" && keys[0]!="string"))
                        throw new InvalidOperationException("AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED");
                    ValidateAuthorScalar(element);
                }
                return;
            case "dict":
                // A dict is a CONTAINER, written per entry exactly as `list` is written per
                // element -- not a scalar slot, which is why AuthorValueSlots and
                // paramtypes.slot_for(27) stay unchanged. The payload is an ordered ARRAY of
                // {key,value} pairs, never a JSON object: an object forces string keys and
                // silently collapses duplicate keys, while the editor's dict is a sequence
                // whose key type is whatever the live leaf carries.
                if(inner.ValueKind!=JsonValueKind.Array || inner.GetArrayLength()>AuthorDictLimit)
                    throw new InvalidOperationException("AUTHOR_VALUE_DICT_SHAPE_INVALID");
                var dictKeys=new HashSet<string>(StringComparer.Ordinal);
                foreach(var entry in inner.EnumerateArray()) {
                    if(entry.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_INVALID");
                    var pair=entry.EnumerateObject().Select(p=>p.Name).ToArray();
                    if(pair.Length!=2 || !pair.Contains("key") || !pair.Contains("value"))
                        throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_INVALID");
                    foreach(var leaf in new[]{"key","value"}) {
                        var leafValue=entry.GetProperty(leaf);
                        if(leafValue.ValueKind!=JsonValueKind.Object) throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED");
                        var leafName=leafValue.EnumerateObject().Select(p=>p.Name).SingleOrDefault();
                        // A leaf is a single-tag SCALAR of a shape AuthorWriteScalar can already
                        // write. list/dict leaves are refused for the same reason the list branch
                        // refuses them: no setter with an in-repo proof. Checking the tag BEFORE
                        // recursing keeps a nested container from riding in through ValidateAuthorScalar.
                        if(leafName!="int" && leafName!="uint" && leafName!="bool" && leafName!="float" && leafName!="string")
                            throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED");
                        ValidateAuthorScalar(leafValue);
                    }
                    if(!dictKeys.Add(CanonicalDictLeaf(entry.GetProperty("key"))))
                        throw new InvalidOperationException("AUTHOR_VALUE_DICT_DUPLICATE_KEY");
                }
                return;
            default:
                throw new InvalidOperationException("AUTHOR_VALUE_TYPE_UNSUPPORTED:"+names[0]);
        }
    }
    // The canonical text of one dict key leaf, used ONLY to detect a duplicate key in one
    // payload. It re-renders the parsed value, not the raw token, so two spellings of the
    // same key ('{"int":1}' and '{"int": 1}') compare equal; a raw-text compare would let a
    // duplicate through. Culture-invariant on purpose (a locale decimal comma must not split
    // one key into two).
    static string CanonicalDictLeaf(JsonElement leaf)
    {
        var name=leaf.EnumerateObject().Select(p=>p.Name).Single();
        var inner=leaf.GetProperty(name);
        return name switch {
            "string" => "string:"+inner.GetString(),
            "bool" => "bool:"+(inner.GetBoolean()?"true":"false"),
            "float" => "float:"+inner.GetDouble().ToString("R",System.Globalization.CultureInfo.InvariantCulture),
            _ => name+":"+inner.GetRawText()
        };
    }
    internal static void ValidateAuthorGraph(JsonElement request)
    {
        string Str(string key) => request.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()! : throw new InvalidOperationException("AUTHOR_REQUIRED_STRING:" + key);
        uint UInt(string key, uint max = uint.MaxValue) => request.TryGetProperty(key, out var v) && v.TryGetUInt32(out var n) && n <= max
            ? n : throw new InvalidOperationException("AUTHOR_REQUIRED_UINT:" + key);
        var action = Str("action");
        var fields = new Dictionary<string, string[]> {
            ["create"] = new[]{"graphKind"}, ["lookup"] = Array.Empty<string>(), ["inspect"] = new[]{"graphId"},
            ["add-node"] = new[]{"graphId","definitionId","x","y","expectedNodeCount"},
            ["set-print"] = new[]{"graphId","nodeId","text"},
            ["set-condition"] = new[]{"graphId","nodeId","value"},
            ["set-value"] = new[]{"graphId","nodeId","definitionId","portKind","portIndex","expect","value","slot"},
            ["set-values"] = new[]{"graphId","expectedNodeCount","values"},
            ["pin-slots"] = new[]{"graphId","nodeId"},
            ["build-count-gate"] = new[]{"graphId","limit","period"},
            ["build-plan"] = new[]{"graphId","expectedNodeCount","plan"},
            ["build-print"] = new[]{"graphId","expectedNodeCount","text"},
            ["connect"] = new[]{"graphId","fromNodeId","fromPortKind","fromPortIndex","toNodeId","toPortKind","toPortIndex"},
            ["disconnect"] = new[]{"graphId","fromNodeId","fromPortKind","fromPortIndex","toNodeId","toPortKind","toPortIndex"},
            ["bind"] = new[]{"graphId","expectedNodeCount","entityId"}, ["export"] = new[]{"graphId"}
        };
        if (!fields.TryGetValue(action, out var extras)) throw new InvalidOperationException("AUTHOR_ACTION_UNSUPPORTED");
        var allowed = new HashSet<string>(new[]{"id","op","nonce","action","name"}.Concat(extras));
        var seen = new HashSet<string>();
        foreach(var p in request.EnumerateObject())
            if(!allowed.Contains(p.Name) || !seen.Add(p.Name)) throw new InvalidOperationException("AUTHOR_UNKNOWN_OR_DUPLICATE_FIELD:" + p.Name);
        if(!Regex.IsMatch(Str("name"), @"\AMW_API_[A-Za-z0-9_]{1,48}\z")) throw new InvalidOperationException("AUTHOR_NAME_INVALID");
        if(action != "create" && action != "lookup" && UInt("graphId") == 0) throw new InvalidOperationException("AUTHOR_GRAPH_ID_ZERO");
        if(action == "create" && request.TryGetProperty("graphKind", out var kindValue) &&
           (kindValue.ValueKind != JsonValueKind.Number || !kindValue.TryGetUInt32(out var createKind) ||
            Array.IndexOf(AuthorGraphKinds, createKind) < 0))
            throw new InvalidOperationException("AUTHOR_GRAPH_KIND_UNSUPPORTED");
        if(action == "add-node") {
            // The closed {1,2,71} set is removed. It was never the authority and it
            // could not be: the authority is the live node-definition registry, applied
            // further down in AuthorGraph() where the resource models exist (kind==6,
            // exact server category {10001,20000,22000,0}, exactly one model behind the
            // id). ValidateAuthorGraph is static and has no registry access, so a copy of
            // the rule here could only ever be narrower than the real one -- and it was:
            // it refused 70/373/586 before a bridge request was ever built.
            // Only the *shape* is still checked here: a uint32 definition id.
            UInt("definitionId");
            UInt("expectedNodeCount",127);
            foreach(var key in new[]{"x","y"})
                if(!request.TryGetProperty(key,out var v) || !v.TryGetDouble(out var d) || !double.IsFinite(d) || Math.Abs(d)>10000)
                    throw new InvalidOperationException("AUTHOR_LAYOUT_INVALID:"+key);
        }
        if(action == "bind" && (UInt("expectedNodeCount",128)==0 || UInt("entityId")==0)) throw new InvalidOperationException("AUTHOR_EMPTY_BIND");
        if(action == "build-print") {
            if(UInt("expectedNodeCount")!=0) throw new InvalidOperationException("AUTHOR_PRINT_REQUIRES_EMPTY_GRAPH");
            if(Str("text")!=AuthorPrintText(Str("name"))) throw new InvalidOperationException("AUTHOR_PRINT_TEXT_MISMATCH");
        }
        if(action == "build-plan") {
            // One dispatch builds a whole graph. The shape is checked here; the node
            // definitions are resolved against the live registry further down, where a
            // static copy of that rule could only ever be narrower than the real one.
            if(UInt("expectedNodeCount")!=0) throw new InvalidOperationException("AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH");
            if(!request.TryGetProperty("plan",out var planValue) || planValue.ValueKind!=JsonValueKind.Object)
                throw new InvalidOperationException("AUTHOR_REQUIRED_OBJECT:plan");
            if(!planValue.TryGetProperty("nodes",out var planNodes) || planNodes.ValueKind!=JsonValueKind.Array ||
               planNodes.GetArrayLength()==0 || planNodes.GetArrayLength()>128)
                throw new InvalidOperationException("AUTHOR_PLAN_NODES");
            // Validate every dict before BuildAuthorPlan spends the claim or creates nodes.
            // A bad later entry must not leave an earlier entry appended to the live graph.
            if(planValue.TryGetProperty("values",out var planValues) && planValues.ValueKind==JsonValueKind.Array) {
                foreach(var item in planValues.EnumerateArray()) {
                    if(item.ValueKind==JsonValueKind.Object && item.TryGetProperty("value",out var planScalar) &&
                       planScalar.ValueKind==JsonValueKind.Object &&
                       (planScalar.TryGetProperty("dict",out _) || planScalar.TryGetProperty("vector3",out _)))
                        ValidateAuthorScalar(planScalar);
                    if(item.ValueKind==JsonValueKind.Object && item.TryGetProperty("slot",out var planSlot) &&
                       planSlot.ValueKind==JsonValueKind.String && planSlot.GetString()=="vector3")
                        AuthorVectorPayload(item.GetProperty("value"));
                }
            }
        }
        if(action == "set-print") { UInt("nodeId"); if(Str("text").Length>1024) throw new InvalidOperationException("AUTHOR_TEXT_TOO_LONG"); }
        if(action == "set-condition") {
            UInt("nodeId");
            if(!request.TryGetProperty("value",out var value) ||
               (value.ValueKind!=JsonValueKind.True && value.ValueKind!=JsonValueKind.False))
                throw new InvalidOperationException("AUTHOR_REQUIRED_BOOL:value");
        }
        if(action == "pin-slots") { UInt("nodeId"); }
        if(action == "set-values") {
            if(UInt("expectedNodeCount",128)==0) throw new InvalidOperationException("AUTHOR_VALUES_EMPTY_GRAPH");
            if(Str("id").Length==0 || Str("id").Length>128) throw new InvalidOperationException("AUTHOR_VALUES_REQUEST_ID_INVALID");
            if(!request.TryGetProperty("values",out var values)) throw new InvalidOperationException("AUTHOR_REQUIRED_ARRAY:values");
            ValidateAuthorValueBatch(values);
        }
        if(action == "set-value") {
            UInt("nodeId");
            if(request.TryGetProperty("definitionId",out _ ) && UInt("definitionId")==0)
                throw new InvalidOperationException("AUTHOR_NODE_IDENTITY_MISMATCH");
            // The port kind is explicit and fixed to the data-input kind, the same enum the
            // existing connect path already pins (author.py:70-72): 3 = input data.
            if((request.TryGetProperty("portKind",out _) ? UInt("portKind") : 3u) != 3u)
                throw new InvalidOperationException("AUTHOR_VALUE_PORT_KIND_UNSUPPORTED");
            // D2: the index is required, never defaulted. ValidateAuthorGraph has no registry
            // access, so it cannot know which index exists; a hardcoded 0 here (or in the CLI)
            // would silently aim the write at a different pin than the caller named. The live
            // registry is the authority and it is consulted in AuthorGraph() below, where an
            // undeclared (kind,index) is refused as AUTHOR_VALUE_PORT_UNKNOWN.
            UInt("portIndex");
            // `expect` is not decoration. The caller states the (serverParamType, genericId)
            // it believes the pin carries, in the SAME numbering the adapter reads from the
            // live registry. data/node-contracts carries a DIFFERENT number in
            // valueTypeValueRaw (defId 1 3:0: 5 vs serverParamType 6, defId 79 3:3:
            // List vs 10); a caller that mixes the two is refused here instead of writing
            // into a wrongly-typed slot.
            if(!request.TryGetProperty("expect",out var expect) || expect.ValueKind!=JsonValueKind.Object)
                throw new InvalidOperationException("AUTHOR_REQUIRED_OBJECT:expect");
            foreach(var part in new[]{"serverParamType","genericId"})
                if(!expect.TryGetProperty(part,out var partValue) || !partValue.TryGetUInt32(out _))
                    throw new InvalidOperationException("AUTHOR_EXPECT_INVALID:"+part);
            if(!request.TryGetProperty("value",out var scalar)) throw new InvalidOperationException("AUTHOR_REQUIRED_VALUE");
            ValidateAuthorScalar(scalar);
            if(request.TryGetProperty("slot",out var slotValue) &&
               (slotValue.ValueKind!=JsonValueKind.String || Array.IndexOf(AuthorValueSlots,slotValue.GetString()!)<0))
                throw new InvalidOperationException("AUTHOR_VALUE_SLOT_UNSUPPORTED");
        }
        if(action == "build-count-gate") {
            if(!request.TryGetProperty("limit",out var countLimit) || countLimit.ValueKind!=JsonValueKind.Number ||
               !countLimit.TryGetUInt32(out var positiveLimit) || positiveLimit==0 || positiveLimit>1000000)
                throw new InvalidOperationException("AUTHOR_COUNT_LIMIT_INVALID");
            if(!request.TryGetProperty("period",out var period) || period.ValueKind!=JsonValueKind.Number || !period.TryGetDouble(out var seconds) ||
               !double.IsFinite(seconds) || seconds<0.1 || seconds>3600)
                throw new InvalidOperationException("AUTHOR_COUNT_PERIOD_INVALID");
        }
        if(action == "connect" || action == "disconnect") {
            UInt("fromNodeId"); UInt("toNodeId");
            // Port kinds/indices are explicit. An omitted field keeps the historical
            // execution pin (2,0)->(1,0) that the pre-existing wire built; an omitted
            // field never selects a new pin by itself. Kinds are the native enum
            // values 1..4, not guesses.
            var fromKind = request.TryGetProperty("fromPortKind",out _) ? UInt("fromPortKind") : 2u;
            var toKind = request.TryGetProperty("toPortKind",out _) ? UInt("toPortKind") : 1u;
            if(fromKind < 1 || fromKind > 4) throw new InvalidOperationException("AUTHOR_EDGE_PORT_KIND_UNSUPPORTED:fromPortKind");
            if(toKind < 1 || toKind > 4) throw new InvalidOperationException("AUTHOR_EDGE_PORT_KIND_UNSUPPORTED:toPortKind");
            if(request.TryGetProperty("fromPortIndex",out _)) UInt("fromPortIndex");
            if(request.TryGetProperty("toPortIndex",out _)) UInt("toPortIndex");
        }
    }

    // The graph actions that mutate NOTHING, so the bound-graph guard in AuthorGraph() may let
    // them through a bound graph. This is an ALLOWLIST for exactly one reason: an action that is
    // not named here is treated as a WRITE, so a new action (or a typo) fails closed toward the
    // refusal instead of silently gaining bound-graph access. Each name is justified by the branch
    // it selects, not by its label:
    //   pin-slots -> the AuthorGraph() branch whose status is `node-value-slots-read-only`: it
    //                reads the DECLARED pin schema (AuthorDeclaredPins) and the LIVE instance
    //                storage kind (AuthorStorageKind), invokes no native constructor/setter/
    //                Link/Add, and returns graphModified:false / nativeConstructorsInvoked:false.
    //                It is the discovery instrument the value branch's read half needs -- and on
    //                a BOUND graph that read is the whole point, since a bound graph is the one
    //                whose instance values are materialised.
    // Every other graph action that reaches the guard -- build-print, build-plan, build-count-gate,
    // add-node, set-value, connect, disconnect, set-print, set-condition -- performs a native
    // mutation and therefore keeps the refusal. `bind` is exempt on its own line (its branch is
    // idempotent: an already-bound graph returns the read-back, it does not re-write).
    static bool AuthorReadOnly(string action) => action=="pin-slots";

    public object AuthorGraph(JsonElement request, string exportDirectory)
    {
        ValidateAuthorGraph(request);
        string S(string key)=>request.GetProperty(key).GetString()!;
        uint U(string key)=>request.GetProperty(key).GetUInt32();
        // An absent port field keeps the historical execution pin, never a new one.
        uint OU(string key,uint fallback)=>request.TryGetProperty(key,out var probe)&&probe.TryGetUInt32(out var value)?value:fallback;
        var action=S("action"); var name=S("name");
        var resources=Resources();
        var matches=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==name)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(action=="create") {
            if(matches.Length!=0) throw new InvalidOperationException("AUTHOR_NAME_ALREADY_EXISTS");
            if(Spent("author-create",name)) throw new InvalidOperationException("AUTHOR_CREATE_ALREADY_ATTEMPTED");
            Spend("author-create",name);
            var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
            var create=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
            // No graphKind keeps the single proven server kind; a supplied one was already
            // restricted to the recorded kinds by ValidateAuthorGraph.
            var graphKind=request.TryGetProperty("graphKind",out var kindValue)?kindValue.GetUInt32():20000u;
            create.Invoke(manager,new object?[]{Enum.ToObject(create.GetParameters()[0].ParameterType,graphKind),name,0u,null});
            return new {ok=true,status="create-requested-readback-pending",name,graphKind,persistentSaveVerified=false,runtimeVerified=false};
        }
        if(action=="lookup" && matches.Length==0) return new {ok=true,status="lookup-pending",name,persistentSaveVerified=false,runtimeVerified=false};
        if(matches.Length!=1 || (action!="lookup" && matches[0].Id!=U("graphId"))) throw new InvalidOperationException("AUTHOR_GRAPH_IDENTITY_MISMATCH");
        var graph=matches[0]; var nodes=GraphNodes(graph.Model);
        // The node category this graph's OWN kind draws from. A graph whose stored category is
        // not one of the four recorded kinds is refused rather than defaulted to the server one:
        // defaulting is what made a client graph silently search the wrong registry.
        if(graph.Category==null || graph.Category.Length!=4 || graph.Category[0]!=10000u ||
           graph.Category[2]!=21001u || graph.Category[3]!=0u ||
           Array.IndexOf(AuthorGraphKinds,graph.Category[1])<0)
            throw new InvalidOperationException("AUTHOR_GRAPH_CATEGORY_UNSUPPORTED:"+
                string.Join(",",graph.Category??Array.Empty<uint>()));
        var authorCategory=AuthorCategory(graph.Category[1]);
        uint Def(object n)=>(uint)Field(Stored(n,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"));
        object Node(uint id,uint definition) {
            if(!nodes.Contains(id) || Def(nodes[id]!)!=definition) throw new InvalidOperationException("AUTHOR_NODE_IDENTITY_MISMATCH");
            return nodes[id]!;
        }
        object State(string status) {
            var level=entityModels.Where(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u).ToArray();
            return new {ok=true,status,name,graphId=graph.Id,nodeCount=nodes.Count,
                nodes=nodes.Keys.Cast<object>().Select(k=>new {nodeId=Convert.ToUInt32(k),definitionId=Def(nodes[k]!)}).ToArray(),
                boundEntityIds=entityModels.Where(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)).Select(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))).Distinct().ToArray(),
                boundToLevel=level.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)),
                persistentSaveVerified=false,runtimeVerified=false};
        }
        if(action=="inspect" || action=="lookup") return State("editor-model-readback");
        if(action=="export") return ExportResource(graph,exportDirectory);
        // Editing a bound graph could immediately change gameplay. Require a separate unbound graph.
        // A READ-ONLY action is the one exception: it answers from the editor model and invokes no
        // native constructor/setter/Link/Add, so permitting it on a bound graph cannot reach live
        // gameplay. The exemption is the AuthorReadOnly ALLOWLIST, so every action that is not
        // proven read-only -- including any added later -- still takes this refusal verbatim.
        var bound=entityModels.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id));
        if(action!="bind" && bound && !AuthorReadOnly(action)) throw new InvalidOperationException("AUTHOR_BOUND_GRAPH_EDIT_REFUSED");
        if(action=="build-print") {
            BuildAuthorPrint(graph, resources, name, S("text"));
            return State("print-built-export-readback-pending");
        }
        if(action=="build-plan") {
            BuildAuthorPlan(graph, resources, request.GetProperty("plan"));
            return State("plan-built-export-readback-pending");
        }
        if(action=="build-count-gate") {
            BuildAuthorCountGate(graph, resources, name, U("limit"), (float)request.GetProperty("period").GetDouble());
            return State("count-gate-built-export-readback-pending");
        }
        var countGateReady = action=="bind" && Spent("author-count-ready",graph.Id.ToString()) &&
            nodes.Count==13 && nodes.Values.Cast<object>().Select(Def).OrderBy(n=>n).SequenceEqual(
                new uint[]{1,1,2,2,2,14,14,71,73,79,82,83,230});
        // Same two facts, one of them no longer a hardcoded id set. The 128-node cap is
        // unchanged. "Is this definition placeable in the server domain" is now decided
        // by the live registry instead of by membership in {1,2,71} -- which is exactly
        // what AUTHOR_GRAPH_OUTSIDE_SUPPORTED_SUBSET encoded. Behaviour that must NOT
        // change: a definition that is absent, or aliased by more than one model, still
        // fails the WHOLE graph closed, and the refusal still names the offender by id.
        // The countGateReady exemption is preserved verbatim: the 13-node count-gate and
        // the two-node print graph stay reachable even if the registry read is partial.
        if(!countGateReady && nodes.Count>128) throw new InvalidOperationException("AUTHOR_GRAPH_NODE_LIMIT_EXCEEDED");
        if(!countGateReady) foreach(var placeable in nodes.Values.Cast<object>().Select(Def).Distinct())
            if(!TryResolveAuthorDefinition(resources,placeable,authorCategory,out _))
                throw new InvalidOperationException("AUTHOR_GRAPH_NODE_DEFINITION_NOT_PLACEABLE:"+placeable);
        if(action=="bind" && U("expectedNodeCount")==2 && Regex.IsMatch(name,@"\AMW_API_SOL_L10_[a-z0-9]{6,16}_print\z") && !countGateReady) {
            // No ready reconstruction from a new scope. Partial or unknown builders
            // fail closed even when two nodes survived a failed setter/link.
            if(!Spent("author-print-ready",graph.Id.ToString()) || nodes.Count!=2 ||
               !nodes.Values.Cast<object>().Select(Def).OrderBy(n=>n).SequenceEqual(new uint[]{1,71}))
                throw new InvalidOperationException("AUTHOR_PRINT_NOT_READY_FOR_BIND");
        }
        if(action=="bind") {
            if(nodes.Count!=U("expectedNodeCount")) throw new InvalidOperationException("AUTHOR_NODE_COUNT_CONFLICT");
            var entityId=U("entityId");
            var entities=entityModels.Where(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==entityId).Distinct().ToArray();
            if(entities.Length!=1) throw new InvalidOperationException("AUTHOR_ENTITY_IDENTITY_NOT_UNIQUE");
            var entity=entities[0];
            if(EntityBindings(entity).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)) return State("already-bound-editor-model-readback");
            if((uint)entity.GetType().GetMethod(B("G9oiCBkSaYQ"),Fields)!.Invoke(entity,null)! !=entityId ||
               (uint)graph.Model.GetType().GetMethod(B("MexKm2jjjVm"),Fields)!.Invoke(graph.Model,null)! !=graph.Id)
                throw new InvalidOperationException("AUTHOR_NATIVE_ID_MISMATCH");
            var bindTarget=graph.Id+":"+entityId;
            if(Spent("author-bind",bindTarget)) throw new InvalidOperationException("AUTHOR_BIND_ALREADY_ATTEMPTED");
            var param=Editor().GetType(Param,true)!;
            var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
            object Wrap(string method,object v)=>param.GetMethod(method,BindingFlags.Public|BindingFlags.Static)!.Invoke(null,new[]{v})!;
            args.Add(Wrap(B("h8diA3iOGmJ"),true)); args.Add(Wrap(B("bKliA0tj1p1"),entityId));
            args.Add(Wrap(B("qsriAuLLSBe"),1u)); args.Add(Wrap(B("bKliA0tj1p1"),graph.Id));
            var producer=ExistingSingleton(Editor(),Producer);
            Spend("author-bind",bindTarget);
            producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,new object?[]{"beyondEditObjService","AddInstructionGraphForEditObj",null,args});
            return new {ok=true,status="binding-requested-readback-pending",name,graphId=graph.Id,entityId,persistentSaveVerified=false,runtimeVerified=false};
        }
        if(action=="add-node") {
            if(nodes.Count!=U("expectedNodeCount")) throw new InvalidOperationException("AUTHOR_NODE_COUNT_CONFLICT");
            var definitions=resources.Where(r=>r.Kind==6 && r.Id==U("definitionId") && r.Category.SequenceEqual(authorCategory)).ToArray();
            if(definitions.Length==0 || definitions.Any(r=>!ReferenceEquals(r.Model,definitions[0].Model)))
                throw new InvalidOperationException("AUTHOR_DEFINITION_IDENTITY_CONFLICT");
            var definition=definitions[0];
            if(definition.Id==2) RequireAuthorBranchDefinition(definition.Model);
            // The three-label test goes with the {1,2,71} set it duplicated. A label is a
            // display string; pinning it made "the definition happens to be called
            // 打印字符串" a precondition for writing a node, which is not an identity fact.
            // The identity facts that survive are the two directly above this line
            // (kind==6, exact server category, exactly one model; and for id==2 the exact
            // branch signature). What still has to fail closed is a definition declaring
            // NO pins at all: connect, any value write and the post-add readback all
            // address a pin by (kind,index), and against a pin-less definition they would
            // be silent no-ops instead of refusals.
            // NOTE: whether the surviving identity is SUFFICIENT is a live question --
            // see live-probe-plan.md §5 P3b. A definition that resolves uniquely here but
            // is rejected by native AddNode must still surface as AUTHOR_NODE_READBACK_FAILED
            // (:206 below), never as a false success.
            if(AuthorDeclaredPins(resources,definition.Id,authorCategory).Count==0) throw new InvalidOperationException("AUTHOR_DEFINITION_HAS_NO_DECLARED_PINS:"+definition.Id);
            var before=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).ToHashSet();
            var node=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,new object?[]{Stored(definition.Model,B("U0oKESVcL9L")),request.GetProperty("x").GetDouble(),request.GetProperty("y").GetDouble(),null,null});
            var added=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).Where(k=>!before.Contains(k)).ToArray();
            if(node==null || nodes.Count!=before.Count+1 || added.Length!=1 || Def(nodes[added[0]]!)!=definition.Id) throw new InvalidOperationException("AUTHOR_NODE_READBACK_FAILED");
            return State("node-added-editor-model-readback");
        }
        if(action=="set-values") {
            if(nodes.Count!=U("expectedNodeCount")) throw new InvalidOperationException("AUTHOR_NODE_COUNT_CONFLICT");
            var items=request.GetProperty("values").EnumerateArray().ToArray();
            var batchClaim=graph.Id+":"+S("id");
            var prepared=new (object Node,uint DefinitionId,string Slot,string Claim)[items.Length];
            return AuthorRunValueBatch(graph.Id,items.Length,i=>{
                var item=items[i]; var nodeId=item.GetProperty("nodeId").GetUInt32();
                var definitionId=item.GetProperty("definitionId").GetUInt32();
                var node=Node(nodeId,definitionId);
                var index=item.GetProperty("portIndex").GetInt32();
                var declared=AuthorDeclaredPins(resources,definitionId,authorCategory);
                if(!declared.TryGetValue((3,index),out var pin)) throw new InvalidOperationException("AUTHOR_VALUE_PORT_UNKNOWN:3:"+index);
                var expect=item.GetProperty("expect");
                if(pin.TypeId!=expect.GetProperty("serverParamType").GetInt32() || pin.GenericId!=expect.GetProperty("genericId").GetInt32())
                    throw new InvalidOperationException("AUTHOR_VALUE_TYPE_MISMATCH");
                var slot=item.GetProperty("slot").GetString()!;
                var claim=graph.Id+":"+nodeId+":3:"+index;
                if(Spent("author-set-value",claim)) throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED");
                AuthorPreflightPinValue(resources,definitionId,authorCategory,node,index,item.GetProperty("value"),slot);
                prepared[i]=(node,definitionId,slot,claim);
            },()=>{
                if(Spent("author-set-values",batchClaim)) throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED");
                Spend("author-set-values",batchClaim);
            },i=>{
                var item=items[i]; var p=prepared[i];
                // Share the single-value claim. A partially failed list/dict append is
                // never replayed through either entry point in this adapter scope.
                Spend("author-set-value",p.Claim);
                var written=AuthorWritePinValue(resources,p.DefinitionId,authorCategory,p.Node,3,
                    item.GetProperty("portIndex").GetInt32(),item.GetProperty("value"),p.Slot);
                return new {index=i,nodeId=item.GetProperty("nodeId").GetUInt32(),definitionId=p.DefinitionId,
                    portKind=3,portIndex=item.GetProperty("portIndex").GetInt32(),slot=written.Slot,
                    storageKind=written.StorageKind,elementsWritten=written.ElementsWritten,readback=written.Readback};
            });
        }
        if(action=="pin-slots" || action=="set-value") {
            // D1: `nodes` and `Def` are locals of THIS method (AuthoringGraph.cs:116-117).
            // They are read here, where they are in scope, and handed to the class-level
            // helpers as arguments -- the helpers themselves cannot see them.
            var node=GraphNode(nodes,U("nodeId"));
            var definitionId=Def(node);
            if(request.TryGetProperty("definitionId",out var expectedDefinition) && expectedDefinition.GetUInt32()!=definitionId)
                throw new InvalidOperationException("AUTHOR_NODE_IDENTITY_MISMATCH");
            var declared=AuthorDeclaredPins(resources,definitionId,authorCategory);
            if(action=="pin-slots") {
                // Read-only. This is the discovery instrument the live plan needs: it reports,
                // per declared pin, the signature the adapter compares AND the storage kind the
                // live instance actually carries. Nothing in data/node-contracts carries the
                // latter -- FinishNodeCatalog.cs:43-57 and GameNodeCatalog.cs read the
                // DEFINITION, never an instance value.
                return new {ok=true,status="node-value-slots-read-only",graphId=graph.Id,nodeId=U("nodeId"),
                    definitionId,
                    pins=declared.Values.OrderBy(p=>p.Kind).ThenBy(p=>p.Index).Select(pin=>{
                        object? storageKind=null; object? vector3=null; var probe="not-a-data-input-pin";
                        if(pin.Kind==3) {
                            try {
                                var value=AuthorPinScalar(node,pin.Kind,pin.Index);
                                storageKind=AuthorStorageKind(value); probe="read";
                                if((int)storageKind==7) {
                                    if(pin.TypeId!=0 && pin.TypeId!=12) throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_DECLARATION_MISMATCH");
                                    vector3=AuthorReadVector3(value);
                                }
                            }
                            catch(Exception ex) { probe=ex.GetType().Name+":"+ex.Message; }
                        }
                        return new {kind=pin.Kind,index=pin.Index,name=pin.Name,serverParamType=pin.TypeId,
                            genericId=pin.GenericId,storageKind,vector3,probe};
                    }).ToArray(),
                    nativeConstructorsInvoked=false,graphModified=false,sentToGame=false,
                    persistentSaveVerified=false,runtimeVerified=false};
            }
            var portKind=3; // validated to 3 above; written explicitly so the edge target string is unambiguous
            var portIndex=(int)U("portIndex");
            if(!declared.TryGetValue((portKind,portIndex),out var declaredPin))
                throw new InvalidOperationException("AUTHOR_VALUE_PORT_UNKNOWN:"+portKind+":"+portIndex);
            var expect=request.GetProperty("expect");
            var expectType=(int)expect.GetProperty("serverParamType").GetUInt32();
            var expectGeneric=(int)expect.GetProperty("genericId").GetUInt32();
            if(declaredPin.TypeId!=expectType || declaredPin.GenericId!=expectGeneric)
                throw new InvalidOperationException("AUTHOR_VALUE_TYPE_MISMATCH:"+declaredPin.TypeId+":"+declaredPin.GenericId+"!"+expectType+":"+expectGeneric);
            var slot=request.TryGetProperty("slot",out var slotField)?slotField.GetString()!:"auto";
            if(slot=="vector3" || request.GetProperty("value").TryGetProperty("vector3",out _))
                AuthorPreflightPinValue(resources,definitionId,authorCategory,node,portIndex,request.GetProperty("value"),slot);
            var claim=graph.Id+":"+U("nodeId")+":"+portKind+":"+portIndex;
            if(Spent("author-"+action,claim)) throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED");
            Spend("author-"+action,claim); // before the first native mutation; a partial failure never replays
            var written=AuthorWritePinValue(resources,definitionId,authorCategory,node,portKind,portIndex,request.GetProperty("value"),slot);
            return new {ok=true,status="value-set-readback-verified",graphId=graph.Id,nodeId=U("nodeId"),
                portKind,portIndex,slot=written.Slot,storageKind=written.StorageKind,
                elementsWritten=written.ElementsWritten,readback=written.Readback,
                persistentSaveVerified=false,runtimeVerified=false};
        }
        if(action=="connect" || action=="disconnect") {
            var fromKind=(int)OU("fromPortKind",2u); var toKind=(int)OU("toPortKind",1u);
            var fromPortIndex=(int)OU("fromPortIndex",0u); var toPortIndex=(int)OU("toPortIndex",0u);
            var fromId=U("fromNodeId"); var toId=U("toNodeId");
            if(fromId==toId) throw new InvalidOperationException("AUTHOR_SELF_LINK_REFUSED");
            if(fromKind!=2 && fromKind!=4) throw new InvalidOperationException("AUTHOR_EDGE_SOURCE_NOT_OUTPUT");
            if(toKind!=1 && toKind!=3) throw new InvalidOperationException("AUTHOR_EDGE_TARGET_NOT_INPUT");
            var edgeClass=fromKind==2 && toKind==1?"execution":fromKind==4 && toKind==3?"data":null;
            if(edgeClass==null) throw new InvalidOperationException("AUTHOR_EDGE_DIRECTION_MISMATCH");
            if(edgeClass=="execution" && (fromPortIndex>1 || toPortIndex!=0))
                throw new InvalidOperationException("AUTHOR_FLOW_PORT_UNSUPPORTED");
            if(!nodes.Contains(fromId) || !nodes.Contains(toId)) throw new InvalidOperationException("AUTHOR_NODE_IDENTITY_MISMATCH");
            var from=nodes[fromId]!; var to=nodes[toId]!;
            // Node composition stays bounded by AUTHOR_GRAPH_OUTSIDE_SUPPORTED_SUBSET
            // above; the port itself is now decided by the declared schema below,
            // so there is no second, hardcoded definition whitelist here.
            // Native GetPin and native link acceptance remain the authority. The two
            // branch ports are from the exact 7.1 server definition, not enum guesses.
            if(Def(from)==2 || Def(to)==2) {
                var definitions=resources.Where(r=>r.Kind==6 && r.Id==2 && r.Category.SequenceEqual(authorCategory)).ToArray();
                if(definitions.Length==0 || definitions.Any(r=>!ReferenceEquals(r.Model,definitions[0].Model)))
                    throw new InvalidOperationException("AUTHOR_DEFINITION_IDENTITY_CONFLICT");
                RequireAuthorBranchDefinition(definitions[0].Model);
            }
            // The declared port schema comes from the live node-definition registry:
            // a pin the definition does not declare is refused by name, never guessed,
            // and a data edge needs two ends with equal declared (typeId,genericId).
            var fromPins=AuthorDeclaredPins(resources,Def(from),authorCategory);
            var toPins=AuthorDeclaredPins(resources,Def(to),authorCategory);
            if(!fromPins.TryGetValue((fromKind,fromPortIndex),out var fromPin))
                throw new InvalidOperationException("AUTHOR_EDGE_PORT_UNKNOWN:"+fromKind+":"+fromPortIndex);
            if(!toPins.TryGetValue((toKind,toPortIndex),out var toPin))
                throw new InvalidOperationException("AUTHOR_EDGE_PORT_UNKNOWN:"+toKind+":"+toPortIndex);
            // 2026-10-06: a GENERIC end (declared typeId 0) is un-materialized. The native Link
            // accepts it and the editor resolves the type from the connected concrete end -- this
            // is the shape this file's own BuildAuthorCountGate local Link already builds
            // (concrete (3,3) into generic (0,0), the Link(tick,4,4,less,3,0) call below).
            // Insisting on declared-type equality here refused an edge the editor itself builds.
            // Concrete-to-concrete edges are still compared exactly.
            if(edgeClass=="data" && fromPin.TypeId!=0 && toPin.TypeId!=0 &&
               (fromPin.TypeId!=toPin.TypeId || fromPin.GenericId!=toPin.GenericId))
                throw new InvalidOperationException("AUTHOR_EDGE_TYPE_MISMATCH:"+fromPin.TypeId+":"+fromPin.GenericId+"!"+toPin.TypeId+":"+toPin.GenericId);
            var edgeTarget=graph.Id+":"+fromId+":"+fromKind+":"+fromPortIndex+":"+toId+":"+toKind+":"+toPortIndex;
            if(Spent("author-"+action,edgeTarget)) throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED");
            var output=Pin(from,fromKind,fromPortIndex); var input=Pin(to,toKind,toPortIndex);
            object Address(object pin)=>pin.GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(pin,null)!;
            var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
            var link=ctor.Invoke(new[]{Address(output),Address(input)});
            if(action=="disconnect") {
                var map=LinkMap(graph.Model);
                if(!HasLink(map,link)) return State("edge-already-absent-editor-model-readback");
                Spend("author-"+action,edgeTarget); // consumes the attempt before the native removal
                var disconnect=graph.Model.GetType().GetMethods(Fields).Single(m=>m.Name==B("vJwKOEFj00D") && m.GetParameters().Length==3);
                if(!(bool)disconnect.Invoke(graph.Model,new object?[]{link,null,false})!)
                    throw new InvalidOperationException("AUTHOR_LINK_DISCONNECT_REJECTED");
                if(HasLink(LinkMap(graph.Model),link)) throw new InvalidOperationException("AUTHOR_LINK_PRESENT_AFTER_DISCONNECT");
                return State("link-disconnected-readback-verified");
            }
            Spend("author-"+action,edgeTarget); // before the first native mutation; a partial failure never replays
            if(!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{link,null,-1})!) throw new InvalidOperationException("AUTHOR_LINK_REJECTED");
            return State("link-accepted-export-readback-pending");
        }
        var target=graph.Id+":"+U("nodeId");
        if(Spent("author-"+action,target)) throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED");
        if(action=="set-print") {
            var pin=Pin(Node(U("nodeId"),1),3,0);
            var wrapper=pin.GetType().GetProperty("value")!.GetValue(pin)!;
            var value=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) ?? throw new InvalidOperationException("AUTHOR_VALUE_NULL");
            var setter=value.GetType().GetMethod(B("MfLKK0bLIju"),Fields)!;
            Spend("author-"+action,target);
            setter.Invoke(value,new object?[]{S("text"),null});
            return State("print-value-set-export-readback-pending");
        }
        if(action=="set-condition") {
            var node=Node(U("nodeId"),2);
            var definition=resources.Where(r=>r.Kind==6 && r.Id==2 && r.Category.SequenceEqual(authorCategory)).ToArray();
            if(definition.Length==0 || definition.Any(r=>!ReferenceEquals(r.Model,definition[0].Model)))
                throw new InvalidOperationException("AUTHOR_DEFINITION_IDENTITY_CONFLICT");
            RequireAuthorBranchDefinition(definition[0].Model);
            var wrapper=Pin(node,3,0).GetType().GetProperty("value")!.GetValue(Pin(node,3,0))!;
            var value=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) ?? throw new InvalidOperationException("AUTHOR_VALUE_NULL");
            var setter=value.GetType().GetMethod(B("CHHKK434xan"),Fields)!;
            if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(bool))
                throw new InvalidOperationException("AUTHOR_BOOL_SETTER_SIGNATURE");
            Spend("author-"+action,target);
            setter.Invoke(value,new object?[]{request.GetProperty("value").GetBoolean(),null});
            return State("branch-condition-set-export-readback-pending");
        }
        throw new InvalidOperationException("AUTHOR_ACTION_UNSUPPORTED");
    }

    // The one place "may this definition be placed in this graph" is decided:
    // kind 6, the exact category tuple of the graph being edited, and exactly one model
    // behind the identity. add-node keeps its own inline copy of the same predicate because
    // it also needs the resolved model; this overload exists for the whole-graph gate,
    // which only needs the yes/no. Both fail closed identically. `category` is the graph's
    // own kind (AuthorCategory), never a fixed server tuple -- see that helper.
    static bool TryResolveAuthorDefinition(List<Resource> resources,uint definitionId,uint[] category,out Resource definition)
    {
        var matches=resources.Where(r=>r.Kind==6 && r.Id==definitionId && r.Category.SequenceEqual(category)).ToArray();
        definition=matches.Length==1 && !matches.Any(r=>!ReferenceEquals(r.Model,matches[0].Model))?matches[0]:null!;
        return definition!=null;
    }

    // Declared pins of one node definition, read from the live registry:
    // (kind,index) -> AuthorPin. A definition that is absent or not unique fails
    // closed, and an undeclared (kind,index) is never inferred from a number.
    Dictionary<(int,int),AuthorPin> AuthorDeclaredPins(List<Resource> resources,uint definitionId,uint[] category)
    {
        var matches=resources.Where(r=>r.Kind==6 && r.Id==definitionId && r.Category.SequenceEqual(category)).ToArray();
        if(matches.Length!=1 || matches.Any(r=>!ReferenceEquals(r.Model,matches[0].Model)))
            throw new InvalidOperationException("AUTHOR_EDGE_DEFINITION_NOT_UNIQUE:"+definitionId);
        var table=new Dictionary<(int,int),AuthorPin>();
        foreach(var pin in (IEnumerable)matches[0].Model) {
            var key=Stored(pin,B("quGKmYyTPnA")) ?? throw new InvalidOperationException("AUTHOR_EDGE_PIN_SCHEMA_MISMATCH");
            var kind=Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")));
            var index=Convert.ToInt32(Field(key,B("hWTK5MSRidQ")));
            var wrapped=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(pin,null)!;
            var declared=wrapped.GetType().GetProperty("Value")!.GetValue(wrapped);
            var typeId=declared==null?0:Convert.ToInt32(Stored(declared,B("pR9KY126SEr")));
            var genericId=declared==null?0:Convert.ToInt32(Stored(declared,B("fbGKY8GZn68")));
            if(!table.TryAdd((kind,index),new AuthorPin(kind,index,typeId,genericId,Stored(pin,B("T5GKmPxKaWk")) as string ?? "")))
                throw new InvalidOperationException("AUTHOR_EDGE_PIN_SCHEMA_MISMATCH");
        }
        return table;
    }
    sealed record AuthorPin(int Kind,int Index,int TypeId,int GenericId,string Name);
    static string AuthorPrintText(string name)
    {
        var match=Regex.Match(name,@"\AMW_API_SOL_L10_([a-z0-9]{6,16})_print\z");
        if(!match.Success) throw new InvalidOperationException("AUTHOR_PRINT_NAME_INVALID");
        return "SOL_L10_"+match.Groups[1].Value+"_PRINT_ONCE";
    }
    // Same native Add/GetPin/string setter/link as the proved 7.1 two-node graph.
    // Only this fixed smoke shape is composed; no caller-selected definitions or pins.
    void BuildAuthorPrint(Resource graph,List<Resource> resources,string name,string text)
    {
        if(text!=AuthorPrintText(name)) throw new InvalidOperationException("AUTHOR_PRINT_TEXT_MISMATCH");
        if(GraphNodes(graph.Model).Count!=0) throw new InvalidOperationException("AUTHOR_PRINT_REQUIRES_EMPTY_GRAPH");
        var claim=graph.Id.ToString();
        if(Spent("author-print",claim)) throw new InvalidOperationException("AUTHOR_PRINT_ALREADY_ATTEMPTED");
        var definitions=new Dictionary<uint,Resource>();
        foreach(var id in new uint[]{71,1}) {
            // The server tuple stays LITERAL here on purpose: this is the fixed 7.1 server
            // smoke shape (two-node print graph), not a caller-selected graph kind. Asked for
            // on any other kind it fails closed below, naming the definition -- it can never
            // silently write the shape into the wrong registry.
            var matches=resources.Where(r=>r.Kind==6 && r.Id==id && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0})).ToArray();
            if(matches.Length!=1 || Stored(matches[0].Model,B("DsBKEwvlwAl")) as string != (id==71?"实体创建时":"打印字符串"))
                throw new InvalidOperationException("AUTHOR_PRINT_DEFINITION_MISMATCH:"+id);
            var signatures=new List<string>();
            foreach(var pin in (IEnumerable)matches[0].Model) {
                var key=Stored(pin,B("quGKmYyTPnA")) ?? throw new InvalidOperationException("AUTHOR_PRINT_SCHEMA_MISMATCH");
                var wrapped=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(pin,null)!;
                var definition=wrapped.GetType().GetProperty("Value")!.GetValue(wrapped);
                int Part(string field)=>definition==null?0:Convert.ToInt32(Stored(definition,B(field)));
                signatures.Add(Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")))+":"+Convert.ToInt32(Field(key,B("hWTK5MSRidQ")))+":"+
                    Part("pR9KY126SEr")+":"+Part("fbGKY8GZn68")+":"+Part("eOjKYPILbRH")+":"+(Stored(pin,B("T5GKmPxKaWk")) as string ?? ""));
            }
            var expected=id==71?new[]{"2:0:0:0:0:","4:0:1:1:0:事件源实体","4:1:2:2:0:事件源GUID"}:
                new[]{"1:0:0:0:0:","2:0:0:0:0:","3:0:6:6:0:字符串"};
            if(!signatures.OrderBy(s=>s,StringComparer.Ordinal).SequenceEqual(expected.OrderBy(s=>s,StringComparer.Ordinal)))
                throw new InvalidOperationException("AUTHOR_PRINT_SCHEMA_MISMATCH:"+id);
            definitions.Add(id,matches[0]);
        }
        Spend("author-print",claim); // consumes attempt before first native mutation
        (object Node,uint Id) Add(uint id,double x) {
            var nodes=GraphNodes(graph.Model);var before=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).ToHashSet();
            var node=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
                new object?[]{Stored(definitions[id].Model,B("U0oKESVcL9L")),x,0d,null,null});
            var added=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).Where(k=>!before.Contains(k)).ToArray();
            if(node==null || nodes.Count!=before.Count+1 || added.Length!=1 ||
               (uint)Field(Stored(nodes[added[0]]!,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=id)
                throw new InvalidOperationException("AUTHOR_PRINT_NODE_READBACK_FAILED");
            return (node,added[0]);
        }
        var eventAdded=Add(71,0);var printAdded=Add(1,300);
        var eventNode=eventAdded.Node;var print=printAdded.Node;
        var textPin=Pin(print,3,0);var wrapper=textPin.GetType().GetProperty("value")!.GetValue(textPin)!;
        var value=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) ?? throw new InvalidOperationException("AUTHOR_PRINT_VALUE_NULL");
        var setter=value.GetType().GetMethod(B("MfLKK0bLIju"),Fields)!;
        if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(string))
            throw new InvalidOperationException("AUTHOR_PRINT_SETTER_SIGNATURE");
        var printId=printAdded.Id;var eventId=eventAdded.Id;
        Spend("author-set-print",graph.Id+":"+printId);
        setter.Invoke(value,new object?[]{text,null});
        object Address(object node,int kind)=>Pin(node,kind,0).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(node,kind,0),null)!;
        var constructor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
        var edge=constructor.Invoke(new[]{Address(eventNode,2),Address(print,1)});
        Spend("author-connect",graph.Id+":"+eventId+":0:"+printId);
        if(graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{edge,null,-1}) is not true)
            throw new InvalidOperationException("AUTHOR_PRINT_LINK_REJECTED");
        if(GraphNodes(graph.Model).Count!=2) throw new InvalidOperationException("AUTHOR_PRINT_NODE_READBACK_FAILED");
        Spend("author-print-ready",claim); // export/GIA is still mandatory before operator bind
    }

    // Exact historical 7.1 branch signature, re-read from the live registry before
    // authoring. A stale definition fails before any node/constant mutation.
    void RequireAuthorBranchDefinition(object definition)
    {
        var pins=((IEnumerable)definition).Cast<object>().ToArray();
        var expected=new HashSet<string>{"1:0:0:0","2:0:0:0","2:1:0:0","3:0:4:4"};
        var actual=new HashSet<string>();
        foreach(var pin in pins) {
            var key=Stored(pin,B("quGKmYyTPnA")) ?? throw new InvalidOperationException("AUTHOR_BRANCH_SCHEMA_MISMATCH");
            var wrapped=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(pin,null)!;
            var value=wrapped.GetType().GetProperty("Value")!.GetValue(wrapped);
            var signature=Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")))+":"+
                Convert.ToInt32(Field(key,B("hWTK5MSRidQ")))+":"+
                (value==null?0:Convert.ToInt32(Stored(value,B("pR9KY126SEr"))))+":"+
                (value==null?0:Convert.ToInt32(Stored(value,B("fbGKY8GZn68"))));
            if(!actual.Add(signature)) throw new InvalidOperationException("AUTHOR_BRANCH_SCHEMA_MISMATCH");
        }
        if(pins.Length!=4 || !actual.SetEquals(expected)) throw new InvalidOperationException("AUTHOR_BRANCH_SCHEMA_MISMATCH");
    }

    // One fixed numerical slice from GameLoopGraph: own repeating timer -> native
    // event loop-count -> integer comparison -> two marker branches. No variable CRUD.
    void BuildAuthorCountGate(Resource graph, List<Resource> resources, string name, uint limit, float period)
    {
        if(GraphNodes(graph.Model).Count!=0) throw new InvalidOperationException("AUTHOR_COUNT_REQUIRES_EMPTY_GRAPH");
        var claim=graph.Id.ToString();
        if(Spent("author-count",claim)) throw new InvalidOperationException("AUTHOR_COUNT_ALREADY_ATTEMPTED");
        var schemas=new Dictionary<uint,(string Label,string[] Pins)> {
            [1] = ("打印字符串", new[]{"1:0:0:0:0:","2:0:0:0:0:","3:0:6:6:0:字符串"}),
            [2] = ("双分支", new[]{"1:0:0:0:0:","2:0:0:0:0:是","2:1:0:0:0:否","3:0:4:4:1:条件"}),
            [14] = ("是否相等", new[]{"3:0:0:0:0:输入1","3:1:0:0:0:输入2","4:0:4:4:1:结果"}),
            [71] = ("实体创建时", new[]{"2:0:0:0:0:","4:0:1:1:0:事件源实体","4:1:2:2:0:事件源GUID"}),
            [73] = ("获取自身实体", new[]{"4:0:1:1:0:自身实体"}),
            [79] = ("启动定时器", new[]{"1:0:0:0:0:","2:0:0:0:0:","3:0:1:1:0:目标实体","3:1:6:6:0:定时器名称","3:2:4:4:1:是否循环","3:3:10:10:0:定时器序列","3:4:2:2:0:context_GUID"}),
            [82] = ("终止定时器", new[]{"1:0:0:0:0:","2:0:0:0:0:","3:0:1:1:0:目标实体","3:1:6:6:0:定时器名称"}),
            [83] = ("定时器触发时", new[]{"2:0:0:0:0:","4:0:1:1:0:事件源实体","4:1:2:2:0:事件源GUID","4:2:6:6:0:定时器名称","4:3:3:3:0:定时器序列序号","4:4:3:3:0:循环次数","4:5:2:2:0:context_GUID"}),
            [230] = ("数值小于", new[]{"3:0:0:0:0:左值","3:1:0:0:0:右值","3:2:14:10002:2:op","4:0:4:4:1:结果"}),
        };
        var definitions=new Dictionary<uint,Resource>();
        foreach(var item in schemas) {
            // Same reasoning as BuildAuthorPrint: the count gate is a fixed 7.1 server smoke
            // shape, so its registry tuple stays literal and a non-server graph fails closed
            // by name rather than being silently resolved against the wrong category.
            var matches=resources.Where(r=>r.Kind==6 && r.Id==item.Key && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0})).ToArray();
            if(matches.Length!=1 || Stored(matches[0].Model,B("DsBKEwvlwAl")) as string != item.Value.Label)
                throw new InvalidOperationException("AUTHOR_COUNT_DEFINITION_MISMATCH:"+item.Key);
            var pins=((IEnumerable)matches[0].Model).Cast<object>().ToArray();
            var signatures=new List<string>();
            foreach(var pin in pins) {
                var key=Stored(pin,B("quGKmYyTPnA")) ?? throw new InvalidOperationException("AUTHOR_COUNT_SCHEMA_MISMATCH");
                var wrapper=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(pin,null)!;
                var definition=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper);
                int Part(string field)=>definition==null?0:Convert.ToInt32(Stored(definition,B(field)));
                signatures.Add(Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")))+":"+Convert.ToInt32(Field(key,B("hWTK5MSRidQ")))+":"+
                    Part("pR9KY126SEr")+":"+Part("fbGKY8GZn68")+":"+Part("eOjKYPILbRH")+":"+(Stored(pin,B("T5GKmPxKaWk")) as string ?? ""));
            }
            if(!signatures.OrderBy(x=>x,StringComparer.Ordinal).SequenceEqual(item.Value.Pins.OrderBy(x=>x,StringComparer.Ordinal)))
                throw new InvalidOperationException("AUTHOR_COUNT_SCHEMA_MISMATCH:"+item.Key);
            definitions.Add(item.Key,matches[0]);
        }
        // Compile-time binding profile checks the exact editor SHA/MVID and method
        // contracts. No caller selects a symbol, constructor, definition, pin or opcode.
        Spend("author-count",claim); // before first native mutation; partial failures never replay
        object Add(uint id,int order) {
            var nodes=GraphNodes(graph.Model);var before=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).ToHashSet();
            var node=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
                new object?[]{Stored(definitions[id].Model,B("U0oKESVcL9L")),(double)(order%4*400),(double)(order/4*400),null,null});
            var added=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).Where(k=>!before.Contains(k)).ToArray();
            if(node==null || nodes.Count!=before.Count+1 || added.Length!=1 ||
               (uint)Field(Stored(nodes[added[0]]!,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=id)
                throw new InvalidOperationException("AUTHOR_COUNT_NODE_READBACK_FAILED");
            return node;
        }
        void Link(object from,int fk,int fi,object to,int tk,int ti) {
            object Address(object n,int k,int i)=>Pin(n,k,i).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(n,k,i),null)!;
            var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
            var edge=ctor.Invoke(new[]{Address(from,fk,fi),Address(to,tk,ti)});
            if(graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{edge,null,-1}) is not true)
                throw new InvalidOperationException("AUTHOR_COUNT_LINK_REJECTED");
        }
        object Value(object n,int i) {
            var pin=Pin(n,3,i);var wrapper=pin.GetType().GetProperty("value")!.GetValue(pin)!;
            return wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) ?? throw new InvalidOperationException("AUTHOR_COUNT_VALUE_NULL");
        }
        object Scalar(object n,int i) {
            var value=Value(n,i);
            if(Convert.ToInt32(value.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(value,null))==10000)
                value=value.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(value,null) ?? throw new InvalidOperationException("AUTHOR_COUNT_GENERIC_NULL");
            return value;
        }
        void SetText(object n,int i,string text)=>Scalar(n,i).GetType().GetMethod(B("MfLKK0bLIju"),Fields)!.Invoke(Scalar(n,i),new object?[]{text,null});
        var created=Add(71,0);var self=Add(73,1);var ownerEqual=Add(14,2);var ownerBranch=Add(2,3);
        var timer=Add(79,4);var tick=Add(83,5);var nameEqual=Add(14,6);var nameBranch=Add(2,7);
        var less=Add(230,8);var countBranch=Add(2,9);var below=Add(1,10);var reached=Add(1,11);var stop=Add(82,12);
        if(GraphNodes(graph.Model).Count!=13) throw new InvalidOperationException("AUTHOR_COUNT_NODE_READBACK_FAILED");
        Link(created,2,0,ownerBranch,1,0);Link(ownerBranch,2,0,timer,1,0);
        Link(created,4,0,ownerEqual,3,0);Link(self,4,0,ownerEqual,3,1);Link(ownerEqual,4,0,ownerBranch,3,0);Link(self,4,0,timer,3,0);
        Link(tick,2,0,nameBranch,1,0);Link(tick,4,2,nameEqual,3,0);Link(nameEqual,4,0,nameBranch,3,0);
        Link(nameBranch,2,0,countBranch,1,0);Link(tick,4,4,less,3,0);Link(less,4,0,countBranch,3,0);
        Link(countBranch,2,0,below,1,0);Link(countBranch,2,1,stop,1,0);Link(self,4,0,stop,3,0);Link(stop,2,0,reached,1,0);
        var timerName=name+"_COUNT";
        SetText(timer,1,timerName);SetText(nameEqual,1,timerName);SetText(stop,1,timerName);
        SetText(below,0,name+"_COUNT_BELOW");SetText(reached,0,name+"_COUNT_REACHED");
        // The ordinary timer's boolean is an enum widget. Reuse GameLoopGraph's
        // uint enum setter (native true=1), not the separate bool storage slot.
        var loop=Value(timer,2);var boolSetter=loop.GetType().GetMethod(B("X8oKKHB87Ue"),Fields)!;
        if(boolSetter.GetParameters().Length!=2 || boolSetter.GetParameters()[0].ParameterType!=typeof(uint))
            throw new InvalidOperationException("AUTHOR_COUNT_BOOL_SIGNATURE");
        boolSetter.Invoke(loop,new object?[]{1u,null});
        var sequencePin=((IEnumerable)definitions[79].Model).Cast<object>().Single(p=>{
            var key=Stored(p,B("quGKmYyTPnA"))!;return Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")))==3 && Convert.ToInt32(Field(key,B("hWTK5MSRidQ")))==3;});
        var sequenceWrapper=sequencePin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(sequencePin,null)!;
        var sequenceDefinition=sequenceWrapper.GetType().GetProperty("Value")!.GetValue(sequenceWrapper)!;
        var elementDefinition=sequenceDefinition.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(sequenceDefinition,null)!;
        var sequence=Value(timer,3);var element=sequence.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(sequence,new object?[]{elementDefinition,null})!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!.Invoke(element,new object?[]{period,null});
        var threshold=Scalar(less,1);
        // Native type inference from loop-count must have materialized S_INT on
        // both operands. Writing an int slot on None/float is not accepted.
        if(Convert.ToInt32(threshold.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(threshold,null))!=2 ||
           Convert.ToInt32(Scalar(less,0).GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(Scalar(less,0),null))!=2)
            throw new InvalidOperationException("AUTHOR_COUNT_INT_TYPE_NOT_MATERIALIZED");
        var setter=threshold.GetType().GetMethod(B("c84KKE8ihrN"),Fields)!;
        if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(int))
            throw new InvalidOperationException("AUTHOR_COUNT_INT_SIGNATURE");
        setter.Invoke(threshold,new object?[]{checked((int)limit),null});
        var readback=threshold.GetType().GetMethod(B("ilqKKrw7dhN"),Fields)!.Invoke(threshold,null)!;
        if(readback.GetType().GetProperty("Value")!.GetValue(readback) is not int observed || observed!=(int)limit)
            throw new InvalidOperationException("AUTHOR_COUNT_INT_READBACK_MISMATCH");
        Spend("author-count-ready",claim);
    }

    // One dispatch builds a whole graph from a caller plan. This is the batched form of the
    // per-node path: the runner re-hashes the entire pin set on EVERY dispatch, so a
    // forty-operation graph costs forty hashes and cannot fit inside the five-minute bridge
    // lease. Composing it in one call is the same native Add/Link/setter work the fixed count
    // gate above already does, generalised to a caller-supplied shape.
    //
    // The plan references nodes by their index in plan.nodes. Nothing is selected by name, and
    // every definition is still resolved against the LIVE registry (kind==6, exact server
    // category, exactly one model behind the id) before anything is added. Order is
    // nodes -> edges -> values, because a generic data pin (type 0) is materialised by the
    // native editor from a linked sibling, and a value write into an unmaterialised generic
    // pin is exactly the "加得进去配不出效果" case this must refuse rather than fake.
    void BuildAuthorPlan(Resource graph, List<Resource> resources, JsonElement plan)
    {
        if(GraphNodes(graph.Model).Count!=0) throw new InvalidOperationException("AUTHOR_PLAN_REQUIRES_EMPTY_GRAPH");
        var claim=graph.Id.ToString();
        if(Spent("author-plan",claim)) throw new InvalidOperationException("AUTHOR_PLAN_ALREADY_ATTEMPTED");
        var planNodes=plan.GetProperty("nodes");
        var count=planNodes.GetArrayLength();
        // The one definition category this plan resolves against, hoisted so the dict branch's
        // declared-pin lookup reuses the SAME array Resolve uses -- one hardcopy, not two.
        var planCategory=new uint[]{10001,20000,22000,0};
        var definitions=new Dictionary<uint,Resource>();
        Resource Resolve(uint id) {
            if(definitions.TryGetValue(id,out var cached)) return cached;
            var found=resources.Where(r=>r.Kind==6 && r.Id==id && r.Category.SequenceEqual(planCategory)).ToArray();
            if(found.Length!=1 || found.Any(r=>!ReferenceEquals(r.Model,found[0].Model)))
                throw new InvalidOperationException("AUTHOR_PLAN_DEFINITION_NOT_UNIQUE:"+id);
            definitions[id]=found[0]; return found[0];
        }
        var ids=new uint[count];
        for(int i=0;i<count;i++) {
            var spec=planNodes[i];
            if(spec.ValueKind!=JsonValueKind.Object || !spec.TryGetProperty("definitionId",out var idValue) ||
               !idValue.TryGetUInt32(out var id))
                throw new InvalidOperationException("AUTHOR_PLAN_NODE_SPEC:"+i);
            ids[i]=id; Resolve(id);
        }
        // A bad vector declaration or payload is refused before creating even the
        // first node. Storage materialization is checked again after native links.
        if(plan.TryGetProperty("values",out var vectorValues) && vectorValues.ValueKind==JsonValueKind.Array)
            foreach(var item in vectorValues.EnumerateArray()) {
                if(!item.TryGetProperty("value",out var value)) continue;
                var slot=item.TryGetProperty("slot",out var s)?s.GetString():null;
                if(slot!="vector3" && !value.TryGetProperty("vector3",out _)) continue;
                AuthorVectorPayload(value);
                if(slot!="auto" && slot!="vector3") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3");
                var ni=item.GetProperty("node").GetInt32();
                if(ni<0 || ni>=ids.Length) throw new InvalidOperationException("AUTHOR_PLAN_VALUE_NODE");
                AuthorRequireVectorDeclaration(resources,ids[ni],planCategory,3,item.GetProperty("portIndex").GetInt32());
            }
        Spend("author-plan",claim); // before the first native mutation; a partial failure never replays
        object Add(uint id,double x,double y) {
            var nodes=GraphNodes(graph.Model);var before=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).ToHashSet();
            var node=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
                new object?[]{Stored(definitions[id].Model,B("U0oKESVcL9L")),x,y,null,null});
            var added=nodes.Keys.Cast<object>().Select(Convert.ToUInt32).Where(k=>!before.Contains(k)).ToArray();
            if(node==null || nodes.Count!=before.Count+1 || added.Length!=1 ||
               (uint)Field(Stored(nodes[added[0]]!,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=id)
                throw new InvalidOperationException("AUTHOR_PLAN_NODE_READBACK_FAILED");
            return node;
        }
        void Link(object from,int fk,int fi,object to,int tk,int ti) {
            object Address(object n,int k,int i)=>Pin(n,k,i).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(n,k,i),null)!;
            var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
            var edge=ctor.Invoke(new[]{Address(from,fk,fi),Address(to,tk,ti)});
            if(graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{edge,null,-1}) is not true)
                throw new InvalidOperationException("AUTHOR_PLAN_LINK_REJECTED");
        }
        var handles=new List<object>(count);
        for(int i=0;i<count;i++) {
            var spec=planNodes[i];
            double x=spec.TryGetProperty("x",out var xv)&&xv.ValueKind==JsonValueKind.Number?xv.GetDouble():0;
            double y=spec.TryGetProperty("y",out var yv)&&yv.ValueKind==JsonValueKind.Number?yv.GetDouble():0;
            handles.Add(Add(ids[i],x,y));
        }
        if(handles.Count!=count) throw new InvalidOperationException("AUTHOR_PLAN_NODE_READBACK_FAILED");
        if(plan.TryGetProperty("edges",out var edges) && edges.ValueKind==JsonValueKind.Array) {
            foreach(var item in edges.EnumerateArray()) {
                int Part(string key)=>item.TryGetProperty(key,out var v)&&v.TryGetInt32(out var n)?n
                    :throw new InvalidOperationException("AUTHOR_PLAN_EDGE_SPEC:"+key);
                int from=Part("from"), to=Part("to");
                if(from<0||from>=handles.Count||to<0||to>=handles.Count||from==to)
                    throw new InvalidOperationException("AUTHOR_PLAN_EDGE_INDEX");
                Link(handles[from],Part("fromKind"),Part("fromIndex"),handles[to],Part("toKind"),Part("toIndex"));
            }
        }
        if(plan.TryGetProperty("values",out var values) && values.ValueKind==JsonValueKind.Array) {
            foreach(var item in values.EnumerateArray()) {
                if(!item.TryGetProperty("node",out var nv) || !nv.TryGetInt32(out var ni) || ni<0 || ni>=handles.Count)
                    throw new InvalidOperationException("AUTHOR_PLAN_VALUE_NODE");
                if(!item.TryGetProperty("portIndex",out var pv) || !pv.TryGetInt32(out var pi))
                    throw new InvalidOperationException("AUTHOR_PLAN_VALUE_PORT");
                if(!item.TryGetProperty("slot",out var sv) || sv.ValueKind!=JsonValueKind.String ||
                   !item.TryGetProperty("value",out var val) || val.ValueKind!=JsonValueKind.Object)
                    throw new InvalidOperationException("AUTHOR_PLAN_VALUE_SPEC");
                var scalar=AuthorPinScalar(handles[ni],3,pi);
                var slot=sv.GetString()!;
                var payloadName=val.EnumerateObject().First().Name;
                if(slot=="string" || payloadName=="string") {
                    // The string read-back symbol is NOT in the binding profile, so the
                    // shared AuthorWriteScalar path refuses it by name. Mirror set-print
                    // instead (AuthoringGraph.cs:457-465), which writes through the proven
                    // string setter and returns without a read-back. A non-string payload
                    // under a string slot is still refused -- this narrows nothing.
                    if(payloadName!="string") throw new InvalidOperationException("AUTHOR_PLAN_VALUE_SLOT_PAYLOAD_MISMATCH:string");
                    var text=val.GetProperty("string").GetString() ?? throw new InvalidOperationException("AUTHOR_PLAN_VALUE_STRING_NULL");
                    if(text.Length>1024) throw new InvalidOperationException("AUTHOR_PLAN_VALUE_TEXT_TOO_LONG");
                    scalar.GetType().GetMethod(B("MfLKK0bLIju"),Fields)!.Invoke(scalar,new object?[]{text,null});
                } else if(payloadName=="vector3" || slot=="vector3") {
                    AuthorWritePinValue(resources,ids[ni],planCategory,handles[ni],3,pi,val,slot);
                } else if(payloadName=="dict") {
                    // Batched-path dict constant. `scalar` is the pin's LIVE value object
                    // (fetched at :823), so the branch's own storage-kind assert (:1047) sees
                    // the instance, exactly as on the set-value path. `planCategory` is the one
                    // definition category this method resolves against (also used by Resolve).
                    AuthorWriteDict(resources,ids[ni],planCategory,3,pi,scalar,val.GetProperty("dict"),slot);
                } else {
                    AuthorWriteScalar(scalar,val,slot);
                }
            }
        }
        Spend("author-plan-ready",claim);
    }

    // ---- value writes -------------------------------------------------------------------
    // Kept separate so offline tests exercise the same preflight/stop-on-failure loop
    // as the dispatcher. There is deliberately no rollback and no retry.
    internal static object AuthorRunValueBatch(uint graphId,int count,Action<int> preflight,Action begin,Func<int,object> write)
    {
        if(count<1 || count>AuthorValueBatchLimit) throw new InvalidOperationException("AUTHOR_VALUES_COUNT_INVALID");
        var completed=new List<object>(); var indices=new List<int>(); int index=0; bool writing=false;
        try {
            for(index=0;index<count;index++) preflight(index);
            index=-1; begin();
            for(index=0;index<count;index++) {
                writing=true;
                completed.Add(write(index));
                indices.Add(index);
            }
            return new {ok=true,status="values-set-readback-verified",graphId,requestedCount=count,
                completedIndices=indices.ToArray(),completed=completed.ToArray(),failedIndex=(int?)null,
                outcomeUncertain=false,retryAttempted=false,persistentSaveVerified=false,runtimeVerified=false};
        } catch(Exception ex) {
            var cause=ex is TargetInvocationException invocation && invocation.InnerException!=null ? invocation.InnerException : ex;
            return new {ok=false,status=writing?"values-partially-written":"values-preflight-refused",graphId,
                requestedCount=count,completedIndices=indices.ToArray(),completed=completed.ToArray(),failedIndex=index,
                error=cause.GetType().Name+":"+cause.Message,outcomeUncertain=writing,retryAttempted=false,
                persistentSaveVerified=false,runtimeVerified=false};
        }
    }

    // Resolve all native storage and setter/getter signatures before the first value is
    // written. Container descriptors let us check every future leaf without appending it.
    void AuthorPreflightLeaf(Type type,int storage,JsonElement payload,string slot)
    {
        var tag=payload.EnumerateObject().Single().Name;
        var resolved=slot=="auto"?AuthorAutoSlot(storage,tag):slot;
        var contract=resolved switch {
            "uint"=>(1,"uint",typeof(uint),"LhkKKbraAbs","cPOKKedklwd"),
            "int"=>(2,"int",typeof(int),"c84KKE8ihrN","ilqKKrw7dhN"),
            "bool"=>(3,"bool",typeof(bool),"CHHKK434xan","RJCKKnWqvLO"),
            "float"=>(4,"float",typeof(float),"SH7KKvk8cxe","ngMKKCVBuMA"),
            "string"=>(5,"string",typeof(string),"MfLKK0bLIju","ur7KK2NiYZ4"),
            "enum"=>(6,"uint",typeof(uint),"X8oKKHB87Ue","cPOKKedklwd"),
            _=>throw new InvalidOperationException("AUTHOR_VALUE_SLOT_UNSUPPORTED")
        };
        if(storage!=contract.Item1 || tag!=contract.Item2)
            throw new InvalidOperationException("AUTHOR_VALUE_STORAGE_PAYLOAD_MISMATCH:"+storage+":"+resolved+":"+tag);
        var setter=type.GetMethod(B(contract.Item4),Fields);
        var getter=type.GetMethod(B(contract.Item5),Fields);
        if(setter==null || setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=contract.Item3 ||
           getter==null || getter.GetParameters().Length!=0 || getter.ReturnType.GetProperty("Value")==null)
            throw new InvalidOperationException("AUTHOR_VALUE_ACCESSOR_SIGNATURE:"+resolved);
    }

    void AuthorPreflightPinValue(List<Resource> resources,uint definitionId,uint[] category,object node,int index,JsonElement payload,string slot)
    {
        var scalar=AuthorPinScalar(node,3,index); var storage=AuthorStorageKind(scalar);
        var tagged=payload.EnumerateObject().Single();
        if(tagged.Name=="vector3" || slot=="vector3") {
            AuthorVectorPayload(payload);
            if(slot!="auto" && slot!="vector3") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3");
            AuthorRequireVectorDeclaration(resources,definitionId,category,3,index);
            AuthorVectorChildren(scalar); return;
        }
        if(tagged.Name!="list" && tagged.Name!="dict") {
            AuthorPreflightLeaf(scalar.GetType(),storage,payload,slot); return;
        }
        if(storage!=(tagged.Name=="list"?10002:10003)) throw new InvalidOperationException("AUTHOR_VALUE_CONTAINER_STORAGE_MISMATCH");
        var append=scalar.GetType().GetMethod(B("KRQKKuygfFk"),Fields);
        if(append==null || append.GetParameters().Length!=2) throw new InvalidOperationException("AUTHOR_VALUE_APPEND_SIGNATURE");
        var descriptor=AuthorDeclaredPinObject(resources,definitionId,category,3,index);
        var child=descriptor.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(descriptor,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_CONTAINER_ELEMENT_UNDEFINED");
        if(!append.GetParameters()[0].ParameterType.IsInstanceOfType(child))
            throw new InvalidOperationException("AUTHOR_VALUE_APPEND_DESCRIPTOR_MISMATCH");
        // The native append return type is the concrete value type used by the ordinary
        // list/dict writer. No constructor or append is invoked during this preflight.
        var leafType=append.ReturnType;
        if(tagged.Name=="list") {
            foreach(var leaf in tagged.Value.EnumerateArray())
                AuthorPreflightLeaf(leafType,AuthorDeclaredStorage(child),leaf,slot);
        } else {
            if(AuthorDeclaredStorage(child)!=10007) throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_TYPE_MISMATCH");
            var key=child.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(child,null)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:key");
            var value=child.GetType().GetMethod(B("oRlK7UMaIYn"),Fields)!.Invoke(child,null)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:value");
            foreach(var pair in tagged.Value.EnumerateArray()) {
                AuthorPreflightLeaf(leafType,AuthorDeclaredStorage(key),pair.GetProperty("key"),slot);
                AuthorPreflightLeaf(leafType,AuthorDeclaredStorage(value),pair.GetProperty("value"),slot);
            }
        }
    }

    // Everything below reads the pin's LIVE value object and writes through a setter that
    // already has an in-repo proof. Nothing here is selected from data/node-contracts: that
    // artifact records elementType as "unknown" for defId 79's 定时器序列 and for defId 70's
    // 单位标签索引列表 alike, so an element type has to be read live or not written at all.
    //
    // SCOPE (this is the D1 fix, and it is a compile question, not a style one). These are
    // members of the class, so nothing below may name a local of AuthorGraph(). The first
    // draft reached for two of them --
    //   AuthoringGraph.cs:116  var nodes=GraphNodes(graph.Model);      (local variable)
    //   AuthoringGraph.cs:117  uint Def(object n)=>(uint)Field(...);   (local function)
    // -- which is CS0103 in both cases. They are passed in as parameters instead. The one
    // and only place that reads them is still AuthorGraph() itself, so "which node" and
    // "which definition" keep exactly one definition each; nothing is re-derived here.

    sealed record AuthorWriteResult(string Slot,int StorageKind,int ElementsWritten,object? Readback);

    // A node the caller named, with no expectation about which definition it is. The existing
    // Node(id,definition) helper asserts a fixed definition, which defeats the whole point.
    // The node map is the one AuthorGraph() already holds (AuthoringGraph.cs:116); it is a
    // parameter because that map is a method local and this is a class member.
    object GraphNode(IDictionary nodes,uint id)
    {
        if(!nodes.Contains(id)) throw new InvalidOperationException("AUTHOR_NODE_IDENTITY_MISMATCH");
        return nodes[id]!;
    }

    // The pin's value object, with a Generics placeholder unwrapped exactly the way the proven
    // count builder already does it (AuthoringGraph.cs:444-449). An absent Value is a named
    // refusal, never coerced into a default.
    object AuthorPinScalar(object node,int kind,int index)
    {
        var pin=Pin(node,kind,index);
        var wrapper=pin.GetType().GetProperty("value")!.GetValue(pin)!;
        var value=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_NULL");
        if(AuthorStorageKind(value)==10000) // Generics: the slot exists but carries no concrete type
            value=value.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(value,null)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_GENERIC_UNBOUND");
        return value;
    }

    // The storage-kind code, read from the object itself. The scalar paths below use:
    //   1 (uint reference) 7.1 dUME7NLuq2KGEudewSI8.g1wLu1mo5kr; AuditGraph's config ID setter
    //   2 (integer)  AuthoringGraph.cs:479  KiPKKaQUNLS(...)!=2 -> AUTHOR_COUNT_INT_TYPE_NOT_MATERIALIZED
    //   6 (enum)     FinishGraph.cs:114     KiPKKaQUNLS(...)!=6 -> FINISH_REPAIR_EXPECTED_ENUM
    //   10000 (Generics) AuthoringGraph.cs:446 and pin-config.cs:390,403,704,735
    static int AuthorStorageKind(object scalar)
        => Convert.ToInt32(scalar.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(scalar,null));

    // "auto" is deliberately narrow: reference uint (1), integer (2), and enum uint (6).
    // Every other code -- including the codes the contract artifact names for
    // float and string (4 and 5 in data/node-contracts/shared/value-type-codes.json), which NO
    // code in this repo has ever read back through KiPKKaQUNLS -- is refused BY NAME, so the
    // caller must state the slot explicitly and accept the read-back check. LIVE-CONFIRM-B.
    string AuthorAutoSlot(object scalar,string payloadName)
        => AuthorAutoSlot(AuthorStorageKind(scalar),payloadName);

    static string AuthorAutoSlot(int storage,string payloadName)
        => storage switch {
            1 when payloadName=="uint" => "uint",
            2 when payloadName=="int" => "int",
            6 when payloadName=="uint" => "enum",
            7 when payloadName=="vector3" => "vector3",
            10000 => throw new InvalidOperationException("AUTHOR_VALUE_NOT_MATERIALIZED"),
            _ => throw new InvalidOperationException("AUTHOR_VALUE_SLOT_UNPROVEN:"+storage+":"+payloadName)
        };

    // One write per call. Setter / read-back pairs and their in-repo proofs:
    //   int    c84KKE8ihrN / ilqKKrw7dhN   AuthoringGraph.cs:482-488 (count-gate threshold)
    //   string MfLKK0bLIju / ur7KK2NiYZ4   AuthoringGraph.cs:250-254 (print text)
    //   float  SH7KKvk8cxe / ngMKKCVBuMA   FinishGraph.cs:88      (225 创建三维向量 X/Y/Z)
    //   enum   X8oKKHB87Ue / cPOKKedklwd   FinishGraph.cs:116-118 (enum-backed boolean)
    //   bool   CHHKK434xan / RJCKKnWqvLO   AuthoringGraph.cs:263-269 (双分支 条件)
    //   uint   LhkKKbraAbs / cPOKKedklwd  N6WX98qouJ0 writes lIZXkU1hhuI;
    //          BdsXk9NE0ND is that same uint getter's alias (7.1 YMt9KPX9...:289-322,530-532).
    // The read-back is mandatory and a mismatch refuses. A write that lands in a different
    // storage slot than the pin declares is a wrong value, not a slow one, and it must never
    // look like success -- that is exactly the "加得进去配不出效果" failure this patch exists
    // to avoid. LIVE-CONFIRM-C: the bool/enum pair shares one declared type tuple (4,4,1) and
    // lives in two slots; the read-back is what makes the wrong choice loud instead of silent.
    object? AuthorWriteScalar(object scalar,JsonElement payload,string slot)
    {
        var name=payload.EnumerateObject().Single().Name;
        var inner=payload.GetProperty(name);
        var resolved=slot=="auto"?AuthorAutoSlot(scalar,name):slot;
        switch(resolved) {
            case "vector3":
                return AuthorWriteVector3(scalar,payload);
            case "uint": {
                if(AuthorStorageKind(scalar)!=1) throw new InvalidOperationException("AUTHOR_VALUE_UINT_STORAGE_MISMATCH");
                var setter=scalar.GetType().GetMethod(B("LhkKKbraAbs"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(uint))
                    throw new InvalidOperationException("AUTHOR_VALUE_UINT_SETTER_SIGNATURE");
                if(name!="uint") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:uint");
                var wanted=inner.GetUInt32();
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("cPOKKedklwd"),Fields)!.Invoke(scalar,null)!;
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not uint seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:uint");
                return seen;
            }
            case "int": {
                var setter=scalar.GetType().GetMethod(B("c84KKE8ihrN"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(int))
                    throw new InvalidOperationException("AUTHOR_VALUE_INT_SETTER_SIGNATURE");
                if(name!="int") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:int");
                var wanted=inner.GetInt32();
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("ilqKKrw7dhN"),Fields)!.Invoke(scalar,null)!;
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not int seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:int");
                return seen;
            }
            case "enum": {
                var setter=scalar.GetType().GetMethod(B("X8oKKHB87Ue"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(uint))
                    throw new InvalidOperationException("AUTHOR_VALUE_ENUM_SETTER_SIGNATURE");
                if(name!="uint") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:enum");
                var wanted=inner.GetUInt32();
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("cPOKKedklwd"),Fields)!.Invoke(scalar,null)!;
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not uint seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:enum");
                return seen;
            }
            case "bool": {
                var setter=scalar.GetType().GetMethod(B("CHHKK434xan"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(bool))
                    throw new InvalidOperationException("AUTHOR_VALUE_BOOL_SETTER_SIGNATURE");
                if(name!="bool") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:bool");
                var wanted=inner.GetBoolean();
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("RJCKKnWqvLO"),Fields)!.Invoke(scalar,null)!;
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not bool seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:bool");
                return seen;
            }
            case "float": {
                var setter=scalar.GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(float))
                    throw new InvalidOperationException("AUTHOR_VALUE_FLOAT_SETTER_SIGNATURE");
                if(name!="float") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:float");
                var wanted=(float)inner.GetDouble();
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("ngMKKCVBuMA"),Fields)!.Invoke(scalar,null)!;
                // Bit-exact on the float32 the native slot can hold, not a tolerance compare:
                // a rounded value is the same class of wrong as a value in the wrong slot.
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not float seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:float");
                return seen;
            }
            case "string": {
                var setter=scalar.GetType().GetMethod(B("MfLKK0bLIju"),Fields)!;
                if(setter.GetParameters().Length!=2 || setter.GetParameters()[0].ParameterType!=typeof(string))
                    throw new InvalidOperationException("AUTHOR_VALUE_STRING_SETTER_SIGNATURE");
                if(name!="string") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:string");
                var wanted=inner.GetString()!;
                setter.Invoke(scalar,new object?[]{wanted,null});
                var wrapper=scalar.GetType().GetMethod(B("ur7KK2NiYZ4"),Fields)!.Invoke(scalar,null)!;
                if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not string seen || seen!=wanted)
                    throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:string");
                return seen;
            }
            default:
                throw new InvalidOperationException("AUTHOR_VALUE_SLOT_UNSUPPORTED:"+resolved);
        }
    }

    // The declared type object of one pin, read from the definition model's pin list -- the
    // same source AuthorDeclaredPins walks and the same one the count builder uses at
    // AuthoringGraph.cs:469-473. A list pin's element definition can only be obtained here.
    object AuthorDeclaredPinObject(List<Resource> resources,uint definitionId,uint[] category,int kind,int index)
    {
        var matches=resources.Where(r=>r.Kind==6 && r.Id==definitionId && r.Category.SequenceEqual(category)).ToArray();
        if(matches.Length!=1 || matches.Any(r=>!ReferenceEquals(r.Model,matches[0].Model)))
            throw new InvalidOperationException("AUTHOR_EDGE_DEFINITION_NOT_UNIQUE:"+definitionId);
        foreach(var pin in (IEnumerable)matches[0].Model) {
            var key=Stored(pin,B("quGKmYyTPnA")) ?? throw new InvalidOperationException("AUTHOR_EDGE_PIN_SCHEMA_MISMATCH");
            if(Convert.ToInt32(Field(key,B("TqBK5Pk3Cw2")))!=kind || Convert.ToInt32(Field(key,B("hWTK5MSRidQ")))!=index) continue;
            var wrapper=pin.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(pin,null)!;
            return wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DECLARATION_NULL");
        }
        throw new InvalidOperationException("AUTHOR_VALUE_PORT_UNKNOWN:"+kind+":"+index);
    }

    // A list pin is appended to element by element. The element definition is read live from
    // the pin's declared type object and each element is appended through the proven pair
    // (Ov2K7oYGvHi -> KRQKKuygfFk, AuthoringGraph.cs:469-475); the element's own storage kind
    // then decides the scalar setter, exactly as for a scalar pin.
    // The list is APPENDED TO, never cleared first: this adapter has no proven clear
    // operation, and a half-applied list would be worse than a refusal. A caller that needs
    // an exact list writes onto a freshly placed node, whose list starts empty.
    // LIVE-CONFIRM-D: for defId 79 3:3 the proven element is a float; whether an int element
    // (defId 70 3:1, whose contract records elementType "unknown") materialises as an int
    // slot is NOT known offline, and AuthorAutoSlot will refuse rather than guess.
    // `definitionId` is the one AuthorGraph() read through its own Def() local (line 117); the
    // unused `node` shape of the first draft is gone rather than carried as a dead parameter.
    int AuthorWriteList(List<Resource> resources,uint definitionId,uint[] category,int kind,int index,object list,JsonElement items,string slot)
    {
        // The list slot itself is identified by the code the contract artifact names for List
        // (data/node-contracts/shared/value-type-codes.json: "List" = 10002). This is the one
        // place a code from that artifact is used, and it is used only as a sanity check on a
        // slot we are already addressing by (kind,index) -- never to choose a setter.
        if(AuthorStorageKind(list)!=10002) throw new InvalidOperationException("AUTHOR_VALUE_NOT_A_LIST:"+AuthorStorageKind(list));
        var declaration=AuthorDeclaredPinObject(resources,definitionId,category,kind,index);
        var elementDefinition=declaration.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(declaration,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_LIST_ELEMENT_UNDEFINED");
        var count=0;
        foreach(var item in items.EnumerateArray()) {
            var element=list.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(list,new object?[]{elementDefinition,null})
                ?? throw new InvalidOperationException("AUTHOR_VALUE_LIST_ELEMENT_NULL");
            AuthorWriteScalar(element,item,slot is "auto" or "list" ? "auto" : slot);
            count++;
        }
        return count;
    }

    // A dict pin (contract serverParamType 27) is a CONTAINER, written the same way a list is:
    // per entry, through the append call AuthorWriteList already resolves. Nothing below is a
    // new symbol -- every B("...") here is registered in EditorBindingProfile.Generated.cs and
    // re-verified against the pinned 7.1 metadata (see DICT-WRITE-CODE-PLAN.md):
    //   KiPKKaQUNLS/FAVX90STAmy  container storage kind (10003 for a dict)
    //   KRQKKuygfFk/Vo1XkeKXfjj  append one entry               (the list branch's own append)
    //   Ov2K7oYGvHi/rKlXHia7SDm  descriptor child-0 = entry descriptor (the list branch's call)
    //   eUgKKLsg3Lw/fPpXkwLeLOm  entry child-0 = key leaf
    //   XnwKKQKmI5G/q6cXkL8eycl  entry child-1 = value leaf
    // Each leaf is written through the ORDINARY scalar setter, resolved from the leaf's OWN
    // storage kind by AuthorAutoSlot -- the key type is NOT hardcoded here, so a key tag that
    // cannot match the live leaf refuses by name. Appended, never cleared, for the same reason
    // as the list: this adapter has no proven clear, and a half-applied dict is worse than a
    // refusal. An empty dict writes 0 entries and is NOT hollow -- the storage-kind assert
    // below still runs before it returns.
    // The descriptor's registered valueType field predicts the initialized leaf storage.
    // Resolve every pair before append: a wrong tag must not leave an empty entry behind.
    int AuthorDeclaredStorage(object descriptor)
        => Convert.ToInt32(Stored(descriptor,B("O2EKYx5c6Xs")));

    string AuthorDictLeafSlot(object descriptor,JsonElement leaf,string slot)
    {
        var storage=AuthorDeclaredStorage(descriptor);
        var name=leaf.EnumerateObject().Single().Name;
        var resolved=slot=="auto"?AuthorAutoSlot(storage,name):slot;
        var expected=resolved switch { "uint"=>1,"int"=>2,"bool"=>3,"float"=>4,"string"=>5,"enum"=>6,_=>-1 };
        if(storage!=expected || name!=(resolved=="enum"?"uint":resolved))
            throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_TYPE_MISMATCH:"+storage+":"+resolved+":"+name);
        return resolved;
    }

    int AuthorWriteDict(List<Resource> resources,uint definitionId,uint[] category,int kind,int index,object dict,JsonElement entries,string slot)
    {
        if(AuthorStorageKind(dict)!=10003) throw new InvalidOperationException("AUTHOR_VALUE_NOT_A_DICT:"+AuthorStorageKind(dict));
        // Both request paths validate the full dict before mutation. Keep the local
        // container/entry checks as named refusals at the native writer boundary.
        if(entries.ValueKind!=JsonValueKind.Array || entries.GetArrayLength()>AuthorDictLimit)
            throw new InvalidOperationException("AUTHOR_VALUE_DICT_SHAPE_INVALID");
        var descriptor=AuthorDeclaredPinObject(resources,definitionId,category,kind,index);
        var entryDescriptor=descriptor.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(descriptor,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_UNDEFINED");
        if(AuthorDeclaredStorage(entryDescriptor)!=10007)
            throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_TYPE_MISMATCH");
        var keyDescriptor=entryDescriptor.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(entryDescriptor,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:key");
        var valueDescriptor=entryDescriptor.GetType().GetMethod(B("oRlK7UMaIYn"),Fields)!.Invoke(entryDescriptor,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:value");
        var leafSlot=slot is "auto" or "dict" ? "auto" : slot;
        var prepared=new List<(JsonElement Key,JsonElement Value,string KeySlot,string ValueSlot)>();
        foreach(var pair in entries.EnumerateArray()) {
            if(pair.ValueKind!=JsonValueKind.Object || !pair.TryGetProperty("key",out var keyLeaf) ||
               !pair.TryGetProperty("value",out var valueLeaf) || pair.EnumerateObject().Count()!=2)
                throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_INVALID");
            if(keyLeaf.ValueKind!=JsonValueKind.Object || valueLeaf.ValueKind!=JsonValueKind.Object)
                throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED");
            prepared.Add((keyLeaf,valueLeaf,AuthorDictLeafSlot(keyDescriptor,keyLeaf,leafSlot),
                AuthorDictLeafSlot(valueDescriptor,valueLeaf,leafSlot)));
        }
        var count=0;
        foreach(var pair in prepared) {
            var entry=dict.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(dict,new object?[]{entryDescriptor,null})
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_APPEND_FAILED");
            if(AuthorStorageKind(entry)!=10007) throw new InvalidOperationException("AUTHOR_VALUE_DICT_ENTRY_TYPE_MISMATCH");
            var key=entry.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(entry,null)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:key");
            var value=entry.GetType().GetMethod(B("XnwKKQKmI5G"),Fields)!.Invoke(entry,null)
                ?? throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_UNDEFINED:value");
            if(AuthorStorageKind(key)!=AuthorDeclaredStorage(keyDescriptor) ||
               AuthorStorageKind(value)!=AuthorDeclaredStorage(valueDescriptor))
                throw new InvalidOperationException("AUTHOR_VALUE_DICT_LEAF_STORAGE_MISMATCH");
            AuthorWriteScalar(key,pair.Key,pair.KeySlot);
            AuthorWriteScalar(value,pair.Value,pair.ValueSlot);
            count++;
        }
        return count;
    }

    AuthorWriteResult AuthorWritePinValue(List<Resource> resources,uint definitionId,uint[] category,object node,int kind,int index,JsonElement payload,string slot)
    {
        var name=payload.EnumerateObject().Single().Name;
        if(name=="vector3" || slot=="vector3") {
            if(slot!="auto" && slot!="vector3") throw new InvalidOperationException("AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3");
            AuthorRequireVectorDeclaration(resources,definitionId,category,kind,index);
            var vector=AuthorPinScalar(node,kind,index);
            return new AuthorWriteResult("vector3",7,3,AuthorWriteVector3(vector,payload));
        }
        if(name=="list") {
            var list=AuthorPinScalar(node,kind,index);
            var written=AuthorWriteList(resources,definitionId,category,kind,index,list,payload.GetProperty("list"),slot);
            return new AuthorWriteResult("list",10002,written,written);
        }
        if(name=="dict") {
            var dict=AuthorPinScalar(node,kind,index);
            var written=AuthorWriteDict(resources,definitionId,category,kind,index,dict,payload.GetProperty("dict"),slot);
            return new AuthorWriteResult("dict",10003,written,written);
        }
        var scalar=AuthorPinScalar(node,kind,index);
        var storage=AuthorStorageKind(scalar);
        var resolved=slot=="auto"?AuthorAutoSlot(scalar,name):slot;
        var readback=AuthorWriteScalar(scalar,payload,resolved);
        return new AuthorWriteResult(resolved,storage,0,readback);
    }

}

