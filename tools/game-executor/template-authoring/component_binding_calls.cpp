#include "component_binding_calls.h"

namespace ge::component_binding {
namespace {
void starting_mutation(BindResult& result) {
    result.mutationCalled = true;
    result.outcomeUncertain = true;
    result.needsOwnerNotification = true;
    result.needsDependencyRefresh = true;
}
void bind(Kind kind, const NativeCalls& calls, const Readbacks& reads,
          const Evidence& evidence, BindResult& result, bool fieldsOnly = false) {
    result = {};
    if (evidence.kind != kind || !evidence.owner || !evidence.config || !evidence.templateId ||
        !evidence.ownerAndConfigVerified || !evidence.templateExistsAndKindVerified)
        return;
    const bool shop = kind == Kind::shop;
    const auto setter = shop ? calls.setShopReference : calls.setBagReference;
    const auto refresh = shop ? calls.refreshShopDependencies : calls.refreshBagDependencies;
    const auto hash = shop ? shop_reference_hash : bag_reference_hash;
    const bool typed = calls.createTypedReference || calls.initializeReferenceId || calls.referenceTypeName;
    if ((typed ? (!calls.createTypedReference || !calls.initializeReferenceId || !calls.referenceTypeName) : !calls.createReference) ||
        !setter || !reads.referenceId || !reads.boundId ||
        (shop && (!calls.addShopEntry || !reads.entryIndex))) {
        result.code = BindCode::missing_binding;
        return;
    }
    try {
        result.referenceFactoryCalled = true;
        result.exceptionStage = BindStage::reference_factory;
        result.reference = typed ? calls.createTypedReference(calls.referenceTypeName) : calls.createReference(evidence.templateId);
        result.exceptionStage = BindStage::none;
        if (!result.reference) { result.code = BindCode::null_reference; return; }
        std::uint32_t id = 0;
        if (typed) {
            // The pool initializes this reference to ID/classifier zero. Read
            // the actual object/class before invoking its formal ID setter.
            if (!reads.referenceId(reads.context, result.reference, &id)) {
                result.code = BindCode::reference_readback_failed; return;
            }
            if (id != 0) { result.code = BindCode::reference_id_mismatch; return; }
            result.exceptionStage = BindStage::reference_initialize;
            calls.initializeReferenceId(result.reference, evidence.templateId);
            result.exceptionStage = BindStage::none;
        }
        if (!reads.referenceId(reads.context, result.reference, &id)) {
            result.code = BindCode::reference_readback_failed; return;
        }
        if (id != evidence.templateId) {
            result.code = BindCode::reference_id_mismatch; return;
        }
        result.referenceReadbackVerified = true;
        void* target = evidence.config;
        if (shop) {
            starting_mutation(result);
            result.addCalled = true;
            result.exceptionStage = BindStage::shop_add;
            result.entry = calls.addShopEntry(evidence.config);
            result.exceptionStage = BindStage::none;
            if (!result.entry) { result.code = BindCode::null_entry; return; }
            std::int32_t index = 0;
            if (!reads.entryIndex(reads.context, result.entry, &index)) {
                result.code = BindCode::entry_index_readback_failed; return;
            }
            // Native8250dc0 allocates positive int32 IDs beginning at1. No
            // guessed maximum, list offset or CLI default is substituted here.
            if (index <= 0) { result.code = BindCode::invalid_entry_index; return; }
            result.shopIndex = index;
            result.entryIndexReadbackVerified = true;
            target = result.entry;
        }
        starting_mutation(result);
        result.setterCalled = true;
        result.exceptionStage = BindStage::setter;
        setter(target, hash, result.reference);
        result.exceptionStage = BindStage::none;
        id = 0;
        if (!reads.boundId(reads.context, target, hash, &id)) {
            result.code = BindCode::binding_readback_failed; return;
        }
        if (id != evidence.templateId) {
            result.code = BindCode::binding_id_mismatch; return;
        }
        result.fieldReadbackVerified = true;
        if (refresh && !fieldsOnly) {
            result.dependencyRefreshCalled = true;
            result.exceptionStage = BindStage::dependency_refresh;
            refresh(evidence.config, 0, nullptr);
            result.exceptionStage = BindStage::none;
            // Only the required call completed; dependency state is not claimed
            // verified and outcomeUncertain/needsOwnerNotification stay true.
            result.needsDependencyRefresh = false;
        }
        result.code = BindCode::returned;
    } catch (...) {
        result.code = BindCode::call_exception;
    }
}
}
BindResult bind_shop(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence) {
    BindResult result; bind_shop_into(calls, reads, evidence, &result); return result;
}
BindResult bind_bag(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence) {
    BindResult result; bind_bag_into(calls, reads, evidence, &result); return result;
}
void bind_shop_into(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence, BindResult* out) {
    if (out) bind(Kind::shop, calls, reads, evidence, *out);
}
void bind_bag_into(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence, BindResult* out) {
    if (out) bind(Kind::bag, calls, reads, evidence, *out);
}
void bind_shop_fields_into(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence, BindResult* out) {
    if (out) bind(Kind::shop, calls, reads, evidence, *out, true);
}
void bind_bag_fields_into(const NativeCalls& calls, const Readbacks& reads, const Evidence& evidence, BindResult* out) {
    if (out) bind(Kind::bag, calls, reads, evidence, *out, true);
}
}
