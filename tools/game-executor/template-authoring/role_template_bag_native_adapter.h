#pragma once
#include "role_template_bag_action.h"

enum class NativeRoleTemplateBagCode : std::uint32_t {
    action_returned, invalid_review, invalid_context, invalid_request,
    metadata_unavailable, native_exception
};
// Dedicated action10 / protocol receipt14; version1 of this private payload.
struct NativeRoleTemplateBagReceipt {
    std::uint32_t size, version, sehCode, readbackSehCode, afterSceneUnchanged;
    NativeRoleTemplateBagCode code;
    std::uint32_t metadataUsageInProgress, metadataCallsStarted, metadataCallsCompleted;
    std::uint64_t initializedClasses[9];
    bool nativeCallAttempted, componentMutationCalled, runtimeStateMayHaveChanged;
    ge::templates::RoleTemplateBagResult action;
    GameContextSnapshot expected, after;
    ge::templates::RoleTemplateBagWorkspace workspace;
};
void ExecuteNativeRoleTemplateBagAction(const GameContextSnapshot*, NativeRoleTemplateBagReceipt*) noexcept;
