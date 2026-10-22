#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "reopen_action.h"
namespace {
volatile LONG actionClaim=0;
bool Copy(void* dst,const void* src,std::size_t n) noexcept {
 __try {std::memcpy(dst,src,n);return true;}__except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
bool ReadActionBytes(void*,std::uint64_t address,void* out,std::size_t n) noexcept {
 if(!out||!n||n>2048||address<0x10000||address>=0x800000000000ULL||n>0x800000000000ULL-address)return false;
 const auto end=address+n;for(auto p=address;p<end;){MEMORY_BASIC_INFORMATION q{};
  if(VirtualQuery(reinterpret_cast<const void*>(p),&q,sizeof(q))!=sizeof(q)||q.State!=MEM_COMMIT||(q.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return false;
  const auto prot=q.Protect&0xff;
  if(prot!=PAGE_READONLY&&prot!=PAGE_READWRITE&&prot!=PAGE_WRITECOPY&&prot!=PAGE_EXECUTE_READ&&prot!=PAGE_EXECUTE_READWRITE&&prot!=PAGE_EXECUTE_WRITECOPY)return false;
  const auto next=reinterpret_cast<std::uint64_t>(q.BaseAddress)+q.RegionSize;if(next<=p||next>0x800000000000ULL)return false;p=next<end?next:end;
 }return Copy(out,reinterpret_cast<const void*>(address),n);
}
bool Identity() noexcept {
 if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>HR_DEADLINE)return false;
 FILETIME c{},e{},k{},u{};if(!GetProcessTimes(GetCurrentProcess(),&c,&e,&k,&u))return false;
 if(((std::uint64_t(c.dwHighDateTime)<<32)|c.dwLowDateTime)!=HR_TARGET_CREATION)return false;
 if(!GetThreadTimes(GetCurrentThread(),&c,&e,&k,&u))return false;
 return ((std::uint64_t(c.dwHighDateTime)<<32)|c.dwLowDateTime)==HR_TARGET_THREAD_CREATION;
}
}
void ExecuteGameReopenAction(ReopenActionSnapshot* out) noexcept {
 using namespace ge::reopen;if(!out)return;*out={};auto& a=out->action;
 a.size=sizeof(a);a.version=1;a.action=4;a.status=REFUSED;a.invocation=HR_NONCE;a.levelId=HR_REOPEN_EXPECTED_LEVEL_ID;
 if(InterlockedCompareExchange(&actionClaim,1,0)!=0){a.status=REENTRY;return;}
 if(!Identity()){a.status=WRONG_IDENTITY;return;}
 const auto base=reinterpret_cast<std::uint64_t>(GetModuleHandleW(nullptr));
 if(!ValidateRoute(base,ReadActionBytes,nullptr)){a.status=BAD_ROUTE;return;}a.routeBefore=1;
 CaptureGameReopenGuardBundle(&out->context,&out->catalog,&out->type,&out->scheduler,&out->guards);
 if(out->context.moduleBase!=base||!ValidateFresh(*out)){a.status=BAD_FRESH_EVIDENCE;return;}
 if(!Identity()||!ValidateRoute(base,ReadActionBytes,nullptr)){a.status=BAD_ROUTE;return;}a.routeAfter=1;
 if(!ValidateCurrent(*out,ReadActionBytes,nullptr)){a.status=CURRENT_CHANGED;return;}
 a.levelManager=out->catalog.levelManager;a.record=out->guards.currentRecord;a.entry=base+0x13564e90ULL;a.preflightAccepted=1;
 const auto fn=reinterpret_cast<ge::scene::ReopenCurrent>(a.entry);
 a.call=ge::scene::dispatch_reopen(fn,reinterpret_cast<void*>(a.levelManager),reinterpret_cast<void*>(a.record));
 a.status=a.call.nativeCallReturned?RETURNED_PENDING:EXCEPTION_PENDING;
 // Independent immediate diagnostic; never changes call/pending evidence on failure.
 if(a.call.nativeCallReturned)CaptureGameSchedulerCoroutines(&out->context,&out->type,&out->postScheduler);
}
