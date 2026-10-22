using System.Reflection;
using Miliastra.EditorBridge;
public sealed class Packet {}
public interface Current {void pGDP79hTafv(Packet p);}
public interface Legacy {void seAYooJHAHf(Packet p);}
public interface SameNameWrongOwner {void pGDP79hTafv(Packet p);}
public interface WrongReturn {int pGDP79hTafv(Packet p);}
public interface WrongArity {void pGDP79hTafv(Packet p, Packet q);}
public interface TwoMethods {void pGDP79hTafv(Packet p);void other(Packet p);}
public static class Program {
 static int checks;
 static void Check(bool value,string title) {if(!value)throw new Exception(title);checks++;Console.WriteLine("PASS "+title);}
 static NativePacketObserverProxy Proxy<T>(out T sink) where T:class {sink=DispatchProxy.Create<T,NativePacketObserverProxy>();return(NativePacketObserverProxy)(object)sink;}
 static void Invalid(Type t) {var p=Proxy<Current>(out _);try{p.Configure(t.GetMethods()[0]);throw new Exception("accepted invalid contract");}catch(InvalidOperationException){checks++;}}
 public static void Main() {
  int n=0;var p=Proxy<Current>(out var sink);var packet=new Packet();p.Configure(typeof(Current).GetMethods()[0]);p.Receive=x=>{Check(ReferenceEquals(x,packet),"same packet instance");n++;};sink.pGDP79hTafv(packet);Check(n==1&&p.CallbackErrors==0&&p.CallbackInvocations==1,"current 7.1 callback delivered");
  var l=Proxy<Legacy>(out var legacy);l.Configure(typeof(Legacy).GetMethods()[0]);int ln=0;l.Receive=_=>ln++;legacy.seAYooJHAHf(packet);Check(ln==1,"configured name independent");
  var wrong=Proxy<Current>(out var wrongSink);wrong.Configure(typeof(SameNameWrongOwner).GetMethods()[0]);wrong.Receive=_=>throw new Exception("must not deliver");wrongSink.pGDP79hTafv(packet);Check(wrong.ContractRejectedCallbacks==1&&wrong.CallbackErrors==1&&wrong.CallbackInvocations==0,"same name wrong owner refused without throwing");
  var unc=Proxy<Current>(out var uncSink);uncSink.pGDP79hTafv(packet);Check(unc.ContractRejectedCallbacks==1,"unconfigured refused");
  sink.pGDP79hTafv(null!);Check(p.CallbackErrors==1&&p.ContractRejectedCallbacks==1&&n==1,"null packet refused");
  p.Receive=_=>throw new Exception("callback");sink.pGDP79hTafv(packet);Check(p.CallbackErrors==2&&p.CallbackInvocations==2,"callback exception contained");
  p.Receive=null;sink.pGDP79hTafv(packet);Check(p.CallbackErrors==2&&p.CallbackInvocations==3,"cleared callback safe");
  try{p.Configure(typeof(Current).GetMethods()[0]);throw new Exception("reconfigured");}catch(InvalidOperationException){checks++;}
  Invalid(typeof(WrongReturn));Invalid(typeof(WrongArity));Invalid(typeof(TwoMethods));
  Console.WriteLine("RESULT checks="+checks+" all passed; no editor/game loaded");
 }
}
