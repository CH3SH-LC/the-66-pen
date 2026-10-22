#include "../skill_calls.h"
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
int checks = 0;
void require(bool ok) { ++checks; if (!ok) throw std::runtime_error("check failed"); }
int nameToken = 0, resourceToken = 0;
std::vector<std::string> calls;
bool nullName = false, nullResource = false, throwAllocate = false, throwCreate = false;
void reset() { calls.clear(); nullName = nullResource = throwAllocate = throwCreate = false; }
void* __cdecl allocate(const char* text, std::int32_t length) {
    calls.emplace_back("name:" + std::string(text, static_cast<std::size_t>(length)));
    if (throwAllocate) throw std::runtime_error("allocation");
    return nullName ? nullptr : &nameToken;
}
void* __cdecl create(void* name, void* source) {
    calls.emplace_back("create");
    require(name == &nameToken);
    require(source == nullptr);
    if (throwCreate) throw std::runtime_error("create");
    return nullResource ? nullptr : &resourceToken;
}
void no_calls(ge::skills::CreateResult result, ge::skills::CallCode code) {
    require(result.code == code);
    require(!result.resource && !result.allocationCalled && !result.createCalled && !result.outcomeUncertain);
    require(calls.empty());
}
}
int main() {
    using namespace ge::skills;
    const CountLimitEvidence valid{true, 2, 3};
    reset();
    auto r = create_skill_named(create, allocate, "MW_Farm", valid);
    require(r.code == CallCode::returned && r.resource == &resourceToken);
    require(r.allocationCalled && r.createCalled && r.outcomeUncertain);
    require(calls == std::vector<std::string>({"name:MW_Farm", "create"}));
    reset();
    r = create_skill(create, &nameToken, valid);
    require(r.code == CallCode::returned && !r.allocationCalled && r.createCalled && r.outcomeUncertain);
    require(calls == std::vector<std::string>({"create"}));
    reset();
    no_calls(create_skill_named(create, allocate, "MW_Farm", {false, 0, 100}), CallCode::unknown_limit);
    no_calls(create_skill_named(create, allocate, "MW_Farm", {true, 3, 3}), CallCode::limit_reached);
    no_calls(create_skill_named(create, allocate, "MW_Farm", {true, 4, 3}), CallCode::limit_reached);
    for (const CountLimitEvidence e : {CountLimitEvidence{true, -1, 3}, {true, 0, 0},
            {true, 0, -1}, {true, static_cast<std::int64_t>(INT32_MAX) + 1, 4294967295LL},
            {true, 0, 4294967296LL}})
        no_calls(create_skill_named(create, allocate, "MW_Farm", e), CallCode::invalid_limit);
    no_calls(create_skill_named(nullptr, allocate, "MW_Farm", valid), CallCode::missing_binding);
    no_calls(create_skill_named(create, nullptr, "MW_Farm", valid), CallCode::missing_binding);
    no_calls(create_skill(create, nullptr, valid), CallCode::null_managed_name);
    for (const auto& text : {std::string(), std::string(129, 'x'), std::string("a\0b", 3), std::string("\xc0\xaf", 2)})
        no_calls(create_skill_named(create, allocate, text, valid), CallCode::invalid_name);
    nullName = true;
    r = create_skill_named(create, allocate, "MW_Farm", valid);
    require(r.code == CallCode::null_managed_name && r.allocationCalled && !r.createCalled && !r.outcomeUncertain);
    require(calls.size() == 1);
    reset(); nullResource = true;
    r = create_skill_named(create, allocate, "MW_Farm", valid);
    require(r.code == CallCode::null_resource && r.allocationCalled && r.createCalled && r.outcomeUncertain);
    require(calls.size() == 2);
    reset(); throwCreate = true;
    r = create_skill_named(create, allocate, "MW_Farm", valid);
    require(r.code == CallCode::call_exception && r.allocationCalled && r.createCalled && r.outcomeUncertain);
    require(calls.size() == 2);
    reset(); throwAllocate = true;
    r = create_skill_named(create, allocate, "MW_Farm", valid);
    require(r.code == CallCode::call_exception && r.allocationCalled && !r.createCalled && !r.outcomeUncertain);
    require(calls.size() == 1);
    std::cout << "skill_calls: " << checks << " checks passed\n";
}
