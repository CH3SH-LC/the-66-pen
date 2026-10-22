#include "../item_action.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ge::templates;
namespace {
constexpr std::uint64_t module = 0x140000000ULL, global = 0x100000, manager = 0x120000;
constexpr std::uint64_t pd = 0x130000, cd = 0x140000, pb = 0x150000, pe = 0x160000;
constexpr std::uint64_t cb = 0x180000, ce = 0x190000, controller = 0x200000, controllerClass = 0x210000;
constexpr std::uint64_t countInfo = 0x220000, createInfo = 0x230000, generic = 0x240000;
constexpr std::uint64_t constructor = 0x250000, list = 0x260000, mainClass = 0x310000, companionClass = 0x320000;
constexpr std::uint64_t oldMain = 0x500000, newMain = 0x500100, oldComp = 0x600000, newComp = 0x600100;
constexpr std::uint32_t oldId = 0x42000001, newId = 0x42000002;
constexpr auto name = "MW_API_作物";
int checks = 0;
void Check(bool value, const char* label) {
    ++checks; if (!value) { std::fprintf(stderr, "FAIL: %s\n", label); std::exit(1); }
}
enum class Behavior { success, no_main, wrong_class, old_main_changed, no_companion,
    wrong_parent, wrong_guid, wrong_comp_class, old_comp_changed, partial_post, throw_create };
struct Harness {
    std::vector<unsigned char> memory = std::vector<unsigned char>(0x800000);
    std::uint64_t globalSlot = global, countSlot = 0, createSlot = 0, failAddress = 0;
    std::uint32_t limit = 8, defaultValue = 123, ownId = newId;
    int reads = 0, inits = 0, counts = 0, limits = 0, controllers = 0, allocations = 0, defaults = 0, creates = 0;
    bool badMetadata = false, wrongMethod = false, nullList = false, nullController = false;
    bool initializeCountCaches = true;
    bool nullName = false, changeSourceOnName = false, changeGlobalOnName = false, changeMethodOnName = false;
    bool throwMetadata = false, throwName = false, throwDefault = false;
    std::string order;
    Behavior behavior = Behavior::success;
    template<class T> void Put(std::uint64_t at, T value) { std::memcpy(memory.data() + at - global, &value, sizeof(value)); }
    template<class T> T Get(std::uint64_t at) const { T value{}; std::memcpy(&value, memory.data() + at - global, sizeof(value)); return value; }
    static bool Read(void* context, std::uint64_t at, void* target, std::size_t size) noexcept {
        auto& h = *static_cast<Harness*>(context); ++h.reads;
        if (at == h.failAddress) return false;
        std::uint64_t value = 0; bool slot = true;
        if (at == module + kTemplateGlobalSlotRva) value = h.globalSlot;
        else if (at == module + 0x58ed380) value = h.countSlot;
        else if (at == module + 0x59369e0) value = h.createSlot;
        else if (at == module + 0x5819590) value = controllerClass;
        else if (at == module + 0x57b3610) value = mainClass;
        else if (at == module + 0x57ede90) value = companionClass;
        else slot = false;
        if (slot && size == 8) { std::memcpy(target, &value, 8); return true; }
        if (at == module + 0x578bf8c && size == 4) { std::memcpy(target, &h.limit, 4); return true; }
        if (at < global || at - global > h.memory.size() || size > h.memory.size() - static_cast<std::size_t>(at - global)) return false;
        std::memcpy(target, h.memory.data() + at - global, size); return true;
    }
    void Dictionary(std::uint64_t dict, std::uint64_t buckets, std::uint64_t entries) {
        Put<std::uint64_t>(dict, 0x300000); Put(dict + 0x20, buckets); Put(dict + 0x28, entries);
        Put<std::int32_t>(dict + 0x44, -1); Put<std::uint64_t>(buckets + 0x18, 7); Put<std::uint64_t>(entries + 0x18, 7);
    }
    void Add(std::uint64_t dict, std::uint64_t buckets, std::uint64_t entries, std::uint32_t key, std::uint64_t value) {
        const auto count = Get<std::uint32_t>(dict + 0x38); const auto hash = key & 0x7fffffffU;
        const auto bucket = buckets + 0x20 + (hash % 7) * 4;
        const TemplateNativeEntry e{static_cast<std::int32_t>(hash), Get<std::int32_t>(bucket) - 1, key, 0, value};
        Put(entries + 0x20 + count * sizeof(e), e); Put(bucket, count + 1);
        Put(dict + 0x38, count + 1); Put(dict + 0x3c, Get<std::uint32_t>(dict + 0x3c) + 1);
    }
    void Main(std::uint64_t resource, std::uint32_t id) {
        Put(resource, mainClass); Put(resource + 0x1c, id); Put<std::uint32_t>(resource + 0xb4, 9);
        Add(pd, pb, pe, id, resource);
    }
    void Companion(std::uint64_t resource, std::uint32_t id, std::uint32_t own) {
        Put(resource, companionClass); Put(resource + 0x1c, own); Put(resource + 0xa8, id);
        Put<std::uint32_t>(resource + 0x10, 0); Put<std::uint32_t>(resource + 0x14, 1); Put<std::uint32_t>(resource + 0x18, 4);
        Add(cd, cb, ce, id, resource);
    }
    Harness() {
        Put(global + 0xa420, manager); Put(manager + 0x40, pd); Put(manager + 0x10, cd);
        Put(controller, controllerClass); Put<std::uint64_t>(controller + 0x10, 0);
        Put(countInfo + 0x10, generic); Put<std::uint64_t>(generic + 0x10, 0x330000);
        Put(generic + 0x18, constructor); Put<std::uint64_t>(constructor + 8, module + 0x1000);
        Put<std::uint64_t>(createInfo + 8, module + 0x9b0e0d0); Put<std::int32_t>(list + 0x18, 2);
        Dictionary(pd, pb, pe); Dictionary(cd, cb, ce); Main(oldMain, oldId); Companion(oldComp, oldId, 9);
    }
};
Harness* active = nullptr;
ItemActionResult result{};
void __cdecl Metadata(std::uint32_t index) {
    auto& h = *active; ++h.inits; h.order += 'M'; Check(index == 0x1b911, "only exact UI metadata group initialized");
    if (h.throwMetadata) throw std::runtime_error("metadata");
    h.countSlot = h.badMetadata ? 0x60012345 : countInfo; h.createSlot = createInfo;
    if (h.wrongMethod) h.Put<std::uint64_t>(createInfo + 8, module + 0x1000);
}
void* __cdecl Count(void* m, void* output, void* filter, std::uint8_t first, std::uint8_t second, void* info) {
    auto& h = *active; ++h.counts; h.order += 'Q';
    Check(m == reinterpret_cast<void*>(manager) && !output && !filter && first == 1 && second == 1 &&
        info == reinterpret_cast<void*>(countInfo), "six exact count arguments including initialized MethodInfo");
    // Model the current native count entry's lazy metadata side effect, not an
    // extra action binding or a manual production write to runtime metadata.
    if (h.initializeCountCaches) {
        if (!h.Get<std::uint64_t>(generic + 0x10)) h.Put<std::uint64_t>(generic + 0x10, 0x330000);
        if (!h.Get<std::uint64_t>(generic + 0x18)) h.Put(generic + 0x18, constructor);
    }
    return h.nullList ? nullptr : reinterpret_cast<void*>(list);
}
void __cdecl Limit() { ++active->limits; active->order += 'L'; }
void* __cdecl Controller() {
    auto& h = *active; ++h.controllers; h.order += 'G';
    h.Put(global + 0x26ed0, controller); return h.nullController ? nullptr : reinterpret_cast<void*>(controller);
}
void* __cdecl Allocate(const char* text, std::int32_t length) {
    auto& h = *active; ++h.allocations; h.order += 'N';
    Check(std::string(text, static_cast<std::size_t>(length)) == name, "exact UTF8 name allocation");
    if (h.throwName) throw std::runtime_error("name");
    if (h.changeSourceOnName) h.Put<std::uint64_t>(controller + 0x10, oldMain);
    if (h.changeGlobalOnName) h.globalSlot += 8;
    if (h.changeMethodOnName) h.createSlot += 8;
    return h.nullName ? nullptr : reinterpret_cast<void*>(0x900000);
}
std::uint32_t __cdecl Default() {
    auto& h = *active; ++h.defaults; h.order += 'D';
    Check(result.item.defaultGetterCalled && !result.item.handlerCalled &&
        result.item.exceptionStage == ItemStage::default_getter, "caller sees default progress before call without a false creation flag");
    if (h.throwDefault) throw std::runtime_error("default"); return h.defaultValue;
}
void __cdecl Create(void* c, void* folder, void* text, std::int32_t type, std::int32_t option, std::uint32_t value, void* info) {
    auto& h = *active; ++h.creates; h.order += 'C';
    Check(result.item.handlerCalled && result.item.outcomeUncertain &&
        result.item.exceptionStage == ItemStage::create_handler, "caller sees handler progress before entry for outer SEH recovery");
    Check(c == reinterpret_cast<void*>(controller) && !folder && text == reinterpret_cast<void*>(0x900000) &&
        type == 0 && option == 0 && value == h.defaultValue && info == reinterpret_cast<void*>(createInfo), "seven fixed ordinary-item arguments");
    if (h.behavior != Behavior::no_main) h.Main(newMain, newId);
    if (h.behavior != Behavior::no_companion) h.Companion(newComp, newId, h.ownId);
    if (h.behavior == Behavior::wrong_class) h.Put<std::uint64_t>(newMain, mainClass + 8);
    if (h.behavior == Behavior::old_main_changed) h.Put<std::uint64_t>(oldMain, mainClass + 8);
    if (h.behavior == Behavior::wrong_parent) h.Put(newComp + 0xa8, oldId);
    if (h.behavior == Behavior::wrong_guid) h.Put<std::uint32_t>(newComp + 0x18, 3);
    if (h.behavior == Behavior::wrong_comp_class) h.Put<std::uint64_t>(newComp, companionClass + 8);
    if (h.behavior == Behavior::old_comp_changed) h.Put<std::uint32_t>(oldComp + 0x1c, 8);
    if (h.behavior == Behavior::partial_post) h.failAddress = ce + 0x20;
    if (h.behavior == Behavior::throw_create) throw std::runtime_error("partial native mutation");
}
GameContextSnapshot Baseline() {
    GameContextSnapshot b{}; b.structSize = sizeof(b); b.version = 1; b.status = GS_OK; b.flags = 1951;
    b.moduleBase = module; b.global = global; b.peImageSize = 0x20000000; b.peTimestamp = 123;
    b.currentContext = 0x270000; b.contextManager = 0x280000; b.saveManager = 0x290000; b.reserved = 1073741842;
    b.entityCaptured = b.entityValidEntries = 1; b.entities[0].id = 5; b.entities[0].owner = 0x2a0000;
    b.entities[0].context = b.currentContext; return b;
}
ItemActionWorkspace workspace{};
struct Invocation {
    GameContextSnapshot current = Baseline(), expected = current;
    ItemActionReview review{42, 73, 200, &expected}; ItemActionRuntime runtime{42, 73, 100, true};
    ItemActionBindings calls{Metadata, Count, Limit, Controller, Allocate, Create, Default};
    ItemActionCode Run(Harness& h, std::string_view text = name) {
        active = &h; std::memset(&workspace, 0, sizeof(workspace));
        ExecuteItemAction(&current, review, runtime, {&h, Harness::Read}, calls, text, &workspace, &result); return result.code;
    }
};
void NoCreate(const Harness& h) { Check(!h.creates && !result.createCalled && !result.outcomeUncertain, "no creation attempt before all gates"); }
void OneCreate(const Harness& h) { Check(h.creates == 1 && result.createCalled && result.outcomeUncertain, "one creation attempt, never retried, acceptance remains limited"); }
}
int main() {
    for (const auto own : {newId, 7U}) {
        Harness h; Invocation i; h.ownId = own;
        Check(i.Run(h) == ItemActionCode::catalog_verified, "main and companion plus one verified");
        Check(h.order == "MQLGNDC" && h.inits == 1 && h.counts == 1 && h.controllers == 1, "fixed initialization and call order");
        Check(result.createdId == newId && result.createdResource == newMain && result.companionOwnId == own &&
            result.companionResource == newComp && result.mainCatalogVerified && result.companionCatalogVerified, "actual independent identities retained");
        Check(result.count == 2 && result.limit == 8 && workspace.after.primary.row_count == 2 && workspace.after.companion.row_count == 2, "native count and both full catalog captures"); OneCreate(h);
        Check(result.observedMainClass == mainClass && result.observedCompanionClass == companionClass,
            "observed native classes retained for independent receipt verification");
    }
    for (const auto limit : {0U, 1U, 2U}) {
        Harness h; Invocation i; h.limit = limit;
        Check(i.Run(h) == ItemActionCode::count_limit_rejected && h.order == "MQL", "limit checked before controller allocation"); NoCreate(h);
    }
    for (int mask = 1; mask <= 3; ++mask) {
        Harness h; Invocation i;
        if (mask & 1) h.Put<std::uint64_t>(generic + 0x10, 0);
        if (mask & 2) h.Put<std::uint64_t>(generic + 0x18, 0);
        Check(i.Run(h) == ItemActionCode::catalog_verified && h.order == "MQLGNDC" && h.counts == 1,
            "native count may populate either or both initially-null generic caches");
        OneCreate(h);
    }
    for (int mask = 1; mask <= 3; ++mask) {
        Harness h; Invocation i; h.initializeCountCaches = false;
        if (mask & 1) h.Put<std::uint64_t>(generic + 0x10, 0);
        if (mask & 2) h.Put<std::uint64_t>(generic + 0x18, 0);
        Check(i.Run(h) == ItemActionCode::metadata_unavailable && h.order == "MQ" && !h.limits,
            "count returning without populating required generic caches refuses creation");
        NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i;
        if (reason == 0) h.Put<std::uint64_t>(generic + 0x10, 1);
        if (reason == 1) h.Put<std::uint64_t>(generic + 0x18, 1);
        if (reason == 2) h.Put<std::uint64_t>(constructor + 8, module - 1);
        Check(i.Run(h) == ItemActionCode::metadata_unavailable && !h.counts,
            "non-null invalid generic metadata remains rejected before count");
        NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i; h.badMetadata = reason == 0; h.wrongMethod = reason == 1;
        if (reason == 2) h.Put<std::uint64_t>(countInfo + 0x10, 0);
        Check(i.Run(h) == ItemActionCode::metadata_unavailable && !h.counts, "encoded or wrong or incomplete metadata rejected"); NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i; h.nullList = reason == 0;
        if (reason == 1) h.Put<std::int32_t>(list + 0x18, -1);
        if (reason == 2) h.failAddress = list + 0x18;
        Check(i.Run(h) == ItemActionCode::count_unreadable && !h.limits, "invalid count stops before limit init"); NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i; h.nullController = reason == 0;
        if (reason == 1) h.Put<std::uint64_t>(controller, controllerClass + 8);
        if (reason == 2) h.Put<std::uint64_t>(controller + 0x10, oldMain);
        Check(i.Run(h) == ItemActionCode::controller_unavailable && !h.allocations, "missing wrong-class or clone controller refused"); NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i; h.changeSourceOnName = reason == 0; h.changeGlobalOnName = reason == 1; h.changeMethodOnName = reason == 2;
        Check(i.Run(h) == ItemActionCode::context_changed && !h.defaults, "fresh verification after allocation prevents stale creation"); NoCreate(h);
    }
    for (int reason = 0; reason < 4; ++reason) {
        Harness h; Invocation i;
        if (reason == 0) ++i.runtime.pid; if (reason == 1) ++i.runtime.tid;
        if (reason == 2) i.runtime.now = i.review.deadline; if (reason == 3) i.runtime.codeVerified = false;
        Check(i.Run(h) == ItemActionCode::invalid_review && !h.reads && h.order.empty(), "review gate before reads and native calls"); NoCreate(h);
    }
    {
        Harness h; Invocation i; i.current.reserved++;
        Check(i.Run(h) == ItemActionCode::invalid_context && !h.reads, "strict current level checked"); NoCreate(h);
    }
    {
        Harness h; Invocation i; i.calls.initializeMetadata = nullptr;
        Check(i.Run(h) == ItemActionCode::missing_binding && !h.reads, "metadata binding required"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.failAddress = ce + 0x20;
        Check(i.Run(h) == ItemActionCode::baseline_capture_failed && h.order.empty(), "partial baseline cannot initialize or mutate"); NoCreate(h);
    }
    {
        Harness h; Invocation i; h.failAddress = module + 0x578bf8c;
        Check(i.Run(h) == ItemActionCode::limit_unreadable && !h.controllers, "unknown limit stops controller creation"); NoCreate(h);
    }
    {
        Harness h; Invocation i;
        Check(i.Run(h, "") == ItemActionCode::invalid_name && h.order.empty(), "invalid name before any native initialization"); NoCreate(h);
    }
    for (int reason = 0; reason < 3; ++reason) {
        Harness h; Invocation i; h.nullName = reason == 0; h.throwMetadata = reason == 1; h.throwName = reason == 2;
        Check(i.Run(h) == (reason == 0 ? ItemActionCode::name_allocation_failed : ItemActionCode::call_exception), "allocation and initialization failures classified"); NoCreate(h);
    }
    for (int reason = 0; reason < 2; ++reason) {
        Harness h; Invocation i; h.defaultValue = reason == 0 ? 0U : 123U; h.throwDefault = reason == 1;
        Check(i.Run(h) == ItemActionCode::item_call_failed && result.item.defaultGetterCalled, "default getter zero or exception refuses handler"); NoCreate(h);
    }
    for (const auto behavior : {Behavior::no_main, Behavior::wrong_class, Behavior::old_main_changed}) {
        Harness h; Invocation i; h.behavior = behavior;
        Check(i.Run(h) == ItemActionCode::main_delta_failed && !result.mainCatalogVerified, "main count class and old-row retention enforced"); OneCreate(h);
    }
    for (const auto behavior : {Behavior::no_companion, Behavior::wrong_guid, Behavior::wrong_comp_class, Behavior::old_comp_changed}) {
        Harness h; Invocation i; h.behavior = behavior;
        Check(i.Run(h) == ItemActionCode::companion_delta_failed && result.mainCatalogVerified && !result.companionCatalogVerified, "companion independent delta and identity gates"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::wrong_parent;
        const auto code = i.Run(h); Check(code == ItemActionCode::post_capture_failed || code == ItemActionCode::companion_delta_failed, "wrong companion parent rejected"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::partial_post;
        Check(i.Run(h) == ItemActionCode::post_capture_failed && !result.mainCatalogVerified, "partial post-capture never accepted"); OneCreate(h);
    }
    {
        Harness h; Invocation i; h.behavior = Behavior::throw_create;
        Check(i.Run(h) == ItemActionCode::item_call_failed && result.item.exceptionStage == ItemStage::create_handler &&
            workspace.after.primary.row_count == 2 && workspace.after.companion.row_count == 2, "throwing void handler still captures partial mutation"); OneCreate(h);
    }
    std::printf("item_action_test: %d checks passed; synthetic memory and host stubs only\n", checks);
}
