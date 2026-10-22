#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "game_context_snapshot.h"
#include <cmath>
#include <cstring>

// ---------------------------------------------------------------------------------------
// Version-varying offsets.
//
// Every offset that can move between game builds is a macro, so a new build is described by
// its build profile instead of by an edit here. A legacy build (neither profile switch set,
// see the header) keeps exactly the literals this snapshot was verified against; its
// behavior and layout are unchanged. A strict build -- readonly bootstrap or reviewed
// action -- must be handed all of them by its profile header: a missing one is an #error,
// never a silently reused
// stale literal. Offsets that belong to the array/entry layout rather than to the build
// (bucket head, entry base, entry stride and the Entry fields) stay literals on purpose.
#if GS_STRICT_PROFILE
#if !defined(GS_GLOBAL_SLOT_RVA) || !defined(GS_CONTEXT_MANAGER_OFFSET) || \
    !defined(GS_SAVE_MANAGER_OFFSET) || !defined(GS_MANAGER_KEY_OFFSET) || \
    !defined(GS_MANAGER_DICTIONARY_OFFSET) || !defined(GS_CONTEXT_BUCKETS_OFFSET) || \
    !defined(GS_CONTEXT_ENTRIES_OFFSET) || !defined(GS_CONTEXT_ORIGIN_OFFSET) || \
    !defined(GS_CONTEXT_VERSION_OFFSET)
#error "a strict profile requires the global/manager/context offsets from the build profile"
#endif
#if !defined(GS_ENTITY_DICTIONARY_OFFSET) || !defined(GS_ENTITY_BUCKETS_OFFSET) || \
    !defined(GS_ENTITY_ENTRIES_OFFSET) || !defined(GS_ENTITY_VERSION_OFFSET) || \
    !defined(GS_OWNER_ID_OFFSET) || !defined(GS_OWNER_CONTEXT_OFFSET) || \
    !defined(GS_OWNER_CONFIG_OFFSET) || !defined(GS_CONFIG_ID_OFFSET)
#error "a strict profile requires the entity/owner offsets from the build profile"
#endif
#else
#ifndef GS_GLOBAL_SLOT_RVA
#define GS_GLOBAL_SLOT_RVA 0x555fac8
#endif
#ifndef GS_CONTEXT_MANAGER_OFFSET
#define GS_CONTEXT_MANAGER_OFFSET 0xa3c0
#endif
#ifndef GS_SAVE_MANAGER_OFFSET
#define GS_SAVE_MANAGER_OFFSET 0xac50
#endif
#ifndef GS_MANAGER_KEY_OFFSET
#define GS_MANAGER_KEY_OFFSET 0x3c
#endif
#ifndef GS_MANAGER_DICTIONARY_OFFSET
#define GS_MANAGER_DICTIONARY_OFFSET 0x18
#endif
#ifndef GS_CONTEXT_BUCKETS_OFFSET
#define GS_CONTEXT_BUCKETS_OFFSET 0x10
#endif
#ifndef GS_CONTEXT_ENTRIES_OFFSET
#define GS_CONTEXT_ENTRIES_OFFSET 0x30
#endif
#ifndef GS_CONTEXT_ORIGIN_OFFSET
#define GS_CONTEXT_ORIGIN_OFFSET 0x38
#endif
#ifndef GS_ENTITY_DICTIONARY_OFFSET
#define GS_ENTITY_DICTIONARY_OFFSET 0x20
#endif
#ifndef GS_ENTITY_BUCKETS_OFFSET
#define GS_ENTITY_BUCKETS_OFFSET 0x18
#endif
#ifndef GS_ENTITY_ENTRIES_OFFSET
#define GS_ENTITY_ENTRIES_OFFSET 0x28
#endif
#ifndef GS_ENTITY_VERSION_OFFSET
#define GS_ENTITY_VERSION_OFFSET 0x3c
#endif
#ifndef GS_OWNER_ID_OFFSET
#define GS_OWNER_ID_OFFSET 0x1c
#endif
#ifndef GS_OWNER_CONTEXT_OFFSET
#define GS_OWNER_CONTEXT_OFFSET 0xb0
#endif
#ifndef GS_OWNER_CONFIG_OFFSET
#define GS_OWNER_CONFIG_OFFSET 0xa8
#endif
#ifndef GS_CONFIG_ID_OFFSET
#define GS_CONFIG_ID_OFFSET 0x1c
#endif
// GS_CONTEXT_VERSION_OFFSET has no legacy literal: the legacy snapshot never reads it, so
// only the strict branch below references it.
#endif

