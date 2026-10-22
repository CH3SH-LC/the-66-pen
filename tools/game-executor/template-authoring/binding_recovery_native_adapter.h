#pragma once
#include "binding_recovery.h"
struct NativeBindingRecoveryReceipt {
    std::uint32_t size, version, sehCode, afterSceneUnchanged, priorHashVerified, tokenRefusalHashVerified;
    GameContextSnapshot expected, after;
    ge::templates::BindingRecoveryWorkspace workspace;
    ge::templates::BindingRecoveryResult result;
};
void ExecuteNativeBindingRecovery(const GameContextSnapshot*, NativeBindingRecoveryReceipt*) noexcept;
