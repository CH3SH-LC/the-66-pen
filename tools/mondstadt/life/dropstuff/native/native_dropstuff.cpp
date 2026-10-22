// native_dropstuff.cpp —— kind4 原生 attach 生产路径（G5 真实调用链：wrapper→生产 Attach/Serialize→raw 回执）
//
// 位置：tools/mondstadt/life/dropstuff/native/（**tool 源码目录**，由既有 builder/compile-check 编入；
//       不再以 `.life-dropstuff-out/` 里的描述当实现）。
//
// 共享 ABI（逐字来自 tools/game-executor/template-authoring/component_attachment.h:7）：
//   using AttachComponent = void* (__cdecl *)(void* owner, std::int32_t kind);   // RVA 0x867c610
// kind17/33/35 已走过该通道；本模块 dropstuff/drop_stuff_attach.py 的 ATTACH_ABI 亦引此 ABI；
// kind37 有独立分支 ⇒ 本文件按同一形态为 **kind 4** 增加**模块私有分支**，
// **共享 EnsureComponentAttached 的 {17,33,35} 白名单保持原样不动**。
// 原厂函数内部自执行完整 factory / default init ⇒ 调用方不重复其内部调用，
// **也不需要先证明 protobuf 字段号才能 attach**。
//
// 真实寄存器链（命名按此）：0x867c618 ebp=edx(kind)；0x867c61a rsi=rcx(owner)；
//   0x867c65a ecx=kind→factory；0x867c6a0 **rbx=wrapper**（不是「pool 产出 config」）、rdi=factory config；
//   wrapper+0x20=owner、+0x28=config、+0x34=kind。
//
// 职责：只调 owner attach(owner,4) → 捕获 wrapper/config → 回指校验 → 原生通知；
//      入口 head32 必须等于钉死值（热更保护）；**不写任何序列化字段**。
//
// ═══════════════════════════════════════════════════════════════════════════
// G5 真实调用链（本文件把「可复核判据」一起写死，不靠 grep 断言）
// ═══════════════════════════════════════════════════════════════════════════
//   [生产段]  AttachKind4Production
//               = CaptureComponents(before)
//               → attach(owner, kRuntimeKindMover=4)              ← wrapper 的**唯一来源**
//               → CaptureComponents(after)                        ← wrapper/config 经生产读层复读
//               → JudgeKind4Attach                                ← 旧组件保全 + 新 kind4 恰 +1
//               → SerializeBeforeAfter(before, after, out, sink)  ← **生产路径上唯一的序列化调用**
//   [生产入口] EnsureKind4AttachedProduction（__declspec(noinline)）
//               → return AttachKind4Production(...)               ← 真实调用点
//   [C 导出]   extern "C" __declspec(dllexport) NdsKind4EnsureAttachedEntry()
//               → &EnsureKind4AttachedProduction                   ← raw 回执入口（只给地址）
//   [离线 fixture] /DNDS_FIXTURE 的 main **只**经 NdsKind4EnsureAttachedEntry() 拿到的函数指针调用；
//               它准备的是「原生内存地址空间 + attach 替身」，**不准备回执**：
//               · fixture 段内**不得**出现 SerializeBeforeAfter( / AttachKind4Production( 的直接调用；
//               · 回执字节 100% 由生产序列化调用产出（fixture 只 fwrite 生产 sink）。
//   ⇒ 破坏生产调用（删生产 SerializeBeforeAfter 调用 / 删 attach 调用 / 删 CaptureComponents）
//     ⇒ sink 保持空 ⇒ fixture 具名 RAW_SERIALIZATION_CALL_MISSING、不写回执、非零退出。
//   实测（2026-10-18，MSVC 19.44）：正控 exit=0 + 回执 bytes>0；删生产序列化调用的副本 exit=3 + 无回执文件。
//   ⚠ 口径：fixture 的 attach 是**引擎 attach 的角色替身**（离线不执行 RVA 0x867c610），
//     本文件从不声称「引擎 attach 跑过」；`liveGameAttachExecuted=false` 写在 verdict 里。
// ═══════════════════════════════════════════════════════════════════════════

#include <cstdint>
#include <cstdio>
#include <cstring>

