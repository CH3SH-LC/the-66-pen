using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// The command channel -- Producer.Ikci0qkvMZX(service, command, callback, params) --
// is the largest interface surface this project has recovered but never exercised.
// 23 command names across 13 channels were read off the decompiler; none has ever
// been sent, and the survey records "the server-side semantics, side effects and
// idempotency of the commands are entirely unverified".
//
// This probe closes the FIRST half of that gap without touching the second.
//
// WHAT IT SENDS, EXACTLY
//   One dispatch per channel, carrying a command name that cannot exist:
//
//       __miliastra_probe_unknown_command__
//
//   plus one dispatch on a service name that cannot exist. No recovered command name
//   -- not DoExport, not DeleteEditObj, not PlayMusic -- is ever placed in a request
//   by this code. That is deliberate: a server cannot act on a command it does not
//   recognise, so the probe can establish whether the dispatch path reaches the
//   server, what a rejection looks like, and whether a receipt comes back, while
//   being unable to cause an effect. Answering "does this path work at all" before
//   sending anything real is the whole point.
//
// WHAT IT DOES NOT DO
//   It does not send a known command. It does not send parameters (null, as
//   ImportAllDebugLog does). It does not register a callback. It does not retry.
//
// The receipt's request-id field is read with the same name RequestDebugLogs uses
// (dJVi0tPDg6E); a null receipt is reported as such rather than thrown, because
// "no receipt" is itself one of the answers being sought.
internal sealed partial class EditorAdapter
{
    const string ProbeUnknownCommand = "__miliastra_probe_unknown_command__";
    const string ProbeUnknownService = "__miliastra_probe_unknown_service__";

    // Every channel name the selector slots return, in slot order, deduplicated.
    //
    // Every slot is examined, not just the ones whose target is the dispatcher. The
    // channel names do NOT live in the dispatch slot: that slot's value is the
    // dispatcher itself. They are the values of other slots whose targets are
    // zero-argument static methods returning string. The shape test below is what
    // selects them, which is exactly how VerifyChannels finds the same 13 names.
    List<string> ResolveChannelNames()
    {
        var asm = Editor();
        var names = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        foreach (var slot in VerifySlots)
        {
            var owner = asm.GetType(slot.Owner, false);
            var fi = owner?.GetField(slot.Field, Statics);
            if (fi?.GetValue(null) is not Delegate del) continue;
            var m = del.Method;
            if (!m.IsStatic || m.GetParameters().Length != 0 || m.ReturnType != typeof(string)) continue;
            string? value;
            try { value = m.Invoke(null, null) as string; }
            catch { continue; }
            if (string.IsNullOrEmpty(value)) continue;
            if (seen.Add(value!)) names.Add(value!);
        }
        return names;
    }

    readonly record struct SendOutcome(bool Threw, string? Error, bool ReceiptPresent, uint? RequestId);

    SendOutcome DispatchOnce(MethodInfo dispatch, object producer, string service, string command)
    {
        object? receipt = null;
        string? error = null;
        uint? requestId = null;
        try
        {
            // null callback, null parameter list: the sparest dispatch the signature allows.
            receipt = dispatch.Invoke(producer, new object?[] { service, command, null, null });
            if (receipt != null)
            {
                var idField = receipt.GetType().GetField(B("dJVi0tPDg6E"), Fields);
                if (idField?.GetValue(receipt) is uint id) requestId = id;
            }
        }
        catch (TargetInvocationException tie) when (tie.InnerException != null)
        {
            error = tie.InnerException.GetType().Name + ": " + tie.InnerException.Message;
        }
        catch (Exception ex)
        {
            error = ex.GetType().Name + ": " + ex.Message;
        }
        return new SendOutcome(error != null, error, receipt != null, requestId);
    }

    public object CommandProbe()
    {
        var producer = ExistingSingleton(Editor(), Producer);
        var dispatch = producer.GetType().GetMethod(B("Ikci0qkvMZX"), Fields)
            ?? throw new InvalidOperationException("COMMAND_PROBE_DISPATCH_METHOD_MISSING");

        var channels = ResolveChannelNames();

        // One probe per channel, then one against a service that does not exist, so a
        // "channel not found" rejection can be told apart from a "command not found" one.
        var targets = channels.Select(c => (Service: c, Command: ProbeUnknownCommand)).ToList();
        if (channels.Count > 0)
            targets.Add((ProbeUnknownService, ProbeUnknownCommand));

        var probes = targets.Select(t =>
        {
            var outcome = DispatchOnce(dispatch, producer, t.Service, t.Command);
            return new
            {
                service = t.Service,
                command = t.Command,
                threw = outcome.Threw,
                error = outcome.Error,
                receiptPresent = outcome.ReceiptPresent,
                receiptRequestId = outcome.RequestId
            };
        }).ToList();

        int threw = probes.Count(p => p.threw);
        int receipted = probes.Count(p => p.receiptPresent);

        return new
        {
            ok = true,
            status = "command-probe-dispatched-unknown-names-only",
            probeCommandName = ProbeUnknownCommand,
            probeServiceName = ProbeUnknownService,
            scope = "sent only command/service names that cannot exist; no recovered command name was ever " +
                    "placed in a request; no parameters; no callback; nothing retried",
            channelCount = channels.Count,
            probeCount = probes.Count,
            threwCount = threw,
            receiptCount = receipted,
            channels,
            probes,
            knownCommandsSent = 0,
            persistentSaveVerified = false,
            playtestVerified = false
        };
    }
}
