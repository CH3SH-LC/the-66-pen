#include "skill_action.h"
#include <initializer_list>

namespace ge::skills {
namespace {
using namespace ge::templates;
template<class T> bool Read(TemplateReadSource s, std::uint64_t at, T& value) noexcept {
    return s.read && at >= 0x10000 && at < 0x800000000000ULL - sizeof(T) &&
        s.read(s.context, at, &value, sizeof(value));
}
bool Pointer(TemplateReadSource s, std::uint64_t at, std::uint64_t& value) noexcept {
    return Read(s, at, value) && TemplatePointer(value);
}
bool SameScene(const GameContextSnapshot& a, const GameContextSnapshot& b) noexcept {
    if (a.structSize != sizeof(a) || b.structSize != sizeof(b) || a.version != 1 || b.version != 1 ||
        a.status != GS_OK || b.status != GS_OK || (a.flags & 1951) != 1951 || (b.flags & 1951) != 1951 ||
        ((a.flags | b.flags) & 96) || a.entityRejected || b.entityRejected || a.activeKey || b.activeKey ||
        !a.reserved || a.reserved != b.reserved || a.moduleBase != b.moduleBase || a.global != b.global ||
        a.currentContext != b.currentContext || a.contextManager != b.contextManager || a.saveManager != b.saveManager ||
        a.peTimestamp != b.peTimestamp || a.peImageSize != b.peImageSize || !TemplatePointer(a.moduleBase) ||
        !TemplatePointer(a.global) || !TemplatePointer(a.currentContext) || a.entityCaptured > kMaxEntities ||
        a.entityCaptured != b.entityCaptured || a.entityCaptured != a.entityValidEntries || b.entityCaptured != b.entityValidEntries) return false;
    for (std::uint32_t i = 0; i < a.entityCaptured; ++i) {
        const auto& x = a.entities[i]; const auto& y = b.entities[i];
        if (x.id != y.id || x.owner != y.owner || x.config != y.config || x.context != y.context ||
            x.configId != y.configId || x.dictionaryKey != y.dictionaryKey || x.flags != y.flags) return false;
    }
    return true;
}
bool Roots(TemplateReadSource s, const GameContextSnapshot& scene, std::uint64_t manager, std::uint64_t table) noexcept {
    std::uint64_t value = 0;
    return Pointer(s, scene.moduleBase + kTemplateGlobalSlotRva, value) && value == scene.global &&
        Pointer(s, scene.global + 0xa420, value) && value == manager &&
        Pointer(s, scene.global + 0x17688, value) && value == table;
}
TemplateDelta MainDelta(const TemplateCatalogCapture& before, const TemplateCatalogCapture& after,
    std::uint64_t klass, std::uint64_t returned) noexcept {
    const auto fail=[](CatalogCode code) { return TemplateDelta{code,{}}; };
    const auto a=MainTemplateView(before), b=MainTemplateView(after);
    if (!a.complete || !b.complete) return fail(CatalogCode::incomplete);
    if (!ValidTemplateCatalog(a) || !ValidTemplateCatalog(b)) return fail(CatalogCode::invalid_catalog);
    if (a.manager != b.manager || a.level_id != b.level_id) return fail(CatalogCode::context_changed);
    if (b.count != a.count + 1) return fail(CatalogCode::count_mismatch);
    for (std::uint32_t i=0; i<a.count; ++i) {
        const auto& x=a.rows[i]; bool found=false;
        for (std::uint32_t j=0; j<b.count; ++j) {
            const auto& y=b.rows[j];
            if (x.id==y.id && x.subtype==y.subtype && x.resource==y.resource && x.klass==y.klass) found=true;
        }
        if (!found) return fail(CatalogCode::prior_resource_changed);
    }
    for (std::uint32_t j=0; j<b.count; ++j) {
        const auto& y=b.rows[j]; bool old=false;
        for (std::uint32_t i=0; i<a.count; ++i) if (a.rows[i].id==y.id) old=true;
        if (old) continue;
        if (y.subtype!=6 || y.klass!=klass || y.resource!=returned ||
            (y.id&0xe0000000U)!=0x40000000U || ((y.id>>22)&127U)!=6)
            return fail(CatalogCode::added_resource_mismatch);
        return {CatalogCode::verified,y};
    }
    return fail(CatalogCode::added_resource_mismatch);
}
bool SameCompanion(const TemplateCompanionIdentity& x, const TemplateCompanionIdentity& y) noexcept {
    return x.key==y.key && x.parent_id==y.parent_id && x.own_id==y.own_id && x.resource==y.resource &&
        x.klass==y.klass && x.guid_domain[0]==y.guid_domain[0] && x.guid_domain[1]==y.guid_domain[1] &&
        x.guid_domain[2]==y.guid_domain[2];
}
bool CompanionDelta(const TemplateCatalogCapture& a, const TemplateCatalogCapture& b, SkillActionResult& out) noexcept {
    if (b.companion.row_count != a.companion.row_count+1) return false;
    for (std::uint32_t i=0; i<a.companion.row_count; ++i) {
        bool found=false;
        for (std::uint32_t j=0; j<b.companion.row_count; ++j)
            if (SameCompanion(a.companion_rows[i],b.companion_rows[j])) found=true;
        if (!found) return false;
    }
    for (std::uint32_t j=0; j<b.companion.row_count; ++j) {
        const auto& row=b.companion_rows[j]; bool old=false;
        for (std::uint32_t i=0; i<a.companion.row_count; ++i) if (row.key==a.companion_rows[i].key) old=true;
        if (old) continue;
        if (row.key!=out.createdId || row.parent_id!=out.createdId || !row.own_id ||
            row.klass!=out.observedCompanionClass || row.guid_domain[0]!=0 || row.guid_domain[1]!=1 || row.guid_domain[2]!=4) return false;
        out.companionOwnId=row.own_id; out.companionResource=row.resource; return true;
    }
    return false;
}
}
void ExecuteSkillAction(const GameContextSnapshot* current, const SkillActionReview& review,
    const SkillActionRuntime& runtime, ge::templates::TemplateReadSource source,
    const SkillActionBindings& calls, std::string_view name, SkillActionWorkspace* work, SkillActionResult* out) noexcept {
    using namespace ge::templates;
    if (!out) return;
    // A retained caller-owned attempt cannot be replayed by reusing this result.
    if (out->createCalled) return;
    *out={}; out->code=SkillActionCode::invalid_review; out->mainDeltaCode=CatalogCode::incomplete;
    if (!review.expected || !review.pid || !review.tid || runtime.pid!=review.pid || runtime.tid!=review.tid ||
        runtime.now>=review.deadline || !runtime.codeVerified) return;
    out->code=SkillActionCode::invalid_context;
    if (!current || !SameScene(*current,*review.expected)) return;
    out->code=SkillActionCode::missing_binding;
    if (!source.read || !work || !calls.initializeMetadata || !calls.findDefault || !calls.stringNewLen || !calls.create) return;
    out->code=SkillActionCode::invalid_name;
    if (make_managed_name(nullptr,name).code==ge::templates::CallCode::invalid_name) return;
    CaptureTemplateCatalog(current,source,&work->capture,&work->before);
    out->code=SkillActionCode::baseline_capture_failed;
    if (work->before.code!=TemplateCaptureCode::complete) return;
    out->primaryCountBefore=work->before.primary.row_count; out->companionCountBefore=work->before.companion.row_count;
    out->code=SkillActionCode::local_capture_capacity;
    if (out->primaryCountBefore>=kMaxTemplateRows || out->companionCountBefore>=kMaxTemplateRows) return;
    out->code=SkillActionCode::default_table_unavailable;
    if (!Pointer(source,current->global+0x17688,out->defaultTable)) return;
    try {
        out->stage=SkillActionStage::metadata_initialization;
        for (auto group : {0x8a8aU,0xea00U}) {
            ++out->metadataCallsStarted; calls.initializeMetadata(group); ++out->metadataCallsCompleted;
        }
        out->code=SkillActionCode::context_changed;
        if (!Roots(source,*current,work->before.manager,out->defaultTable)) return;
        out->stage=SkillActionStage::default_lookup; out->defaultLookupCalled=true;
        out->defaultRecord=reinterpret_cast<std::uint64_t>(calls.findDefault(2));
        out->code=SkillActionCode::default_record_unavailable;
        if (!TemplatePointer(out->defaultRecord) || !Read(source,out->defaultRecord+0x24,out->defaultType) ||
            out->defaultType!=2 || !Read(source,out->defaultRecord+0x34,out->defaultValue)) return;
        out->stage=SkillActionStage::name_allocation; out->allocationCalled=true;
        const auto named=make_managed_name(calls.stringNewLen,name); out->nameCode=named.code;
        out->allocationCalled=named.allocationCalled; out->code=SkillActionCode::name_allocation_failed;
        if (named.code!=ge::templates::CallCode::returned) return;
        out->code=SkillActionCode::context_changed;
        std::uint32_t type=0,value=0;
        if (!Roots(source,*current,work->before.manager,out->defaultTable) ||
            !Read(source,out->defaultRecord+0x24,type) || type!=out->defaultType ||
            !Read(source,out->defaultRecord+0x34,value) || value!=out->defaultValue) return;
        out->stage=SkillActionStage::skill_creation; out->createCalled=true; out->outcomeUncertain=true;
        out->returnedResource=reinterpret_cast<std::uint64_t>(calls.create(named.managed_name,nullptr));
        out->stage=SkillActionStage::none; out->postCaptureAttempted=true;
        CaptureTemplateCatalog(current,source,&work->capture,&work->after);
        out->code=SkillActionCode::null_resource;
        if (!TemplatePointer(out->returnedResource)) return;
        out->code=SkillActionCode::post_capture_failed;
        if (work->after.code!=TemplateCaptureCode::complete) return;
        out->code=SkillActionCode::classes_unavailable;
        if (!Pointer(source,current->moduleBase+0x57d3ff8,out->observedMainClass) ||
            !Pointer(source,current->moduleBase+0x57c98f8,out->observedCompanionClass)) return;
        const auto delta=MainDelta(work->before,work->after,out->observedMainClass,out->returnedResource);
        out->mainDeltaCode=delta.code; out->code=SkillActionCode::main_delta_failed;
        if (delta.code!=CatalogCode::verified) return;
        out->createdId=delta.added.id; out->mainCatalogVerified=true;
        out->code=SkillActionCode::companion_delta_failed;
        if (!CompanionDelta(work->before,work->after,*out)) return;
        out->companionCatalogVerified=true; out->code=SkillActionCode::catalog_verified;
    } catch (...) {
        out->code=SkillActionCode::call_exception;
        if (out->createCalled) {
            out->postCaptureAttempted=true;
            CaptureTemplateCatalog(current,source,&work->capture,&work->after);
        }
    }
}
}
