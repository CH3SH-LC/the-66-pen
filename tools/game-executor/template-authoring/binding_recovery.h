#pragma once
#include "binding_native_adapter.h"

namespace ge::templates {
struct BindingRecoveryResult;
using CloseRecoveryCore = bool (__cdecl *)(void*, std::int32_t, bool, void*, bool); // 9c270a0
struct RecoveryNativeCalls { ge::component_edit::NotifyComponent notify; CloseRecoveryCore closeCore; };
// Separate reviewed action: finalize an attached EMPTY bag after a definitely
// null reference result. Never repeat attachment, reference creation or setter.
struct BindingRecoveryIdentity {
    std::uint32_t entityId, templateId, componentId;
    std::uint64_t owner, wrapper, config, transaction;
};
struct BindingRecoveryReview {
    std::uint32_t pid, tid;
    std::uint64_t processCreation, threadCreation, deadline;
    const GameContextSnapshot* expected;
    // Immutable bytes extracted from the SHA-bound failed raw receipt. The
    // adapter verifies that SHA and signs a fresh single-attempt review.
    const NativeBindingReceipt* prior;
    BindingRecoveryIdentity identity;
    // SHA-bound v1 refusal. Only its legacy 49800-byte prefix may be read.
    const BindingRecoveryResult* tokenRefusal;
    const ge::component_edit::EditState* reviewedPending;
};
struct BindingRecoveryRuntime {
    std::uint32_t pid, tid;
    std::uint64_t processCreation, threadCreation, now;
    bool codeVerified, priorReceiptHashVerified, tokenRefusalHashVerified, reviewedPendingHashVerified;
};
enum class BindingRecoveryCode : std::uint32_t {
    invalid_review, invalid_prior, context_changed, component_changed,
    empty_reference_changed, token_changed, edit_failed, post_components_failed,
    transaction_closed, duplicate_attempt, diagnostic_read
};
struct BindingRecoveryResult {
    BindingRecoveryCode code;
    bool identityVerified, emptyReferenceVerified, tokenVerified;
    bool transactionClosed, needsBinding, outcomeUncertain;
    std::uint64_t emptyReference, tokenClass, tokenLabel;
    std::int32_t tokenDepth;
    std::uint8_t tokenFlags[2];
    std::uint32_t emptyReferenceClassification, emptyReferenceId;
    ge::component_edit::Result edit;
    std::uint32_t recoveryVersion;
    bool pendingScopeVerified, closeCoreCalled, closeCoreReturned, originalTokenUnused;
};
struct BindingRecoveryWorkspace {
    ge::component_attachment::CaptureWorkspace capture;
    ge::component_attachment::ComponentSnapshot before, after;
};
// Only notify+closeCore use native calls. The original token is neither read,
// dereferenced nor returned to the pool. Completion means the original transaction
// closed around the retained empty attachment; NOT binding, persistence or play.
// An outer adapter owns SEH and retains edit.notifyCalled/closeCalled on faults.
void CloseUnboundBagAttachment(const GameContextSnapshot*, const BindingRecoveryReview&,
    const BindingRecoveryRuntime&, TemplateReadSource, const RecoveryNativeCalls&,
    BindingRecoveryWorkspace*, BindingRecoveryResult*) noexcept;
// No native calls. afterNotify stores a CURRENT diagnostic capture although
// notifyCalled stays false; edit.code is the readiness/environment check result.
void ReadUnboundBagEditDiagnostic(const GameContextSnapshot*, const BindingRecoveryReview&,
    const BindingRecoveryRuntime&, TemplateReadSource, const RecoveryNativeCalls&,
    BindingRecoveryWorkspace*, BindingRecoveryResult*) noexcept;
}
