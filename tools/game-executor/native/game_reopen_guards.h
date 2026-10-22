#pragma once
#include <cstdint>
#include <cstddef>
#include "game_context_snapshot.h"
#include "game_level_catalog.h"
#include "game_lifecycle_type.h"
#include "game_scheduler_coroutines.h"
namespace guarddraft {
// Pure core: the caller supplies read-only bytes; no process API or game call exists here.
using ReadBytes=bool(*)(void*,std::uint64_t,void*,std::size_t) noexcept;
enum Status:std::uint32_t {OK=0,INPUT_REFUSED=1,ANCHOR=2,UNREADABLE=3,STRUCTURE=4,LIMIT=5,UNSTABLE=6,HOTFIX=7,UNINITIALIZED=8,UNKNOWN_BRANCH=9};
enum Value:std::uint32_t {UNKNOWN=0,FALSE_VALUE=1,TRUE_VALUE=2};
struct EvidenceStamp {std::uint64_t invocation,processCreation;std::uint32_t processId,reserved;};
// The dispatcher must stamp each freshly captured result; stamping old bytes is NOT freshness proof.
struct Inputs {
 EvidenceStamp current,contextStamp,catalogStamp,typeStamp,schedulerStamp;
 unsigned char diskImageSha256[32];
 const GameContextSnapshot* context;const LevelCatalogSnapshot* catalog;
 const LifecycleTypeSnapshot* type;const SchedulerCoroutinesSnapshot* scheduler;
};
enum LookupRefusalStage:std::uint32_t {LOOKUP_NONE=0,LOOKUP_COMPARER=1,LOOKUP_CAPACITY=2,LOOKUP_COUNTS=3,LOOKUP_CHAIN=4,LOOKUP_VISIT_LIMIT=5,LOOKUP_NOT_FOUND=6,LOOKUP_READ=7};
struct ModeDictionaryDiagnostic {
 std::uint32_t observed,lookupRefusalStage;std::uint64_t bucketCapacity,entryCapacity;
 std::int32_t count,freeCount;std::uint32_t version,visitedEntries;
};
static_assert(sizeof(ModeDictionaryDiagnostic)==40,"mode dictionary diagnostic ABI");
struct Result {
 std::uint32_t structSize,version,status,flags,confirmation,earlyAbort,confirmationReason,earlyReason;
 std::uint64_t invocation,moduleBase,global,currentRecord,modeRecord,modeDictionary,table;
 std::uint32_t levelId,modeId,modeEncoded,xorKey,decoded,tableLength,modeLiveEntries,parserError;
 std::uint32_t schedulerTargetCount,schedulerUnavailableCount,schedulerRows,readCalls,readBytes,recheckCalls,recheckBytes,reserved;
 std::uint32_t schedulerStatus,schedulerFlags,schedulerComplete,reserved2;
 ModeDictionaryDiagnostic modeDiagnostic;
};
static_assert(offsetof(Result,modeDiagnostic)==168 && sizeof(Result)==208,"guard result ABI v2 preserves v1 prefix");
struct Span {std::uint64_t address;std::uint32_t offset,size;};
struct Scratch {unsigned char bytes[131072];Span spans[2048];};
// Caller-owned scratch avoids a large native callback stack; no allocation inside evaluation.
void Evaluate(const Inputs&,ReadBytes,void*,Scratch&,Result&) noexcept;
}

// Captures all four prerequisite snapshots inside one current callback before stamping them.
void CaptureGameReopenGuardBundle(GameContextSnapshot*,LevelCatalogSnapshot*,LifecycleTypeSnapshot*,SchedulerCoroutinesSnapshot*,guarddraft::Result*) noexcept;
