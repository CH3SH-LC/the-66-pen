using System.IO;
using System.Collections;
using System.Reflection;
using System.Reflection.Emit;
using System.Text.Json;

// These delegates are created and inspected, never invoked. All targets have a tripwire.
if (args.Length != 1) throw new ArgumentException("Supply the isolated, freshly built bridge DLL.");
var bridge = Assembly.LoadFrom(Path.GetFullPath(args[0]));
var verifier = bridge.GetType("Miliastra.EditorBridge.DynamicProxyVerifier", true)!;
var verify = verifier.GetMethod("Verify", BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)!;
var results = new List<object>();
int passed = 0;
MethodInfo target = typeof(Target).GetMethod(nameof(Target.Dispatch))!;

void Check(string name, Delegate proxy, bool wanted, MethodInfo? expected = null)
{
    object result = verify.Invoke(null, new object[] { proxy, expected ?? target })!;
    bool actual = (bool)result.GetType().GetProperty("Verified")!.GetValue(result)!;
    string reason = (string)result.GetType().GetProperty("Reason")!.GetValue(result)!;
    results.Add(new { name, wanted, actual, reason, result });
    if (actual != wanted) throw new Exception(name + ": expected " + wanted + " got " + actual + " / " + reason);
    passed++;
}

Check("instance-object-cast-short-arguments", Make(), true);
Check("instance-object-cast-long-arguments", Make(argForm: 2), true);
Check("instance-object-cast-compact-arguments", Make(argForm: 0), true);
Check("nonvirtual-instance-callvirt", Make(callvirt: true), true);
Check("typed-instance-no-cast", Make(typed: true), true);
var staticTarget = typeof(Target).GetMethod(nameof(Target.StaticDispatch))!;
Check("static-method-forwarder", MakeStatic(staticTarget), true, staticTarget);
var genericTarget = typeof(GenericTarget<string>).GetMethod(nameof(GenericTarget<string>.Dispatch))!;
Check("generic-type-owner-is-outside-bounded-grammar", Make(owner: typeof(GenericTarget<string>), actual: genericTarget), false, genericTarget);

Check("ordinary-delegate-is-not-dynamic", (ClosedProxy)new Target().Dispatch, false);
var multicast = Delegate.Combine(Make(), Make());
Check("multicast-rejected", multicast, false);
Check("closed-target-rejected", Make(closed: true), false);
Check("same-signature-wrong-method", Make(actual: typeof(Target).GetMethod(nameof(Target.Other))!), false);
var otherTarget = typeof(OtherTarget).GetMethod(nameof(OtherTarget.Dispatch))!;
Check("same-name-wrong-declaring-type", Make(owner: typeof(OtherTarget), actual: otherTarget), false);
Check("swapped-string-arguments", Make(order: new[] { 0, 2, 1, 3, 4 }), false);
Check("duplicated-string-argument", Make(order: new[] { 0, 1, 1, 3, 4 }), false);
Check("extra-leading-nop", Make(prefix: il => il.Emit(OpCodes.Nop)), false);
Check("extra-static-field-write", Make(prefix: il => { il.Emit(OpCodes.Ldc_I4_1); il.Emit(OpCodes.Stsfld, typeof(Target).GetField(nameof(Target.Calls))!); }), false);
Check("extra-method-call", Make(prefix: il => il.Emit(OpCodes.Call, typeof(Target).GetMethod(nameof(Target.SideEffect))!)), false);
Check("branch-before-forwarder", Make(prefix: il => { var label = il.DefineLabel(); il.Emit(OpCodes.Br_S, label); il.MarkLabel(label); }), false);
Check("declared-local-rejected", Make(local: true), false);
Check("trailing-instruction-after-ret", Make(trailing: true), false);
Check("unnecessary-cast-rejected", Make(typed: true, forceCast: true), false);
Check("wrong-cast-type-rejected", Make(cast: typeof(DerivedTarget)), false);
Check("covariant-delegate-signature-rejected", Make(objectReturnDelegate: true), false);
var virtualTarget = typeof(Target).GetMethod(nameof(Target.VirtualDispatch))!;
Check("overridable-callvirt-rejected", Make(actual: virtualTarget, callvirt: true), false, virtualTarget);
Check("virtual-direct-call-is-exact", Make(actual: virtualTarget), true, virtualTarget);
var finalTarget = typeof(SealedTarget).GetMethod(nameof(SealedTarget.VirtualDispatch))!;
Check("sealed-callvirt-is-exact", Make(owner: typeof(SealedTarget), actual: finalTarget, callvirt: true), true, finalTarget);

