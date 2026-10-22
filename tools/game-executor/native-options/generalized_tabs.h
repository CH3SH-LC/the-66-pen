#pragma once
// Generalized kind-17 option-card installer (action code 13, receipt protocol 18).
//
// This header removes the four hardcodes that made the historical action usable for
// exactly two hosts and three fixed Chinese labels. It is NOT a replacement:
// native_tabs.h/.cpp stay untouched so the historical action (HR_ACTION 12, at its own
// level) remains traceable and reproducible.
//
//   hardcode                                            replaced by
//   native_tabs.cpp:128 the two host ids                 gt::kHosts (GT_HOSTS table)
//   native_tabs.cpp:90-91 the three Chinese labels       gt::kHosts[].options[].text
//   native_tabs.h:17    TabHostResult::options[2]        kMaxOptionsPerHost + optionCount
//   native_tabs.cpp:36  the historical level id          GT_LEVEL_ID (explicit + checked)
//
// The four literal values live in GENERALIZED-TABS.md §1 and in the historical files
// themselves; this header carries none of them on purpose (the offline checker asserts
// that).
//
// The parameter table is baked at compile time by build_generalized.py into
// target_config.h (force-included with /FI), exactly the way build.py bakes
// TAB_CODE_RVAS / TAB_EXPECTED_SNAPSHOT. No address in generalized_tabs.cpp is a
// literal: every one arrives as a GT_* macro from either runtime-profile.json, the
// reviewed spec, or a cited entry in build_generalized.py (see GENERALIZED-TABS.md).
#include "../native/game_context_snapshot.h"
#include "../template-authoring/component_attachment.h"
#include "../template-authoring/owner_notification_calls.h"
#include <cstddef>
#include <cstdint>
#include <type_traits>

#if !defined(GT_HOSTS) || !defined(GT_HOST_COUNT)
#error "GT_HOSTS/GT_HOST_COUNT parameter table required: use tools/game-executor/native-options/build_generalized.py"
#endif

