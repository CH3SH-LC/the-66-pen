using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Threading;

namespace Miliastra.EditorBridge;

// Passive receipt evidence for the fixed 7.1 initialization packet. No send, replay,
// native call or success assertion. Called only from the existing dispatcher.
internal sealed partial class EditorAdapter
{
    const string InitManagerType = "RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx";
    const string InitPacketType = "Q4bmxBLCduuQZJ26BNvJ.lOecMKLCvJpWqQJhQFma";
    const string InitBodyInterface = "BLvN1YxXA1gALdrCAxg.LOn3vwxLoP3mi8YY1Es";
    const string InitPayloadType = "FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM";
    const string InitHeaderType = "PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw";
    const string InitBuiltinReceiverType = "CMA1XZL6sIiP8kjKPgY4.oXGPPWL64bTmn2CjmWVm";
    const int InitEventLimit = 16;
    sealed record InitPacketReceipt(long sequence, DateTime receivedUtc, long receivedTick,
        int managedThreadId, uint? levelId, bool parsed, string? error);
    readonly List<InitPacketReceipt> initReceipts = new();
    Assembly? initAssembly;
    Type? initPacketType, initPayloadType, initHeaderType;
    FieldInfo? initKindField, initBodyField, initHeaderField, initIdField, initCacheField;
    object? initManager, initBaselinePayload, initProducer;
    object[] initReceiversAtStart = Array.Empty<object>();
    object[]? initCleanupReceiversBefore, initCleanupDeferredBefore;
    bool initObservationStarted;
    string? initObservationId;
    DateTime? initStartedUtc;
    long initStartedTick, initSequence, initDroppedEvents;
    int initParseErrors, initEvidenceErrors, initThreadErrors;
    bool initSequenceOverflow;
    uint? initBaselineLevelId;
    NativePacketObserverProxy.CallbackMoment? observerStartedMoment, observerRegisteredMoment, observerStoppedMoment;
    string? observerStopReason;
    static NativePacketObserverProxy.CallbackMoment ObserverNow() => new(DateTime.UtcNow, Stopwatch.GetTimestamp());
    void MarkObserverStarted()
    {
        RequireInitDispatcher();
        if (observerStartedMoment != null) throw new InvalidOperationException("OBSERVER_TIMING_ALREADY_STARTED");
        observerStartedMoment = ObserverNow();
    }
    void MarkObserverRegistered()
    {
        RequireInitDispatcher();
        observerRegisteredMoment ??= ObserverNow();
    }
    void MarkObserverStopped(string reason)
    {
        RequireInitDispatcher();
        // Later bridge cleanup must not replace the first actual stop or its reason.
        if (observerStartedMoment == null || observerStoppedMoment != null) return;
        observerStoppedMoment = ObserverNow(); observerStopReason = reason;
    }
    object ObserverTimingEvidence()
    {
        var lastCallback = packetObserver?.LastCallbackMoment;
        return new {scope="current-observer-instance-only", stopwatchFrequency=Stopwatch.Frequency,
            startedUtc=observerStartedMoment?.utc, startedTick=observerStartedMoment?.tick,
            registrationCompletedUtc=observerRegisteredMoment?.utc, registrationCompletedTick=observerRegisteredMoment?.tick,
            stoppedUtc=observerStoppedMoment?.utc, stoppedTick=observerStoppedMoment?.tick, stopReason=observerStopReason,
            lastCallbackUtc=lastCallback?.utc, lastCallbackTick=lastCallback?.tick,
            lastCallbackScope="proxy-entry-including-rejected-or-detached-callbacks", historical1022Inferred=false};
    }

