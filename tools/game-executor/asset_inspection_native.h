#pragma once
#include "native_transform.h"
constexpr unsigned kAssetEntities=8, kAssetObjects=64, kAssetNameChars=96;
struct AssetMatrix { float m[16]; };
struct AssetBounds { TransformVec3 center,extents; };
struct AssetObject {
    std::uint64_t object,klass,transform,gameObject,mesh;
    // kind: 1 renderer, 2 collider. geometry: 1 MeshRenderer shared mesh local bounds.
    unsigned kind,enabled,active,isTrigger,isSceneQuery,belongs,stable,geometry;
    AssetBounds worldBounds,localGeometryBounds;
    AssetMatrix localToWorld;
    unsigned nameStatus,nameLength,meshNameStatus,meshNameLength;
    wchar_t name[kAssetNameChars],meshName[kAssetNameChars];
};
struct AssetEntity {
    unsigned entityId,status,count,roots,poseUnchanged,reserved;
    std::uint64_t unity,view;
    AssetMatrix localToWorld,worldToLocal;
    AssetObject objects[kAssetObjects];
};
struct AssetReceipt {
    unsigned size,version,status,stage,seh,count,completed,nativeCalls;
    unsigned sceneUnchanged,mutationCalls,failedRva,failedValue;
    TransformReceipt transform;
    AssetEntity entities[kAssetEntities];
};
static_assert(sizeof(wchar_t)==2 && sizeof(AssetObject)==584 && sizeof(AssetEntity)==37544,"asset inspection ABI");
void ExecuteAssetInspection(const GameContextSnapshot*,AssetReceipt*) noexcept;
