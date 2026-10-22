#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "game_reopen_guards.h"
#include "guard_profile.generated.h"
namespace {
// One compiled attempt owns one fixed buffer. Reentry is refused, never waited on.
guarddraft::Scratch guardScratch{};
volatile LONG guardCaptureClaim=0;
struct GuardReadBudget {std::uint32_t calls=0,bytes=0;bool exceeded=false;};
bool GuardCopy(void* target,const void* source,std::size_t size) noexcept {
 __try {std::memcpy(target,source,size);return true;}
 __except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
bool ReadGuardBytes(void* user,std::uint64_t address,void* target,std::size_t size) noexcept {
 if(!user||!target||!size)return false;
 auto& budget=*static_cast<GuardReadBudget*>(user);
 // Includes the core's complete second read of every tracked span.
 if(size>16384||budget.calls>=4096||size>262144-budget.bytes){budget.exceeded=true;return false;}
 ++budget.calls;budget.bytes+=static_cast<std::uint32_t>(size);
 if(address<0x10000||address>=0x800000000000ULL||size>0x800000000000ULL-address)return false;
 const auto end=address+size;
 for(auto p=address;p<end;){
  MEMORY_BASIC_INFORMATION region{};
  if(VirtualQuery(reinterpret_cast<const void*>(p),&region,sizeof(region))!=sizeof(region)||
     region.State!=MEM_COMMIT||(region.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return false;
  const auto protection=region.Protect&0xff;
  if(protection!=PAGE_READONLY&&protection!=PAGE_READWRITE&&protection!=PAGE_WRITECOPY&&
     protection!=PAGE_EXECUTE_READ&&protection!=PAGE_EXECUTE_READWRITE&&protection!=PAGE_EXECUTE_WRITECOPY)return false;
  const auto next=reinterpret_cast<std::uint64_t>(region.BaseAddress)+region.RegionSize;
  if(next<=p||next>0x800000000000ULL)return false;p=next<end?next:end;
 }
 return GuardCopy(target,reinterpret_cast<const void*>(address),size);
}
}
void CaptureGameReopenGuardBundle(GameContextSnapshot* context,LevelCatalogSnapshot* catalog,LifecycleTypeSnapshot* type,SchedulerCoroutinesSnapshot* scheduler,guarddraft::Result* out) noexcept {
 if(!out)return;*out={};out->structSize=sizeof(*out);out->version=2;out->status=guarddraft::INPUT_REFUSED;
 if(!context||!catalog||!type||!scheduler)return;
 if(InterlockedCompareExchange(&guardCaptureClaim,1,0)!=0)return;
 *context={};*catalog={};*type={};*scheduler={};
 if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||!HR_NONCE||GetTickCount64()>HR_DEADLINE)return;
 FILETIME creation{},exitTime{},kernel{},user{};
 if(!GetProcessTimes(GetCurrentProcess(),&creation,&exitTime,&kernel,&user))return;
 const std::uint64_t created=(std::uint64_t(creation.dwHighDateTime)<<32)|creation.dwLowDateTime;
 if(created!=HR_TARGET_CREATION)return;
 guarddraft::Inputs input{};
 input.current={HR_NONCE,created,GetCurrentProcessId(),0};
 std::memcpy(input.diskImageSha256,guarddraft::kImageSha,sizeof(input.diskImageSha256));
 // Only fresh, locally produced structs enter the core. No externally supplied stamps are accepted.
 CaptureGameContextSnapshot(context);input.context=context;input.contextStamp=input.current;
 CaptureGameLevelCatalog(context,catalog);input.catalog=catalog;input.catalogStamp=input.current;
 CaptureGameLifecycleType(context,type);input.type=type;input.typeStamp=input.current;
 CaptureGameSchedulerCoroutines(context,type,scheduler);input.scheduler=scheduler;input.schedulerStamp=input.current;
 GuardReadBudget budget{};guarddraft::Evaluate(input,ReadGuardBytes,&budget,guardScratch,*out);
 if(budget.exceeded){out->status=guarddraft::LIMIT;out->flags&=7;out->confirmation=guarddraft::UNKNOWN;out->earlyAbort=guarddraft::UNKNOWN;}
}