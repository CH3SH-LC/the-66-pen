#pragma once
#include "template_catalog_capture.h"

// The native component edit transaction, restricted to bag33/shop35. The host
// must keep current build/hotfix/context/game-thread verification through both
// phases. No direct owner virtual call, history fabrication, retry or rollback.
namespace ge::component_edit {
using OpenTransaction = void* (__cdecl *)(void*, bool, bool); // e827750
using SnapshotComponent = void (__cdecl *)(void*, void*, std::int32_t); // 107abdf0
using NotifyComponent = void (__cdecl *)(void*, void*); // 9c26c70
using CloseTransaction = void (__cdecl *)(void*); // c7bab90
struct NativeCalls { OpenTransaction open; SnapshotComponent snapshot; NotifyComponent notify; CloseTransaction close; };
struct Evidence {
    std::uint64_t moduleBase, global, owner, wrapper, config;
    std::int32_t kind;
    bool codeAndThreadVerified;
};
constexpr std::uint32_t kMaxPendingEdits = 256;
struct EditRecord { std::uint64_t pointer, klass, object, after, before; std::uint8_t dirty; };
enum class ReadCode : std::uint32_t { complete, unreadable, invalid, unstable };
struct EditState {
    ReadCode code;
    std::uint32_t count, version, targetCount;
    std::int32_t baseDepth, depth;
    std::uint8_t flags[3];
    std::uint64_t manager, list, items, recordClass, literal, capacity;
    EditRecord target, records[kMaxPendingEdits];
};
enum class Code : std::uint32_t {
    invalid_evidence, missing_calls, invalid_environment, busy, read_failed,
    ready, opened_without_handle, snapshot_failed, snapshot_ready,
    duplicate_attempt, notify_failed, notification_verified, close_failed, complete, call_exception
};
enum class Stage : std::uint32_t { none, open, snapshot, notify, close };
struct Result {
    Code code;
    Stage stage;
    std::uint64_t transaction;
    bool openCalled, snapshotCalled, notifyCalled, closeCalled;
    bool snapshotVerified, notificationVerified, closeVerified;
    bool transactionMayBeOpen, outcomeUncertain;
    // True even after complete: only native save/export and reopen can prove it.
    bool needsPersistenceAcceptance;
    Evidence evidence;
    EditState before, afterSnapshot, afterNotify, afterClose;
};
void CaptureEditState(ge::templates::TemplateReadSource, const Evidence&, EditState*) noexcept;
// Environment preflight is usable before attachment (wrapper/config may be0).
// Only pending transaction state is checked; undo/redo history is not inspected.
Code CheckComponentEditReady(ge::templates::TemplateReadSource, const Evidence&, EditState*) noexcept;
void BeginComponentEdit(ge::templates::TemplateReadSource, const NativeCalls&, const Evidence&, Result*) noexcept;
// Call only after fields-only setter readback. It includes native dependency
// refresh via wrapper virtual120, then owner notification and real record dirty.
// If any stage is uncertain, no subsequent call/close is attempted automatically.
void CompleteComponentEdit(ge::templates::TemplateReadSource, const NativeCalls&, const Evidence&, Result*) noexcept;
}
