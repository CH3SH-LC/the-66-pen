#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "game_context_snapshot.h"
#include "game_level_catalog.h"
#if !defined(GSL_ARCHIVE_OFFSET) || !defined(GSL_DICTIONARY_OFFSET) || !defined(GSL_SELECTED_OFFSET) || !defined(GSL_RECORD_ID_OFFSET) || !defined(GSL_DIRTY_OFFSET) || !defined(GSL_EXPECTED_LEVEL_ID) || !defined(GSL_ANCHOR_RVAS) || !defined(GSL_ANCHOR_LENGTHS) || !defined(GSL_ANCHOR_BYTES) || !defined(GSL_HOTFIX_RVAS)
#error "complete version-specific catalog evidence required"
#endif
namespace {
constexpr std::uint32_t anchorRvas[]={GSL_ANCHOR_RVAS},anchorLengths[]={GSL_ANCHOR_LENGTHS},hotfixRvas[]={GSL_HOTFIX_RVAS};
constexpr unsigned char anchorBytes[][1024]={GSL_ANCHOR_BYTES};
static_assert(sizeof(anchorRvas)==sizeof(anchorLengths) && sizeof(anchorRvas)/4==sizeof(anchorBytes)/1024,"anchor dimensions");
bool Copy(void* target,const void* source,std::size_t size) noexcept {
    __try {std::memcpy(target,source,size);return true;}
    __except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
struct Reader {
    LevelCatalogSnapshot* out;
    bool Fail(std::uint32_t code) noexcept {out->status=code;return false;}
    bool Ptr(std::uint64_t p) const noexcept {return p>=0x10000 && p<0x0000800000000000ULL && !(p&7);}
    bool Read(std::uint64_t address,void* target,std::size_t size) noexcept {
        if(!size || size>65536 || out->bytesRead>1048576-size || out->readCalls>=4096)return Fail(5);
        ++out->readCalls;out->bytesRead+=static_cast<std::uint32_t>(size);
        if(address<0x10000 || address>=0x0000800000000000ULL-size)return Fail(3);
        const auto end=address+size;
        for(auto p=address;p<end;) {
            MEMORY_BASIC_INFORMATION region{};
            if(VirtualQuery(reinterpret_cast<const void*>(p),&region,sizeof(region))!=sizeof(region) ||
                region.State!=MEM_COMMIT || (region.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return Fail(3);
            const auto protection=region.Protect&0xff;
            if(protection!=PAGE_READONLY && protection!=PAGE_READWRITE && protection!=PAGE_WRITECOPY &&
                protection!=PAGE_EXECUTE_READ && protection!=PAGE_EXECUTE_READWRITE && protection!=PAGE_EXECUTE_WRITECOPY)return Fail(3);
            const auto next=reinterpret_cast<std::uint64_t>(region.BaseAddress)+region.RegionSize;
            if(next<=p || next>0x0000800000000000ULL)return Fail(3);p=next<end?next:end;
        }
        return Copy(target,reinterpret_cast<const void*>(address),size) || Fail(3);
    }
    template<class T>bool At(std::uint64_t p,std::uint64_t offset,T& value) noexcept {
        if(!Ptr(p) || offset>0x0000800000000000ULL-p)return Fail(3);
        return Read(p+offset,&value,sizeof(value));
    }
    bool Pointer(std::uint64_t p,std::uint64_t offset,std::uint64_t& value) noexcept {
        return At(p,offset,value) && (Ptr(value) || Fail(4));
    }
};
bool Hotfix(Reader& r,const GameContextSnapshot& b) noexcept {
    for(auto offset:hotfixRvas) {
        unsigned char value=0xff;
        if(offset>=b.peImageSize)return r.Fail(2);
        if(!r.Read(b.moduleBase+offset,&value,1))return false;
        if(value!=0)return r.Fail(7);
    }return true;
}
struct Roots {
    std::uint64_t global,save,level,archive,dictionary,gate,gateObject,mode;
    std::uint32_t modeValue,levelId,selectedId;
    unsigned char editing,dirty;
};
bool ReadRoots(Reader& r,const GameContextSnapshot& b,Roots& a) noexcept {
    if(!r.Pointer(b.moduleBase,GS_GLOBAL_SLOT_RVA,a.global) || a.global!=b.global ||
       !r.Pointer(a.global,GS_SAVE_MANAGER_OFFSET,a.save) || a.save!=b.saveManager ||
       !r.Pointer(a.global,GS_LEVEL_MANAGER_OFFSET,a.level) ||
       !r.Pointer(a.global,GS_LEVEL_GATE_MANAGER_OFFSET,a.gate) ||
       !r.Pointer(a.gate,GS_LEVEL_GATE_OBJECT_OFFSET,a.gateObject) ||
       !r.Pointer(a.global,GS_LEVEL_MODE_MANAGER_OFFSET,a.mode) ||
       !r.At(a.mode,GS_LEVEL_MODE_OFFSET,a.modeValue) ||
       !r.At(a.level,GS_LEVEL_ID_OFFSET,a.levelId) || !r.At(a.level,GS_LEVEL_EDITING_OFFSET,a.editing) ||
       !r.Pointer(a.save,GSL_ARCHIVE_OFFSET,a.archive) || !r.Pointer(a.archive,GSL_DICTIONARY_OFFSET,a.dictionary) ||
       !r.At(a.archive,GSL_SELECTED_OFFSET,a.selectedId) || !r.At(a.save,GSL_DIRTY_OFFSET,a.dirty))return r.Fail(r.out->status==1?4:r.out->status);
    return (a.modeValue==GS_LEVEL_MODE_REQUIRED && a.editing!=0 && a.levelId==GSL_EXPECTED_LEVEL_ID &&
        a.levelId==b.reserved && a.selectedId==a.levelId && a.dirty<=1) || r.Fail(8);
}
bool Same(const Roots& a,const Roots& b) noexcept {
 return a.global==b.global && a.save==b.save && a.level==b.level && a.archive==b.archive &&
 a.dictionary==b.dictionary && a.gate==b.gate && a.gateObject==b.gateObject && a.mode==b.mode &&
 a.modeValue==b.modeValue && a.levelId==b.levelId && a.selectedId==b.selectedId && a.editing==b.editing && a.dirty==b.dirty;
}
template<class T>T From(const unsigned char* data,std::size_t offset) noexcept {T value{};std::memcpy(&value,data+offset,sizeof(value));return value;}
}
void CaptureGameLevelCatalog(const GameContextSnapshot* baseline,LevelCatalogSnapshot* out) noexcept {
 if(!out)return;*out={};out->structSize=sizeof(*out);out->version=1;out->status=1;
 if(!baseline || baseline->status!=GS_OK || (baseline->flags&1951)!=1951 || (baseline->flags&96) ||
    baseline->entityRejected || baseline->entityCaptured!=baseline->entityValidEntries)return;
 Reader r{out};const auto& b=*baseline;out->flags=1;
 for(std::size_t i=0;i<sizeof(anchorRvas)/sizeof(anchorRvas[0]);++i) {
    const auto length=anchorLengths[i];unsigned char actual[1024]{};
    if(!length || length>sizeof(actual) || anchorRvas[i]>=b.peImageSize || length>b.peImageSize-anchorRvas[i]){out->status=2;return;}
    if(!r.Read(b.moduleBase+anchorRvas[i],actual,length))return;
    if(std::memcmp(actual,anchorBytes[i],length)!=0){out->status=2;return;}
 }out->flags|=2;
 if(!Hotfix(r,b))return;
 Roots before{};if(!ReadRoots(r,b,before))return;
 out->archive=before.archive;out->dictionary=before.dictionary;out->levelManager=before.level;
 out->levelId=before.levelId;out->selectedId=before.selectedId;out->dirtyByte=before.dirty;
 unsigned char header[0x48]{},headerAfter[0x48]{};
 if(!r.Read(before.dictionary,header,sizeof(header)))return;
 out->buckets=From<std::uint64_t>(header,0x20);out->entries=From<std::uint64_t>(header,0x28);out->comparer=From<std::uint64_t>(header,0x30);
 if(out->comparer && !r.Ptr(out->comparer)){out->status=4;return;}
 const auto count=From<std::int32_t>(header,0x38),free=From<std::int32_t>(header,0x40);out->versionBefore=From<std::uint32_t>(header,0x3c);
 std::uint64_t bucketsLength=0,entriesLength=0;
 if(!r.At(out->buckets,0x18,bucketsLength) || !r.At(out->entries,0x18,entriesLength))return;
 if(!bucketsLength || !entriesLength || bucketsLength>kMaxLevelCatalog || entriesLength>kMaxLevelCatalog){out->status=5;return;}
 out->bucketCapacity=static_cast<std::uint32_t>(bucketsLength);out->entryCapacity=static_cast<std::uint32_t>(entriesLength);
 out->initializedCount=static_cast<std::uint32_t>(count);out->freeCount=static_cast<std::uint32_t>(free);
 std::int32_t buckets[kMaxLevelCatalog]{},bucketsAfter[kMaxLevelCatalog]{};
 LevelCatalogEntry entries[kMaxLevelCatalog]{},entriesAfter[kMaxLevelCatalog]{};
 const auto bucketBytes=out->bucketCapacity*sizeof(buckets[0]),entryBytes=out->entryCapacity*sizeof(entries[0]);
 if(!r.Read(out->buckets+0x20,buckets,bucketBytes) || !r.Read(out->entries+0x20,entries,entryBytes))return;
 out->parserError=ParseLevelCatalog(buckets,out->bucketCapacity,entries,out->entryCapacity,count,free,
    [&r](std::uint64_t record,std::uint32_t& id) noexcept {return r.At(record,GSL_RECORD_ID_OFFSET,id);},*out);
 if(out->parserError){if(out->status==1)out->status=4;return;}
 bool activeFound=false;for(std::uint32_t i=0;i<out->recordCount;++i)if(out->rows[i].id==out->levelId)activeFound=true;
 if(!activeFound){out->status=4;return;}out->flags|=8;
 std::uint64_t bucketsLengthAfter=0,entriesLengthAfter=0;
 if(!r.Read(out->dictionary,headerAfter,sizeof(headerAfter)) || !r.At(out->buckets,0x18,bucketsLengthAfter) ||
    !r.At(out->entries,0x18,entriesLengthAfter) || !r.Read(out->buckets+0x20,bucketsAfter,bucketBytes) ||
    !r.Read(out->entries+0x20,entriesAfter,entryBytes))return;
 out->versionAfter=From<std::uint32_t>(headerAfter,0x3c);
 if(std::memcmp(header,headerAfter,sizeof(header)) || std::memcmp(buckets,bucketsAfter,bucketBytes) ||
    std::memcmp(entries,entriesAfter,entryBytes) || bucketsLengthAfter!=bucketsLength || entriesLengthAfter!=entriesLength){out->status=6;return;}
 for(std::uint32_t i=0;i<out->recordCount;++i) {
    std::uint32_t id=0;if(!r.At(out->rows[i].record,GSL_RECORD_ID_OFFSET,id))return;
    if(id!=out->rows[i].id){out->status=6;return;}
 }
 Roots after{};if(!ReadRoots(r,b,after))return;if(!Same(before,after)){out->status=6;return;}out->flags|=16;
 if(!Hotfix(r,b))return;out->flags|=4;out->status=0;
}
