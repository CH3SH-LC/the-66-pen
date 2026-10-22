using System;
using System.Collections.Generic;
using System.Windows.Threading;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    readonly List<DispatcherTimer> leaseTimers=new();
    readonly List<(object Transport,object Receipt)> exportReceipts=new();
    internal DateTime ExportQuiescenceUtc=>exportObservationUntilUtc;
    // A scope which never created any observer-owned state has nothing to
    // unregister. Do not build the unrelated full observer evidence snapshot:
    // it resolves native packet types even in an otherwise empty private host.
    // Any partial setup, prior activity, receipt, timer or failure keeps the
    // original StopLogObserver path (and its failure semantics) intact.
    bool LeaseObserverUnused() =>
        packetObserver==null && observerProducer==null && originalReceivers.Length==0 &&
        observerTimer==null && !observerActive && observerCleanupError==null && observerLeaseSeconds==25 &&
        observerStartedMoment==null && observerRegisteredMoment==null && observerStoppedMoment==null && observerStopReason==null &&
        observedPackets==0 && observedLogPackets==0 && observerScanObjects==0 && !observerScanLimited &&
        observedPacketKinds.Count==0 && observedMarkers.Count==0 && scenePacketSnapshots.Count==0 &&
        debugLogReceipt==null && debugLogReply==null && debugLogReplyUtc==null && debugLogRequestId==null &&
        debugLogRpcSuccess==null && debugLogRpcReplyUtc==null && debugLogRpcMatchedResponses==0 && !logEnableAttempted &&
        !initObservationStarted && initAssembly==null && initPacketType==null && initPayloadType==null && initHeaderType==null &&
        initKindField==null && initBodyField==null && initHeaderField==null && initIdField==null && initCacheField==null &&
        initManager==null && initBaselinePayload==null && initProducer==null && initReceiversAtStart.Length==0 &&
        initCleanupReceiversBefore==null && initCleanupDeferredBefore==null && initObservationId==null && initStartedUtc==null &&
        initStartedTick==0 && initSequence==0 && initDroppedEvents==0 && initParseErrors==0 && initEvidenceErrors==0 &&
        initThreadErrors==0 && !initSequenceOverflow && initBaselineLevelId==null && initReceipts.Count==0;

    object CleanupObserverForLease()
    {
        RequireInitDispatcher();
        if(!LeaseObserverUnused())return StopLogObserver("bridge-lease-cleanup");
        return new {ok=true,active=false,observerRegistered=false,originalReceiversPreserved=true,
            cleanupNoOp=true,reason="no-observer-owned-state-created",nativeObserverCalls=0,
            evidenceScope="empty-owned-state-only",runtimeVerified=false};
    }

    internal object CleanupForLease()
    {
        var errors=new List<Exception>();
        try{RestoreFinishMinimalDiagnostic();}catch(Exception ex){errors.Add(ex);}
        try{RestoreFinishSettlementDiagnostic();}catch(Exception ex){errors.Add(ex);}
        var timerCount=leaseTimers.Count;
        foreach(var timer in leaseTimers)timer.Stop();
        leaseTimers.Clear();
        object? observer=null;
        try{observer=CleanupObserverForLease();}catch(Exception ex){errors.Add(ex);}
        var receiptCount=exportReceipts.Count;
        foreach(var item in exportReceipts)
        {
            try{item.Transport.GetType().GetMethod(B("MSgi0zbjIEA"),Fields)!.Invoke(item.Transport,new[]{item.Receipt});}
            catch(Exception ex){errors.Add(ex);}
        }
        exportReceipts.Clear();
        if(errors.Count>0)throw new AggregateException("LEASE_CLEANUP_INCOMPLETE",errors);
        return new {timersStopped=timerCount,exportReceiptsRemoved=receiptCount,observer};
    }
}
