using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
namespace ReopenContentTests;
public class Node {public Node? Next; public byte[] Bytes=Enumerable.Range(0,1024).Select(i=>(byte)i).ToArray(); public string Text=new('x',1024); public long Large=long.MaxValue; public float Float=float.NaN; public int Getter=>throw new Exception("GETTER_CALLED");}
public class BadEnumerable:IEnumerable {public IEnumerator GetEnumerator()=>throw new Exception("ENUMERATOR_CALLED");}
public class WithDelegate {public Action Callback=()=>throw new Exception("DELEGATE_CALLED");}
public static class Program {
 public static int Main(string[] args){
  var assembly=Assembly.LoadFrom(args[0]); var type=assembly.GetType("Miliastra.EditorBridge.EditorAdapter+ContentFieldReader",true)!;
  const BindingFlags F=BindingFlags.Instance|BindingFlags.Public|BindingFlags.NonPublic;
  object Reader()=>Activator.CreateInstance(type,F,null,new object?[]{typeof(Node).Assembly,null},null)!;
  JsonElement Read(object r,object v)=>JsonSerializer.SerializeToElement(type.GetMethod("Read",F)!.Invoke(r,new[]{v}));
  JsonElement Summary(object r)=>JsonSerializer.SerializeToElement(type.GetMethod("Summary",F)!.Invoke(r,null));
  int checks=0; void Check(bool ok,string name){checks++;if(!ok)throw new Exception(name);Console.WriteLine("PASS "+name);}
  var node=new Node();node.Next=node;var reader=Reader();
  var budget=type.GetField("budget",F)!.GetValue(reader)!;var clock=(System.Diagnostics.Stopwatch)budget.GetType().GetField("Clock",F)!.GetValue(budget)!;
  Check(!clock.IsRunning && clock.ElapsedTicks==0,"registry discovery does not consume field-read clock");
  var result=Read(reader,node);var json=result.GetRawText();
  Check(clock.IsRunning,"field-read clock starts with first Read");
  Check(Summary(reader).GetProperty("complete").GetBoolean(),"cycle fields read without getters");
  Check(result.GetProperty("objects").GetArrayLength()==1,"self reference has one object");
  Check(result.GetProperty("objects")[0].GetProperty("fields").EnumerateArray().Single(x=>x.GetProperty("name").GetString()=="Bytes").GetProperty("value").GetProperty("base64").GetString()==Convert.ToBase64String(node.Bytes),"all 1024 bytes retained");
  Check(json.Contains(node.Text),"string beyond old 256 limit retained");
  Check(json.Contains(long.MaxValue.ToString()),"int64 exact text retained");
  Check(json.Contains("System.Single")&&json.Contains("bits"),"nonfinite float exact bits retained");
  var bad=Reader();Read(bad,new BadEnumerable());Check(!Summary(bad).GetProperty("complete").GetBoolean(),"unknown enumerable rejected without invocation");
  var del=Reader();Read(del,new WithDelegate());Check(!Summary(del).GetProperty("complete").GetBoolean(),"runtime delegate rejected");
  var tooBig=Reader();Read(tooBig,new int[16385]);Check(Summary(tooBig).GetProperty("truncated").GetBoolean(),"array limit explicit");
  var huge=Reader();Read(huge,new string('z',4194305));Check(Summary(huge).GetProperty("truncated").GetBoolean(),"byte budget explicit");
  var dict=Reader();Read(dict,new Dictionary<uint,List<int>>{{1,new(){2,3}}});Check(Summary(dict).GetProperty("complete").GetBoolean(),"known BCL dictionary and list complete");
  var root=Reader();Read(root,new object());Check(!Summary(root).GetProperty("complete").GetBoolean(),"foreign non-data object rejected");
  var known=Reader();var knownData=Read(known,new h27B3oXlxcN6dvR6aQBi.yudq5KXlmuVpBrR7rVQF());Check(Summary(known).GetProperty("complete").GetBoolean() && knownData.GetRawText().Contains("VerifiedBackingField"),"known node enumerator never invoked; backing field retained");
  var set=Reader();Read(set,new HashSet<int>{4,5});Check(Summary(set).GetProperty("complete").GetBoolean(),"known BCL HashSet stored values complete");
  var shared=Reader();var sharedValue=Read(shared,new Dictionary<string,object>{{"node:1",node},{"graph:1",new List<Node>{node,node}}});Check(Summary(shared).GetProperty("complete").GetBoolean() && sharedValue.GetProperty("objects").GetArrayLength()==3,"aggregate business roots share one reference table without duplicate model copies");
  Console.WriteLine("CHECKS="+checks);return 0;
 }
}
