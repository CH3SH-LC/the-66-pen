#include "../trigger_region_add.h"
#include <cstdio>
#include <limits>
#include <stdexcept>
using namespace ge::trigger_region_add;
namespace tr = ge::trigger_region;
namespace {
int editObject, parent, collection, transaction, regionName, listName, countMI, addMI;
int oldA, oldB, newRegion, box, checks = 0;
int factories, numbers, appends, writes;
unsigned nextIndex, captures;
bool nullFactory, failAppend, badPrefix, badCapture, badList, badGeometry;
Row rows[3]; unsigned rowCount;
float vectors[3][3];
Result result;
void check(bool v, const char* message) { if (!v) throw std::runtime_error(message); ++checks; }
void reset() {
    factories = numbers = appends = writes = 0; captures = 0; nextIndex = 7;
    nullFactory = failAppend = badPrefix = badCapture = badList = badGeometry = false;
    rows[0] = Row{&oldA, 2}; rows[1] = Row{&oldB, 9}; rowCount = 2;
    for (auto& v : vectors) for (auto& a : v) a = 0;
}
void* __cdecl factory(const void* name) {
    ++factories;
    check(name == &regionName && result.factoryCalled && result.mutationCalled &&
          result.outcomeUncertain && result.exceptionStage == Stage::factory,
          "factory has correct name and caller-owned progress");
    return nullFactory ? nullptr : &newRegion;
}
void* __cdecl get_list(void* p, const void* name) {
    check(p == &parent && name == &listName, "official property getter ABI");
    return badList ? nullptr : &collection;
}
void __cdecl number(void* p, void* r, const void* name) {
    ++numbers;
    check(p == &parent && r == &newRegion && name == &listName &&
          result.numberingCalled && result.exceptionStage == Stage::number,
          "formal numbering argument order and progress");
}
std::uint32_t __cdecl index(void* r, std::uint32_t hash, const void* mi) {
    check(r == &newRegion && hash == index_hash && !mi, "index getter ABI");
    return nextIndex;
}
std::int32_t __cdecl count(void* p, const void* mi) {
    check(p == &collection && mi == &countMI, "count uses real hidden MethodInfo");
    return static_cast<std::int32_t>(rowCount);
}
void __cdecl append(void* p, void* r, const void* mi) {
    ++appends;
    check(p == &collection && r == &newRegion && mi == &addMI &&
          result.appendCalled && result.needsOwnerNotification &&
          result.exceptionStage == Stage::append, "append ABI and pre-call progress");
    rows[rowCount++] = Row{r, nextIndex};
    if (failAppend) throw std::runtime_error("append fault after mutation");
}
bool capture(void*, void* p, Row* out, std::size_t capacity, std::uint32_t* n) {
    ++captures;
    check(p == &collection && capacity >= rowCount, "actual collection capture");
    if (badCapture) return false;
    *n = rowCount;
    for (unsigned i = 0; i < rowCount; ++i) out[i] = rows[i];
    if (badPrefix && rowCount == 3) out[0].index = 3;
    return true;
}
bool verify(void*, void* p, tr::ObjectKind k) {
    if (k == tr::ObjectKind::region) return p == &newRegion;
    if (k == tr::ObjectKind::box) return p == &box;
    return p == vectors[0] || p == vectors[1] || p == vectors[2];
}
std::uint32_t __cdecl shape(void* p, std::uint32_t hash, const void* mi) {
    check(p == &newRegion && hash == tr::shape_hash && !mi, "shape getter ABI"); return 0;
}
void* __cdecl get_box(void*, std::uint32_t hash, const void*) {
    check(hash == tr::box_hash, "box hash"); return &box;
}
void* __cdecl vector(void*, std::uint32_t hash, const void*) {
    for (unsigned i = 0; i < 3; ++i) if (hash == tr::vector_hashes[i]) return vectors[i];
    return nullptr;
}
float __cdecl axis(void* p, std::uint32_t hash, const void*) {
    for (unsigned i = 0; i < 3; ++i) if (hash == tr::axis_hashes[i]) return static_cast<float*>(p)[i];
    throw std::runtime_error("axis hash");
}
void __cdecl set_axis(void* p, std::uint32_t hash, float value, const void* mi) {
    ++writes;
    check(result.appendCalled && result.membershipVerified && result.geometry.mutationCalled &&
          result.exceptionStage == Stage::geometry && !mi, "geometry only after real membership");
    if (badGeometry) throw std::runtime_error("geometry fault");
    for (unsigned i = 0; i < 3; ++i) if (hash == tr::axis_hashes[i]) {
        static_cast<float*>(p)[i] = value; return;
    }
}
Calls calls() { return {factory, get_list, number, index, count, &countMI, append, &addMI,
                       {shape, get_box, vector, axis, set_axis}}; }
Evidence evidence() {
    Evidence e;
    e.editObject = &editObject; e.parentEntry = &parent; e.collection = &collection;
    e.transactionToken = &transaction; e.transactionSnapshotVerified = true;
    e.currentParentAndBuildVerified = true; e.managedRegionName = &regionName;
    e.managedListName = &listName; e.exactManagedLiteralsVerified = true;
    e.nativeLimit = 8; e.nativeLimitVerified = true; e.capture = capture; e.verifyObject = verify;
    return e;
}
}
int main() {
    try {
        auto n = calls(); auto e = evidence();
        tr::BoxValues v{{-2.5f, 1.25f, 5.75f}, {3.5f, 2.5f, 4.5f}, {0, 90.5f, 0}};
        reset(); add_box_into(n, e, v, &result);
        check(result.code == Code::added_pending_notification && result.index == 7 &&
              result.beforeCount == 2 && result.afterCount == 3, "preserve actual native index, not count or zero");
        check(factories == 1 && numbers == 1 && appends == 1 && writes == 9 && captures == 3,
              "one allocation, one numbering, one append, final geometry readback");
        check(result.membershipVerified && result.geometryVerified && result.needsOwnerNotification &&
              result.needsTransactionClose && result.outcomeUncertain, "no owner/transaction completion invented");
        check(vectors[0][1] == 1.25f && vectors[1][0] == 3.5f && vectors[2][1] == 90.5f,
              "desired box values reached formal float setters");
        reset(); e.transactionSnapshotVerified = false; add_box_into(n, e, v, &result);
        check(!factories && !captures && result.code == Code::invalid_evidence, "unverified transaction has zero calls");
        e = evidence(); reset(); e.nativeLimitVerified = false; add_box_into(n, e, v, &result);
        check(!factories && !captures, "unknown limit rejected before native calls");
        e = evidence(); reset(); e.nativeLimit = 2; add_box_into(n, e, v, &result);
        check(result.code == Code::at_limit && !factories && !appends, "real native limit enforced");
        e = evidence(); reset(); n.appendMethodInfo = nullptr; add_box_into(n, e, v, &result);
        check(result.code == Code::missing_binding && !factories && !captures, "missing hidden MI rejected");
        n = calls(); reset(); v.scale[1] = 0; add_box_into(n, e, v, &result);
        check(result.code == Code::invalid_values && !factories && !captures, "bad geometry rejected before allocation");
        v.scale[1] = 2.5f; reset(); badCapture = true; add_box_into(n, e, v, &result);
        check(result.code == Code::readback_failed && !factories, "no readable before means no mutation");
        reset(); badList = true; add_box_into(n, e, v, &result);
        check(result.code == Code::readback_failed && !factories, "parent list identity checked");
        reset(); nullFactory = true; add_box_into(n, e, v, &result);
        check(result.code == Code::factory_null && factories == 1 && !numbers && !appends, "null allocation no further calls");
        reset(); nextIndex = 0; add_box_into(n, e, v, &result);
        check(result.code == Code::invalid_index && !appends && !writes, "zero native index no append");
        reset(); nextIndex = 9; add_box_into(n, e, v, &result);
        check(result.code == Code::invalid_index && !appends, "duplicate index no append");
        reset(); failAppend = true; add_box_into(n, e, v, &result);
        check(result.code == Code::call_exception && result.exceptionStage == Stage::append &&
              result.appendCalled && rowCount == 3 && !writes && appends == 1,
              "append exception preserves caller progress, does not rollback or retry");
        reset(); badPrefix = true; add_box_into(n, e, v, &result);
        check(result.code == Code::append_mismatch && !writes && !result.membershipVerified,
              "existing rows must be preserved before geometry");
        reset(); badGeometry = true; add_box_into(n, e, v, &result);
        check(result.code == Code::geometry_failed && rowCount == 3 && writes == 1 &&
              result.geometry.settersStarted == 1 && result.needsOwnerNotification,
              "geometry exception keeps appended region and precise nested progress");
        std::printf("trigger_region_add checks=%d passed\n", checks); return 0;
    } catch (const std::exception& ex) { std::fprintf(stderr, "%s\n", ex.what()); return 1; }
}
