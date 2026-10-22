#pragma once
#include <cstdint>
constexpr std::uint32_t kTerrainRuntimeComponents=8192, kTerrainRuntimeTargets=4, kTerrainRuntimeHits=128;
struct TerrainRuntimeComponent {
    std::uint64_t object, gameObject;
    std::uint32_t active, enabled, visible, reserved;
    float bounds[6]; // Unity Bounds: center.xyz, extents.xyz, in world coordinates.
};
struct TerrainRuntimeHit { std::uint64_t collider,index; unsigned char raw[80]; };
struct TerrainRuntimeTarget {
    std::uint64_t key,cell,renderState,cellTransform,dirty,logicalPresent,rayTests,hitCount;
    float worldCenter[4],ray[8]; // origin.xyz, distance, direction.xyz, reserved.
    TerrainRuntimeHit hits[kTerrainRuntimeHits];
};
struct TerrainRuntimeReceipt {
    std::uint64_t size,version,status,stage,readCalls,root,colliderClass,rendererClass,
        colliderArray,rendererArray,colliderCount,rendererCount,scannedColliders,scannedRenderers,targetCount,reserved;
    float matrix[16],steps[4];
    TerrainRuntimeComponent colliders[kTerrainRuntimeComponents],renderers[kTerrainRuntimeComponents];
    TerrainRuntimeTarget targets[kTerrainRuntimeTargets];
};
static_assert(sizeof(TerrainRuntimeComponent)==56,"Runtime component wire ABI");
static_assert(sizeof(TerrainRuntimeHit)==96,"Runtime hit wire ABI");
static_assert(sizeof(TerrainRuntimeTarget)==12400,"Runtime target wire ABI");
static_assert(sizeof(TerrainRuntimeReceipt)==967312,"Runtime receipt wire ABI");
