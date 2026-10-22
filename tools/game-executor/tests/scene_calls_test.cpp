#include "../native/scene_calls.h"
#include <cmath>
#include <cstdio>
#include <initializer_list>
#include <limits>
#include <stdexcept>

using namespace ge::scene;
namespace {
int checks = 0, creates = 0, saves = 0;
int context_value = 11, owner_value = 22, manager_value = 33;
bool return_null = false;
std::int32_t save_status = 0;
std::uint32_t expected_template = 1402;
void check(bool ok, const char* text) {
    if (!ok) throw std::runtime_error(text);
    ++checks;
}
bool same(const Vec3& v, float x, float y, float z) {
    return v.x == x && v.y == y && v.z == z;
}
__declspec(noinline) void* __cdecl capture_create(
    void* context, std::uint32_t resource, std::uint8_t builtin,
    const Vec3* position, const Vec3* rotation, const Vec3* scale,
    std::uint32_t requested, std::uint8_t flag8, void* extra,
    std::uint8_t flag10, std::uint8_t flag11) {
    ++creates;
    check(context == &context_value && resource == expected_template && builtin == 1,
          "register arguments");
    check(position && rotation && scale && same(*position, 1, -2, 3) &&
          same(*rotation, 0, 90, -45) && same(*scale, 1, 2, 3),
          "three indirect vectors including degree rotation");
    check(requested == 0 && flag8 == 1 && extra == nullptr && flag10 == 0 && flag11 == 0,
          "all seven stack arguments including original drag constants");
    return return_null ? nullptr : &owner_value;
}
__declspec(noinline) std::int32_t __cdecl capture_save(void* manager) {
    ++saves;
    check(manager == &manager_value, "save manager identity");
    return save_status;
}
}
int main() {
    static_assert(sizeof(void*) == 8, "The contract must be tested on Windows x64.");
    try {
        PlacementInput input{1402, {101, 198, -297}, {100, 200, -300},
                             {0, 90, -45}, {1, 2, 3}};
        const auto result = place_builtin(capture_create, &context_value, input);
        check(result.code == CallCode::returned && result.owner == &owner_value &&
              same(result.local_position, 1, -2, 3) && creates == 1,
              "single invocation and returned owner");
        check(same(input.world_position, 101, 198, -297), "input not mutated");
        expected_template = std::numeric_limits<std::uint32_t>::max();
        input.template_id = expected_template;
        check(place_builtin(capture_create, &context_value, input).code == CallCode::returned,
              "unsigned template upper bound");
        const int baseline = creates;
        input.template_id = std::uint64_t{1} << 32;
        check(place_builtin(capture_create, &context_value, input).code == CallCode::invalid_input,
              "reject truncation from request uint64 to game uint32");
        input.template_id = 0;
        check(place_builtin(capture_create, &context_value, input).code == CallCode::invalid_input,
              "reject missing template");
        input.template_id = expected_template;
        input.world_position.x = std::numeric_limits<float>::max();
        input.context_origin.x = -std::numeric_limits<float>::max();
        check(place_builtin(capture_create, &context_value, input).code == CallCode::invalid_input,
              "reject float subtraction overflow before calling");
        input.world_position.x = 101; input.context_origin.x = 100;
        input.rotation_degrees.y = std::numeric_limits<float>::quiet_NaN();
        check(place_builtin(capture_create, &context_value, input).code == CallCode::invalid_input,
              "reject NaN rotation");
        input.rotation_degrees.y = 90; input.scale.z = 0;
        check(place_builtin(capture_create, &context_value, input).code == CallCode::invalid_input,
              "reject zero scale");
        input.scale.z = 3;
        check(place_builtin(nullptr, &context_value, input).code == CallCode::missing_binding &&
              place_builtin(capture_create, nullptr, input).code == CallCode::missing_binding &&
              creates == baseline, "invalid calls cause no native effects");
        return_null = true;
        const auto empty = place_builtin(capture_create, &context_value, input);
        check(empty.code == CallCode::null_entity && !empty.owner && creates == baseline+1,
              "null factory result is not success and is not retried");
        const auto missing = save_current(nullptr, &manager_value);
        const auto no_manager = save_current(capture_save, nullptr);
        check(!missing.called && !no_manager.called && saves == 0 &&
              missing.code == CallCode::missing_binding && no_manager.code == CallCode::missing_binding,
              "missing save binding does not look like status zero success");
        for (const auto status : {0, 1, 2, 3, -1}) {
            save_status = status;
            const int before = saves;
            const auto saved = save_current(capture_save, &manager_value);
            check(saved.called && saved.native_status == status && saves == before+1 &&
                  saved.code == (status == 0 ? CallCode::returned : CallCode::native_save_rejected),
                  "preserve native save status without bool inversion or retry");
        }
        std::printf("{\"scope\":\"win64_scene_call_contract\",\"checks_passed\":%d,"
                    "\"capture_create_calls\":%d,\"capture_save_calls\":%d,"
                    "\"game_runtime_verified\":false,\"gil_save_verified\":false}\n",
                    checks, creates, saves);
        return 0;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "scene-call contract failed: %s\n", error.what());
        return 1;
    }
}
