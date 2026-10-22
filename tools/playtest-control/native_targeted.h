#pragma once
#include "native_directory.h"
struct TargetInputGuard {
    std::uint64_t avatar,manager,component,inputState,context,view;
    std::uint64_t componentClass,expectedClass,componentOwner,managedAvatar,strengthSlot,activeSlot;
    std::uint32_t avatarId,disabled,owned,blocked,sourceActive,valid,frame,reserved;
};
struct TargetedReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t actionAttempted,actionReturned,guardVerified,optionOrdinal,editorGuid,runtimeId,stopReason,reserved;
    std::uint64_t moduleBase,checkedTick,callTick,reserved64;
    DirectoryReceipt directory;
    ContactOption immediate;
    DirectoryRow source;
    TargetInputGuard input;
};
static_assert(sizeof(TargetInputGuard)==128,"target input ABI");
static_assert(sizeof(TargetedReceipt)==9581760,"target receipt ABI");
void ExecuteTargeted(TargetedReceipt*) noexcept;
