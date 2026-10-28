#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_assembly.h"
#include <cstring>
#include <cmath>
#if HR_ACTION != 17 || !ASSEMBLY_REVIEWED || !GS_REVIEWED_ACTION_PROFILE || TRANSFORM_WRITE != 0
#error "Assembly requires its own pinned contract and read-only preflight"
#endif
namespace {
using U=std::uint64_t;
bool memory(U at,void* out,std::size_t n) noexcept {
    if(!out||!n||at<0x10000||at>=0x800000000000ULL||n>0x800000000000ULL-at)return false;
    MEMORY_BASIC_INFORMATION r{};
    if(VirtualQuery(reinterpret_cast<void*>(at),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||
       (r.Protect&(PAGE_NOACCESS|PAGE_GUARD))||n>r.RegionSize-(at-reinterpret_cast<U>(r.BaseAddress)))return false;
    __try{std::memcpy(out,reinterpret_cast<void*>(at),n);return true;}
    __except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
template<class T>bool read(U p,T& v){return memory(p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&v>=0x10000&&v<0x800000000000ULL?v:0;}
bool code(const GameContextSnapshot& s,AssemblyReceipt* o){
    constexpr std::uint32_t rvas[]={ASSEMBLY_CODE_RVAS};
    constexpr unsigned char heads[][32]={ASSEMBLY_CODE_BYTES};
    unsigned char bytes[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)
        if(!memory(s.moduleBase+rvas[i],bytes,32)||std::memcmp(bytes,heads[i],32)){
            o->failedRva=rvas[i];return false;
        }
    constexpr std::uint32_t flags[]={ASSEMBLY_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(s.moduleBase+r,v)||v){
        o->failedRva=r;o->failedValue=v;return false;
    }}
    return true;
}
bool undo(const GameContextSnapshot& s,unsigned& pending,int& depth){
    const U manager=ptr(s.global+0xecd0),list=ptr(manager+0x18);
    int base=0;unsigned char flags[3]{};
    return manager&&list&&read(list+0x18,pending)&&pending==0&&
        read(manager+0x30,base)&&read(manager+0x34,depth)&&base>=0&&depth==base&&
        read(manager+0x28,flags)&&!flags[1]&&!flags[2];
}
void diagnoseUndo(const GameContextSnapshot& s,AssemblyReceipt* o){
    o->undoManager=ptr(s.global+0xecd0);
    const U list=ptr(o->undoManager+0x18),items=ptr(list+0x10);
    if(!o->undoManager||!list||!items)return;
    read(list+0x18,o->undoCount);read(o->undoManager+0x30,o->undoBase);
    read(o->undoManager+0x34,o->undoDepth);read(o->undoManager+0x28,o->undoFlags);
    if(o->undoCount!=1)return;
    o->undoRecord=ptr(items+0x20);o->undoClass=ptr(o->undoRecord);
    o->undoTarget=ptr(o->undoRecord+0x18);o->undoBefore=ptr(o->undoRecord+0x28);
    unsigned char dirty=0;read(o->undoRecord+0x30,dirty);o->undoDirty=dirty;
    o->undoFunction0=ptr(o->undoClass+0xf0);o->undoFunction1=ptr(o->undoClass+0x120);
    o->undoFunction2=ptr(o->undoClass+0x130);
}
U component(const GameContextSnapshot& s,U owner,int kind,U slot){
    const U method=ptr(s.moduleBase+slot),context=ptr(method+0x10),expected=ptr(context+0x10);
    const U c=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,int)>(s.moduleBase+0x8678480)(
        reinterpret_cast<void*>(owner),kind));
    return expected&&c&&ptr(c)==expected&&ptr(c+0x20)==owner?c:0;
}
bool scenery(const GameContextSnapshot& s,U owner){
    const U c=component(s,owner,1,0x596c498),list=ptr(owner+0x68);
    unsigned char flag=0;unsigned attached=9999;
    return c&&read(c+0x44,flag)&&flag==1&&list&&read(list+0x18,attached)&&attached==0;
}
bool accessories(const GameContextSnapshot& s,U owner,U& c,unsigned& count,U& items){
    c=component(s,owner,40,0x596c090);
    const U ids=ptr(c+0x38),list=ptr(c+0x40);
    items=ptr(list+0x10);unsigned idCount=9999;U capacity=0;
    return c&&ids&&list&&items&&read(list+0x18,count)&&count<=999&&
        read(ids+0x18,idCount)&&idCount==count&&read(items+0x18,capacity)&&
        capacity>=count&&capacity<=4096;
}
bool world(const GameContextSnapshot& s,U owner,AssemblyWorld& w){
    const U c=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,int)>(s.moduleBase+0x867f250)(
        reinterpret_cast<void*>(owner),1));
    const U unity=ptr(c+0x78);
    if(!c||ptr(c)!=ptr(s.moduleBase+0x57c8eb8)||ptr(c+0x20)!=owner||!unity||!ptr(unity+0x10))return false;
    reinterpret_cast<void(*)(void*,TransformVec3*)>(s.moduleBase+0x1436d00)(
        reinterpret_cast<void*>(unity),&w.position);
    // Same hidden return buffers as the native scene-to-accessory operation.
    reinterpret_cast<void(*)(TransformVec3*,void*)>(s.moduleBase+0x74ec720)(
        &w.rotation,reinterpret_cast<void*>(c));
    reinterpret_cast<void(*)(TransformVec3*,void*)>(s.moduleBase+0x74f0610)(
        &w.scale,reinterpret_cast<void*>(c));
    const auto values=reinterpret_cast<const float*>(&w);
    for(unsigned i=0;i<9;++i)if(!std::isfinite(values[i]))return false;
    return w.scale.x>0&&w.scale.y>0&&w.scale.z>0;
}
bool nearVec(const TransformVec3& a,const TransformVec3& b){
    return std::fabs(a.x-b.x)<=0.003f&&std::fabs(a.y-b.y)<=0.003f&&std::fabs(a.z-b.z)<=0.003f;
}
void quaternion(const TransformVec3& e,double q[4]){
    constexpr double d=3.14159265358979323846/360.;
    const double x=e.x*d,y=e.y*d,z=e.z*d;
    const double sx=std::sin(x),cx=std::cos(x),sy=std::sin(y),cy=std::cos(y),sz=std::sin(z),cz=std::cos(z);
    q[0]=cy*sx*cz+sy*cx*sz;q[1]=sy*cx*cz-cy*sx*sz;
    q[2]=cy*cx*sz-sy*sx*cz;q[3]=cy*cx*cz+sy*sx*sz;
}
bool same(const AssemblyWorld& a,const AssemblyWorld& b){
    double q[4],r[4],dot=0;quaternion(a.rotation,q);quaternion(b.rotation,r);
    for(unsigned i=0;i<4;++i)dot+=q[i]*r[i];
    return nearVec(a.position,b.position)&&nearVec(a.scale,b.scale)&&std::fabs(dot)>=0.999999;
}
bool scene(const GameContextSnapshot& a,const GameContextSnapshot& b,AssemblyReceipt* o){
    if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||b.status!=GS_OK||
       (b.flags&1951)!=1951||(b.flags&96)||b.reserved!=TRANSFORM_LEVEL||b.entityRejected||
       b.entityCaptured!=b.entityValidEntries||a.entityCaptured!=b.entityCaptured+o->mutationCalls||
       a.currentContext!=b.currentContext||a.global!=b.global||a.moduleBase!=b.moduleBase||
       a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||
       b.entityVersionBefore!=b.entityVersionAfter||std::memcmp(a.origin,b.origin,sizeof(a.origin)))return false;
    for(unsigned i=0;i<a.entityCaptured;++i){
        const auto& x=a.entities[i];bool removed=false;
        for(unsigned k=0;k<o->count;++k)if(o->rows[k].called&&o->rows[k].sourceId==x.id)removed=true;
        unsigned found=0;
        for(unsigned j=0;j<b.entityCaptured;++j){const auto& y=b.entities[j];
            if(x.id==y.id){++found;if(x.owner!=y.owner||x.config!=y.config||x.context!=y.context||
                x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;}}
        if(found!=(removed?0U:1U))return false;
    }return true;
}
void execute(const GameContextSnapshot& s,AssemblyReceipt* o){
    o->status=1;o->stage=1;o->mode=ASSEMBLY_WRITE;o->count=ASSEMBLY_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||
       GetTickCount64()>=HR_DEADLINE||o->count<1||o->count>64||!code(s,o))return;
    ExecuteTransform(&s,&o->beforePose);
    if(o->beforePose.status||o->beforePose.seh||o->beforePose.completed!=TRANSFORM_COUNT||
       o->beforePose.sceneUnchanged!=1)return;
    constexpr unsigned groups[]={ASSEMBLY_USAGE_GROUPS};
    for(auto g:groups)reinterpret_cast<void(*)(unsigned)>(s.moduleBase+0x524250)(g);
    diagnoseUndo(s,o);
