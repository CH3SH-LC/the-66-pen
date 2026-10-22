#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "game_scene_action.h"
#include "scene_calls.h"
#include <algorithm>
#include <cstring>
#ifndef HR_ROTATION
#define HR_ROTATION 0,0,0
#endif
#ifndef HR_SCALE
#define HR_SCALE 1,1,1
#endif
#if !GS_STRICT_PROFILE && !defined(GS_OWNER_ID_OFFSET)
#define GS_OWNER_ID_OFFSET 0x1c
#endif

// ---------------------------------------------------------------------------------------
// Version-varying entry points and offsets, under the same rule as the snapshot copy: a
// legacy build (neither strict switch, see the header) keeps the literals this action was
// verified against, byte for byte. A strict build must be handed every one of these by its
// profile header -- a missing one is an #error, never a silently reused stale value, and a
// reviewed action has no unreviewed fallback.
#if GS_STRICT_PROFILE
#if !defined(HR_LEVEL_ANCHOR_RVA) || !defined(HR_PLACE_ANCHOR_RVA) || !defined(HR_SAVE_ANCHOR_RVA) || \
    !defined(HR_LEVEL_MANAGER_OFFSET) || !defined(HR_STACK_PUMP_RVA) || !defined(HR_STACK_OUTER_RVA)
#error "a strict profile requires the level/place/save anchor RVAs, the level manager offset and both stack RVAs"
#endif
#if !defined(GS_PROFILE_HOTFIX_RVAS)
#error "a strict profile requires GS_PROFILE_HOTFIX_RVAS for the pre-call hotfix recheck"
#endif
#if !defined(HR_EXPECTED_CONTEXT)
#error "a strict profile requires HR_EXPECTED_CONTEXT"
#endif
#else
#ifndef HR_LEVEL_ANCHOR_RVA
#define HR_LEVEL_ANCHOR_RVA 0xe920a70
#endif
#ifndef HR_PLACE_ANCHOR_RVA
#define HR_PLACE_ANCHOR_RVA 0xb7a1aa0
#endif
#ifndef HR_SAVE_ANCHOR_RVA
#define HR_SAVE_ANCHOR_RVA 0xddbfe60
#endif
#ifndef HR_LEVEL_MANAGER_OFFSET
#define HR_LEVEL_MANAGER_OFFSET 0x9c70
#endif
#ifndef HR_STACK_PUMP_RVA
#define HR_STACK_PUMP_RVA 0xa4deb8
#endif
#ifndef HR_STACK_OUTER_RVA
#define HR_STACK_OUTER_RVA 0xa54d4a
#endif
#endif

#if GS_STRICT_PROFILE
constexpr std::uint32_t kHotfixRvas[] = { GS_PROFILE_HOTFIX_RVAS };
constexpr std::size_t kHotfixCount = sizeof(kHotfixRvas) / sizeof(kHotfixRvas[0]);
static_assert(kHotfixCount >= 1 && kHotfixCount <= 64, "profile hotfix watch list is bounded");
// Element types the profile header must emit: the id arrays as 32-bit unsigned ids and the
// three pointer arrays as 64-bit unsigned literals. The arrays are positional: element i
// must describe the i-th entity of the before snapshot's walk order.
constexpr std::size_t kExpectedEntityCount =
    sizeof(HR_EXPECTED_ENTITY_IDS) / sizeof(HR_EXPECTED_ENTITY_IDS[0]);
static_assert(kExpectedEntityCount >= 1 && kExpectedEntityCount <= kMaxEntities,
    "the reviewed baseline must fit the snapshot capacity");
static_assert(sizeof(HR_EXPECTED_OWNER_POINTERS) / sizeof(HR_EXPECTED_OWNER_POINTERS[0]) == kExpectedEntityCount,
    "one expected owner pointer per baseline entity");
static_assert(sizeof(HR_EXPECTED_CONFIG_POINTERS) / sizeof(HR_EXPECTED_CONFIG_POINTERS[0]) == kExpectedEntityCount,
    "one expected config pointer per baseline entity");
