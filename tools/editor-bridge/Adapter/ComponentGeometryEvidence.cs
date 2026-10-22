using System;
using System.Collections.Generic;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    const int GeometryPacketLimit = 8;
    int geometryPacketsSeen;
    readonly List<object> geometryPackets = new();

    // Called only with an actual 1017 body already delivered to our observer.
    // Retain bounded configuration evidence; do not request resources or infer dimensions.
    void CaptureGeometry1017(object? body)
    {
        RequireInitDispatcher();
        geometryPacketsSeen++;
        if (geometryPackets.Count >= GeometryPacketLimit) return;
        var observedUtc = DateTime.UtcNow;
        var observedTick = System.Diagnostics.Stopwatch.GetTimestamp();
        try
        {
            if (body == null) throw new InvalidOperationException("GEOMETRY_PACKET_BODY_NULL");
            var data = Geometry1017Fields.ReadReceived1017(body,
                System.Windows.Application.Current!.Dispatcher);
            geometryPackets.Add(new {sequence=geometryPacketsSeen, observedUtc, observedTick,
                readOk=true, data});
        }
        catch (Exception ex)
        {
            geometryPackets.Add(new {sequence=geometryPacketsSeen, observedUtc, observedTick,
                readOk=false, error=ex.GetType().Name, reason=ex.Message});
        }
    }

    object Geometry1017Evidence() => new {
        source="received-1017-resource-delta-observer", receivedPackets=observedPacketKinds.GetValueOrDefault(1017),
        captureAttempts=geometryPacketsSeen, captureLimit=GeometryPacketLimit,
        limited=observedPacketKinds.GetValueOrDefault(1017)>GeometryPacketLimit,
        captured=geometryPackets.Count!=0, packets=geometryPackets.ToArray(),
        absentPacketMeans="not-observed-in-this-window", sentToGame=false,
        prefabLibraryIdMappingVerified=false, geometryVerified=false, worldBoundsVerified=false
    };
}
