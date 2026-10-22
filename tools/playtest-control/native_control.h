#pragma once
#include "native_observe.h"
// Operation 3 is read-only. 4..7 call exactly one reviewed official entry.
struct TrialState {
    std::uint64_t global,editor,task,room,cache,data,settleManager,settleContext,settleData,model,settings,loadTask,cacheEditData,taskEditData,coroutine;
    std::uint32_t editorLevel,sceneId,taskType,taskPhase,token,roomToken,ownerUid,localUid,editing,isTrial,cacheIsTrial,currentIsTrial,multi,loadPhase,remakeCount,settleTrial,settleHidden,sceneType,readable,entryReady,trialReady,exitReady,avatarActive,reserved;
};
struct ControlReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t actionAttempted,actionReturned,stateStable,precondition;
    std::uint32_t frameBefore,frameAfter,renderedBefore,renderedAfter,width,height,pngBytes,frameStatus,reserved[4];
    PlayReceipt observation;
    TrialState before,after;
    unsigned char png[8U*1024U*1024U];
};
static_assert(sizeof(TrialState)==216 && sizeof(ControlReceipt)==864+8U*1024U*1024U,"control receipt ABI");
void ExecuteControl(ControlReceipt*) noexcept;
