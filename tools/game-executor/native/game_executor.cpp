#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "game_executor.h"
#include <cmath>
#include <cstring>
#include <new>

struct Entry {
    GE_Request request{};
    GE_Result result{};
    uint64_t deadline=0;
};
struct GE_Executor {
    SRWLOCK lock=SRWLOCK_INIT;
    GE_Adapter adapter{};
    DWORD owner=0;
    bool bound=false;
    bool pumping=false;
    Entry entries[GE_HISTORY_CAPACITY]{};
    uint32_t history_count=0;
    uint32_t queue[GE_QUEUE_CAPACITY]{};
    uint32_t head=0;
    uint32_t count=0;
};
namespace {
struct Guard {
    SRWLOCK* lock;
    explicit Guard(SRWLOCK* value):lock(value) { AcquireSRWLockExclusive(lock); }
    ~Guard() { ReleaseSRWLockExclusive(lock); }
    Guard(const Guard&)=delete;
    Guard& operator=(const Guard&)=delete;
};
void message(GE_Result& r, const char* text) {
    size_t i=0;
    for (;i+1<GE_MESSAGE_CAPACITY && text[i];++i) r.message[i]=text[i];
    r.message[i]='\0';
}
void finish(Entry& e, uint32_t state, const char* text, int32_t detail=0) {
    e.result.state=state; e.result.detail_code=detail; message(e.result,text);
}
bool valid(const GE_Request& r) {
    if (r.struct_size!=sizeof(GE_Request) || !r.request_id || !r.scene_id ||
        !r.ttl_ms || r.ttl_ms>GE_MAX_TTL_MS ||
        (r.operation!=GE_CREATE_INSTANCE && r.operation!=GE_SAVE_LEVEL)) return false;
    for (unsigned i=0;i<3;++i) {
        if (!std::isfinite(r.position[i]) || !std::isfinite(r.rotation[i]) || !std::isfinite(r.scale[i])) return false;
        if (r.operation==GE_SAVE_LEVEL && (r.position[i]!=0 || r.rotation[i]!=0 || r.scale[i]!=0)) return false;
        if (r.operation==GE_CREATE_INSTANCE && r.scale[i]<=0) return false;
    }
    return r.operation==GE_CREATE_INSTANCE ? r.template_id!=0 : r.template_id==0;
}
bool same(const GE_Request& a,const GE_Request& b) {
    if (a.struct_size!=b.struct_size || a.operation!=b.operation || a.request_id!=b.request_id ||
        a.scene_id!=b.scene_id || a.scene_revision!=b.scene_revision || a.ttl_ms!=b.ttl_ms ||
        a.template_id!=b.template_id) return false;
    for(unsigned i=0;i<3;++i)
        if(a.position[i]!=b.position[i] || a.rotation[i]!=b.rotation[i] || a.scale[i]!=b.scale[i]) return false;
    return true;
}
Entry* find(GE_Executor* x,uint64_t id) {
    for(uint32_t i=0;i<x->history_count;++i) if(x->entries[i].request.request_id==id) return &x->entries[i];
    return nullptr;
}
bool available(const GE_Adapter& a,uint32_t operation) {
    return operation==GE_CREATE_INSTANCE ? a.create_instance!=nullptr : a.save_level!=nullptr;
}
void run(Entry& local,const GE_Adapter& adapter) {
    if(GetTickCount64()>=local.deadline) { finish(local,GE_EXPIRED,"expired before execution"); return; }
    GE_Scene current{};
    int32_t rc=0;
    try { rc=adapter.read_scene(adapter.context,&current); }
    catch(...) { finish(local,GE_FAILED,"read_scene callback threw; not retried",GE_INTERNAL); return; }
    if(rc!=0) { finish(local,GE_FAILED,"read_scene callback failed; not retried",rc); return; }
    local.result.scene_id=current.scene_id; local.result.scene_revision=current.revision;
    if(current.scene_id!=local.request.scene_id || current.revision!=local.request.scene_revision) {
        finish(local,GE_SCENE_CHANGED,"scene or revision differs; operation not executed"); return;
    }
    if(GetTickCount64()>=local.deadline) { finish(local,GE_EXPIRED,"expired during scene check; operation not executed"); return; }
    GE_AdapterResult output{};
    try {
        const GE_Execute callback=local.request.operation==GE_CREATE_INSTANCE ? adapter.create_instance : adapter.save_level;
        rc=callback(adapter.context,&local.request,&output);
    } catch(...) { finish(local,GE_FAILED,"operation callback threw; not retried",GE_INTERNAL); return; }
    local.result.entity_id=output.entity_id;
    local.result.detail_code=output.detail_code ? output.detail_code : rc;
    local.result.state=rc==0 ? GE_COMPLETED : GE_FAILED;
    output.message[GE_MESSAGE_CAPACITY-1]='\0';
    message(local.result,output.message[0] ? output.message : (rc==0 ? "adapter completed; executor receipt only" : "adapter failed; not retried"));
}
}

