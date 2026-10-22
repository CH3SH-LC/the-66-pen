using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Existing editor models only. No serializer, RPC, constructor, setter or arbitrary getter.
internal sealed partial class EditorAdapter
{
    internal sealed class ContentFieldReader
    {
        const BindingFlags F = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
        internal const int MaxObjects = 65536, MaxItems = 16384, MaxDepth = 48, MaxBytes = 8 * 1024 * 1024;
        readonly Assembly assembly;
        internal sealed class Budget { internal readonly Stopwatch Clock=new(); internal int Objects,Bytes; }
        readonly Budget budget;
        readonly Dictionary<object,int> seen = new(ReferenceEqualityComparer.Instance);
        internal readonly List<string> Errors = new();
        internal bool Truncated;
        int objects, bytes;
        internal ContentFieldReader(Assembly assembly, Budget? budget=null) { this.assembly = assembly; this.budget=budget??new Budget(); }
        object Fail(string why, bool limit = false) { Errors.Add(why); Truncated |= limit; return new { unavailable = true, reason = why }; }
        static FieldInfo? Find(Type type, string field) {
            for (var t = type; t != null; t = t.BaseType) if(t.GetField(field,F) is FieldInfo f) return f;
            return null;
        }
        internal static object? Raw(object value, string field) => (Find(value.GetType(),field) ?? throw new MissingFieldException(value.GetType().FullName,field)).GetValue(value);
        readonly List<object> records=new();
        object Record(int id,object record) {records.Add(record);return new {refId=id};}
        internal object Read(object? value) {if(!budget.Clock.IsRunning)budget.Clock.Start();var root=Walk(value,0);return new {root,objects=records.ToArray()};}
        object? Walk(object? value, int depth)
        {
            if (value == null) return null;
            objects++; if (++budget.Objects > MaxObjects) return Fail("FIELD_VALUE_LIMIT",true);
            if (depth > MaxDepth) return Fail("FIELD_DEPTH_LIMIT",true);
            if (budget.Clock.ElapsedMilliseconds > 10000) return Fail("FIELD_TIME_LIMIT",true);
            var type=value.GetType();
            if (value is string s) { bytes=checked(bytes+s.Length*2); budget.Bytes=checked(budget.Bytes+s.Length*2); return budget.Bytes<=MaxBytes?s:Fail("STRING_BYTE_BUDGET",true); }
            if (value is byte[] blob) { bytes=checked(bytes+blob.Length); budget.Bytes=checked(budget.Bytes+blob.Length); return budget.Bytes<=MaxBytes?new {encoding="base64",length=blob.Length,base64=Convert.ToBase64String(blob)}:Fail("BLOB_BYTE_BUDGET",true); }
            if (value is float f) return new {scalarType="System.Single",bits=BitConverter.SingleToInt32Bits(f).ToString("x8",CultureInfo.InvariantCulture)};
            if (value is double d) return new {scalarType="System.Double",bits=BitConverter.DoubleToInt64Bits(d).ToString("x16",CultureInfo.InvariantCulture)};
            if (type.IsEnum) return new {scalarType=type.FullName,value=Convert.ChangeType(value,Enum.GetUnderlyingType(type),CultureInfo.InvariantCulture)};
            if (value is ulong or long) return new {scalarType=type.FullName,value=Convert.ToString(value,CultureInfo.InvariantCulture)};
            if (type.IsPrimitive && value is not IntPtr && value is not UIntPtr || value is decimal) return value;
            if (value is Delegate || value is Type || value is MemberInfo || value is IntPtr || value is UIntPtr) return Fail("UNSUPPORTED_RUNTIME_VALUE:"+type.FullName);
            if (!type.IsValueType && seen.TryGetValue(value,out var prior)) return new {refId=prior};
            var id=seen.Count+1;
            if (!type.IsValueType) seen.Add(value,id);
            try {
                if (type.IsGenericType) {
                    var generic=type.GetGenericTypeDefinition().FullName;
                    // Exact 7.1 field-only storage contracts, from the saved annotated sources.
                    var data=generic switch {
                        "sGSkeTXZnJ86i9h8AAF9.MoivF7XZA3MetiaLJVSU`1"=>"PIWXZgk5Tyr",
                        "IP7RdoXwe26RM9Pnjq3V.qknVfrXwms8uvpf8GYF6`1"=>"i4gXwUOgjxk",
                        "mMgotSXLrd3uXenrH36d.v14VncXLVn61xcWY9dpL`2"=>"MZXXXPVwoVh",
                        "Ss3WKuXZVPQoP5I07YO3.oaMXDuXZ6XQHCebtV4iO`1"=>"t9gXZ38FrdQ",
                        "vkNQubXLXRds8Ypg8CDv.WupssAXLwY5NGCQQMQWk`1"=>"o26XLglnP6U", _=>null};
                    if(data!=null) return Record(id,new {objectId=id,type=type.FullName,dataField=data,value=Walk(Raw(value,data),depth+1),scope="stored-business-value"});
                    if(generic=="vxMD1WA32SifRCWMXAF.vfZLBjAKUPu1EKQR2pa`1") {
                        var array=(Array)(Raw(value,"OXE1MG9S4T") ?? throw new InvalidOperationException("REPEATED_ARRAY_NULL"));
                        var count=(int)Raw(value,"count")!;
                        if(count<0 || count>array.Length || count>MaxItems) return Fail("REPEATED_COUNT_LIMIT",true);
                        var items=new object?[count]; for(int i=0;i<count;i++) items[i]=Walk(array.GetValue(i),depth+1);
                        return Record(id,new {objectId=id,type=type.FullName,count,items,unusedCapacityRead=false});
                    }
                    // Only BCL collection implementations execute their own enumerator/indexer.
                    if(type.GetGenericTypeDefinition()==typeof(List<>)) {
                        var list=(IList)value; if(list.Count>MaxItems)return Fail("LIST_COUNT_LIMIT",true);
                        var items=new object?[list.Count]; for(int i=0;i<items.Length;i++)items[i]=Walk(list[i],depth+1);
                        return Record(id,new {objectId=id,type=type.FullName,count=items.Length,items});
                    }
                    if(type.GetGenericTypeDefinition()==typeof(HashSet<>)) {
                        var items=new List<object?>(); foreach(var item in (IEnumerable)value) {if(items.Count>=MaxItems)return Fail("SET_COUNT_LIMIT",true);items.Add(Walk(item,depth+1));}
                        return Record(id,new {objectId=id,type=type.FullName,count=items.Count,items,unordered=true});
                    }
                    if(type.GetGenericTypeDefinition()==typeof(Dictionary<,>)) {
                        var map=(IDictionary)value; if(map.Count>MaxItems)return Fail("DICTIONARY_COUNT_LIMIT",true);
                        var entries=new List<object>(); foreach(DictionaryEntry e in map) entries.Add(new {key=Walk(e.Key,depth+1),value=Walk(e.Value,depth+1)});
                        return Record(id,new {objectId=id,type=type.FullName,count=entries.Count,entries});
                    }
                }
                if(value is Array a) {
                    if(a.Rank!=1 || a.GetLowerBound(0)!=0 || a.Length>MaxItems)return Fail("ARRAY_SHAPE_LIMIT",true);
                    var items=new object?[a.Length]; for(int i=0;i<items.Length;i++)items[i]=Walk(a.GetValue(i),depth+1);
                    return Record(id,new {objectId=id,type=type.FullName,count=items.Length,items});
                }
                // These two 7.1 models implement pin enumeration, but all business state is
                // held in the verified instance fields below. Never invoke their enumerators.
                if(value is IEnumerable && type.FullName!="h27B3oXlxcN6dvR6aQBi.yudq5KXlmuVpBrR7rVQF" &&
                    type.FullName!="aXUR4PXWZRmAHaw0UCFG.O6Xe5UXWOepEMsrsi0jb")return Fail("UNVERIFIED_ENUMERABLE:"+type.FullName);
                if(type.Assembly!=assembly)return Fail("UNSUPPORTED_FIELD_TYPE:"+type.FullName);
                var fields=new List<object>();
                for(var t=type;t!=null && t!=typeof(object);t=t.BaseType) {
                    // Common model base contains UI state, parent pointers, event subscribers,
                    // undo bookkeeping and process-local IDs, not persisted model content.
                    if(t.FullName=="hnRX5SXOfpHoFMcisZBH.sSJI8CXOTXcMB9gP3URF")break;
                    foreach(var field in t.GetFields(F).OrderBy(x=>x.Name,StringComparer.Ordinal)) {
                        if(fields.Count>=256){fields.Add(Fail("FIELD_COUNT_LIMIT",true));break;}
                        fields.Add(new {declaringType=t.FullName,name=field.Name,value=Walk(field.GetValue(value),depth+1)});
                    }
                }
                var result=new {objectId=type.IsValueType?(int?)null:id,type=type.FullName,fields};
                return type.IsValueType?result:Record(id,result);
            } catch(Exception ex) {return Fail("FIELD_READ:"+type.FullName+":"+ex.GetType().Name);}
        }
        internal object Summary() => new {complete=Errors.Count==0 && !Truncated,truncated=Truncated,errorCount=Errors.Count,errors=Errors.ToArray(),visitedValues=objects,payloadBytes=bytes};
    }

