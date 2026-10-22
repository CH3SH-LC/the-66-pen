#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstring>
#include "game_context_snapshot.h"
#include "game_lifecycle_type.h"
#include "game_scheduler_coroutines.h"
#if !defined(GSC_ANCHOR_RVAS) || !defined(GSC_ANCHOR_LENGTHS) || !defined(GSC_ANCHOR_BYTES) || !defined(GSC_HOTFIX_RVAS) || !defined(GSC_EXPECTED_LEVEL_ID)
#error "complete version-specific scheduler profile required"
#endif
namespace {
constexpr std::uint32_t anchorRvas[]={GSC_ANCHOR_RVAS},anchorLengths[]={GSC_ANCHOR_LENGTHS},hotfixRvas[]={GSC_HOTFIX_RVAS};
constexpr unsigned char anchorBytes[][4096]={GSC_ANCHOR_BYTES};
static_assert(sizeof(anchorRvas)==sizeof(anchorLengths) && sizeof(anchorRvas)/4==sizeof(anchorBytes)/4096,"anchor dimensions");
bool Copy(void* target,const void* source,std::size_t size) noexcept {
 __try {std::memcpy(target,source,size);return true;}
 __except(EXCEPTION_EXECUTE_HANDLER){return false;}
}
struct Reader {
 SchedulerCoroutinesSnapshot* out;
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
 std::uint64_t global,save,level,gate,gateObject,mode,scheduler,list,array,owner,klass,capacity,managedTypesRoot,coroutineClass;
 std::int32_t count;std::uint32_t version,modeValue,levelId;
 std::uint16_t typeCount;unsigned char editing,initialized,referencePolicy;
};
bool Pointer(Reader& r,std::uint64_t p,std::uint64_t offset,std::uint64_t& result) noexcept {
 return r.At(p,offset,result) && (r.Ptr(result)||r.Fail(4));
}
bool RootsRead(Reader& r,const GameContextSnapshot& b,const LifecycleTypeSnapshot& t,Roots& x) noexcept {
 if(!r.Image(b,GS_GLOBAL_SLOT_RVA,&x.global,8) || !r.Ptr(x.global) ||
    !Pointer(r,x.global,GS_SAVE_MANAGER_OFFSET,x.save) || !Pointer(r,x.global,GS_LEVEL_MANAGER_OFFSET,x.level) ||
    !Pointer(r,x.global,GS_LEVEL_GATE_MANAGER_OFFSET,x.gate) || !Pointer(r,x.gate,GS_LEVEL_GATE_OBJECT_OFFSET,x.gateObject) ||
    !Pointer(r,x.global,GS_LEVEL_MODE_MANAGER_OFFSET,x.mode) || !r.At(x.mode,GS_LEVEL_MODE_OFFSET,x.modeValue) ||
    !r.At(x.level,GS_LEVEL_ID_OFFSET,x.levelId) || !r.At(x.level,GS_LEVEL_EDITING_OFFSET,x.editing) ||
    !Pointer(r,x.global,GSC_SCHEDULER_OFFSET,x.scheduler) || !Pointer(r,x.global,GSC_OWNER_OFFSET,x.owner) ||
    !Pointer(r,x.scheduler,GSC_LIST_OFFSET,x.list) || !Pointer(r,x.list,GSC_ARRAY_OFFSET,x.array) ||
    !r.At(x.list,GSC_COUNT_OFFSET,x.count) || !r.At(x.list,GSC_VERSION_OFFSET,x.version) ||
    !r.At(x.array,GSC_ARRAY_CAPACITY_OFFSET,x.capacity) || !r.Image(b,GSC_INITIALIZED_RVA,&x.initialized,1))return false;
 if(!r.Image(b,GSC_REFERENCE_POLICY_RVA,&x.referencePolicy,1))return false;
 if(x.initialized!=1)return r.Fail(8);
 if(!r.Image(b,GSC_MANAGED_TYPES_ROOT_RVA,&x.managedTypesRoot,8))return false;
 if(!x.managedTypesRoot)return r.Fail(8);
 if(!Pointer(r,x.managedTypesRoot,GSC_COROUTINE_CLASS_OFFSET,x.coroutineClass))return false;
 if(!r.Image(b,GSC_CLASS_SLOT_RVA,&x.klass,8) || !r.Ptr(x.klass) || !r.At(x.klass,GSC_TYPE_COUNT_OFFSET,x.typeCount))return false;
 if(x.global!=b.global || x.save!=b.saveManager || x.modeValue!=GS_LEVEL_MODE_REQUIRED || !x.editing ||
    x.levelId!=b.reserved || x.levelId!=GSC_EXPECTED_LEVEL_ID || x.klass!=t.classPointer || x.typeCount!=t.slotCountBefore)return r.Fail(8);
 if(!ValidSchedulerListBounds(x.count,x.capacity)) {
  // Preserve first-pass values only. A failed second pass must not overwrite the first sample.
  if(!(r.out->flags&8)) {
   auto& out=*r.out;out.moduleBase=b.moduleBase;out.global=x.global;out.scheduler=x.scheduler;out.list=x.list;
   out.array=x.array;out.lifecycleOwner=x.owner;out.targetClass=x.klass;out.classSlot=b.moduleBase+GSC_CLASS_SLOT_RVA;
   out.managedTypesRoot=x.managedTypesRoot;out.coroutineClass=x.coroutineClass;out.levelId=x.levelId;
   out.typeSlotCount=x.typeCount;out.referencePolicyBefore=x.referencePolicy;
   RecordSchedulerBoundsDiagnostic(out,x.count,x.capacity,x.version);
  }
  return r.Fail(5);
 }
 std::uint64_t functions[kMaxLifecycleTypeSlots]{};
 if(!r.Read(x.klass+GSC_TYPE_FUNCTIONS_OFFSET,functions,static_cast<std::size_t>(x.typeCount)*8))return false;
 if(std::memcmp(functions,t.functions,static_cast<std::size_t>(x.typeCount)*8))return r.Fail(6);
 return true;
}
bool Same(const Roots& a,const Roots& b) noexcept {
 return a.global==b.global&&a.save==b.save&&a.level==b.level&&a.gate==b.gate&&a.gateObject==b.gateObject&&a.mode==b.mode&&
 a.scheduler==b.scheduler&&a.list==b.list&&a.array==b.array&&a.owner==b.owner&&a.klass==b.klass&&a.capacity==b.capacity&&
 a.count==b.count&&a.version==b.version&&a.modeValue==b.modeValue&&a.levelId==b.levelId&&a.typeCount==b.typeCount&&
 a.editing==b.editing&&a.initialized==b.initialized&&a.managedTypesRoot==b.managedTypesRoot&&a.coroutineClass==b.coroutineClass&&a.referencePolicy==b.referencePolicy;
}
bool RowRead(Reader& r,std::uint64_t handle,std::uint32_t index,const Roots& roots,SchedulerCoroutineRow& row) noexcept {
 row={};row.handle=handle;row.index=index;
 if(!handle){row.disposition=SC_NULL_HANDLE;return true;}
 if(!r.Ptr(handle))return r.Fail(4);
 if(!r.At(handle,0,row.handleClass))return false;
 if(row.handleClass!=roots.coroutineClass){row.disposition=SC_OTHER_HANDLE_CLASS;return true;}
 if(!r.At(handle,GSC_HANDLE_HOLDER_OFFSET,row.holder))return false;
 if(!row.holder){row.disposition=SC_NULL_HOLDER;return true;}
 if(!r.Ptr(row.holder))return r.Fail(4);
 unsigned char released=0;
 if(!r.At(row.holder,GSC_HOLDER_TOKEN_OFFSET,row.gcTokenOpaque) || !r.At(row.holder,GSC_HOLDER_KIND_OFFSET,row.referenceKind) ||
    !r.At(row.holder,GSC_HOLDER_ITERATOR_OFFSET,row.iterator) || !r.At(row.holder,GSC_HOLDER_NATIVE_OWNER_OFFSET,row.holderNativeOwner) ||
    !r.At(row.holder,GSC_HOLDER_REFCOUNT_OFFSET,row.referenceCount) || !r.At(row.holder,GSC_HOLDER_RETENTION_OFFSET,row.retainedByWrapper) ||
    !r.At(row.holder,GSC_HOLDER_RELEASED_OFFSET,released))return false;
 row.released=released;
 // A released holder or unknown reference kind never authorizes following iterator or GC token.
 if(!row.released && row.referenceKind==2 && row.retainedByWrapper==1 && row.referenceCount>0 &&
    row.holder!=row.handle && row.iterator && row.iterator!=row.handle && row.iterator!=row.holder) {
  if(!r.Ptr(row.iterator))return r.Fail(4);
  if(!r.At(row.iterator,0,row.iteratorClass))return false;
  if(!r.Ptr(row.iteratorClass))return r.Fail(4);
  if(row.iteratorClass==roots.klass) {
   if(!r.At(row.iterator,GSC_ITERATOR_OWNER_OFFSET,row.iteratorOwner) || !r.At(row.iterator,GSC_ITERATOR_STATE_OFFSET,row.state) ||
      !r.At(row.iterator,GSC_ITERATOR_CURRENT_OFFSET,row.currentYield))return false;
  }
 }
 row.disposition=ClassifySchedulerRow(row,roots.klass,roots.owner,roots.coroutineClass);return true;
}
}
void CaptureGameSchedulerCoroutines(const GameContextSnapshot* baseline,const LifecycleTypeSnapshot* type,SchedulerCoroutinesSnapshot* out) noexcept {
 if(!out)return;*out={};out->structSize=sizeof(*out);out->version=1;out->status=1;
 if(!baseline || baseline->status!=GS_OK || (baseline->flags&1951)!=1951 || (baseline->flags&96) ||
    baseline->entityRejected || baseline->entityCaptured!=baseline->entityValidEntries || baseline->reserved!=GSC_EXPECTED_LEVEL_ID ||
    !type || type->structSize!=sizeof(*type) || type->version!=1 || type->status!=0 || type->flags!=kLifecycleTypeRequiredFlags ||
    type->moduleBase!=baseline->moduleBase || type->levelId!=baseline->reserved || type->matchCount!=1 ||
    type->slotCountBefore!=type->slotCountAfter || !type->slotCountBefore || type->slotCountBefore>kMaxLifecycleTypeSlots ||
    type->matchIndex>=type->slotCountBefore || type->expectedFunction!=baseline->moduleBase+GSC_TARGET_FUNCTION_RVA ||
    type->functions[type->matchIndex]!=type->expectedFunction)return;
 Reader r{out};const auto& b=*baseline;out->flags=1;
 if(!Code(r,b))return;out->flags|=2;
 if(!Hotfix(r,b))return;out->flags|=4;
 Roots before{};if(!RootsRead(r,b,*type,before))return;out->flags|=8;
 out->moduleBase=b.moduleBase;out->global=before.global;out->scheduler=before.scheduler;out->list=before.list;
 out->array=before.array;out->lifecycleOwner=before.owner;out->targetClass=before.klass;out->classSlot=b.moduleBase+GSC_CLASS_SLOT_RVA;
 out->managedTypesRoot=before.managedTypesRoot;out->coroutineClass=before.coroutineClass;
 out->levelId=before.levelId;out->listCountBefore=static_cast<std::uint32_t>(before.count);out->listCapacity=static_cast<std::uint32_t>(before.capacity);
 out->versionBefore=before.version;out->typeSlotCount=before.typeCount;out->referencePolicyBefore=before.referencePolicy;
 std::uint64_t handles[kMaxSchedulerCoroutineHandles]{},handlesAfter[kMaxSchedulerCoroutineHandles]{};
 // Only logical List elements are read; capacity tail is not part of the sample.
 const auto arrayBytes=static_cast<std::size_t>(before.count)*8;
 if(arrayBytes && !r.Read(before.array+GSC_ARRAY_DATA_OFFSET,handles,arrayBytes))return;
 for(std::uint32_t i=0;i<out->listCountBefore;++i) {
  auto& row=out->rows[i];if(!RowRead(r,handles[i],i,before,row))return;
  ++out->rowCount;
  if(row.disposition==SC_NULL_HANDLE)++out->nullHandleCount;
  else if(row.disposition==SC_TARGET)++out->targetCount;
  else if(row.disposition==SC_OTHER_CLASS || row.disposition==SC_OTHER_OWNER)++out->otherCount;
  else ++out->unavailableCount;
 }out->flags|=16;
 // Re-read every observed row, including holder markers and null handles; do not call any resolver.
 for(std::uint32_t i=0;i<out->rowCount;++i) {
  SchedulerCoroutineRow after{};if(!RowRead(r,handles[i],i,before,after))return;
  if(std::memcmp(&after,&out->rows[i],sizeof(after))){out->status=6;return;}
 }
 if(arrayBytes && !r.Read(before.array+GSC_ARRAY_DATA_OFFSET,handlesAfter,arrayBytes))return;
 if(std::memcmp(handles,handlesAfter,arrayBytes)){out->status=6;return;}
 Roots after{};if(!RootsRead(r,b,*type,after))return;
 out->listCountAfter=static_cast<std::uint32_t>(after.count);out->versionAfter=after.version;out->referencePolicyAfter=after.referencePolicy;
 if(!Same(before,after)){out->status=6;return;}out->flags|=32;
 if(!Code(r,b))return;out->flags|=64;
 if(!Hotfix(r,b))return;out->flags|=128;out->status=0;
}
