#pragma once
#include "game_reopen_guards.h"
#include "reopen_call.h"
// This is a dedicated action build, never a read-only extension.
#if HR_ACTION != 4 || GS_BOOTSTRAP_READONLY || !GS_REVIEWED_ACTION_PROFILE || HR_ACTION_PROFILE_REVIEWED != 1 || HR_REOPEN_ACTION_REVIEWED != 1
#error "Dedicated reopen requires action 4 and both explicit review markers"
#endif
#if HR_REOPEN_EXPECTED_LEVEL_ID != 1073741840 || HR_REOPEN_ALLOWED_CALLS != 1 || HR_REOPEN_REVIEW_NONCE != HR_NONCE || HR_NONCE == 0
#error "Reopen profile must bind one reviewed invocation to the dedicated current level"
#endif
namespace ge::reopen {
enum Status : std::uint32_t { REFUSED=1, WRONG_IDENTITY=2, REENTRY=3, BAD_ROUTE=4, BAD_FRESH_EVIDENCE=5, CURRENT_CHANGED=6, RETURNED_PENDING=7, EXCEPTION_PENDING=8 };
struct ActionResult {
 std::uint32_t size,version,action,status;
 std::uint64_t invocation,entry,levelManager,record;
 std::uint32_t levelId,preflightAccepted,routeBefore,routeAfter;
 scene::ReopenCallResult call;
 std::uint32_t reserved;
};
static_assert(sizeof(ActionResult)==104,"reopen action POD v1");
struct Snapshot {
 GameContextSnapshot context;LevelCatalogSnapshot catalog;LifecycleTypeSnapshot type;
 SchedulerCoroutinesSnapshot scheduler;guarddraft::Result guards;ActionResult action;
 SchedulerCoroutinesSnapshot postScheduler;
};
// Internal pure validators. They do not confer authorization or establish producer provenance.
bool ValidateFresh(const Snapshot&) noexcept;
bool ValidateRoute(std::uint64_t,guarddraft::ReadBytes,void*) noexcept;
bool ValidateCurrent(const Snapshot&,guarddraft::ReadBytes,void*) noexcept;
}
using ReopenActionSnapshot=ge::reopen::Snapshot;
// The only production entry: obtains its own current-callback snapshots, then calls once.
void ExecuteGameReopenAction(ReopenActionSnapshot*) noexcept;
