#pragma once
#include "template_catalog_capture.h"
#include <cstdint>

namespace ge::component_attachment {
constexpr std::uint32_t kMaxComponents = 256;
using AttachComponent = void* (__cdecl *)(void* owner, std::int32_t kind); // 867c610
using ReadSource = ge::templates::TemplateReadSource;
enum class CaptureCode : std::uint32_t { complete, invalid_input, unreadable, invalid_structure, limit_exceeded, unstable, set_list_disagree };
struct ComponentRow {
    std::uint64_t wrapper, wrapper_class, config, config_class;
    std::int32_t kind;
    std::uint8_t enabled, reserved[3];
};
struct ComponentSnapshot {
    CaptureCode code;
    std::uint32_t bytes_read, read_calls, count, set_count;
    std::uint64_t owner, owner_class, set, list, buckets, slots, items;
    std::uint32_t set_capacity, list_capacity, set_last_index, set_version, list_version;
    std::int32_t set_free_head;
    std::uint8_t owner_state, reserved[7];
    std::int32_t kinds[kMaxComponents];
    ComponentRow rows[kMaxComponents];
};
struct NativeSetSlot { std::int32_t hash, next, value; };
static_assert(sizeof(NativeSetSlot) == 12, "Current HashSet<int> slot layout");
struct CaptureWorkspace {
    unsigned char set_header[0x38], list_header[0x20];
    std::int32_t buckets[kMaxComponents];
    NativeSetSlot slots[kMaxComponents];
    std::uint64_t items[kMaxComponents];
    bool seen[kMaxComponents];
    unsigned char compare[kMaxComponents * sizeof(NativeSetSlot)];
};
// Reads the SET and LIST independently, including all allocated array capacity,
// checks the complete kind sets match, and rechecks identities and structures.
// No game getter, Contains, allocation, write or initialization is used.
void CaptureComponents(ReadSource, std::uint64_t owner, CaptureWorkspace*, ComponentSnapshot*) noexcept;
struct AttachmentEvidence {
    std::uint64_t owner, owner_class, wrapper_class, config_class;
    std::int32_t kind; // Native option cards 17, bag 33 or shop 35.
    // Adapter-owned: current build/hotfix, game thread, and exact owned entity.
    bool owner_and_thread_verified;
};
enum class AttachCode : std::uint32_t {
    existing, attached_verified, invalid_evidence, missing_binding, before_failed,
    identity_mismatch, after_failed, context_changed, null_return,
    delta_mismatch, call_exception, capture_limit
};
struct AttachmentResult {
    AttachCode code;
    ComponentRow component;
    std::uint64_t returned_wrapper;
    bool attach_called, before_verified, after_verified, outcome_uncertain;
};
struct AttachmentWorkspace {
    CaptureWorkspace capture;
    ComponentSnapshot before, after;
};
// Reuse an already consistent component, otherwise call attach exactly once.
// Any attempted call stays uncertain until later binding/export/save/play checks.
// C++ exceptions are recorded; hardware SEH remains the native adapter's job.
void EnsureComponentAttached(ReadSource, AttachComponent, const AttachmentEvidence&,
    AttachmentWorkspace*, AttachmentResult*) noexcept;
}
