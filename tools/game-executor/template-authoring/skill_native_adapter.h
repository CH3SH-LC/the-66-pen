#pragma once
#include "skill_action.h"

// Dedicated action 9 / receipt 13. Existing helper actions cannot dispatch it.
struct NativeSkillReceipt {
    std::uint32_t size, version, sehCode, afterSceneUnchanged;
    ge::skills::SkillActionResult action;
    GameContextSnapshot expected, after;
    ge::skills::SkillActionWorkspace workspace;
};
void ExecuteNativeSkillAction(const GameContextSnapshot*, NativeSkillReceipt*) noexcept;
