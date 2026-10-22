#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_material.h"
#include <cmath>
#include <cstring>
#if HR_ACTION != 22 || !MATERIAL_REVIEWED || !GS_REVIEWED_ACTION_PROFILE
#error "Material requires dedicated action22 / protocol28"
#endif
#if MATERIAL_WRITE != 0 && MATERIAL_WRITE != 1
#error "Material mode must be inspect(0) or set(1)"
#endif
// Only the offline harness defines this symbol. Production cards are compiled
// from pinned sources with generated headers and never expose a dispatch table.
#ifdef MATERIAL_PRIVATE_TEST
extern void* MaterialTestNative(unsigned);
extern bool MaterialTestRead(std::uint64_t,void*,std::size_t);
#endif
namespace {
using U=std::uint64_t;
template<class F> F native(U b,unsigned rva){
#ifdef MATERIAL_PRIVATE_TEST
    (void)b;return reinterpret_cast<F>(MaterialTestNative(rva));
#else
    return reinterpret_cast<F>(b+rva);
#endif
}
bool memory(U at,void* out,std::size_t n) noexcept {
#ifdef MATERIAL_PRIVATE_TEST
    return MaterialTestRead(at,out,n);
#else
    if(!out||!n||at<0x10000||at>=0x800000000000ULL||n>0x800000000000ULL-at)return false;
    std::size_t done=0;
    while(done<n){MEMORY_BASIC_INFORMATION r{};const auto p=at+done;
        if(VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||(r.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
        const auto left=r.RegionSize-static_cast<std::size_t>(p-reinterpret_cast<U>(r.BaseAddress));const auto part=n-done<left?n-done:left;
        __try{std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(p),part);}__except(EXCEPTION_EXECUTE_HANDLER){return false;}done+=part;
    }return true;
#endif
}
template<class T> bool read(U p,T& v){return memory(p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&v>=0x10000&&v<0x800000000000ULL?v:0;}
U lookup(U b,U owner,int kind){return reinterpret_cast<U>(native<void*(*)(void*,int)>(b,0x867f250)(reinterpret_cast<void*>(owner),kind));}
bool valid(const MaterialState& v){return v.enableMaterial<=1&&v.coverDecorationMaterial<=1&&v.coverDecorationColor<=1&&v.enableColor<=1&&std::isfinite(v.alphaPercent)&&v.alphaPercent>=0&&v.alphaPercent<=100;}
bool primitive(unsigned id){return id==10009002||id==10009003||id==10009008||id==10009009;}
bool isA(U klass,U expected){unsigned char depth=0,wanted=0;if(!read(klass+0xc5,depth)||!read(expected+0xc5,wanted)||!wanted||wanted>64||depth<wanted)return false;const U h=ptr(klass+0x40);return h&&ptr(h+(wanted-1)*8)==expected;}
U hash(const void* p,std::size_t n,U seed=1469598103934665603ULL){const auto bytes=static_cast<const unsigned char*>(p);for(std::size_t i=0;i<n;++i){seed^=bytes[i];seed*=1099511628211ULL;}return seed;}
bool scene(const GameContextSnapshot& a,const GameContextSnapshot& b){
    if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||a.status!=GS_OK||b.status!=GS_OK||(a.flags&1951)!=1951||(b.flags&1951)!=1951||
       a.reserved!=MATERIAL_LEVEL||b.reserved!=MATERIAL_LEVEL||a.entityRejected||b.entityRejected||a.entityCaptured!=a.entityValidEntries||b.entityCaptured!=b.entityValidEntries||
       a.entityCaptured!=b.entityCaptured||a.entityCaptured>kMaxEntities||a.currentContext!=b.currentContext||a.global!=b.global||a.moduleBase!=b.moduleBase||
       a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter||std::memcmp(a.origin,b.origin,sizeof(a.origin)))return false;
    for(unsigned i=0;i<a.entityCaptured;++i){const auto& x=a.entities[i];const auto& y=b.entities[i];if(x.id!=y.id||x.owner!=y.owner||x.config!=y.config||x.context!=y.context||x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;}return true;
}
bool code(const GameContextSnapshot& s,MaterialReceipt* o){
    if(s.moduleBase!=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"))||s.peTimestamp!=HR_GAME_TIMESTAMP||s.peImageSize!=HR_GAME_IMAGE_SIZE)return false;
    static constexpr unsigned rvas[]={MATERIAL_CODE_RVAS};static constexpr unsigned char expected[][32]={MATERIAL_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(*rvas);++i)if(!memory(s.moduleBase+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={GS_PROFILE_HOTFIX_RVAS,MATERIAL_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(s.moduleBase+r,v)||v){o->failedRva=r;o->failedValue=v;return false;}}return true;
}
bool capture(U b,MaterialRow& row,MaterialState& out){
    if(native<unsigned(*)(void*)>(b,0xc0e9830)(reinterpret_cast<void*>(row.owner))!=row.configId)return false;
    const U c=lookup(b,row.owner,22),t=lookup(b,row.owner,1);
    if(!c||ptr(c)!=ptr(b+0x57caca0)||ptr(c+0x20)!=row.owner||!t||ptr(t)!=ptr(b+0x57c8eb8)||ptr(t+0x20)!=row.owner)return false;
    // Material refresh propagates through group kind40. This first primitive
    // implementation refuses both membership and group ownership entirely.
    if(lookup(b,row.owner,40)||native<void*(*)(void*,int)>(b,0x8678480)(reinterpret_cast<void*>(row.owner),40))return false;
    const U unity=ptr(t+0x78),view=ptr(t+0x30);
    if(!unity||!ptr(unity+0x10)||!view||!ptr(view+0x10)||!read(c+0x30,out)||!valid(out))return false;
    if(row.component&&(row.component!=c||row.klass!=ptr(c)||row.unity!=unity||row.view!=view))return false;
    row.component=c;row.klass=ptr(c);row.unity=unity;row.view=view;return true;
}
bool intList(U list,int* values,unsigned& count){
    unsigned n=0,version=0,again=0;U capacity=0;const U array=ptr(list+0x10);
    if(!list||!array||!read(list+0x18,n)||n>4||!read(list+0x1c,version)||!read(array+0x18,capacity)||capacity<n||capacity>1024)return false;
    if(n&&!memory(array+0x20,values,n*4))return false;
    for(unsigned i=0;i<n;++i)for(unsigned j=0;j<i;++j)if(values[i]==values[j])return false;
    if(!read(list+0x1c,again)||version!=again)return false;count=n;return true;
}
bool catalog(U b,MaterialRow& r){
    U list=0,labels=0;r.materialCount=r.modeCount=0;
    native<void(*)(unsigned,U*,U*)>(b,0x123be610)(r.configId,&list,&labels);
    if(!intList(list,r.allowedMaterials,r.materialCount))return false;
    // Native queries reuse scratch lists. Copy materials before querying modes.
    native<void(*)(unsigned,U*,U*)>(b,0x123be370)(r.configId,&list,&labels);
    if(!intList(list,r.allowedModes,r.modeCount))return false;
    r.colorAllowed=native<bool(*)(unsigned)>(b,0x123be980)(r.configId)?1U:0U;
    r.nativeBlocked=native<bool(*)(unsigned)>(b,0x123beb10)(r.configId)?1U:0U;return true;
}
#if MATERIAL_WRITE || defined(MATERIAL_PRIVATE_TEST)
bool contains(const int* items,unsigned count,int wanted){for(unsigned i=0;i<count;++i)if(items[i]==wanted)return true;return false;}
bool desiredAllowed(const MaterialRow& r){const auto& v=r.desired;return valid(v)&&!r.nativeBlocked&&
    (!v.enableColor||(r.colorAllowed&&contains(r.allowedModes,r.modeCount,v.blendMode)))&&
    (!v.enableMaterial||((v.material==6710||v.material==6711)&&contains(r.allowedMaterials,r.materialCount,v.material)));}
#endif
struct ShaderIds {int enable,color,blend;U petrified,frozen;};
bool ids(U b,ShaderIds& p){
    const U a=ptr(b+0x5a34168),c=ptr(b+0x5a34170),d=ptr(b+0x5a34178);p.petrified=ptr(b+0x5a34208);p.frozen=ptr(b+0x5a34210);
    if(!a||!c||!d||!p.petrified||!p.frozen)return false;using Get=int(*)(void*);
    p.enable=native<Get>(b,0x143d380)(reinterpret_cast<void*>(a));p.color=native<Get>(b,0x143d380)(reinterpret_cast<void*>(c));p.blend=native<Get>(b,0x143d380)(reinterpret_cast<void*>(d));return p.enable!=p.color&&p.enable!=p.blend&&p.color!=p.blend;
}
bool descendant(U b,U child,U root){U seen[64]{};for(unsigned i=0;child&&i<64;++i){if(child==root)return true;for(unsigned j=0;j<i;++j)if(seen[j]==child)return false;if(!ptr(child+0x10))return false;seen[i]=child;child=reinterpret_cast<U>(native<void*(*)(void*)>(b,0x14374b0)(reinterpret_cast<void*>(child)));}return false;}
bool slots(U b,U owner,const ShaderIds& p,MaterialSlot* out,unsigned& count,bool required){
    count=0;const U component=lookup(b,owner,1);if(!component)return !required;
    const U roots[]={ptr(component+0x78),ptr(component+0x30)},type=ptr(b+0x57a11e8);U renderers[64]{};unsigned rendererCount=0;
    if(!type)return false;
    for(unsigned rootIndex=0;rootIndex<2;++rootIndex){const U root=roots[rootIndex];if(!root||!ptr(root+0x10)){if(required)return false;continue;}if(rootIndex&&root==roots[0])continue;
        const U array=reinterpret_cast<U>(native<void*(*)(void*,U,bool)>(b,0x19cbcac0)(reinterpret_cast<void*>(root),type,true));U length=0;
        if(!array||!read(array+0x18,length)||length>64)return false;
        for(U i=0;i<length;++i){const U renderer=ptr(array+0x20+i*8);if(!renderer||!ptr(renderer+0x10)||!isA(ptr(renderer),type))return false;
            bool found=false;for(unsigned j=0;j<rendererCount;++j)if(renderers[j]==renderer)found=true;if(found)continue;if(rendererCount>=64)return false;renderers[rendererCount++]=renderer;
            const U transform=reinterpret_cast<U>(native<void*(*)(void*)>(b,0x1453c10)(reinterpret_cast<void*>(renderer)));
            const U go=reinterpret_cast<U>(native<void*(*)(void*)>(b,0x1453c60)(reinterpret_cast<void*>(renderer)));
            if(!transform||!go||!descendant(b,transform,root))return false;
            const unsigned active=native<bool(*)(void*)>(b,0x19c9b820)(reinterpret_cast<void*>(go))?1U:0U;
            const unsigned enabled=native<bool(*)(void*)>(b,0x19cd26c0)(reinterpret_cast<void*>(renderer))?1U:0U;
            // sharedMaterials is observational; .materials would create clones.
            const U materials=reinterpret_cast<U>(native<void*(*)(void*)>(b,0x19cd29e0)(reinterpret_cast<void*>(renderer)));U n=0;
            if(!materials||!read(materials+0x18,n)||n>kMaterialSlots||n>kMaterialSlots-count)return false;
            for(U k=0;k<n;++k){auto& slot=out[count++];slot.renderer=renderer;slot.material=ptr(materials+0x20+k*8);slot.slot=static_cast<unsigned>(k);slot.active=active;slot.enabled=enabled;
                if(!slot.material||!ptr(slot.material+0x10))return false;auto object=reinterpret_cast<void*>(slot.material);
                // 1282cd90 uses Renderer.SetCustomProperty*, not Material.Set*.
                // Native Renderer+120 is the same block read by GetPropertyBlock
                // (144cb40) and populated by SetCustomPropertyColor (179a3f0 ->
                // 179af20). Use its actual read-only lookup and color getter,
                // exactly as MaterialPropertyBlock.GetColorImpl (144f1e0).
                const U engine=ptr(renderer+0x10),block=ptr(engine+0x120);
                if(block){using Index=int(*)(void*,int,int);auto nativeBlock=reinterpret_cast<void*>(block);
                    // Renderer.GetCustomPropertyFloat calls 179af20, which can
                    // copy its block. Avoid that allocation in observation:
                    // after native typed lookup, read exactly the descriptor
                    // and scalar addresses used by 179a0e0 / 144f040 instead.
                    const int enableIndex=native<Index>(b,0x1607030)(nativeBlock,p.enable,0);
                    if(enableIndex>=0){unsigned descriptor=0;const U entries=ptr(block+0x50),data=ptr(block+0x70);if(enableIndex>65535||!entries||!data||!read(entries+static_cast<U>(enableIndex)*8,descriptor)||!read(data+(descriptor&0xfffff),slot.enable))return false;slot.properties|=1;}
                    const int index=native<Index>(b,0x1607030)(nativeBlock,p.color,1);
                    if(index>=0){slot.properties|=2;float color[4]{};auto returned=native<float*(*)(void*,float*,int)>(b,0x1607290)(nativeBlock,color,index);if(returned!=color)return false;std::memcpy(slot.rgba,color,sizeof(color));}
                    const int blendIndex=native<Index>(b,0x1607030)(nativeBlock,p.blend,0);
                    if(blendIndex>=0){unsigned descriptor=0;const U entries=ptr(block+0x50),data=ptr(block+0x70);if(blendIndex>65535||!entries||!data||!read(entries+static_cast<U>(blendIndex)*8,descriptor)||!read(data+(descriptor&0xfffff),slot.blend))return false;slot.properties|=4;}
                }
                using Keyword=bool(*)(void*,void*);
                slot.keywords=(native<Keyword>(b,0x19cbdc00)(object,reinterpret_cast<void*>(p.petrified))?1U:0U)|(native<Keyword>(b,0x19cbdc00)(object,reinterpret_cast<void*>(p.frozen))?2U:0U);
                if(!std::isfinite(slot.enable)||!std::isfinite(slot.blend))return false;for(float v:slot.rgba)if(!std::isfinite(v))return false;
            }
        }
    }return !required||count>0;
}
#if MATERIAL_WRITE || defined(MATERIAL_PRIVATE_TEST)
bool shaderMatches(const MaterialRow& r){
    if(!r.afterSlots||r.beforeSlots!=r.afterSlots)return false;const auto& s=r.desired;
    const float expected[]={static_cast<float>((s.argb>>16)&255)/255.f,static_cast<float>((s.argb>>8)&255)/255.f,static_cast<float>(s.argb&255)/255.f,static_cast<float>(s.argb>>24)/255.f};
    for(unsigned i=0;i<r.afterSlots;++i){const auto& a=r.afterRender[i];const auto& before=r.beforeRender[i];
        if(a.renderer!=before.renderer||a.slot!=before.slot||a.active!=before.active||a.enabled!=before.enabled)return false;
        if(s.enableColor){if((a.properties&7)!=7||std::fabs(a.enable-1.f)>0.0001f||std::fabs(a.blend-(s.blendMode==6701?1.f:0.f))>0.0001f)return false;for(unsigned j=0;j<4;++j)if(std::fabs(a.rgba[j]-expected[j])>0.0001f)return false;}
        else if((a.properties&1)&&std::fabs(a.enable)>0.0001f)return false;
        const unsigned keywords=s.enableMaterial?(s.material==6711?1U:2U):0U;if(a.keywords!=keywords)return false;
    }return true;
}
struct EditState {U manager,list,items,record,before;unsigned count,version;int base,depth;unsigned char flags[3],dirty;};
bool editState(U base,U global,U component,EditState& s){
    s={};s.manager=ptr(global+0xecd0);s.list=ptr(s.manager+0x18);s.items=ptr(s.list+0x10);U capacity=0;
    if(!s.manager||!s.list||!s.items||!read(s.list+0x18,s.count)||s.count>128||!read(s.items+0x18,capacity)||capacity<s.count||capacity>4096||!read(s.list+0x1c,s.version)||
       !read(s.manager+0x30,s.base)||!read(s.manager+0x34,s.depth)||!read(s.manager+0x28,s.flags)||s.base<0||s.depth<s.base||s.flags[1]||s.flags[2])return false;
    for(unsigned i=0;i<s.count;++i){const U record=ptr(s.items+0x20+i*8);if(!record||ptr(record)!=ptr(base+0x5812cf8)||ptr(record+0x18)!=component||s.record)return false;s.record=record;s.before=ptr(record+0x28);if(!s.before||!read(record+0x30,s.dirty))return false;}return true;
}
bool closeOwned(const GameContextSnapshot& s,MaterialRow& r,const EditState& start){
    EditState now{};if(!r.openCalled||r.closeCalled||!r.transaction||!editState(s.moduleBase,s.global,r.component,now)||now.manager!=start.manager||now.depth!=start.depth+1)return false;
    r.closeCalled=1;native<void(*)(void*)>(s.moduleBase,0xc7bab90)(reinterpret_cast<void*>(r.transaction));if(!editState(s.moduleBase,s.global,r.component,now))return false;
    r.pendingAfter=now.count;r.depthAfter=static_cast<unsigned>(now.depth);r.closed=now.depth==start.depth&&now.count==0?1U:0U;return r.closed!=0;
}
struct MaterialPayload {float alpha;int blend,rgb;unsigned argb;unsigned char enableColor,coverDecorationMaterial,coverDecorationColor,enableMaterial;int material;};
static_assert(sizeof(MaterialPayload)==24 && offsetof(MaterialPayload,enableColor)==16 && offsetof(MaterialPayload,coverDecorationMaterial)==17 && offsetof(MaterialPayload,coverDecorationColor)==18 && offsetof(MaterialPayload,enableMaterial)==19 && offsetof(MaterialPayload,material)==20,"native protobuf payload scalar layout");
bool mutate(const GameContextSnapshot& s,MaterialRow& r,const ShaderIds& p){
    const U b=s.moduleBase;EditState start{},now{};MaterialState fresh{};r.stage=1;
    if(!capture(b,r,fresh)||std::memcmp(&fresh,&r.before,sizeof(fresh))||!catalog(b,r)||!desiredAllowed(r))return false;
    if(!editState(b,s.global,r.component,start)||start.count||start.depth!=start.base)return false;
    // Allocate a real native protobuf instance, not a fabricated object/vtable.
    // Only its newly allocated scalar payload is filled by this module. The
    // existing component is changed exclusively by native ed54450.
    const U klass=ptr(b+0x57d7620);if(!klass)return false;
    r.payload=reinterpret_cast<U>(native<void*(*)(void*)>(b,0x52aa00)(reinterpret_cast<void*>(klass)));
    if(!r.payload||ptr(r.payload)!=klass)return false;
    const auto& d=r.desired;const MaterialPayload payload{d.alphaPercent,d.blendMode,d.rgb,d.argb,d.enableColor,d.coverDecorationMaterial,d.coverDecorationColor,d.enableMaterial,d.material};
    std::memcpy(reinterpret_cast<void*>(r.payload+0x18),&payload,sizeof(payload));
    r.pendingBefore=start.count;r.depthBefore=static_cast<unsigned>(start.depth);r.stage=2;r.openCalled=1;r.uncertain=1;
    r.transaction=reinterpret_cast<U>(native<void*(*)(void*,bool,bool)>(b,0xe827750)(nullptr,false,false));if(!r.transaction)return false;
    r.stage=3;r.snapshotCalled=1;native<void(*)(void*,void*,int)>(b,0x107abdf0)(reinterpret_cast<void*>(r.component),nullptr,0);
    if(!editState(b,s.global,r.component,now)||now.manager!=start.manager||now.depth!=start.depth+1||now.count!=1||!now.record||!now.before||now.dirty){closeOwned(s,r,start);return false;}
    r.pendingSnapshot=now.count;r.record=now.record;r.beforeBlob=now.before;r.stage=4;r.deserializeCalled=1;
    const U returned=reinterpret_cast<U>(native<void*(*)(void*,void*)>(b,0xed54450)(reinterpret_cast<void*>(r.payload),reinterpret_cast<void*>(r.component)));
    if(returned!=r.component||!capture(b,r,r.after)||std::memcmp(&r.after,&r.desired,sizeof(r.after))){closeOwned(s,r,start);return false;}
    r.readbackVerified=1;r.stage=5;r.notifyCalled=1;native<void(*)(void*,void*)>(b,0x9c26c70)(reinterpret_cast<void*>(start.manager),reinterpret_cast<void*>(r.component));
    if(!editState(b,s.global,r.component,now)||now.count!=1||now.record!=r.record||now.before!=r.beforeBlob||now.dirty!=1){closeOwned(s,r,start);return false;}
    r.stage=6;if(!closeOwned(s,r,start))return false;r.stage=7;r.refreshCalled=1;
    native<void(*)(void*)>(b,0xe549580)(reinterpret_cast<void*>(r.component));
    if(!capture(b,r,r.after)||std::memcmp(&r.after,&r.desired,sizeof(r.after))||!slots(b,r.owner,p,r.afterRender,r.afterSlots,true)||!shaderMatches(r))return false;
    r.guardAfter=hash(r.afterRender,r.afterSlots*sizeof(MaterialSlot));r.shaderVerified=1;r.stage=8;r.uncertain=0;r.status=0;return true;
}
#endif
bool guards(const GameContextSnapshot& s,MaterialReceipt* o,const ShaderIds& p,bool after){
    const U b=s.moduleBase;
    for(unsigned i=0;i<s.entityCaptured;++i){auto& g=o->guards[i];const auto& entity=s.entities[i];
        const U component=lookup(b,entity.owner,22);MaterialState state{};
        if(component&&(ptr(component)!=ptr(b+0x57caca0)||ptr(component+0x20)!=entity.owner||!read(component+0x30,state)||!valid(state)))return false;
        MaterialSlot collected[kMaterialSlots]{};unsigned n=0;if(!slots(b,entity.owner,p,collected,n,false))return false;
        const U digest=hash(collected,n*sizeof(MaterialSlot));
        if(!after){g.entityId=entity.id;g.owner=entity.owner;g.component=component;g.before=state;g.rendererHashBefore=digest;
            for(unsigned j=0;j<o->count;++j)if(o->rows[j].entityId==entity.id)g.target=1;
            if(!g.target){for(unsigned j=0;j<n;++j)for(unsigned target=0;target<o->count;++target)for(unsigned k=0;k<o->rows[target].beforeSlots;++k)
                if(collected[j].material==o->rows[target].beforeRender[k].material){o->sharedMaterialsObserved=1;}}
            ++o->guardCount;
        }else{if(g.entityId!=entity.id||g.owner!=entity.owner||g.component!=component)return false;g.after=state;g.rendererHashAfter=digest;
            if(!g.target&&(std::memcmp(&g.before,&g.after,sizeof(state))||g.rendererHashBefore!=g.rendererHashAfter))return false;}
    }return true;
}
void execute(const GameContextSnapshot& s,MaterialReceipt* o){
    o->status=1;o->stage=1;o->mode=MATERIAL_WRITE;o->count=MATERIAL_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||!o->count||o->count>kMaterialBatch||
       !scene(s,*reinterpret_cast<const GameContextSnapshot*>(MATERIAL_EXPECTED))||!code(s,o))return;
    const U b=s.moduleBase;static constexpr unsigned groups[]={MATERIAL_USAGE_GROUPS};for(auto group:groups){native<void(*)(unsigned)>(b,0x524250)(group);++o->nativeCalls;}
    ShaderIds properties{};if(!ids(b,properties))return;static constexpr MaterialRequest requests[]={MATERIAL_REQUESTS};o->stage=2;
    for(unsigned i=0;i<o->count;++i){auto& r=o->rows[i];const auto& q=requests[i];r.entityId=q.entityId;r.mask=q.mask;r.status=1;r.desired=q.desired;
        for(unsigned j=0;j<i;++j)if(o->rows[j].entityId==r.entityId)return;
        unsigned found=0;for(unsigned j=0;j<s.entityCaptured;++j)if(s.entities[j].id==r.entityId){r.owner=s.entities[j].owner;r.configId=s.entities[j].configId;++found;}
        if(found!=1||!primitive(r.configId)||!capture(b,r,r.before)||!catalog(b,r)||!slots(b,r.owner,properties,r.beforeRender,r.beforeSlots,true))return;
        r.guardBefore=hash(r.beforeRender,r.beforeSlots*sizeof(MaterialSlot));
#if MATERIAL_WRITE
        if(!q.mask||q.mask>127||q.configId!=r.configId||q.expectedComponent!=r.component||std::memcmp(&r.before,&q.expected,sizeof(r.before))||!desiredAllowed(r))return;
#else
        r.desired=r.before;r.after=r.before;r.readbackVerified=1;r.status=0;
#endif
    }
    // Color changes per-renderer blocks; 1282d0a0 clones material instances.
    // Observe all non-target renderers and recheck both pointer and properties.
    if(!guards(s,o,properties,false))return;o->stage=3;
#if MATERIAL_WRITE
    for(unsigned i=0;i<o->count;++i){if(!mutate(s,o->rows[i],properties))return;++o->completed;}
#else
    for(unsigned i=0;i<o->count;++i){auto& r=o->rows[i];if(!capture(b,r,r.after)||std::memcmp(&r.before,&r.after,sizeof(r.before))||!slots(b,r.owner,properties,r.afterRender,r.afterSlots,true))return;
        r.guardAfter=hash(r.afterRender,r.afterSlots*sizeof(MaterialSlot));if(r.guardBefore!=r.guardAfter)return;++o->completed;}
#endif
    o->stage=4;if(!guards(s,o,properties,true))return;o->guardsUnchanged=1;
    // Re-read every target after all edits: later callbacks must not undo an
    // earlier target or change a shared target material silently.
    for(unsigned i=0;i<o->count;++i){auto& r=o->rows[i];MaterialSlot finalSlots[kMaterialSlots]{};unsigned n=0;MaterialState finalState{};
        if(!capture(b,r,finalState)||std::memcmp(&finalState,&r.after,sizeof(finalState))||!slots(b,r.owner,properties,finalSlots,n,true)||n!=r.afterSlots||std::memcmp(finalSlots,r.afterRender,n*sizeof(MaterialSlot)))return;}
    CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=scene(s,o->afterScene)?1U:0U;if(!o->sceneUnchanged)return;o->status=0;o->stage=5;
}
}
void ExecuteMaterial(const GameContextSnapshot* s,MaterialReceipt* o) noexcept {
    if(!s||!o)return;std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=1;
    __try{execute(*s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
