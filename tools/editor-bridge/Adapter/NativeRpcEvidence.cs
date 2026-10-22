using System;

namespace Miliastra.EditorBridge;

// Read-only capture of the native reply message for our debug-log RPC request.
// Source evidence: .runtime/editor-bridge/control-research/rpc-response-proto.cs
// declares U8hGWcazKO84hvpc042G.rMyEXuazimvWHMFk7awm with private uint rrlazLEZM8f
// (public accessor DtMazsQwg5b) and private bool y9iazq3HFOv (accessor xyyaz8uwdMa);
// rpc-receipt.cs shows reply ids are allocated from 1 with 0 meaning "unset"
// (pD9YMQi0ZT7ZULgeNBHv.hLmi0G2qn6e), so only a nonzero request id is matchable.
//
// Scope limit: this partial only reads fields off an already-delivered payload.
// It never sends, never invokes a property accessor, never logs the raw payload,
// and never throws on the reply flag -- the flag value itself is the evidence.
internal sealed partial class EditorAdapter
{
    static string DebugLogReplyType => B("U8hGWcazKO84hvpc042G.rMyEXuazimvWHMFk7awm");
    static string DebugLogRequestIdField => B("rrlazLEZM8f");
    static string DebugLogSuccessField => B("y9iazq3HFOv");

    // Assigned by the caller that issues the debug-log request. Null or 0 means
    // no request is outstanding, so no reply can be attributed to us.
    internal uint? debugLogRequestId;
    internal bool? debugLogRpcSuccess;
    internal DateTime? debugLogRpcReplyUtc;
    internal int debugLogRpcMatchedResponses;

    // Called from the reply observer only. An unmatched payload is ignored silently.
    internal void CaptureDebugLogRpcReply(object? payload)
    {
        if (debugLogRequestId is not uint requestId || requestId == 0u) return;
        if (payload == null || payload.GetType().FullName != DebugLogReplyType) return;
        if (Field(payload, DebugLogRequestIdField) is not uint replyId || replyId != requestId) return;
        debugLogRpcSuccess = Field(payload, DebugLogSuccessField) as bool?;
        debugLogRpcReplyUtc = DateTime.UtcNow;
        debugLogRpcMatchedResponses++;
    }
}
