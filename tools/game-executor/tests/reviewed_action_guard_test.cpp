// Private-host memory only. No hooks, process access, UAC or game calls.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#define GS_REVIEWED_ACTION_PROFILE 1
#define HR_ACTION_PROFILE_REVIEWED 1
#define HR_ACTION 2
#define HR_TARGET_PID GetCurrentProcessId()
#define HR_TARGET_TID GetCurrentThreadId()
#define HR_DEADLINE 0xffffffffffffffffULL
#define HR_EXPECTED_LEVEL 99
#define HR_LEVEL_ANCHOR_RVA 0x100
#define HR_PLACE_ANCHOR_RVA 0x120
#define HR_SAVE_ANCHOR_RVA 0x140
#define HR_LEVEL_ANCHOR 0,0,0,0
#define HR_PLACE_ANCHOR 0,0,0,0
#define HR_SAVE_ANCHOR 0,0,0,0
#define HR_LEVEL_MANAGER_OFFSET 0x80
#define HR_STACK_PUMP_RVA 0x200
#define HR_STACK_OUTER_RVA 0x300
#define GS_PROFILE_HOTFIX_RVAS 0x400,0x401
#define HR_EXPECTED_CONTEXT 0x80000ULL
static constexpr unsigned int HR_EXPECTED_ENTITY_IDS[]={123};
static constexpr unsigned long long HR_EXPECTED_OWNER_POINTERS[]={0xc0000};
static constexpr unsigned long long HR_EXPECTED_CONFIG_POINTERS[]={0xd0000};
static constexpr unsigned int HR_EXPECTED_CONFIG_IDS[]={20001034};
static constexpr unsigned long long HR_EXPECTED_ENTITY_CONTEXTS[]={0x80000};
#include "../native/game_scene_action.cpp"
#include <array>
#include <cstdio>
#include <cstdlib>
void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept {out->status=GS_UNREADABLE;}
int main() {
    std::array<unsigned char,4096> memory{};
    GameContextSnapshot before{};GameSceneActionResult result{};int checks=0;
    auto require=[&](bool ok,const char* name){++checks;if(!ok)std::printf("{\"ok\":false,\"test\":\"%s\"}\n",name);return ok;};
    before.moduleBase=reinterpret_cast<std::uint64_t>(memory.data());before.global=before.moduleBase;
    before.reserved=99;before.currentContext=HR_EXPECTED_CONTEXT;before.status=GS_OK;before.flags=1951;
    before.stackCount=2;before.stack[0]=before.moduleBase+0x200;before.stack[1]=before.moduleBase+0x300;
    before.entityCaptured=before.entityValidEntries=1;
    before.entities[0].id=123;before.entities[0].owner=0xc0000;before.entities[0].config=0xd0000;
    before.entities[0].configId=20001034;before.entities[0].context=0x80000;
    std::uint64_t manager=0x10000;std::memcpy(memory.data()+0x80,&manager,8);
    if(!require(BaselineIdentityMatches(before),"full_identity_match"))return 1;
    before.entities[0].configId++;
    ExecuteGameSceneAction(&before,&result);
    if(!require(result.status==6&&result.called==0,"config_change_refused_before_getter"))return 1;
    before.entities[0].configId--;
    before.entities[0].owner++;
    if(!require(!BaselineIdentityMatches(before),"owner_change_refused"))return 1;
    before.entities[0].owner--;before.currentContext++;
    if(!require(!BaselineIdentityMatches(before),"context_change_refused"))return 1;
    before.currentContext--;memory[0x401]=1;
    ExecuteGameSceneAction(&before,&result);
    if(!require(result.status==3&&result.called==0,"hotfix_refused_before_getter"))return 1;
    memory[0x401]=0;before.flags&=~512;
    ExecuteGameSceneAction(&before,&result);
    if(!require(result.status==1&&result.called==0,"incomplete_evidence_refused"))return 1;
    before.flags=1951;before.stack[1]++;
    ExecuteGameSceneAction(&before,&result);
    if(!require(result.status==2&&result.called==0,"stack_refused"))return 1;
    before.stack[1]--;memory[0x140]=1;
    ExecuteGameSceneAction(&before,&result);
    if(!require(result.status==3&&result.called==0,"anchor_refused"))return 1;
    std::printf("{\"ok\":true,\"checks\":%d,\"scope\":\"private-host-no-game-no-calls\"}\n",checks);return 0;
}
