#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "binding_native_adapter.h"
#include <cstring>
#include <type_traits>

#if !defined(TA_BINDING_REVIEWED) || TA_BINDING_REVIEWED != 1 || HR_ACTION != 7 || !GS_REVIEWED_ACTION_PROFILE
#error "Binding adapter requires its own reviewed action 7 profile"
#endif
#if !defined(TA_REFERENCE_ANCHOR_RVAS) || !defined(TA_REFERENCE_ANCHOR_BYTES) || !defined(TA_REFERENCE_HOTFIX_RVAS) || !defined(TA_REFERENCE_USAGE_GROUPS)
#error "Native binding requires the reviewed typed-pool reference route"
#endif
#if !defined(TA_BINDING_ANCHOR_RVAS) || !defined(TA_BINDING_ANCHOR_BYTES) || !defined(TA_BINDING_HOTFIX_RVAS)
#error "Missing binding current-build code/hotfix evidence"
#endif
static_assert(TA_BINDING_KIND == 33 || TA_BINDING_KIND == 35, "Fixed bag/shop only");
namespace {
bool read_memory(void*, std::uint64_t address, void* target, std::size_t length) noexcept {
    if (!target || !length || address < 0x10000 || address >= 0x0000800000000000ULL ||
        length > 0x0000800000000000ULL - address) return false;
    std::size_t done = 0;
    while (done < length) {
        MEMORY_BASIC_INFORMATION region{}; const auto at = address + done;
        if (VirtualQuery(reinterpret_cast<const void*>(at), &region, sizeof(region)) != sizeof(region) ||
            region.State != MEM_COMMIT || (region.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
        const auto start = reinterpret_cast<std::uint64_t>(region.BaseAddress);
        if (at < start || at - start >= region.RegionSize) return false;
        const auto available = region.RegionSize - static_cast<std::size_t>(at - start);
        const auto part = length - done < available ? length - done : available;
        __try { std::memcpy(static_cast<unsigned char*>(target) + done, reinterpret_cast<const void*>(at), part); }
        __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
        done += part;
    }
    return true;
}
bool verify_code(const GameContextSnapshot& current) noexcept {
    if (current.moduleBase != reinterpret_cast<std::uint64_t>(GetModuleHandleW(L"YuanShen.exe")) ||
        current.peTimestamp != HR_GAME_TIMESTAMP || current.peImageSize != HR_GAME_IMAGE_SIZE) return false;
    constexpr std::uint32_t rvas[] = {TA_BINDING_ANCHOR_RVAS};
    constexpr unsigned char anchors[][32] = {TA_BINDING_ANCHOR_BYTES};
    static_assert(sizeof(rvas) / sizeof(rvas[0]) == 25 && sizeof(anchors) / sizeof(anchors[0]) == 25, "fixed binding/edit entry evidence");
    unsigned char actual[32]{};
    for (std::size_t i = 0; i < sizeof(rvas) / sizeof(rvas[0]); ++i)
        if (!read_memory(nullptr, current.moduleBase + rvas[i], actual, sizeof(actual)) ||
            std::memcmp(actual, anchors[i], sizeof(actual))) return false;
    constexpr std::uint32_t referenceRvas[] = {TA_REFERENCE_ANCHOR_RVAS};
    constexpr unsigned char referenceAnchors[][32] = {TA_REFERENCE_ANCHOR_BYTES};
    static_assert(sizeof(referenceRvas) / sizeof(referenceRvas[0]) == 4 && sizeof(referenceAnchors) / sizeof(referenceAnchors[0]) == 4, "fixed typed reference initialization evidence");
    for (std::size_t i = 0; i < sizeof(referenceRvas) / sizeof(referenceRvas[0]); ++i)
        if (!read_memory(nullptr, current.moduleBase + referenceRvas[i], actual, sizeof(actual)) ||
            std::memcmp(actual, referenceAnchors[i], sizeof(actual))) return false;
    constexpr std::uint32_t watches[] = {GS_PROFILE_HOTFIX_RVAS, TA_BINDING_HOTFIX_RVAS, TA_REFERENCE_HOTFIX_RVAS};
    for (auto rva : watches) {
        unsigned char value = 255;
        if (!read_memory(nullptr, current.moduleBase + rva, &value, 1) || value) return false;
    }
    return true;
}
bool same_scene(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    if (a.structSize != sizeof(a) || b.structSize != sizeof(b) || a.version != 1 || b.version != 1 ||
        a.status != GS_OK || b.status != GS_OK || (a.flags & 1951) != 1951 || (b.flags & 1951) != 1951 ||
        ((a.flags | b.flags) & 96) || a.entityRejected || b.entityRejected || a.activeKey || b.activeKey ||
        !a.reserved || a.reserved != b.reserved || a.moduleBase != b.moduleBase || a.global != b.global ||
        a.currentContext != b.currentContext || a.contextManager != b.contextManager || a.saveManager != b.saveManager ||
        a.peImageSize != b.peImageSize || a.peTimestamp != b.peTimestamp ||
        !ge::templates::TemplatePointer(a.moduleBase) || !ge::templates::TemplatePointer(a.global) ||
        !ge::templates::TemplatePointer(a.currentContext) || a.entityCaptured > kMaxEntities ||
        a.entityCaptured != b.entityCaptured || a.entityCaptured != a.entityValidEntries || b.entityCaptured != b.entityValidEntries ||
        a.entityVersionBefore != b.entityVersionBefore || a.entityVersionAfter != b.entityVersionAfter) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i]; const auto& y = b.entities[i];
        if (x.id != y.id || x.owner != y.owner || x.config != y.config || x.context != y.context ||
            x.configId != y.configId || x.dictionaryKey != y.dictionaryKey || x.flags != y.flags) return false;
    }
    return true;
}
void recover_progress(NativeBindingReceipt* out) noexcept {
    auto& action = out->action;
    out->componentMutationCalled = action.attachment.attach_called || action.binding.mutationCalled;
    out->nativeCallAttempted = out->metadataCallsStarted || action.binding.referenceFactoryCalled || out->componentMutationCalled ||
        action.edit.openCalled || action.edit.snapshotCalled || action.edit.notifyCalled || action.edit.closeCalled;
    out->runtimeStateMayHaveChanged = out->nativeCallAttempted;
    action.outcomeUncertain = action.outcomeUncertain || action.attachment.outcome_uncertain ||
        action.attachment.attach_called || action.binding.outcomeUncertain || action.binding.mutationCalled || action.edit.outcomeUncertain;
    action.needsOwnerNotification = action.needsOwnerNotification || action.binding.needsOwnerNotification;
}
void capture_after(const GameContextSnapshot* before, NativeBindingReceipt* out) noexcept {
    if (!out->nativeCallAttempted) return;
    // On reuse/partial/fault paths retain independent raw after-state, without
    // promoting it to successful binding or claiming notification/export/save.
    if (out->action.code != ge::templates::BindingActionCode::binding_verified) {
        ge::templates::CaptureTemplateCatalog(before, {nullptr, read_memory},
            &out->workspace.catalogScratch, &out->workspace.afterCatalog);
        if (out->action.owner)
            ge::component_attachment::CaptureComponents({nullptr, read_memory}, out->action.owner,
                &out->workspace.attachment.capture, &out->workspace.postComponents);
    }
    CaptureGameContextSnapshot(&out->after);
    out->afterSceneUnchanged = same_scene(*before, out->after) ? 1U : 0U;
}
void execute(const GameContextSnapshot* before, NativeBindingReceipt* out) noexcept {
    using namespace ge::templates;
    static_assert(sizeof(TA_EXPECTED_SNAPSHOT) == sizeof(GameContextSnapshot), "reviewed baseline ABI");
    std::memcpy(&out->expected, TA_EXPECTED_SNAPSHOT, sizeof(out->expected));
    out->code = NativeBindingCode::invalid_review;
    if (GetCurrentProcessId() != HR_TARGET_PID || GetCurrentThreadId() != HR_TARGET_TID ||
        GetTickCount64() >= HR_DEADLINE || !verify_code(*before)) return;
    out->code = NativeBindingCode::invalid_context;
    if (!same_scene(*before, out->expected)) return;
    out->code = NativeBindingCode::invalid_request;
    constexpr bool shop = TA_BINDING_KIND == 35;
    constexpr std::uint32_t templateId = TA_BINDING_TEMPLATE_ID;
    if constexpr (!TA_BINDING_ENTITY_ID || !templateId || (templateId & 0xe0000000U) != 0x40000000U ||
        ((templateId >> 22) & 127) != (shop ? 15U : 11U)) return;
    std::uint32_t matches = 0;
    for (std::uint32_t i = 0; i < before->entityCaptured; ++i) {
        const auto& entity = before->entities[i];
        if (entity.id != TA_BINDING_ENTITY_ID) continue;
        constexpr auto required = GE_ID_READ | GE_CONTEXT_MATCH | GE_KEY_MATCH | GE_CONTEXT_READ;
        if ((entity.flags & required) != required || entity.dictionaryKey != entity.id ||
            entity.context != before->currentContext || !TemplatePointer(entity.owner)) return;
        ++matches;
    }
    if (matches != 1) return;
    using InitializeMetadata = void (__cdecl *)(std::uint32_t);
    const auto initialize = reinterpret_cast<InitializeMetadata>(before->moduleBase + 0x524250);
    // Exact groups used by resolver/attach/resource factory/reference factory.
    // Calling only the initializer does not invoke these constructors/factories.
    constexpr std::uint32_t groups[] = {TA_BINDING_USAGE_GROUPS, TA_REFERENCE_USAGE_GROUPS};
    for (auto group : groups) {
        out->metadataUsageInProgress = group; ++out->metadataCallsStarted;
        out->nativeCallAttempted = true; out->runtimeStateMayHaveChanged = true;
        initialize(group);
        ++out->metadataCallsCompleted; out->metadataUsageInProgress = 0;
    }
    out->code = NativeBindingCode::metadata_unavailable;
    constexpr std::uint32_t slots[] = {0x57dda88,0x57b1060,0x57b0058,0x57e9bd0,0x57e9bf0,0x57b3280,0x5812cf8,0x57af188};
    for (std::size_t i = 0; i < 8; ++i) {
        unsigned char prefix[16]{};
        if (!read_memory(nullptr, before->moduleBase + slots[i], &out->initializedClasses[i], 8) ||
            !TemplatePointer(out->initializedClasses[i]) ||
            !read_memory(nullptr, out->initializedClasses[i], prefix, sizeof(prefix))) return;
    }
    const auto base = before->moduleBase;
    std::uint64_t typeName = 0;
    std::int32_t typeNameLength = 0;
    constexpr char16_t expectedTypeName[] = u"ClientBeyondConfigReferenceEditData";
    char16_t observedTypeName[sizeof(expectedTypeName) / sizeof(expectedTypeName[0]) - 1]{};
    if (!read_memory(nullptr, base + 0x5a016f8, &typeName, sizeof(typeName)) || !TemplatePointer(typeName) ||
        !read_memory(nullptr, typeName + 0x10, &typeNameLength, sizeof(typeNameLength)) ||
        typeNameLength != static_cast<std::int32_t>(sizeof(observedTypeName) / sizeof(observedTypeName[0])) ||
        !read_memory(nullptr, typeName + 0x14, observedTypeName, sizeof(observedTypeName)) ||
        std::memcmp(observedTypeName, expectedTypeName, sizeof(observedTypeName))) return;
    const BindingActionReview review{HR_TARGET_PID, HR_TARGET_TID, HR_DEADLINE, &out->expected};
    const BindingActionRuntime runtime{GetCurrentProcessId(), GetCurrentThreadId(), GetTickCount64(), verify_code(*before)};
    const BindingActionCalls calls{
        reinterpret_cast<ge::component_attachment::AttachComponent>(base + 0x867c610), {
        nullptr, // Never use the old typed resource lookup for bag/shop templates.
        reinterpret_cast<ge::component_binding::AddShopEntry>(base + 0x8250bf0),
        reinterpret_cast<ge::component_binding::SetReference>(base + 0x8a3a760),
        reinterpret_cast<ge::component_binding::SetReference>(base + 0x10ed3110),
        reinterpret_cast<ge::component_binding::RefreshDependencies>(base + 0x82514f0),
        reinterpret_cast<ge::component_binding::RefreshDependencies>(base + 0x10ed3250),
        reinterpret_cast<ge::component_binding::CreateTypedReference>(base + 0x95f6410),
        reinterpret_cast<ge::component_binding::InitializeReferenceId>(base + 0x1013f9f0),
        reinterpret_cast<void*>(typeName)}, {
        reinterpret_cast<ge::component_edit::OpenTransaction>(base + 0xe827750),
        reinterpret_cast<ge::component_edit::SnapshotComponent>(base + 0x107abdf0),
        reinterpret_cast<ge::component_edit::NotifyComponent>(base + 0x9c26c70),
        reinterpret_cast<ge::component_edit::CloseTransaction>(base + 0xc7bab90)}, true};
    ExecuteBindingAction(before, review, runtime, {nullptr, read_memory}, calls,
        {TA_BINDING_ENTITY_ID, templateId, TA_BINDING_KIND}, &out->workspace, &out->action);
    out->code = NativeBindingCode::action_returned;
}
}
void ExecuteNativeBindingAction(const GameContextSnapshot* before, NativeBindingReceipt* out) noexcept {
    if (!before || !out) return;
    static_assert(std::is_trivially_copyable<NativeBindingReceipt>::value, "receipt byte reset");
    // No large aggregate temporary. Preserve BindResult's nonzero default:
    // zero means returned, whereas its value-initialized state is invalid.
    std::memset(out, 0, sizeof(*out));
    out->action.binding.code = ge::component_binding::BindCode::invalid_evidence;
    out->size = sizeof(*out); out->version = 2;
    out->code = NativeBindingCode::invalid_review;
    out->action.code = ge::templates::BindingActionCode::invalid_review;
    __try { execute(before, out); }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        out->sehCode = GetExceptionCode(); out->code = NativeBindingCode::native_exception;
        if (out->action.stage == ge::templates::BindingActionStage::attachment) {
            out->action.code = ge::templates::BindingActionCode::attachment_failed;
            if (out->action.attachment.attach_called)
                out->action.attachment.code = ge::component_attachment::AttachCode::call_exception;
        } else if (out->action.stage == ge::templates::BindingActionStage::binding) {
            out->action.code = ge::templates::BindingActionCode::binding_failed;
            if (out->action.binding.exceptionStage != ge::component_binding::BindStage::none)
                out->action.binding.code = ge::component_binding::BindCode::call_exception;
        } else if (out->action.stage == ge::templates::BindingActionStage::edit_begin || out->action.stage == ge::templates::BindingActionStage::edit_complete) {
            out->action.code = out->action.stage == ge::templates::BindingActionStage::edit_begin ?
                ge::templates::BindingActionCode::edit_begin_failed : ge::templates::BindingActionCode::edit_complete_failed;
            out->action.edit.code = ge::component_edit::Code::call_exception;
        }
    }
    recover_progress(out);
    __try { capture_after(before, out); }
    __except (EXCEPTION_EXECUTE_HANDLER) { out->readbackSehCode = GetExceptionCode(); }
}