extern "C" {
uint32_t GE_CALL GE_GetAbiVersion(void) { return GE_ABI_VERSION; }
uint32_t GE_CALL GE_ApiVersion(void) { return GE_ABI_VERSION; }
uint32_t GE_CALL GE_StructureSize(uint32_t kind) {
    switch(kind) {
    case 1: return sizeof(GE_Request);
    case 2: return sizeof(GE_Result);
    case 3: return sizeof(GE_Adapter);
    case 4: return sizeof(GE_AdapterResult);
    default: return 0;
    }
}
uint64_t GE_CALL GE_NowMs(void) { return GetTickCount64(); }
int32_t GE_CALL GE_Create(GE_Executor** out) {
    if(!out) return GE_INVALID;
    *out=new(std::nothrow) GE_Executor();
    return *out ? GE_OK : GE_INTERNAL;
}
int32_t GE_CALL GE_Destroy(GE_Executor* x) {
    if(!x) return GE_INVALID;
    {
        Guard g(&x->lock);
        if(x->pumping) return GE_BUSY;
        if(x->bound && GetCurrentThreadId()!=x->owner) return GE_WRONG_THREAD;
    }
    delete x; return GE_OK;
}
int32_t GE_CALL GE_Bind(GE_Executor* x,const GE_Adapter* a) {
    if(!x || !a || a->struct_size!=sizeof(GE_Adapter) || a->abi_version!=GE_ABI_VERSION || !a->read_scene) return GE_INVALID;
    Guard g(&x->lock);
    if(x->bound || x->pumping) return GE_BUSY;
    x->adapter=*a; x->owner=GetCurrentThreadId(); x->bound=true;
    return GE_OK;
}
int32_t GE_CALL GE_Unbind(GE_Executor* x) {
    if(!x) return GE_INVALID;
    Guard g(&x->lock);
    if(!x->bound) return GE_UNAVAILABLE;
    if(GetCurrentThreadId()!=x->owner) return GE_WRONG_THREAD;
    if(x->pumping) return GE_BUSY;
    while(x->count) {
        const uint32_t index=x->queue[x->head]; x->head=(x->head+1)%GE_QUEUE_CAPACITY; --x->count;
        finish(x->entries[index],GE_RESULT_UNAVAILABLE,"adapter unbound before execution");
    }
    x->adapter={}; x->owner=0; x->bound=false; return GE_OK;
}
int32_t GE_CALL GE_Submit(GE_Executor* x,const GE_Request* r,GE_Result* out) {
    if(out) *out={};
    if(!x || !r || !out || !valid(*r)) return GE_INVALID;
    Guard g(&x->lock);
    if(Entry* old=find(x,r->request_id)) {
        if(!same(old->request,*r)) return GE_ID_CONFLICT;
        *out=old->result; return GE_OK;
    }
    if(!x->bound || !available(x->adapter,r->operation)) return GE_UNAVAILABLE;
    if(x->count==GE_QUEUE_CAPACITY) return GE_QUEUE_FULL;
    if(x->history_count==GE_HISTORY_CAPACITY) return GE_HISTORY_FULL;
    const uint32_t index=x->history_count++;
    Entry& e=x->entries[index]; e.request=*r; e.deadline=GetTickCount64()+r->ttl_ms;
    e.result.struct_size=sizeof(GE_Result); e.result.state=GE_QUEUED;
    e.result.request_id=r->request_id; e.result.operation=r->operation;
    e.result.scene_id=r->scene_id; e.result.scene_revision=r->scene_revision;
    message(e.result,"queued for owner thread; no operation executed");
    x->queue[(x->head+x->count)%GE_QUEUE_CAPACITY]=index; ++x->count;
    *out=e.result; return GE_OK;
}
int32_t GE_CALL GE_GetResult(GE_Executor* x,uint64_t id,GE_Result* out) {
    if(out) *out={};
    if(!x || !id || !out) return GE_INVALID;
    Guard g(&x->lock);
    Entry* e=find(x,id);
    if(!e) return GE_NOT_FOUND;
    *out=e->result; return GE_OK;
}
int32_t GE_CALL GE_Pump(GE_Executor* x,uint32_t max_requests,uint32_t* processed) {
    if(processed) *processed=0;
    if(!x || !processed || !max_requests || max_requests>GE_QUEUE_CAPACITY) return GE_INVALID;
    GE_Adapter adapter{};
    {
        Guard g(&x->lock);
        if(!x->bound) return GE_UNAVAILABLE;
        if(GetCurrentThreadId()!=x->owner) return GE_WRONG_THREAD;
        if(x->pumping) return GE_BUSY;
        x->pumping=true; adapter=x->adapter;
    }
    while(*processed<max_requests) {
        uint32_t index=0; Entry local{};
        {
            Guard g(&x->lock);
            if(!x->count) break;
            index=x->queue[x->head]; x->head=(x->head+1)%GE_QUEUE_CAPACITY; --x->count;
            x->entries[index].result.state=GE_RUNNING;
            local=x->entries[index];
        }
        run(local,adapter);
        { Guard g(&x->lock); x->entries[index].result=local.result; }
        ++*processed;
    }
    { Guard g(&x->lock); x->pumping=false; }
    return GE_OK;
}
BOOL WINAPI DllMain(HINSTANCE,DWORD,LPVOID) { return TRUE; }
}
