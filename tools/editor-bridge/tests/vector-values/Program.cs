using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;

// Isolated production-method tests. No BeyondEditor assembly, singleton,
// process, native dispatch, lease, or game data is loaded or touched.
public static class Program
{
    public static int Main(string[] args)
    {
        var type=Assembly.LoadFrom(args[0]).GetType("Miliastra.EditorBridge.EditorAdapter",true)!;
        const BindingFlags F=BindingFlags.Static|BindingFlags.NonPublic;
        var validate=type.GetMethod("ValidateAuthorGraph",F)!;
        var payload=type.GetMethod("AuthorVectorPayload",F)!;
        var execute=type.GetMethod("AuthorRunVectorWrite",F)!;
        int checks=0;
        void Check(bool condition,string label) {if(!condition)throw new Exception(label);checks++;Console.WriteLine("PASS "+label);}
        bool Reject(MethodInfo method,params object[] input) {
            try {method.Invoke(null,input);return false;}
            catch(TargetInvocationException error) when(error.InnerException is InvalidOperationException) {return true;}
        }
        JsonElement P(string text)=>JsonDocument.Parse(text).RootElement.Clone();
        foreach(var bad in new[]{"{}","{\"vector3\":[]}","{\"vector3\":[1,2]}","{\"vector3\":[1,2,3,4]}",
            "{\"vector3\":[true,2,3]}","{\"vector3\":[null,2,3]}","{\"vector3\":[1000000001,2,3]}",
            "{\"vector3\":[1,2,3],\"float\":2}","{\"vector3\":[1,2,3],\"vector3\":[4,5,6]}"})
            Check(Reject(payload,P(bad)),"strict vector payload refusal");
        var xyz=(float[])payload.Invoke(null,new object[]{P("{\"vector3\":[1.125,-2.75,0.1]}")})!;
        Check(xyz.SequenceEqual(new[]{1.125f,-2.75f,0.1f}),"three axes converted once to float32");
        var req=P("{\"id\":\"v1\",\"op\":\"author-graph\",\"action\":\"set-value\",\"name\":\"MW_API_vector\",\"graphId\":1073741900,\"nodeId\":17,\"portKind\":3,\"portIndex\":1,\"expect\":{\"serverParamType\":12,\"genericId\":12},\"slot\":\"vector3\",\"value\":{\"vector3\":[1,2,3]}}");
        Check(!Reject(validate,req),"production single request accepts vector3");
        Check(Reject(validate,P(req.GetRawText().Replace("[1,2,3]","[1,2]"))),"single request rejects shape before dispatch");
        var events=new List<string>(); var state=new float[3];
        Action<int,float> write=(i,n)=>{events.Add("w"+i);state[i]=n;};
        Func<int,float> read=i=>{events.Add("r"+i);return state[i];};
        var seen=(float[])execute.Invoke(null,new object[]{xyz,write,read})!;
        Check(seen.SequenceEqual(xyz) && events.SequenceEqual(new[]{"w0","w1","w2","r0","r1","r2"}),"all production axes written and independently read");
        Check(Reject(execute,xyz,write,(Func<int,float>)(i=>i==2?99:xyz[i])),"Z mismatch cannot report vector success");
        Check(Reject(execute,new[]{0f,0f,-0f},write,(Func<int,float>)(i=>0f)),"negative zero mismatch rejected bit exactly");
        events.Clear();
        Check(Reject(execute,xyz,(Action<int,float>)((i,n)=>{events.Add("w"+i);if(i==1)throw new InvalidOperationException("fixture-error");}),read),"write failure propagated");
        Check(events.SequenceEqual(new[]{"w0","w1"}),"partial write stops without retry or third write");
        var assembly=type.Assembly;
        var buildType=assembly.GetType("Miliastra.EditorBridge.BuildIdentity",true)!;
        var identity=(Dictionary<string,object?>)buildType.GetMethod("Snapshot",F)!.Invoke(null,null)!;
        Check((int)identity["graphVector3Contract"]! == 1,"loaded production assembly declares vector contract");
        Check((string)identity["mvid"]! == assembly.ManifestModule.ModuleVersionId.ToString("D"),"MVID comes from the executing assembly");
        Check((string)identity["name"]! == assembly.GetName().Name,"name comes from the executing assembly");
        Check((string)identity["sha256"]! == Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(args[0]))).ToLowerInvariant(),"loaded identity SHA matches the exact production candidate bytes");
        Check((string)identity["path"]! == Path.GetFullPath(args[0]),"loaded identity records the actual assembly location");
        Console.WriteLine("CHECKS="+checks);return 0;
    }
}
