#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "game_context_snapshot.h"
#include "game_lifecycle_type.h"
#if !defined(GLT_CLASS_SLOT_RVA) || !defined(GLT_INITIALIZED_RVA) || !defined(GLT_SLOT_COUNT_OFFSET) || !defined(GLT_FUNCTIONS_OFFSET) || !defined(GLT_TARGET_FUNCTION_RVA) || !defined(GLT_EXPECTED_LEVEL_ID) || !defined(GLT_ANCHOR_RVAS) || !defined(GLT_ANCHOR_LENGTHS) || !defined(GLT_ANCHOR_BYTES) || !defined(GLT_HOTFIX_RVAS)
#error "complete version-specific lifecycle evidence required"
#endif
namespace {
constexpr std::uint32_t anchorRvas[]={GLT_ANCHOR_RVAS},anchorLengths[]={GLT_ANCHOR_LENGTHS},hotfixRvas[]={GLT_HOTFIX_RVAS};
constexpr unsigned char anchorBytes[][4096]={GLT_ANCHOR_BYTES};
static_assert(sizeof(anchorRvas)==sizeof(anchorLengths) && sizeof(anchorRvas)/4==sizeof(anchorBytes)/4096,"anchor dimensions");
bool Copy(void* target,const void* source,std::size_t size) noexcept {
 __try {std::memcpy(target,source,size);return true;}
 __except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
struct Reader {
 LifecycleTypeSnapshot* out;
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
 bool Image(const GameContextSnapshot& b,std::uint32_t rva,void* target,std::size_t length) noexcept {
  if(rva>=b.peImageSize || length>b.peImageSize-rva)return Fail(2);
  return Read(b.moduleBase+rva,target,length);
 }
};
bool Code(Reader& r,const GameContextSnapshot& b) noexcept {
 for(std::size_t i=0;i<sizeof(anchorRvas)/sizeof(anchorRvas[0]);++i) {
  const auto length=anchorLengths[i];unsigned char actual[4096]{};
  if(!length || length>sizeof(actual))return r.Fail(2);
  if(!r.Image(b,anchorRvas[i],actual,length))return false;
  if(std::memcmp(actual,anchorBytes[i],length))return r.Fail(2);
 }return true;
}
bool Hotfix(Reader& r,const GameContextSnapshot& b) noexcept {
 for(auto rva:hotfixRvas) {
  unsigned char value=0xff;if(!r.Image(b,rva,&value,1))return false;
  if(value)return r.Fail(7);
 }return true;
}
struct Roots {
 std::uint64_t global,save,level,gate,gateObject,mode;
 std::uint32_t modeValue,levelId;unsigned char editing;
};
bool RootsRead(Reader& r,const GameContextSnapshot& b,Roots& x) noexcept {
 if(!r.Image(b,GS_GLOBAL_SLOT_RVA,&x.global,sizeof(x.global)) || !r.Ptr(x.global) ||
    !r.At(x.global,GS_SAVE_MANAGER_OFFSET,x.save) || !r.At(x.global,GS_LEVEL_MANAGER_OFFSET,x.level) ||
    !r.At(x.global,GS_LEVEL_GATE_MANAGER_OFFSET,x.gate) || !r.At(x.gate,GS_LEVEL_GATE_OBJECT_OFFSET,x.gateObject) ||
    !r.At(x.global,GS_LEVEL_MODE_MANAGER_OFFSET,x.mode) || !r.At(x.mode,GS_LEVEL_MODE_OFFSET,x.modeValue) ||
    !r.At(x.level,GS_LEVEL_ID_OFFSET,x.levelId) || !r.At(x.level,GS_LEVEL_EDITING_OFFSET,x.editing))return false;
 return (x.global==b.global && x.save==b.saveManager && r.Ptr(x.save) && r.Ptr(x.level) && r.Ptr(x.gateObject) &&
    x.modeValue==GS_LEVEL_MODE_REQUIRED && x.levelId==b.reserved && x.levelId==GLT_EXPECTED_LEVEL_ID && x.editing!=0) || r.Fail(1);
}
bool RootsSame(const Roots& a,const Roots& b) noexcept {
 return a.global==b.global && a.save==b.save && a.level==b.level && a.gate==b.gate && a.gateObject==b.gateObject &&
 a.mode==b.mode && a.modeValue==b.modeValue && a.levelId==b.levelId && a.editing==b.editing;
}
}
void CaptureGameLifecycleType(const GameContextSnapshot* baseline,LifecycleTypeSnapshot* out) noexcept {
 if(!out)return;*out={};out->structSize=sizeof(*out);out->version=1;out->status=1;out->matchIndex=0xffffffffu;
 if(!baseline || baseline->status!=GS_OK || (baseline->flags&1951)!=1951 || (baseline->flags&96) ||
    baseline->entityRejected || baseline->entityCaptured!=baseline->entityValidEntries || baseline->reserved!=GLT_EXPECTED_LEVEL_ID)return;
 Reader r{out};const auto& b=*baseline;Roots rootsBefore{};
 if(!RootsRead(r,b,rootsBefore))return;
 out->flags=1;out->moduleBase=b.moduleBase;out->imageSize=b.peImageSize;out->levelId=b.reserved;
 if(GLT_CLASS_SLOT_RVA>=b.peImageSize || 8>b.peImageSize-GLT_CLASS_SLOT_RVA || GLT_TARGET_FUNCTION_RVA>=b.peImageSize){out->status=2;return;}
 out->classSlot=b.moduleBase+GLT_CLASS_SLOT_RVA;out->expectedFunction=b.moduleBase+GLT_TARGET_FUNCTION_RVA;
 if(!Code(r,b))return;out->flags|=2;
 if(!Hotfix(r,b))return;out->flags|=4;
 unsigned char initialized=0;
 if(!r.Image(b,GLT_INITIALIZED_RVA,&initialized,1))return;out->initializedBefore=initialized;
 // This is the allocator wrapper's lazy metadata flag, not a global lifecycle
 // readiness flag. A readonly probe may observe an independently populated type
 // slot while the flag is zero. Such evidence must never satisfy write guards.
#if GS_BOOTSTRAP_READONLY == 1
 const bool diagnosticOnly=initialized==0;
 if(initialized!=1 && !diagnosticOnly){out->status=8;return;}
 if(!diagnosticOnly)out->flags|=8;
#else
 if(initialized!=1){out->status=8;return;}out->flags|=8;
#endif
 if(!r.Read(out->classSlot,&out->classPointer,8))return;
#if GS_BOOTSTRAP_READONLY == 1
 // Bit 256 only exists on the non-success readonly diagnostic path. It says
 // the slot was read, including a null value; zero pointers without it are unknown.
 if(diagnosticOnly) {
  out->flags|=256;
  if(!out->classPointer){out->status=8;return;}
 }
#endif
 if(!r.Ptr(out->classPointer)){out->status=4;return;}
 std::uint16_t count=0;if(!r.At(out->classPointer,GLT_SLOT_COUNT_OFFSET,count))return;out->slotCountBefore=count;
 if(!count || count>kMaxLifecycleTypeSlots){out->status=5;return;}
 out->functionsAddress=out->classPointer+GLT_FUNCTIONS_OFFSET;
 out->trailingWordsAddress=out->functionsAddress+count*8;
 const auto length=static_cast<std::size_t>(count)*8;
 if(!r.Read(out->functionsAddress,out->functions,length) || !r.Read(out->trailingWordsAddress,out->trailingWords,length))return;
 out->parserError=MatchLifecycleFunction(out->functions,count,out->expectedFunction,out->matchCount,out->matchIndex);
 if(out->parserError){out->status=out->parserError==3?9:out->parserError==4?10:4;return;}out->flags|=16;
 std::uint64_t functionsAfter[kMaxLifecycleTypeSlots]{},infosAfter[kMaxLifecycleTypeSlots]{},classAfter=0;
 std::uint16_t countAfter=0;unsigned char initializedAfter=0;
 if(!r.Image(b,GLT_INITIALIZED_RVA,&initializedAfter,1) || !r.Read(out->classSlot,&classAfter,8) ||
    !r.At(out->classPointer,GLT_SLOT_COUNT_OFFSET,countAfter) || !r.Read(out->functionsAddress,functionsAfter,length) ||
    !r.Read(out->trailingWordsAddress,infosAfter,length))return;
 out->initializedAfter=initializedAfter;out->slotCountAfter=countAfter;
 if(initializedAfter!=initialized || classAfter!=out->classPointer || countAfter!=count ||
    std::memcmp(functionsAfter,out->functions,length) || std::memcmp(infosAfter,out->trailingWords,length)){out->status=6;return;}
 Roots rootsAfter{};if(!RootsRead(r,b,rootsAfter))return;
 if(!RootsSame(rootsBefore,rootsAfter)){out->status=6;return;}out->flags|=32;
 if(!Code(r,b))return;out->flags|=64;
 if(!Hotfix(r,b))return;out->flags|=128;
#if GS_BOOTSTRAP_READONLY == 1
 // Fully stable diagnostic binding is status 8 / flags 503, never status 0 / 255.
 out->status=diagnosticOnly?8:0;
#else
 out->status=0;
#endif
}
