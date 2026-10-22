#include "../binding_action.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <stdexcept>
#include <vector>

using namespace ge::templates;
namespace {
constexpr std::uint64_t module = 0x140000000ULL, owner = 0x100000, set = 0x110000, list = 0x120000;
constexpr std::uint64_t buckets = 0x130000, slots = 0x140000, items = 0x150000, wrapper = 0x160000, config = 0x180000;
constexpr std::uint64_t global = 0x300000, manager = 0x301000, main_dict = 0x310000, companion_dict = 0x320000;
constexpr std::uint64_t main_buckets = 0x330000, main_entries = 0x340000, companion_buckets = 0x350000, companion_entries = 0x360000;
constexpr std::uint64_t bag_resource = 0x390000, shop_resource = 0x391000;
constexpr std::uint64_t shop_list = 0x500000, shop_items = 0x510000, entry = 0x520000, reference = 0x530000;
constexpr std::uint64_t owner_class = 0x800000, wrapper_class = 0x810000, bag_class = 0x820000, shop_class = 0x830000;
constexpr std::uint64_t reference_class = 0x880000, bag_resource_class = 0x8a0000, shop_resource_class = 0x8b0000;
constexpr std::uint32_t entity_id = 31, bag_id = 1119879169, shop_id = 1136656385;
int checks = 0;
char16_t type_name[] = u"ClientBeyondConfigReferenceEditData";
void Check(bool ok, const char* label) { ++checks; if (!ok) { std::fprintf(stderr,"FAIL: %s\n",label); std::exit(1); } }
struct Memory {
    std::vector<unsigned char> bytes = std::vector<unsigned char>(0x800000);
    std::map<std::uint64_t,std::uint64_t> imageSlots;
    std::uint64_t fail_address = 0;
    unsigned reads = 0, attach_calls = 0, reference_calls = 0, add_calls = 0, setter_calls = 0, refresh_calls = 0;
    std::int32_t kind;
    bool throw_attach = false, wrong_reference = false, throw_setter = false, mutate_after_refresh = false;
    bool fail_post_catalog = false, mutate_catalog = false, bad_pool_class = false, wrong_classifier = false;
    unsigned initialize_calls = 0;
    template<class T> void Put(std::uint64_t p,T value) { std::memcpy(bytes.data()+static_cast<std::size_t>(p-owner),&value,sizeof(value)); }
    template<class T> T Get(std::uint64_t p) const { T value{}; std::memcpy(&value,bytes.data()+static_cast<std::size_t>(p-owner),sizeof(value)); return value; }
    static bool Read(void* context,std::uint64_t p,void* target,std::size_t size) noexcept {
        auto& m=*static_cast<Memory*>(context); ++m.reads;
        if(p==m.fail_address)return false;
        const auto slot=m.imageSlots.find(p);
        if(slot!=m.imageSlots.end() && size==8){std::memcpy(target,&slot->second,8);return true;}
        if(p<owner || p-owner>m.bytes.size() || size>m.bytes.size()-static_cast<std::size_t>(p-owner))return false;
        std::memcpy(target,m.bytes.data()+static_cast<std::size_t>(p-owner),size);return true;
    }
    void Dictionary(std::uint64_t d,std::uint64_t b,std::uint64_t e) {
        Put<std::uint64_t>(d,0x870000);Put(d+0x20,b);Put(d+0x28,e);Put<std::int32_t>(d+0x44,-1);
        Put<std::uint64_t>(b+0x18,7);Put<std::uint64_t>(e+0x18,7);
    }
    void AddTemplate(std::uint32_t id,std::uint64_t object,std::uint64_t klass,std::uint32_t subtype) {
        const auto n=Get<std::uint32_t>(main_dict+0x38),hash=id&0x7fffffffU;
        const auto bucket=main_buckets+0x20+(hash%7)*4;
        TemplateNativeEntry e{static_cast<std::int32_t>(hash),Get<std::int32_t>(bucket)-1,id,0,object};
        Put(main_entries+0x20+n*sizeof(e),e);Put(bucket,n+1);Put(main_dict+0x38,n+1);
        Put(object,klass);Put(object+0x1c,id);Put(object+0xb4,subtype);
    }
    void SetReference(std::uint32_t id,std::uint64_t p=reference) {
        Put(p,reference_class);Put<std::uint32_t>(p+0x18,(id>>30)&1);Put(p+0x1c,id);
    }
    void AddComponent() {
        const auto bucket=buckets+0x20+(static_cast<std::uint32_t>(kind)%7)*4;
        Put(slots+0x20,ge::component_attachment::NativeSetSlot{kind,-1,kind});Put<std::int32_t>(bucket,1);
        Put<std::uint32_t>(set+0x28,1);Put<std::uint32_t>(set+0x2c,1);Put<std::uint32_t>(set+0x34,1);
        Put(items+0x20,wrapper);Put<std::uint32_t>(list+0x18,1);Put<std::uint32_t>(list+0x1c,1);
        Put(wrapper,wrapper_class);Put(wrapper+0x20,owner);Put(wrapper+0x28,config);Put(wrapper+0x34,kind);
        Put<std::uint32_t>(wrapper+0x1c,0x40123456);Put<std::uint8_t>(wrapper+0x30,0);
        Put(config,kind==33?bag_class:shop_class);Put(config+0x18,wrapper);Put(config+0x20,owner);
        if(kind==35){Put(config+0x30,shop_list);Put<std::uint64_t>(shop_list,0x850000);Put(shop_list+0x10,shop_items);Put<std::uint64_t>(shop_items+0x18,4);}
    }
    void AddShopEntry(std::uint32_t id=0) {
        const auto count=Get<std::uint32_t>(shop_list+0x18);
        const auto p=entry+count*0x100,ref=reference+count*0x100;
        Put<std::uint64_t>(p,0x860000);Put(p+0x18,ref);Put<std::int32_t>(p+0x2c,7+static_cast<std::int32_t>(count));SetReference(id,ref);
        Put(shop_items+0x20+count*8,p);Put(shop_list+0x18,count+1);Put<std::uint32_t>(shop_list+0x1c,count+1);
    }
    explicit Memory(std::int32_t selectedKind):kind(selectedKind) {
        Put(owner,owner_class);Put(owner+0x30,set);Put(owner+0x68,list);Put<std::uint8_t>(owner+0x9c,1);
        Put<std::uint64_t>(set,0x840000);Put(set+0x10,buckets);Put<std::uint64_t>(set+0x18,0x850000);Put(set+0x20,slots);Put<std::int32_t>(set+0x30,-1);
        Put<std::uint64_t>(list,0x860000);Put(list+0x10,items);
        Put<std::uint64_t>(buckets+0x18,7);Put<std::uint64_t>(slots+0x18,7);Put<std::uint64_t>(items+0x18,7);
        Put(global+0xa420,manager);Put(manager+0x40,main_dict);Put(manager+0x10,companion_dict);
        Dictionary(main_dict,main_buckets,main_entries);Dictionary(companion_dict,companion_buckets,companion_entries);
        AddTemplate(bag_id,bag_resource,bag_resource_class,12);AddTemplate(shop_id,shop_resource,shop_resource_class,17);
        imageSlots={{module+kTemplateGlobalSlotRva,global},{module+0x57e9bd0,bag_resource_class},{module+0x57e9bf0,shop_resource_class},
            {module+0x57b0058,wrapper_class},{module+0x57dda88,bag_class},{module+0x57b1060,shop_class},{module+0x57b3280,reference_class}};
    }
};
Memory* active=nullptr;
void* __cdecl Attach(void* p,std::int32_t kind) {
    auto& m=*active;++m.attach_calls;
    Check(reinterpret_cast<std::uint64_t>(p)==owner && kind==m.kind,"attach exact selected owner/kind");
    m.AddComponent();if(m.throw_attach)throw std::runtime_error("attach");return reinterpret_cast<void*>(wrapper);
}
void* __cdecl MakeReference(void* typeName) {
    auto& m=*active;++m.reference_calls;
    Check(typeName==type_name,"reference pool receives exact type name");
    // Use a different object from the entry's initialized placeholder reference.
    m.SetReference(0,reference+0x800);
    if (m.bad_pool_class) m.Put(reference+0x800,bag_resource_class);
    return reinterpret_cast<void*>(reference+0x800);
}
void __cdecl InitializeReference(void* ref,std::uint32_t id) {
    auto& m=*active;++m.initialize_calls;
    Check(ref==reinterpret_cast<void*>(reference+0x800) && id==(m.kind==33?bag_id:shop_id),"native ID setter receives returned pool object and exact ID");
    m.SetReference(m.wrong_reference?id+1:id,reference+0x800);
    if (m.wrong_classifier) m.Put<std::uint32_t>(reference+0x800+0x18,0);
}
void* __cdecl AddEntry(void* p) {
    auto& m=*active;++m.add_calls;Check(reinterpret_cast<std::uint64_t>(p)==config && m.kind==35,"shop add only correct config");
    m.AddShopEntry();return reinterpret_cast<void*>(entry);
}
void __cdecl Set(void* p,std::uint32_t hash,void* ref) {
    auto& m=*active;++m.setter_calls;
    const bool shop=m.kind==35;
    Check(reinterpret_cast<std::uint64_t>(p)==(shop?entry:config) && hash==(shop?ge::component_binding::shop_reference_hash:ge::component_binding::bag_reference_hash),"formal field hash and target");
    if(m.throw_setter)throw std::runtime_error("setter");
    m.Put(reinterpret_cast<std::uint64_t>(p)+(shop?0x18:0x38),reinterpret_cast<std::uint64_t>(ref));
}
void __cdecl Refresh(void* p,std::int32_t flag,void* zero) {
    auto& m=*active;++m.refresh_calls;Check(reinterpret_cast<std::uint64_t>(p)==config && !flag && !zero,"formal dependency refresh arguments");
    if(m.mutate_after_refresh)m.Put<std::uint32_t>(reference+0x800+0x1c,(m.kind==33?bag_id:shop_id)+1);
    if(m.fail_post_catalog)m.fail_address=main_entries+0x20;
    if(m.mutate_catalog)m.Put<std::uint64_t>(bag_resource,0x8c0000);
}
GameContextSnapshot Baseline() {
    GameContextSnapshot b{};b.structSize=sizeof(b);b.version=1;b.status=GS_OK;b.flags=1951;b.moduleBase=module;b.global=global;
    b.currentContext=0x290000;b.contextManager=0x291000;b.saveManager=0x292000;b.peImageSize=0x6000000;b.reserved=1073741842;
    b.entityCaptured=b.entityValidEntries=1;auto& e=b.entities[0];e.id=e.dictionaryKey=entity_id;e.owner=owner;e.context=b.currentContext;e.flags=GE_ID_READ|GE_CONTEXT_MATCH|GE_KEY_MATCH|GE_CONTEXT_READ;return b;
}
BindingActionWorkspace workspace{};BindingActionResult result{};
struct Invocation {
    GameContextSnapshot current=Baseline(),expected=current;
    BindingActionReview review{42,73,200,&expected};BindingActionRuntime runtime{42,73,100,true};
    BindingActionCalls calls{Attach,{nullptr,AddEntry,Set,Set,Refresh,Refresh,MakeReference,InitializeReference,type_name}};
    BindingActionRequest request;
    explicit Invocation(std::int32_t kind):request{entity_id,kind==33?bag_id:shop_id,kind}{}
    BindingActionCode Run(Memory& m) {
        active=&m;std::memset(&workspace,0,sizeof(workspace));
        ExecuteBindingAction(&current,review,runtime,{&m,Memory::Read},calls,request,&workspace,&result);return result.code;
    }
};
void NoCalls(const Memory& m) { Check(!m.attach_calls && !m.reference_calls && !m.initialize_calls && !m.add_calls && !m.setter_calls && !m.refresh_calls,"all native work rejected before mutation"); }
}
int main() {
    for(const auto kind:{33,35}) {
        Memory m(kind);Invocation i(kind);
        Check(i.Run(m)==BindingActionCode::binding_verified,"absent component attach and bind verified");
        Check(m.attach_calls==1 && m.reference_calls==1 && m.initialize_calls==1 && m.setter_calls==1 && m.refresh_calls==1 && m.add_calls==(kind==35?1U:0U),"single ordered native mutations");
        Check(result.entityId==entity_id && result.componentId==0x40123456 && result.wrapper==wrapper && result.config==config &&
            result.templateResource==(kind==33?bag_resource:shop_resource),"native owner template and component IDs retained");
        Check(result.catalogVerified && result.templateVerified && result.componentVerified && result.postBindingVerified && result.catalogsUnchanged,"all independent readbacks retained");
        Check(result.outcomeUncertain && result.needsOwnerNotification && result.shopIndex==(kind==35?7:0),"preserve unknown owner notification and native shop index");
        Check(m.Get<std::uint8_t>(wrapper+0x30)==0,"do not force component enabled");
    }
    for(const auto kind:{33,35}) {
        Memory m(kind);Invocation i(kind);m.AddComponent();
        if(kind==33){m.SetReference(bag_id);m.Put(config+0x38,reference);}else m.AddShopEntry(shop_id);
        Check(i.Run(m)==BindingActionCode::reused && result.reused && result.postBindingVerified,"same template reused with exact readback");
        Check(!result.outcomeUncertain && !result.needsOwnerNotification && result.shopIndex==(kind==35?7:0),"reuse has no new mutation receipt");NoCalls(m);
    }
    for(const auto kind:{33,35}) {
        Memory m(kind);Invocation i(kind);m.AddComponent();
        if(kind==33){m.SetReference(bag_id+1);m.Put(config+0x38,reference);}else m.AddShopEntry(shop_id+1);
        Check(i.Run(m)==BindingActionCode::existing_template_conflict,"different template never overwritten");NoCalls(m);
    }
    {
        Memory m(35);Invocation i(35);m.AddComponent();m.AddShopEntry();
        Check(i.Run(m)==BindingActionCode::existing_unbound_shop_entry,"existing empty shop entry not duplicated");NoCalls(m);
    }
    {
        Memory m(35);Invocation i(35);m.AddComponent();m.AddShopEntry(shop_id);m.AddShopEntry(shop_id);
        Check(i.Run(m)==BindingActionCode::ambiguous_shop_entries,"multiple shops require explicit selection");NoCalls(m);
    }
    for(const auto kind:{33,35}) {
        Memory m(kind);Invocation i(kind);m.AddComponent();
        Check(i.Run(m)==BindingActionCode::binding_verified && !m.attach_calls && m.setter_calls==1,"existing blank component binds without attach");
    }
    {
        Memory m(35);Invocation i(35);i.request.templateId=bag_id;
        Check(i.Run(m)==BindingActionCode::invalid_request && !m.reads,"wrong business band rejected before reads");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);i.request.templateId=bag_id+1;
        Check(i.Run(m)==BindingActionCode::template_not_found,"nonexistent template never causes attach");NoCalls(m);
    }
    for(const auto wrongClass:{false,true}) {
        Memory m(35);Invocation i(35);
        if(wrongClass)m.Put<std::uint64_t>(shop_resource,bag_resource_class);else m.Put<std::uint32_t>(shop_resource+0xb4,12);
        Check(i.Run(m)==BindingActionCode::template_kind_mismatch,"actual resource class and subtype verified");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);m.imageSlots[module+0x57dda88]=0;
        Check(i.Run(m)==BindingActionCode::types_unavailable,"uninitialized metadata explicitly refused");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);i.calls.bind.refreshBagDependencies=nullptr;
        Check(i.Run(m)==BindingActionCode::missing_binding,"refresh preflight before attach");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);i.request.entityId++;
        Check(i.Run(m)==BindingActionCode::owner_not_found,"explicit entity must be in verified snapshot");NoCalls(m);
    }
    {
        Memory m(35);Invocation i(35);i.runtime.tid++;
        Check(i.Run(m)==BindingActionCode::invalid_review && !m.reads,"wrong game thread refused");NoCalls(m);
    }
    {
        Memory m(35);Invocation i(35);i.current.reserved++;
        Check(i.Run(m)==BindingActionCode::invalid_context && !m.reads,"changed level refused");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);m.fail_address=companion_entries+0x20;
        Check(i.Run(m)==BindingActionCode::catalog_failed,"partial companion capture refuses attach");NoCalls(m);
    }
    {
        Memory m(35);Invocation i(35);m.Put<std::uint32_t>(set+0x28,1);
        Check(i.Run(m)==BindingActionCode::components_failed,"divergent component structures refuse attach");NoCalls(m);
    }
    {
        Memory m(33);Invocation i(33);m.throw_attach=true;
        Check(i.Run(m)==BindingActionCode::attachment_failed && m.attach_calls==1 && !m.reference_calls && result.outcomeUncertain,"partial attach exception no binding or retry");
    }
    {
        Memory m(35);Invocation i(35);m.AddComponent();m.wrong_reference=true;
        Check(i.Run(m)==BindingActionCode::binding_failed && m.reference_calls==1 && !m.add_calls && !m.setter_calls,"incorrect reference ID rejected before shop add");
    }
    for (const auto kind : {33,35}) {
        Memory m(kind);Invocation i(kind);m.AddComponent();m.bad_pool_class=true;
        Check(i.Run(m)==BindingActionCode::binding_failed && m.reference_calls==1 && !m.initialize_calls && !m.setter_calls && !m.add_calls && !m.attach_calls,
              "wrong pooled class rejected before ID initializer or component mutation");
    }
    for (const auto kind : {33,35}) {
        Memory m(kind);Invocation i(kind);m.AddComponent();m.wrong_classifier=true;
        Check(i.Run(m)==BindingActionCode::binding_failed && m.initialize_calls==1 && !m.setter_calls && !m.add_calls && !m.attach_calls,
              "matching ID with incorrect classifier is rejected without reattaching empty component");
    }
    {
        Memory m(35);Invocation i(35);m.throw_setter=true;
        Check(i.Run(m)==BindingActionCode::binding_failed && m.add_calls==1 && m.setter_calls==1 && !m.refresh_calls && result.outcomeUncertain,"setter exception retains mutation and never retries");
    }
    {
        Memory m(33);Invocation i(33);m.mutate_after_refresh=true;
        Check(i.Run(m)==BindingActionCode::post_binding_failed && result.needsOwnerNotification,"post-refresh installed ID verified again");
    }
    {
        Memory m(33);Invocation i(33);m.fail_post_catalog=true;
        Check(i.Run(m)==BindingActionCode::post_catalog_failed && result.outcomeUncertain,"post catalog partial remains unaccepted");
    }
    {
        Memory m(35);Invocation i(35);m.mutate_catalog=true;
        Check(i.Run(m)==BindingActionCode::catalog_changed && result.outcomeUncertain,"unexpected template mutation detected");
    }
    std::printf("binding_action_test: %d checks passed; synthetic catalogs/components and stub calls only\n",checks);
}
