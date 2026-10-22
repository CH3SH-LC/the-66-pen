// Per-build target constants are supplied by /FI hook_receipt_config.h.
// Each immutable build enables identity, context, or one guarded scene operation.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "hook_receipt_protocol.h"

extern "C" __declspec(dllexport) LRESULT CALLBACK ReceiptHook(int code, WPARAM mode, LPARAM value) {
    HANDLE mapping = nullptr;
    Receipt* receipt = nullptr;
    if (code == HC_ACTION && mode == PM_REMOVE && value != 0 &&
        GetCurrentProcessId() == HR_TARGET_PID && GetCurrentThreadId() == HR_TARGET_TID &&
        GetTickCount64() <= HR_DEADLINE) {
        const MSG* message = reinterpret_cast<const MSG*>(value);
        if (message->message == HR_MESSAGE_ID && message->wParam == HR_NONCE && message->lParam == 1) {
            mapping = OpenFileMappingW(FILE_MAP_WRITE, FALSE, HR_MAPPING);
            if (mapping) receipt = static_cast<Receipt*>(MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, sizeof(Receipt)));
            if (receipt && receipt->magic == 0x31524847 && receipt->version == kReceiptVersion &&
                receipt->nonce == HR_NONCE && receipt->deadline == HR_DEADLINE &&
                receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID) {
                InterlockedIncrement(&receipt->active);
                InterlockedIncrement(&receipt->callbacks);
                if (InterlockedCompareExchange(&receipt->claim, 1, 0) == 0) {
#if HR_READ_REOPEN_GUARDS
                    CaptureGameReopenGuardBundle(&receipt->context,&receipt->catalog,&receipt->lifecycleType,&receipt->schedulerCoroutines,&receipt->reopenGuards);
#else
#if HR_READ_CONTEXT
                    CaptureGameContextSnapshot(&receipt->context);
#if HR_READ_LEVEL_CATALOG
                    CaptureGameLevelCatalog(&receipt->context,&receipt->catalog);
#endif
#if HR_READ_LIFECYCLE_TYPE
                    CaptureGameLifecycleType(&receipt->context,&receipt->lifecycleType);
#endif
#if HR_READ_SCHEDULER_COROUTINES
                    CaptureGameSchedulerCoroutines(&receipt->context,&receipt->lifecycleType,&receipt->schedulerCoroutines);
#endif
#endif
#endif
#if HR_ACTION
                    ExecuteGameSceneAction(&receipt->context, &receipt->action);
#endif
                    InterlockedExchange(&receipt->pid, static_cast<LONG>(GetCurrentProcessId()));
                    InterlockedExchange(&receipt->tid, static_cast<LONG>(GetCurrentThreadId()));
                    InterlockedExchange(&receipt->claim, 2);
                }
            } else {
                if (receipt) UnmapViewOfFile(receipt);
                receipt = nullptr;
            }
        }
    }
    const LRESULT next = CallNextHookEx(nullptr, code, mode, value);
    if (receipt) {
        InterlockedDecrement(&receipt->active);
        UnmapViewOfFile(receipt);
    }
    if (mapping) CloseHandle(mapping);
    return next;
}

BOOL WINAPI DllMain(HINSTANCE, DWORD, LPVOID) { return TRUE; }
