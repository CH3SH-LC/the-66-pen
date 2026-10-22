#pragma once
#include "native_observe.h"
constexpr unsigned kFrameCapacity=8U*1024U*1024U;
constexpr unsigned kRuntimePage=128;
struct RuntimeContext {
    std::uint64_t levelManager,levelData,levelGuid,trialTask,dictionary,entries;
    std::uint32_t readable,isTrial,serverVersion,taskType,taskState,dictionaryCount,dictionaryVersion,reserved;
};
struct RuntimeEntity {
    std::uint64_t entity,klass,transform,gameObject;
    std::uint32_t id,entryIndex,positionStatus,activeStatus,active,localAvatar,worldGetterRva,reserved;
    std::uint32_t configId,entityType,isTickable,isEntityReady,isLoaded,runtimeIdentityStatus;
    float unity[3],origin[3],world[3];
    std::uint32_t padding;
};
struct AcceptanceReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t frameBefore,frameAfter,renderedBefore,renderedAfter,width,height,pngBytes,frameStatus;
    std::uint32_t pageStart,pageEnd,count,enumerationStatus,entryCapacity,dictionaryStable,reserved[2];
    PlayReceipt observation;
    RuntimeContext before,after;
    RuntimeEntity entities[kRuntimePage];
    unsigned char png[kFrameCapacity];
};
static_assert(sizeof(RuntimeContext)==80 && sizeof(RuntimeEntity)==128,"runtime records ABI");
static_assert(sizeof(AcceptanceReceipt)==8388608+96+336+160+128*128,"acceptance ABI");
void ExecuteAcceptance(AcceptanceReceipt*) noexcept;
