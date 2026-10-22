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
void Check(bool ok, const char* label) { ++checks; if (!ok) { std::fprintf(stderr,"FAIL: %s\n",label); std::exit(1); } }
struct Memory {
    std::vector<unsigned char> bytes = std::vector<unsigned char>(0x800000);
    std::map<std::uint64_t,std::uint64_t> imageSlots;
    std::uint64_t fail_address = 0;
    unsigned reads = 0, attach_calls = 0, reference_calls = 0, add_calls = 0, setter_calls = 0, refresh_calls = 0;
    std::int32_t kind;
    bool throw_attach = false, wrong_reference = false, throw_setter = false, mutate_after_refresh = false;
    bool fail_post_catalog = false, mutate_catalog = false;
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
void* __cdecl MakeReference(std::uint32_t id) {
    auto& m=*active;++m.reference_calls;
    Check(id==(m.kind==33?bag_id:shop_id),"reference factory receives explicit template ID");
    // Use a different object from the entry's initialized placeholder reference.
    m.SetReference(m.wrong_reference?id+1:id,reference+0x800);return reinterpret_cast<void*>(reference+0x800);
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
    BindingActionCalls calls{Attach,{MakeReference,AddEntry,Set,Set,Refresh,Refresh}};
    BindingActionRequest request;
    explicit Invocation(std::int32_t kind):request{entity_id,kind==33?bag_id:shop_id,kind}{}
    BindingActionCode Run(Memory& m) {
        active=&m;std::memset(&workspace,0,sizeof(workspace));
        ExecuteBindingAction(&current,review,runtime,{&m,Memory::Read},calls,request,&workspace,&result);return result.code;
    }
};
void NoCalls(const Memory& m) { Check(!m.attach_calls && !m.reference_calls && !m.add_calls && !m.setter_calls && !m.refresh_calls,"all native work rejected before mutation"); }
}

