#include "../template_calls.h"
#include <cstdio>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ge::templates;
namespace {
int checks = 0, allocations = 0, creations = 0;
int manager_token = 1, name_token = 2, resource_token = 3;
bool null_name = false, null_resource = false, throw_create = false;
std::string expected_name, observed_name;
void check(bool ok, const char* message) {
    if (!ok) throw std::runtime_error(message);
    ++checks;
}
__declspec(noinline) void* __cdecl capture_name(const char* bytes, std::int32_t length) {
    ++allocations;
    observed_name.assign(bytes, static_cast<std::size_t>(length));
    check(observed_name == expected_name, "native constructor gets exact UTF8 bytes and byte length");
    return null_name ? nullptr : &name_token;
}
__declspec(noinline) void* __cdecl capture_create(
    void* manager, void* source, std::int32_t subtype, void* name,
    void* callback, std::uint32_t requested_id, std::uint8_t name_flag) {
    ++creations;
    check(manager == &manager_token && source == nullptr && subtype == 11 && name == &name_token,
          "currency service register arguments and pointer identities");
    check(callback == nullptr && requested_id == 0 && name_flag == 0,
          "currency service three stack arguments preserve automatic ID and UI flags");
    if (throw_create) throw std::runtime_error("native-call stub exception");
    return null_resource ? nullptr : &resource_token;
}
void no_effects(const CreateResult& result, CallCode expected, int old_alloc, int old_create) {
    check(result.code == expected && !result.resource && !result.allocationCalled &&
          !result.createCalled && !result.outcomeUncertain &&
          allocations == old_alloc && creations == old_create,
          "rejected input must allocate nothing and create nothing");
}
}
int main() {
    static_assert(sizeof(void*) == 8, "Windows x64 ABI test required.");
    try {
        const CountLimitEvidence room{true, 0, 10};
        expected_name = u8"农场金币";
        const auto result = create_currency_named(capture_create, capture_name,
                                                  &manager_token, expected_name, room);
        check(result.code == CallCode::returned && result.resource == &resource_token &&
              result.allocationCalled && result.createCalled && result.outcomeUncertain &&
              allocations == 1 && creations == 1 && observed_name == u8"农场金币",
              "Chinese name allocation then one full service call; registration not asserted");

        const int old_alloc = allocations, old_create = creations;
        struct GateCase { CountLimitEvidence evidence; CallCode expected; };
        for (const auto& scenario : std::vector<GateCase>{
                 {{false,0,10},CallCode::unknown_limit},
                 {{true,-1,10},CallCode::invalid_limit},
                 {{true,0,-1},CallCode::invalid_limit},
                 {{true,0,0},CallCode::invalid_limit},
                 {{true,10,10},CallCode::limit_reached},
                 {{true,11,10},CallCode::limit_reached},
                 {{true,0,std::int64_t{1}<<32},CallCode::invalid_limit},
                 {{true,std::int64_t{1}<<31,std::int64_t{1}<<32},CallCode::invalid_limit}}) {
            no_effects(create_currency_named(capture_create,capture_name,&manager_token,
                       expected_name,scenario.evidence),scenario.expected,old_alloc,old_create);
        }
        no_effects(create_currency_named(nullptr,capture_name,&manager_token,expected_name,room),
                   CallCode::missing_binding,old_alloc,old_create);
        no_effects(create_currency_named(capture_create,nullptr,&manager_token,expected_name,room),
                   CallCode::missing_binding,old_alloc,old_create);
        no_effects(create_currency_named(capture_create,capture_name,nullptr,expected_name,room),
                   CallCode::missing_binding,old_alloc,old_create);
        no_effects(create_currency(capture_create,&manager_token,nullptr,room),
                   CallCode::null_managed_name,old_alloc,old_create);

        // External boundary cases, not a second UTF8 decoder in the test.
        for (const auto& text : std::vector<std::string>{"",std::string(129,'a'),
                 std::string("a\0b",3),"\x80","\xc0\xaf","\xc1\xbf",
                 "\xe0\x80\xaf","\xed\xa0\x80","\xf0\x80\x80\xaf",
                 "\xf4\x90\x80\x80","\xf5\x80\x80\x80","\xff",
                 "\xe4\xb8","\xe4\x41\xad"}) {
            no_effects(create_currency_named(capture_create,capture_name,&manager_token,text,room),
                       CallCode::invalid_name,old_alloc,old_create);
            const auto invalid = make_managed_name(capture_name,text);
            check(invalid.code == CallCode::invalid_name && !invalid.allocationCalled &&
                  allocations == old_alloc,"name-only path rejects invalid UTF8 without allocation");
        }
        for (const auto& text : std::vector<std::string>{std::string(128,'a'),u8"金币🌾",
                 "\xc2\x80","\xed\x9f\xbf","\xee\x80\x80","\xf4\x8f\xbf\xbf"}) {
            expected_name = text;
            const auto named = make_managed_name(capture_name,text);
            check(named.code == CallCode::returned && named.managed_name == &name_token &&
                  named.allocationCalled,"accepted UTF8 and 128-byte boundary preserved");
        }
        const auto missing = make_managed_name(nullptr,"Coin");
        check(missing.code == CallCode::missing_binding && !missing.allocationCalled,
              "missing string constructor distinct from native null result");

        expected_name = "Coin";
        null_name = true;
        int before_alloc = allocations, before_create = creations;
        const auto failed_name = create_currency_named(capture_create,capture_name,&manager_token,
                                                        expected_name,room);
        check(failed_name.code == CallCode::null_managed_name && failed_name.allocationCalled &&
              !failed_name.createCalled && !failed_name.outcomeUncertain &&
              allocations == before_alloc+1 && creations == before_create,
              "null string allocation stops before resource call; no retry or registration uncertainty");
        null_name = false; null_resource = true;
        before_alloc = allocations; before_create = creations;
        const auto failed_create = create_currency_named(capture_create,capture_name,&manager_token,
                                                          expected_name,room);
        check(failed_create.code == CallCode::null_resource && !failed_create.resource &&
              failed_create.allocationCalled && failed_create.createCalled &&
              failed_create.outcomeUncertain && allocations == before_alloc+1 &&
              creations == before_create+1,"native null is uncertain and never retried");

        null_resource = false; throw_create = true;
        before_create = creations;
        bool propagated = false;
        try { (void)create_currency(capture_create,&manager_token,&name_token,room); }
        catch (const std::runtime_error&) { propagated = true; }
        check(propagated && creations == before_create+1,"call exception propagates without retry");
        std::printf("{\"scope\":\"win64_template_calls_host_contract\",\"checks_passed\":%d,"
                    "\"allocation_calls\":%d,\"create_calls\":%d,\"game_runtime_verified\":false,"
                    "\"registered_verified\":false,\"save_verified\":false}\n",checks,allocations,creations);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr,"template call test failed: %s\n",error.what());
        return 1;
    }
}
