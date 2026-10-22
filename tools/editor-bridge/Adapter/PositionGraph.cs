using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    const string PositionGraphName="MW_Character_Position_20260916";
    const string PositionTimerName="MW_POSITION_ONESHOT_20260916";
    const string PositionMarker="MW_CHARACTER_POSITION_NEXT_20260916";
    bool positionBuildAttempted;
    public object CreatePositionGraph()
    {
        if(Spent("create",PositionGraphName) || Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==PositionGraphName))
            throw new InvalidOperationException("POSITION_CREATE_ALREADY_PRESENT_OR_ATTEMPTED");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
        Spend("create",PositionGraphName);
        method.Invoke(manager,new object?[]{Enum.ToObject(method.GetParameters()[0].ParameterType,20000),PositionGraphName,0u,null});
        return new {ok=true,name=PositionGraphName,status="position-created-unbound"};
    }
    public object BuildPositionGraph()
    {
        if(positionBuildAttempted)throw new InvalidOperationException("POSITION_BUILD_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==PositionGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        if(GraphNodes(graph.Model).Count!=0)throw new InvalidOperationException("POSITION_NOT_EMPTY");
        if(entityModels.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)))throw new InvalidOperationException("POSITION_MUST_BE_UNBOUND");
        positionBuildAttempted=true;
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
                throw new InvalidOperationException("POSITION_LINK_REJECTED:"+fk+":"+fi+"->"+tk+":"+ti);
        }
        object Value(object n,int i){var p=Pin(n,3,i);var w=p.GetType().GetProperty("value")!.GetValue(p)!;return w.GetType().GetProperty("Value")!.GetValue(w)!;}
        void Set(object n,int i,string method,object data){var v=Value(n,i);if(v.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(v,null)!.ToString()=="Generics")v=v.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(v,null)!;v.GetType().GetMethod(method,Fields)!.Invoke(v,new object?[]{data,null});}
        var created=Add(71,0);var self=Add(73,1);var ownerEqual=Add(14,2);var ownerBranch=Add(2,3);
        var timer=Add(79,4);var tick=Add(83,5);var nameEqual=Add(14,6);var tickBranch=Add(2,7);
        var players=Add(248,8);var playerLoop=Add(509,9);var roles=Add(258,10);var roleLoop=Add(509,11);
        var position=Add(99,12);var convert=Add(180,13);var markerPrint=Add(1,14);var print=Add(1,15);
        Link(created,4,0,ownerEqual,3,0);Link(self,4,0,ownerEqual,3,1);Link(ownerEqual,4,0,ownerBranch,3,0);
        Link(created,2,0,ownerBranch,1,0);Link(ownerBranch,2,0,timer,1,0);Link(self,4,0,timer,3,0);
        Set(timer,1,B("MfLKK0bLIju"),PositionTimerName);Set(timer,2,B("CHHKK434xan"),false);
        // One-shot timer keeps the native float-list sequence definition used by the
        // audit graph; the list holds a single float 3f rather than a guessed enum.
        var timerDef=resources.First(r=>r.Kind==6 && r.Id==79 && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        var sequenceConfig=((IEnumerable)timerDef.Model).Cast<object>().Single(p=>Convert.ToInt32(Field(Stored(p,B("quGKmYyTPnA"))!,B("TqBK5Pk3Cw2")))==3 && (int)Field(Stored(p,B("quGKmYyTPnA"))!,B("hWTK5MSRidQ"))==3);
        var wrapper=sequenceConfig.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(sequenceConfig,null)!;
        var sequenceDef=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        var elementDef=sequenceDef.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(sequenceDef,null)!;
        var sequence=Value(timer,3);
        var element=sequence.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(sequence,new object?[]{elementDef,null})!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!.Invoke(element,new object?[]{3f,null});
        Link(tick,4,2,nameEqual,3,0);Set(nameEqual,1,B("MfLKK0bLIju"),PositionTimerName);
        Link(nameEqual,4,0,tickBranch,3,0);Link(tick,2,0,tickBranch,1,0);
        Link(tickBranch,2,0,playerLoop,1,0);
        Link(players,4,0,playerLoop,3,0);Link(playerLoop,4,0,roles,3,0);Link(roles,4,0,roleLoop,3,0);
        Link(playerLoop,2,0,roleLoop,1,0);
        Link(roleLoop,4,0,position,3,0);Link(position,4,0,convert,3,0);Link(convert,4,0,print,3,0);
        Link(roleLoop,2,0,markerPrint,1,0);Link(markerPrint,2,0,print,1,0);
        Set(markerPrint,0,B("MfLKK0bLIju"),PositionMarker);
        if(GraphNodes(graph.Model).Count!=16)throw new InvalidOperationException("POSITION_NODE_COUNT_MISMATCH");
        return new {ok=true,status="position-authored-unbound-export-required",graphId=graph.Id,nodeCount=GraphNodes(graph.Model).Count,
            timer=PositionTimerName,marker=PositionMarker,bound=false,runtimeVerified=false};
    }
    public object ExportPositionGraph(string directory)
    {
        var graph=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==PositionGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        return ExportResource(graph,directory);
    }
    public object BindPositionGraph()
    {
        var resources=Resources();
        foreach(var requirement in new[]{(CalibrationGraphName,7),(TiledRouteName,39)})
        {
            var bound=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==requirement.Item1)
                .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
            if(GraphNodes(bound.Model).Count!=requirement.Item2 || !entityModels.Any(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u && EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==bound.Id)))
                throw new InvalidOperationException("BOUND_COURSE_REQUIRED_FOR_POSITION");
        }
        var matches=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==PositionGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(matches.Length!=1 || GraphNodes(matches[0].Model).Count!=16)throw new InvalidOperationException("POSITION_GRAPH_NOT_READY");
        return BindOwnGraph(PositionGraphName,null,16);
    }
}
