#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
std::uint64_t expectedCreation=0;
#define HR_READ_REOPEN_GUARDS 1
#define HR_READ_CONTEXT 1
#define HR_READ_LEVEL_CATALOG 1
#define HR_READ_LIFECYCLE_TYPE 1
#define HR_READ_SCHEDULER_COROUTINES 1
#define GS_BOOTSTRAP_READONLY 1
#define HR_ACTION 0
#define HR_TARGET_PID GetCurrentProcessId()
#define HR_TARGET_TID GetCurrentThreadId()
#define HR_TARGET_CREATION expectedCreation
#define HR_NONCE 77ULL
#define HR_DEADLINE UINT64_MAX
#include "../native/game_reopen_guards_capture.cpp"
#include <cstdio>
#include <cstdlib>
std::uint32_t producerSequence=0;
void CaptureGameContextSnapshot(GameContextSnapshot* p) noexcept {producerSequence=producerSequence*10+1;*p={};}
void CaptureGameLevelCatalog(const GameContextSnapshot*,LevelCatalogSnapshot* p) noexcept {producerSequence=producerSequence*10+2;*p={};}
void CaptureGameLifecycleType(const GameContextSnapshot*,LifecycleTypeSnapshot* p) noexcept {producerSequence=producerSequence*10+3;*p={};}
void CaptureGameSchedulerCoroutines(const GameContextSnapshot*,const LifecycleTypeSnapshot*,SchedulerCoroutinesSnapshot* p) noexcept {producerSequence=producerSequence*10+4;*p={};}
int main(){
 int checks=0;auto check=[&](bool ok){if(!ok)std::exit(1);++checks;};
 SYSTEM_INFO system{};GetSystemInfo(&system);const auto page=system.dwPageSize;
 auto memory=static_cast<unsigned char*>(VirtualAlloc(nullptr,static_cast<SIZE_T>(page)*2,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));check(memory!=nullptr);
 memory[page-1]=31;memory[page]=42;unsigned char target[8]{};GuardReadBudget budget{};const auto address=reinterpret_cast<std::uint64_t>(memory+page-4);
 check(ReadGuardBytes(&budget,address,target,8));check(target[3]==31&&target[4]==42);check(budget.calls==1&&budget.bytes==8);
 DWORD old=0;check(VirtualProtect(memory+page,page,PAGE_NOACCESS,&old)!=FALSE);check(!ReadGuardBytes(&budget,address,target,8));check(VirtualProtect(memory+page,page,PAGE_READWRITE,&old)!=FALSE);
 check(VirtualProtect(memory+page,page,PAGE_READWRITE|PAGE_GUARD,&old)!=FALSE);check(!ReadGuardBytes(&budget,address,target,8));check(VirtualProtect(memory+page,page,PAGE_READWRITE,&old)!=FALSE);
 check(VirtualProtect(memory+page,page,PAGE_EXECUTE,&old)!=FALSE);check(!ReadGuardBytes(&budget,address,target,8));check(VirtualProtect(memory+page,page,PAGE_READONLY,&old)!=FALSE);check(ReadGuardBytes(&budget,address,target,8));
 check(!ReadGuardBytes(&budget,0xffffffffffffffffULL,target,8));check(!ReadGuardBytes(&budget,0x7ffffffffffcULL,target,8));check(!ReadGuardBytes(&budget,address,target,0));check(!ReadGuardBytes(&budget,address,nullptr,1));
 check(!GuardCopy(target,reinterpret_cast<const void*>(1),1));
 budget={};budget.calls=4095;check(ReadGuardBytes(&budget,address,target,1));check(!ReadGuardBytes(&budget,address,target,1)&&budget.exceeded);
 budget={};budget.bytes=262136;check(ReadGuardBytes(&budget,address,target,8));check(!ReadGuardBytes(&budget,address,target,1)&&budget.exceeded);
 budget={};check(!ReadGuardBytes(&budget,address,target,16385)&&budget.exceeded);
 check(VirtualFree(memory,0,MEM_RELEASE)!=FALSE);
 FILETIME created{},exited{},kernel{},user{};check(GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user)!=FALSE);
 expectedCreation=(std::uint64_t(created.dwHighDateTime)<<32)|created.dwLowDateTime;
 GameContextSnapshot context{};LevelCatalogSnapshot catalog{};LifecycleTypeSnapshot type{};SchedulerCoroutinesSnapshot scheduler{};guarddraft::Result result{};
 ++expectedCreation;CaptureGameReopenGuardBundle(&context,&catalog,&type,&scheduler,&result);check(producerSequence==0&&result.status==guarddraft::INPUT_REFUSED);
 --expectedCreation;guardCaptureClaim=0;CaptureGameReopenGuardBundle(&context,&catalog,&type,&scheduler,&result);check(producerSequence==1234);check(result.confirmation==guarddraft::UNKNOWN&&result.earlyAbort==guarddraft::UNKNOWN);
 producerSequence=0;CaptureGameReopenGuardBundle(&context,&catalog,&type,&scheduler,&result);check(producerSequence==0&&result.status==guarddraft::INPUT_REFUSED);
 std::printf("{\"ok\":true,\"checks\":%d,\"memoryScope\":\"test-process-owned-pages-only\",\"gameProcessAccessed\":false,\"gameMethodsCalled\":0}\n",checks);return 0;
}