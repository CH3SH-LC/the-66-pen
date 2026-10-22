#pragma once
#include "template_catalog.h"
#include "../native/game_context_snapshot.h"
#include <cstddef>
#include <cstdint>

// Current 7.1 layout, verified against 173773e0/173770b0. The adapter supplies
// a safe, read-only reader and a freshly verified snapshot on the game thread.
// This module does not resolve symbols, attach, invoke game code, or allocate.
namespace ge::templates {
constexpr std::uint64_t kTemplateGlobalSlotRva = 0x5783de8;
constexpr std::uint32_t kTemplateCaptureByteBudget = 2 * 1024 * 1024;
constexpr std::uint32_t kTemplateCaptureReadBudget = 40000;
using TemplateMemoryRead = bool (*)(void*, std::uint64_t, void*, std::size_t) noexcept;
struct TemplateReadSource { void* context; TemplateMemoryRead read; };
enum class TemplateCaptureCode : std::uint32_t {
    complete = 0, invalid_baseline = 1, unreadable = 2, invalid_structure = 3,
    limit_exceeded = 4, unstable = 5
};
struct TemplateCompanionIdentity {
    std::uint32_t key, parent_id, own_id, guid_domain[3];
    std::uint64_t resource, klass;
};
struct TemplateDictionaryCapture {
    std::uint64_t dictionary, buckets, entries, comparer;
    std::uint32_t bucket_capacity, entry_capacity, initialized_count, free_count;
    std::uint32_t version_before, version_after, row_count;
    std::int32_t free_head;
};
struct TemplateCatalogCapture {
    TemplateCaptureCode code;
    std::uint32_t level_id, bytes_read, read_calls;
    std::uint64_t global, manager;
    TemplateDictionaryCapture primary, companion;
    TemplateIdentity primary_rows[kMaxTemplateRows];
    TemplateCompanionIdentity companion_rows[kMaxTemplateRows];
};
// Raw receipt.py decoding uses this fixed x64 catalogue ABI.
static_assert(sizeof(TemplateIdentity) == 24 && sizeof(TemplateCompanionIdentity) == 40, "catalogue row ABI");
static_assert(sizeof(TemplateDictionaryCapture) == 64 && offsetof(TemplateCatalogCapture, primary_rows) == 160, "catalogue header ABI");
static_assert(sizeof(TemplateCatalogCapture) == 262304, "catalogue receipt ABI");
struct TemplateNativeEntry {
    std::int32_t hash, next;
    std::uint32_t key, padding;
    std::uint64_t value;
};
static_assert(sizeof(TemplateNativeEntry) == 24, "Current native entry layout");
struct TemplateDictionaryWorkspace {
    unsigned char header[0x48];
    std::int32_t buckets[kMaxTemplateRows];
    TemplateNativeEntry entries[kMaxTemplateRows];
    bool seen[kMaxTemplateRows];
};
// Caller-owned workspace avoids a large stack frame and heap allocation.
struct TemplateCatalogCaptureWorkspace {
    TemplateDictionaryWorkspace primary, companion;
    unsigned char compare[65536];
};
void CaptureTemplateCatalog(const GameContextSnapshot* baseline, TemplateReadSource source,
    TemplateCatalogCaptureWorkspace* workspace, TemplateCatalogCapture* out) noexcept;
inline TemplateCatalogView MainTemplateView(const TemplateCatalogCapture& value) noexcept {
    return {value.primary_rows, value.primary.row_count, value.manager, value.level_id,
        value.code == TemplateCaptureCode::complete};
}
// Stability is an interval comparison, not an atomic snapshot. The adapter must
// retain its verified build/hotfix and same-thread guards before any action.
}
