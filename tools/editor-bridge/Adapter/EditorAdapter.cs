using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Fixed, source-verified editor operations. Call only on the existing WPF dispatcher.
internal sealed partial class EditorAdapter
{
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    static string Registry => B("ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre");
    static string Producer => B("tbLtNPi0Ktj7XmlZMWvt.mCglXsi0ijgrwvs0SPGh");
    static string Param => B("yqZNjiiAvUGtexJ8Y8LW.IxtFOgiA4qhGnLhEyLFv");
    static string Model6 => B("IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C");
    static string Model9 => B("cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH");
    readonly HashSet<uint> attemptedExports=new();
    DateTime exportObservationUntilUtc;
    // One-shot guards, keyed by kind AND target rather than by kind alone.
    //
    // These were single bools, which is the same thing while a session touches one
    // graph -- and wrong the moment a session builds a whole game. Starting from an
    // empty project creates four graphs, and the second creator was refused with
    // CREATE_ALREADY_ATTEMPTED: not because it repeated itself, but because a
    // different graph's creation had already spent the same flag. The rule these
    // guards encode is "do not run this same mutation twice", and that rule names a
    // target, so the guard has to name one too.
    readonly HashSet<string> spent = new(StringComparer.Ordinal);
    bool Spent(string kind, string target) => spent.Contains(kind + ":" + target);
    void Spend(string kind, string target) => spent.Add(kind + ":" + target);
    bool editAttempted;
    bool wireAttempted;
    bool syncAttempted;
    DateTime? syncInvocationUtc;
    DateTime? syncRequestObservedUtc;
    int syncRequestsAfterInvocation;
    string? syncRequestPayloadType;
    public object SyncEditorChanges()
    {
        if(syncAttempted)throw new InvalidOperationException("SYNC_ALREADY_ATTEMPTED");
        var graphs=Resources().Where(r=>r.Kind==9).GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        var calibration=graphs.SingleOrDefault(r=>(Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName);
        // The demo graph and its bisect variants are all this project's own content. A swap
        // keeps the replaced graph on disk (there is no delete), so the session legitimately
        // holds one more graph than is bound; the ceiling moves with it.
        var allowed=new Dictionary<string,int>{{CalibrationGraphName,7},{RoutePlacementName,12},{TiledRouteName,39},{AuditGraphName,13},{PositionGraphName,16},{FinishGraphName,23},{GameLoopGraphName,GameLoopNodeTarget},{GameLoopVariantNoScoreboardName,GameLoopVariantNoScoreboardNodes},{GameLoopVariantCoreName,GameLoopVariantCoreNodes}};
        if(calibration==null || graphs.Length>6 || graphs.Any(r=>!allowed.TryGetValue(Stored(r.Model,B("c1pKbESgr8S")) as string??"",out var count) || GraphNodes(r.Model).Count!=count) ||
            graphs.Select(r=>Stored(r.Model,B("c1pKbESgr8S")) as string).Distinct().Count()!=graphs.Length)
            throw new InvalidOperationException("OWN_CALIBRATION_AND_ROUTE_SESSION_REQUIRED");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        // Save on graph category 21001 calls this native sync method. This is
        // an editor-wide sync, not proof of durable level persistence.
        if(!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"),Fields)!.Invoke(manager,new object[]{false})!)
            throw new InvalidOperationException("EDITOR_NOT_READY_TO_SYNC");
        syncAttempted=true;
        syncInvocationUtc=DateTime.UtcNow;
        manager.GetType().GetMethod(B("fIviJCKIQSe"),Fields)!.Invoke(manager,null);
        return new {ok=true,status="native-editor-sync-invoked",graphId=calibration.Id,
            scope="native-editor-wide-sync",persistentSaveVerified=false,playtestVerified=false};
    }
    const string ImportedGraphName="MW_Bridge_Import_20260916";
    const string CalibrationGraphName="MW_Platform_Calibration_20260916";
    bool logRequestAttempted;
    bool prefabRequestAttempted;
    List<object> prefabModels=new();
    List<object> entityModels=new();
    const string TestGraphName="MW_Bridge_Test_20260916";
    Dictionary<string,int> modelTypeCounts=new();
    List<object> entities=new();
    // The registry walk can reach the same entity model through more than one dictionary,
    // so `entities` used to carry one row per VISIT rather than one per entity: 14 entities
    // came back as 28 rows. SceneCatalogSnapshot() already de-duplicated by id, and the two
    // numbers disagreed in the same reply, which is exactly the kind of trap a reader falls
    // into. The raw visit count is kept separately so the duplication stays visible instead
    // of being silently smoothed over.
    HashSet<uint> entityIdsSeen=new();
    int entityRowsBeforeDedup;
    List<object> prefabCandidates=new();
    object? Stored(object model,string field)
    {
        try{return Field(Field(model,field),B("VpIiRZgdEln"));}
        catch(InvalidOperationException){return null;}
    }
    sealed record Resource(object Model, uint[] Category, uint Id, int Kind);
    static string B(string legacy) => EditorBindingProfile.Resolve(legacy);
    Assembly Editor() => EditorBindingProfile.RequireEditor();
    object Field(object obj, string name)
    {
        for (var t = obj.GetType(); t != null; t = t.BaseType)
            if (t.GetField(name, Fields | BindingFlags.DeclaredOnly) is FieldInfo f)
                return f.GetValue(obj) ?? throw new InvalidOperationException("NULL_FIELD:" + name);
        throw new MissingFieldException(name);
    }
    object ExistingSingleton(Assembly a, string typeName)
    {
        var target = a.GetType(typeName, true)!;
        var holder = a.GetType(B("yT2GjCi3sEnq3X39OnMH.vSwq2Ui3deULA6AUjQxt`1"), true)!.MakeGenericType(target);
        var lazy = holder.GetField(B("rZmi38av5uw"), BindingFlags.NonPublic | BindingFlags.Static)!.GetValue(null)!;
        if (!(bool)lazy.GetType().GetProperty("IsValueCreated")!.GetValue(lazy)!)
            throw new InvalidOperationException("SINGLETON_NOT_CREATED");
        return lazy.GetType().GetProperty("Value")!.GetValue(lazy)!;
    }
    List<Resource> Resources() => ResourcesCore(null);
    List<Resource> ResourcesForReopenContent(EditorBindingProfile.ReopenContentReadBinding binding) => ResourcesCore(binding);
    List<Resource> ResourcesCore(EditorBindingProfile.ReopenContentReadBinding? binding)
    {
        // No ambient state; ordinary callers take precisely the existing binding path.
        string B(string legacy) => binding == null ? EditorAdapter.B(legacy) : binding.Resolve(legacy);
        object? Stored(object model, string field)
        {
            if (binding == null) return this.Stored(model, field);
            try { return Field(Field(model, field), B("VpIiRZgdEln")); }
            catch (InvalidOperationException) { return null; }
        }
        object? KeyFields(object? key) => binding == null ? this.KeyFields(key) : key == null ? null : new {
            category = new[]{B("oLyiwZX255H"),B("AwbiwrjxUDX"),B("UFWiwJNegmh"),B("RBTiwn649Hy")}.Select(n => (uint)Field(key,n)).ToArray(),
            id = (uint)Field(key,B("namiwGPRyPS"))};
        object[] EntityBindings(object entity)
        {
            if (binding == null) return this.EntityBindings(entity);
            var list=entity.GetType().GetMethod(B("t6ViSxlgnQ3"),Fields)!.Invoke(entity,null)!;
            return ((IEnumerable)Field(list,B("VAfiNjPuW4e"))).Cast<object>().ToArray();
        }
        if (!System.Windows.Application.Current.Dispatcher.CheckAccess()) throw new InvalidOperationException("WRONG_THREAD");
        var root = Field(ExistingSingleton(Editor(), B("ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre")), B("bwbixDw3yob"));
        var result = new List<Resource>(); int nodes = 0;
        // The registry walk reaches the same model through more than one dictionary, so the
        // collected list used to hold one entry per VISIT. The graphs came back three times
        // each and the entities twice, which made resourceCount, groups[].count and
        // userGraphs all visit counts rather than resource counts. De-duplicating here fixes
        // every caller at once instead of one consumer at a time.
        var resourceSeen = new HashSet<string>();
        modelTypeCounts=new();
        entities=new();prefabCandidates=new();entityModels=new();prefabModels=new();entityIdsSeen=new();entityRowsBeforeDedup=0;
        void Visit(object node, int depth)
        {
            if (++nodes > 4096 || depth > 6) throw new InvalidOperationException("REGISTRY_LIMIT");
            foreach (DictionaryEntry entry in (IDictionary)Field(node, B("JkmYibSuDZr")))
            {
                var model = entry.Value!; string? name = model.GetType().FullName;
                modelTypeCounts[name!]=modelTypeCounts.GetValueOrDefault(name!)+1;
                if(name==B("Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr"))
                {
                    entityModels.Add(model);
                    entityRowsBeforeDedup++;
                    if(entityIdsSeen.Add((uint)entry.Key))
                    entities.Add(new {registryId=entry.Key,name=Stored(model,B("WAAiS5WkxlA")),prefabId=Stored(model,B("TuuiS94iUgu")),
                        identity=KeyFields(Stored(model,B("Qi8iCzKCkTt"))),graphBindings=EntityBindings(model).Select(KeyFields).ToArray()});
                }
                if(name==B("nWLQffitWoLLGIT98hlP.hRwGGsitgmhQZo9c1XOp"))
                {
                    prefabModels.Add(model);
                    var label=Stored(model,B("PChiBEHqYMS")) as string;
                    if(new uint[]{20001875,20001224,20001876,20001877,20001878}.Contains((uint)entry.Key) ||
                        (prefabCandidates.Count<80 && label!=null && new[]{"平台","方块","立方","石板","木板"}.Any(label.Contains)))
                        prefabCandidates.Add(new {registryId=entry.Key,name=label,identity=KeyFields(Stored(model,B("atbiBHcMllT"))),nativeKind=Stored(model,B("qgriBv1ZZtL"))});
                }
                if (name != B("IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C") && name != B("cwoW1eKmGGThJGs9Wxvm.A8NrPMKmnpQkIiiyYetH")) continue;
                var wrapper = Field(model, name == B("IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C") ? B("U0oKESVcL9L") : B("fLGKbbHeoYG"));
                var key = Field(wrapper, B("VpIiRZgdEln"));
                var category = new[] {B("oLyiwZX255H"), B("AwbiwrjxUDX"), B("UFWiwJNegmh"), B("RBTiwn649Hy")}.Select(n => (uint)Field(key,n)).ToArray();
                uint id = (uint)Field(key,B("namiwGPRyPS"));
                if (id != (uint)entry.Key) throw new InvalidOperationException("REGISTRY_ID_MISMATCH");
                int resourceKind = name == B("IpVbUoKHNx7P6wEKeDT2.jxqH4eKHRgIc1AAI2M9C") ? 6 : 9;
                if (resourceSeen.Add(resourceKind + "|" + string.Join(",", category) + "|" + id))
                    result.Add(new Resource(model, category, id, resourceKind));
                if (result.Count > 10000) throw new InvalidOperationException("RESOURCE_LIMIT");
            }
            foreach (DictionaryEntry entry in (IDictionary)Field(node,B("pIxYiE5REC8")))
            { Visit(entry.Value!,depth+1); }
        }
        Visit(root,0); return result;
    }
    object? KeyFields(object? key)=>key==null?null:new {
        category=new[]{B("oLyiwZX255H"),B("AwbiwrjxUDX"),B("UFWiwJNegmh"),B("RBTiwn649Hy")}.Select(n=>(uint)Field(key,n)),
        id=(uint)Field(key,B("namiwGPRyPS"))};
    public object Catalog()
    {
        var resources=Resources();
        var producer=ExistingSingleton(Editor(),Producer);
        var transport=Field(producer,B("xu7i0pEkGOC"));
        object? StoredName(Resource r)
        {
            try{return Field(Field(r.Model,r.Kind==6?B("DsBKEwvlwAl"):B("c1pKbESgr8S")),B("VpIiRZgdEln"));}
            catch(InvalidOperationException){return null;}
        }
        return new {ok=true, resourceCount=resources.Count,modelTypeCounts,
            entities, entityCount=entities.Count, entityRowsBeforeDedup,
            entitiesNote="entities is de-duplicated by registryId; entityRowsBeforeDedup is how many times the registry walk reached an entity model, which is larger when the same model is reachable from more than one dictionary.",
            prefabCandidates,scene=SceneCatalogSnapshot(),finishNodes=FinishNodeCatalog(resources),
            userGraphs=resources.Where(r=>r.Kind==9).Select(r=>new {category=r.Category,id=r.Id,name=StoredName(r),nodeCount=GraphNodes(r.Model).Count}),
            serverNodeDefinitions=resources.Where(r=>r.Kind==6 && r.Category[1]==20000).Select(r=>new {id=r.Id,name=StoredName(r)}).Distinct(),
            gameplayDefinitions=resources.Where(r=>r.Kind==6 && r.Category[1]==20000 &&
                (new uint[]{71,252}.Contains(r.Id) || new[]{"缩放","自身","相等","分支","初始化","仅执行一次"}.Any(s=>(StoredName(r) as string)?.Contains(s)==true)))
                .Select(r=>new {id=r.Id,name=StoredName(r),description=Stored(r.Model,B("HM9KEypghgm")),
                    pins=((IEnumerable)r.Model).Cast<object>().Select(p=>new {
                        name=Stored(p,B("T5GKmPxKaWk")),
                        kind=Convert.ToInt32(Field(Stored(p,B("quGKmYyTPnA"))!,B("TqBK5Pk3Cw2"))),
                        index=(int)Field(Stored(p,B("quGKmYyTPnA"))!,B("hWTK5MSRidQ"))}).ToArray()}).ToArray(),
            groups=resources.GroupBy(r=>string.Join(",",r.Category)).Select(g=>new {
                category=g.First().Category, count=g.Count(), models=g.GroupBy(r=>r.Kind).Select(k=>new {kind=k.Key,count=k.Count()}),
                samples=g.Take(8).Select(r=>new {id=r.Id,name=StoredName(r)}), minId=g.Min(r=>r.Id),maxId=g.Max(r=>r.Id)}),
            transportInitialized=Field(transport,B("t87iAmTH226")),
            transportCallbackPresent=transport.GetType().GetField(B("CO3iA5rBn33"),Fields)!.GetValue(transport)!=null,
            transportSocket=ReadTransportSocket(producer),
            levelLifecycle=LevelLifecycleSnapshot(),
            activeRoot="existing-lazy-singleton"};
    }
    IDictionary GraphNodes(object graph)
    {
        var map=graph.GetType().GetMethod(B("K61KONg4LUT"),Fields)!.Invoke(graph,null)!;
        return (IDictionary)Field(map,B("cHuiFsU5V56"));
    }
    object[] EntityBindings(object entity)
    {
        var list=entity.GetType().GetMethod(B("t6ViSxlgnQ3"),Fields)!.Invoke(entity,null)!;
        return ((IEnumerable)Field(list,B("VAfiNjPuW4e"))).Cast<object>().ToArray();
    }
    object? ExistingLogModel()
    {
        var registry=ExistingSingleton(Editor(),B("TisVe3KoM4SfmwtFXy3n.dDOKwYKoP8tIefHhgog5"));
        return ((IDictionary)Field(registry,B("nImKoZ6adkL"))).Values.Cast<object>()
            .FirstOrDefault(v=>v.GetType().FullName==B("XvpSBIuvoMSpMenoIqRg.C9ev3quv9MKMEBmJNJDj"));
    }
    public object RuntimeEvidence()
    {
        var resources=Resources();
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var context=Field(manager,B("Ke9indRyUDY"));
        var log=ExistingLogModel();
        var records=log==null?Array.Empty<object>():((IEnumerable)Field(log,B("dYQu35DBaxK"))).Cast<object>().ToArray();
        var markers=new[]{"MW_CALIBRATION_PLATFORM_CREATED_20260916","MW_BRIDGE_ENTITY_CREATED_20260916",AuditMarker,FinishMonitorMarker,FinishReachedMarker};
        var found=new HashSet<string>();
        var pending=new Queue<(object Value,int Depth)>();
        foreach(var record in records.Take(128))
        {
            var field=record.GetType().GetField(B("FSUuOVsfGPM"),Fields);
            if(field?.GetValue(record) is object payload)pending.Enqueue((payload,0));
        }
        // The native protobuf Descriptor is null. Do not invoke its JSON formatter/ToString.
        // Only inspect instance fields and bounded collections, never arbitrary property getters.
        var visited=new HashSet<object>(ReferenceEqualityComparer.Instance);
        int inspected=0;bool limited=records.Length>128;
        while(pending.Count>0 && inspected<8192)
        {
            var (value,depth)=pending.Dequeue();
            if(!visited.Add(value))continue;
            inspected++;
            if(value is string text){foreach(var marker in markers)if(text.Contains(marker,StringComparison.Ordinal))found.Add(marker);continue;}
            var type=value.GetType();
            if(type.IsPrimitive || type.IsEnum || value is byte[])continue;
            if(depth>=12){limited=true;continue;}
            if(value is IEnumerable collection)
            {
                int count=0;
                foreach(var item in collection){if(count++>=256){limited=true;break;}if(item!=null)pending.Enqueue((item,depth+1));}
            }
            else if(type.Assembly.GetName().Name=="BeyondEditor")
            {
                foreach(var field in type.GetFields(Fields))if(field.GetValue(value) is object child)pending.Enqueue((child,depth+1));
            }
        }
        limited|=pending.Count>0;
        return new {ok=true,observedUtc=DateTime.UtcNow,editorLevelState=Convert.ToInt32(Field(context,B("JkFiGb7j1JI"))),
            logModelPresent=log!=null,logRecordCount=records.Length,scannedRecordLimit=128,ownMarkers=found.ToArray(),
            markerScanObjects=inspected,markerScanLimited=limited,
            graphIds=resources.Where(r=>r.Kind==9).Select(r=>r.Id).Distinct().ToArray(),entityRegistrySlotCount=entityModels.Count,
            uniqueEntityModelCount=entityModels.Select(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))).Distinct().Count(),
            playtestVerified=false,notice="Missing markers do not prove the graph has not executed; this is existing editor log cache only."};
    }
    NativePacketObserverProxy? packetObserver;
    object? observerProducer;
    object[] originalReceivers=Array.Empty<object>();
    System.Windows.Threading.DispatcherTimer? observerTimer;
    bool observerActive;
    int observedPackets, observedLogPackets, observerScanObjects;
    bool observerScanLimited;
    string? observerCleanupError;
    object? debugLogReceipt;
    object? debugLogReply;
    DateTime? debugLogReplyUtc;
    readonly Dictionary<int,int> observedPacketKinds=new();
    readonly HashSet<string> observedMarkers=new();
    int observerLeaseSeconds=25;
    public object StartExternalAssetObserver()=>StartLogObserver(120);
    public object StartLogObserver(int seconds=25)
    {
        RequireInitDispatcher();
        if(seconds!=25 && seconds!=120)throw new InvalidOperationException("INVALID_OBSERVER_DURATION");
        if(packetObserver!=null)throw new InvalidOperationException("OBSERVER_ALREADY_ATTEMPTED");
        observerLeaseSeconds=seconds;
        var producer=ExistingSingleton(Editor(),Producer);
        var receivers=(IList)Field(producer,B("EdBi0U13Ia7"));
        var contract=Editor().GetType(B("mms6AS3ILkPSiIMIK84R.a2loy23IhuQeagPQb4Bx"),true)!;
        var methods=contract.GetMethods();
        if(!contract.IsInterface || methods.Length!=1 || methods[0].Name!=B("seAYooJHAHf") || methods[0].ReturnType!=typeof(void))
            throw new InvalidOperationException("OBSERVER_CONTRACT_CHANGED");
        BeginLevelInitObservation(producer);
        originalReceivers=receivers.Cast<object>().ToArray();
        packetObserver=(NativePacketObserverProxy)DispatchProxy.Create(contract,typeof(NativePacketObserverProxy));
        packetObserver.Configure(methods[0]);
        packetObserver.Receive=ObservePacket;
        observerProducer=producer;
        MarkObserverStarted();
        observerActive=true;
        producer.GetType().GetMethod(B("hUBi0lBOqTW"),Fields)!.Invoke(producer,new object[]{packetObserver});
        MarkObserverRegistered();
        observerTimer=new System.Windows.Threading.DispatcherTimer{Interval=TimeSpan.FromSeconds(observerLeaseSeconds)};
        observerTimer.Tick+=(_,_)=>{
            try{StopLogObserver("observer-lease-expired");}
            catch(Exception ex){MarkObserverStopped("observer-lease-expired");observerActive=false;observerTimer.Stop();observerCleanupError=ex.GetType().Name;}
        };
        leaseTimers.Add(observerTimer);
        observerTimer.Start();
        return LogObserverEvidence();
    }
    readonly List<object> scenePacketSnapshots=new();
    object SnapshotScenePayload(object? value,int depth,ref int remaining)
    {
        if(value==null)return new {isNull=true};
        if(--remaining<0 || depth>10)return new {limited=true,type=value.GetType().FullName};
        var t=value.GetType();
        if(t.IsPrimitive || t.IsEnum || value is decimal)return value;
        if(value is string str)return str.Length<=256?str:str.Substring(0,256);
        if(value is byte[] bytes)return new {byteLength=bytes.Length};
        if(value is IEnumerable list)
        {
            var items=new List<object>();
            foreach(var item in list){if(items.Count>=64 || remaining<=0)break;items.Add(SnapshotScenePayload(item,depth+1,ref remaining));}
            return new {type=t.FullName,items};
        }
        var fields=new Dictionary<string,object>();
        foreach(var f in t.GetFields(Fields))
        {
            if(f.IsStatic || fields.Count>=64 || remaining<=0)continue;
            try{fields[f.Name]=SnapshotScenePayload(f.GetValue(value),depth+1,ref remaining);}
            catch(Exception ex){fields[f.Name]=new {error=ex.GetType().Name};}
        }
        return new {type=t.FullName,fields};
    }
    void ObservePacket(object packet)
    {
        if(!observerActive)return;
        ObserveLevelInitPacket(packet);
        observedPackets++;
        var id=Convert.ToInt32(packet.GetType().GetMethod(B("oAb3IcMu6on"),Fields)!.Invoke(packet,null));
        if(observedPacketKinds.Count<64 || observedPacketKinds.ContainsKey(id))observedPacketKinds[id]=observedPacketKinds.GetValueOrDefault(id)+1;
        if(id==1017 && scenePacketSnapshots.Count<32 && observerLeaseSeconds==120)
        {
            try {
                var body=packet.GetType().GetMethod(B("NJr3IrdInPt"),Fields)!.Invoke(packet,null);
                CaptureGeometry1017(body);
                int remaining=1500;
                var snapshot=SnapshotScenePayload(body,0,ref remaining);
                scenePacketSnapshots.Add(new {utc=DateTime.UtcNow,id,snapshot,nodeLimitReached=remaining<=0});
            } catch(Exception ex){scenePacketSnapshots.Add(new {utc=DateTime.UtcNow,id,error=ex.GetType().Name});}
        }
        if(id==1020){CaptureExternalAssets(packet.GetType().GetMethod(B("NJr3IrdInPt"),Fields)!.Invoke(packet,null));return;}
        if(id==1019)
        {
            CaptureDebugLogRpcReply(packet.GetType().GetMethod(B("NJr3IrdInPt"),Fields)!.Invoke(packet,null));
            return;
        }
        if(id==1015 && syncInvocationUtc.HasValue)
        {
            var reply=packet.GetType().GetMethod(B("NJr3IrdInPt"),Fields)!.Invoke(packet,null);
            syncRequestPayloadType=reply?.GetType().FullName;
            // Native EyAiibCGyGJ schedules action 3; its Execute invokes sync.
            // 1015 is an inbound sync request, NOT an acknowledgement of 1014.
            if(reply?.GetType().Name==B("ULcU3FaeSaW8mUS8GDgi"))
            {
                syncRequestsAfterInvocation++;
                syncRequestObservedUtc=DateTime.UtcNow;
            }
            return;
        }
        if(id!=3002 && id!=3006)return;
        observedLogPackets++;
        if(observedLogPackets>32){observerScanLimited=true;return;}
        var payload=packet.GetType().GetMethod(B("NJr3IrdInPt"),Fields)!.Invoke(packet,null);
        if(payload==null)return;
        var structuredPosition=CaptureStructuredPositionLogs(payload);
        var pending=new Queue<(object Value,int Depth)>();pending.Enqueue((payload,0));
        var visited=new HashSet<object>(ReferenceEqualityComparer.Instance);
        int count=0;
        while(pending.Count>0 && count<8192)
        {
            var (value,depth)=pending.Dequeue();
            if(!visited.Add(value))continue;
            count++;
            CaptureAuditPrint(value);
            if(!structuredPosition)CapturePositionPrint(value);
            if(value is string text)
            {
                foreach(var marker in new[]{"MW_CALIBRATION_PLATFORM_CREATED_20260916","MW_BRIDGE_ENTITY_CREATED_20260916","MW_ROUTE_TILED_CREATED_20260916",AuditMarker,FinishMonitorMarker,FinishReachedMarker})
                    if(text.Contains(marker,StringComparison.Ordinal))observedMarkers.Add(marker);
                continue;
            }
            var type=value.GetType();
            if(type.IsPrimitive || type.IsEnum || value is byte[])continue;
            if(depth>=12){observerScanLimited=true;continue;}
            if(value is IEnumerable items)
            {
                int n=0;
                foreach(var item in items){if(n++>=256){observerScanLimited=true;break;}if(item!=null)pending.Enqueue((item,depth+1));}
            }
            else if(type.Assembly==Editor())
                foreach(var field in type.GetFields(Fields))if(field.GetValue(value) is object child)pending.Enqueue((child,depth+1));
        }
        observerScanObjects+=count;observerScanLimited|=pending.Count>0;
    }
    public object LogObserverEvidence()
    {
        var receivers=observerProducer==null?null:(IList)Field(observerProducer,B("EdBi0U13Ia7"));
        return new {ok=true,active=observerActive,observerTiming=ObserverTimingEvidence(),observedPackets,observedLogPackets,
            ownMarkers=observedMarkers.ToArray(),observerScanObjects,observerScanLimited,
            packetKinds=observedPacketKinds,scenePacketSnapshots=scenePacketSnapshots.ToArray(),observerCleanupError,debugLogReply,debugLogReplyUtc,debugLogRequestId,debugLogRpcSuccess,debugLogRpcReplyUtc,debugLogRpcMatchedResponses,
            syncInvocationUtc,syncRequestObservedUtc,syncRequestPayloadType,syncRequestsAfterInvocation,auditPrints,positionPrints,
            structuredPositionLogs=StructuredPositionLogEvidence(),runLogSample=RunLogSampleEvidence(),audioService=AudioServiceEvidence(),positionCapture=PositionCaptureEvidence(),
            externalAssets=ExternalAssetEvidence(),
            levelInitialization=LevelInitObservationEvidence(),
            componentGeometry=Geometry1017Evidence(),
            persistentSaveVerified=false,
            callbackErrors=packetObserver?.CallbackErrors??0,
            callbackInvocations=packetObserver?.CallbackInvocations??0,
            contractRejectedCallbacks=packetObserver?.ContractRejectedCallbacks??0,
            originalReceiversPreserved=receivers!=null && originalReceivers.All(r=>receivers.Contains(r)),
            observerRegistered=receivers!=null && packetObserver!=null && receivers.Contains(packetObserver),
            leaseSeconds=observerLeaseSeconds,playtestVerified=false,
            notice="Markers may originate from historical debug logs; absence is not proof of nonexecution."};
    }
    public object StopLogObserver()=>StopLogObserver("explicit-stop");
    object StopLogObserver(string reason)
    {
        RequireInitDispatcher();
        CaptureLevelInitObserverCleanupBaseline();
        MarkObserverStopped(reason);
        observerActive=false;observerTimer?.Stop();
        if(packetObserver!=null && observerProducer!=null)
        {
            packetObserver.Receive=null;
            // Called on the dispatcher, outside the native delivery enumeration.
            // Native unregister queues removal until the next packet. Complete
            // removal of only our sink here so an idle connection cannot retain it.
            observerProducer.GetType().GetMethod(B("MsOi0h1OdBN"),Fields)!.Invoke(observerProducer,new object[]{packetObserver});
            ((IList)Field(observerProducer,B("EdBi0U13Ia7"))).Remove(packetObserver);
            var deferred=Field(observerProducer,B("IF2i0RhOw8l"));
            deferred.GetType().GetMethod("Remove")!.Invoke(deferred,new object[]{packetObserver});
        }
        if(debugLogReceipt!=null && observerProducer!=null)
        {
            var transport=Field(observerProducer,B("xu7i0pEkGOC"));
            transport.GetType().GetMethod(B("MSgi0zbjIEA"),Fields)!.Invoke(transport,new[]{debugLogReceipt});
            debugLogReceipt=null;
        }
        return LogObserverEvidence();
    }
    void ReceiveDebugLogReply<T>(List<T> values)
    {
        try
        {
            debugLogReply=values.Take(32).Select(v=>typeof(T).GetFields(Fields)
                .Where(f=>f.FieldType.IsPrimitive || f.FieldType.IsEnum)
                .ToDictionary(f=>f.Name,f=>f.GetValue(v))).ToArray();
            debugLogReplyUtc=DateTime.UtcNow;
        }
        catch(Exception ex){observerCleanupError="reply:"+ex.GetType().Name;}
    }
    bool logEnableAttempted;
    public object EnableDebugLogging() => EnableDebugLoggingCore(false,null,Array.Empty<uint>());
    // The caller names the graph(s) to log; the identity is read from the request and
    // verified against the live level inside ConfigureOwnGraphLogSelection. No id or
    // name is baked in here.
    public object EnableOwnGraphLogging(JsonElement request)
    {
        var (requestedName,requestedIds)=OwnGraphLogSelectionRequest(request);
        return EnableDebugLoggingCore(true,requestedName,requestedIds);
    }
    object EnableDebugLoggingCore(bool selectOwnGraphs,string? requestedName,uint[] requestedIds)
    {
        if(logEnableAttempted)throw new InvalidOperationException("LOG_ENABLE_ALREADY_ATTEMPTED");
        if(!observerActive)throw new InvalidOperationException("NO_ACTIVE_LOG_OBSERVER");
        var producer=ExistingSingleton(Editor(),Producer);
        var connection=Field(producer,B("wYxi0oLiHdJ"));
        var connectionType=Editor().GetType(B("UJ5oX33I8PVUcq563icT.NZ9BZA3IM2qyEiuWoLhM"),true)!;
        var isReady=connectionType.GetMethod(B("XnxYo1tjrX0"),Fields)
            ?? throw new MissingMethodException("LOG_CONTROL_CONNECTION_READY");
        if(!connectionType.IsInstanceOfType(connection) || !(bool)isReady.Invoke(connection,null)!)
            throw new InvalidOperationException("EDITOR_CONNECTION_NOT_READY");
        // Exact rKguvffMJQa(true) payload. Prior state is unknown; no guessed restore.
        var inner=Activator.CreateInstance(Editor().GetType(B("TCeimgaSv8HFWBZL2Emr.bNf3IEaS4GdguXca3eut"),true)!)!;
        var outer=Activator.CreateInstance(Editor().GetType(B("uY432DaSLO9E1Pagl8Y2.SNYUqraShudVtwQSLBmO"),true)!)!;
        var setEnabled=inner.GetType().GetMethod(B("XwtaSuJH9gv"),Fields)
            ?? throw new MissingMethodException("LOG_CONTROL_SET_ENABLED");
        var setControl=outer.GetType().GetMethod(B("h0UaSTjlMFm"),Fields)
            ?? throw new MissingMethodException("LOG_CONTROL_SET_INNER");
        setEnabled.Invoke(inner,new object[]{true});
        var selectionPlan=selectOwnGraphs ? ConfigureOwnGraphLogSelection(inner,requestedName,requestedIds) : null;
        var selectedServerGraphIds=selectionPlan?.Ids ?? Array.Empty<uint>();
        setControl.Invoke(outer,new[]{inner});
        if(!(bool)Field(inner,B("I0DaSPm1JQc")) || !ReferenceEquals(Field(outer,B("doEaSUah24B")),inner))
            throw new InvalidOperationException("LOG_CONTROL_PAYLOAD_READBACK_FAILED");
        logEnableAttempted=true;
        producer.GetType().GetMethod(B("PHCi086M7o5"),Fields)!.Invoke(producer,new object[]{(ushort)3001,outer});
        return new {ok=true,status="native-log-enable-requested",messageId=3001,requestedEnabled=true,
            selectionSpecified=selectOwnGraphs,selectedServerGraphIds,selectedClientGraphIds=Array.Empty<uint>(),
            selection=selectionPlan,
            acknowledged=false,previousEnabledState="unknown",startsPlaytest=false};
    }
    public object RequestDebugLogs()
    {
        if(logRequestAttempted)throw new InvalidOperationException("LOG_REQUEST_ALREADY_ATTEMPTED");
        if(ExistingLogModel()==null && !observerActive)throw new InvalidOperationException("NO_LOG_RECEIVER_PRESENT");
        logRequestAttempted=true;
        // Exact native XlouvVFL1Yn request: no path, no arguments, no play-state transition.
        var producer=ExistingSingleton(Editor(),Producer);
        var param=Editor().GetType(Param,true)!;
        var callbackType=typeof(Action<>).MakeGenericType(typeof(List<>).MakeGenericType(param));
        var callback=typeof(EditorAdapter).GetMethod(nameof(ReceiveDebugLogReply),BindingFlags.NonPublic|BindingFlags.Instance)!
            .MakeGenericMethod(param).CreateDelegate(callbackType,this);
        debugLogReceipt=producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,
            new object?[]{"beyondExportService","ImportAllDebugLog",callback,null});
        if(debugLogReceipt==null)throw new InvalidOperationException("DEBUG_LOG_RECEIPT_MISSING");
        debugLogRequestId=(uint)Field(debugLogReceipt,B("dJVi0tPDg6E"));
        if(debugLogRequestId==0)throw new InvalidOperationException("DEBUG_LOG_REQUEST_NOT_DISPATCHED");
        if(observerProducer==null)observerProducer=producer;
        var cleanup=new System.Windows.Threading.DispatcherTimer{Interval=TimeSpan.FromSeconds(30)};
        cleanup.Tick+=(_,_)=>{cleanup.Stop();try{
            if(debugLogReceipt!=null){var transport=Field(producer,B("xu7i0pEkGOC"));transport.GetType().GetMethod(B("MSgi0zbjIEA"),Fields)!.Invoke(transport,new[]{debugLogReceipt});debugLogReceipt=null;}
        }catch(Exception ex){observerCleanupError="receipt-cleanup:"+ex.GetType().Name;}};
        leaseTimers.Add(cleanup);
        cleanup.Start();
        return new {ok=true,status="debug-log-refresh-requested",startsPlaytest=false};
    }
    public object BindTestGraph()
        => BindOwnGraph(TestGraphName,1073741825u,2);
    public object RequestCalibrationPrefab()
    {
        if(prefabRequestAttempted)throw new InvalidOperationException("PREFAB_REQUEST_ALREADY_ATTEMPTED");
        Resources();
        var prefab=prefabModels.FirstOrDefault(p=>(uint)Field(Stored(p,B("atbiBHcMllT"))!,B("namiwGPRyPS"))==20001875u &&
            (Stored(p,B("PChiBEHqYMS")) as string)=="通常立方体") ?? throw new InvalidOperationException("CALIBRATION_PREFAB_NOT_FOUND");
        var kind=Convert.ToInt32(Stored(prefab,B("qgriBv1ZZtL")));
        if(kind!=1)return new {ok=true,status="native-kind-guard-skipped",nativeKind=kind,requested=false};
        var id=(uint)prefab.GetType().GetMethod(B("VKeiBaSKFxp"),Fields)!.Invoke(prefab,null)!;
        if(id!=20001875u)throw new InvalidOperationException("PREFAB_NATIVE_ID_MISMATCH");
        var param=Editor().GetType(Param,true)!;
        var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        args.Add(param.GetMethod(B("bKliA0tj1p1"),BindingFlags.Static|BindingFlags.Public)!.Invoke(null,new object[]{id}));
        var producer=ExistingSingleton(Editor(),Producer);
        prefabRequestAttempted=true;
        producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,new object?[]{"beyondEditObjService","RequestPrefabInstance",null,args});
        return new {ok=true,status="native-prefab-instance-requested-readback-pending",prefabId=id,requested=true};
    }
    public object BindCalibrationGraph()
        => BindOwnGraph(CalibrationGraphName,null,7);
    public object RenameRealtimeLabTree(bool restore)
    {
        var resources=Resources();
        if(resources.Any(r=>r.Kind==9))throw new InvalidOperationException("LAB_EXPECTED_NO_GRAPHS");
        var sceneEntities=entityModels.GroupBy(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS")))
            .Select(g=>g.First()).Where(e=>Convert.ToInt32(Stored(e,B("yEpiSj6okKa")))==1402).ToArray();
        if(sceneEntities.Length!=1)throw new InvalidOperationException("LAB_EXPECTED_SINGLE_SCENE_TREE");
        var tree=sceneEntities[0];
        var id=(uint)Field(Stored(tree,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"));
        var name=Stored(tree,B("WAAiS5WkxlA")) as string;
        var expected=restore?"RT_Probe_Tree":"乔木";
        var target=restore?"乔木":"RT_Probe_Tree";
        if(id!=1077936129u || (name!=expected && name!=target))
            throw new InvalidOperationException("LAB_TREE_IDENTITY_CHANGED");
        if(name==target)return new {ok=true,status="already-named",id,name=target};
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if(!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"),Fields)!.Invoke(manager,new object[]{false})!)
            throw new InvalidOperationException("EDITOR_NOT_READY");
        // Native implementation sends the RPC. Never set the local name field.
        manager.GetType().GetMethod("ModifyEditObjName",Fields)!.Invoke(manager,new object[]{id,target});
        return new {ok=true,status="native-rename-requested-readback-pending",id,before=name,requestedName=target,
            localModelWritten=false,reloadInvoked=false,persistentSaveVerified=false};
    }
    // Bounded lab probe. Native menu permits RequestPrefabInstance only for kind 1.
    // This requests the default custom prefab context; it is NOT proven placement.
    public object RequestRealtimeLabPrefab()
    {
        if(prefabRequestAttempted)throw new InvalidOperationException("PREFAB_REQUEST_ALREADY_ATTEMPTED");
        var resources=Resources();
        var entityIds=entityModels.Select(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))).Distinct().ToArray();
        if(resources.Any(r=>r.Kind==9) || entityIds.Length!=11)
            throw new InvalidOperationException("REALTIME_LAB_REQUIRES_BLANK_BASELINE");
        var prefab=prefabModels.FirstOrDefault(p=>(uint)Field(Stored(p,B("atbiBHcMllT"))!,B("namiwGPRyPS"))==1086324737u &&
            (Stored(p,B("PChiBEHqYMS")) as string)=="默认模版")
            ?? throw new InvalidOperationException("LAB_PREFAB_NOT_FOUND");
        if(Convert.ToInt32(Stored(prefab,B("qgriBv1ZZtL")))!=1)
            throw new InvalidOperationException("LAB_PREFAB_NATIVE_KIND_MISMATCH");
        var id=(uint)prefab.GetType().GetMethod(B("VKeiBaSKFxp"),Fields)!.Invoke(prefab,null)!;
        if(id!=1086324737u)throw new InvalidOperationException("LAB_PREFAB_ID_MISMATCH");
        var param=Editor().GetType(Param,true)!;
        var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        args.Add(param.GetMethod(B("bKliA0tj1p1"),BindingFlags.Static|BindingFlags.Public)!.Invoke(null,new object[]{id}));
        prefabRequestAttempted=true;
        var receipt=ExistingSingleton(Editor(),Producer).GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!
            .Invoke(ExistingSingleton(Editor(),Producer),new object?[]{"beyondEditObjService","RequestPrefabInstance",null,args});
        return new {ok=true,status="lab-prefab-requested-effect-unverified",prefabId=id,nativeKind=1,
            receiptPresent=receipt!=null,entityIdsBefore=entityIds,reloadInvoked=false,sceneCreationVerified=false};
    }
    public object RequestRealtimeTreePrefab()
    {
        if(prefabRequestAttempted)throw new InvalidOperationException("PREFAB_REQUEST_ALREADY_ATTEMPTED");
        var resources=Resources();
        var entityIds=entityModels.Select(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))).Distinct().ToArray();
        if(resources.Any(r=>r.Kind==9) || entityIds.Length!=13)
            throw new InvalidOperationException("REALTIME_LAB_TREE_BASELINE_CHANGED");
        var prefab=prefabModels.FirstOrDefault(p=>(uint)Field(Stored(p,B("atbiBHcMllT"))!,B("namiwGPRyPS"))==1077936129u &&
            (Stored(p,B("PChiBEHqYMS")) as string)=="RT_Probe_Tree")
            ?? throw new InvalidOperationException("LAB_PREFAB_NOT_FOUND");
        if(Convert.ToInt32(Stored(prefab,B("qgriBv1ZZtL")))!=1)
            throw new InvalidOperationException("LAB_PREFAB_NATIVE_KIND_MISMATCH");
        var id=(uint)prefab.GetType().GetMethod(B("VKeiBaSKFxp"),Fields)!.Invoke(prefab,null)!;
        if(id!=1077936129u)throw new InvalidOperationException("LAB_PREFAB_ID_MISMATCH");
        var trees=entityModels.Where(e=>Convert.ToInt32(Stored(e,B("yEpiSj6okKa")))==1402)
            .GroupBy(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))).ToArray();
        if(trees.Length!=1 || trees[0].Key!=1077936129u)throw new InvalidOperationException("LAB_TREE_IDENTITY_CHANGED");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if(!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"),Fields)!.Invoke(manager,new object[]{false})!)
            throw new InvalidOperationException("EDITOR_NOT_READY");
        var param=Editor().GetType(Param,true)!;
        var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        args.Add(param.GetMethod(B("bKliA0tj1p1"),BindingFlags.Static|BindingFlags.Public)!.Invoke(null,new object[]{id}));
        prefabRequestAttempted=true;
        var receipt=ExistingSingleton(Editor(),Producer).GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!
            .Invoke(ExistingSingleton(Editor(),Producer),new object?[]{"beyondEditObjService","RequestPrefabInstance",null,args});
        return new {ok=true,status="lab-prefab-requested-effect-unverified",prefabId=id,nativeKind=1,
            receiptPresent=receipt!=null,entityIdsBefore=entityIds,reloadInvoked=false,sceneCreationVerified=false};
    }
    object BindOwnGraph(string name,uint? expectedId,int expectedNodes)
    {
        if(Spent("bind",name))throw new InvalidOperationException("BIND_ALREADY_ATTEMPTED");
        var resources=Resources();
        var matches=resources.Where(r=>r.Kind==9 && (!expectedId.HasValue || r.Id==expectedId.Value) &&
            (Stored(r.Model,B("c1pKbESgr8S")) as string)==name).GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(matches.Length!=1)throw new InvalidOperationException("OWN_GRAPH_IDENTITY_NOT_UNIQUE");
        var graph=matches[0];
        if(GraphNodes(graph.Model).Count!=expectedNodes)throw new InvalidOperationException("TEST_GRAPH_NOT_READY");
        var entity=entityModels.FirstOrDefault(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u &&
            (Stored(e,B("WAAiS5WkxlA")) as string)=="关卡实体")
            ?? throw new InvalidOperationException("LEVEL_ENTITY_NOT_FOUND");
        if(EntityBindings(entity).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id))
            return new {ok=true,status="already-bound",entityId=1094713345u,graphId=graph.Id};
        var entityId=(uint)entity.GetType().GetMethod(B("G9oiCBkSaYQ"),Fields)!.Invoke(entity,null)!;
        var graphId=(uint)graph.Model.GetType().GetMethod(B("MexKm2jjjVm"),Fields)!.Invoke(graph.Model,null)!;
        if(entityId!=1094713345u || graphId!=graph.Id)throw new InvalidOperationException("NATIVE_ID_MISMATCH");
        var p=Editor().GetType(Param,true)!;
        var list=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(p))!;
        object Wrap(string method,object value)=>p.GetMethod(method,BindingFlags.Public|BindingFlags.Static)!.Invoke(null,new[]{value})!;
        list.Add(Wrap(B("h8diA3iOGmJ"),true));
        list.Add(Wrap(B("bKliA0tj1p1"),entityId));
        list.Add(Wrap(B("qsriAuLLSBe"),1u));
        list.Add(Wrap(B("bKliA0tj1p1"),graphId));
        var producer=ExistingSingleton(Editor(),Producer);
        Spend("bind",name);
        producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,
            new object?[]{"beyondEditObjService","AddInstructionGraphForEditObj",null,list});
        return new {ok=true,status="binding-requested-readback-pending",entityId,graphId};
    }
    object Pin(object node,int kind,int index)
    {
        var method=node.GetType().GetMethods(Fields).Single(m=>m.Name=="GetPin" && m.GetParameters().Length==2);
        return method.Invoke(node,new[]{Enum.ToObject(method.GetParameters()[0].ParameterType,kind),(object)index})
            ?? throw new InvalidOperationException("REQUIRED_PIN_MISSING");
    }
    public object WireTestEvent()
    {
        if(wireAttempted)throw new InvalidOperationException("WIRE_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.FirstOrDefault(r=>r.Kind==9 && r.Id==1073741825u &&
            (Stored(r.Model,B("c1pKbESgr8S")) as string)==TestGraphName)
            ?? throw new InvalidOperationException("OWN_TEST_GRAPH_NOT_FOUND");
        var nodes=GraphNodes(graph.Model);
        if(nodes.Count!=1 || !nodes.Contains(1u))throw new InvalidOperationException("TEST_GRAPH_STATE_MISMATCH");
        var print=nodes[1u]!;
        if((uint)Field(Stored(print,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=1u)
            throw new InvalidOperationException("PRINT_NODE_MISMATCH");
        var input=Pin(print,1,0);
        var textPin=Pin(print,3,0);
        var valueWrapper=textPin.GetType().GetProperty("value")!.GetValue(textPin)!;
        var value=valueWrapper.GetType().GetProperty("Value")!.GetValue(valueWrapper)
            ?? throw new InvalidOperationException("PRINT_VALUE_NOT_INITIALIZED");
        var setter=value.GetType().GetMethod(B("MfLKK0bLIju"),Fields)!;
        var eventDef=resources.First(r=>r.Kind==6 && r.Id==71 && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        if((Stored(eventDef.Model,B("DsBKEwvlwAl")) as string)!="实体创建时")
            throw new InvalidOperationException("EVENT_DEFINITION_MISMATCH");
        var linkType=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!;
        var constructor=linkType.GetConstructors().Single(c=>c.GetParameters().Length==2);
        var connect=graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!;
        wireAttempted=true;
        setter.Invoke(value,new object?[]{"MW_BRIDGE_ENTITY_CREATED_20260916",null});
        var eventNode=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!
            .Invoke(graph.Model,new object?[]{Stored(eventDef.Model,B("U0oKESVcL9L")),0d,200d,null,null})
            ?? throw new InvalidOperationException("EVENT_NODE_NOT_CREATED");
        var output=Pin(eventNode,2,0);
        object Address(object pin)=>pin.GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(pin,null)!;
        var link=constructor.Invoke(new[]{Address(output),Address(input)});
        var linked=(bool)connect.Invoke(graph.Model,new object?[]{link,null,-1})!;
        if(!linked)throw new InvalidOperationException("LINK_REJECTED");
        return new {ok=true,status="editor-graph-wired-game-export-pending",graphId=graph.Id,nodeCount=nodes.Count,
            linked,marker="MW_BRIDGE_ENTITY_CREATED_20260916"};
    }
    public object AddTestPrint()
    {
        if(editAttempted)throw new InvalidOperationException("EDIT_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.FirstOrDefault(r=>r.Kind==9 && r.Id==1073741825u &&
            (Stored(r.Model,B("c1pKbESgr8S")) as string)==TestGraphName)
            ?? throw new InvalidOperationException("OWN_TEST_GRAPH_NOT_FOUND");
        var nodes=GraphNodes(graph.Model);
        if(nodes.Count!=0)throw new InvalidOperationException("TEST_GRAPH_NOT_EMPTY");
        var definition=resources.First(r=>r.Kind==6 && r.Id==1 && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        if((Stored(definition.Model,B("DsBKEwvlwAl")) as string)!="打印字符串")
            throw new InvalidOperationException("PRINT_DEFINITION_MISMATCH");
        var key=Stored(definition.Model,B("U0oKESVcL9L"))!;
        editAttempted=true;
        var node=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!
            .Invoke(graph.Model,new object?[]{key,400d,200d,null,null});
        if(node==null || nodes.Count!=1)throw new InvalidOperationException("NODE_NOT_CREATED");
        return new {ok=true,status="editor-model-edited-game-save-not-verified",graphId=graph.Id,
            nodeCount=nodes.Count,nodeIds=nodes.Keys.Cast<object>().ToArray(),definitionId=1};
    }
    public object CreateTestGraph()
    {
        if(Spent("create",TestGraphName))throw new InvalidOperationException("CREATE_ALREADY_ATTEMPTED");
        if(Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==TestGraphName))
            throw new InvalidOperationException("TEST_GRAPH_ALREADY_EXISTS");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
        var kind=Enum.ToObject(method.GetParameters()[0].ParameterType,20000);
        Spend("create",TestGraphName);
        method.Invoke(manager,new object?[]{kind,TestGraphName,0u,null});
        return new {ok=true,status="create-requested-not-verified",name=TestGraphName,graphKind=20000,folderId=0};
    }
    public object CreateCalibrationGraph()
    {
        if(Spent("create",CalibrationGraphName))throw new InvalidOperationException("CREATE_ALREADY_ATTEMPTED");
        if(Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName))
            throw new InvalidOperationException("CALIBRATION_ALREADY_EXISTS");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
        Spend("create",CalibrationGraphName);
        method.Invoke(manager,new object?[]{Enum.ToObject(method.GetParameters()[0].ParameterType,20000),CalibrationGraphName,0u,null});
        return new {ok=true,status="create-requested-readback-pending",name=CalibrationGraphName};
    }
    public object BuildCalibrationGraph()
    {
        if(Spent("calibration-build",CalibrationGraphName))throw new InvalidOperationException("CALIBRATION_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.FirstOrDefault(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName)
            ?? throw new InvalidOperationException("CALIBRATION_GRAPH_NOT_FOUND");
        if(GraphNodes(graph.Model).Count!=0)throw new InvalidOperationException("CALIBRATION_NOT_EMPTY");
        // This graph is deliberately left unbound until its exported parameters and guard are verified.
        Spend("calibration-build",CalibrationGraphName);
        object Add(uint id,double x,double y)
        {
            var def=resources.First(r=>r.Kind==6 && r.Id==id && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
            return graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
                new object?[]{Stored(def.Model,B("U0oKESVcL9L")),x,y,null,null})!;
        }
        void Link(object from,int fromKind,int fromIndex,object to,int toKind,int toIndex)
        {
            object Address(object n,int k,int i)=>Pin(n,k,i).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(n,k,i),null)!;
            var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
            var link=ctor.Invoke(new[]{Address(from,fromKind,fromIndex),Address(to,toKind,toIndex)});
            if(!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{link,null,-1})!)
                throw new InvalidOperationException("CALIBRATION_LINK_REJECTED");
        }
        void Set(object node,int index,string setter,object data)
        {
            var pin=Pin(node,3,index);
            var wrapper=pin.GetType().GetProperty("value")!.GetValue(pin)!;
            var value=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) ?? throw new InvalidOperationException("CALIBRATION_VALUE_NULL");
            value.GetType().GetMethod(setter,Fields)!.Invoke(value,new object?[]{data,null});
        }
        var ev=Add(71,0,0); var self=Add(73,0,300); var equal=Add(14,350,250);
        var branch=Add(2,700,0); var spawn=Add(252,1050,0); var print=Add(1,1450,0);
        Link(ev,4,0,equal,3,0); Link(self,4,0,equal,3,1); Link(equal,4,0,branch,3,0);
        Link(ev,2,0,branch,1,0); Link(branch,2,0,spawn,1,0); Link(spawn,2,0,print,1,0);
        Link(self,4,0,spawn,3,3);
        Set(spawn,0,B("LhkKKbraAbs"),20001875u);
        Set(spawn,5,B("CHHKK434xan"),false);
        Set(spawn,6,B("c84KKE8ihrN"),1);
        Set(print,0,B("MfLKK0bLIju"),"MW_CALIBRATION_PLATFORM_CREATED_20260916");
        return new {ok=true,status="calibration-authored-unbound-export-pending",name=CalibrationGraphName,graphId=graph.Id,nodeCount=GraphNodes(graph.Model).Count};
    }
    public object ExportCalibrationGraph(string outputDirectory)
    {
        var resource=Resources().FirstOrDefault(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName)
            ?? throw new InvalidOperationException("CALIBRATION_GRAPH_NOT_FOUND");
        return ExportResource(resource,outputDirectory);
    }
    public object SetCalibrationOrigin()
    {
        if(Spent("calibration-origin",CalibrationGraphName))throw new InvalidOperationException("CALIBRATION_ALREADY_ATTEMPTED");
        var resources=Resources();
        // This was pinned to 1073741827, the id the calibration graph happened to be
        // given in the first level it was built in. Level ids are assigned per level,
        // so that pin made the op refuse in every other project -- precisely the case
        // "develop the demo from an empty project" needs. The name is the graph's
        // stable identity; the id is a property of where it currently lives.
        var graph=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).SingleOrDefault()
            ?? throw new InvalidOperationException("CALIBRATION_GRAPH_NOT_FOUND");
        var nodes=GraphNodes(graph.Model);
        if(nodes.Count!=6 || !nodes.Contains(5u))throw new InvalidOperationException("CALIBRATION_STATE_MISMATCH");
        var spawn=nodes[5u]!;
        if((uint)Field(Stored(spawn,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=252u)throw new InvalidOperationException("SPAWN_NODE_MISMATCH");
        var definition=resources.First(r=>r.Kind==6 && r.Id==192u && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        if((Stored(definition.Model,B("DsBKEwvlwAl")) as string)!="三维向量：零向量")throw new InvalidOperationException("ZERO_VECTOR_DEFINITION_MISMATCH");
        Spend("calibration-origin",CalibrationGraphName);
        var zero=graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
            new object?[]{Stored(definition.Model,B("U0oKESVcL9L")),700d,500d,null,null})!;
        object Address(object n,int kind,int index)=>Pin(n,kind,index).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(n,kind,index),null)!;
        var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
        foreach(int index in new[]{1,2})
        {
            var link=ctor.Invoke(new[]{Address(zero,4,0),Address(spawn,3,index)});
            if(!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{link,null,-1})!)
                throw new InvalidOperationException("ORIGIN_LINK_REJECTED");
        }
        return new {ok=true,status="explicit-zero-position-rotation-export-pending",nodeCount=nodes.Count,graphId=graph.Id};
    }
    public object ImportVerifiedGraph()
        => ImportFixedGraph(ImportedGraphName,"verified-test-graph.pb","9C733120A7FD614F5576ED528CA998AFDCFB096D31463CE031EFB82743BFC334",2);
    const string TiledRouteName="MW_Route_Tiled_20260916";
    public object ImportTiledRoute()
        => ImportFixedGraph(TiledRouteName,"tiled-route.pb","25A49E51CCDBF2FDE730C2990FF38AD1DC04F7D15A10CEA4E575B4EE6BBF79F8",39);
    public object ExportTiledRoute(string outputDirectory)
    {
        var matches=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==TiledRouteName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(matches.Length!=1 || GraphNodes(matches[0].Model).Count!=39)throw new InvalidOperationException("TILED_ROUTE_NOT_READY");
        return ExportResource(matches[0],outputDirectory);
    }
    public object BindTiledRoute()
    {
        var calibration=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        if(GraphNodes(calibration.Model).Count!=7 || !entityModels.Any(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u && EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==calibration.Id)))
            throw new InvalidOperationException("BOUND_CALIBRATION_CENTER_REQUIRED");
        return BindOwnGraph(TiledRouteName,null,39);
    }
    const string RoutePlacementName="MW_Route_Placement_20260916";
    public object ImportRoutePlacement()
        => ImportFixedGraph(RoutePlacementName,"route-placement.pb","60AFAE47AFE7ECB34BB2950449BF22CFB13BA27523ED1F6590A9C190A6B5A15F",12);
    public object ExportRoutePlacement(string outputDirectory)
    {
        var matches=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==RoutePlacementName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(matches.Length!=1 || GraphNodes(matches[0].Model).Count!=12)throw new InvalidOperationException("ROUTE_GRAPH_NOT_READY");
        return ExportResource(matches[0],outputDirectory);
    }
    public object ImportCalibrationGraph()
        => ImportFixedGraph(CalibrationGraphName,"calibration-graph.pb","52CF5C276D6FDF0CCB96022AAC5D5CC3259D50D71834ABF12D9ABFEC93DF947D",7);
    object ImportFixedGraph(string name,string fileName,string expectedHash,int expectedNodes)
    {
        if(Spent("import",name))throw new InvalidOperationException("IMPORT_ALREADY_ATTEMPTED");
        if(Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==name))
            throw new InvalidOperationException("IMPORT_GRAPH_ALREADY_EXISTS");
        string path=Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\imports",fileName);
        var bytes=File.ReadAllBytes(path);
        var hash=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes));
        if(hash!=expectedHash)
            throw new InvalidOperationException("IMPORT_PAYLOAD_HASH_MISMATCH");
        var a=Editor();
        var protoType=a.GetType(B("dtCyX8ao6wX81LGIyEgY.f4A1VQaoFD29hLxbgRyd"),true)!;
        var parser=protoType.GetProperty(B("rJZaopuTsYW"),BindingFlags.Public|BindingFlags.Static)!.GetValue(null)!;
        var proto=parser.GetType().GetMethod(B("hGkESFcAaV"),new[]{typeof(byte[])})!.Invoke(parser,new object[]{bytes})!;
        var manager=ExistingSingleton(a,B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var temporary=manager.GetType().GetMethod(B("WnqiJxnOpxs"),BindingFlags.Static|BindingFlags.NonPublic)!.Invoke(null,new[]{proto})
            ?? throw new InvalidOperationException("GRAPH_DESERIALIZATION_FAILED");
        try
        {
            if(GraphNodes(temporary).Count!=expectedNodes)throw new InvalidOperationException("IMPORT_NODE_COUNT_MISMATCH");
            var create=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
            Spend("import",name);
            create.Invoke(manager,new object?[]{Enum.ToObject(create.GetParameters()[0].ParameterType,20000),name,0u,temporary});
        }
        finally
        {
            // Native create deep-copies its source. Release only our temporary model.
            temporary.GetType().GetMethod("Recycle",Fields)!.Invoke(temporary,null);
        }
        return new {ok=true,status="file-graph-import-requested-readback-pending",name=name,payloadSha256=hash,nodeCount=expectedNodes};
    }
    public object ExportImportedGraph(string outputDirectory)
    {
        var resource=Resources().FirstOrDefault(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==ImportedGraphName)
            ?? throw new InvalidOperationException("IMPORTED_GRAPH_NOT_FOUND");
        return ExportResource(resource,outputDirectory);
    }
    sealed class ExportReplyCapture
    {
      readonly string path;
      public ExportReplyCapture(string path){this.path=path;}
      public void Receive<T>(List<T> values)
      {
        try
        {
            var rows=values.Take(32).Select(value=>typeof(T).GetFields(Fields)
                .Where(f=>f.FieldType.IsPrimitive || f.FieldType.IsEnum || f.FieldType==typeof(string))
                .ToDictionary(f=>f.Name,f=>f.GetValue(value))).ToArray();
            File.WriteAllText(path,System.Text.Json.JsonSerializer.Serialize(new {receivedUtc=DateTime.UtcNow,rows}));
        }
        catch(Exception ex){BridgeLog.Write("export reply capture failed: "+ex.GetType().Name);}
    }
    }
    public object ExportFirst(string outputDirectory)
    {
        // Type 6 includes built-in node definitions such as "Print String". Their
        // presence and a successful RPC do not make them user-created assets.
        var resources=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==TestGraphName).ToList();
        if(resources.Count==0) throw new InvalidOperationException("NO_USER_GRAPH_IN_ACTIVE_REGISTRY");
        return ExportResource(resources[0],outputDirectory);
    }
    object ExportResource(Resource r,string outputDirectory)
    {
        // Native C6xKBZLdA0J accepts model kinds 6 or 9 only; our bridge further
        // restricts export to the project-owned user graph (kind 9).
        if(r.Kind!=9)throw new InvalidOperationException("UNSUPPORTED_EXPORT_MODEL");
        if(attemptedExports.Contains(r.Id) || attemptedExports.Count>=2)throw new InvalidOperationException("EXPORT_DUPLICATE_OR_LEASE_LIMIT");
        if(DateTime.UtcNow<exportObservationUntilUtc)throw new InvalidOperationException("PREVIOUS_EXPORT_OBSERVATION_PENDING");
        var a=Editor(); var producer=ExistingSingleton(a,Producer);
        var p=a.GetType(Param,true)!; var list=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(p))!;
        object Wrap(string method,object value)=>p.GetMethod(method,BindingFlags.Public|BindingFlags.Static)!.Invoke(null,new[]{value})!;
        foreach(var c in r.Category) list.Add(Wrap(B("qsriAuLLSBe"),c));
        list.Add(Wrap(B("bKliA0tj1p1"),r.Id));
        Directory.CreateDirectory(outputDirectory);
        string path=Path.Combine(outputDirectory,"bridge-export-"+Guid.NewGuid().ToString("N")+".gia");
        if(File.Exists(path))throw new IOException("OUTPUT_EXISTS");
        list.Add(Wrap(B("wNLiAK8Wcix"),path));
        var replyPath=path+".reply.json";
        var capture=new ExportReplyCapture(replyPath);
        var callbackType=typeof(Action<>).MakeGenericType(typeof(List<>).MakeGenericType(p));
        var callback=typeof(ExportReplyCapture).GetMethod(nameof(ExportReplyCapture.Receive),BindingFlags.Public|BindingFlags.Instance)!
            .MakeGenericMethod(p).CreateDelegate(callbackType,capture);
        attemptedExports.Add(r.Id); // no retry after a possibly successful asynchronous send
        exportObservationUntilUtc=DateTime.UtcNow.AddSeconds(30);
        var receipt=producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,new object?[]{"beyondExportService","DoExport",callback,list});
        // Remove only our callback registration after a bounded observation interval.
        var transport=Field(producer,B("xu7i0pEkGOC"));
        if(receipt!=null)exportReceipts.Add((transport,receipt));
        var cleanup=new System.Windows.Threading.DispatcherTimer{Interval=TimeSpan.FromSeconds(30)};
        cleanup.Tick+=(_,_)=>{
            cleanup.Stop();
            try {transport.GetType().GetMethod(B("MSgi0zbjIEA"),Fields)!.Invoke(transport,new[]{receipt});exportReceipts.RemoveAll(item=>ReferenceEquals(item.Receipt,receipt));}
            catch(Exception ex){BridgeLog.Write("export callback cleanup failed: "+ex.GetType().Name);}
        };
        leaseTimers.Add(cleanup);
        cleanup.Start();
        var receiptFields=receipt?.GetType().GetFields(Fields).Where(f=>f.FieldType.IsPrimitive).ToDictionary(f=>f.Name,f=>f.GetValue(receipt));
        return new {ok=true,status="invoked-not-confirmed",receiptFields,path,replyPath,callbackWindowSeconds=30,category=r.Category,id=r.Id,modelType=r.Kind};
    }
}
