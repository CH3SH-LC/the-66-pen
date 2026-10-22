#include "currency_action.h"
#include <limits>

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
template<class T> bool read(TemplateReadSource source, std::uint64_t address, T& value) noexcept {
    return source.read && source.read(source.context, address, &value, sizeof(value));
}
bool pointer(TemplateReadSource source, std::uint64_t address, std::uint64_t& value) noexcept {
    return read(source, address, value) && TemplatePointer(value);
}
bool companion_equal(const TemplateCatalogCapture& a, const TemplateCatalogCapture& b) noexcept {
    if (a.companion.row_count != b.companion.row_count) return false;
    for (std::uint32_t i = 0; i < a.companion.row_count; ++i) {
        const auto& x = a.companion_rows[i]; bool found = false;
        for (std::uint32_t j = 0; j < b.companion.row_count; ++j) {
            const auto& y = b.companion_rows[j];
            if (x.key == y.key && x.parent_id == y.parent_id && x.own_id == y.own_id &&
                x.resource == y.resource && x.klass == y.klass &&
                x.guid_domain[0] == y.guid_domain[0] && x.guid_domain[1] == y.guid_domain[1] &&
                x.guid_domain[2] == y.guid_domain[2]) {found = true; break;}
        }
        if (!found) return false;
    }
    return true;
}
}

void ExecuteCurrencyAction(const GameContextSnapshot* current,
    const CurrencyActionReview& review, const CurrencyActionRuntime& runtime,
    TemplateReadSource source, const CurrencyActionBindings& calls, std::string_view name,
    CurrencyActionWorkspace* work, CurrencyActionResult* out) noexcept {
    if (!out) return;
    *out = {}; out->code = CurrencyActionCode::invalid_review;
    out->mainDeltaCode = CatalogCode::incomplete;
    if (!review.expected || !review.pid || !review.tid || runtime.pid != review.pid ||
        runtime.tid != review.tid || runtime.now >= review.deadline || !runtime.codeVerified) return;
    out->code = CurrencyActionCode::invalid_context;
    if (!current || !same_scene(*current, *review.expected)) return;
    out->code = CurrencyActionCode::missing_binding;
    if (!source.read || !work || !calls.create || !calls.stringNewLen ||
        !calls.lookupGroup || !calls.initializeLimits) return;
    CaptureTemplateCatalog(current, source, &work->capture, &work->before);
    out->code = CurrencyActionCode::baseline_capture_failed;
    if (work->before.code != TemplateCaptureCode::complete) return;
    try {
        std::uint64_t groups = 0;
        out->code = CurrencyActionCode::group_unavailable;
        if (!pointer(source, current->global + 0xb0a0, groups)) return;
        out->stage = CurrencyActionStage::group_lookup; out->groupLookupCalled = true;
        const auto group = reinterpret_cast<std::uint64_t>(calls.lookupGroup(reinterpret_cast<void*>(groups), 23));
        if (!TemplatePointer(group)) return;
        std::uint64_t items = 0, dictionary = 0;
        std::int32_t initialized = 0, free = 0;
        out->code = CurrencyActionCode::count_unreadable;
        if (!pointer(source, group + 0x50, items) || !pointer(source, items + 0x38, dictionary) ||
            !read(source, dictionary + 0x3c, initialized) || !read(source, dictionary + 0x38, free) ||
            initialized < 0 || free < 0 || free > initialized) return;
        out->count = static_cast<std::int64_t>(initialized) - free;
        out->stage = CurrencyActionStage::limit_initialization; out->limitInitializationCalled = true;
        calls.initializeLimits();
        std::uint32_t limit = 0; out->code = CurrencyActionCode::limit_unreadable;
        if (!read(source, current->moduleBase + 0x578bf50, limit)) return;
        out->limit = limit; out->code = CurrencyActionCode::count_limit_rejected;
        if (!limit || out->count >= limit) return;
        // A validated name is allocated only after every count gate. The name
        // helper validates UTF8 before invoking the allocator.
        out->stage = CurrencyActionStage::name_allocation;
        const auto named = make_managed_name(calls.stringNewLen, name);
        out->allocationCalled = named.allocationCalled; out->callCode = named.code;
        if (named.code != CallCode::returned) {
            out->code = named.code == CallCode::invalid_name ? CurrencyActionCode::invalid_name :
                CurrencyActionCode::name_allocation_failed; return;
        }
        // Native initialization may have changed the global singleton or asset
        // manager. Never create against a stale manager captured beforehand.
        std::uint64_t global = 0, manager = 0;
        out->code = CurrencyActionCode::context_changed;
        if (!pointer(source, current->moduleBase + kTemplateGlobalSlotRva, global) ||
            global != current->global || !pointer(source, global + 0xa420, manager) ||
            manager != work->before.manager) return;
        out->stage = CurrencyActionStage::resource_creation;
        out->createCalled = true; out->outcomeUncertain = true;
        const auto result = create_currency(calls.create, reinterpret_cast<void*>(manager),
            named.managed_name, {true, out->count, out->limit});
        out->callCode = result.code;
        out->returnedResource = reinterpret_cast<std::uint64_t>(result.resource);
        // Even a null native return can accompany a partial mutation. Always
        // capture afterward; a null return still cannot count as successful.
        CaptureTemplateCatalog(current, source, &work->capture, &work->after);
        out->code = CurrencyActionCode::post_capture_failed;
        if (work->after.code != TemplateCaptureCode::complete) return;
        out->code = CurrencyActionCode::create_returned_null;
        if (!result.resource) return;
        std::uint64_t klass = 0; out->code = CurrencyActionCode::resource_class_unreadable;
        if (!pointer(source, current->moduleBase + 0x57d9ae0, klass)) return;
        out->observedCurrencyClass = klass;
        const auto delta = VerifySingleMainTemplateCreated(MainTemplateView(work->before),
            MainTemplateView(work->after), 11, klass, out->returnedResource);
        out->mainDeltaCode = delta.code; out->code = CurrencyActionCode::main_delta_failed;
        if (delta.code != CatalogCode::verified) return;
        out->mainCatalogVerified = true; out->createdId = delta.added.id;
        out->code = CurrencyActionCode::companion_changed;
        if (!companion_equal(work->before, work->after)) return;
        out->companionCatalogUnchanged = true;
        out->code = CurrencyActionCode::catalog_verified;
    } catch (...) {
        // The surrounding native adapter additionally catches SEH faults. Keep
        // the phase and attempted-call flags; never attempt a second creation.
        out->code = CurrencyActionCode::call_exception;
        if (out->stage == CurrencyActionStage::name_allocation) out->allocationCalled = true;
        if (out->createCalled) CaptureTemplateCatalog(current, source, &work->capture, &work->after);
    }
}
}
