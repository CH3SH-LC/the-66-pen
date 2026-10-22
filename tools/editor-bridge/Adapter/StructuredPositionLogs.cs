using System;
using System.Collections;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    // cc-type0.cs:136/276 identifies the two payload types; batch-log-proto.cs:37
    // proves the direct repeated-record field. No graph ID or timestamp inference.
    static string PositionRecordType => B("HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD");
    static string PositionBatchType => B("IGmDiMatq2IanW3w1IR0.YGZiiaatLoanyfGQd2hQ");
    const int StructuredPacketLimit=32;
    const int StructuredRecordLimit=4096;
    int structuredPackets,structuredBatchPackets,structuredSinglePackets,structuredRecords;
    int structuredMalformed;
    bool structuredLimited;

    bool CaptureStructuredPositionLogs(object payload)
    {
        var name=payload.GetType().FullName;
        if(name!=PositionRecordType && name!=PositionBatchType)return false;
        if(structuredPackets>=StructuredPacketLimit){structuredLimited=true;return true;}
        structuredPackets++;
        if(name==PositionRecordType)
        {
            structuredSinglePackets++;
            structuredRecords++;
            CapturePositionPrint(payload);
            CaptureRunLogRecord(payload);
            return true;
        }
        structuredBatchPackets++;
        if(Field(payload,B("WLlatRfEhBx")) is not IEnumerable records)
        {structuredMalformed++;return true;}
        int count=0;
        foreach(var record in records)
        {
            if(count>=StructuredRecordLimit){structuredLimited=true;break;}
            count++;
            if(record==null || record.GetType().FullName!=PositionRecordType)
            {structuredMalformed++;continue;}
            structuredRecords++;
            CapturePositionPrint(record);
            CaptureRunLogRecord(record);
        }
        return true;
    }

    object StructuredPositionLogEvidence()=>new
    {
        recognizedPackets=structuredPackets,batchPackets=structuredBatchPackets,
        singlePackets=structuredSinglePackets,recordsScanned=structuredRecords,
        malformedRecords=structuredMalformed,limited=structuredLimited,
        packetLimit=StructuredPacketLimit,recordsPerPacketLimit=StructuredRecordLimit,
        runtimePositionParsed=false
    };
}