#if GS_STRICT_PROFILE
// The build profile's own evidence: loaded-function anchors to byte-compare, the return RVAs
// this snapshot is only valid on, and the module bytes that must still be at their default.
#if !defined(GS_PROFILE_ANCHOR_RVAS) || !defined(GS_PROFILE_ANCHOR_BYTES) || \
    !defined(GS_PROFILE_STACK_RVAS) || !defined(GS_PROFILE_HOTFIX_RVAS)
#error "a strict profile requires GS_PROFILE_ANCHOR_RVAS, GS_PROFILE_ANCHOR_BYTES, GS_PROFILE_STACK_RVAS and GS_PROFILE_HOTFIX_RVAS"
#endif
constexpr std::uint32_t kAnchorRvas[] = { GS_PROFILE_ANCHOR_RVAS };
constexpr unsigned char kAnchorBytes[][32] = { GS_PROFILE_ANCHOR_BYTES };
constexpr std::size_t kAnchorCount = sizeof(kAnchorRvas) / sizeof(kAnchorRvas[0]);
// A row shorter than 32 initializers is zero-filled by the language, and the comparison
// below then fails against real memory -- closed, but the profile must be exactly 32 bytes
// per row. Lengths are bounded so the watch lists cannot grow into a hidden read budget.
static_assert(sizeof(kAnchorBytes[0]) == 32, "Each profile anchor row is exactly 32 bytes");
static_assert(sizeof(kAnchorBytes) / sizeof(kAnchorBytes[0]) == kAnchorCount, "One byte row per anchor RVA");
static_assert(kAnchorCount >= 1 && kAnchorCount <= 32, "Profile anchor count is bounded");
constexpr std::uint32_t kStackRvas[] = { GS_PROFILE_STACK_RVAS };
constexpr std::size_t kStackRvaCount = sizeof(kStackRvas) / sizeof(kStackRvas[0]);
static_assert(kStackRvaCount >= 1 && kStackRvaCount <= kMaxStack, "Expected return RVAs must fit the captured stack");
constexpr std::uint32_t kHotfixRvas[] = { GS_PROFILE_HOTFIX_RVAS };
constexpr std::size_t kHotfixCount = sizeof(kHotfixRvas) / sizeof(kHotfixRvas[0]);
static_assert(kHotfixCount >= 1 && kHotfixCount <= 64, "Profile hotfix watch list is bounded");
#endif

