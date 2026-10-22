// Disk-evidenced Unity getters and Collider.Raycast only. No setters, refresh,
// Physics.SyncTransforms, terrain transaction, saving, or desktop operations.
bool runtimeBounds(const float* b) {
    for (unsigned i=0;i<6;++i) if (!std::isfinite(b[i]) || std::fabs(b[i])>1.0e7f || (i>=3 && b[i]<0)) return false;
    return true;
}
bool runtimeHeads(U base) {
    static constexpr std::uint32_t rvas[]={TERRAIN_RUNTIME_RVAS};
    static constexpr unsigned char heads[][32]={TERRAIN_RUNTIME_HEADS}; unsigned char actual[32]{};
    for (std::size_t i=0;i<sizeof(rvas)/sizeof(*rvas);++i)
        if (!memory(base+rvas[i],actual,32) || std::memcmp(actual,heads[i],32)) return false;
    return true;
}
bool runtimeComponents(U base,TerrainRuntimeReceipt& r,bool renderer) {
    using Children=U(*)(U,U,bool); using Object=U(*)(U); using Boolean=bool(*)(U); using Bounds=void(*)(U,float*);
    U& array=renderer?r.rendererArray:r.colliderArray; U& count=renderer?r.rendererCount:r.colliderCount;
    U& scanned=renderer?r.scannedRenderers:r.scannedColliders;
    auto* rows=renderer?r.renderers:r.colliders;
    ++r.readCalls; array=reinterpret_cast<Children>(base+0x19cbcac0)(r.root,renderer?r.rendererClass:r.colliderClass,true);
    if (!array || !read(array+0x18,count) || count>kTerrainRuntimeComponents) return false;
    for (U i=0;i<count;++i) {
        if (GetTickCount64()>=HR_DEADLINE) return false;
        auto& c=rows[i]; c.object=pointer(array+0x20+8*i); if (!c.object) return false;
        // Duplicates would invalidate completeness/identity of the query.
        for (U j=0;j<i;++j) if (rows[j].object==c.object) return false;
        ++r.readCalls; c.gameObject=reinterpret_cast<Object>(base+0x1453c60)(c.object); if (!c.gameObject) return false;
        ++r.readCalls; c.active=reinterpret_cast<Boolean>(base+0x1452eb0)(c.gameObject)?1U:0U;
        ++r.readCalls; c.enabled=reinterpret_cast<Boolean>(base+(renderer?0x982f40:0x10dee70))(c.object)?1U:0U;
        ++r.readCalls; reinterpret_cast<Bounds>(base+(renderer?0x982810:0x12c8310))(c.object,c.bounds);
        if (renderer) { ++r.readCalls; c.visible=reinterpret_cast<Boolean>(base+0x982ff0)(c.object)?1U:0U; }
        if (!runtimeBounds(c.bounds)) return false;
        ++scanned;
    }
    return true;
}
bool runtimeIntersects(const float* b,const float* ray) {
    float low=0,high=ray[3];
    for (unsigned a=0;a<3;++a) {
        const float origin=ray[a],direction=ray[4+a],mn=b[a]-b[3+a],mx=b[a]+b[3+a];
        if (std::fabs(direction)<1.0e-8f) { if (origin<mn || origin>mx) return false; continue; }
        float t1=(mn-origin)/direction,t2=(mx-origin)/direction;
        if (t1>t2) { const float swap=t1;t1=t2;t2=swap; }
        low=low>t1?low:t1;high=high<t2?high:t2;
        if (high<low) return false;
    }
    return true;
}
bool runtimeTarget(U base,TerrainReceipt* o,TerrainRuntimeTarget& t,unsigned index) {
    auto& r=o->runtime; t.key=kTerrainRuntimeKeys[index];
    Dict d{};if (!dictionary(o->dictionary,d,262144)) return false;
    for (std::uint32_t i=0;i<d.count;++i) {
        const U entry=d.entries+0x20+24ULL*i;std::int32_t hash=-1;std::uint32_t key=0;
        if (!read(entry,hash)) return false;if (hash<0) continue;
        if (!read(entry+8,key)) return false;
        if (key==t.key) { if(t.cell)return false;t.cell=pointer(entry+16); }
    }
    if (!stable(d)) return false;
    for (U i=0;i<o->beforeCount;++i) if (o->before[i].key==t.key) t.logicalPresent=1;
    if (t.cell) {
        t.renderState=pointer(t.cell+0x50);t.cellTransform=pointer(t.renderState+0x20);unsigned char dirty=255;
        if (!t.renderState || !t.cellTransform || !read(t.renderState+0x38,dirty) || dirty>1) return false;
        t.dirty=dirty; // Capture all requested physical queries even when stale.
    } else if (t.logicalPresent) return false;
    const float x=static_cast<float>(t.key&0xffff)*r.steps[0],z=static_cast<float>(t.key>>16)*r.steps[2];
    float up[3]={r.matrix[4],r.matrix[5],r.matrix[6]};
    const float length=std::sqrt(up[0]*up[0]+up[1]*up[1]+up[2]*up[2]);
    if (!std::isfinite(length) || length<1.0e-5f) return false;
    float high=-1.0e30f,low=1.0e30f;
    for (unsigned a=0;a<3;++a) { up[a]/=length;t.worldCenter[a]=r.matrix[a]*x+r.matrix[8+a]*z+r.matrix[12+a]; }
    if(t.cellTransform) {
        float actual[16]{};using Matrix=void(*)(U,float*);++r.readCalls;
        reinterpret_cast<Matrix>(base+0x14377c0)(t.cellTransform,actual);
        for(unsigned a=0;a<3;++a)if(!std::isfinite(actual[12+a]) || std::fabs(actual[12+a]-t.worldCenter[a])>0.005f)return false;
    }
    for (U i=0;i<r.colliderCount;++i) {
        const auto& c=r.colliders[i];if (!c.active || !c.enabled) continue;
        float center=0,extent=0;
        for (unsigned a=0;a<3;++a) {center+=(c.bounds[a]-t.worldCenter[a])*up[a];extent+=c.bounds[3+a]*std::fabs(up[a]);}
        high=high>center+extent?high:center+extent;low=low<center-extent?low:center-extent;
    }
    // Empty terrain still gets a physical query interval, anchored on the actual
    // transform; the scale comes from the native cell-size vector, not config height.
    if (high<low) {high=r.steps[1]*length;low=-r.steps[1]*length;}
    t.ray[3]=high-low+2;
    if (!std::isfinite(t.ray[3]) || t.ray[3]<=0 || t.ray[3]>1.0e7f) return false;
    for (unsigned a=0;a<3;++a) {t.ray[a]=t.worldCenter[a]+up[a]*(high+1);t.ray[4+a]=-up[a];}
    struct Ray {float origin[3],direction[3];};
    struct Buffer {unsigned char before[16],hit[80],after[16];};
    using Cast=bool(*)(U,const Ray*,void*,float,bool,bool);
    for (U i=0;i<r.colliderCount;++i) {
        const auto& c=r.colliders[i];if (!c.active || !c.enabled || !runtimeIntersects(c.bounds,t.ray)) continue;
        Ray ray{};for(unsigned a=0;a<3;++a){ray.origin[a]=t.ray[a];ray.direction[a]=t.ray[4+a];}
        Buffer buffer{};std::memset(buffer.before,0xa5,16);std::memset(buffer.after,0x5a,16);
        ++r.readCalls;++t.rayTests;
        const bool hit=reinterpret_cast<Cast>(base+0x12c8370)(c.object,&ray,buffer.hit,t.ray[3],false,false);
        for(unsigned a=0;a<16;++a)if(buffer.before[a]!=0xa5 || buffer.after[a]!=0x5a)return false;
        // The confirmed writer touches [0,56). Future layout drift is refusal.
        for(unsigned a=56;a<80;++a)if(buffer.hit[a])return false;
        if(!hit)continue;
        U hitObject=0;std::memcpy(&hitObject,buffer.hit,sizeof(hitObject));
        if(hitObject!=c.object || t.hitCount>=kTerrainRuntimeHits)return false;
        auto& row=t.hits[t.hitCount++];row.collider=c.object;row.index=i;std::memcpy(row.raw,buffer.hit,80);
    }
    t.worldCenter[3]=1; // v2: this target's complete query is captured.
    return true;
}
bool runtimeProbe(const GameContextSnapshot& scene,TerrainReceipt* o) {
    auto& r=o->runtime;r.size=sizeof(r);r.version=2;r.status=1;r.stage=1;r.targetCount=TERRAIN_RUNTIME_TARGET_COUNT;
    const U base=scene.moduleBase;
    if(!runtimeHeads(base))return false;
    const U gate=pointer(o->manager+0x30);unsigned char active=255;
    if(!gate || !read(gate+0x8b,active) || active>1)return false;
    r.reserved=1ULL|(static_cast<U>(active)<<1); // known bit + actual tick gate.
    r.root=pointer(pointer(o->owner+0xc0)+0x18);r.colliderClass=pointer(base+0x57a1da0);r.rendererClass=pointer(base+0x57a11e8);
    if(!r.root || !r.colliderClass || !r.rendererClass || !memory(base+0x578d658,r.steps,12) ||
       r.steps[0]!=5 || r.steps[1]!=2.5f || r.steps[2]!=5)return false;
    using Matrix=void(*)(U,float*);++r.readCalls;reinterpret_cast<Matrix>(base+0x14377c0)(r.root,r.matrix);
    for(float f:r.matrix)if(!std::isfinite(f) || std::fabs(f)>1.0e7f)return false;
    r.stage=2;if(!runtimeComponents(base,r,false) || !runtimeComponents(base,r,true))return false;
    r.stage=3;
    for(unsigned i=0;i<TERRAIN_RUNTIME_TARGET_COUNT;++i)if(!runtimeTarget(base,o,r.targets[i],i))return false;
    r.stage=4;if(!runtimeHeads(base))return false;
    for(unsigned i=0;i<TERRAIN_RUNTIME_TARGET_COUNT;++i)if(r.targets[i].dirty)return false;
    r.status=0;return true;
}
