#include "binding_action.h"
#include <cstring>

namespace ge::templates {
namespace {
using ge::component_attachment::ComponentRow;
using ge::component_attachment::ComponentSnapshot;
bool SameScene(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    if (a.structSize != sizeof(a) || b.structSize != sizeof(b) || a.version != 1 || b.version != 1 ||
        a.status != GS_OK || b.status != GS_OK || (a.flags & 1951) != 1951 || (b.flags & 1951) != 1951 ||
        ((a.flags | b.flags) & 96) || a.entityRejected || b.entityRejected || a.activeKey || b.activeKey ||
        !a.reserved || a.reserved != b.reserved || a.moduleBase != b.moduleBase || a.global != b.global ||
        a.currentContext != b.currentContext || a.contextManager != b.contextManager || a.saveManager != b.saveManager ||
        a.peImageSize != b.peImageSize || a.peTimestamp != b.peTimestamp || !TemplatePointer(a.moduleBase) ||
        !TemplatePointer(a.global) || !TemplatePointer(a.currentContext) || a.entityCaptured > kMaxEntities ||
        a.entityCaptured != b.entityCaptured || a.entityCaptured != a.entityValidEntries || b.entityCaptured != b.entityValidEntries) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i]; const auto& y = b.entities[i];
        if (x.owner != y.owner || x.id != y.id || x.config != y.config || x.configId != y.configId ||
            x.context != y.context || x.dictionaryKey != y.dictionaryKey || x.flags != y.flags) return false;
    }
    return true;
}
template<class T> T From(const unsigned char* bytes, std::size_t at) noexcept {
    T value{}; std::memcpy(&value, bytes + at, sizeof(value)); return value;
}
struct Reader {
    TemplateReadSource source;
    std::uint64_t referenceClass;
    std::uint32_t reads = 0, bytes = 0;
    bool Read(std::uint64_t p, void* target, std::size_t size) noexcept {
        constexpr std::uint64_t end = 0x0000800000000000ULL;
        if (!size || size > 65536 || reads >= 4096 || size > 256 * 1024 - bytes ||
            p < 0x10000 || p >= end || size > end - p) return false;
        ++reads; bytes += static_cast<std::uint32_t>(size);
        return source.read(source.context, p, target, size);
    }
    template<class T> bool At(std::uint64_t p, std::uint64_t offset, T& value) noexcept {
        return TemplatePointer(p) && offset < 0x0000800000000000ULL - p && Read(p + offset, &value, sizeof(value));
    }
    bool Reference(std::uint64_t pointer, std::uint32_t& id) noexcept {
        id = 0;
        if (!pointer) return true; // Empty field; no existing template to replace.
        if (!TemplatePointer(pointer)) return false;
        unsigned char prefix[0x20]{};
        if (!Read(pointer, prefix, sizeof(prefix)) || From<std::uint64_t>(prefix, 0) != referenceClass) return false;
        id = From<std::uint32_t>(prefix, 0x1c);
        return From<std::uint32_t>(prefix, 0x18) == ((id >> 30) & 1);
    }
};
bool ReadReference(void* context, void* pointer, std::uint32_t* id) {
    return pointer && id && static_cast<Reader*>(context)->Reference(reinterpret_cast<std::uint64_t>(pointer), *id);
}
bool ReadIndex(void* context, void* entry, std::int32_t* index) {
    return index && static_cast<Reader*>(context)->At(reinterpret_cast<std::uint64_t>(entry), 0x2c, *index);
}
bool ReadBound(void* context, void* target, std::uint32_t hash, std::uint32_t* id) {
    auto& r = *static_cast<Reader*>(context); std::uint64_t reference = 0;
    const auto offset = hash == ge::component_binding::shop_reference_hash ? 0x18U :
        hash == ge::component_binding::bag_reference_hash ? 0x38U : 0U;
    return offset && id && r.At(reinterpret_cast<std::uint64_t>(target), offset, reference) && r.Reference(reference, *id);
}
BindingActionCode ObserveBinding(Reader& r, const ComponentRow& component, ObservedBinding& out) noexcept {
    out = {};
    if (component.kind == 33) {
        std::uint64_t check = 0;
        if (!r.At(component.config, 0x38, out.reference) || !r.Reference(out.reference, out.templateId) ||
            !r.At(component.config, 0x38, check) || check != out.reference) return BindingActionCode::binding_read_failed;
        std::uint32_t id = 0;
        return r.Reference(check, id) && id == out.templateId ? BindingActionCode::binding_verified : BindingActionCode::binding_read_failed;
    }
    std::uint64_t list = 0, items = 0, capacity = 0, check = 0;
    unsigned char header[0x20]{}, after[0x20]{};
    if (!r.At(component.config, 0x30, list) || !TemplatePointer(list) || !r.Read(list, header, sizeof(header))) return BindingActionCode::binding_read_failed;
    const auto count = From<std::int32_t>(header, 0x18); items = From<std::uint64_t>(header, 0x10);
    if (!TemplatePointer(From<std::uint64_t>(header, 0)) || count < 0 || !r.At(items, 0x18, capacity) ||
        capacity > 256 || static_cast<std::uint64_t>(count) > capacity) return BindingActionCode::binding_read_failed;
    out.shopCount = static_cast<std::uint32_t>(count);
    // This action configures one shop slot. It does not choose among or replace
    // multiple preexisting shops; that requires a separate explicit request.
    if (count > 1) return BindingActionCode::ambiguous_shop_entries;
    std::uint64_t entries[256]{}, entriesAfter[256]{};
    if (capacity && !r.Read(items + 0x20, entries, static_cast<std::size_t>(capacity) * 8)) return BindingActionCode::binding_read_failed;
    if (count) {
        unsigned char entry[0x30]{};
        out.entry = entries[0];
        if (!TemplatePointer(out.entry) || !r.Read(out.entry, entry, sizeof(entry)) || !TemplatePointer(From<std::uint64_t>(entry, 0))) return BindingActionCode::binding_read_failed;
        out.reference = From<std::uint64_t>(entry, 0x18); out.shopIndex = From<std::int32_t>(entry, 0x2c);
        if (out.shopIndex <= 0 || !r.Reference(out.reference, out.templateId)) return BindingActionCode::binding_read_failed;
        unsigned char again[0x30]{};
        if (!r.Read(out.entry, again, sizeof(again)) || std::memcmp(entry, again, sizeof(entry))) return BindingActionCode::binding_read_failed;
        std::uint32_t id = 0;
        if (!r.Reference(out.reference, id) || id != out.templateId) return BindingActionCode::binding_read_failed;
    }
    std::uint64_t capacityAfter = 0;
    if (!r.Read(list, after, sizeof(after)) || std::memcmp(header, after, sizeof(header)) || !r.At(items, 0x18, capacityAfter) || capacity != capacityAfter ||
        (capacity && (!r.Read(items + 0x20, entriesAfter, static_cast<std::size_t>(capacity) * 8) || std::memcmp(entries, entriesAfter, static_cast<std::size_t>(capacity) * 8))) ||
        !r.At(component.config, 0x30, check) || check != list) return BindingActionCode::binding_read_failed;
    return BindingActionCode::binding_verified;
}
const ComponentRow* Find(const ComponentSnapshot& snapshot, std::int32_t kind) noexcept {
    for (std::uint32_t i = 0; i < snapshot.count; ++i) if (snapshot.rows[i].kind == kind) return &snapshot.rows[i];
    return nullptr;
}
bool CatalogsEqual(const TemplateCatalogCapture& a, const TemplateCatalogCapture& b) noexcept {
    if (a.manager != b.manager || a.level_id != b.level_id || a.primary.row_count != b.primary.row_count || a.companion.row_count != b.companion.row_count) return false;
    for (std::uint32_t i = 0; i < a.primary.row_count; ++i) {
        bool found = false;
        for (std::uint32_t j = 0; j < b.primary.row_count; ++j) if (!std::memcmp(&a.primary_rows[i], &b.primary_rows[j], sizeof(TemplateIdentity))) found = true;
        if (!found) return false;
    }
    for (std::uint32_t i = 0; i < a.companion.row_count; ++i) {
        bool found = false;
        for (std::uint32_t j = 0; j < b.companion.row_count; ++j) if (!std::memcmp(&a.companion_rows[i], &b.companion_rows[j], sizeof(TemplateCompanionIdentity))) found = true;
        if (!found) return false;
    }
    return true;
}
void RecordBinding(BindingActionResult& out, const ObservedBinding& observed) noexcept { out.entry = observed.entry; out.shopIndex = observed.shopIndex; }
}
void ExecuteBindingAction(const GameContextSnapshot* current, const BindingActionReview& review,
    const BindingActionRuntime& runtime, TemplateReadSource source, const BindingActionCalls& calls,
    const BindingActionRequest& request, BindingActionWorkspace* work, BindingActionResult* out) noexcept {
    if (!out) return;
    *out = {}; out->code = BindingActionCode::invalid_review;
    if (!review.expected || !review.pid || !review.tid || runtime.pid != review.pid || runtime.tid != review.tid ||
        runtime.now >= review.deadline || !runtime.codeVerified) return;
    out->code = BindingActionCode::invalid_context;
    if (!current || !SameScene(*current, *review.expected)) return;
    out->code = BindingActionCode::invalid_request;
    const bool shop = request.kind == 35;
    if (!request.entityId || !request.templateId || (!shop && request.kind != 33) || !work || !source.read ||
        (request.templateId & 0xe0000000U) != 0x40000000U || ((request.templateId >> 22) & 127) != (shop ? 15U : 11U)) return;
    out->entityId = request.entityId; out->templateId = request.templateId;
    out->code = BindingActionCode::owner_not_found; std::uint32_t owners = 0;
    for (std::uint32_t i = 0; i < current->entityCaptured; ++i) {
        const auto& entity = current->entities[i];
        if (entity.id != request.entityId) continue;
        constexpr std::uint32_t required = GE_ID_READ | GE_CONTEXT_MATCH | GE_KEY_MATCH | GE_CONTEXT_READ;
        if ((entity.flags & required) != required || entity.dictionaryKey != entity.id || entity.context != current->currentContext || !TemplatePointer(entity.owner)) return;
        out->owner = entity.owner; ++owners;
    }
    if (owners != 1) return;
    out->code = BindingActionCode::missing_binding;
    const bool typedReference = calls.bind.createTypedReference || calls.bind.initializeReferenceId || calls.bind.referenceTypeName;
    if ((typedReference ? (!calls.bind.createTypedReference || !calls.bind.initializeReferenceId || !calls.bind.referenceTypeName) : !calls.bind.createReference) ||
        (shop && (!calls.bind.addShopEntry || !calls.bind.setShopReference || !calls.bind.refreshShopDependencies)) ||
        (!shop && (!calls.bind.setBagReference || !calls.bind.refreshBagDependencies))) return;
    out->stage = BindingActionStage::catalog;
    CaptureTemplateCatalog(current, source, &work->catalogScratch, &work->beforeCatalog);
    out->code = BindingActionCode::catalog_failed;
    if (work->beforeCatalog.code != TemplateCaptureCode::complete) return;
    out->catalogVerified = true;
    Reader r{source, 0}; std::uint64_t resource_class = 0, wrapper_class = 0, config_class = 0, owner_class = 0;
    out->code = BindingActionCode::types_unavailable;
    if (!r.At(current->moduleBase, shop ? 0x57e9bf0 : 0x57e9bd0, resource_class) || !TemplatePointer(resource_class) ||
        !r.At(current->moduleBase, 0x57b0058, wrapper_class) || !TemplatePointer(wrapper_class) ||
        !r.At(current->moduleBase, shop ? 0x57b1060 : 0x57dda88, config_class) || !TemplatePointer(config_class) ||
        !r.At(current->moduleBase, 0x57b3280, r.referenceClass) || !TemplatePointer(r.referenceClass) ||
        !r.At(out->owner, 0, owner_class) || !TemplatePointer(owner_class)) return;
    out->code = BindingActionCode::template_not_found;
    for (std::uint32_t i = 0; i < work->beforeCatalog.primary.row_count; ++i) {
        const auto& row = work->beforeCatalog.primary_rows[i]; if (row.id != request.templateId) continue;
        out->code = BindingActionCode::template_kind_mismatch;
        if (row.subtype != (shop ? 17U : 12U) || row.klass != resource_class) return;
        out->templateResource = row.resource; out->templateVerified = true;
    }
    if (!out->templateVerified) return;
    out->stage = BindingActionStage::components;
    ge::component_attachment::CaptureComponents(source, out->owner, &work->attachment.capture, &work->attachment.before);
    out->code = BindingActionCode::components_failed;
    if (work->attachment.before.code != ge::component_attachment::CaptureCode::complete) return;
    const auto* existing = Find(work->attachment.before, request.kind);
    if (existing) {
        out->code = BindingActionCode::component_class_mismatch;
        if (existing->wrapper_class != wrapper_class || existing->config_class != config_class) return;
        out->code = ObserveBinding(r, *existing, work->beforeBinding);
        if (out->code != BindingActionCode::binding_verified) return;
        if (work->beforeBinding.templateId && work->beforeBinding.templateId != request.templateId) { out->code = BindingActionCode::existing_template_conflict; return; }
        if (shop && work->beforeBinding.shopCount && !work->beforeBinding.templateId) { out->code = BindingActionCode::existing_unbound_shop_entry; return; }
    } else if (!calls.attach) { out->code = BindingActionCode::missing_binding; return; }
    ge::component_edit::Evidence editEvidence{current->moduleBase, current->global, out->owner, 0, 0, request.kind, runtime.codeVerified};
    if (calls.requireEditTransaction && (!existing || work->beforeBinding.templateId != request.templateId)) {
        out->code = BindingActionCode::edit_environment_failed;
        if (!calls.edit.open || !calls.edit.snapshot || !calls.edit.notify || !calls.edit.close ||
            ge::component_edit::CheckComponentEditReady(source, editEvidence, &out->edit.before) != ge::component_edit::Code::ready) return;
    }
    out->stage = BindingActionStage::attachment;
    const ge::component_attachment::AttachmentEvidence evidence{out->owner, owner_class, wrapper_class, config_class, request.kind, true};
    ge::component_attachment::EnsureComponentAttached(source, calls.attach, evidence, &work->attachment, &out->attachment);
    out->outcomeUncertain = out->attachment.outcome_uncertain;
    out->code = BindingActionCode::attachment_failed;
    if (out->attachment.code != ge::component_attachment::AttachCode::existing && out->attachment.code != ge::component_attachment::AttachCode::attached_verified) return;
    const auto component = out->attachment.component; out->wrapper = component.wrapper; out->config = component.config; out->componentVerified = true;
    out->code = BindingActionCode::component_id_unreadable;
    if (!r.At(component.wrapper, 0x1c, out->componentId) || !out->componentId) return;
    // Re-read after ensure; a fresh attach may legitimately have initialized data.
    out->code = ObserveBinding(r, component, work->beforeBinding);
    if (out->code != BindingActionCode::binding_verified) return;
    if (work->beforeBinding.templateId == request.templateId) {
        RecordBinding(*out, work->beforeBinding); out->reused = true; out->postBindingVerified = true;
        out->code = BindingActionCode::reused;
    }
    if (!out->reused) {
    if (work->beforeBinding.templateId) { out->code = BindingActionCode::existing_template_conflict; return; }
    if (shop && work->beforeBinding.shopCount) { out->code = BindingActionCode::existing_unbound_shop_entry; return; }
    if (calls.requireEditTransaction) {
        editEvidence.wrapper = out->wrapper; editEvidence.config = out->config;
        out->stage = BindingActionStage::edit_begin;
        ge::component_edit::BeginComponentEdit(source, calls.edit, editEvidence, &out->edit);
        out->outcomeUncertain = out->outcomeUncertain || out->edit.outcomeUncertain;
        if (out->edit.code != ge::component_edit::Code::snapshot_ready) { out->code = BindingActionCode::edit_begin_failed; return; }
    }
    out->stage = BindingActionStage::binding;
    const ge::component_binding::Readbacks reads{&r, ReadReference, ReadIndex, ReadBound};
    const ge::component_binding::Evidence bindEvidence{reinterpret_cast<void*>(out->owner), reinterpret_cast<void*>(out->config), request.templateId,
        shop ? ge::component_binding::Kind::shop : ge::component_binding::Kind::bag, true, true};
    if (calls.requireEditTransaction) {
        if (shop) ge::component_binding::bind_shop_fields_into(calls.bind, reads, bindEvidence, &out->binding);
        else ge::component_binding::bind_bag_fields_into(calls.bind, reads, bindEvidence, &out->binding);
    } else if (shop) ge::component_binding::bind_shop_into(calls.bind, reads, bindEvidence, &out->binding);
    else ge::component_binding::bind_bag_into(calls.bind, reads, bindEvidence, &out->binding);
    out->outcomeUncertain = out->outcomeUncertain || out->binding.outcomeUncertain;
    out->needsOwnerNotification = out->binding.needsOwnerNotification;
    out->code = BindingActionCode::binding_failed;
    if (out->binding.code != ge::component_binding::BindCode::returned) return;
    if (calls.requireEditTransaction) {
        out->stage = BindingActionStage::edit_complete;
        ge::component_edit::CompleteComponentEdit(source, calls.edit, editEvidence, &out->edit);
        if (out->edit.code != ge::component_edit::Code::complete) { out->code = BindingActionCode::edit_complete_failed; return; }
        out->binding.needsDependencyRefresh = false;
        out->binding.needsOwnerNotification = false;
        out->needsOwnerNotification = false;
    } else if (!out->binding.dependencyRefreshCalled || out->binding.needsDependencyRefresh) return;
    }
    out->stage = BindingActionStage::post_readback;
    out->code = ObserveBinding(r, component, work->afterBinding);
    if (out->code != BindingActionCode::binding_verified || work->afterBinding.templateId != request.templateId ||
        (shop && (work->afterBinding.shopCount != 1 || (!out->reused && (work->afterBinding.entry != reinterpret_cast<std::uint64_t>(out->binding.entry) || work->afterBinding.shopIndex != out->binding.shopIndex))))) {
        out->code = BindingActionCode::post_binding_failed; return;
    }
    RecordBinding(*out, work->afterBinding); out->postBindingVerified = true;
    ge::component_attachment::CaptureComponents(source, out->owner, &work->attachment.capture, &work->postComponents);
    out->code = BindingActionCode::post_components_failed;
    const auto& boundComponents = out->attachment.attach_called ? work->attachment.after : work->attachment.before;
    if (work->postComponents.code != ge::component_attachment::CaptureCode::complete || work->postComponents.count != boundComponents.count ||
        work->postComponents.owner_class != boundComponents.owner_class || work->postComponents.owner_state != boundComponents.owner_state) return;
    for (std::uint32_t i = 0; i < boundComponents.count; ++i)
        // Full native notification may legitimately change wrapper enable through
        // inheritance. All identities remain fixed; expose the actual byte.
        if (calls.requireEditTransaction && !out->reused && boundComponents.rows[i].wrapper == out->wrapper) {
            auto old = boundComponents.rows[i]; old.enabled = work->postComponents.rows[i].enabled;
            if (std::memcmp(&old, &work->postComponents.rows[i], sizeof(ComponentRow))) return;
        } else if (std::memcmp(&boundComponents.rows[i], &work->postComponents.rows[i], sizeof(ComponentRow))) return;
    CaptureTemplateCatalog(current, source, &work->catalogScratch, &work->afterCatalog);
    out->code = BindingActionCode::post_catalog_failed;
    if (work->afterCatalog.code != TemplateCaptureCode::complete) return;
    out->code = BindingActionCode::catalog_changed;
    if (!CatalogsEqual(work->beforeCatalog, work->afterCatalog)) return;
    out->catalogsUnchanged = true; out->code = out->reused ? BindingActionCode::reused : BindingActionCode::binding_verified;
}
}
