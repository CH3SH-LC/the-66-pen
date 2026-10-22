// Full production ReceiptHook -> StepInput -> scene/dictionary/ownership/input
// checks against private memory. Only engine endpoints and process clock/name
// resolution are stand-ins. This never opens a process or installs a hook.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cstdint>
using F=std::uint64_t;
static F fixtureBase=0,fixtureTick=100;static unsigned fixtureFrame=1,pulses=0,presses=0,downs=0,ups=0;
static float positionX=0;static bool reenter=false;static MSG fixtureMessage{};
static DWORD fixtureIdentity(){return 1;}
static ULONGLONG fixtureClock(){return fixtureTick;}
static HMODULE fixtureModule(LPCWSTR name){return std::wcscmp(name,L"YuanShen.exe")==0?reinterpret_cast<HMODULE>(fixtureBase):nullptr;}
#undef HR_DEADLINE
#define HR_DEADLINE 1000000ULL
#undef HR_GAME_TIMESTAMP
#define HR_GAME_TIMESTAMP 0U
#undef HR_GAME_IMAGE_SIZE
#define HR_GAME_IMAGE_SIZE 0x1a000000U
#undef PLAY_CODE_RVAS
#undef PLAY_CODE_BYTES
#undef PLAY_HOTFIX_RVAS
#define PLAY_CODE_RVAS 0x1000U
#define PLAY_CODE_BYTES {0}
#define PLAY_HOTFIX_RVAS 0x1080U
#undef CONTROL_CODE_RVAS
#undef CONTROL_CODE_BYTES
#undef CONTROL_HOTFIX_RVAS
#define CONTROL_CODE_RVAS 0x1000U
#define CONTROL_CODE_BYTES {0}
#define CONTROL_HOTFIX_RVAS 0x1080U
#undef INPUT_CODE_RVAS
#undef INPUT_CODE_BYTES
#undef INPUT_HOTFIX_RVAS
#define INPUT_CODE_RVAS 0x1000U
#define INPUT_CODE_BYTES {0}
#define INPUT_HOTFIX_RVAS 0x1080U
#undef CONTROL_GLOBAL
#undef CONTROL_EDITOR
#undef CONTROL_TASK
#undef CONTROL_TOKEN
#undef CONTROL_CACHE
#undef CONTROL_DATA
#define CONTROL_GLOBAL (fixtureBase+0x20000)
#define CONTROL_EDITOR (fixtureBase+0x35000)
#define CONTROL_TASK (fixtureBase+0x36000)
#define CONTROL_TOKEN 7U
#define CONTROL_CACHE (fixtureBase+0x38000)
#define CONTROL_DATA (fixtureBase+0x39000)
#undef INPUT_AVATAR
#undef INPUT_AVATAR_ID
#undef INPUT_COMPONENT
#undef INPUT_CONTEXT
#undef INPUT_VIEW
#undef INPUT_BUTTON
#undef INPUT_SLOT
#undef INPUT_ITEM
#define INPUT_AVATAR (fixtureBase+0x44000)
#define INPUT_AVATAR_ID 7U
#define INPUT_COMPONENT (fixtureBase+0x4d000)
#define INPUT_CONTEXT (fixtureBase+0x4a000)
#define INPUT_VIEW (fixtureBase+0x4b000)
#if INPUT_OPERATION == 12
#define INPUT_BUTTON (fixtureBase+0x5e000)
#else
#define INPUT_BUTTON (fixtureBase+0x54000)
#endif
#define INPUT_SLOT 2U
#define INPUT_ITEM (fixtureBase+0x5c000)
#define GetCurrentProcessId fixtureIdentity
#define GetCurrentThreadId fixtureIdentity
#define GetTickCount64 fixtureClock
#define GetModuleHandleW fixtureModule
#include "native_input.cpp"
#include "../native/hook_receipt.cpp"
#undef GetCurrentProcessId
#undef GetCurrentThreadId
#undef GetTickCount64
#undef GetModuleHandleW
namespace {
void commit(F at,SIZE_T n=4096){const F start=at&~0xfffULL;const SIZE_T length=static_cast<SIZE_T>((at+n-start+4095)&~4095ULL);if(!VirtualAlloc(reinterpret_cast<void*>(start),length,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(30);}
template<class T>void put(F at,T value){commit(at,sizeof(T));std::memcpy(reinterpret_cast<void*>(at),&value,sizeof(value));}
void q(F at,F value){put(at,value);}void u(F at,unsigned value){put(at,value);}void byteValue(F at,unsigned char value){put(at,value);}
void jump(F at,F target){commit(at);unsigned char bytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};std::memcpy(bytes+2,&target,8);std::memcpy(reinterpret_cast<void*>(at),bytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);}
bool active(void*){return true;}
void enginePosition(void*,float* value){value[0]=positionX;value[1]=0;value[2]=0;}
unsigned frame(){return fixtureFrame;}
void magnitude(void*,float value){put(fixtureBase+0x4f030,value);}
void direction(void*,bool value,float angle){byteValue(fixtureBase+0x4f040,value?1U:0U);put(fixtureBase+0x4f044,angle);}
void source(void*,float angle,float strength){put(fixtureBase+0x4c194,angle);put(fixtureBase+0x4c174,strength);byteValue(fixtureBase+0x4c167,strength>0?1U:0U);}
void joystick(void* context,float angle,float strength){
    if(reinterpret_cast<F>(context)!=INPUT_CONTEXT)RaiseException(0xe0010101,0,0,nullptr);
    ++pulses;source(nullptr,angle,strength);
    if(!reenter){reenter=true;ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));reenter=false;}
}
unsigned action(void*,unsigned slot){return slot==2?0x167U:0U;}
void* button(void*,unsigned slot){return slot==2?reinterpret_cast<void*>(fixtureBase+0x54000):nullptr;}
bool down(void*,unsigned slot){if(slot!=2)return false;++downs;byteValue(fixtureBase+0x54038,1);return true;}
bool up(void*,unsigned slot){if(slot!=2)return false;++ups;byteValue(fixtureBase+0x54038,0);return true;}
void* label(void* item){return reinterpret_cast<F>(item)==INPUT_ITEM?reinterpret_cast<void*>(fixtureBase+0x60000):nullptr;}
void press(void* object){if(reinterpret_cast<F>(object)!=fixtureBase+0x5e000)RaiseException(0xe0010102,0,0,nullptr);++presses;}
void setup(){
    fixtureBase=reinterpret_cast<F>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!fixtureBase)ExitProcess(31);
    commit(fixtureBase,0x2000);commit(fixtureBase+0x20000,0x43000);
    IMAGE_DOS_HEADER dos{};dos.e_magic=IMAGE_DOS_SIGNATURE;dos.e_lfanew=0x100;std::memcpy(reinterpret_cast<void*>(fixtureBase),&dos,sizeof(dos));
    IMAGE_NT_HEADERS64 nt{};nt.Signature=IMAGE_NT_SIGNATURE;nt.OptionalHeader.SizeOfImage=HR_GAME_IMAGE_SIZE;std::memcpy(reinterpret_cast<void*>(fixtureBase+0x100),&nt,sizeof(nt));
    const F b=fixtureBase,g=b+0x20000;
    q(b+0x5783de8,g);q(g+0xa440,b+0x31000);q(g+0xa430,b+0x32000);q(b+0x32050,b+0x33000);q(b+0x33030,b+0x34000);u(b+0x34070,5);
    q(g+0xa960,b+0x35000);u(b+0x35098,PLAY_TARGET_LEVEL);q(b+0x35090,b+0x36000);u(b+0x36050,7);u(b+0x36054,1);u(b+0x3605c,10);
    q(g+0xa150,b+0x37000);q(b+0x37090,b+0x38000);q(b+0x37068,b+0x38000);q(b+0x38020,b+0x39000);byteValue(b+0x38030,1);
    q(g+0xf390,b+0x3a000);q(b+0x3a070,b+0x3b000);q(b+0x3b010,b+0x3c000);u(b+0x3c024,7);q(g+0xaa40,b+0x3d000);byteValue(b+0x3d0e5,1);q(g+0xad80,b+0x3e000);
    q(b+0x31118,b+0x3f000);u(b+0x3f158,123);u(b+0x31230,123);u(b+0x311cc,47504);
    q(g+0x9d50,b+0x40000);q(b+0x40150,b+0x41000);u(b+0x40250,7);q(b+0x41020,b+0x42000);q(b+0x41028,b+0x43000);q(b+0x42018,1);u(b+0x42020,1);q(b+0x43018,1);u(b+0x43020,7);u(b+0x43024,0xffffffffU);u(b+0x43028,7);q(b+0x43030,b+0x44000);
    q(b+0x44000,b+0x47000);q(b+0x57b1570,b+0x47000);q(b+0x474c8,b+0x9a96970);q(b+0x441e8,b+0x45000);q(b+0x45010,0x10000);q(b+0x44038,b+0x46000);q(b+0x46010,0x10000);byteValue(b+0x4449b,1);
    q(b+0x57a8ae8,b+0x48000);byteValue(b+0x480c7,1);commit(b+0x57872a4,12);
    q(g+0x9c70,b+0x49000);q(b+0x491a8,b+0x50000);q(b+0x50010,b+0x51000);u(b+0x50020,1);q(b+0x51018,1);q(b+0x51020,b+0x4a000);
    q(b+0x57b3288,b+0x61000);q(b+0x4a000,b+0x61000);q(b+0x4a450,b+0x4b000);q(b+0x57b3860,b+0x62000);q(b+0x4b000,b+0x62000);
    q(g+0x9ca0,b+0x4c000);q(b+0x4c090,b+0x44000);q(b+0x4c0c0,b+0x4d000);q(b+0x4d000,b+0x4e000);q(b+0x57f0aa8,b+0x4e000);q(b+0x4d028,b+0x44000);q(b+0x4d110,b+0x4f000);q(b+0x4e450,b+0x12b51c50);q(b+0x4e2f0,b+0x12b526e0);
    q(b+0x4b2d8,b+0x52000);q(b+0x52000,b+0x53000);q(b+0x5805de8,b+0x53000);q(b+0x54000,b+0x55000);q(b+0x5813bd0,b+0x55000);q(b+0x54010,0x10000);u(b+0x54020,7);q(b+0x54028,b+0x44000);
    q(b+0x4b1f8,b+0x56000);q(b+0x56028,b+0x57000);q(b+0x56020,b+0x58000);q(b+0x57040,b+0x59000);q(b+0x58040,b+0x5a000);u(b+0x59018,1);q(b+0x59010,b+0x5b000);q(b+0x5b018,1);q(b+0x5b020,b+0x5c000);
    q(b+0x5c000,b+0x5d000);q(b+0x57e59d8,b+0x5d000);q(b+0x5c030,b+0x5e000);q(b+0x5e000,b+0x5f000);q(b+0x579f538,b+0x5f000);q(b+0x5e010,0x10000);byteValue(b+0x5e0b0,1);byteValue(b+0x5e0c0,1);
    static constexpr std::uint16_t text[]={0x6253,0x5f00,0x5546,0x5e97};u(b+0x60010,4);std::memcpy(reinterpret_cast<void*>(b+0x60014),text,sizeof(text));commit(b+0x59196f0,8);
    jump(b+0x1436d00,reinterpret_cast<F>(&enginePosition));jump(b+0x19c9b820,reinterpret_cast<F>(&active));jump(b+0x1455060,reinterpret_cast<F>(&active));jump(b+0x19c9de20,reinterpret_cast<F>(&frame));
    jump(b+0x12b51c50,reinterpret_cast<F>(&magnitude));jump(b+0x12b526e0,reinterpret_cast<F>(&direction));jump(b+0x10f6ce50,reinterpret_cast<F>(&source));jump(b+0xc935160,reinterpret_cast<F>(&joystick));
    jump(b+0x115e4860,reinterpret_cast<F>(&action));jump(b+0x115d67b0,reinterpret_cast<F>(&button));jump(b+0x115d6650,reinterpret_cast<F>(&down));jump(b+0x115d0820,reinterpret_cast<F>(&up));jump(b+0x10a80140,reinterpret_cast<F>(&label));jump(b+0x19dc6600,reinterpret_cast<F>(&press));
}
}
DWORD WINAPI pipeline(void*){
    setup();HANDLE mapping=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(Receipt),HR_MAPPING);if(!mapping||GetLastError()==ERROR_ALREADY_EXISTS)return 1;
    auto receipt=static_cast<Receipt*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Receipt)));if(!receipt)return 2;std::memset(receipt,0,sizeof(*receipt));receipt->magic=0x31524847;receipt->version=kReceiptVersion;receipt->nonce=HR_NONCE;receipt->deadline=HR_DEADLINE;receipt->expectedPid=HR_TARGET_PID;receipt->expectedTid=HR_TARGET_TID;
    fixtureMessage.message=HR_MESSAGE_ID;fixtureMessage.wParam=HR_NONCE;fixtureMessage.lParam=1;
    unsigned iterations=0;while(receipt->claim!=2&&iterations++<250){
        // A stand-in engine frame consumes the actual source written by the
        // production callback. This displacement is explicitly synthetic.
        float strength=0;std::memcpy(&strength,reinterpret_cast<void*>(fixtureBase+0x4c174),4);if(*reinterpret_cast<unsigned char*>(fixtureBase+0x4c167))positionX+=strength*0.05f;
        ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));
        if(receipt->claim!=2)ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));
        ++fixtureFrame;fixtureTick+=16;
    }
    const auto& o=receipt->acceptance;
    std::printf("{\"stage\":%u,\"status\":%u,\"stopReason\":%u,\"seh\":%u,\"callbacks\":%u,\"points\":%u,\"sourceIdle\":%u,\"released\":%u,\"pulses\":%u,\"controlStatus\":%u,\"trialReady\":%u}\n",o.stage,o.status,o.stopReason,o.seh,o.callbacks,o.points,o.sourceIdle,o.released,pulses,o.control.status,o.control.after.trialReady);
    if(receipt->claim!=2||receipt->active||receipt->callbacks!=static_cast<LONG>(o.callbacks)||o.status||o.seh||o.stage!=3||!o.released||!o.resourcesReleased||!o.control.after.trialReady)return 3;
    if constexpr(INPUT_OPERATION==10){if(pulses<2||pulses>=o.callbacks||o.points<2||!o.sourceIdle||positionX<=0||*reinterpret_cast<unsigned char*>(fixtureBase+0x4c167))return 4;}
    else if constexpr(INPUT_OPERATION==11){if(downs!=1||ups!=1||!o.pressAccepted)return 5;}
    else if constexpr(INPUT_OPERATION==12){if(presses!=1||o.optionIndex!=0)return 6;}
    else {if(o.actionAttempted||o.options!=1||!o.optionComplete)return 7;}
    const LONG calls=receipt->callbacks;ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->callbacks!=calls||receipt->active)return 8;
    HANDLE file=CreateFileW(L"input-pipeline.bin",GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);if(file==INVALID_HANDLE_VALUE)return 9;DWORD written=0;const bool saved=WriteFile(file,&o,sizeof(o),&written,nullptr)!=FALSE&&written==sizeof(o);CloseHandle(file);if(!saved)return 10;
    UnmapViewOfFile(receipt);CloseHandle(mapping);VirtualFree(reinterpret_cast<void*>(fixtureBase),0,MEM_RELEASE);return 0;
}
int main(){
    HANDLE thread=CreateThread(nullptr,64*1024,pipeline,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 20;if(WaitForSingleObject(thread,30000)!=WAIT_OBJECT_0)return 21;DWORD result=99;GetExitCodeThread(thread,&result);CloseHandle(thread);if(result)return static_cast<int>(result);
    std::puts("{\"ok\":true,\"gameAccess\":false,\"desktopAccess\":false,\"productionHookAndCallback\":true,\"engineEndpointsAreStandins\":true,\"playerMotionVerified\":false,\"checks\":5,\"callbackStackReserve\":65536}");return 0;
}
