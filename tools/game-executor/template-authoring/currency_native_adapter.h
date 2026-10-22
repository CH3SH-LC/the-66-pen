#pragma once
#include "currency_action.h"

// Only built by the isolated template action candidate builder. Never loaded by
// an existing read/create/save operation or the current fixed helper lease.
struct NativeCurrencyReceipt {
    std::uint32_t size, version, sehCode, afterSceneUnchanged;
    ge::templates::CurrencyActionResult action;
    GameContextSnapshot expected, after;
    ge::templates::CurrencyActionWorkspace workspace;
};
void ExecuteNativeCurrencyAction(const GameContextSnapshot*, NativeCurrencyReceipt*) noexcept;
