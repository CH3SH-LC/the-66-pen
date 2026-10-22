// Runs only in this private test host. No hooks, process reads, game methods or UAC.
#define GS_BOOTSTRAP_READONLY 1
#define HR_ACTION 0
#define HR_GAME_TIMESTAMP 123
#define HR_GAME_IMAGE_SIZE 4096
#define HR_CONTEXT_ANCHOR_RVA 0x100
#define HR_CONTEXT_ANCHOR 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
#define GS_GLOBAL_SLOT_RVA 0x80
#define GS_CONTEXT_MANAGER_OFFSET 0xc210
#define GS_SAVE_MANAGER_OFFSET 0xdb50
#define GS_MANAGER_KEY_OFFSET 0x38
#define GS_MANAGER_DICTIONARY_OFFSET 0x10
#define GS_CONTEXT_BUCKETS_OFFSET 0x28
#define GS_CONTEXT_ENTRIES_OFFSET 0x30
#define GS_CONTEXT_VERSION_OFFSET 0x38
#define GS_CONTEXT_ORIGIN_OFFSET 0x38
#define GS_ENTITY_DICTIONARY_OFFSET 0x18
#define GS_ENTITY_BUCKETS_OFFSET 0x20
#define GS_ENTITY_ENTRIES_OFFSET 0x28
#define GS_ENTITY_VERSION_OFFSET 0x3c
#define GS_OWNER_ID_OFFSET 0x1c
#define GS_OWNER_CONTEXT_OFFSET 0xa0
#define GS_OWNER_CONFIG_OFFSET 0xb8
#define GS_CONFIG_ID_OFFSET 0x1c
#define GS_PROFILE_ANCHOR_RVAS 0x100,0x120,0x140,0x160
#define GS_PROFILE_ANCHOR_BYTES {0},{0},{0},{0}
#define GS_PROFILE_STACK_RVAS 0x200,0x300
#define GS_PROFILE_HOTFIX_RVAS 0x400,0x401,0x402,0x403
#define GS_READ_LEVEL_METADATA 1
#define GS_LEVEL_GATE_MANAGER_OFFSET 0xa430
#define GS_LEVEL_GATE_OBJECT_OFFSET 0x50
#define GS_LEVEL_MODE_MANAGER_OFFSET 0xa440
#define GS_LEVEL_MODE_OFFSET 0x1cc
#define GS_LEVEL_MODE_REQUIRED 0xb993
#define GS_LEVEL_MANAGER_OFFSET 0xa960
#define GS_LEVEL_EDITING_OFFSET 0xc9
#define GS_LEVEL_ID_OFFSET 0x98
#include "../native/game_context_snapshot.cpp"
#include <array>
#include <cstdio>

