// The actual renderer reads material style+30 -> TileWaterConfig+10 list,
// matches TileWaterTypeConfig+10, instantiates prefab+18 and applies scaleY+20.
// Capture only already-loaded objects; no lazy getters or game allocation.
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
    const auto& x=*static_cast<const TerrainWaterTypeRow*>(a);const auto& y=*static_cast<const TerrainWaterTypeRow*>(b);
    if(x.materialId!=y.materialId)return x.materialId<y.materialId?-1:1;
    return x.typeId<y.typeId?-1:x.typeId>y.typeId?1:0;
}
bool catalogCapture(const GameContextSnapshot& s,TerrainReceipt* o,TerrainCatalogReceipt& r,unsigned char* scratch) {
    std::memset(&r,0,sizeof(r));r.size=sizeof(r);r.version=1;r.status=1;r.stage=1;
    if(!catalogCode(s))return false;
    r.root=pointer(pointer(o->owner+0xc0)+0x18);r.styleDictionary=pointer(pointer(o->manager+0x10)+0x18);
    if(!r.root||!memory(s.moduleBase+0x578d658,r.steps,12)||r.steps[0]!=5||r.steps[1]!=2.5f||r.steps[2]!=5)return false;
    using Matrix=void(*)(U,float*);reinterpret_cast<Matrix>(s.moduleBase+0x14377c0)(r.root,r.matrix);
    for(float v:r.matrix)if(!std::isfinite(v)||std::fabs(v)>1.0e7f)return false;
    if(r.matrix[3]!=0||r.matrix[7]!=0||r.matrix[11]!=0||r.matrix[15]!=1)return false;
    Dict styles{};if(!dictionary(r.styleDictionary,styles,8192))return false;
    std::memset(scratch,0,kScratchBytes);if(!reachable(styles,scratch))return false;
    r.styleCount=styles.count-styles.free;r.styleVersion=styles.version;r.stage=2;
    for(std::uint32_t i=0;i<styles.count;++i) {
        if(GetTickCount64()>=HR_DEADLINE)return false;
        if(!(scratch[i/8]&(1U<<(i%8))))continue;
        const U entry=styles.entries+0x20+24ULL*i,style=pointer(entry+16);std::uint32_t material=0;
        if(!style||!read(entry+8,material))return false;
        U config=0;if(!read(style+0x30,config))return false;if(!config)continue;
        const U list=pointer(config+0x10);U items=0,capacity=0;std::uint32_t count=0,version=0;
        if(!list||!read(list+0x18,count)||!read(list+0x1c,version)||count>kWaterCatalogCapacity)return false;
        if(!count)continue;
        items=pointer(list+0x10);if(!items||!read(items+0x18,capacity)||capacity<count||capacity>4096)return false;
        ++r.materialCount;
        for(std::uint32_t j=0;j<count;++j) {
            if(r.waterTypeCount>=kWaterCatalogCapacity)return false;
            auto& row=r.types[r.waterTypeCount++];row.style=style;row.waterConfig=config;row.list=list;
            row.materialId=material;row.listIndex=j;row.listCount=count;row.listVersion=version;
            row.typeConfig=pointer(items+0x20+8ULL*j);
            if(!row.typeConfig||!memory(row.typeConfig+0x10,row.rawType,sizeof(row.rawType)))return false;
            std::memcpy(&row.typeId,row.rawType,4);std::memcpy(&row.prefab,row.rawType+8,8);std::memcpy(&row.scaleY,row.rawType+16,4);
            if(!row.typeId||!std::isfinite(row.scaleY)||row.scaleY<=0||row.scaleY>10000)return false;
            if(row.prefab&&!read(row.prefab+0x10,row.prefabNative))return false;
        }
        U afterItems=0;std::uint32_t afterCount=0,afterVersion=0;
        if(!read(list+0x10,afterItems)||!read(list+0x18,afterCount)||!read(list+0x1c,afterVersion)||afterItems!=items||afterCount!=count||afterVersion!=version)return false;
    }
    if(!r.waterTypeCount||!stable(styles))return false;
    std::qsort(r.types,static_cast<std::size_t>(r.waterTypeCount),sizeof(TerrainWaterTypeRow),catalogCompare);
    for(U i=1;i<r.waterTypeCount;++i)if(catalogCompare(&r.types[i-1],&r.types[i])==0)return false;
    r.stage=3;float matrix[16]{};reinterpret_cast<Matrix>(s.moduleBase+0x14377c0)(r.root,matrix);
    if(std::memcmp(matrix,r.matrix,sizeof(matrix))||!stable(styles)||!catalogCode(s))return false;
    for(U i=0;i<r.waterTypeCount;++i){const auto& row=r.types[i];unsigned char fields[24]{};U config=0,list=0,items=0,prefabNative=0;std::uint32_t count=0,version=0;
        if(!read(row.style+0x30,config)||config!=row.waterConfig||!read(config+0x10,list)||list!=row.list||
           !read(list+0x10,items)||!read(list+0x18,count)||!read(list+0x1c,version)||count!=row.listCount||version!=row.listVersion||
           pointer(items+0x20+8ULL*row.listIndex)!=row.typeConfig||!memory(row.typeConfig+0x10,fields,sizeof(fields))||std::memcmp(fields,row.rawType,sizeof(fields)))return false;
        if(row.prefab&&(!read(row.prefab+0x10,prefabNative)||prefabNative!=row.prefabNative))return false;
    }
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
