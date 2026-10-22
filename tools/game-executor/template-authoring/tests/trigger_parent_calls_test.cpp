#include "../trigger_parent_calls.h"
#include <cstdio>
#include <stdexcept>
using namespace ge::trigger_parent;
namespace {
int controller, owner, editObject, config, wrapper, descriptor, collection, transaction, typeName;
int oldA, oldB, fresh, region, name, checks;
unsigned gates, adds, captures, verifications;
bool limitOK, contextOK, contextDrifts, throwGate, throwAdd, failAfter;
bool appendInstead, alterOld, wrongClass, wrongRegion, duplicateIndex, reuseEntry, noInsert;
Snapshot live;
Result result;
void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
    ++checks;
}
Entry make_entry(void* object, std::uint32_t id) {
    Entry e;
    e.object = object; e.name = &name; e.definition = entry_definition; e.index = id;
    e.active = e.editorEnabled = 1;
    e.selectedCount = 1; e.selected[0] = 17;
    e.complementCount = 2; e.complement[0] = -4; e.complement[1] = 91;
    e.regionCount = 1; e.regions[0] = Region{&region, region_definition, 0, 0};
    return e;
}
void reset() {
    result = Result{}; live = Snapshot{};
    gates = adds = captures = verifications = 0;
    limitOK = contextOK = true;
    contextDrifts = throwGate = throwAdd = failAfter = false;
    appendInstead = alterOld = wrongClass = wrongRegion = duplicateIndex = reuseEntry = noInsert = false;
    live.collection = &collection; live.count = 2;
    live.rows[0] = make_entry(&oldA, 2); live.rows[1] = make_entry(&oldB, 9);
}
bool verify(void*, const Evidence& e) {
    ++verifications;
    check(e.controller == &controller && e.config == &config && e.propertyWrapper == &wrapper &&
          e.propertyDescriptor == &descriptor && e.editObject == &editObject && e.owner == &owner,
          "host receives actual controller/config/wrapper/owner relations");
    return contextOK && !(contextDrifts && verifications == 2);
}
bool capture(void*, void* list, Snapshot* out) {
    ++captures;
    check(list == &collection, "capture gets exact verified collection");
    if (failAfter && adds) return false;
    *out = live;
    return true;
}
bool __cdecl can_add(void* receiver, const void* literal) {
    ++gates;
    check(receiver == &controller && literal == &typeName && result.limitCalled &&
          result.stage == Stage::limit && !result.addCalled, "limit ABI and pre-call progress");
    if (throwGate) throw std::runtime_error("gate fault");
    return limitOK;
}
void __cdecl add(void* receiver, const void* literal) {
    ++adds;
    check(receiver == &controller && literal == &typeName && result.addCalled &&
          result.mutationCalled && result.outcomeUncertain && result.needsOwnerNotification &&
          result.needsTransactionClose && result.stage == Stage::add,
          "add ABI and caller-owned mutation progress visible inside native call");
    if (!noInsert) {
        const auto freshRow = make_entry(reuseEntry ? &oldA : &fresh, duplicateIndex ? 9 : 7);
        if (appendInstead) live.rows[live.count] = freshRow;
        else {
            for (unsigned i = live.count; i; --i) live.rows[i] = live.rows[i - 1];
            live.rows[0] = freshRow;
        }
        ++live.count;
        if (wrongClass) live.rows[0].definition = 55635;
        if (wrongRegion) live.rows[0].regions[0].definition = 1;
        if (alterOld) live.rows[1].selected[0] = 0;
    }
    if (throwAdd) throw std::runtime_error("fault after native mutation");
}
NativeCalls calls() { return {can_add, add}; }
Evidence evidence() {
    Evidence e;
    e.controller = &controller; e.owner = &owner; e.editObject = &editObject; e.config = &config;
    e.propertyWrapper = &wrapper; e.propertyDescriptor = &descriptor; e.collection = &collection;
    e.transactionToken = &transaction; e.managedTypeName = &typeName;
    e.currentCodeAndThreadVerified = e.transactionSnapshotVerified = true;
    e.verifyContext = verify; e.capture = capture;
    return e;
}
}
int main() {
    try {
        auto n = calls(); auto e = evidence();
        reset(); create_default_into(n, e, &result);
        check(result.code == Code::created_pending_notification && result.structureVerified &&
              result.entry == &fresh && result.index == 7, "actual native parent index, not list offset or guessed zero");
        check(gates == 1 && adds == 1 && captures == 2 && verifications == 2, "one gate and one formal add");
        check(result.after.rows[1].object == &oldA && result.after.rows[2].object == &oldB,
              "native Insert(0) preserves ordered old rows");
        check(result.after.rows[0].selected[0] == 17 && result.after.rows[0].complement[0] == -4 &&
              result.after.rows[0].regions[0].index == 0, "report untouched unknown filters/default region index");
        check(result.outcomeUncertain && result.needsOwnerNotification && result.needsTransactionClose &&
              !result.event92Proven && !result.characterFilterProven, "structure success does not invent notification/event/filter proof");
        create_default_into(n, e, &result);
        check(result.code == Code::duplicate_attempt && adds == 1 && result.structureVerified,
              "same result cannot automatically retry and retains original evidence");

        reset(); e.transactionSnapshotVerified = false; create_default_into(n, e, &result);
        check(result.code == Code::invalid_evidence && !gates && !adds && !captures, "no transaction proof has zero native calls");
        reset(); e = evidence(); e.propertyWrapper = nullptr; create_default_into(n, e, &result);
        check(!gates && !adds && result.code == Code::invalid_evidence, "missing parent wrapper rejected");
        reset(); e = evidence(); n.add = nullptr; create_default_into(n, e, &result);
        check(result.code == Code::missing_calls && !gates && !captures, "missing binding fails before native gate");
        reset(); n = calls(); contextOK = false; create_default_into(n, e, &result);
        check(result.code == Code::invalid_context && !gates && !adds,
              "host rejects unproved controller or alternate class27029 branch");
        reset(); contextDrifts = true; create_default_into(n, e, &result);
        check(result.code == Code::context_changed && gates == 1 && !adds, "fresh context recheck after native gate");
        reset(); live.collection = &config; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !gates && !adds, "wrong collection cannot reach mutation");
        reset(); live.rows[1].index = 2; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !gates && !adds, "ambiguous existing indices rejected");
        reset(); live.rows[0].selectedCount = static_cast<unsigned>(filter_capacity + 1);
        create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !adds, "oversized filter capture is not truncated");
        reset(); limitOK = false; create_default_into(n, e, &result);
        check(result.code == Code::at_native_limit && gates == 1 && !adds && !result.mutationCalled,
              "native limit rejection never allocates");
        reset(); throwGate = true; create_default_into(n, e, &result);
        check(result.code == Code::call_exception && result.stage == Stage::limit && !result.addCalled &&
              !result.mutationCalled, "gate fault does not pretend creation started");
        reset(); throwAdd = true; create_default_into(n, e, &result);
        check(result.code == Code::call_exception && result.stage == Stage::add && result.addCalled &&
              result.outcomeUncertain && adds == 1 && live.count == 3 && captures == 1,
              "post-mutation fault preserves progress and causes no retry/rollback");
        reset(); failAfter = true; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && result.addCalled && !result.structureVerified,
              "unreadable after state remains uncertain");
        reset(); appendInstead = true; create_default_into(n, e, &result);
        check(result.code == Code::unexpected_change && !result.structureVerified, "append is not native insert-at-zero");
        reset(); alterOld = true; create_default_into(n, e, &result);
        check(result.code == Code::unexpected_change && !result.structureVerified, "old target-list change is reported");
        reset(); wrongClass = true; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !result.structureVerified, "other parent class rejected after call");
        reset(); wrongRegion = true; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !result.structureVerified, "unexpected default region class rejected");
        reset(); duplicateIndex = true; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !result.structureVerified, "native duplicate index fails readback");
        reset(); reuseEntry = true; create_default_into(n, e, &result);
        check(result.code == Code::read_failed && !result.structureVerified, "reused old pointer is not a new parent");
        reset(); noInsert = true; create_default_into(n, e, &result);
        check(result.code == Code::unexpected_change && result.addCalled && !result.structureVerified,
              "no collection change is not success");
        std::printf("trigger_parent_calls: %d checks passed (host fakes only)\n", checks);
        return 0;
    } catch (const std::exception& e) { std::fprintf(stderr, "%s\n", e.what()); return 1; }
}
