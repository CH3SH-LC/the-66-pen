#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "display_text.h"
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
bool code(const GameContextSnapshot& s,DisplayTextReceipt* o){
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

using Str=void*(*)(const char*,std::int32_t);
using Fn1=void(*)(void*);
U string(U base,const char* x){return reinterpret_cast<U>(reinterpret_cast<Str>(base+0x526de0)(x,static_cast<int>(std::strlen(x))));}
bool text(U p,char16_t* chars,int& len){len=0;std::memset(chars,0,128);return p&&read(p+0x10,len)&&len>=0&&len<64&&(!len||memory(nullptr,p+0x14,chars,len*2));}
bool equal(U p,const char16_t* expected){char16_t chars[64]{};int len=0;return text(p,chars,len)&&std::char_traits<char16_t>::length(expected)==static_cast<std::size_t>(len)&&!std::memcmp(chars,expected,len*2);}
U at(U l,int i){int n=0;if(!l||!read(l+0x18,n)||n<0||n>4096||i<0||i>=n)return 0;const U a=ptr(l+0x10);U cap=0;if(!a||!read(a+0x18,cap)||cap<static_cast<U>(n)||cap>8192)return 0;return ptr(a+0x20+static_cast<U>(i)*8);}
bool updateLabels(const GameContextSnapshot& s,DisplayTextReceipt* o,unsigned which){
 auto& r=o->hosts[which];const U b=s.moduleBase;const unsigned count=which?2:1;
 const ge::templates::TemplateReadSource source{nullptr,memory};
 const ge::component_edit::Evidence e{b,s.global,r.owner,r.attachment.component.wrapper,r.config,17,true};
 const ge::component_edit::NativeCalls calls{reinterpret_cast<ge::component_edit::OpenTransaction>(b+0xe827750),reinterpret_cast<ge::component_edit::SnapshotComponent>(b+0x107abdf0),reinterpret_cast<ge::component_edit::NotifyComponent>(b+0x9c26c70),reinterpret_cast<ge::component_edit::CloseTransaction>(b+0xc7bab90)};
 ge::component_edit::BeginComponentEdit(source,calls,e,&r.edit);if(r.edit.code!=ge::component_edit::Code::snapshot_ready)return false;
 const char* label=which?u8"种田（消耗1颗种子）":u8"打开商店";
 const U p=at(ptr(r.config+0x38),0),v=string(b,label);if(!p||!v)return false;
 reinterpret_cast<void(*)(void*,std::uint32_t,void*)>(b+0x9438b60)(reinterpret_cast<void*>(p),0xbde64e3e,reinterpret_cast<void*>(v));
 reinterpret_cast<Fn1>(b+0x9438510)(reinterpret_cast<void*>(p));
 ge::component_edit::CompleteComponentEdit(source,calls,e,&r.edit);
 if(r.edit.code!=ge::component_edit::Code::complete||!capture(b,r,count)||!equal(ptr(p+0x30),which?u"种田（消耗1颗种子）":u"打开商店"))return false;
 r.readbackVerified=1;r.status=0;return true;
}
void execute(const GameContextSnapshot* before,DisplayTextReceipt* o){
 o->status=1;o->stage=1;std::memcpy(&o->expectedScene,TAB_EXPECTED_SNAPSHOT,sizeof(o->expectedScene));
 if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||!scene(*before,o->expectedScene)||!code(*before,o))return;
 const U b=before->moduleBase;constexpr std::uint32_t groups[]={TAB_USAGE_GROUPS};
 for(auto g:groups){reinterpret_cast<void(*)(unsigned)>(b+0x524250)(g);++o->metadataCalls;}
 o->stage=2;const U manager=ptr(before->global+0xee80),mi=ptr(b+0x5903e10);if(!manager||!mi)return;
 const U resource=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,unsigned,void*)>(b+0x142a0540)(reinterpret_cast<void*>(manager),1,reinterpret_cast<void*>(mi)));if(!resource)return;
 const U prop=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,unsigned)>(b+0x8678480)(reinterpret_cast<void*>(resource),66));
 if(!prop||ptr(prop)!=ptr(b+0x57e1fc0))return;o->textProperty=prop;
 U registry=ptr(prop+0x38);if(!registry||!read(registry+0x28,o->language)||o->language!=2)return;
 U entries=ptr(registry+0x18);if(!entries||!read(entries+0x18,o->beforeCount)||o->beforeCount>4096)return;
 for(unsigned i=0;i<2;++i){auto& r=o->hosts[i];r.entityId=i?1077936133:1077936131;unsigned found=0;
  for(unsigned j=0;j<before->entityCaptured;++j)if(before->entities[j].id==r.entityId){r.owner=before->entities[j].owner;++found;}
  if(found!=1||!r.owner)return;
  ge::component_attachment::CaptureComponents({nullptr,memory},r.owner,&r.attachmentWork.capture,&r.attachmentWork.before);
  if(r.attachmentWork.before.code!=ge::component_attachment::CaptureCode::complete)return;
  unsigned got=0;for(unsigned j=0;j<r.attachmentWork.before.count;++j){const auto& v=r.attachmentWork.before.rows[j];if(v.kind==17){r.attachment.component=v;r.config=v.config;++got;}}
  if(got!=1||!capture(b,r,i?2:1))return;
  if(!equal(ptr(r.options[0].pointer+0x30),i?u"播种（消耗1颗种子）":u"打开农场商店"))return;
 }
 o->attempted=1;o->stage=3;
 for(unsigned i=0;i<2;++i){if(!updateLabels(*before,o,i))return;++o->completedHosts;}
 // This is the editor's native text refresh: collect from the entire current
 // export, then reconcile its language resource. It does not upload or play.
 o->stage=4;reinterpret_cast<void(*)(void*,bool)>(b+0x13d15330)(reinterpret_cast<void*>(prop),true);
 registry=ptr(prop+0x38);entries=ptr(registry+0x18);
 if(!entries||!read(entries+0x18,o->afterCount)||o->afterCount>4096)return;
 const char16_t* expected[]={u"田园种子",u"新鲜作物",u"田园币",u"打开商店",u"种田（消耗1颗种子）",u"收获作物"};
 // Keep the existing enable/localization flags. Fill the primary-language
 // value through the same editor setter used by the language table.
 for(unsigned k=0;k<6;++k){auto& row=o->texts[k];row.index=-1;unsigned found=0;U entry=0;
  for(unsigned i=0;i<o->afterCount;++i){U t=at(entries,static_cast<int>(i));if(t&&equal(ptr(t+0x20),expected[k])){entry=t;row.index=static_cast<int>(i);++found;}}
  if(found!=1||ptr(entry)!=ptr(b+0x57e86e0))return;
  if(!text(ptr(entry+0x20),row.source,row.sourceLength)||!read(entry+0x34,row.enabled))return;
  U oldText=0;reinterpret_cast<bool(*)(void*,unsigned,U*)>(b+0x11796380)(reinterpret_cast<void*>(entry),o->language,&oldText);
  if(!text(oldText,row.before,row.beforeLength))return;row.language=o->language;
  reinterpret_cast<void(*)(void*,int,unsigned,void*)>(b+0x13d1cb40)(reinterpret_cast<void*>(prop),row.index,o->language,reinterpret_cast<void*>(ptr(entry+0x20)));
  U afterText=0;if(!reinterpret_cast<bool(*)(void*,unsigned,U*)>(b+0x11796380)(reinterpret_cast<void*>(entry),o->language,&afterText)||!text(afterText,row.after,row.afterLength)||!equal(afterText,expected[k]))return;
  unsigned char flag=255;if(!read(entry+0x34,flag)||flag!=row.enabled)return;++o->translatedCount;
 }
 o->stage=5;CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=scene(*before,o->afterScene)?1U:0U;
 if(!o->sceneUnchanged)return;o->status=0;o->stage=20;
}
}
void ExecuteDisplayTextAction(const GameContextSnapshot* s,DisplayTextReceipt* o) noexcept {
 if(!s||!o)return;std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=1;
 __try{execute(s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->sehCode=GetExceptionCode();o->status=2;}
}
