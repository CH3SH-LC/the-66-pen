// Fixed Mondstadt range expansion through the game's vector setter.
// Official save handler 7c0d840 assigns the same full size to basic+18 and +38.
// It does not move the range centre: validation uses zero-centred half extents.
#include "native_bounds.h"
#include "native_observe.cpp"
#if HR_ACTION != 19 || !PLAY_BOUNDS_REVIEWED
#error "Fixed bounds profile required"
#endif
namespace {
bool boundsCode(U b,BoundsReceipt* o){
    static constexpr unsigned rvas[]={BOUNDS_CODE_RVAS};
    static constexpr unsigned char expected[][32]={BOUNDS_CODE_BYTES};
    static constexpr unsigned flags[]={BOUNDS_HOTFIX_RVAS};
    unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)
        if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){
            o->observation.failedRva=rvas[i];return false;
        }
    for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->observation.failedRva=r;return false;}}
    return true;
}
bool getVector(U p,float* out){
    // Native vector storage order is z,y,x, not the Unity argument order.
    return read(p+0x20,out[0])&&read(p+0x1c,out[1])&&read(p+0x18,out[2])&&finite(out);
}
bool allValue(const float* p,float v){return p[0]==v&&p[1]==v&&p[2]==v;}
bool sameVector(const float* p,const float* q){return p[0]==q[0]&&p[1]==q[1]&&p[2]==q[2];}
bool baseline(const BoundsReceipt* o){
    return (allValue(o->beforePrimary,0)||allValue(o->beforePrimary,100))&&allValue(o->beforeCached,100);
}
void changeBounds(U b,BoundsReceipt* o){
    o->guardStatus=3;
    o->manager=ptr(o->observation.after.global+0xbfe0);
    const U container=ptr(o->manager+0x20);
    o->basic=ptr(container+0x20);o->primary=ptr(o->basic+0x18);o->cached=ptr(o->basic+0x38);
    const U klass=ptr(b+0x57b6588);
    if(!o->manager||!container||!o->basic||!o->primary||!o->cached||o->primary==o->cached||
       !klass||ptr(o->primary)!=klass||ptr(o->cached)!=klass||
       !getVector(o->primary,o->beforePrimary)||!getVector(o->cached,o->beforeCached))return;
    if constexpr(BOUNDS_OPERATION==1){
        getVector(o->primary,o->afterPrimary);getVector(o->cached,o->afterCached);
        o->guardStatus=0;o->settingsUnchanged=1;o->status=0;o->stage=3;return;
    }
    o->guardStatus=4;if(!baseline(o))return;
    unsigned char before[0x98]{},after[0x98]{};
    if(!memory(o->basic,before,sizeof(before)))return;
    o->desired[0]=800;o->desired[1]=300;o->desired[2]=800;
    o->writeStarted=1;o->resourcesReleased=0;
    ++o->nativeCalls;reinterpret_cast<void(*)(U,const float*)>(b+0x1083b150)(o->primary,o->desired);
    ++o->nativeCalls;reinterpret_cast<void(*)(U,const float*)>(b+0x1083b150)(o->cached,o->desired);
    if(!getVector(o->primary,o->afterPrimary)||!getVector(o->cached,o->afterCached)||
       !sameVector(o->desired,o->afterPrimary)||!sameVector(o->desired,o->afterCached))return;
    if(!memory(o->basic,after,sizeof(after))||std::memcmp(before,after,sizeof(before)))return;
    o->settingsUnchanged=1;o->writeCompleted=1;o->resourcesReleased=1;
    o->guardStatus=0;o->status=0;o->stage=3;
}
void executeBounds(BoundsReceipt* o){
    o->status=1;o->stage=1;o->resourcesReleased=1;o->guardStatus=1;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));
    if(!b||!boundsCode(b,o))return;
    ExecutePlayObservation(&o->observation);
    const auto& p=o->observation;
    if(p.status||p.seh||p.stage!=3||p.mode!=1||!p.stable||
       p.after.editorLevel!=1073741845U||PLAY_TARGET_LEVEL!=1073741845U)return;
    o->stage=2;changeBounds(b,o);
}
}
void ExecuteAcceptance(BoundsReceipt* o) noexcept{
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=1;o->operation=BOUNDS_OPERATION;
    o->observation.bytes=sizeof(PlayReceipt);o->observation.version=1;o->observation.status=1;
    o->observation.targetLevel=PLAY_TARGET_LEVEL;o->observation.stable=1;
    o->observation.before.positionStatus=o->observation.after.positionStatus=1;
    __try{executeBounds(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
