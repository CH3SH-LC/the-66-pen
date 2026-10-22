// Generalized kind-17 option-card installer. See GENERALIZED-TABS.md.
//
// Same reviewed native calls as native_tabs.cpp, driven by the compile-time parameter
// table (gt::kHosts) instead of the two hardcoded hosts and three hardcoded labels.
// Every address below is a GT_* macro baked by build_generalized.py; the file contains
// no RVA, slot or property literal at all.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "generalized_tabs.h"
#include <cstring>
#if HR_ACTION != 13 || !defined(TA_GENERALIZED_TABS_REVIEWED) || TA_GENERALIZED_TABS_REVIEWED != 1 || !GS_REVIEWED_ACTION_PROFILE
#error "Generalized option cards require HR_ACTION 13, TA_GENERALIZED_TABS_REVIEWED==1 and a reviewed action profile"
#endif

namespace {
using U = std::uint64_t;
using gt::RefuseCode;

// Bounded, structure-checked read from the game process; identical to
// native_tabs.cpp:11-22 (it is the reviewed reader, not a new one).
bool memory(void*, U at, void* out, std::size_t n) noexcept {
    if (!out || !n || at < 0x10000 || at >= 0x800000000000ULL || n > 0x800000000000ULL - at) return false;
    std::size_t done = 0;
    while (done < n) {
        MEMORY_BASIC_INFORMATION r{};
        const auto p = at + done;
        if (VirtualQuery(reinterpret_cast<void*>(p), &r, sizeof(r)) != sizeof(r) || r.State != MEM_COMMIT ||
            (r.Protect & (PAGE_NOACCESS | PAGE_GUARD))) return false;
        const auto left = r.RegionSize - static_cast<std::size_t>(p - reinterpret_cast<U>(r.BaseAddress));
        const auto part = n - done < left ? n - done : left;
        __try { std::memcpy(static_cast<unsigned char*>(out) + done, reinterpret_cast<void*>(p), part); }
        __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
        done += part;
    }
    return true;
}
template <class T> bool read(U p, T& v) { return memory(nullptr, p, &v, sizeof(v)); }
U ptr(U p) { U v = 0; return read(p, v) && v >= 0x10000 && v < 0x800000000000ULL ? v : 0; }

// Every refusal records a named code, the stage and (when known) the host/option, and
// moves the receipt out of the "not yet decided" state. status stays 0 only for a
// fully verified run.
bool refuse(gt::NativeGeneralizedTabsReceipt* o, RefuseCode code, std::uint32_t stage,
            std::uint32_t host = gt::kNoIndex, std::uint32_t option = gt::kNoIndex) noexcept {
    if (o->refuseCode == static_cast<std::uint32_t>(RefuseCode::none)) {
        o->refuseCode = static_cast<std::uint32_t>(code);
        o->refuseStage = stage;
        o->refuseHost = host;
        o->refuseOption = option;
    }
    if (host < gt::kMaxHosts) {
        gt::HostResult& r = o->hosts[host];
        r.refuseCode = static_cast<std::uint32_t>(code);
        r.refuseStage = stage;
        r.refuseOption = option;
    }
    if (o->status == 0 || o->status == 1) o->status = 3;
    return false;
}

// UTF-16 -> UTF-8 into a caller buffer, no allocation: the game string factory takes
// (bytes, length) exactly as native_tabs.cpp:104 passed its u8 literal. Lone
// surrogates and buffer overflow return 0, which becomes option_text_encode_failed.
std::size_t utf8_from_utf16(const char16_t* text, char* out, std::size_t capacity) noexcept {
    std::size_t n = 0;
    for (std::size_t i = 0; text[i] != 0; ++i) {
        std::uint32_t cp = text[i];
        if (cp >= 0xd800 && cp <= 0xdbff) {
            const std::uint32_t low = text[i + 1];
            if (low < 0xdc00 || low > 0xdfff) return 0;
            cp = 0x10000u + ((cp - 0xd800u) << 10) + (low - 0xdc00u);
            ++i;
        } else if (cp >= 0xdc00 && cp <= 0xdfff) {
            return 0;
        }
        char bytes[4];
        std::size_t k = 0;
        if (cp < 0x80u) {
            bytes[k++] = static_cast<char>(cp);
        } else if (cp < 0x800u) {
            bytes[k++] = static_cast<char>(0xc0u | (cp >> 6));
            bytes[k++] = static_cast<char>(0x80u | (cp & 0x3fu));
        } else if (cp < 0x10000u) {
            bytes[k++] = static_cast<char>(0xe0u | (cp >> 12));
            bytes[k++] = static_cast<char>(0x80u | ((cp >> 6) & 0x3fu));
            bytes[k++] = static_cast<char>(0x80u | (cp & 0x3fu));
        } else {
            bytes[k++] = static_cast<char>(0xf0u | (cp >> 18));
            bytes[k++] = static_cast<char>(0x80u | ((cp >> 12) & 0x3fu));
            bytes[k++] = static_cast<char>(0x80u | ((cp >> 6) & 0x3fu));
            bytes[k++] = static_cast<char>(0x80u | (cp & 0x3fu));
        }
        if (n + k + 1 > capacity) return 0;
        for (std::size_t j = 0; j < k; ++j) out[n++] = bytes[j];
    }
    if (!n || n + 1 > capacity) return 0;
    out[n] = 0;
    return n;
}

// The pinned code anchors and hotfix bytes are checked before anything is called, the
// same way native_tabs.cpp:25-34 did it. A mismatch is a named refusal, never a retry.
bool anchors(const GameContextSnapshot& s, gt::NativeGeneralizedTabsReceipt* o) {
    if (s.moduleBase != reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe")) ||
        s.peTimestamp != HR_GAME_TIMESTAMP || s.peImageSize != HR_GAME_IMAGE_SIZE)
        return refuse(o, RefuseCode::module_or_build_mismatch, gt::stage::build_anchors);
    constexpr std::uint32_t rvas[] = {GT_CODE_RVAS};
    constexpr unsigned char expected[][32] = {GT_CODE_BYTES};
    unsigned char actual[32]{};
    for (std::size_t i = 0; i < sizeof(rvas) / sizeof(rvas[0]); ++i) {
        if (!memory(nullptr, s.moduleBase + rvas[i], actual, 32) || std::memcmp(actual, expected[i], 32)) {
            o->failedRva = rvas[i];
            return refuse(o, RefuseCode::build_anchor_mismatch, gt::stage::build_anchors);
        }
    }
    constexpr std::uint32_t flags[] = {GS_PROFILE_HOTFIX_RVAS, GT_HOTFIX_RVAS};
    for (auto r : flags) {
        unsigned char v = 255;
        if (!read(s.moduleBase + r, v) || v) {
            o->failedRva = r;
            o->failedValue = v;
            return refuse(o, RefuseCode::hotfix_active, gt::stage::build_anchors);
        }
    }
    return true;
}

// Scene identity against the declared level. Both snapshots must carry the level
// observation and the *declared* level id: the level is a parameter, but never blind.
// `onMismatch` distinguishes "the live scene is not the compiled baseline"
// (expected_scene_mismatch) from "the scene changed while installing" (scene_changed).
bool scene(const GameContextSnapshot& a, const GameContextSnapshot& b, std::uint32_t levelId,
           RefuseCode onMismatch, std::uint32_t stage, gt::NativeGeneralizedTabsReceipt* o) {
    if (b.structSize != sizeof(GameContextSnapshot) || b.status != GS_OK)
        return refuse(o, RefuseCode::snapshot_not_ok, stage);
    if ((b.flags & GS_LEVEL_OBSERVED) == 0 || (a.flags & GS_LEVEL_OBSERVED) == 0)
        return refuse(o, RefuseCode::level_not_observed, stage);
    if (b.reserved != levelId || a.reserved != levelId)
        return refuse(o, RefuseCode::level_mismatch, stage);
    if ((b.flags & gt::kRequiredSnapshotFlags) != gt::kRequiredSnapshotFlags)
        return refuse(o, RefuseCode::snapshot_flags_incomplete, stage);
    if (b.entityRejected || b.entityCaptured != b.entityValidEntries || a.entityCaptured != b.entityCaptured ||
        b.entityCaptured > kMaxEntities)
        return refuse(o, onMismatch, stage);
    if (a.currentContext != b.currentContext || a.global != b.global || a.moduleBase != b.moduleBase ||
        a.entityDictionary != b.entityDictionary || a.contextDictionary != b.contextDictionary ||
        a.entityVersionBefore != b.entityVersionBefore || a.entityVersionAfter != b.entityVersionAfter)
        return refuse(o, onMismatch, stage);
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i];
        const auto& y = b.entities[i];
        if (x.id != y.id || x.owner != y.owner || x.config != y.config || x.context != y.context ||
            x.configId != y.configId || x.dictionaryKey != y.dictionaryKey)
            return refuse(o, onMismatch, stage);
    }
    return true;
}

