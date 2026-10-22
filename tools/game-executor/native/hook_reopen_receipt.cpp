#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hook_reopen_protocol.h"
extern "C" __declspec(dllexport) LRESULT CALLBACK ReceiptHook(int code,WPARAM mode,LPARAM value) {
 HANDLE mapping=nullptr;Receipt* receipt=nullptr;
 if(code==HC_ACTION&&mode==PM_REMOVE&&value&&GetCurrentProcessId()==HR_TARGET_PID&&GetCurrentThreadId()==HR_TARGET_TID&&GetTickCount64()<=HR_DEADLINE){
  const auto* message=reinterpret_cast<const MSG*>(value);
  const bool actionMessage=message->lParam==1;
  const bool observationMessage=message->lParam>ge::observation::messageBase&&message->lParam<=ge::observation::messageBase+ge::observation::maxSamples;
  if(message->message==HR_MESSAGE_ID&&message->wParam==HR_NONCE&&(actionMessage||observationMessage)){
   mapping=OpenFileMappingW(FILE_MAP_WRITE,FALSE,HR_MAPPING);
   if(mapping)receipt=static_cast<Receipt*>(MapViewOfFile(mapping,FILE_MAP_WRITE,0,0,sizeof(Receipt)));
   if(receipt&&receipt->magic==0x31524847&&receipt->version==kReceiptVersion&&receipt->nonce==HR_NONCE&&
      receipt->deadline==HR_DEADLINE&&receipt->expectedPid==HR_TARGET_PID&&receipt->expectedTid==HR_TARGET_TID){
    InterlockedIncrement(&receipt->active);
    if(actionMessage){
     InterlockedIncrement(&receipt->callbacks);
     if(InterlockedCompareExchange(&receipt->claim,1,0)==0){
      ExecuteGameReopenAction(&receipt->reopen);
      InterlockedExchange(&receipt->pid,static_cast<LONG>(GetCurrentProcessId()));
      InterlockedExchange(&receipt->tid,static_cast<LONG>(GetCurrentThreadId()));
      InterlockedExchange(&receipt->claim,2);
     }
    }else{
     auto& e=receipt->observation;auto& h=e.header;const LONG sequence=static_cast<LONG>(message->lParam-ge::observation::messageBase);
     if(receipt->claim==2&&receipt->callbacks==1&&ge::observation::Eligible(h,sequence,GetTickCount64(),HR_NONCE)&&InterlockedCompareExchange(&e.reading,1,0)==0){
      InterlockedIncrement(&h.callbacks);
      // Exactly one bounded read; never wait or call a game method in this branch.
      CaptureGameSchedulerCoroutines(&receipt->reopen.context,&receipt->reopen.type,&e.last);
      ge::observation::Accept(e,receipt->reopen,sequence,GetTickCount64());
      InterlockedExchange(&h.completed,sequence);InterlockedExchange(&e.reading,0);
     }else InterlockedIncrement(&h.rejected);
    }
   }else{if(receipt)UnmapViewOfFile(receipt);receipt=nullptr;}
  }
 }
 const LRESULT next=CallNextHookEx(nullptr,code,mode,value);
 if(receipt){InterlockedDecrement(&receipt->active);UnmapViewOfFile(receipt);}if(mapping)CloseHandle(mapping);return next;
}
BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID){return TRUE;}