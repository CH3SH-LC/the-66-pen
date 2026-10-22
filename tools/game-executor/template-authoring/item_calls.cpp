#include "item_calls.h"
#include <limits>

namespace ge::templates {
namespace {
ItemResult rejected(ItemCode code) {
    return {code, ItemStage::none, 0, false, false, false, false};
}
ItemCode gate(const ItemBindings& bindings, const ItemControllerEvidence& controller,
              const CountLimitEvidence& limit) {
    if (!limit.valid) return ItemCode::unknown_limit;
    if (limit.count < 0 || limit.limit <= 0 ||
        limit.count > std::numeric_limits<std::int32_t>::max() ||
        limit.limit > std::numeric_limits<std::uint32_t>::max())
        return ItemCode::invalid_limit;
    if (limit.count >= limit.limit) return ItemCode::limit_reached;
    if (!controller.valid || !controller.controller) return ItemCode::unverified_controller;
    if (controller.source) return ItemCode::source_not_empty;
    if (!bindings.create || !bindings.read_default || !bindings.method_info)
        return ItemCode::missing_binding;
    return ItemCode::call_returned;
}
void invoke(const ItemBindings& bindings, const ItemControllerEvidence& controller,
            void* name, StringNewLen allocate, std::string_view utf8, ItemResult& result) {
    result = rejected(ItemCode::call_returned);
    try {
        result.exceptionStage = ItemStage::default_getter;
        result.defaultGetterCalled = true;
        // Same current native getter used by the real new-item UI. Never cache
        // or substitute an invented template value between seed/crop calls.
        result.defaultValue = bindings.read_default();
        result.exceptionStage = ItemStage::none;
        if (result.defaultValue == 0) {
            result.code = ItemCode::default_unavailable;
            return;
        }
        if (allocate) {
            result.exceptionStage = ItemStage::name_allocation;
            result.allocationCalled = true;
            const auto allocated = make_managed_name(allocate, utf8);
            result.exceptionStage = ItemStage::none;
            name = allocated.managed_name;
            if (!name) {
                result.code = ItemCode::null_managed_name;
                return;
            }
        }
        result.exceptionStage = ItemStage::create_handler;
        result.handlerCalled = true;
        result.outcomeUncertain = true;
        // 0/0 are proved UI defaults; folder=null has an explicit native guard.
        // Keep the native wrapper: its mandatory property initializer callback
        // cannot be replaced with currency's null callback.
        bindings.create(controller.controller, nullptr, name, 0, 0,
                        result.defaultValue, bindings.method_info);
        result.exceptionStage = ItemStage::none;
    } catch (...) {
        result.code = ItemCode::native_exception;
    }
}
}

ItemResult create_normal_item(const ItemBindings& bindings,
                             const ItemControllerEvidence& controller,
                             void* managed_name, const CountLimitEvidence& limit) {
    ItemResult result{};
    create_normal_item_into(bindings, controller, managed_name, limit, &result);
    return result;
}

void create_normal_item_into(const ItemBindings& bindings,
                             const ItemControllerEvidence& controller,
                             void* managed_name, const CountLimitEvidence& limit,
                             ItemResult* progress) {
    if (!progress) return;
    *progress = rejected(gate(bindings, controller, limit));
    if (progress->code != ItemCode::call_returned) return;
    if (!managed_name) { progress->code = ItemCode::null_managed_name; return; }
    invoke(bindings, controller, managed_name, nullptr, {}, *progress);
}

ItemResult create_normal_item_named(const ItemBindings& bindings, StringNewLen allocate,
                                   const ItemControllerEvidence& controller,
                                   std::string_view utf8, const CountLimitEvidence& limit) {
    const auto code = gate(bindings, controller, limit);
    if (code != ItemCode::call_returned) return rejected(code);
    // Reuse the shared UTF8/name validation with allocation disabled.
    if (make_managed_name(nullptr, utf8).code == CallCode::invalid_name)
        return rejected(ItemCode::invalid_name);
    if (!allocate) return rejected(ItemCode::missing_binding);
    ItemResult result{};
    invoke(bindings, controller, nullptr, allocate, utf8, result);
    return result;
}
}
