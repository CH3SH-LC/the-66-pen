#pragma once
#include "binding_action.h"

enum class NativeBindingCode : std::uint32_t {
    action_returned, invalid_review, invalid_context, invalid_request,
    metadata_unavailable, native_exception
};
// Private action 7 / receipt 11 candidate. Existing helper does not dispatch it.
struct NativeBindingReceipt {
    std::uint32_t size, version, sehCode, readbackSehCode, afterSceneUnchanged;
    NativeBindingCode code;
    std::uint32_t metadataUsageInProgress, metadataCallsStarted, metadataCallsCompleted;
    std::uint64_t initializedClasses[8];
    bool nativeCallAttempted, componentMutationCalled, runtimeStateMayHaveChanged;
    ge::templates::BindingActionResult action;
    GameContextSnapshot expected, after;
    ge::templates::BindingActionWorkspace workspace;
};
void ExecuteNativeBindingAction(const GameContextSnapshot*, NativeBindingReceipt*) noexcept;