namespace {
constexpr std::uint32_t kBudget = kSnapshotReadBudget;
constexpr std::uint32_t kMaxEntries = kSnapshotDictionaryCapacity;
constexpr std::uint64_t kGlobalSlot = GS_GLOBAL_SLOT_RVA;

bool GuardedCopy(void* target, const void* source, std::size_t size) noexcept {
    __try { std::memcpy(target, source, size); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

struct Reader {
    GameContextSnapshot* output;
    std::uint64_t maximum;

    bool Fail(GameSnapshotStatus status) noexcept {
        output->lastReadStatus = status;
        return false;
    }
    bool Object(std::uint64_t address) const noexcept {
        return address >= 0x10000 && address <= maximum && (address & 7) == 0;
    }
    bool Read(std::uint64_t address, void* target, std::size_t size) noexcept {
        if (!size || size > kBudget || output->bytesRead > kBudget - size || output->readCalls >= kSnapshotReadCalls)
            return Fail(GS_LIMIT_EXCEEDED);
        ++output->readCalls;
        output->bytesRead += static_cast<std::uint32_t>(size);
        if (address < 0x10000 || address > maximum || size - 1 > maximum - address)
            return Fail(GS_UNREADABLE);
        const std::uint64_t end = address + size;
        for (std::uint64_t cursor = address; cursor < end;) {
            MEMORY_BASIC_INFORMATION region{};
            if (VirtualQuery(reinterpret_cast<const void*>(cursor), &region, sizeof(region)) != sizeof(region) ||
                region.State != MEM_COMMIT || (region.Protect & (PAGE_GUARD | PAGE_NOACCESS))) return Fail(GS_UNREADABLE);
            const DWORD protection = region.Protect & 0xff;
            if (protection != PAGE_READONLY && protection != PAGE_READWRITE && protection != PAGE_WRITECOPY &&
                protection != PAGE_EXECUTE_READ && protection != PAGE_EXECUTE_READWRITE && protection != PAGE_EXECUTE_WRITECOPY)
                return Fail(GS_UNREADABLE);
            const std::uint64_t begin = reinterpret_cast<std::uint64_t>(region.BaseAddress);
            if (region.RegionSize > maximum - begin) return Fail(GS_UNREADABLE);
            const std::uint64_t next = begin + region.RegionSize;
            if (next <= cursor) return Fail(GS_UNREADABLE);
            cursor = next < end ? next : end;
        }
        return GuardedCopy(target, reinterpret_cast<const void*>(address), size) || Fail(GS_UNREADABLE);
    }
    template<class T> bool At(std::uint64_t object, std::uint64_t offset, T& value) noexcept {
        if (object > maximum || offset > maximum - object) return Fail(GS_UNREADABLE);
        return Read(object + offset, &value, sizeof(value));
    }
};

#if defined(GS_READ_LEVEL_METADATA) && GS_READ_LEVEL_METADATA
#if !GS_STRICT_PROFILE || !defined(GS_LEVEL_GATE_MANAGER_OFFSET) || !defined(GS_LEVEL_GATE_OBJECT_OFFSET) || !defined(GS_LEVEL_MODE_MANAGER_OFFSET) || !defined(GS_LEVEL_MODE_OFFSET) || !defined(GS_LEVEL_MODE_REQUIRED) || !defined(GS_LEVEL_MANAGER_OFFSET) || !defined(GS_LEVEL_EDITING_OFFSET) || !defined(GS_LEVEL_ID_OFFSET)
#error "Level observation requires a complete strict versioned layout"
#endif
struct LevelObservation {
    std::uint64_t gateManager, gateObject, modeManager, levelManager;
    std::uint32_t mode, levelId;
    unsigned char editing;
};
bool ReadLevelObservation(Reader& reader, LevelObservation& value) noexcept {
    const auto global = reader.output->global;
    if (!reader.At(global, GS_LEVEL_GATE_MANAGER_OFFSET, value.gateManager) || !reader.Object(value.gateManager) ||
        !reader.At(value.gateManager, GS_LEVEL_GATE_OBJECT_OFFSET, value.gateObject) || !reader.Object(value.gateObject) ||
        !reader.At(global, GS_LEVEL_MODE_MANAGER_OFFSET, value.modeManager) || !reader.Object(value.modeManager) ||
        !reader.At(global, GS_LEVEL_MANAGER_OFFSET, value.levelManager) || !reader.Object(value.levelManager))
        return reader.Fail(GS_INVALID_STRUCTURE);
    if (!reader.At(value.modeManager, GS_LEVEL_MODE_OFFSET, value.mode) ||
        !reader.At(value.levelManager, GS_LEVEL_EDITING_OFFSET, value.editing) ||
        !reader.At(value.levelManager, GS_LEVEL_ID_OFFSET, value.levelId)) return false;
    return (value.mode == GS_LEVEL_MODE_REQUIRED && value.editing != 0 && value.levelId != 0) || reader.Fail(GS_INVALID_STRUCTURE);
}
bool SameLevelObservation(const LevelObservation& a, const LevelObservation& b) noexcept {
    return a.gateManager == b.gateManager && a.gateObject == b.gateObject && a.modeManager == b.modeManager &&
        a.levelManager == b.levelManager && a.mode == b.mode && a.editing == b.editing && a.levelId == b.levelId;
}
#endif

struct Dictionary {
    std::uint64_t address, buckets, entries, bucketLength, entryLength;
    std::uint32_t bucketOffset, entryOffset;
};
struct Entry {
    std::int32_t hash, next;
    std::uint32_t key, padding;
    std::uint64_t value;
};
static_assert(sizeof(Entry) == 24, "1558dc90 and16727700 entry stride");

bool LoadDictionary(Reader& reader, std::uint64_t address, std::uint32_t bucketOffset,
    std::uint32_t entryOffset, std::uint32_t limit, Dictionary& result) noexcept {
    result = {};
    result.address = address; result.bucketOffset = bucketOffset; result.entryOffset = entryOffset;
    if (!reader.Object(address)) return reader.Fail(GS_INVALID_STRUCTURE);
    if (!reader.At(address, bucketOffset, result.buckets) || !reader.At(address, entryOffset, result.entries)) return false;
    if (!result.buckets && !result.entries) return true;
    if (!reader.Object(result.buckets) || !reader.Object(result.entries)) return reader.Fail(GS_INVALID_STRUCTURE);
    if (!reader.At(result.buckets, 0x18, result.bucketLength) || !reader.At(result.entries, 0x18, result.entryLength)) return false;
    if (result.bucketLength > limit || result.entryLength > limit) return reader.Fail(GS_LIMIT_EXCEEDED);
    if (!result.bucketLength || !result.entryLength) return reader.Fail(GS_INVALID_STRUCTURE);
    return true;
}

void SampleOwner(Reader& reader, const Entry& entry) noexcept {
    auto& output = *reader.output;
    if (output.entityCaptured == kMaxEntities) { output.flags |= GS_ENTITIES_TRUNCATED; return; }
    auto& entity = output.entities[output.entityCaptured++];
    entity.owner = entry.value; entity.dictionaryKey = entry.key;
    bool valid = reader.Object(entity.owner);
    if (valid && reader.At(entity.owner, GS_OWNER_ID_OFFSET, entity.id)) {
        entity.flags |= GE_ID_READ;
        if (entity.id == entry.key) entity.flags |= GE_KEY_MATCH;
        else valid = false;
    } else valid = false;
    if (reader.Object(entity.owner) && reader.At(entity.owner, GS_OWNER_CONTEXT_OFFSET, entity.context)) {
        entity.flags |= GE_CONTEXT_READ;
        if (entity.context == output.currentContext) entity.flags |= GE_CONTEXT_MATCH;
        else valid = false;
    } else valid = false;
    if (reader.Object(entity.owner) && reader.At(entity.owner, GS_OWNER_CONFIG_OFFSET, entity.config)) {
        if (!entity.config) entity.flags |= GE_CONFIG_NULL;
        // 1156c6e0:1156c7fa..1156c823 serializes this exact configuration ID.
        else if (reader.Object(entity.config) && reader.At(entity.config, GS_CONFIG_ID_OFFSET, entity.configId)) entity.flags |= GE_CONFIG_ID_READ;
        else valid = false;
    } else valid = false;
    // No guessed transform/component offsets; position remains explicitly absent.
    if (!valid) { ++output.entityRejected; output.flags |= GS_ENTITY_READ_FAILURE; }
}

bool WalkDictionary(Reader& reader, const Dictionary& dictionary, bool contexts) noexcept {
    std::uint64_t visited[kMaxEntries / 64]{};
    auto& output = *reader.output;
    for (std::uint32_t bucket = 0; bucket < dictionary.bucketLength; ++bucket) {
        std::int32_t head = 0;
        if (!reader.At(dictionary.buckets, 0x20 + static_cast<std::uint64_t>(bucket) * 4, head)) return false;
        if (head < 0 || static_cast<std::uint64_t>(head) > dictionary.entryLength) return reader.Fail(GS_INVALID_STRUCTURE);
        for (std::int32_t index = head - 1; index >= 0;) {
            if (static_cast<std::uint64_t>(index) >= dictionary.entryLength) return reader.Fail(GS_INVALID_STRUCTURE);
            const auto slot = static_cast<std::uint32_t>(index);
            const std::uint64_t bit = std::uint64_t{1} << (slot % 64);
            if (visited[slot / 64] & bit) return reader.Fail(GS_INVALID_STRUCTURE);
            visited[slot / 64] |= bit;
            Entry entry{};
            if (!reader.At(dictionary.entries, 0x20 + static_cast<std::uint64_t>(slot) * 24, entry)) return false;
            // Occupancy follows bucket reachability, never a guessed free-entry marker.
            if (entry.hash < 0 || static_cast<std::uint32_t>(entry.hash) % dictionary.bucketLength != bucket || entry.next < -1)
                return reader.Fail(GS_INVALID_STRUCTURE);
            if (contexts) {
                ++output.contextValidEntries;
                if (entry.key == output.activeKey) {
                    ++output.contextMatchingEntries;
                    output.currentContext = entry.value;
                }
            } else {
                ++output.entityValidEntries;
                SampleOwner(reader, entry);
            }
            index = entry.next;
        }
    }
    return true;
}

bool SameDictionary(Reader& reader, const Dictionary& original) noexcept {
    Dictionary current{};
    if (!LoadDictionary(reader, original.address, original.bucketOffset, original.entryOffset, kMaxEntries, current)) return false;
    return current.buckets == original.buckets && current.entries == original.entries &&
        current.bucketLength == original.bucketLength && current.entryLength == original.entryLength;
}

bool VerifyBuild(Reader& reader) noexcept {
    auto& output = *reader.output;
    IMAGE_DOS_HEADER dos{};
    if (!reader.At(output.moduleBase, 0, dos)) return false;
    if (dos.e_magic != IMAGE_DOS_SIGNATURE || dos.e_lfanew < 64 || dos.e_lfanew > 0x100000) return reader.Fail(GS_BUILD_MISMATCH);
    IMAGE_NT_HEADERS64 nt{};
    if (!reader.At(output.moduleBase, static_cast<std::uint32_t>(dos.e_lfanew), nt)) return false;
    output.peTimestamp = nt.FileHeader.TimeDateStamp;
    output.peImageSize = nt.OptionalHeader.SizeOfImage;
#if defined(HR_GAME_TIMESTAMP) && defined(HR_GAME_IMAGE_SIZE) && defined(HR_CONTEXT_ANCHOR) && defined(HR_CONTEXT_ANCHOR_RVA)
    constexpr unsigned char expected[] = { HR_CONTEXT_ANCHOR };
    static_assert(sizeof(expected) >= 16 && sizeof(expected) <= 64, "Use a reviewed16..64 byte anchor");
    if (nt.Signature != IMAGE_NT_SIGNATURE || nt.FileHeader.Machine != IMAGE_FILE_MACHINE_AMD64 ||
        nt.OptionalHeader.Magic != IMAGE_NT_OPTIONAL_HDR64_MAGIC ||
        output.peTimestamp != HR_GAME_TIMESTAMP || output.peImageSize != HR_GAME_IMAGE_SIZE ||
        output.peImageSize <= kGlobalSlot + 8 || HR_CONTEXT_ANCHOR_RVA >= output.peImageSize ||
        sizeof(expected) > output.peImageSize - HR_CONTEXT_ANCHOR_RVA) return reader.Fail(GS_BUILD_MISMATCH);
    unsigned char actual[sizeof(expected)]{};
    if (!reader.Read(output.moduleBase + HR_CONTEXT_ANCHOR_RVA, actual, sizeof(actual))) return false;
    if (std::memcmp(expected, actual, sizeof(expected)) != 0) return reader.Fail(GS_BUILD_MISMATCH);
    output.flags |= GS_BUILD_VERIFIED;
    return true;
#else
    return reader.Fail(GS_BUILD_MISMATCH);
#endif
}

#if GS_STRICT_PROFILE
// The three checks below are the readonly profile's own evidence about the process, and
// every one of them is a checked read bounded by the module image size in the PE header.
// None of them calls a game function; they read the module and the stack this snapshot
// already captured.

// Byte-compare each loaded-function anchor the profile names. Runs after the normal build
// check, and fails as a build mismatch: a moved anchor means this profile describes another
// build.
bool VerifyProfileAnchors(Reader& reader) noexcept {
    auto& output = *reader.output;
    for (std::uint32_t i = 0; i < kAnchorCount; ++i) {
        const std::uint32_t rva = kAnchorRvas[i];
        if (rva >= output.peImageSize || sizeof(kAnchorBytes[0]) > output.peImageSize - rva)
            return reader.Fail(GS_BUILD_MISMATCH);
        unsigned char actual[sizeof(kAnchorBytes[0])]{};
        if (!reader.Read(output.moduleBase + rva, actual, sizeof(actual))) return false;
        if (std::memcmp(actual, kAnchorBytes[i], sizeof(actual)) != 0) return reader.Fail(GS_BUILD_MISMATCH);
    }
    return true;
}

// Every expected module-relative return RVA must be present in the stack captured before
// anything was read. This is what lets the profile's offsets be trusted for this call path
// only; it deliberately runs before the first game object is dereferenced. The captured
// stack stays in the snapshot either way, so a mismatch can be diagnosed from the receipt.
bool VerifyStack(Reader& reader) noexcept {
    auto& output = *reader.output;
    for (std::uint32_t i = 0; i < kStackRvaCount; ++i) {
        if (kStackRvas[i] >= output.peImageSize) return reader.Fail(GS_STACK_MISMATCH);
        bool found = false;
        for (std::uint32_t frame = 0; frame < output.stackCount && !found; ++frame) {
            const std::uint64_t address = output.stack[frame];
            found = address >= output.moduleBase && address - output.moduleBase == kStackRvas[i];
        }
        if (!found) return reader.Fail(GS_STACK_MISMATCH);
    }
    output.flags |= GS_STACK_VERIFIED;
    return true;
}

// The watched module bytes must still be at their default (zero). A patched build is not a
// build this profile has been checked against, even when every anchor still matches.
bool CheckHotfixBytes(Reader& reader) noexcept {
    auto& output = *reader.output;
    for (std::uint32_t i = 0; i < kHotfixCount; ++i) {
        if (kHotfixRvas[i] >= output.peImageSize) return reader.Fail(GS_HOTFIX_ACTIVE);
        unsigned char byte = 0xff;
        if (!reader.Read(output.moduleBase + kHotfixRvas[i], &byte, 1)) return false;
        if (byte != 0) return reader.Fail(GS_HOTFIX_ACTIVE);
    }
    return true;
}
#endif
} // namespace

void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept {
    if (!out) return;
    std::memset(out, 0, sizeof(*out)); // Do not materialize a v2 snapshot on the callback stack.
    out->structSize = sizeof(*out); out->version = kSnapshotVersion;
    out->status = GS_UNREADABLE;
    void* frames[kMaxStack]{};
    out->stackCount = CaptureStackBackTrace(0, kMaxStack, frames, nullptr);
    for (std::uint32_t i = 0; i < out->stackCount; ++i) out->stack[i] = reinterpret_cast<std::uint64_t>(frames[i]);
    if (out->stackCount) out->flags |= GS_STACK_CAPTURED;
    SYSTEM_INFO system{};
    GetSystemInfo(&system);
    Reader reader{out, reinterpret_cast<std::uint64_t>(system.lpMaximumApplicationAddress)};
    out->moduleBase = reinterpret_cast<std::uint64_t>(GetModuleHandleW(nullptr));
    if (!out->moduleBase) { out->status = GS_MODULE_UNAVAILABLE; return; }
    if (!VerifyBuild(reader)) { out->status = out->lastReadStatus; return; }
#if GS_STRICT_PROFILE
    // Anchor, call-path and hotfix evidence first: no game object is dereferenced until the
    // profile has been shown to describe this exact build, this exact call path and an
    // unpatched module.
    if (!VerifyProfileAnchors(reader) || !VerifyStack(reader) || !CheckHotfixBytes(reader)) {
        out->status = out->lastReadStatus; return;
    }
#endif
    if (!reader.At(out->moduleBase, GS_GLOBAL_SLOT_RVA, out->global) || !reader.Object(out->global) ||
        !reader.At(out->global, GS_CONTEXT_MANAGER_OFFSET, out->contextManager) || !reader.At(out->global, GS_SAVE_MANAGER_OFFSET, out->saveManager) ||
        !reader.Object(out->contextManager) || !reader.At(out->contextManager, GS_MANAGER_KEY_OFFSET, out->activeKey) ||
        !reader.At(out->contextManager, GS_MANAGER_DICTIONARY_OFFSET, out->contextDictionary)) {
        out->status = out->lastReadStatus ? out->lastReadStatus : GS_INVALID_STRUCTURE; return;
    }
#if GS_STRICT_PROFILE
    // The strict profiles are verified against context zero only. Any other active key
    // means the walk below would describe a context this profile was never checked against.
    // A reviewed action refuses here too: acting inside another context is not reviewed.
    if (out->activeKey != 0) { out->status = GS_INVALID_STRUCTURE; return; }
#endif
#if defined(GS_READ_LEVEL_METADATA) && GS_READ_LEVEL_METADATA
    LevelObservation levelBefore{};
    if (!ReadLevelObservation(reader, levelBefore)) { out->status = out->lastReadStatus; return; }
#endif
    Dictionary contexts{};
    // da508a0 ->1558dc90: buckets+GS_CONTEXT_BUCKETS_OFFSET, entries+GS_CONTEXT_ENTRIES_OFFSET, int key atentry+8.
    if (!LoadDictionary(reader, out->contextDictionary, GS_CONTEXT_BUCKETS_OFFSET, GS_CONTEXT_ENTRIES_OFFSET, 256, contexts)) { out->status = out->lastReadStatus; return; }
    out->contextBuckets = contexts.buckets; out->contextEntries = contexts.entries;
    out->contextCapacity = static_cast<std::uint32_t>(contexts.entryLength);
#if GS_STRICT_PROFILE
    // Version of the context registry, held locally (no ABI field) and re-read after both
    // dictionary walks.
    std::uint32_t contextVersionBefore = 0;
    if (!reader.At(out->contextDictionary, GS_CONTEXT_VERSION_OFFSET, contextVersionBefore)) { out->status = out->lastReadStatus; return; }
#endif
    if (!WalkDictionary(reader, contexts, true)) { out->status = out->lastReadStatus; return; }
    out->flags |= GS_CONTEXTS_COMPLETE;
    if (!out->contextMatchingEntries) { out->status = GS_CONTEXT_NOT_FOUND; return; }
    if (out->contextMatchingEntries != 1 || !reader.Object(out->currentContext)) { out->status = GS_INVALID_STRUCTURE; return; }
    if (!reader.Read(out->currentContext + GS_CONTEXT_ORIGIN_OFFSET, out->origin, sizeof(out->origin)) ||
        !reader.At(out->currentContext, GS_ENTITY_DICTIONARY_OFFSET, out->entityDictionary)) { out->status = out->lastReadStatus; return; }
    for (float coordinate : out->origin) if (!std::isfinite(coordinate)) { out->status = GS_INVALID_STRUCTURE; return; }
    out->flags |= GS_ORIGIN_READ;
    Dictionary entities{};
    //16727700: buckets+GS_ENTITY_BUCKETS_OFFSET, entries+GS_ENTITY_ENTRIES_OFFSET, int key atentry+8, owner atentry+10.
    if (!LoadDictionary(reader, out->entityDictionary, GS_ENTITY_BUCKETS_OFFSET, GS_ENTITY_ENTRIES_OFFSET, kMaxEntries, entities) ||
        !reader.At(out->entityDictionary, GS_ENTITY_VERSION_OFFSET, out->entityVersionBefore)) { out->status = out->lastReadStatus; return; }
    out->entityBuckets = entities.buckets; out->entityEntries = entities.entries;
    out->entityCapacity = static_cast<std::uint32_t>(entities.entryLength);
    if (!WalkDictionary(reader, entities, false)) { out->status = out->lastReadStatus; return; }
    out->flags |= GS_ENTITIES_COMPLETE;
    std::uint64_t global = 0, manager = 0, dictionary = 0, entityDictionary = 0;
    std::uint32_t key = 0;
#if GS_STRICT_PROFILE
    std::uint32_t contextVersionAfter = 0;
#endif
    if (!reader.At(out->moduleBase, GS_GLOBAL_SLOT_RVA, global) || !reader.At(out->global, GS_CONTEXT_MANAGER_OFFSET, manager) ||
        !reader.At(out->contextManager, GS_MANAGER_DICTIONARY_OFFSET, dictionary) || !reader.At(out->contextManager, GS_MANAGER_KEY_OFFSET, key) ||
        !reader.At(out->currentContext, GS_ENTITY_DICTIONARY_OFFSET, entityDictionary) ||
        !reader.At(out->entityDictionary, GS_ENTITY_VERSION_OFFSET, out->entityVersionAfter)
#if GS_STRICT_PROFILE
        || !reader.At(out->contextDictionary, GS_CONTEXT_VERSION_OFFSET, contextVersionAfter)
#endif
        ) { out->status = out->lastReadStatus; return; }
    if (global != out->global || manager != out->contextManager || dictionary != out->contextDictionary || key != out->activeKey ||
        entityDictionary != out->entityDictionary || out->entityVersionBefore != out->entityVersionAfter
#if GS_STRICT_PROFILE
        || contextVersionBefore != contextVersionAfter
#endif
        || !SameDictionary(reader, contexts) || !SameDictionary(reader, entities)) { out->status = GS_UNSTABLE; return; }
    out->flags |= GS_STRUCTURE_RECHECKED;
#if GS_STRICT_PROFILE
    // The walk must have seen the whole scene, not a truncated or partly rejected one, and
    // the module must still be at its default bytes after it. The flags set above are left
    // exactly as they are, so a refusal still tells the decoder why it happened.
    if (out->flags & GS_ENTITIES_TRUNCATED) { out->status = GS_LIMIT_EXCEEDED; return; }
    if (out->entityCaptured != out->entityValidEntries || out->entityRejected) { out->status = GS_PARTIAL_ENTITIES; return; }
    if (!CheckHotfixBytes(reader)) { out->status = out->lastReadStatus; return; }
#if defined(GS_READ_LEVEL_METADATA) && GS_READ_LEVEL_METADATA
    LevelObservation levelAfter{};
    if (!ReadLevelObservation(reader, levelAfter)) { out->status = out->lastReadStatus; return; }
    if (!SameLevelObservation(levelBefore, levelAfter)) { out->status = GS_UNSTABLE; return; }
    out->reserved = levelAfter.levelId;
    out->flags |= GS_LEVEL_OBSERVED;
#endif
    out->flags |= GS_HOTFIX_DEFAULT_CONFIRMED;
    out->status = GS_OK;
#else
    out->status = out->entityRejected ? GS_PARTIAL_ENTITIES : GS_OK;
#endif
}
