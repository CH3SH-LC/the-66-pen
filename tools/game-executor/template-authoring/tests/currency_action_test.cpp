#include "../currency_action.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ge::templates;
namespace {
constexpr std::uint64_t module = 0x140000000ULL, global = 0x100000, manager = 0x120000;
constexpr std::uint64_t primary_dict = 0x130000, companion_dict = 0x140000;
constexpr std::uint64_t primary_buckets = 0x150000, primary_entries = 0x160000;
constexpr std::uint64_t companion_buckets = 0x180000, companion_entries = 0x190000;
constexpr std::uint64_t groups = 0x200000, group = 0x210000, items = 0x220000, counts = 0x230000;
constexpr std::uint64_t old_resource = 0x500000, new_resource = 0x500100, companion = 0x700000;
constexpr std::uint64_t currency_class = 0x340000;
constexpr std::uint32_t old_id = 0x42000001, currency_id = 0x42800001;
constexpr auto name = "MW_API_种田金币";
int checks = 0;
void Check(bool value, const char* label) {
    ++checks; if (!value) { std::fprintf(stderr, "FAIL: %s\n", label); std::exit(1); }
}
enum class Behavior { success, null_return, no_delta, old_changed, companion_changed, partial_post,
    wrong_return, wrong_class, throw_before_create, throw_after_create };
struct Harness {
    // Same dictionary header/array/entry layout as the AJ capture tests.
    std::vector<unsigned char> memory = std::vector<unsigned char>(0x800000);
    std::uint64_t global_slot = global, klass_slot = currency_class, fail_address = 0;
    std::uint32_t limit = 8, read_calls = 0, lookup_calls = 0, init_calls = 0, allocation_calls = 0, create_calls = 0;
    bool null_group = false, null_name = false, throw_group = false, throw_init = false, throw_name = false;
    bool change_global_on_name = false, change_manager_on_name = false;
    Behavior behavior = Behavior::success;
    std::string order;
    template<class T> void Put(std::uint64_t address, T value) {
        std::memcpy(memory.data() + static_cast<std::size_t>(address - global), &value, sizeof(value));
    }
    template<class T> T Get(std::uint64_t address) const {
        T value{}; std::memcpy(&value, memory.data() + static_cast<std::size_t>(address - global), sizeof(value)); return value;
    }
    static bool Read(void* context, std::uint64_t address, void* target, std::size_t size) noexcept {
        auto& h = *static_cast<Harness*>(context); ++h.read_calls;
        if (address == h.fail_address) return false;
        if (address == module + kTemplateGlobalSlotRva && size == 8) { std::memcpy(target, &h.global_slot, 8); return true; }
        if (address == module + 0x578bf50 && size == 4) { std::memcpy(target, &h.limit, 4); return true; }
        if (address == module + 0x57d9ae0 && size == 8) { std::memcpy(target, &h.klass_slot, 8); return true; }
        if (address < global || address - global > h.memory.size() || size > h.memory.size() - static_cast<std::size_t>(address - global)) return false;
        std::memcpy(target, h.memory.data() + static_cast<std::size_t>(address - global), size); return true;
    }
    void Dictionary(std::uint64_t dictionary, std::uint64_t buckets, std::uint64_t entries) {
        Put<std::uint64_t>(dictionary, 0x300000); Put(dictionary + 0x20, buckets); Put(dictionary + 0x28, entries);
        Put<std::int32_t>(dictionary + 0x44, -1); Put<std::uint64_t>(buckets + 0x18, 7); Put<std::uint64_t>(entries + 0x18, 7);
    }
    void Add(std::uint64_t dictionary, std::uint64_t buckets, std::uint64_t entries,
        std::uint32_t key, std::uint64_t pointer) {
        const auto count = Get<std::uint32_t>(dictionary + 0x38);
        const auto hash = key & 0x7fffffffU; const auto bucket = buckets + 0x20 + (hash % 7) * 4;
        const auto previous = Get<std::int32_t>(bucket);
        const TemplateNativeEntry e{static_cast<std::int32_t>(hash), previous - 1, key, 0, pointer};
        Put(entries + 0x20 + count * sizeof(e), e); Put(bucket, count + 1);
        Put(dictionary + 0x38, count + 1); Put(dictionary + 0x3c, Get<std::uint32_t>(dictionary + 0x3c) + 1);
    }
    void AddCurrency() {
        Put(new_resource, currency_class); Put(new_resource + 0x1c, currency_id); Put<std::uint32_t>(new_resource + 0xb4, 11);
        Add(primary_dict, primary_buckets, primary_entries, currency_id, new_resource);
    }
    Harness() {
        Put(global + 0xa420, manager); Put(manager + 0x40, primary_dict); Put(manager + 0x10, companion_dict);
        Put(global + 0xb0a0, groups); Put(group + 0x50, items); Put(items + 0x38, counts);
        Put<std::int32_t>(counts + 0x3c, 3); Put<std::int32_t>(counts + 0x38, 1);
        Dictionary(primary_dict, primary_buckets, primary_entries); Dictionary(companion_dict, companion_buckets, companion_entries);
        Put<std::uint64_t>(old_resource, 0x310000); Put(old_resource + 0x1c, old_id); Put<std::uint32_t>(old_resource + 0xb4, 9);
        Put<std::uint64_t>(companion, 0x320000); Put(companion + 0x1c, old_id); Put(companion + 0xa8, old_id);
        Put<std::uint32_t>(companion + 0x10, 0); Put<std::uint32_t>(companion + 0x14, 1); Put<std::uint32_t>(companion + 0x18, 4);
        Add(primary_dict, primary_buckets, primary_entries, old_id, old_resource);
        Add(companion_dict, companion_buckets, companion_entries, old_id, companion);
    }
};
Harness* active = nullptr;
void* __cdecl Lookup(void* value, std::uint32_t category) {
    auto& h = *active; ++h.lookup_calls; h.order += 'G';
    Check(reinterpret_cast<std::uint64_t>(value) == groups && category == 23, "native group arguments");
    if (h.throw_group) throw std::runtime_error("group");
    return h.null_group ? nullptr : reinterpret_cast<void*>(group);
}
void __cdecl Initialize() {
    auto& h = *active; ++h.init_calls; h.order += 'L';
    if (h.throw_init) throw std::runtime_error("limit");
}
void* __cdecl Allocate(const char* text, std::int32_t length) {
    auto& h = *active; ++h.allocation_calls; h.order += 'N';
    Check(std::string(text, static_cast<std::size_t>(length)) == name, "UTF8 exact name and byte length");
    if (h.throw_name) throw std::runtime_error("name");
    if (h.change_global_on_name) h.global_slot += 8;
    if (h.change_manager_on_name) h.Put<std::uint64_t>(global + 0xa420, manager + 8);
    return h.null_name ? nullptr : reinterpret_cast<void*>(0x900000);
}
void* __cdecl Create(void* value, void* source, std::int32_t subtype, void* managed_name,
    void* callback, std::uint32_t requested_id, std::uint8_t name_flag) {
    auto& h = *active; ++h.create_calls; h.order += 'C';
    Check(reinterpret_cast<std::uint64_t>(value) == manager && !source && subtype == 11 &&
        managed_name == reinterpret_cast<void*>(0x900000) && !callback && !requested_id && !name_flag,
        "seven exact currency create arguments");
    if (h.behavior == Behavior::throw_before_create) throw std::runtime_error("before registration");
    if (h.behavior != Behavior::no_delta) h.AddCurrency();
    if (h.behavior == Behavior::throw_after_create) throw std::runtime_error("after registration");
    if (h.behavior == Behavior::old_changed) h.Put<std::uint64_t>(old_resource, 0x350000);
    if (h.behavior == Behavior::companion_changed) h.Put(companion + 0x1c, old_id + 1);
    if (h.behavior == Behavior::partial_post) h.fail_address = companion_entries + 0x20;
    if (h.behavior == Behavior::wrong_class) h.Put<std::uint64_t>(new_resource, 0x350000);
    if (h.behavior == Behavior::null_return) return nullptr;
    return reinterpret_cast<void*>(h.behavior == Behavior::wrong_return ? old_resource : new_resource);
}
GameContextSnapshot Baseline() {
    GameContextSnapshot b{}; b.structSize = sizeof(b); b.version = 1; b.status = GS_OK; b.flags = 1951;
    b.moduleBase = module; b.global = global; b.peImageSize = 0x6000000; b.peTimestamp = 123;
    b.currentContext = 0x240000; b.contextManager = 0x250000; b.saveManager = 0x260000; b.reserved = 1073741842;
    b.entityCaptured = b.entityValidEntries = 1; b.entities[0].id = 5; b.entities[0].owner = 0x270000;
    b.entities[0].context = b.currentContext; return b;
}
CurrencyActionWorkspace workspace{};
CurrencyActionResult result{};
struct Invocation {
    GameContextSnapshot current = Baseline(), expected = current;
    CurrencyActionReview review{42, 73, 200, &expected};
    CurrencyActionRuntime runtime{42, 73, 100, true};
    CurrencyActionBindings calls{Create, Allocate, Lookup, Initialize};
    CurrencyActionCode Run(Harness& h, std::string_view text = name) {
        active = &h; std::memset(&workspace, 0, sizeof(workspace));
        ExecuteCurrencyAction(&current, review, runtime, {&h, Harness::Read}, calls, text, &workspace, &result);
        return result.code;
    }
};
void NoCreate(const Harness& h) { Check(!h.create_calls && !result.createCalled && !result.outcomeUncertain, "no create or uncertain registration before attempt"); }
void OneCreate(const Harness& h) { Check(h.create_calls == 1 && result.createCalled && result.outcomeUncertain, "single creation attempt never retried"); }
}
int main() {
    {
        Harness h; Invocation i;
        Check(i.Run(h) == CurrencyActionCode::catalog_verified, "success verifies actual captured catalogs");
        Check(h.order == "GLNC" && h.lookup_calls == 1 && h.init_calls == 1 && h.allocation_calls == 1, "ordered single calls");
        Check(result.count == 2 && result.limit == 8 && result.createdId == currency_id && result.returnedResource == new_resource, "native count and created identity");
        Check(result.mainCatalogVerified && result.companionCatalogUnchanged && workspace.after.primary.row_count == 2, "main plus one and companion unchanged"); OneCreate(h);
    }
    for (const auto limit : {0U, 2U, 1U}) {
        Harness h; Invocation i; h.limit = limit;
        Check(i.Run(h) == CurrencyActionCode::count_limit_rejected, "zero full or exceeded limit");
        Check(h.order == "GL" && !h.allocation_calls, "limit refuses before name allocation"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.Put<std::int32_t>(counts + 0x38, 4);
        Check(i.Run(h) == CurrencyActionCode::count_unreadable && !h.init_calls, "invalid count refuses before limit init"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.fail_address = module + 0x578bf50;
        Check(i.Run(h) == CurrencyActionCode::limit_unreadable && !h.allocation_calls, "unreadable limit refuses allocation"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.null_group = true;
        Check(i.Run(h) == CurrencyActionCode::group_unavailable && !h.init_calls, "missing currency group"); NoCreate(h);
    }
    for (int reason = 0; reason != 4; ++reason) {
        Harness h; Invocation i;
        if (reason == 0) ++i.runtime.pid;
        if (reason == 1) ++i.runtime.tid;
        if (reason == 2) i.runtime.now = i.review.deadline;
        if (reason == 3) i.runtime.codeVerified = false;
        Check(i.Run(h) == CurrencyActionCode::invalid_review && !h.read_calls && h.order.empty(), "review guard zero reads and calls"); NoCreate(h);
    }
    for (int reason = 0; reason != 4; ++reason) {
        Harness h; Invocation i;
        if (reason == 0) ++i.current.reserved;
        if (reason == 1) ++i.current.entities[0].id;
        if (reason == 2) i.current.activeKey = 1;
        if (reason == 3) i.current.flags |= GS_ENTITIES_TRUNCATED;
        Check(i.Run(h) == CurrencyActionCode::invalid_context && !h.read_calls && h.order.empty(), "context guard zero reads and calls"); NoCreate(h);
    }
    {
        Harness h; Invocation i; i.calls.create = nullptr;
        Check(i.Run(h) == CurrencyActionCode::missing_binding && !h.read_calls && h.order.empty(), "missing binding before capture"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.fail_address = companion_entries + 0x20;
        Check(i.Run(h) == CurrencyActionCode::baseline_capture_failed && h.order.empty(), "partial baseline refuses all native calls"); NoCreate(h);
    }
    for (const auto text : {std::string_view{}, std::string_view("\xc0\xaf", 2), std::string_view("a\0b", 3)}) {
        Harness h; Invocation i;
        Check(i.Run(h, text) == CurrencyActionCode::invalid_name && !h.allocation_calls, "invalid UTF8 name never allocated"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.null_name = true;
        Check(i.Run(h) == CurrencyActionCode::name_allocation_failed && result.allocationCalled, "null name allocation"); NoCreate(h);
    }
    for (int reason = 0; reason != 2; ++reason) {
        Harness h; Invocation i; h.change_global_on_name = reason == 0; h.change_manager_on_name = reason == 1;
        Check(i.Run(h) == CurrencyActionCode::context_changed && h.allocation_calls == 1, "root identity changed by initialization"); NoCreate(h);
    }
    for (int phase = 0; phase != 3; ++phase) {
        Harness h; Invocation i; h.throw_group = phase == 0; h.throw_init = phase == 1; h.throw_name = phase == 2;
        Check(i.Run(h) == CurrencyActionCode::call_exception, "precreation C++ exception classified");
        Check(static_cast<int>(result.stage) == phase + 1, "exception phase retained");
        if (phase == 2) Check(result.allocationCalled, "throwing allocation recorded as attempted"); NoCreate(h);
    }
    for (const auto behavior : {Behavior::throw_before_create, Behavior::throw_after_create}) {
        Harness h; Invocation i; h.behavior = behavior;
        Check(i.Run(h) == CurrencyActionCode::call_exception && result.stage == CurrencyActionStage::resource_creation, "creation exception retained");
        Check(workspace.after.code == TemplateCaptureCode::complete && workspace.after.primary.row_count == (behavior == Behavior::throw_after_create ? 2U : 1U), "exception captures partial mutation"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::null_return;
        Check(i.Run(h) == CurrencyActionCode::create_returned_null && workspace.after.primary.row_count == 2, "null return with registered resource remains uncertain"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::old_changed;
        Check(i.Run(h) == CurrencyActionCode::main_delta_failed && result.mainDeltaCode == CatalogCode::prior_resource_changed, "changed old primary refused"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::companion_changed;
        Check(i.Run(h) == CurrencyActionCode::companion_changed && result.mainCatalogVerified && !result.companionCatalogUnchanged, "companion mutation rejected independently"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::partial_post;
        Check(i.Run(h) == CurrencyActionCode::post_capture_failed && workspace.after.code == TemplateCaptureCode::unreadable, "partial post-read never accepted"); OneCreate(h);
    }
    for (const auto behavior : {Behavior::no_delta, Behavior::wrong_return, Behavior::wrong_class}) {
        Harness h; Invocation i; h.behavior = behavior;
        Check(i.Run(h) == CurrencyActionCode::main_delta_failed && !result.mainCatalogVerified, "no delta or incorrect result/class rejected"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.fail_address = module + 0x57d9ae0;
        Check(i.Run(h) == CurrencyActionCode::resource_class_unreadable, "missing exact resource class refuses acceptance"); OneCreate(h);
    }
    std::printf("currency_action_test: %d checks passed; synthetic native memory and stub calls only\n", checks);
}