// Independent list reader, identical to native_tabs.cpp:45-47: it checks the counted
// length, the allocated capacity and the 64-element ceiling before copying.
bool list(U listPointer, std::uint32_t expected, U* items) {
    std::int32_t n = -1;
    U cap = 0, array = ptr(listPointer + 0x10);
    if (!array || !read(listPointer + 0x18, n) || n != static_cast<std::int32_t>(expected) ||
        !read(array + 0x18, cap) || cap < expected || cap > 64) return false;
    return memory(nullptr, array + 0x20, items, expected * sizeof(U));
}

// Collider readback: exactly one collider, sphere shape, the declared radius.
RefuseCode captureCollider(U base, gt::HostResult& r) noexcept {
    U coll[1]{};
    r.colliderCount = 1;
    if (!list(ptr(r.config + 0x30), 1, coll)) return RefuseCode::collider_list_shape_mismatch;
    r.collider = coll[0];
    if (ptr(r.collider) != ptr(base + GT_COLLIDER_SLOT)) return RefuseCode::collider_class_mismatch;
    if (!read(r.collider + 0x5c, r.colliderShape) || r.colliderShape != static_cast<std::int32_t>(GT_COLLIDER_SHAPE))
        return RefuseCode::collider_shape_mismatch;
    r.sphere = ptr(r.collider + 0x48);
    if (!r.sphere) return RefuseCode::collider_sphere_missing;
    if (!read(r.sphere + 0x20, r.radius) || r.radius != GT_RADIUS) return RefuseCode::radius_mismatch;
    r.radiusVerified = 1;
    return RefuseCode::none;
}

