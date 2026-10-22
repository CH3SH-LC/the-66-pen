#pragma once
#include "template_calls.h"

namespace ge::skills {
// Current 7.1 d1f8af0; d1f9030 passes name in RCX and source=null in RDX.
// The helper owns the mandatory initializer callback and companion creation.
// Its inspected body does not consume an additional incoming MethodInfo.
using CreateSkill = void* (__cdecl *)(void* managed_name, void* source);
using ge::templates::CountLimitEvidence;
using ge::templates::StringNewLen;

enum class CallCode : std::uint32_t {
    returned, invalid_name, missing_binding, null_managed_name,
    unknown_limit, invalid_limit, limit_reached, null_resource, call_exception
};
struct CreateResult {
    CallCode code;
    void* resource;
    bool allocationCalled;
    bool createCalled;
    // A successful helper return is not registration proof. The host must check
    // BOTH the kind-6 template and its same-ID CPPMHBGMMAN companion.
    bool outcomeUncertain;
};

// Host supplies fresh, proven custom-skill count/limit evidence. This module
// cannot establish the UI limit's source and rejects unknown evidence. Bindings,
// loaded default tables, game-thread execution and native SEH remain host-owned.
// No source cloning, UI invocation, registration readback, retry or rollback.
CreateResult create_skill(CreateSkill create, void* managed_name,
                          const CountLimitEvidence& evidence);
CreateResult create_skill_named(CreateSkill create, StringNewLen allocate,
                                std::string_view utf8,
                                const CountLimitEvidence& evidence);
}