#if ASSEMBLY_WRITE
    // The editor can leave one completed property record pending even after
    // saving. Do not erase it or fold it into our geometry operation. Close a
    // separate, owned, empty native transaction so the game's 9c270a0 commits
    // it to normal undo history. An active or unrecognized record is refused.
    if(o->undoCount){
        if(o->undoCount!=1||o->undoBase!=o->undoDepth||o->undoFlags||
           !o->undoTarget||!o->undoBefore||o->undoDirty>1||
           o->undoClass!=ptr(s.moduleBase+0x5812cf8)){o->failedValue=211;return;}
        o->undoReserved=1;
        const U transaction=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,bool,bool)>(
            s.moduleBase+0xe827750)(nullptr,false,false));
        if(!transaction)return;
        reinterpret_cast<void(*)(void*)>(s.moduleBase+0xc7bab90)(reinterpret_cast<void*>(transaction));
        unsigned pending=9999;int depth=-1;
        if(!undo(s,pending,depth)||depth!=static_cast<int>(o->undoDepth))return;
        o->undoReserved=2;
        // A native commit cannot substitute for the complete unchanged-scene
        // and selected-pose preflight.
        ExecuteTransform(&s,&o->beforePose);
        if(o->beforePose.status||o->beforePose.seh||o->beforePose.sceneUnchanged!=1)return;
    }
