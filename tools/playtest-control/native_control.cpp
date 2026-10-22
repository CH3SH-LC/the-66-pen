// Fixed official trial actions. No UI input, network fabrication, generic call,
// retry, state overwrite, restart, publication or automatic dialog confirmation.
#include "native_control.h"
#include "native_observe.cpp"
#if HR_ACTION != 19 || !PLAY_ACCEPTANCE_REVIEWED || CONTROL_OPERATION < 3 || CONTROL_OPERATION > 8
#error "Dedicated trial-control profile required"
#endif
namespace {
bool controlCode(U b,ControlReceipt* o){
    static constexpr unsigned rvas[]={CONTROL_CODE_RVAS};
    static constexpr unsigned char bytes[][32]={CONTROL_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(bytes[i],actual,32)){o->observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={CONTROL_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->observation.failedRva=r;o->observation.failedValue=v;return false;}}
    return true;
}
bool byte(U at,unsigned& value){unsigned char v=255;if(!read(at,v)||v>1)return false;value=v;return true;}
// Existing UI model cache only. The official GetModel<T> allocates when absent,
// so the observer does not call it. Exact initialized generic class is required.
void settings(U b,U global,TrialState& s){
    const U method=ptr(b+0x59196f0),klass=ptr(ptr(method+0x10)+0x18);
    const U dict=ptr(ptr(global+0x9c70)+0x98),entries=ptr(dict+0x18);U capacity=0;
    if(!klass||!entries||!read(entries+0x18,capacity)||capacity>4096)return;
    for(U i=0;i<capacity;++i){
        const U at=entries+0x20+i*24;std::int32_t hash=-1;U object=0;
        if(!read(at,hash)||!read(at+16,object))return;
        if(hash<0||!object||ptr(object)!=klass)continue;
        if(s.model){s.model=s.settings=0;return;}s.model=object;s.settings=ptr(object+0x18);
    }
}
void state(U b,const PlaySample& sampleValue,TrialState& s,ControlReceipt* o){
    s.global=sampleValue.global;s.editor=sampleValue.editorManager;s.editorLevel=sampleValue.editorLevel;s.sceneId=sampleValue.rawMode;s.editing=sampleValue.editing;
    if(!s.global||!s.editor)return;
    s.task=ptr(s.editor+0x90);s.coroutine=ptr(s.editor+0x80);
    const U level=ptr(s.global+0xa150),social=ptr(s.global+0xf390),beyond=ptr(s.global+0xaa40),mode=sampleValue.modeManager;
    s.cache=ptr(level+0x90);s.data=ptr(level+0x68);s.cacheEditData=ptr(s.cache+0x20);s.taskEditData=ptr(s.task+0x40);
    s.room=ptr(ptr(social+0x70)+0x10);s.loadTask=ptr(ptr(s.global+0xad80)+0x30);
    s.settleManager=ptr(beyond+0x68);s.settleContext=ptr(s.settleManager+0x28);s.settleData=ptr(s.settleManager+0xf0);
    s.loadPhase=0xffffffffU;s.remakeCount=0xffffffffU;
    if(s.task&&read(s.task+0x50,s.token)&&read(s.task+0x54,s.taskType)&&s.taskType<=2&&read(s.task+0x5c,s.taskPhase)&&s.taskPhase<=12)s.readable|=1;
    if(s.room&&byte(s.room+0x22,s.multi)&&read(s.room+0x24,s.roomToken))s.readable|=2;
    if(mode&&read(mode+0x230,s.ownerUid)&&read(ptr(mode+0x118)+0x158,s.localUid)&&s.localUid)s.readable|=4;
    if(beyond&&byte(beyond+0xe5,s.isTrial))s.readable|=8;
    if(s.cache&&byte(s.cache+0x30,s.cacheIsTrial)&&s.cacheEditData)s.readable|=16;
    if(s.data&&byte(s.data+0x30,s.currentIsTrial))s.readable|=32;
    const U loader=ptr(s.global+0xad80);
    if(loader&&(!s.loadTask||read(s.loadTask+0x28,s.loadPhase)))s.readable|=64;
    const U history=ptr(level+0x60);
    if(level&&(!history||read(history+0x18,s.remakeCount))){if(!history)s.remakeCount=0;s.readable|=128;}
    if(s.settleData&&s.settleContext&&ptr(s.settleContext+0x2a0)==s.settleData&&byte(s.settleData+0x82,s.settleTrial)&&byte(s.settleData+0x80,s.settleHidden))s.readable|=256;
    const U scene=ptr(sampleValue.gateObject+0x30);
    if(scene&&read(scene+0x70,s.sceneType))s.readable|=512;
    settings(b,s.global,s);
    if(sampleValue.avatarStatus==2&&sampleValue.positionStatus==0){
        const U gameObject=ptr(sampleValue.avatar+0x38);
        if(gameObject&&ptr(gameObject+0x10)){++o->nativeCalls;s.avatarActive=reinterpret_cast<bool(*)(void*)>(b+0x19c9b820)(reinterpret_cast<void*>(gameObject))?1U:0U;}
    }
    const bool host=(s.readable&4)&&s.ownerUid==s.localUid;
    s.entryReady=(s.readable&31)==31&&s.editing==1&&s.sceneId==0xb993&&s.editorLevel==PLAY_TARGET_LEVEL&&!s.coroutine&&s.taskType==1&&s.taskPhase==9&&s.token&&s.token==s.roomToken&&!s.multi&&host&&s.cacheIsTrial&&s.model&&s.settings?1U:0U;
    // Only the positively proven Beyond type=5 branch is accepted. The type=1
    // dungeon-config lookup has not been transcribed; it remains unknown.
    s.trialReady=(s.readable&0x27e)==0x27e&&s.sceneType==5&&s.editing==0&&s.isTrial&&s.currentIsTrial&&s.cacheIsTrial&&s.cache==s.data&&s.token&&s.roomToken==s.token&&!s.multi&&host&&(!s.loadTask||s.loadPhase==10)&&s.avatarActive?1U:0U;
    s.exitReady=(s.readable&256)&&s.settleTrial&&!s.settleHidden&&s.isTrial&&s.data==s.cache&&s.token&&s.token==s.roomToken&&!s.multi?1U:0U;
}
bool origin(const TrialState& s){return s.global==CONTROL_GLOBAL&&s.editor==CONTROL_EDITOR&&s.task==CONTROL_TASK;}
bool bound(const TrialState& s){return origin(s)&&s.token==CONTROL_TOKEN&&s.roomToken==CONTROL_TOKEN&&s.cache==CONTROL_CACHE&&s.cacheEditData==CONTROL_DATA;}
unsigned precondition(const TrialState& s,const PlayReceipt& observation){
    if constexpr(CONTROL_OPERATION==3)return 0;
    else if constexpr(CONTROL_OPERATION==4){
        if(observation.mode!=1||!observation.stable||s.editorLevel!=PLAY_TARGET_LEVEL)return 10;
        if((s.readable&5)!=5||s.coroutine||s.taskPhase!=0||s.taskType!=0)return 11;
        if(s.ownerUid!=s.localUid||!s.localUid)return 12;
        if(s.room&&(!(s.readable&2)||s.multi))return 13;
        return 0;
    }
    else{
        if(!origin(s))return 20;
        if constexpr(CONTROL_OPERATION==5){
            if(!s.entryReady||s.token!=CONTROL_TOKEN||s.cache!=CONTROL_CACHE||s.cacheEditData!=CONTROL_DATA)return 21;
            if(s.token==CONTROL_INITIAL_TOKEN||s.cacheEditData==CONTROL_INITIAL_DATA)return 22;
            return 0;
        }else{
            if(!bound(s))return 23;
            const bool freshSettlement=s.exitReady&&s.settleData!=CONTROL_INITIAL_SETTLE;
            if constexpr(CONTROL_OPERATION==6)return !s.trialReady||freshSettlement?24U:(!(s.readable&128)||s.remakeCount)?25U:0U;
            else if constexpr(CONTROL_OPERATION==7)return !freshSettlement||s.settleData==CONTROL_EXIT_SETTLE||s.settleContext!=CONTROL_SETTLE_CONTEXT||s.settleData!=CONTROL_SETTLE_DATA?26U:0U;
            else return s.trialReady&&!freshSettlement?0U:27U;
        }
    }
}
void trialFrame(U b,ControlReceipt* o){
    U texture=0;o->frameStatus=1;
    __try{
        ++o->nativeCalls;const unsigned width=reinterpret_cast<unsigned(*)()>(b+0x19cc2fd0)();
        ++o->nativeCalls;const unsigned height=reinterpret_cast<unsigned(*)()>(b+0x19cc2fe0)();
        if(!width||!height||width>4096||height>4096){o->frameStatus=2;return;}
        ++o->nativeCalls;o->frameBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
        ++o->nativeCalls;o->renderedBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
        o->resourcesReleased=0;++o->nativeCalls;
        texture=reinterpret_cast<U>(reinterpret_cast<void*(*)(int)>(b+0x19d141e0)(1));
        if(!texture)o->resourcesReleased=1;
        if(texture&&ptr(texture+0x10)){
            ++o->nativeCalls;o->width=reinterpret_cast<unsigned(*)(void*)>(b+0x19cae530)(reinterpret_cast<void*>(texture));
            ++o->nativeCalls;o->height=reinterpret_cast<unsigned(*)(void*)>(b+0x19cae5a0)(reinterpret_cast<void*>(texture));
            if(o->width&&o->height&&o->width<=4096&&o->height<=4096){
                ++o->nativeCalls;const U png=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x19cd3610)(reinterpret_cast<void*>(texture)));U bytes=0;
                if(png&&read(png+0x18,bytes)&&bytes>=57&&bytes<=sizeof(o->png)&&memory(png+0x20,o->png,static_cast<std::size_t>(bytes))){o->pngBytes=static_cast<unsigned>(bytes);o->frameStatus=0;}
                else o->frameStatus=3;
            }else o->frameStatus=2;
        }
    }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->frameStatus=4;}
    if(texture){
        o->resourcesReleased=0;
        __try{++o->nativeCalls;reinterpret_cast<void(*)(void*,bool)>(b+0x19cb2dd0)(reinterpret_cast<void*>(texture),false);U cached=1;if(read(texture+0x10,cached)&&cached==0)o->resourcesReleased=1;}
        __except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->frameStatus=5;}
    }
    ++o->nativeCalls;o->frameAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
    ++o->nativeCalls;o->renderedAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
}
void callAction(U b,ControlReceipt* o){
    if constexpr(CONTROL_OPERATION>=4&&CONTROL_OPERATION<=7){
        // Attempt is recorded BEFORE the native entry. Missing return is uncertain.
        o->actionAttempted=1;++o->nativeCalls;
        if constexpr(CONTROL_OPERATION==4)reinterpret_cast<void(*)()>(b+0x13721870)();
        else if constexpr(CONTROL_OPERATION==5)reinterpret_cast<void(*)()>(b+0x13726d20)();
        else if constexpr(CONTROL_OPERATION==6)reinterpret_cast<void(*)()>(b+0x13724240)();
        else if constexpr(CONTROL_OPERATION==7)reinterpret_cast<void(*)(void*)>(b+0x138cbaf0)(reinterpret_cast<void*>(o->before.settleContext));
        o->actionReturned=1;
    }
}
void executeControl(ControlReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!code(b,&o->observation)||!controlCode(b,o))return;
    ExecutePlayObservation(&o->observation);if(o->observation.status||!o->observation.stable)return;
    state(b,o->observation.after,o->before,o);state(b,o->observation.after,o->after,o);o->stage=2;
    if(std::memcmp(&o->before,&o->after,sizeof(TrialState))!=0){o->status=3;o->precondition=31;return;}
    o->precondition=precondition(o->before,o->observation);
    if(o->precondition){o->status=3;return;}
    callAction(b,o);
    if constexpr(CONTROL_OPERATION==8)trialFrame(b,o);
    // Re-observe independently after dispatch, never infer asynchronous success.
    ExecutePlayObservation(&o->observation);std::memset(&o->after,0,sizeof(o->after));state(b,o->observation.after,o->after,o);
    o->stateStable=std::memcmp(&o->before,&o->after,sizeof(TrialState))==0?1U:0U;
    o->stage=3;o->status=o->observation.status||o->observation.seh||o->seh||!o->resourcesReleased||(CONTROL_OPERATION==8&&(o->frameStatus||!o->stateStable||precondition(o->after,o->observation)))?2U:0U;
}
}
void ExecuteControl(ControlReceipt* o) noexcept{
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=2;o->status=1;o->stage=1;o->operation=CONTROL_OPERATION;o->resourcesReleased=1;
    o->observation.bytes=sizeof(PlayReceipt);o->observation.version=1;o->observation.status=1;o->observation.targetLevel=PLAY_TARGET_LEVEL;
    o->observation.before.positionStatus=o->observation.after.positionStatus=1;
    __try{executeControl(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
