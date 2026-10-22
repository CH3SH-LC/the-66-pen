using System.Collections.Generic;
namespace BLvN1YxXA1gALdrCAxg { public interface LOn3vwxLoP3mi8YY1Es {} }
namespace PvFe2SR2cEiUZJHHMgIk {
 public class MduRq9R20uL9IPOAZEbw {private uint yoJRBJp4HeU; public MduRq9R20uL9IPOAZEbw(uint id){yoJRBJp4HeU=id;}}
 public class DerivedHeader : MduRq9R20uL9IPOAZEbw {public DerivedHeader(uint id):base(id){}}
}
namespace FnULH5Rwt7ZoyShipQfM {
 public class G1dmgnRwicSy3RHXRPwM : BLvN1YxXA1gALdrCAxg.LOn3vwxLoP3mi8YY1Es {
  private PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw? RmVRLESORxj;
  public G1dmgnRwicSy3RHXRPwM(uint id){RmVRLESORxj=new(id);}
  public G1dmgnRwicSy3RHXRPwM(PvFe2SR2cEiUZJHHMgIk.MduRq9R20uL9IPOAZEbw? header){RmVRLESORxj=header;}
 }
 public class WrongPayload : BLvN1YxXA1gALdrCAxg.LOn3vwxLoP3mi8YY1Es {}
 public class DerivedPayload : G1dmgnRwicSy3RHXRPwM {public DerivedPayload(uint id):base(id){}}
}
namespace Q4bmxBLCduuQZJ26BNvJ {
 public class lOecMKLCvJpWqQJhQFma {
  private ushort CpXLCUYqbP0; private BLvN1YxXA1gALdrCAxg.LOn3vwxLoP3mi8YY1Es? V06LCTfPYaj;
  public lOecMKLCvJpWqQJhQFma(ushort kind,BLvN1YxXA1gALdrCAxg.LOn3vwxLoP3mi8YY1Es? body){CpXLCUYqbP0=kind;V06LCTfPYaj=body;}
 }
 public class DerivedPacket : lOecMKLCvJpWqQJhQFma {public DerivedPacket():base(1022,new FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM(1)){}}
}
namespace RBvsLtXoVfy2fj2abowI {
 public class cnQXC4XoSIRRZGYUssnx {
  private FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM? YwCXahy5RIN;
  public cnQXC4XoSIRRZGYUssnx(FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM? body){YwCXahy5RIN=body;}
  public void Set(FnULH5Rwt7ZoyShipQfM.G1dmgnRwicSy3RHXRPwM? body){YwCXahy5RIN=body;}
 }
}
namespace CMA1XZL6sIiP8kjKPgY4 { public class oXGPPWL64bTmn2CjmWVm {} }
namespace Fixture {
 public interface Sink { void pGDP79hTafv(Q4bmxBLCduuQZJ26BNvJ.lOecMKLCvJpWqQJhQFma packet); }
 public class Producer {public List<object> receivers=new();public HashSet<object> deferred=new();}
 public class WrongField {public ulong field;}
 public class StaticField {public static uint field;}
 public class BaseField {public uint field;}
 public class InheritedField:BaseField {}
}
