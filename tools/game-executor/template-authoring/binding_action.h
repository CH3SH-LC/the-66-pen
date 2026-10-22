#pragma once
#include "component_attachment.h"
#include "component_binding_calls.h"
#include "owner_notification_calls.h"

namespace ge::templates {
struct BindingActionReview {
    std::uint32_t pid, tid;
    std::uint64_t deadline;
    const GameContextSnapshot* expected;
};
struct BindingActionRuntime { std::uint32_t pid, tid; std::uint64_t now; bool codeVerified; };
struct BindingActionRequest { std::uint32_t entityId, templateId; std::int32_t kind; };
struct BindingActionCalls {
    ge::component_attachment::AttachComponent attach;
    ge::component_binding::NativeCalls bind;
    ge::component_edit::NativeCalls edit{};
    bool requireEditTransaction = false; // Legacy host API only; native adapter sets true.
};
enum class BindingActionCode : std::uint32_t {
    binding_verified, reused, invalid_review, invalid_context, invalid_request,
    owner_not_found, missing_binding, catalog_failed, types_unavailable,
    template_not_found, template_kind_mismatch, components_failed,
    component_class_mismatch, binding_read_failed, existing_template_conflict,
    ambiguous_shop_entries, existing_unbound_shop_entry, attachment_failed,
    component_id_unreadable, binding_failed, post_binding_failed,
    post_components_failed, post_catalog_failed, catalog_changed,
    edit_environment_failed, edit_begin_failed, edit_complete_failed
};
enum class BindingActionStage : std::uint32_t { none, catalog, components, attachment, binding, post_readback, edit_begin, edit_complete };
struct ObservedBinding {
    std::uint64_t reference, entry;
    std::uint32_t templateId, shopCount;
    std::int32_t shopIndex;
};
struct BindingActionResult {
    BindingActionCode code;
    BindingActionStage stage;
    std::uint32_t entityId, templateId, componentId;
    std::uint64_t owner, templateResource, wrapper, config, entry;
    std::int32_t shopIndex;
    ge::component_attachment::AttachmentResult attachment;
    ge::component_binding::BindResult binding;
    bool catalogVerified, templateVerified, componentVerified, reused;
    bool postBindingVerified, catalogsUnchanged, needsOwnerNotification, outcomeUncertain;
    ge::component_edit::Result edit;
};
struct BindingActionWorkspace {
    TemplateCatalogCaptureWorkspace catalogScratch;
    TemplateCatalogCapture beforeCatalog, afterCatalog;
    ge::component_attachment::AttachmentWorkspace attachment;
    ge::component_attachment::ComponentSnapshot postComponents;
    ObservedBinding beforeBinding, afterBinding;
};
// Fixed bag/shop route, current native template types bag12/band11, shop17/band15.
// Runtime type slots must already be initialized by the reviewed adapter; this
// action never guesses types, calls metadata initialization, saves, or retries.
void ExecuteBindingAction(const GameContextSnapshot*, const BindingActionReview&,
    const BindingActionRuntime&, TemplateReadSource, const BindingActionCalls&,
    const BindingActionRequest&, BindingActionWorkspace*, BindingActionResult*) noexcept;
}
