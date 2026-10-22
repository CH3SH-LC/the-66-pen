#pragma once
#include "native_control.h"
constexpr unsigned kInventoryLimit=4096;
struct InventoryContext {
    std::uint64_t avatar,component,modules,moduleEntries,moduleClass,module,bag,totalsList,totalsArray,slotsList,slotsArray,generationDictionary,generationEntries,templateKey;
    std::uint32_t avatarId,avatarConfigId,moduleCapacity,totalCount,totalCapacity,totalVersion,slotCount,slotCapacity,slotVersion,bagCapacity,bagOccupied,generation,generationCapacity,generationIndex,status,reserved;
    unsigned char moduleHeader[64],generationHeader[64];
};
struct InventoryRow {
    std::uint64_t object,item,key,quantity;
    std::uint32_t index,instanceId,itemKind,reserved;
};
struct InventoryReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t contextStable,samplesStable,totalCaptured,slotCaptured,reserved[4];
    std::uint64_t avatar,component,module,bag;
    ControlReceipt control;
    InventoryContext before,after;
    InventoryRow totals[2][kInventoryLimit],slots[2][kInventoryLimit];
};
static_assert(sizeof(InventoryContext)==304 && sizeof(InventoryRow)==48 && sizeof(InventoryReceipt)==sizeof(ControlReceipt)+787136,"inventory ABI");
void ExecuteInventory(InventoryReceipt*) noexcept;
