#pragma once
#include <cstdint>
#include <cstddef>
#include <type_traits>
constexpr std::uint32_t kMaxSchedulerCoroutineHandles=128;
constexpr std::uint32_t kSchedulerCoroutinesRequiredFlags=255;
constexpr std::uint32_t kSchedulerBoundsObservedFailure=256;
constexpr std::uint32_t kSchedulerCapacitySaturatedFailure=512;
enum SchedulerRowDisposition:std::uint32_t {SC_NULL_HANDLE=0,SC_NULL_HOLDER=1,SC_RELEASED=2,SC_UNKNOWN_REFERENCE_KIND=3,SC_NULL_ITERATOR=4,SC_OTHER_CLASS=5,SC_OTHER_OWNER=6,SC_TARGET=7,SC_UNAVAILABLE_HOLDER_STATE=8,SC_OTHER_HANDLE_CLASS=9};
struct SchedulerCoroutineRow {
 std::uint64_t handle,handleClass,holder,iterator,iteratorClass,iteratorOwner,currentYield,holderNativeOwner,gcTokenOpaque;
 std::uint32_t index,disposition,referenceKind;
 std::int32_t referenceCount;
 std::uint32_t retainedByWrapper,released;
 std::int32_t state;
 std::uint32_t reserved;
};
struct SchedulerCoroutinesSnapshot {
 std::uint32_t structSize,version,status,flags;
 std::uint64_t moduleBase,global,scheduler,list,array,lifecycleOwner,targetClass,classSlot,managedTypesRoot,coroutineClass;
 std::uint32_t levelId,listCountBefore,listCountAfter,listCapacity,versionBefore,versionAfter,rowCount,targetCount;
 std::uint32_t nullHandleCount,unavailableCount,otherCount,bytesRead,readCalls,typeSlotCount,referencePolicyBefore,referencePolicyAfter;
 SchedulerCoroutineRow rows[kMaxSchedulerCoroutineHandles];
};
static_assert(sizeof(SchedulerCoroutineRow)==104 && offsetof(SchedulerCoroutineRow,index)==72,"scheduler row ABI");
static_assert(offsetof(SchedulerCoroutinesSnapshot,rows)==160 && sizeof(SchedulerCoroutinesSnapshot)==13472,"scheduler sample ABI v1");
static_assert(std::is_trivial<SchedulerCoroutinesSnapshot>::value,"fixed POD only");
// Failure-only diagnostics: no array was followed and stability has not been checked.
inline void RecordSchedulerBoundsDiagnostic(SchedulerCoroutinesSnapshot& out,std::int32_t count,std::uint64_t capacity,std::uint32_t version) noexcept {
 out.listCountBefore=static_cast<std::uint32_t>(count);
 out.listCapacity=capacity>UINT32_MAX ? UINT32_MAX : static_cast<std::uint32_t>(capacity);
 out.versionBefore=version;out.flags|=kSchedulerBoundsObservedFailure;
 if(capacity>UINT32_MAX)out.flags|=kSchedulerCapacitySaturatedFailure;
}
inline bool ValidSchedulerListBounds(std::int32_t count,std::uint64_t capacity) noexcept {
 return count>=0 && static_cast<std::uint32_t>(count)<=kMaxSchedulerCoroutineHandles &&
        capacity<=INT32_MAX && static_cast<std::uint64_t>(count)<=capacity;
}
inline std::uint32_t ClassifySchedulerRow(const SchedulerCoroutineRow& r,std::uint64_t targetClass,std::uint64_t targetOwner,std::uint64_t coroutineClass) noexcept {
 if(!r.handle)return SC_NULL_HANDLE;
 if(r.handleClass!=coroutineClass)return SC_OTHER_HANDLE_CLASS;
 if(!r.holder)return SC_NULL_HOLDER;
 if(r.released)return SC_RELEASED;
 if(r.referenceKind!=2)return SC_UNKNOWN_REFERENCE_KIND;
 if(r.retainedByWrapper!=1 || r.referenceCount<=0 || r.holder==r.handle ||
    (r.iterator && (r.iterator==r.handle || r.iterator==r.holder)))return SC_UNAVAILABLE_HOLDER_STATE;
 if(!r.iterator)return SC_NULL_ITERATOR;
 if(r.iteratorClass!=targetClass)return SC_OTHER_CLASS;
 if(r.iteratorOwner!=targetOwner)return SC_OTHER_OWNER;
 return SC_TARGET;
}
struct GameContextSnapshot;
struct LifecycleTypeSnapshot;
void CaptureGameSchedulerCoroutines(const GameContextSnapshot*,const LifecycleTypeSnapshot*,SchedulerCoroutinesSnapshot*) noexcept;
