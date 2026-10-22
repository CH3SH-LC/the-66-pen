#include "skill_calls.h"
#include <limits>

namespace ge::skills {
namespace {
CreateResult rejected(CallCode code) { return {code, nullptr, false, false, false}; }
CallCode preflight(CreateSkill create, const CountLimitEvidence& evidence) {
    if (!evidence.valid) return CallCode::unknown_limit;
    if (evidence.count < 0 || evidence.limit <= 0 ||
        evidence.count > std::numeric_limits<std::int32_t>::max() ||
        evidence.limit > std::numeric_limits<std::uint32_t>::max())
        return CallCode::invalid_limit;
    if (evidence.count >= evidence.limit) return CallCode::limit_reached;
    return create ? CallCode::returned : CallCode::missing_binding;
}
}

CreateResult create_skill(CreateSkill create, void* managed_name,
                          const CountLimitEvidence& evidence) {
    const auto gate = preflight(create, evidence);
    if (gate != CallCode::returned) return rejected(gate);
    if (!managed_name) return rejected(CallCode::null_managed_name);
    auto result = rejected(CallCode::returned);
    result.createCalled = true;
    result.outcomeUncertain = true;
    try {
        result.resource = create(managed_name, nullptr);
        if (!result.resource) result.code = CallCode::null_resource;
    } catch (...) {
        result.code = CallCode::call_exception;
    }
    return result;
}

CreateResult create_skill_named(CreateSkill create, StringNewLen allocate,
                                std::string_view utf8,
                                const CountLimitEvidence& evidence) {
    const auto gate = preflight(create, evidence);
    if (gate != CallCode::returned) return rejected(gate);
    if (!allocate) return rejected(CallCode::missing_binding);
    ge::templates::NameResult name{};
    try {
        name = ge::templates::make_managed_name(allocate, utf8);
    } catch (...) {
        auto result = rejected(CallCode::call_exception);
        result.allocationCalled = true;
        return result;
    }
    if (name.code != ge::templates::CallCode::returned) {
        auto code = CallCode::invalid_name;
        if (name.code == ge::templates::CallCode::null_managed_name)
            code = CallCode::null_managed_name;
        auto result = rejected(code);
        result.allocationCalled = name.allocationCalled;
        return result;
    }
    auto result = create_skill(create, name.managed_name, evidence);
    result.allocationCalled = name.allocationCalled;
    return result;
}
}
