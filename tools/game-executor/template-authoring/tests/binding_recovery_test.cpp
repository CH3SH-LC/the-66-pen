// Reuse the existing synthetic native-memory fixture without rerunning its suite.
#define main binding_edit_fixture_main
#include "binding_edit_test.cpp"
#undef main
#include "../binding_recovery.h"
#include <cstddef>

namespace {
NativeBindingReceipt prior{};
BindingRecoveryWorkspace recoveryWork{};
BindingRecoveryResult recoveryResult{};
BindingRecoveryResult tokenRefusal{};
ge::component_edit::EditState reviewedPending{};
constexpr std::uint64_t appendedRecord = 0x690000, appendedClass = 0x6a0000;
unsigned tokenReads = 0;
constexpr std::uint64_t tokenClass = 0x680000;
void* __cdecl AttachEmpty(void* object, std::int32_t kind) {
    auto* attached = Attach(object, kind);
    active->SetReference(0); active->Put(config + 0x38, reference);
    return attached;
}
void* __cdecl NullReference(std::uint32_t id) {
    ++active->reference_calls; Check(id == bag_id, "failed original factory used bag ID"); return nullptr;
}
void __cdecl RecoveryNotify(void* managerArg, void* object) {
    ++notifies;
    Check(reinterpret_cast<std::uint64_t>(managerArg) == editManager && reinterpret_cast<std::uint64_t>(object) == wrapper,
        "recovery notifies only original wrapper");
    Check(active->attach_calls == 1 && active->reference_calls == 1 && !active->setter_calls && !active->add_calls,
        "recovery never repeats attachment/factory or starts setter/add");
    if (failStage == 3) throw std::runtime_error("notify");
    if (!skipDirty) active->Put<std::uint8_t>(editRecord + 0x30, 1);
    active->Put<std::uint8_t>(wrapper + 0x30, 1);
}
bool RecoveryRead(void* context, std::uint64_t at, void* target, std::size_t size) noexcept {
    if (at >= transaction && at < transaction + 0x20) { ++tokenReads; return false; }
    return Memory::Read(context, at, target, size);
}
bool __cdecl CloseCore(void* managerArg, std::int32_t depth, bool merge, void* label, bool skip) {
    ++closes;
    Check(reinterpret_cast<std::uint64_t>(managerArg) == editManager && depth == prior.action.edit.before.depth && !merge && !label && !skip,
        "core uses original manager/depth/false/null/false ABI");
    Check(recoveryResult.closeCoreCalled && recoveryResult.edit.closeCalled && recoveryResult.edit.stage == ge::component_edit::Stage::close,
        "caller-owned progress is visible before native core starts");
    Check(notifies == 1 && active->Get<std::uint8_t>(editRecord + 0x30) == 1, "dirty readback precedes core close");
    if (failStage == 4) throw std::runtime_error("close core");
    if (failStage == 5) return false;
    active->Put<std::int32_t>(editManager + 0x34, depth); active->Put<std::uint32_t>(editList + 0x18, 0);
    active->Put<std::uint32_t>(editList + 0x1c, 10); return true;
}
struct RecoveryInvocation {
    Invocation initial{33};
    BindingRecoveryReview review{42, 73, 10, 11, 200, &initial.expected, &prior,
        {entity_id, bag_id, 0x40123456, owner, wrapper, config, transaction}, &tokenRefusal, &reviewedPending};
    BindingRecoveryRuntime runtime{42, 73, 10, 11, 100, true, true, true, true};
    RecoveryNativeCalls calls{RecoveryNotify, CloseCore};
    explicit RecoveryInvocation(Memory& m) {
        PrepareEdit(m); Configure(initial);
        initial.calls.attach = AttachEmpty; initial.calls.bind.createReference = NullReference;
        Check(initial.Run(m) == BindingActionCode::binding_failed && result.edit.snapshotVerified && !notifies && !closes,
            "construct actual null-reference failure with original transaction open");
        std::memset(&prior, 0, sizeof(prior)); prior.size = sizeof(prior); prior.version = 2;
        prior.afterSceneUnchanged = 1; prior.metadataCallsStarted = prior.metadataCallsCompleted = 17;
        prior.nativeCallAttempted = prior.componentMutationCalled = prior.runtimeStateMayHaveChanged = true;
        prior.action = result; prior.after = initial.current; prior.workspace = workspace;
        prior.initializedClasses[5] = reference_class;
        ge::component_attachment::CaptureComponents({&m, Memory::Read}, owner, &prior.workspace.attachment.capture, &prior.workspace.postComponents);
        m.imageSlots[module + 0x57d7c90] = tokenClass; m.Put(transaction, tokenClass);
        m.Put<std::uint64_t>(transaction + 0x10, 0); m.Put<std::int32_t>(transaction + 0x18, 0);
        m.Put<std::uint16_t>(transaction + 0x1c, 0);
        std::memset(&recoveryResult, 0, sizeof(recoveryResult));
        std::memset(&tokenRefusal, 0, sizeof(tokenRefusal));
        tokenRefusal.code = BindingRecoveryCode::token_changed;
        tokenRefusal.identityVerified = tokenRefusal.emptyReferenceVerified = tokenRefusal.needsBinding = tokenRefusal.outcomeUncertain = true;
        tokenRefusal.emptyReference = reference; tokenRefusal.edit = prior.action.edit; tokenReads = 0;
        m.Put(editItems + 0x28, appendedRecord); m.Put(appendedRecord, appendedClass);
        m.Put<std::uint32_t>(editList + 0x18, 2);
        m.Put<std::uint32_t>(editList + 0x1c, prior.action.edit.afterSnapshot.version + 1);
        ge::component_edit::CaptureEditState({&m, Memory::Read}, prior.action.edit.evidence, &reviewedPending);
    }
    BindingRecoveryCode Run(Memory& m) {
        CloseUnboundBagAttachment(&initial.current, review, runtime, {&m, RecoveryRead}, calls, &recoveryWork, &recoveryResult);
        return recoveryResult.code;
    }
};
void NoRecoveryCalls() { Check(opens == 1 && snapshots == 1 && !notifies && !closes, "mismatch rejects before recovery native calls"); }
}
int main() {
    { Memory m(33); RecoveryInvocation r(m);
      Check(r.Run(m) == BindingRecoveryCode::transaction_closed, "empty attachment transaction closes");
      Check(recoveryResult.transactionClosed && recoveryResult.needsBinding && recoveryResult.outcomeUncertain,
        "closure does not claim binding/persistence success");
      Check(recoveryResult.edit.closeVerified && !recoveryResult.edit.transactionMayBeOpen && opens == 1 && snapshots == 1 && notifies == 1 && closes == 1,
        "only original transaction notified and closed once");
      Check(m.Get<std::uint32_t>(reference + 0x1c) == 0 && m.Get<std::uint64_t>(config + 0x38) == reference,
        "native empty reference retained");
      Check(recoveryResult.emptyReferenceClassification == 0 && recoveryResult.emptyReferenceId == 0,
        "raw recovery result retains actual empty classification and ID");
      Check(!tokenReads && !recoveryResult.tokenVerified && recoveryResult.originalTokenUnused && recoveryResult.closeCoreCalled &&
        recoveryResult.closeCoreReturned && recoveryResult.pendingScopeVerified && recoveryResult.recoveryVersion == 2,
        "v2 never reads or pretends to verify/recycle old token");
      Check(r.Run(m) == BindingRecoveryCode::duplicate_attempt && notifies == 1 && closes == 1, "retained recovery result cannot replay"); }
    for (int scenario = 0; scenario < 12; ++scenario) {
        Memory m(33); RecoveryInvocation r(m);
        switch (scenario) {
        case 0: ++r.runtime.processCreation; break;
        case 1: r.runtime.priorReceiptHashVerified = false; break;
        case 2: ++r.review.identity.transaction; break;
        case 3: prior.action.binding.setterCalled = true; break;
        case 4: tokenRefusal.edit.closeCalled = true; break;
        case 5: r.runtime.tokenRefusalHashVerified = false; break;
        case 6: m.Put<std::uint32_t>(reference + 0x1c, bag_id); break;
        case 7: m.Put<std::uint8_t>(editRecord + 0x30, 1); break;
        case 8: m.Put<std::uint32_t>(wrapper + 0x1c, 17); break;
        case 9: m.Put<std::uint32_t>(editList + 0x1c, 99); break;
        case 10: r.runtime.reviewedPendingHashVerified = false; break;
        case 11: m.Put(appendedRecord, appendedClass + 8); break;
        }
        Check(r.Run(m) != BindingRecoveryCode::transaction_closed, "changed source/session/token/pending/component/field rejected"); NoRecoveryCalls();
        if (scenario < 4) Check(recoveryResult.emptyReferenceId == 0xffffffffU, "unread default ID remains sentinel");
    }
    { Memory m(33); RecoveryInvocation r(m); failStage = 3;
      Check(r.Run(m) == BindingRecoveryCode::edit_failed && notifies == 1 && !closes && recoveryResult.edit.notifyCalled,
        "notify exception retains attempted state without close");
      Check(r.Run(m) == BindingRecoveryCode::duplicate_attempt && notifies == 1, "uncertain notify cannot retry"); }
    { Memory m(33); RecoveryInvocation r(m); skipDirty = true;
      Check(r.Run(m) == BindingRecoveryCode::edit_failed && notifies == 1 && !closes, "no dirty readback means no close"); }
    { Memory m(33); RecoveryInvocation r(m); failStage = 4;
      Check(r.Run(m) == BindingRecoveryCode::edit_failed && recoveryResult.edit.closeCalled && !recoveryResult.transactionClosed,
        "close exception never invents closed success"); }
    { Memory m(33); RecoveryInvocation r(m); failStage = 5;
      Check(r.Run(m) == BindingRecoveryCode::edit_failed && recoveryResult.closeCoreCalled && !recoveryResult.closeCoreReturned &&
        recoveryResult.edit.transactionMayBeOpen, "false core return retains open uncertainty"); }
    for (bool environmentChanged : {false, true}) {
        Memory m(33); RecoveryInvocation r(m);
        if (environmentChanged) m.Put<std::uint64_t>(wrapper_class + 0x130, 0);
        else m.Put<std::uint32_t>(editList + 0x1c, 99);
        ReadUnboundBagEditDiagnostic(&r.initial.current, r.review, r.runtime, {&m, RecoveryRead}, {}, &recoveryWork, &recoveryResult);
        Check(recoveryResult.code == BindingRecoveryCode::diagnostic_read && !notifies && !closes && !tokenReads,
            "readonly diagnostic makes no native or token calls");
        Check(recoveryResult.edit.afterNotify.code == ge::component_edit::ReadCode::complete && recoveryResult.edit.afterNotify.count == 2,
            "current pending state retained even after environment refusal");
        Check(environmentChanged ? recoveryResult.edit.code == ge::component_edit::Code::invalid_environment :
            recoveryResult.edit.afterNotify.version == 99, "diagnostic exposes actual readiness failure or current changed version");
    }
    std::printf("binding_recovery_test: %d checks passed; synthetic only\n", checks);
    std::printf("RecoveryResult=%zu editOffset=%zu RecoveryWorkspace=%zu\n", sizeof(BindingRecoveryResult),
        offsetof(BindingRecoveryResult, edit), sizeof(BindingRecoveryWorkspace));
    return 0;
}