// Deliberately corrupt ONLY newly-created test delegates' resolver snapshots to exercise
// fail-closed malformed/unrecognized inputs. They are never invoked after mutation.
Delegate altered;
altered = Make();
var gmiType = typeof(DynamicMethod).Assembly.GetType("System.Reflection.Emit.GenericMethodInfo", true)!;
Tokens(altered)[CallIndex(altered)] = Activator.CreateInstance(gmiType,
    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null,
    new object[] { target.MethodHandle, typeof(Target).TypeHandle }, null)!;
Check("ordinary-method-with-context-handle-token", altered, true);
altered = Make(); Code(altered)[0] = 0xff;
Check("unknown-opcode-rejected", altered, false);
altered = Make(); Code(altered)[^6] = 0x73;
Check("constructor-opcode-rejected", altered, false);
altered = Make(); Code(altered)[^2] = 0x0a;
Check("unsupported-method-token-prefix", altered, false);
altered = Make(); Array.Fill(Code(altered), (byte)0xff, Code(altered).Length - 5, 3);
Check("out-of-range-call-token", altered, false);
altered = Make(); Code(altered)[0] = 0x0e; Code(altered)[1] = 0xff;
Check("out-of-range-argument-index", altered, false);
altered = Make(); Tokens(altered)[CallIndex(altered)] = "unrecognized token payload";
Check("wrong-token-payload-type", altered, false);
altered = Make(); Tokens(altered)[CallIndex(altered)] = ((DynamicMethod)Make().Method);
Check("nested-dynamic-method-token", altered, false);
altered = Make(); SetResolver(altered, "m_localSignature", new byte[] { 7, 1, 0x0e });
Check("nonzero-locals-signature", altered, false);
altered = Make(); SetResolver(altered, "m_exceptionHeader", new byte[] { 1, 0, 0, 0 });
Check("exception-handler-bytes", altered, false);
altered = Make(); SetResolver(altered, "m_code", new byte[] { 2, 0x74, 1 });
Check("truncated-type-token", altered, false);
altered = Make(); SetResolver(altered, "m_code", new byte[257]);
Check("oversized-il", altered, false);
altered = Make(); Tokens(altered).Clear();
Check("missing-token-scope", altered, false);
var valueTarget = typeof(ValueTarget).GetMethod(nameof(ValueTarget.Dispatch))!;
Check("single-uint-struct-return-call-ret", MakeValue(), true, valueTarget);
Check("single-uint-struct-return-callvirt-ret", MakeValue(callvirt: true), true, valueTarget);
Check("single-uint-struct-return-long-args", MakeValue(longArgs: true), true, valueTarget);
Check("value-return-box-unbox-rejected", MakeValue(boxRoundTrip: true), false, valueTarget);
Check("different-struct-return-rejected", MakeValue(actual: typeof(ValueTarget).GetMethod(nameof(ValueTarget.DifferentReturn))!), false, valueTarget);
var refValueTarget = typeof(ValueTarget).GetMethod(nameof(ValueTarget.RefReturn))!;
Check("byref-struct-return-rejected", MakeValue(actual: refValueTarget), false, refValueTarget);
Check("exact-editor-7.1-int-operand-tailcallvirt-template", MakeObserved(), true, valueTarget);
Check("exact-editor-7.1-explicit-padding-same-il", MakeObserved(padding: 3), true, valueTarget);
Check("editor-template-wrong-receiver-type", MakeObserved(stringReceiver: true), false, valueTarget);
Check("editor-template-other-parameter-erasure", MakeObserved(eraseCallback: true), false, valueTarget);
Check("editor-template-two-nops", MakeObserved(padding: 2), false, valueTarget);
Check("editor-template-four-nops", MakeObserved(padding: 4), false, valueTarget);
Check("editor-template-no-padding", MakeObserved(padding: 0), false, valueTarget);
Check("editor-template-no-tail", MakeObserved(tail: false), false, valueTarget);
Check("editor-template-wrong-target", MakeObserved(actual: typeof(ValueTarget).GetMethod(nameof(ValueTarget.Other))!), false, valueTarget);
altered = MakeObserved(); Code(altered)[11] = 0x28;
Check("editor-template-call-instead-of-callvirt", altered, false, valueTarget);
altered = MakeObserved(); Code(altered)[8] = 0xfe; Code(altered)[9] = 0x14; Code(altered)[10] = 0;
Check("editor-template-tail-in-wrong-position", altered, false, valueTarget);
altered = MakeObserved(); Code(altered)[6] = 0x14;
Check("editor-template-padding-side-effect-opcode", altered, false, valueTarget);
altered = MakeObserved(); Code(altered)[15] = 0x0a;
Check("editor-template-unsupported-token", altered, false, valueTarget);
altered = MakeObserved(); Code(altered)[1] = 4; Code(altered)[2] = 3;
Check("editor-template-reordered-arguments", altered, false, valueTarget);
if (Target.Calls != 0) throw new Exception("Business target was invoked while verifying.");
Console.WriteLine(JsonSerializer.Serialize(new { ok = true, passed, targetInvocations = Target.Calls,
    runtime = Environment.Version.ToString(), bridge = bridge.Location, tests = results }, new JsonSerializerOptions { WriteIndented = true }));