int main() {
    int count=0;
    auto require=[&](bool condition,const char* name) { ++count; if(!condition) {std::printf("{\"ok\":false,\"test\":\"%s\"}\n",name);return false;}return true; };
    std::array<unsigned char,4096> image{};
    GameContextSnapshot out{};
    out.moduleBase=reinterpret_cast<std::uint64_t>(image.data());out.peImageSize=4096;
    SYSTEM_INFO info{};GetSystemInfo(&info);
    Reader reader{&out,reinterpret_cast<std::uint64_t>(info.lpMaximumApplicationAddress)};
    if(!require(VerifyProfileAnchors(reader),"anchors_match"))return 1;
    image[0x140]=1;
    if(!require(!VerifyProfileAnchors(reader)&&out.lastReadStatus==GS_BUILD_MISMATCH,"anchor_mutation_rejected"))return 1;
    image[0x140]=0;out.lastReadStatus=0;out.peImageSize=0x170;
    if(!require(!VerifyProfileAnchors(reader),"anchor_bounds_rejected"))return 1;
    out.peImageSize=4096;out.stackCount=2;out.stack[0]=out.moduleBase+0x200;out.stack[1]=out.moduleBase+0x300;
    if(!require(VerifyStack(reader)&&(out.flags&GS_STACK_VERIFIED),"stack_match"))return 1;
    out.stack[1]++;
    if(!require(!VerifyStack(reader)&&out.lastReadStatus==GS_STACK_MISMATCH,"stack_mismatch_rejected"))return 1;
    if(!require(CheckHotfixBytes(reader),"hotfix_zero"))return 1;
    image[0x402]=1;
    if(!require(!CheckHotfixBytes(reader)&&out.lastReadStatus==GS_HOTFIX_ACTIVE,"active_hotfix_rejected"))return 1;
    alignas(8) std::array<unsigned char,64> buckets{};
    alignas(8) std::array<unsigned char,64> entries{};
    const std::int32_t head=1;std::memcpy(buckets.data()+0x20,&head,4);
    Entry entry{0,-1,0,0,0x10000};std::memcpy(entries.data()+0x20,&entry,sizeof(entry));
    Dictionary dictionary{0,reinterpret_cast<std::uint64_t>(buckets.data()),reinterpret_cast<std::uint64_t>(entries.data()),1,1,0,0};
    if(!require(WalkDictionary(reader,dictionary,true)&&out.contextMatchingEntries==1,"reachable_dictionary_entry"))return 1;
    entry.next=0;std::memcpy(entries.data()+0x20,&entry,sizeof(entry));
    if(!require(!WalkDictionary(reader,dictionary,true)&&out.lastReadStatus==GS_INVALID_STRUCTURE,"dictionary_cycle_rejected"))return 1;
    entry.next=-1;entry.hash=-1;std::memcpy(entries.data()+0x20,&entry,sizeof(entry));
    if(!require(!WalkDictionary(reader,dictionary,true),"invalid_hash_rejected"))return 1;
    alignas(8) std::array<unsigned char,65536> globals{};
    alignas(8) std::array<unsigned char,128> gate{};
    alignas(8) std::array<unsigned char,512> mode{};
    alignas(8) std::array<unsigned char,256> level{};
    out.global=reinterpret_cast<std::uint64_t>(globals.data());
    std::uint64_t ptr=reinterpret_cast<std::uint64_t>(gate.data());std::memcpy(globals.data()+0xa430,&ptr,8);
    std::memcpy(gate.data()+0x50,&ptr,8);
    ptr=reinterpret_cast<std::uint64_t>(mode.data());std::memcpy(globals.data()+0xa440,&ptr,8);
    ptr=reinterpret_cast<std::uint64_t>(level.data());std::memcpy(globals.data()+0xa960,&ptr,8);
    std::uint32_t number=0xb993;std::memcpy(mode.data()+0x1cc,&number,4);
    number=99;std::memcpy(level.data()+0x98,&number,4);level[0xc9]=1;
    LevelObservation first{},second{};
    if(!require(ReadLevelObservation(reader,first)&&first.levelId==99,"level_default_predicates_observed"))return 1;
    if(!require(ReadLevelObservation(reader,second)&&SameLevelObservation(first,second),"level_unchanged"))return 1;
    second.levelId++;
    if(!require(!SameLevelObservation(first,second),"level_change_rejected"))return 1;
    level[0xc9]=0;
    if(!require(!ReadLevelObservation(reader,second),"not_editing_rejected"))return 1;
    level[0xc9]=1;mode[0x1cc]=0;
    if(!require(!ReadLevelObservation(reader,second),"wrong_mode_rejected"))return 1;
    number=0xb993;std::memcpy(mode.data()+0x1cc,&number,4);number=0;std::memcpy(level.data()+0x98,&number,4);
    if(!require(!ReadLevelObservation(reader,second),"zero_level_rejected"))return 1;
    GameContextSnapshot own{};CaptureGameContextSnapshot(&own);
    if(!require(own.status==GS_BUILD_MISMATCH,"wrong_host_no_object_dereference"))return 1;
    std::printf("{\"ok\":true,\"tests\":%d,\"scope\":\"private-host-only-no-game\"}\n",count);
    return 0;
}
