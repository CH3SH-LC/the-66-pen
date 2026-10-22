using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Course finish graph: polls the active character position every 0.25s and settles
// the level only when the player stands on the goal pad (distance <= 2 from the
// goal centre AND height >= 2.4). The height term is what keeps a player standing
// under the pad, on the lower pad or on the ground from settling the level by
// accident. Same fixed native mechanics as PositionGraph.cs: one native create,
// one Build that mutates the empty unbound graph only, one export, one bind.
internal sealed partial class EditorAdapter
{
    const string FinishGraphName="MW_Course_Finish_20260916";
    const string FinishTimerName="MW_FINISH_POLL_20260916";
    const string FinishMonitorMarker="MW_FINISH_MONITOR_STARTED_20260916";
    const string FinishReachedMarker="MW_FINISH_REACHED_20260916";

    // 2026-10-06: the goal was a magic number buried in Build(). It is now a named
    // constant so "which course does this finish graph settle" is answerable without
    // reading the node wiring. Repointed from the old MVP course pad (17, 2.5, 0) to
    // the top of the 20-layer spiral course in level 1073741841: the summit platform
    // is the entity at (-3.00, 31.30, 3.00) scale (6, 0.5, 6), so its walkable top
    // face is y = 31.55. maxDistance/minHeight semantics are unchanged.
    //
    // This is a DELIBERATE repoint, not a parameterisation: the bridge op carries no
    // argument (BridgeServer.cs dispatches it with none) and adding one would also
    // need the runner's closed per-op field table widened. Rebuilding the OLD course's
    // finish graph now needs these three numbers changed back.
    const float FinishGoalX=-3f, FinishGoalY=31.55f, FinishGoalZ=3f;
    const float FinishMaxDistance=2f, FinishMinHeight=31.0f;

