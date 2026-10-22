#include "../item_calls.h"
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ge::templates;
namespace {
int checks=0, gets=0, allocations=0, calls=0;
int controller_token=1, name_token=2, method_token=3, source_token=4;
std::uint32_t configured_default=70001, observed_default=0;
ItemStage throw_at=ItemStage::none;
bool null_name=false;
std::string expected_name, phases;
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
    ++checks;
}
__declspec(noinline) std::uint32_t __cdecl get_default() {
    ++gets; phases+='D';
    if (throw_at==ItemStage::default_getter) throw std::runtime_error("getter");
    return configured_default;
}
__declspec(noinline) void* __cdecl make_name(const char* bytes, std::int32_t length) {
    ++allocations; phases+='N';
    check(std::string(bytes,static_cast<std::size_t>(length))==expected_name,"UTF8 and length preserved");
    if (throw_at==ItemStage::name_allocation) throw std::runtime_error("name");
    return null_name ? nullptr : &name_token;
}
__declspec(noinline) void __cdecl create(void* controller, void* folder, void* name,
    std::int32_t type, std::int32_t option, std::uint32_t default_value, void* method) {
    ++calls; phases+='C'; observed_default=default_value;
    check(controller==&controller_token && folder==nullptr && name==&name_token,
          "native controller, optional folder and name ABI");
    check(type==0 && option==0 && default_value==configured_default && method==&method_token,
          "normal-item UI defaults, fresh native value and hidden MethodInfo ABI");
    if (throw_at==ItemStage::create_handler) throw std::runtime_error("handler");
}
ItemBindings bindings{create,get_default,&method_token};
ItemControllerEvidence controller{true,&controller_token,nullptr};
CountLimitEvidence room{true,0,100};
void no_effects(ItemResult result, ItemCode code, int g, int a, int c) {
    check(result.code==code && !result.defaultGetterCalled && !result.allocationCalled &&
          !result.handlerCalled && !result.outcomeUncertain && gets==g && allocations==a && calls==c,
          "rejection performs no native call");
}
}
int main() {
    static_assert(sizeof(void*)==8,"Windows x64 ABI test required");
    try {
        expected_name=u8"种子";
        auto result=create_normal_item_named(bindings,make_name,controller,expected_name,room);
        check(result.code==ItemCode::call_returned && result.defaultGetterCalled &&
              result.allocationCalled && result.handlerCalled && result.outcomeUncertain &&
              result.defaultValue==70001 && phases=="DNC","one native handler; outcome still requires catalogue readback");
        configured_default=70002; phases.clear(); expected_name=u8"作物";
        result=create_normal_item_named(bindings,make_name,controller,expected_name,room);
        check(result.defaultValue==70002 && observed_default==70002 && phases=="DNC",
              "seed/crop share implementation but each reads a fresh native default");

        const int g=gets,a=allocations,c=calls;
        for (auto entry : std::vector<std::pair<CountLimitEvidence,ItemCode>>{
            {{false,0,100},ItemCode::unknown_limit},{{true,-1,100},ItemCode::invalid_limit},
            {{true,0,0},ItemCode::invalid_limit},{{true,0,-1},ItemCode::invalid_limit},
            {{true,100,100},ItemCode::limit_reached},{{true,101,100},ItemCode::limit_reached},
            {{true,0,std::int64_t{1}<<32},ItemCode::invalid_limit},
            {{true,std::int64_t{1}<<31,100},ItemCode::invalid_limit}})
            no_effects(create_normal_item_named(bindings,make_name,controller,expected_name,entry.first),entry.second,g,a,c);
        for (const auto evidence : std::vector<ItemControllerEvidence>{
            {false,&controller_token,nullptr},{true,nullptr,nullptr}})
            no_effects(create_normal_item(bindings,evidence,&name_token,room),ItemCode::unverified_controller,g,a,c);
        no_effects(create_normal_item(bindings,{true,&controller_token,&source_token},&name_token,room),
                   ItemCode::source_not_empty,g,a,c);
        for (const auto binding : std::vector<ItemBindings>{
            {nullptr,get_default,&method_token},{create,nullptr,&method_token},{create,get_default,nullptr}})
            no_effects(create_normal_item(binding,controller,&name_token,room),ItemCode::missing_binding,g,a,c);
        no_effects(create_normal_item(bindings,controller,nullptr,room),ItemCode::null_managed_name,g,a,c);
        no_effects(create_normal_item_named(bindings,nullptr,controller,expected_name,room),ItemCode::missing_binding,g,a,c);
        for (const auto& invalid : std::vector<std::string>{"",std::string(129,'a'),std::string("a\0b",3),"\xed\xa0\x80"})
            no_effects(create_normal_item_named(bindings,make_name,controller,invalid,room),ItemCode::invalid_name,g,a,c);

        configured_default=0; phases.clear();
        result=create_normal_item_named(bindings,make_name,controller,expected_name,room);
        check(result.code==ItemCode::default_unavailable && result.defaultGetterCalled &&
              !result.handlerCalled && !result.allocationCalled && !result.outcomeUncertain && phases=="D",
              "unavailable native default is not substituted or created");
        configured_default=70003; null_name=true; phases.clear();
        result=create_normal_item_named(bindings,make_name,controller,expected_name,room);
        check(result.code==ItemCode::null_managed_name && result.allocationCalled &&
              !result.handlerCalled && !result.outcomeUncertain && phases=="DN","null string stops before handler");
        null_name=false;
        for (const auto phase : {ItemStage::default_getter,ItemStage::name_allocation,ItemStage::create_handler}) {
            throw_at=phase; phases.clear(); const int prior_calls=calls;
            result=create_normal_item_named(bindings,make_name,controller,expected_name,room);
            check(result.code==ItemCode::native_exception && result.exceptionStage==phase,
                  "exception identifies exact native phase");
            const bool attempted=phase==ItemStage::create_handler;
            check(result.handlerCalled==attempted && result.outcomeUncertain==attempted &&
                  calls-prior_calls==(attempted?1:0) &&
                  phases==(phase==ItemStage::default_getter?"D":phase==ItemStage::name_allocation?"DN":"DNC"),
                  "exceptions never retry; attempted handler remains uncertain");
        }
        throw_at=ItemStage::none; phases.clear();
        result=create_normal_item(bindings,controller,&name_token,room);
        check(result.code==ItemCode::call_returned && !result.allocationCalled &&
              result.handlerCalled && result.outcomeUncertain && phases=="DC","preallocated-name path preserves same native wrapper");
        std::printf("{\"scope\":\"win64_normal_item_calls_host_contract\",\"checks_passed\":%d,"
                    "\"getter_calls\":%d,\"handler_calls\":%d,\"game_runtime_verified\":false,"
                    "\"registered_verified\":false,\"save_verified\":false}\n",checks,gets,calls);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr,"normal item call test failed: %s\n",error.what()); return 1;
    }
}