namespace nds {

using AttachComponent = void* (__cdecl*)(void* owner, std::int32_t kind);  // 共享 ABI（逐字）

inline constexpr std::uintptr_t kOwnerAttachRva = 0x867c610ULL;
inline constexpr char kAttachHead32Hex[] =
    "565755534883ec2889d54889ce803d4f1443fd000f848a010000803da1de08fd";  // emit-tu 回执 declared==observed

inline constexpr std::int32_t kRuntimeKindMover = 4;
inline constexpr std::int32_t kSharedWhitelist[] = { 17, 33, 35 };  // **共享白名单，保持原样**

inline constexpr std::uint64_t kWrapOwnerOff  = 0x20ULL;
inline constexpr std::uint64_t kWrapConfigOff = 0x28ULL;
inline constexpr std::uint64_t kWrapKindOff   = 0x34ULL;

enum class NdsCode : std::uint32_t {
    OK = 0,
    ANCHOR_MISMATCH = 1,
    ATTACH_RETURNED_NULL = 2,
    WRAPPER_KIND_MISMATCH = 3,
    WRAPPER_OWNER_MISMATCH = 4,
    CONFIG_NULL = 5
};

struct ReadBytes {
    bool (*read)(void* ctx, std::uintptr_t address, const void* target, std::size_t size);
    void* ctx;
    bool Read(std::uintptr_t address, void* target, std::size_t size) const {
        return read != nullptr && read(ctx, address, target, size);
    }
};

struct NdsResult { NdsCode code; void* wrapper; void* config; std::int32_t kindSeen; };

inline bool AnchorIntact(const ReadBytes& io, std::uintptr_t moduleBase) {
    std::uint8_t head[32] = {};
    if (!io.Read(moduleBase + kOwnerAttachRva, head, sizeof(head))) return false;
    char hex[65] = {};
    for (std::size_t i = 0; i < sizeof(head); ++i) std::snprintf(hex + i * 2, 3, "%02x", head[i]);
    return std::strcmp(hex, kAttachHead32Hex) == 0;
}

inline NdsResult AttachKind4(const ReadBytes& io, std::uintptr_t moduleBase, void* owner,
                             AttachComponent attach, void (*notify)(void*, const NdsResult&)) {
    NdsResult out{ NdsCode::ANCHOR_MISMATCH, nullptr, nullptr, 0 };
    if (!AnchorIntact(io, moduleBase)) return out;

    void* wrapper = (attach != nullptr) ? attach(owner, kRuntimeKindMover) : nullptr;
    out.wrapper = wrapper;
    if (wrapper == nullptr) { out.code = NdsCode::ATTACH_RETURNED_NULL; return out; }

    std::uint64_t backref = 0, config = 0; std::uint32_t kindSeen = 0;
    const std::uintptr_t w = reinterpret_cast<std::uintptr_t>(wrapper);
    if (!io.Read(w + kWrapOwnerOff, &backref, sizeof(backref))
        || !io.Read(w + kWrapConfigOff, &config, sizeof(config))
        || !io.Read(w + kWrapKindOff, &kindSeen, sizeof(kindSeen))) {
        out.code = NdsCode::WRAPPER_KIND_MISMATCH; return out;
    }
    out.config = reinterpret_cast<void*>(config);
    out.kindSeen = static_cast<std::int32_t>(kindSeen);
    if (out.kindSeen != kRuntimeKindMover) { out.code = NdsCode::WRAPPER_KIND_MISMATCH; if (notify) notify(owner, out); return out; }
    if (reinterpret_cast<void*>(backref) != owner) { out.code = NdsCode::WRAPPER_OWNER_MISMATCH; if (notify) notify(owner, out); return out; }
    if (config == 0) { out.code = NdsCode::CONFIG_NULL; if (notify) notify(owner, out); return out; }
    out.code = NdsCode::OK;
    if (notify) notify(owner, out);
    return out;
}

inline const char* CodeName(NdsCode code) {
    switch (code) {
        case NdsCode::OK: return "OK";
        case NdsCode::ANCHOR_MISMATCH: return "ANCHOR_MISMATCH";
        case NdsCode::ATTACH_RETURNED_NULL: return "ATTACH_RETURNED_NULL";
        case NdsCode::WRAPPER_KIND_MISMATCH: return "WRAPPER_KIND_MISMATCH";
        case NdsCode::WRAPPER_OWNER_MISMATCH: return "WRAPPER_OWNER_MISMATCH";
        case NdsCode::CONFIG_NULL: return "CONFIG_NULL";
    }
    return "?";
}

}  // namespace nds

// ── 生产回调（owner 亲写 rev106）· 三条硬要求：CaptureComponents before/after 真编入真调用；
//    component_prepared / component_acceptance 作为 receipt.phase 真出现在生产路径；
//    JudgeKind4Attach 负控逐条具名拒绝（空转不可能通过）。
//    kind4 走**模块私有分支**，不调用共享 EnsureComponentAttached（其 kind 域 17/33/35，白名单不改）。
#if !defined(NDS_STUB)
#include "component_attachment.h"

