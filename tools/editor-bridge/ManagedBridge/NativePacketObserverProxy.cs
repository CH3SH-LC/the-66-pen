using System;
using System.Reflection;
using System.Diagnostics;
using System.Threading;

namespace Miliastra.EditorBridge;

// Configured with the current, verified one-method packet-sink contract before registration.
// Never throw into the editor's existing receiver loop.
public class NativePacketObserverProxy : DispatchProxy
{
    // Actual proxy entry, including rejected or already-detached callbacks. Not a 1022 receipt.
    public sealed record CallbackMoment(DateTime utc, long tick);
    CallbackMoment? lastCallbackMoment;
    public CallbackMoment? LastCallbackMoment => Volatile.Read(ref lastCallbackMoment);
    MethodInfo? callbackMethod;
    Type? packetType;
    public Action<object>? Receive { get; set; }
    public int CallbackErrors { get; private set; }
    public int ContractRejectedCallbacks { get; private set; }
    public int CallbackInvocations { get; private set; }
    public void Configure(MethodInfo method)
    {
        if (callbackMethod != null) throw new InvalidOperationException("OBSERVER_CONTRACT_ALREADY_CONFIGURED");
        if (method == null) throw new ArgumentNullException(nameof(method));
        var owner = method.DeclaringType;
        var parameters = method.GetParameters();
        if (owner?.IsInterface != true || owner.ContainsGenericParameters ||
            owner.GetMethods().Length != 1 || !owner.GetMethods()[0].Equals(method) ||
            method.IsStatic || method.ContainsGenericParameters || method.ReturnType != typeof(void) ||
            parameters.Length != 1 || !parameters[0].ParameterType.IsClass ||
            parameters[0].IsOut || parameters[0].ParameterType.IsByRef)
            throw new InvalidOperationException("OBSERVER_CALLBACK_CONTRACT_INVALID");
        callbackMethod = method;
        packetType = parameters[0].ParameterType;
    }
    protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
    {
        try
        {
            Volatile.Write(ref lastCallbackMoment, new CallbackMoment(DateTime.UtcNow, Stopwatch.GetTimestamp()));
            if (callbackMethod == null || !callbackMethod.Equals(targetMethod) ||
                args?.Length != 1 || args[0] == null || !packetType!.IsInstanceOfType(args[0]))
            {
                ContractRejectedCallbacks++;
                CallbackErrors++;
                return null;
            }
            CallbackInvocations++;
            Receive?.Invoke(args[0]!);
        }
        catch { CallbackErrors++; }
        return null;
    }
}
