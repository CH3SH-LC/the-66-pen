#pragma once
#include "../native/game_context_snapshot.h"
#include <cstdint>
struct TransformVec3 { float x,y,z; };
struct TransformPose { TransformVec3 localPosition,rotationDegrees,scale,worldPosition; };
struct TransformRequest {
    std::uint32_t entityId,mask,requireRoot,expectedFrame;
    std::uint64_t expectedParent;
    TransformPose expected,desired;
};
struct TransformRow {
    std::uint32_t entityId,status,mask,called;
    std::uint64_t owner,component,klass,unity,parent,transaction;
    TransformPose before,desired,after;
    std::uint32_t stage,openCalled,snapshotCalled,notifyCalled,closeCalled,closed,readbackVerified,uncertain;
    std::uint32_t pendingBefore,pendingSnapshot,pendingAfter,depthBefore,depthAfter,frameKind;
    std::uint64_t record,beforeBlob;
};
static_assert(sizeof(TransformPose)==48 && sizeof(TransformRequest)==120 && sizeof(TransformRow)==280,"transform ABI");
constexpr std::uint32_t kTransformBatch=128;
struct TransformReceipt {
    std::uint32_t size,version,status,stage,seh,count,completed,sceneUnchanged,failedRva,failedValue,mode,nativeCalls;
    TransformRow rows[kTransformBatch];
    GameContextSnapshot afterScene;
};
void ExecuteTransform(const GameContextSnapshot*,TransformReceipt*) noexcept;
