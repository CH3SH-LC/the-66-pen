#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_static.h"
#include <cstring>
#if HR_ACTION != 16 || !STATIC_REVIEWED || !GS_REVIEWED_ACTION_PROFILE || TRANSFORM_WRITE != 0
#error "Static conversion requires its own reviewed contract and read-only pose capture"
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
bool code(const GameContextSnapshot& s,StaticReceipt* o){
    constexpr std::uint32_t rvas[]={STATIC_CODE_RVAS};
    constexpr unsigned char heads[][32]={STATIC_CODE_BYTES};
    unsigned char bytes[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)
        if(!memory(s.moduleBase+rvas[i],bytes,32)||std::memcmp(bytes,heads[i],32)){
            o->failedRva=rvas[i];return false;
        }
    constexpr std::uint32_t flags[]={STATIC_HOTFIX_RVAS};
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
bool capture(const GameContextSnapshot& s,StaticRow& row,unsigned& flag,unsigned& attached){
    // Same exact generic class resolution and kind-1 lookup as 97eb360.
    const U method=ptr(s.moduleBase+0x596c498),context=ptr(method+0x10),expected=ptr(context+0x10);
    const U c=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,int)>(s.moduleBase+0x8678480)(
        reinterpret_cast<void*>(row.owner),1));
    unsigned char value=255;const U list=ptr(row.owner+0x68);
    if(!expected||!c||ptr(c)!=expected||!read(c+0x44,value)||value>1||
       !list||!read(list+0x18,attached)||attached>128)return false;
    if(row.component&&(row.component!=c||row.klass!=expected))return false;
    row.component=c;row.klass=expected;flag=value;return true;
}
void execute(const GameContextSnapshot& s,StaticReceipt* o){
    o->status=1;o->stage=1;o->mode=STATIC_WRITE;o->count=TRANSFORM_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||
       GetTickCount64()>=HR_DEADLINE||o->count<1||o->count>kTransformBatch||!code(s,o))return;
    // This validates complete scene identity, editor mode, build, stack, and poses.
    ExecuteTransform(&s,&o->beforePose);
    if(o->beforePose.status||o->beforePose.seh||o->beforePose.completed!=o->count||
       o->beforePose.sceneUnchanged!=1)return;
    constexpr unsigned groups[]={STATIC_USAGE_GROUPS};
    for(auto g:groups)reinterpret_cast<void(*)(unsigned)>(s.moduleBase+0x524250)(g);
    o->stage=2;
    for(unsigned i=0;i<o->count;++i){
        auto& r=o->rows[i];const auto& pose=o->beforePose.rows[i];
        r.entityId=pose.entityId;r.owner=pose.owner;r.status=1;
        if(!capture(s,r,r.beforeFlag,r.attachedBefore)||!undo(s,r.pendingBefore,r.depthBefore))return;
#if STATIC_WRITE
        if(r.beforeFlag!=0)return;
#endif
        r.afterFlag=r.beforeFlag;r.attachedAfter=r.attachedBefore;
        r.pendingAfter=r.pendingBefore;r.depthAfter=r.depthBefore;
    }
    o->stage=3;
    for(unsigned i=0;i<o->count;++i){
        auto& r=o->rows[i];
#if STATIC_WRITE
        unsigned flag=0,attached=0,pending=0;int depth=0;
        if(!code(s,o)||!capture(s,r,flag,attached)||flag!=r.beforeFlag||
           attached!=r.attachedBefore||!undo(s,pending,depth)||depth!=r.depthBefore)return;
        r.called=1;++o->mutationCalls;
        // Actual drag-static/template-dropdown route. It owns its undo transaction,
        // removes behavior components and sets the basic component's static flag.
        r.returned=reinterpret_cast<bool(*)(void*,bool)>(s.moduleBase+0x97eb360)(
            reinterpret_cast<void*>(r.owner),true)?1U:0U;
        if(!capture(s,r,r.afterFlag,r.attachedAfter)||!undo(s,r.pendingAfter,r.depthAfter)||
           r.afterFlag!=1||r.attachedAfter!=0||r.depthAfter!=r.depthBefore||!r.returned)return;
#endif
        r.status=0;++o->completed;
    }
    o->stage=4;ExecuteTransform(&s,&o->afterPose);
    if(o->afterPose.status||o->afterPose.seh||o->afterPose.completed!=o->count||
       o->afterPose.sceneUnchanged!=1)return;
    for(unsigned i=0;i<o->count;++i){
        const auto& a=o->beforePose.rows[i];const auto& b=o->afterPose.rows[i];
        if(a.entityId!=b.entityId||a.owner!=b.owner||a.unity!=b.unity||a.parent!=b.parent||
           std::memcmp(&a.before,&b.after,sizeof(TransformPose)))return;
    }
    o->sceneUnchanged=1;o->status=0;o->stage=5;
}
}
void ExecuteStatic(const GameContextSnapshot* s,StaticReceipt* o) noexcept{
    if(!s||!o)return;
    std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=1;
    __try{execute(*s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