// Option readback with the UTF-16 comparison: every row is compared unit by unit
// against the compile-time Chinese caption, never against what was just written.
RefuseCode captureOptions(U base, gt::HostResult& r, const gt::HostSpec& spec) noexcept {
    U opts[gt::kMaxOptionsPerHost]{};
    r.optionCount = spec.optionCount;
    if (!list(ptr(r.config + 0x38), spec.optionCount, opts)) return RefuseCode::option_list_shape_mismatch;
    r.textVerified = 1;
    for (std::uint32_t i = 0; i < spec.optionCount; ++i) {
        gt::OptionRow& row = r.options[i];
        row.pointer = opts[i];
        row.klass = ptr(row.pointer);
        row.expectedIndex = spec.options[i].index;
        row.expectedEnabled = spec.options[i].enabled != 0u ? 1u : 0u;
        row.mismatchUnit = gt::kNoIndex;
        r.refuseOption = i;
        if (row.klass != ptr(base + GT_OPTION_SLOT)) return RefuseCode::option_class_mismatch;
        const U text = ptr(row.pointer + 0x30);
        if (!read(row.pointer + 0x40, row.index) || !read(row.pointer + 0x4c, row.sort) ||
            !read(row.pointer + 0x48, row.icon) || !read(row.pointer + 0x50, row.filter) ||
            !read(row.pointer + 0x56, row.activeOrEnabledState) || !read(row.pointer + 0x54, row.rowEnabledByte) ||
            !text || !read(text + 0x10, row.textLength) || row.textLength <= 0 ||
            row.textLength >= static_cast<std::int32_t>(gt::kMaxTextUnits) ||
            !memory(nullptr, text + 0x14, row.text, static_cast<std::size_t>(row.textLength) * sizeof(char16_t)))
            return RefuseCode::option_row_unreadable;
        row.indexMatched = row.index == row.expectedIndex ? 1u : 0u;
        row.enabledMatched = static_cast<std::uint32_t>(row.activeOrEnabledState) == row.expectedEnabled ? 1u : 0u;
        const char16_t* expected = spec.options[i].text;
        std::uint32_t units = 0;
        while (units < gt::kMaxTextUnits && expected[units] != 0) ++units;
        row.expectedTextUnits = units;
        std::uint32_t mismatch = gt::kNoIndex;
        for (std::uint32_t u = 0; u < units; ++u) {
            if (u >= static_cast<std::uint32_t>(row.textLength) || row.text[u] != expected[u]) { mismatch = u; break; }
        }
        if (mismatch == gt::kNoIndex && static_cast<std::uint32_t>(row.textLength) != units) mismatch = units;
        row.mismatchUnit = mismatch;
        row.textMatched = mismatch == gt::kNoIndex ? 1u : 0u;
        if (!row.indexMatched) return RefuseCode::option_index_mismatch;
        if (!row.enabledMatched) return RefuseCode::option_enabled_mismatch;
        if (!row.textMatched) { r.textVerified = 0; return RefuseCode::option_text_mismatch; }
    }
    r.refuseOption = gt::kNoIndex;
    return RefuseCode::none;
}

