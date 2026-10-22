#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_properties.h"
#include "../template-authoring/template_catalog_capture.h"
#include <cstring>
#if HR_ACTION != 24 || !PROPERTIES_REVIEWED || !GS_REVIEWED_ACTION_PROFILE
#error Dedicated action24 protocol30 required
#endif
#ifdef PROPERTIES_PRIVATE_TEST
extern void* PropertiesTestNative(unsigned);
extern bool PropertiesTestRead(std::uint64_t,void*,std::size_t);
#endif
namespace {
using U=std::uint64_t;using namespace ge::templates;
template<class F> F native(U b,unsigned r){
#ifdef PROPERTIES_PRIVATE_TEST
 (void)b;return reinterpret_cast<F>(PropertiesTestNative(r));
#else
 return reinterpret_cast<F>(b+r);
#endif
}
bool memory(U p,void* out,std::size_t n) noexcept {
#ifdef PROPERTIES_PRIVATE_TEST
 return PropertiesTestRead(p,out,n);
#else
 if(!out||!n||p<0x10000||p>=0x800000000000ULL||n>0x800000000000ULL-p)return false;
 std::size_t done=0;while(done<n){MEMORY_BASIC_INFORMATION r{};const U at=p+done;
  if(VirtualQuery(reinterpret_cast<void*>(at),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||(r.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
  const auto left=r.RegionSize-static_cast<std::size_t>(at-reinterpret_cast<U>(r.BaseAddress)),part=n-done<left?n-done:left;
  __try{std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(at),part);}__except(EXCEPTION_EXECUTE_HANDLER){return false;}done+=part;
 }return true;
#endif
}
bool catalogRead(void*,U p,void* out,std::size_t n) noexcept {return memory(p,out,n);}
template<class T> bool read(U p,T& v){return memory(p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&TemplatePointer(v)?v:0;}
U hash(const void* data,std::size_t n,U h=1469598103934665603ULL){const auto p=static_cast<const unsigned char*>(data);for(std::size_t i=0;i<n;++i){h^=p[i];h*=1099511628211ULL;}return h;}
bool equal(const PropertyState& a,const PropertyState& b){return !std::memcmp(&a,&b,sizeof(a));}
bool text(U str,std::uint16_t* out,unsigned& length){
 std::memset(out,0,256);length=0;if(!str)return true;
 int n=-1,again=-1;if(!read(str+0x10,n)||n<0||n>=128)return false;
 if(n&&!memory(str+0x14,out,static_cast<std::size_t>(n)*2))return false;
 if(!read(str+0x10,again)||n!=again)return false;length=static_cast<unsigned>(n);return true;
}
U property(U b,U resource,unsigned kind){return reinterpret_cast<U>(native<void*(*)(void*,unsigned)>(b,0x8678480)(reinterpret_cast<void*>(resource),kind));}
bool named(U b,U owner,U& prop,PropertyState& s){
 const U found=property(b,owner,1);if(!found||ptr(found)!=ptr(b+0x57b5318)||ptr(found+0x20)!=owner||(prop&&prop!=found))return false;prop=found;
 U value=ptr(found+0x30);unsigned length=0;std::uint16_t buf[128]{};
 if(!text(value,buf,length))return false;if(!length)value=ptr(found+0x38);
 return text(value,s.name,s.nameLength);
}
bool capture(U b,PropertyRow& r,PropertyState& s){
 s={};if(!r.resource||!named(b,r.resource,r.nameProperty,s))return false;
 const unsigned kind=r.subtype==9?39U:41U;const U prop=property(b,r.resource,kind),data=ptr(prop+0x30);
 if(!prop||ptr(prop)!=ptr(b+(r.subtype==9?0x57b3608:0x57e11b0))||ptr(prop+0x20)!=r.resource||!data||ptr(data)!=ptr(b+(r.subtype==9?0x57e8af0:0x57e8730))||(r.dataProperty&&r.dataProperty!=prop)||(r.data&&r.data!=data))return false;
 r.dataProperty=prop;r.data=data;
 if(!read(data+(r.subtype==9?0x3c:0x2c),s.iconId))return false;
 if(native<unsigned(*)(void*,unsigned)>(b,r.subtype==9?0xb840280:0x8b31880)(reinterpret_cast<void*>(data),0xc0154b8d)!=s.iconId)return false;
 if(r.subtype==9){
  const U basic=ptr(data+0x18),inter=ptr(data+0x28);unsigned char trade=255;
  if(!basic||!inter||ptr(basic)!=ptr(b+0x57e83a8)||ptr(inter)!=ptr(b+0x57dcfc0)||ptr(basic+0x18)!=data||ptr(inter+0x20)!=data||(r.basic&&r.basic!=basic)||(r.inter&&r.inter!=inter)||!read(basic+0x40,s.stackLimit)||!read(inter+0x28,trade)||trade>1)return false;
  r.basic=basic;r.inter=inter;s.isTradeable=trade;
  if(native<unsigned(*)(void*,unsigned)>(b,0xebaae50)(reinterpret_cast<void*>(basic),0x13abec4a)!=s.stackLimit||native<bool(*)(void*,unsigned)>(b,0xeb7a3a0)(reinterpret_cast<void*>(inter),0xf4ce55d9)!=(trade!=0))return false;
 }return true;
}
bool scene(const GameContextSnapshot& a,const GameContextSnapshot& b){
 if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||a.status!=GS_OK||b.status!=GS_OK||(a.flags&1951)!=1951||(b.flags&1951)!=1951||a.reserved!=PROPERTIES_LEVEL||b.reserved!=PROPERTIES_LEVEL||a.entityRejected||b.entityRejected||a.entityCaptured!=a.entityValidEntries||b.entityCaptured!=b.entityValidEntries||a.entityCaptured!=b.entityCaptured||a.entityCaptured>kMaxEntities||a.moduleBase!=b.moduleBase||a.global!=b.global||a.currentContext!=b.currentContext||a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter||std::memcmp(a.origin,b.origin,sizeof(a.origin)))return false;
 for(unsigned i=0;i<a.entityCaptured;++i){const auto& x=a.entities[i];const auto& y=b.entities[i];if(x.id!=y.id||x.owner!=y.owner||x.config!=y.config||x.context!=y.context||x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;}return true;
}
bool code(const GameContextSnapshot& s,PropertyReceipt& o){
#ifndef PROPERTIES_PRIVATE_TEST
 if(s.moduleBase!=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"))||s.peTimestamp!=HR_GAME_TIMESTAMP||s.peImageSize!=HR_GAME_IMAGE_SIZE)return false;
#endif
 static constexpr unsigned rvas[]={PROPERTIES_CODE_RVAS};static constexpr unsigned char bytes[][32]={PROPERTIES_CODE_BYTES};unsigned char actual[32]{};
 for(unsigned i=0;i<sizeof(rvas)/sizeof(*rvas);++i)if(!memory(s.moduleBase+rvas[i],actual,32)||std::memcmp(actual,bytes[i],32)){o.failedRva=rvas[i];return false;}
 static constexpr unsigned flags[]={GS_PROFILE_HOTFIX_RVAS,PROPERTIES_HOTFIX_RVAS};for(unsigned r:flags){unsigned char v=255;if(!read(s.moduleBase+r,v)||v){o.failedRva=r;o.failedValue=v;return false;}}return true;
}
bool icons(U b,unsigned category,unsigned* values,unsigned& count){
 const U list=reinterpret_cast<U>(native<void*(*)(unsigned)>(b,0x102e2180)(category)),array=ptr(list+0x10);U capacity=0;unsigned version=0,again=0;
 if(!list||!array||!read(list+0x18,count)||!count||count>kIconOptions||!read(list+0x1c,version)||!read(array+0x18,capacity)||capacity<count||capacity>8192)return false;
 for(unsigned i=0;i<count;++i){const U obj=ptr(array+0x20+i*8);unsigned cat=0,encoded=0;
  if(!obj||!read(obj+0x24,cat)||cat!=category||!read(obj+0x34,encoded))return false;
  values[i]=native<unsigned(*)(unsigned*)>(b,0xbb2c5e0)(&encoded);if(!values[i])return false;
  for(unsigned j=0;j<i;++j)if(values[j]==values[i])return false;
 }return read(list+0x1c,again)&&version==again;
}
bool contains(const unsigned* a,unsigned n,unsigned v){for(unsigned i=0;i<n;++i)if(a[i]==v)return true;return false;}
struct Edit {U manager,list,items,record,blob;unsigned count;int base,depth;unsigned char flags[3],dirty;};
bool edit(U b,U global,U prop,Edit& e){
 e={};e.manager=ptr(global+0xecd0);e.list=ptr(e.manager+0x18);e.items=ptr(e.list+0x10);U capacity=0;
 if(!e.manager||!e.list||!e.items||!read(e.list+0x18,e.count)||e.count>1||!read(e.items+0x18,capacity)||capacity<e.count||capacity>4096||!read(e.manager+0x30,e.base)||!read(e.manager+0x34,e.depth)||!read(e.manager+0x28,e.flags)||e.base<0||e.depth<e.base||e.flags[1]||e.flags[2])return false;
 if(e.count){e.record=ptr(e.items+0x20);e.blob=ptr(e.record+0x28);if(!prop||!e.record||ptr(e.record)!=ptr(b+0x5812cf8)||ptr(e.record+0x18)!=prop||!e.blob||!read(e.record+0x30,e.dirty))return false;}return true;
}
// Hash every resource's property dictionary and supported definition payload.
// Selected scalar bytes are masked, so preservation is checked independently
// from desired-value readback. No arbitrary object graph serialization claim.
bool region(U p,unsigned n,unsigned zero,unsigned width,U& h){unsigned char bytes[256]{};if(n>256||!memory(p,bytes,n))return false;if(width){if(zero+width>n)return false;std::memset(bytes+zero,0,width);}h=hash(bytes,n,h);return true;}
bool guard(U b,U owner,unsigned subtype,unsigned mask,U& h){
 h=1469598103934665603ULL;const U d=ptr(owner+0x20),entries=ptr(d+0x18),buckets=ptr(d+0x20);U cap=0,bcap=0;
 if(!d||!region(d,0x40,0,0,h)||!entries||!buckets||!read(entries+0x18,cap)||cap>256||!read(buckets+0x18,bcap)||bcap>256)return false;
 unsigned char buf[6144]{};if(cap&&!memory(entries+0x20,buf,static_cast<std::size_t>(cap)*24))return false;h=hash(buf,static_cast<std::size_t>(cap)*24,h);
 if(bcap&&!memory(buckets+0x20,buf,static_cast<std::size_t>(bcap)*4))return false;h=hash(buf,static_cast<std::size_t>(bcap)*4,h);
 const U name=property(b,owner,1);if(name){if(ptr(name+0x20)!=owner||!region(name+0x30,24,0,(mask&1)?8:0,h))return false;PropertyState s{};U np=0;if(!named(b,owner,np,s))return false;if(!(mask&1))h=hash(&s,sizeof(s),h);}
 if(subtype==9||subtype==11){const U p=property(b,owner,subtype==9?39:41),data=ptr(p+0x30);if(!p||ptr(p+0x20)!=owner||!data||!region(p+0x30,8,0,0,h))return false;
  if(subtype==9){if(!region(data+0x10,0x30,0x2c,(mask&2)?4:0,h))return false;const U basic=ptr(data+0x18),inter=ptr(data+0x28);
   if(!basic||!inter||!region(basic+0x10,0x38,0x30,(mask&4)?4:0,h)||!region(inter+0x10,0x28,0x18,(mask&8)?1:0,h))return false;
  }else if(!region(data+0x10,0x28,0x1c,(mask&2)?4:0,h))return false;
 }return true;
}
bool closeOwned(const GameContextSnapshot& s,PropertyRow& r,const Edit& start){
 Edit now{};if(!r.openCalled||r.closeCalled||!r.transaction||!edit(s.moduleBase,s.global,r.dataProperty,now)||now.manager!=start.manager||now.depth!=start.depth+1)return false;
 r.closeCalled=1;native<void(*)(void*)>(s.moduleBase,0xc7bab90)(reinterpret_cast<void*>(r.transaction));
 if(!edit(s.moduleBase,s.global,0,now))return false;r.pendingAfter=now.count;r.depthAfter=static_cast<unsigned>(now.depth);r.closed=now.count==0&&now.depth==start.depth?1U:0U;return r.closed!=0;
}
bool mutate(const GameContextSnapshot& s,PropertyReceipt& o,PropertyRow& r){
 const U b=s.moduleBase;Edit start{},now{};if(!edit(b,s.global,0,start)||start.count||start.depth!=start.base)return false;
 PropertyState fresh{};if(!capture(b,r,fresh)||!equal(fresh,r.before))return false;r.pendingBefore=start.count;r.depthBefore=static_cast<unsigned>(start.depth);
 r.stage=1;r.uncertain=1;
 if(r.mask&1){
  // Allocate only a real managed string; existing name/property fields are
  // changed solely by the complete native rename service.
  char utf8[512]{};const int bytes=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,reinterpret_cast<const wchar_t*>(r.desired.name),static_cast<int>(r.desired.nameLength),utf8,sizeof(utf8),nullptr,nullptr);if(bytes<=0)return false;
  const U str=reinterpret_cast<U>(native<void*(*)(const char*,int)>(b,0x526de0)(utf8,bytes));
  if(!str)return false;r.renameCalled=1;++o.nativeCalls;
  if(!native<bool(*)(void*,unsigned,void*,bool)>(b,0xb0a6ec0)(reinterpret_cast<void*>(o.manager),r.id,reinterpret_cast<void*>(str),false))return false;
  if(!edit(b,s.global,0,now)||now.count||now.depth!=start.depth)return false;
 }
 r.stage=2;
 if(r.mask&14){
  r.openCalled=1;++o.nativeCalls;r.transaction=reinterpret_cast<U>(native<void*(*)(void*,bool,bool)>(b,0xe827750)(nullptr,false,false));
  bool success=false;
  do {if(!r.transaction||!edit(b,s.global,0,now)||now.count||now.depth!=start.depth+1)break;
   r.snapshotCalled=1;native<void(*)(void*,void*,bool)>(b,0x107abdf0)(reinterpret_cast<void*>(r.dataProperty),nullptr,false);
   if(!edit(b,s.global,r.dataProperty,now)||now.count!=1||now.depth!=start.depth+1||now.dirty)break;
   r.pendingSnapshot=now.count;r.record=now.record;r.beforeBlob=now.blob;r.stage=3;
   if(r.mask&2){++r.setterCalls;native<void(*)(void*,unsigned,unsigned)>(b,r.subtype==9?0xb840d40:0x8b30d70)(reinterpret_cast<void*>(r.data),0xc0154b8d,r.desired.iconId);}
   if(r.mask&4){++r.setterCalls;native<void(*)(void*,unsigned,unsigned)>(b,0xebabe30)(reinterpret_cast<void*>(r.basic),0x13abec4a,r.desired.stackLimit);}
   if(r.mask&8){++r.setterCalls;native<void(*)(void*,unsigned,bool)>(b,0xeb7a7e0)(reinterpret_cast<void*>(r.inter),0xf4ce55d9,r.desired.isTradeable!=0);}
   r.stage=4;r.notifyCalled=1;native<void(*)(void*,void*)>(b,0x9c26c70)(reinterpret_cast<void*>(start.manager),reinterpret_cast<void*>(r.dataProperty));
   if(!edit(b,s.global,r.dataProperty,now)||now.record!=r.record||now.blob!=r.beforeBlob||now.dirty!=1)break;success=true;
  }while(false);
  const bool closed=closeOwned(s,r,start);if(!success||!closed)return false;
 }else{r.pendingAfter=0;r.depthAfter=r.depthBefore;r.closed=1;}
 r.stage=5;
 if(!capture(b,r,r.after)||!equal(r.after,r.desired))return false;
 if(r.companion){PropertyState companion{};if(!named(b,r.companion,r.companionName,companion))return false;
  if((r.mask&1)&&(companion.nameLength!=r.desired.nameLength||std::memcmp(companion.name,r.desired.name,256)))return false;
 }r.companionNameVerified=1;r.readbackVerified=1;r.uncertain=0;r.stage=6;return true;
}
static TemplateCatalogCapture beforeCatalog,afterCatalog;static TemplateCatalogCaptureWorkspace catalogWorkspace;
void execute(const GameContextSnapshot* s,PropertyReceipt* o){
 std::memset(o,0,sizeof(*o));o->size=sizeof(*o);o->version=30;o->status=1;o->count=PROPERTIES_COUNT;o->mode=PROPERTIES_WRITE;
 if(!s||o->count<1||o->count>kPropertyBatch)return;
 const auto expected=reinterpret_cast<const GameContextSnapshot*>(PROPERTIES_EXPECTED);
 if(!scene(*expected,*s)||!code(*s,*o))return;o->stage=1;
 static constexpr unsigned groups[]={PROPERTIES_USAGE_GROUPS};for(auto group:groups)native<void(*)(unsigned)>(s->moduleBase,0x524250)(group);
 CaptureTemplateCatalog(s,{nullptr,catalogRead},&catalogWorkspace,&beforeCatalog);if(beforeCatalog.code!=TemplateCaptureCode::complete)return;
 o->manager=beforeCatalog.manager;o->catalogBefore=hash(&beforeCatalog,sizeof(beforeCatalog));
 if(!icons(s->moduleBase,9,o->itemIcons,o->itemIconCount)||!icons(s->moduleBase,8,o->currencyIcons,o->currencyIconCount))return;
 static constexpr PropertyRequest requests[]={PROPERTIES_REQUESTS};
 for(unsigned i=0;i<o->count;++i){const auto& q=requests[i];auto& r=o->rows[i];r.id=q.id;r.subtype=q.subtype;r.mask=q.mask;r.status=1;
  if((q.subtype!=9&&q.subtype!=11)||q.reserved||q.mask>15||(q.subtype==11&&(q.mask&12))||(!PROPERTIES_WRITE&&q.mask))return;
  for(unsigned j=0;j<i;++j)if(o->rows[j].id==r.id)return;
  for(unsigned j=0;j<beforeCatalog.primary.row_count;++j){const auto& x=beforeCatalog.primary_rows[j];if(x.id==q.id&&x.subtype==q.subtype)r.resource=x.resource;}
  if(!capture(s->moduleBase,r,r.before))return;r.desired=PROPERTIES_WRITE?q.desired:r.before;
  if constexpr(PROPERTIES_WRITE!=0){if(r.resource!=q.resource||r.nameProperty!=q.nameProperty||r.dataProperty!=q.dataProperty||!equal(r.before,q.expected))return;}
  if(r.desired.nameLength>=128||r.desired.isTradeable>1||(r.subtype==9&&!r.desired.stackLimit))return;
  PropertyState masked=r.before;if(q.mask&1){masked.nameLength=r.desired.nameLength;std::memcpy(masked.name,r.desired.name,256);}if(q.mask&2)masked.iconId=r.desired.iconId;if(q.mask&4)masked.stackLimit=r.desired.stackLimit;if(q.mask&8)masked.isTradeable=r.desired.isTradeable;
  if(!equal(masked,r.desired)||((q.mask&1)&&!r.desired.nameLength))return;
  r.iconAllowed=contains(r.subtype==9?o->itemIcons:o->currencyIcons,r.subtype==9?o->itemIconCount:o->currencyIconCount,r.desired.iconId)?1U:0U;
  if((q.mask&2)&&!r.iconAllowed)return;
  for(unsigned j=0;j<beforeCatalog.companion.row_count;++j){const auto& x=beforeCatalog.companion_rows[j];if(x.key==r.id){if(r.companion)return;r.companion=x.resource;}}
  if(r.subtype==9&&!r.companion)return;
  if(r.companion){PropertyState cs{};if(!named(s->moduleBase,r.companion,r.companionName,cs))return;}
 }
 for(unsigned side=0;side<2;++side){const unsigned count=side?beforeCatalog.companion.row_count:beforeCatalog.primary.row_count;
  for(unsigned j=0;j<count;++j){if(o->guardCount>=kPropertyGuards)return;auto& g=o->guards[o->guardCount++];g.companion=side;g.id=side?beforeCatalog.companion_rows[j].key:beforeCatalog.primary_rows[j].id;g.subtype=side?0:beforeCatalog.primary_rows[j].subtype;g.resource=side?beforeCatalog.companion_rows[j].resource:beforeCatalog.primary_rows[j].resource;unsigned mask=0;
   for(unsigned i=0;i<o->count;++i)if(g.id==o->rows[i].id){g.target=1;mask=side?(o->rows[i].mask&1):o->rows[i].mask;}
   if(!guard(s->moduleBase,g.resource,g.subtype,mask,g.before))return;
  }
 }o->stage=2;
 for(unsigned i=0;i<o->count;++i){auto& r=o->rows[i];if(r.mask){if constexpr(PROPERTIES_WRITE!=0){if(!mutate(*s,*o,r))return;}else return;}else {if(!capture(s->moduleBase,r,r.after)||!equal(r.before,r.after))return;r.readbackVerified=r.companionNameVerified=1;r.stage=6;}
  r.status=0;++o->completed;
 }o->stage=3;
 CaptureTemplateCatalog(s,{nullptr,catalogRead},&catalogWorkspace,&afterCatalog);if(afterCatalog.code!=TemplateCaptureCode::complete)return;o->catalogAfter=hash(&afterCatalog,sizeof(afterCatalog));
 if(std::memcmp(&beforeCatalog,&afterCatalog,sizeof(beforeCatalog)))return;o->catalogUnchanged=1;
 for(unsigned j=0;j<o->guardCount;++j){auto& g=o->guards[j];unsigned mask=0;for(unsigned i=0;i<o->count;++i)if(g.id==o->rows[i].id)mask=g.companion?(o->rows[i].mask&1):o->rows[i].mask;
  if(!guard(s->moduleBase,g.resource,g.subtype,mask,g.after)||g.before!=g.after)return;
 }o->guardsUnchanged=1;CaptureGameContextSnapshot(&o->afterScene);if(!scene(*s,o->afterScene))return;o->sceneUnchanged=1;o->stage=4;o->status=0;
}
}
void ExecuteProperties(const GameContextSnapshot* s,PropertyReceipt* o) noexcept {
 if(!o)return;__try{execute(s,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
