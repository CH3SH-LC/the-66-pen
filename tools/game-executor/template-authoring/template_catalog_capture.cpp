#include "template_catalog_capture.h"
#include <cstring>

namespace ge::templates {
namespace {
constexpr std::uint64_t kAddressEnd = 0x0000800000000000ULL;
template<class T> T From(const unsigned char* bytes, std::size_t offset) noexcept {
    T value{}; std::memcpy(&value, bytes + offset, sizeof(value)); return value;
}
struct Reader {
    TemplateReadSource source;
    TemplateCatalogCapture& out;
    bool Fail(TemplateCaptureCode code) noexcept { out.code = code; return false; }
    bool Read(std::uint64_t address, void* data, std::size_t length) noexcept {
        if (!length || length > 65536 || length > kTemplateCaptureByteBudget - out.bytes_read ||
            out.read_calls >= kTemplateCaptureReadBudget) return Fail(TemplateCaptureCode::limit_exceeded);
        if (address < 0x10000 || address >= kAddressEnd || length > kAddressEnd - address)
            return Fail(TemplateCaptureCode::invalid_structure);
        ++out.read_calls; out.bytes_read += static_cast<std::uint32_t>(length);
        return source.read(source.context, address, data, length) || Fail(TemplateCaptureCode::unreadable);
    }
    template<class T> bool At(std::uint64_t p, std::uint64_t offset, T& value) noexcept {
        if (!TemplatePointer(p) || offset >= kAddressEnd - p)
            return Fail(TemplateCaptureCode::invalid_structure);
        return Read(p + offset, &value, sizeof(value));
    }
    bool Block(std::uint64_t p, void* data, std::size_t length) noexcept {
        auto bytes = static_cast<unsigned char*>(data);
        for (std::size_t offset = 0; offset < length;) {
            const auto chunk = length - offset > 65536 ? 65536 : length - offset;
            if (!Read(p + offset, bytes + offset, chunk)) return false;
            offset += chunk;
        }
        return true;
    }
    bool Compare(std::uint64_t p, const void* data, std::size_t length, unsigned char* buffer) noexcept {
        const auto bytes = static_cast<const unsigned char*>(data);
        for (std::size_t offset = 0; offset < length;) {
            const auto chunk = length - offset > 65536 ? 65536 : length - offset;
            if (!Read(p + offset, buffer, chunk)) return false;
            if (std::memcmp(bytes + offset, buffer, chunk)) return Fail(TemplateCaptureCode::unstable);
            offset += chunk;
        }
        return true;
    }
};
struct Roots { std::uint64_t global, manager, primary, companion; };
bool ReadRoots(Reader& r, const GameContextSnapshot& b, Roots& roots) noexcept {
    if (!r.At(b.moduleBase, kTemplateGlobalSlotRva, roots.global)) return false;
    if (roots.global != b.global) return r.Fail(TemplateCaptureCode::unstable);
    if (!r.At(roots.global, 0xa420, roots.manager) || !r.At(roots.manager, 0x40, roots.primary) ||
        !r.At(roots.manager, 0x10, roots.companion)) return false;
    return (TemplatePointer(roots.primary) && TemplatePointer(roots.companion) &&
        roots.primary != roots.companion) || r.Fail(TemplateCaptureCode::invalid_structure);
}
bool ReadDictionary(Reader& r, std::uint64_t pointer, TemplateDictionaryCapture& d,
    TemplateDictionaryWorkspace& w) noexcept {
    d.dictionary = pointer;
    if (!r.Read(pointer, w.header, sizeof(w.header))) return false;
    if (!TemplatePointer(From<std::uint64_t>(w.header, 0))) return r.Fail(TemplateCaptureCode::invalid_structure);
    d.buckets = From<std::uint64_t>(w.header, 0x20); d.entries = From<std::uint64_t>(w.header, 0x28);
    d.comparer = From<std::uint64_t>(w.header, 0x30);
    const auto count = From<std::int32_t>(w.header, 0x38), free = From<std::int32_t>(w.header, 0x40);
    d.version_before = From<std::uint32_t>(w.header, 0x3c); d.free_head = From<std::int32_t>(w.header, 0x44);
    if (count < 0 || free < 0 || free > count || (d.comparer && !TemplatePointer(d.comparer)))
        return r.Fail(TemplateCaptureCode::invalid_structure);
    if (count > static_cast<std::int32_t>(kMaxTemplateRows)) return r.Fail(TemplateCaptureCode::limit_exceeded);
    d.initialized_count = static_cast<std::uint32_t>(count); d.free_count = static_cast<std::uint32_t>(free);
    // A newly constructed empty dictionary has not yet allocated either array.
    if (!d.buckets && !d.entries)
        return (!count && !free && (d.free_head == 0 || d.free_head == -1)) || r.Fail(TemplateCaptureCode::invalid_structure);
    std::uint64_t buckets_length = 0, entries_length = 0;
    if (!r.At(d.buckets, 0x18, buckets_length) || !r.At(d.entries, 0x18, entries_length)) return false;
    if (buckets_length > kMaxTemplateRows || entries_length > kMaxTemplateRows)
        return r.Fail(TemplateCaptureCode::limit_exceeded);
    if (!buckets_length || buckets_length != entries_length || d.initialized_count > entries_length)
        return r.Fail(TemplateCaptureCode::invalid_structure);
    d.bucket_capacity = static_cast<std::uint32_t>(buckets_length);
    d.entry_capacity = static_cast<std::uint32_t>(entries_length);
    return r.Block(d.buckets + 0x20, w.buckets, d.bucket_capacity * sizeof(w.buckets[0])) &&
        r.Block(d.entries + 0x20, w.entries, d.entry_capacity * sizeof(w.entries[0]));
}
bool ReadPrimary(Reader& r, std::uint32_t key, std::uint64_t pointer, TemplateIdentity& row) noexcept {
    unsigned char prefix[0x20]{};
    if (!TemplatePointer(pointer)) return r.Fail(TemplateCaptureCode::invalid_structure);
    if (!r.Read(pointer, prefix, sizeof(prefix)) || !r.At(pointer, 0xb4, row.subtype)) return false;
    row.id = From<std::uint32_t>(prefix, 0x1c); row.resource = pointer;
    row.klass = From<std::uint64_t>(prefix, 0);
    return (row.id == key && row.subtype && TemplatePointer(row.klass)) || r.Fail(TemplateCaptureCode::invalid_structure);
}
bool ReadCompanion(Reader& r, std::uint32_t key, std::uint64_t pointer, TemplateCompanionIdentity& row) noexcept {
    unsigned char prefix[0x20]{};
    if (!TemplatePointer(pointer)) return r.Fail(TemplateCaptureCode::invalid_structure);
    if (!r.Read(pointer, prefix, sizeof(prefix)) || !r.At(pointer, 0xa8, row.parent_id)) return false;
    row.key = key; row.own_id = From<std::uint32_t>(prefix, 0x1c); row.resource = pointer;
    row.klass = From<std::uint64_t>(prefix, 0);
    std::memcpy(row.guid_domain, prefix + 0x10, sizeof(row.guid_domain));
    return (row.parent_id == key && row.own_id && TemplatePointer(row.klass)) || r.Fail(TemplateCaptureCode::invalid_structure);
}
bool Parse(Reader& r, TemplateDictionaryCapture& d, TemplateDictionaryWorkspace& w, bool companion) noexcept {
    for (std::uint32_t bucket = 0; bucket < d.bucket_capacity; ++bucket) {
        const auto head = w.buckets[bucket];
        if (head < 0 || head > static_cast<std::int32_t>(d.initialized_count)) return r.Fail(TemplateCaptureCode::invalid_structure);
        for (auto index = head - 1; index != -1;) {
            if (index < 0 || index >= static_cast<std::int32_t>(d.initialized_count) || w.seen[index])
                return r.Fail(TemplateCaptureCode::invalid_structure);
            w.seen[index] = true; const auto& e = w.entries[index];
            if (e.hash < 0 || static_cast<std::uint32_t>(e.hash) % d.bucket_capacity != bucket || !e.key)
                return r.Fail(TemplateCaptureCode::invalid_structure);
            for (std::uint32_t j = 0; j < d.row_count; ++j) {
                const auto old_key = companion ? r.out.companion_rows[j].key : r.out.primary_rows[j].id;
                const auto old_pointer = companion ? r.out.companion_rows[j].resource : r.out.primary_rows[j].resource;
                if (old_key == e.key || old_pointer == e.value) return r.Fail(TemplateCaptureCode::invalid_structure);
            }
            if (companion) {
                if (!ReadCompanion(r, e.key, e.value, r.out.companion_rows[d.row_count])) return false;
            } else if (!ReadPrimary(r, e.key, e.value, r.out.primary_rows[d.row_count])) return false;
            ++d.row_count; index = e.next;
        }
    }
    if (d.row_count != d.initialized_count - d.free_count) return r.Fail(TemplateCaptureCode::invalid_structure);
    auto free_index = d.free_head;
    for (std::uint32_t n = 0; n < d.free_count; ++n) {
        if (free_index < 0 || free_index >= static_cast<std::int32_t>(d.initialized_count) || w.seen[free_index])
            return r.Fail(TemplateCaptureCode::invalid_structure);
        w.seen[free_index] = true; const auto& e = w.entries[free_index];
        if (e.hash >= 0) return r.Fail(TemplateCaptureCode::invalid_structure);
        free_index = e.next;
    }
    if (d.free_count && free_index != -1) return r.Fail(TemplateCaptureCode::invalid_structure);
    for (std::uint32_t i = 0; i < d.initialized_count; ++i)
        if (!w.seen[i]) return r.Fail(TemplateCaptureCode::invalid_structure);
    return true;
}
bool Recheck(Reader& r, TemplateDictionaryCapture& d, const TemplateDictionaryWorkspace& w,
    bool companion, unsigned char* buffer) noexcept {
    if (!r.Compare(d.dictionary, w.header, sizeof(w.header), buffer)) return false;
    d.version_after = d.version_before;
    if (d.bucket_capacity) {
        std::uint64_t buckets_length = 0, entries_length = 0;
        if (!r.At(d.buckets, 0x18, buckets_length) || !r.At(d.entries, 0x18, entries_length)) return false;
        if (buckets_length != d.bucket_capacity || entries_length != d.entry_capacity) return r.Fail(TemplateCaptureCode::unstable);
        if (!r.Compare(d.buckets + 0x20, w.buckets, d.bucket_capacity * sizeof(w.buckets[0]), buffer) ||
            !r.Compare(d.entries + 0x20, w.entries, d.entry_capacity * sizeof(w.entries[0]), buffer)) return false;
    }
    for (std::uint32_t i = 0; i < d.row_count; ++i) {
        if (companion) {
            const auto& old = r.out.companion_rows[i]; TemplateCompanionIdentity value{};
            if (!ReadCompanion(r, old.key, old.resource, value)) return false;
            if (std::memcmp(&old, &value, sizeof(value))) return r.Fail(TemplateCaptureCode::unstable);
        } else {
            const auto& old = r.out.primary_rows[i]; TemplateIdentity value{};
            if (!ReadPrimary(r, old.id, old.resource, value)) return false;
            if (std::memcmp(&old, &value, sizeof(value))) return r.Fail(TemplateCaptureCode::unstable);
        }
    }
    // Check version again after resource reads, not only before them.
    return r.Compare(d.dictionary, w.header, sizeof(w.header), buffer);
}
}
void CaptureTemplateCatalog(const GameContextSnapshot* baseline, TemplateReadSource source,
    TemplateCatalogCaptureWorkspace* workspace, TemplateCatalogCapture* out) noexcept {
    if (!out) return;
    std::memset(out, 0, sizeof(*out)); out->code = TemplateCaptureCode::invalid_baseline;
    // 2026-10-19: ABI 由 structSize + 编译期 kSnapshotVersion 共同决定；不再写死 v1。
    if (!baseline || !workspace || !source.read || baseline->structSize != sizeof(*baseline) || baseline->version != kSnapshotVersion ||
        baseline->status != GS_OK || (baseline->flags & 1951) != 1951 || (baseline->flags & 96) ||
        baseline->entityRejected || baseline->entityCaptured != baseline->entityValidEntries || !baseline->reserved ||
        !TemplatePointer(baseline->moduleBase) || !TemplatePointer(baseline->global) ||
        baseline->peImageSize <= kTemplateGlobalSlotRva + sizeof(std::uint64_t)) return;
    std::memset(workspace, 0, sizeof(*workspace)); Reader r{source, *out};
    Roots before{}; if (!ReadRoots(r, *baseline, before)) return;
    out->global = before.global; out->manager = before.manager; out->level_id = baseline->reserved;
    if (!ReadDictionary(r, before.primary, out->primary, workspace->primary) ||
        !ReadDictionary(r, before.companion, out->companion, workspace->companion) ||
        !Parse(r, out->primary, workspace->primary, false) || !Parse(r, out->companion, workspace->companion, true) ||
        !Recheck(r, out->primary, workspace->primary, false, workspace->compare) ||
        !Recheck(r, out->companion, workspace->companion, true, workspace->compare)) return;
    Roots after{}; if (!ReadRoots(r, *baseline, after)) return;
    if (std::memcmp(&before, &after, sizeof(before))) { out->code = TemplateCaptureCode::unstable; return; }
    out->code = TemplateCaptureCode::complete;
}
}
