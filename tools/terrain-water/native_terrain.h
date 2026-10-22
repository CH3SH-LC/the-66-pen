#pragma once
#include "../native/game_context_snapshot.h"
#include <cstdint>
#if TERRAIN_RUNTIME_PROBE
#include "terrain_runtime.h"
#endif
#if TERRAIN_CATALOG_PROBE || TERRAIN_CATALOG_GUARD
#include "terrain_catalog.h"
#endif
constexpr std::uint32_t kTerrainCapacity = 65536;
// Metadata usage initialization legitimately changes 0 -> 1. Hotfix dispatch
// flags select a different implementation and must still be exactly zero.
constexpr bool TerrainRuntimeFlagAccepted(unsigned char value,bool initialized) noexcept {
    return initialized ? value<=1 : value==0;
}
struct TerrainCellRow { std::uint32_t key, height, material, extraA, extraB, extraC; };
// Fixed independent wire ABI: 32 uint64 header words followed by two row arrays.
struct TerrainReceipt {
    std::uint64_t size, version, status, stage, sehCode, mutationCalls, completed,
        transactionMayBeOpen, outcomeUncertain, beforeCount, afterCount, terrainId,
        manager, owner, dictionary, beforeVersion, afterVersion, failedKey,
        failedRva, failedValue, openCalled, snapshotCalled, notifyCalled, closeCalled,
        snapshotVerified, notificationVerified, closeVerified, sceneUnchanged,
        captureStable, terrainCount, constantsValid, reserved;
    TerrainCellRow before[kTerrainCapacity], after[kTerrainCapacity];
    GameContextSnapshot afterScene;
#if TERRAIN_RUNTIME_PROBE
    TerrainRuntimeReceipt runtime;
#endif
#if TERRAIN_CATALOG_PROBE
    TerrainCatalogReceipt catalog;
#endif
};
static_assert(sizeof(TerrainCellRow) == 24, "Terrain row ABI");
static_assert(sizeof(TerrainReceipt) == 256 + 48 * kTerrainCapacity + sizeof(GameContextSnapshot)
#if TERRAIN_RUNTIME_PROBE
    +sizeof(TerrainRuntimeReceipt)
#endif
#if TERRAIN_CATALOG_PROBE
    +sizeof(TerrainCatalogReceipt)
#endif
    , "Terrain receipt ABI");
void ExecuteTerrainAction(const GameContextSnapshot*, TerrainReceipt*) noexcept;
