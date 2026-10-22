// Private host only: the production callback rejects before resolving a target.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include "native_control.cpp"
#include <initializer_list>
namespace {
alignas(8) unsigned char texture[32]{},png[96]{};
unsigned calls=0,captures=0,destroys=0;bool throwAction=false,oversize=false,failDestroy=false;
void official(){++calls;if(throwAction)RaiseException(0xe0010001,0,0,nullptr);}
void returned(void* context){if(context!=texture)RaiseException(0xe0010002,0,0,nullptr);official();}
unsigned screen(){return 1;}unsigned counter(){return 7;}
void* capture(int factor){if(factor!=1)return nullptr;++captures;U p=0x10000;std::memcpy(texture+16,&p,8);return texture;}
unsigned dimension(void* p){return p==texture?1U:0U;}
void* encode(void*){U n=oversize?8U*1024U*1024U+1ULL:64ULL;std::memcpy(png+24,&n,8);return png;}
void destroy(void* p,bool assets){if(p!=texture||assets)RaiseException(0xe0010002,0,0,nullptr);++destroys;if(failDestroy)RaiseException(0xe0010003,0,0,nullptr);std::memset(texture+16,0,8);}
void jump(U at,U target){if(!VirtualAlloc(reinterpret_cast<void*>(at&~0xfffULL),4096,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(20);unsigned char codeBytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};std::memcpy(codeBytes+2,&target,8);std::memcpy(reinterpret_cast<void*>(at),codeBytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);}
bool exceptionAttempt(U base,ControlReceipt* receipt){
    __try{callAction(base,receipt);}__except(EXCEPTION_EXECUTE_HANDLER){return receipt->actionAttempted==1&&receipt->actionReturned==0&&GetExceptionCode()==0xe0010001;}
    return CONTROL_OPERATION==3||CONTROL_OPERATION==8;
}
}
DWORD WINAPI worker(void* value){ExecuteControl(static_cast<ControlReceipt*>(value));return 0;}
int main(){
    auto receipt=static_cast<ControlReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(ControlReceipt)));
    if(!receipt)return 1;
    HANDLE thread=CreateThread(nullptr,64*1024,worker,receipt,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);
    if(!thread)return 2;
    if(WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0)return 3;CloseHandle(thread);
    const bool rejected=receipt->bytes==sizeof(ControlReceipt)&&receipt->version==2&&receipt->status==1&&receipt->stage==1&&!receipt->actionAttempted&&!receipt->nativeCalls&&!receipt->seh;
    TrialState s{};PlayReceipt observation{};
    const unsigned denied=precondition(s,observation);
    const bool guard=CONTROL_OPERATION==3?denied==0:denied!=0;
    if(!rejected||!guard)return 4;
    const U base=reinterpret_cast<U>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!base)return 5;
    for(unsigned r:{0x13721870U,0x13726d20U,0x13724240U})jump(base+r,reinterpret_cast<U>(&official));jump(base+0x138cbaf0,reinterpret_cast<U>(&returned));
    std::memset(receipt,0,sizeof(*receipt));receipt->before.settleContext=reinterpret_cast<U>(texture);callAction(base,receipt);
    const bool writing=CONTROL_OPERATION>=4&&CONTROL_OPERATION<=7;
    if(calls!=(writing?1U:0U)||receipt->actionAttempted!=(writing?1U:0U)||receipt->actionReturned!=(writing?1U:0U))return 6;
    throwAction=true;std::memset(receipt,0,sizeof(*receipt));receipt->before.settleContext=reinterpret_cast<U>(texture);if(!exceptionAttempt(base,receipt))return 7;
    for(unsigned r:{0x19cc2fd0U,0x19cc2fe0U})jump(base+r,reinterpret_cast<U>(&screen));for(unsigned r:{0x19c9de20U,0x19c9de30U})jump(base+r,reinterpret_cast<U>(&counter));
    jump(base+0x19d141e0,reinterpret_cast<U>(&capture));jump(base+0x19cae530,reinterpret_cast<U>(&dimension));jump(base+0x19cae5a0,reinterpret_cast<U>(&dimension));jump(base+0x19cd3610,reinterpret_cast<U>(&encode));jump(base+0x19cb2dd0,reinterpret_cast<U>(&destroy));
    std::memset(receipt,0,sizeof(*receipt));trialFrame(base,receipt);if(receipt->frameStatus||receipt->seh||receipt->resourcesReleased!=1||receipt->pngBytes!=64||captures!=1||destroys!=1)return 8;
    oversize=true;std::memset(receipt,0,sizeof(*receipt));trialFrame(base,receipt);if(receipt->frameStatus!=3||receipt->resourcesReleased!=1||destroys!=2)return 9;
    oversize=false;failDestroy=true;std::memset(receipt,0,sizeof(*receipt));trialFrame(base,receipt);if(receipt->frameStatus!=5||receipt->resourcesReleased||receipt->seh!=0xe0010003)return 10;
    VirtualFree(reinterpret_cast<void*>(base),0,MEM_RELEASE);
    HeapFree(GetProcessHeap(),0,receipt);
    std::puts("{\"ok\":true,\"checks\":7,\"gameAccess\":false,\"desktopAccess\":false,\"privateProcessOnly\":true,\"callbackStackReserve\":65536}");return 0;
}