namespace {
constexpr std::uint64_t editManager=0x600000,editList=0x610000,editItems=0x620000;
constexpr std::uint64_t editClass=0x630000,editRecord=0x640000,editSnapshot=0x650000,literal=0x660000,transaction=0x670000;
unsigned opens=0,snapshots=0,notifies=0,closes=0;
int failStage=0;bool skipDirty=false,extraRecord=false,changeEnable=false,partialAfterNotify=false;
void PrepareEdit(Memory& m) {
    opens=snapshots=notifies=closes=0;failStage=0;skipDirty=extraRecord=changeEnable=partialAfterNotify=false;
    m.Put(global+0xecd0,editManager);m.Put(editManager+0x18,editList);m.Put(editList+0x10,editItems);
    m.Put<std::uint64_t>(editItems+0x18,8);
    m.imageSlots[module+0x5812cf8]=editClass;m.imageSlots[module+0x59fe288]=literal;
    m.Put(wrapper_class+0x120,module+0x106ffc40);m.Put(wrapper_class+0x130,module+0x106ff240);
    m.Put(bag_class+0x378,module+0x10ed3250);m.Put(shop_class+0x378,module+0x82514f0);
    m.Put(bag_class+0x350,module+0xb613ce0);m.Put(shop_class+0x350,module+0xb613ce0);m.Put(owner_class+0x280,module+0x112386f0);
    m.Put<std::int32_t>(literal+0x10,21);const char16_t text[]=u"modifyBeyondComponent";
    for(unsigned i=0;i<21;++i)m.Put(literal+0x14+i*2,text[i]);
}
void* __cdecl OpenEdit(void* label,bool a,bool b) {
    ++opens;Check(!label&&!a&&!b,"native open exact null/false/false");
    Check(!active->setter_calls,"snapshot transaction opens before setter");
    if(failStage==1)throw std::runtime_error("open");
    active->Put<std::int32_t>(editManager+0x34,1);return reinterpret_cast<void*>(transaction);
}
void __cdecl SnapshotEdit(void* object,void* name,std::int32_t mode) {
    ++snapshots;Check(reinterpret_cast<std::uint64_t>(object)==wrapper&&reinterpret_cast<std::uint64_t>(name)==literal&&!mode,"snapshot wrapper and actual native literal");
    Check(!active->setter_calls&&opens==1,"snapshot is before any setter");
    if(failStage==2)throw std::runtime_error("snapshot");
    auto& m=*active;auto count=m.Get<std::uint32_t>(editList+0x18);
    for(unsigned i=0;i<count;++i)if(m.Get<std::uint64_t>(m.Get<std::uint64_t>(editItems+0x20+i*8)+0x18)==wrapper)return;
    m.Put(editRecord,editClass);m.Put(editRecord+0x18,wrapper);m.Put(editRecord+0x28,editSnapshot);
    m.Put(editItems+0x20+count*8,editRecord);m.Put(editList+0x18,count+1);m.Put(editList+0x1c,count+1);
    if(extraRecord){m.Put(editItems+0x20+(count+1)*8,editRecord);m.Put(editList+0x18,count+2);}
}
void __cdecl NotifyEdit(void* managerArg,void* object) {
    ++notifies;Check(reinterpret_cast<std::uint64_t>(managerArg)==editManager&&reinterpret_cast<std::uint64_t>(object)==wrapper,"post uses edit manager and same wrapper");
    Check(active->setter_calls==1&&!active->refresh_calls,"notification replaces separate dependency refresh");
    if(failStage==3)throw std::runtime_error("notify");
    Refresh(reinterpret_cast<void*>(config),0,nullptr);
    if(!skipDirty)active->Put<std::uint8_t>(editRecord+0x30,1);
    if(changeEnable)active->Put<std::uint8_t>(wrapper+0x30,1);
    if(partialAfterNotify)active->fail_address=editRecord+0x30;
}
void __cdecl CloseEdit(void* handle) {
    ++closes;Check(reinterpret_cast<std::uint64_t>(handle)==transaction,"close only returned transaction");
    Check(notifies==1&&active->Get<std::uint8_t>(editRecord+0x30)==1,"dirty readback precedes close");
    if(failStage==4)throw std::runtime_error("close");
    active->Put<std::int32_t>(editManager+0x34,0);active->Put<std::uint32_t>(editList+0x18,0);active->Put<std::uint32_t>(editList+0x1c,10);
}
void Configure(Invocation& i){i.calls.edit={OpenEdit,SnapshotEdit,NotifyEdit,CloseEdit};i.calls.requireEditTransaction=true;}
}
int main(){
    for(int kind:{33,35})for(bool existing:{false,true}){
        Memory m(kind);Invocation i(kind);PrepareEdit(m);Configure(i);if(existing)m.AddComponent();changeEnable=true;
        Check(i.Run(m)==BindingActionCode::binding_verified,"transactional binding full action succeeds");
        Check(opens==1&&snapshots==1&&notifies==1&&closes==1&&m.refresh_calls==1,"one complete transaction and exactly one refresh");
        Check(result.edit.snapshotVerified&&result.edit.notificationVerified&&result.edit.closeVerified&&!result.edit.transactionMayBeOpen,"real pending-record readbacks retained");
        Check(!result.binding.dependencyRefreshCalled&&!result.binding.needsDependencyRefresh&&!result.needsOwnerNotification,"fields-only path avoids old direct refresh");
        Check(result.edit.needsPersistenceAcceptance&&result.outcomeUncertain&&result.catalogsUnchanged,"notification is not disk save acceptance");
        Check(workspace.postComponents.rows[0].enabled==1,"native inheritance enable change read back");
        Check(m.attach_calls==(existing?0U:1U),"attach only if missing");
    }
    for(int phase:{1,2,3,4}){
        Memory m(35);Invocation i(35);PrepareEdit(m);Configure(i);m.AddComponent();failStage=phase;
        auto code=i.Run(m);Check(code==(phase<=2?BindingActionCode::edit_begin_failed:BindingActionCode::edit_complete_failed),"precise failure phase returned");
        Check(result.edit.code==ge::component_edit::Code::call_exception&&result.edit.transactionMayBeOpen&&result.outcomeUncertain,"called state survives exception");
        Check(opens==1&&snapshots==(phase>=2?1U:0U)&&notifies==(phase>=3?1U:0U)&&closes==(phase>=4?1U:0U),"no cleanup calls or retries after exception");
    }
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);m.throw_setter=true;
     Check(i.Run(m)==BindingActionCode::binding_failed&&result.edit.snapshotVerified&&!notifies&&!closes&&result.edit.transactionMayBeOpen,"partial setter does not invent close/notify success");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);skipDirty=true;
     Check(i.Run(m)==BindingActionCode::edit_complete_failed&&notifies==1&&!closes,"return without dirty readback is not accepted");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);partialAfterNotify=true;
     Check(i.Run(m)==BindingActionCode::edit_complete_failed&&notifies==1&&!closes,"partial post-notify read prevents close");}
    {Memory m(35);Invocation i(35);PrepareEdit(m);Configure(i);extraRecord=true;
     Check(i.Run(m)==BindingActionCode::edit_begin_failed&&!m.setter_calls&&!notifies&&!closes,"unexpected pending record before setter rejected");}
    {Memory m(35);Invocation i(35);PrepareEdit(m);Configure(i);m.Put<std::uint64_t>(owner_class+0x280,module+1);
     Check(i.Run(m)==BindingActionCode::edit_environment_failed&&!opens&&!m.attach_calls,"unknown owner notification target rejects before attach");}
    {Memory m(35);Invocation i(35);PrepareEdit(m);Configure(i);m.Put<std::int32_t>(editManager+0x34,1);
     Check(i.Run(m)==BindingActionCode::edit_environment_failed&&!opens&&!m.attach_calls,"active native transaction rejected before attachment");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);m.AddComponent();m.SetReference(bag_id);m.Put(config+0x38,reference);
     Check(i.Run(m)==BindingActionCode::reused&&!opens&&!snapshots&&!notifies&&!closes,"already bound template reuses without new transaction");
     Check(result.catalogsUnchanged&&workspace.postComponents.code==ge::component_attachment::CaptureCode::complete&&workspace.afterCatalog.code==TemplateCaptureCode::complete,"reuse retains independent post components and both catalogs");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);m.Put<char16_t>(literal+0x14,u'X');
     Check(i.Run(m)==BindingActionCode::edit_environment_failed&&!opens&&!m.attach_calls,"wrong metadata literal rejected before mutations");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);m.AddComponent();
     m.Put(editManager+0x10,editSnapshot+0x1000);m.Put(editManager+0x20,editSnapshot+0x2000); // opaque nonempty undo/redo roots
     m.Put(editRecord,editClass);m.Put(editRecord+0x18,wrapper);m.Put(editRecord+0x28,editSnapshot);m.Put(editItems+0x20,editRecord);m.Put<std::uint32_t>(editList+0x18,1);
     Check(i.Run(m)==BindingActionCode::binding_verified&&result.edit.before.targetCount==1&&result.edit.afterSnapshot.count==1,"native snapshot dedup and prior history are allowed");
     Check(m.Get<std::uint64_t>(editManager+0x10)==editSnapshot+0x1000,"history is not cleared by this layer");}
    {Memory m(33);Invocation i(33);PrepareEdit(m);Configure(i);m.AddComponent();active=&m;
     ge::component_edit::Evidence e{module,global,owner,wrapper,config,33,true};ge::component_edit::Result out{};
     ge::component_edit::BeginComponentEdit({&m,Memory::Read},i.calls.edit,e,&out);
     ge::component_edit::BeginComponentEdit({&m,Memory::Read},i.calls.edit,e,&out);
     Check(out.code==ge::component_edit::Code::duplicate_attempt&&opens==1&&snapshots==1,"same result cannot replay begin");}
    std::printf("binding_edit_test: %d checks passed; synthetic memory/stub native calls only\n",checks);return 0;
}
