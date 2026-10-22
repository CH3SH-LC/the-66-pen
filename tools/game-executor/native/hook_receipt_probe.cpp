// No runtime target arguments: PID/TID/start time/image/DLL/nonce/deadline are
// fixed in the per-run build profile. Only standard thread-specific hook APIs.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <vector>
#ifndef HR_SELFTEST_ONLY
#define HR_SELFTEST_ONLY 0
#endif

#include "hook_receipt_protocol.h"
static_assert(HR_TARGET_PID != 0 && HR_TARGET_TID != 0, "Global hooks are forbidden");
// Same defaults as the snapshot header; kept local so a profile that does not include that
// header (HR_READ_CONTEXT=0) resolves them too.
#ifndef GS_BOOTSTRAP_READONLY
#define GS_BOOTSTRAP_READONLY 0
#endif
#ifndef GS_REVIEWED_ACTION_PROFILE
#define GS_REVIEWED_ACTION_PROFILE 0
#endif
#ifndef GS_STRICT_PROFILE
#define GS_STRICT_PROFILE (GS_BOOTSTRAP_READONLY || GS_REVIEWED_ACTION_PROFILE)
#endif
#ifndef HR_ACTION
#define HR_ACTION 0
#endif
#if GS_BOOTSTRAP_READONLY && GS_REVIEWED_ACTION_PROFILE
#error "Choose one profile mode: GS_BOOTSTRAP_READONLY or GS_REVIEWED_ACTION_PROFILE, never both"
#endif
// The readonly bootstrap inspects and never acts. game_context_snapshot.cpp enforces the
// same rule for its own translation unit; this one covers the probe that would carry out
// the action.
#if GS_BOOTSTRAP_READONLY && HR_ACTION != 0
#error "GS_BOOTSTRAP_READONLY forbids HR_ACTION != 0"
#endif
// A reviewed action profile is only accepted with the explicit review marker and one of the
// three reviewed operations; there is no unreviewed fallback.
#if GS_REVIEWED_ACTION_PROFILE
#if !defined(HR_ACTION_PROFILE_REVIEWED)
#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION_PROFILE_REVIEWED defined as 1"
#elif HR_ACTION_PROFILE_REVIEWED != 1
#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION_PROFILE_REVIEWED == 1"
#endif
#if HR_ACTION < 1 || HR_ACTION > 3
#error "GS_REVIEWED_ACTION_PROFILE requires HR_ACTION in 1..3"
#endif
#endif

static int Fail(const char* stage, DWORD error = GetLastError()) {
    std::printf("{\"ok\":false,\"stage\":\"%s\",\"win32\":%lu,\"selfTestOnly\":%s}\n", stage, error, HR_SELFTEST_ONLY ? "true" : "false");
    return 1;
}
static bool ElevatedHigh() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) return false;
    TOKEN_ELEVATION elevation{};
    DWORD needed = 0;
    bool high = false;
    if (GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &needed) && elevation.TokenIsElevated) {
        GetTokenInformation(token, TokenIntegrityLevel, nullptr, 0, &needed);
        std::vector<BYTE> data(needed);
        if (needed && GetTokenInformation(token, TokenIntegrityLevel, data.data(), needed, &needed)) {
            const auto label = reinterpret_cast<const TOKEN_MANDATORY_LABEL*>(data.data());
            const DWORD count = *GetSidSubAuthorityCount(label->Label.Sid);
            high = count && *GetSidSubAuthority(label->Label.Sid, count - 1) >= SECURITY_MANDATORY_HIGH_RID;
        }
    }
    CloseHandle(token);
    return high;
}

