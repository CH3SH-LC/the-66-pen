#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <type_traits>
constexpr std::uint32_t kMaxLevelCatalog = 512;
struct LevelCatalogRow { std::uint32_t id, key; std::uint64_t record; };
struct LevelCatalogEntry { std::int32_t hash, next; std::uint32_t key, padding; std::uint64_t value; };
struct LevelCatalogSnapshot {
    std::uint32_t structSize, version, status, flags;
    std::uint64_t archive, dictionary, buckets, entries, levelManager, comparer;
    std::uint32_t levelId, selectedId, initializedCount, freeCount, bucketCapacity, entryCapacity;
    std::uint32_t versionBefore, versionAfter, bytesRead, readCalls, dirtyByte, recordCount;
    std::uint32_t parserError, reserved;
    LevelCatalogRow rows[kMaxLevelCatalog];
};
static_assert(sizeof(LevelCatalogRow)==16 && sizeof(LevelCatalogEntry)==24,"catalog element ABI");
static_assert(offsetof(LevelCatalogSnapshot,rows)==120 && sizeof(LevelCatalogSnapshot)==8312,"catalog ABI v1");
static_assert(std::is_trivial<LevelCatalogSnapshot>::value,"fixed POD only");
// Pure bounded occupancy parser. No dictionary lookup/comparer or game methods.
// Custom hash codes are allowed: consistency is verified against the bucket chain.
template<class ReadId>
std::uint32_t ParseLevelCatalog(const std::int32_t* buckets, std::uint32_t bucketCapacity,
 const LevelCatalogEntry* entries,std::uint32_t entryCapacity,std::int32_t count,std::int32_t free,
 ReadId readId,LevelCatalogSnapshot& out) noexcept {
    out.recordCount=0;
    if(!bucketCapacity || !entryCapacity || bucketCapacity>kMaxLevelCatalog || entryCapacity>kMaxLevelCatalog) return 1;
    if(count<0 || count>static_cast<std::int32_t>(entryCapacity) || free<0 || free>count) return 2;
    bool seen[kMaxLevelCatalog]{};
    for(std::uint32_t bucket=0;bucket<bucketCapacity;++bucket) {
        const auto head=buckets[bucket];
        if(head<0 || head>static_cast<std::int32_t>(entryCapacity)) return 3;
        for(std::int32_t index=head-1;index!=-1;) {
            if(index<0 || index>=count || seen[index]) return 4;
            seen[index]=true;const auto& item=entries[index];
            if(item.hash<0 || static_cast<std::uint32_t>(item.hash)%bucketCapacity!=bucket ||
                item.next < -1 || item.next>=static_cast<std::int32_t>(entryCapacity) || !item.key) return 5;
            if(item.value<0x10000 || item.value>=0x0000800000000000ULL || (item.value&7)) return 6;
            for(std::uint32_t i=0;i<out.recordCount;++i)
                if(out.rows[i].key==item.key || out.rows[i].record==item.value) return 7;
            std::uint32_t id=0;if(!readId(item.value,id)) return 8;
            if(id!=item.key) return 9;
            if(out.recordCount>=kMaxLevelCatalog) return 10;
            out.rows[out.recordCount++]={id,item.key,item.value};index=item.next;
        }
    }
    return out.recordCount==static_cast<std::uint32_t>(count-free)?0:11;
}
struct GameContextSnapshot;
void CaptureGameLevelCatalog(const GameContextSnapshot* baseline,LevelCatalogSnapshot* out) noexcept;
