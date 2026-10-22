// Private address-space fixture. Never opens or hooks the game.
#undef HR_DEADLINE
#define HR_DEADLINE 0xffffffffffffffffULL
#include "native_scene_frame.cpp"
#include <cstdio>
#include <initializer_list>
namespace {
alignas(8) unsigned char tex[32]{},arr[96]{},cam[32]{},trans[32]{};
unsigned frameCount=7,captures=0,destroys=0,frees=0,renders=0;
bool badPng=false,throwRender=false,liveHandle=false;
float pos[3]={1,2,3},rot[4]={0,0,0,1};
unsigned screen(){return 1;} unsigned counter(){return frameCount;}
U camera(){return reinterpret_cast<U>(cam);} U current(){return 0;}
U transform(U){return reinterpret_cast<U>(trans);} float fov(U){return 60;}
void getP(U,float* p){std::memcpy(p,pos,sizeof(pos));}
void getR(U,float* p){std::memcpy(p,rot,sizeof(rot));}
void setP(U,const float* p){std::memcpy(pos,p,sizeof(pos));}
void setR(U,const float* p){std::memcpy(rot,p,sizeof(rot));}
void render(U){++renders;if(throwRender)RaiseException(0xe0030001,0,0,nullptr);}
U capture(int factor){if(factor!=1)return 0;++captures;U v=0x10000;std::memcpy(tex+16,&v,8);return reinterpret_cast<U>(tex);}
unsigned dimension(U){return 1;}
U encode(U){U n=badPng?kSceneFrameCapacity+1ULL:64ULL;std::memcpy(arr+24,&n,8);return reinterpret_cast<U>(arr);}
unsigned alloc(U p){if(p!=reinterpret_cast<U>(tex))return 0;liveHandle=true;return 19;}
U target(unsigned h){return h==19&&liveHandle?reinterpret_cast<U>(tex):0;}
void freeHandle(unsigned h){if(h!=19||!liveHandle)ExitProcess(90);liveHandle=false;++frees;}
void destroy(U p,float delay){if(p!=reinterpret_cast<U>(tex)||delay!=0)ExitProcess(91);++destroys;}
void jump(U at,U targetAddress){
    if(!VirtualAlloc(reinterpret_cast<void*>(at&~0xfffULL),4096,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(92);
    unsigned char bytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};
    std::memcpy(bytes+2,&targetAddress,8);std::memcpy(reinterpret_cast<void*>(at),bytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);
}
DWORD WINAPI rejected(void* p){StepSceneFrame(static_cast<SceneFrameReceipt*>(p));return 0;}
void attempt(U b,SceneFrameReceipt* o){__try{captureScene(b,o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();}}
void reset(SceneFrameReceipt* o){std::memset(o,0,sizeof(*o));o->observation.after.positionStatus=0;}
}
int main(){
    auto o=static_cast<SceneFrameReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(SceneFrameReceipt)));if(!o)return 1;
    HANDLE t=CreateThread(nullptr,65536,rejected,o,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!t)return 2;
    if(WaitForSingleObject(t,10000)!=WAIT_OBJECT_0)return 3;CloseHandle(t);
    if(o->guardStatus!=1||o->nativeCalls||o->callbacks!=1)return 4;
    const U b=reinterpret_cast<U>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!b)return 5;
    U ptrValue=0x10000;std::memcpy(cam+16,&ptrValue,8);std::memcpy(trans+16,&ptrValue,8);
    for(unsigned r:{0x19cc2fd0U,0x19cc2fe0U})jump(b+r,reinterpret_cast<U>(&screen));
    for(unsigned r:{0x19c9de20U,0x19c9de30U})jump(b+r,reinterpret_cast<U>(&counter));
    jump(b+0x19cac410,reinterpret_cast<U>(&camera));jump(b+0x19cac420,reinterpret_cast<U>(&current));
    jump(b+0x19cbc860,reinterpret_cast<U>(&transform));jump(b+0x19cab280,reinterpret_cast<U>(&fov));
    jump(b+0x19cb62b0,reinterpret_cast<U>(&getP));jump(b+0x19cb62d0,reinterpret_cast<U>(&setP));
    jump(b+0x19cb6e50,reinterpret_cast<U>(&getR));jump(b+0x19cb6e60,reinterpret_cast<U>(&setR));
    jump(b+0x19cac540,reinterpret_cast<U>(&render));jump(b+0x19d141e0,reinterpret_cast<U>(&capture));
    jump(b+0x19cae530,reinterpret_cast<U>(&dimension));jump(b+0x19cae5a0,reinterpret_cast<U>(&dimension));
    jump(b+0x19cd3610,reinterpret_cast<U>(&encode));jump(b+0x19cb2d70,reinterpret_cast<U>(&destroy));
    jump(b+0x195d3a90,reinterpret_cast<U>(&alloc));jump(b+0x195d38b0,reinterpret_cast<U>(&target));jump(b+0x195d3b40,reinterpret_cast<U>(&freeHandle));
    reset(o);attempt(b,o);
    if(o->frameStatus||o->seh||o->resourcesReleased||!liveHandle||!o->cameraRestored||captures!=1||destroys!=1)return 6;
    if(collectScene(b,o,false)||o->resourcesReleased||frees)return 7;
    ++frameCount;
    if(collectScene(b,o,false)||o->resourcesReleased||frees)return 8; // next frame alone is insufficient
    std::memset(tex+16,0,8);
    if(!collectScene(b,o,false)||!o->resourcesReleased||!o->handleReleased||frees!=1)return 9;
    badPng=true;reset(o);attempt(b,o);
    if(o->frameStatus!=3||!o->cameraRestored||!o->destroyQueued)return 10;
    if(!collectScene(b,o,true)||o->resourcesReleased||!o->handleReleased||frees!=2)return 11; // timeout remains uncertain
    badPng=false;
    if constexpr(SCENE_OPERATION==2){
        throwRender=true;reset(o);attempt(b,o);
        if(o->seh!=0xe0030001||!o->cameraRestored||!o->resourcesReleased||o->texture||pos[0]!=1||rot[3]!=1)return 12;
        if(renders!=3)return 13;
    }
    VirtualFree(reinterpret_cast<void*>(b),0,MEM_RELEASE);HeapFree(GetProcessHeap(),0,o);
    std::puts("{\"ok\":true,\"checks\":9,\"gameAccess\":false,\"privateProcessOnly\":true,\"deferredCleanupTested\":true,\"callbackStackReserve\":65536}");return 0;
}
