#pragma once
#include "item_calls.h"
#include "template_catalog_capture.h"
#include <string_view>

namespace ge::templates {
using InitializeItemMetadata = void (__cdecl *)(std::uint32_t usageIndex);
using CountNormalItems = void* (__cdecl *)(void* manager, void* outputList, void* filter,
    std::uint8_t includeManager20, std::uint8_t includeManager40, void* methodInfo);
using GetItemController = void* (__cdecl *)();
using InitializeItemLimits = void (__cdecl *)();
struct ItemActionBindings {
    InitializeItemMetadata initializeMetadata; // Fixed 0x524250; only usage 0x1b911.
    CountNormalItems count;
    InitializeItemLimits initializeLimits;
    GetItemController controller;
    StringNewLen stringNewLen;
    CreateNormalItem create;
    ReadDefaultItemValue readDefault;
};
struct ItemActionReview {
    std::uint32_t pid, tid;
    std::uint64_t deadline;
    const GameContextSnapshot* expected;
};
struct ItemActionRuntime {
    std::uint32_t pid, tid;
    std::uint64_t now;
    // Supplied by the adapter after fixed current-build anchors/hotfix checks.
    bool codeVerified;
};
enum class ItemActionCode : std::uint32_t {
    catalog_verified, invalid_review, invalid_context, missing_binding,
    baseline_capture_failed, metadata_unavailable, count_unreadable,
    limit_unreadable, count_limit_rejected, controller_unavailable,
    invalid_name, name_allocation_failed, context_changed, item_call_failed,
    post_capture_failed, resource_class_unreadable, main_delta_failed,
    companion_delta_failed, call_exception
};
enum class ItemActionStage : std::uint32_t {
    none, metadata_initialization, count, limit_initialization,
    controller_lookup, name_allocation, item_creation
};
struct ItemActionResult {
    ItemActionCode code;
    ItemActionStage stage;
    ItemResult item;
    CatalogCode mainDeltaCode;
    CallCode nameCode;
    std::int64_t count, limit;
    std::uint32_t createdId, companionOwnId;
    std::uint64_t createdResource, companionResource;
    std::uint64_t observedMainClass, observedCompanionClass;
    bool metadataInitializationCalled, countCalled, limitInitializationCalled;
    bool controllerLookupCalled, allocationCalled, createCalled;
    bool mainCatalogVerified, companionCatalogVerified;
    // Registration alone does not prove name/default/export/save acceptance.
    bool outcomeUncertain;
};
struct ItemActionWorkspace {
    TemplateCatalogCaptureWorkspace capture;
    TemplateCatalogCapture before, after;
};
// Fixed ordinary-item creation, on an adapter-verified game thread. No discovery,
// IPC, raw native writes, retry or save. Workspace is caller-owned and large.
void ExecuteItemAction(const GameContextSnapshot* current,
    const ItemActionReview&, const ItemActionRuntime&, TemplateReadSource,
    const ItemActionBindings&, std::string_view name,
    ItemActionWorkspace*, ItemActionResult*) noexcept;
}
