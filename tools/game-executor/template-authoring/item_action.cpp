#include "item_action.h"

namespace ge::templates {
namespace {
bool same_scene(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    constexpr std::uint32_t required = 1951;
    if (a.status != GS_OK || b.status != GS_OK || (a.flags & required) != required ||
        (b.flags & required) != required || a.entityRejected || b.entityRejected ||
        ((a.flags | b.flags) & (GS_ENTITIES_TRUNCATED | GS_ENTITY_READ_FAILURE)) ||
        a.activeKey || b.activeKey || !a.reserved || a.reserved != b.reserved ||
        a.moduleBase != b.moduleBase || a.global != b.global ||
        a.currentContext != b.currentContext || a.contextManager != b.contextManager ||
        a.saveManager != b.saveManager || a.peTimestamp != b.peTimestamp ||
        a.peImageSize != b.peImageSize || !TemplatePointer(a.moduleBase) ||
        !TemplatePointer(a.global) || !TemplatePointer(a.currentContext) ||
        a.entityCaptured != a.entityValidEntries || b.entityCaptured != b.entityValidEntries ||
        a.entityCaptured != b.entityCaptured || a.entityCaptured > kMaxEntities) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i]; const auto& y = b.entities[i];
        if (x.id != y.id || x.owner != y.owner || x.config != y.config ||
            x.context != y.context || x.configId != y.configId ||
            x.dictionaryKey != y.dictionaryKey || x.flags != y.flags) return false;
    }
    return true;
}
template<class T> bool read(TemplateReadSource s, std::uint64_t address, T& v) noexcept {
    return s.read && s.read(s.context, address, &v, sizeof(v));
}
bool pointer(TemplateReadSource s, std::uint64_t address, std::uint64_t& v) noexcept {
    return read(s, address, v) && TemplatePointer(v);
}
bool count_metadata(TemplateReadSource source, const GameContextSnapshot& current,
    std::uint64_t info, bool requireInitialized) noexcept {
    std::uint64_t generic = 0, listClass = 0, constructor = 0, code = 0;
    if (!pointer(source, info + 0x10, generic) ||
        !read(source, generic + 0x10, listClass) ||
        !read(source, generic + 0x18, constructor)) return false;
    // Native 144e26f0 resolves initially-null slots through 51b200(info,0/1).
    // Validate populated slots now, and require both populated after that call.
    if ((!listClass && requireInitialized) || (listClass && !TemplatePointer(listClass))) return false;
    if (!constructor) return !requireInitialized;
    return TemplatePointer(constructor) && read(source, constructor + 8, code) &&
        code >= current.moduleBase && code - current.moduleBase < current.peImageSize;
}
bool roots_current(const GameContextSnapshot& s, TemplateReadSource source,
    std::uint64_t expectedManager) noexcept {
    std::uint64_t global = 0, manager = 0;
    return pointer(source, s.moduleBase + kTemplateGlobalSlotRva, global) && global == s.global &&
        pointer(source, global + 0xa420, manager) && manager == expectedManager;
}
bool controller_current(const GameContextSnapshot& s, TemplateReadSource source,
    std::uint64_t value) noexcept {
    std::uint64_t singleton = 0, klass = 0, expected = 0, parent = 0;
    return TemplatePointer(value) && pointer(source, s.global + 0x26ed0, singleton) &&
        singleton == value && pointer(source, value, klass) &&
        pointer(source, s.moduleBase + 0x5819590, expected) && klass == expected &&
        read(source, value + 0x10, parent) && parent == 0;
}
bool same_companion(const TemplateCompanionIdentity& x, const TemplateCompanionIdentity& y) noexcept {
    return x.key == y.key && x.parent_id == y.parent_id && x.own_id == y.own_id &&
        x.resource == y.resource && x.klass == y.klass &&
        x.guid_domain[0] == y.guid_domain[0] && x.guid_domain[1] == y.guid_domain[1] &&
        x.guid_domain[2] == y.guid_domain[2];
}
bool companion_added(const TemplateCatalogCapture& before, const TemplateCatalogCapture& after,
    std::uint32_t mainId, std::uint64_t klass, ItemActionResult& result) noexcept {
    if (after.companion.row_count != before.companion.row_count + 1) return false;
    for (std::uint32_t i = 0; i < before.companion.row_count; ++i) {
        bool found = false;
        for (std::uint32_t j = 0; j < after.companion.row_count; ++j)
            if (same_companion(before.companion_rows[i], after.companion_rows[j])) { found = true; break; }
        if (!found) return false;
    }
    for (std::uint32_t j = 0; j < after.companion.row_count; ++j) {
        const auto& row = after.companion_rows[j]; bool existed = false;
        for (std::uint32_t i = 0; i < before.companion.row_count; ++i)
            if (row.key == before.companion_rows[i].key) { existed = true; break; }
        if (existed) continue;
        if (row.key != mainId || row.parent_id != mainId || !row.own_id || row.klass != klass ||
            row.guid_domain[0] != 0 || row.guid_domain[1] != 1 || row.guid_domain[2] != 4) return false;
        result.companionOwnId = row.own_id; result.companionResource = row.resource; return true;
    }
    return false;
}
}