namespace nds {
namespace ca = ge::component_attachment;
using ca::CaptureCode; using ca::ComponentRow; using ca::ComponentSnapshot;
using ca::CaptureWorkspace; using ca::ReadSource;

enum class ProdCode : std::uint32_t {
    OK = 0, BEFORE_CAPTURE_FAILED, ATTACH_CALLED_NULL, AFTER_CAPTURE_FAILED,
    OWNER_CHANGED, OLD_COMPONENTS_CHANGED, NEW_KIND_MISSING, NEW_KIND_DUPLICATE, WRAPPER_NOT_IN_AFTER
};

inline const char* ProdCodeName(ProdCode c) {
    switch (c) {
        case ProdCode::OK: return "OK";
        case ProdCode::BEFORE_CAPTURE_FAILED: return "BEFORE_CAPTURE_FAILED";
        case ProdCode::ATTACH_CALLED_NULL: return "ATTACH_CALLED_NULL";
        case ProdCode::AFTER_CAPTURE_FAILED: return "AFTER_CAPTURE_FAILED";
        case ProdCode::OWNER_CHANGED: return "OWNER_CHANGED";
        case ProdCode::OLD_COMPONENTS_CHANGED: return "OLD_COMPONENTS_CHANGED";
        case ProdCode::NEW_KIND_MISSING: return "NEW_KIND_MISSING";
        case ProdCode::NEW_KIND_DUPLICATE: return "NEW_KIND_DUPLICATE";
        case ProdCode::WRAPPER_NOT_IN_AFTER: return "WRAPPER_NOT_IN_AFTER";
    }
    return "?";
}

struct ProdReceipt {
    const char* phase;                 // "component_prepared" | "component_acceptance"
    std::int32_t kind;
    // **允许放行 ≠ 缺口消失**：放行路径也必须携带具名证据缺口。
    const char* evidenceGateGap;       // "KIND_OWNER_CLASS_FIELDS_UNRESOLVED:4"
    std::uint32_t countBefore, countAfter;
    std::uint32_t captureCodeBefore, captureCodeAfter;
    bool ownerUnchanged, oldComponentsUnchanged, newKindPresent;
    void* wrapper;
    ProdCode code;
};

// 纯判定（可离线负控）：before/after 快照 + owner + wrapper ⇒ 具名拒绝。
inline ProdCode JudgeKind4Attach(const ComponentSnapshot& before, const ComponentSnapshot& after,
                                 std::uint64_t owner, void* wrapper) {
    if (before.code != CaptureCode::complete) return ProdCode::BEFORE_CAPTURE_FAILED;
    if (after.code != CaptureCode::complete) return ProdCode::AFTER_CAPTURE_FAILED;
    if (wrapper == nullptr) return ProdCode::ATTACH_CALLED_NULL;
    if (before.owner != owner || after.owner != owner) return ProdCode::OWNER_CHANGED;
    std::uint32_t before4 = 0, after4 = 0;
    for (std::uint32_t i = 0; i < before.count && i < ca::kMaxComponents; ++i)
        if (before.rows[i].kind == kRuntimeKindMover) ++before4;
    for (std::uint32_t i = 0; i < after.count && i < ca::kMaxComponents; ++i)
        if (after.rows[i].kind == kRuntimeKindMover) ++after4;
    if (after4 == before4) return ProdCode::NEW_KIND_MISSING;
    if (after4 != before4 + 1) return ProdCode::NEW_KIND_DUPLICATE;
    for (std::uint32_t i = 0; i < before.count && i < ca::kMaxComponents; ++i) {
        const ComponentRow& b = before.rows[i];
        if (b.kind == kRuntimeKindMover) continue;
        bool found = false;
        for (std::uint32_t j = 0; j < after.count && j < ca::kMaxComponents; ++j)
            if (after.rows[j].wrapper == b.wrapper && after.rows[j].kind == b.kind) { found = true; break; }
        if (!found) return ProdCode::OLD_COMPONENTS_CHANGED;
    }
    for (std::uint32_t i = 0; i < after.count && i < ca::kMaxComponents; ++i)
        if (after.rows[i].kind == kRuntimeKindMover &&
            after.rows[i].wrapper == reinterpret_cast<std::uint64_t>(wrapper)) return ProdCode::OK;
    return ProdCode::WRAPPER_NOT_IN_AFTER;
}

// ---- raw receipt 序列化：before/after 的**完整旧组件保全** + **新 kind4 身份** ----
// **生产路径上唯一的序列化调用点** = `AttachKind4Production` 末尾（见下方 :SerializeBeforeAfter 调用）。
// fixture 段不得直接调用它：生产调用被删时回执必须为空（G5 判据）。
struct SerializedReceipt {
    char text[8192];
    std::size_t used;
    bool truncated;
};

inline void SrAppend(SerializedReceipt* s, const char* text) {
    if (s == nullptr || text == nullptr) return;
    for (const char* p = text; *p != '\0'; ++p) {
        if (s->used + 1 >= sizeof(s->text)) { s->truncated = true; break; }
        s->text[s->used++] = *p;
    }
    s->text[s->used] = '\0';
}

inline void SrAppendU64(SerializedReceipt* s, std::uint64_t value) {
    char buffer[32] = {};
    std::snprintf(buffer, sizeof(buffer), "%llu", static_cast<unsigned long long>(value));
    SrAppend(s, buffer);
}

inline void SrAppendI32(SerializedReceipt* s, std::int32_t value) {
    char buffer[24] = {};
    std::snprintf(buffer, sizeof(buffer), "%d", static_cast<int>(value));
    SrAppend(s, buffer);
}

inline void SrAppendRow(SerializedReceipt* s, const ComponentRow& row, bool first) {
    if (!first) SrAppend(s, ",");
    SrAppend(s, "{\"wrapper\":"); SrAppendU64(s, row.wrapper);
    SrAppend(s, ",\"wrapperClass\":"); SrAppendU64(s, row.wrapper_class);
    SrAppend(s, ",\"config\":"); SrAppendU64(s, row.config);
    SrAppend(s, ",\"configClass\":"); SrAppendU64(s, row.config_class);
    SrAppend(s, ",\"kind\":"); SrAppendI32(s, row.kind);
    SrAppend(s, ",\"enabled\":"); SrAppend(s, row.enabled ? "true" : "false");
    SrAppend(s, "}");
}

// 字段名清单（序列化产物的 shape，供离线核对）：
// phase kind code evidenceGateGap owner oldOwnerBefore oldOwnerAfter
// countBefore countAfter captureCodeBefore captureCodeAfter beforeRows[] afterRows[]
//   rows: wrapper wrapperClass config configClass kind enabled
// oldComponentsPreserved[]: wrapper kind present
// newKind4: wrapper owner config configClass present wrapperInAfter
inline void SerializeBeforeAfter(const ComponentSnapshot& before, const ComponentSnapshot& after,
                                 const ProdReceipt& receipt, SerializedReceipt* sink) {
    if (sink == nullptr) return;
    sink->used = 0;
    sink->truncated = false;
    sink->text[0] = '\0';
    SrAppend(sink, "{\"phase\":\""); SrAppend(sink, receipt.phase ? receipt.phase : "");
    SrAppend(sink, "\",\"kind\":"); SrAppendI32(sink, receipt.kind);
    SrAppend(sink, ",\"code\":\""); SrAppend(sink, ProdCodeName(receipt.code));
    SrAppend(sink, "\",\"evidenceGateGap\":\"");
    SrAppend(sink, receipt.evidenceGateGap ? receipt.evidenceGateGap : "");
    SrAppend(sink, "\",\"owner\":"); SrAppendU64(sink, before.owner);
    SrAppend(sink, ",\"oldOwnerBefore\":"); SrAppendU64(sink, before.owner);
    SrAppend(sink, ",\"oldOwnerAfter\":"); SrAppendU64(sink, after.owner);
    SrAppend(sink, ",\"countBefore\":"); SrAppendI32(sink, static_cast<std::int32_t>(before.count));
    SrAppend(sink, ",\"countAfter\":"); SrAppendI32(sink, static_cast<std::int32_t>(after.count));
    SrAppend(sink, ",\"captureCodeBefore\":"); SrAppendI32(sink, static_cast<std::int32_t>(receipt.captureCodeBefore));
    SrAppend(sink, ",\"captureCodeAfter\":"); SrAppendI32(sink, static_cast<std::int32_t>(receipt.captureCodeAfter));
    SrAppend(sink, ",\"beforeRows\":[");
    for (std::uint32_t i = 0; i < before.count && i < ca::kMaxComponents; ++i)
        SrAppendRow(sink, before.rows[i], i == 0);
    SrAppend(sink, "],\"afterRows\":[");
    for (std::uint32_t i = 0; i < after.count && i < ca::kMaxComponents; ++i)
        SrAppendRow(sink, after.rows[i], i == 0);
    // **完整旧组件保全**：before 里每个非 kind4 行，逐个标注在 after 中是否仍存在（wrapper+kind）。
    SrAppend(sink, "],\"oldComponentsPreserved\":[");
    bool firstOld = true;
    for (std::uint32_t i = 0; i < before.count && i < ca::kMaxComponents; ++i) {
        const ComponentRow& row = before.rows[i];
        if (row.kind == kRuntimeKindMover) continue;
        bool present = false;
        for (std::uint32_t j = 0; j < after.count && j < ca::kMaxComponents; ++j)
            if (after.rows[j].wrapper == row.wrapper && after.rows[j].kind == row.kind) { present = true; break; }
        if (!firstOld) SrAppend(sink, ",");
        firstOld = false;
        SrAppend(sink, "{\"wrapper\":"); SrAppendU64(sink, row.wrapper);
        SrAppend(sink, ",\"kind\":"); SrAppendI32(sink, row.kind);
        SrAppend(sink, ",\"present\":"); SrAppend(sink, present ? "true" : "false");
        SrAppend(sink, "}");
    }
    // **新 kind4 身份**：wrapper / owner / config 三值（config 取 after 里 kind4 行的真实字段）。
    SrAppend(sink, "],\"newKind4\":{\"wrapper\":");
    SrAppendU64(sink, reinterpret_cast<std::uint64_t>(receipt.wrapper));
    SrAppend(sink, ",\"owner\":"); SrAppendU64(sink, before.owner);
    std::uint64_t config = 0, configClass = 0;
    bool present = false, wrapperInAfter = false;
    for (std::uint32_t i = 0; i < after.count && i < ca::kMaxComponents; ++i) {
        if (after.rows[i].kind != kRuntimeKindMover) continue;
        if (!present) { config = after.rows[i].config; configClass = after.rows[i].config_class; present = true; }
        if (after.rows[i].wrapper == reinterpret_cast<std::uint64_t>(receipt.wrapper)) wrapperInAfter = true;
    }
    SrAppend(sink, ",\"config\":"); SrAppendU64(sink, config);
    SrAppend(sink, ",\"configClass\":"); SrAppendU64(sink, configClass);
    SrAppend(sink, ",\"present\":"); SrAppend(sink, present ? "true" : "false");
    SrAppend(sink, ",\"wrapperInAfter\":"); SrAppend(sink, wrapperInAfter ? "true" : "false");
    SrAppend(sink, "}}");
}

// 生产回调本体：CaptureComponents(before) → attach(owner,4) → CaptureComponents(after) → 判定 → 序列化。
inline ProdReceipt AttachKind4Production(ReadSource rs, CaptureWorkspace* ws, std::uint64_t owner,
                                         AttachComponent attach, SerializedReceipt* sink = nullptr) {
    ProdReceipt out{};
    out.kind = kRuntimeKindMover;
    out.phase = "component_prepared";
    // 证据缺口始终具名（通道成功挂载也不代表字段语义已证）。
    out.evidenceGateGap = "KIND_OWNER_CLASS_FIELDS_UNRESOLVED:4";
    out.code = ProdCode::OK;
    ComponentSnapshot before{}, after{};
    ca::CaptureComponents(rs, owner, ws, &before);              // CaptureComponents #1（生产路径）
    out.captureCodeBefore = static_cast<std::uint32_t>(before.code);
    out.countBefore = before.count;
    if (before.code != CaptureCode::complete) { out.code = ProdCode::BEFORE_CAPTURE_FAILED; return out; }
    out.phase = "component_acceptance";
    out.wrapper = (attach != nullptr) ? attach(reinterpret_cast<void*>(owner), kRuntimeKindMover) : nullptr;
    if (out.wrapper == nullptr) { out.code = ProdCode::ATTACH_CALLED_NULL; return out; }
    ca::CaptureComponents(rs, owner, ws, &after);               // CaptureComponents #2（after，生产路径）
    out.captureCodeAfter = static_cast<std::uint32_t>(after.code);
    out.countAfter = after.count;
    out.code = JudgeKind4Attach(before, after, owner, out.wrapper);
    out.ownerUnchanged = (before.owner == owner && after.owner == owner);
    out.oldComponentsUnchanged = (out.code != ProdCode::OLD_COMPONENTS_CHANGED);
    out.newKindPresent = (out.code != ProdCode::NEW_KIND_MISSING && out.code != ProdCode::NEW_KIND_DUPLICATE);
    SerializeBeforeAfter(before, after, out, sink);   // ← **生产路径上的序列化调用（唯一）**
    return out;
}

// ---- 生产入口：**非 inline 导出**，强制把 `AttachKind4Production` 的代码发进 .obj ----
// （此前全是 inline 且无非 inline 调用者 ⇒ 编译器不发射 ⇒ obj 仅 612 B、函数不在二进制里。）
__declspec(noinline) ProdReceipt EnsureKind4AttachedProduction(ReadSource rs, CaptureWorkspace* ws,
                                                              std::uint64_t owner,
                                                              AttachComponent attach,
                                                              SerializedReceipt* sink = nullptr) {
    return AttachKind4Production(rs, ws, owner, attach, sink);   // 真实调用点（生产段内）
}

// C 链接导出：取上面的地址 ⇒ 两个函数都必须被发射。参数保持 C++ 类型，故导出面只给地址。
extern "C" __declspec(dllexport) void* NdsKind4EnsureAttachedEntry() {
    return reinterpret_cast<void*>(&EnsureKind4AttachedProduction);
}

}  // namespace nds
#endif  // !NDS_STUB

