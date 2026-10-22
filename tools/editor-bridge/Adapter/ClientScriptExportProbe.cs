using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Windows.Threading;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    public object ExportClientScriptProbe(string outputDirectory)
    {
        var (probe, rows, _) = CheckClientScriptProbe();
        if (!probe.CreateSpent || probe.DeleteSpent || probe.Target is not ClientScriptRow target ||
            rows.Count != 1 || target.Id == 0 || rows[0].Id != target.Id ||
            !ReferenceEquals(rows[0].Model, target.Model) ||
            !StringComparer.Ordinal.Equals(rows[0].Name, probe.Name) ||
            !StringComparer.Ordinal.Equals(rows[0].Path, probe.Name + ".lua"))
            throw new InvalidOperationException("CLIENT_SCRIPT_EXPORT_PROBE_NOT_OWNED");
        if (attemptedExports.Contains(target.Id) || attemptedExports.Count >= 2)
            throw new InvalidOperationException("CLIENT_SCRIPT_EXPORT_DUPLICATE_OR_LEASE_LIMIT");
        if (DateTime.UtcNow < exportObservationUntilUtc)
            throw new InvalidOperationException("PREVIOUS_EXPORT_OBSERVATION_PENDING");

        if (string.IsNullOrWhiteSpace(outputDirectory))
            throw new ArgumentException("OUTPUT_DIRECTORY_REQUIRED", nameof(outputDirectory));
        var directory = Path.GetFullPath(outputDirectory);
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, "client-script-" + Guid.NewGuid().ToString("N") + ".gia");
        if (File.Exists(path)) throw new IOException("OUTPUT_EXISTS");
        var replyPath = path + ".reply.json";

        if (File.Exists(replyPath)) throw new IOException("REPLY_OUTPUT_EXISTS");

        var assembly = Editor();
        var producer = ExistingSingleton(assembly, Producer);
        var paramType = assembly.GetType(Param, true)!;
        var list = (System.Collections.IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(paramType))!;
        object Wrap(string method, object value) => paramType.GetMethod(method, BindingFlags.Static | BindingFlags.Public)!
            .Invoke(null, new[] { value })!;
        list.Add(Wrap(B("bKliA0tj1p1"), target.Id));
        list.Add(Wrap(B("wNLiAK8Wcix"), path));

        var capture = new ExportReplyCapture(replyPath);
        var callbackType = typeof(Action<>).MakeGenericType(typeof(List<>).MakeGenericType(paramType));
        var callback = typeof(ExportReplyCapture).GetMethod(nameof(ExportReplyCapture.Receive), BindingFlags.Public | BindingFlags.Instance)!
            .MakeGenericMethod(paramType).CreateDelegate(callbackType, capture);
        attemptedExports.Add(target.Id);
        exportObservationUntilUtc = DateTime.UtcNow.AddSeconds(30);
        var receipt = producer.GetType().GetMethod(B("Ikci0qkvMZX"), Fields)!
            .Invoke(producer, new object?[] { "beyondExportService", "DoExportClientScript", callback, list });

        var transport = Field(producer, B("xu7i0pEkGOC"));
        if (receipt != null) exportReceipts.Add((transport, receipt));
        var cleanup = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
        cleanup.Tick += (_, _) =>
        {
            cleanup.Stop();
            try
            {
                if (receipt != null)
                    transport.GetType().GetMethod(B("MSgi0zbjIEA"), Fields)!.Invoke(transport, new[] { receipt });
                if (receipt != null) exportReceipts.RemoveAll(item => ReferenceEquals(item.Receipt, receipt));
            }
            catch (Exception ex) { BridgeLog.Write("client-script export callback cleanup failed: " + ex.GetType().Name); }
        };
        leaseTimers.Add(cleanup);
        cleanup.Start();
        var receiptFields = receipt?.GetType().GetFields(Fields)
            .Where(field => field.FieldType.IsPrimitive).ToDictionary(field => field.Name, field => field.GetValue(receipt));
        return new
        {
            ok = true,
            status = "invoked-not-confirmed",
            id = target.Id,
            path,
            replyPath,
            receiptFields,
            callbackWindowSeconds = 30
        };
    }
}




