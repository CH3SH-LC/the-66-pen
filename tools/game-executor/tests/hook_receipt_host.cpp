// Independent test host. It is neither the game nor a game adapter.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstdio>

#include "../native/hook_receipt_protocol.h"

int wmain() {
    MSG message{};
    PeekMessageW(&message, nullptr, WM_USER, WM_USER, PM_NOREMOVE);
    const UINT messageId = RegisterWindowMessageW(HR_MESSAGE_NAME);
    FILETIME creation{}, exit{}, kernel{}, user{};
    if (!messageId || !GetProcessTimes(GetCurrentProcess(), &creation, &exit, &kernel, &user)) return 2;
    const std::uint64_t ticks = (static_cast<std::uint64_t>(creation.dwHighDateTime) << 32) | creation.dwLowDateTime;
    std::printf("{\"kind\":\"SELFTEST_HOST_READY\",\"pid\":%lu,\"tid\":%lu,\"creationTicks\":%llu,\"messageId\":%u}\n",
        GetCurrentProcessId(), GetCurrentThreadId(), static_cast<unsigned long long>(ticks), messageId);
    std::fflush(stdout);
    unsigned int handled = 0;
    const ULONGLONG deadline = GetTickCount64() + 300000;
    while (GetTickCount64() < deadline) {
        MsgWaitForMultipleObjectsEx(0, nullptr, 100, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
            if (message.message == WM_QUIT) return 0;
            if (message.message != messageId || message.wParam != HR_NONCE) continue;
            if (message.lParam == 1) ++handled;
            if (message.lParam == 2) {
                HANDLE mapping = OpenFileMappingW(FILE_MAP_WRITE, FALSE, HR_MAPPING);
                Receipt* receipt = mapping ? static_cast<Receipt*>(MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, sizeof(Receipt))) : nullptr;
                if (receipt && receipt->magic == 0x31524847 && receipt->nonce == HR_NONCE) {
                    InterlockedExchange(&receipt->hostPid, static_cast<LONG>(GetCurrentProcessId()));
                    InterlockedExchange(&receipt->hostTid, static_cast<LONG>(GetCurrentThreadId()));
                    InterlockedIncrement(&receipt->hostPings);
                    std::printf("{\"kind\":\"HOST_POST_UNHOOK_PING\",\"handledOriginalMessages\":%u}\n", handled);
                    std::fflush(stdout);
                }
                if (receipt) UnmapViewOfFile(receipt);
                if (mapping) CloseHandle(mapping);
            }
            if (message.lParam == 3) return 0;
        }
    }
    std::puts("{\"kind\":\"HOST_DEADLINE\"}");
    return 3;
}
