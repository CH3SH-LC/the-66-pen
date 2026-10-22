#pragma once
#include <cstdint>
constexpr unsigned kTerrainCatalogCapacity=512;
struct TerrainMaterialRow {
    std::uint64_t object,style;
    std::uint32_t dictionaryKey,encodedId,id,nameHash,category,reserved;
    unsigned char rawFields[48]; // object+10..3f, retained without semantic guesses.
};
struct TerrainCatalogReceipt {
    std::uint64_t size,version,status,stage,root,configDictionary,configCount,configVersion,
        styleDictionary,styleCount,styleVersion,materialCount,decoderTable,decoderKey,stable,reserved;
    float matrix[16],steps[4];
    unsigned char keyTable[2048];
    TerrainMaterialRow materials[kTerrainCatalogCapacity];
};
static_assert(sizeof(TerrainMaterialRow)==88,"Catalog row ABI");
static_assert(sizeof(TerrainCatalogReceipt)==47312,"Catalog receipt ABI");
