#include "scene_calls.h"
#include <cmath>
#include <limits>

namespace ge::scene {
namespace {
bool finite(const Vec3& v) {
    return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z);
}
}
PlacementResult place_builtin(PlacementFactory factory, void* context,
                              const PlacementInput& input) {
    PlacementResult result{CallCode::invalid_input, nullptr, {0, 0, 0}};
    if (!input.template_id || input.template_id > std::numeric_limits<std::uint32_t>::max() ||
        !finite(input.world_position) || !finite(input.context_origin) ||
        !finite(input.rotation_degrees) || !finite(input.scale) ||
        input.scale.x <= 0 || input.scale.y <= 0 || input.scale.z <= 0)
        return result;
    // Match the observed native float subtraction; don't reinterpret this as
    // screen-space conversion or convert angles to radians a second time.
    const Vec3 position{input.world_position.x-input.context_origin.x,
                        input.world_position.y-input.context_origin.y,
                        input.world_position.z-input.context_origin.z};
    if (!finite(position)) return result;
    result.local_position = position;
    if (!factory || !context) {
        result.code = CallCode::missing_binding;
        return result;
    }
    // Copy all indirect values before calling, just as the drag caller does.
    const Vec3 rotation = input.rotation_degrees, scale = input.scale;
    // The 3rd argument is a caller-selected mode flag, not a constant of the ABI. Over the 21
    // recovered callers of 0x106df3c0 in 7.1 it is passed as 1 (8 call sites: 97fd890, be77ee0
    // x2, be7ce60 x2, c7ff920, d1f72b0, d31aae6, e41de90, f3e0200), as 0 (6 call sites: 13ca9bd0,
    // 97ef1b0, be78c50 x2, d31aeb0, ea16be0), and from a register (97fb350 passes r15d/ebx,
    // be749b0 r14d, bcdb7b0 esi) -- see .runtime/verification/update-repair-20260924/native-port/.
    // The drag caller d31aae6 passes 1, which is what this build has always sent. It is a macro
    // so a reviewed probe build can ask the one question that cannot be settled offline: whether
    // a 3xxxxxxx creature template needs a different value. Undefined -> 1, so an ordinary build
    // and tests/scene_calls_test.cpp (which asserts builtin == 1) are unchanged.
#ifdef HR_PLACE_BUILTIN
    constexpr std::uint8_t builtin = static_cast<std::uint8_t>(HR_PLACE_BUILTIN);
#else
    constexpr std::uint8_t builtin = 1;
#endif
    result.owner = factory(context, static_cast<std::uint32_t>(input.template_id),
                           builtin, &position, &rotation, &scale, 0, 1, nullptr, 0, 0);
    result.code = result.owner ? CallCode::returned : CallCode::null_entity;
    return result;
}

SaveResult save_current(SaveCurrentLevel save, void* save_manager) {
    if (!save || !save_manager) return {CallCode::missing_binding, 0, false};
    const std::int32_t status = save(save_manager);
    return {status == 0 ? CallCode::returned : CallCode::native_save_rejected,
            status, true};
}
}
