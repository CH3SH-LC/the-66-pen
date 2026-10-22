#pragma once
#include "skill_calls.h"
#include "template_catalog_capture.h"

namespace ge::skills {
using InitializeSkillMetadata = void (__cdecl *)(std::uint32_t);
// The same default-table selector used by 128ef5b0; it allocates a temporary
// filtered/sorted list, so this preflight is not described as read-only.
using FindSkillDefault = void* (__cdecl *)(std::int32_t filter);
struct SkillActionBindings {
    InitializeSkillMetadata initializeMetadata;
    FindSkillDefault findDefault; // 102e20f0, fixed filter 2.
    StringNewLen stringNewLen;
    CreateSkill create; // Full d1f8af0(name, nullptr), owns mandatory callback.
};
struct SkillActionReview {
    std::uint32_t pid, tid;
    std::uint64_t deadline;
    const GameContextSnapshot* expected;
};
struct SkillActionRuntime {
    std::uint32_t pid, tid;
    std::uint64_t now;
    bool codeVerified; // Adapter verifies the current fixed code/hotfix profile.
};
enum class SkillActionCode : std::uint32_t {
    catalog_verified, invalid_review, invalid_context, missing_binding,
    invalid_name, baseline_capture_failed, local_capture_capacity,
    default_table_unavailable, default_record_unavailable, name_allocation_failed,
    context_changed, null_resource, post_capture_failed, classes_unavailable,
    main_delta_failed, companion_delta_failed, call_exception
};
enum class SkillActionStage : std::uint32_t {
    none, metadata_initialization, default_lookup, name_allocation, skill_creation
};
struct SkillActionResult {
    SkillActionCode code;
    SkillActionStage stage;
    ge::templates::CatalogCode mainDeltaCode;
    ge::templates::CallCode nameCode;
    std::uint64_t defaultTable, defaultRecord, returnedResource;
    std::uint64_t observedMainClass, observedCompanionClass, companionResource;
    std::uint32_t defaultType, defaultValue, createdId, companionOwnId;
    std::uint32_t primaryCountBefore, companionCountBefore, metadataCallsStarted, metadataCallsCompleted;
    bool defaultLookupCalled, allocationCalled, createCalled, postCaptureAttempted;
    bool mainCatalogVerified, companionCatalogVerified, outcomeUncertain;
};
struct SkillActionWorkspace {
    ge::templates::TemplateCatalogCaptureWorkspace capture;
    ge::templates::TemplateCatalogCapture before, after;
};
// Fixed UI-equivalent helper path; no fabricated native count/limit evidence.
// 4096 is the existing local receipt capacity, NOT an official skill limit.
// Every native-entry progress flag is caller-owned and set before the call.
// Result must be zero-initialized for a new reviewed invocation; never clear a
// retained attempted result to replay a request.
// A native adapter owns SEH, fresh code/thread identity and after-scene capture.
// Registration proof does not prove name/default contents, attachment or save.
void ExecuteSkillAction(const GameContextSnapshot*, const SkillActionReview&,
    const SkillActionRuntime&, ge::templates::TemplateReadSource,
    const SkillActionBindings&, std::string_view name,
    SkillActionWorkspace*, SkillActionResult*) noexcept;
}
