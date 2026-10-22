// Native surface semantics are pinned independently of the existing SetCell ABI.
// This reader performs no game calls and no lazy resource loads.
bool shapeCode(const GameContextSnapshot& s,TerrainReceipt* o) {
    static constexpr std::uint32_t rvas[]={TERRAIN_SHAPES_RVAS};
    static constexpr unsigned char heads[][32]={TERRAIN_SHAPES_HEADS};unsigned char actual[32]{};
    for(std::size_t i=0;i<sizeof(rvas)/sizeof(*rvas);++i)
        if(!memory(s.moduleBase+rvas[i],actual,32)||std::memcmp(actual,heads[i],32)){o->failedRva=rvas[i];return false;}
    static constexpr std::uint32_t hotfix[]={TERRAIN_SHAPES_HOTFIX},initialized[]={TERRAIN_SHAPES_INITIALIZED};
    for(auto r:hotfix){unsigned char v=255;if(!read(s.moduleBase+r,v)||!TerrainRuntimeFlagAccepted(v,false)){o->failedRva=r;o->failedValue=v;return false;}}
    for(auto r:initialized){unsigned char v=255;if(!read(s.moduleBase+r,v)||!TerrainRuntimeFlagAccepted(v,true)){o->failedRva=r;o->failedValue=v;return false;}}
    return true;
}
void shapeHash(U& hash,U value) { for(unsigned i=0;i<8;++i){hash^=(value>>(i*8))&255;hash*=1099511628211ULL;} }
bool shapeLookup(U at,std::uint32_t key,U& value,unsigned char* scratch,U& hash) {
    Dict d{};value=0;unsigned found=0;
    if(!dictionary(at,d,8192))return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(d,scratch))return false;
    shapeHash(hash,at);shapeHash(hash,d.version);shapeHash(hash,d.count);shapeHash(hash,d.free);
    for(std::uint32_t i=0;i<d.count;++i){
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U entry=d.entries+0x20+24ULL*i;std::uint32_t actual=0;
        if(!read(entry+8,actual))return false;
        if(actual==key){value=pointer(entry+16);++found;}
    }
    shapeHash(hash,key);shapeHash(hash,value);
    return found==1&&value&&stable(d);
}
bool shapePathDirectory(U at,unsigned char* scratch,U& hash,U& validPrefabs) {
    Dict d{};if(!dictionary(at,d,8192))return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(d,scratch))return false;
    shapeHash(hash,at);shapeHash(hash,d.version);shapeHash(hash,d.count);shapeHash(hash,d.free);
    for(std::uint32_t i=0;i<d.count;++i){
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U entry=d.entries+0x20+24ULL*i,config=pointer(entry+16);std::uint32_t key=0,actual=0;U prefab=0,native=0;
        if(!config||!read(entry+8,key)||!read(config+0x10,actual)||key!=actual||!read(config+0x18,prefab))return false;
        if(prefab){native=pointer(prefab+0x10);if(native)++validPrefabs;}
        // Native fallback skips absent configurations. Count and report only
        // real loaded resources; this is NOT proof of every rendered path mask.
        shapeHash(hash,key);shapeHash(hash,config);shapeHash(hash,prefab);shapeHash(hash,native);
    }
    return stable(d);
}
bool shapeResources(const GameContextSnapshot& s,TerrainReceipt* o,unsigned char* scratch,U& hash) {
    if(!shapeCode(s,o))return false;
    hash=14695981039346656037ULL;
    const U palette=pointer(o->manager+0x10),styles=pointer(palette+0x18);
    if(!palette||!styles)return false;
    for(std::uint32_t wantedIndex=0;wantedIndex!=TERRAIN_SHAPE_MATERIAL_COUNT;++wantedIndex){
        const auto& wanted=kTerrainShapeMaterials[wantedIndex];
        if(GetTickCount64()>=HR_DEADLINE)return false;
        U style=0;o->failedKey=wanted.material;o->failedRva=0xba4c850;o->failedValue=0;
        if(!shapeLookup(styles,wanted.material,style,scratch,hash))return false;
        if(wanted.slopeTypeMask){
            const U slopes=pointer(style+0x10);if(!slopes)return false;
            for(std::uint32_t type=1;type<=3;++type)if(wanted.slopeTypeMask&(1U<<type)){
                U prefab=0;o->failedValue=type;
                if(!shapeLookup(slopes,type,prefab,scratch,hash))return false;
                const U native=pointer(prefab+0x10);if(!native)return false;shapeHash(hash,native);
            }
        }
        if(wanted.path){
            U loaded=0;o->failedRva=0xba4c1a0;
            if(!shapePathDirectory(pointer(style+0x38),scratch,hash,loaded))return false;
            o->failedRva=0xba4c2e0;
            if(!shapePathDirectory(pointer(style+0x20),scratch,hash,loaded)||!loaded)return false;
        }
    }
    o->failedKey=0;o->failedRva=0;o->failedValue=0;
    return shapeCode(s,o);
}