namespace gt {

// ---- receipt capacity -------------------------------------------------------
// The host limit IS the receipt array: hosts[kMaxHosts]. A request that needs more
// hosts is refused with host_limit_exceeded (build phase) and never truncated.
constexpr std::uint32_t kMaxHosts = 4;
// Per-host option cards. native_tabs.h:17 fixed this at 2; here it is a capacity
// with a per-host count. The fresh native component starts with exactly one card
// (native_tabs.cpp:81), further cards are created and appended in table order.
constexpr std::uint32_t kMaxOptionsPerHost = 4;
// Mirrors native_tabs.h TabRow::text[48]; the readback refuses textLength >= this.
constexpr std::uint32_t kMaxTextUnits = 48;
constexpr std::uint32_t kNoIndex = 0xffffffffu;

// Flags every compared snapshot must carry (native_tabs.cpp:36 used the literal
// 1951). GS_LEVEL_OBSERVED is part of the mask: without it `reserved` is not a
// level id at all.
constexpr std::uint32_t kRequiredSnapshotFlags =
    GS_BUILD_VERIFIED | GS_ORIGIN_READ | GS_CONTEXTS_COMPLETE | GS_ENTITIES_COMPLETE |
    GS_STRUCTURE_RECHECKED | GS_STACK_CAPTURED | GS_STACK_VERIFIED |
    GS_HOTFIX_DEFAULT_CONFIRMED | GS_LEVEL_OBSERVED;

// ---- named refusal codes ----------------------------------------------------
// ONE list, three consumers: this enum, the receipt's name table (printed by the
// generated receipt_layout.cpp), build_generalized.py's spec validator and
// verify_generalized_receipt.py. "phase" is where the code is raised first:
//   build   = build_generalized.py refuses to bake the table
//   runtime = generalized_tabs.cpp refuses inside the game process
//   verify  = verify_generalized_receipt.py refuses to certify the receipt
// Every failure path in this deliverable carries one of these names plus the stage
// number it happened at. Nothing reports success by omission.
//
// The last five codes are the snapshot-ABI gate. The snapshot describes itself (its first
// four uint32 are structSize/version/status/flags, game_context_snapshot.h:104) and the
// entity count follows from the byte count through 184 + 32*8 + N*64, the formula owned by
// tools/game-executor/decode_context_snapshot.py. Both reviewed ABIs -- v1 (512 entities,
// 33208 B) and v2 (4096 entities, 262584 B) -- are accepted; a size that is neither, a
// payload that disagrees with its own header, and a payload that is not the ABI the
// translation unit was compiled for are all refused by name. No path truncates or pads.
#define GT_REFUSE_CODES(X) \
    X(none, 0, runtime) \
    X(invalid_parameter_table, 1, runtime) \
    X(entry_guard_failed, 2, runtime) \
    X(module_or_build_mismatch, 3, runtime) \
    X(build_anchor_mismatch, 4, runtime) \
    X(hotfix_active, 5, runtime) \
    X(snapshot_not_ok, 6, runtime) \
    X(snapshot_flags_incomplete, 7, runtime) \
    X(level_not_observed, 8, runtime) \
    X(level_mismatch, 9, runtime) \
    X(expected_scene_mismatch, 10, runtime) \
    X(host_entity_not_unique, 11, runtime) \
    X(owner_unreadable, 12, runtime) \
    X(component_capture_failed, 13, runtime) \
    X(component_already_present, 14, runtime) \
    X(attach_not_verified, 15, runtime) \
    X(component_kind_mismatch, 16, runtime) \
    X(edit_begin_failed, 17, runtime) \
    X(option_list_shape_mismatch, 18, runtime) \
    X(option_list_add_method_mismatch, 19, runtime) \
    X(option_factory_failed, 20, runtime) \
    X(option_class_mismatch, 21, runtime) \
    X(option_text_encode_failed, 22, runtime) \
    X(option_text_alloc_failed, 23, runtime) \
    X(collider_list_shape_mismatch, 24, runtime) \
    X(collider_class_mismatch, 25, runtime) \
    X(collider_shape_mismatch, 26, runtime) \
    X(collider_sphere_missing, 27, runtime) \
    X(radius_mismatch, 28, runtime) \
    X(option_row_unreadable, 29, runtime) \
    X(option_index_mismatch, 30, runtime) \
    X(option_enabled_mismatch, 31, runtime) \
    X(option_text_mismatch, 32, runtime) \
    X(edit_complete_failed, 33, runtime) \
    X(kind_readback_failed, 34, runtime) \
    X(component_kind_readback_mismatch, 35, runtime) \
    X(scene_changed, 36, runtime) \
    X(unhandled_exception, 37, runtime) \
    X(host_limit_exceeded, 38, build) \
    X(option_limit_exceeded, 39, build) \
    X(option_text_too_long, 40, build) \
    X(option_index_invalid, 41, build) \
    X(option_enabled_count_invalid, 42, build) \
    X(level_id_invalid, 43, build) \
    X(level_evidence_required, 44, build) \
    X(spec_not_object, 45, build) \
    X(spec_schema_version, 46, build) \
    X(spec_action_mismatch, 47, build) \
    X(kind_invalid, 48, build) \
    X(kind_unsupported_by_primitive, 49, build) \
    X(kind_not_profiled, 50, build) \
    X(radius_invalid, 51, build) \
    X(radius_not_float32, 52, build) \
    X(hosts_required, 53, build) \
    X(host_not_object, 54, build) \
    X(host_entity_id_invalid, 55, build) \
    X(host_entity_duplicate, 56, build) \
    X(options_required, 57, build) \
    X(option_not_object, 58, build) \
    X(option_index_duplicate, 59, build) \
    X(option_text_required, 60, build) \
    X(option_text_not_chinese, 61, build) \
    X(option_text_not_utf16, 62, build) \
    X(option_enabled_invalid, 63, build) \
    X(layout_incomplete, 64, verify) \
    X(layout_refuse_table_missing, 65, verify) \
    X(receipt_bytes_missing, 66, verify) \
    X(receipt_size_mismatch, 67, verify) \
    X(transport_not_ok, 68, verify) \
    X(business_status_not_ok, 69, verify) \
    X(receipt_refused, 70, verify) \
    X(receipt_summary_disagrees, 71, verify) \
    X(host_count_mismatch, 72, verify) \
    X(spec_host_limit_exceeded, 73, verify) \
    X(host_capacity_mismatch, 74, verify) \
    X(host_entity_mismatch, 75, verify) \
    X(attach_code_not_verified, 76, verify) \
    X(option_count_mismatch, 77, verify) \
    X(spec_radius_mismatch, 78, verify) \
    X(exit_receipt_rejected, 79, verify) \
    X(spec_not_normalizable, 80, verify) \
    X(evidence_output_exists, 81, verify) \
    X(option_text_not_printable, 82, build) \
    X(snapshot_abi_derivation_failed, 83, build) \
    X(snapshot_size_mismatch, 84, build) \
    X(snapshot_abi_unsupported, 85, build) \
    X(scene_size_mismatch, 86, verify) \
    X(scene_abi_mismatch, 87, verify)

enum class RefuseCode : std::uint32_t {
#define GT_REFUSE_ENUM(name, value, phase) name = value,
    GT_REFUSE_CODES(GT_REFUSE_ENUM)
#undef GT_REFUSE_ENUM
};

// Stage numbers, mirroring the historical numbering so a receipt from either action
// reads the same way: 1 entry, 2 build anchors, 3 declared scene (native_tabs had 1
// and 2), 10+i per-host install (kept as stage::host_install + i), 20 after-scene.
namespace stage {
constexpr std::uint32_t entry = 1;
constexpr std::uint32_t build_anchors = 2;
constexpr std::uint32_t scene_declared = 3;
constexpr std::uint32_t host_scan = 4;
constexpr std::uint32_t metadata_bootstrap = 5;
constexpr std::uint32_t host_install = 10;
constexpr std::uint32_t scene_after = 20;
}

// ---- the parameter table ----------------------------------------------------
struct OptionSpec {
    std::int32_t index;        // 1-based card ordinal, written to the card and its index property
    std::uint32_t enabled;     // 1 = the card starts active; exactly one per host
    const char16_t* text;      // the Chinese caption, compared back as UTF-16
};
struct HostSpec {
    std::uint64_t entityId;
    std::uint32_t optionCount;
    OptionSpec options[kMaxOptionsPerHost];
};

inline constexpr HostSpec kHosts[] = GT_HOSTS;
constexpr std::uint32_t kHostCount = static_cast<std::uint32_t>(sizeof(kHosts) / sizeof(kHosts[0]));

// Compile-time validation of the table the builder baked. The same rules are
// enforced in Python (named refusals) and again at runtime; a hand-edited table
// stops the build here instead of writing a wrong card into a live scene.
//
// The table is a constexpr array, so MSVC reports C4127 ("conditional expression is
// constant") on every branch of these checks -- including the ones reached from the
// static_assert below -- and /W4 /WX turns that into error C2220. The branches are
// deliberate: generalized_tabs.cpp calls this same function again at runtime. The
// suppression is scoped to this function (push/pop) and to this warning only; it was
// found by the kind17 dual-ABI self-check, the first build that actually compiles this
// header.
#pragma warning(push)
#pragma warning(disable : 4127)
constexpr bool HostTableWellFormed() noexcept {
    if (kHostCount == 0 || kHostCount > kMaxHosts) return false;
    for (std::uint32_t h = 0; h < kHostCount; ++h) {
        const HostSpec& host = kHosts[h];
        if (host.entityId == 0ULL || host.optionCount == 0u || host.optionCount > kMaxOptionsPerHost) return false;
        std::uint32_t enabled = 0;
        for (std::uint32_t o = 0; o < host.optionCount; ++o) {
            const OptionSpec& option = host.options[o];
            if (option.text == nullptr || option.index < 1) return false;
            std::uint32_t units = 0;
            while (units < kMaxTextUnits && option.text[units] != 0) ++units;
            if (units == 0u || units >= kMaxTextUnits) return false;
            if (option.enabled != 0u) {
                if (option.enabled != 1u) return false;
                ++enabled;
            }
            for (std::uint32_t p = 0; p < o; ++p)
                if (host.options[p].index == option.index) return false;
        }
        if (enabled != 1u) return false;
        for (std::uint32_t p = 0; p < h; ++p)
            if (kHosts[p].entityId == host.entityId) return false;
    }
    return true;
}
static_assert(HostTableWellFormed(), "GT_PARAMETER_TABLE_INVALID (see GENERALIZED-TABS.md refusal codes)");
#pragma warning(pop)
static_assert(kMaxOptionsPerHost <= 64u, "GT_OPTION_LIST_READER_BOUND (native option list reader caps capacity at 64)");

// ---- receipt ---------------------------------------------------------------
// One option card as read back from the game, plus its verdict against the table.
struct OptionRow {
    std::uint64_t pointer, klass;
    std::int32_t index, sort, textLength;
    std::uint32_t icon, filter;
    std::uint8_t activeOrEnabledState; // row+0x56: the byte property GT_INITIAL_ACTIVE_PROPERTY writes
    std::uint8_t rowEnabledByte;       // row+0x54: never written here, observed only
    std::uint16_t reserved;
    char16_t text[kMaxTextUnits];
    std::int32_t expectedIndex;
    std::uint32_t expectedEnabled, indexMatched, enabledMatched, textMatched;
    std::uint32_t expectedTextUnits, mismatchUnit; // kNoIndex when every unit matched
};

struct HostResult {
    std::uint32_t entityId, status, refuseCode, refuseStage, refuseOption;
    std::uint32_t optionCount, colliderCount, readbackVerified, textVerified, radiusVerified;
    std::uint32_t componentKind, kindRowsFound, kindRowIndex, kindRowMatchesConfig, kindRowEnabled;
    std::uint64_t owner, ownerClass, config, collider, sphere;
    std::int32_t colliderShape;
    float radius;
    std::uint32_t beforeComponents, afterComponents;
    OptionRow options[kMaxOptionsPerHost];
    ge::component_attachment::AttachmentWorkspace attachmentWork;
    ge::component_attachment::AttachmentResult attachment;
    ge::component_attachment::ComponentSnapshot kindReadback;
    ge::component_edit::Result edit;
};

struct NativeGeneralizedTabsReceipt {
    std::uint32_t size, version, status, stage, sehCode, attempted, sceneUnchanged;
    std::uint32_t failedRva, failedValue, metadataCalls, completedHosts;
    std::uint32_t refuseCode, refuseStage, refuseHost, refuseOption;
    std::uint32_t hostCount, kind, expectedLevelId, levelIdBefore, levelIdAfter;
    float radius;
    std::uint32_t reserved;
    GameContextSnapshot expectedScene, afterScene;
    HostResult hosts[kMaxHosts];
};
static_assert(std::is_standard_layout<NativeGeneralizedTabsReceipt>::value &&
    std::is_trivially_copyable<NativeGeneralizedTabsReceipt>::value,
    "Generalized tabs receipt must stay a fixed POD shared through a file mapping");
static_assert(static_cast<std::size_t>(kMaxHosts) ==
    sizeof(NativeGeneralizedTabsReceipt::hosts) / sizeof(HostResult),
    "HOST LIMIT MUST EQUAL THE RECEIPT ARRAY (see GENERALIZED-TABS.md)");
// status: 0 verified, 1 not executed (an entry guard refused before any call),
// 2 hardware exception (sehCode carries it), 3 refused with refuseCode/refuseStage.
// host.status: 0 verified, 10..12 install progress, 13..15 readback progress.

} // namespace gt

void ExecuteGeneralizedTabAction(const GameContextSnapshot*, gt::NativeGeneralizedTabsReceipt*) noexcept;
