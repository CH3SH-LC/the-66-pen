#include "trigger_parent_calls.h"

namespace ge::trigger_parent {
namespace {
bool valid(const Snapshot& s, const Evidence& e) {
    if (s.collection != e.collection || s.count > parent_capacity) return false;
    for (std::uint32_t i = 0; i < s.count; ++i) {
        const auto& r = s.rows[i];
        if (!r.object || r.definition != entry_definition || !r.index ||
            r.selectedCount > filter_capacity || r.complementCount > filter_capacity ||
            r.regionCount > region_capacity || r.active > 1 || r.editorEnabled > 1) return false;
        for (std::uint32_t j = 0; j < i; ++j)
            if (r.object == s.rows[j].object || r.index == s.rows[j].index) return false;
        for (std::uint32_t j = 0; j < r.regionCount; ++j)
            if (!r.regions[j].object || r.regions[j].definition != region_definition) return false;
    }
    return true;
}
bool same(const Entry& a, const Entry& b) {
    if (a.object != b.object || a.name != b.name || a.definition != b.definition ||
        a.index != b.index || a.active != b.active || a.editorEnabled != b.editorEnabled ||
        a.selectedCount != b.selectedCount || a.complementCount != b.complementCount ||
        a.regionCount != b.regionCount) return false;
    for (std::uint32_t i = 0; i < a.selectedCount; ++i)
        if (a.selected[i] != b.selected[i]) return false;
    for (std::uint32_t i = 0; i < a.complementCount; ++i)
        if (a.complement[i] != b.complement[i]) return false;
    for (std::uint32_t i = 0; i < a.regionCount; ++i) {
        const auto& x = a.regions[i]; const auto& y = b.regions[i];
        if (x.object != y.object || x.definition != y.definition ||
            x.index != y.index || x.shape != y.shape) return false;
    }
    return true;
}
bool inserted(const Result& r) {
    if (r.after.count != r.before.count + 1) return false;
    const auto& fresh = r.after.rows[0];
    for (std::uint32_t i = 0; i < r.before.count; ++i)
        if (fresh.object == r.before.rows[i].object || fresh.index == r.before.rows[i].index ||
            !same(r.before.rows[i], r.after.rows[i + 1])) return false;
    return true;
}
}
void create_default_into(const NativeCalls& n, const Evidence& e, Result* out) {
    if (!out) return;
    if (out->attemptStarted) { out->code = Code::duplicate_attempt; return; }
    out->attemptStarted = true;
    out->needsTransactionClose = e.transactionToken != nullptr;
    if (!e.controller || !e.owner || !e.editObject || !e.config || !e.propertyWrapper ||
        !e.propertyDescriptor || !e.collection || !e.transactionToken || !e.managedTypeName ||
        !e.currentCodeAndThreadVerified || !e.transactionSnapshotVerified ||
        !e.verifyContext || !e.capture) return;
    if (!n.canAdd || !n.add) { out->code = Code::missing_calls; return; }
    try {
        out->stage = Stage::context;
        if (!e.verifyContext(e.context, e)) { out->code = Code::invalid_context; return; }
        out->stage = Stage::before_capture;
        if (!e.capture(e.context, e.collection, &out->before) || !valid(out->before, e)) {
            out->code = Code::read_failed; return;
        }
        if (out->before.count == parent_capacity) { out->code = Code::receipt_capacity; return; }
        out->stage = Stage::limit;
        out->limitCalled = true;
        if (!n.canAdd(e.controller, e.managedTypeName)) { out->code = Code::at_native_limit; return; }
        out->stage = Stage::recheck;
        if (!e.verifyContext(e.context, e)) { out->code = Code::context_changed; return; }
        out->stage = Stage::add;
        out->addCalled = out->mutationCalled = out->outcomeUncertain = true;
        out->needsOwnerNotification = true;
        // Native 9c464b0 owns allocation, 9c468a0 numbering/naming, wrapper
        // hooks and collection interface slot3 Insert(0,entry,MethodInfo).
        n.add(e.controller, e.managedTypeName);
        out->stage = Stage::after_capture;
        if (!e.capture(e.context, e.collection, &out->after) || !valid(out->after, e)) {
            out->code = Code::read_failed; return;
        }
        if (!inserted(*out)) { out->code = Code::unexpected_change; return; }
        out->entry = out->after.rows[0].object;
        out->index = out->after.rows[0].index;
        out->structureVerified = true;
        out->stage = Stage::none;
        out->code = Code::created_pending_notification;
    } catch (...) { out->code = Code::call_exception; }
}
}
