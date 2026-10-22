#include "../skill_action.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ge::templates;
using namespace ge::skills;
namespace {
constexpr std::uint64_t module=0x140000000ULL, global=0x100000, manager=0x120000;
constexpr std::uint64_t pd=0x130000, cd=0x140000, pb=0x150000, pe=0x160000, cb=0x180000, ce=0x190000;
constexpr std::uint64_t table=0x200000, record=0x210000, mainClass=0x310000, compClass=0x320000;
constexpr std::uint64_t oldMain=0x500000, newMain=0x500100, oldComp=0x600000, newComp=0x600100;
constexpr std::uint32_t oldId=0x41800001, newId=0x41800002;
constexpr auto name="MW_API_种植能力";
int checks=0;
void Check(bool value,const char* label) {
    ++checks; if (!value) { std::fprintf(stderr,"FAIL: %s\n",label); std::exit(1); }
}
enum class Behavior { success,no_main,wrong_class,old_main_changed,no_comp,wrong_parent,
    wrong_guid,wrong_comp_class,old_comp_changed,partial_post,throw_create,null_create,wrong_return,wrong_band };
struct Harness {
    std::vector<unsigned char> memory=std::vector<unsigned char>(0x800000);
    std::uint64_t globalSlot=global, failAddress=0;
    std::uint32_t ownId=7;
    int reads=0,inits=0,defaults=0,allocations=0,creates=0;
    bool nullDefault=false,nullName=false,changeGlobal=false,changeDefault=false;
    bool throwMetadata=false,throwDefault=false,throwName=false;
    std::string order;
    Behavior behavior=Behavior::success;
    template<class T> void Put(std::uint64_t at,T value) { std::memcpy(memory.data()+at-global,&value,sizeof(value)); }
    template<class T> T Get(std::uint64_t at) const { T value{};std::memcpy(&value,memory.data()+at-global,sizeof(value));return value; }
    static bool Read(void* context,std::uint64_t at,void* target,std::size_t size) noexcept {
        auto& h=*static_cast<Harness*>(context); ++h.reads;
        if (at==h.failAddress) return false;
        std::uint64_t value=0; bool slot=true;
        if (at==module+kTemplateGlobalSlotRva) value=h.globalSlot;
        else if (at==module+0x57d3ff8) value=mainClass;
        else if (at==module+0x57c98f8) value=compClass;
        else slot=false;
        if (slot && size==8) {std::memcpy(target,&value,8);return true;}
        if (at<global || at-global>h.memory.size() || size>h.memory.size()-static_cast<std::size_t>(at-global)) return false;
        std::memcpy(target,h.memory.data()+at-global,size);return true;
    }
    void Dictionary(std::uint64_t dict,std::uint64_t buckets,std::uint64_t entries) {
        Put<std::uint64_t>(dict,0x300000);Put(dict+0x20,buckets);Put(dict+0x28,entries);
        Put<std::int32_t>(dict+0x44,-1);Put<std::uint64_t>(buckets+0x18,7);Put<std::uint64_t>(entries+0x18,7);
    }
    void Add(std::uint64_t dict,std::uint64_t buckets,std::uint64_t entries,std::uint32_t key,std::uint64_t value) {
        const auto count=Get<std::uint32_t>(dict+0x38), hash=key&0x7fffffffU;
        const auto bucket=buckets+0x20+(hash%Get<std::uint64_t>(buckets+0x18))*4;
        const TemplateNativeEntry entry{static_cast<std::int32_t>(hash),Get<std::int32_t>(bucket)-1,key,0,value};
        Put(entries+0x20+count*sizeof(entry),entry);Put(bucket,count+1);
        Put(dict+0x38,count+1);Put(dict+0x3c,Get<std::uint32_t>(dict+0x3c)+1);
    }
    void Main(std::uint64_t resource,std::uint32_t id) {
        Put(resource,mainClass);Put(resource+0x1c,id);Put<std::uint32_t>(resource+0xb4,6);Add(pd,pb,pe,id,resource);
    }
    void Companion(std::uint64_t resource,std::uint32_t id,std::uint32_t own) {
        Put(resource,compClass);Put(resource+0x1c,own);Put(resource+0xa8,id);
        Put<std::uint32_t>(resource+0x10,0);Put<std::uint32_t>(resource+0x14,1);Put<std::uint32_t>(resource+0x18,4);
        Add(cd,cb,ce,id,resource);
    }
    Harness() {
        Put(global+0xa420,manager);Put(manager+0x40,pd);Put(manager+0x10,cd);Put(global+0x17688,table);
        Put<std::uint32_t>(record+0x24,2);Put<std::uint32_t>(record+0x34,123);
        Dictionary(pd,pb,pe);Dictionary(cd,cb,ce);Main(oldMain,oldId);Companion(oldComp,oldId,9);
    }
};
Harness* active=nullptr;
SkillActionResult result{};
SkillActionWorkspace workspace{};
void __cdecl Metadata(std::uint32_t group) {
    auto& h=*active;++h.inits;h.order+='M';
    Check(group==(h.inits==1?0x8a8aU:0xea00U),"only exact skill metadata groups");
    Check(result.metadataCallsStarted==static_cast<std::uint32_t>(h.inits) &&
        result.metadataCallsCompleted+1==result.metadataCallsStarted && result.stage==SkillActionStage::metadata_initialization,
        "caller owns in-flight metadata progress");
    if (h.throwMetadata) throw std::runtime_error("metadata");
}
void* __cdecl Default(std::int32_t filter) {
    auto& h=*active;++h.defaults;h.order+='D';
    Check(filter==2 && result.defaultLookupCalled && !result.createCalled && result.stage==SkillActionStage::default_lookup,
        "native defaults filter and caller-owned progress");
    if (h.throwDefault) throw std::runtime_error("default");
    return h.nullDefault?nullptr:reinterpret_cast<void*>(record);
}
void* __cdecl Allocate(const char* text,std::int32_t length) {
    auto& h=*active;++h.allocations;h.order+='N';
    Check(std::string(text,static_cast<std::size_t>(length))==name && result.allocationCalled &&
        result.stage==SkillActionStage::name_allocation,"UTF8 bytes and caller-owned allocation progress");
    if (h.throwName) throw std::runtime_error("name");
    if (h.changeGlobal) h.globalSlot+=8;
    if (h.changeDefault) h.Put<std::uint32_t>(record+0x34,124);
    return h.nullName?nullptr:reinterpret_cast<void*>(0x900000);
}
void* __cdecl Create(void* text,void* source) {
    auto& h=*active;++h.creates;h.order+='C';
    Check(text==reinterpret_cast<void*>(0x900000) && !source,"full helper receives name and fixed null source");
    Check(result.createCalled && result.outcomeUncertain && result.stage==SkillActionStage::skill_creation,
        "attempt and uncertainty retained before helper entry including native SEH");
    const auto id=h.behavior==Behavior::wrong_band?0x42000002U:newId;
    if (h.behavior!=Behavior::no_main) h.Main(newMain,id);
    if (h.behavior!=Behavior::no_comp) h.Companion(newComp,id,h.ownId);
    if (h.behavior==Behavior::wrong_class) h.Put<std::uint64_t>(newMain,mainClass+8);
    if (h.behavior==Behavior::old_main_changed) h.Put<std::uint64_t>(oldMain,mainClass+8);
    if (h.behavior==Behavior::wrong_parent) h.Put(newComp+0xa8,oldId);
    if (h.behavior==Behavior::wrong_guid) h.Put<std::uint32_t>(newComp+0x18,3);
    if (h.behavior==Behavior::wrong_comp_class) h.Put<std::uint64_t>(newComp,compClass+8);
    if (h.behavior==Behavior::old_comp_changed) h.Put<std::uint32_t>(oldComp+0x1c,8);
    if (h.behavior==Behavior::partial_post) h.failAddress=ce+0x20;
    if (h.behavior==Behavior::throw_create) throw std::runtime_error("partial registration");
    if (h.behavior==Behavior::null_create) return nullptr;
    return reinterpret_cast<void*>(h.behavior==Behavior::wrong_return?oldMain:newMain);
}
GameContextSnapshot Baseline() {
    GameContextSnapshot b{};b.structSize=sizeof(b);b.version=1;b.status=GS_OK;b.flags=1951;
    b.moduleBase=module;b.global=global;b.peImageSize=0x20000000;b.peTimestamp=123;
    b.currentContext=0x270000;b.contextManager=0x280000;b.saveManager=0x290000;b.reserved=1073741842;
    b.entityCaptured=b.entityValidEntries=1;b.entities[0].id=5;b.entities[0].owner=0x2a0000;b.entities[0].context=b.currentContext;
    return b;
}
struct Invocation {
    GameContextSnapshot current=Baseline(),expected=current;
    SkillActionReview review{42,73,200,&expected};SkillActionRuntime runtime{42,73,100,true};
    SkillActionBindings calls{Metadata,Default,Allocate,Create};
    SkillActionCode Run(Harness& h,std::string_view text=name,bool reset=true) {
        active=&h;if (reset) {result={};std::memset(&workspace,0,sizeof(workspace));}
        ExecuteSkillAction(&current,review,runtime,{&h,Harness::Read},calls,text,&workspace,&result);return result.code;
    }
};
void NoCreate(const Harness& h) {Check(!h.creates && !result.createCalled && !result.outcomeUncertain,"no registration attempt before gates");}
void OneCreate(const Harness& h) {Check(h.creates==1 && result.createCalled && result.outcomeUncertain,"one attempt; no retry or persistence claim");}
}
int main() {
    {
        Harness h;Invocation i;
        Check(i.Run(h)==SkillActionCode::catalog_verified,"complete primary and companion deltas accepted");
        Check(h.order=="MMDNC" && result.metadataCallsCompleted==2,"full-helper call sequence");
        Check(result.createdId==newId && result.returnedResource==newMain && result.companionOwnId==7 &&
            result.companionResource==newComp && result.mainCatalogVerified && result.companionCatalogVerified,
            "actual identities read back, companion own ID independently recorded");
        Check(result.observedMainClass==mainClass && result.observedCompanionClass==compClass &&
            result.defaultRecord==record && result.defaultValue==123 && result.postCaptureAttempted,
            "observed class and default evidence retained");OneCreate(h);
        Check(i.Run(h,name,false)==SkillActionCode::catalog_verified && h.creates==1,"retained attempt cannot replay");
    }
    for (int reason=0;reason<4;++reason) {
        Harness h;Invocation i;
        if (reason==0) ++i.runtime.pid;if(reason==1) ++i.runtime.tid;
        if (reason==2) i.runtime.now=i.review.deadline;if(reason==3) i.runtime.codeVerified=false;
        Check(i.Run(h)==SkillActionCode::invalid_review && !h.reads && h.order.empty(),"identity deadline and profile before reads");NoCreate(h);
    }
    {
        Harness h;Invocation i;++i.current.entities[0].id;
        Check(i.Run(h)==SkillActionCode::invalid_context && !h.reads,"entity baseline mismatch refused");NoCreate(h);
    }
    {
        Harness h;Invocation i;i.calls.findDefault=nullptr;
        Check(i.Run(h)==SkillActionCode::missing_binding && !h.reads,"missing native binding refused");NoCreate(h);
    }
    for (const auto text:{std::string{},std::string("a\0b",3),std::string(129,'x')}) {
        Harness h;Invocation i;
        Check(i.Run(h,text)==SkillActionCode::invalid_name && !h.reads,"invalid UTF8 name shape refused before native calls");NoCreate(h);
    }
    {
        Harness h;Invocation i;h.failAddress=ce+0x20;
        Check(i.Run(h)==SkillActionCode::baseline_capture_failed && h.order.empty(),"incomplete baseline refuses native calls");NoCreate(h);
    }
    {
        Harness h;Invocation i;
        h.Put<std::uint32_t>(pd+0x38,0);h.Put<std::uint32_t>(pd+0x3c,0);
        std::memset(h.memory.data()+pb+0x20-global,0,kMaxTemplateRows*4);
        h.Put<std::uint64_t>(pb+0x18,kMaxTemplateRows);h.Put<std::uint64_t>(pe+0x18,kMaxTemplateRows);
        for(std::uint32_t row=0;row<kMaxTemplateRows;++row) h.Main(oldMain+row*0x100,oldId+row);
        Check(i.Run(h)==SkillActionCode::local_capture_capacity && result.primaryCountBefore==kMaxTemplateRows && h.order.empty(),
            "local full receipt capacity stops before native entry without inventing official skill limit");NoCreate(h);
    }
    {
        Harness h;Invocation i;h.Put<std::uint64_t>(global+0x17688,0);
        Check(i.Run(h)==SkillActionCode::default_table_unavailable && h.order.empty(),"missing actual default table stops initialization");NoCreate(h);
    }
    for(int reason=0;reason<3;++reason) {
        Harness h;Invocation i;h.nullDefault=reason==0;
        if(reason==1) h.Put<std::uint32_t>(record+0x24,3);if(reason==2) h.failAddress=record+0x34;
        Check(i.Run(h)==SkillActionCode::default_record_unavailable && !h.allocations,"unavailable wrong-filter or unreadable default record refused");NoCreate(h);
    }
    for(int reason=0;reason<2;++reason) {
        Harness h;Invocation i;h.changeGlobal=reason==0;h.changeDefault=reason==1;
        Check(i.Run(h)==SkillActionCode::context_changed && !h.creates,"fresh roots and selected default checked after name allocation");NoCreate(h);
    }
    {
        Harness h;Invocation i;h.nullName=true;
        Check(i.Run(h)==SkillActionCode::name_allocation_failed && result.allocationCalled,"null managed name separately classified");NoCreate(h);
    }
    for(int reason=0;reason<3;++reason) {
        Harness h;Invocation i;h.throwMetadata=reason==0;h.throwDefault=reason==1;h.throwName=reason==2;
        Check(i.Run(h)==SkillActionCode::call_exception && result.stage!=SkillActionStage::none,"pre-create exceptions retain stage without registration claim");NoCreate(h);
    }
    for(const auto behavior:{Behavior::no_main,Behavior::wrong_class,Behavior::old_main_changed,Behavior::wrong_return,Behavior::wrong_band}) {
        Harness h;Invocation i;h.behavior=behavior;
        Check(i.Run(h)==SkillActionCode::main_delta_failed && !result.mainCatalogVerified,"primary count class identity band and unchanged previous resources checked");OneCreate(h);
    }
    for(const auto behavior:{Behavior::no_comp,Behavior::wrong_guid,Behavior::wrong_comp_class,Behavior::old_comp_changed}) {
        Harness h;Invocation i;h.behavior=behavior;
        Check(i.Run(h)==SkillActionCode::companion_delta_failed && result.mainCatalogVerified && !result.companionCatalogVerified,
            "companion delta class domain and old identity checked");OneCreate(h);
    }
    {
        Harness h;Invocation i;h.behavior=Behavior::wrong_parent;
        const auto code=i.Run(h);Check(code==SkillActionCode::post_capture_failed || code==SkillActionCode::companion_delta_failed,"wrong companion parent rejected");OneCreate(h);
    }
    {
        Harness h;Invocation i;h.behavior=Behavior::partial_post;
        Check(i.Run(h)==SkillActionCode::post_capture_failed && !result.mainCatalogVerified,"partial post state not accepted");OneCreate(h);
    }
    {
        Harness h;Invocation i;h.behavior=Behavior::null_create;
        Check(i.Run(h)==SkillActionCode::null_resource && result.postCaptureAttempted && workspace.after.primary.row_count==2,
            "null return does not erase partial registration evidence");OneCreate(h);
    }
    {
        Harness h;Invocation i;h.behavior=Behavior::throw_create;
        Check(i.Run(h)==SkillActionCode::call_exception && result.stage==SkillActionStage::skill_creation && result.postCaptureAttempted &&
            workspace.after.primary.row_count==2 && workspace.after.companion.row_count==2,
            "exception during registration retains attempted phase and partial raw state");OneCreate(h);
    }
    std::printf("skill_action_test: %d checks passed; synthetic memory and host stubs only\n",checks);
}
