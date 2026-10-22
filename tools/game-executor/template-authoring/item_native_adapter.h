#pragma once
#include "item_action.h"

// Compile-only isolated action 6 candidate. No existing helper dispatches it.
struct NativeItemReceipt {
    std::uint32_t size, version, sehCode, afterSceneUnchanged;
    ge::templates::ItemActionResult action;
    GameContextSnapshot expected, after;
    ge::templates::ItemActionWorkspace workspace;
};
void ExecuteNativeItemAction(const GameContextSnapshot*, NativeItemReceipt*) noexcept;
