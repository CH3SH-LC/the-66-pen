#pragma once
#include "game_context_snapshot.h"

// Largest number of entities one callback may create. The alternative -- one callback per
// entity -- costs one Windows elevation prompt per entity, which is not a workflow anyone
// can run for a decorated level. The batch is in ONE callback so the whole set is created
// inside a single verified context, and the post-conditions are checked for all of them at
// once afterwards.
constexpr std::uint32_t kMaxBatch = 256;

struct GameSceneActionResult {
    std::uint32_t size, version, action, status;
    std::uint32_t levelId, expectedLevelId, called, entityId;
    std::uint64_t owner;
    std::int32_t saveStatus;
    std::uint32_t callCode;
    // Batch results. placedId[i] is the id the game assigned to the i-th requested
    // placement, in request order, so the caller can map an id back to the spec that made
    // it. Single-placement actions leave placedCount at 0 and use entityId as before.
    std::uint32_t placedCount;
    std::uint32_t placedId[kMaxBatch];
    GameContextSnapshot after;
};
static_assert(offsetof(GameSceneActionResult, after) % 8 == 0, "after snapshot must stay 8-aligned");
static_assert(sizeof(GameSceneActionResult) ==
    offsetof(GameSceneActionResult, after) + sizeof(GameContextSnapshot), "action receipt ABI");
// Fixed build profile, one operation, current process and observed message loop.
// Status: 0 completed; 1 invalid snapshot; 2 stack mismatch; 3 anchor mismatch
// (also a hotfix byte that is nonzero or unreadable in a strict profile);
// 4 level manager unreadable; 5 level mismatch; 6 baseline mismatch (in a strict profile
// this covers the compiled context pointer and entity identity, checked before any call);
// 7 native call rejected; 8 post-create registration or post-save snapshot mismatch.
// Status 0 is a receipt for the call, never evidence of persistence.
void ExecuteGameSceneAction(const GameContextSnapshot* before, GameSceneActionResult* out);
