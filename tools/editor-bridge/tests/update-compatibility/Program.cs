using System.IO;
using System.Collections;
using System.Reflection;
using System.Reflection.Emit;
using System.Text.Json;

public static class ProbeCounter
{
    public static int Calls;
    public static string? EmptyMethod;
    public static string? ThrowMethod;
    public static string Read(string method)
    {
        Calls++;
        if (method == ThrowMethod) throw new InvalidOperationException("fixture exception");
        return method == EmptyMethod ? "" : "fixture:" + method;
    }
    public static string Wrong() { Calls++; throw new Exception("wrong target must never execute"); }
}

public static class Program
{
    static int checks;
    static void Check(bool value, string name) { if (!value) throw new Exception("FAILED:" + name); checks++; }
    static JsonElement Invoke(object adapter, Type type, string method) =>
        JsonSerializer.SerializeToElement(type.GetMethod(method)!.Invoke(adapter, null));
    public static int Main(string[] args)
    {
        var bridge = Assembly.LoadFrom(Path.GetFullPath(args[0]));
        var type = bridge.GetType("Miliastra.EditorBridge.EditorAdapter", true)!;
        var adapter = Activator.CreateInstance(type, true)!;
        // This is a fabricated in-memory assembly. No game/editor binary is loaded.
        var fake = AssemblyBuilder.DefineDynamicAssembly(new AssemblyName("BeyondEditor"), AssemblyBuilderAccess.Run);
        var module = fake.DefineDynamicModule("OfflineFixture");
        var empty = Invoke(adapter, type, "VerifyChannels");
        Check(!empty.GetProperty("ok").GetBoolean(), "zero selectors cannot pass");
        Check(empty.GetProperty("counts").GetProperty("invoked").GetInt32() == 0, "zero actual invocations");
        var slots = ((IEnumerable)type.GetField("VerifySlots", BindingFlags.NonPublic|BindingFlags.Static)!.GetValue(null)!)
            .Cast<object>().Select(s => new {
                Owner = (string)s.GetType().GetProperty("Owner")!.GetValue(s)!,
                Field = (string)s.GetType().GetProperty("Field")!.GetValue(s)!,
                Target = (string)s.GetType().GetProperty("TargetType")!.GetValue(s)!,
                Method = (string)s.GetType().GetProperty("TargetMethod")!.GetValue(s)!
            }).ToArray();
        var required = new HashSet<string> { "YSDhqo1YVyx","BsxLvIOuJMp","cN5hqlJY835","Is6hqU640RJ",
            "Cg3LuDiYIgD","JxZLSauoPXi","boGLyQBJv9p","wtRlSp6GrvH","P9plSZjW9OJ","KJZlSrdSUL1",
            "TnxlzlI8Hk0","Oerlz9Jdbnf","VdghK1XTDpm" };
        var builders = slots.SelectMany(s=>new[]{s.Owner,s.Target}).Distinct()
            .ToDictionary(n=>n,n=>module.DefineType(n,TypeAttributes.Public|TypeAttributes.Class));
        foreach(var item in slots.Select(s=>(s.Target,s.Method)).Distinct())
        {
            var method=builders[item.Target].DefineMethod(item.Method,MethodAttributes.Public|MethodAttributes.Static,typeof(string),Type.EmptyTypes);
            var il=method.GetILGenerator();il.Emit(OpCodes.Ldstr,item.Method);
            il.Emit(OpCodes.Call,typeof(ProbeCounter).GetMethod(nameof(ProbeCounter.Read))!);il.Emit(OpCodes.Ret);
        }
        foreach(var s in slots) builders[s.Owner].DefineField(s.Field,typeof(Delegate),FieldAttributes.Public|FieldAttributes.Static);
        var created=builders.ToDictionary(p=>p.Key,p=>p.Value.CreateType()!);
        foreach(var s in slots) created[s.Owner].GetField(s.Field)!.SetValue(null,
            created[s.Target].GetMethod(s.Method)!.CreateDelegate(typeof(Func<string>)));
        ProbeCounter.Calls=0;
        var all=Invoke(adapter,type,"VerifyChannels");
        Check(all.GetProperty("ok").GetBoolean(),"complete required selector coverage passes");
        Check(ProbeCounter.Calls==13,"only 13 required readers execute; commands excluded");
        var first=slots.First(s=>required.Contains(s.Field));
        var field=created[first.Owner].GetField(first.Field)!;var original=field.GetValue(null);
        field.SetValue(null,null);ProbeCounter.Calls=0;
        var missing=Invoke(adapter,type,"VerifyChannels");
        Check(!missing.GetProperty("ok").GetBoolean() && ProbeCounter.Calls==12,"one missing required reader fails");
        field.SetValue(null,(Func<string>)ProbeCounter.Wrong);ProbeCounter.Calls=0;
        var wrong=Invoke(adapter,type,"VerifyChannels");
        Check(!wrong.GetProperty("ok").GetBoolean() && ProbeCounter.Calls==12,"wrong target rejected without invocation");
        field.SetValue(null,original);ProbeCounter.EmptyMethod=first.Method;ProbeCounter.Calls=0;
        var emptyValue=Invoke(adapter,type,"VerifyChannels");
        Check(!emptyValue.GetProperty("ok").GetBoolean() && emptyValue.GetProperty("counts").GetProperty("failed").GetInt32()==1,"empty reader value fails");
        ProbeCounter.EmptyMethod=null;ProbeCounter.ThrowMethod=first.Method;
        var thrown=Invoke(adapter,type,"VerifyChannels");
        Check(!thrown.GetProperty("ok").GetBoolean() && thrown.GetProperty("counts").GetProperty("failed").GetInt32()==1,"throwing reader fails");
        ProbeCounter.ThrowMethod=null;
        var interfaces=Invoke(adapter,type,"VerifyInterfaces");
        Check(interfaces.GetProperty("counts").GetProperty("matched").GetInt32()==slots.Length,"fixture has all named delegate matches");
        Check(!interfaces.GetProperty("ok").GetBoolean(),"all slot matches cannot hide missing producer registry or required types");
        Check(interfaces.GetProperty("counts").GetProperty("requiredTypesMissing").GetInt32()>0,"missing required types reported");
        Check(!interfaces.GetProperty("producer").GetProperty("resolved").GetBoolean(),"missing producer reported");
        Console.WriteLine(JsonSerializer.Serialize(new{ok=true,checks,scope="actual compiled Adapter with fabricated in-memory assembly; no game or user process contact"}));
        return 0;
    }
}