// ═══════════════════════════════════════════════════════════════════════════
// 离线 fixture（`/DNDS_FIXTURE`）：**只准备"原生内存 + attach 替身"，不准备回执**
// ═══════════════════════════════════════════════════════════════════════════
// 链路：fixture → NdsKind4EnsureAttachedEntry()（C 导出）
//            → EnsureKind4AttachedProduction（noinline 生产入口）
//            → AttachKind4Production（生产 Attach/Serialize 本体）
//            → CaptureComponents(before) → FixtureAttach → CaptureComponents(after)
//            → JudgeKind4Attach → SerializeBeforeAfter（生产序列化调用）
// 本段**不调用** SerializeBeforeAfter / AttachKind4Production（源码检查器同判：
// drop_stuff_attach.py:production_chain_sites ⇒ RAW_SERIALIZATION_CALL_MISSING），
// 只把生产 sink 的字节原样落盘 ⇒ 删掉生产序列化调用时这里拿不到任何字节。
#ifdef NDS_FIXTURE
#include <array>

namespace {

// 固定假地址空间：常量基址 ⇒ 同一份源码/编译器下回执字节可复现。
constexpr std::uint64_t kFixtureBase = 0x10000000ULL;
constexpr std::size_t kFixtureSize = 0x8000;
// owner / HashSet 头 / List 头 / 三个数组 / 组件行 / config / class 对象的偏移（全部 8 字节对齐）。
constexpr std::size_t kOwnerOff = 0x0100;
constexpr std::size_t kSetHeaderOff = 0x0300;
constexpr std::size_t kListHeaderOff = 0x0380;
constexpr std::size_t kBucketsOff = 0x0400;
constexpr std::size_t kSlotsOff = 0x0500;
constexpr std::size_t kItemsOff = 0x0600;
constexpr std::size_t kRowsOff = 0x0700;
constexpr std::size_t kConfigsOff = 0x0800;
constexpr std::size_t kClassesOff = 0x0900;
constexpr std::size_t kRowStride = 0x40;
constexpr std::size_t kConfigStride = 0x40;
constexpr std::uint32_t kSetCapacity = 4;   // buckets/slots/items 容量（≥ before+1）
constexpr std::uint32_t kBeforeCount = 2;   // attach 前：kind17 + kind33；attach 后：+kind4

static_assert(kOwnerOff + 0xA0 <= kSetHeaderOff, "fixture owner fits before set header");
static_assert(kSetHeaderOff + 0x38 <= kListHeaderOff, "fixture set header fits before list header");
static_assert(kListHeaderOff + 0x20 <= kBucketsOff, "fixture list header fits before buckets");
static_assert(kBucketsOff + 0x20 + kSetCapacity * 4 <= kSlotsOff, "fixture buckets array fits");
static_assert(kSlotsOff + 0x20 + kSetCapacity * 12 <= kItemsOff, "fixture slots array fits");
static_assert(kItemsOff + 0x20 + kSetCapacity * 8 <= kRowsOff, "fixture items array fits");
static_assert(kRowsOff + 3 * kRowStride <= kConfigsOff, "fixture 3 wrapper rows fit");
static_assert(kConfigsOff + 3 * kConfigStride <= kClassesOff, "fixture 3 configs fit");
static_assert(kClassesOff + 0x40 <= kFixtureSize, "fixture class objects fit");
static_assert(((kOwnerOff | kSetHeaderOff | kListHeaderOff | kBucketsOff | kSlotsOff | kItemsOff
             | kRowsOff | kConfigsOff | kClassesOff) & 7u) == 0, "fixture addresses must be 8-byte aligned");

struct FixtureSpace {
    std::array<unsigned char, kFixtureSize> bytes{};
    int attachCalls = 0;
    std::int32_t attachKind = 0;
    std::uint64_t attachReturn = 0;
    bool attachReturnNull = false;
    bool attachOwnerMismatch = false;
};

FixtureSpace g_fixture;

std::uint64_t Addr(std::size_t offset) { return kFixtureBase + static_cast<std::uint64_t>(offset); }

template <class T> void Put(std::size_t offset, T value) {
    std::memcpy(g_fixture.bytes.data() + offset, &value, sizeof(T));
}

// 组件行（wrapper 0x38 字节 + config 0x28 字节）：回指必须与 production 读层要求逐项一致。
void SeedComponent(std::uint32_t index, std::uint64_t wrapperClassAddress, std::int32_t kind,
                   std::uint64_t configClassAddress) {
    const std::size_t w = kRowsOff + index * kRowStride;
    const std::size_t c = kConfigsOff + index * kConfigStride;
    Put<std::uint64_t>(w + 0x00, wrapperClassAddress);              // wrapper_class
    Put<std::uint64_t>(w + 0x20, Addr(kOwnerOff));                  // wrapper+0x20 = owner
    Put<std::uint64_t>(w + 0x28, Addr(c));                          // wrapper+0x28 = config
    Put<std::uint8_t>(w + 0x30, static_cast<std::uint8_t>(1));      // enabled
    Put<std::int32_t>(w + 0x34, kind);                              // kind
    Put<std::uint64_t>(c + 0x00, configClassAddress);               // config_class
    Put<std::uint64_t>(c + 0x18, Addr(w));                          // config+0x18 = wrapper
    Put<std::uint64_t>(c + 0x20, Addr(kOwnerOff));                  // config+0x20 = owner
}

// attach 前的原生状态：owner + 两个组件（kind17/kind33）；kind4 对象**已在内存里但未入链**。
void ApplyBeforeState() {
    Put<std::int32_t>(kSetHeaderOff + 0x28, static_cast<std::int32_t>(kBeforeCount)); // set count
    Put<std::int32_t>(kSetHeaderOff + 0x2c, static_cast<std::int32_t>(kBeforeCount)); // set last
    Put<std::int32_t>(kSetHeaderOff + 0x30, -1);                                      // free head
    Put<std::uint32_t>(kSetHeaderOff + 0x34, 21);                                     // set version
    Put<std::uint32_t>(kListHeaderOff + 0x1c, 34);                                    // list version
    // 桶头 = 槽下标+1；**空桶哨兵是 0**（共享读层 component_attachment.cpp:94 的 head<0 即 invalid_structure，
    // 且 :95 的 index=head-1 在 head==0 时为 -1 终止 ⇒ -1 不是合法空桶值）。
    const std::int32_t buckets[kSetCapacity] = { 1, 2, 0, 0 };
    for (std::uint32_t i = 0; i < kSetCapacity; ++i)
        Put<std::int32_t>(kBucketsOff + 0x20 + i * 4, buckets[i]);
    const std::int32_t hashes[kBeforeCount] = { 4, 5 };   // hash % capacity == bucket
    const std::int32_t kinds[kBeforeCount] = { 17, 33 };
    for (std::uint32_t i = 0; i < kBeforeCount; ++i) {
        Put<std::int32_t>(kSlotsOff + 0x20 + i * 12 + 0, hashes[i]);
        Put<std::int32_t>(kSlotsOff + 0x20 + i * 12 + 4, -1);
        Put<std::int32_t>(kSlotsOff + 0x20 + i * 12 + 8, kinds[i]);
    }
    Put<std::int32_t>(kSlotsOff + 0x20 + kBeforeCount * 12 + 0, 0);   // kind4 slot 未入链
    Put<std::int32_t>(kSlotsOff + 0x20 + kBeforeCount * 12 + 4, 0);
    Put<std::int32_t>(kSlotsOff + 0x20 + kBeforeCount * 12 + 8, 0);
    Put<std::int32_t>(kListHeaderOff + 0x18, static_cast<std::int32_t>(kBeforeCount));
    for (std::uint32_t i = 0; i < kSetCapacity; ++i) {
        const std::uint64_t wrapper = i < kBeforeCount ? Addr(kRowsOff + i * kRowStride) : 0;
        Put<std::uint64_t>(kItemsOff + 0x20 + i * 8, wrapper);
    }
}

// attach 替身的真实效应：把已在内存里的 kind4 组件挂进 HashSet + List（生产读层随后独立复读）。
void ApplyAttachedState() {
    Put<std::int32_t>(kSetHeaderOff + 0x28, 3);   // set count
    Put<std::int32_t>(kSetHeaderOff + 0x2c, 3);   // set last
    Put<std::int32_t>(kSetHeaderOff + 0x30, -1);
    Put<std::uint32_t>(kSetHeaderOff + 0x34, 22);
    Put<std::uint32_t>(kListHeaderOff + 0x1c, 35);
    Put<std::int32_t>(kBucketsOff + 0x20 + 2 * 4, 3);                       // bucket2 → slot index2
    Put<std::int32_t>(kSlotsOff + 0x20 + 2 * 12 + 0, 6);                    // hash 6 % 4 == 2
    Put<std::int32_t>(kSlotsOff + 0x20 + 2 * 12 + 4, -1);
    Put<std::int32_t>(kSlotsOff + 0x20 + 2 * 12 + 8, nds::kRuntimeKindMover); // value = kind4
    Put<std::int32_t>(kListHeaderOff + 0x18, 3);
    Put<std::uint64_t>(kItemsOff + 0x20 + 2 * 8, Addr(kRowsOff + 2 * kRowStride));
}

void SeedAddressSpace() {
    g_fixture = FixtureSpace{};
    // owner：+0x00 class、+0x30 set、+0x68 list、+0x9c state
    Put<std::uint64_t>(kOwnerOff + 0x00, Addr(kClassesOff));
    Put<std::uint64_t>(kOwnerOff + 0x30, Addr(kSetHeaderOff));
    Put<std::uint64_t>(kOwnerOff + 0x68, Addr(kListHeaderOff));
    Put<std::uint8_t>(kOwnerOff + 0x9c, static_cast<std::uint8_t>(1));
    // HashSet 头（0x38）/ List 头（0x20）
    Put<std::uint64_t>(kSetHeaderOff + 0x00, Addr(kClassesOff));
    Put<std::uint64_t>(kSetHeaderOff + 0x10, Addr(kBucketsOff));
    Put<std::uint64_t>(kSetHeaderOff + 0x18, Addr(kClassesOff));
    Put<std::uint64_t>(kSetHeaderOff + 0x20, Addr(kSlotsOff));
    Put<std::uint64_t>(kListHeaderOff + 0x00, Addr(kClassesOff));
    Put<std::uint64_t>(kListHeaderOff + 0x10, Addr(kItemsOff));
    // buckets/slots/items 头 +0x18 = 容量
    Put<std::uint64_t>(kBucketsOff + 0x18, static_cast<std::uint64_t>(kSetCapacity));
    Put<std::uint64_t>(kSlotsOff + 0x18, static_cast<std::uint64_t>(kSetCapacity));
    Put<std::uint64_t>(kItemsOff + 0x18, static_cast<std::uint64_t>(kSetCapacity));
    // 三个组件对象都在内存里（kind4 是"已存在但未入链"的待挂件）
    SeedComponent(0, Addr(kClassesOff + 0x00), 17, Addr(kClassesOff + 0x28));
    SeedComponent(1, Addr(kClassesOff + 0x08), 33, Addr(kClassesOff + 0x30));
    SeedComponent(2, Addr(kClassesOff + 0x10), nds::kRuntimeKindMover, Addr(kClassesOff + 0x38));
    ApplyBeforeState();
}

bool FixtureRead(void* context, std::uint64_t address, void* target, std::size_t size) noexcept {
    (void)context;
    if (address < kFixtureBase) return false;
    const std::uint64_t offset = address - kFixtureBase;
    if (offset > kFixtureSize || size > kFixtureSize - static_cast<std::size_t>(offset)) return false;
    std::memcpy(target, g_fixture.bytes.data() + static_cast<std::size_t>(offset), size);
    return true;
}

// attach 替身：扮演引擎 attach(RVA 0x867c610) 的**同一 ABI 角色**（离线不执行引擎函数）。
// 它只做两件事：(1) 校验 owner/kind；(2) 把内存里的 kind4 组件挂进 set+list。
// 返回值 = 该 wrapper 的真实（本地址空间）地址 ⇒ 生产路径回写 receipt.wrapper，
// 再经 CaptureComponents 从内存复读校验（newKind4.wrapper 不是 fixture 塞进回执的常量）。
void* __cdecl FixtureAttach(void* owner, std::int32_t kind) {
    ++g_fixture.attachCalls;
    g_fixture.attachKind = kind;
    if (g_fixture.attachReturnNull) return nullptr;
    if (kind != nds::kRuntimeKindMover) return nullptr;
    if (reinterpret_cast<std::uint64_t>(owner) != Addr(kOwnerOff)) {
        g_fixture.attachOwnerMismatch = true;
        return nullptr;
    }
    ApplyAttachedState();
    g_fixture.attachReturn = Addr(kRowsOff + 2 * kRowStride);
    return reinterpret_cast<void*>(g_fixture.attachReturn);
}

void WriteFailureVerdict(const char* path) {
    std::FILE* verdict = std::fopen(path, "wb");
    if (verdict == nullptr) return;
    std::fprintf(verdict,
                 "{\n  \"schema\": \"nds-kind4-chain-verdict-v1\",\n"
                 "  \"ok\": false,\n  \"failure\": \"RAW_SERIALIZATION_CALL_MISSING\",\n"
                 "  \"receiptPath\": null,\n  \"receiptBytes\": 0,\n"
                 "  \"attachCalls\": %d,\n  \"liveGameAttachExecuted\": false\n}\n",
                 g_fixture.attachCalls);
    std::fclose(verdict);
}

void WriteVerdict(const char* path, const char* receiptPath, const nds::ProdReceipt& receipt,
                  std::size_t receiptBytes, bool wrapperMatches, bool ok) {
    std::FILE* verdict = std::fopen(path, "wb");
    if (verdict == nullptr) return;
    std::fprintf(verdict, "{\n  \"schema\": \"nds-kind4-chain-verdict-v1\",\n");
    std::fprintf(verdict, "  \"fixture\": \"native_dropstuff.cpp:NDS_FIXTURE\",\n");
    std::fprintf(verdict, "  \"chain\": [\"NdsKind4EnsureAttachedEntry\", \"EnsureKind4AttachedProduction\", "
                          "\"AttachKind4Production\", \"CaptureComponents(before)\", \"attach(owner,4)\", "
                          "\"CaptureComponents(after)\", \"JudgeKind4Attach\", \"SerializeBeforeAfter\"],\n");
    std::fprintf(verdict, "  \"attachRva\": \"0x867c610\",\n  \"attachDouble\": \"FixtureAttach\",\n");
    std::fprintf(verdict, "  \"liveGameAttachExecuted\": false,\n");
    std::fprintf(verdict, "  \"addressSpaceBase\": %llu,\n", static_cast<unsigned long long>(kFixtureBase));
    std::fprintf(verdict, "  \"attachCalls\": %d,\n  \"attachKind\": %d,\n",
                 g_fixture.attachCalls, static_cast<int>(g_fixture.attachKind));
    std::fprintf(verdict, "  \"attachReturn\": %llu,\n",
                 static_cast<unsigned long long>(g_fixture.attachReturn));
    std::fprintf(verdict, "  \"receiptWrapper\": %llu,\n",
                 static_cast<unsigned long long>(reinterpret_cast<std::uint64_t>(receipt.wrapper)));
    std::fprintf(verdict, "  \"wrapperFromAttachReturn\": %s,\n", wrapperMatches ? "true" : "false");
    std::fprintf(verdict, "  \"owner\": %llu,\n", static_cast<unsigned long long>(Addr(kOwnerOff)));
    std::fprintf(verdict, "  \"countBefore\": %u,\n  \"countAfter\": %u,\n",
                 receipt.countBefore, receipt.countAfter);
    std::fprintf(verdict, "  \"captureCodeBefore\": %u,\n  \"captureCodeAfter\": %u,\n",
                 receipt.captureCodeBefore, receipt.captureCodeAfter);
    std::fprintf(verdict, "  \"receiptCode\": \"%s\",\n  \"phase\": \"%s\",\n",
                 nds::ProdCodeName(receipt.code), receipt.phase);
    std::fprintf(verdict, "  \"receiptBytes\": %llu,\n",
                 static_cast<unsigned long long>(receiptBytes));
    std::fprintf(verdict, "  \"receiptPath\": \"%s\",\n", receiptPath);
    std::fprintf(verdict, "  \"verdictPath\": \"%s\",\n", path);
    std::fprintf(verdict, "  \"ok\": %s\n}\n", ok ? "true" : "false");
    std::fclose(verdict);
}

}  // namespace

