// Private host only. Expired/foreign identity production callback, plus the
// actual enumeration and capture functions against owned heap/stub objects.
#undef HR_DEADLINE
#define HR_DEADLINE 0xffffffffffffffffULL
#include "native_acceptance.cpp"
#include <cstdio>
#include <initializer_list>
namespace {
alignas(8) unsigned char textureObject[32]{},pngArray[96]{};
unsigned captures=0,destroys=0;bool badPng=false,badDestroy=false;
unsigned screen(){return 1;} unsigned counter(){return 7;}
void* capture(int factor){if(factor!=1)return nullptr;++captures;U native=0x10000;std::memcpy(textureObject+16,&native,8);return textureObject;}
unsigned dimension(void* p){return p==textureObject?1U:0U;}
void* encode(void* p){if(p!=textureObject)return nullptr;U length=badPng?kFrameCapacity+1ULL:64ULL;std::memcpy(pngArray+24,&length,8);return pngArray;}
void destroy(void* p,bool assets){if(p!=textureObject||assets)RaiseException(0xe0010002,0,0,nullptr);++destroys;if(badDestroy)RaiseException(0xe0010001,0,0,nullptr);std::memset(textureObject+16,0,8);}
void jump(U at,U target){if(!VirtualAlloc(reinterpret_cast<void*>(at&~0xfffULL),4096,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(20);unsigned char codeBytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};std::memcpy(codeBytes+2,&target,8);std::memcpy(reinterpret_cast<void*>(at),codeBytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);}
DWORD WINAPI worker(void* p){ExecuteAcceptance(static_cast<AcceptanceReceipt*>(p));return 0;}
}
int main(){
    auto out=static_cast<AcceptanceReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(AcceptanceReceipt)));if(!out)return 1;
    HANDLE thread=CreateThread(nullptr,65536,worker,out,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 2;
    if(WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0)return 3;CloseHandle(thread);
    if(out->bytes!=sizeof(*out)||out->status!=1||out->stage!=1||out->seh||out->nativeCalls)return 4;
    // Reserve address space for the original RVAs, commit only the stub pages.
    const U base=reinterpret_cast<U>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!base)return 5;
    alignas(8) unsigned char dictionary[0x50]{},entries[0x20+130*24]{},object[0x500]{},klass[0x600]{};
    const U dp=reinterpret_cast<U>(dictionary),ep=reinterpret_cast<U>(entries),op=reinterpret_cast<U>(object),kp=reinterpret_cast<U>(klass);
    auto q=[](void* p,U v){std::memcpy(p,&v,8);};auto d=[](void* p,unsigned v){std::memcpy(p,&v,4);};
    q(dictionary+0x28,ep);q(entries+0x18,130);q(object,kp);d(object+0x3a8,7);d(object+0x4dc,2001);d(object+0x458,2);object[0x320]=1;object[0x482]=1;object[0x42f]=1;
    for(unsigned i=0;i<130;++i){d(entries+0x20+i*24,7);d(entries+0x28+i*24,7);q(entries+0x30+i*24,op);}
    std::memset(out,0,sizeof(*out));out->before.dictionary=dp;out->before.dictionaryCount=130;enumerate(base,out);
    if(out->enumerationStatus||out->count!=128||out->pageEnd!=128||out->entities[0].configId!=2001||out->entities[0].isLoaded!=1||out->entities[0].positionStatus!=1)return 6;
    std::memset(out,0,sizeof(*out));out->before.dictionary=dp;out->before.dictionaryCount=2;d(entries+0x20,0xffffffff);enumerate(base,out);
    if(out->enumerationStatus||out->count!=1||out->entities[0].entryIndex!=1)return 7;
    std::memset(out,0,sizeof(*out));out->before.dictionary=dp;out->before.dictionaryCount=131;enumerate(base,out);if(out->enumerationStatus!=1)return 8;
    q(dictionary+0x30,kp);std::memset(out,0,sizeof(*out));out->before.dictionary=dp;enumerate(base,out);if(out->enumerationStatus!=1)return 9;q(dictionary+0x30,0);
    // Redirect only this private allocation. The game image is neither found
    // nor opened, and no window/message hook or GPU function is invoked.
    for(unsigned r:{0x19cc2fd0U,0x19cc2fe0U})jump(base+r,reinterpret_cast<U>(&screen));
    for(unsigned r:{0x19c9de20U,0x19c9de30U})jump(base+r,reinterpret_cast<U>(&counter));
    jump(base+0x19d141e0,reinterpret_cast<U>(&capture));jump(base+0x19cae530,reinterpret_cast<U>(&dimension));jump(base+0x19cae5a0,reinterpret_cast<U>(&dimension));jump(base+0x19cd3610,reinterpret_cast<U>(&encode));jump(base+0x19cb2dd0,reinterpret_cast<U>(&destroy));
    std::memset(out,0,sizeof(*out));frame(base,out);if(out->frameStatus||out->seh||out->resourcesReleased!=1||out->pngBytes!=64||captures!=1||destroys!=1)return 10;
    badPng=true;std::memset(out,0,sizeof(*out));frame(base,out);if(out->frameStatus!=3||out->resourcesReleased!=1||destroys!=2)return 11;
    badPng=false;badDestroy=true;std::memset(out,0,sizeof(*out));frame(base,out);if(out->frameStatus!=5||out->resourcesReleased||out->seh!=0xe0010001)return 12;
    VirtualFree(reinterpret_cast<void*>(base),0,MEM_RELEASE);HeapFree(GetProcessHeap(),0,out);
    std::puts("{\"ok\":true,\"checks\":8,\"gameAccess\":false,\"privateProcessOnly\":true,\"callbackStackReserve\":65536,\"captureStubOnly\":true}");return 0;
}