    static object ContentKey(CrudKey k) => new {category=new[]{k.Category0,k.Category1,k.Category2,k.Category3},id=k.Id};
    object? ContentStored(object owner,string legacy) {
        var wrapper=ContentFieldReader.Raw(owner,B(legacy));
        return wrapper==null?null:ContentFieldReader.Raw(wrapper,B("VpIiRZgdEln"));
    }
    (object Payload,uint Id) ContentIdentity() {
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if(manager.GetType().FullName!="RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx")throw new InvalidOperationException("CONTENT_MANAGER_TYPE");
        var payload=ContentFieldReader.Raw(manager,"YwCXahy5RIN") ?? throw new InvalidOperationException("CONTENT_PAYLOAD_NULL");
        if(payload.GetType().FullName!="FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM")throw new InvalidOperationException("CONTENT_PAYLOAD_TYPE");
        var header=ContentFieldReader.Raw(payload,"RmVRLESORxj") ?? throw new InvalidOperationException("CONTENT_HEADER_NULL");
        if(header.GetType().FullName!="PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw" || ContentFieldReader.Raw(header,"yoJRBJp4HeU") is not uint id)throw new InvalidOperationException("CONTENT_LEVEL_ID_TYPE");
        return (payload,id);
    }
    object ContentEndpoint(object endpoint) {
        var pin=Field(endpoint,B("Ds3K5LVxwhM"));
        return new {nodeId=(uint)Field(endpoint,B("iihK5hUQPDy")),kind=Convert.ToInt32(Field(pin,B("TqBK5Pk3Cw2"))),index=Convert.ToInt32(Field(pin,B("hWTK5MSRidQ")))};
    }
    public object InspectReopenContent() => CaptureReopenContent(false);
    // Fixed diagnostics only: one identical capture; never accepted as round-trip evidence.
    public object ProfileReopenContentSingleCapture() => CaptureReopenContent(true);
    object CaptureReopenContent(bool profileOnly)
    {
        RequireInitDispatcher();
        using var readBinding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var timingStart=Stopwatch.GetTimestamp();
        var timingStages=new Dictionary<string,long>();
        T Timed<T>(string name,Func<T> read) {
            var start=Stopwatch.GetTimestamp();
            try { return read(); }
            finally { timingStages.Add(name,Stopwatch.GetTimestamp()-start); }
        }
        void RecordTiming(string name,long start) => timingStages.Add(name,Stopwatch.GetTimestamp()-start);
        object TimingSnapshot() {
            var end=Stopwatch.GetTimestamp();
            return new {clock="Stopwatch",frequency=Stopwatch.Frequency,startTick=timingStart,endTick=end,totalTicks=end-timingStart,
                stages=new Dictionary<string,long>(timingStages),scope="adapter-dispatcher-call-through-content-hash; excludes bridge response serialization and transport"};
        }
        var captureNumber=0;
        var captureCounts=new {entityCount=0,graphCount=0,nodeCount=0,linkCount=0};
        var begin=DateTime.UtcNow; var identity=Timed("identity.before",ContentIdentity);
        if(identity.Id!=1073741840u)throw new InvalidOperationException("CONTENT_EXPECTED_LEVEL_1839");
        object Capture(out bool complete,out bool truncated,out int errorCount) {
            var captureStart=Stopwatch.GetTimestamp();
            var prefix="capture"+(++captureNumber)+".";
            var roots=new Dictionary<string,object?>();
            object Raw(object? value,string key) {roots.Add(key,value);return new {rootKey=key};}
            var resources=Timed(prefix+"resources",()=>ResourcesForReopenContent(readBinding)); var entities=Timed(prefix+"entities",ReadCrudEntities);
            var entityRowsStart=Stopwatch.GetTimestamp();
            if(entities.Count>128)throw new InvalidOperationException("CONTENT_ENTITY_LIMIT");
            var groups=resources.Where(r=>r.Kind==9).GroupBy(r=>r.Id).OrderBy(g=>g.Key).ToArray();
            if(groups.Length>128)throw new InvalidOperationException("CONTENT_GRAPH_LIMIT");
            var entityRows=entities.Values.OrderBy(e=>e.Key.Id).Select(e=>new {id=e.Key.Id,category=new[]{e.Key.Category0,e.Key.Category1,e.Key.Category2,e.Key.Category3},name=e.Name,prefabId=e.PrefabId,templateId=e.TemplateId,nativeEntityType=e.EntityType,nativeInstanceKind=e.InstanceKind,
                transform=TransformSnapshot(Field(e.Model,SceneTransformField)),graphBindings=EntityBindings(e.Model).Select(KeyFields).ToArray(),
                componentPresenceVerified=false,componentPresence=(bool?)null,rawFields=Raw(e.Model,"entity:"+e.Key.Id)}).ToArray();
            RecordTiming(prefix+"entityRowsAndGraphIndex",entityRowsStart);
            var graphRowsStart=Stopwatch.GetTimestamp();
            var graphRows=new List<object>(); int nodeTotal=0,linkTotal=0;
            foreach(var group in groups) {
                var graph=group.First();
                if(group.Any(r=>!ReferenceEquals(r.Model,graph.Model) || !r.Category.SequenceEqual(graph.Category)))throw new InvalidOperationException("CONTENT_GRAPH_ALIAS_CONFLICT");
                var nodes=GraphNodes(graph.Model); if(nodes.Count>4096)throw new InvalidOperationException("CONTENT_NODE_LIMIT");
                var nodeRows=nodes.Keys.Cast<object>().Select(k=>Convert.ToUInt32(k)).OrderBy(k=>k).Select(id=>{
                    var node=nodes[id] ?? throw new InvalidOperationException("CONTENT_NODE_NULL");
                    return new {id,definition=KeyFields(ContentStored(node,"tLtKHleyQAZ")),layout=new {x=Raw(ContentStored(node,"OpoKHL2l9bW"),"layout-x:"+graph.Id+":"+id),y=Raw(ContentStored(node,"Ft9KHqmCANf"),"layout-y:"+graph.Id+":"+id)},rawFields=Raw(node,"node:"+graph.Id+":"+id)};
                }).ToArray();
                var map=graph.Model.GetType().GetMethod(B("yKHKOFfNm2M"),Fields)!.Invoke(graph.Model,null)!;
                var links=(IDictionary)Field(map,B("cHuiFsU5V56")); if(links.Count>16384)throw new InvalidOperationException("CONTENT_LINK_LIMIT");
                var linkRows=links.Keys.Cast<object>().Select(e=>new {from=ContentEndpoint(Field(e,B("fH0izeMOw73"))),to=ContentEndpoint(Field(e,B("ABfizkqh4mD")))}).ToArray();
                nodeTotal+=nodes.Count;linkTotal+=links.Count;
                graphRows.Add(new {id=graph.Id,category=graph.Category,name=ContentStored(graph.Model,"c1pKbESgr8S"),nodeCount=nodes.Count,nodes=nodeRows,linkCount=links.Count,links=linkRows,
                    boundEntityIds=entities.Values.Where(e=>EntityBindings(e.Model).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)).Select(e=>e.Key.Id).OrderBy(x=>x).ToArray(),rawFields=Raw(graph.Model,"graph:"+graph.Id)});
            }
            RecordTiming(prefix+"graphRows",graphRowsStart);
            var rawFieldsStart=Stopwatch.GetTimestamp();
            var retained=Raw(identity.Payload,"retained-init");
            // One capture-wide reference table. Nodes reached through their graph are not
            // copied again when also named explicitly; every business root is retained.
            var reader=new ContentFieldReader(Editor());
            var rawFields=new {value=reader.Read(roots),read=reader.Summary()};
            complete=reader.Errors.Count==0 && !reader.Truncated; truncated=reader.Truncated; errorCount=reader.Errors.Count;
            RecordTiming(prefix+"rawFields",rawFieldsStart);
            RecordTiming(prefix+"total",captureStart);
            captureCounts=new {entityCount=entityRows.Length,graphCount=graphRows.Count,nodeCount=nodeTotal,linkCount=linkTotal};
            return new {entityCount=entityRows.Length,entities=entityRows,graphCount=graphRows.Count,graphs=graphRows,nodeCount=nodeTotal,linkCount=linkTotal,retainedInitialization=retained,rawFields};
        }
        var first=Capture(out var firstComplete,out var firstTruncated,out var firstErrors);
        if(profileOnly) {
            var sampleAfter=Timed("identity.after",ContentIdentity);
            var sampleIdentityStable=ReferenceEquals(identity.Payload,sampleAfter.Payload) && identity.Id==sampleAfter.Id;
            var sampleJson=Timed("dtoSerialize.first",()=>JsonSerializer.Serialize(first));
            return new {ok=firstComplete && sampleIdentityStable,schemaVersion=1,status="reopen-content-single-capture-profile",profileOnly=true,
                observedUtc=begin,finishedUtc=DateTime.UtcNow,levelId=identity.Id,sampleReadComplete=firstComplete,samePayloadIdentity=sampleIdentityStable,
                complete=false,captureComplete=false,stableReadback=false,truncated=firstTruncated,errorCount=firstErrors,counts=captureCounts,
                contentSha256=Timed("contentHash",()=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(sampleJson))).ToLowerInvariant()),
                reopenVerified=false,persistentSaveVerified=false,freshLoadVerified=false,sentToGame=false,timing=TimingSnapshot()};
        }
        var second=Capture(out var secondComplete,out var secondTruncated,out var secondErrors);
        var after=Timed("identity.after",ContentIdentity);
        // Serialize only our detached DTOs, never a native editor model or protocol object.
        var firstJson=Timed("dtoSerialize.first",()=>JsonSerializer.Serialize(first)); var secondJson=Timed("dtoSerialize.second",()=>JsonSerializer.Serialize(second));
        var stable=Timed("stableComparison",()=>ReferenceEquals(identity.Payload,after.Payload) && identity.Id==after.Id && firstJson==secondJson);
        var complete=firstComplete && secondComplete && stable;
        return new {ok=complete,schemaVersion=2,status=complete?"reopen-content-read-only-complete":"reopen-content-read-only-incomplete",observedUtc=begin,finishedUtc=DateTime.UtcNow,
            levelId=identity.Id,scope="materialized-editor-business-fields-and-retained-initialization-shared-graph",captureComplete=complete,complete,truncated=firstTruncated||secondTruncated,errorCount=firstErrors+secondErrors,stableReadback=stable,
            contentSha256=Timed("contentHash",()=>Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(firstJson))).ToLowerInvariant()),content=first,
            verifiedGetters=new[]{B("K61KONg4LUT"),B("t6ViSxlgnQ3"),B("yKHKOFfNm2M")},arbitraryGettersInvoked=false,nativeSerializerInvoked=false,nativeConstructorsInvoked=false,sentToGame=false,
            semanticComponentMappingVerified=false,formalGilParameterMappingVerified=false,freshLoadVerified=false,persistentSaveVerified=false,reopenVerified=false,
            excludedRuntimeBase="hnRX5SXOfpHoFMcisZBH.sSJI8CXOTXcMB9gP3URF",storageWrappersInclude="business-value-only; notifications and subscribers excluded",timing=TimingSnapshot()};
    }
}
