// One fixed action. Runtime enumeration is read-only. Capture allocates and
// destroys exactly one newly returned Texture2D; it is not labelled read-only.
#include "native_acceptance.h"
#include "native_observe.cpp"
#if HR_ACTION != 19 || !PLAY_ACCEPTANCE_REVIEWED
#error "Dedicated acceptance profile required"
#endif
namespace {
bool acceptanceCode(U b,AcceptanceReceipt* o){
    static constexpr unsigned rvas[]={ACCEPT_CODE_RVAS};
    static constexpr unsigned char expected[][32]={ACCEPT_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->observation.failedRva=rvas[i];return false;}
    return true;
}
void context(U global,U dictionary,RuntimeContext& c){
    c.dictionary=dictionary;c.entries=ptr(dictionary+0x28);
    c.levelManager=ptr(global+0xa150);c.trialTask=ptr(ptr(global+0xa960)+0x90);
    c.levelData=ptr(c.levelManager+0x68);unsigned char trial=0;
    if(c.levelData&&read(c.levelData+0x38,c.levelGuid)&&read(c.levelData+0x34,c.serverVersion)&&read(c.levelData+0x30,trial)){c.isTrial=trial;c.readable|=1;}
    if(c.trialTask&&read(c.trialTask+0x58,c.taskType)&&read(c.trialTask+0x5c,c.taskState))c.readable|=2;
    if(dictionary&&read(dictionary+0x38,c.dictionaryCount)&&read(dictionary+0x3c,c.dictionaryVersion))c.readable|=4;
}
void entityPosition(U b,RuntimeEntity& r,AcceptanceReceipt* o){
    r.positionStatus=1;r.activeStatus=1;
    // The slot is checked, never invoked as an unreviewed virtual function.
    const U world=ptr(r.klass+0x178);if(world>=b&&world-b<=0xffffffffULL)r.worldGetterRva=static_cast<unsigned>(world-b);
    if(r.klass==ptr(b+0x57b1570)){
        PlaySample s{};s.avatar=r.entity;s.avatarStatus=2;position(b,s,&o->observation);
        r.positionStatus=s.positionStatus;r.transform=s.transform;
        std::memcpy(r.unity,s.unity,sizeof(r.unity));std::memcpy(r.origin,s.origin,sizeof(r.origin));std::memcpy(r.world,s.world,sizeof(r.world));
    }else if(world==b+0x9a7acd0&&ptr(r.klass+0x4c8)==b+0x9a96970){
        unsigned char initialized=0;const U originClass=ptr(b+0x57a8ae8);
        r.transform=ptr(r.entity+0x1e8);
        if(originClass&&read(originClass+0xc7,initialized)&&initialized&&r.transform&&ptr(r.transform+0x10)&&read(b+0x57872a4,r.origin)&&finite(r.origin)){
            ++o->nativeCalls;reinterpret_cast<void(*)(void*,float*)>(b+0x1436d00)(reinterpret_cast<void*>(r.transform),r.unity);
            if(finite(r.unity)){for(unsigned i=0;i<3;++i)r.world[i]=r.unity[i]+r.origin[i];if(finite(r.world))r.positionStatus=0;}
        }
    }
    // Base position+transform slot pair proves this is the reviewed Entity
    // layout. Unknown derived overrides retain an unknown active state.
    if((world==b+0x9a7acd0||r.klass==ptr(b+0x57b1570))&&ptr(r.klass+0x4c8)==b+0x9a96970){
        r.gameObject=ptr(r.entity+0x38);
        if(r.gameObject&&ptr(r.gameObject+0x10)){++o->nativeCalls;r.active=reinterpret_cast<bool(*)(void*)>(b+0x19c9b820)(reinterpret_cast<void*>(r.gameObject))?1U:0U;r.activeStatus=0;}
    }
}
void enumerate(U b,AcceptanceReceipt* o){
    o->pageStart=ACCEPT_PAGE_START;o->pageEnd=ACCEPT_PAGE_START;o->enumerationStatus=1;
    const U dictionary=o->before.dictionary;
    if(!dictionary)return;
    U comparer=0,capacity=0;if(!read(dictionary+0x30,comparer)||comparer)return;
    const U entries=ptr(dictionary+0x28);
    if(!entries&&o->before.dictionaryCount==0&&ACCEPT_PAGE_START==0){o->enumerationStatus=0;return;}
    if(!entries||!read(entries+0x18,capacity)||capacity>65536||o->before.dictionaryCount>capacity)return;
    o->entryCapacity=static_cast<unsigned>(capacity);
    // Dictionary Count is the initialized-entry high-water mark, not the
    // number of live items. Negative hash slots are free and skipped.
    if(ACCEPT_PAGE_START>o->before.dictionaryCount)return;
    for(unsigned i=ACCEPT_PAGE_START;i<o->before.dictionaryCount&&o->count<kRuntimePage;++i){
        if(GetTickCount64()>=HR_DEADLINE){o->enumerationStatus=3;return;}
        const U at=entries+0x20+static_cast<U>(i)*24;std::int32_t hash=0;
        if(!read(at,hash)){o->enumerationStatus=2;return;}o->pageEnd=i+1;
        if(hash<0)continue;
        RuntimeEntity r{};if(!read(at+8,r.id)||!r.id){o->enumerationStatus=2;return;}
        r.entity=ptr(at+16);r.klass=ptr(r.entity);if(!r.entity||!r.klass){o->enumerationStatus=2;return;}
        unsigned runtimeId=0;unsigned char tickable=0,ready=0,loaded=0;
        if(!read(r.entity+0x3a8,runtimeId)||runtimeId!=r.id||!read(r.entity+0x4dc,r.configId)||!read(r.entity+0x458,r.entityType)||!read(r.entity+0x320,tickable)||!read(r.entity+0x482,ready)||!read(r.entity+0x42f,loaded)||tickable>1||ready>1||loaded>1){o->enumerationStatus=2;return;}
        r.isTickable=tickable;r.isEntityReady=ready;r.isLoaded=loaded;
        r.entryIndex=i;r.localAvatar=r.entity==o->observation.after.avatar?1U:0U;entityPosition(b,r,o);o->entities[o->count]=r;++o->count;
    }
    o->enumerationStatus=0;
}
void frame(U b,AcceptanceReceipt* o){
    U texture=0; o->frameStatus=1;
    __try{
        ++o->nativeCalls;const unsigned screenWidth=reinterpret_cast<unsigned(*)()>(b+0x19cc2fd0)();
        ++o->nativeCalls;const unsigned screenHeight=reinterpret_cast<unsigned(*)()>(b+0x19cc2fe0)();
        if(!screenWidth||!screenHeight||screenWidth>4096||screenHeight>4096){o->frameStatus=2;return;}
        ++o->nativeCalls;o->frameBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
        ++o->nativeCalls;o->renderedBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
        // superSize is fixed to one. The >1 branch re-renders scenes and is
        // expressly excluded. A read of the last game backbuffer may be stale.
        o->resourcesReleased=0;
        ++o->nativeCalls;texture=reinterpret_cast<U>(reinterpret_cast<void*(*)(int)>(b+0x19d141e0)(1));
        if(!texture)o->resourcesReleased=1;
        if(texture&&ptr(texture+0x10)){
            ++o->nativeCalls;o->width=reinterpret_cast<unsigned(*)(void*)>(b+0x19cae530)(reinterpret_cast<void*>(texture));
            ++o->nativeCalls;o->height=reinterpret_cast<unsigned(*)(void*)>(b+0x19cae5a0)(reinterpret_cast<void*>(texture));
            if(o->width&&o->height&&o->width<=4096&&o->height<=4096){
                ++o->nativeCalls;const U png=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x19cd3610)(reinterpret_cast<void*>(texture)));U bytes=0;
                if(png&&read(png+0x18,bytes)&&bytes>=57&&bytes<=kFrameCapacity&&memory(png+0x20,o->png,static_cast<std::size_t>(bytes))){o->pngBytes=static_cast<unsigned>(bytes);o->frameStatus=0;}
                else o->frameStatus=3;
            }else o->frameStatus=2;
        }
    }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->frameStatus=4;}
    if(texture){
        o->resourcesReleased=0;
        __try{++o->nativeCalls;reinterpret_cast<void(*)(void*,bool)>(b+0x19cb2dd0)(reinterpret_cast<void*>(texture),false);
            // GetCachedPtr is exactly the managed Object +0x10 field. Zero is
            // required; returning from DestroyImmediate alone is insufficient.
            U cached=1;if(read(texture+0x10,cached)&&cached==0)o->resourcesReleased=1;
        }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->frameStatus=5;}
    }
    ++o->nativeCalls;o->frameAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
    ++o->nativeCalls;o->renderedAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
}
void acceptance(AcceptanceReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b)return;
    if(!code(b,&o->observation)||!acceptanceCode(b,o))return;
    ExecutePlayObservation(&o->observation);if(o->observation.status||!o->observation.stable)return;
    // Capture is never allowed in another positively observed editor level.
    if(o->observation.mode==1&&o->observation.after.editorLevel!=PLAY_TARGET_LEVEL){o->status=3;return;}
    // EntityManager's own [EntityMap] diagnostic and duplicate-runtime-ID
    // guard enumerate +1e8. +150 is the avatar index and is not substituted.
    context(o->observation.after.global,ptr(o->observation.after.avatarManager+0x1e8),o->before);o->stage=2;
    if constexpr(ACCEPT_OPERATION==1)enumerate(b,o);
    else if constexpr(ACCEPT_OPERATION==2){
        // Current release proves target identity only in editor mode. Do not
        // claim pixels from an unbound trial or the main game as target proof.
        if(o->observation.mode!=1){o->status=4;return;}frame(b,o);
    }else return;
    context(o->observation.after.global,ptr(o->observation.after.avatarManager+0x1e8),o->after);
    // Independently read editor/avatar guards again after the operation.
    std::memset(&o->observation.after,0,sizeof(o->observation.after));
    o->observation.readableAfter=sample(b,o->observation.after,&o->observation);
    o->observation.stable=stable(o->observation.before,o->observation.after)&&o->observation.readableBefore==o->observation.readableAfter?1U:0U;
    o->observation.mode=0;
    if(o->observation.readableBefore==15&&o->observation.readableAfter==15){
        if(o->observation.before.rawMode!=o->observation.after.rawMode||o->observation.before.editing!=o->observation.after.editing||o->observation.before.editorLevel!=o->observation.after.editorLevel)o->observation.mode=2;
        else if(o->observation.stable&&o->observation.after.rawMode==0xb993&&o->observation.after.gateObject&&o->observation.after.editing)o->observation.mode=1;
    }
    o->dictionaryStable=std::memcmp(&o->before,&o->after,sizeof(o->before))==0?1U:0U;
    o->stage=3;
    o->status=(o->seh||!o->resourcesReleased||!o->observation.stable||(ACCEPT_OPERATION==1&&(o->enumerationStatus||!o->dictionaryStable))||(ACCEPT_OPERATION==2&&(o->frameStatus||o->observation.mode!=1)))?2U:0U;
}
}
void ExecuteAcceptance(AcceptanceReceipt* o) noexcept{
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=1;o->status=1;o->stage=1;o->operation=ACCEPT_OPERATION;o->resourcesReleased=1;
    // Even a pre-target rejection has a well-formed embedded record. A zeroed
    // position must never masquerade as a successfully read avatar transform.
    o->observation.bytes=sizeof(PlayReceipt);o->observation.version=1;o->observation.status=1;o->observation.stage=1;o->observation.targetLevel=PLAY_TARGET_LEVEL;
    o->observation.before.positionStatus=o->observation.after.positionStatus=1;
    __try{acceptance(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
