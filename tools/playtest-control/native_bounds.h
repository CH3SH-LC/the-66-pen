#pragma once
#include "native_observe.h"
struct BoundsReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t guardStatus,writeStarted,writeCompleted,settingsUnchanged,reserved[12];
    PlayReceipt observation;
    std::uint64_t manager,basic,primary,cached;
    float beforePrimary[3],beforeCached[3],afterPrimary[3],afterCached[3],desired[3],padding;
};
static_assert(sizeof(BoundsReceipt)==528,"bounds receipt ABI");
void ExecuteAcceptance(BoundsReceipt*) noexcept;
