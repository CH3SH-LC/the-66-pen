#include "template_calls.h"
#include <limits>

namespace ge::templates {
namespace {
bool valid_name(std::string_view text) {
    if (text.empty() || text.size() > 128 || !text.data()) return false;
    for (std::size_t i = 0; i < text.size();) {
        const auto first = static_cast<unsigned char>(text[i++]);
        if (first == 0) return false;
        if (first < 0x80) continue;
        std::uint32_t value = 0, minimum = 0;
        unsigned trailing = 0;
        if (first >= 0xc2 && first <= 0xdf) {
            value = first & 0x1f; minimum = 0x80; trailing = 1;
        } else if (first >= 0xe0 && first <= 0xef) {
            value = first & 0x0f; minimum = 0x800; trailing = 2;
        } else if (first >= 0xf0 && first <= 0xf4) {
            value = first & 0x07; minimum = 0x10000; trailing = 3;
        } else return false;
        if (text.size()-i < trailing) return false;
        for (unsigned n = 0; n < trailing; ++n) {
            const auto next = static_cast<unsigned char>(text[i++]);
            if ((next & 0xc0) != 0x80) return false;
            value = (value << 6) | (next & 0x3f);
        }
        if (value < minimum || value > 0x10ffff ||
            (value >= 0xd800 && value <= 0xdfff)) return false;
    }
    return true;
}
CallCode check_limit(const CountLimitEvidence& evidence) {
    if (!evidence.valid) return CallCode::unknown_limit;
    if (evidence.count < 0 || evidence.limit <= 0 ||
        evidence.count > std::numeric_limits<std::int32_t>::max() ||
        evidence.limit > std::numeric_limits<std::uint32_t>::max())
        return CallCode::invalid_limit;
    if (evidence.count >= evidence.limit) return CallCode::limit_reached;
    return CallCode::returned;
}
CreateResult rejected(CallCode code) {
    return {code, nullptr, false, false, false};
}
}

NameResult make_managed_name(StringNewLen allocate, std::string_view utf8) {
    if (!valid_name(utf8)) return {CallCode::invalid_name, nullptr, false};
    if (!allocate) return {CallCode::missing_binding, nullptr, false};
    void* name = allocate(utf8.data(), static_cast<std::int32_t>(utf8.size()));
    return {name ? CallCode::returned : CallCode::null_managed_name, name, true};
}

CreateResult create_currency(CreateTemplate create, void* manager,
                             void* managed_name, const CountLimitEvidence& evidence) {
    const auto gate = check_limit(evidence);
    if (gate != CallCode::returned) return rejected(gate);
    if (!create || !manager) return rejected(CallCode::missing_binding);
    if (!managed_name) return rejected(CallCode::null_managed_name);
    // Preserve all seven arguments of the observed currency UI service call.
    // Full service owns native ID allocation, properties, names and registration.
    void* resource = create(manager, nullptr, 11, managed_name, nullptr, 0, 0);
    return {resource ? CallCode::returned : CallCode::null_resource,
            resource, false, true, true};
}

CreateResult create_currency_named(CreateTemplate create, StringNewLen allocate,
                                   void* manager, std::string_view utf8,
                                   const CountLimitEvidence& evidence) {
    const auto gate = check_limit(evidence);
    if (gate != CallCode::returned) return rejected(gate);
    if (!valid_name(utf8)) return rejected(CallCode::invalid_name);
    if (!create || !allocate || !manager) return rejected(CallCode::missing_binding);
    const auto name = make_managed_name(allocate, utf8);
    if (name.code != CallCode::returned) {
        auto result = rejected(name.code);
        result.allocationCalled = name.allocationCalled;
        return result;
    }
    auto result = create_currency(create, manager, name.managed_name, evidence);
    result.allocationCalled = name.allocationCalled;
    return result;
}
}
