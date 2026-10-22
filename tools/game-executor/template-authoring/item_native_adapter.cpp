#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "item_native_adapter.h"
#include <cstring>
#include <type_traits>

#if !defined(TA_ITEM_REVIEWED) || TA_ITEM_REVIEWED != 1 || HR_ACTION != 6 || !GS_REVIEWED_ACTION_PROFILE
#error "Item adapter requires its own reviewed action 6 profile"
#endif
#if !defined(TA_ITEM_ANCHOR_RVAS) || !defined(TA_ITEM_ANCHOR_BYTES) || !defined(TA_ITEM_HOTFIX_RVAS)
#error "Missing item current-build code/hotfix evidence"
#endif

namespace {
bool read_memory(void*, std::uint64_t address, void* target, std::size_t length) noexcept {
    if (!target || !length || address < 0x10000 || address >= 0x0000800000000000ULL ||
        length > 0x0000800000000000ULL - address) return false;
    std::size_t done = 0;
    while (done < length) {
        MEMORY_BASIC_INFORMATION region{};
        const auto at = address + done;
        if (VirtualQuery(reinterpret_cast<const void*>(at), &region, sizeof(region)) != sizeof(region) ||
            region.State != MEM_COMMIT || (region.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
        const auto start = reinterpret_cast<std::uint64_t>(region.BaseAddress);
        if (at < start || at - start >= region.RegionSize) return false;
        const auto available = region.RegionSize - static_cast<std::size_t>(at - start);
        const auto part = (length - done < available) ? length - done : available;
        __try { std::memcpy(static_cast<unsigned char*>(target) + done, reinterpret_cast<const void*>(at), part); }
        __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
        done += part;
    }
    return true;
}
bool verify_code(const GameContextSnapshot& current) noexcept {
    if (current.moduleBase != reinterpret_cast<std::uint64_t>(GetModuleHandleW(L"YuanShen.exe")) ||
        current.peTimestamp != HR_GAME_TIMESTAMP || current.peImageSize != HR_GAME_IMAGE_SIZE) return false;
    constexpr std::uint32_t rvas[] = {TA_ITEM_ANCHOR_RVAS};
    constexpr unsigned char anchors[][32] = {TA_ITEM_ANCHOR_BYTES};
    static_assert(sizeof(rvas) / sizeof(rvas[0]) == sizeof(anchors) / sizeof(anchors[0]), "anchor count");
    static_assert(sizeof(rvas) / sizeof(rvas[0]) == 8, "seven item entries and transitive full creation service");
    unsigned char actual[32]{};
    for (std::size_t i = 0; i < sizeof(rvas) / sizeof(rvas[0]); ++i)
        if (!read_memory(nullptr, current.moduleBase + rvas[i], actual, sizeof(actual)) ||
            std::memcmp(actual, anchors[i], sizeof(actual))) return false;
    constexpr std::uint32_t watches[] = {GS_PROFILE_HOTFIX_RVAS, TA_ITEM_HOTFIX_RVAS};
    for (auto rva : watches) {
        unsigned char value = 255;
        if (!read_memory(nullptr, current.moduleBase + rva, &value, 1) || value != 0) return false;
    }
    return true;
}
bool unchanged(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    if (b.status != GS_OK || (b.flags & 1951) != 1951 || b.entityRejected ||
        b.entityCaptured != b.entityValidEntries || a.entityCaptured != b.entityCaptured ||
        b.entityCaptured > kMaxEntities || b.currentContext != a.currentContext ||
        b.reserved != a.reserved || b.global != a.global || b.moduleBase != a.moduleBase ||
        b.entityVersionBefore != a.entityVersionBefore || b.entityVersionAfter != a.entityVersionAfter) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i]; const auto& y = b.entities[i];
        if (x.id != y.id || x.owner != y.owner || x.config != y.config || x.context != y.context ||
            x.configId != y.configId || x.dictionaryKey != y.dictionaryKey) return false;
    }
    return true;
}
void capture_scene(const GameContextSnapshot* before, NativeItemReceipt* out) noexcept {
    CaptureGameContextSnapshot(&out->after);
    out->afterSceneUnchanged = unchanged(*before, out->after) ? 1U : 0U;
}
void execute(const GameContextSnapshot* before, NativeItemReceipt* out) noexcept {
    using namespace ge::templates;
    static_assert(sizeof(TA_EXPECTED_SNAPSHOT) == sizeof(GameContextSnapshot), "reviewed baseline ABI");
    std::memcpy(&out->expected, TA_EXPECTED_SNAPSHOT, sizeof(out->expected));
    const ItemActionReview review{HR_TARGET_PID, HR_TARGET_TID, HR_DEADLINE, &out->expected};
    const ItemActionRuntime runtime{GetCurrentProcessId(), GetCurrentThreadId(), GetTickCount64(), verify_code(*before)};
    const auto base = before->moduleBase;
    const ItemActionBindings calls{
        reinterpret_cast<InitializeItemMetadata>(base + 0x524250),
        reinterpret_cast<CountNormalItems>(base + 0x144e26f0),
        reinterpret_cast<InitializeItemLimits>(base + 0x7887c70),
        reinterpret_cast<GetItemController>(base + 0x9b0e050),
        reinterpret_cast<StringNewLen>(base + 0x526de0),
        reinterpret_cast<CreateNormalItem>(base + 0x9b0e0d0),
        reinterpret_cast<ReadDefaultItemValue>(base + 0x7888da0)};
    ExecuteItemAction(before, review, runtime, {nullptr, read_memory}, calls,
        std::string_view(TA_ITEM_NAME, sizeof(TA_ITEM_NAME) - 1), &out->workspace, &out->action);
    if (out->action.createCalled) capture_scene(before, out);
}
}
void ExecuteNativeItemAction(const GameContextSnapshot* before, NativeItemReceipt* out) noexcept {
    if (!before || !out) return;
    static_assert(std::is_trivially_copyable<NativeItemReceipt>::value, "receipt byte reset");
    // Do not materialize the large aggregate on the game thread's stack.
    std::memset(out, 0, sizeof(*out)); out->size = sizeof(*out); out->version = 1;
    out->action.code = ge::templates::ItemActionCode::invalid_review;
    __try { execute(before, out); }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        out->sehCode = GetExceptionCode();
        out->action.code = ge::templates::ItemActionCode::call_exception;
        // Progress is written to caller-owned storage BEFORE each native call.
        // A default/name fault therefore never becomes a false handler attempt.
        if (out->action.item.exceptionStage != ge::templates::ItemStage::none)
            out->action.item.code = ge::templates::ItemCode::native_exception;
        out->action.createCalled = out->action.item.handlerCalled;
        out->action.outcomeUncertain = out->action.item.outcomeUncertain || out->action.item.handlerCalled;
        if (out->action.stage == ge::templates::ItemActionStage::name_allocation)
            out->action.allocationCalled = true;
        if (out->action.createCalled) {
            ge::templates::CaptureTemplateCatalog(before, {nullptr, read_memory},
                &out->workspace.capture, &out->workspace.after);
            capture_scene(before, out);
        }
    }
}
