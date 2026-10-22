#pragma once
#include <cstdint>

// Internal host-side call contracts, not a remote-address or game-loading API.
// Only an adapter already running on the verified game scene thread may use
// these functions with live context/manager objects and resolved entry points.
// Nothing here discovers a process, resolves an RVA, binds GE_Pump or hooks it.
namespace ge::scene {
struct Vec3 { float x, y, z; };
static_assert(sizeof(Vec3) == 12);

// YuanShen 7.1 default drag caller d31aae6 -> 106df3c0, Windows x64.
// Historical caller 1362a429 -> b7a1aa0 used the same parameter ABI.
// The vectors are indirect 12-byte values, in position/rotation/scale order.
using PlacementFactory = void* (__cdecl *)(
    void* context, std::uint32_t template_id, std::uint8_t builtin,
    const Vec3* position, const Vec3* rotation_degrees, const Vec3* scale,
    std::uint32_t requested_id, std::uint8_t flag8,
    void* optional_data, std::uint8_t flag10, std::uint8_t flag11);

// 7.1 caller 135635e4 passes global+db50 to 11fe2f00. Its return is a
// status enum, not bool: zero follows 11c03960==1 and post-save calls.
// Historical ddbfe60(global+ac50) used the same parameter/status ABI.
using SaveCurrentLevel = std::int32_t (__cdecl *)(void* save_manager);

enum class CallCode : std::uint32_t {
    returned = 0, invalid_input = 1, missing_binding = 2,
    null_entity = 3, native_save_rejected = 4
};
struct PlacementInput {
    std::uint64_t template_id;
    Vec3 world_position;
    Vec3 context_origin;
    Vec3 rotation_degrees;
    Vec3 scale;
};
struct PlacementResult {
    CallCode code;
    void* owner;
    Vec3 local_position;
};
struct SaveResult {
    CallCode code;
    std::int32_t native_status;
    bool called;
};

// Returned != registered/visible/persistent. Owner identity, actual context,
// scene revision, undo/dirty state and disk readback remain adapter duties.
// Neither helper retries a native call or attempts rollback after an effect.
PlacementResult place_builtin(PlacementFactory factory, void* context,
                              const PlacementInput& input);
SaveResult save_current(SaveCurrentLevel save, void* save_manager);
}
