#pragma once
#include "native_control.h"
constexpr unsigned kVitalsPage=128, kVitalsRows=129, kVitalsTable=3072;
struct VitalsRow {
    std::uint64_t entity,klass,component,properties;
    std::uint32_t id,configId,entityType,flags,status,hpStatus,lifeStatus,alive,localAvatar,entryIndex;
    float currentHp,maxHp;
    unsigned char currentEncoded[16],maxEncoded[16];
};
struct VitalsContext {std::uint32_t count,version,capacity,avatarId;};
struct VitalsReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased;
    std::uint32_t count,pageStart,pageEnd,dictionaryStable,samplesStable,tableStatus,reserved[2];
    std::uint64_t dictionary,entries,table,avatar;
    ControlReceipt control;
    VitalsContext before,after;
    unsigned char tableBefore[kVitalsTable],tableAfter[kVitalsTable];
    VitalsRow first[kVitalsRows],second[kVitalsRows];
};
static_assert(sizeof(VitalsRow)==112 && sizeof(VitalsReceipt)==sizeof(ControlReceipt)+35168,"vitals ABI");
void ExecuteVitals(VitalsReceipt*) noexcept;
