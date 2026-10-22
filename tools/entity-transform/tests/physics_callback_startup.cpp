// Actual non-game callback entry on a private small-stack thread; compile fixtures only.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstddef>
#include <cstring>
#include "native_physics.h"
static_assert(HR_TARGET_PID==1 && HR_TARGET_TID==1 && HR_DEADLINE==1,"Never run against a real target");
struct Context {GameContextSnapshot* snapshot;PhysicsReceipt* receipt;};
DWORD WINAPI Run(LPVOID arg){auto c=static_cast<Context*>(arg);ExecutePhysics(c->snapshot,c->receipt);return 0;}
int main(){
    if(GetCurrentProcessId()==1)return 2;
    Context c{};c.snapshot=static_cast<GameContextSnapshot*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(GameContextSnapshot)));
    c.receipt=static_cast<PhysicsReceipt*>(HeapAlloc(GetProcessHeap(),0,sizeof(PhysicsReceipt)));
    if(!c.snapshot||!c.receipt)return 3;std::memset(c.receipt,0xa5,sizeof(*c.receipt));
    HANDLE thread=CreateThread(nullptr,64*1024,Run,&c,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 4;
    DWORD code=99;if(WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0||!GetExitCodeThread(thread,&code))return 5;CloseHandle(thread);
    const auto& r=*c.receipt;bool zero=true;
    const auto bytes=reinterpret_cast<const unsigned char*>(&r.transform);
    for(std::size_t i=0;i<sizeof(r)-offsetof(PhysicsReceipt,transform);++i)if(bytes[i])zero=false;
    const bool ok=code==0&&r.size==sizeof(r)&&r.version==1&&r.status==1&&r.stage==1&&r.count==TRANSFORM_COUNT&&r.seh==0&&r.nativeCalls==0&&r.mutationCalls==0&&zero;
    std::printf("{\"ok\":%s,\"kind\":\"physics-callback-startup\",\"receiptBytes\":%zu,\"privateThreadStack\":65536,\"gameProcessAccessed\":false,\"nativeCalls\":%u,\"requestCount\":%u}\n",ok?"true":"false",sizeof(r),r.nativeCalls,r.count);
    HeapFree(GetProcessHeap(),0,c.receipt);HeapFree(GetProcessHeap(),0,c.snapshot);return ok?0:6;
}
