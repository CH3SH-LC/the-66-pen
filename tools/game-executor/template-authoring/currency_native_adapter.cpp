#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "currency_native_adapter.h"
#include <cstring>
#include <type_traits>

#if !defined(TA_CURRENCY_REVIEWED) || TA_CURRENCY_REVIEWED != 1 || HR_ACTION != 5 || !GS_REVIEWED_ACTION_PROFILE
#error "Currency adapter requires its own reviewed action 5 profile"
#endif
#if !defined(TA_CURRENCY_ANCHOR_RVAS) || !defined(TA_CURRENCY_ANCHOR_BYTES) || !defined(TA_CURRENCY_HOTFIX_RVAS)
#error "Missing currency current-build code/hotfix evidence"
#endif

namespace {
bool read_memory(void*, std::uint64_t address, void* target, std::size_t length) noexcept {
    if (!target || !length || address < 0x10000 || address >= 0x0000800000000000ULL ||
        length > 0x0000800000000000ULL - address) return false;
    // A bounded read can span adjacent committed regions. Check every byte's
    // region before copying; never change target page permissions.
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
        __try {std::memcpy(static_cast<unsigned char*>(target) + done, reinterpret_cast<const void*>(at), part);}
        __except (EXCEPTION_EXECUTE_HANDLER) {return false;}
        done += part;
    }
    return true;
}
bool verify_code(const GameContextSnapshot& current) noexcept {
    if (current.moduleBase != reinterpret_cast<std::uint64_t>(GetModuleHandleW(L"YuanShen.exe")) ||
        current.peTimestamp != HR_GAME_TIMESTAMP || current.peImageSize != HR_GAME_IMAGE_SIZE) return false;
    constexpr std::uint32_t rvas[] = {TA_CURRENCY_ANCHOR_RVAS};
    constexpr unsigned char anchors[][32] = {TA_CURRENCY_ANCHOR_BYTES};
    static_assert(sizeof(rvas) / sizeof(rvas[0]) == sizeof(anchors) / sizeof(anchors[0]), "anchor count");
    static_assert(sizeof(rvas) / sizeof(rvas[0]) >= 4, "all four native calls require anchors");
    unsigned char actual[32]{};
    for (std::size_t i = 0; i < sizeof(rvas) / sizeof(rvas[0]); ++i)
        if (!read_memory(nullptr, current.moduleBase + rvas[i], actual, sizeof(actual)) ||
            std::memcmp(actual, anchors[i], sizeof(actual))) return false;
    constexpr std::uint32_t watches[] = {GS_PROFILE_HOTFIX_RVAS, TA_CURRENCY_HOTFIX_RVAS};
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
void execute(const GameContextSnapshot* before, NativeCurrencyReceipt* out) noexcept {
    using namespace ge::templates;
    static_assert(sizeof(TA_EXPECTED_SNAPSHOT) == sizeof(GameContextSnapshot), "reviewed baseline ABI");
    std::memcpy(&out->expected, TA_EXPECTED_SNAPSHOT, sizeof(out->expected));
    const CurrencyActionReview review{HR_TARGET_PID, HR_TARGET_TID, HR_DEADLINE, &out->expected};
    const CurrencyActionRuntime runtime{GetCurrentProcessId(), GetCurrentThreadId(), GetTickCount64(), verify_code(*before)};
    const auto base = before->moduleBase;
    const CurrencyActionBindings calls{
        reinterpret_cast<CreateTemplate>(base + 0xb0a90c0),
        reinterpret_cast<StringNewLen>(base + 0x526de0),
        reinterpret_cast<LookupCurrencyGroup>(base + 0xb4fcc60),
        reinterpret_cast<InitializeResourceLimits>(base + 0x7887c70)};
    ExecuteCurrencyAction(before, review, runtime, {nullptr, read_memory}, calls,
        std::string_view(TA_CURRENCY_NAME, sizeof(TA_CURRENCY_NAME) - 1), &out->workspace, &out->action);
    if (out->action.createCalled) {
        CaptureGameContextSnapshot(&out->after);
        out->afterSceneUnchanged = unchanged(*before, out->after) ? 1U : 0U;
    }
}
}
void ExecuteNativeCurrencyAction(const GameContextSnapshot* before, NativeCurrencyReceipt* out) noexcept {
    if (!before || !out) return;
    static_assert(std::is_trivially_copyable<NativeCurrencyReceipt>::value, "receipt byte reset");
    // Clear caller-owned storage directly; aggregate assignment can put this
    // nearly-megabyte receipt temporary on the game thread's stack.
    std::memset(out, 0, sizeof(*out)); out->size = sizeof(*out); out->version = 1;
    out->action.code = ge::templates::CurrencyActionCode::invalid_review;
    __try {execute(before, out);}
    __except (EXCEPTION_EXECUTE_HANDLER) {
        out->sehCode = GetExceptionCode();
        out->action.code = ge::templates::CurrencyActionCode::call_exception;
        // Name allocation can fault before returning its flag. Creation's flag
        // is set before the service is called and remains a no-retry marker.
        if (out->action.stage == ge::templates::CurrencyActionStage::name_allocation)
            out->action.allocationCalled = true;
        out->action.outcomeUncertain = out->action.createCalled;
    }
}
