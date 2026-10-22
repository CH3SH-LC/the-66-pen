#include "../component_attachment.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <vector>

using namespace ge::component_attachment;
namespace {
constexpr std::uint64_t owner = 0x100000, set = 0x110000, list = 0x120000;
constexpr std::uint64_t buckets = 0x130000, slots = 0x140000, items = 0x150000;
constexpr std::uint64_t owner_class = 0x800000, wrapper_class = 0x810000;
constexpr std::uint64_t bag_class = 0x820000, shop_class = 0x830000;
int checks = 0;
void Check(bool ok, const char* name) {
    ++checks; if (!ok) { std::fprintf(stderr, "FAIL: %s\n", name); std::exit(1); }
}
enum class Behavior { normal, set_only, list_only, null_return, wrong_return,
    wrong_config_class, broken_backref, old_changed, owner_changed, partial_read,
    throw_before, throw_after };
struct Memory {
    std::vector<unsigned char> bytes = std::vector<unsigned char>(0x100000);
    std::uint64_t fail_address = 0, watch_address = 0, change_address = 0;
    std::uint32_t reads = 0, attach_calls = 0, watch_hits = 0, new_value = 0;
    std::uint8_t new_enabled = 1;
    Behavior behavior = Behavior::normal;
    template<class T> void Put(std::uint64_t address, T value) {
        std::memcpy(bytes.data() + static_cast<std::size_t>(address - owner), &value, sizeof(value));
    }
    template<class T> T Get(std::uint64_t address) const {
        T value{}; std::memcpy(&value, bytes.data() + static_cast<std::size_t>(address - owner), sizeof(value)); return value;
    }
    static bool Read(void* context, std::uint64_t address, void* target, std::size_t size) noexcept {
        auto& m = *static_cast<Memory*>(context); ++m.reads;
        if (address == m.fail_address) return false;
        if (address == m.watch_address && ++m.watch_hits == 2) m.Put(m.change_address, m.new_value);
        if (address < owner || address - owner > m.bytes.size() || size > m.bytes.size() - static_cast<std::size_t>(address - owner)) return false;
        std::memcpy(target, m.bytes.data() + static_cast<std::size_t>(address - owner), size); return true;
    }
    void AddSet(std::int32_t kind) {
        const auto index = Get<std::uint32_t>(set + 0x2c);
        const auto capacity = Get<std::uint64_t>(buckets + 0x18);
        const auto bucket = buckets + 0x20 + (static_cast<std::uint32_t>(kind) % capacity) * 4;
        const NativeSetSlot slot{kind, Get<std::int32_t>(bucket) - 1, kind};
        Put(slots + 0x20 + index * sizeof(slot), slot); Put(bucket, index + 1);
        Put(set + 0x2c, index + 1); Put(set + 0x28, Get<std::uint32_t>(set + 0x28) + 1);
        Put(set + 0x34, Get<std::uint32_t>(set + 0x34) + 1);
    }
    std::uint64_t AddList(std::int32_t kind) {
        const auto index = Get<std::uint32_t>(list + 0x18);
        const std::uint64_t wrapper = 0x160000 + index * 0x100, config = 0x180000 + index * 0x100;
        Put(wrapper, wrapper_class); Put(wrapper + 0x20, owner); Put(wrapper + 0x28, config);
        Put(wrapper + 0x34, kind); Put(wrapper + 0x30, new_enabled);
        Put(config, kind == 33 ? bag_class : shop_class); Put(config + 0x18, wrapper); Put(config + 0x20, owner);
        Put(items + 0x20 + index * 8, wrapper); Put(list + 0x18, index + 1);
        Put(list + 0x1c, Get<std::uint32_t>(list + 0x1c) + 1); return wrapper;
    }
    std::uint64_t Add(std::int32_t kind) { AddSet(kind); return AddList(kind); }
    explicit Memory(std::uint32_t capacity = 7) {
        Put(owner, owner_class); Put(owner + 0x30, set); Put(owner + 0x68, list); Put<std::uint8_t>(owner + 0x9c, 1);
        Put<std::uint64_t>(set, 0x840000); Put(set + 0x10, buckets); Put<std::uint64_t>(set + 0x18, 0x850000);
        Put(set + 0x20, slots); Put<std::int32_t>(set + 0x30, -1);
        Put<std::uint64_t>(list, 0x860000); Put(list + 0x10, items);
        Put<std::uint64_t>(buckets + 0x18, capacity); Put<std::uint64_t>(slots + 0x18, capacity); Put<std::uint64_t>(items + 0x18, capacity);
    }
};
Memory* active = nullptr;
void* __cdecl Attach(void* value, std::int32_t kind) {
    auto& m = *active; ++m.attach_calls;
    Check(reinterpret_cast<std::uint64_t>(value) == owner && (kind == 33 || kind == 35), "exact attach(owner,33/35) contract");
    if (m.behavior == Behavior::throw_before) throw std::runtime_error("before attach");
    std::uint64_t wrapper = 0;
    if (m.behavior != Behavior::list_only) m.AddSet(kind);
    if (m.behavior != Behavior::set_only) wrapper = m.AddList(kind);
    if (m.behavior == Behavior::throw_after) throw std::runtime_error("after attach");
    if (m.behavior == Behavior::wrong_config_class) m.Put<std::uint64_t>(m.Get<std::uint64_t>(wrapper + 0x28), 0x870000);
    if (m.behavior == Behavior::broken_backref) m.Put<std::uint64_t>(m.Get<std::uint64_t>(wrapper + 0x28) + 0x20, owner + 8);
    if (m.behavior == Behavior::old_changed) m.Put<std::uint8_t>(0x160000 + 0x30, 0);
    if (m.behavior == Behavior::owner_changed) m.Put<std::uint8_t>(owner + 0x9c, 0);
    if (m.behavior == Behavior::partial_read) m.fail_address = slots + 0x20;
    if (m.behavior == Behavior::null_return) return nullptr;
    return reinterpret_cast<void*>(m.behavior == Behavior::wrong_return ? wrapper + 8 : wrapper);
}
AttachmentWorkspace workspace{};
AttachmentResult result{};
AttachmentEvidence Evidence(std::int32_t kind = 35) { return {owner, owner_class, wrapper_class, kind == 33 ? bag_class : shop_class, kind, true}; }
AttachCode Ensure(Memory& m, AttachmentEvidence e = Evidence(), AttachComponent attach = Attach) {
    active = &m; std::memset(&workspace, 0, sizeof(workspace));
    EnsureComponentAttached({&m, Memory::Read}, attach, e, &workspace, &result); return result.code;
}
void NoCall(const Memory& m) { Check(!m.attach_calls && !result.attach_called && !result.outcome_uncertain, "no attach before verified absence"); }
void Once(const Memory& m) { Check(m.attach_calls == 1 && result.attach_called && result.outcome_uncertain, "at most one attach; retain uncertainty"); }
}
int main() {
    for (const auto kind : {33, 35}) {
        Memory m; m.Add(8);
        Check(Ensure(m, Evidence(kind)) == AttachCode::attached_verified, "bag/shop attached with two-sided delta");
        Check(result.component.kind == kind && result.component.config && result.component.enabled == 1 &&
            workspace.before.count == 1 && workspace.after.count == 2 && workspace.after.set_count == 2, "complete matching component identity");
        Check(result.before_verified && result.after_verified, "both stable captures recorded"); Once(m);
    }
    for (const auto kind : {33, 35}) {
        Memory m; const auto existing = m.Add(kind);
        Check(Ensure(m, Evidence(kind), nullptr) == AttachCode::existing && result.component.wrapper == existing, "existing component reused without attach binding"); NoCall(m);
    }
    {
        Memory m; m.new_enabled = 0;
        Check(Ensure(m) == AttachCode::attached_verified && result.component.enabled == 0, "native enable zero preserved"); Once(m);
    }
    {
        Memory m; m.Put<std::uint64_t>(set + 0x10, 0); m.Put<std::uint64_t>(set + 0x20, 0);
        CaptureComponents({&m, Memory::Read}, owner, &workspace.capture, &workspace.before);
        Check(workspace.before.code == CaptureCode::complete && !workspace.before.count, "unallocated empty set captured independently");
    }
    {
        Memory m(256); for (int kind = 1; kind <= 256; ++kind) m.Add(kind);
        Check(Ensure(m) == AttachCode::existing && workspace.before.count == 256, "full bounded 256 component capture");
        Check(workspace.before.bytes_read < 128 * 1024 && workspace.before.read_calls < 4096, "complete capture fits fixed budgets"); NoCall(m);
    }
    {
        Memory m(256); for (int kind = 100; kind < 356; ++kind) m.Add(kind);
        Check(Ensure(m) == AttachCode::capture_limit, "full capture bound refuses unobservable append"); NoCall(m);
    }
    {
        Memory m; m.AddSet(35);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::set_list_disagree, "set says present list absent"); NoCall(m);
    }
    {
        Memory m; m.AddList(35);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::set_list_disagree, "list says present set absent"); NoCall(m);
    }
    {
        Memory m; m.AddSet(33); m.AddList(35);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::set_list_disagree, "same counts with different kinds refused"); NoCall(m);
    }
    {
        Memory m; m.Add(35); m.Add(35);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::invalid_structure, "duplicate kind refused"); NoCall(m);
    }
    {
        Memory m; m.Add(8); auto slot = m.Get<NativeSetSlot>(slots + 0x20); slot.next = 0; m.Put(slots + 0x20, slot);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::invalid_structure, "set cycle refused"); NoCall(m);
    }
    {
        Memory m; m.Add(8); m.Put<std::int32_t>(set + 0x28, 0);
        Check(Ensure(m) == AttachCode::before_failed, "set count inconsistent with chains"); NoCall(m);
    }
    {
        Memory m; m.Put<std::uint64_t>(items + 0x18, 257);
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::limit_exceeded, "oversized list capacity refused"); NoCall(m);
    }
    {
        Memory m; m.fail_address = buckets + 0x20;
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::unreadable, "partial set read refused"); NoCall(m);
    }
    {
        Memory m; m.watch_address = set; m.change_address = set + 0x34; m.new_value = 77;
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::unstable, "set changed during capture"); NoCall(m);
    }
    {
        Memory m; m.Add(35); m.watch_address = 0x160000; m.change_address = 0x160000; m.new_value = 0x890000;
        Check(Ensure(m) == AttachCode::before_failed && workspace.before.code == CaptureCode::unstable, "wrapper identity changed during capture"); NoCall(m);
    }
    for (const auto kind : {0, 5, 34, 36}) {
        Memory m; auto e = Evidence(); e.kind = kind;
        Check(Ensure(m, e) == AttachCode::invalid_evidence && !m.reads, "only bag/shop allowed"); NoCall(m);
    }
    {
        Memory m; auto e = Evidence(); e.owner_and_thread_verified = false;
        Check(Ensure(m, e) == AttachCode::invalid_evidence && !m.reads, "unverified caller context refused"); NoCall(m);
    }
    {
        Memory m; auto e = Evidence(); e.owner_class += 8;
        Check(Ensure(m, e) == AttachCode::identity_mismatch, "owner class mismatch"); NoCall(m);
    }
    {
        Memory m; m.Add(35); auto e = Evidence(); e.config_class += 8;
        Check(Ensure(m, e) == AttachCode::identity_mismatch, "existing config class mismatch"); NoCall(m);
    }
    {
        Memory m;
        Check(Ensure(m, Evidence(), nullptr) == AttachCode::missing_binding, "missing attach binding for absent component"); NoCall(m);
    }
    for (const auto mode : {Behavior::set_only, Behavior::list_only, Behavior::broken_backref, Behavior::partial_read}) {
        Memory m; m.behavior = mode;
        Check(Ensure(m) == AttachCode::after_failed && !result.after_verified, "partial/inconsistent after-state refused"); Once(m);
    }
    for (const auto mode : {Behavior::wrong_return, Behavior::wrong_config_class, Behavior::old_changed}) {
        Memory m; m.Add(8); m.behavior = mode;
        Check(Ensure(m) == AttachCode::delta_mismatch && result.after_verified, "wrong return/class or changed prior item refused"); Once(m);
    }
    {
        Memory m; m.behavior = Behavior::owner_changed;
        Check(Ensure(m) == AttachCode::context_changed, "owner state changed after native call"); Once(m);
    }
    {
        Memory m; m.behavior = Behavior::null_return;
        Check(Ensure(m) == AttachCode::null_return && result.after_verified && workspace.after.count == 1, "null return with attachment retained as uncertain"); Once(m);
    }
    for (const auto mode : {Behavior::throw_before, Behavior::throw_after}) {
        Memory m; m.behavior = mode;
        Check(Ensure(m) == AttachCode::call_exception && result.after_verified, "exception captured with independent after read");
        Check(workspace.after.count == (mode == Behavior::throw_after ? 1U : 0U), "exception partial registration retained"); Once(m);
    }
    {
        // A deleted slot remains in lastIndex and is accounted for by freeHead.
        Memory m; m.Add(7); m.Add(8);
        m.Put<std::int32_t>(buckets + 0x20, 0); m.Put<std::uint32_t>(set + 0x28, 1); m.Put<std::int32_t>(set + 0x30, 0);
        m.Put(slots + 0x20, NativeSetSlot{-1, -1, 7});
        m.Put(items + 0x20, m.Get<std::uint64_t>(items + 0x28)); m.Put<std::uint32_t>(list + 0x18, 1);
        CaptureComponents({&m, Memory::Read}, owner, &workspace.capture, &workspace.before);
        Check(workspace.before.code == CaptureCode::complete && workspace.before.count == 1 && workspace.before.kinds[0] == 8, "free-slot chain complete capture");
    }
    std::printf("component_attachment_test: %d checks passed; synthetic memory and one-shot stubs only\n", checks);
}
