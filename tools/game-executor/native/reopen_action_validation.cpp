#include "reopen_action.h"
#include "reopen_route.generated.h"
#include <cstring>
namespace ge::reopen {namespace {
bool Ptr(std::uint64_t p) noexcept{return p>=0x10000&&p<0x800000000000ULL&&!(p&7);}
template<class T>bool Read(guarddraft::ReadBytes read,void* user,std::uint64_t p,std::uint64_t off,T& v) noexcept {
 return read&&Ptr(p)&&off<0x800000000000ULL-p&&sizeof(T)<=0x800000000000ULL-p-off&&read(user,p+off,&v,sizeof(v));
}
}
struct ExpectedEntity {std::uint32_t id,configId;std::uint64_t owner,config,context;};
constexpr ExpectedEntity expectedEntities[]={HR_REOPEN_EXPECTED_ENTITY_ROWS};
static_assert(HR_REOPEN_EXPECTED_ENTITY_COUNT>0&&HR_REOPEN_EXPECTED_ENTITY_COUNT<=kMaxEntities,"reviewed entity bound");
static_assert(sizeof(expectedEntities)/sizeof(expectedEntities[0])==HR_REOPEN_EXPECTED_ENTITY_COUNT,"reviewed entity count");
static_assert(HR_REOPEN_EXPECTED_CONTEXT>=0x10000ULL&&HR_REOPEN_EXPECTED_CONTEXT<0x800000000000ULL,"reviewed context required");
bool ValidateFresh(const Snapshot& b) noexcept {
 const auto& c=b.context;const auto& d=b.catalog;const auto& t=b.type;const auto& s=b.scheduler;const auto& g=b.guards;
 if(c.structSize!=sizeof(c)||c.version!=1||c.status||(c.flags&1951)!=1951||(c.flags&96)||c.entityRejected||
    c.entityCaptured!=c.entityValidEntries||c.entityCaptured>kMaxEntities||c.reserved!=HR_REOPEN_EXPECTED_LEVEL_ID||
    c.peTimestamp!=HR_GAME_TIMESTAMP||c.peImageSize!=HR_GAME_IMAGE_SIZE||!Ptr(c.moduleBase)||!Ptr(c.global)||!Ptr(c.saveManager))return false;
 if(c.currentContext!=HR_REOPEN_EXPECTED_CONTEXT||c.entityCaptured!=HR_REOPEN_EXPECTED_ENTITY_COUNT)return false;
 for(std::uint32_t n=0;n<c.entityCaptured;++n){const auto& actual=c.entities[n];unsigned matches=0;
  for(std::uint32_t j=0;j<n;++j)if(c.entities[j].id==actual.id)return false;
  for(const auto& expected:expectedEntities)if(actual.id==expected.id){
   if(actual.configId!=expected.configId||actual.owner!=expected.owner||actual.config!=expected.config||actual.context!=expected.context)return false;++matches;}
  if(matches!=1)return false;
 }
 if(d.structSize!=sizeof(d)||d.version!=1||d.status||d.flags!=31||d.parserError||d.reserved||d.dirtyByte||
    d.levelId!=HR_REOPEN_EXPECTED_LEVEL_ID||d.selectedId!=d.levelId||d.versionBefore!=d.versionAfter||
    !d.recordCount||d.recordCount>kMaxLevelCatalog||!Ptr(d.levelManager))return false;
 if(t.structSize!=sizeof(t)||t.version!=1||t.status||t.flags!=255||t.moduleBase!=c.moduleBase||t.levelId!=d.levelId)return false;
 if(s.structSize!=sizeof(s)||s.version!=1||s.status||s.flags!=255||s.moduleBase!=c.moduleBase||s.global!=c.global||
    s.levelId!=d.levelId||s.rowCount>128||s.rowCount!=s.listCountBefore||s.rowCount!=s.listCountAfter||
    !ValidSchedulerListBounds(static_cast<std::int32_t>(s.rowCount),s.listCapacity)||s.versionBefore!=s.versionAfter||s.targetCount)return false;
 // Only the explicitly reviewed categories are eligible. This is not engine-wide absence proof.
 static_assert((HR_REOPEN_ALLOWED_SCHEDULER_MASK&~((1U<<SC_NULL_HANDLE)|(1U<<SC_RELEASED)|(1U<<SC_OTHER_CLASS)|(1U<<SC_OTHER_OWNER)|(1U<<SC_OTHER_HANDLE_CLASS)))==0,"No unknown live holders or target may be allowed");
 for(std::uint32_t n=0;n<s.rowCount;++n){const auto& r=s.rows[n];
  if(r.index!=n||r.disposition>SC_OTHER_HANDLE_CLASS||!(HR_REOPEN_ALLOWED_SCHEDULER_MASK&(1U<<r.disposition))||
     r.disposition!=ClassifySchedulerRow(r,s.targetClass,s.lifecycleOwner,s.coroutineClass))return false;}
 if(g.structSize!=sizeof(g)||g.version!=HR_REOPEN_GUARD_RESULT_VERSION||g.status!=guarddraft::OK||g.flags!=15||
    g.confirmation!=guarddraft::FALSE_VALUE||g.earlyAbort!=guarddraft::FALSE_VALUE||g.invocation!=HR_NONCE||
    g.moduleBase!=c.moduleBase||g.global!=c.global||g.levelId!=d.levelId||g.modeId!=0xb993||g.schedulerStatus||
    g.schedulerFlags!=255||g.schedulerComplete!=1||g.schedulerTargetCount||g.schedulerRows!=s.rowCount||!Ptr(g.currentRecord))return false;
 unsigned matches=0;
 for(std::uint32_t n=0;n<d.recordCount;++n){const auto& row=d.rows[n];if(row.id!=row.key||!Ptr(row.record))return false;
  if(row.id==d.levelId){if(row.record!=g.currentRecord)return false;++matches;}}
 return matches==1;
}
bool ValidateRoute(std::uint64_t base,guarddraft::ReadBytes read,void* user) noexcept {
 if(!Ptr(base)||!read)return false;
 for(const auto& a:route::anchors){unsigned char bytes[2048]{};
  if(!a.size||a.size>sizeof(bytes)||a.rva>=HR_GAME_IMAGE_SIZE||a.size>HR_GAME_IMAGE_SIZE-a.rva||
     base>0x800000000000ULL-HR_GAME_IMAGE_SIZE||!read(user,base+a.rva,bytes,a.size)||std::memcmp(bytes,a.bytes,a.size))return false;}
 for(auto rva:route::hotfix){unsigned char byte=255;if(rva>=HR_GAME_IMAGE_SIZE||!read(user,base+rva,&byte,1)||byte)return false;}
 return true;
}
bool ValidateCurrent(const Snapshot& b,guarddraft::ReadBytes read,void* user) noexcept {
 std::uint64_t global=0,manager=0,save=0,archive=0,mode=0,gate=0,gateObject=0;
 std::uint32_t level=0,selected=0,recordId=0,modeId=0;unsigned char dirty=255,editing=0;
 return Read(read,user,b.context.moduleBase,0x5783de8,global)&&global==b.context.global&&
  Read(read,user,global,0xa960,manager)&&manager==b.catalog.levelManager&&
  Read(read,user,global,0xdb50,save)&&save==b.context.saveManager&&
  Read(read,user,save,0x48,archive)&&archive==b.catalog.archive&&
  Read(read,user,archive,0x38,selected)&&selected==HR_REOPEN_EXPECTED_LEVEL_ID&&
  Read(read,user,manager,0x98,level)&&level==selected&&Read(read,user,manager,0xc9,editing)&&editing&&
  Read(read,user,save,0xa2,dirty)&&!dirty&&Read(read,user,b.guards.currentRecord,0x2c,recordId)&&recordId==level&&
  Read(read,user,global,0xa440,mode)&&Read(read,user,mode,0x1cc,modeId)&&modeId==0xb993&&
  Read(read,user,global,0xa430,gate)&&Read(read,user,gate,0x50,gateObject)&&Ptr(gateObject);
}
}