int wmain(int argc, wchar_t**) {
    if (argc != 1) return Fail("NO_RUNTIME_TARGET_ARGUMENTS", ERROR_INVALID_PARAMETER);
    if (GetTickCount64() > HR_DEADLINE) return Fail("PROFILE_DEADLINE", ERROR_TIMEOUT);
    const bool elevated = ElevatedHigh();
    if (!elevated && !HR_SELFTEST_ONLY) return Fail("ELEVATED_HIGH_TOKEN_REQUIRED", ERROR_ACCESS_DENIED);
    if (HR_SELFTEST_ONLY) {
        const wchar_t* leaf = wcsrchr(HR_TARGET_IMAGE, L'\\');
        if (!leaf || wcscmp(leaf + 1, L"hook_receipt_host.exe") != 0) return Fail("SELFTEST_HOST_REQUIRED", ERROR_INVALID_NAME);
    }
    HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, HR_TARGET_PID);
    if (!process) return Fail("TARGET_QUERY");
    wchar_t image[32768]{};
    DWORD chars = static_cast<DWORD>(sizeof(image) / sizeof(image[0]));
    FILETIME creation{}, exit{}, kernel{}, user{};
    BOOL wow64 = TRUE;
    const bool queried = QueryFullProcessImageNameW(process, 0, image, &chars) &&
        GetProcessTimes(process, &creation, &exit, &kernel, &user) && IsWow64Process(process, &wow64);
    const DWORD queryError = GetLastError();
    CloseHandle(process);
    const std::uint64_t ticks = (static_cast<std::uint64_t>(creation.dwHighDateTime) << 32) | creation.dwLowDateTime;
    if (!queried) return Fail("TARGET_IDENTITY_QUERY", queryError);
    if (_wcsicmp(image, HR_TARGET_IMAGE) != 0 || ticks != HR_TARGET_CREATION || wow64) return Fail("TARGET_IDENTITY_MISMATCH", ERROR_INVALID_DATA);
#if defined(HR_TARGET_THREAD_CREATION)
    // GetThreadTimes needs THREAD_QUERY_INFORMATION on top of the right the owner check
    // uses; if the wider open is refused this fails closed at THREAD_QUERY, never by
    // skipping the identity check.
    const DWORD threadAccess = THREAD_QUERY_LIMITED_INFORMATION | THREAD_QUERY_INFORMATION;
#else
    const DWORD threadAccess = THREAD_QUERY_LIMITED_INFORMATION;
#endif
    HANDLE thread = OpenThread(threadAccess, FALSE, HR_TARGET_TID);
    if (!thread) return Fail("THREAD_QUERY");
    const DWORD ownerPid = GetProcessIdOfThread(thread);
#if defined(HR_TARGET_THREAD_CREATION)
    // The thread creation time is part of the fixed target identity: a recycled TID whose
    // thread started later must not receive the hook, even inside the right process.
    FILETIME threadCreation{}, threadExit{}, threadKernel{}, threadUser{};
    const bool threadTimesQueried = GetThreadTimes(thread, &threadCreation, &threadExit, &threadKernel, &threadUser) != FALSE;
    const DWORD threadTimesError = GetLastError();
    const std::uint64_t threadTicks = (static_cast<std::uint64_t>(threadCreation.dwHighDateTime) << 32) | threadCreation.dwLowDateTime;
#endif
    CloseHandle(thread);
    if (ownerPid != HR_TARGET_PID) return Fail("THREAD_OWNER_MISMATCH", ERROR_INVALID_DATA);
#if defined(HR_TARGET_THREAD_CREATION)
    if (!threadTimesQueried) return Fail("THREAD_IDENTITY_QUERY", threadTimesError);
    if (threadTicks != HR_TARGET_THREAD_CREATION) return Fail("THREAD_IDENTITY_MISMATCH", ERROR_INVALID_DATA);
