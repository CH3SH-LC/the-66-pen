// Actual production input callback and helpers, in this private host only.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include "native_input.cpp"
namespace {
alignas(8) unsigned char fakeButton[256]{},fakeComponent[512]{},fakeInput[96]{},fakeAvatar[128]{},fakeManager[512]{};
unsigned downs=0,ups=0;bool throwDown=false;
void magnitude(void*,float v){std::memcpy(fakeInput+0x30,&v,4);}
void direction(void*,bool active,float angle){fakeInput[0x40]=active?1U:0U;std::memcpy(fakeInput+0x44,&angle,4);}
void source(void*,float,float strength){fakeManager[0x167]=strength>0?1U:0U;std::memcpy(fakeManager+0x174,&strength,4);}
bool down(void*,unsigned){++downs;fakeButton[0x38]=1;if(throwDown)RaiseException(0xe0010001,0,0,nullptr);return true;}
bool up(void*,unsigned){++ups;fakeButton[0x38]=0;return true;}
bool active(void*){return true;}
unsigned action(void*,unsigned slot){return slot==2?0x167U:0U;}
void* button(void*,unsigned slot){return slot==2?fakeButton:nullptr;}
void commit(U at){if(!VirtualAlloc(reinterpret_cast<void*>(at&~0xfffULL),4096,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(20);}
void put(U at,U value){commit(at);std::memcpy(reinterpret_cast<void*>(at),&value,8);}
void jump(U at,U target){commit(at);unsigned char bytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};std::memcpy(bytes+2,&target,8);std::memcpy(reinterpret_cast<void*>(at),bytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);}
bool throwingTap(U b,InputReceipt* o){__try{attackTap(b,o);}__except(EXCEPTION_EXECUTE_HANDLER){return GetExceptionCode()==0xe0010001&&!o->actionReturned&&o->released&&o->releaseAttempted;}return false;}
}
DWORD WINAPI worker(void* p){return StepInput(static_cast<InputReceipt*>(p))?0U:1U;}
int main(){
    auto o=static_cast<InputReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(InputReceipt)));if(!o)return 1;
    HANDLE thread=CreateThread(nullptr,64*1024,worker,o,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!thread)return 2;
    if(WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0)return 3;DWORD codeValue=1;GetExitCodeThread(thread,&codeValue);CloseHandle(thread);
    if(codeValue||o->stage!=3||o->status!=1||o->callbacks!=1||o->nativeCalls||o->actionAttempted||o->seh||o->stopReason!=11||o->control.observation.bytes!=336||o->control.observation.targetLevel!=PLAY_TARGET_LEVEL)return 4;
    const U base=reinterpret_cast<U>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!base)return 5;
    jump(base+0x12b51c50,reinterpret_cast<U>(&magnitude));jump(base+0x12b526e0,reinterpret_cast<U>(&direction));jump(base+0x10f6ce50,reinterpret_cast<U>(&source));
    o->component=reinterpret_cast<U>(fakeComponent);o->inputState=reinterpret_cast<U>(fakeInput);o->manager=reinterpret_cast<U>(fakeManager);fakeInput[0x40]=fakeManager[0x167]=1;float value=0.5f;std::memcpy(fakeInput+0x30,&value,4);std::memcpy(fakeManager+0x174,&value,4);
    if(!releaseMove(base,o)||!o->releaseAttempted||!o->released||fakeInput[0x40])return 6;
    jump(base+0x115d6650,reinterpret_cast<U>(&down));jump(base+0x115d0820,reinterpret_cast<U>(&up));
    std::memset(o,0,sizeof(*o));o->button=reinterpret_cast<U>(fakeButton);attackTap(base,o);if(downs!=1||ups!=1||o->status||!o->actionReturned||!o->released)return 7;
    std::memset(o,0,sizeof(*o));o->button=reinterpret_cast<U>(fakeButton);throwDown=true;if(!throwingTap(base,o)||downs!=2||ups!=2||fakeButton[0x38])return 8;
    // An exact BeyondAttack enum mapping is selected from the current panel.
    alignas(8) unsigned char panel[64]{};const U panelType=0x90000,buttonType=0xa0000,avatar=reinterpret_cast<U>(fakeAvatar),nativeObject=0x10000;unsigned id=123;
    std::memcpy(panel,&panelType,8);std::memcpy(fakeButton,&buttonType,8);std::memcpy(fakeButton+0x10,&nativeObject,8);std::memcpy(fakeButton+0x28,&avatar,8);std::memcpy(fakeButton+0x20,&id,4);
    put(base+0x5805de8,panelType);put(base+0x5813bd0,buttonType);jump(base+0x115e4860,reinterpret_cast<U>(&action));jump(base+0x115d67b0,reinterpret_cast<U>(&button));jump(base+0x1455060,reinterpret_cast<U>(&active));
    std::memset(o,0,sizeof(*o));o->actionPanel=reinterpret_cast<U>(panel);o->avatar=avatar;o->avatarId=id;attackButton(base,o);if(o->button!=reinterpret_cast<U>(fakeButton)||o->attackSlot!=2||o->attackAction!=0x167)return 9;
    o->avatarId=999;attackButton(base,o);if(o->button||o->attackAction)return 10;
    // Stack top must be the exact in-level main context, not any cached model.
    auto global=static_cast<unsigned char*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,0xa000));if(!global)return 11;
    alignas(8) unsigned char ui[512]{},stack[64]{},array[64]{},context[64]{};U v=reinterpret_cast<U>(ui);std::memcpy(global+0x9c70,&v,8);v=reinterpret_cast<U>(stack);std::memcpy(ui+0x1a8,&v,8);v=reinterpret_cast<U>(array);std::memcpy(stack+0x10,&v,8);unsigned count=1;std::memcpy(stack+0x20,&count,4);v=1;std::memcpy(array+0x18,&v,8);v=reinterpret_cast<U>(context);std::memcpy(array+0x20,&v,8);const U type=0xb0000;std::memcpy(context,&type,8);put(base+0x57b3288,type);
    if(mainContext(base,reinterpret_cast<U>(global))!=reinterpret_cast<U>(context))return 12;count=129;std::memcpy(stack+0x20,&count,4);if(mainContext(base,reinterpret_cast<U>(global)))return 13;
    HeapFree(GetProcessHeap(),0,global);VirtualFree(reinterpret_cast<void*>(base),0,MEM_RELEASE);HeapFree(GetProcessHeap(),0,o);
    std::puts("{\"ok\":true,\"checks\":8,\"gameAccess\":false,\"desktopAccess\":false,\"privateProcessOnly\":true,\"callbackStackReserve\":65536}");return 0;
}
