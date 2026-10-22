// Synthetic types only; the BeyondEditor assembly is never loaded.
// Field layout mirrors .runtime/verification/resource-sync-payload/key-registration.cs:19-27
// (FevvcZiBkS31NrEJZJIG): five sequential uint fields, so offsets 0/4/8/12/16.
// Category quad is written by the Fevvc(Ixx, uint) ctor (key-registration.cs:215-267) as
// list[0..3] of the path returned by IxxdqjiYXvUxMvfd5Mwm; the real registration path is
// (10003, 50013, 0, 0) -- see tag-category-factory.cs:1079-1082 (dttKlHAIjhe) and
// tag-handler.cs (`new FevvcZiBkS31NrEJZJIG(dttKlHAIjhe(), num4)`).
// 23 is a message/model enum and is NOT interchangeable with the registration path.
namespace nhvlt3i2jU53g9xeFtUu;
public struct FixtureKey { public uint oLyiwZX255H,AwbiwrjxUDX,UFWiwJNegmh,RBTiwn649Hy,namiwGPRyPS; }
public class FixtureValue<T> { public T VpIiRZgdEln; public FixtureValue(T value)=>VpIiRZgdEln=value; }
public class FixtureBase {
    protected FixtureValue<string>? WAAiS5WkxlA;
    protected FixtureValue<FixtureKey> Qi8iCzKCkTt;
    public FixtureBase(string? name,uint id):this(name,id,CategoryLeaf0,CategoryLeaf1,0u,0u){}
    public FixtureBase(string? name,uint id,uint c0,uint c1,uint c2,uint c3){
        WAAiS5WkxlA=name==null?null:new(name);
        Qi8iCzKCkTt=new(new(){oLyiwZX255H=c0,AwbiwrjxUDX=c1,UFWiwJNegmh=c2,RBTiwn649Hy=c3,namiwGPRyPS=id});
    }
    internal const uint CategoryLeaf0=10003u,CategoryLeaf1=50013u;
    internal const uint StaleMessageGroup=23u;
}
public sealed class mha7Cmi2N9yPWiDcXdhA:FixtureBase {
    public mha7Cmi2N9yPWiDcXdhA(string? name,uint id):base(name,id){}
    public mha7Cmi2N9yPWiDcXdhA(string? name,uint id,uint c0,uint c1,uint c2,uint c3):base(name,id,c0,c1,c2,c3){}
}
