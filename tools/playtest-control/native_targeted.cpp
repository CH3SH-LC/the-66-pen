// Atomic targeted native option: observe and bind the actual callback model on
// the game thread immediately before normal Button.Press. No result mutation.
#include "native_targeted.h"
#include "native_directory.cpp"
#include <algorithm>
#if TARGETED_OPERATION != 19
#error "Fixed targeted interaction required"
#endif
namespace {
bool targetedCode(U b,TargetedReceipt* o){
    static constexpr unsigned rvas[]={TARGETED_CODE_RVAS};static constexpr unsigned char heads[][32]={TARGETED_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,heads[i],32)){o->stopReason=2;return false;}
    static constexpr unsigned flags[]={TARGETED_HOTFIX_RVAS};for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->stopReason=2;return false;}}return true;
}
bool targetedDirectory(const DirectorySample& s,DirectoryRow& selected,U* keys){
    if(s.status||s.recordCount!=s.count||!s.count||s.count>kDirectoryRows)return false;
    unsigned found=0;for(unsigned i=0;i<s.count;++i){const auto& r=s.rows[i];if(!r.editorGuid||!r.record)return false;keys[i]=r.editorGuid;keys[kDirectoryRows+i]=r.record;if(r.editorGuid==TARGETED_GUID){selected=r;++found;}}
    std::sort(keys,keys+s.count);std::sort(keys+kDirectoryRows,keys+kDirectoryRows+s.count);
    for(unsigned i=1;i<s.count;++i)if(keys[i]==keys[i-1]||keys[kDirectoryRows+i]==keys[kDirectoryRows+i-1])return false;return found==1;
}
bool targetedMap(const ContactSample& s,const ContactOption& r){
    if(s.mapStatus||r.ownerStatus||r.status||!r.active||!r.enabled||r.ownerRuntimeId!=TARGETED_RUNTIME_ID||r.owner.runtimeId!=TARGETED_RUNTIME_ID||r.owner.status||r.owner.flags!=3||r.owner.localAvatar)return false;
    unsigned byRuntime=0,byGuid=0,reverse=0;bool mapped=false,back=false;
    for(unsigned i=0;i<s.mapCount;++i){const auto& x=s.mappings[i];if(x.hash<0)continue;if(x.runtimeId==TARGETED_RUNTIME_ID){++byRuntime;mapped=x.editorGuid==TARGETED_GUID&&x.beyondId!=0;}if(x.editorGuid==TARGETED_GUID)++byGuid;}
    for(unsigned i=0;i<s.reverseCount;++i){const auto& x=s.reverse[i];if(x.hash>=0&&x.editorGuid==TARGETED_GUID){++reverse;back=x.runtimeId==TARGETED_RUNTIME_ID;}}
    return mapped&&back&&byRuntime==1&&byGuid==1&&reverse==1;
}
bool targetedInput(U b,TargetedReceipt* o,const ContactSample& s){
    const auto& c=o->directory.contact.control;auto& i=o->input;
    i.avatar=c.observation.after.avatar;i.avatarId=c.observation.after.avatarId;i.manager=ptr(c.after.global+0x9ca0);i.component=ptr(i.manager+0xc0);i.inputState=ptr(i.component+0x110);i.context=s.mainContext;i.view=s.view;
    i.componentClass=ptr(i.component);i.expectedClass=ptr(b+0x57f0aa8);i.componentOwner=ptr(i.component+0x28);i.managedAvatar=ptr(i.manager+0x90);i.strengthSlot=ptr(i.componentClass+0x450);i.activeSlot=ptr(i.componentClass+0x2f0);
    unsigned char disabled=255,owned=0,blocked=255,source=255;
    if(i.avatar!=TARGETED_AVATAR||i.avatarId!=TARGETED_AVATAR_ID||i.context!=TARGETED_CONTEXT||i.view!=TARGETED_VIEW||i.managedAvatar!=i.avatar||!i.componentClass||i.componentClass!=i.expectedClass||i.componentOwner!=i.avatar||!i.inputState||i.strengthSlot!=b+0x12b51c50||i.activeSlot!=b+0x12b526e0)return false;
    if(!read(i.inputState+0x42,disabled)||disabled||!read(i.avatar+0x49b,owned)||owned!=1||!read(i.context+0x766,blocked)||blocked||!read(i.manager+0x167,source)||source>1)return false;
    i.disabled=disabled;i.owned=owned;i.blocked=blocked;i.sourceActive=source;i.valid=1;return true;
}
void targeted(TargetedReceipt* o,ContactSample* fresh,U* keys){
    ExecuteDirectory(&o->directory);auto& d=o->directory;auto& c=d.contact;const auto& before=c.first;
    if(d.status||d.stage!=3||!d.stable||d.first.status||c.status||!c.stable||!c.control.after.trialReady||!bound(c.control.after)){o->stopReason=1;return;}
    const U b=d.moduleBase;o->moduleBase=b;o->stage=2;if(!targetedCode(b,o))return;
    static constexpr unsigned char expected[]={TARGETED_OPTION_BYTES};static_assert(sizeof(expected)==sizeof(ContactOption),"exact immutable callback association");
    if(TARGETED_OPTION>=before.optionCount||before.optionsStatus||std::memcmp(&before.options[TARGETED_OPTION],expected,sizeof(expected))||!targetedMap(before,before.options[TARGETED_OPTION])){o->stopReason=3;return;}
    if(!targetedDirectory(d.first,o->source,keys)){o->stopReason=4;return;}
    // This is a new read in this callback, not an external pre/post claim. No
    // game frame, queued work, or yield is allowed before the actual callback.
    if(!contactContext(b,*fresh,c.control.after.global)){o->stopReason=5;return;}
    const unsigned calls=c.nativeCalls;contactOptions(b,c.control.after.global,&c,*fresh);o->nativeCalls+=c.nativeCalls-calls;c.nativeCalls=calls;
    if(fresh->optionsStatus||TARGETED_OPTION>=fresh->optionCount||fresh->entityManager!=before.entityManager||fresh->dictionary!=before.dictionary||fresh->entries!=before.entries||fresh->entityCount!=before.entityCount||fresh->entityVersion!=before.entityVersion||fresh->mainContext!=before.mainContext||fresh->view!=before.view||fresh->panel!=before.panel){o->stopReason=5;return;}
    if(fresh->mapCount!=before.mapCount||fresh->reverseCount!=before.reverseCount||fresh->map!=before.map||fresh->reverseMap!=before.reverseMap||std::memcmp(fresh->mappings,before.mappings,sizeof(before.mappings))||std::memcmp(fresh->reverse,before.reverse,sizeof(before.reverse))){o->stopReason=5;return;}
    o->immediate=fresh->options[TARGETED_OPTION];
    if(std::memcmp(&o->immediate,expected,sizeof(expected))||!targetedMap(*fresh,o->immediate)||!targetedInput(b,o,*fresh)){o->stopReason=6;return;}
    ++o->nativeCalls;o->input.frame=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();o->checkedTick=GetTickCount64();
    // The final pure memory read detects list-item reuse and callback swaps
    // even if the button pointer itself has remained unchanged.
    ContactOption last{};last.item=o->immediate.item;last.button=ptr(last.item+0x30);last.panel=o->immediate.panel;last.index=o->immediate.index;last.ownerStatus=1;
    if(last.button!=o->immediate.button||!contactText(b,ptr(last.item+0x38),last)){o->stopReason=7;return;}contactCallback(b,last);
    const unsigned lastCalls=c.nativeCalls;contactOptionOwner(b,&c,*fresh,last);o->nativeCalls+=c.nativeCalls-lastCalls;c.nativeCalls=lastCalls;
    if(std::memcmp(&last,&o->immediate,sizeof(last))||ptr(d.first.levelManager+0x68)!=d.first.levelData||ptr(d.first.levelData+0x20)!=d.first.editData||ptr(d.first.container+0x10)!=d.first.list||ptr(d.first.list+0x10)!=d.first.entries||GetTickCount64()>=HR_DEADLINE){o->stopReason=7;return;}
    unsigned token=0,version=0,count=0;
    if(!read(c.control.after.task+0x50,token)||token!=c.control.after.token||!read(d.first.list+0x1c,version)||version!=d.first.listVersion||!read(d.first.list+0x18,count)||count!=d.first.count){o->stopReason=7;return;}
    unsigned guid=0,templateId=0;if(ptr(o->source.record)!=o->source.klass||ptr(o->source.record+0x20)!=o->source.templateRecord||!read(o->source.record+0x30,guid)||guid!=o->source.editorGuid||!read(o->source.templateRecord+0x18,templateId)||templateId!=o->source.templateId){o->stopReason=7;return;}
    o->guardVerified=1;o->callTick=GetTickCount64();o->actionAttempted=1;++o->nativeCalls;
    reinterpret_cast<void(*)(void*)>(b+0x19dc6600)(reinterpret_cast<void*>(last.button));
    o->actionReturned=1;o->stage=3;o->status=0;
}
}
void ExecuteTargeted(TargetedReceipt* o) noexcept {
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=9;o->status=1;o->stage=1;o->operation=19;o->resourcesReleased=1;o->optionOrdinal=TARGETED_OPTION;o->editorGuid=TARGETED_GUID;o->runtimeId=TARGETED_RUNTIME_ID;o->immediate.status=2;o->immediate.ownerStatus=1;
    auto fresh=static_cast<ContactSample*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(ContactSample)));auto keys=static_cast<U*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,2*kDirectoryRows*sizeof(U)));
    __try{if(fresh&&keys)targeted(o,fresh,keys);else{o->stopReason=8;ExecuteDirectory(&o->directory);}}
    __except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
    if(fresh)HeapFree(GetProcessHeap(),0,fresh);if(keys)HeapFree(GetProcessHeap(),0,keys);
}
