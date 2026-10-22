#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_terrain.h"
#include "terrain_request.h"
#include <cstring>
#include <cstdlib>
#include <cmath>
#if HR_ACTION != 14 || !TERRAIN_ACTION_REVIEWED || !GS_REVIEWED_ACTION_PROFILE
#error Dedicated terrain action profile required
#endif
namespace {
using U = std::uint64_t;
// The complete dictionary can have 262144 slots. Keep this bounded 32 KiB
// reachability bitmap off the editor callback's existing stack.
constexpr std::size_t kScratchBytes=262144/8;
bool memory(U at, void* out, std::size_t n) noexcept {
    if (!out || !n || at < 0x10000 || at >= 0x800000000000ULL || n > 0x800000000000ULL-at) return false;
    std::size_t done = 0;
    while (done < n) {
        MEMORY_BASIC_INFORMATION r{}; const U p=at+done;
        if (VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r)) != sizeof(r) || r.State != MEM_COMMIT || (r.Protect & (PAGE_NOACCESS|PAGE_GUARD))) return false;
        const auto left=r.RegionSize-static_cast<std::size_t>(p-reinterpret_cast<U>(r.BaseAddress));
        const auto part=n-done < left ? n-done : left;
        __try { std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(p),part); }
        __except(EXCEPTION_EXECUTE_HANDLER) { return false; }
        done+=part;
    }
    return true;
}
template<class T> bool read(U at,T& v) { return memory(at,&v,sizeof(v)); }
U pointer(U at) { U v=0; return read(at,v) && v>=0x10000 && v<0x800000000000ULL ? v : 0; }
bool code(const GameContextSnapshot& s,TerrainReceipt* o) {
    if (s.moduleBase!=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe")) || s.peTimestamp!=HR_GAME_TIMESTAMP || s.peImageSize!=HR_GAME_IMAGE_SIZE) return false;
    static constexpr std::uint32_t rvas[]={TERRAIN_CODE_RVAS};
    static constexpr unsigned char heads[][32]={TERRAIN_CODE_BYTES}; unsigned char actual[32]{};
    for (std::size_t i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)
        if (!memory(s.moduleBase+rvas[i],actual,32) || std::memcmp(actual,heads[i],32)) { o->failedRva=rvas[i]; return false; }
    static constexpr std::uint32_t flags[]={GS_PROFILE_HOTFIX_RVAS,TERRAIN_HOTFIX_RVAS};
    for (auto r:flags) { unsigned char v=255; if (!read(s.moduleBase+r,v) || !TerrainRuntimeFlagAccepted(v,false)) { o->failedRva=r; o->failedValue=v; return false; } }
    static constexpr std::uint32_t initialized[]={TERRAIN_INITIALIZATION_RVAS};
    for (auto r:initialized) { unsigned char v=255; if (!read(s.moduleBase+r,v) || !TerrainRuntimeFlagAccepted(v,true)) { o->failedRva=r; o->failedValue=v; return false; } }
    return true;
}
bool sameScene(const GameContextSnapshot& a,const GameContextSnapshot& b) {
    if (b.structSize!=sizeof(b) || b.version!=kSnapshotVersion || b.status!=GS_OK || (b.flags&1951)!=1951 ||
        b.reserved!=TERRAIN_LEVEL_ID || b.entityRejected || b.entityCaptured!=b.entityValidEntries ||
        a.entityCaptured!=b.entityCaptured || b.entityCaptured>kMaxEntities || a.currentContext!=b.currentContext ||
        a.global!=b.global || a.moduleBase!=b.moduleBase || a.entityDictionary!=b.entityDictionary ||
        a.contextDictionary!=b.contextDictionary || a.entityVersionBefore!=b.entityVersionBefore || a.entityVersionAfter!=b.entityVersionAfter) return false;
    for (std::uint32_t i=0;i<a.entityCaptured;++i) {
        const auto& x=a.entities[i]; const auto& y=b.entities[i];
        if (x.id!=y.id || x.owner!=y.owner || x.config!=y.config || x.context!=y.context || x.configId!=y.configId || x.dictionaryKey!=y.dictionaryKey) return false;
    }
    return true;
}
struct Dict { U pointer,entries,capacity,buckets,bucketCapacity; std::uint32_t count,free,version; };
bool dictionary(U p,Dict& d,std::uint32_t maximum) {
    d={}; d.pointer=p;
    if (!p || !(d.entries=pointer(p+0x28)) || !(d.buckets=pointer(p+0x20)) || !read(p+0x38,d.count) || !read(p+0x40,d.free) ||
        !read(p+0x3c,d.version) || !read(d.entries+0x18,d.capacity) || !read(d.buckets+0x18,d.bucketCapacity)) return false;
    return d.free<=d.count && d.count<=d.capacity && d.capacity<=maximum && d.bucketCapacity>0 && d.bucketCapacity<=maximum;
}
bool stable(const Dict& d) {
    Dict b{}; return dictionary(d.pointer,b,262144) && d.pointer==b.pointer && d.entries==b.entries &&
        d.capacity==b.capacity && d.buckets==b.buckets && d.bucketCapacity==b.bucketCapacity &&
        d.count==b.count && d.free==b.free && d.version==b.version;
}
bool reachable(const Dict& d,unsigned char* seen) {
    std::uint32_t total=0;
    for (U bucket=0;bucket<d.bucketCapacity;++bucket) {
        std::int32_t head=0; if (!read(d.buckets+0x20+bucket*4,head) || head<0) return false;
        std::int32_t slot=head-1;
        while (slot>=0) {
            const auto i=static_cast<std::uint32_t>(slot);
            if (i>=d.count || (seen[i/8] & (1U<<(i%8)))) return false;
            seen[i/8]|=static_cast<unsigned char>(1U<<(i%8));
            std::int32_t hash=-1,next=-2; const U entry=d.entries+0x20+24ULL*i;
            if (!read(entry,hash) || !read(entry+4,next) || hash<0 || static_cast<U>(hash)%d.bucketCapacity!=bucket || next< -1) return false;
            ++total; slot=next;
        }
    }
    return total==d.count-d.free;
}
bool locate(const GameContextSnapshot& s,TerrainReceipt* o,unsigned char* seen) {
    o->manager=pointer(s.global+0x18b90); Dict d{};
    if (!dictionary(pointer(o->manager+0x40),d,8192)) return false;
    std::memset(seen,0,kScratchBytes); if (!reachable(d,seen)) return false;
    std::uint32_t found=0,valid=0;
    for (std::uint32_t i=0;i<d.count;++i) {
        const U entry=d.entries+0x20+24ULL*i; std::int32_t hash=-1; std::uint32_t id=0,actual=0;
        if (!read(entry,hash)) return false; if (!(seen[i/8] & (1U<<(i%8)))) continue;
        ++valid; const U owner=pointer(entry+16), meta=pointer(owner+0xe0);
        if (!read(entry+8,id) || !meta || !read(meta+0x18,actual) || actual!=id) return false;
        if (id==TERRAIN_ID) { o->owner=owner; ++found; }
    }
    o->terrainCount=valid;
    return found==1 && valid==d.count-d.free && stable(d);
}
int compare(const void* a,const void* b) {
    const auto x=static_cast<const TerrainCellRow*>(a)->key,y=static_cast<const TerrainCellRow*>(b)->key;
    return x<y ? -1 : x>y ? 1 : 0;
}
bool capture(U owner,TerrainCellRow* rows,U& count,U& version,U& dict,unsigned char* seen) {
    Dict d{}; dict=pointer(owner+0xd8); count=0;
    if (!dictionary(dict,d,262144)) return false;
    std::memset(seen,0,kScratchBytes); if (!reachable(d,seen)) return false;
    std::uint32_t valid=0;
    for (std::uint32_t i=0;i<d.count;++i) {
        const U entry=d.entries+0x20+24ULL*i; std::int32_t hash=-1;
        if (!read(entry,hash)) return false; if (!(seen[i/8] & (1U<<(i%8)))) continue; ++valid;
        TerrainCellRow r{}; U coord=0; const U cell=pointer(entry+16), state=pointer(cell+0x20);
        if (!state || !read(entry+8,r.key) || !read(state+0x18,coord) ||
            !read(state+0x24,r.height) || !read(state+0x14,r.material) || !read(state+0x20,r.extraA) ||
            !read(state+0x28,r.extraB) || !read(state+0x10,r.extraC)) return false;
        const U x=coord&0xffffffffULL,z=coord>>32;
        if (x>=9999 || z>=9999 || r.height>=9999 || r.key!=(x|(z<<16))) return false;
        if (!(r.height || r.extraA || r.extraC)) continue; // native export excludes tombstones
        if (count>=kTerrainCapacity) return false; rows[count++]=r;
    }
    if (valid!=d.count-d.free || !stable(d)) return false;
    std::qsort(rows,static_cast<std::size_t>(count),sizeof(*rows),compare);
    for (U i=1;i<count;++i) if (rows[i-1].key==rows[i].key) return false;
    version=d.version; return true;
}
struct Pending { U manager,list,items,record,object,before,after; std::uint32_t count; std::int32_t base,depth; unsigned char flags[4],dirty; };
#include "terrain_rebuild.inc"
#if TERRAIN_RUNTIME_PROBE
#include "terrain_runtime.inc"
#endif
bool pending(U global,Pending& s) {
    s={}; s.manager=pointer(global+0xecd0); s.list=pointer(s.manager+0x18); s.items=pointer(s.list+0x10); U cap=0;
    if (!s.items || !read(s.manager+0x28,s.flags) || !read(s.manager+0x30,s.base) || !read(s.manager+0x34,s.depth) ||
        !read(s.list+0x18,s.count) || !read(s.items+0x18,cap) || s.count>1 || s.count>cap || cap>4096 || s.base<0 || s.depth<s.base || s.flags[1] || s.flags[2]) return false;
    if (!s.count) return true;
    s.record=pointer(s.items+0x20);
    return s.record && read(s.record+0x18,s.object) && read(s.record+0x28,s.before) && read(s.record+0x20,s.after) && read(s.record+0x30,s.dirty);
}
#if TERRAIN_CATALOG_PROBE || TERRAIN_CATALOG_GUARD
#include "terrain_catalog.inc"
#endif
#if TERRAIN_SHAPES_GUARD
#include "terrain_shapes_v3.inc"
#endif
void execute(const GameContextSnapshot* scene,TerrainReceipt* o,unsigned char* scratch) {
    o->status=1; o->stage=1; o->terrainId=TERRAIN_ID;
    const auto* expected=reinterpret_cast<const GameContextSnapshot*>(kTerrainExpectedScene);
    if (GetCurrentProcessId()!=HR_TARGET_PID || GetCurrentThreadId()!=HR_TARGET_TID || GetTickCount64()>=HR_DEADLINE ||
        !sameScene(*expected,*scene) || !code(*scene,o)) return;
    const U base=scene->moduleBase; std::uint32_t limits[3]{};
    if (!memory(base+0x578d64c,limits,sizeof(limits)) || limits[0]!=9999 || limits[1]!=9999 || limits[2]!=9999) { o->failedRva=0xF0000010u; return; }
    o->constantsValid=1; o->stage=2;
    if (!locate(*scene,o,scratch) || !capture(o->owner,o->before,o->beforeCount,o->beforeVersion,o->dictionary,scratch)) { o->failedRva=0xF0000011u; return; }
    U secondDict=0;
    if (!capture(o->owner,o->after,o->afterCount,o->afterVersion,secondDict,scratch) || secondDict!=o->dictionary ||
        o->beforeVersion!=o->afterVersion || o->beforeCount!=o->afterCount ||
        std::memcmp(o->before,o->after,static_cast<std::size_t>(o->beforeCount)*sizeof(TerrainCellRow))) { o->failedRva=0xF0000012u; return; }
    o->captureStable=1; o->stage=3;
    if (TERRAIN_INSPECT_ONLY) {
#if TERRAIN_RUNTIME_PROBE || TERRAIN_CATALOG_PROBE
#if TERRAIN_CATALOG_PROBE
        const bool observed=catalogCapture(*scene,o,o->catalog,scratch);
#else
        const bool observed=runtimeProbe(*scene,o);
#endif
        if(!capture(o->owner,o->after,o->afterCount,o->afterVersion,secondDict,scratch) || secondDict!=o->dictionary ||
           o->beforeVersion!=o->afterVersion || o->beforeCount!=o->afterCount ||
           std::memcmp(o->before,o->after,static_cast<std::size_t>(o->beforeCount)*sizeof(TerrainCellRow))){ o->failedRva=0xF0000013u; return; }
        CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=sameScene(*scene,o->afterScene)?1ULL:0ULL;
        if(!o->sceneUnchanged || !code(*scene,o) || !observed){ if(!o->failedRva)o->failedRva=0xF0000013u; return; }
#else
        std::memcpy(&o->afterScene,scene,sizeof(*scene));o->sceneUnchanged=1;
#endif
        o->status=0;return;
    }
    if (o->beforeCount!=TERRAIN_BEFORE_COUNT || std::memcmp(o->before,kTerrainBefore,sizeof(TerrainCellRow)*TERRAIN_BEFORE_COUNT)) { o->failedRva=0xF0000001u; return; }
#if TERRAIN_CATALOG_GUARD
    if(!catalogGuard(*scene,o,scratch)){ o->failedRva=0xF0000002u; return; }
#endif
#if TERRAIN_SHAPES_GUARD
    U shapeResourcesBefore=0;
    if(!shapeResources(*scene,o,scratch,shapeResourcesBefore)){ o->failedRva=0xF0000003u; return; }
    o->reserved|=256ULL;
#endif
    if(!rebuildCode(*scene,o)){ if(!o->failedRva)o->failedRva=0xF0000004u; return; }
    Pending pre{},snap{},notice{},closed{};
    if (!pending(scene->global,pre)) { o->failedRva=0xF0000005u; return; }
    if (pre.count) { o->failedRva=0xF0000006u; return; }
    if (pre.depth!=pre.base) { o->failedRva=0xF0000007u; return; }
    if(TERRAIN_REFRESH_ONLY) {
        if(!rebuild(*scene,o,scratch,kTerrainBefore,TERRAIN_BEFORE_COUNT))return;
        if(!pending(scene->global,closed) || closed.manager!=pre.manager || closed.list!=pre.list || closed.items!=pre.items ||
           closed.count || closed.base!=pre.base || closed.depth!=pre.depth || std::memcmp(closed.flags,pre.flags,sizeof(pre.flags))){ o->failedRva=0xF0000014u; return; }
        CaptureGameContextSnapshot(&o->afterScene);o->sceneUnchanged=sameScene(*scene,o->afterScene)?1ULL:0ULL;
        if(!o->sceneUnchanged || !code(*scene,o))return;
        o->outcomeUncertain=0;o->status=0;return;
    }
    o->stage=4; // all scene/cell/transaction guards complete before the first call
    using Open=void*(*)(void*,bool,bool); using Snapshot=void(*)(void*,void*,int);
    using Notify=void(*)(void*,void*); using Close=void(*)(void*);
    using Label=void*(*)(int); using Set=void(*)(void*,U,std::uint32_t,std::uint32_t,std::uint32_t,std::uint32_t,std::uint32_t);
    using Delete=void(*)(void*,U);
    // Label is the editor's real terrain undo label (enum 1), not a guessed literal.
    void* label=reinterpret_cast<Label>(base+0x13f16780)(1);
    if (!label || !code(*scene,o)) return;
    o->openCalled=1; o->transactionMayBeOpen=1; o->outcomeUncertain=1;
    void* transaction=reinterpret_cast<Open>(base+0xe827750)(nullptr,false,false);
    if (!transaction) { o->failedRva=0xF0000015u; return; }
    o->stage=5; o->snapshotCalled=1;
    reinterpret_cast<Snapshot>(base+0x107abdf0)(reinterpret_cast<void*>(o->owner),label,0);
    if (!pending(scene->global,snap) || snap.manager!=pre.manager || snap.list!=pre.list || snap.count!=1 ||
        snap.depth!=pre.depth+1 || snap.object!=o->owner || !snap.before || snap.after || snap.dirty ||
        pointer(snap.record)!=pointer(base+0x5812cf8)) { o->failedRva=0xF0000016u; return; }
    o->snapshotVerified=1; o->stage=6;
    for (std::size_t i=0;i<sizeof(kTerrainEdits)/sizeof(kTerrainEdits[0]);++i) {
        const auto& r=kTerrainEdits[i]; const U coord=static_cast<U>(r.after.key&0xffff)|(static_cast<U>(r.after.key>>16)<<32);
        o->failedKey=r.after.key; ++o->mutationCalls;
        if (r.remove) reinterpret_cast<Delete>(base+0xba539a0)(reinterpret_cast<void*>(o->owner),coord);
        else reinterpret_cast<Set>(base+0xba53650)(reinterpret_cast<void*>(o->owner),coord,r.after.height,r.after.material,r.after.extraA,r.after.extraB,r.after.extraC);
        ++o->completed;
    }
    o->stage=7;
    if (!capture(o->owner,o->after,o->afterCount,o->afterVersion,secondDict,scratch) || secondDict!=o->dictionary ||
        o->afterCount!=TERRAIN_AFTER_COUNT || std::memcmp(o->after,kTerrainAfter,sizeof(TerrainCellRow)*TERRAIN_AFTER_COUNT)) { o->failedRva=0xF0000017u; return; }
    o->notifyCalled=1;
    reinterpret_cast<Notify>(base+0x9c26c70)(reinterpret_cast<void*>(pre.manager),reinterpret_cast<void*>(o->owner));
    if (!pending(scene->global,notice) || notice.manager!=snap.manager || notice.list!=snap.list || notice.record!=snap.record ||
        notice.object!=snap.object || notice.before!=snap.before || notice.count!=1 || notice.depth!=snap.depth || notice.dirty!=1) { o->failedRva=0xF0000018u; return; }
    o->notificationVerified=1; o->stage=8; o->closeCalled=1;
    reinterpret_cast<Close>(base+0xc7bab90)(transaction);
    if (!pending(scene->global,closed) || closed.manager!=pre.manager || closed.list!=pre.list || closed.count || closed.depth!=pre.depth) { o->failedRva=0xF0000019u; return; }
    o->closeVerified=1; o->transactionMayBeOpen=0;
    if(!rebuild(*scene,o,scratch,kTerrainAfter,TERRAIN_AFTER_COUNT)){ o->failedRva=0xF000001Au; return; }
#if TERRAIN_SHAPES_GUARD
    U shapeResourcesAfter=0;
    if(!shapeResources(*scene,o,scratch,shapeResourcesAfter)||shapeResourcesBefore!=shapeResourcesAfter){ o->failedRva=0xF000001Bu; return; }
    o->reserved|=512ULL;
#endif
    CaptureGameContextSnapshot(&o->afterScene); o->sceneUnchanged=sameScene(*scene,o->afterScene)?1ULL:0ULL;
    o->stage=9;
    if (!o->sceneUnchanged || !code(*scene,o)) return;
    o->failedKey=0; o->outcomeUncertain=0; o->status=0;
}
}
void ExecuteTerrainAction(const GameContextSnapshot* s,TerrainReceipt* o) noexcept {
    if (!s || !o) return;
    std::memset(o,0,sizeof(*o)); o->size=sizeof(*o); o->version=1;
#if TERRAIN_RUNTIME_PROBE
    o->version=2;
#endif
#if TERRAIN_CATALOG_PROBE
    o->version=3;
#endif
    const HANDLE heap=GetProcessHeap();
    auto* scratch=static_cast<unsigned char*>(HeapAlloc(heap,0,kScratchBytes));
    if (!scratch) { o->status=3; return; } // No transaction or game call occurred.
    __try { execute(s,o,scratch); }
    __except(EXCEPTION_EXECUTE_HANDLER) { o->sehCode=GetExceptionCode(); o->status=2; }
    HeapFree(heap,0,scratch);
}