static Delegate Make(bool typed = false, bool closed = false, int argForm = 1,
    bool callvirt = false, Type? owner = null, MethodInfo? actual = null, int[]? order = null,
    Action<ILGenerator>? prefix = null, bool local = false, bool trailing = false,
    bool forceCast = false, Type? cast = null, bool objectReturnDelegate = false)
{
    owner ??= typeof(Target);
    actual ??= typeof(Target).GetMethod(nameof(Target.Dispatch))!;
    Type[] parameters = { typed ? owner : typeof(object), typeof(string), typeof(string), typeof(Action<List<Item>>), typeof(List<Item>) };
    var method = new DynamicMethod("", typeof(Receipt), parameters, typeof(Target).Module, true);
    var il = method.GetILGenerator();
    if (local) il.DeclareLocal(typeof(string));
    prefix?.Invoke(il);
    foreach (int i in order ?? new[] { 0, 1, 2, 3, 4 })
    {
        if (argForm == 2) il.Emit(OpCodes.Ldarg, (short)i);
        else if (argForm == 1 || i > 3) il.Emit(OpCodes.Ldarg_S, (byte)i);
        else il.Emit(new[] { OpCodes.Ldarg_0, OpCodes.Ldarg_1, OpCodes.Ldarg_2, OpCodes.Ldarg_3 }[i]);
        if (i == 0 && (!typed || forceCast)) il.Emit(OpCodes.Castclass, cast ?? owner);
    }
    il.Emit(callvirt ? OpCodes.Callvirt : OpCodes.Call, actual);
    il.Emit(OpCodes.Ret);
    if (trailing) il.Emit(OpCodes.Nop);
    if (closed) return method.CreateDelegate(typeof(ClosedProxy), new Target());
    return method.CreateDelegate(typed ? typeof(TypedProxy) : objectReturnDelegate ? typeof(ObjectReturnProxy) : typeof(ObjectProxy));
}
static Delegate MakeStatic(MethodInfo target)
{
    var method = new DynamicMethod("", typeof(Receipt), target.GetParameters().Select(p => p.ParameterType).ToArray(), typeof(Target).Module, true);
    var il = method.GetILGenerator();
    for (int i = 0; i < 4; i++) il.Emit(OpCodes.Ldarg_S, (byte)i);
    il.Emit(OpCodes.Call, target); il.Emit(OpCodes.Ret);
    return method.CreateDelegate(typeof(ClosedProxy));
}
static Delegate MakeValue(bool callvirt = false, bool longArgs = false, bool boxRoundTrip = false, MethodInfo? actual = null)
{
    actual ??= typeof(ValueTarget).GetMethod(nameof(ValueTarget.Dispatch))!;
    var parameters = new[] { typeof(object), typeof(string), typeof(string), typeof(Action<List<Item>>), typeof(List<Item>) };
    var method = new DynamicMethod("", actual.ReturnType, parameters, typeof(Target).Module, true);
    var il = method.GetILGenerator();
    for (int i = 0; i < 5; i++)
    {
        if (longArgs) il.Emit(OpCodes.Ldarg, (short)i); else il.Emit(OpCodes.Ldarg_S, (byte)i);
        if (i == 0) il.Emit(OpCodes.Castclass, typeof(ValueTarget));
    }
    il.Emit(callvirt ? OpCodes.Callvirt : OpCodes.Call, actual);
    if (boxRoundTrip) { il.Emit(OpCodes.Box, actual.ReturnType); il.Emit(OpCodes.Unbox_Any, actual.ReturnType); }
    il.Emit(OpCodes.Ret);
    return method.CreateDelegate(actual.ReturnType.IsByRef ? typeof(RefValueProxy) :
        actual.ReturnType == typeof(OtherReceipt) ? typeof(OtherValueProxy) : typeof(ValueProxy));
}
static Delegate MakeObserved(int padding = -1, bool stringReceiver = false, bool eraseCallback = false,
    bool tail = true, MethodInfo? actual = null)
{
    actual ??= typeof(ValueTarget).GetMethod(nameof(ValueTarget.Dispatch))!;
    var parameters = new[] { stringReceiver ? typeof(string) : typeof(object), typeof(string), typeof(string),
        eraseCallback ? typeof(object) : typeof(Action<List<Item>>), typeof(List<Item>) };
    var method = new DynamicMethod("", typeof(ValueReceipt), parameters, typeof(ValueTarget), true);
    var il = method.GetILGenerator();
    il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Ldarg_1); il.Emit(OpCodes.Ldarg_2); il.Emit(OpCodes.Ldarg_3);
    // The editor generator uses the int overload; its three extra operand bytes
    // decode as NOPs after the one-byte ldarg.s operand. Preserve that exact shape.
    if (padding < 0) il.Emit(OpCodes.Ldarg_S, 4);
    else { il.Emit(OpCodes.Ldarg_S, (byte)4); for (int i = 0; i < padding; i++) il.Emit(OpCodes.Nop); }
    if (tail) il.Emit(OpCodes.Tailcall);
    il.Emit(OpCodes.Callvirt, actual); il.Emit(OpCodes.Ret);
    return method.CreateDelegate(stringReceiver ? typeof(StringReceiverValueProxy) :
        eraseCallback ? typeof(ErasedCallbackValueProxy) : typeof(ValueProxy));
}
static object Resolver(Delegate proxy) => typeof(DynamicMethod).GetField("_resolver", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(proxy.Method)!;
static byte[] Code(Delegate proxy) => (byte[])Resolver(proxy).GetType().GetField("m_code", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(Resolver(proxy))!;
static IList Tokens(Delegate proxy)
{
    var resolver = Resolver(proxy);
    var scope = resolver.GetType().GetField("m_scope", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(resolver)!;
    return (IList)scope.GetType().GetField("m_tokens", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(scope)!;
}
static int CallIndex(Delegate proxy) => BitConverter.ToInt32(Code(proxy), Code(proxy).Length - 5) & 0xffffff;
static void SetResolver(Delegate proxy, string name, object value) => Resolver(proxy).GetType().GetField(name, BindingFlags.Instance | BindingFlags.NonPublic)!.SetValue(Resolver(proxy), value);

public sealed class Receipt { }
public sealed class Item { }
public delegate Receipt ObjectProxy(object target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate Receipt TypedProxy(Target target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate object ObjectReturnProxy(object target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate Receipt ClosedProxy(string a, string b, Action<List<Item>> cb, List<Item> items);
public class Target
{
    public static int Calls;
    public Receipt Dispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Calls++; throw new Exception("Target must never run"); }
    public Receipt Other(string a, string b, Action<List<Item>> cb, List<Item> items) { Calls++; throw new Exception("Target must never run"); }
    public virtual Receipt VirtualDispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Calls++; throw new Exception("Target must never run"); }
    public static Receipt StaticDispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Calls++; throw new Exception("Target must never run"); }
    public static void SideEffect() { Calls++; throw new Exception("Side effect must never run"); }
}
public sealed class DerivedTarget : Target { }
public sealed class SealedTarget : Target
{
    public override Receipt VirtualDispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Calls++; throw new Exception("Target must never run"); }
}
public sealed class OtherTarget
{
    public Receipt Dispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
}
public sealed class GenericTarget<T>
{
    public Receipt Dispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
}

// Mirrors the real receipt's one uint instance field. This static initializer is
// another tripwire: metadata inspection must not initialize the value-return type.
public readonly struct ValueReceipt
{
    private readonly uint id;
    public uint Id => id;
    public ValueReceipt(uint value) { id = value; }
    static ValueReceipt() { Target.Calls++; throw new Exception("Value return type initializer must never run"); }
}
public readonly struct OtherReceipt { public readonly uint Id; }
public delegate ValueReceipt ValueProxy(object target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate OtherReceipt OtherValueProxy(object target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate ref ValueReceipt RefValueProxy(object target, string a, string b, Action<List<Item>> cb, List<Item> items);
public sealed class ValueTarget
{
    public ValueReceipt Other(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
    public ValueReceipt Dispatch(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
    public OtherReceipt DifferentReturn(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
    public ref ValueReceipt RefReturn(string a, string b, Action<List<Item>> cb, List<Item> items) { Target.Calls++; throw new Exception("Target must never run"); }
}

public delegate ValueReceipt StringReceiverValueProxy(string target, string a, string b, Action<List<Item>> cb, List<Item> items);
public delegate ValueReceipt ErasedCallbackValueProxy(object target, string a, string b, object cb, List<Item> items);
