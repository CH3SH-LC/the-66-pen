#pragma once
#include <cstdint>
#include <string_view>

// Internal call contracts for a future reviewed adapter on the game thread.
// No process discovery, address resolver, injection, IPC, persistence or retry.
namespace ge::templates {
// Current 7.1 currency UI b4fa4e1 -> b0a90c0, Windows x64.
using CreateTemplate = void* (__cdecl *)(
    void* manager, void* source, std::int32_t subtype, void* managed_name,
    void* callback, std::uint32_t requested_id, std::uint8_t name_flag);
// Current 7.1 metadata literal call 526dad -> 526de0: UTF8 bytes + byte length.
using StringNewLen = void* (__cdecl *)(const char* utf8, std::int32_t byte_length);

enum class CallCode : std::uint32_t {
    returned = 0, invalid_name = 1, missing_binding = 2,
    null_managed_name = 3, unknown_limit = 4, invalid_limit = 5,
    limit_reached = 6, null_resource = 7
};
// The adapter supplies fresh native UI count/limit evidence. This module checks
// its values, but cannot establish their provenance or current scene identity.
struct CountLimitEvidence {
    bool valid;
    std::int64_t count;
    std::int64_t limit;
};
struct NameResult {
    CallCode code;
    void* managed_name;
    bool allocationCalled;
};
struct CreateResult {
    CallCode code;
    void* resource;
    bool allocationCalled;
    bool createCalled;
    // Once create is called this remains true until the adapter verifies native
    // registration. A returned pointer alone does not clear it. Name allocation
    // alone never makes resource registration uncertain.
    bool outcomeUncertain;
};

// Reject empty, >128-byte, embedded-NUL or malformed UTF8 before allocation.
NameResult make_managed_name(StringNewLen allocate, std::string_view utf8);
CreateResult create_currency(CreateTemplate create, void* manager,
                             void* managed_name, const CountLimitEvidence& evidence);
// Thin sequential convenience: check every precondition before name allocation.
// Both functions are called at most once; exceptions propagate without retry.
CreateResult create_currency_named(CreateTemplate create, StringNewLen allocate,
                                   void* manager, std::string_view utf8,
                                   const CountLimitEvidence& evidence);
}
