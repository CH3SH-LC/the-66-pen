#include "../component_binding_calls.h"
#include <array>
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <string>

using namespace ge::component_binding;
namespace {
std::array<unsigned char, 128> owner{}, config{}, reference{}, entry{};
int context = 0, checks = 0;
std::uint32_t requested = 1136656385;
std::int32_t actual_index = 7;
Kind active = Kind::shop;
std::string events;
bool null_ref = false, bad_ref = false, no_ref_read = false, null_entry = false;
bool no_index_read = false, no_bound_read = false, bad_bound = false;
bool throw_add = false, throw_set = false, throw_refresh = false;
bool typed_mode = false, throw_id = false;
std::uint32_t reference_id = 0;
char16_t type_name[] = u"ClientBeyondConfigReferenceEditData";
void check(bool good, const char* reason) {
    if (!good) throw std::runtime_error(reason);
    ++checks;
}
void reset(Kind kind) {
    active = kind; events.clear(); actual_index = 7;
    requested = kind == Kind::shop ? 1136656385 : 1119879169;
    null_ref = bad_ref = no_ref_read = null_entry = no_index_read = false;
    no_bound_read = bad_bound = throw_add = throw_set = throw_refresh = false;
    typed_mode = throw_id = false; reference_id = 0;
}
void* __cdecl make_ref(std::uint32_t id) {
    events += 'F'; check(id == requested, "factory gets exact uint32 template ID");
    return null_ref ? nullptr : reference.data();
}
void* __cdecl pool_ref(void* name) {
    events += 'P'; check(name == type_name, "pool receives exact managed type-name pointer, not numeric template ID");
    return null_ref ? nullptr : reference.data();
}
void __cdecl set_reference_id(void* ref, std::uint32_t id) {
    events += 'T'; check(ref == reference.data() && id == requested && events == "PRT", "ID initializer receives pool object and requested ID after class/default readback");
    if (throw_id) throw std::runtime_error("id exception");
    reference_id = bad_ref ? id - 1 : id;
}
bool read_ref(void* ctx, void* value, std::uint32_t* id) {
    events += 'R';
    check(ctx == &context && value == reference.data(), "factory reference readback uses actual pointer/context");
    if (no_ref_read) return false;
    *id = typed_mode ? reference_id : bad_ref ? requested-1 : requested;
    return true;
}
void* __cdecl add(void* value) {
    events += 'A'; check(value == config.data() && active == Kind::shop, "shop add gets config, never owner or bag");
    if (throw_add) throw std::runtime_error("add exception");
    return null_entry ? nullptr : entry.data();
}
bool read_index(void* ctx, void* value, std::int32_t* index) {
    events += 'I'; check(ctx == &context && value == entry.data(), "read the returned entry index");
    if (no_index_read) return false;
    *index = actual_index; return true;
}
void set(void* target, std::uint32_t hash, void* ref, Kind expected) {
    events += 'S';
    check(active == expected && ref == reference.data(), "select the correct formal setter and factory reference");
    check(target == (expected == Kind::shop ? entry.data() : config.data()) &&
          hash == (expected == Kind::shop ? 0xf6589f9cu : 0x14ae9e6cu),
          "setter target, field hash and reference have exact ABI argument order");
    if (throw_set) throw std::runtime_error("setter exception");
}
void __cdecl shop_set(void* t, std::uint32_t h, void* r) { set(t,h,r,Kind::shop); }
void __cdecl bag_set(void* t, std::uint32_t h, void* r) { set(t,h,r,Kind::bag); }
bool read_bound(void* ctx, void* target, std::uint32_t hash, std::uint32_t* id) {
    events += 'B';
    check(ctx == &context && target == (active == Kind::shop ? entry.data() : config.data()) &&
          hash == (active == Kind::shop ? shop_reference_hash : bag_reference_hash),
          "installed reference readback uses actual target and field");
    if (no_bound_read) return false;
    *id = bad_bound ? requested-1 : requested; return true;
}
void refresh(void* target, std::int32_t flag, void* zero, Kind expected) {
    events += 'D';
    check(active == expected && target == config.data() && flag == 0 && zero == nullptr,
          "kind-specific +378 gets config, flag0 and zero context in ABI order");
    if (throw_refresh) throw std::runtime_error("refresh exception");
}
void __cdecl shop_refresh(void* t, std::int32_t f, void* z) { refresh(t,f,z,Kind::shop); }
void __cdecl bag_refresh(void* t, std::int32_t f, void* z) { refresh(t,f,z,Kind::bag); }
NativeCalls calls() { return {make_ref,add,shop_set,bag_set,shop_refresh,bag_refresh}; }
NativeCalls typed_calls() {
    typed_mode = true; auto c = calls(); c.createReference = nullptr;
    c.createTypedReference = pool_ref; c.initializeReferenceId = set_reference_id; c.referenceTypeName = type_name; return c;
}
Readbacks reads() { return {&context,read_ref,read_index,read_bound}; }
Evidence evidence() { return {owner.data(),config.data(),requested,active,true,true}; }
BindResult invoke(const NativeCalls& c, const Readbacks& r, const Evidence& e) {
    return active == Kind::shop ? bind_shop(c,r,e) : bind_bag(c,r,e);
}
void uncertain(const BindResult& r) {
    check(r.mutationCalled && r.outcomeUncertain && r.needsOwnerNotification,
          "mutation remains uncertain and needs owner notification regardless of returned pointers/readback");
}
}
int main() {
    static_assert(sizeof(void*) == 8, "Windows x64 contract test required");
    try {
        owner.fill(0x81); config.fill(0x92); reference.fill(0xa3); entry.fill(0xb4);
        const auto owner_before=owner, config_before=config, ref_before=reference, entry_before=entry;
        for (Kind kind : {Kind::shop,Kind::bag}) {
            reset(kind); auto c = typed_calls();
            auto r = invoke(c, reads(), evidence());
            check(r.code == BindCode::returned && r.referenceReadbackVerified &&
                  events == (kind == Kind::shop ? "PRTRAISBD" : "PRTRSBD"), "typed pool/default read/ID setter/readback precede component mutation");
            reset(kind); c = typed_calls(); null_ref = true;
            r = invoke(c, reads(), evidence());
            check(r.code == BindCode::null_reference && events == "P" && !r.mutationCalled, "null pool result is not retried or initialized");
            reset(kind); c = typed_calls(); no_ref_read = true;
            r = invoke(c, reads(), evidence());
            check(r.code == BindCode::reference_readback_failed && events == "PR" && !r.mutationCalled, "unverified pool object never reaches native ID setter");
            reset(kind); c = typed_calls(); reference_id = requested;
            r = invoke(c, reads(), evidence());
            check(r.code == BindCode::reference_id_mismatch && events == "PR" && !r.mutationCalled, "stale pool object must have been natively reset");
            reset(kind); c = typed_calls(); bad_ref = true;
            r = invoke(c, reads(), evidence());
            check(r.code == BindCode::reference_id_mismatch && events == "PRTR" && !r.mutationCalled, "failed ID initializer readback blocks component add/set");
            reset(kind); c = typed_calls(); throw_id = true;
            r = invoke(c, reads(), evidence());
            check(r.code == BindCode::call_exception && r.exceptionStage == BindStage::reference_initialize &&
                  r.referenceFactoryCalled && events == "PRT" && !r.mutationCalled, "ID initializer exception retains caller-owned phase without retry");
            for (int missing = 0; missing < 3; ++missing) {
                reset(kind); c = typed_calls(); c.createReference = make_ref;
                if (missing == 0) c.createTypedReference = nullptr;
                if (missing == 1) c.initializeReferenceId = nullptr;
                if (missing == 2) c.referenceTypeName = nullptr;
                r = invoke(c, reads(), evidence());
                check(r.code == BindCode::missing_binding && events.empty(), "incomplete typed route never falls back to legacy resource lookup");
            }
        }
        for (Kind kind : {Kind::shop,Kind::bag}) {
            reset(kind);
            auto c=calls(); auto rd=reads();
            if (kind == Kind::bag) { c.addShopEntry=nullptr; rd.entryIndex=nullptr; }
            const auto result=invoke(c,rd,evidence());
            check(result.code == BindCode::returned && result.fieldReadbackVerified &&
                  result.referenceReadbackVerified && result.setterCalled && result.dependencyRefreshCalled &&
                  !result.needsDependencyRefresh,"formal bind and field readback complete without claiming owner acceptance");
            check(events == (kind == Kind::shop ? "FRAISBD" : "FRSBD"), "strict order and no bag add/index callback");
            check(kind == Kind::shop ? result.shopIndex == 7 && result.entryIndexReadbackVerified :
                  !result.entry && !result.addCalled && !result.entryIndexReadbackVerified,
                  "native shop ID returned, bag has no invented index");
            uncertain(result);

            reset(kind); null_ref=true;
            const auto missing=invoke(calls(),reads(),evidence());
            check(missing.code == BindCode::null_reference && events == "F" &&
                  !missing.mutationCalled && !missing.outcomeUncertain && !missing.needsOwnerNotification,
                  "null reference does not mutate components or call setters");
        }
        reset(Kind::shop);
        auto zero_id=evidence(); zero_id.templateId=0;
        const auto zero_result=bind_shop(calls(),reads(),zero_id);
        check(zero_result.code == BindCode::invalid_evidence && events.empty() &&
              !zero_result.referenceFactoryCalled && !zero_result.addCalled && !zero_result.setterCalled &&
              !zero_result.mutationCalled,"zero template ID is rejected before factory/add/set");
        for (int failure=0; failure<5; ++failure) {
            events.clear(); auto e=evidence(); auto rd=reads(); auto c=calls();
            if (failure==0) e.ownerAndConfigVerified=false;
            if (failure==1) e.templateExistsAndKindVerified=false;
            if (failure==2) e.kind=Kind::bag;
            if (failure==3) rd.entryIndex=nullptr;
            if (failure==4) c.setShopReference=nullptr;
            const auto r=bind_shop(c,rd,e);
            check(events.empty() && !r.referenceFactoryCalled && !r.mutationCalled,
                  "all host evidence and required calls/readbacks gate before factory");
        }
        for (bool unreadable : {false,true}) {
            reset(Kind::shop); no_ref_read=unreadable; bad_ref=!unreadable;
            const auto r=bind_shop(calls(),reads(),evidence());
            check(r.code == (unreadable ? BindCode::reference_readback_failed : BindCode::reference_id_mismatch) &&
                  events == "FR" && !r.mutationCalled,"unknown/wrong reference never reaches add");
        }
        reset(Kind::shop); null_entry=true;
        auto r=bind_shop(calls(),reads(),evidence());
        check(r.code == BindCode::null_entry && events == "FRA" && !r.setterCalled,
              "null add result stops; no retry/rollback"); uncertain(r);
        for (auto index : {std::int32_t{0},std::int32_t{-1},std::numeric_limits<std::int32_t>::min()}) {
            reset(Kind::shop); actual_index=index;
            r=bind_shop(calls(),reads(),evidence());
            check(r.code == BindCode::invalid_entry_index && events == "FRAI" &&
                  !r.setterCalled && !r.entryIndexReadbackVerified,"invalid native index never reaches setter");
            uncertain(r);
        }
        reset(Kind::shop); actual_index=std::numeric_limits<std::int32_t>::max();
        r=bind_shop(calls(),reads(),evidence());
        check(r.code == BindCode::returned && r.shopIndex == actual_index,
              "no guessed maximum replaces positive native int32 index");
        reset(Kind::shop); no_index_read=true;
        r=bind_shop(calls(),reads(),evidence());
        check(r.code == BindCode::entry_index_readback_failed && events == "FRAI" && !r.setterCalled,
              "unreadable native index never replaced with zero"); uncertain(r);
        for (bool unreadable : {false,true}) {
            reset(Kind::bag); no_bound_read=unreadable; bad_bound=!unreadable;
            r=bind_bag(calls(),reads(),evidence());
            check(r.code == (unreadable ? BindCode::binding_readback_failed : BindCode::binding_id_mismatch) &&
                  events == "FRSB" && !r.fieldReadbackVerified && !r.dependencyRefreshCalled,
                  "failed installed-field readback never claims binding or refresh"); uncertain(r);
        }
        reset(Kind::bag); auto c=calls(); c.refreshBagDependencies=nullptr;
        r=bind_bag(c,reads(),evidence());
        check(r.code == BindCode::returned && events == "FRSB" && r.needsDependencyRefresh &&
              !r.dependencyRefreshCalled,"missing explicitly-bound refresh remains pending"); uncertain(r);
        for (int stage=0; stage<3; ++stage) {
            reset(Kind::shop); throw_add=stage==0; throw_set=stage==1; throw_refresh=stage==2;
            r=bind_shop(calls(),reads(),evidence());
            check(r.code == BindCode::call_exception && events == (stage==0 ? "FRA" : stage==1 ? "FRAIS" : "FRAISBD") &&
                  r.needsDependencyRefresh,"exception preserves call state and never retries"); uncertain(r);
        }
        check(owner==owner_before && config==config_before && reference==ref_before && entry==entry_before,
              "call layer never reads guessed fields or performs raw object writes");
        std::printf("{\"scope\":\"component_binding_host_contract\",\"checks_passed\":%d,"
                    "\"game_runtime_verified\":false,\"owner_notification_verified\":false,\"save_verified\":false}\n",checks);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr,"component binding test failed: %s\n",error.what()); return 1;
    }
}
