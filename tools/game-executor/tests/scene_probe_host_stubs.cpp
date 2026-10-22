// Private host fixture only: never linked into production builders. Exercise
// the actual receipt hook/probe without resolving or calling any game address.
#include <cstring>
#include "../native/hook_receipt_protocol.h"

void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept {
    std::memset(out, 0, sizeof(*out));
    out->structSize = sizeof(*out);
    out->version = kSnapshotVersion;
    out->status = GS_OK;
}

#if HR_ACTION
void ExecuteGameSceneAction(const GameContextSnapshot* before, GameSceneActionResult* out) {
    std::memset(out, 0, sizeof(*out));
    out->size = sizeof(*out);
    out->version = 1;
    out->action = HR_ACTION;
    out->called = 1;
    out->saveStatus = 0;
    std::memcpy(&out->after, before, sizeof(out->after));
}
#endif