#endif
    struct Pair{unsigned sourceId,hostId;};constexpr Pair pairs[]={ASSEMBLY_PAIRS};
    o->stage=2;
    for(unsigned i=0;i<o->count;++i){
        auto& r=o->rows[i];r.sourceId=pairs[i].sourceId;r.hostId=pairs[i].hostId;r.status=1;
        if(r.sourceId==r.hostId)return;
        for(unsigned j=0;j<o->count;++j)
            if(r.sourceId==pairs[j].hostId||(j<i&&r.sourceId==pairs[j].sourceId))return;
        for(unsigned j=0;j<s.entityCaptured;++j){
            if(s.entities[j].id==r.sourceId){r.source=s.entities[j].owner;r.modelId=s.entities[j].configId;}
            if(s.entities[j].id==r.hostId)r.host=s.entities[j].owner;
        }
        U sourceComponent=0,sourceItems=0,items=0;unsigned sourceCount=9999;
        AssemblyWorld host{};
        if(!r.source||!r.host){o->failedValue=201;return;}
        if(!scenery(s,r.source)){o->failedValue=202;return;}
        if(!scenery(s,r.host)){o->failedValue=203;return;}
        if(!accessories(s,r.source,sourceComponent,sourceCount,sourceItems)||sourceCount){o->failedValue=204;return;}
        if(!accessories(s,r.host,r.component,r.beforeCount,items)||r.beforeCount>934){o->failedValue=205;return;}
        if(!world(s,r.source,r.before)){o->failedValue=207;return;}
        if(!world(s,r.host,host)){o->failedValue=208;return;}
        if(std::fabs(host.scale.x-host.scale.y)>.0001f||std::fabs(host.scale.x-host.scale.z)>.0001f){o->failedValue=209;return;}
        const float dx=host.position.x-r.before.position.x,dy=host.position.y-r.before.position.y,dz=host.position.z-r.before.position.z;
        if(dx*dx+dz*dz>32*32||std::fabs(dy)>24){o->failedValue=210;return;}
        if(!undo(s,r.pendingBefore,r.depthBefore))o->failedValue=206;
        r.after=r.before;r.afterCount=r.beforeCount;r.pendingAfter=0;r.depthAfter=r.depthBefore;
    }
    if(o->failedValue)return;
    o->stage=3;
    for(unsigned i=0;i<o->count;++i){
        auto& r=o->rows[i];
#if ASSEMBLY_WRITE
        U c=0,items=0;unsigned pending=9999,currentCount=9999;int depth=-1;AssemblyWorld current{};
        if(!code(s,o)||!world(s,r.source,current)||!same(r.before,current)||
           !accessories(s,r.host,c,currentCount,items)||c!=r.component||currentCount>=999||
           !undo(s,pending,depth)||depth!=r.depthBefore)return;
        r.beforeCount=currentCount;r.called=1;++o->mutationCalls;
        // Official "select from scene": clone config, attach, preserve world TRS,
        // and delete the old independent entity, all inside the native undo scope.
        r.accessory=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,void*)>(s.moduleBase+0x97f7f90)(
            reinterpret_cast<void*>(r.source),reinterpret_cast<void*>(r.host)));
        if(!r.accessory||!undo(s,r.pendingAfter,r.depthAfter)||r.depthAfter!=r.depthBefore||
           !accessories(s,r.host,c,r.afterCount,items)||c!=r.component||r.afterCount!=r.beforeCount+1||
           !read(r.accessory+0x1c,r.accessoryId)||!r.accessoryId||
           !world(s,r.accessory,r.after)||!same(r.before,r.after))return;
        unsigned found=0;for(unsigned j=0;j<r.afterCount;++j)if(ptr(items+0x20+j*8)==r.accessory)++found;
        if(found!=1)return;
#endif
        r.status=0;++o->completed;
    }
    o->stage=4;CaptureGameContextSnapshot(&o->afterScene);
    if(!scene(s,o->afterScene,o))return;
    o->sceneUnchanged=1;o->status=0;o->stage=5;
}
}
void ExecuteAssembly(const GameContextSnapshot* s,AssemblyReceipt* o) noexcept{
    if(!s||!o)return;
    std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=2;
    __try{execute(*s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
