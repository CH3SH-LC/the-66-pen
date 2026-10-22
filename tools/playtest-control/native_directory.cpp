// Exact current trial's exported source directory. No enumeration/getter calls.
#include "native_directory.h"
#include "native_contact.cpp"
#if DIRECTORY_OPERATION != 18
#error "Fixed source-directory observation required"
#endif
namespace {
bool directoryCode(U b,DirectoryReceipt* o){
    static constexpr unsigned rvas[]={DIRECTORY_CODE_RVAS};static constexpr unsigned char bytes[][32]={DIRECTORY_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,bytes[i],32)){o->contact.control.observation.failedRva=rvas[i];return false;}
    return true;
}
void directorySample(U b,DirectoryReceipt* o,DirectorySample& s){
    s.status=1;const auto& c=o->contact.control;s.global=c.after.global;s.levelManager=ptr(s.global+0xa150);s.levelData=ptr(s.levelManager+0x68);s.editData=ptr(s.levelData+0x20);
    s.editClass=ptr(s.editData);s.expectedEditClass=ptr(b+0x57cad48);s.expectedCommonClass=ptr(b+0x57dc148);s.expectedContainerClass=ptr(b+0x57dc0b8);
    if(s.levelData!=c.after.data||s.levelData!=c.after.cache||s.editData!=c.after.cacheEditData||!s.editClass||s.editClass!=s.expectedEditClass)return;
    s.commonData=ptr(s.editData+0x20);s.commonClass=ptr(s.commonData);if(!s.commonClass||s.commonClass!=s.expectedCommonClass)return;
    s.container=ptr(s.commonData+0x28);s.containerClass=ptr(s.container);if(!s.containerClass||s.containerClass!=s.expectedContainerClass)return;
    unsigned short count=0;if(!read(s.containerClass+0xbe,count)||count<=35||count>4096)return;s.virtualCount=count;
    s.enumerator=ptr(s.containerClass+0x1e8);s.enumeratorMethodInfo=ptr(s.containerClass+0x1e8+8ULL*count);
    // f840f50 calls this slot. 1713e080's verified implementation reads +10
    // List, then 1886ba50 consumes its version/count/array. Never invoke it.
    if(s.enumerator!=b+0x1713e080||!s.enumeratorMethodInfo)return;
    s.list=ptr(s.container+0x10);s.entries=ptr(s.list+0x10);
    unsigned used=0;if(!s.list||!s.entries||!read(s.list+0x18,used)||used>kDirectoryRows||!read(s.list+0x1c,s.listVersion)||!read(s.entries+0x18,s.capacity)||s.capacity<used||s.capacity>65536)return;s.count=used;
    if(!memory(s.container,s.containerHeader,32)||!memory(s.list,s.listHeader,32))return;
    for(unsigned i=0;i<s.count;++i){if(GetTickCount64()>=HR_DEADLINE)return;auto& r=s.rows[i];r.record=ptr(s.entries+0x20+8ULL*i);r.klass=ptr(r.record);r.templateRecord=ptr(r.record+0x20);if(!r.record||!r.klass||!read(r.record+0x30,r.editorGuid)||!r.editorGuid||!r.templateRecord||!read(r.templateRecord+0x18,r.templateId))return;++s.recordCount;}
    s.status=0;
}
void directory(DirectoryReceipt* o){
    ExecuteContact(&o->contact);const auto& q=o->contact;const auto& c=q.control;
    if(q.status||q.stage!=3||!q.stable||!c.after.trialReady||!bound(c.after))return;
    const U b=q.moduleBase;o->moduleBase=b;if(!directoryCode(b,o))return;o->stage=2;
    directorySample(b,o,o->first);directorySample(b,o,o->second);
    PlaySample last{};if(sample(b,last,&o->contact.control.observation)!=c.observation.readableAfter||!stable(c.observation.after,last))return;
    TrialState finish{};state(b,last,finish,&o->contact.control);if(std::memcmp(&finish,&c.after,sizeof(finish))||!bound(finish))return;
    o->stable=!std::memcmp(&o->first,&o->second,sizeof(DirectorySample));o->stage=3;o->status=o->stable?0U:2U;
}
}
void ExecuteDirectory(DirectoryReceipt* o) noexcept {if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=8;o->status=1;o->stage=1;o->operation=18;o->resourcesReleased=1;o->first.status=o->second.status=1;
    __try{directory(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}}