    bool finishBuildAttempted;
    public object CreateFinishGraph()
    {
        if(Spent("create",FinishGraphName) || Resources().Any(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==FinishGraphName))
            throw new InvalidOperationException("FINISH_CREATE_ALREADY_PRESENT_OR_ATTEMPTED");
        var manager=ExistingSingleton(Editor(),B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method=manager.GetType().GetMethod(B("yBnirE4YONq"),Fields)!;
        Spend("create",FinishGraphName);
        method.Invoke(manager,new object?[]{Enum.ToObject(method.GetParameters()[0].ParameterType,20000),FinishGraphName,0u,null});
        return new {ok=true,name=FinishGraphName,status="finish-created-unbound"};
    }
    public object BuildFinishGraph()
    {
        if(finishBuildAttempted)throw new InvalidOperationException("FINISH_BUILD_ALREADY_ATTEMPTED");
        var resources=Resources();
        var graph=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==FinishGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        if(GraphNodes(graph.Model).Count!=0)throw new InvalidOperationException("FINISH_NOT_EMPTY");
        if(entityModels.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)))throw new InvalidOperationException("FINISH_MUST_BE_UNBOUND");
        finishBuildAttempted=true;
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
                throw new InvalidOperationException("FINISH_LINK_REJECTED:"+fk+":"+fi+"->"+tk+":"+ti);
        }
        object Value(object n,int i){var p=Pin(n,3,i);var w=p.GetType().GetProperty("value")!.GetValue(p)!;return w.GetType().GetProperty("Value")!.GetValue(w)!;}
        void Set(object n,int i,string method,object data){var v=Value(n,i);if(v.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(v,null)!.ToString()=="Generics")v=v.GetType().GetMethod(B("eUgKKLsg3Lw"),Fields)!.Invoke(v,null)!;v.GetType().GetMethod(method,Fields)!.Invoke(v,new object?[]{data,null});}
        // Order is 1-based in the contract below and maps to a 5-wide layout grid.
        var created=Add(71,0);var self=Add(73,1);var ownerEqual=Add(14,2);var ownerBranch=Add(2,3);
        var startPrint=Add(1,4);var timer=Add(79,5);var tick=Add(83,6);var nameEqual=Add(14,7);
        // 2026-10-06: node 804 (获取指定玩家的前台角色) is REMOVED. The official node catalogue
        // annotates it "仅经典模式可用" -- CLASSIC MODE ONLY -- and level 1073741841 is 超限模式,
        // which is exactly what the editor refused at save/upload: 「经典模式无法设置这个」 naming
        // this graph's id. Node selection was not otherwise at fault: every other definition here
        // is a strict prefix of the proven 29-node MVP course graph, which uploads fine.
        //
        // The chain was  列表迭代循环 -> 804(取前台角色) -> 99(取位置)
        // and is now     列表迭代循环 ->              99(取位置)
        // i.e. the PLAYER entity's own position, which IS the character's position in 超限模式
        // (the player plays 奇偶). 99/509/248 all carry no mode annotation, so the rebuilt graph
        // contains no mode-restricted node at all. Node count drops 23 -> 22.
        var tickBranch=Add(2,8);var players=Add(248,9);var playerLoop=Add(509,10);
        var position=Add(99,12);var goal=Add(225,13);var distance=Add(244,14);var nearPad=Add(231,15);
        var axis=Add(9,16);var aboveGround=Add(233,17);var both=Add(226,18);var reachBranch=Add(2,19);
        var timerRead=Add(82,20);var reachedPrint=Add(1,21);var settle=Add(77,22);
        // Flow: create -> owner check -> start print, and tick -> poll -> on-pad settle.
        Link(created,2,0,ownerBranch,1,0);Link(ownerBranch,2,0,startPrint,1,0);Link(startPrint,2,0,timer,1,0);
        Link(tick,2,0,tickBranch,1,0);Link(tickBranch,2,0,playerLoop,1,0);
        Link(playerLoop,2,0,reachBranch,1,0);Link(reachBranch,2,0,timerRead,1,0);
        Link(timerRead,2,0,reachedPrint,1,0);Link(reachedPrint,2,0,settle,1,0);
        // Data: owner equality, timer identity, polling and the two-part win test.
        Link(created,4,0,ownerEqual,3,0);Link(self,4,0,ownerEqual,3,1);Link(ownerEqual,4,0,ownerBranch,3,0);
        Link(self,4,0,timer,3,0);
        Set(startPrint,0,B("MfLKK0bLIju"),FinishMonitorMarker);
        Set(timer,1,B("MfLKK0bLIju"),FinishTimerName);Set(timer,2,B("X8oKKHB87Ue"),1u);
        // Repeating 0.25s poll; the same proven native float-list sequence definition
        // used by the position graph, holding a single float instead of a guessed enum.
        var timerDef=resources.First(r=>r.Kind==6 && r.Id==79 && r.Category.SequenceEqual(new uint[]{10001,20000,22000,0}));
        var sequenceConfig=((IEnumerable)timerDef.Model).Cast<object>().Single(p=>Convert.ToInt32(Field(Stored(p,B("quGKmYyTPnA"))!,B("TqBK5Pk3Cw2")))==3 && (int)Field(Stored(p,B("quGKmYyTPnA"))!,B("hWTK5MSRidQ"))==3);
        var wrapper=sequenceConfig.GetType().GetMethod(B("l6uKazVUo9s"),Fields)!.Invoke(sequenceConfig,null)!;
        var sequenceDef=wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        var elementDef=sequenceDef.GetType().GetMethod(B("Ov2K7oYGvHi"),Fields)!.Invoke(sequenceDef,null)!;
        var sequence=Value(timer,3);
        var element=sequence.GetType().GetMethod(B("KRQKKuygfFk"),Fields)!.Invoke(sequence,new object?[]{elementDef,null})!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!.Invoke(element,new object?[]{0.25f,null});
        Link(tick,4,2,nameEqual,3,0);Set(nameEqual,1,B("MfLKK0bLIju"),FinishTimerName);
        Link(nameEqual,4,0,tickBranch,3,0);
        Link(players,4,0,playerLoop,3,0);Link(playerLoop,4,0,position,3,0);
        // Goal centre — see FinishGoalX/Y/Z at the top of this file.
        Set(goal,0,B("SH7KKvk8cxe"),FinishGoalX);Set(goal,1,B("SH7KKvk8cxe"),FinishGoalY);Set(goal,2,B("SH7KKvk8cxe"),FinishGoalZ);
        Link(position,4,0,distance,3,0);Link(goal,4,0,distance,3,1);
        Link(distance,4,0,nearPad,3,0);Set(nearPad,1,B("SH7KKvk8cxe"),FinishMaxDistance);
        Link(position,4,0,axis,3,0);Link(axis,4,1,aboveGround,3,0);Set(aboveGround,1,B("SH7KKvk8cxe"),FinishMinHeight);
        Link(nearPad,4,0,both,3,0);Link(aboveGround,4,0,both,3,1);
        Link(both,4,0,reachBranch,3,0);
        Link(self,4,0,timerRead,3,0);Set(timerRead,1,B("MfLKK0bLIju"),FinishTimerName);
        Set(reachedPrint,0,B("MfLKK0bLIju"),FinishReachedMarker);
        Set(settle,0,B("X8oKKHB87Ue"),1u);
        if(GraphNodes(graph.Model).Count!=22)throw new InvalidOperationException("FINISH_NODE_COUNT_MISMATCH");
        return new {ok=true,status="finish-authored-unbound-export-required",graphId=graph.Id,nodeCount=GraphNodes(graph.Model).Count,
            timer=FinishTimerName,monitorMarker=FinishMonitorMarker,reachedMarker=FinishReachedMarker,
            goal=new[]{(double)FinishGoalX,(double)FinishGoalY,(double)FinishGoalZ},
            maxDistance=(double)FinishMaxDistance,minimumHeight=(double)FinishMinHeight,
            bound=false,runtimeVerified=false};
    }
    // Native enum-backed bool uses cPOKKedklwd(), not RJCKKnWqvLO().
    // Verified by node-instance.cs Pp2KbkDhLfG and finish-bool-slots.json.
    public object RepairFinishBooleans()
    {
        var graph=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==FinishGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        var nodes=GraphNodes(graph.Model);
        if(graph.Id!=1073741828u || nodes.Count!=22 || entityModels.Any(e=>EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==graph.Id)))
            throw new InvalidOperationException("FINISH_REPAIR_REQUIRES_OWN_UNBOUND_GRAPH");
        object Value(uint node,int index){var p=Pin(nodes[node]!,3,index);var w=p.GetType().GetProperty("value")!.GetValue(p)!;return w.GetType().GetProperty("Value")!.GetValue(w)!;}
        // 2026-10-06: the settle node's index moved 23 -> 22 with the removal of node 804 above.
        var values=new[]{Value(6,2),Value(22,0)};
        foreach(var v in values)
            if(Convert.ToInt32(v.GetType().GetMethod(B("KiPKKaQUNLS"),Fields)!.Invoke(v,null))!=6)
                throw new InvalidOperationException("FINISH_REPAIR_EXPECTED_ENUM");
        foreach(var v in values) v.GetType().GetMethod(B("X8oKKHB87Ue"),Fields)!.Invoke(v,new object?[]{1u,null});
        var readback=values.Select(v=>{var w=v.GetType().GetMethod(B("cPOKKedklwd"),Fields)!.Invoke(v,null)!;return (uint)w.GetType().GetProperty("Value")!.GetValue(w)!;}).ToArray();
        if(readback.Any(v=>v!=1u))throw new InvalidOperationException("FINISH_BOOL_READBACK_MISMATCH");
        return new{ok=true,status="finish-enum-booleans-repaired-unbound",graphId=graph.Id,readback,runtimeVerified=false};
    }
    public object ExportFinishGraph(string directory)
    {
        var graph=Resources().Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==FinishGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
        return ExportResource(graph,directory);
    }
    public object BindFinishGraph()
    {
        var resources=Resources();
        // 2026-10-06: the three-graph requirement below is the OLD MVP course's prerequisite,
        // not a general one. It is kept VERBATIM when that course is present (if any of the
        // three graphs exists, all three must exist, carry their exact node counts and be
        // bound to the level entity). A DIFFERENT course -- none of the three exists at all --
        // is not the old course and must not be forced to carry its graphs. What still has to
        // hold in that case is that the level entity is present and the finish graph itself is
        // ready, which is checked immediately below either way.
        //
        // Recorded plainly: this REPLACES an unconditional gate with a conditional one, so a
        // caller who deletes those three graphs can now bind without them. That is the
        // deliberate trade for settling a second course, and it is why the waiver is stated
        // here rather than left to be inferred from the diff.
        var legacyGraphNames=new[]{CalibrationGraphName,TiledRouteName,PositionGraphName};
        var legacyPresent=resources.Any(r=>r.Kind==9 && Stored(r.Model,B("c1pKbESgr8S")) is string n && Array.IndexOf(legacyGraphNames,n)>=0);
        if(legacyPresent)
        {
            foreach(var requirement in new[]{(CalibrationGraphName,7),(TiledRouteName,39),(PositionGraphName,16)})
            {
                var bound=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==requirement.Item1)
                    .GroupBy(r=>r.Id).Select(g=>g.First()).Single();
                if(GraphNodes(bound.Model).Count!=requirement.Item2 || !entityModels.Any(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u && EntityBindings(e).Any(k=>(uint)Field(k,B("namiwGPRyPS"))==bound.Id)))
                    throw new InvalidOperationException("BOUND_COURSE_REQUIRED_FOR_FINISH");
            }
        }
        else if(!entityModels.Any(e=>(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS"))==1094713345u))
        {
            throw new InvalidOperationException("FINISH_LEVEL_ENTITY_REQUIRED");
        }
        var matches=resources.Where(r=>r.Kind==9 && (Stored(r.Model,B("c1pKbESgr8S")) as string)==FinishGraphName)
            .GroupBy(r=>r.Id).Select(g=>g.First()).ToArray();
        if(matches.Length!=1 || GraphNodes(matches[0].Model).Count!=22)throw new InvalidOperationException("FINISH_GRAPH_NOT_READY");
        return BindOwnGraph(FinishGraphName,null,22);
    }

    // 2026-10-06: DELETE, by name, for the finish graph only.
    //
    // Needed because the graph built before this date contains node 804
    // (获取指定玩家的前台角色), which the official catalogue annotates 仅经典模式可用, and level
    // 1073741841 is 超限模式 -- so the editor refuses the level at save/upload and names this
    // graph's id. The graph has to be REPLACED by the mode-neutral build below, and there is no
    // node-removal path through author.py (its GRAPH_ACTIONS carry no delete), while
    // delete-owned-graph-ids cannot see this graph at all: it reports graphModelsVisible=1 but
    // modelMatched=0, i.e. its walk never resolves the model.
    //
    // The reachable set is exactly one graph: the one whose stored name equals FinishGraphName,
    // required to be UNIQUE, and required to be UNBOUND (a bound graph is refused rather than
    // deleted -- unbind-finish-graph exists for that, so the two steps stay separable).
    //
    // Same native call OwnedGraphDelete already uses (resource -> zgVKB6OS1MZ()), preceded by the
    // same re-resolve-and-recheck the sibling does, and followed by an independent read-back.
    // 2026-10-06: strip the one mode-restricted node out of the ALREADY-BUILT finish graph.
    //
    // Why not rebuild: the corrected 22-node build (BuildFinishGraph above) only runs on an EMPTY
    // graph, and there is no path to empty this one -- author.py's GRAPH_ACTIONS carry no node
    // delete, and neither delete-owned-graph-ids nor a resource-node delete reaches a graph that
    // Resources() can see (measured: the WPF walk reports graphModelsVisible=1 but modelMatched=0,
    // and the Resources() object itself does NOT carry zgVKB6OS1MZ -> FINISH_DELETE_NATIVE_METHOD_MISSING).
    //
    // So the node is replaced in place with the same three native calls ClassicTeleportRepair
    // already proved on a graph model: remove (zbUKmIZoGMn), and re-link (LapKOOcuGY1). Nothing is
    // created here -- the graph loses a node and gains one edge.
    //
    // Reachable set: one graph, named FinishGraphName, UNBOUND. The victim must be the definition
    // 804 node and nothing else; every precondition is checked before anything is invoked, and the
    // result is read back.
    public object StripFinishClassicNode()
    {
        var resources = Resources();
        var matches = resources.Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == FinishGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (matches.Length != 1) throw new InvalidOperationException("FINISH_STRIP_LOOKUP:expected=1:actual=" + matches.Length);
        var graph = matches[0];
        if (entityModels.Any(e => EntityBindings(e).Any(k => (uint)Field(k, B("namiwGPRyPS")) == graph.Id)))
            throw new InvalidOperationException("FINISH_STRIP_REFUSES_A_BOUND_GRAPH");

        uint Def(object n) => (uint)Field(Stored(n, B("tLtKHleyQAZ"))!, B("namiwGPRyPS"));
        var nodes = GraphNodes(graph.Model);
        if (nodes.Count != 23) throw new InvalidOperationException("FINISH_STRIP_REQUIRES_23_NODES:actual=" + nodes.Count);
        // GraphNodes returns the NON-generic IDictionary, so LINQ needs an explicit Cast.
        var byDef = nodes.Values.Cast<object>().GroupBy(n => Def(n)).ToDictionary(g => g.Key, g => g.ToArray());
        if (!byDef.TryGetValue(804u, out var victims) || victims.Length != 1)
            throw new InvalidOperationException("FINISH_STRIP_VICTIM_804_NOT_UNIQUE");
        if (!byDef.TryGetValue(509u, out var loops) || loops.Length != 1)
            throw new InvalidOperationException("FINISH_STRIP_LOOP_509_NOT_UNIQUE");
        if (!byDef.TryGetValue(99u, out var positions) || positions.Length != 1)
            throw new InvalidOperationException("FINISH_STRIP_POSITION_99_NOT_UNIQUE");
        uint victimId = 0;
        foreach (DictionaryEntry kv in nodes)
            if (ReferenceEquals(kv.Value, victims[0])) victimId = (uint)kv.Key;
        if (victimId == 0) throw new InvalidOperationException("FINISH_STRIP_VICTIM_ID_UNRESOLVED");

        // Remove the mode-restricted node.
        if (!(bool)graph.Model.GetType().GetMethod(B("zbUKmIZoGMn"), Fields)!
                .Invoke(graph.Model, new object?[] { victimId, null, false, false, false })!)
            throw new InvalidOperationException("FINISH_STRIP_DELETE_REJECTED");

        // Loop output -> position input, the edge the removed node used to carry.
        object Address(object n, int k, int i) => Pin(n, k, i).GetType().GetMethod(B("SrvK5eKUmbB"), Fields)!.Invoke(Pin(n, k, i), null)!;
        var ctor = Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"), true)!.GetConstructors().Single(c => c.GetParameters().Length == 2);
        var link = ctor.Invoke(new[] { Address(loops[0], 4, 0), Address(positions[0], 3, 0) });
        if (!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(graph.Model, new object?[] { link, null, -1 })!)
            throw new InvalidOperationException("FINISH_STRIP_RELINK_REJECTED");

        var after = GraphNodes(graph.Model);
        var defsAfter = after.Values.Cast<object>().Select(Def).ToArray();
        var ok = after.Count == 22 && !defsAfter.Contains(804u) && defsAfter.Count(d => d == 509u) == 1 && defsAfter.Count(d => d == 99u) == 1;
        return new
        {
            ok,
            status = ok ? "finish-classic-node-stripped" : "finish-strip-readback-mismatch",
            graphId = graph.Id, removedNodeId = victimId, removedDefinition = 804u,
            nodeCountAfter = after.Count, definitionsAfter = defsAfter.OrderBy(d => d).ToArray(),
            persistentSaveVerified = false
        };
    }

    // 2026-10-06: added because the finish graph could be BOUND and not un-bound. The sibling
    // GameLoopGraph has had UnbindGameLoopGraph since the start; the finish graph never got
    // one, so a binding this adapter created could not be taken back by this adapter -- the
    // only remaining routes were delete-owned-graph-ids (which refuses this graph: it reports
    // graphModelsVisible=1 but modelMatched=0, i.e. its walk never resolves the finish graph
    // model) or the user's hands in the editor.
    //
    // Same three steps as the sibling, and the same safety shape: find the graph by its exact
    // name, require EXACTLY one, find the level entity's binding collection, remove the entry
    // whose bound id is this graph's, then READ THE COLLECTION BACK and refuse if the id is
    // still there. The graph itself is left in place -- this removes a binding, never data --
    // so the operation is reversible by calling bind-finish-graph again.
    public object UnbindFinishGraph()
    {
        var resources = Resources();
        var byId = resources.Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var matches = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == FinishGraphName).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("FINISH_UNBIND_LOOKUP:expected=1:actual=" + matches.Length);
        var graph = matches[0];
        var entity = entityModels.FirstOrDefault(e => (uint)Field(Stored(e, B("Qi8iCzKCkTt"))!, B("namiwGPRyPS")) == 1094713345u)
            ?? throw new InvalidOperationException("FINISH_UNBIND_LEVEL_ENTITY_NOT_FOUND");

        var collection = entity.GetType().GetMethod(B("t6ViSxlgnQ3"), Fields)!.Invoke(entity, null)
            ?? throw new InvalidOperationException("FINISH_UNBIND_COLLECTION_MISSING");
        var inner = Field(collection, B("VAfiNjPuW4e"))
            ?? throw new InvalidOperationException("FINISH_UNBIND_INNER_LIST_MISSING");
        var entries = ((IEnumerable)inner).Cast<object>().ToArray();

        var index = -1;
        for (var i = 0; i < entries.Length; i++)
        {
            var boundId = (uint)Field(entries[i], B("namiwGPRyPS"));
            if (boundId == graph.Id) { index = i; break; }
        }
        if (index < 0)
            return new { ok = true, status = "finish-not-bound-nothing-to-do", graphId = graph.Id, bindingCount = entries.Length };

        var remove = collection.GetType().GetMethod(B("lUBiNLoXRl5"), Fields)
            ?? throw new InvalidOperationException("FINISH_UNBIND_REMOVE_METHOD_MISSING");
        remove.Invoke(collection, new object?[] { index, true });

        var remaining = ((IEnumerable)Field(collection, B("VAfiNjPuW4e"))!).Cast<object>()
            .Select(k => (uint)Field(k, B("namiwGPRyPS"))).OrderBy(x => x).ToArray();
        if (remaining.Contains(graph.Id))
            throw new InvalidOperationException("FINISH_UNBIND_DID_NOT_TAKE");
        return new
        {
            ok = true,
            status = "finish-unbound",
            graphId = graph.Id,
            removedIndex = index,
            bindingCountBefore = entries.Length,
            remainingBindingIds = remaining,
            graphStillExists = true,
            reversible = true,
            persistentSaveVerified = false
        };
    }
}