int main(int argc, char** argv) {
    const char* receiptPath = (argc > 1 && argv[1] != nullptr && argv[1][0] != '\0')
        ? argv[1] : ".life-dropstuff-out/nds_before_after.json";
    const char* verdictPath = (argc > 2 && argv[2] != nullptr && argv[2][0] != '\0')
        ? argv[2] : ".life-dropstuff-out/nds_chain_verdict.json";

    SeedAddressSpace();
    nds::ReadSource source{ &g_fixture, &FixtureRead };

    // ① 只经 C 导出入口取生产入口地址（不是直接写 &EnsureKind4AttachedProduction）。
    void* entry = nds::NdsKind4EnsureAttachedEntry();
    std::printf("NDS_CHAIN_ENTRY=%p export=NdsKind4EnsureAttachedEntry\n", entry);
    if (entry == nullptr) {
        std::printf("RAW_RECEIPT_ENTRY_MISSING: C 导出入口返回空指针\n");
        return 4;
    }
    // 生产入口的**函数指针类型**（与 `EnsureKind4AttachedProduction` 声明逐参对齐；fixture 不按名字取符号）。
    using ProductionEntry = nds::ProdReceipt (*)(nds::ReadSource, nds::CaptureWorkspace*, std::uint64_t,
                                                 nds::AttachComponent, nds::SerializedReceipt*);
    const ProductionEntry production = reinterpret_cast<ProductionEntry>(entry);

    // ② 生产入口 → 生产 Attach/Serialize 本体；回执 sink 是**生产序列化产物**的唯一落点。
    nds::CaptureWorkspace workspace{};
    nds::SerializedReceipt sink{};
    const nds::ProdReceipt receipt =
        production(source, &workspace, Addr(kOwnerOff), &FixtureAttach, &sink);

    std::printf("NDS_RECEIPT code=%s phase=%s bytes=%llu truncated=%d\n",
                nds::ProdCodeName(receipt.code), receipt.phase,
                static_cast<unsigned long long>(sink.used), sink.truncated ? 1 : 0);
    std::printf("NDS_ATTACH calls=%d kind=%d returned=0x%llx returnNull=%d ownerMismatch=%d\n",
                g_fixture.attachCalls, static_cast<int>(g_fixture.attachKind),
                static_cast<unsigned long long>(g_fixture.attachReturn),
                g_fixture.attachReturnNull ? 1 : 0, g_fixture.attachOwnerMismatch ? 1 : 0);
    std::printf("NDS_PATH countBefore=%u countAfter=%u captureBefore=%u captureAfter=%u wrapper=0x%llx\n",
                receipt.countBefore, receipt.countAfter, receipt.captureCodeBefore, receipt.captureCodeAfter,
                static_cast<unsigned long long>(reinterpret_cast<std::uint64_t>(receipt.wrapper)));

    if (sink.used == 0) {
        // **负控判据**：生产序列化调用被摘掉（或生产段提前返回）⇒ 回执必为空 ⇒ 具名失败、不写回执。
        std::printf("RAW_SERIALIZATION_CALL_MISSING: 生产路径序列化未产生任何字节；回执必须经生产入口产出\n");
        WriteFailureVerdict(verdictPath);
        return 3;
    }

    // ③ 只把生产 sink 的字节原样落盘（fixture 不重新序列化）。
    std::FILE* file = std::fopen(receiptPath, "wb");
    if (file == nullptr) { std::printf("RAW_RECEIPT_WRITE_FAILED path=%s\n", receiptPath); return 5; }
    const std::size_t written = std::fwrite(sink.text, 1, sink.used, file);
    std::fclose(file);
    if (written != sink.used) { std::printf("RAW_RECEIPT_WRITE_SHORT path=%s\n", receiptPath); return 6; }
    std::printf("NDS_RAW_RECEIPT path=%s bytes=%llu\n", receiptPath,
                static_cast<unsigned long long>(sink.used));

    // ④ 判据：code/phase/计数/wrapper==attach 返回/旧组件保全（任一不成立即非零）。
    const bool wrapperMatches = g_fixture.attachReturn != 0
        && reinterpret_cast<std::uint64_t>(receipt.wrapper) == g_fixture.attachReturn;
    const bool ok = receipt.code == nds::ProdCode::OK
        && !sink.truncated
        && g_fixture.attachCalls == 1
        && g_fixture.attachKind == nds::kRuntimeKindMover
        && !g_fixture.attachOwnerMismatch
        && wrapperMatches
        && receipt.countBefore == kBeforeCount
        && receipt.countAfter == kBeforeCount + 1
        && receipt.captureCodeBefore == static_cast<std::uint32_t>(ge::component_attachment::CaptureCode::complete)
        && receipt.captureCodeAfter == static_cast<std::uint32_t>(ge::component_attachment::CaptureCode::complete)
        && std::strcmp(receipt.phase, "component_acceptance") == 0
        && receipt.ownerUnchanged && receipt.oldComponentsUnchanged && receipt.newKindPresent;
    WriteVerdict(verdictPath, receiptPath, receipt, sink.used, wrapperMatches, ok);
    std::printf("NDS_CHAIN ok=%d\n", ok ? 1 : 0);
    return ok ? 0 : 1;
}
#endif  // NDS_FIXTURE

