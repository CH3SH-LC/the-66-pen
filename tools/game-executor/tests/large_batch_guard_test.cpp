// Compile the real batch branch and test its SEH boundary in a private host.
#define GS_LARGE_SCENE 1
#define HR_ACTION 3
#define HR_TARGET_PID GetCurrentProcessId()
#define HR_TARGET_TID GetCurrentThreadId()
#define HR_DEADLINE 0xffffffffffffffffULL
#define HR_EXPECTED_LEVEL 99
#define HR_LEVEL_ANCHOR 0,0,0,0
#define HR_PLACE_ANCHOR 0,0,0,0
#define HR_SAVE_ANCHOR 0,0,0,0
#define HR_PLACEMENT_COUNT 1
static constexpr unsigned int HR_EXPECTED_ENTITY_IDS[] = {1000};
static constexpr unsigned int HR_PLACEMENT_TEMPLATE[] = {20001034};
static constexpr float HR_PLACEMENT_TRANSFORM[] = {100,20,-60,0,90,0,1,2,1};
#include "../native/game_scene_action.cpp"
#include <cstdio>
void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept {out->status=GS_UNREADABLE;}
void* __cdecl Throws(void*,std::uint32_t,std::uint8_t,const ge::scene::Vec3*,const ge::scene::Vec3*,
    const ge::scene::Vec3*,std::uint32_t,std::uint8_t,void*,std::uint8_t,std::uint8_t) {
    RaiseException(0xe0000042, 0, 0, nullptr); return nullptr;
}
void* __cdecl ReturnsNull(void*,std::uint32_t,std::uint8_t,const ge::scene::Vec3*,const ge::scene::Vec3*,
    const ge::scene::Vec3*,std::uint32_t,std::uint8_t,void*,std::uint8_t,std::uint8_t) { return nullptr; }
int main() {
    const ge::scene::PlacementInput input{20001034,{100,20,-60},{100,20,-60},{0,90,0},{1,2,1}};
    ge::scene::PlacementResult result{}; std::uint32_t exception=0;
    if(PlaceBatchSafely(Throws,reinterpret_cast<void*>(0x10000),input,&result,&exception)||exception!=0xe0000042)return 1;
    exception=0;
    if(!PlaceBatchSafely(ReturnsNull,reinterpret_cast<void*>(0x10000),input,&result,&exception)||exception||result.code!=ge::scene::CallCode::null_entity)return 2;
    std::printf("{\"ok\":true,\"checks\":2,\"scope\":\"private-native-batch-no-game\"}\n");
    return 0;
}
