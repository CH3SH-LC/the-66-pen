// Private memory only; complete production hook/callback, actual HP decoder.
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
#undef INVENTORY_CODE_RVAS
#undef INVENTORY_CODE_BYTES
#undef INVENTORY_HOTFIX_RVAS
#define INVENTORY_CODE_RVAS 0x1000U
#define INVENTORY_CODE_BYTES {0}
#define INVENTORY_HOTFIX_RVAS 0x1080U
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
#include "native_inventory.cpp"
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

    commit(b+0x59196f0,8);
    q(b+0x57dbd80,b+0x47000);byteValue(b+0x470c5,1);
    q(b+0x57d4e40,b+0x70000);byteValue(b+0x700c5,1);q(b+0x583b038,b+0x71000);byteValue(b+0x710c5,1);
    q(g+0x36520,b+0x72000);q(b+0x72010,b+0x73000);q(b+0x72018,3072);q(b+0x73000,12);q(b+0x73010,256);
    for(unsigned i=0;i<3072;++i)byteValue(b+0x72020+i,static_cast<unsigned char>(i&255));
    q(b+0x401e8,b+0x74000);q(b+0x74028,b+0x75000);u(b+0x74038,3);u(b+0x7403c,9);q(b+0x75018,3);
    u(b+0x75020,7);u(b+0x75028,7);q(b+0x75030,b+0x44000);
    u(b+0x75038,0xffffffffU);u(b+0x75050,9);u(b+0x75058,9);q(b+0x75060,b+0x76000);
    for(unsigned i=0;i<2;++i){
        const F entity=i?b+0x76000:b+0x44000,manager=b+0x78000+i*0x1000,array=b+0x7a000+i*0x1000,component=b+0x7c000+i*0x1000,properties=b+0x7e000+i*0x1000;
        q(entity,b+0x47000);u(entity+0x3a8,i?9U:7U);u(entity+0x4dc,i?21010101U:10000001U);u(entity+0x458,i?2U:1U);byteValue(entity+0x49b,i?0U:1U);byteValue(entity+0x42f,1);byteValue(entity+0x482,1);q(entity+0x1a0,b+0x77000);
        q(entity+0x2d0,manager);q(manager+0x68,array);q(array+0x18,14);q(array+0x20+13*8,component);q(component,b+0x70000);q(component+0x28,entity);q(component+0x138,properties);q(properties,b+0x71000);
        // Fixed independently specified IEEE-754 encodings with identity rows.
        static constexpr unsigned char current[16]={0,0,0,0,0,0,0,0,0,0,0xc8,0x42,0,0,0xc8,0x42};
        static constexpr unsigned char maximum[16]={0,0,0,0,0,0,0,0,0,0,0xf0,0x42,0,0,0xf0,0x42};
        commit(properties,4096);if(!i)std::memcpy(reinterpret_cast<void*>(properties+0x5e0),current,16);std::memcpy(reinterpret_cast<void*>(properties+0x570),maximum,16);
    }
    // Actual inventory production layout, owned private heap only.
    const F component=b+0x90000,module=b+0x90700,bag=b+0x90800;
    q(b+0x7a018,18);q(b+0x7a020+17*8,component);q(component,b+0x90100);q(b+0x57d1b10,b+0x90100);q(component+0x28,b+0x44000);
    q(b+0x58e83c0,b+0x90200);q(b+0x90210,b+0x90300);q(b+0x90318,b+0x90400);byteValue(b+0x904c8,1);
    q(component+0x180,b+0x90500);q(b+0x90518,b+0x90600);q(b+0x90618,2);u(b+0x90620,0xffffffffU);u(b+0x90638,7);q(b+0x90640,b+0x99900);q(b+0x90648,module);
    q(module,b+0x90400);q(module+0x10,component);q(module+0x58,bag);q(bag,b+0x91000);q(b+0x57d7e30,b+0x91000);q(bag+0x10,module);
    q(bag+0x18,b+0x90900);q(b+0x90910,b+0x90a00);u(b+0x90918,2);u(b+0x9091c,4);q(b+0x90a18,2);
    q(bag+0x30,b+0x90b00);q(b+0x90b10,b+0x90c00);u(b+0x90b18,3);u(b+0x90b1c,8);q(b+0x90c18,3);
    u(bag+0x50,3);u(bag+0x54,2);q(bag+0x58,(99ULL<<32)|5);u(bag+0x60,23);
    q(b+0x5816978,b+0x91100);q(b+0x5834880,b+0x91200);q(b+0x57ed678,b+0x91300);
    q(g+0xa410,b+0x91600);q(b+0x916a0,b+0x91400);q(b+0x91420,b+0x91500);q(b+0x91518,2);u(b+0x91520,0xffffffffU);u(b+0x91534,7);u(b+0x9153c,7);u(b+0x91544,23);
    for(unsigned i=0;i<2;++i){
        const F total=b+0x92000+i*0x1000,slot=b+0x94000+i*0x1000,item=b+0x97000+i*0x1000;
        q(b+0x90a20+i*8,total);q(total,b+0x91100);q(total+0x10,i?9:25);q(total+0x18,((i?1115684866ULL:1115684865ULL)<<32)|13);
        q(b+0x90c20+i*8,slot);q(slot,b+0x91200);q(slot+0x10,item);u(slot+0x18,i);
        q(item,b+0x91300);q(item+0x20,(1107296258ULL<<32)|12);u(item+0x28,100+i);u(item+0x30,3+i);u(item+0x38,1);
    }
    q(b+0x90c30,b+0x96000);q(b+0x96000,b+0x91200);u(b+0x96018,2);
    jump(b+0x1436d00,reinterpret_cast<F>(&enginePosition));jump(b+0x19c9b820,reinterpret_cast<F>(&active));jump(b+0x19c9de20,reinterpret_cast<F>(&frame));
}
}
DWORD WINAPI pipeline(void*){
    setup();auto early=static_cast<InventoryReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(InventoryReceipt)));if(!early)return 1;
    fixtureTick=1000000;ExecuteInventory(early);if(early->stage!=1||early->status!=1||early->nativeCalls||early->seh)return 2;HeapFree(GetProcessHeap(),0,early);fixtureTick=100;
    HANDLE mapping=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(Receipt),HR_MAPPING);if(!mapping||GetLastError()==ERROR_ALREADY_EXISTS)return 3;
    auto receipt=static_cast<Receipt*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Receipt)));if(!receipt)return 4;
    std::memset(receipt,0,sizeof(*receipt));receipt->magic=0x31524847;receipt->version=kReceiptVersion;receipt->nonce=HR_NONCE;receipt->deadline=HR_DEADLINE;receipt->expectedPid=HR_TARGET_PID;receipt->expectedTid=HR_TARGET_TID;
    fixtureMessage.message=HR_MESSAGE_ID;fixtureMessage.wParam=HR_NONCE;fixtureMessage.lParam=1;
    ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));const auto& o=receipt->acceptance;
    std::printf("{\"stage\":%u,\"status\":%u,\"seh\":%u,\"contextStable\":%u,\"samplesStable\":%u,\"beforeStatus\":%u,\"afterStatus\":%u,\"controlStatus\":%u}\n",o.stage,o.status,o.seh,o.contextStable,o.samplesStable,o.before.status,o.after.status,o.control.status);
    if(receipt->claim!=2||receipt->active||receipt->callbacks!=1||o.status||o.seh||o.stage!=3||!o.resourcesReleased||!o.control.after.trialReady)return 5;
    if(o.totalCaptured!=2||o.slotCaptured!=3||o.totals[0][0].quantity!=25||o.slots[0][0].quantity+o.slots[0][1].quantity!=7||o.slots[0][2].item)return 6;
    HANDLE file=CreateFileW(L"inventory-pipeline.bin",GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);if(file==INVALID_HANDLE_VALUE)return 7;DWORD written=0;const bool saved=WriteFile(file,&o,sizeof(o),&written,nullptr)!=FALSE&&written==sizeof(o);CloseHandle(file);if(!saved)return 8;
    auto scratch=static_cast<InventoryReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(InventoryReceipt)));if(!scratch)return 9;
    const F b=fixtureBase;InventoryContext ctx{};
    q(b+0x90028,b+0x76000);if(inventoryContext(b,o.control.observation.after,o.control.after.global,ctx))return 10;q(b+0x90028,b+0x44000);
    std::memset(&ctx,0,sizeof(ctx));u(b+0x91544,24);if(inventoryContext(b,o.control.observation.after,o.control.after.global,ctx))return 11;u(b+0x91544,23);
    std::memset(&ctx,0,sizeof(ctx));q(b+0x90758,0);if(inventoryContext(b,o.control.observation.after,o.control.after.global,ctx))return 12;q(b+0x90758,b+0x90800);
    std::memset(&ctx,0,sizeof(ctx));u(b+0x90918,4097);if(inventoryContext(b,o.control.observation.after,o.control.after.global,ctx))return 13;u(b+0x90918,2);
    std::memset(&ctx,0,sizeof(ctx));q(b+0x90858,0);if(inventoryContext(b,o.control.observation.after,o.control.after.global,ctx))return 14;q(b+0x90858,(99ULL<<32)|5);
    q(b+0x93018,(1115684865ULL<<32)|13);if(inventoryRows(b,o.before,scratch->totals[0],scratch->slots[0]))return 15;q(b+0x93018,(1115684866ULL<<32)|13);std::memset(scratch,0,sizeof(*scratch));
    u(b+0x98028,100);if(inventoryRows(b,o.before,scratch->totals[0],scratch->slots[0]))return 16;u(b+0x98028,101);std::memset(scratch,0,sizeof(*scratch));
    u(b+0x95018,7);if(inventoryRows(b,o.before,scratch->totals[0],scratch->slots[0]))return 17;u(b+0x95018,1);std::memset(scratch,0,sizeof(*scratch));
    auto changed=o.before;changed.bagOccupied=1;if(inventoryRows(b,changed,scratch->totals[0],scratch->slots[0]))return 18;std::memset(scratch,0,sizeof(*scratch));
    q(b+0x97000,b+0x91200);if(inventoryRows(b,o.before,scratch->totals[0],scratch->slots[0]))return 19;q(b+0x97000,b+0x91300);std::memset(scratch,0,sizeof(*scratch));
    fixtureTick=1000000;if(inventoryRows(b,o.before,scratch->totals[0],scratch->slots[0]))return 20;fixtureTick=100;
    HeapFree(GetProcessHeap(),0,scratch);UnmapViewOfFile(receipt);CloseHandle(mapping);VirtualFree(reinterpret_cast<void*>(fixtureBase),0,MEM_RELEASE);return 0;
}
int main(){
    HANDLE thread=CreateThread(nullptr,64*1024,pipeline,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 30;if(WaitForSingleObject(thread,30000)!=WAIT_OBJECT_0)return 31;DWORD result=99;GetExitCodeThread(thread,&result);CloseHandle(thread);if(result)return static_cast<int>(result);
    std::puts("{\"ok\":true,\"gameAccess\":false,\"desktopAccess\":false,\"productionHookAndCallback\":true,\"engineEndpointsAreStandins\":true,\"gameplayVerified\":false,\"checks\":14,\"callbackStackReserve\":65536}");return 0;
}