void ExecuteItemAction(const GameContextSnapshot* current,
    const ItemActionReview& review, const ItemActionRuntime& runtime, TemplateReadSource source,
    const ItemActionBindings& calls, std::string_view name,
    ItemActionWorkspace* work, ItemActionResult* out) noexcept {
    if (!out) return;
    *out = {}; out->code = ItemActionCode::invalid_review; out->mainDeltaCode = CatalogCode::incomplete;
    if (!review.expected || !review.pid || !review.tid || runtime.pid != review.pid ||
        runtime.tid != review.tid || runtime.now >= review.deadline || !runtime.codeVerified) return;
    out->code = ItemActionCode::invalid_context;
    if (!current || !same_scene(*current, *review.expected)) return;
    out->code = ItemActionCode::missing_binding;
    if (!source.read || !work || !calls.initializeMetadata || !calls.count || !calls.initializeLimits ||
        !calls.controller || !calls.stringNewLen || !calls.create || !calls.readDefault) return;
    out->code = ItemActionCode::invalid_name;
    if (make_managed_name(nullptr, name).code == CallCode::invalid_name) return;
    CaptureTemplateCatalog(current, source, &work->capture, &work->before);
    out->code = ItemActionCode::baseline_capture_failed;
    if (work->before.code != TemplateCaptureCode::complete) return;
    try {
        out->stage = ItemActionStage::metadata_initialization; out->metadataInitializationCalled = true;
        // Exact group used by 9b0e3d0. Initializes both MethodInfos without UI.
        // No manual writes to slots or per-method initialized guards.
        calls.initializeMetadata(0x1b911);
        std::uint64_t countInfo = 0, createInfo = 0, code = 0;
        out->code = ItemActionCode::metadata_unavailable;
        if (!pointer(source, current->moduleBase + 0x58ed380, countInfo) ||
            !pointer(source, current->moduleBase + 0x59369e0, createInfo) ||
            !read(source, createInfo + 8, code) || code != current->moduleBase + 0x9b0e0d0 ||
            !count_metadata(source, *current, countInfo, false)) return;
        out->code = ItemActionCode::context_changed;
        if (!roots_current(*current, source, work->before.manager)) return;
        out->stage = ItemActionStage::count; out->countCalled = true;
        const auto list = reinterpret_cast<std::uint64_t>(calls.count(
            reinterpret_cast<void*>(work->before.manager), nullptr, nullptr, 1, 1,
            reinterpret_cast<void*>(countInfo)));
        out->code = ItemActionCode::metadata_unavailable;
        if (!count_metadata(source, *current, countInfo, true)) return;
        std::int32_t count = 0; out->code = ItemActionCode::count_unreadable;
        if (!TemplatePointer(list) || !read(source, list + 0x18, count) || count < 0) return;
        out->count = count;
        out->stage = ItemActionStage::limit_initialization; out->limitInitializationCalled = true;
        calls.initializeLimits();
        std::uint32_t limit = 0; out->code = ItemActionCode::limit_unreadable;
        if (!read(source, current->moduleBase + 0x578bf8c, limit)) return;
        out->limit = limit; out->code = ItemActionCode::count_limit_rejected;
        if (!limit || out->count >= limit) return;
        out->stage = ItemActionStage::controller_lookup; out->controllerLookupCalled = true;
        const auto controller = reinterpret_cast<std::uint64_t>(calls.controller());
        out->code = ItemActionCode::controller_unavailable;
        if (!controller_current(*current, source, controller)) return;
        out->stage = ItemActionStage::name_allocation; out->allocationCalled = true;
        const auto named = make_managed_name(calls.stringNewLen, name); out->nameCode = named.code;
        out->allocationCalled = named.allocationCalled;
        out->code = ItemActionCode::name_allocation_failed;
        if (named.code != CallCode::returned) return;
        out->code = ItemActionCode::context_changed;
        if (!roots_current(*current, source, work->before.manager) ||
            !controller_current(*current, source, controller)) return;
        std::uint64_t freshCreate = 0;
        if (!pointer(source, current->moduleBase + 0x59369e0, freshCreate) || freshCreate != createInfo ||
            !read(source, createInfo + 8, code) || code != current->moduleBase + 0x9b0e0d0) return;
        out->stage = ItemActionStage::item_creation;
        create_normal_item_into({calls.create, calls.readDefault, reinterpret_cast<void*>(createInfo)},
            {true, reinterpret_cast<void*>(controller), nullptr}, named.managed_name,
            {true, out->count, out->limit}, &out->item);
        out->createCalled = out->item.handlerCalled; out->outcomeUncertain = out->item.outcomeUncertain;
        // A void return or thrown handler still needs a post-capture, with no retry.
        if (out->createCalled) CaptureTemplateCatalog(current, source, &work->capture, &work->after);
        out->code = ItemActionCode::item_call_failed;
        if (out->item.code != ItemCode::call_returned || !out->createCalled) return;
        out->code = ItemActionCode::post_capture_failed;
        if (work->after.code != TemplateCaptureCode::complete) return;
        out->code = ItemActionCode::resource_class_unreadable;
        if (!pointer(source, current->moduleBase + 0x57b3610, out->observedMainClass) ||
            !pointer(source, current->moduleBase + 0x57ede90, out->observedCompanionClass)) return;
        const auto delta = VerifySingleMainTemplateCreated(MainTemplateView(work->before),
            MainTemplateView(work->after), 9, out->observedMainClass);
        out->mainDeltaCode = delta.code; out->code = ItemActionCode::main_delta_failed;
        if (delta.code != CatalogCode::verified) return;
        out->mainCatalogVerified = true; out->createdId = delta.added.id; out->createdResource = delta.added.resource;
        out->code = ItemActionCode::companion_delta_failed;
        if (!companion_added(work->before, work->after, delta.added.id, out->observedCompanionClass, *out)) return;
        out->companionCatalogVerified = true; out->code = ItemActionCode::catalog_verified;
    } catch (...) {
        // Hardware faults additionally belong to the native adapter's SEH gate.
        out->code = ItemActionCode::call_exception;
        if (out->createCalled) CaptureTemplateCatalog(current, source, &work->capture, &work->after);
    }
}
}
