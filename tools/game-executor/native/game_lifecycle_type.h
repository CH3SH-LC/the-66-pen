#pragma once
#include <cstdint>
#include <cstddef>
#include <type_traits>
constexpr std::uint32_t kMaxLifecycleTypeSlots=128;
constexpr std::uint32_t kLifecycleTypeRequiredFlags=255;
struct LifecycleTypeSnapshot {
 std::uint32_t structSize,version,status,flags;
 std::uint64_t moduleBase,classSlot,classPointer,functionsAddress,trailingWordsAddress,expectedFunction;
 std::uint32_t imageSize,levelId,initializedBefore,initializedAfter,slotCountBefore,slotCountAfter;
 std::uint32_t matchCount,matchIndex,bytesRead,readCalls,parserError,reserved;
 std::uint64_t functions[kMaxLifecycleTypeSlots],trailingWords[kMaxLifecycleTypeSlots];
};
static_assert(sizeof(LifecycleTypeSnapshot)==2160 && offsetof(LifecycleTypeSnapshot,functions)==112 &&
 offsetof(LifecycleTypeSnapshot,trailingWords)==1136,"lifecycle type ABI v1");
static_assert(std::is_trivial<LifecycleTypeSnapshot>::value,"fixed POD only");
// Adjacent words are opaque. The pinned resolver conditionally replaces them from metadata.
// This probe does not read the resolver discriminator or establish MethodInfo semantics.
inline std::uint32_t MatchLifecycleFunction(const std::uint64_t* functions,std::uint32_t count,
 std::uint64_t expected,std::uint32_t& matches,std::uint32_t& index) noexcept {
 matches=0;index=0xffffffffu;
 if(!functions || !count || count>kMaxLifecycleTypeSlots)return 1;
 if(expected<0x10000 || expected>=0x0000800000000000ULL)return 2;
 for(std::uint32_t i=0;i<count;++i)if(functions[i]==expected){++matches;index=i;}
 if(matches==0)return 3;
 if(matches!=1){index=0xffffffffu;return 4;}
 return 0;
}
struct GameContextSnapshot;
void CaptureGameLifecycleType(const GameContextSnapshot* baseline,LifecycleTypeSnapshot* out) noexcept;
