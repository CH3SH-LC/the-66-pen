#pragma once
#include "template_calls.h"

namespace ge::templates {
// Current NormalStuff UI callback 0x9b0e0d0. The native function constructs
// its required initializer delegate before invoking the full creation service.
// The seventh argument is the MethodInfo carried by 0x81ab390's delegate call.
// RAX is not a resource-return contract; the adapter must read catalogue delta.
using CreateNormalItem = void (__cdecl *)(
    void* controller, void* folder, void* managed_name,
    std::int32_t type_choice, std::int32_t option_index,
    std::uint32_t default_value, void* method_info);
using ReadDefaultItemValue = std::uint32_t (__cdecl *)();

struct ItemBindings {
    CreateNormalItem create;
    ReadDefaultItemValue read_default;
    void* method_info;
};
// Only the reviewed adapter can establish current native type, active scene,
// game thread and freshness. valid attests definition 78618 and this exact
// controller's +0x10 source read. Never clear or replace a non-null source.
struct ItemControllerEvidence {
    bool valid;
    void* controller;
    void* source;
};
enum class ItemCode : std::uint32_t {
    call_returned = 0, invalid_name, missing_binding, null_managed_name,
    unknown_limit, invalid_limit, limit_reached, unverified_controller,
    source_not_empty, default_unavailable, native_exception
};
enum class ItemStage : std::uint32_t {
    none = 0, default_getter, name_allocation, create_handler
};
struct ItemResult {
    ItemCode code;
    ItemStage exceptionStage;
    std::uint32_t defaultValue;
    bool defaultGetterCalled;
    bool allocationCalled;
    bool handlerCalled;
    // Every attempted handler call needs native catalogue delta verification,
    // including an exception or a normal return. No resource pointer is exposed.
    bool outcomeUncertain;
};

ItemResult create_normal_item(const ItemBindings& bindings,
                             const ItemControllerEvidence& controller,
                             void* managed_name, const CountLimitEvidence& limit);
// Caller-owned progress survives the adapter's SEH boundary. During a native
// call exceptionStage identifies the active phase; flags are written BEFORE
// entry. On a normal return exceptionStage becomes none. No retry is performed.
void create_normal_item_into(const ItemBindings& bindings,
                             const ItemControllerEvidence& controller,
                             void* managed_name, const CountLimitEvidence& limit,
                             ItemResult* progress);
ItemResult create_normal_item_named(const ItemBindings& bindings, StringNewLen allocate,
                                   const ItemControllerEvidence& controller,
                                   std::string_view utf8, const CountLimitEvidence& limit);
// Calls each native entry at most once. C++ exceptions become phase-specific
// uncertain receipts; hardware/SEH faults remain the adapter's responsibility.
// This module performs no address resolution, process access, catalogue writes,
// delegate construction, persistence, retries or registration verification.
}