#endif
    HANDLE attempt = CreateFileW(HR_ATTEMPT_FILE, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (attempt == INVALID_HANDLE_VALUE) return Fail("ATTEMPT_ALREADY_USED_OR_UNAVAILABLE");
    CloseHandle(attempt);
    HANDLE mapping = CreateFileMappingW(INVALID_HANDLE_VALUE, nullptr, PAGE_READWRITE, 0, sizeof(Receipt), HR_MAPPING);
    if (!mapping) return Fail("MAPPING_CREATE");
    if (GetLastError() == ERROR_ALREADY_EXISTS) { CloseHandle(mapping); return Fail("MAPPING_ALREADY_EXISTS", ERROR_ALREADY_EXISTS); }
    Receipt* receipt = static_cast<Receipt*>(MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(Receipt)));
    if (!receipt) { CloseHandle(mapping); return Fail("MAPPING_VIEW"); }
    // Zero the mapped object in place. Aggregate assignment can materialize two
    // full Receipt temporaries in wmain: v2 actions then exceed the executable's
    // 1 MiB stack reserve before even the first argument/deadline guard executes.
    std::memset(receipt, 0, sizeof(*receipt));
    receipt->magic = 0x31524847; receipt->version = kReceiptVersion;
    receipt->nonce = HR_NONCE; receipt->deadline = HR_DEADLINE;
    receipt->expectedPid = HR_TARGET_PID; receipt->expectedTid = HR_TARGET_TID;
    HMODULE module = LoadLibraryExW(HR_DLL_PATH, nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    HHOOK hook = nullptr;
    int result = 1;
    if (!module) Fail("LOCAL_RECEIPT_DLL_LOAD");
    else {
        const FARPROC address = GetProcAddress(module, "ReceiptHook");
        HOOKPROC callback = nullptr;
        static_assert(sizeof(callback) == sizeof(address), "Windows procedure pointer ABI");
        std::memcpy(&callback, &address, sizeof(callback));
        if (!callback) Fail("RECEIPT_EXPORT");
        else if (!(hook = SetWindowsHookExW(WH_GETMESSAGE, callback, module, HR_TARGET_TID))) Fail("SET_THREAD_HOOK");
        else {
            const ULONGLONG waitDeadline = GetTickCount64() + (HR_ACTION ? 60000 : 10000);
            const bool posted = PostThreadMessageW(HR_TARGET_TID, HR_MESSAGE_ID, HR_NONCE, 1) != FALSE;
            const DWORD postError = GetLastError();
            while (posted && InterlockedCompareExchange(&receipt->claim, 0, 0) != 2 && GetTickCount64() < waitDeadline && GetTickCount64() <= HR_DEADLINE) Sleep(10);
            const bool received = receipt->claim == 2 && static_cast<DWORD>(receipt->pid) == HR_TARGET_PID && static_cast<DWORD>(receipt->tid) == HR_TARGET_TID;
            const bool unhooked = UnhookWindowsHookEx(hook) != FALSE;
            const DWORD unhookError = GetLastError();
            if (unhooked) hook = nullptr;
            const ULONGLONG drainDeadline = GetTickCount64() + 3000;
            while (unhooked && InterlockedCompareExchange(&receipt->active, 0, 0) != 0 && GetTickCount64() < drainDeadline) Sleep(10);
            const bool drained = unhooked && InterlockedCompareExchange(&receipt->active, 0, 0) == 0;
            bool continued = !HR_SELFTEST_ONLY;
            if (drained && HR_SELFTEST_ONLY && posted) {
                const bool again = PostThreadMessageW(HR_TARGET_TID, HR_MESSAGE_ID, HR_NONCE, 1) != FALSE;
                const bool ping = PostThreadMessageW(HR_TARGET_TID, HR_MESSAGE_ID, HR_NONCE, 2) != FALSE;
                const ULONGLONG pingDeadline = GetTickCount64() + 3000;
                while (again && ping && receipt->hostPings == 0 && GetTickCount64() < pingDeadline) Sleep(10);
                continued = receipt->hostPings == 1 && static_cast<DWORD>(receipt->hostPid) == HR_TARGET_PID && static_cast<DWORD>(receipt->hostTid) == HR_TARGET_TID && receipt->active == 0;
            }
            if (!posted) Fail("POST_RECEIPT_MESSAGE", postError);
            else if (!unhooked) Fail("UNHOOK_FAILED", unhookError);
            else if (!drained) Fail("RECEIPT_CALLBACK_DRAIN_TIMEOUT", ERROR_TIMEOUT);
            else if (!received) Fail("RECEIPT_TIMEOUT_OR_IDENTITY", ERROR_TIMEOUT);
            else if (!continued || receipt->callbacks != 1) Fail("POST_UNHOOK_HOST_CHECK", ERROR_INVALID_DATA);
            else {
#if HR_READ_CONTEXT && GS_STRICT_PROFILE
                // Transport and business state are reported separately. The hook ran, the
                // thread was unhooked and the callback drained -- that part is transport and
                // is still true -- but "ok" is only true when the snapshot reached GS_OK
                // and, for an action, when the action completed with a GS_OK post snapshot.
                bool reportedOk = receipt->context.status == GS_OK;
#if HR_READ_LEVEL_CATALOG
                reportedOk = reportedOk && receipt->catalog.status==0 && receipt->catalog.flags==31;
#endif
#if HR_READ_LIFECYCLE_TYPE
                reportedOk = reportedOk && receipt->lifecycleType.status==0 && receipt->lifecycleType.flags==kLifecycleTypeRequiredFlags;
#endif
#if HR_READ_SCHEDULER_COROUTINES
                reportedOk = reportedOk && receipt->schedulerCoroutines.status==0 && receipt->schedulerCoroutines.flags==kSchedulerCoroutinesRequiredFlags;
#endif
#if HR_READ_REOPEN_GUARDS
                reportedOk = reportedOk && receipt->reopenGuards.status==guarddraft::OK && receipt->reopenGuards.flags==15 &&
                    (receipt->reopenGuards.confirmation==guarddraft::FALSE_VALUE || receipt->reopenGuards.confirmation==guarddraft::TRUE_VALUE) && receipt->reopenGuards.earlyAbort==guarddraft::FALSE_VALUE;
#endif
#if HR_ACTION
                reportedOk = reportedOk && receipt->action.status == 0 && receipt->action.called == 1 &&
                    receipt->action.after.status == GS_OK;
#endif
#else
                const bool reportedOk = true;
#endif
                std::printf("{\"ok\":%s,\"scope\":\"%s\",\"selfTestOnly\":%s,\"probeElevatedHigh\":%s,\"pid\":%ld,\"tid\":%ld,\"callbackCount\":%ld,\"activeCallbacks\":%ld,\"unhooked\":true,\"hostPostUnhookPings\":%ld",
                    reportedOk ? "true" : "false",
                    HR_ACTION ? "FIXED_SCENE_ACTION" : HR_READ_CONTEXT ? "READ_ONLY_CONTEXT_RECEIPT" : "IDENTITY_RECEIPT_ONLY",
                    HR_SELFTEST_ONLY ? "true" : "false", elevated ? "true" : "false", receipt->pid, receipt->tid, receipt->callbacks, receipt->active, receipt->hostPings);
                std::printf(",\"receiptNonce\":\"%llu\",\"receiptDeadline\":\"%llu\",\"receiptProtocol\":%u",
                    static_cast<unsigned long long>(receipt->nonce), static_cast<unsigned long long>(receipt->deadline), static_cast<unsigned int>(receipt->version));
#if HR_READ_CONTEXT
                std::printf(",\"snapshotBytes\":%zu,\"snapshotHex\":\"", sizeof(receipt->context));
                const auto bytes = reinterpret_cast<const unsigned char*>(&receipt->context);
                for (std::size_t i = 0; i < sizeof(receipt->context); ++i) std::printf("%02x", static_cast<unsigned int>(bytes[i]));
                std::printf("\"");
#if GS_STRICT_PROFILE
                // Transport succeeded even when the snapshot or the action did not;
                // snapshotHex above is emitted either way, so a refusal still decodes and
                // can be diagnosed.
                std::printf(",\"transportOk\":true,\"snapshotStatus\":%u", receipt->context.status);
#endif
#endif
#if HR_READ_LEVEL_CATALOG
                std::printf(",\"catalogStatus\":%u,\"catalogBytes\":%zu,\"catalogHex\":\"",receipt->catalog.status,sizeof(receipt->catalog));
                const auto catalogBytes=reinterpret_cast<const unsigned char*>(&receipt->catalog);
                for(std::size_t i=0;i<sizeof(receipt->catalog);++i)std::printf("%02x",static_cast<unsigned int>(catalogBytes[i]));
                std::printf("\"");
#endif
#if HR_READ_LIFECYCLE_TYPE
                std::printf(",\"lifecycleTypeStatus\":%u,\"lifecycleTypeBytes\":%zu,\"lifecycleTypeHex\":\"",receipt->lifecycleType.status,sizeof(receipt->lifecycleType));
                const auto lifecycleBytes=reinterpret_cast<const unsigned char*>(&receipt->lifecycleType);
                for(std::size_t i=0;i<sizeof(receipt->lifecycleType);++i)std::printf("%02x",static_cast<unsigned int>(lifecycleBytes[i]));
                std::printf("\"");
#endif
#if HR_READ_SCHEDULER_COROUTINES
                std::printf(",\"schedulerCoroutinesStatus\":%u,\"schedulerCoroutinesBytes\":%zu,\"schedulerCoroutinesHex\":\"",receipt->schedulerCoroutines.status,sizeof(receipt->schedulerCoroutines));
                const auto schedulerBytes=reinterpret_cast<const unsigned char*>(&receipt->schedulerCoroutines);
                for(std::size_t i=0;i<sizeof(receipt->schedulerCoroutines);++i)std::printf("%02x",static_cast<unsigned int>(schedulerBytes[i]));
                std::printf("\"");
#endif
#if HR_READ_REOPEN_GUARDS
                std::printf(",\"reopenGuardsStatus\":%u,\"reopenGuardsBytes\":%zu,\"reopenGuardsHex\":\"",receipt->reopenGuards.status,sizeof(receipt->reopenGuards));
                const auto guardBytes=reinterpret_cast<const unsigned char*>(&receipt->reopenGuards);
                for(std::size_t i=0;i<sizeof(receipt->reopenGuards);++i)std::printf("%02x",static_cast<unsigned int>(guardBytes[i]));
                std::printf("\"");
#endif
#if HR_ACTION
                std::printf(",\"action\":{\"kind\":%u,\"status\":%u,\"levelId\":%u,\"expectedLevelId\":%u,\"called\":%u,\"entityId\":%u,\"owner\":\"0x%llx\",\"nativeSaveStatus\":%d,\"callCode\":%u,\"placedCount\":%u,\"placedIds\":[",
                    receipt->action.action, receipt->action.status, receipt->action.levelId, receipt->action.expectedLevelId,
                    receipt->action.called, receipt->action.entityId, static_cast<unsigned long long>(receipt->action.owner),
                    receipt->action.saveStatus, receipt->action.callCode, receipt->action.placedCount);
                // In request order, so the caller can map an id back to the spec that made
                // it. Empty for single-placement actions, which report entityId instead.
                for (std::uint32_t i = 0; i < receipt->action.placedCount && i < kMaxBatch; ++i)
                    std::printf("%s%u", i ? "," : "", receipt->action.placedId[i]);
                std::printf("]},\"afterSnapshotHex\":\"");
                const auto afterBytes = reinterpret_cast<const unsigned char*>(&receipt->action.after);
                for (std::size_t i = 0; i < sizeof(receipt->action.after); ++i) std::printf("%02x", static_cast<unsigned int>(afterBytes[i]));
                std::printf("\"");
#endif
                std::printf("}\n");
#if HR_READ_CONTEXT && GS_STRICT_PROFILE
                // Nonzero exit when the snapshot or the reviewed action did not reach its
                // success state; the JSON above still carries the hex, so the caller can
                // decode the refusal instead of guessing.
                result = reportedOk ? 0 : 1;
#else
                result = 0;
#endif
            }
        }
    }
    if (hook) {
        if (!UnhookWindowsHookEx(hook)) {
            Fail("CLEANUP_UNHOOK_FAILED");
            // Keep the local module reference through process exit, rather than
            // unloading it while an unsuccessfully removed hook may use it.
            module = nullptr;
        }
    }
    if (module) FreeLibrary(module);
    UnmapViewOfFile(receipt);
    CloseHandle(mapping);
    return result;
}
