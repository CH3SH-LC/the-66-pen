#pragma once
#include <cstdint>
namespace ge::scene {
// Internal ABI/exception adapter only. It does not validate a version, review,
// current runtime evidence or a target RVA and is never an exposed request route.
// Its caller must perform all those checks and own the single-attempt claim.
using ReopenCurrent = void (__cdecl *)(void* levelManager, void* record, void* callback);
enum class ReopenCallCode : std::uint32_t { missing_binding=1, returned=2, exception=3 };
struct ReopenCallResult {
 std::uint32_t size,version;
 ReopenCallCode code;
 std::uint32_t nativeCallAttempted,nativeCallReturned,exceptionCode,businessPending;
 std::uint32_t reopenVerified,persistenceVerified;
};
static_assert(sizeof(ReopenCallResult)==36,"reopen call POD");
// No optional callback, secondary entry, retry or fallback is accepted.
ReopenCallResult dispatch_reopen(ReopenCurrent,void* levelManager,void* record) noexcept;
}