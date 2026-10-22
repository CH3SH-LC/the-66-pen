using System;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Miliastra.EditorBridge;
using Payload=FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM;
using Packet=Q4bmxBLCduuQZJ26BNvJ.lOecMKLCvJpWqQJhQFma;
using Header=PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw;
static class Program {
 static int checks;
 static void Check(bool good,string title){if(!good)throw new Exception(title);checks++;Console.WriteLine("PASS "+title);}
 static long N(JsonElement x,string key)=>x.GetProperty(key).GetInt64();
 static bool B(JsonElement x,string key)=>x.GetProperty(key).GetBoolean();
 static void Reject(Action action,string title){try{action();throw new Exception("unexpected accepted: "+title);}catch(InvalidOperationException){checks++;Console.WriteLine("PASS "+title);}}
 static EditorAdapter New(){var a=new EditorAdapter(new Payload(1073741839));a.Start();return a;}
 [STAThread] static void Main(){
  var app=new System.Windows.Application();
  var a=New();var b=a.Evidence();Check(N(b,"sequence")==0&&N(b,"retainedEvents")==0&&B(b,"currentPayloadSameReference"),"startup cache is not event");
  Check(B(b,"builtinBeforeOwnObserver")&&B(b,"originalReceiverOrderPreserved")&&N(b,"ownReceiverCount")==1,"registered after built-in without replacing receivers");
  a.Manager.Set(new Payload(1073741839));b=a.Evidence();Check(!B(b,"currentPayloadSameReference")&&N(b,"sequence")==0,"same-valued replacement cache does not synthesize receipt");
  a.Receive(new Packet(1017,new Payload(1073741839)));Check(N(a.Evidence(),"sequence")==0,"other message ignored");
  a.Receive(new Packet(1022,new Payload(1073741839)));b=a.Evidence();var evt=b.GetProperty("events")[0];Check(N(b,"sequence")==1&&N(evt,"levelId")==1073741839&&B(evt,"parsed"),"real DispatchProxy receive captures exact 1022 identity");
  Check(N(evt,"receivedTick")>=N(b,"initStartedTick")&&evt.GetProperty("receivedUtc").GetDateTime()>=b.GetProperty("initStartedUtc").GetDateTime(),"event monotonic and UTC start bounds");
  for(int i=0;i<3;i++)a.Evidence();Check(N(a.Evidence(),"sequence")==1,"polling does not increment receipt sequence");
  a.Observe(null);a.Observe(new object());a.Observe(new Q4bmxBLCduuQZJ26BNvJ.DerivedPacket());b=a.Evidence();Check(N(b,"parseErrors")==3&&N(b,"sequence")==1,"null wrong and derived packet types rejected without false event");
  a.Receive(new Packet(1022,null));a.Receive(new Packet(1022,new FnULH5Rwt7ZoyShipQfM.WrongPayload()));a.Receive(new Packet(1022,new Payload((Header?)null)));a.Receive(new Packet(1022,new FnULH5Rwt7ZoyShipQfM.DerivedPayload(1)));a.Receive(new Packet(1022,new Payload(new PvFe2SR2cEiUZJHHMgIk.DerivedHeader(1))));b=a.Evidence();Check(N(b,"sequence")==6&&N(b,"parseErrors")==8&&b.GetProperty("events").EnumerateArray().Skip(1).All(e=>!B(e,"parsed")),"five malformed 1022 payload paths counted and retained as errors");
  Task.Run(()=>a.Observe(new Packet(1022,new Payload(1)))).Wait();b=a.Evidence();Check(N(b,"threadErrors")==1&&N(b,"sequence")==6,"wrong thread receipt rejected and counted");
  bool refused=false;Task.Run(()=>{try{a.Evidence();}catch(InvalidOperationException){refused=true;}}).Wait();Check(refused,"evidence requires dispatcher");
  Reject(a.BeginAgain,"cannot restart observation or erase receipts");
  var full=New();for(int i=0;i<17;i++)full.Receive(new Packet(1022,new Payload((uint)i)));b=full.Evidence();Check(N(b,"sequence")==17&&N(b,"retainedEvents")==16&&N(b,"droppedEvents")==1&&B(b,"overflow"),"event storage bound 16 reports overflow");
  var over=New();over.ForceSequenceOverflow();over.Receive(new Packet(1022,new Payload(1)));Check(B(over.Evidence(),"overflow")&&N(over.Evidence(),"retainedEvents")==0,"sequence saturation refuses wraparound");
  var clean=New();object existingDeferred=new();clean.Producer.deferred.Add(existingDeferred);clean.ScheduleOwnRemoval();Check(B(clean.Evidence(),"ownDeferredPresent"),"own deferred presence observed");clean.Stop();b=clean.Evidence();Check(N(b,"ownReceiverCount")==0&&!B(b,"ownDeferredPresent")&&B(b,"cleanupCompared")&&B(b,"cleanupNonOwnReceiverOrderPreserved")&&B(b,"cleanupNonOwnDeferredPreserved"),"cleanup removes only own sink from both containers");
  clean.Observe(new Packet(1022,new Payload(2)));Check(N(clean.Evidence(),"sequence")==0,"inactive ignores late receipt");
  clean.Producer.receivers.Add(new object());b=clean.Evidence();Check(!B(b,"cleanupNonOwnReceiverOrderPreserved"),"foreign receiver change reported");
  clean.Producer.deferred.Remove(existingDeferred);Check(!B(clean.Evidence(),"cleanupNonOwnDeferredPreserved"),"foreign deferred change reported");
  var missing=new EditorAdapter(null);missing.Start();b=missing.Evidence();Check(!B(b,"baselinePayloadPresent")&&b.GetProperty("baselineLevelId").ValueKind==JsonValueKind.Null,"null baseline truthful and not event");
  var replaced=New();replaced.Manager=new RBvsLtXoVfy2fj2abowI.cnQXC4XoSIRRZGYUssnx(new Payload(1));b=replaced.Evidence();Check(N(b,"evidenceErrors")==1&&b.GetProperty("error").GetString()=="LEVEL_INIT_MANAGER_REPLACED","manager identity change fails evidence");
  Reject(()=>EditorAdapter.ValidateField(typeof(Fixture.WrongField)),"wrong field UInt64 type rejected");Reject(()=>EditorAdapter.ValidateField(typeof(Fixture.StaticField)),"static field rejected");Reject(()=>EditorAdapter.ValidateField(typeof(Fixture.InheritedField)),"inherited field rejected by DeclaredOnly");
  Check(!B(a.Evidence(),"reopenVerified")&&!B(a.Evidence(),"causalReloadVerified"),"observation never claims reload completion");
  Console.WriteLine("RESULT "+checks+" checks passed; synthetic types, real WPF dispatcher and DispatchProxy; no game/editor DLL loaded");
 }
}
