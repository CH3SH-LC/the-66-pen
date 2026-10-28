#pragma once
#include <cstddef>
#include <cstdint>
#include <type_traits>

enum GameSnapshotStatus : std::uint32_t {
    GS_OK = 0, GS_BUILD_MISMATCH = 1, GS_MODULE_UNAVAILABLE = 2,
    GS_UNREADABLE = 3, GS_INVALID_STRUCTURE = 4, GS_LIMIT_EXCEEDED = 5,
    GS_CONTEXT_NOT_FOUND = 6, GS_UNSTABLE = 7, GS_PARTIAL_ENTITIES = 8,
    // Readonly bootstrap only. GS_STACK_MISMATCH: an expected module-relative return RVA
    // was not on the captured stack. GS_HOTFIX_ACTIVE: a watched module byte was not the
    // profile's expected default, before or after the dictionary walks.
    GS_STACK_MISMATCH = 9, GS_HOTFIX_ACTIVE = 10
};
enum GameSnapshotFlags : std::uint32_t {
    GS_BUILD_VERIFIED = 1, GS_ORIGIN_READ = 2, GS_CONTEXTS_COMPLETE = 4,
    GS_ENTITIES_COMPLETE = 8, GS_STRUCTURE_RECHECKED = 16,
    GS_ENTITIES_TRUNCATED = 32, GS_ENTITY_READ_FAILURE = 64, GS_STACK_CAPTURED = 128,
    // Readonly bootstrap only. GS_STACK_VERIFIED: every expected RVA was found.
    // GS_HOTFIX_DEFAULT_CONFIRMED: the watched bytes were zero both before and after the
    // walks; it is set only when both checks pass, so a set bit never contradicts a
    // GS_HOTFIX_ACTIVE status.
    GS_STACK_VERIFIED = 256, GS_HOTFIX_DEFAULT_CONFIRMED = 512, GS_LEVEL_OBSERVED = 1024
};

// Build-profile switches, shared by every translation unit that includes this header.
// Both absent or 0 is the legacy snapshot: the offsets compiled into the .cpp are the
// literals it was verified against, and every check behaves exactly as before. Either
// switch selects a strict profile: all version-varying offsets, the code anchors, the
// expected return RVAs and the hotfix watch bytes must come from the build profile (a
// missing one is a compile error), and the walk refuses to report success on any
// incompleteness it can see. The structure, its size, `version` and the reserved fields are
// identical in every mode.
//
//   GS_BOOTSTRAP_READONLY=1      observation only; an action or HR_ACTION != 0 is refused.
//   GS_REVIEWED_ACTION_PROFILE=1 one reviewed action is allowed, with the same strict
//                                evidence. There is no unreviewed fallback: a strict build
//                                that is missing a profile value does not compile.
#ifndef GS_BOOTSTRAP_READONLY
#define GS_BOOTSTRAP_READONLY 0
#endif
#ifndef GS_REVIEWED_ACTION_PROFILE
#define GS_REVIEWED_ACTION_PROFILE 0
#endif
#ifndef GS_STRICT_PROFILE
#define GS_STRICT_PROFILE (GS_BOOTSTRAP_READONLY || GS_REVIEWED_ACTION_PROFILE)
#endif
#if GS_BOOTSTRAP_READONLY && GS_REVIEWED_ACTION_PROFILE
#error "Choose one profile mode: GS_BOOTSTRAP_READONLY or GS_REVIEWED_ACTION_PROFILE, never both"
#endif
#if GS_BOOTSTRAP_READONLY && defined(HR_ACTION) && HR_ACTION != 0
#error "Readonly bootstrap cannot compile scene actions"
#endif
#if GS_REVIEWED_ACTION_PROFILE && (!defined(HR_ACTION_PROFILE_REVIEWED) || HR_ACTION_PROFILE_REVIEWED != 1 || !defined(HR_ACTION) || HR_ACTION < 1 || (HR_ACTION > 3 && !(HR_ACTION == 4 && defined(HR_REOPEN_ACTION_REVIEWED) && HR_REOPEN_ACTION_REVIEWED == 1)))
#error "Reviewed action profile requires an explicitly reviewed supported action"
#endif
enum GameEntityFlags : std::uint32_t {
    GE_ID_READ = 1, GE_CONFIG_ID_READ = 2, GE_CONTEXT_MATCH = 4,
    GE_KEY_MATCH = 8, GE_POSITION_READ = 16, GE_CONFIG_NULL = 32,
    GE_CONTEXT_READ = 64
};

