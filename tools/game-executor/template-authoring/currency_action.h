#pragma once
#include "template_calls.h"
#include "template_catalog_capture.h"
#include <string_view>

namespace ge::templates {
using LookupCurrencyGroup = void* (__cdecl *)(void* groups, std::uint32_t category);
using InitializeResourceLimits = void (__cdecl *)();
struct CurrencyActionBindings {
    CreateTemplate create;
    StringNewLen stringNewLen;
    LookupCurrencyGroup lookupGroup;
    InitializeResourceLimits initializeLimits;
};
// These are compiled review inputs, never fields supplied by a template request.
// Activation must bind them to the current session's full baseline and build.
struct CurrencyActionReview {
    std::uint32_t pid, tid;
    std::uint64_t deadline;
    const GameContextSnapshot* expected;
};
struct CurrencyActionRuntime {
    std::uint32_t pid, tid;
    std::uint64_t now;
    // True only after comparing the fixed current-build code anchors and hotfix
    // bytes in the loaded module. The native adapter, not the caller, supplies it.
    bool codeVerified;
};
enum class CurrencyActionCode : std::uint32_t {
    catalog_verified, invalid_review, invalid_context, missing_binding,
    baseline_capture_failed, group_unavailable, count_unreadable,
    limit_unreadable, count_limit_rejected, invalid_name, name_allocation_failed,
    context_changed, create_returned_null, post_capture_failed,
    resource_class_unreadable, main_delta_failed, companion_changed,
    call_exception
};
enum class CurrencyActionStage : std::uint32_t {
    none, group_lookup, limit_initialization, name_allocation, resource_creation
};
struct CurrencyActionResult {
    CurrencyActionCode code;
    CurrencyActionStage stage;
    CallCode callCode;
    CatalogCode mainDeltaCode;
    std::int64_t count, limit;
    std::uint64_t returnedResource, observedCurrencyClass;
    std::uint32_t createdId;
    bool groupLookupCalled, limitInitializationCalled, allocationCalled, createCalled;
    bool mainCatalogVerified, companionCatalogUnchanged;
    // Kept true after any creation attempt, even a verified registration: name,
    // defaults, native export and persistence are separate acceptance evidence.
    bool outcomeUncertain;
};
struct CurrencyActionWorkspace {
    TemplateCatalogCaptureWorkspace capture;
    TemplateCatalogCapture before, after;
};
// Candidate game-thread handler. No process discovery, IPC, save or retry.
// All reads use the supplied bounded native reader. The adapter must capture a
// fresh strict snapshot and validate anchors immediately before invoking this.
void ExecuteCurrencyAction(const GameContextSnapshot* current,
    const CurrencyActionReview&, const CurrencyActionRuntime&, TemplateReadSource,
    const CurrencyActionBindings&, std::string_view name,
    CurrencyActionWorkspace*, CurrencyActionResult*) noexcept;
}
