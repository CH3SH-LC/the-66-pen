using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    const string AuditGraphName="MW_Runtime_Count_Audit_20260916";
    const string AuditTimerName="MW_AUDIT_ONESHOT_20260916";
    const string AuditMarker="MW_AUDIT_GLOBAL_PREFAB_20001875_COUNT_NEXT";
    bool auditBuildAttempted;
    readonly List<object> auditPrints=new();
    void CaptureAuditPrint(object value)
    {
        if(auditPrints.Count>=32 || value.GetType().FullName!=B("HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD"))return;
        // Restrict capture to a native record explicitly naming our graph.
        // Preserve printed text as evidence; do not infer course-owned counts.
        var type=value.GetType();
        if(!new[]{B("evca2Fc2YBM"),B("Dsva2frS2bQ"),B("IZYa2chZI6A")}.Any(f=>(type.GetField(f,Fields)?.GetValue(value) as string)==AuditGraphName))return;
        var body=type.GetField(B("vqqa2GmktMW"),Fields)?.GetValue(value);
        if(body?.GetType().FullName!=B("L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB"))return;
        var text=body.GetType().GetField(B("wmmat7vdE8l"),Fields)?.GetValue(body) as string;
        if(text==AuditMarker || (text!=null && text.Length<=6 && uint.TryParse(text,NumberStyles.None,CultureInfo.InvariantCulture,out var count) && count<=100000))
            auditPrints.Add(new {observedUtc=DateTime.UtcNow,printedText=text,graphName=AuditGraphName,courseOwnedCountVerified=false});
    }
    public object CreateAuditGraph()
    {
        if(Spent("create",AuditGraphName) || Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==AuditGraphName))
            throw new InvalidOperationException("AUDIT_CREATE_ALREADY_PRESENT_OR_ATTEMPTED");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
        Spend("create",AuditGraphName);
        method.Invoke(manager,new object?[]{Enum.ToObject(method.GetParameters()[0].ParameterType,20000),AuditGraphName,0u,null});
        return new {ok=true,name=AuditGraphName,status="audit-created-unbound"};
    }
    public object BuildAuditGraph()
    {
        if(auditBuildAttempted)throw new InvalidOperationException("AUDIT_BUILD_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==AuditGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        if(GraphNodes(graph.Model).Count!=0)throw new InvalidOperationException("AUDIT_NOT_EMPTY");
        if(entityModels.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)))throw new InvalidOperationException("AUDIT_MUST_BE_UNBOUND");
        auditBuildAttempted=true;
        object Add(uint id,int order)
        {
            var def=resources.First(r=>r.Kind==6 && r.Id==id && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
            return graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"),Fields)!.Invoke(graph.Model,
                new object?[]{Stored(def.Model,B("U0oKESVcL9L")),(double)((order%5)*400),(double)((order/5)*400),null,null})!;
        }
        void Link(object from,int fk,int fi,object to,int tk,int ti)
        {
            object Address(object n,int k,int i)=>Pin(n,k,i).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(n,k,i),null)!;
            var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!.GetConstructors().Single(c=>c.GetParameters().Length==2);
            var link=ctor.Invoke(new[]{Address(from,fk,fi),Address(to,tk,ti)});
            if(!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"),Fields)!.Invoke(graph.Model,new object?[]{link,null,-1})!)
                throw new InvalidOperationException("AUDIT_LINK_REJECTED:"+fk+":"+fi+"->"+tk+":"+ti);
        }
        object Value(object n,int i){var p=Pin(n,3,i);var w=p.GetType().GetProperty("value")!.GetValue(p)!;return w.GetType().GetProperty("Value")!.GetValue(w)!;}
        void Set(object n,int i,string method,object data){var v=Value(n,i);if(v.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(v,null)!.ToString()=="Generics")v=v.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(v,null)!;v.GetType().GetMethod(method,Fields)!.Invoke(v,new object?[]{data,null});}
        var created=Add(71,0);var self=Add(73,1);var ownerEqual=Add(14,2);var ownerBranch=Add(2,3);
        var timer=Add(79,4);var tick=Add(83,5);var nameEqual=Add(14,6);var timerBranch=Add(2,7);
        var query=Add(320,8);var length=Add(142,9);var convert=Add(180,10);var header=Add(1,11);var count=Add(1,12);
        Link(created,4,0,ownerEqual,3,0);Link(self,4,0,ownerEqual,3,1);Link(ownerEqual,4,0,ownerBranch,3,0);
        Link(created,2,0,ownerBranch,1,0);Link(ownerBranch,2,0,timer,1,0);Link(self,4,0,timer,3,0);
        Set(timer,1,B("MfLKK0bLIju"),AuditTimerName);Set(timer,2,B("CHHKK434xan"),false);
        // Use the native list's element definition, not a guessed scalar enum.
        var timerDef=resources.First(r=>r.Kind==6 && r.Id==79 && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        var sequenceConfig=((IEnumerable)timerDef.Model).Cast<object>().Single(p=>Convert.ToInt32(Field(Stored(p,B("quGKmYyTPnA"))!,B("TqBK5Pk3Cw2")))==3 && (int)Field(Stored(p,B("quGKmYyTPnA"))!,B("hWTK5MSRidQ"))==3);
        var wrapper=sequenceConfig.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(sequenceConfig,null)!;
        var sequenceDef=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        var elementDef=sequenceDef.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(sequenceDef,null)!;
        var sequence=Value(timer,3);
        var element=sequence.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(sequence,new object?[]{elementDef,null})!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!.Invoke(element,new object?[]{1f,null});
        Link(tick,4,2,nameEqual,3,0);Set(nameEqual,1,B("MfLKK0bLIju"),AuditTimerName);
        Link(nameEqual,4,0,timerBranch,3,0);Link(tick,2,0,timerBranch,1,0);
        Link(timerBranch,2,0,header,1,0);Link(header,2,0,count,1,0);
        Set(query,0,B("LhkKKbraAbs"),20001875u);
        Link(query,4,0,length,3,0);Link(length,4,0,convert,3,0);Link(convert,4,0,count,3,0);
        Set(header,0,B("MfLKK0bLIju"),AuditMarker);
        return new {ok=true,status="audit-authored-unbound-export-required",graphId=graph.Id,nodeCount=GraphNodes(graph.Model).Count,
            measures="global prefab count, not course-owned count",runtimeVerified=false};
    }
    public object ExportAuditGraph(string directory)
    {
        var graph=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==AuditGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        return ExportResource(graph,directory);
    }
    public object BindAuditGraph()
    {
        var resources=Resources();
        foreach(var requirement in new[]{(CalibrationGraphName,7),(TiledRouteName,39)})
        {
            var graph=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==requirement.Item1)
                .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
            if(GraphNodes(graph.Model).Count!=requirement.Item2 || !entityModels.Any(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u && EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)))
                throw new InvalidOperationException("BOUND_COURSE_REQUIRED_FOR_AUDIT");
        }
        return BindOwnGraph(AuditGraphName,null,13);
    }
}
