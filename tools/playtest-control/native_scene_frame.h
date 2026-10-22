#pragma once
#include "native_observe.h"
constexpr unsigned kSceneFrameCapacity=8U*1024U*1024U;
struct SceneFrameReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t frameBefore,frameAfter,renderedBefore,renderedAfter,width,height,pngBytes,frameStatus;
    std::uint32_t callbacks,handle,handleReleased,cameraRestored,destroyQueued,frameAdvanced,guardStatus,reserved;
    PlayReceipt observation;
    std::uint64_t texture,cachedBefore,cachedAfter,camera,transform,startedTick;
    float originalPosition[3],originalRotation[4],capturePosition[3],captureRotation[4];
    float restoredPosition[3],restoredRotation[4],fieldOfView;
    unsigned char png[kSceneFrameCapacity];
};
static_assert(sizeof(SceneFrameReceipt)==568+kSceneFrameCapacity,"scene frame ABI");
bool StepSceneFrame(SceneFrameReceipt*) noexcept;
