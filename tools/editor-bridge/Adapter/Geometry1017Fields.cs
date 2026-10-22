using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Threading;

namespace Miliastra.EditorBridge;

// DRAFT ONLY: caller supplies the body of an actually received 1017 packet.
// No subscription, RPC, constructor, serializer, property or enumerator invocation.
// No root exists in the retained 1022 metadata; never use it as a fallback.
internal sealed class Geometry1017Fields
{
    const BindingFlags F = BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.DeclaredOnly;
    const string Prefix = "vxMD1WA32SifRCWMXAF.vfZLBjAKUPu1EKQR2pa`1";
    const string Body = "PWcy2YRxLeDSncyfwSVj.Dn3BJlRxwV59NbJdPD5B";
    const string Group = "Qsp2M3RGZLKrPcNu3xjY.zkqfN6RGODcD5IkUKpMe";
    const string Union = "ad0AXNR7yuWxfMWnReG0.LbCFXhR7KW6v5eWQLLxO";
    const string Prefab = "oZWQMWRPymMgxJPoTiR5.V6SLfPRPKjAGtFJ5fNPt";
    const string Proto = "en2b2gIF9pnjDgPA2hjV.gGj2GHIFVJEtXlv1XmMM";
    const string Components = "AP32clIYuRqdZ7fJTlyS.N0pggoIYfL6RdrGHIETq";
    const string Component = "ma6nNbIQXIHUxeIZVpiN.mUxYM5IQLwhJJKtEVfj9";
    const string Geometry = "G9DnHWItLAPNIddvDVdu.eFrJF0ItwAPHoH8FGiC2";
    const string ShapeGroup = "h82K8tIiSGmMxtfPcYje.IKZUinIi6gqmdsud0QKu";
    const string Shape = "XD2NV0IGvpACBkRTn8XD.I67j4KIGGJUmdMakOUOv";
    const string Vector = "VbO9JOBW798mJRUNxIi7.XhXaV2BWq1VXMxysLFO9";
    static readonly Guid ExpectedMvid = new("39031639-dfe4-4ed3-9109-b21f7d4d47d1");
    readonly List<(object Owner, FieldInfo Field, object? Value)> reads = new();
    readonly List<(Array Array, int Index, object? Value)> cells = new();
    readonly Stopwatch clock = Stopwatch.StartNew();
    Assembly assembly = null!;
    sealed class CollectionRead { internal string Field=""; internal int Declared,Visited; }
    readonly List<CollectionRead> collections=new();
    readonly HashSet<string> truncationReasons=new(StringComparer.Ordinal);
    bool recheckComplete=true;
    void Truncate(string reason) => truncationReasons.Add(reason);
    // 50000 reads / 250 ms remain THE bound. The prefix caps further down are arbitrary cut-offs
    // that can end the walk before any tag-18 component is reached -- the observed
    // geometryComponentCount=0. Raising a cap does not raise this budget; it only changes which of
    // the two stops the walk first, so budget exhaustion has to TRUNCATE and keep what was read.
    // A throw here escapes Read() entirely, and ComponentGeometryEvidence then records
    // readOk=false with every row already collected discarded.
    sealed class BudgetExhausted : Exception {}
    const int BudgetReads = 50000;
    const int BudgetMs = 250;
    bool OverBudget() => reads.Count+cells.Count>BudgetReads || clock.ElapsedMilliseconds>BudgetMs;
    void Budget() { if(OverBudget()) throw new BudgetExhausted(); }
    void Type(object value, string name) {
        Budget(); var t=value.GetType();
        if(t.Assembly!=assembly || t.FullName!=name) throw new InvalidOperationException("GEOMETRY_TYPE:"+name);
    }
    object? Raw(object owner,string name) {
        Budget();
        var field=owner.GetType().GetField(name,F) ?? throw new MissingFieldException(owner.GetType().FullName,name);
        var value=field.GetValue(owner); reads.Add((owner,field,value)); return value;
    }
    object Required(object owner,string name) => Raw(owner,name) ?? throw new InvalidOperationException("GEOMETRY_NULL:"+name);
    int Tag(object owner,string name) {
        var value=Required(owner,name); var t=value.GetType();
        if(!t.IsEnum || t.Assembly!=assembly || Enum.GetUnderlyingType(t)!=typeof(int)) throw new InvalidOperationException("GEOMETRY_TAG_TYPE");
        return Convert.ToInt32(value);
    }
    // This iterator executes only our code. Native collection enumerators are never used.
    IEnumerable<object> Repeated(object owner,string name,string element,int maximum) {
        var value=Required(owner,name); var t=value.GetType();
        if(t.Assembly!=assembly || !t.IsGenericType || t.GetGenericTypeDefinition().FullName!=Prefix ||
           t.GetGenericArguments()[0].FullName!=element) throw new InvalidOperationException("GEOMETRY_REPEATED_TYPE");
        var a=Required(value,"OXE1MG9S4T") as Array ?? throw new InvalidOperationException("GEOMETRY_ARRAY");
        var n=Raw(value,"count") is int count ? count : throw new InvalidOperationException("GEOMETRY_COUNT_TYPE");
        if(a.Rank!=1 || a.GetLowerBound(0)!=0 || a.GetType().GetElementType()!=t.GetGenericArguments()[0] || n<0 || n>a.Length)
            throw new InvalidOperationException("GEOMETRY_COUNT_LIMIT");
        var observed=new CollectionRead {Field=name,Declared=n}; collections.Add(observed);
        int prefix=Math.Min(n,maximum);
        if(prefix<n)Truncate("COLLECTION_PREFIX:"+name);
        for(int i=0;i<prefix;i++) {
            Budget(); var item=a.GetValue(i); cells.Add((a,i,item)); observed.Visited++;
            if(item==null)throw new InvalidOperationException("GEOMETRY_ELEMENT_NULL");
            Type(item,element); yield return item;
        }
    }
    string Float(object owner,string name) => Raw(owner,name) is float value ? BitConverter.SingleToInt32Bits(value).ToString("x8") : throw new InvalidOperationException("GEOMETRY_FLOAT_TYPE");
    object? Vec(object owner,string name) {
        var value=Raw(owner,name); if(value==null)return null; Type(value,Vector);
        return new {xBits=Float(value,"h87BWJq8gBf"),yBits=Float(value,"c4CBW4649Dt"),zBits=Float(value,"OjvBWsJZe3l")};
    }
    static bool Equal(object? a,object? b) => ReferenceEquals(a,b) || (a!=null && b!=null && a.GetType()==b.GetType() &&
        (a.GetType().IsEnum || a.GetType().IsPrimitive) && a.Equals(b));
    void Recheck() {
        // Recheck adds nothing to reads/cells, so its count half cannot newly trip: the counters are
        // frozen once the walk ends. Only the 250 ms clock can, and it fires right after the
        // budget-limited walk this whole change exists for. Degrade to "stability not proven" --
        // returning early while still reporting stableFieldRead=true would be a false claim.
        foreach(var read in reads) { if(OverBudget()){Truncate("RECHECK_LIMIT");recheckComplete=false;return;} if(!Equal(read.Value,read.Field.GetValue(read.Owner))) throw new InvalidOperationException("GEOMETRY_FIELDS_CHANGED"); }
        foreach(var cell in cells) { if(OverBudget()){Truncate("RECHECK_LIMIT");recheckComplete=false;return;} if(!ReferenceEquals(cell.Value,cell.Array.GetValue(cell.Index))) throw new InvalidOperationException("GEOMETRY_ITEMS_CHANGED"); }
    }
    internal static object ReadReceived1017(object body,Dispatcher dispatcher) {
        if(!dispatcher.CheckAccess())throw new InvalidOperationException("GEOMETRY_DISPATCHER_REQUIRED");
        var reader=new Geometry1017Fields(); reader.assembly=body.GetType().Assembly;
        if(reader.assembly.GetName().Name!="BeyondEditor" || reader.assembly.ManifestModule.ModuleVersionId!=ExpectedMvid) throw new InvalidOperationException("GEOMETRY_BUILD_MISMATCH");
        return reader.Read(body);
    }
    object Read(object body) {
        Type(body,Body); var rows=new List<object>(); int protoCount=0, componentCount=0, geometryComponentCount=0; var protoIds=new List<uint>();
        try {
        foreach(var group in Repeated(body,"dR6Rxvt7KsM",Group,4096))
        foreach(var item in Repeated(group,"GkpRGtIK5Ww",Union,8192)) {
            if(Tag(item,"A7dRGI5RXDD")!=11)continue;
            // 128 was far below what the budget covers (50000/(9+3C) protos: ~505 at C=30, ~5555 at
            // C=0) and it landed inside the packet's first union slice. The budget is the real stop;
            // this survives only as a pathological-packet guard.
            if(protoCount>=4096) {Truncate("PROTO_PREFIX_LIMIT");goto Finish;}
            var prefab=Required(item,"f7jRGBh1Il7"); Type(prefab,Prefab);
            var proto=Required(prefab,"KfqRoXPsQtS"); Type(proto,Proto);
            if(Raw(proto,"wpnIFzGZt4k") is not uint id)throw new InvalidOperationException("GEOMETRY_PREFAB_ID_TYPE");
            protoCount++; protoIds.Add(id);
            var components=Required(proto,"KDPI8D1rNqu"); Type(components,Components);
            foreach(var component in Repeated(components,"VmgI0XkYXSb",Component,256)) {
                componentCount++; int kind=Tag(component,"HdDIPUkYYjM"), tag=Tag(component,"iLMIPugmMtk");
                if(tag!=18)continue; geometryComponentCount++;
                var geometry=Required(component,"itWIPf1r9qY"); Type(geometry,Geometry);
                foreach(var shapeGroup in Repeated(geometry,"qIFIt7Sl0RY",ShapeGroup,128))
                foreach(var shape in Repeated(shapeGroup,"wkqItO7g6xJ",Shape,512)) {
                    // A row cap must not end the proto walk: later protos' tag-18 components would
                    // become invisible and geometryComponentCount would be reported as 0. Skip rows,
                    // keep walking, keep the flag -- rows stay a traversal-order prefix.
                    if(rows.Count>=128) {Truncate("SHAPE_ROW_PREFIX_LIMIT");break;}
                    int shapeTag=Tag(shape,"SDfIG09w4be"); var data=Raw(shape,"CXHIGYZK0ge"); object values;
                    if(shapeTag==0 || data==null) {
                        rows.Add(new {rawProtoId=id,componentKind=kind,componentPayloadTag=tag,shapeTag,available=false,reason=data==null?"SHAPE_PAYLOAD_NULL":"SHAPE_TAG_ZERO"}); continue;
                    }
                    switch(shapeTag) {
                    case 11:
                        Type(data,"Du26KVIGFtsxKIgs0O8q.lNRx3RIGckqklGmWroUq");
                        values=new {center=Vec(data,"g9TIvItdMaI"),rawVector1=Vec(data,"nEAIvOgur3Q"),rawVector2=Vec(data,"LVOIvZgWTml")}; break;
                    case 12:
                        Type(data,"wnrea0IvLljM8RmsSL1L.uAJLoKIvw3tLthqip8Tt");
                        values=new {center=Vec(data,"j2oIvavAydA"),radiusBits=Float(data,"NiQIvG2oBi3")}; break;
                    case 13:
                        Type(data,"FaCYDUIvdFSoabpaXQkd.aFOhchIvvTlmD1qnjYVT");
                        values=new {center=Vec(data,"U73IvWcPitT"),rawVector1=Vec(data,"EuAIvgdfyWt"),radiusBits=Float(data,"dM0IvbHmEi1"),heightBits=Float(data,"oc6IvhFZt6m"),direction=Vec(data,"LIoIv6HlWYi")}; break;
                    default: throw new InvalidOperationException("GEOMETRY_UNKNOWN_SHAPE_TAG:"+shapeTag);
                    }
                    rows.Add(new {rawProtoId=id,componentKind=kind,componentPayloadTag=tag,shapeTag,values});
                }
            }
        }
        } catch(BudgetExhausted) { Truncate("GEOMETRY_READ_LIMIT"); }
        Finish:
        Recheck();
        bool truncated=truncationReasons.Count!=0;
        // A count is exact only for its encountered collection; nested totals require full traversal.
        var collectionCoverage=collections.ConvertAll(c=>new {field=c.Field,declaredCount=c.Declared,visitedCount=c.Visited,
            unvisitedCount=c.Declared-c.Visited,complete=c.Declared==c.Visited,countScope="one-encountered-collection"}).ToArray();
        return new {schemaVersion=2,truncated,truncationReasons=new List<string>(truncationReasons).ToArray(),
            sampleComplete=!truncated,packetIndexComplete=!truncated,totalProtoCount=truncated?(int?)null:protoCount,
            totalShapeRowCount=truncated?(int?)null:rows.Count,observedProtoCount=protoCount,observedShapeRowCount=rows.Count,
            collectionCoverage,unvisitedFieldsInspected=false,source="actually-received-1017-resource-delta",protoCount,rawProtoIds=protoIds.ToArray(),rawProtoIdSource="en2b2gIF9pnjDgPA2hjV.gGj2GHIFVJEtXlv1XmMM.wpnIFzGZt4k",componentCount,geometryComponentCount,
            rows=rows.ToArray(),stableFieldRead=recheckComplete,readCount=reads.Count+cells.Count,unusedCapacityRead=false,
            readLimit=BudgetReads,readLimitMs=BudgetMs,recheckComplete,
            geometryVerified=false,collisionKindMappingVerified=false,worldBoundsVerified=false,placementVerified=false,
            scope="bounded-raw-config-shape-prefix; no-absence-inference; totals-null-when-truncated",sentToGame=false};
    }
}

