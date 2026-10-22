#pragma once
#include "native_control.h"
struct InputOption { std::uint64_t item,button;std::uint32_t index,active,enabled,textLength;std::uint16_t text[128]; };
struct InputPoint {std::uint64_t tick;std::uint32_t frame,flags;float world[3],strength,angle;std::uint32_t reserved;};
struct InputReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t actionAttempted,actionReturned,callbacks,points,options,stopReason,released,releaseAttempted;
    std::uint64_t startedTick,lastTick;std::uint32_t firstFrame,lastFrame,pressAccepted,reserved;
    ControlReceipt control;
    std::uint64_t avatar,manager,component,inputState,mainContext,view,actionPanel,inteePanel,button;
    std::uint32_t avatarId,attackSlot,attackAction,optionIndex,optionComplete,inputEnabled,sourceIdle,reserved2;
    InputOption option[64];InputPoint point[192];
};
static_assert(sizeof(InputOption)==288 && sizeof(InputPoint)==40,"input row ABI");
static_assert(sizeof(InputReceipt)==sizeof(ControlReceipt)+26312,"input receipt ABI");
// Returns true only after the card has reached a terminal state. One game-frame
// pulse at most per callback; the game thread is never slept or looped over.
bool StepInput(InputReceipt*) noexcept;
