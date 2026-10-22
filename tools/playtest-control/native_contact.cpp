// Read existing runtime mappings, controller state and UI callback ownership.
// No physics query, input, mutation, lazy getter, or callback is invoked here.
#include "native_contact.h"
#include "native_control.cpp"
#if CONTACT_OPERATION != 17 || CONTROL_OPERATION != 3
#error "Dedicated trial-bound contact observation card required"
#endif
namespace {
bool contactCode(U b,ContactReceipt* o){
    static constexpr unsigned rvas[]={CONTACT_CODE_RVAS};static constexpr unsigned char bytes[][32]={CONTACT_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,bytes[i],32)){o->control.observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={CONTACT_HOTFIX_RVAS};for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->control.observation.failedRva=r;return false;}}return true;
}
bool contactExact(U b,U object,unsigned slot){const U type=ptr(b+slot);return object&&type&&ptr(object)==type;}
bool contactDerives(U klass,U base){if(!klass||!base)return false;if(klass==base)return true;unsigned char depth=0,total=0;if(!read(base+0xc5,depth)||!depth||depth>64||!read(klass+0xc5,total)||total<depth||total>64)return false;return ptr(ptr(klass+0x40)+8ULL*(depth-1))==base;}
bool contactList(U list,U& array,unsigned& count,unsigned limit=64){U length=0;array=ptr(list+0x10);return list&&array&&read(list+0x18,count)&&count<=limit&&read(array+0x18,length)&&length>=count&&length<=65536;}
bool contactContext(U b,ContactSample& s,U global){
    s.entityManager=ptr(global+0x9d50);s.dictionary=ptr(s.entityManager+0x1e8);s.entries=ptr(s.dictionary+0x28);U comparer=1,length=0;
    if(!s.entityManager||!s.dictionary||!read(s.dictionary+0x30,comparer)||comparer||!read(s.dictionary+0x38,s.entityCount)||s.entityCount>65536||!read(s.dictionary+0x3c,s.entityVersion)||!read(s.entityManager+0x250,s.avatarId))return false;
    if(s.entityCount&&(!s.entries||!read(s.entries+0x18,length)||length<s.entityCount||length>65536))return false;s.entityCapacity=static_cast<unsigned>(length);
    s.mapStatus=1;s.optionsStatus=1;s.beyondManager=ptr(global+0xa410);
    if(!contactExact(b,s.beyondManager,0x57b2b08))return true;
    s.map=ptr(s.beyondManager+0xa0);s.reverseMap=ptr(s.beyondManager+0x100);s.mapEntries=ptr(s.map+0x20);s.reverseEntries=ptr(s.reverseMap+0x10);
    unsigned forwardCount=0,reverseCount=0;
    if(!s.map||!s.reverseMap||!memory(s.map,s.mapHeader,80)||!memory(s.reverseMap,s.reverseHeader,80)||!read(s.map+0x44,forwardCount)||forwardCount>kContactMap||!read(s.reverseMap+0x40,reverseCount)||reverseCount>kContactMap)return true;
    s.mapCount=forwardCount;s.reverseCount=reverseCount;
    if(!s.mapEntries||!read(s.mapEntries+0x18,length)||length<s.mapCount||length>65536)return true;s.mapCapacity=static_cast<unsigned>(length);
    if(!s.reverseEntries||!read(s.reverseEntries+0x18,length)||length<s.reverseCount||length>65536)return true;s.reverseCapacity=static_cast<unsigned>(length);
    if(!memory(s.mapEntries+0x20,s.mappings,sizeof(ContactMapEntry)*s.mapCount)||!memory(s.reverseEntries+0x20,s.reverse,sizeof(ContactReverseEntry)*s.reverseCount))return true;
    s.mapStatus=0;return true;
}
void contactRow(U b,U entity,unsigned id,unsigned index,bool local,ContactRow& r){
    r.entity=entity;r.klass=ptr(entity);r.runtimeId=id;r.entryIndex=index;r.localAvatar=local;r.status=1;unsigned actual=0;unsigned char loaded=0,ready=0,cleared=1;
    if(!contactDerives(r.klass,ptr(b+0x57dbd80))||!read(entity+0x3a8,actual)||actual!=id||!read(entity+0x4dc,r.configId)||!read(entity+0x458,r.entityType)||!read(entity+0x42f,loaded)||loaded>1||!read(entity+0x482,ready)||ready>1||!read(entity+0x491,cleared)||cleared>1)return;
    r.flags=loaded|(ready<<1)|(cleared<<2)|(!ptr(entity+0x1a0)?8U:0U);r.status=0;
}
void contactMotion(U b,U avatar,ContactReceipt* o,ContactMotion& m){
    m.status=1;m.manager=ptr(avatar+0x120);m.array=ptr(m.manager+0x68);U count=0;
    if(!m.array||!read(m.array+0x18,count)||count<=20||count>4096)return;
    m.move=ptr(m.array+0x20+20*8);if(!contactExact(b,m.move,0x57b7878)||ptr(m.move+0x28)!=avatar)return;
    m.data=ptr(m.move+0x6d0);m.fsm=ptr(m.move+0x698);
    if(!contactExact(b,m.data,0x57dd580)||ptr(m.data+0x510)!=m.move||ptr(m.move+0x110)!=m.data||!contactExact(b,m.fsm,0x57d73a0)||ptr(m.fsm+0x118)!=m.move||ptr(m.fsm+0x130)!=m.data)return;
    m.state=ptr(m.fsm+0x120);if(!m.state||ptr(m.state+0x98)!=m.move||ptr(m.state+0x48)!=m.data||ptr(m.state+0x50)!=m.fsm)return;
    ++o->nativeCalls;m.frameBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
    if(!read(m.data+0x10,m.motion)||!read(m.data+0x14,m.previousMotion)||!read(m.state+0x138,m.stateType)||!read(m.data+0x4ac,m.beneathResult)||!read(m.data+0x4b0,m.slopeFrame)||!memory(m.data+0x478,m.slopeRaw,52)||!read(m.data+0x424,m.downRayEntityId)||!read(m.data+0x4c4,m.downRayFrame)||!read(m.move+0x140,m.referenceRuntimeId)||!read(m.move+0x190,m.referenceColliderIndex))return;
    m.referenceEntity=ptr(m.move+0x148);m.referenceComponent=ptr(m.move+0x150);m.referenceCollider=ptr(m.move+0x198);m.dataCollider=ptr(m.data+0x150);
    ++o->nativeCalls;m.frameAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();m.status=0;
}
bool contactText(U b,U text,ContactOption& r){if(!text)return true;if(!contactDerives(ptr(text),ptr(b+0x579f540)))return false;const U value=ptr(text+0xe0);if(!value)return true;int n=-1;if(!read(value+0x10,n)||n<0||n>127)return false;r.textLength=static_cast<unsigned>(n);return !n||memory(value+0x14,r.text,n*2);}
// UI binder 9f5ff10 resolves interface slot 6 then passes its uint32 result
// directly to EntityManager.e983110. Inspect only a pure field getter; never
// invoke an unknown generic method or resolve/initialize metadata at runtime.
void contactOptionOwner(U b,ContactReceipt* o,ContactSample& s,ContactOption& r){
    r.ownerStatus=1;unsigned char enabled=0,groups=0;
    if(!read(r.button+0xb0,enabled)||enabled>1||!read(r.button+0xc0,groups)||groups>1||!ptr(r.button+0x10))return;
    ++o->nativeCalls;r.active=reinterpret_cast<bool(*)(void*)>(b+0x1455060)(reinterpret_cast<void*>(r.button));r.enabled=enabled&&groups;
    if(r.status||!r.active)return;
    r.interfaceType=ptr(b+0x57d3330);unsigned short n=0,v=0;
    const U table=ptr(r.callbackClass+0x88);
    if(!r.interfaceType||!table||!read(r.callbackClass+0xc2,n)||!n||n>256||!read(r.callbackClass+0xbe,v)||v>4096)return;
    r.virtualCount=v;
    for(unsigned i=0;i<n;++i){const U at=table+16ULL*i;if(ptr(at)!=r.interfaceType)continue;if(r.interfaceRecord)return;r.interfaceRecord=at;if(!read(at+8,r.interfaceOffset))return;}
    if(!r.interfaceRecord||r.interfaceOffset+6>=r.virtualCount)return;
    r.callbackSlot=ptr(r.callbackClass+0xd0+8ULL*(r.interfaceOffset+4));r.ownerGetter=ptr(r.callbackClass+0xd0+8ULL*(r.interfaceOffset+6));
    r.ownerMethodInfo=ptr(r.callbackClass+0xd0+8ULL*(r.virtualCount+r.interfaceOffset+6));
    if(r.callbackSlot!=b+r.callbackMethod||r.ownerGetter<b||r.ownerGetter-b>=0x20000000ULL||!r.ownerMethodInfo||!memory(r.ownerGetter,r.getterHead,8))return;
    if(r.getterHead[0]==0x8b&&r.getterHead[1]==0x41&&r.getterHead[3]==0xc3)r.fieldOffset=r.getterHead[2];
    else if(r.getterHead[0]==0x8b&&r.getterHead[1]==0x81&&r.getterHead[6]==0xc3)std::memcpy(&r.fieldOffset,r.getterHead+2,4);
    else return;
    if(r.fieldOffset<0x10||r.fieldOffset>0x400||r.fieldOffset%4)return;r.ownerData=r.callbackTarget+r.fieldOffset;
    if(!read(r.ownerData,r.ownerRuntimeId)||!r.ownerRuntimeId)return;
    unsigned found=0,index=0;
    for(unsigned i=0;i<s.entityCount;++i){if(GetTickCount64()>=HR_DEADLINE)return;const U at=s.entries+0x20+24ULL*i;int hash=-1;unsigned id=0;if(!read(at,hash)||!read(at+8,id))return;if(hash<0||id!=r.ownerRuntimeId)continue;++found;index=i;r.ownerObject=ptr(at+16);}
    if(found!=1||!r.ownerObject)return;contactRow(b,r.ownerObject,r.ownerRuntimeId,index,false,r.owner);if(r.owner.status||r.owner.flags!=3)return;r.ownerStatus=0;
}
void contactCallback(U b,ContactOption& r){
    r.status=1;r.event=ptr(r.button+0xd8);const U calls=ptr(r.event+0x10),persistent=ptr(r.event+0x18);U a=0;unsigned n=0;
    if(!contactList(ptr(calls+0x10),a,n,8)||n||!contactList(ptr(persistent+0x10),a,n,8)||n||!contactList(ptr(calls+0x18),a,n,8)||n!=1)return;
    r.invocation=ptr(a+0x20);r.wrapper=ptr(r.invocation+0x10);if(ptr(r.wrapper+0x18)!=b+0x14058e50)return;
    r.delegateObject=ptr(ptr(r.wrapper+0x40)+0x10);const U method=ptr(r.delegateObject+0x18);if(!method||ptr(r.delegateObject+0x10)!=method)return;
    if(method<b||method-b>=0x20000000ULL)return;r.callbackMethod=method-b;r.methodInfo=ptr(r.delegateObject+0x28);r.callbackTarget=ptr(r.delegateObject+0x40);r.callbackClass=ptr(r.callbackTarget);
    // This proves callback association only, not a generic model's entity owner.
    if(!r.callbackTarget||!r.callbackClass)return;r.status=0;
}
void contactOptions(U b,U global,ContactReceipt* o,ContactSample& s){
    const U stack=ptr(ptr(global+0x9c70)+0x1a8),array=ptr(stack+0x10);unsigned n=0;U length=0;
    if(!stack||!array||!read(stack+0x20,n)||!n||n>128||!read(array+0x18,length)||length<n||length>128)return;s.mainContext=ptr(array+0x20+8ULL*(n-1));
    if(!contactExact(b,s.mainContext,0x57b3288))return;s.view=ptr(s.mainContext+0x450);if(!contactExact(b,s.view,0x57b3860))return;s.panel=ptr(s.view+0x1f8);if(!s.panel)return;
    for(unsigned kind=0;kind<2;++kind){const U reusable=ptr(s.panel+(kind?0x20:0x28));U items=0;unsigned count=0;if(!contactList(ptr(reusable+0x40),items,count,kContactOptions)||count+s.optionCount>kContactOptions)return;
        for(unsigned i=0;i<count;++i){if(GetTickCount64()>=HR_DEADLINE)return;auto& r=s.options[s.optionCount++];r.ownerStatus=1;r.item=ptr(items+0x20+8ULL*i);r.panel=kind;r.index=i;r.status=2;if(!contactExact(b,r.item,0x57e59d8))return;r.button=ptr(r.item+0x30);if(!contactExact(b,r.button,0x579f538)||!contactText(b,ptr(r.item+0x38),r))return;contactCallback(b,r);contactOptionOwner(b,o,s,r);}
    }s.optionsStatus=0;
}
bool contactSample(U b,ContactReceipt* o,ContactSample& s,bool first){
    const auto& c=o->control;const U avatar=c.observation.after.avatar;
    if(!contactContext(b,s,c.after.global)||CONTACT_PAGE_START>s.entityCount||s.avatarId!=c.observation.after.avatarId)return false;
    contactRow(b,avatar,s.avatarId,0xffffffffU,true,s.rows[0]);unsigned count=1,page=CONTACT_PAGE_START;if(first)o->count=1;
    for(unsigned i=CONTACT_PAGE_START;i<s.entityCount&&count<kContactRows;++i){if(GetTickCount64()>=HR_DEADLINE)return false;const U at=s.entries+0x20+24ULL*i;int hash=-1;unsigned id=0;if(!read(at,hash))return false;page=i+1;if(first)o->pageEnd=page;if(hash<0)continue;const U entity=ptr(at+16);if(!entity||!read(at+8,id)||!id)return false;if(entity==avatar){if(id!=s.avatarId)return false;continue;}contactRow(b,entity,id,i,false,s.rows[count++]);if(first)o->count=count;}
    if(first){o->count=count;o->pageEnd=page;}else if(count!=o->count||page!=o->pageEnd)return false;
    contactMotion(b,avatar,o,s.motion);contactOptions(b,c.after.global,o,s);return true;
}
void contact(ContactReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!contactCode(b,o))return;
    o->moduleBase=b;ExecuteControl(&o->control);const auto& c=o->control;if(c.status||!c.stateStable||!c.observation.stable||!c.after.trialReady||c.after.exitReady||!bound(c.after)||c.observation.after.avatarStatus!=2)return;o->stage=2;
    if(!contactSample(b,o,o->first,true)||!contactSample(b,o,o->second,false))return;
    PlaySample last{};if(sample(b,last,&o->control.observation)!=c.observation.readableAfter||!stable(c.observation.after,last))return;TrialState finish{};state(b,last,finish,&o->control);if(std::memcmp(&finish,&c.after,sizeof(finish))||!bound(finish))return;
    o->stable=!std::memcmp(&o->first,&o->second,sizeof(ContactSample));o->stage=3;o->status=o->stable?0U:2U;
}
}
void ExecuteContact(ContactReceipt* o) noexcept {if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=7;o->status=1;o->stage=1;o->operation=17;o->resourcesReleased=1;o->pageStart=o->pageEnd=CONTACT_PAGE_START;
    o->first.mapStatus=o->second.mapStatus=o->first.optionsStatus=o->second.optionsStatus=o->first.motion.status=o->second.motion.status=1;
    auto& c=o->control;c.bytes=sizeof(c);c.version=2;c.status=1;c.stage=1;c.operation=3;c.resourcesReleased=1;c.observation.bytes=sizeof(PlayReceipt);c.observation.version=1;c.observation.status=1;c.observation.targetLevel=PLAY_TARGET_LEVEL;c.observation.before.positionStatus=c.observation.after.positionStatus=1;
    __try{contact(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}}
