// Explicit native stubs. Runs our real private mutate/capture/renderer readers;
// it never resolves or invokes an address from YuanShen.exe.
#define MATERIAL_PRIVATE_TEST 1
#include "native_material.cpp"
#include <array>
#include <cstdio>
#include <stdexcept>
#include <vector>
namespace fixture {
alignas(16) unsigned char arena[65536]{};
constexpr U base=0x100000;
U address(unsigned offset){return reinterpret_cast<U>(arena+offset);}
constexpr unsigned O=0x100,C=0x200,T=0x300,K=0x500,TK=0x700,RK=0x900,PK=0xb00,RECK=0xd00,
 UN=0x1000,REN=0x1200,ENGINE=0x1400,BLOCK=0x1800,MAT=0x1a00,RA=0x1c00,MA=0x1e00,HIER=0x2000,
 MAN=0x2200,L=0x2400,IA=0x2600,REC=0x2800,BLOB=0x2a00,TX=0x2c00,AL=0x3000,AA=0x3200,PAY=0x3400,G=0x4000;
MaterialState rendered{};std::vector<unsigned> calls;bool badNotify=false,badRefresh=false,blocked=false;int allowed=6711;
template<class V> void put(unsigned o,V v){std::memcpy(arena+o,&v,sizeof(v));}
void* object(unsigned off){return arena+off;}
void* lookupStub(void* owner,int kind){if(owner!=object(O))throw std::runtime_error("unexpected owner");return kind==22?object(C):kind==1?object(T):nullptr;}
void* noGroup(void*,int){return nullptr;}
void catalogStub(unsigned,U* list,U* labels){put<unsigned>(AL+0x18,1);put<int>(AA+0x20,allowed);*list=address(AL);*labels=0;}
void modesStub(unsigned,U* list,U* labels){put<unsigned>(AL+0x18,2);put<int>(AA+0x20,6700);put<int>(AA+0x24,6701);*list=address(AL);*labels=0;}
bool colorAllowed(unsigned){return true;}
bool materialBlocked(unsigned){return blocked;}
unsigned templateId(void*){return 10009002;}
void* allocate(void* klass){calls.push_back(0x52aa00);if(klass!=object(PK))throw std::runtime_error("wrong payload class");put<U>(PAY,address(PK));return object(PAY);}
void* begin(void* value,bool a,bool b){if(value||a||b)throw std::runtime_error("unexpected transaction args");calls.push_back(0xe827750);put<int>(MAN+0x34,1);return object(TX);}
void snapshot(void* c,void* hint,int mode){if(c!=object(C)||hint||mode)throw std::runtime_error("unexpected snapshot args");calls.push_back(0x107abdf0);put<unsigned>(L+0x18,1);put<U>(REC+0x18,address(C));put<U>(REC+0x28,address(BLOB));put<unsigned char>(REC+0x30,0);}
void* deserialize(void* payload,void* c){if(payload!=object(PAY)||c!=object(C))throw std::runtime_error("wrong deserializer target");calls.push_back(0xed54450);// Reproduce ed54450's observed byte permutation independently of field names.
    const auto* in=arena+PAY;auto* out=arena+C;
    std::memcpy(out+0x38,in+0x24,4);std::memcpy(out+0x44,in+0x18,4);std::memcpy(out+0x3c,in+0x1c,8);
    out[0x34]=in[0x2b];out[0x35]=in[0x29];out[0x36]=in[0x2a];out[0x37]=in[0x28];
    std::memcpy(out+0x30,in+0x2c,4);return c;}
void notify(void* manager,void* c){if(manager!=object(MAN)||c!=object(C))throw std::runtime_error("wrong notify target");calls.push_back(0x9c26c70);put<unsigned char>(REC+0x30,badNotify?0:1);}
void close(void* tx){if(tx!=object(TX))throw std::runtime_error("wrong close target");calls.push_back(0xc7bab90);put<unsigned>(L+0x18,0);put<int>(MAN+0x34,0);}
void refresh(void* c){if(c!=object(C))throw std::runtime_error("wrong refresh target");calls.push_back(0xe549580);if(!badRefresh)std::memcpy(&rendered,arena+C+0x30,sizeof(rendered));}
void* children(void* root,U type,bool inactive){if(root!=object(UN)||type!=address(RK)||!inactive)throw std::runtime_error("wrong renderer collection");return object(RA);}
void* transform(void*){return object(UN);}
void* gameObject(void*){return object(UN);}
bool enabled(void*){return true;}
void* materials(void* r){if(r!=object(REN))throw std::runtime_error("wrong sharedMaterials owner");return object(MA);}
int index(void* block,int property,int kind){if(block!=object(BLOCK))throw std::runtime_error("wrong native renderer block");if(property==2&&kind!=1)throw std::runtime_error("color kind");put<float>(0x3800+4,static_cast<float>(rendered.enableColor));put<float>(0x3800+12,rendered.blendMode==6701?1.f:0.f);return property;}
float getFloat(void* renderer,int id){if(renderer!=object(REN))throw std::runtime_error("Material.GetFloat must not be used");return id==1?static_cast<float>(rendered.enableColor):rendered.blendMode==6701?1.f:0.f;}
float* getColor(void* block,float* color,int id){if(block!=object(BLOCK)||id!=2)throw std::runtime_error("wrong color lookup");unsigned shifts[]={16,8,0,24};for(unsigned i=0;i<4;++i)color[i]=static_cast<float>((rendered.argb>>shifts[i])&255)/255.f;return color;}
bool keyword(void* material,void* value){if(material!=object(MAT))throw std::runtime_error("keyword target");return rendered.enableMaterial&&((value==object(0x6000)&&rendered.material==6711)||(value==object(0x6100)&&rendered.material==6710));}
void reset(){std::memset(arena,0,sizeof(arena));calls.clear();badNotify=badRefresh=blocked=false;allowed=6711;
    put<U>(C,address(K));put<U>(C+0x20,address(O));put<U>(T,address(TK));put<U>(T+0x20,address(O));put<U>(T+0x30,address(UN));put<U>(T+0x78,address(UN));
    put<U>(UN+0x10,address(ENGINE));put<U>(REN,address(RK));put<U>(REN+0x10,address(ENGINE));put<U>(ENGINE+0x120,address(BLOCK));put<U>(MAT+0x10,address(ENGINE));
    put<U>(BLOCK+0x50,address(0x3600));put<U>(BLOCK+0x70,address(0x3800));put<unsigned>(0x3600+8,4);put<unsigned>(0x3600+24,12);
    put<unsigned char>(RK+0xc5,1);put<U>(RK+0x40,address(HIER));put<U>(HIER,address(RK));put<U>(RA+0x18,1);put<U>(RA+0x20,address(REN));put<U>(MA+0x18,1);put<U>(MA+0x20,address(MAT));
    put<U>(MAN+0x18,address(L));put<U>(L+0x10,address(IA));put<U>(IA+0x18,4);put<U>(IA+0x20,address(REC));put<U>(REC,address(RECK));
    put<U>(AL+0x10,address(AA));put<U>(AA+0x18,4);put<unsigned>(AL+0x1c,1);
    rendered={0,0,0,0,0,0xffffffff,6700,0xffffff,100.f};put(C+0x30,rendered);
}
ShaderIds ids(){return {1,2,3,address(0x6000),address(0x6100)};}
MaterialRow row(){MaterialRow r{};r.entityId=77;r.configId=10009002;r.owner=address(O);r.status=1;r.mask=127;
    if(!capture(base,r,r.before)||!slots(base,r.owner,ids(),r.beforeRender,r.beforeSlots,true))throw std::runtime_error("fixture capture failed");
    r.desired={6711,1,0,0,1,0x80123456,6700,0x123456,static_cast<float>(128)/255.f*100.f};return r;
}
GameContextSnapshot scene(){GameContextSnapshot s{};s.moduleBase=base;s.global=address(G);return s;}
void check(bool v,const char* msg){if(!v)throw std::runtime_error(msg);}
}
bool MaterialTestRead(U at,void* output,std::size_t n){using namespace fixture;U value=0;
    if(at==base+0x57caca0)value=address(K);else if(at==base+0x57c8eb8)value=address(TK);else if(at==base+0x57a11e8)value=address(RK);else if(at==base+0x57d7620)value=address(PK);else if(at==base+0x5812cf8)value=address(RECK);else if(at==address(G)+0xecd0)value=address(MAN);
    if(value){if(n!=8)return false;std::memcpy(output,&value,8);return true;}
    const U start=address(0);if(at<start||at-start>sizeof(arena)||n>sizeof(arena)-(at-start))return false;std::memcpy(output,reinterpret_cast<void*>(at),n);return true;
}
void* MaterialTestNative(unsigned rva){using namespace fixture;
#define STUB(r,f) case r:return reinterpret_cast<void*>(&f)
    switch(rva){STUB(0x867f250,lookupStub);STUB(0x8678480,noGroup);STUB(0x123be610,catalogStub);STUB(0x123be370,modesStub);STUB(0x123be980,colorAllowed);STUB(0x123beb10,materialBlocked);STUB(0xc0e9830,templateId);
    STUB(0x52aa00,allocate);STUB(0xe827750,begin);STUB(0x107abdf0,snapshot);STUB(0xed54450,deserialize);STUB(0x9c26c70,notify);STUB(0xc7bab90,close);STUB(0xe549580,refresh);
    STUB(0x19cbcac0,children);STUB(0x1453c10,transform);STUB(0x1453c60,gameObject);STUB(0x19c9b820,enabled);STUB(0x19cd26c0,enabled);STUB(0x19cd29e0,materials);
    STUB(0x1607030,index);STUB(0x19cd21e0,getFloat);STUB(0x1607290,getColor);STUB(0x19cbdc00,keyword);
    default:throw std::runtime_error("UNSTUBBED_NATIVE_CALLBACK");}
#undef STUB
}
int main(){using namespace fixture;try{
    reset();auto r=row();check(mutate(scene(),r,ids()),"success rejected");check(r.stage==8&&r.closed==1&&r.shaderVerified==1&&!r.uncertain,"success evidence");
    check(calls==std::vector<unsigned>{0x52aa00,0xe827750,0x107abdf0,0xed54450,0x9c26c70,0xc7bab90,0xe549580},"transaction native order");
    check(r.after.enableColor==1&&r.after.enableMaterial==1&&r.after.coverDecorationColor==0&&r.after.coverDecorationMaterial==0,"independent enable/decoration flags lost");
    check(r.after.argb==0x80123456&&std::fabs(r.afterRender[0].rgba[0]-18.f/255.f)<0.00001f&&std::fabs(r.afterRender[0].rgba[3]-128.f/255.f)<0.00001f,"channel/alpha readback");
    reset();r=row();put<unsigned>(C+0x38,0xdeadbeef);check(!mutate(scene(),r,ids())&&calls.empty()&&!r.openCalled,"stale precondition edited");
    reset();r=row();allowed=6710;check(!mutate(scene(),r,ids())&&calls.empty(),"unsupported material edited");
    reset();r=row();blocked=true;check(!mutate(scene(),r,ids())&&calls.empty(),"native blacklisted template edited");
    reset();r=row();badNotify=true;check(!mutate(scene(),r,ids())&&r.closed&&r.uncertain&&!r.refreshCalled,"dirty failure not closed/uncertain");
    reset();r=row();badRefresh=true;check(!mutate(scene(),r,ids())&&r.closed&&r.refreshCalled&&r.uncertain&&!r.shaderVerified,"shader failure falsely accepted");
    reset();r=row();put<unsigned>(L+0x18,1);check(!mutate(scene(),r,ids())&&calls.empty(),"foreign transaction entered");
    reset();r=row();put<unsigned char>(C+0x36,9);MaterialState invalid{};check(!capture(base,r,invalid),"invalid bool accepted");
    reset();r=row();put<U>(RA+0x18,65);unsigned count=0;MaterialSlot out[64]{};check(!slots(base,r.owner,ids(),out,count,true),"renderer truncation accepted");
    std::puts("{\"ok\":true,\"checks\":9,\"nativeCallbacksExplicitlyStubbed\":true,\"gameConnected\":false}");return 0;
 }catch(const std::exception& e){std::printf("{\"ok\":false,\"error\":\"%s\",\"nativeCallbacksExplicitlyStubbed\":true}\n",e.what());return 2;}}
