#include "trigger_region_add.h"
#include <cmath>

namespace ge::trigger_region_add {
namespace {
bool valid(const trigger_region::BoxValues& v) {
    for (unsigned a = 0; a != 3; ++a)
        if (!std::isfinite(v.center[a]) || !std::isfinite(v.rotate[a]) ||
            !std::isfinite(v.scale[a]) || v.scale[a] <= 0) return false;
    return true;
}
bool capture(const Calls& n, const Evidence& e, Row* rows, std::uint32_t& size) {
    if (n.getList(e.parentEntry, e.managedListName) != e.collection) return false;
    const auto actual = n.count(e.collection, n.countMethodInfo);
    if (actual < 0 || static_cast<std::size_t>(actual) > capture_capacity) return false;
    if (!e.capture(e.context, e.collection, rows, capture_capacity, &size) ||
        size != static_cast<std::uint32_t>(actual)) return false;
    for (std::uint32_t i = 0; i < size; ++i) {
        if (!rows[i].region || !rows[i].index) return false;
        for (std::uint32_t j = 0; j < i; ++j)
            if (rows[j].region == rows[i].region || rows[j].index == rows[i].index) return false;
    }
    return true;
}
bool appended(const Result& out) {
    if (out.afterCount != out.beforeCount + 1) return false;
    for (std::uint32_t i = 0; i < out.beforeCount; ++i)
        if (out.before[i].region != out.after[i].region ||
            out.before[i].index != out.after[i].index) return false;
    return out.after[out.beforeCount].region == out.region &&
           out.after[out.beforeCount].index == out.index;
}
}
void add_box_into(const Calls& n, const Evidence& e,
                  const trigger_region::BoxValues& values, Result* out) {
    if (!out) return;
    *out = Result{};
    out->needsTransactionClose = e.transactionToken != nullptr;
    if (!e.editObject || !e.parentEntry || !e.collection || !e.transactionToken ||
        !e.transactionSnapshotVerified || !e.currentParentAndBuildVerified ||
        !e.managedRegionName || !e.managedListName || !e.exactManagedLiteralsVerified ||
        !e.nativeLimitVerified || !e.nativeLimit || !e.capture || !e.verifyObject) return;
    const auto& g = n.geometry;
    if (!n.factory || !n.getList || !n.number || !n.getIndex || !n.count ||
        !n.countMethodInfo || !n.append || !n.appendMethodInfo || !g.shape ||
        !g.regionObject || !g.boxVector || !g.vectorAxis || !g.setVectorAxis) {
        out->code = Code::missing_binding; return;
    }
    if (!valid(values)) { out->code = Code::invalid_values; return; }
    try {
        out->exceptionStage = Stage::before_capture;
        if (!capture(n, e, out->before, out->beforeCount)) {
            out->code = Code::readback_failed; return;
        }
        if (out->beforeCount >= e.nativeLimit || out->beforeCount >= capture_capacity) {
            out->code = Code::at_limit; return;
        }
        out->exceptionStage = Stage::factory;
        out->factoryCalled = out->mutationCalled = out->outcomeUncertain = true;
        out->region = n.factory(e.managedRegionName);
        if (!out->region) { out->code = Code::factory_null; return; }
        if (!e.verifyObject(e.context, out->region, trigger_region::ObjectKind::region)) {
            out->code = Code::unexpected_region; return;
        }
        for (std::uint32_t i = 0; i < out->beforeCount; ++i)
            if (out->before[i].region == out->region) {
                out->code = Code::unexpected_region; return;
            }
        out->exceptionStage = Stage::number;
        out->numberingCalled = true;
        n.number(e.parentEntry, out->region, e.managedListName);
        out->exceptionStage = Stage::index;
        out->index = n.getIndex(out->region, index_hash, nullptr);
        if (!out->index) { out->code = Code::invalid_index; return; }
        for (std::uint32_t i = 0; i < out->beforeCount; ++i)
            if (out->before[i].index == out->index) {
                out->code = Code::invalid_index; return;
            }
        out->exceptionStage = Stage::append;
        out->appendCalled = out->needsOwnerNotification = true;
        n.append(e.collection, out->region, n.appendMethodInfo);
        out->exceptionStage = Stage::appended_capture;
        if (!capture(n, e, out->after, out->afterCount) || !appended(*out)) {
            out->code = Code::append_mismatch; return;
        }
        out->membershipVerified = true;
        // Membership is real before reusing the existing-region geometry API.
        // Default initialized box is appended first, exactly as the native UI.
        const trigger_region::Evidence geometryEvidence{
            e.editObject, out->region, true, e.context, e.verifyObject};
        out->exceptionStage = Stage::geometry;
        trigger_region::configure_box_into(g, geometryEvidence, values, &out->geometry);
        if (out->geometry.code != trigger_region::Code::configured || !out->geometry.readbackVerified) {
            out->code = Code::geometry_failed; return;
        }
        out->geometryVerified = true;
        out->exceptionStage = Stage::final_capture;
        out->membershipVerified = false;
        if (!capture(n, e, out->after, out->afterCount) || !appended(*out)) {
            out->code = Code::append_mismatch; return;
        }
        out->membershipVerified = true;
        out->exceptionStage = Stage::none;
        out->code = Code::added_pending_notification;
    } catch (...) { out->code = Code::call_exception; }
}
}
