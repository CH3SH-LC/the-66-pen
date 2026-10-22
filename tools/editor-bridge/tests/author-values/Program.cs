using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

// Load only our isolated compiled bridge. Never load BeyondEditor or call AuthorGraph:
// shape validation and the production batch loop need no editor resources.
public static class Program
{
    public static int Main(string[] args)
    {
        var type=Assembly.LoadFrom(args[0]).GetType("Miliastra.EditorBridge.EditorAdapter",true)!;
        const BindingFlags F=BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic;
        var validate=type.GetMethod("ValidateAuthorGraph",F)!;
        var execute=type.GetMethod("AuthorRunValueBatch",F)!;
        var checks=0;
        void Check(bool condition,string label) { if(!condition) throw new Exception(label); checks++; Console.WriteLine("PASS "+label); }
        object Item(uint id=8001)=>new {nodeId=id,definitionId=22,portKind=3,portIndex=1,
            expect=new {serverParamType=6,genericId=6},slot="string",value=new { @string="MW_SEED_BEFORE" }};
        JsonElement Request(object[] values)=>JsonSerializer.SerializeToElement(new {id="batch-1",op="author-graph",
            action="set-values",name="MW_API_test",graphId=1073741836,expectedNodeCount=93,values});
        bool Reject(JsonElement request) {
            try {validate.Invoke(null,new object[]{request}); return false;}
            catch(TargetInvocationException ex) when(ex.InnerException is InvalidOperationException) {return true;}
        }
        Check(!Reject(Request(Enumerable.Range(0,32).Select(i=>Item((uint)(8001+i))).ToArray())),"32 native IDs accepted");
        Check(Reject(Request(Array.Empty<object>())),"empty batch rejected");
        Check(Reject(Request(Enumerable.Range(0,33).Select(i=>Item((uint)(8001+i))).ToArray())),"33 values rejected");
        Check(Reject(Request(new[]{Item(),Item()})),"duplicate pin rejected before any model read");
        string baseJson=Request(new[]{Item()}).GetRawText();
        foreach(var mutation in new[]{
            baseJson.Replace("\"definitionId\":22","\"definitionId\":0"),
            baseJson.Replace("\"nodeId\":8001","\"nodeId\":8001,\"nodeId\":9000"),
            baseJson.Replace("\"portKind\":3","\"portKind\":4"),
            baseJson.Replace("\"portIndex\":1","\"portIndex\":2147483648"),
            baseJson.Replace("\"genericId\":6","\"genericId\":6,\"extra\":0"),
            baseJson.Replace("\"expectedNodeCount\":93","\"expectedNodeCount\":0"),
            baseJson.Replace("\"slot\":\"string\"","\"slot\":\"guess\"")})
            Check(Reject(JsonDocument.Parse(mutation).RootElement),"closed batch shape refuses malformed input");
        var events=new List<string>();
        JsonElement Run(Action<int> preflight,Action begin,Func<int,object> write)=>JsonSerializer.SerializeToElement(
            execute.Invoke(null,new object[]{1073741836u,3,preflight,begin,write}));
        var success=Run(i=>events.Add("p"+i),()=>events.Add("begin"),i=>{events.Add("w"+i);return new{index=i,readback=10};});
        Check(success.GetProperty("ok").GetBoolean() && events.SequenceEqual(new[]{"p0","p1","p2","begin","w0","w1","w2"}),"all preflight precedes first write and each value written once");
        Check(success.GetProperty("completedIndices").EnumerateArray().Select(x=>x.GetInt32()).SequenceEqual(new[]{0,1,2}),"success has actual completed indices");
        events.Clear();
        var refused=Run(i=>{events.Add("p"+i);if(i==2)throw new InvalidOperationException("TYPE_MISMATCH");},()=>events.Add("begin"),i=>{events.Add("w"+i);return i;});
        Check(!refused.GetProperty("ok").GetBoolean() && !refused.GetProperty("outcomeUncertain").GetBoolean() && events.SequenceEqual(new[]{"p0","p1","p2"}),"later preflight failure writes nothing and consumes no claim");
        Check(refused.GetProperty("failedIndex").GetInt32()==2 && refused.GetProperty("completedIndices").GetArrayLength()==0,"preflight failure index exact");
        events.Clear();
        var partial=Run(i=>{},()=>{},i=>{events.Add("w"+i);if(i==1)throw new InvalidOperationException("READBACK_MISMATCH");return new{index=i,readback=7};});
        Check(!partial.GetProperty("ok").GetBoolean() && partial.GetProperty("outcomeUncertain").GetBoolean() && !partial.GetProperty("retryAttempted").GetBoolean(),"partial failure uncertain and never retried");
        Check(events.SequenceEqual(new[]{"w0","w1"}) && partial.GetProperty("failedIndex").GetInt32()==1 && partial.GetProperty("completedIndices").GetRawText()=="[0]", "partial stop does not write subsequent item or claim failed item completed");
        var replay=Run(i=>{},()=>throw new InvalidOperationException("AUTHOR_MUTATION_ALREADY_ATTEMPTED"),i=>throw new Exception("MUST_NOT_WRITE"));
        Check(!replay.GetProperty("outcomeUncertain").GetBoolean() && replay.GetProperty("completedIndices").GetArrayLength()==0,"spent batch rejected before writes");
        Console.WriteLine("CHECKS="+checks);return 0;
    }
}
