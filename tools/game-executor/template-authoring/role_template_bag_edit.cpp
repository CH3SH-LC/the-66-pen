#include "role_template_bag_edit.h"
#include <cstring>

namespace ge::role_template_edit {
namespace {
using ge::templates::TemplatePointer;
using ge::templates::TemplateReadSource;
struct Reader {
    TemplateReadSource source;
    std::uint32_t calls = 0;
    template<class T> bool at(std::uint64_t p, std::uint32_t offset, T& out) noexcept {
        if (!source.read || !TemplatePointer(p) || ++calls > 8192 || p + offset + sizeof(out) >= 0x800000000000ULL) return false;
        return source.read(source.context, p + offset, &out, sizeof(out));
    }
};
bool environment(Reader& r, const Evidence& e) noexcept {
    if (!e.codeAndThreadVerified || e.kind != 33 || !TemplatePointer(e.owner)) return false;
    std::uint64_t wrapperClass = 0, configClass = 0, ownerClass = 0, value = 0;
    if (!r.at(e.moduleBase, 0x57b0058, wrapperClass) || !r.at(e.moduleBase, e.kind == 35 ? 0x57b1060 : 0x57dda88, configClass) ||
        !r.at(e.owner, 0, ownerClass) || !r.at(wrapperClass, 0x120, value) || value != e.moduleBase + 0x106ffc40 ||
        !r.at(wrapperClass, 0x130, value) || value != e.moduleBase + 0x106ff240 ||
        !r.at(configClass, 0x378, value) || value != e.moduleBase + (e.kind == 35 ? 0x82514f0 : 0x10ed3250) ||
        !r.at(configClass, 0x350, value) || value != e.moduleBase + 0xb613ce0 ||
        !r.at(ownerClass, 0x280, value) || value != e.moduleBase + 0xd410760) return false;
    std::uint64_t expectedOwnerClass=0;
    std::uint32_t id=0,baseConfig=0; std::uint8_t customFlag=255;
    if (!r.at(e.moduleBase,0x57b1068,expectedOwnerClass) || ownerClass!=expectedOwnerClass ||
        !r.at(e.owner,0x1c,id) || id!=1090519041 || !r.at(e.owner,0xb8,baseConfig) || baseConfig!=1000001 ||
        !r.at(e.owner,0xb4,customFlag) || customFlag ||
        !r.at(ownerClass,0x1d0,value) || value!=e.moduleBase+0xd40f5b0) return false;
    if (!e.wrapper && !e.config) return true;
    if (!r.at(e.wrapper, 0, value) || value != wrapperClass || !r.at(e.config, 0, value) || value != configClass ||
        !r.at(e.wrapper, 0x20, value) || value != e.owner || !r.at(e.wrapper, 0x28, value) || value != e.config ||
        !r.at(e.config, 0x18, value) || value != e.wrapper || !r.at(e.config, 0x20, value) || value != e.owner) return false;
    std::int32_t kind = 0; return r.at(e.wrapper, 0x34, kind) && kind == e.kind;
}
bool sameEvidence(const Evidence& a, const Evidence& b) noexcept {
    return a.moduleBase == b.moduleBase && a.global == b.global && a.owner == b.owner && a.wrapper == b.wrapper &&
        a.config == b.config && a.kind == b.kind && b.codeAndThreadVerified;
}
bool sameIdentity(const EditState& a, const EditState& b) noexcept {
    return a.manager == b.manager && a.list == b.list && a.recordClass == b.recordClass && a.literal == b.literal &&
        a.baseDepth == b.baseDepth && !b.flags[1] && !b.flags[2];
}
bool sameOtherRecords(const EditState& a, const EditState& b, bool append) noexcept {
    if (b.count != a.count + (append ? 1U : 0U)) return false;
    for (std::uint32_t i = 0; i < a.count; ++i) {
        const auto& x = a.records[i]; const auto& y = b.records[i];
        if (x.pointer != y.pointer || x.klass != y.klass || x.object != y.object || x.before != y.before || x.after != y.after || x.dirty != y.dirty) return false;
    }
    return true;
}
}
Code CheckReady(TemplateReadSource source, const Evidence& e, EditState* out) noexcept {
    if (!out) return Code::invalid_evidence;
    Reader r{source};
    if (!environment(r, e)) return Code::invalid_environment;
    CaptureEditState(source, e, out);
    if (out->code != ReadCode::complete || out->targetCount > 1) return Code::read_failed;
    // +18 is the pending transaction list, not the undo/redo history. Native
    // start/close uses +30/+34 depth; preexisting history is deliberately allowed.
    if (out->depth != out->baseDepth || out->flags[1] || out->flags[2]) return Code::busy;
    return Code::ready;
}
void Begin(TemplateReadSource source, const NativeCalls& calls, const Evidence& e, Result* out) noexcept {
    if (!out) return;
    if (out->openCalled || out->snapshotCalled) { out->code = Code::duplicate_attempt; return; }
    *out = {}; out->code = Code::invalid_evidence; out->needsPersistenceAcceptance = true;
    if (!TemplatePointer(e.wrapper) || !TemplatePointer(e.config)) return;
    if (!calls.open || !calls.snapshot || !calls.notify || !calls.close) { out->code = Code::missing_calls; return; }
    out->code = CheckReady(source, e, &out->before);
    if (out->code != Code::ready) return;
    out->evidence = e;
    try {
        out->stage = Stage::open; out->openCalled = true; out->transactionMayBeOpen = true; out->outcomeUncertain = true;
        out->transaction = reinterpret_cast<std::uint64_t>(calls.open(nullptr, false, false)); out->stage = Stage::none;
        if (!TemplatePointer(out->transaction)) { out->code = Code::opened_without_handle; return; }
        out->stage = Stage::snapshot; out->snapshotCalled = true;
        calls.snapshot(reinterpret_cast<void*>(e.wrapper), reinterpret_cast<void*>(out->before.literal), 0); out->stage = Stage::none;
        CaptureEditState(source, e, &out->afterSnapshot); const auto& s = out->afterSnapshot;
        out->code = Code::snapshot_failed;
        const bool append = out->before.targetCount == 0;
        if (s.code != ReadCode::complete || !sameIdentity(out->before, s) || s.depth != out->before.depth + 1 ||
            s.targetCount != 1 || !TemplatePointer(s.target.before) || !sameOtherRecords(out->before, s, append) ||
            (append && (s.target.pointer != s.records[s.count - 1].pointer || s.target.dirty || s.target.after))) return;
        out->snapshotVerified = true; out->code = Code::snapshot_ready;
    } catch (...) { out->code = Code::call_exception; }
}
void Complete(TemplateReadSource source, const NativeCalls& calls, const Evidence& e, Result* out) noexcept {
    if (!out) return;
    if (out->notifyCalled || out->closeCalled) { out->code = Code::duplicate_attempt; return; }
    if (!out->snapshotVerified || !out->transactionMayBeOpen || !sameEvidence(out->evidence, e) || !calls.notify || !calls.close) {
        out->code = Code::invalid_evidence; return;
    }
    Reader r{source}; EditState beforeNotify{};
    CaptureEditState(source, e, &beforeNotify);
    if (!environment(r, e) || beforeNotify.code != ReadCode::complete || std::memcmp(&beforeNotify, &out->afterSnapshot, sizeof(beforeNotify))) {
        out->code = Code::notify_failed; return;
    }
    try {
        out->stage = Stage::notify; out->notifyCalled = true;
        calls.notify(reinterpret_cast<void*>(beforeNotify.manager), reinterpret_cast<void*>(e.wrapper)); out->stage = Stage::none;
        CaptureEditState(source, e, &out->afterNotify); const auto& s = out->afterNotify;
        out->code = Code::notify_failed;
        if (s.code != ReadCode::complete || !sameIdentity(beforeNotify, s) || s.depth != beforeNotify.depth ||
            s.count != beforeNotify.count || s.targetCount != 1 || s.target.pointer != beforeNotify.target.pointer ||
            s.target.before != beforeNotify.target.before || s.target.dirty != 1) return;
        for (std::uint32_t i = 0; i < s.count; ++i) {
            const auto& a = beforeNotify.records[i]; const auto& b = s.records[i];
            if (a.pointer != b.pointer || a.klass != b.klass || a.object != b.object || a.before != b.before || a.after != b.after ||
                (a.pointer != s.target.pointer && a.dirty != b.dirty)) return;
        }
        out->notificationVerified = true; out->code = Code::notification_verified;
        out->stage = Stage::close; out->closeCalled = true;
        calls.close(reinterpret_cast<void*>(out->transaction)); out->stage = Stage::none;
        CaptureEditState(source, e, &out->afterClose); out->code = Code::close_failed;
        if (out->afterClose.code != ReadCode::complete || !sameIdentity(out->before, out->afterClose) ||
            out->afterClose.depth != out->before.depth || out->afterClose.count) return;
        out->closeVerified = true; out->transactionMayBeOpen = false; out->code = Code::complete;
    } catch (...) { out->code = Code::call_exception; }
}
}
