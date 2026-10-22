// Execute the production transform entry on a small private thread. All large
// snapshots/receipts live on this process's heap. The synthetic PID=1 guard
// returns before module lookup, metadata initialization, or any game function.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <cstring>
#include "native_transform.h"
static_assert(HR_TARGET_PID == 1 && HR_TARGET_TID == 1 && HR_DEADLINE == 1,
              "Startup harness must never compile for a real target");
namespace {
struct Context { GameContextSnapshot* snapshot; TransformReceipt* receipt; };
DWORD WINAPI Run(LPVOID argument) {
    const auto context = static_cast<Context*>(argument);
    ExecuteTransform(context->snapshot, context->receipt);
    return 0;
}
bool zero(const void* memory, std::size_t size) {
    const auto bytes = static_cast<const unsigned char*>(memory);
    for (std::size_t i = 0; i < size; ++i) if (bytes[i]) return false;
    return true;
}
}
int main() {
    if (GetCurrentProcessId() == HR_TARGET_PID) return 2;
    Context context{};
    context.snapshot = static_cast<GameContextSnapshot*>(HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(GameContextSnapshot)));
    context.receipt = static_cast<TransformReceipt*>(HeapAlloc(GetProcessHeap(), 0, sizeof(TransformReceipt)));
    if (!context.snapshot || !context.receipt) return 3;
    std::memset(context.receipt, 0xa5, sizeof(*context.receipt));
    constexpr SIZE_T stack = 128 * 1024;
    HANDLE thread = CreateThread(nullptr, stack, Run, &context, STACK_SIZE_PARAM_IS_A_RESERVATION, nullptr);
    if (!thread) return 4;
    const DWORD wait = WaitForSingleObject(thread, 10000);
    DWORD code = 0xffffffff;
    const bool joined = wait == WAIT_OBJECT_0 && GetExitCodeThread(thread, &code) != FALSE;
    // A timeout is a failed standalone harness; process exit owns its private
    // allocations. Never free memory while a test thread might still use it.
    if (!joined) return 5;
    CloseHandle(thread);
    const auto& result = *context.receipt;
    const bool ok = code == 0 && result.size == sizeof(result) && result.version == 1 &&
        result.status == 1 && result.stage == 1 && result.mode == TRANSFORM_WRITE &&
        result.count == TRANSFORM_COUNT && result.seh == 0 && result.nativeCalls == 0 &&
        result.completed == 0 && result.sceneUnchanged == 0 &&
        zero(result.rows, sizeof(result.rows)) && zero(&result.afterScene, sizeof(result.afterScene));
    std::printf("{\"ok\":%s,\"kind\":\"transform-callback-startup\",\"privateThreadStack\":%zu,\"receiptBytes\":%zu,\"snapshotBytes\":%zu,\"requestCount\":%u,\"mode\":%u,\"status\":%u,\"stage\":%u,\"nativeCalls\":%u,\"seh\":%u,\"gameProcessAccessed\":false}\n",
        ok ? "true" : "false", stack, sizeof(result), sizeof(*context.snapshot), result.count,
        result.mode, result.status, result.stage, result.nativeCalls, result.seh);
    HeapFree(GetProcessHeap(), 0, context.receipt);
    HeapFree(GetProcessHeap(), 0, context.snapshot);
    return ok ? 0 : 6;
}
