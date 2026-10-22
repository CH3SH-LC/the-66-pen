#pragma once
#include "trigger_calls.h"
#include <cstddef>

// Adds a region to an EXISTING verified ClientTrigger entry (definition 71314).
// No parent trigger creation, event 92 binding, target filtering, transaction
// opening/closing, owner notification, address resolution, or game connection.
namespace ge::trigger_region_add {
constexpr std::size_t capture_capacity = 256; // Local readback bound, not native limit.
constexpr std::uint32_t index_hash = 0x090aa9ab;
using Factory = void* (__cdecl *)(const void*);                   // 95f6410
using GetList = void* (__cdecl *)(void*, const void*);            // 110e5230
using NumberRegion = void (__cdecl *)(void*, void*, const void*);// 104dc950
using Count = std::int32_t (__cdecl *)(void*, const void*);
using Append = void (__cdecl *)(void*, void*, const void*);
struct Calls {
    Factory factory = nullptr;
    GetList getList = nullptr;
    NumberRegion number = nullptr;
    trigger_region::GetUInt getIndex = nullptr; // 12ce17f0
    // Exact collection interface class slot 57d0150, slots 0 and 2.
    // Host resolves both real function pointers AND their hidden MethodInfo.
    Count count = nullptr;
    const void* countMethodInfo = nullptr;
    Append append = nullptr;
    const void* appendMethodInfo = nullptr;
    trigger_region::NativeCalls geometry;
};
struct Row { void* region = nullptr; std::uint32_t index = 0; };
// Reads actual collection order/pointers and each native region index. Rejects
// unreadable or unexpected region classes; no normalization or fabricated rows.
using Capture = bool (*)(void*, void*, Row*, std::size_t, std::uint32_t*);
struct Evidence {
    void* editObject = nullptr;
    void* parentEntry = nullptr;
    void* collection = nullptr;
    // Verified active BA snapshot transaction for this SAME editObject.
    void* transactionToken = nullptr;
    bool transactionSnapshotVerified = false;
    bool currentParentAndBuildVerified = false;
    const void* managedRegionName = nullptr; // ClientBaseBeyondColliderEditData
    const void* managedListName = nullptr;   // colliderList
    bool exactManagedLiteralsVerified = false;
    std::uint32_t nativeLimit = 0; // Actual initialized value at RVA 57887ec.
    bool nativeLimitVerified = false;
    void* context = nullptr;
    Capture capture = nullptr;
    trigger_region::VerifyObject verifyObject = nullptr;
};
enum class Code : std::uint32_t {
    added_pending_notification, invalid_evidence, missing_binding, invalid_values,
    collection_mismatch, readback_failed, at_limit, factory_null,
    unexpected_region, invalid_index, append_mismatch, geometry_failed,
    call_exception
};
enum class Stage : std::uint32_t {
    none, before_capture, factory, number, index, append, appended_capture,
    geometry, final_capture
};
struct Result {
    Code code = Code::invalid_evidence;
    Stage exceptionStage = Stage::none;
    void* region = nullptr;
    std::uint32_t index = 0, beforeCount = 0, afterCount = 0;
    Row before[capture_capacity] = {}, after[capture_capacity] = {};
    trigger_region::Result geometry;
    bool factoryCalled = false, numberingCalled = false, appendCalled = false;
    bool mutationCalled = false, outcomeUncertain = false;
    bool membershipVerified = false, geometryVerified = false;
    bool needsOwnerNotification = false, needsTransactionClose = false;
};
// Caller owns all progress before calls, including faults handled by outer SEH.
// No retry, rollback, raw object/list writes, or notification-complete claim.
void add_box_into(const Calls&, const Evidence&, const trigger_region::BoxValues&, Result*);
}
