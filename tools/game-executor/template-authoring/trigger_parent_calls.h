#pragma once
#include <cstddef>
#include <cstdint>

// Creates one native kind5 parent with native defaults. Does not establish
// server event92 semantics, assign filter values, create a controller, open an
// edit transaction, notify an owner, close/save, resolve addresses or connect.
namespace ge::trigger_parent {
constexpr std::uint32_t controller_definition = 72636;
constexpr std::uint32_t config_definition = 81346;
constexpr std::uint32_t entry_definition = 71314;
constexpr std::uint32_t region_definition = 40001;
// Local receipt bounds only. The actual native limit is checked by canAdd.
constexpr std::size_t parent_capacity = 64, region_capacity = 32, filter_capacity = 32;
using CanAdd = bool (__cdecl *)(void*, const void*); // 9c494b0(controller,name)
using Add = void (__cdecl *)(void*, const void*);    // 9c464b0(controller,name)
struct NativeCalls { CanAdd canAdd = nullptr; Add add = nullptr; };
struct Region {
    void* object = nullptr;
    std::uint32_t definition = 0, index = 0, shape = 0;
};
struct Entry {
    void* object = nullptr;
    void* name = nullptr;
    std::uint32_t definition = 0, index = 0;
    std::uint8_t active = 0, editorEnabled = 0;
    std::uint32_t selectedCount = 0, complementCount = 0, regionCount = 0;
    std::int32_t selected[filter_capacity] = {}, complement[filter_capacity] = {};
    Region regions[region_capacity] = {};
};
struct Snapshot {
    void* collection = nullptr;
    std::uint32_t count = 0;
    Entry rows[parent_capacity] = {};
};
struct Evidence;
// Fresh read-only host check, before both gate and add. It must verify:
// current code/hotfix/thread; exact managed ClientBeyondEntityClientTriggerEditData;
// controller class72636, +18=config81346, +28=real property descriptor whose
// +38 is clientTriggerDataList, config+30=collection; controller+20=propertyWrapper
// related to this editObject/owner/config; active snapshot transaction for this
// same editObject. Reject if propertyWrapper+48 is assignable to class27029
// (9c464b0's alternate baa8290 operation). Do not fabricate a controller/descriptor.
// The whole native add retains propertyWrapper class37247's 330/338 hooks.
using VerifyContext = bool (*)(void*, const Evidence&);
// Read actual list order, exact entry/region classes, and all reported fields.
// Reject unreadable/unstable/oversized lists; never truncate or normalize values.
// Parent index+40, active+45, editorEnabled+46, name+30, selected+28,
// complement+18, regions+38. Region index+58 and shape+5c may include zero;
// no Avatar/filter semantics or default region index is assumed here.
using Capture = bool (*)(void*, void*, Snapshot*);
struct Evidence {
    void* controller = nullptr;
    void* owner = nullptr;
    void* editObject = nullptr;
    void* config = nullptr;
    void* propertyWrapper = nullptr;
    void* propertyDescriptor = nullptr;
    void* collection = nullptr;
    void* transactionToken = nullptr;
    const void* managedTypeName = nullptr;
    bool currentCodeAndThreadVerified = false;
    bool transactionSnapshotVerified = false;
    void* context = nullptr;
    VerifyContext verifyContext = nullptr;
    Capture capture = nullptr;
};
enum class Code : std::uint32_t {
    invalid_evidence, missing_calls, invalid_context, read_failed, receipt_capacity,
    at_native_limit, context_changed, created_pending_notification,
    unexpected_change, call_exception, duplicate_attempt
};
enum class Stage : std::uint32_t { none, context, before_capture, limit, recheck, add, after_capture };
struct Result {
    Code code = Code::invalid_evidence;
    Stage stage = Stage::none;
    Snapshot before, after;
    void* entry = nullptr;
    std::uint32_t index = 0;
    bool attemptStarted = false, limitCalled = false, addCalled = false;
    bool mutationCalled = false, outcomeUncertain = false, structureVerified = false;
    bool needsOwnerNotification = false, needsTransactionClose = false;
    bool event92Proven = false, characterFilterProven = false;
};
// One native add, caller-owned flags before its call, no retries/rollback/raw
// writes. Result must start default-initialized and cannot be reused for retry.
// A host SEH boundary must preserve this Result if native code faults.
void create_default_into(const NativeCalls&, const Evidence&, Result*);
}
