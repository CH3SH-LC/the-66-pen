using System;
using System.Collections;
using System.Reflection;
using System.Text.Json;
using Fixture;
using Manager=RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx;
using Payload=FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM;
using Packet=Q4bmxBLCduuQZJ26BNvJ.lOecMKLCvJpWqQJhQFma;
namespace Miliastra.EditorBridge;
internal sealed partial class EditorAdapter {
 bool observerActive; NativePacketObserverProxy? packetObserver;
 internal Manager Manager; internal Producer Producer=new(); internal Sink? Sink;
 internal EditorAdapter(Payload? payload){Manager=new(payload);Producer.receivers.Add(new CMA1XZL6sIiP8kjKPgY4.oXGPPWL64bTmn2CjmWVm());}
 Assembly Editor()=>typeof(Manager).Assembly;
 static string B(string key)=>key switch {"EdBi0U13Ia7"=>"receivers","IF2i0RhOw8l"=>"deferred",_=>key};
 object ExistingSingleton(Assembly assembly,string type)=>Manager;
 object Field(object value,string name)=>value.GetType().GetField(name)!.GetValue(value)!;
 internal void Start(){BeginLevelInitObservation(Producer);Sink=DispatchProxy.Create<Sink,NativePacketObserverProxy>();packetObserver=(NativePacketObserverProxy)(object)Sink;packetObserver.Configure(typeof(Sink).GetMethods()[0]);packetObserver.Receive=ObserveLevelInitPacket;observerActive=true;Producer.receivers.Add(packetObserver);}
 internal void BeginAgain()=>BeginLevelInitObservation(Producer);
 internal void Observe(object? packet)=>ObserveLevelInitPacket(packet);
 internal void Receive(Packet packet)=>Sink!.pGDP79hTafv(packet);
 internal JsonElement Evidence()=>JsonSerializer.SerializeToElement(LevelInitObservationEvidence());
 internal void Stop(){CaptureLevelInitObserverCleanupBaseline();observerActive=false;packetObserver!.Receive=null;Producer.receivers.Remove(packetObserver);Producer.deferred.Remove(packetObserver);}
 internal void ScheduleOwnRemoval()=>Producer.deferred.Add(packetObserver!);
 internal void ForceSequenceOverflow()=>initSequence=long.MaxValue;
 internal static void ValidateField(Type type)=>RequireInitField(type,"field",typeof(uint));
}
