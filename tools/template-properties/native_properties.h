#pragma once
#include "../native/game_context_snapshot.h"
#include <cstdint>
#include <cstddef>
constexpr unsigned kPropertyBatch=16,kPropertyGuards=8192,kIconOptions=4096;
struct PropertyState { std::uint32_t iconId,stackLimit,isTradeable,nameLength;std::uint16_t name[128]; };
struct PropertyRequest { std::uint32_t id,subtype,mask,reserved;std::uint64_t resource,nameProperty,dataProperty;PropertyState expected,desired; };
struct PropertyRow {
 std::uint32_t id,subtype,mask,status,stage,renameCalled,openCalled,snapshotCalled,setterCalls,notifyCalled,closeCalled,closed,readbackVerified,uncertain,iconAllowed,companionNameVerified;
 std::uint64_t resource,nameProperty,dataProperty,data,basic,inter,companion,companionName,transaction,record,beforeBlob,guardBefore,guardAfter;
 PropertyState before,desired,after;
 std::uint32_t pendingBefore,pendingSnapshot,pendingAfter,depthBefore,depthAfter,reserved;
};
struct PropertyGuard { std::uint32_t id,subtype,target,companion;std::uint64_t resource,before,after; };
struct PropertyReceipt {
 std::uint32_t size,version,status,stage,seh,count,completed,sceneUnchanged,mode,catalogUnchanged,guardsUnchanged,guardCount,failedRva,failedValue,nativeCalls,reserved;
 std::uint64_t manager,catalogBefore,catalogAfter;
 std::uint32_t itemIconCount,currencyIconCount,itemIcons[kIconOptions],currencyIcons[kIconOptions];
 PropertyRow rows[kPropertyBatch];PropertyGuard guards[kPropertyGuards];GameContextSnapshot afterScene;
};
static_assert(sizeof(PropertyState)==272 && sizeof(PropertyRequest)==584 && sizeof(PropertyRow)==1008 && sizeof(PropertyGuard)==40,"property receipt ABI");
void ExecuteProperties(const GameContextSnapshot*,PropertyReceipt*) noexcept;