// The snapshot is a fixed POD shared through a file mapping, so its size IS an ABI: the
// probe, the decoder and the action receipt all take sizeof of it. 32 was enough for the
// levels this project started with, but a level with a full decoration pass holds hundreds
// of entities. When the snapshot cannot hold them all it reports GS_PARTIAL_ENTITIES, and
// every write action then refuses -- the action precondition is a complete snapshot, and
// that is deliberate (acting on a partial view of the scene is how you corrupt one). So
// this bound is the decoration ceiling, not a game limit: the game's own entity dictionary
// is dynamically sized, and newdemo already holds 45 entities.
//
// 512 rather than the exact number needed today, because raising it again costs a rebuild
// of every already-verified artifact, and because the read budget (kBudget in the .cpp)
// has room: a full walk costs roughly 40 bytes per entity.
#ifndef GS_LARGE_SCENE
#define GS_LARGE_SCENE 0
#endif
// Explicit opt-in ABI. Existing component/terrain cards keep the 33208-byte v1
// layout. V2 observes the full scene in one callback; pages are presentation only.
#if GS_LARGE_SCENE
constexpr std::uint32_t kMaxEntities = 4096;
constexpr std::uint32_t kSnapshotVersion = 2;
constexpr std::uint32_t kSnapshotReadBudget = 1024 * 1024;
constexpr std::uint32_t kSnapshotReadCalls = 65536;
// Dictionary storage grows independently of the 4096 live-record ABI.
// A 4059-entity scene crosses the prior 4049-slot allocation.
constexpr std::uint32_t kSnapshotDictionaryCapacity = 16384;
#else
constexpr std::uint32_t kMaxEntities = 512;
constexpr std::uint32_t kSnapshotVersion = 1;
constexpr std::uint32_t kSnapshotReadBudget = 256 * 1024;
constexpr std::uint32_t kSnapshotReadCalls = 16384;
constexpr std::uint32_t kSnapshotDictionaryCapacity = 4096;
#endif
constexpr std::uint32_t kMaxStack = 32;

struct GameEntitySnapshot {
    std::uint64_t owner, config, context;
    std::uint32_t dictionaryKey, id, configId, flags;
    float position[3]; // GE_POSITION_READ is never set: no proven position offset.
    std::uint32_t reserved;
    std::uint64_t reserved2;
};

struct GameContextSnapshot {
    std::uint32_t structSize, version, status, flags;
    std::uint64_t moduleBase, global, contextManager, saveManager;
    std::uint64_t contextDictionary, contextEntries, contextBuckets, currentContext;
    std::uint64_t entityDictionary, entityEntries, entityBuckets;
    std::uint32_t peTimestamp, peImageSize, activeKey, contextCapacity;
    std::uint32_t contextValidEntries, contextMatchingEntries, entityCapacity, entityValidEntries;
    std::uint32_t entityCaptured, entityRejected, bytesRead, readCalls;
    std::uint32_t stackCount, entityVersionBefore, entityVersionAfter, lastReadStatus;
    float origin[3];
    std::uint32_t reserved; // level ID only when GS_LEVEL_OBSERVED; zero otherwise
    std::uint64_t stack[kMaxStack];
    GameEntitySnapshot entities[kMaxEntities];
};

static_assert(sizeof(GameEntitySnapshot) == 64, "Entity snapshot ABI");
static_assert(sizeof(GameContextSnapshot) == 184 + kMaxStack * 8 + kMaxEntities * 64,
    "Context snapshot ABI");
static_assert(std::is_trivial<GameContextSnapshot>::value &&
    std::is_standard_layout<GameContextSnapshot>::value, "Snapshot must remain fixed POD");

// In-process, read-only. No game methods, game writes, heap allocation, or file I/O.
// Missing HR_GAME_TIMESTAMP/HR_GAME_IMAGE_SIZE/HR_CONTEXT_ANCHOR macros fail closed.
// Under GS_STRICT_PROFILE, missing GS_* offset or GS_PROFILE_* macros are a compile error
// instead, and a profile mismatch fails closed before any game object is dereferenced.
void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept;
