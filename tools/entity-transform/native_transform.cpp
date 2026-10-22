#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_transform.h"
#include <cmath>
#include <cstring>
#if HR_ACTION != 13 || !TRANSFORM_REVIEWED || !GS_REVIEWED_ACTION_PROFILE
#error "Transform requires its dedicated, pinned operation contract"
#endif
#if TRANSFORM_WRITE != 0 && TRANSFORM_WRITE != 1
#error "Transform mode must be inspect (0) or set (1)"
#endif
namespace {
using U=std::uint64_t;
bool memory(U at,void* out,std::size_t n) noexcept {
    if(!out||!n||at<0x10000||at>=0x800000000000ULL||n>0x800000000000ULL-at)return false;
    std::size_t done=0;
    while(done<n){MEMORY_BASIC_INFORMATION r{};const auto p=at+done;
        if(VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||(r.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
        const auto left=r.RegionSize-static_cast<std::size_t>(p-reinterpret_cast<U>(r.BaseAddress));const auto part=n-done<left?n-done:left;
        __try{std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(p),part);}__except(EXCEPTION_EXECUTE_HANDLER){return false;}done+=part;
    }return true;
}
template<class T> bool read(U p,T& v){return memory(p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&v>=0x10000&&v<0x800000000000ULL?v:0;}
bool finite(const TransformVec3& v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
bool vectorsNear(const TransformVec3& a,const TransformVec3& b){return std::fabs(a.x-b.x)<=0.0001f&&std::fabs(a.y-b.y)<=0.0001f&&std::fabs(a.z-b.z)<=0.0001f;}
#if TRANSFORM_WRITE
bool sameRequested(const TransformRow& r){
    return vectorsNear(r.after.localPosition,r.desired.localPosition)&&vectorsNear(r.after.rotationDegrees,r.desired.rotationDegrees)&&vectorsNear(r.after.scale,r.desired.scale)&&
        (r.frameKind==2||vectorsNear(r.after.worldPosition,r.desired.worldPosition));
}
#endif
bool scene(const GameContextSnapshot& a,const GameContextSnapshot& b){
    if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||a.status!=GS_OK||b.status!=GS_OK||
       (a.flags&1951)!=1951||(b.flags&1951)!=1951||a.reserved!=TRANSFORM_LEVEL||b.reserved!=TRANSFORM_LEVEL||
       a.entityRejected||b.entityRejected||a.entityCaptured!=a.entityValidEntries||b.entityCaptured!=b.entityValidEntries||
       a.entityCaptured!=b.entityCaptured||a.entityCaptured>kMaxEntities||a.currentContext!=b.currentContext||a.global!=b.global||
       a.moduleBase!=b.moduleBase||a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||
       a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter||std::memcmp(a.origin,b.origin,sizeof(a.origin)))return false;
    for(unsigned i=0;i<a.entityCaptured;++i){const auto& x=a.entities[i];const auto& y=b.entities[i];
        if(x.id!=y.id||x.owner!=y.owner||x.config!=y.config||x.context!=y.context||x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;}
    return true;
}
bool code(const GameContextSnapshot& s,TransformReceipt* o){
    if(s.moduleBase!=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"))||s.peTimestamp!=HR_GAME_TIMESTAMP||s.peImageSize!=HR_GAME_IMAGE_SIZE)return false;
    static constexpr std::uint32_t rvas[]={TRANSFORM_CODE_RVAS};static constexpr unsigned char expected[][32]={TRANSFORM_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(s.moduleBase+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->failedRva=rvas[i];return false;}
    static constexpr std::uint32_t flags[]={GS_PROFILE_HOTFIX_RVAS,TRANSFORM_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(s.moduleBase+r,v)||v){o->failedRva=r;o->failedValue=v;return false;}}
    return true;
}
// 867f250 is the game's kind->runtime-component lookup, not the editor's
// derived configuration list. Its result must be exact kind1 / HNFCGIHKALN.
bool capture(const GameContextSnapshot& s,TransformRow& row,TransformPose& out){
    const U base=s.moduleBase;
    const U c=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,int)>(base+0x867f250)(reinterpret_cast<void*>(row.owner),1));
    if(!c||ptr(c)!=ptr(base+0x57c8eb8)||ptr(c+0x20)!=row.owner)return false;
    const U klass=ptr(c),unity=ptr(c+0x78);
    if(ptr(klass+0x120)!=base+0x74f2800||ptr(klass+0x130)!=base+0xa713db0||!unity||!ptr(unity+0x10))return false;
    const U parent=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(base+0x14374b0)(reinterpret_cast<void*>(unity)));
    // Only direct children use the context translation equation. For nested
    // children we read world position but make no world-target prediction;
    // their native local setter and local serialization remain valid.
    if(!parent)return false;
    const unsigned frame=parent==ptr(s.currentContext+0x10)?1U:2U;
    using GetVector=void(*)(void*,TransformVec3*);
    reinterpret_cast<GetVector>(base+0x1436d90)(reinterpret_cast<void*>(unity),&out.localPosition);
    reinterpret_cast<GetVector>(base+0x1436d00)(reinterpret_cast<void*>(unity),&out.worldPosition);
    reinterpret_cast<GetVector>(base+0x1436f70)(reinterpret_cast<void*>(unity),&out.scale);
    if(!read(c+0xe0,out.rotationDegrees)||!finite(out.localPosition)||!finite(out.worldPosition)||!finite(out.rotationDegrees)||!finite(out.scale))return false;
    TransformVec3 world{out.localPosition.x+s.origin[0],out.localPosition.y+s.origin[1],out.localPosition.z+s.origin[2]};
    if((frame==1&&!vectorsNear(world,out.worldPosition))||out.scale.x<=0||out.scale.y<=0||out.scale.z<=0)return false;
    if(row.component&&(row.component!=c||row.klass!=klass||row.unity!=unity||row.parent!=parent))return false;
    if(row.frameKind&&row.frameKind!=frame)return false;
    row.component=c;row.klass=klass;row.unity=unity;row.parent=parent;row.frameKind=frame;return true;
}
#if TRANSFORM_WRITE
struct EditState {U manager,list,items,record,before;std::uint32_t count,version;int base,depth;unsigned char flags[3],dirty;};
bool state(U base,U global,U component,EditState& s){
    s={};s.manager=ptr(global+0xecd0);s.list=ptr(s.manager+0x18);s.items=ptr(s.list+0x10);U capacity=0;
    if(!s.manager||!s.list||!s.items||!read(s.list+0x18,s.count)||s.count>128||!read(s.items+0x18,capacity)||capacity<s.count||capacity>4096||
       !read(s.list+0x1c,s.version)||!read(s.manager+0x30,s.base)||!read(s.manager+0x34,s.depth)||!read(s.manager+0x28,s.flags)||
       s.base<0||s.depth<s.base||s.flags[1]||s.flags[2])return false;
    for(unsigned i=0;i<s.count;++i){const U record=ptr(s.items+0x20+i*8);
        if(!record||ptr(record)!=ptr(base+0x5812cf8)||ptr(record+0x18)!=component||s.record)return false;
        s.record=record;s.before=ptr(record+0x28);if(!s.before||!read(record+0x30,s.dirty))return false;
    }return true;
}
bool closeOwned(const GameContextSnapshot& s,TransformRow& r,const EditState& start){
    EditState now{};if(!r.openCalled||r.closeCalled||!r.transaction||!state(s.moduleBase,s.global,r.component,now)||now.manager!=start.manager||now.depth!=start.depth+1)return false;
    r.closeCalled=1;reinterpret_cast<void(*)(void*)>(s.moduleBase+0xc7bab90)(reinterpret_cast<void*>(r.transaction));
    if(!state(s.moduleBase,s.global,r.component,now))return false;
    r.pendingAfter=now.count;r.depthAfter=static_cast<unsigned>(now.depth);r.closed=now.depth==start.depth&&now.count==0?1U:0U;return r.closed!=0;
}
bool mutate(const GameContextSnapshot& s,TransformRow& r){
    const U b=s.moduleBase;EditState start{},current{};r.stage=1;
    TransformPose currentPose{};
    // Earlier entities can emit callbacks. Recheck this target immediately before
    // opening its transaction as well as in the all-target preflight.
    if(!capture(s,r,currentPose)||std::memcmp(&currentPose,&r.before,sizeof(currentPose)))return false;
    if(!state(b,s.global,r.component,start)||start.count||start.depth!=start.base)return false;
    r.pendingBefore=start.count;r.depthBefore=static_cast<unsigned>(start.depth);
    r.stage=2;r.openCalled=1;r.uncertain=1;
    r.transaction=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,bool,bool)>(b+0xe827750)(nullptr,false,false));
    if(!r.transaction)return false;
    r.stage=3;r.snapshotCalled=1;
    reinterpret_cast<void(*)(void*,void*,int)>(b+0x107abdf0)(reinterpret_cast<void*>(r.component),reinterpret_cast<void*>(ptr(b+0x5a1d3b8)),0);
    if(!state(b,s.global,r.component,current)||current.manager!=start.manager||current.depth!=start.depth+1||current.count!=1||!current.record||!current.before||current.dirty){closeOwned(s,r,start);return false;}
    r.pendingSnapshot=current.count;r.record=current.record;r.beforeBlob=current.before;
    // Exact same three calls and true notification flag as13df7bb0. Native
    // setters update both Unity and cached serialization fields. No field write.
    using Set=void(*)(void*,const TransformVec3*,bool);
    r.stage=4;auto object=reinterpret_cast<void*>(r.component);
    if(r.mask&1){r.called|=1;reinterpret_cast<Set>(b+0x74ef170)(object,&r.desired.localPosition,true);}
    if(r.mask&2){r.called|=2;reinterpret_cast<Set>(b+0x74f1820)(object,&r.desired.rotationDegrees,true);}
    if(r.mask&4){r.called|=4;reinterpret_cast<Set>(b+0x74ecfc0)(object,&r.desired.scale,true);}
    r.stage=5;
    if(!capture(s,r,r.after)||!sameRequested(r)){closeOwned(s,r,start);return false;}
    r.readbackVerified=1;r.stage=6;r.notifyCalled=1;
    reinterpret_cast<void(*)(void*,void*)>(b+0x9c26c70)(reinterpret_cast<void*>(start.manager),object);
    if(!state(b,s.global,r.component,current)||current.count!=1||current.record!=r.record||current.before!=r.beforeBlob||current.dirty!=1){closeOwned(s,r,start);return false;}
    r.stage=7;if(!closeOwned(s,r,start))return false;
    if(!capture(s,r,r.after)||!sameRequested(r))return false;
    r.stage=8;r.uncertain=0;r.status=0;return true;
}
#endif
void execute(const GameContextSnapshot& s,TransformReceipt* o){
    o->status=1;o->stage=1;o->mode=TRANSFORM_WRITE;o->count=TRANSFORM_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||
       o->count==0||o->count>kTransformBatch||!scene(s,*reinterpret_cast<const GameContextSnapshot*>(TRANSFORM_EXPECTED))||!code(s,o))return;
    // Metadata initialization is the documented loader, not a patched branch.
    static constexpr unsigned groups[]={TRANSFORM_USAGE_GROUPS};
    for(auto group:groups){reinterpret_cast<void(*)(unsigned)>(s.moduleBase+0x524250)(group);++o->nativeCalls;}
    static constexpr TransformRequest requests[]={TRANSFORM_REQUESTS};
    o->stage=2;
    for(unsigned i=0;i<o->count;++i){auto& r=o->rows[i];const auto& q=requests[i];r.entityId=q.entityId;r.mask=q.mask;r.status=1;r.desired=q.desired;
        for(unsigned j=0;j<i;++j)if(o->rows[j].entityId==r.entityId)return;
        unsigned found=0;for(unsigned j=0;j<s.entityCaptured;++j)if(s.entities[j].id==r.entityId){r.owner=s.entities[j].owner;++found;}
        if(found!=1||!r.owner||!capture(s,r,r.before))return;
#if TRANSFORM_WRITE
        if(!q.mask||q.mask>7||std::memcmp(&r.before,&q.expected,sizeof(TransformPose))||
            q.expectedParent!=r.parent||q.expectedFrame!=r.frameKind||(q.requireRoot&&r.frameKind!=1)||
            !finite(q.desired.localPosition)||!finite(q.desired.worldPosition)||!finite(q.desired.rotationDegrees)||!finite(q.desired.scale)||
            q.desired.scale.x<=0||q.desired.scale.y<=0||q.desired.scale.z<=0)return;
#else
        r.desired=r.before;r.after=r.before;r.readbackVerified=1;r.status=0;
#endif
    }
    o->stage=3;
#if TRANSFORM_WRITE
    for(unsigned i=0;i<o->count;++i){if(!mutate(s,o->rows[i]))return;++o->completed;}
#else
    o->completed=o->count;
#endif
    o->stage=4;CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=scene(s,o->afterScene)?1U:0U;
    if(!o->sceneUnchanged)return;o->status=0;o->stage=5;
}
}
void ExecuteTransform(const GameContextSnapshot* s,TransformReceipt* o) noexcept {
    if(!s||!o)return;std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=1;
    __try{execute(*s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