#ifdef NDS_STUB
#include <array>

namespace {

struct FakeMem {
    std::array<std::uint8_t, 256> code{};
    std::array<std::uint8_t, 128> wrapper{};
    std::array<std::uint8_t, 64> config{};
    void* ownerTarget = nullptr;
    std::int32_t kindToReport = 4;
    bool returnNull = false;
    bool mismatchOwner = false;
    int notifyCount = 0;
};

bool StubRead(void* ctx, std::uintptr_t address, const void* target, std::size_t size) {
    auto* mem = static_cast<FakeMem*>(ctx);
    if (address == nds::kOwnerAttachRva) {
        for (std::size_t i = 0; i < size && i < 32; ++i) {
            unsigned value = 0;
            std::sscanf(nds::kAttachHead32Hex + i * 2, "%2x", &value);
            mem->code[i] = static_cast<std::uint8_t>(value);
        }
        std::memcpy(const_cast<void*>(target), mem->code.data(), size);
        return true;
    }
    const std::uintptr_t wrapAddr = reinterpret_cast<std::uintptr_t>(mem->wrapper.data());
    if (address >= wrapAddr && address + size <= wrapAddr + mem->wrapper.size()) {
        std::memcpy(const_cast<void*>(target), mem->wrapper.data() + (address - wrapAddr), size);
        return true;
    }
    const std::uintptr_t confAddr = reinterpret_cast<std::uintptr_t>(mem->config.data());
    if (address >= confAddr && address + size <= confAddr + mem->config.size()) {
        std::memcpy(const_cast<void*>(target), mem->config.data() + (address - confAddr), size);
        return true;
    }
    return false;
}

void StubNotify(void* owner, const nds::NdsResult& result) {
    auto* mem = static_cast<FakeMem*>(owner);
    ++mem->notifyCount;
    std::printf("   notify: code=%s kind=%d config=%p\n", nds::CodeName(result.code),
                result.kindSeen, result.config);
}

void* __cdecl StubAttach(void* owner, std::int32_t kind) {
    auto* mem = static_cast<FakeMem*>(owner);
    (void)kind;
    if (mem->returnNull) return nullptr;
    std::uint64_t ownerBackref = reinterpret_cast<std::uint64_t>(
        mem->mismatchOwner ? nullptr : mem->ownerTarget);
    std::uint64_t configAddr = reinterpret_cast<std::uint64_t>(mem->config.data());
    std::uint32_t kindValue = static_cast<std::uint32_t>(mem->kindToReport);
    std::memcpy(mem->wrapper.data() + nds::kWrapOwnerOff, &ownerBackref, sizeof(ownerBackref));
    std::memcpy(mem->wrapper.data() + nds::kWrapConfigOff, &configAddr, sizeof(configAddr));
    std::memcpy(mem->wrapper.data() + nds::kWrapKindOff, &kindValue, sizeof(kindValue));
    return mem->wrapper.data();
}

struct Case { const char* name; std::int32_t kind; bool nullReturn; bool mismatchOwner; nds::NdsCode expect; };

}  // namespace

