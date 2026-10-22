#include "binding_recovery.h"
#include <cstring>
#include <type_traits>

namespace ge::templates {
namespace {
bool sameScene(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    if (a.structSize != sizeof(a) || b.structSize != sizeof(b) || a.version != 1 || b.version != 1 ||
        a.status != GS_OK || b.status != GS_OK || (a.flags & 1951) != 1951 || (b.flags & 1951) != 1951 ||
        ((a.flags | b.flags) & 96) || a.entityRejected || b.entityRejected || a.activeKey || b.activeKey ||
        !a.reserved || a.reserved != b.reserved || a.moduleBase != b.moduleBase || a.global != b.global ||
        a.currentContext != b.currentContext || a.contextManager != b.contextManager || a.saveManager != b.saveManager ||
        a.peTimestamp != b.peTimestamp || a.peImageSize != b.peImageSize || a.entityCaptured > kMaxEntities ||
        a.entityCaptured != b.entityCaptured || a.entityCaptured != a.entityValidEntries || b.entityCaptured != b.entityValidEntries ||
        a.entityVersionBefore != b.entityVersionBefore || a.entityVersionAfter != b.entityVersionAfter) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i)
        if (std::memcmp(&a.entities[i], &b.entities[i], sizeof(GameEntitySnapshot))) return false;
    return true;
}
template<class T> bool read(TemplateReadSource source, std::uint64_t at, T& value) noexcept {
    // Scalar fields such as wrapper+1c/token+1c are intentionally unaligned.
    // Validate the address range here; validate object pointer VALUES separately.
    return source.read && at >= 0x10000 && at < 0x800000000000ULL - sizeof(value) &&
        source.read(source.context, at, &value, sizeof(value));
}
bool sameComponents(const ge::component_attachment::ComponentSnapshot& a,
    const ge::component_attachment::ComponentSnapshot& b, std::uint64_t target, bool allowEnable) noexcept {
    using ge::component_attachment::CaptureCode;
    if (a.code != CaptureCode::complete || b.code != CaptureCode::complete || a.count != b.count ||
        a.count > ge::component_attachment::kMaxComponents || a.owner != b.owner || a.owner_class != b.owner_class ||
        a.owner_state != b.owner_state || a.set != b.set || a.list != b.list || a.set_count != b.set_count) return false;
    for (std::uint32_t i = 0; i < a.count; ++i) {
        auto old = a.rows[i];
        if (allowEnable && old.wrapper == target) old.enabled = b.rows[i].enabled;
        if (a.kinds[i] != b.kinds[i] || std::memcmp(&old, &b.rows[i], sizeof(old))) return false;
    }
    return true;
}
bool priorMatches(const NativeBindingReceipt& p, const BindingRecoveryIdentity& id) noexcept {
    const auto& a = p.action; const auto& b = a.binding; const auto& e = a.edit;
    if (p.size != sizeof(p) || p.version != 2 || p.sehCode || p.readbackSehCode || p.afterSceneUnchanged != 1 ||
        p.code != NativeBindingCode::action_returned || !p.nativeCallAttempted || !p.componentMutationCalled ||
        p.metadataUsageInProgress || p.metadataCallsStarted != 17 || p.metadataCallsStarted != p.metadataCallsCompleted ||
        !id.entityId || !id.templateId || !id.componentId || !TemplatePointer(id.transaction) ||
        a.entityId != id.entityId || a.templateId != id.templateId || a.componentId != id.componentId ||
        a.owner != id.owner || a.wrapper != id.wrapper || a.config != id.config || e.transaction != id.transaction ||
        a.code != BindingActionCode::binding_failed || a.stage != BindingActionStage::binding ||
        !a.catalogVerified || !a.templateVerified || !a.componentVerified || a.reused || a.postBindingVerified ||
        a.attachment.code != ge::component_attachment::AttachCode::attached_verified || !a.attachment.attach_called ||
        !a.attachment.before_verified || !a.attachment.after_verified || a.attachment.returned_wrapper != id.wrapper ||
        a.attachment.component.wrapper != id.wrapper || a.attachment.component.config != id.config || a.attachment.component.kind != 33 ||
        b.code != ge::component_binding::BindCode::null_reference || b.exceptionStage != ge::component_binding::BindStage::none ||
        !b.referenceFactoryCalled || b.reference || b.referenceReadbackVerified || b.addCalled || b.setterCalled ||
        b.fieldReadbackVerified || b.dependencyRefreshCalled || b.mutationCalled ||
        e.code != ge::component_edit::Code::snapshot_ready || e.stage != ge::component_edit::Stage::none ||
        !e.openCalled || !e.snapshotCalled || !e.snapshotVerified || !e.transactionMayBeOpen ||
        e.notifyCalled || e.closeCalled || e.notificationVerified || e.closeVerified ||
        e.evidence.owner != id.owner || e.evidence.wrapper != id.wrapper || e.evidence.config != id.config || e.evidence.kind != 33 ||
        e.before.count || e.before.targetCount || e.before.depth != e.before.baseDepth ||
        e.afterSnapshot.count != 1 || e.afterSnapshot.targetCount != 1 || e.afterSnapshot.depth != e.before.depth + 1 ||
        e.afterSnapshot.target.object != id.wrapper || e.afterSnapshot.target.dirty || e.afterSnapshot.target.after ||
        !TemplatePointer(e.afterSnapshot.target.before) || !TemplatePointer(p.workspace.beforeBinding.reference) ||
        p.workspace.beforeBinding.templateId || p.workspace.beforeBinding.entry || p.workspace.beforeBinding.shopCount) return false;
    return true;
}
bool emptyReference(TemplateReadSource source, const NativeBindingReceipt& prior,
    const BindingRecoveryIdentity& id, BindingRecoveryResult& out) noexcept {
    std::uint64_t klass = 0, again = 0; std::uint32_t fields[2]{};
    out.emptyReferenceClassification = out.emptyReferenceId = 0xffffffffU;
    auto& reference = out.emptyReference;
    if (!read(source, id.config + 0x38, reference) || reference != prior.workspace.beforeBinding.reference ||
        !read(source, reference, klass) || klass != prior.initializedClasses[5] ||
        !read(source, reference + 0x18, fields) || !read(source, id.config + 0x38, again) || again != reference) return false;
    out.emptyReferenceClassification = fields[0]; out.emptyReferenceId = fields[1];
    return !fields[0] && !fields[1];
}
bool sameEditIdentity(const ge::component_edit::EditState& a, const ge::component_edit::EditState& b) noexcept {
    return a.manager == b.manager && a.list == b.list && a.recordClass == b.recordClass &&
        a.literal == b.literal && a.baseDepth == b.baseDepth && !b.flags[1] && !b.flags[2];
}
bool refusalMatches(const BindingRecoveryResult& r, const NativeBindingReceipt& prior) noexcept {
    // r may point into the shorter v1 receipt: never inspect the appended v2 fields.
    return r.code == BindingRecoveryCode::token_changed && r.identityVerified && r.emptyReferenceVerified &&
        !r.tokenVerified && !r.transactionClosed && r.needsBinding && r.outcomeUncertain &&
        r.emptyReference == prior.workspace.beforeBinding.reference &&
        !r.emptyReferenceClassification && !r.emptyReferenceId &&
        !r.edit.notifyCalled && !r.edit.closeCalled &&
        !std::memcmp(&r.edit, &prior.action.edit, sizeof(r.edit));
}
bool reviewedScopeMatches(const ge::component_edit::EditState& original, const ge::component_edit::EditState& reviewed) noexcept {
    if (original.count != 1 || original.targetCount != 1 || original.version == 0xffffffffU ||
        reviewed.count != 2 || reviewed.version != original.version + 1 ||
        !TemplatePointer(reviewed.records[1].pointer) || !TemplatePointer(reviewed.records[1].klass) ||
        reviewed.records[1].pointer == original.records[0].pointer || reviewed.records[1].klass == original.recordClass) return false;
    auto allowed = original;
    allowed.count = 2; ++allowed.version; allowed.records[1] = reviewed.records[1];
    // The non-component row exposes pointer/class only. Its zero data fields
    // are capture sentinels, not a claim that its unknown payload is unchanged.
    if (reviewed.records[1].object || reviewed.records[1].after || reviewed.records[1].before || reviewed.records[1].dirty) return false;
    return !std::memcmp(&allowed, &reviewed, sizeof(allowed));
}
void completeScope(TemplateReadSource source, const RecoveryNativeCalls& calls,
    const ge::component_edit::EditState& reviewed, BindingRecoveryResult& out) noexcept {
    using namespace ge::component_edit;
    auto& edit = out.edit; const auto& e = edit.evidence;
    EditState beforeNotify{};
    // This existing check validates all wrapper/config/owner virtual targets;
    // the exact one-open-scope state must return busy rather than ready.
    if (CheckComponentEditReady(source, e, &beforeNotify) != Code::busy ||
        beforeNotify.code != ReadCode::complete ||
        !reviewedScopeMatches(edit.afterSnapshot, reviewed) ||
        std::memcmp(&beforeNotify, &reviewed, sizeof(beforeNotify))) return;
    out.pendingScopeVerified = true;
    try {
        edit.stage = Stage::notify; edit.notifyCalled = true;
        calls.notify(reinterpret_cast<void*>(beforeNotify.manager), reinterpret_cast<void*>(e.wrapper));
        edit.stage = Stage::none;
        CaptureEditState(source, e, &edit.afterNotify); const auto& s = edit.afterNotify;
        edit.code = Code::notify_failed;
        if (s.code != ReadCode::complete || !sameEditIdentity(beforeNotify, s) || s.depth != beforeNotify.depth ||
            s.count != beforeNotify.count || s.version != beforeNotify.version || s.targetCount != 1 || s.target.pointer != beforeNotify.target.pointer ||
            s.target.before != beforeNotify.target.before || s.target.dirty != 1) return;
        for (std::uint32_t i = 0; i < s.count; ++i) {
            const auto& a = beforeNotify.records[i]; const auto& b = s.records[i];
            if (a.pointer != b.pointer || a.klass != b.klass || a.object != b.object ||
                a.before != b.before || a.after != b.after || b.dirty != (a.pointer == s.target.pointer ? 1 : a.dirty)) return;
        }
        edit.notificationVerified = true; edit.code = Code::notification_verified;
        // c7babc8's exact inner close, with the original open(nullptr,false,false)
        // arguments and proven old depth. Do not read, clear or pool the old token.
        edit.stage = Stage::close; edit.closeCalled = true; out.closeCoreCalled = true;
        out.closeCoreReturned = calls.closeCore(reinterpret_cast<void*>(s.manager), edit.before.depth, false, nullptr, false);
        edit.stage = Stage::none; edit.code = Code::close_failed;
        CaptureEditState(source, e, &edit.afterClose);
        if (!out.closeCoreReturned || edit.afterClose.code != ReadCode::complete ||
            !sameEditIdentity(edit.before, edit.afterClose) || edit.afterClose.depth != edit.before.depth || edit.afterClose.count) return;
        edit.closeVerified = true; edit.transactionMayBeOpen = false; edit.code = Code::complete;
    } catch (...) { edit.code = Code::call_exception; }
}
}
namespace {
bool prepareRecovery(const GameContextSnapshot* current, const BindingRecoveryReview& review,
    const BindingRecoveryRuntime& runtime, TemplateReadSource source, bool callContractValid,
    BindingRecoveryWorkspace* work, BindingRecoveryResult* out) noexcept {
    if (!out) return false;
    if (out->edit.notifyCalled || out->edit.closeCalled) { out->code = BindingRecoveryCode::duplicate_attempt; return false; }
    static_assert(std::is_trivially_copyable<BindingRecoveryResult>::value, "caller-owned recovery receipt");
    std::memset(out, 0, sizeof(*out));
    out->recoveryVersion = 2; out->originalTokenUnused = true;
    out->emptyReferenceClassification = out->emptyReferenceId = 0xffffffffU;
    if (!review.pid || !review.tid || !review.processCreation || !review.threadCreation || runtime.pid != review.pid ||
        runtime.tid != review.tid || runtime.processCreation != review.processCreation || runtime.threadCreation != review.threadCreation ||
        runtime.now >= review.deadline || !runtime.codeVerified || !runtime.priorReceiptHashVerified || !runtime.tokenRefusalHashVerified ||
        !review.prior || !review.tokenRefusal || !review.expected || !current || !work || !source.read || !callContractValid) return false;
    out->code = BindingRecoveryCode::invalid_prior;
    const auto& prior = *review.prior; const auto& id = review.identity;
    if (!priorMatches(prior, id) || !refusalMatches(*review.tokenRefusal, prior)) return false;
    // The exact failed result is retained, never reconstructed as a successful setter.
    std::memcpy(&out->edit, &prior.action.edit, sizeof(out->edit));
    out->needsBinding = true; out->outcomeUncertain = true;
    out->code = BindingRecoveryCode::context_changed;
    if (!sameScene(*current, *review.expected) || !sameScene(*current, prior.after) ||
        out->edit.evidence.moduleBase != current->moduleBase || out->edit.evidence.global != current->global) return false;
    std::uint32_t owners = 0;
    for (std::uint32_t i = 0; i < current->entityCaptured; ++i)
        if (current->entities[i].id == id.entityId && current->entities[i].dictionaryKey == id.entityId &&
            current->entities[i].owner == id.owner && current->entities[i].context == current->currentContext) ++owners;
    if (owners != 1) return false;
    out->identityVerified = true;
    out->code = BindingRecoveryCode::component_changed;
    ge::component_attachment::CaptureComponents(source, id.owner, &work->capture, &work->before);
    if (!sameComponents(prior.workspace.attachment.after, work->before, id.wrapper, false) ||
        !sameComponents(prior.workspace.postComponents, work->before, id.wrapper, false)) return false;
    std::uint32_t componentId = 0;
    if (!read(source, id.wrapper + 0x1c, componentId) || componentId != id.componentId) return false;
    out->code = BindingRecoveryCode::empty_reference_changed;
    if (!emptyReference(source, prior, id, *out)) return false;
    out->emptyReferenceVerified = true;
    return true;
}
}
void CloseUnboundBagAttachment(const GameContextSnapshot* current, const BindingRecoveryReview& review,
    const BindingRecoveryRuntime& runtime, TemplateReadSource source, const RecoveryNativeCalls& calls,
    BindingRecoveryWorkspace* work, BindingRecoveryResult* out) noexcept {
    if (!prepareRecovery(current, review, runtime, source,
        calls.notify && calls.closeCore && review.reviewedPending && runtime.reviewedPendingHashVerified, work, out)) return;
    const auto& prior = *review.prior;
    const auto& id = review.identity;
    // Explicit partial-attachment finalization: native wrapper notification also
    // supports the constructor's empty reference (10ed32db/10ed32dd, ID == 0).
    // The core path verifies the exact pending scope without touching the old token.
    out->code = BindingRecoveryCode::edit_failed;
    completeScope(source, calls, *review.reviewedPending, *out);
    if (out->edit.code != ge::component_edit::Code::complete || !out->edit.closeVerified || out->edit.transactionMayBeOpen) return;
    out->transactionClosed = true;
    out->code = BindingRecoveryCode::post_components_failed;
    ge::component_attachment::CaptureComponents(source, id.owner, &work->capture, &work->after);
    if (!sameComponents(work->before, work->after, id.wrapper, true) || !emptyReference(source, prior, id, *out)) return;
    out->code = BindingRecoveryCode::transaction_closed;
}
void ReadUnboundBagEditDiagnostic(const GameContextSnapshot* current, const BindingRecoveryReview& review,
    const BindingRecoveryRuntime& runtime, TemplateReadSource source, const RecoveryNativeCalls& calls,
    BindingRecoveryWorkspace* work, BindingRecoveryResult* out) noexcept {
    if (!prepareRecovery(current, review, runtime, source, !calls.notify && !calls.closeCore, work, out)) return;
    out->edit.code = ge::component_edit::CheckComponentEditReady(source, out->edit.evidence, &out->edit.afterNotify);
    // Check can reject environment before its state read. Always capture the
    // CURRENT pending records independently, without notifying or closing.
    ge::component_edit::CaptureEditState(source, out->edit.evidence, &out->edit.afterNotify);
    out->pendingScopeVerified = out->edit.code == ge::component_edit::Code::busy &&
        out->edit.afterNotify.code == ge::component_edit::ReadCode::complete &&
        !std::memcmp(&out->edit.afterNotify, &out->edit.afterSnapshot, sizeof(out->edit.afterNotify));
    out->code = BindingRecoveryCode::diagnostic_read;
}
}
