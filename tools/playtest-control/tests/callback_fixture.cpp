// Private-process fixture. It never opens a target or installs a hook.
#include "native_observe.cpp"
#include <cstdio>
DWORD WINAPI worker(void* p){ExecutePlayObservation(static_cast<PlayReceipt*>(p));return 0;}
int main(){
    auto out=static_cast<PlayReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(PlayReceipt)));
    if(!out)return 1;
    HANDLE t=CreateThread(nullptr,65536,worker,out,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);
    if(!t)return 2;
    if(WaitForSingleObject(t,10000)!=WAIT_OBJECT_0)return 3;CloseHandle(t);
    if(out->bytes!=336||out->status!=1||out->stage!=1||out->seh||out->nativeCalls)return 4;
    const U base=reinterpret_cast<U>(VirtualAlloc(nullptr,0x57c0000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));if(!base)return 5;
    alignas(8) unsigned char manager[0x260]{},dict[0x40]{},buckets[0x28]{},entries[0x50]{},object[0x500]{},klass[0x600]{};
    auto put=[](void* p,U v){std::memcpy(p,&v,8);};auto dword=[](void* p,unsigned v){std::memcpy(p,&v,4);};
    const U mp=reinterpret_cast<U>(manager),dp=reinterpret_cast<U>(dict),bp=reinterpret_cast<U>(buckets),ep=reinterpret_cast<U>(entries),op=reinterpret_cast<U>(object),kp=reinterpret_cast<U>(klass);
    put(reinterpret_cast<void*>(base+0x57b1570),kp);put(manager+0x150,dp);dword(manager+0x250,7);put(dict+0x20,bp);put(dict+0x28,ep);
    put(buckets+0x18,1);dword(buckets+0x20,1);put(entries+0x18,1);dword(entries+0x20,7);dword(entries+0x24,0xffffffffU);dword(entries+0x28,7);put(entries+0x30,op);put(object,kp);
    PlaySample s{};s.avatarManager=mp;if(avatar(base,s)!=2||s.avatar!=op||s.avatarId!=7)return 6;
    put(dict+0x30,kp);if(avatar(base,s)!=3)return 7;put(dict+0x30,0);
    dword(manager+0x250,0);if(avatar(base,s)!=1)return 8;dword(manager+0x250,7);
    put(object,dp);if(avatar(base,s)!=4)return 9;put(object,kp);
    put(entries+0x18,65537);if(avatar(base,s)!=5)return 10;put(entries+0x18,1);
    dword(entries+0x20,8);dword(entries+0x24,0);if(avatar(base,s)!=5)return 11;
    VirtualFree(reinterpret_cast<void*>(base),0,MEM_RELEASE);HeapFree(GetProcessHeap(),0,out);
    std::puts("{\"ok\":true,\"privateProcessOnly\":true,\"callbackStackReserve\":65536,\"checks\":7,\"gameAccess\":false}");return 0;
}
