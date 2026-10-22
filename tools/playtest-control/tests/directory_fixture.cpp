// Private memory only; complete production hook/callback, actual runtime mapping/option-owner reader.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cstdint>
#pragma comment(lib,"User32.lib")
using F=std::uint64_t;
static F fixtureBase=0,fixtureTick=100;static unsigned fixtureFrame=1;
static MSG fixtureMessage{};
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
#undef CONTACT_CODE_RVAS
#undef CONTACT_CODE_BYTES
#undef CONTACT_HOTFIX_RVAS
#define CONTACT_CODE_RVAS 0x1000U
#define CONTACT_CODE_BYTES {0}
#define CONTACT_HOTFIX_RVAS 0x1080U
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
#define GetCurrentProcessId fixtureIdentity
#define GetCurrentThreadId fixtureIdentity
#define GetTickCount64 fixtureClock
#define GetModuleHandleW fixtureModule
#undef DIRECTORY_CODE_RVAS
#undef DIRECTORY_CODE_BYTES
#define DIRECTORY_CODE_RVAS 0x1000U
#define DIRECTORY_CODE_BYTES {0}
#include "native_directory.cpp"
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
void enginePosition(void*,float* value){value[0]=0;value[1]=0;value[2]=0;}
unsigned frame(){return fixtureFrame;}
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

    q(b+0x57dbd80,b+0x47000);byteValue(b+0x470c5,1);
    q(b+0x401e8,b+0x74000);q(b+0x74028,b+0x75000);u(b+0x74038,4);u(b+0x7403c,9);q(b+0x75018,4);
    u(b+0x75020,7);u(b+0x75028,7);q(b+0x75030,b+0x44000);u(b+0x75038,0xffffffffU);
    u(b+0x75050,9);u(b+0x75058,9);q(b+0x75060,b+0x76000);u(b+0x75068,10);u(b+0x75070,10);q(b+0x75078,b+0x77000);
    for(unsigned i=0;i<3;++i){const F e=i?b+0x75000+i*0x1000:b+0x44000;q(e,b+0x47000);u(e+0x3a8,i?8+i:7);u(e+0x4dc,i?21010101:10000001);u(e+0x458,i?2:1);byteValue(e+0x42f,1);byteValue(e+0x482,1);q(e+0x1a0,b+0x72000);}
    q(b+0x44120,b+0x78000);q(b+0x78068,b+0x7a000);q(b+0x7a018,21);q(b+0x7a020+20*8,b+0x7c000);
    q(b+0x57b7878,b+0xa0000);q(b+0x7c000,b+0xa0000);q(b+0x7c028,b+0x44000);q(b+0x7c6d0,b+0x7e000);q(b+0x7c110,b+0x7e000);q(b+0x7c698,b+0x80000);
    q(b+0x57dd580,b+0xa0100);q(b+0x7e000,b+0xa0100);q(b+0x7e510,b+0x7c000);q(b+0x57d73a0,b+0xa0200);q(b+0x80000,b+0xa0200);q(b+0x80118,b+0x7c000);q(b+0x80130,b+0x7e000);q(b+0x80120,b+0x82000);q(b+0x82098,b+0x7c000);q(b+0x82048,b+0x7e000);q(b+0x82050,b+0x80000);u(b+0x7e4b0,1);
    q(g+0xa410,b+0x83000);q(b+0x83000,b+0xa1000);q(b+0x57b2b08,b+0xa1000);q(b+0x830a0,b+0x84000);q(b+0x83100,b+0x86000);q(b+0x84020,b+0x85000);u(b+0x84044,2);q(b+0x85018,2);q(b+0x86010,b+0x87000);u(b+0x86040,2);q(b+0x87018,2);
    for(unsigned i=0;i<2;++i){F at=b+0x85020+i*20;u(at,9+i);u(at+4,0xffffffffU);u(at+8,9+i);u(at+12,1001+i);u(at+16,9001+i);at=b+0x87020+i*16;u(at,1001+i);u(at+4,0xffffffffU);u(at+8,1001+i);u(at+12,9+i);}
    q(g+0x9c70,b+0x90000);q(b+0x901a8,b+0x91000);q(b+0x91010,b+0x92000);u(b+0x91020,1);q(b+0x92018,1);q(b+0x92020,b+0x93000);q(b+0x93000,b+0xa2000);q(b+0x57b3288,b+0xa2000);q(b+0x93450,b+0x94000);q(b+0x94000,b+0xa3000);q(b+0x57b3860,b+0xa3000);q(b+0x941f8,b+0x95000);
    q(b+0x95028,b+0x96000);q(b+0x96040,b+0x97000);q(b+0x97010,b+0x98000);u(b+0x97018,1);q(b+0x98018,1);q(b+0x98020,b+0x9c000);
    q(b+0x95020,b+0x99000);q(b+0x99040,b+0x9a000);q(b+0x9a010,b+0x9b000);q(b+0x9b018,1);
    q(b+0x9c000,b+0xa4000);q(b+0x57e59d8,b+0xa4000);q(b+0x9c030,b+0x9d000);q(b+0x9d000,b+0xa5000);q(b+0x579f538,b+0xa5000);q(b+0x9d010,b+0x9d800);byteValue(b+0x9d0b0,1);byteValue(b+0x9d0c0,1);
    q(b+0x9c038,b+0x9e000);q(b+0x9e000,b+0xa6000);q(b+0x579f540,b+0xa6000);q(b+0x9e0e0,b+0x9f000);u(b+0x9f010,4);static constexpr wchar_t label[]=L"\u6d4b\u8bd5\u4ea4\u4e92";std::memcpy(reinterpret_cast<void*>(b+0x9f014),label,8);
    q(b+0x9d0d8,b+0xa7000);q(b+0xa7010,b+0xa8000);q(b+0xa7018,b+0xa9000);q(b+0xa8010,b+0xaa000);q(b+0xa9010,b+0xaa000);q(b+0xaa010,b+0xab000);q(b+0xab018,1);
    q(b+0xa8018,b+0xac000);q(b+0xac010,b+0xad000);u(b+0xac018,1);q(b+0xad018,1);q(b+0xad020,b+0xae000);q(b+0xae010,b+0xaf000);q(b+0xaf018,b+0x14058e50);q(b+0xaf040,b+0xb0000);q(b+0xb0010,b+0xb1000);q(b+0xb1010,b+0x100000);q(b+0xb1018,b+0x100000);q(b+0xb1028,b+0xb5000);q(b+0xb1040,b+0xb2000);q(b+0xb2000,b+0xb3000);u(b+0xb2030,10);
    q(b+0x57d3330,b+0xb4000);q(b+0xb3088,b+0xb6000);put<unsigned short>(b+0xb30c2,1);put<unsigned short>(b+0xb30be,16);q(b+0xb6000,b+0xb4000);u(b+0xb6008,3);q(b+0xb30d0+7*8,b+0x100000);q(b+0xb30d0+9*8,b+0x101000);q(b+0xb30d0+25*8,b+0xb5000);
    static constexpr unsigned char getter[]={0x8b,0x41,0x30,0xc3,0x90,0x90,0x90,0x90};commit(b+0x101000);std::memcpy(reinterpret_cast<void*>(b+0x101000),getter,8);
    jump(b+0x1455060,reinterpret_cast<F>(&active));
    jump(b+0x1436d00,reinterpret_cast<F>(&enginePosition));jump(b+0x19c9b820,reinterpret_cast<F>(&active));jump(b+0x19c9de20,reinterpret_cast<F>(&frame));
}
}
DWORD WINAPI pipeline(void*){
    setup();const F b=fixtureBase;
    q(b+0x39000,b+0xc0000);q(b+0x57cad48,b+0xc0000);q(b+0x39020,b+0xc1000);q(b+0xc1000,b+0xc2000);q(b+0x57dc148,b+0xc2000);q(b+0xc1028,b+0xc3000);q(b+0xc3000,b+0xc4000);q(b+0x57dc0b8,b+0xc4000);
    put<unsigned short>(b+0xc40be,64);q(b+0xc41e8,b+0x1713e080);q(b+0xc41e8+64*8,b+0xc5000);q(b+0xc3010,b+0xc6000);q(b+0xc6010,b+0xc7000);u(b+0xc6018,2);u(b+0xc601c,5);q(b+0xc7018,2);
    for(unsigned i=0;i<2;++i){F at=b+0xc8000+i*0x1000;q(b+0xc7020+i*8,at);q(at,b+0xca000);q(at+0x20,b+0xcb000);u(at+0x30,1001+i);}u(b+0xcb018,55);
    auto early=static_cast<DirectoryReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(DirectoryReceipt)));if(!early)return 1;
    fixtureTick=1000000;ExecuteDirectory(early);if(early->stage!=1||early->status!=1||early->nativeCalls||early->seh)return 2;HeapFree(GetProcessHeap(),0,early);fixtureTick=100;
    HANDLE mapping=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(Receipt),HR_MAPPING);if(!mapping||GetLastError()==ERROR_ALREADY_EXISTS)return 3;
    auto receipt=static_cast<Receipt*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Receipt)));if(!receipt)return 4;
    std::memset(receipt,0,sizeof(*receipt));receipt->magic=0x31524847;receipt->version=kReceiptVersion;receipt->nonce=HR_NONCE;receipt->deadline=HR_DEADLINE;receipt->expectedPid=HR_TARGET_PID;receipt->expectedTid=HR_TARGET_TID;
    fixtureMessage.message=HR_MESSAGE_ID;fixtureMessage.wParam=HR_NONCE;fixtureMessage.lParam=1;
    ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));const auto& o=receipt->acceptance;
    std::printf("{\"stage\":%u,\"status\":%u,\"seh\":%u,\"directoryStatus\":%u,\"stable\":%u,\"contactStatus\":%u}\n",o.stage,o.status,o.seh,o.first.status,o.stable,o.contact.status);
    HANDLE file=CreateFileW(L"directory-pipeline.bin",GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);if(file==INVALID_HANDLE_VALUE)return 8;DWORD written=0;const bool saved=WriteFile(file,&o,sizeof(o),&written,nullptr)!=FALSE&&written==sizeof(o);CloseHandle(file);if(!saved)return 9;
    if(receipt->claim!=2||receipt->active||receipt->callbacks!=1||o.status||o.seh||o.stage!=3||!o.resourcesReleased||!o.contact.control.after.trialReady)return 5;
    if(o.first.status||o.first.count!=2||o.first.rows[0].editorGuid!=1001||o.first.rows[1].editorGuid!=1002)return 6;
    auto check=static_cast<DirectoryReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(DirectoryReceipt)));if(!check)return 10;
    q(b+0x39000,b+0xc0008);ExecuteDirectory(check);if(check->status||check->first.status==0)return 11;q(b+0x39000,b+0xc0000);
    q(b+0xc1000,b+0xc2008);ExecuteDirectory(check);if(check->status||check->first.status==0)return 12;q(b+0xc1000,b+0xc2000);
    q(b+0xc3000,b+0xc4008);ExecuteDirectory(check);if(check->status||check->first.status==0)return 13;q(b+0xc3000,b+0xc4000);
    q(b+0xc41e8,b+0x1713e081);ExecuteDirectory(check);if(check->status||check->first.status==0)return 14;q(b+0xc41e8,b+0x1713e080);
    u(b+0xc6018,8193);ExecuteDirectory(check);if(check->status||check->first.status==0)return 15;u(b+0xc6018,2);
    q(b+0xc7018,1);ExecuteDirectory(check);if(check->status||check->first.status==0)return 16;q(b+0xc7018,2);
    q(b+0xc7020,0);ExecuteDirectory(check);if(check->status||check->first.status==0)return 17;q(b+0xc7020,b+0xc8000);
    u(b+0xc8030,0);ExecuteDirectory(check);if(check->status||check->first.status==0)return 18;u(b+0xc8030,1001);
    u(b+0xc9030,1001);ExecuteDirectory(check);if(check->status||check->first.status||check->first.rows[0].editorGuid!=check->first.rows[1].editorGuid)return 19;u(b+0xc9030,1002);
    u(b+0x36050,8);ExecuteDirectory(check);if(check->status==0||check->stage!=1)return 22;u(b+0x36050,7);
    HeapFree(GetProcessHeap(),0,check);UnmapViewOfFile(receipt);CloseHandle(mapping);VirtualFree(reinterpret_cast<void*>(fixtureBase),0,MEM_RELEASE);return 0;
}
int main(){
    HANDLE thread=CreateThread(nullptr,64*1024,pipeline,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 20;if(WaitForSingleObject(thread,30000)!=WAIT_OBJECT_0)return 21;DWORD result=99;GetExitCodeThread(thread,&result);CloseHandle(thread);if(result)return static_cast<int>(result);
    std::puts("{\"ok\":true,\"gameAccess\":false,\"desktopAccess\":false,\"productionHookAndCallback\":true,\"engineEndpointsAreStandins\":true,\"gameplayVerified\":false,\"checks\":13,\"callbackStackReserve\":65536}");return 0;
}
