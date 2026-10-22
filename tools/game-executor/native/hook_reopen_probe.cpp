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

#include "hook_reopen_protocol.h"
static_assert(HR_SELFTEST_ONLY==0,"dedicated action probe cannot replay host self-tests");
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
#if HR_ACTION != 4 || HR_REOPEN_ACTION_REVIEWED != 1
#error "GS_REVIEWED_ACTION_PROFILE requires reviewed HR_ACTION 4"
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
    *receipt = {};
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
            // Keep the same mapping, nonce and hook for bounded read-only follow-up.
            // The action claim remains 2; observations have their own sequence/counters.
            if(received){
                using namespace ge::observation;
                auto& e=receipt->observation;auto& h=e.header;Initialize(e,receipt->reopen,GetTickCount64());
                ULONGLONG next=GetTickCount64();
                while(InterlockedCompareExchange(&h.status,0,0)==OBSERVING){
                    const auto now=GetTickCount64();
                    if(now>HR_DEADLINE){InterlockedCompareExchange(&h.status,DEADLINE_UNKNOWN,OBSERVING);break;}
                    if(now-h.startTick>=maxDurationMs){InterlockedCompareExchange(&h.status,TIMEOUT_UNKNOWN,OBSERVING);break;}
                    const LONG requested=InterlockedCompareExchange(&h.requested,0,0),completed=InterlockedCompareExchange(&h.completed,0,0);
                    if(requested==completed&&InterlockedCompareExchange(&e.reading,0,0)==0){
                        if(requested>=static_cast<LONG>(maxSamples)){InterlockedCompareExchange(&h.status,LIMIT_UNKNOWN,OBSERVING);break;}
                        if(now>=next&&InterlockedCompareExchange(&h.status,0,0)==OBSERVING){
                            const LONG sequence=InterlockedIncrement(&h.requested);next=now+intervalMs;
                            if(!PostThreadMessageW(HR_TARGET_TID,HR_MESSAGE_ID,HR_NONCE,messageBase+sequence)){
                                InterlockedCompareExchange(&h.status,POST_FAILED_UNKNOWN,OBSERVING);break;
                            }
                        }
                    }
                    Sleep(1); // probe process only; the game callback never sleeps.
                }
            }
            const bool unhooked = UnhookWindowsHookEx(hook) != FALSE;
            const DWORD unhookError = GetLastError();
            if (unhooked) hook = nullptr;
            const ULONGLONG drainDeadline = GetTickCount64() + 3000;
            while (unhooked && InterlockedCompareExchange(&receipt->active, 0, 0) != 0 && GetTickCount64() < drainDeadline) Sleep(10);
            const bool drained = unhooked && InterlockedCompareExchange(&receipt->active, 0, 0) == 0;
            if(drained&&received&&receipt->observation.header.status!=ge::observation::FOLLOWUP_STAGE_PROVEN&&receipt->observation.header.status!=ge::observation::INITIAL_STAGE_PROVEN)receipt->observation.header.endTick=GetTickCount64();
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
                const auto& b=receipt->reopen;const auto& a=b.action;
                const bool returned=a.status==ge::reopen::RETURNED_PENDING&&a.call.nativeCallAttempted==1&&a.call.nativeCallReturned==1&&a.call.businessPending==1;
                // A returned asynchronous call is never a business-success receipt.
                std::printf("{\"ok\":false,\"transportOk\":true,\"scope\":\"REVIEWED_REOPEN_ACTION\",\"pid\":%ld,\"tid\":%ld,\"callbackCount\":%ld,\"activeCallbacks\":%ld,\"unhooked\":true,\"businessPending\":%s,\"reopenVerified\":false,\"persistenceVerified\":false,\"callReturned\":%s",receipt->pid,receipt->tid,receipt->callbacks,receipt->active,a.call.businessPending?"true":"false",returned?"true":"false");
                auto emit=[](const char* name,const void* p,std::size_t size,std::uint32_t status){
                    std::printf(",\"%sStatus\":%u,\"%sBytes\":%zu,\"%sHex\":\"",name,status,name,size,name);
                    const auto bytes=static_cast<const unsigned char*>(p);for(std::size_t i=0;i<size;++i)std::printf("%02x",static_cast<unsigned int>(bytes[i]));std::printf("\"");};
                emit("snapshot",&b.context,sizeof(b.context),b.context.status);
                emit("catalog",&b.catalog,sizeof(b.catalog),b.catalog.status);
                emit("lifecycleType",&b.type,sizeof(b.type),b.type.status);
                emit("schedulerCoroutines",&b.scheduler,sizeof(b.scheduler),b.scheduler.status);
                emit("reopenGuards",&b.guards,sizeof(b.guards),b.guards.status);
                emit("postSchedulerCoroutines",&b.postScheduler,sizeof(b.postScheduler),b.postScheduler.status);
                const auto& observe=receipt->observation;
                emit("reopenObservation",&observe.header,sizeof(observe.header),static_cast<std::uint32_t>(observe.header.status));
                emit("followupSchedulerCoroutines",&observe.proof,sizeof(observe.proof),observe.proof.status);
                emit("lastObservationSchedulerCoroutines",&observe.last,sizeof(observe.last),observe.last.status);
                emit("reopenAction",&a,sizeof(a),a.status);std::printf("}\n");
                result=returned?0:1; // process exit reports only dispatch; JSON business ok remains false.
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
