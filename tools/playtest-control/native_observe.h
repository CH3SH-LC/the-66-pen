#pragma once
#include <cstdint>
struct PlaySample {
    std::uint64_t global,modeManager,gateManager,gateObject,editorManager,avatarManager,dictionary,avatar,transform;
    std::uint32_t rawMode,editing,editorLevel,avatarId,avatarStatus,positionStatus,avatarBranch;
    float unity[3],origin[3],world[3];
};
struct PlayReceipt {
    std::uint32_t bytes,version,status,seh,stage,failedRva,failedValue,nativeCalls;
    std::uint32_t mode,stable,readableBefore,readableAfter,targetLevel,reserved[3];
    PlaySample before,after;
};
static_assert(sizeof(PlaySample)==136 && sizeof(PlayReceipt)==336,"play observation ABI");
void ExecutePlayObservation(PlayReceipt*) noexcept;
