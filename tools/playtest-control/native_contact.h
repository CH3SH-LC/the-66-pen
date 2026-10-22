#pragma once
#include "native_control.h"
#include <cstdint>
constexpr unsigned kContactRows=129,kContactOptions=64,kContactMap=8192;
// Native dictionary entries, including tombstones; independently decoded later.
struct ContactMapEntry {std::int32_t hash,next;std::uint32_t runtimeId,editorGuid,beyondId;};
struct ContactReverseEntry {std::int32_t hash,next;std::uint32_t editorGuid,runtimeId;};
struct ContactRow {
    std::uint64_t entity,klass;
    std::uint32_t runtimeId,configId,entityType,flags,status,localAvatar,entryIndex,reserved;
};
struct ContactMotion {
    std::uint64_t manager,array,move,data,fsm,state,referenceEntity,referenceComponent,referenceCollider,dataCollider;
    std::uint32_t status,motion,previousMotion,stateType,beneathResult,slopeFrame,referenceRuntimeId,referenceColliderIndex;
    std::uint32_t downRayEntityId,downRayFrame,frameBefore,frameAfter;
    unsigned char slopeRaw[52];std::uint32_t reserved;
};
struct ContactOption {
    std::uint64_t item,button,event,invocation,wrapper,delegateObject,callbackTarget,callbackClass,callbackMethod,methodInfo;
    std::uint32_t status,panel,index,textLength;
    std::uint16_t text[128];
    std::uint64_t interfaceType,interfaceRecord,callbackSlot,ownerGetter,ownerMethodInfo,ownerData,ownerObject;
    std::uint32_t ownerStatus,interfaceOffset,virtualCount,fieldOffset,ownerRuntimeId,active,enabled,reserved;
    unsigned char getterHead[8];
    ContactRow owner;
};
struct ContactSample {
    std::uint64_t entityManager,dictionary,entries,beyondManager,map,mapEntries,reverseMap,reverseEntries,mainContext,view,panel;
    std::uint32_t entityCount,entityVersion,entityCapacity,avatarId,mapCount,mapCapacity,reverseCount,reverseCapacity,optionCount,mapStatus,optionsStatus,reserved;
    unsigned char mapHeader[80],reverseHeader[80];
    ContactMotion motion;
    ContactRow rows[kContactRows];
    ContactOption options[kContactOptions];
    ContactMapEntry mappings[kContactMap];
    ContactReverseEntry reverse[kContactMap];
};
struct ContactReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased,pageStart,pageEnd,count,stable;
    std::uint64_t moduleBase;std::uint32_t reserved[2];
    ControlReceipt control;
    ContactSample first,second;
};
static_assert(sizeof(ContactMapEntry)==20&&sizeof(ContactReverseEntry)==16&&sizeof(ContactRow)==48);
static_assert(sizeof(ContactMotion)==184&&sizeof(ContactOption)==496);
void ExecuteContact(ContactReceipt*) noexcept;
