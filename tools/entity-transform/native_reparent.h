#pragma once
#include "native_assembly.h"
struct ReparentRow {
    std::uint32_t accessoryId,oldHostId,hostId,modelId,status,called;
    std::uint32_t oldBefore,oldAfter,newBefore,newAfter,parentBefore,parentAfter;
    std::uint64_t accessory,oldHost,host,childComponent,oldComponent,component,transform,transaction;
    AssemblyWorld before,after;
    std::uint32_t pendingBefore,pendingAfter;
    std::int32_t depthBefore,depthAfter;
    std::uint32_t opened,closed;
    // Runtime kind-40 references use component IDs, not scene entity IDs.
    std::uint32_t oldComponentId,componentId;
};
static_assert(sizeof(ReparentRow)==216,"reparent row ABI v2");
struct ReparentReceipt {
    AssemblyReceipt common;
    ReparentRow transfers[512];
    // ABI v3: row transaction boundaries refer to this one shared batch scope.
    std::uint64_t startedTick,preflightDoneTick,mutationDoneTick,finishedTick,batchTransaction;
    std::uint32_t budgetMillis,budgetExceeded,batchOpened,batchClosed,pendingPeak,reserved;
    std::int32_t baseDepth,batchDepth;
};
void ExecuteReparent(const GameContextSnapshot*,ReparentReceipt*) noexcept;