bool install(const GameContextSnapshot& s, gt::NativeGeneralizedTabsReceipt* o, std::uint32_t hostIndex) {
    const std::uint32_t stage = gt::stage::host_install + hostIndex;
    gt::HostResult& r = o->hosts[hostIndex];
    const gt::HostSpec& spec = gt::kHosts[hostIndex];
    const U base = s.moduleBase;
    r.status = 10;
    if (!r.owner) return refuse(o, RefuseCode::owner_unreadable, stage, hostIndex);
    const ge::templates::TemplateReadSource source{nullptr, memory};
    const ge::component_attachment::AttachmentEvidence evidence{
        r.owner, r.ownerClass, ptr(base + GT_WRAPPER_SLOT), ptr(base + GT_CLASS_SLOT),
        static_cast<std::int32_t>(GT_KIND), true};
    ge::component_attachment::EnsureComponentAttached(
        source, reinterpret_cast<ge::component_attachment::AttachComponent>(base + GT_ATTACH_RVA),
        evidence, &r.attachmentWork, &r.attachment);
    // An existing component is not overwritten: the host scan already refused that
    // case, and this branch refuses it again with the attachment receipt as evidence.
    // A later run needs an explicit recovery based on that receipt, never a replay.
    if (r.attachment.code == ge::component_attachment::AttachCode::existing)
        return refuse(o, RefuseCode::component_already_present, stage, hostIndex);
    if (r.attachment.code != ge::component_attachment::AttachCode::attached_verified)
        return refuse(o, RefuseCode::attach_not_verified, stage, hostIndex);
    r.config = r.attachment.component.config;
    r.componentKind = static_cast<std::uint32_t>(r.attachment.component.kind);
    if (r.componentKind != static_cast<std::uint32_t>(GT_KIND))
        return refuse(o, RefuseCode::component_kind_mismatch, stage, hostIndex);
    r.beforeComponents = r.attachmentWork.before.count;
    r.afterComponents = r.attachmentWork.after.count;
    const ge::component_edit::Evidence e{
        base, s.global, r.owner, r.attachment.component.wrapper, r.config,
        static_cast<std::int32_t>(GT_KIND), true};
    const ge::component_edit::NativeCalls calls{
        reinterpret_cast<ge::component_edit::OpenTransaction>(base + GT_EDIT_OPEN_RVA),
        reinterpret_cast<ge::component_edit::SnapshotComponent>(base + GT_EDIT_SNAPSHOT_RVA),
        reinterpret_cast<ge::component_edit::NotifyComponent>(base + GT_EDIT_NOTIFY_RVA),
        reinterpret_cast<ge::component_edit::CloseTransaction>(base + GT_EDIT_CLOSE_RVA)};
    r.status = 11;
    ge::component_edit::BeginComponentEdit(source, calls, e, &r.edit);
    if (r.edit.code != ge::component_edit::Code::snapshot_ready)
        return refuse(o, RefuseCode::edit_begin_failed, stage, hostIndex);

    using SetInt = void (*)(void*, std::uint32_t, std::int32_t);
    using SetBool = void (*)(void*, std::uint32_t, bool);
    using SetText = void (*)(void*, std::uint32_t, void*);
    using SetFloat = void (*)(void*, std::uint32_t, float);
    using String = void* (*)(const char*, std::int32_t);
    using Factory = void* (*)(void*);
    using Add = void (*)(void*, void*, void*);
    const auto setIndex = reinterpret_cast<void (*)(void*, int)>(base + GT_SET_INDEX_RVA);
    U optionList = ptr(r.config + 0x38);
    U colliders[1]{};
    U options[gt::kMaxOptionsPerHost]{};
    r.status = 12;
    // A freshly attached component starts with exactly one card (native_tabs.cpp:81);
    // the table's remaining cards are created and appended in table order.
    if (!optionList || !list(optionList, 1, options)) return refuse(o, RefuseCode::option_list_shape_mismatch, stage, hostIndex);
    if (!list(ptr(r.config + 0x30), 1, colliders)) return refuse(o, RefuseCode::collider_list_shape_mismatch, stage, hostIndex);
    for (std::uint32_t i = 0; i < spec.optionCount; ++i) {
        if (i) {
            const U method = ptr(base + GT_OPTION_LIST_ADD_METHOD_SLOT);
            if (!method || ptr(method) != ptr(optionList))
                return refuse(o, RefuseCode::option_list_add_method_mismatch, stage, hostIndex, i);
            const U factoryArg = ptr(base + GT_OPTION_FACTORY_SLOT);
            if (!factoryArg) return refuse(o, RefuseCode::option_factory_failed, stage, hostIndex, i);
            options[i] = reinterpret_cast<U>(reinterpret_cast<Factory>(base + GT_OPTION_FACTORY_RVA)(
                reinterpret_cast<void*>(factoryArg)));
            if (!options[i] || ptr(options[i]) != ptr(base + GT_OPTION_SLOT))
                return refuse(o, RefuseCode::option_factory_failed, stage, hostIndex, i);
            // The exact closed List<Option>.Add MethodInfo is used in the component
            // initializer; the same call also increments the list version
            // (native_tabs.cpp:97-99).
            reinterpret_cast<Add>(base + GT_OPTION_LIST_ADD_RVA)(
                reinterpret_cast<void*>(optionList), reinterpret_cast<void*>(options[i]),
                reinterpret_cast<void*>(method));
        }
        if (ptr(options[i]) != ptr(base + GT_OPTION_SLOT))
            return refuse(o, RefuseCode::option_class_mismatch, stage, hostIndex, i);
        auto card = reinterpret_cast<void*>(options[i]);
        setIndex(card, static_cast<int>(spec.options[i].index));
        // native_tabs.cpp:103 wrote the same ordinal to property GT_INDEX_PROPERTY; the
        // readback below proves the visible index, not this property independently.
        reinterpret_cast<SetInt>(base + GT_SET_INT_RVA)(
            card, GT_INDEX_PROPERTY, static_cast<std::int32_t>(spec.options[i].index));
        char utf8[gt::kMaxTextUnits * 4]{};
        const std::size_t bytes = utf8_from_utf16(spec.options[i].text, utf8, sizeof(utf8));
        if (!bytes) return refuse(o, RefuseCode::option_text_encode_failed, stage, hostIndex, i);
        auto text = reinterpret_cast<String>(base + GT_STRING_FACTORY_RVA)(utf8, static_cast<std::int32_t>(bytes));
        if (!text) return refuse(o, RefuseCode::option_text_alloc_failed, stage, hostIndex, i);
        reinterpret_cast<SetText>(base + GT_SET_TEXT_RVA)(card, GT_CAPTION_PROPERTY, text);
        reinterpret_cast<SetBool>(base + GT_SET_BOOL_RVA)(
            card, GT_INITIAL_ACTIVE_PROPERTY, spec.options[i].enabled != 0u);
        reinterpret_cast<void (*)(void*)>(base + GT_TOUCH_RVA)(card);
    }
    auto collider = reinterpret_cast<void*>(colliders[0]);
    if (ptr(colliders[0]) != ptr(base + GT_COLLIDER_SLOT))
        return refuse(o, RefuseCode::collider_class_mismatch, stage, hostIndex);
    // 2026-10-19: 与历史可用动作一致——collider 形状用 0x12ce23f0 的 SetInt 写。
    reinterpret_cast<SetInt>(base + GT_SET_INT_COLLIDER_RVA)(
        collider, GT_COLLIDER_SHAPE_PROPERTY, static_cast<std::int32_t>(GT_COLLIDER_SHAPE));
    auto sphere = reinterpret_cast<void*>(ptr(colliders[0] + 0x48));
    if (!sphere) return refuse(o, RefuseCode::collider_sphere_missing, stage, hostIndex);
    reinterpret_cast<SetFloat>(base + GT_SET_FLOAT_RVA)(sphere, GT_COLLIDER_RADIUS_PROPERTY, GT_RADIUS);

    r.status = 13;
    RefuseCode verdict = captureCollider(base, r);
    if (verdict != RefuseCode::none) return refuse(o, verdict, stage, hostIndex);
    verdict = captureOptions(base, r, spec);
    if (verdict != RefuseCode::none) return refuse(o, verdict, stage, hostIndex, r.refuseOption);
    r.readbackVerified = 1;
    r.status = 14;
    ge::component_edit::CompleteComponentEdit(source, calls, e, &r.edit);
    if (r.edit.code != ge::component_edit::Code::complete)
        return refuse(o, RefuseCode::edit_complete_failed, stage, hostIndex);

    // Independent read-only readback of the attached component kind: the component set
    // is re-captured after the commit and the row must carry the declared kind, the
    // same config pointer and the wrapper/config classes the attachment used.
    r.status = 15;
    ge::component_attachment::CaptureComponents(source, r.owner, &r.attachmentWork.capture, &r.kindReadback);
    if (r.kindReadback.code != ge::component_attachment::CaptureCode::complete)
        return refuse(o, RefuseCode::kind_readback_failed, stage, hostIndex);
    for (std::uint32_t j = 0; j < r.kindReadback.count; ++j) {
        const auto& row = r.kindReadback.rows[j];
        if (row.kind != static_cast<std::int32_t>(GT_KIND)) continue;
        ++r.kindRowsFound;
        r.kindRowIndex = j;
        r.kindRowEnabled = row.enabled ? 1u : 0u;
        if (row.config == r.config && row.wrapper_class == ptr(base + GT_WRAPPER_SLOT) &&
            row.config_class == ptr(base + GT_CLASS_SLOT)) r.kindRowMatchesConfig = 1;
    }
    if (r.kindRowsFound != 1 || !r.kindRowMatchesConfig)
        return refuse(o, RefuseCode::component_kind_readback_mismatch, stage, hostIndex);
    r.status = 0;
    return true;
}

