#pragma once
#include "../native/game_context_snapshot.h"
#include <cstdint>
#include <cstddef>
struct MaterialState {
    std::int32_t material;
    std::uint8_t enableMaterial,coverDecorationMaterial,coverDecorationColor,enableColor;
    std::uint32_t argb;
    std::int32_t blendMode,rgb;
    float alphaPercent;
};
static_assert(offsetof(MaterialState,enableMaterial)==4 && offsetof(MaterialState,coverDecorationMaterial)==5 && offsetof(MaterialState,coverDecorationColor)==6 && offsetof(MaterialState,enableColor)==7 && offsetof(MaterialState,argb)==8,"native component flag offsets");
struct MaterialRequest { std::uint32_t entityId,configId,mask,reserved;std::uint64_t expectedComponent;MaterialState expected,desired; };
struct MaterialSlot {
    std::uint64_t renderer,material;
    std::uint32_t slot,active,enabled,properties;
    float enable,blend,rgba[4];
    std::uint32_t keywords,reserved;
};
constexpr unsigned kMaterialBatch=32,kMaterialSlots=64;
struct MaterialRow {
    std::uint32_t entityId,configId,status,mask;
    std::uint64_t owner,component,klass,unity,view,transaction,payload;
    MaterialState before,desired,after;
    std::uint32_t stage,openCalled,snapshotCalled,deserializeCalled,notifyCalled,closeCalled,closed,refreshCalled,readbackVerified,shaderVerified,uncertain;
    std::uint32_t pendingBefore,pendingSnapshot,pendingAfter,depthBefore,depthAfter,colorAllowed,materialCount,modeCount,beforeSlots,afterSlots,nativeBlocked;
    std::uint64_t record,beforeBlob;
    std::int32_t allowedMaterials[4],allowedModes[4];
    std::uint64_t guardBefore,guardAfter;
    MaterialSlot beforeRender[kMaterialSlots],afterRender[kMaterialSlots];
};
struct MaterialGuard {
    std::uint32_t entityId,target;
    std::uint64_t owner,component,rendererHashBefore,rendererHashAfter;
    MaterialState before,after;
};
struct MaterialReceipt {
    std::uint32_t size,version,status,stage,seh,count,completed,sceneUnchanged,failedRva,failedValue,mode,nativeCalls,guardCount,guardsUnchanged,sharedMaterialsObserved,reserved;
    MaterialRow rows[kMaterialBatch];
    MaterialGuard guards[kMaxEntities];
    GameContextSnapshot afterScene;
};
static_assert(sizeof(MaterialState)==24 && sizeof(MaterialRequest)==72 && sizeof(MaterialSlot)==64,"material scalar ABI");
static_assert(sizeof(MaterialRow)==8488 && sizeof(MaterialGuard)==88,"material receipt ABI");
void ExecuteMaterial(const GameContextSnapshot*,MaterialReceipt*) noexcept;
