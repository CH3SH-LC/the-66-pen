#include "component_attachment.h"
#include <cstring>

namespace ge::component_attachment {
namespace {
constexpr std::uint32_t byte_budget = 128 * 1024, read_budget = 4096;
constexpr std::uint64_t address_end = 0x0000800000000000ULL;
bool Ptr(std::uint64_t p) noexcept { return ge::templates::TemplatePointer(p); }
template<class T> T From(const unsigned char* bytes, std::size_t offset) noexcept {
    T value{}; std::memcpy(&value, bytes + offset, sizeof(value)); return value;
}
struct Reader {
    ReadSource source; ComponentSnapshot& out;
    bool Fail(CaptureCode code) noexcept { out.code = code; return false; }
    bool Read(std::uint64_t p, void* target, std::size_t size) noexcept {
        if (!size || size > 65536 || size > byte_budget - out.bytes_read || out.read_calls >= read_budget)
            return Fail(CaptureCode::limit_exceeded);
        if (p < 0x10000 || p >= address_end || size > address_end - p) return Fail(CaptureCode::invalid_structure);
        ++out.read_calls; out.bytes_read += static_cast<std::uint32_t>(size);
        return source.read(source.context, p, target, size) || Fail(CaptureCode::unreadable);
    }
    template<class T> bool At(std::uint64_t p, std::uint64_t offset, T& value) noexcept {
        if (!Ptr(p) || offset >= address_end - p) return Fail(CaptureCode::invalid_structure);
        return Read(p + offset, &value, sizeof(value));
    }
    bool Compare(std::uint64_t p, const void* target, std::size_t size, unsigned char* buffer) noexcept {
        if (!size) return true;
        return Read(p, buffer, size) && (std::memcmp(target, buffer, size) == 0 || Fail(CaptureCode::unstable));
    }
};
struct Roots {
    std::uint64_t owner_class, set, list;
    std::uint8_t state;
};
bool ReadRoots(Reader& r, std::uint64_t owner, Roots& roots) noexcept {
    if (!r.At(owner, 0, roots.owner_class) || !r.At(owner, 0x30, roots.set) ||
        !r.At(owner, 0x68, roots.list) || !r.At(owner, 0x9c, roots.state)) return false;
    return (Ptr(roots.owner_class) && Ptr(roots.set) && Ptr(roots.list) && roots.set != roots.list) || r.Fail(CaptureCode::invalid_structure);
}
bool SameRoots(const Roots& a, const Roots& b) noexcept {
    return a.owner_class == b.owner_class && a.set == b.set && a.list == b.list && a.state == b.state;
}
bool ReadRow(Reader& r, std::uint64_t pointer, ComponentRow& row) noexcept {
    unsigned char wrapper[0x38]{}, config[0x28]{};
    if (!Ptr(pointer)) return r.Fail(CaptureCode::invalid_structure);
    if (!r.Read(pointer, wrapper, sizeof(wrapper))) return false;
    row.wrapper = pointer; row.wrapper_class = From<std::uint64_t>(wrapper, 0);
    row.config = From<std::uint64_t>(wrapper, 0x28); row.kind = From<std::int32_t>(wrapper, 0x34);
    row.enabled = wrapper[0x30];
    if (!Ptr(row.wrapper_class) || !Ptr(row.config) || row.kind <= 0 ||
        From<std::uint64_t>(wrapper, 0x20) != r.out.owner) return r.Fail(CaptureCode::invalid_structure);
    if (!r.Read(row.config, config, sizeof(config))) return false;
    row.config_class = From<std::uint64_t>(config, 0);
    return (Ptr(row.config_class) && From<std::uint64_t>(config, 0x18) == pointer &&
        From<std::uint64_t>(config, 0x20) == r.out.owner) || r.Fail(CaptureCode::invalid_structure);
}
bool ReadStructures(Reader& r, CaptureWorkspace& w) noexcept {
    auto& o = r.out;
    if (!r.Read(o.set, w.set_header, sizeof(w.set_header)) || !r.Read(o.list, w.list_header, sizeof(w.list_header))) return false;
    if (!Ptr(From<std::uint64_t>(w.set_header, 0)) || !Ptr(From<std::uint64_t>(w.list_header, 0)) ||
        !Ptr(From<std::uint64_t>(w.set_header, 0x18))) return r.Fail(CaptureCode::invalid_structure);
    o.buckets = From<std::uint64_t>(w.set_header, 0x10); o.slots = From<std::uint64_t>(w.set_header, 0x20);
    o.items = From<std::uint64_t>(w.list_header, 0x10);
    const auto count = From<std::int32_t>(w.set_header, 0x28), last = From<std::int32_t>(w.set_header, 0x2c);
    const auto list_count = From<std::int32_t>(w.list_header, 0x18);
    o.set_free_head = From<std::int32_t>(w.set_header, 0x30);
    o.set_version = From<std::uint32_t>(w.set_header, 0x34); o.list_version = From<std::uint32_t>(w.list_header, 0x1c);
    if (count < 0 || last < 0 || count > last || list_count < 0) return r.Fail(CaptureCode::invalid_structure);
    if (last > static_cast<std::int32_t>(kMaxComponents) || list_count > static_cast<std::int32_t>(kMaxComponents))
        return r.Fail(CaptureCode::limit_exceeded);
    o.set_count = static_cast<std::uint32_t>(count); o.set_last_index = static_cast<std::uint32_t>(last);
    o.count = static_cast<std::uint32_t>(list_count);
    std::uint64_t list_capacity = 0;
    if (!r.At(o.items, 0x18, list_capacity)) return false;
    if (list_capacity > kMaxComponents) return r.Fail(CaptureCode::limit_exceeded);
    if (o.count > list_capacity) return r.Fail(CaptureCode::invalid_structure);
    o.list_capacity = static_cast<std::uint32_t>(list_capacity);
    if (o.list_capacity && !r.Read(o.items + 0x20, w.items, o.list_capacity * sizeof(w.items[0]))) return false;
    if (!o.buckets && !o.slots)
        return (!count && !last && o.set_free_head == -1) || r.Fail(CaptureCode::invalid_structure);
    std::uint64_t bucket_capacity = 0, slot_capacity = 0;
    if (!r.At(o.buckets, 0x18, bucket_capacity) || !r.At(o.slots, 0x18, slot_capacity)) return false;
    if (bucket_capacity > kMaxComponents || slot_capacity > kMaxComponents) return r.Fail(CaptureCode::limit_exceeded);
    if (!bucket_capacity || bucket_capacity != slot_capacity || o.set_last_index > slot_capacity)
        return r.Fail(CaptureCode::invalid_structure);
    o.set_capacity = static_cast<std::uint32_t>(bucket_capacity);
    return r.Read(o.buckets + 0x20, w.buckets, o.set_capacity * sizeof(w.buckets[0])) &&
        r.Read(o.slots + 0x20, w.slots, o.set_capacity * sizeof(w.slots[0]));
}
bool Parse(Reader& r, CaptureWorkspace& w) noexcept {
    auto& o = r.out; std::uint32_t seen_count = 0;
    for (std::uint32_t bucket = 0; bucket < o.set_capacity; ++bucket) {
        const auto head = w.buckets[bucket];
        if (head < 0 || head > static_cast<std::int32_t>(o.set_last_index)) return r.Fail(CaptureCode::invalid_structure);
        for (auto index = head - 1; index != -1;) {
            if (index < 0 || index >= static_cast<std::int32_t>(o.set_last_index) || w.seen[index]) return r.Fail(CaptureCode::invalid_structure);
            w.seen[index] = true; const auto& slot = w.slots[index];
            if (slot.hash < 0 || static_cast<std::uint32_t>(slot.hash) % o.set_capacity != bucket || slot.value <= 0)
                return r.Fail(CaptureCode::invalid_structure);
            for (std::uint32_t i = 0; i < seen_count; ++i)
                if (o.kinds[i] == slot.value) return r.Fail(CaptureCode::invalid_structure);
            o.kinds[seen_count++] = slot.value; index = slot.next;
        }
    }
    if (seen_count != o.set_count) return r.Fail(CaptureCode::invalid_structure);
    auto free = o.set_free_head;
    for (std::uint32_t i = o.set_count; i < o.set_last_index; ++i) {
        if (free < 0 || free >= static_cast<std::int32_t>(o.set_last_index) || w.seen[free]) return r.Fail(CaptureCode::invalid_structure);
        w.seen[free] = true; free = w.slots[free].next;
    }
    if (free != -1) return r.Fail(CaptureCode::invalid_structure);
    for (std::uint32_t i = 0; i < o.set_last_index; ++i)
        if (!w.seen[i]) return r.Fail(CaptureCode::invalid_structure);
    // LIST is read independently, even when the SET claims the target is absent.
    for (std::uint32_t i = 0; i < o.count; ++i) {
        if (!ReadRow(r, w.items[i], o.rows[i])) return false;
        for (std::uint32_t j = 0; j < i; ++j)
            if (o.rows[i].kind == o.rows[j].kind || o.rows[i].wrapper == o.rows[j].wrapper ||
                o.rows[i].config == o.rows[j].config) return r.Fail(CaptureCode::invalid_structure);
    }
    if (o.count != o.set_count) return r.Fail(CaptureCode::set_list_disagree);
    for (std::uint32_t i = 0; i < o.count; ++i) {
        bool found = false;
        for (std::uint32_t j = 0; j < o.set_count; ++j) if (o.rows[i].kind == o.kinds[j]) found = true;
        if (!found) return r.Fail(CaptureCode::set_list_disagree);
    }
    return true;
}
bool Recheck(Reader& r, CaptureWorkspace& w) noexcept {
    auto& o = r.out;
    if (!r.Compare(o.set, w.set_header, sizeof(w.set_header), w.compare) ||
        !r.Compare(o.list, w.list_header, sizeof(w.list_header), w.compare)) return false;
    std::uint64_t length = 0;
    if (!r.At(o.items, 0x18, length)) return false;
    if (length != o.list_capacity) return r.Fail(CaptureCode::unstable);
    if (!r.Compare(o.items + 0x20, w.items, o.list_capacity * sizeof(w.items[0]), w.compare)) return false;
    if (o.set_capacity) {
        if (!r.At(o.buckets, 0x18, length)) return false;
        if (length != o.set_capacity) return r.Fail(CaptureCode::unstable);
        if (!r.At(o.slots, 0x18, length)) return false;
        if (length != o.set_capacity) return r.Fail(CaptureCode::unstable);
        if (!r.Compare(o.buckets + 0x20, w.buckets, o.set_capacity * sizeof(w.buckets[0]), w.compare) ||
            !r.Compare(o.slots + 0x20, w.slots, o.set_capacity * sizeof(w.slots[0]), w.compare)) return false;
    }
    for (std::uint32_t i = 0; i < o.count; ++i) {
        ComponentRow row{}; if (!ReadRow(r, o.rows[i].wrapper, row)) return false;
        if (std::memcmp(&row, &o.rows[i], sizeof(row))) return r.Fail(CaptureCode::unstable);
    }
    return r.Compare(o.set, w.set_header, sizeof(w.set_header), w.compare) &&
        r.Compare(o.list, w.list_header, sizeof(w.list_header), w.compare);
}
bool RowIdentity(const ComponentRow& row, const AttachmentEvidence& e) noexcept {
    return row.kind == e.kind && row.wrapper_class == e.wrapper_class && row.config_class == e.config_class;
}
}
void CaptureComponents(ReadSource source, std::uint64_t owner, CaptureWorkspace* work, ComponentSnapshot* out) noexcept {
    if (!out) return;
    std::memset(out, 0, sizeof(*out)); out->code = CaptureCode::invalid_input;
    if (!source.read || !work || !Ptr(owner)) return;
    std::memset(work, 0, sizeof(*work)); out->owner = owner; Reader r{source, *out};
    Roots before{}; if (!ReadRoots(r, owner, before)) return;
    out->owner_class = before.owner_class; out->set = before.set; out->list = before.list; out->owner_state = before.state;
    if (!ReadStructures(r, *work) || !Parse(r, *work) || !Recheck(r, *work)) return;
    Roots after{}; if (!ReadRoots(r, owner, after)) return;
    if (!SameRoots(before, after)) { out->code = CaptureCode::unstable; return; }
    out->code = CaptureCode::complete;
}
void EnsureComponentAttached(ReadSource source, AttachComponent attach, const AttachmentEvidence& e,
    AttachmentWorkspace* work, AttachmentResult* out) noexcept {
    if (!out) return;
    *out = {}; out->code = AttachCode::invalid_evidence;
    if (!e.owner_and_thread_verified || !Ptr(e.owner) || !Ptr(e.owner_class) || !Ptr(e.wrapper_class) ||
        !Ptr(e.config_class) || (e.kind != 17 && e.kind != 33 && e.kind != 35) || !work || !source.read) return;
    CaptureComponents(source, e.owner, &work->capture, &work->before);
    out->code = AttachCode::before_failed;
    if (work->before.code != CaptureCode::complete) return;
    out->before_verified = true; out->code = AttachCode::identity_mismatch;
    if (work->before.owner_class != e.owner_class) return;
    for (std::uint32_t i = 0; i < work->before.count; ++i) {
        const auto& row = work->before.rows[i];
        if (row.kind != e.kind) continue;
        if (!RowIdentity(row, e)) return;
        out->component = row; out->code = AttachCode::existing; return;
    }
    // Do not start a mutation whose mandatory +1 readback cannot fit our bound.
    out->code = AttachCode::capture_limit;
    if (work->before.count == kMaxComponents) return;
    out->code = AttachCode::missing_binding; if (!attach) return;
    out->attach_called = true; out->outcome_uncertain = true;
    try { out->returned_wrapper = reinterpret_cast<std::uint64_t>(attach(reinterpret_cast<void*>(e.owner), e.kind)); }
    catch (...) {
        out->code = AttachCode::call_exception;
        CaptureComponents(source, e.owner, &work->capture, &work->after);
        out->after_verified = work->after.code == CaptureCode::complete; return;
    }
    CaptureComponents(source, e.owner, &work->capture, &work->after);
    out->code = AttachCode::after_failed;
    if (work->after.code != CaptureCode::complete) return;
    out->after_verified = true;
    const auto& before = work->before; const auto& after = work->after;
    out->code = AttachCode::context_changed;
    if (before.owner_class != after.owner_class || before.set != after.set || before.list != after.list ||
        before.owner_state != after.owner_state) return;
    out->code = AttachCode::null_return; if (!out->returned_wrapper) return;
    out->code = AttachCode::delta_mismatch;
    if (after.count != before.count + 1 || after.set_count != before.set_count + 1) return;
    for (std::uint32_t i = 0; i < before.count; ++i)
        if (std::memcmp(&before.rows[i], &after.rows[i], sizeof(ComponentRow))) return;
    const auto& added = after.rows[before.count];
    if (!RowIdentity(added, e) || added.wrapper != out->returned_wrapper) return;
    out->component = added; out->code = AttachCode::attached_verified;
}
}
