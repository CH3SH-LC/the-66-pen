// Independent synthetic host. This process is not Genshin or an editor adapter.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "../native/game_executor.h"
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <thread>
#include <vector>

static int checks=0;
static int failures=0;
static void check(bool ok,const char* name) {
    ++checks;
    if(!ok) { ++failures; std::cerr << "FAIL: " << name << '\n'; }
}
struct SyntheticHost {
    GE_Executor* executor=nullptr;
    GE_Scene scene{42,7};
    DWORD owner=GetCurrentThreadId();
    std::atomic<unsigned> creates{0},saves{0},reads{0},wrong_thread{0};
    bool fail=false,throw_execute=false,throw_read=false,reenter=false;
    uint64_t read_reenter_id=0;
    DWORD read_delay=0;
};
static int32_t GE_CALL read_scene(void* context,GE_Scene* state) {
    auto& h=*static_cast<SyntheticHost*>(context);
    ++h.reads;
    if(GetCurrentThreadId()!=h.owner) ++h.wrong_thread;
    if(h.read_reenter_id) {
        GE_Result pending{}; uint32_t n=99;
        check(GE_GetResult(h.executor,h.read_reenter_id,&pending)==GE_OK && pending.state==GE_RUNNING,"read_scene can read RUNNING");
        check(GE_Pump(h.executor,1,&n)==GE_BUSY && n==0,"read_scene recursive Pump rejected");
        check(GE_Unbind(h.executor)==GE_BUSY,"read_scene cannot unbind");
        check(GE_Destroy(h.executor)==GE_BUSY,"read_scene cannot destroy");
    }
    if(h.throw_read) throw std::runtime_error("synthetic read failure");
    if(h.read_delay) Sleep(h.read_delay);
    *state=h.scene; return 0;
}
static int32_t GE_CALL execute(void* context,const GE_Request* request,GE_AdapterResult* result) {
    auto& h=*static_cast<SyntheticHost*>(context);
    if(GetCurrentThreadId()!=h.owner) ++h.wrong_thread;
    if(request->operation==GE_CREATE_INSTANCE) ++h.creates; else ++h.saves;
    if(h.reenter) {
        GE_Result pending{}; uint32_t n=99;
        check(GE_GetResult(h.executor,request->request_id,&pending)==GE_OK && pending.state==GE_RUNNING,"callback can read RUNNING");
        check(GE_Submit(h.executor,request,&pending)==GE_OK && pending.state==GE_RUNNING,"callback duplicate is RUNNING without reexecution");
        check(GE_Pump(h.executor,1,&n)==GE_BUSY && n==0,"recursive Pump rejected");
        check(GE_Unbind(h.executor)==GE_BUSY,"callback cannot unbind");
        check(GE_Destroy(h.executor)==GE_BUSY,"callback cannot destroy");
        std::thread producer([&] {
            GE_Result concurrent{};
            check(GE_Submit(h.executor,request,&concurrent)==GE_OK && concurrent.state==GE_RUNNING,"concurrent Submit during callback is cached");
            check(GE_GetResult(h.executor,request->request_id,&concurrent)==GE_OK && concurrent.state==GE_RUNNING,"concurrent GetResult during callback");
        }); producer.join();
    }
    if(h.throw_execute) throw std::runtime_error("synthetic operation failure");
    result->entity_id=request->operation==GE_CREATE_INSTANCE ? 1234 : 0;
    result->detail_code=h.fail ? 901 : 0;
    strcpy_s(result->message,"synthetic host executor receipt; not game/GIL acceptance");
    return h.fail ? 5 : 0;
}
static GE_Adapter adapter(SyntheticHost& host) {
    GE_Adapter a{}; a.struct_size=sizeof(a); a.abi_version=GE_ABI_VERSION;
    a.context=&host; a.read_scene=read_scene; a.create_instance=execute; a.save_level=execute;
    return a;
}
static GE_Request request(uint64_t id,uint32_t operation=GE_CREATE_INSTANCE) {
    GE_Request r{}; r.struct_size=sizeof(r); r.operation=operation;
    r.request_id=id; r.scene_id=42; r.scene_revision=7; r.ttl_ms=10000;
    if(operation==GE_CREATE_INSTANCE) { r.template_id=17; r.scale[0]=r.scale[1]=r.scale[2]=1; }
    return r;
}
static void pump(SyntheticHost& host,uint32_t expected=1) {
    uint32_t count=99;
    check(GE_Pump(host.executor,GE_QUEUE_CAPACITY,&count)==GE_OK && count==expected,"owner pumps expected count");
}
static GE_Result result(SyntheticHost& host,uint64_t id) {
    GE_Result r{}; check(GE_GetResult(host.executor,id,&r)==GE_OK,"GetResult finds accepted id"); return r;
}
static void basic_lifecycle() {
    SyntheticHost host; GE_Result out{}; auto r=request(1); uint32_t n=9;
    check(GE_Create(&host.executor)==GE_OK,"Create");
    check(GE_Submit(host.executor,&r,&out)==GE_UNAVAILABLE,"unbound Submit unavailable");
    check(GE_Pump(host.executor,1,&n)==GE_UNAVAILABLE && n==0,"unbound Pump unavailable");
    check(GE_GetResult(host.executor,1,&out)==GE_NOT_FOUND,"unaccepted id absent");
    auto a=adapter(host); a.abi_version=99;
    check(GE_Bind(host.executor,&a)==GE_INVALID,"wrong adapter ABI rejected");
    a=adapter(host); check(GE_Bind(host.executor,&a)==GE_OK,"Bind owner");
    check(GE_Bind(host.executor,&a)==GE_BUSY,"cannot replace bound adapter");
    std::thread submitter([&] {
        GE_Result queued{}; uint32_t count=99;
        check(GE_Submit(host.executor,&r,&queued)==GE_OK && queued.state==GE_QUEUED,"different thread submits");
        check(GE_Pump(host.executor,1,&count)==GE_WRONG_THREAD && count==0,"different thread cannot pump");
        check(GE_Unbind(host.executor)==GE_WRONG_THREAD,"different thread cannot unbind");
        check(GE_Destroy(host.executor)==GE_WRONG_THREAD,"different thread cannot destroy bound executor");
    }); submitter.join();
    check(host.creates==0 && host.reads==0,"Submit executes no callbacks");
    check(GE_Submit(host.executor,&r,&out)==GE_OK && out.state==GE_QUEUED,"queued duplicate cached");
    auto conflict=r; conflict.position[0]=1;
    check(GE_Submit(host.executor,&conflict,&out)==GE_ID_CONFLICT,"different parameters conflict");
    host.reenter=true; host.read_reenter_id=1; pump(host); host.reenter=false; host.read_reenter_id=0;
    out=result(host,1);
    check(out.state==GE_COMPLETED && out.entity_id==1234 && host.creates==1 && host.wrong_thread==0,"callback executes once on owner");
    check(GE_Submit(host.executor,&r,&out)==GE_OK && out.state==GE_COMPLETED && host.creates==1,"completed duplicate cached");
    // Padding is deliberately different; equality must not memcmp the struct.
    GE_Request padded; std::memset(&padded,0xA5,sizeof(padded));
    padded.struct_size=r.struct_size; padded.operation=r.operation; padded.request_id=r.request_id;
    padded.scene_id=r.scene_id; padded.scene_revision=r.scene_revision; padded.ttl_ms=r.ttl_ms; padded.template_id=r.template_id;
    for(unsigned i=0;i<3;++i) {padded.position[i]=r.position[i]; padded.rotation[i]=r.rotation[i]; padded.scale[i]=r.scale[i];}
    check(GE_Submit(host.executor,&padded,&out)==GE_OK && out.state==GE_COMPLETED,"padding ignored in duplicate comparison");
    auto save=request(2,GE_SAVE_LEVEL);
    check(GE_Submit(host.executor,&save,&out)==GE_OK,"save queued"); pump(host);
    check(result(host,2).state==GE_COMPLETED && host.saves==1,"synthetic save receipt");
    auto pending=request(3); check(GE_Submit(host.executor,&pending,&out)==GE_OK,"pending before unbind");
    check(GE_Unbind(host.executor)==GE_OK,"owner unbind");
    check(result(host,3).state==GE_RESULT_UNAVAILABLE && host.creates==1,"unbind cancels pending");
    check(GE_Submit(host.executor,&r,&out)==GE_OK && out.state==GE_COMPLETED,"historical receipt survives unbind");
    check(GE_Bind(host.executor,&a)==GE_OK,"rebind");
    check(GE_Submit(host.executor,&pending,&out)==GE_OK && out.state==GE_RESULT_UNAVAILABLE,"cancelled request not retried after rebind");
    check(GE_Destroy(host.executor)==GE_OK,"Destroy");
}
static void expiry_scene_and_failures() {
    SyntheticHost h; GE_Result out{}; GE_Create(&h.executor); auto a=adapter(h); GE_Bind(h.executor,&a);
    auto expired=request(10); expired.ttl_ms=1;
    check(GE_Submit(h.executor,&expired,&out)==GE_OK,"short TTL accepted"); Sleep(25); pump(h);
    check(result(h,10).state==GE_EXPIRED && h.creates==0 && h.reads==0,"expired before read never executes");
    check(GE_Submit(h.executor,&expired,&out)==GE_OK && out.state==GE_EXPIRED,"expired duplicate does not refresh TTL");
    const unsigned reads_before_slow=h.reads.load();
    auto slow=request(11); slow.ttl_ms=100; h.read_delay=150;
    check(GE_Submit(h.executor,&slow,&out)==GE_OK,"slow read request accepted"); pump(h); h.read_delay=0;
    check(result(h,11).state==GE_EXPIRED && h.creates==0 && h.reads==reads_before_slow+1,"expiry after one actual read prevents operation");
    auto revision=request(12); GE_Submit(h.executor,&revision,&out); ++h.scene.revision; pump(h);
    check(result(h,12).state==GE_SCENE_CHANGED && h.creates==0,"revision changed since Submit rejected");
    h.scene={42,7}; auto scene=request(13,GE_SAVE_LEVEL); GE_Submit(h.executor,&scene,&out); h.scene.scene_id=99; pump(h);
    out=result(h,13); check(out.state==GE_SCENE_CHANGED && out.scene_id==99 && h.saves==0,"changed scene rejects save");
    h.scene={42,7}; h.fail=true; auto failed=request(14); GE_Submit(h.executor,&failed,&out); pump(h);
    check(result(h,14).state==GE_FAILED && h.creates==1,"callback failure final");
    h.fail=false; GE_Submit(h.executor,&failed,&out); pump(h,0);
    check(out.state==GE_FAILED && h.creates==1,"failed callback is never retried");
    h.throw_execute=true; auto throws=request(15); GE_Submit(h.executor,&throws,&out); pump(h); h.throw_execute=false;
    check(result(h,15).state==GE_FAILED && h.creates==2,"C++ callback exception caught");
    h.throw_read=true; auto read_throws=request(16); GE_Submit(h.executor,&read_throws,&out); pump(h); h.throw_read=false;
    check(result(h,16).state==GE_FAILED && h.creates==2,"read exception does not execute operation");
    check(GE_Destroy(h.executor)==GE_OK,"failure-case executor destroy");
}
static void limits_validation_and_concurrency() {
    SyntheticHost h; GE_Result out{}; GE_Create(&h.executor); auto a=adapter(h); a.save_level=nullptr; GE_Bind(h.executor,&a);
    auto save=request(50,GE_SAVE_LEVEL);
    check(GE_Submit(h.executor,&save,&out)==GE_UNAVAILABLE,"missing operation adapter unavailable");
    auto invalid=request(51); invalid.position[0]=std::numeric_limits<float>::quiet_NaN();
    check(GE_Submit(h.executor,&invalid,&out)==GE_INVALID,"NaN rejected");
    invalid=request(51); invalid.ttl_ms=0; check(GE_Submit(h.executor,&invalid,&out)==GE_INVALID,"zero TTL rejected");
    invalid=request(51); invalid.ttl_ms=GE_MAX_TTL_MS+1; check(GE_Submit(h.executor,&invalid,&out)==GE_INVALID,"excessive TTL rejected");
    invalid=request(51); invalid.operation=99; check(GE_Submit(h.executor,&invalid,&out)==GE_INVALID,"unknown operation rejected");
    invalid=request(51,GE_SAVE_LEVEL); invalid.template_id=1; check(GE_Submit(h.executor,&invalid,&out)==GE_INVALID,"save payload must be canonical");
    std::atomic<unsigned> errors{0}; auto shared=request(60);
    std::vector<std::thread> threads;
    for(int t=0;t<8;++t) threads.emplace_back([&] {
        for(int i=0;i<30;++i) {GE_Result r{}; if(GE_Submit(h.executor,&shared,&r)!=GE_OK || r.state!=GE_QUEUED) ++errors;}
    });
    for(auto& t:threads) t.join();
    check(errors==0,"eight concurrent producers deduplicate same id"); pump(h);
    check(h.creates==1,"concurrent duplicate executed once");
    for(uint64_t i=0;i<GE_QUEUE_CAPACITY;++i) {auto r=request(100+i); check(GE_Submit(h.executor,&r,&out)==GE_OK,"fixed queue accepts capacity");}
    auto overflow=request(999);
    check(GE_Submit(h.executor,&overflow,&out)==GE_QUEUE_FULL,"queue capacity rejection");
    check(GE_GetResult(h.executor,999,&out)==GE_NOT_FOUND,"queue rejected id not recorded");
    pump(h,GE_QUEUE_CAPACITY);
    check(h.creates==1+GE_QUEUE_CAPACITY,"queue drain count");
    // Fill every lifetime ledger slot; no evictions that could allow replay.
    for(uint64_t i=GE_QUEUE_CAPACITY+1;i<GE_HISTORY_CAPACITY;++i) {
        auto r=request(1000+i); check(GE_Submit(h.executor,&r,&out)==GE_OK,"ledger slot accepted"); pump(h);
    }
    check(GE_Submit(h.executor,&overflow,&out)==GE_HISTORY_FULL,"history exhaustion rejects instead of evicting");
    check(GE_Submit(h.executor,&shared,&out)==GE_OK && out.state==GE_COMPLETED,"oldest result retained at history capacity");
    check(h.creates==GE_HISTORY_CAPACITY && h.wrong_thread==0,"all callbacks stay owner thread");
    check(GE_Destroy(h.executor)==GE_OK,"limit-case executor destroy");
}
int main() {
    check(GE_ApiVersion()==1 && GE_GetAbiVersion()==1,"ABI version");
    check(GE_StructureSize(1)==sizeof(GE_Request) && GE_StructureSize(2)==sizeof(GE_Result) &&
          GE_StructureSize(3)==sizeof(GE_Adapter) && GE_StructureSize(4)==sizeof(GE_AdapterResult) &&
          GE_StructureSize(99)==0,"ABI sizes");
    basic_lifecycle(); expiry_scene_and_failures(); limits_validation_and_concurrency();
    std::cout << "{\"host\":\"independent synthetic native host, not game\",\"checks\":" << checks
              << ",\"failures\":" << failures << ",\"requestSize\":" << sizeof(GE_Request)
              << ",\"resultSize\":" << sizeof(GE_Result) << ",\"adapterSize\":" << sizeof(GE_Adapter)
              << ",\"adapterResultSize\":" << sizeof(GE_AdapterResult) << "}\n";
    return failures ? 1 : 0;
}
