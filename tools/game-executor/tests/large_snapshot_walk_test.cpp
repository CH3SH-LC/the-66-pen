// Private memory only; exercises the actual production dictionary walker at scale.
#define GS_LARGE_SCENE 1
#define main LegacyReadonlyGuardMain
#include "readonly_snapshot_guard_test.cpp"
#undef main
#include <vector>

int main() {
    static GameContextSnapshot output{};
    SYSTEM_INFO info{}; GetSystemInfo(&info);
    int checks = 0;
    auto check = [&](bool ok, const char* name) { ++checks; if (!ok) std::printf("FAIL %s\n", name); return ok; };
    if (!check(sizeof(output) == 262584 && kSnapshotVersion == 2, "explicit-v2-abi")) return 1;
    for (std::uint32_t count : {600U, 3000U, 4096U, 4097U}) {
        std::memset(&output, 0, sizeof(output));
        output.currentContext = 0x80000;
        std::vector<unsigned char> buckets(0x20 + 8192 * 4);
        std::vector<unsigned char> entries(0x20 + 8192 * 24);
        std::vector<unsigned char> owners(count * 256);
        std::vector<unsigned char> configs(count * 64);
        for (std::uint32_t i = 0; i < count; ++i) {
            const std::int32_t head = static_cast<std::int32_t>(i + 1);
            std::memcpy(buckets.data() + 0x20 + i * 4, &head, 4);
            const std::uint32_t id = 1000 + i, configId = 20001034;
            const auto owner = reinterpret_cast<std::uint64_t>(owners.data() + i * 256);
            const auto config = reinterpret_cast<std::uint64_t>(configs.data() + i * 64);
            Entry row{static_cast<std::int32_t>(i), -1, id, 0, owner};
            std::memcpy(entries.data() + 0x20 + i * 24, &row, sizeof(row));
            std::memcpy(owners.data() + i * 256 + GS_OWNER_ID_OFFSET, &id, 4);
            std::memcpy(owners.data() + i * 256 + GS_OWNER_CONTEXT_OFFSET, &output.currentContext, 8);
            std::memcpy(owners.data() + i * 256 + GS_OWNER_CONFIG_OFFSET, &config, 8);
            std::memcpy(configs.data() + i * 64 + GS_CONFIG_ID_OFFSET, &configId, 4);
        }
        Reader reader{&output, reinterpret_cast<std::uint64_t>(info.lpMaximumApplicationAddress)};
        Dictionary dictionary{0, reinterpret_cast<std::uint64_t>(buckets.data()),
            reinterpret_cast<std::uint64_t>(entries.data()), 8192, 8192, 0, 0};
        if (!check(WalkDictionary(reader, dictionary, false), "bounded-large-walk")) return 1;
        if (!check(output.entityValidEntries == count && output.entityCaptured == (count > 4096 ? 4096 : count), "complete-counts")) return 1;
        if (!check(output.entityRejected == 0 && output.bytesRead <= kSnapshotReadBudget && output.readCalls <= kSnapshotReadCalls, "budget-and-owner-checks")) return 1;
        if (!check(bool(output.flags & GS_ENTITIES_TRUNCATED) == (count > 4096), "overflow-explicitly-truncated")) return 1;
        for (std::uint32_t i = 0; i < output.entityCaptured; ++i) {
            if (!check(output.entities[i].id == 1000 + i && output.entities[i].flags == 79, "every-id-owner-key-context")) return 1;
        }
        // A budget exhausted midway is a rejection, never a successful prefix.
        std::memset(&output, 0, sizeof(output)); output.bytesRead = kSnapshotReadBudget;
        if (!check(!WalkDictionary(reader, dictionary, false) && output.lastReadStatus == GS_LIMIT_EXCEEDED, "budget-exhaustion-refused")) return 1;
    }
    std::printf("{\"ok\":true,\"checks\":%d,\"scope\":\"private-memory-no-game\"}\n", checks);
    return 0;
}
