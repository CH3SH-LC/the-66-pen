#pragma once
#include <windows.h>
#include <cstdint>
#include <cstddef>
#ifndef HR_READ_CONTEXT
#define HR_READ_CONTEXT 0
#endif
#ifndef HR_ACTION
#define HR_ACTION 0
#endif
#if HR_READ_CONTEXT
#include "game_context_snapshot.h"
#endif
#ifndef HR_READ_LEVEL_CATALOG
#define HR_READ_LEVEL_CATALOG 0
#endif
#if HR_READ_LEVEL_CATALOG
#include "game_level_catalog.h"
static_assert(HR_READ_CONTEXT==1 && HR_ACTION==0 && GS_BOOTSTRAP_READONLY==1,"readonly catalog only");
#endif
#ifndef HR_READ_LIFECYCLE_TYPE
#define HR_READ_LIFECYCLE_TYPE 0
#endif
#if HR_READ_LIFECYCLE_TYPE
#include "game_lifecycle_type.h"
static_assert(HR_READ_CONTEXT==1 && HR_ACTION==0 && GS_BOOTSTRAP_READONLY==1,"readonly lifecycle type only");
#endif
#ifndef HR_READ_SCHEDULER_COROUTINES
#define HR_READ_SCHEDULER_COROUTINES 0
#endif
#if HR_READ_SCHEDULER_COROUTINES
#include "game_scheduler_coroutines.h"
static_assert(HR_READ_CONTEXT==1 && HR_READ_LIFECYCLE_TYPE==1 && HR_ACTION==0 && GS_BOOTSTRAP_READONLY==1,"readonly scheduler requires lifecycle type");
#endif
#ifndef HR_READ_REOPEN_GUARDS
#define HR_READ_REOPEN_GUARDS 0
#endif
#if HR_READ_REOPEN_GUARDS
#include "game_reopen_guards.h"
static_assert(HR_READ_CONTEXT==1 && HR_READ_LEVEL_CATALOG==1 && HR_READ_LIFECYCLE_TYPE==1 && HR_READ_SCHEDULER_COROUTINES==1 && HR_ACTION==0 && GS_BOOTSTRAP_READONLY==1,"readonly reopen guards require all inputs");
#endif
#if HR_ACTION
#include "game_scene_action.h"
static_assert(HR_READ_CONTEXT == 1, "Actions require verified context");
#endif

struct Receipt {
    DWORD magic, version;
    std::uint64_t nonce, deadline;
    DWORD expectedPid, expectedTid;
    volatile LONG claim, pid, tid, callbacks, active, hostPings, hostPid, hostTid;
#if HR_READ_CONTEXT
    GameContextSnapshot context;
#endif
#if HR_READ_LEVEL_CATALOG
    LevelCatalogSnapshot catalog;
#endif
#if HR_READ_LIFECYCLE_TYPE
    LifecycleTypeSnapshot lifecycleType;
#endif
#if HR_READ_SCHEDULER_COROUTINES
    SchedulerCoroutinesSnapshot schedulerCoroutines;
#endif
#if HR_READ_REOPEN_GUARDS
    guarddraft::Result reopenGuards;
#endif
#if HR_ACTION
    GameSceneActionResult action;
#endif
};
static_assert(sizeof(void*) == 8, "x64 receipt ABI");
#if HR_READ_CONTEXT
static_assert(offsetof(Receipt, context) == 64, "receipt prefix ABI");
constexpr DWORD kReceiptVersion = HR_READ_REOPEN_GUARDS ? 8 : HR_READ_SCHEDULER_COROUTINES ? 6 : HR_READ_LIFECYCLE_TYPE ? 5 : HR_READ_LEVEL_CATALOG ? 4 : HR_ACTION ? 3 : 2;
#else
static_assert(sizeof(Receipt) == 64, "receipt ABI");
constexpr DWORD kReceiptVersion = 1;
#endif
