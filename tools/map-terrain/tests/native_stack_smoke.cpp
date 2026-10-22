// Compile-only card identity makes every game branch unreachable. This executable
// exercises real initialization/refusal on a 64 KiB reserved worker stack.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <cstddef>
#include "native_terrain.h"
static_assert(HR_TARGET_PID==1 && HR_TARGET_TID==1 && HR_DEADLINE==1,
              "Offline stack smoke requires the expired compile-only identity");
struct State { GameContextSnapshot* scene; TerrainReceipt* receipt; DWORD result; };
static DWORD WINAPI Worker(void* parameter) {
    auto* state=static_cast<State*>(parameter);
    ExecuteTerrainAction(state->scene,state->receipt);
    const auto* r=state->receipt;
    bool ok=r->size==sizeof(*r) && r->version==(TERRAIN_CATALOG_PROBE?3ULL:TERRAIN_RUNTIME_PROBE?2ULL:1ULL) && r->status==1 && r->stage==1 && !r->sehCode &&
        !r->mutationCalls && !r->completed && !r->openCalled && !r->transactionMayBeOpen && !r->outcomeUncertain;
    const auto* bytes=reinterpret_cast<const unsigned char*>(r);
    for(std::size_t i=offsetof(TerrainReceipt,before);i<sizeof(*r);++i)if(bytes[i]){ok=false;break;}
    state->result=ok?0U:3U;return state->result;
}
int main() {
    // Regression for the real 0x5a9359e refusal: 1 is normal initialization,
    // while the same value in a real hotfix dispatch byte remains a refusal.
    for(unsigned int value=0;value<256;++value) {
        const auto byte=static_cast<unsigned char>(value);
        if(TerrainRuntimeFlagAccepted(byte,false)!=(value==0) ||
           TerrainRuntimeFlagAccepted(byte,true)!=(value==0 || value==1))return 6;
    }
    const HANDLE heap=GetProcessHeap();State state{};
    state.scene=static_cast<GameContextSnapshot*>(HeapAlloc(heap,HEAP_ZERO_MEMORY,sizeof(GameContextSnapshot)));
    state.receipt=static_cast<TerrainReceipt*>(HeapAlloc(heap,0,sizeof(TerrainReceipt)));
    if(!state.scene || !state.receipt)return 2;
    std::memset(state.receipt,0xa5,sizeof(TerrainReceipt));
    HANDLE thread=CreateThread(nullptr,64*1024,Worker,&state,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);
    if(!thread)return 4;
    const DWORD wait=WaitForSingleObject(thread,10000);DWORD code=5;
    if(wait==WAIT_OBJECT_0)GetExitCodeThread(thread,&code);
    CloseHandle(thread);
    if(wait!=WAIT_OBJECT_0)return 5; // Process exit ends only this local fixture.
    HeapFree(heap,0,state.receipt);HeapFree(heap,0,state.scene);
    const bool ok=code==0 && state.result==0;
    std::printf("{\"ok\":%s,\"receiptBytes\":%zu,\"snapshotBytes\":%zu,\"workerStackReserve\":65536,\"runtimeFlagCases\":512,\"nativeCalled\":false,\"gameProcessOpened\":false}\n",
                ok?"true":"false",sizeof(TerrainReceipt),sizeof(GameContextSnapshot));
    return ok?0:3;
}
