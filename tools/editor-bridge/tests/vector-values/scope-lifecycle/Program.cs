using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;

// A private, windowless TestHost. Loads the actual production bridge and calls
// its actual Entry/pipe/worker/cleanup. Never injects another process, loads
// BeyondEditor, changes lifecycle fields, or invokes editor adapter operations.
internal static class Program
{
    private const BindingFlags PrivateStatic=BindingFlags.NonPublic|BindingFlags.Static;
    private static Assembly Bridge=null!;
    private static Type Entry=null!;
    private static string Output="", Exe="";
    private static int Pid, Checks;
    private static long StartTicks;
    private static readonly List<object> Events=new();
    private sealed record Scope(string Directory,string Pipe,string Nonce,DateTimeOffset Expires)
    {
        public string Settings=>Path.Combine(Directory,"bridge-settings.json");
    }

    [STAThread]
    private static int Main(string[] args)
    {
        if(args.Length!=3)return 2;
        var root=Path.GetFullPath(Environment.CurrentDirectory);
        Output=Path.GetFullPath(args[1]);
        if(!Output.StartsWith(Path.Combine(root,".runtime","graph-vector-values")+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))return 3;
        Directory.CreateDirectory(Output);
        using(var process=Process.GetCurrentProcess()) {
            Pid=process.Id;StartTicks=process.StartTime.ToUniversalTime().Ticks;
            Exe=Path.GetFullPath(process.MainModule!.FileName!);
        }
        if(Path.GetFileName(Exe)!="TestHost.exe")return 4;
        Bridge=Assembly.LoadFrom(Path.GetFullPath(args[0]));
        Entry=Bridge.GetType("Miliastra.EditorBridge.Entry",true)!;
        int result=1;
        if(args[2]=="cleanup-failure") {
            try {FailureScenario().GetAwaiter().GetResult();Save(true,null,args[2]);return 0;}
            catch(Exception error){Save(false,error.ToString(),args[2]);return 1;}
        }
        if(args[2]!="clean-renewal" && !new[]{"observer-active","observer-partial","observer-failed"}.Contains(args[2]))return 5;
        var application=new Application {ShutdownMode=ShutdownMode.OnExplicitShutdown};
        _=Task.Run(async()=> {
            try {
                if(args[2]=="clean-renewal")await SuccessScenario(application);
                else await ObserverFaultScenario(application,args[2]);
                Save(true,null,args[2]);result=0;
            }
            catch(Exception error){Save(false,error.ToString(),args[2]);}
            finally {_ = application.Dispatcher.BeginInvoke(new Action(application.Shutdown));}
        });
        application.Run(); // No Window is created or shown.
        return result;
    }

