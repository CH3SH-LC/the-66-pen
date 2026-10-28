#pragma once
#include "native_transform.h"
struct AssemblyWorld { TransformVec3 position, rotation, scale; };
struct AssemblyRow {
    std::uint32_t sourceId,hostId,status,called,beforeCount,afterCount,pendingBefore,pendingAfter;
    std::int32_t depthBefore,depthAfter;
    std::uint64_t source,host,accessory,component;
    AssemblyWorld before,after;
    std::uint32_t accessoryId,modelId;
};
static_assert(sizeof(AssemblyRow)==152,"assembly row ABI");
struct AssemblyReceipt {
    std::uint32_t size,version,status,stage,seh,count,completed,sceneUnchanged;
    std::uint32_t mode,mutationCalls,failedRva,failedValue;
    TransformReceipt beforePose;
    GameContextSnapshot afterScene;
    AssemblyRow rows[128];
    std::uint64_t undoManager,undoRecord,undoClass,undoTarget,undoBefore,undoFunction0,undoFunction1,undoFunction2;
    std::uint32_t undoCount,undoBase,undoDepth,undoFlags,undoDirty,undoReserved;
};
void ExecuteAssembly(const GameContextSnapshot*,AssemblyReceipt*) noexcept;
