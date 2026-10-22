using System;
using System.Collections;
using System.Collections.Generic;

namespace Miliastra.EditorBridge;

// Bounded sample of the structured log records the editor receives, ACROSS ALL GRAPHS.
//
// Why this exists: CapturePositionPrint (PositionLogs.cs:15-32) reads every structured record
// but keeps only the ones whose graph name equals the one hardcoded PositionGraphName. A live
// session scanned 83 records from 5 packets with zero malformed and retained NONE of them,
// because none came from that graph. debug.events needs the run's node logs generally, not one
// graph's position prints, so this captures a bounded sample of whatever arrives.
//
// Deliberately weak claims:
//   * The record shape is read through the same field names PositionLogs already uses, so this
//     adds no new binding assumptions.
//   * The body is reported as a TYPE NAME plus, only when the type is the one known text
//     carrier, its string. Anything else is reported as opaque.
//   * runtimeSemanticsVerified stays false. A captured row proves a record was received and
//     what graph it names; it does NOT prove what the record means or that a graph ran now.
internal sealed partial class EditorAdapter
{
    const int RunLogSampleLimit = 64;
    readonly List<object> runLogSample = new();
    int runLogRecordsSeen;
    int runLogRecordsWithNoName;
    bool runLogSampleLimited;

    static string[] RunLogNameFields() =>
        new[] { B("evca2Fc2YBM"), B("Dsva2frS2bQ"), B("IZYa2chZI6A") };
    static string RunLogBodyField => B("vqqa2GmktMW");
    static string RunLogTextBodyType => B("L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB");
    static string RunLogTextField => B("wmmat7vdE8l");

    // Called from the same place CapturePositionPrint is. Never throws: a shape this reader
    // does not understand is counted, not fatal.
    void CaptureRunLogRecord(object record)
    {
        runLogRecordsSeen++;
        string? name = null;
        object? body = null;
        try
        {
            var type = record.GetType();
            foreach (var field in RunLogNameFields())
            {
                if (type.GetField(field, Fields)?.GetValue(record) is string value && value.Length != 0)
                {
                    name = value;
                    break;
                }
            }
            body = type.GetField(RunLogBodyField, Fields)?.GetValue(record);
        }
        catch (Exception) { return; }
        if (name == null) { runLogRecordsWithNoName++; return; }
        if (runLogSample.Count >= RunLogSampleLimit) { runLogSampleLimited = true; return; }
        string bodyType = body?.GetType().FullName ?? "null";
        string? text = null;
        bool textReadable = false;
        if (body != null && bodyType == RunLogTextBodyType)
        {
            try { text = body.GetType().GetField(RunLogTextField, Fields)?.GetValue(body) as string; textReadable = true; }
            catch (Exception) { textReadable = false; }
        }
        // The text is truncated rather than filtered: an unexpected string is evidence too,
        // and silently dropping it is the failure mode this project keeps repeating.
        if (text != null && text.Length > 512) text = text.Substring(0, 512) + "...<truncated>";
        runLogSample.Add(new
        {
            observedUtc = DateTime.UtcNow,
            graphName = name,
            bodyType,
            bodyTextReadable = textReadable,
            bodyText = text,
            runtimeSemanticsVerified = false
        });
    }

    object RunLogSampleEvidence() => new
    {
        recordsSeen = runLogRecordsSeen,
        recordsWithNoGraphName = runLogRecordsWithNoName,
        sampleLimit = RunLogSampleLimit,
        sampleLimited = runLogSampleLimited,
        sample = runLogSample.ToArray(),
        scope = "received-structured-log-records-across-all-graphs; name and body type only",
        runtimeSemanticsVerified = false,
        notice = "A captured row proves a record was RECEIVED and which graph it names. "
               + "It does not prove the record's meaning, nor that a graph executed in this session."
    };
}
