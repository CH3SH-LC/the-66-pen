#include "trigger_calls.h"
#include <cmath>

namespace ge::trigger_region {
namespace {
const float* vector_at(const BoxValues& v, unsigned i) {
    return i == 0 ? v.center : i == 1 ? v.scale : v.rotate;
}
float* vector_at(BoxValues& v, unsigned i) {
    return i == 0 ? v.center : i == 1 ? v.scale : v.rotate;
}
bool preflight(const NativeCalls& n, const Evidence& e, Result& out) {
    if (!e.owner || !e.region || !e.currentRegionAndOwnerVerified || !e.verifyObject) {
        out.code = Code::invalid_evidence; return false;
    }
    if (!n.shape || !n.regionObject || !n.boxVector || !n.vectorAxis) {
        out.code = Code::missing_binding; return false;
    }
    out.exceptionStage = Stage::preflight;
    if (!e.verifyObject(e.context, e.region, ObjectKind::region)) {
        out.code = Code::unexpected_object; return false;
    }
    if (n.shape(e.region, shape_hash, nullptr) != 0) {
        out.code = Code::unsupported_shape; return false;
    }
    out.box = n.regionObject(e.region, box_hash, nullptr);
    if (!out.box || !e.verifyObject(e.context, out.box, ObjectKind::box)) {
        out.code = Code::unexpected_object; return false;
    }
    for (unsigned i = 0; i < 3; ++i) {
        out.vectors[i] = n.boxVector(out.box, vector_hashes[i], nullptr);
        if (!out.vectors[i] || !e.verifyObject(e.context, out.vectors[i], ObjectKind::vector)) {
            out.code = Code::unexpected_object; return false;
        }
        for (unsigned j = 0; j < i; ++j) if (out.vectors[i] == out.vectors[j]) {
            out.code = Code::aliased_vectors; return false;
        }
    }
    out.exceptionStage = Stage::none;
    return true;
}
void read_values(const NativeCalls& n, Result& out) {
    out.exceptionStage = Stage::read;
    for (unsigned i = 0; i < 3; ++i) for (unsigned a = 0; a < 3; ++a)
        vector_at(out.observed, i)[a] = n.vectorAxis(out.vectors[i], axis_hashes[a], nullptr);
    out.exceptionStage = Stage::none;
    out.readbackVerified = true;
}
bool valid(const BoxValues& v) {
    for (unsigned i = 0; i < 3; ++i) for (unsigned a = 0; a < 3; ++a)
        if (!std::isfinite(vector_at(v, i)[a])) return false;
    for (float value : v.scale) if (value <= 0) return false;
    return true;
}
}
void read_box_into(const NativeCalls& n, const Evidence& e, Result* result) {
    if (!result) return;
    *result = Result{};
    try {
        if (!preflight(n, e, *result)) return;
        read_values(n, *result);
        result->code = Code::read_returned;
    } catch (...) { result->code = Code::call_exception; }
}
void configure_box_into(const NativeCalls& n, const Evidence& e,
                        const BoxValues& values, Result* result) {
    if (!result) return;
    *result = Result{};
    if (!valid(values)) { result->code = Code::invalid_values; return; }
    if (!n.setVectorAxis) { result->code = Code::missing_binding; return; }
    try {
        if (!preflight(n, e, *result)) return;
        for (unsigned i = 0; i < 3; ++i) for (unsigned a = 0; a < 3; ++a) {
            result->exceptionStage = Stage::setter;
            result->mutationCalled = result->outcomeUncertain = result->needsOwnerNotification = true;
            ++result->settersStarted;
            n.setVectorAxis(result->vectors[i], axis_hashes[a], vector_at(values, i)[a], nullptr);
        }
        // Read all nine values after all setters: catches a setter modifying a
        // previously written axis. Successful readback leaves owner work pending.
        result->exceptionStage = Stage::readback;
        for (unsigned i = 0; i < 3; ++i) for (unsigned a = 0; a < 3; ++a) {
            float got = n.vectorAxis(result->vectors[i], axis_hashes[a], nullptr);
            vector_at(result->observed, i)[a] = got;
            if (got != vector_at(values, i)[a]) {
                result->code = Code::readback_mismatch;
                result->exceptionStage = Stage::none;
                return;
            }
            ++result->axesVerified;
        }
        result->readbackVerified = true;
        result->exceptionStage = Stage::none;
        result->code = Code::configured;
    } catch (...) { result->code = Code::call_exception; }
}
}