static_assert(sizeof(HR_EXPECTED_CONFIG_IDS) / sizeof(HR_EXPECTED_CONFIG_IDS[0]) == kExpectedEntityCount,
    "one expected config id per baseline entity");
static_assert(sizeof(HR_EXPECTED_ENTITY_CONTEXTS) / sizeof(HR_EXPECTED_ENTITY_CONTEXTS[0]) == kExpectedEntityCount,
    "one expected context pointer per baseline entity");
#endif

namespace {
bool CopyChecked(std::uint64_t address, void* target, std::size_t size) noexcept {
    MEMORY_BASIC_INFORMATION region{};
    if (!address || !size || VirtualQuery(reinterpret_cast<const void*>(address), &region, sizeof(region)) != sizeof(region) ||
        region.State != MEM_COMMIT || (region.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return false;
    const auto begin = reinterpret_cast<std::uint64_t>(region.BaseAddress);
    if (address < begin || address - begin >= region.RegionSize || size > region.RegionSize - (address - begin)) return false;
    __try { std::memcpy(target, reinterpret_cast<const void*>(address), size); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}
template<std::size_t N> bool Anchor(std::uint64_t base, std::uint32_t rva, const unsigned char (&expected)[N]) noexcept {
    unsigned char actual[N]{};
    return CopyChecked(base + rva, actual, N) && std::memcmp(actual, expected, N) == 0;
}
#if HR_ACTION == 3
bool PlaceBatchSafely(ge::scene::PlacementFactory factory, void* context,
    const ge::scene::PlacementInput& input, ge::scene::PlacementResult* result,
    std::uint32_t* exception) noexcept {
    __try { *result = ge::scene::place_builtin(factory, context, input); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { *exception = GetExceptionCode(); return false; }
}
#endif
bool CompletePostSnapshot(const GameContextSnapshot& before, const GameContextSnapshot& after) noexcept {
    return after.status == GS_OK && after.currentContext == before.currentContext &&
        after.entityCaptured == after.entityValidEntries && after.entityRejected == 0 &&
        (after.flags & (GS_ENTITIES_TRUNCATED | GS_ENTITY_READ_FAILURE)) == 0
#if GS_STRICT_PROFILE
        && (after.flags & 1951) == 1951 && after.reserved == before.reserved
#endif
        ;
}
// O(N log N) identity reconciliation, bounded stack scratch (32 KiB in v2).
// Dictionary insertion may rehash/reorder, so positional comparison is invalid here.
bool BaselinePreserved(const GameContextSnapshot& before, const GameContextSnapshot& after) noexcept {
    if (before.entityCaptured > kMaxEntities || after.entityCaptured > kMaxEntities) return false;
    const GameEntitySnapshot* sorted[kMaxEntities]{};
    for (std::uint32_t i = 0; i < after.entityCaptured; ++i) sorted[i] = &after.entities[i];
    std::sort(sorted, sorted + after.entityCaptured, [](const auto* a, const auto* b) {return a->id < b->id;});
    for (std::uint32_t i = 1; i < after.entityCaptured; ++i) if (sorted[i - 1]->id == sorted[i]->id) return false;
    for (std::uint32_t i = 0; i < before.entityCaptured; ++i) {
        const auto& a = before.entities[i];
        const auto found = std::lower_bound(sorted, sorted + after.entityCaptured, a.id,
            [](const auto* entity, std::uint32_t id) {return entity->id < id;});
        if (found == sorted + after.entityCaptured) return false;
        const auto& b = **found;
        if (a.id != b.id || a.owner != b.owner || a.config != b.config || a.configId != b.configId || a.context != b.context) return false;
    }
    return true;
}
bool StackMatches(const GameContextSnapshot& value) noexcept {
    bool pump = false, outer = false;
    for (std::uint32_t i = 0; i < value.stackCount && i < 32; ++i) {
        if (value.stack[i] < value.moduleBase) continue;
        const auto rva = value.stack[i] - value.moduleBase;
        pump |= rva == HR_STACK_PUMP_RVA;
        outer |= rva == HR_STACK_OUTER_RVA;
    }
    return pump && outer;
}
#if GS_STRICT_PROFILE
// The reviewed profile compiles the exact entity identity it was reviewed against. A level
// edited since then, or a different context, is not the scene this action is allowed to
// touch: a mismatch is refused before any game call, never reconciled afterwards.
bool BaselineIdentityMatches(const GameContextSnapshot& before) noexcept {
    if (before.currentContext != static_cast<std::uint64_t>(HR_EXPECTED_CONTEXT)) return false;
    if (before.entityCaptured != kExpectedEntityCount) return false;
    for (std::uint32_t i = 0; i < kExpectedEntityCount; ++i) {
        const auto& entity = before.entities[i];
        if (entity.id != HR_EXPECTED_ENTITY_IDS[i] ||
            entity.owner != static_cast<std::uint64_t>(HR_EXPECTED_OWNER_POINTERS[i]) ||
            entity.config != static_cast<std::uint64_t>(HR_EXPECTED_CONFIG_POINTERS[i]) ||
            entity.configId != HR_EXPECTED_CONFIG_IDS[i] ||
            entity.context != static_cast<std::uint64_t>(HR_EXPECTED_ENTITY_CONTEXTS[i])) return false;
    }
    return true;
}
// Watched module bytes must still be at their default. Unreadable counts as not default, so
// a failure here refuses the call rather than skipping the check.
bool HotfixBytesDefault(std::uint64_t moduleBase) noexcept {
    for (std::uint32_t i = 0; i < kHotfixCount; ++i) {
        unsigned char byte = 0xff;
        if (!CopyChecked(moduleBase + kHotfixRvas[i], &byte, 1) || byte != 0) return false;
    }
    return true;
}
#endif
}

void ExecuteGameSceneAction(const GameContextSnapshot* before, GameSceneActionResult* out) {
    if (!before || !out) return;
    std::memset(out, 0, sizeof(*out)); // The receipt lives in the mapping, not on the callback stack.
    out->size = sizeof(*out); out->version = 1; out->action = HR_ACTION;
    out->saveStatus = -1; // Not called; creation must not imply a successful save.
    out->expectedLevelId = HR_EXPECTED_LEVEL; out->status = 1;
    if (before->status != GS_OK || (before->flags & 31) != 31 || before->entityRejected ||
        before->entityCaptured != before->entityValidEntries || before->activeKey != 0 ||
#if GS_STRICT_PROFILE
        // Strict profiles require the evidence only they produce: the verified call path and
        // the confirmed hotfix default. A truncated or partly rejected walk is refused too.
        (before->flags & 1951) != 1951 || before->reserved != HR_EXPECTED_LEVEL || (before->flags & (GS_ENTITIES_TRUNCATED | GS_ENTITY_READ_FAILURE)) != 0 ||
#endif
        GetCurrentProcessId() != HR_TARGET_PID || GetCurrentThreadId() != HR_TARGET_TID || GetTickCount64() >= HR_DEADLINE) return;
    out->status = 2;
    if (!StackMatches(*before)) return;
    constexpr unsigned char levelAnchor[] = { HR_LEVEL_ANCHOR };
    constexpr unsigned char placeAnchor[] = { HR_PLACE_ANCHOR };
    constexpr unsigned char saveAnchor[] = { HR_SAVE_ANCHOR };
    out->status = 3;
    if (!Anchor(before->moduleBase, HR_LEVEL_ANCHOR_RVA, levelAnchor) ||
        !Anchor(before->moduleBase, HR_PLACE_ANCHOR_RVA, placeAnchor) ||
        !Anchor(before->moduleBase, HR_SAVE_ANCHOR_RVA, saveAnchor)) return;
    out->status = 4;
    std::uint64_t levelManager = 0;
    if (!CopyChecked(before->global + HR_LEVEL_MANAGER_OFFSET, &levelManager, sizeof(levelManager)) || !levelManager) return;
#if GS_STRICT_PROFILE
    // Both checks below are the last ones before the first game call; identity or level
    // checks that run after a call cannot un-make it. The compiled baseline identity must
    // match this snapshot exactly (status 6), and the profile's hotfix bytes must still be
    // at their default (status 3) -- nonzero or unreadable refuses here, nothing is called.
    out->status = 6;
    if (!BaselineIdentityMatches(*before)) return;
    out->status = 3;
    if (!HotfixBytesDefault(before->moduleBase)) return;
    out->status = 4;
#endif
    // Exact getter used by the native save command. It checks editing state and
    // honours this build's hotfix route; no guessed raw current-level value.
    using GetLevel = std::uint32_t (__cdecl *)(void*);
    out->levelId = reinterpret_cast<GetLevel>(before->moduleBase + HR_LEVEL_ANCHOR_RVA)(reinterpret_cast<void*>(levelManager));
    out->status = 5;
    if (out->levelId != HR_EXPECTED_LEVEL) return;
    out->status = 6;
    if (before->entityCaptured != sizeof(HR_EXPECTED_ENTITY_IDS) / sizeof(HR_EXPECTED_ENTITY_IDS[0])) return;
#if !GS_STRICT_PROFILE
    for (auto id : HR_EXPECTED_ENTITY_IDS) {
        bool found = false;
        for (std::uint32_t i = 0; i < before->entityCaptured; ++i) found |= before->entities[i].id == id;
        if (!found) return;
    }
#endif
#if HR_ACTION == 1
    const ge::scene::PlacementInput input{HR_TEMPLATE_ID, {HR_POSITION},
        {before->origin[0], before->origin[1], before->origin[2]}, {HR_ROTATION}, {HR_SCALE}};
    out->called = 1;
    const auto placed = ge::scene::place_builtin(
        reinterpret_cast<ge::scene::PlacementFactory>(before->moduleBase + HR_PLACE_ANCHOR_RVA),
        reinterpret_cast<void*>(before->currentContext), input);
    out->callCode = static_cast<std::uint32_t>(placed.code);
    out->owner = reinterpret_cast<std::uint64_t>(placed.owner);
    out->status = 7;
    if (placed.code != ge::scene::CallCode::returned) return;
    CaptureGameContextSnapshot(&out->after);
    out->status = 8;
    if (!CompletePostSnapshot(*before, out->after) ||
        out->after.entityValidEntries != before->entityValidEntries + 1 ||
        out->after.entityCaptured != out->after.entityValidEntries) return;
    if (!BaselinePreserved(*before, out->after)) return;
    for (std::uint32_t i = 0; i < out->after.entityCaptured; ++i) {
        const auto& entity = out->after.entities[i];
        if (entity.owner == out->owner && entity.configId == HR_TEMPLATE_ID && (entity.flags & 79) == 79) {
            out->entityId = entity.id; out->status = 0; return;
        }
    }
#elif HR_ACTION == 2
    const auto saved = ge::scene::save_current(
        reinterpret_cast<ge::scene::SaveCurrentLevel>(before->moduleBase + HR_SAVE_ANCHOR_RVA),
        reinterpret_cast<void*>(before->saveManager));
    out->called = saved.called ? 1 : 0;
    out->callCode = static_cast<std::uint32_t>(saved.code);
    out->saveStatus = saved.native_status;
    out->status = saved.code == ge::scene::CallCode::returned ? 0 : 7;
    CaptureGameContextSnapshot(&out->after);
    // "Returned" only says the native call came back. A save is reported as success only
    // when the scene can still be observed afterwards: the post snapshot must be complete
    // for the same context and must show the same entity identity set the before snapshot
    // showed, unchanged. This is a receipt, not evidence of persistence.
    if (out->status == 0) {
        if (!CompletePostSnapshot(*before, out->after) ||
            out->after.entityCaptured != before->entityCaptured ||
            out->after.entityValidEntries != before->entityValidEntries || out->after.entityRejected ||
            (out->after.flags & (GS_ENTITIES_TRUNCATED | GS_ENTITY_READ_FAILURE)) != 0) { out->status = 8; return; }
        if (!BaselinePreserved(*before, out->after)) { out->status = 8; return; }
    }
#elif HR_ACTION == 3
    // Batch create: N entities in ONE callback.
    //
    // Why batch at all: one callback per entity means one Windows elevation prompt per
    // entity. The single-create path needs that because each run compiles a one-shot
    // profile bound to the exact expected entity set; for a decorated level that is
    // hundreds of prompts, which is not a workflow. Here the whole request list is
    // compiled into this binary and executed inside one already-verified context.
    //
    // What is NOT relaxed: the identity/level/anchor checks above all still run, every
    // placement still goes through the same native factory the drag path uses, and the
    // post-conditions below are checked for the whole set (exactly +N, every prior entity
    // preserved, and every requested placement resolved back to a real id by owner).
    static_assert(HR_PLACEMENT_COUNT > 0 && HR_PLACEMENT_COUNT <= kMaxBatch, "batch size out of range");
    void* owners[HR_PLACEMENT_COUNT] = {};
    out->called = 1;
    const auto factory = reinterpret_cast<ge::scene::PlacementFactory>(before->moduleBase + HR_PLACE_ANCHOR_RVA);
    const ge::scene::Vec3 origin{before->origin[0], before->origin[1], before->origin[2]};
    bool stopped = false;
    for (std::uint32_t i = 0; i < HR_PLACEMENT_COUNT; ++i) {
        // Bound a long callback as well as its start. Expiry stops without replay,
        // rollback, or pretending the preceding placements never happened.
        if (GetTickCount64() >= HR_DEADLINE) { out->callCode = 0x100; stopped = true; break; }
        const float* const row = &HR_PLACEMENT_TRANSFORM[i * 9];
        const ge::scene::PlacementInput input{
            HR_PLACEMENT_TEMPLATE[i], {row[0], row[1], row[2]}, origin,
            {row[3], row[4], row[5]}, {row[6], row[7], row[8]}};
        ge::scene::PlacementResult placed{};
        if (!PlaceBatchSafely(factory, reinterpret_cast<void*>(before->currentContext), input, &placed, &out->callCode)) {
            stopped = true; break;
        }
        if (placed.code != ge::scene::CallCode::returned) {
            out->callCode = static_cast<std::uint32_t>(placed.code); stopped = true; break;
        }
        owners[i] = placed.owner;
        out->placedCount = i + 1;
        // Keep every already-known ID even if the eventual snapshot or a later
        // placement fails. The full after snapshot still independently checks it.
        CopyChecked(reinterpret_cast<std::uint64_t>(placed.owner) + GS_OWNER_ID_OFFSET,
            &out->placedId[i], sizeof(out->placedId[i]));
    }
    CaptureGameContextSnapshot(&out->after);
    out->status = stopped ? 7 : 8;
    if (!CompletePostSnapshot(*before, out->after) ||
        out->after.entityValidEntries != before->entityValidEntries + out->placedCount ||
        !BaselinePreserved(*before, out->after)) return;
    for (std::uint32_t i = 0; i < out->placedCount; ++i) {
        bool found = false;
        for (std::uint32_t j = 0; j < out->after.entityCaptured; ++j) {
            const auto& entity = out->after.entities[j];
            if (entity.owner == static_cast<std::uint64_t>(reinterpret_cast<std::uintptr_t>(owners[i])) &&
                entity.configId == HR_PLACEMENT_TEMPLATE[i] && (entity.flags & 79) == 79) {
                if (out->placedId[i] && out->placedId[i] != entity.id) return;
                out->placedId[i] = entity.id; found = true; break;
            }
        }
        if (!found) return;
    }
    if (!stopped && out->placedCount == HR_PLACEMENT_COUNT) out->status = 0;

#else
#error Unsupported fixed action
#endif
}
