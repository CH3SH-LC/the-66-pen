#include "../trigger_calls.h"
#include <cstdio>
#include <limits>
#include <stdexcept>
using namespace ge::trigger_region;
namespace {
int owner, region, box, checks, writes, gets;
float vectors[3][3] = {};
unsigned shape = 0;
bool missing_last = false, aliases = false, throw_set = false, corrupt = false;
Result result;
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
    ++checks;
}
void reset() {
    writes = gets = 0; shape = 0;
    missing_last = aliases = throw_set = corrupt = false;
    for (auto& v : vectors) for (float& x : v) x = 0;
}
bool verify(void*, void* value, ObjectKind kind) {
    if (kind == ObjectKind::region) return value == &region;
    if (kind == ObjectKind::box) return value == &box;
    return value == vectors[0] || value == vectors[1] || value == vectors[2];
}
std::uint32_t __cdecl get_shape(void* p, std::uint32_t hash, const void* mi) {
    ++gets; check(p == &region && hash == shape_hash && !mi, "shape ABI"); return shape;
}
void* __cdecl get_box(void* p, std::uint32_t hash, const void* mi) {
    check(p == &region && hash == box_hash && !mi, "region getter ABI"); return &box;
}
void* __cdecl get_vector(void* p, std::uint32_t hash, const void* mi) {
    check(p == &box && !mi, "box getter target and MethodInfo");
    for (unsigned i = 0; i < 3; ++i) if (hash == vector_hashes[i]) {
        if (i == 2 && missing_last) return nullptr;
        return vectors[aliases ? 0 : i];
    }
    throw std::runtime_error("unknown vector field");
}
float __cdecl get_axis(void* p, std::uint32_t hash, const void* mi) {
    check(!mi, "read MethodInfo is null");
    for (unsigned a = 0; a < 3; ++a) if (hash == axis_hashes[a]) return static_cast<float*>(p)[a];
    throw std::runtime_error("unknown axis field");
}
void __cdecl set_axis(void* p, std::uint32_t hash, float value, const void* mi) {
    ++writes;
    check(!mi && result.mutationCalled && result.outcomeUncertain && result.needsOwnerNotification,
          "progress visible inside native setter");
    check(result.settersStarted == static_cast<unsigned>(writes) && result.exceptionStage == Stage::setter,
          "caller-owned call count and fault stage precede call");
    if (throw_set) throw std::runtime_error("fake native failure");
    for (unsigned a = 0; a < 3; ++a) if (hash == axis_hashes[a]) {
        static_cast<float*>(p)[a] = value;
        if (corrupt && writes == 9) vectors[0][0] += 1;
        return;
    }
    throw std::runtime_error("unknown setter axis");
}
}
int main() {
    try {
        NativeCalls n{get_shape, get_box, get_vector, get_axis, set_axis};
        Evidence e{&owner, &region, true, nullptr, verify};
        BoxValues desired{{-3.25f, 0.5f, 7.75f}, {2.5f, 1.25f, 4.5f}, {15.5f, 90.25f, -30.75f}};
        reset(); configure_box_into(n, e, desired, &result);
        check(result.code == Code::configured && result.axesVerified == 9 && result.readbackVerified, "nine axes read back");
        check(writes == 9 && vectors[0][0] == -3.25f && vectors[1][1] == 1.25f && vectors[2][2] == -30.75f,
              "float argument and center-scale-rotate ordering");
        check(result.outcomeUncertain && result.needsOwnerNotification, "geometry readback does not claim owner completion");
        read_box_into(n, e, &result);
        check(result.code == Code::read_returned && !result.mutationCalled && result.observed.rotate[1] == 90.25f,
              "read-only path returns actual native values");
        reset(); missing_last = true; configure_box_into(n, e, desired, &result);
        check(result.code == Code::unexpected_object && !writes, "preflight all vectors before writing");
        reset(); aliases = true; configure_box_into(n, e, desired, &result);
        check(result.code == Code::aliased_vectors && !writes, "reject ambiguous shared vectors before mutation");
        reset(); shape = 1; configure_box_into(n, e, desired, &result);
        check(result.code == Code::unsupported_shape && !writes, "never reinterpret sphere as box");
        reset(); e.currentRegionAndOwnerVerified = false; configure_box_into(n, e, desired, &result);
        check(result.code == Code::invalid_evidence && !gets && !writes, "missing ownership evidence causes zero native calls");
        e.currentRegionAndOwnerVerified = true;
        reset(); BoxValues invalid = desired; invalid.scale[0] = 0;
        configure_box_into(n, e, invalid, &result);
        check(result.code == Code::invalid_values && !gets && !writes, "zero scale fails before calls");
        invalid = desired; invalid.center[0] = std::numeric_limits<float>::infinity();
        configure_box_into(n, e, invalid, &result);
        check(result.code == Code::invalid_values && !gets, "nonfinite input fails before calls");
        reset(); throw_set = true; configure_box_into(n, e, desired, &result);
        check(result.code == Code::call_exception && result.settersStarted == 1 && result.exceptionStage == Stage::setter,
              "setter fault retains started mutation, no retry");
        reset(); corrupt = true; configure_box_into(n, e, desired, &result);
        check(result.code == Code::readback_mismatch && !result.readbackVerified && writes == 9,
              "final readback catches earlier-axis overwrite, no rollback");
        std::printf("trigger_calls checks=%d passed\n", checks); return 0;
    } catch (const std::exception& ex) { std::fprintf(stderr, "%s\n", ex.what()); return 1; }
}