    static bool InitOnDispatcher() => System.Windows.Application.Current?.Dispatcher.CheckAccess() == true;
    static void RequireInitDispatcher()
    {
        if (!InitOnDispatcher()) throw new InvalidOperationException("LEVEL_INIT_WRONG_THREAD");
    }
    static FieldInfo RequireInitField(Type owner, string name, Type fieldType)
    {
        var field = owner.GetField(name, BindingFlags.Instance | BindingFlags.Public |
            BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
        if (field == null || field.IsStatic || field.FieldType != fieldType)
            throw new InvalidOperationException("LEVEL_INIT_FIELD_CONTRACT_MISMATCH");
        return field;
    }
    uint? InitReadPayloadId(object? payload)
    {
        if (payload == null) return null;
        if (payload.GetType() != initPayloadType)
            throw new InvalidOperationException("LEVEL_INIT_PAYLOAD_TYPE_MISMATCH");
        var header = initHeaderField!.GetValue(payload);
        if (header == null) return null;
        if (header.GetType() != initHeaderType)
            throw new InvalidOperationException("LEVEL_INIT_HEADER_TYPE_MISMATCH");
        return (uint)initIdField!.GetValue(header)!;
    }
    void BeginLevelInitObservation(object producer)
    {
        RequireInitDispatcher();
        if (initObservationStarted) throw new InvalidOperationException("LEVEL_INIT_ALREADY_STARTED");
        // Editor() verifies the version profile before these exact fields are cached.
        var assembly = Editor();
        var managerType = assembly.GetType(InitManagerType, true)!;
        initPacketType = assembly.GetType(InitPacketType, true)!;
        initPayloadType = assembly.GetType(InitPayloadType, true)!;
        initHeaderType = assembly.GetType(InitHeaderType, true)!;
        var bodyInterface = assembly.GetType(InitBodyInterface, true)!;
        if (!bodyInterface.IsInterface || !bodyInterface.IsAssignableFrom(initPayloadType))
            throw new InvalidOperationException("LEVEL_INIT_BODY_CONTRACT_MISMATCH");
        initKindField = RequireInitField(initPacketType, "CpXLCUYqbP0", typeof(ushort));
        initBodyField = RequireInitField(initPacketType, "V06LCTfPYaj", bodyInterface);
        initHeaderField = RequireInitField(initPayloadType, "RmVRLESORxj", initHeaderType);
        initIdField = RequireInitField(initHeaderType, "yoJRBJp4HeU", typeof(uint));
        initCacheField = RequireInitField(managerType, "YwCXahy5RIN", initPayloadType);
        var manager = ExistingSingleton(assembly, B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        if (manager.GetType() != managerType) throw new InvalidOperationException("LEVEL_INIT_MANAGER_TYPE_MISMATCH");
        var initialPayload = initCacheField.GetValue(manager);
        initBaselineLevelId = InitReadPayloadId(initialPayload);
        initReceiversAtStart = ((IList)Field(producer, B("EdBi0U13Ia7"))).Cast<object>().ToArray();
        // Ensure cleanup evidence can inspect the existing deferred set before registering anything.
        _ = ((IEnumerable)Field(producer, B("IF2i0RhOw8l"))).Cast<object>().ToArray();
        initAssembly = assembly; initManager = manager; initProducer = producer;
        initBaselinePayload = initialPayload; // Strong reference: equality is always ReferenceEquals.
        initObservationId = Guid.NewGuid().ToString("N");
        initStartedUtc = DateTime.UtcNow; initStartedTick = Stopwatch.GetTimestamp();
        initObservationStarted = true;
    }
    void ObserveLevelInitPacket(object? packet)
    {
        if (!initObservationStarted || !observerActive) return;
        if (!InitOnDispatcher()) { Interlocked.Increment(ref initThreadErrors); return; }
        long sequence = 0, tick = 0; DateTime utc = default;
        uint? levelId = null; string? error = null;
        try
        {
            if (packet == null || packet.GetType() != initPacketType)
                throw new InvalidOperationException("LEVEL_INIT_PACKET_TYPE_MISMATCH");
            if ((ushort)initKindField!.GetValue(packet)! != 1022) return;
            // Only a received packet 1022 can advance this sequence. Polls never do.
            if (initSequence == long.MaxValue) { initSequenceOverflow = true; return; }
            sequence = ++initSequence; utc = DateTime.UtcNow; tick = Stopwatch.GetTimestamp();
            levelId = InitReadPayloadId(initBodyField!.GetValue(packet));
            if (!levelId.HasValue) throw new InvalidOperationException("LEVEL_INIT_MISSING_PAYLOAD_OR_HEADER");
        }
        catch (Exception ex)
        {
            initParseErrors++;
            error = ex is InvalidOperationException ? ex.Message : ex.GetType().Name;
        }
        if (sequence == 0) return;
        if (initReceipts.Count >= InitEventLimit) { initDroppedEvents++; return; }
        initReceipts.Add(new InitPacketReceipt(sequence, utc, tick, Environment.CurrentManagedThreadId,
            levelId, error == null, error));
    }
    static bool InitSameReferences(object[] left, object[] right) => left.Length == right.Length &&
        left.Where((item, index) => !ReferenceEquals(item, right[index])).Any() == false;
    static bool InitSameReferenceSet(object[] left, object[] right) => left.Length == right.Length &&
        left.All(item => right.Count(other => ReferenceEquals(item, other)) == 1);
    object[] InitWithoutOwn(IEnumerable values) => values.Cast<object>()
        .Where(item => !ReferenceEquals(item, packetObserver)).ToArray();
    void CaptureLevelInitObserverCleanupBaseline()
    {
        RequireInitDispatcher();
        if (!initObservationStarted || initProducer == null || initCleanupReceiversBefore != null) return;
        initCleanupReceiversBefore = InitWithoutOwn((IEnumerable)Field(initProducer, B("EdBi0U13Ia7")));
        initCleanupDeferredBefore = InitWithoutOwn((IEnumerable)Field(initProducer, B("IF2i0RhOw8l")));
    }
    object LevelInitObservationEvidence()
    {
        RequireInitDispatcher();
        if (!initObservationStarted) return new {started=false, observerTiming=ObserverTimingEvidence(), reopenVerified=false};
        try
        {
            var currentManager = ExistingSingleton(initAssembly!, B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
            bool managerSame = ReferenceEquals(currentManager, initManager);
            if (!managerSame) throw new InvalidOperationException("LEVEL_INIT_MANAGER_REPLACED");
            var currentPayload = initCacheField!.GetValue(currentManager);
            var currentId = InitReadPayloadId(currentPayload);
            var receivers = ((IEnumerable)Field(initProducer!, B("EdBi0U13Ia7"))).Cast<object>().ToArray();
            var deferred = ((IEnumerable)Field(initProducer!, B("IF2i0RhOw8l"))).Cast<object>().ToArray();
            var ownIndices = Enumerable.Range(0, receivers.Length).Where(i => ReferenceEquals(receivers[i], packetObserver)).ToArray();
            var builtinIndices = Enumerable.Range(0, receivers.Length).Where(i =>
                receivers[i].GetType().Assembly == initAssembly && receivers[i].GetType().FullName == InitBuiltinReceiverType).ToArray();
            var nonOwn = InitWithoutOwn(receivers); var nonOwnDeferred = InitWithoutOwn(deferred);
            return new {started=true, observationId=initObservationId, initStartedUtc, initStartedTick, observerTiming=ObserverTimingEvidence(),
                stopwatchFrequency=Stopwatch.Frequency, source="received-1022-packet-observer",
                sequence=initSequence, retainedEvents=initReceipts.Count, eventLimit=InitEventLimit,
                droppedEvents=initDroppedEvents, overflow=initDroppedEvents>0 || initSequenceOverflow,
                events=initReceipts.ToArray(), parseErrors=initParseErrors, evidenceErrors=initEvidenceErrors,
                threadErrors=initThreadErrors, baselinePayloadPresent=initBaselinePayload!=null,
                baselineLevelId=initBaselineLevelId, currentPayloadPresent=currentPayload!=null,
                currentLevelId=currentId, currentPayloadSameReference=ReferenceEquals(currentPayload,initBaselinePayload),
                managerSameReference=managerSame, ownReceiverCount=ownIndices.Length,
                ownReceiverIndex=ownIndices.Length==1 ? (int?)ownIndices[0] : null, builtinReceiverIndices=builtinIndices,
                builtinBeforeOwnObserver=ownIndices.Length==1 && builtinIndices.Length==1 && builtinIndices[0]<ownIndices[0],
                originalReceiverOrderPreserved=InitSameReferences(initReceiversAtStart,nonOwn),
                ownDeferredPresent=deferred.Any(item=>ReferenceEquals(item,packetObserver)),
                cleanupCompared=initCleanupReceiversBefore!=null,
                cleanupNonOwnReceiverOrderPreserved=initCleanupReceiversBefore==null ? (bool?)null : InitSameReferences(initCleanupReceiversBefore,nonOwn),
                cleanupNonOwnDeferredPreserved=initCleanupDeferredBefore==null ? (bool?)null : InitSameReferenceSet(initCleanupDeferredBefore,nonOwnDeferred),
                active=observerActive, nativeMethodsInvoked=false, sentToGame=false, reloadInvoked=false,
                causalReloadVerified=false, reopenVerified=false};
        }
        catch (Exception ex)
        {
            initEvidenceErrors++;
            return new {started=true, observationId=initObservationId, sequence=initSequence, observerTiming=ObserverTimingEvidence(),
                error=ex is InvalidOperationException ? ex.Message : ex.GetType().Name,
                parseErrors=initParseErrors, evidenceErrors=initEvidenceErrors, threadErrors=initThreadErrors,
                events=initReceipts.ToArray(), reopenVerified=false};
        }
    }
}
