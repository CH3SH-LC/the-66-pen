#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_tabs.h"
#include <cstring>
#include <string>
#if HR_ACTION != 12 || !TA_TABS_REVIEWED || !GS_REVIEWED_ACTION_PROFILE
#error "Dedicated native option cards contract required"
#endif
namespace {
using U=std::uint64_t;
bool memory(void*,U at,void* out,std::size_t n) noexcept {
    if(!out||!n||at<0x10000||at>=0x800000000000ULL||n>0x800000000000ULL-at)return false;
    std::size_t done=0;
    while(done<n){MEMORY_BASIC_INFORMATION r{};const auto p=at+done;
        if(VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||
           (r.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
        const auto left=r.RegionSize-static_cast<std::size_t>(p-reinterpret_cast<U>(r.BaseAddress));
        const auto part=n-done<left?n-done:left;
        __try{std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(p),part);}
        __except(EXCEPTION_EXECUTE_HANDLER){return false;}done+=part;
    }return true;
}
template<class T> bool read(U p,T& v){return memory(nullptr,p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&v>=0x10000&&v<0x800000000000ULL?v:0;}
bool code(const GameContextSnapshot& s,NativeTabReceipt* o){
    if(s.moduleBase!=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"))||s.peTimestamp!=HR_GAME_TIMESTAMP||s.peImageSize!=HR_GAME_IMAGE_SIZE)return false;
    constexpr std::uint32_t rvas[]={TAB_CODE_RVAS};constexpr unsigned char expected[][32]={TAB_CODE_BYTES};
    unsigned char actual[32]{};
    for(std::size_t i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i){
        if(!memory(nullptr,s.moduleBase+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->failedRva=rvas[i];return false;}}
    constexpr std::uint32_t flags[]={GS_PROFILE_HOTFIX_RVAS,TAB_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(s.moduleBase+r,v)||v){o->failedRva=r;o->failedValue=v;return false;}}
    return true;
}
bool scene(const GameContextSnapshot& a,const GameContextSnapshot& b){
    if(b.structSize!=sizeof(b)||b.status!=GS_OK||(b.flags&1951)!=1951||b.reserved!=1073741842||b.entityRejected||
       b.entityCaptured!=b.entityValidEntries||a.entityCaptured!=b.entityCaptured||b.entityCaptured>kMaxEntities||
       a.currentContext!=b.currentContext||a.global!=b.global||a.moduleBase!=b.moduleBase||
       a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||
       a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter)return false;
    for(std::uint32_t i=0;i<a.entityCaptured;++i){const auto& x=a.entities[i];const auto& y=b.entities[i];
        if(x.id!=y.id||x.owner!=y.owner||x.config!=y.config||x.context!=y.context||x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;}
    return true;
}
bool list(U list,std::uint32_t expected,U* items){std::int32_t n=-1;U cap=0,array=ptr(list+0x10);
    if(!array||!read(list+0x18,n)||n!=static_cast<std::int32_t>(expected)||!read(array+0x18,cap)||cap<expected||cap>64)return false;
    return memory(nullptr,array+0x20,items,expected*sizeof(U));}
bool capture(U base,TabHostResult& r,std::uint32_t count){
    U opts[2]{},coll[1]{};r.optionCount=count;r.colliderCount=1;
    if(!list(ptr(r.config+0x38),count,opts)||!list(ptr(r.config+0x30),1,coll))return false;
    r.collider=coll[0];r.sphere=ptr(r.collider+0x48);
    if(ptr(r.collider)!=ptr(base+0x57b8560)||!read(r.collider+0x5c,r.colliderShape)||r.colliderShape!=1||
       !r.sphere||!read(r.sphere+0x20,r.radius)||r.radius!=2.0f)return false;
    for(std::uint32_t i=0;i<count;++i){auto& t=r.options[i];t.pointer=opts[i];t.klass=ptr(t.pointer);
        const U text=ptr(t.pointer+0x30);
        if(t.klass!=ptr(base+0x57e8910)||!read(t.pointer+0x40,t.index)||!read(t.pointer+0x4c,t.sort)||
           !read(t.pointer+0x48,t.icon)||!read(t.pointer+0x50,t.filter)||!read(t.pointer+0x56,t.active)||
           !read(t.pointer+0x54,t.enabled)||!text||!read(text+0x10,t.textLength)||t.textLength<=0||t.textLength>=48||
           !memory(nullptr,text+0x14,t.text,t.textLength*sizeof(char16_t))||t.index!=static_cast<int>(i+1)||t.active!=(i==0))return false;
    }return true;
}
bool install(const GameContextSnapshot& s,NativeTabReceipt* o,unsigned which){
    auto& r=o->hosts[which];const U base=s.moduleBase;const unsigned count=which?2:1;
    const ge::templates::TemplateReadSource source{nullptr,memory};
    ge::component_attachment::AttachmentEvidence evidence{r.owner,ptr(r.owner),ptr(base+0x57b0058),ptr(base+0x57dda60),17,true};
    r.status=10;
    ge::component_attachment::EnsureComponentAttached(source,reinterpret_cast<ge::component_attachment::AttachComponent>(base+0x867c610),evidence,&r.attachmentWork,&r.attachment);
    // An existing component is not overwritten. A later run needs an explicit
    // recovery based on its receipt, never an automatic replay of setters.
    if(r.attachment.code!=ge::component_attachment::AttachCode::attached_verified)return false;
    r.config=r.attachment.component.config;
    const ge::component_edit::Evidence e{base,s.global,r.owner,r.attachment.component.wrapper,r.config,17,true};
    const ge::component_edit::NativeCalls calls{
        reinterpret_cast<ge::component_edit::OpenTransaction>(base+0xe827750),
        reinterpret_cast<ge::component_edit::SnapshotComponent>(base+0x107abdf0),
        reinterpret_cast<ge::component_edit::NotifyComponent>(base+0x9c26c70),
        reinterpret_cast<ge::component_edit::CloseTransaction>(base+0xc7bab90)};
    r.status=11;ge::component_edit::BeginComponentEdit(source,calls,e,&r.edit);
    if(r.edit.code!=ge::component_edit::Code::snapshot_ready)return false;
    U options[2]{},colliders[1]{};const U optionList=ptr(r.config+0x38);
    r.status=12;if(!list(optionList,1,options)||!list(ptr(r.config+0x30),1,colliders))return false;
    using SetInt=void(*)(void*,std::uint32_t,std::int32_t);
    using SetBool=void(*)(void*,std::uint32_t,bool);
    using SetText=void(*)(void*,std::uint32_t,void*);
    using SetFloat=void(*)(void*,std::uint32_t,float);
    using String=void*(*)(const char*,std::int32_t);
    using Factory=void*(*)(void*);
    using Add=void(*)(void*,void*,void*);
    const auto setIndex=reinterpret_cast<void(*)(void*,int)>(base+0x9438200);
    const char* labels[]={which?u8"播种（消耗1颗种子）":u8"打开农场商店",u8"收获作物"};
    const char16_t* labels16[]={which?u"播种（消耗1颗种子）":u"打开农场商店",u"收获作物"};
    for(unsigned i=0;i<count;++i){
        if(i){const U method=ptr(base+0x58bfe30);
            if(!method||ptr(method)!=ptr(optionList))return false;
            options[i]=reinterpret_cast<U>(reinterpret_cast<Factory>(base+0x95f6410)(reinterpret_cast<void*>(ptr(base+0x5a298b8))));
            if(!options[i]||ptr(options[i])!=ptr(base+0x57e8910))return false;
            // The exact closed List<Option>.Add MethodInfo is used in the
            // component initializer at1076d5aa;18baf8c0 also increments version.
            reinterpret_cast<Add>(base+0x18baf8c0)(reinterpret_cast<void*>(optionList),reinterpret_cast<void*>(options[i]),reinterpret_cast<void*>(method));
        }
        if(ptr(options[i])!=ptr(base+0x57e8910))return false;
        auto p=reinterpret_cast<void*>(options[i]);setIndex(p,static_cast<int>(i+1));
        reinterpret_cast<SetInt>(base+0x94393d0)(p,0x090aa9ab,static_cast<int>(i+1));
        auto text=reinterpret_cast<String>(base+0x526de0)(labels[i],static_cast<int>(std::strlen(labels[i])));
        if(!text)return false;
        reinterpret_cast<SetText>(base+0x9438b60)(p,0xbde64e3e,text);
        reinterpret_cast<SetBool>(base+0x9439240)(p,0x3d94f45f,i==0);
        reinterpret_cast<void(*)(void*)>(base+0x9438510)(p);
    }
    auto collider=reinterpret_cast<void*>(colliders[0]);
    if(ptr(colliders[0])!=ptr(base+0x57b8560))return false;
    reinterpret_cast<SetInt>(base+0x12ce23f0)(collider,0x99112b76,1);
    auto sphere=reinterpret_cast<void*>(ptr(colliders[0]+0x48));if(!sphere)return false;
    reinterpret_cast<SetFloat>(base+0xe80b1b0)(sphere,0x0dba4cb3,2.0f);
    r.status=13;if(!capture(base,r,count))return false;
    for(unsigned i=0;i<count;++i){const auto& t=r.options[i];
        if(std::char_traits<char16_t>::length(labels16[i])!=static_cast<std::size_t>(t.textLength)||
           std::memcmp(t.text,labels16[i],t.textLength*sizeof(char16_t)))return false;}
    r.readbackVerified=1;r.status=14;ge::component_edit::CompleteComponentEdit(source,calls,e,&r.edit);
    if(r.edit.code!=ge::component_edit::Code::complete)return false;
    r.status=0;return true;
}
void execute(const GameContextSnapshot* before,NativeTabReceipt* o){
    o->status=1;o->stage=1;std::memcpy(&o->expectedScene,TAB_EXPECTED_SNAPSHOT,sizeof(o->expectedScene));
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||
       !scene(*before,o->expectedScene)||!code(*before,o))return;
    o->stage=2;
    for(unsigned i=0;i<2;++i){auto& r=o->hosts[i];r.entityId=i?1077936133:1077936131;unsigned found=0;
        for(unsigned j=0;j<before->entityCaptured;++j)if(before->entities[j].id==r.entityId){r.owner=before->entities[j].owner;++found;}
        if(found!=1||!r.owner)return;
        ge::component_attachment::CaptureComponents({nullptr,memory},r.owner,&r.attachmentWork.capture,&r.attachmentWork.before);
        if(r.attachmentWork.before.code!=ge::component_attachment::CaptureCode::complete)return;
        for(unsigned j=0;j<r.attachmentWork.before.count;++j)if(r.attachmentWork.before.rows[j].kind==17)return;
    }
    o->stage=3;constexpr std::uint32_t groups[]={TAB_USAGE_GROUPS};
    for(auto group:groups){o->attempted=1;reinterpret_cast<void(*)(unsigned)>(before->moduleBase+0x524250)(group);++o->metadataCalls;}
    for(unsigned i=0;i<2;++i){o->stage=10+i;if(!install(*before,o,i))return;++o->completedHosts;}
    CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=scene(*before,o->afterScene)?1U:0U;
    o->stage=20;if(!o->sceneUnchanged)return;o->status=0;
}
}
void ExecuteNativeTabAction(const GameContextSnapshot* s,NativeTabReceipt* o) noexcept {
    if(!s||!o)return;std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=1;
    __try{execute(s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->sehCode=GetExceptionCode();o->status=2;}
}
