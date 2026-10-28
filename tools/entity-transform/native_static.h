#pragma once
#include "native_transform.h"
struct StaticRow {
    std::uint32_t entityId,status,beforeFlag,afterFlag,called,returned;
    std::uint64_t owner,component,klass;
    std::uint32_t attachedBefore,attachedAfter,pendingBefore,pendingAfter;
    std::int32_t depthBefore,depthAfter;
};
static_assert(sizeof(StaticRow)==72,"static row ABI");
struct StaticReceipt {
    std::uint32_t size,version,status,stage,seh,count,completed,sceneUnchanged;
    std::uint32_t mode,mutationCalls,failedRva,failedValue;
    TransformReceipt beforePose;
    TransformReceipt afterPose;
    StaticRow rows[kTransformBatch];
};
void ExecuteStatic(const GameContextSnapshot*,StaticReceipt*) noexcept;
