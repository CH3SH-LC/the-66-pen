// Production identity reconciliation, rehash order and tail corruption at 4096.
#define GS_LARGE_SCENE 1
#define main LegacyReviewedGuardMain
#include "reviewed_action_guard_test.cpp"
#undef main

int main() {
    static GameContextSnapshot before{}, after{};
    before.entityCaptured = 3000; after.entityCaptured = 3064;
    for (std::uint32_t i = 0; i < after.entityCaptured; ++i) {
        GameEntitySnapshot entity{};
        entity.id = 1000 + i; entity.owner = 0x100000 + i * 256;
        entity.config = 0x800000 + i * 64; entity.configId = 20001034; entity.context = 0x80000;
        after.entities[after.entityCaptured - 1 - i] = entity;
        if (i < before.entityCaptured) before.entities[i] = entity;
    }
    if (!BaselinePreserved(before, after)) return 1;
    // The last old entity (well beyond the old 512 ceiling) changed ownership.
    after.entities[64].owner++;
    if (BaselinePreserved(before, after)) return 2;
    after.entities[64].owner--;
    after.entities[0].id = after.entities[1].id;
    if (BaselinePreserved(before, after)) return 3;
    std::printf("{\"ok\":true,\"checks\":3,\"scope\":\"private-identity-no-game\"}\n");
    return 0;
}
