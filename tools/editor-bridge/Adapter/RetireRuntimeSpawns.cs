using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    // The two runtime spawn graphs stay bound to the level entity, so at play time they still
    // re-create platforms that are now baked into the saved static level (six platforms, GIL 34
    // static entities confirmed in editor). Retiring removes only their first execution link
    // (event 实体创建时 OUTPUT_FLOW -> branch INPUT_FLOW) with the native link-graph disconnect.
    // Graph definitions, every node and value, both node counts, the position graph and all
    // static entities are left untouched. This is a fixed single attempt; no retry, no catch.
    const uint RetireCalibrationGraphId=1073741825u;
    const uint RetireTiledRouteGraphId=1073741826u;
    // Position monitoring is optional while constructing a new static course.
    const int RetireCalibrationGraphNodes=7;
    const int RetireTiledRouteGraphNodes=39;
    const int RetirePositionGraphNodes=16;
    const uint RetireEventDefinitionId=71u;
    const uint RetireBranchDefinitionId=2u;
    bool retireAttempted;

    public object RetireRuntimeSpawns()
    {
        if(retireAttempted)throw new InvalidOperationException("RETIRE_ALREADY_ATTEMPTED");
        var resources=Resources();
        var calibration=resources.Where(r=>r.Kind==9 && r.Id==RetireCalibrationGraphId &&
            (Stored(r.Model,B("c1pKbESgr8S")) as string)==CalibrationGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(calibration.Length!=1)throw new InvalidOperationException("CALIBRATION_GRAPH_IDENTITY_NOT_UNIQUE");
        var tiled=resources.Where(r=>r.Kind==9 && r.Id==RetireTiledRouteGraphId &&
            (Stored(r.Model,B("c1pKbESgr8S")) as string)==TiledRouteName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(tiled.Length!=1)throw new InvalidOperationException("TILED_ROUTE_GRAPH_IDENTITY_NOT_UNIQUE");
        var position=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==PositionGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(position.Length>1)throw new InvalidOperationException("POSITION_GRAPH_IDENTITY_NOT_UNIQUE");
        if(position.Length==1 && GraphNodes(position[0].Model).Count!=RetirePositionGraphNodes)
            throw new InvalidOperationException("POSITION_GRAPH_STATE_MISMATCH");
        var targets=new[]{calibration[0],tiled[0]};
        var expectedNodes=new[]{RetireCalibrationGraphNodes,RetireTiledRouteGraphNodes};
        for(int i=0;i<targets.Length;i++)
            if(GraphNodes(targets[i].Model).Count!=expectedNodes[i])
                throw new InvalidOperationException("SPAWN_GRAPH_STATE_MISMATCH");
        // Read-only: resolve the native link map, rebuild each first execution link from the
        // verified event/branch nodes and confirm the map currently holds it. Every check runs
        // before the first write, so an unexpected shape aborts with the graphs untouched.
        var maps=new object[targets.Length];
        var links=new object[targets.Length];
        var present=new bool[targets.Length];
        for(int i=0;i<targets.Length;i++)
        {
            links[i]=ExecutionLink(targets[i].Model);
            maps[i]=LinkMap(targets[i].Model);
            present[i]=HasLink(maps[i],links[i]);
        }
        retireAttempted=true;
        var results=new List<object>();
        for(int i=0;i<targets.Length;i++)
        {
            var model=targets[i].Model;
            bool disconnected=false;
            if(present[i])
            {
                var disconnect=model.GetType().GetMethods(Fields)
                    .Single(m=>m.Name==B("vJwKOEFj00D") && m.GetParameters().Length==3);
                if(!(bool)disconnect.Invoke(model,new object?[]{links[i],null,false})!)
                    throw new InvalidOperationException("EXECUTION_LINK_DISCONNECT_REJECTED");
                disconnected=true;
            }
            var linkPresentAfter=HasLink(maps[i],links[i]);
            if(linkPresentAfter)throw new InvalidOperationException("EXECUTION_LINK_STILL_PRESENT");
            if(GraphNodes(model).Count!=expectedNodes[i])throw new InvalidOperationException("NODE_COUNT_CHANGED");
            results.Add(new {graphId=(uint)targets[i].Id,name=Stored(model,B("c1pKbESgr8S")) as string,
                nodeCount=GraphNodes(model).Count,
                status=disconnected?"execution-link-disconnected-readback-verified":"already-disabled",
                linkPresentBefore=present[i],linkPresentAfter});
        }
        return new {ok=true,status="runtime-spawns-retired-readback-only-export-and-game-not-run",
            runtimeSpawnLinkDisabled=true,staticEntitiesTouched=false,positionGraphTouched=false,
            positionGraphNodes=position.Length==1?RetirePositionGraphNodes:0,results};
    }
    // Original export shape of both graphs: node 1 = event definition 71, node 4 = branch
    // definition 2; link is event pin(2,0) OUTPUT_FLOW -> branch pin(1,0) INPUT_FLOW.
    object ExecutionLink(object model)
    {
        var nodes=GraphNodes(model);
        if(!nodes.Contains(1u) || !nodes.Contains(4u))throw new InvalidOperationException("EXECUTION_NODES_MISSING");
        var eventNode=nodes[1u]!;
        var branchNode=nodes[4u]!;
        if((uint)Field(Stored(eventNode,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=RetireEventDefinitionId)
            throw new InvalidOperationException("EVENT_NODE_MISMATCH");
        if((uint)Field(Stored(branchNode,B("tLtKHleyQAZ"))!,B("namiwGPRyPS"))!=RetireBranchDefinitionId)
            throw new InvalidOperationException("BRANCH_NODE_MISMATCH");
        object Address(object node,int kind,int index)
            =>Pin(node,kind,index).GetType().GetMethod(B("SrvK5eKUmbB"),Fields)!.Invoke(Pin(node,kind,index),null)!;
        var ctor=Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"),true)!
            .GetConstructors().Single(c=>c.GetParameters().Length==2);
        return ctor.Invoke(new[]{Address(eventNode,2,0),Address(branchNode,1,0)});
    }
    object LinkMap(object model)
    {
        return model.GetType().GetMethod(B("yKHKOFfNm2M"),Fields)!.Invoke(model,null)
            ?? throw new InvalidOperationException("LINK_MAP_NOT_RESOLVED");
    }
    bool HasLink(object map,object link)
        =>(bool)map.GetType().GetMethod(B("FZXiF0RdqqB"),Fields)!.Invoke(map,new object?[]{link})!;
}
