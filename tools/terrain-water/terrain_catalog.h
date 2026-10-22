#pragma once
#include <cstdint>
constexpr std::uint32_t kWaterCatalogCapacity=512;
struct TerrainWaterTypeRow {
    std::uint64_t style,waterConfig,list,typeConfig,prefab,prefabNative;
    std::uint32_t materialId,typeId,listIndex,listCount,listVersion,reserved;
    float scaleY;std::uint32_t reserved2;
    unsigned char rawType[24];
};
struct TerrainCatalogReceipt {
    std::uint64_t size,version,status,stage,root,styleDictionary,styleCount,styleVersion,
        materialCount,waterTypeCount,stable,reserved,reserved2,reserved3,reserved4,reserved5;
    float matrix[16],steps[4];
    TerrainWaterTypeRow types[kWaterCatalogCapacity];
};
static_assert(sizeof(TerrainWaterTypeRow)==104,"Water type row ABI");
static_assert(sizeof(TerrainCatalogReceipt)==53456,"Water catalogue ABI");
