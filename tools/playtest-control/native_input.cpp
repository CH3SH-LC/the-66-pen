// The normal player input consumer and current native menu callbacks only.
// Never writes transforms, collision results, inventory, skill results or graphs.
#include "native_input.h"
#include "native_control.cpp"
#if INPUT_OPERATION < 9 || INPUT_OPERATION > 12 || CONTROL_OPERATION != 3
#error "Dedicated bounded input card required"
#endif
namespace {
bool inputCode(U b,InputReceipt* o){
    static constexpr unsigned rvas[]={INPUT_CODE_RVAS};static constexpr unsigned char bytes[][32]={INPUT_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,bytes[i],32)){o->control.observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={INPUT_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->control.observation.failedRva=r;return false;}}return true;
}
bool exact(U b,U object,unsigned slot){return object&&ptr(object)==ptr(b+slot)&&ptr(object);}
U mainContext(U b,U global){
    const U stack=ptr(ptr(global+0x9c70)+0x1a8),array=ptr(stack+0x10);unsigned count=0;U capacity=0;
    if(!stack||!array||!read(stack+0x20,count)||!count||count>128||!read(array+0x18,capacity)||capacity>128||count>capacity)return 0;
    const U top=ptr(array+0x20+8ULL*(count-1));return exact(b,top,0x57b3288)?top:0;
}
bool liveObject(U b,U object,InputReceipt* o){if(!object||!ptr(object+0x10))return false;++o->nativeCalls;return reinterpret_cast<bool(*)(void*)>(b+0x1455060)(reinterpret_cast<void*>(object));}
bool inputBinding(U b,InputReceipt* o){
    const auto& sampleValue=o->control.observation.after;const auto& s=o->control.after;
    if(o->control.status||!o->control.stateStable||!o->control.observation.stable||sampleValue.avatarStatus!=2||sampleValue.positionStatus||!s.trialReady||!bound(s)||s.exitReady)return false;
    const U manager=ptr(s.global+0x9ca0),component=ptr(manager+0xc0),context=mainContext(b,s.global),view=ptr(context+0x450),input=ptr(component+0x110);
    unsigned char disabled=255,owned=0,blocked=255;
    if(!manager||ptr(manager+0x90)!=sampleValue.avatar||!exact(b,component,0x57f0aa8)||ptr(component+0x28)!=sampleValue.avatar||!input||!view||!exact(b,view,0x57b3860)||!read(input+0x42,disabled)||disabled||!read(sampleValue.avatar+0x49b,owned)||owned!=1||!read(context+0x766,blocked)||blocked)return false;
    if(ptr(ptr(component)+0x450)!=b+0x12b51c50||ptr(ptr(component)+0x2f0)!=b+0x12b526e0)return false;
    unsigned char sourceActive=255;float sourceStrength=1;
    if(!read(manager+0x167,sourceActive)||sourceActive>1||!read(manager+0x174,sourceStrength)||!std::isfinite(sourceStrength))return false;
    o->sourceIdle=sourceActive==0&&sourceStrength==0?1U:0U;
    if constexpr(INPUT_OPERATION==10){if(!o->actionAttempted&&!o->sourceIdle)return false;}
    if(o->avatar&&(o->avatar!=sampleValue.avatar||o->avatarId!=sampleValue.avatarId||o->manager!=manager||o->component!=component||o->mainContext!=context||o->view!=view))return false;
    if constexpr(INPUT_OPERATION!=9){if(sampleValue.avatar!=INPUT_AVATAR||sampleValue.avatarId!=INPUT_AVATAR_ID||component!=INPUT_COMPONENT||context!=INPUT_CONTEXT||view!=INPUT_VIEW)return false;}
    o->avatar=sampleValue.avatar;o->avatarId=sampleValue.avatarId;o->manager=manager;o->component=component;o->inputState=input;o->mainContext=context;o->view=view;o->actionPanel=ptr(view+0x2d8);o->inteePanel=ptr(view+0x1f8);o->inputEnabled=1;return true;
}
bool stringValue(U string,std::uint16_t* text,unsigned& length){std::int32_t n=-1;if(!string||!read(string+0x10,n)||n<0||n>127)return false;length=static_cast<unsigned>(n);return !n||memory(string+0x14,text,static_cast<std::size_t>(n)*2);}
void options(U b,InputReceipt* o){
    o->options=0;o->optionComplete=0;std::memset(o->option,0,sizeof(o->option));unsigned total=0;
    if(!o->inteePanel)return;
    // Current active reusable list entries, pickup first, dialog second: same
    // ordering used by MonoInteePanel.GetOptionAt. Never instantiate missing UI.
    static constexpr unsigned fields[]={0x28U,0x20U};for(unsigned field:fields){
        const U list=ptr(ptr(o->inteePanel+field)+0x40),array=ptr(list+0x10);unsigned count=0;U capacity=0;
        if(!list||!read(list+0x18,count)||count>64-total)return;
        if(count&&(!array||!read(array+0x18,capacity)||capacity<count||capacity>256))return;
        for(unsigned i=0;i<count;++i){auto& row=o->option[total];row.index=total++;row.item=ptr(array+0x20+8ULL*i);
            if(!exact(b,row.item,0x57e59d8))return;row.button=ptr(row.item+0x30);if(!exact(b,row.button,0x579f538))return;
            row.active=liveObject(b,row.button,o)?1U:0U;unsigned char enabled=0,groups=0;
            if(!read(row.button+0xb0,enabled)||enabled>1||!read(row.button+0xc0,groups)||groups>1)return;row.enabled=enabled&&groups?1U:0U;
            ++o->nativeCalls;const U text=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x10a80140)(reinterpret_cast<void*>(row.item)));
            if(!stringValue(text,row.text,row.textLength))return;o->options=total;
        }
    }o->optionComplete=1;
}
void attackButton(U b,InputReceipt* o){
    o->attackSlot=0xffffffffU;o->attackAction=0;o->button=0;if(!exact(b,o->actionPanel,0x5805de8))return;
    for(unsigned slot=0;slot<19;++slot){
        ++o->nativeCalls;const unsigned action=reinterpret_cast<unsigned(*)(void*,unsigned)>(b+0x115e4860)(reinterpret_cast<void*>(o->actionPanel),slot);
        if(action!=0x167)continue; // Current native enum parser a344250: BeyondAttack.
        ++o->nativeCalls;const U button=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,unsigned)>(b+0x115d67b0)(reinterpret_cast<void*>(o->actionPanel),slot));
        if(o->button||!exact(b,button,0x5813bd0)||ptr(button+0x28)!=o->avatar){o->button=0;return;}
        unsigned id=0;if(!read(button+0x20,id)||id!=o->avatarId||!liveObject(b,button,o))return;
        o->attackSlot=slot;o->attackAction=action;o->button=button;
    }
}
void recordPoint(U b,InputReceipt* o,unsigned frame,unsigned flags){if(o->points>=192)return;auto& point=o->point[o->points++];point.tick=GetTickCount64();point.frame=frame;point.flags=flags;std::memcpy(point.world,o->control.observation.after.world,12);read(o->inputState+0x30,point.strength);read(o->inputState+0x44,point.angle);(void)b;}
bool releaseMove(U b,InputReceipt* o){
    o->releaseAttempted=1;
    // Clear the normal joystick source first; otherwise the next engine Tick
    // would repopulate the component even after the immediate release below.
    ++o->nativeCalls;reinterpret_cast<void(*)(void*,float,float)>(b+0x10f6ce50)(reinterpret_cast<void*>(o->manager),0.0f,0.0f);
    ++o->nativeCalls;reinterpret_cast<void(*)(void*,float)>(b+0x12b51c50)(reinterpret_cast<void*>(o->component),0.0f);
    ++o->nativeCalls;reinterpret_cast<void(*)(void*,bool,float)>(b+0x12b526e0)(reinterpret_cast<void*>(o->component),false,0.0f);
    unsigned char active=255,sourceActive=255;float strength=1,sourceStrength=1;if(read(o->inputState+0x40,active)&&read(o->inputState+0x30,strength)&&read(o->manager+0x167,sourceActive)&&read(o->manager+0x174,sourceStrength)&&active==0&&strength==0&&sourceActive==0&&sourceStrength==0){o->released=1;o->sourceIdle=1;return true;}return false;
}
void attackTap(U b,InputReceipt* o){
    o->actionAttempted=1;o->released=0;
    __try{
        ++o->nativeCalls;o->pressAccepted=reinterpret_cast<bool(*)(void*,unsigned)>(b+0x115d6650)(reinterpret_cast<void*>(o->actionPanel),o->attackSlot)?1U:0U;
    }__finally{
        // Pair an attempted press even when the native down path raises SEH.
        o->releaseAttempted=1;++o->nativeCalls;reinterpret_cast<bool(*)(void*,unsigned)>(b+0x115d0820)(reinterpret_cast<void*>(o->actionPanel),o->attackSlot);
        unsigned char held=255;if(read(o->button+0x38,held)&&held==0)o->released=1;
    }
    o->actionReturned=1;o->status=o->pressAccepted&&o->released?0U:4U;
}
bool releaseStillOwnedMove(U b,InputReceipt* o){
    // Do not invoke a stale controller after scene/avatar replacement.
    if(!o->actionAttempted||o->released||!o->component)return false;
    const U global=ptr(b+0x5783de8),manager=ptr(global+0x9ca0);
    if(manager!=o->manager||ptr(manager+0x90)!=o->avatar||ptr(manager+0xc0)!=o->component||!exact(b,o->component,0x57f0aa8)||ptr(o->component+0x28)!=o->avatar||ptr(o->component+0x110)!=o->inputState)return false;
    return releaseMove(b,o);
}
bool step(U b,InputReceipt* o){
    if(!inputCode(b,o)){o->stopReason=2;return true;}
    ExecuteControl(&o->control);if(!inputBinding(b,o)){o->stopReason=3;if constexpr(INPUT_OPERATION==10)releaseStillOwnedMove(b,o);return true;}
    ++o->nativeCalls;const unsigned frame=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();const U now=GetTickCount64();
    if(!o->startedTick){o->startedTick=now;o->firstFrame=frame;options(b,o);attackButton(b,o);recordPoint(b,o,frame,0);}
    if constexpr(INPUT_OPERATION==9){o->released=1;o->status=0;return true;}
    else if constexpr(INPUT_OPERATION==10){
        if(o->actionAttempted&&frame==o->lastFrame){if(now-o->startedTick>4000){o->stopReason=4;releaseMove(b,o);return true;}return false;}
        if(o->actionAttempted)recordPoint(b,o,frame,1);
        const auto& first=o->point[0];const auto& current=o->control.observation.after;float distance=0;
        for(unsigned i=0;i<3;++i){const float d=current.world[i]-first.world[i];distance+=d*d;}
        const bool stop=o->actionAttempted&&(now-o->startedTick>=INPUT_DURATION_MS||distance>=INPUT_MAX_DISTANCE*INPUT_MAX_DISTANCE||o->points>=191||frame-o->firstFrame>=180);
        if(stop){o->stopReason=distance>=INPUT_MAX_DISTANCE*INPUT_MAX_DISTANCE?6U:1U;if(releaseMove(b,o)){o->status=0;o->actionReturned=1;}return true;}
        o->actionAttempted=1;o->actionReturned=0;++o->nativeCalls;
        // Exact current joystick delegate. Engine Tick then consumes this input
        // through its normal controller/physics path; no transform or result write.
        reinterpret_cast<void(*)(void*,float,float)>(b+0xc935160)(reinterpret_cast<void*>(o->mainContext),INPUT_ANGLE,INPUT_STRENGTH);
        o->actionReturned=1;o->lastFrame=frame;o->lastTick=now;return false;
    }else if constexpr(INPUT_OPERATION==11){
        if(!o->button||o->button!=INPUT_BUTTON||o->attackSlot!=INPUT_SLOT||o->attackAction!=0x167){o->stopReason=7;return true;}
        unsigned char held=255;if(!read(o->button+0x38,held)||held){o->stopReason=8;return true;}
        attackTap(b,o);return true;
    }else{
        if(!o->optionComplete||INPUT_OPTION>=o->options){o->stopReason=9;return true;}
        const auto& selected=o->option[INPUT_OPTION];static constexpr std::uint16_t expected[]={INPUT_LABEL_UTF16};
        if(selected.item!=INPUT_ITEM||selected.button!=INPUT_BUTTON||!selected.active||!selected.enabled||selected.textLength!=INPUT_LABEL_LENGTH||std::memcmp(selected.text,expected,INPUT_LABEL_LENGTH*2)){o->stopReason=10;return true;}
        o->optionIndex=INPUT_OPTION;o->button=selected.button;o->actionAttempted=1;++o->nativeCalls;
        reinterpret_cast<void(*)(void*)>(b+0x19dc6600)(reinterpret_cast<void*>(selected.button));o->actionReturned=1;o->released=1;o->status=0;return true;
    }
}
}
bool StepInput(InputReceipt* o) noexcept {
    if(!o)return true;
    if(o->stage==0){std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=3;o->status=1;o->stage=1;o->operation=INPUT_OPERATION;o->resourcesReleased=1;o->attackSlot=0xffffffffU;
        // Valid diagnostic ABI even when rejected before any target resolution.
        auto& c=o->control;c.bytes=sizeof(c);c.version=2;c.status=1;c.stage=1;c.operation=3;c.resourcesReleased=1;
        c.observation.bytes=sizeof(PlayReceipt);c.observation.version=1;c.observation.status=1;c.observation.targetLevel=PLAY_TARGET_LEVEL;c.observation.before.positionStatus=c.observation.after.positionStatus=1;
    }
    ++o->callbacks;bool done=true;
    __try{
        if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE){o->stopReason=11;}
        else {const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(b)done=step(b,o);}
    }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
    if(done){
        if constexpr(INPUT_OPERATION==10){if(o->actionAttempted&&!o->released){
            __try{const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(b&&inputCode(b,o))releaseStillOwnedMove(b,o);}
            __except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
        }}
        o->stage=3;if(o->actionAttempted&&!o->released)o->resourcesReleased=0;
    }
    return done;
}