int main() {
    const Case cases[] = {
        { "positive(kind=4, owner ok)", 4, false, false, nds::NdsCode::OK },
        { "negative(kind=26)", 26, false, false, nds::NdsCode::WRAPPER_KIND_MISMATCH },
        { "negative(attach null)", 4, true, false, nds::NdsCode::ATTACH_RETURNED_NULL },
        { "negative(owner backref mismatch)", 4, false, true, nds::NdsCode::WRAPPER_OWNER_MISMATCH },
    };
    const int total = static_cast<int>(sizeof(cases) / sizeof(cases[0]));
    int failed = 0;
    for (int i = 0; i < total; ++i) {
        FakeMem mem;
        mem.kindToReport = cases[i].kind;
        mem.returnNull = cases[i].nullReturn;
        mem.mismatchOwner = cases[i].mismatchOwner;
        mem.ownerTarget = static_cast<void*>(&mem);
        nds::ReadBytes io{ &StubRead, &mem };
        std::printf("case %s (expect %s):\n", cases[i].name, nds::CodeName(cases[i].expect));
        nds::NdsResult result = nds::AttachKind4(io, 0, static_cast<void*>(&mem), &StubAttach, &StubNotify);
        const bool ok = result.code == cases[i].expect;
        if (!ok) ++failed;
        std::printf("   result: code=%s kindSeen=%d wrapper=%p config=%p notify=%d %s\n",
                    nds::CodeName(result.code), result.kindSeen, result.wrapper, result.config,
                    mem.notifyCount, ok ? "[PASS]" : "[FAIL]");
    }
    std::printf("NDS_STUB total=%d failed=%d\n", total, failed);
    return failed == 0 ? 0 : 1;
}
#endif  // NDS_STUB
