// Read initialized native dictionaries. Never call the lazy catalog getter,
// allocate game objects, load a resource, change the tool, or modify terrain.
bool catalogCode(const GameContextSnapshot& s) {
    static constexpr std::uint32_t rvas[]={TERRAIN_CATALOG_RVAS};
    static constexpr unsigned char heads[][32]={TERRAIN_CATALOG_HEADS};unsigned char bytes[32]{};
    for(std::size_t i=0;i<sizeof(rvas)/sizeof(*rvas);++i)
        if(!memory(s.moduleBase+rvas[i],bytes,32)||std::memcmp(bytes,heads[i],32))return false;
    static constexpr std::uint32_t hotfix[]={TERRAIN_CATALOG_HOTFIX},initialized[]={TERRAIN_CATALOG_INITIALIZED};
    for(auto at:hotfix){unsigned char v=255;if(!read(s.moduleBase+at,v)||v!=0)return false;}
    for(auto at:initialized){unsigned char v=255;if(!read(s.moduleBase+at,v)||v>1)return false;}
    return true;
}
int catalogCompare(const void* a,const void* b) {
    const auto x=static_cast<const TerrainMaterialRow*>(a)->id,y=static_cast<const TerrainMaterialRow*>(b)->id;
    return x<y?-1:x>y?1:0;
}
bool catalogCapture(const GameContextSnapshot& s,TerrainReceipt* o,TerrainCatalogReceipt& r,unsigned char* scratch) {
    std::memset(&r,0,sizeof(r));r.size=sizeof(r);r.version=1;r.status=1;r.stage=1;
    if(!catalogCode(s))return false;
    r.root=pointer(pointer(o->owner+0xc0)+0x18);r.configDictionary=pointer(s.global+0x33db0);
    r.styleDictionary=pointer(pointer(o->manager+0x10)+0x18);r.decoderTable=pointer(s.global+0xf620);
    std::uint32_t decodeKey=0;U tableLength=0;
    if(!r.root||!r.decoderTable||!read(r.decoderTable+0x18,tableLength)||tableLength<2048||tableLength>65536||
       !memory(r.decoderTable+0x20,r.keyTable,sizeof(r.keyTable))||!read(s.moduleBase+0x578bd50,decodeKey)||
       !memory(s.moduleBase+0x578d658,r.steps,12)||r.steps[0]!=5||r.steps[1]!=2.5f||r.steps[2]!=5)return false;
    r.decoderKey=decodeKey;
    using Matrix=void(*)(U,float*);reinterpret_cast<Matrix>(s.moduleBase+0x14377c0)(r.root,r.matrix);
    for(float v:r.matrix)if(!std::isfinite(v)||std::fabs(v)>1.0e7f)return false;
    if(r.matrix[3]!=0||r.matrix[7]!=0||r.matrix[11]!=0||r.matrix[15]!=1)return false;
    Dict configs{},styles{};
    if(!dictionary(r.configDictionary,configs,262144)||!dictionary(r.styleDictionary,styles,8192))return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(configs,scratch))return false;
    r.configCount=configs.count-configs.free;r.configVersion=configs.version;
    r.styleCount=styles.count-styles.free;r.styleVersion=styles.version;r.stage=2;
    for(std::uint32_t i=0;i<configs.count;++i) {
        if(GetTickCount64()>=HR_DEADLINE)return false;
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U entry=configs.entries+0x20+24ULL*i,object=pointer(entry+16);std::uint32_t category=0;
        if(!object||!read(object+0x34,category))return false;if(category!=2)continue;
        if(r.materialCount>=kTerrainCatalogCapacity)return false;
        auto& row=r.materials[r.materialCount++];row.object=object;row.category=category;
        if(!read(entry+8,row.dictionaryKey)||!read(object+0x24,row.encodedId)||!read(object+0x2c,row.nameHash)||
           !memory(object+0x10,row.rawFields,sizeof(row.rawFields)))return false;
        const std::uint32_t encoded=row.encodedId^decodeKey;
        row.id=(std::uint32_t(r.keyTable[0x400|(encoded>>24)])<<24)|
               (std::uint32_t(r.keyTable[0x500|((encoded>>16)&255)])<<16)|
               (std::uint32_t(r.keyTable[0x600|((encoded>>8)&255)])<<8)|r.keyTable[0x700|(encoded&255)];
        if(row.id>0x7fffffffU)return false;
    }
    if(!r.materialCount||!stable(configs))return false;
    std::qsort(r.materials,static_cast<std::size_t>(r.materialCount),sizeof(TerrainMaterialRow),catalogCompare);
    for(U i=1;i<r.materialCount;++i)if(r.materials[i-1].id==r.materials[i].id)return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(styles,scratch))return false;
    for(std::uint32_t i=0;i<styles.count;++i) {
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U entry=styles.entries+0x20+24ULL*i;std::uint32_t key=0;const U value=pointer(entry+16);
        if(!value||!read(entry+8,key))return false;
        for(U j=0;j<r.materialCount;++j)if(r.materials[j].id==key){if(r.materials[j].style)return false;r.materials[j].style=value;}
    }
    r.stage=3;float matrix[16]{};reinterpret_cast<Matrix>(s.moduleBase+0x14377c0)(r.root,matrix);
    if(std::memcmp(matrix,r.matrix,sizeof(matrix))||!stable(configs)||!stable(styles)||!catalogCode(s))return false;
    unsigned char fields[48]{};
    for(U i=0;i<r.materialCount;++i)if(!memory(r.materials[i].object+0x10,fields,sizeof(fields))||std::memcmp(fields,r.materials[i].rawFields,sizeof(fields)))return false;
    unsigned char table[256]{};
    for(unsigned i=0;i<8;++i)if(!memory(r.decoderTable+0x20+256ULL*i,table,sizeof(table))||std::memcmp(table,r.keyTable+256*i,sizeof(table)))return false;
    std::uint32_t finalKey=0;if(!read(s.moduleBase+0x578bd50,finalKey)||finalKey!=decodeKey)return false;
    r.stable=1;r.status=0;r.stage=4;return true;
}
#if TERRAIN_CATALOG_GUARD
bool catalogGuard(const GameContextSnapshot& s,TerrainReceipt* o,unsigned char* scratch) {
    const HANDLE heap=GetProcessHeap();auto* actual=static_cast<TerrainCatalogReceipt*>(HeapAlloc(heap,HEAP_ZERO_MEMORY,sizeof(TerrainCatalogReceipt)));
    if(!actual)return false;
    const bool valid=catalogCapture(s,o,*actual,scratch)&&std::memcmp(actual,kTerrainExpectedCatalog,sizeof(*actual))==0;
    HeapFree(heap,0,actual);return valid;
}
#endif