    private static void Check(bool condition,string name)
    {
        if(!condition)throw new InvalidOperationException(name);
        Checks++; Events.Add(new {name,ok=true,recordedUtc=DateTimeOffset.UtcNow});
        Console.WriteLine("PASS "+name);
    }
    private static void Save(bool ok,string? error,string scenario)
    {
        var snapshot=Bridge.GetType("Miliastra.EditorBridge.BuildIdentity",true)!.GetMethod("Snapshot",PrivateStatic)!.Invoke(null,null);
        var report=new {ok,error,scenario,checks=Checks,pid=Pid,startUtcTicks=StartTicks.ToString(CultureInfo.InvariantCulture),
            executable=Exe,bridgeAssembly=snapshot,events=Events,
            scopeRoot=Path.Combine(Output,".runtime","editor-bridge","runs"),
            beyondEditorLoaded=BeyondLoaded(),gameAccessed=false,desktopOperated=false,
            privateHostLifecycleOnly=true,observerOwnedStateFaultInjected=scenario.StartsWith("observer-"),
            framework=System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,runtimeGameplayVerified=false};
        File.WriteAllText(Path.Combine(Output,"result.json"),JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}),new UTF8Encoding(false));
        Console.WriteLine("CHECKS="+Checks+" OK="+ok);
    }
    private static bool BeyondLoaded()=>AppDomain.CurrentDomain.GetAssemblies().Any(a=>(a.GetName().Name??"").StartsWith("BeyondEditor",StringComparison.OrdinalIgnoreCase));
    private static Scope NewScope(double seconds=15,string? nonce=null,string? pipe=null)
    {
        var scope=new Scope(Path.Combine(Output,".runtime","editor-bridge","runs",Guid.NewGuid().ToString("D")),
            pipe??("vector-lifecycle-"+Guid.NewGuid().ToString("N")),
            nonce??Convert.ToHexString(RandomNumberGenerator.GetBytes(32)),DateTimeOffset.UtcNow.AddSeconds(seconds));
        Directory.CreateDirectory(scope.Directory);WriteSettings(scope);return scope;
    }
    private static void WriteSettings(Scope scope)=>File.WriteAllText(scope.Settings,JsonSerializer.Serialize(new {
        pid=Pid,startUtcTicks=StartTicks.ToString(CultureInfo.InvariantCulture),nonce=scope.Nonce,pipeName=scope.Pipe,
        expiresUtc=scope.Expires.ToString("O"),expectedExe=Exe}),new UTF8Encoding(false));
    private static int Start(Scope scope)=>(int)Entry.GetMethod("Start")!.Invoke(null,new object[]{scope.Settings})!;
    private static bool Completed()
    {
        var worker=Entry.GetField("_server",PrivateStatic)!.GetValue(null)!;
        return (bool)worker.GetType().GetProperty("IsCompleted",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(worker)!;
    }
    private static async Task<JsonElement> Call(Scope scope,string operation,string? nonce=null)
    {
        using var pipe=new NamedPipeClientStream(".",scope.Pipe,PipeDirection.InOut,PipeOptions.Asynchronous);
        await pipe.ConnectAsync(3000);
        using var writer=new StreamWriter(pipe,new UTF8Encoding(false),1024,true){AutoFlush=true};
        using var reader=new StreamReader(pipe,new UTF8Encoding(false),false,1024,true);
        await writer.WriteLineAsync(JsonSerializer.Serialize(new {id=Guid.NewGuid().ToString("D"),op=operation,nonce=nonce??scope.Nonce}));
        var line=await reader.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(3));
        return JsonDocument.Parse(line??throw new IOException("empty reply")).RootElement.Clone();
    }
    private static async Task<JsonElement> Closed(Scope scope,bool clean)
    {
        var path=Path.Combine(scope.Directory,"lease-closed.json");
        var until=DateTime.UtcNow.AddSeconds(8);
        while(DateTime.UtcNow<until) {
            if(File.Exists(path)) {
                try {
                    var closed=JsonDocument.Parse(File.ReadAllText(path)).RootElement.Clone();
                    if(!clean || Completed())return closed;
                } catch(IOException) {} catch(JsonException) {}
            }
            await Task.Delay(20);
        }
        throw new TimeoutException("private worker did not publish expected closure/completion");
    }
    private static void AssertClosed(JsonElement closed,bool clean,string label)
    {
        Check(closed.GetProperty("pid").GetInt32()==Pid,label+" closure belongs to private host");
        Check(closed.GetProperty("cleanupSucceeded").GetBoolean()==clean,label+" cleanup result is explicit");
        Check(!closed.GetProperty("hostProcessTerminated").GetBoolean(),label+" did not terminate host");
        Check(Completed()==clean,label+" native IsCompleted matches cleanup result");
        if(clean)Check(closed.GetProperty("cleanupEvidence").GetProperty("observer").GetProperty("cleanupNoOp").GetBoolean(),label+" unused observer used explicit empty-state cleanup");
    }
    private static async Task AssertPing(Scope scope,string label)
    {
        var ping=await Call(scope,"ping");
        Check(ping.GetProperty("ok").GetBoolean() && ping.GetProperty("pid").GetInt32()==Pid,label+" actual pipe ping identity");
        Check(!ping.GetProperty("beyondEditorAssemblyLoaded").GetBoolean(),label+" no editor assembly loaded");
        Check(ping.GetProperty("bridgeAssembly").GetProperty("mvid").GetString()==Bridge.ManifestModule.ModuleVersionId.ToString("D"),label+" actual executing revision unchanged");
    }
    private static async Task SuccessScenario(Application app)
    {
        Check(!BeyondLoaded(),"private host starts without editor assemblies");
        Check((int)Entry.GetMethod("Start")!.Invoke(null,new object[]{""})! == 2,"invalid settings rejected before a worker");
        var first=NewScope();
        Check(Start(first)==0,"valid scope accepted after rejected Start resets guard");
        await AssertPing(first,"first");
        var second=NewScope();
        Check(Start(second)==1,"active worker rejects overlapping fresh scope");
        Check(!File.Exists(Path.Combine(second.Directory,"bridge-ready.json")),"active rejection did not claim fresh scope");
        using(var releaseDispatcher=new ManualResetEventSlim(false)) {
            var entered=new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            _ = app.Dispatcher.BeginInvoke(new Action(()=>{entered.SetResult(true);releaseDispatcher.Wait(TimeSpan.FromSeconds(6));}));
            await entered.Task;
            try {
                var stop=await Call(first,"stop");
                Check(stop.GetProperty("stopped").GetBoolean() && !stop.GetProperty("cleanupComplete").GetBoolean(),"stop reply does not claim completed cleanup");
                Check(Start(second)==1,"stopped listener cannot renew before dispatcher cleanup");
                Check(!Completed(),"native completion stays false while cleanup is queued");
            } finally {releaseDispatcher.Set();}
        }
        AssertClosed(await Closed(first,true),true,"stop");
        Check(Start(first)==10,"accepted settings path cannot be reused after clean closure");
        Check(Start(NewScope(nonce:first.Nonce))==10,"accepted nonce cannot be reused at a new path");
        Check(Start(NewScope(pipe:first.Pipe))==10,"accepted pipe cannot be reused with a new nonce");
        // This path/nonce was rejected while busy, never accepted or reserved.
        // Shorten only this unaccepted fixture's deadline to exercise real expiry.
        second=second with {Expires=DateTimeOffset.UtcNow.AddSeconds(2)};WriteSettings(second);
        Check(Start(second)==0,"same loaded revision accepts a fresh scope after clean completion");
        await AssertPing(second,"second");
        var bad=await Call(second,"ping",first.Nonce);
        Check(!bad.GetProperty("ok").GetBoolean() && bad.GetProperty("error").GetString()=="nonce_mismatch","old nonce cannot authenticate new scope");
        AssertClosed(await Closed(second,true),true,"natural expiry");
        var third=NewScope();
        Check(Start(third)==0,"natural expiry permits another clean same-revision scope");
        await AssertPing(third,"third");
        await Call(third,"stop");
        AssertClosed(await Closed(third,true),true,"final stop");
        Check(!BeyondLoaded(),"no editor assembly was loaded during private lifecycle");
    }
    private static async Task FailureScenario()
    {
        Check(Application.Current==null,"failure fixture has no dispatcher");
        var scope=NewScope(2);
        Check(Start(scope)==0,"private worker can begin before cleanup dependency is tested");
        AssertClosed(await Closed(scope,false),false,"failed cleanup");
        Check(Start(NewScope())==1,"cleanup failure blocks same-revision renewal");
        Check(!BeyondLoaded(),"failed cleanup test never loads editor assembly");
    }

    private static async Task ObserverFaultScenario(Application app,string scenario)
    {
        var scope=NewScope(2);
        Check(Start(scope)==0,"private worker accepted before owned-state fault injection");
        // Negative fault injection only in this newly created private host.
        // Do not modify Entry/worker completion flags or fabricate a success.
        // The actual production cleanup and worker must refuse these states.
        await app.Dispatcher.InvokeAsync(()=>{
            var worker=Entry.GetField("_server",PrivateStatic)!.GetValue(null)!;
            var adapter=worker.GetType().GetField("_adapter",BindingFlags.NonPublic|BindingFlags.Instance)!.GetValue(worker)!;
            var name=scenario=="observer-active"?"observerActive":scenario=="observer-partial"?"initPacketType":"observerCleanupError";
            object value=scenario=="observer-active"?true:scenario=="observer-partial"?typeof(object):"private-fixture-existing-cleanup-failure";
            adapter.GetType().GetField(name,BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(adapter,value);
        }).Task;
        AssertClosed(await Closed(scope,false),false,scenario);
        Check(Start(NewScope())==1,"owned observer state failure was not converted to renewable success");
        Check(!BeyondLoaded(),"owned-state fault test never loads editor assembly");
    }
}
