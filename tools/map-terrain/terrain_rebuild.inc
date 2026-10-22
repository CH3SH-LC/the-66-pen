// This is the same explicit owner rebuild used by native initial cell creation
// (13f12d98), loading (13f113a0) and batch updates (13f19905). Tick alone is
// insufficient: 13f13c0a gates it on the editing-tool activation byte.
bool rebuildCode(const GameContextSnapshot& scene,TerrainReceipt* o) {
    static constexpr std::uint32_t rvas[]={TERRAIN_REBUILD_RVAS};
    static constexpr unsigned char heads[][32]={TERRAIN_REBUILD_HEADS};unsigned char actual[32]{};
    for(std::size_t i=0;i<sizeof(rvas)/sizeof(*rvas);++i)
        if(!memory(scene.moduleBase+rvas[i],actual,32) || std::memcmp(actual,heads[i],32)){o->failedRva=rvas[i];return false;}
    static constexpr std::uint32_t hotfix[]={TERRAIN_REBUILD_HOTFIX};
    static constexpr std::uint32_t initialized[]={TERRAIN_REBUILD_INITIALIZED};
    for(auto r:hotfix){unsigned char v=255;if(!read(scene.moduleBase+r,v) || !TerrainRuntimeFlagAccepted(v,false)){o->failedRva=r;o->failedValue=v;return false;}}
    for(auto r:initialized){unsigned char v=255;if(!read(scene.moduleBase+r,v) || !TerrainRuntimeFlagAccepted(v,true)){o->failedRva=r;o->failedValue=v;return false;}}
    return true;
}
bool dirtyCells(U owner,U& count,unsigned char* scratch) {
    count=0;Dict d{};if(!dictionary(pointer(owner+0xd8),d,262144))return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(d,scratch))return false;
    for(std::uint32_t i=0;i<d.count;++i) {
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U cell=pointer(d.entries+0x20+24ULL*i+16),render=pointer(cell+0x50);unsigned char dirty=255;
        if(!render || !read(render+0x38,dirty) || dirty>1)return false;
        count+=dirty;
    }
    return stable(d);
}
bool rebuild(const GameContextSnapshot& scene,TerrainReceipt* o,unsigned char* scratch,const TerrainCellRow* expected,U count) {
    U beforeDirty=0;unsigned char beforeGate=255,afterGate=255;const U gate=pointer(o->manager+0x30);
    if(!rebuildCode(scene,o) || !dirtyCells(o->owner,beforeDirty,scratch) || !gate || !read(gate+0x8b,beforeGate) || beforeGate>1)return false;
    // Receipt reserved word is explicitly versioned by the preparation record:
    // low bits called, returned, dirty-clear, rows-same, gate-known, gate-before,
    // gate-after; high32 is the complete dirty count before rebuilding.
    // Bits8/9 belong only to explicitly prepared v3 shape resource guards.
    o->reserved=(o->reserved&768ULL)|(beforeDirty<<32)|16ULL|(static_cast<U>(beforeGate)<<5);
    o->stage=10;o->outcomeUncertain=1;o->reserved|=1;
    using Rebuild=void(*)(void*);
    reinterpret_cast<Rebuild>(scene.moduleBase+0xba50e20)(reinterpret_cast<void*>(o->owner));
    o->reserved|=2;
    U afterDirty=0,dict=0;
    if(!dirtyCells(o->owner,afterDirty,scratch) || afterDirty || !read(gate+0x8b,afterGate) || beforeGate!=afterGate)return false;
    o->reserved|=4ULL|(static_cast<U>(afterGate)<<6);
    if(!capture(o->owner,o->after,o->afterCount,o->afterVersion,dict,scratch) || dict!=o->dictionary ||
       o->afterCount!=count || std::memcmp(o->after,expected,static_cast<std::size_t>(count)*sizeof(TerrainCellRow)))return false;
    o->reserved|=8;o->stage=11;
    return rebuildCode(scene,o);
}