void execute(const GameContextSnapshot* before, gt::NativeGeneralizedTabsReceipt* o) {
    o->status = 1;
    o->stage = gt::stage::entry;
    o->hostCount = gt::kHostCount;
    o->kind = static_cast<std::uint32_t>(GT_KIND);
    o->radius = GT_RADIUS;
    o->expectedLevelId = static_cast<std::uint32_t>(GT_LEVEL_ID);
    std::memcpy(&o->expectedScene, GT_EXPECTED_SNAPSHOT, sizeof(o->expectedScene));
    // The table is validated at compile time; this repeats the check against the
    // builder's declared count so a hand-edited header cannot silently disagree.
    if (!gt::HostTableWellFormed() || gt::kHostCount != static_cast<std::uint32_t>(GT_HOST_COUNT) ||
        static_cast<std::uint32_t>(GT_LEVEL_ID) == 0)
        return static_cast<void>(refuse(o, RefuseCode::invalid_parameter_table, gt::stage::entry));
    if (GetCurrentProcessId() != HR_TARGET_PID || GetCurrentThreadId() != HR_TARGET_TID ||
        GetTickCount64() >= HR_DEADLINE)
        return static_cast<void>(refuse(o, RefuseCode::entry_guard_failed, gt::stage::entry));
    o->stage = gt::stage::build_anchors;
    if (!anchors(*before, o)) return;
    o->stage = gt::stage::scene_declared;
    o->levelIdBefore = before->reserved;
    if (!scene(*before, o->expectedScene, static_cast<std::uint32_t>(GT_LEVEL_ID),
               RefuseCode::expected_scene_mismatch, gt::stage::scene_declared, o)) return;
    o->stage = gt::stage::host_scan;
    for (std::uint32_t i = 0; i < gt::kHostCount; ++i) {
        gt::HostResult& r = o->hosts[i];
        const gt::HostSpec& spec = gt::kHosts[i];
        r.entityId = static_cast<std::uint32_t>(spec.entityId);
        r.optionCount = spec.optionCount;
        r.status = 1;
        std::uint32_t found = 0;
        for (std::uint32_t j = 0; j < before->entityCaptured; ++j) {
            if (before->entities[j].id == r.entityId) {
                r.owner = before->entities[j].owner;
                ++found;
            }
        }
        if (found != 1 || !r.owner) return static_cast<void>(refuse(o, RefuseCode::host_entity_not_unique, gt::stage::host_scan, i));
        r.ownerClass = ptr(r.owner);
        if (!r.ownerClass) return static_cast<void>(refuse(o, RefuseCode::owner_unreadable, gt::stage::host_scan, i));
        ge::component_attachment::CaptureComponents(
            {nullptr, memory}, r.owner, &r.attachmentWork.capture, &r.kindReadback);
        if (r.kindReadback.code != ge::component_attachment::CaptureCode::complete)
            return static_cast<void>(refuse(o, RefuseCode::component_capture_failed, gt::stage::host_scan, i));
        for (std::uint32_t j = 0; j < r.kindReadback.count; ++j)
            if (r.kindReadback.rows[j].kind == static_cast<std::int32_t>(GT_KIND))
                return static_cast<void>(refuse(o, RefuseCode::component_already_present, gt::stage::host_scan, i));
    }
    // The usage-group metadata bootstrap, identical to native_tabs.cpp:135-136. It is
    // counted in the receipt (metadataCalls) so a reader can see it happened.
    o->stage = gt::stage::metadata_bootstrap;
    constexpr std::uint32_t groups[] = {GT_USAGE_GROUPS};
    for (auto group : groups) {
        o->attempted = 1;
        reinterpret_cast<void (*)(unsigned)>(before->moduleBase + GT_METADATA_GROUP_RVA)(group);
        ++o->metadataCalls;
    }
    for (std::uint32_t i = 0; i < gt::kHostCount; ++i) {
        o->stage = gt::stage::host_install + i;
        if (!install(*before, o, i)) return;
        ++o->completedHosts;
    }
    CaptureGameContextSnapshot(&o->afterScene);
    o->stage = gt::stage::scene_after;
    o->levelIdAfter = o->afterScene.reserved;
    if (!scene(*before, o->afterScene, static_cast<std::uint32_t>(GT_LEVEL_ID),
               RefuseCode::scene_changed, gt::stage::scene_after, o)) return;
    o->sceneUnchanged = 1;
    o->stage = 0;
    o->status = 0;
}
} // namespace

void ExecuteGeneralizedTabAction(const GameContextSnapshot* s, gt::NativeGeneralizedTabsReceipt* o) noexcept {
    if (!s || !o) return;
    std::memset(o, 0, sizeof(*o));
    o->size = sizeof(*o);
    o->version = 1;
    o->refuseCode = static_cast<std::uint32_t>(gt::RefuseCode::none);
    o->refuseHost = gt::kNoIndex;
    o->refuseOption = gt::kNoIndex;
    __try { execute(s, o); }
    __except (EXCEPTION_EXECUTE_HANDLER) {
        o->sehCode = GetExceptionCode();
        o->status = 2;
        if (o->refuseCode == static_cast<std::uint32_t>(gt::RefuseCode::none)) {
            o->refuseCode = static_cast<std::uint32_t>(gt::RefuseCode::unhandled_exception);
            o->refuseStage = o->stage;
        }
    }
}
