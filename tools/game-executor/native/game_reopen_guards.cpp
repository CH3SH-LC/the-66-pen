#include "game_reopen_guards.h"
#include "guard_profile.generated.h"
#include <cstring>
namespace guarddraft {namespace {
bool Ptr(std::uint64_t p) noexcept {return p>=0x10000 && p<0x800000000000ULL && !(p&7);}
struct Reader {
 ReadBytes read;void* user;Scratch& scratch;Result& out;
 bool Fail(std::uint32_t s) noexcept {out.status=s;return false;}
 bool Bytes(std::uint64_t p,void* dst,std::size_t n) noexcept {
  if(!n||n>16384||out.readCalls>=2048||n>131072-out.readBytes)return Fail(LIMIT);
  if(p<0x10000||p>=0x800000000000ULL||n>0x800000000000ULL-p)return Fail(UNREADABLE);
  if(!read(user,p,dst,n))return Fail(UNREADABLE);
  auto& s=scratch.spans[out.readCalls++];s={p,out.readBytes,static_cast<std::uint32_t>(n)};
  std::memcpy(scratch.bytes+out.readBytes,dst,n);out.readBytes+=static_cast<std::uint32_t>(n);return true;
 }
 template<class T>bool At(std::uint64_t p,std::uint64_t offset,T& v) noexcept {
  return (Ptr(p)&&offset<0x800000000000ULL-p) ? Bytes(p+offset,&v,sizeof(v)):Fail(UNREADABLE);
 }
 bool Pointer(std::uint64_t p,std::uint64_t off,std::uint64_t& v) noexcept {return At(p,off,v)&&(Ptr(v)||Fail(STRUCTURE));}
 bool Recheck() noexcept {
  unsigned char actual[16384]{};
  for(std::uint32_t i=0;i<out.readCalls;++i){const auto& s=scratch.spans[i];
   if(!read(user,s.address,actual,s.size))return Fail(UNREADABLE);
   ++out.recheckCalls;out.recheckBytes+=s.size;
   if(std::memcmp(actual,scratch.bytes+s.offset,s.size))return Fail(UNSTABLE);
  }return true;
 }
};
bool Stamp(const EvidenceStamp& a,const EvidenceStamp& b) noexcept {
 return a.invocation && a.invocation==b.invocation && a.processCreation==b.processCreation && a.processId==b.processId && !a.reserved&&!b.reserved;
}
bool Prerequisites(const Inputs& i,Result& o) noexcept {
 if(!i.context||!i.catalog||!i.type||!i.scheduler||i.current.processId!=kPid||i.current.processCreation!=kCreation||
    !Stamp(i.current,i.contextStamp)||!Stamp(i.current,i.catalogStamp)||!Stamp(i.current,i.typeStamp)||!Stamp(i.current,i.schedulerStamp)||
    std::memcmp(i.diskImageSha256,kImageSha,32))return false;
 const auto& b=*i.context;const auto& c=*i.catalog;const auto& t=*i.type;const auto& s=*i.scheduler;
 if(b.structSize!=sizeof(b)||b.version!=1||b.status!=0||(b.flags&1951)!=1951||(b.flags&96)||b.entityRejected||
    b.entityCaptured!=b.entityValidEntries||b.entityCaptured>kMaxEntities||b.reserved!=kLevel||
    b.peTimestamp!=kTimestamp||b.peImageSize!=kImageSize||!Ptr(b.moduleBase)||!Ptr(b.global)||!Ptr(b.saveManager))return false;
 if(c.structSize!=sizeof(c)||c.version!=1||c.status!=0||c.flags!=31||c.parserError||c.reserved||c.levelId!=kLevel||c.selectedId!=kLevel||
    c.dirtyByte||c.recordCount<1||c.recordCount>512||c.versionBefore!=c.versionAfter||c.initializedCount<c.freeCount||
    c.recordCount!=c.initializedCount-c.freeCount||c.entryCapacity>512||c.bucketCapacity>512||!c.bucketCapacity||c.initializedCount>c.entryCapacity)return false;
 std::uint32_t hits=0;for(std::uint32_t n=0;n<c.recordCount;++n){if(c.rows[n].id!=c.rows[n].key||!Ptr(c.rows[n].record))return false;
  for(std::uint32_t j=0;j<n;++j)if(c.rows[n].id==c.rows[j].id||c.rows[n].record==c.rows[j].record)return false;
  if(c.rows[n].id==kLevel){o.currentRecord=c.rows[n].record;++hits;}}
 if(hits!=1)return false;
 if(t.structSize!=sizeof(t)||t.version!=1||t.status||t.flags!=255||t.parserError||t.reserved||t.moduleBase!=b.moduleBase||t.imageSize!=kImageSize||t.levelId!=kLevel||
    t.classSlot!=b.moduleBase+0x5826620||t.initializedBefore!=1||t.initializedAfter!=1||!Ptr(t.classPointer)||t.slotCountBefore<1||t.slotCountBefore>128||
    t.slotCountBefore!=t.slotCountAfter||t.matchCount!=1||t.matchIndex>=t.slotCountBefore||t.expectedFunction!=b.moduleBase+0x9037840||
    t.functionsAddress!=t.classPointer+0xd0||t.trailingWordsAddress!=t.functionsAddress+8*t.slotCountBefore)return false;
 hits=0;for(std::uint32_t n=0;n<t.slotCountBefore;++n)if(t.functions[n]==t.expectedFunction)++hits;
 if(hits!=1||t.functions[t.matchIndex]!=t.expectedFunction)return false;
 o.invocation=i.current.invocation;o.moduleBase=b.moduleBase;o.global=b.global;o.levelId=kLevel;
 o.schedulerStatus=s.status;o.schedulerFlags=s.flags;o.schedulerTargetCount=s.targetCount;o.schedulerUnavailableCount=s.unavailableCount;o.schedulerRows=s.rowCount;
 if(s.structSize!=sizeof(s)||s.version!=1||s.status>8||(s.flags&~1023U)||s.rowCount>128)return false;
 if(s.flags&768U){
  const bool saturated=(s.flags&512U)!=0;const auto count=static_cast<std::int32_t>(s.listCountBefore);
  if(s.status!=5||s.flags!=(263U|(saturated?512U:0U))||s.rowCount||s.targetCount||s.unavailableCount||s.otherCount||s.nullHandleCount||
     s.listCountAfter||s.versionAfter||s.referencePolicyAfter||(saturated&&s.listCapacity!=UINT32_MAX)||
     (count>=0&&count<=128&&s.listCapacity<=INT32_MAX&&static_cast<std::uint32_t>(count)<=s.listCapacity))return false;
  const SchedulerCoroutineRow zero{};for(const auto& row:s.rows)if(std::memcmp(&row,&zero,sizeof(row)))return false;
 }
 if(s.status!=0){
  // Failed same-invocation sampling is an observation limitation, not a false guard or absence proof.
  if((s.moduleBase&&s.moduleBase!=b.moduleBase)||(s.global&&s.global!=b.global)||(s.levelId&&s.levelId!=kLevel)||
     (s.targetClass&&s.targetClass!=t.classPointer)||(s.classSlot&&s.classSlot!=t.classSlot))return false;
  return true;
 }
 if(s.structSize!=sizeof(s)||s.version!=1||s.status||s.flags!=255||s.moduleBase!=b.moduleBase||s.global!=b.global||s.levelId!=kLevel||
    s.targetClass!=t.classPointer||s.classSlot!=t.classSlot||s.typeSlotCount!=t.slotCountBefore||s.listCountBefore!=s.listCountAfter||
    s.versionBefore!=s.versionAfter||s.referencePolicyBefore!=s.referencePolicyAfter||s.rowCount!=s.listCountBefore||s.listCapacity>INT32_MAX||s.rowCount>s.listCapacity)return false;
 std::uint32_t target=0,unavailable=0,other=0,nulls=0;
 for(std::uint32_t n=0;n<s.rowCount;++n){const auto& r=s.rows[n];if(r.index!=n||r.reserved||r.disposition!=ClassifySchedulerRow(r,s.targetClass,s.lifecycleOwner,s.coroutineClass))return false;
  if(r.disposition==SC_TARGET)++target;else if(r.disposition==SC_NULL_HANDLE)++nulls;
  else if(r.disposition==SC_OTHER_CLASS||r.disposition==SC_OTHER_OWNER)++other;else ++unavailable;}
 if(target!=s.targetCount||unavailable!=s.unavailableCount||other!=s.otherCount||nulls!=s.nullHandleCount)return false;
 o.invocation=i.current.invocation;o.moduleBase=b.moduleBase;o.global=b.global;o.levelId=kLevel;
 o.schedulerTargetCount=target;o.schedulerUnavailableCount=unavailable;o.schedulerRows=s.rowCount;o.schedulerComplete=1;return true;
}
bool Code(Reader& r,std::uint64_t base) noexcept {
 for(const auto& a:kAnchors){unsigned char raw[2048]{};if(!a.size||a.size>2048||a.rva>kImageSize-a.size)return r.Fail(ANCHOR);
  if(!r.Bytes(base+a.rva,raw,a.size))return false;if(std::memcmp(raw,a.bytes,a.size))return r.Fail(ANCHOR);}
 for(auto x:kHotfix){unsigned char v=255;if(!r.Bytes(base+x,&v,1))return false;if(v)return r.Fail(HOTFIX);}return true;
}
// Pinned default-comparer lookup: one target bucket, then its collision chain; stop at first match.
// No full-dictionary enumeration or uniqueness claim. Never inspect mode value+0x2c.
bool LookupMode(Reader& r,std::uint64_t dict,std::uint32_t key,std::uint64_t& value) noexcept {
 std::uint64_t buckets=0,entries=0,comparer=0,bc=0,ec=0;std::int32_t count=0,free=0;std::uint32_t version=0;
 if(!r.Pointer(dict,0x20,buckets)||!r.Pointer(dict,0x28,entries)||!r.At(dict,0x30,comparer)||!r.At(dict,0x38,count)||
    !r.At(dict,0x3c,version)||!r.At(dict,0x40,free)||!r.At(buckets,0x18,bc)||!r.At(entries,0x18,ec))return false;
 auto& d=r.out.modeDiagnostic;d={1,LOOKUP_NONE,bc,ec,count,free,version,0};
 if(comparer){d.lookupRefusalStage=LOOKUP_COMPARER;return r.Fail(UNKNOWN_BRANCH);}
 if(!bc||!ec||bc>INT32_MAX||ec>INT32_MAX){d.lookupRefusalStage=LOOKUP_CAPACITY;return r.Fail(LIMIT);}
 if(count<0||free<0||free>count||static_cast<std::uint64_t>(count)>ec){d.lookupRefusalStage=LOOKUP_COUNTS;return r.Fail(STRUCTURE);}
 const auto hash=key&0x7fffffffU;const auto bucket=hash%static_cast<std::uint32_t>(bc);std::int32_t head=0;
 if(!r.At(buckets,0x20+static_cast<std::uint64_t>(bucket)*4,head)){d.lookupRefusalStage=LOOKUP_READ;return false;}
 if(!head){d.lookupRefusalStage=LOOKUP_NOT_FOUND;return r.Fail(UNKNOWN_BRANCH);}
 if(head<0||static_cast<std::uint64_t>(head)>ec){d.lookupRefusalStage=LOOKUP_CHAIN;return r.Fail(STRUCTURE);}
 std::uint32_t seen[512]{};std::int32_t index=head-1;
 for(;;){
  if(d.visitedEntries>=512){d.lookupRefusalStage=LOOKUP_VISIT_LIMIT;return r.Fail(LIMIT);}
  if(index<0||static_cast<std::uint64_t>(index)>=ec){d.lookupRefusalStage=LOOKUP_CHAIN;return r.Fail(STRUCTURE);}
  for(std::uint32_t j=0;j<d.visitedEntries;++j)if(seen[j]==static_cast<std::uint32_t>(index)){d.lookupRefusalStage=LOOKUP_CHAIN;return r.Fail(STRUCTURE);}
  LevelCatalogEntry entry{};
  if(!r.At(entries,0x20+static_cast<std::uint64_t>(index)*sizeof(entry),entry)){d.lookupRefusalStage=LOOKUP_READ;return false;}
  seen[d.visitedEntries++]=static_cast<std::uint32_t>(index);
  if(static_cast<std::uint32_t>(entry.hash)==hash&&entry.key==key){
   if(!Ptr(entry.value)){d.lookupRefusalStage=LOOKUP_CHAIN;return r.Fail(STRUCTURE);}value=entry.value;return true;
  }
  if(entry.next==-1){d.lookupRefusalStage=LOOKUP_NOT_FOUND;return r.Fail(UNKNOWN_BRANCH);}
  index=entry.next;
 }
}
bool Roots(Reader& r,const Inputs& i) noexcept {
 const auto& b=*i.context;const auto& c=*i.catalog;const auto& t=*i.type;const auto& s=*i.scheduler;
 std::uint64_t global=0,save=0,level=0,gate=0,gateObject=0,mode=0,archive=0,dict=0,owner=0,scheduler=0,klass=0,list=0,array=0;
 std::uint32_t levelId=0,selected=0,modeId=0,id=0,dictVersion=0;unsigned char editing=0,dirty=255,initialized=0;std::uint16_t slots=0;
 if(!r.Pointer(b.moduleBase,0x5783de8,global)||!r.Pointer(global,0xdb50,save)||!r.Pointer(global,0xa960,level)||
    !r.Pointer(global,0xa430,gate)||!r.Pointer(gate,0x50,gateObject)||!r.Pointer(global,0xa440,mode)||!r.At(mode,0x1cc,modeId)||
    !r.At(level,0x98,levelId)||!r.At(level,0xc9,editing)||!r.Pointer(save,0x48,archive)||!r.Pointer(archive,0x28,dict)||
    !r.At(archive,0x38,selected)||!r.At(save,0xa2,dirty)||!r.At(r.out.currentRecord,0x2c,id)||!r.At(dict,0x3c,dictVersion)||
    !r.Pointer(global,0xbfd0,owner)||!r.Pointer(global,0xa040,scheduler)||!r.Pointer(b.moduleBase,0x5826620,klass)||
    !r.At(b.moduleBase,0x5aa8dd1,initialized)||!r.At(klass,0xbe,slots))return false;
 if(global!=b.global||save!=b.saveManager||level!=c.levelManager||modeId!=0xb993||levelId!=kLevel||selected!=kLevel||id!=kLevel||!editing||dirty||
    archive!=c.archive||dict!=c.dictionary||dictVersion!=c.versionAfter||(s.lifecycleOwner&&owner!=s.lifecycleOwner)||(s.scheduler&&scheduler!=s.scheduler)||klass!=t.classPointer||
    slots!=t.slotCountBefore||initialized!=1)return r.Fail(STRUCTURE);
 std::uint64_t fn[128]{};if(!r.Bytes(klass+0xd0,fn,slots*8))return false;
 if(std::memcmp(fn,t.functions,slots*8))return r.Fail(UNSTABLE);
 // Bind full current catalog membership (not just a pointer with a matching ID).
 std::uint64_t cb=0,ce=0,cmp=0,bc=0,ec=0;std::int32_t count=0,free=0;
 if(!r.Pointer(dict,0x20,cb)||!r.Pointer(dict,0x28,ce)||!r.At(dict,0x30,cmp)||!r.At(dict,0x38,count)||!r.At(dict,0x40,free)||
    !r.At(cb,0x18,bc)||!r.At(ce,0x18,ec))return false;
 if(cb!=c.buckets||ce!=c.entries||cmp!=c.comparer||bc!=c.bucketCapacity||ec!=c.entryCapacity||count!=static_cast<std::int32_t>(c.initializedCount)||free!=static_cast<std::int32_t>(c.freeCount))return r.Fail(STRUCTURE);
 std::int32_t bs[512]{};LevelCatalogEntry es[512]{};LevelCatalogSnapshot now{};
 if(!r.Bytes(cb+0x20,bs,static_cast<std::size_t>(bc)*4)||!r.Bytes(ce+0x20,es,static_cast<std::size_t>(ec)*24))return false;
 r.out.parserError=ParseLevelCatalog(bs,static_cast<std::uint32_t>(bc),es,static_cast<std::uint32_t>(ec),count,free,
   [&r](std::uint64_t v,std::uint32_t& x) noexcept{return r.At(v,0x2c,x);},now);
 if(r.out.parserError||now.recordCount!=c.recordCount||std::memcmp(now.rows,c.rows,c.recordCount*sizeof(LevelCatalogRow)))return r.Fail(STRUCTURE);
 if(s.status!=0){r.out.modeId=modeId;return true;}
 if(!r.Pointer(scheduler,0x20,list)||!r.Pointer(list,0x10,array))return false;
 if(list!=s.list||array!=s.array)return r.Fail(UNSTABLE);
 std::int32_t sc=0;std::uint32_t sv=0;std::uint64_t cap=0;
 if(!r.At(list,0x18,sc)||!r.At(list,0x1c,sv)||!r.At(array,0x18,cap))return false;
 if(sc!=static_cast<std::int32_t>(s.rowCount)||sv!=s.versionAfter||cap!=s.listCapacity)return r.Fail(UNSTABLE);
 // Revalidate list handles only. Holder fields remain the same-invocation scheduler producer's responsibility.
 std::uint64_t handles[128]{};if(s.rowCount&&!r.Bytes(array+0x20,handles,static_cast<std::size_t>(s.rowCount)*8))return false;
 for(std::uint32_t n=0;n<s.rowCount;++n)if(handles[n]!=s.rows[n].handle)return r.Fail(UNSTABLE);
 r.out.modeId=modeId;return true;
}
bool Confirmation(Reader& r) noexcept {
 auto& o=r.out;std::uint64_t klass=0,manager=0,context=0,value=0,target=0,actual=0,hierarchy=0,ancestor=0;unsigned char init=0,td=0,ad=0;
 if(!r.Pointer(o.moduleBase,0x57cc7f8,klass)||!r.At(klass,0xc7,init))return false;
 if(!init)return r.Fail(UNINITIALIZED);
 if(!r.At(o.global,0xf390,manager))return false;
 if(!manager){o.confirmation=FALSE_VALUE;o.confirmationReason=1;return true;}
 if(!r.At(manager,0x30,context))return false;
 if(!context){o.confirmationReason=2;return r.Fail(UNKNOWN_BRANCH);}
 if(!r.At(context,0x18,value))return false;
 if(!value){o.confirmation=FALSE_VALUE;o.confirmationReason=3;return true;}
 if(!r.Pointer(o.moduleBase,0x5808090,target)||!r.Pointer(value,0,actual)||!r.At(target,0xc5,td)||!r.At(actual,0xc5,ad))return false;
 if(!td||td>128||ad>128)return r.Fail(LIMIT);
 if(ad<td){o.confirmation=FALSE_VALUE;o.confirmationReason=4;return true;}
 if(!r.Pointer(actual,0x40,hierarchy)||!r.At(hierarchy,static_cast<std::uint64_t>(td-1)*8,ancestor))return false;
 if(!Ptr(ancestor))return r.Fail(STRUCTURE);
 o.confirmation=ancestor==target?TRUE_VALUE:FALSE_VALUE;o.confirmationReason=5;return true;
}
bool Early(Reader& r) noexcept {
 auto& o=r.out;std::uint64_t klass=0;unsigned char metadata=0,init=0;
 if(!r.At(o.moduleBase,0x5aab638,metadata)||!r.Pointer(o.moduleBase,0x57af200,klass)||!r.At(klass,0xc7,init))return false;
 if(metadata!=1||!init)return r.Fail(UNINITIALIZED);
 if(!r.Pointer(o.global,0x24b50,o.modeDictionary)||!LookupMode(r,o.modeDictionary,o.modeId,o.modeRecord))return false;
 if(!r.At(o.modeRecord,0x84,o.modeEncoded)||!r.At(o.moduleBase,0x578bd50,o.xorKey)||!r.Pointer(o.global,0xf620,o.table)||!r.At(o.table,0x18,o.tableLength))return false;
 if(o.tableLength<0x800||o.tableLength>65536)return r.Fail(LIMIT);
 unsigned char table[1024]{};if(!r.Bytes(o.table+0x420,table,sizeof(table)))return false;
 const auto x=o.modeEncoded^o.xorKey;
 o.decoded=(std::uint32_t(table[(x>>24)&255])<<24)|(std::uint32_t(table[0x100|((x>>16)&255)])<<16)|
           (std::uint32_t(table[0x200|((x>>8)&255)])<<8)|std::uint32_t(table[0x300|(x&255)]);
 if(!o.decoded){o.earlyReason=2;return r.Fail(UNKNOWN_BRANCH);}o.earlyAbort=FALSE_VALUE;o.earlyReason=1;return true;
}
}
void Evaluate(const Inputs& i,ReadBytes read,void* user,Scratch& scratch,Result& out) noexcept {
 out={};out.structSize=sizeof(out);out.version=2;out.status=INPUT_REFUSED;
 bool stable=false;struct Finalize{Result& o;bool& stable;~Finalize(){if(!stable){o.confirmation=UNKNOWN;o.earlyAbort=UNKNOWN;}}} finalize{out,stable};
 if(!read||!Prerequisites(i,out))return;out.flags=1;Reader r{read,user,scratch,out};
 if(!Code(r,out.moduleBase))return;out.flags|=2;
 if(!Roots(r,i))return;out.flags|=4;
 const bool confirmation=Confirmation(r);const auto confirmationStatus=out.status;
 // Only semantic unknown/known branches may continue; a bad read or bound invalidates the attempt.
 if(!confirmation&&confirmationStatus!=UNKNOWN_BRANCH&&confirmationStatus!=UNINITIALIZED)return;
 out.status=INPUT_REFUSED;const bool early=Early(r);const auto earlyStatus=out.status;
 if(!early&&earlyStatus!=UNKNOWN_BRANCH&&earlyStatus!=UNINITIALIZED)return;
 if(!r.Recheck()){out.confirmation=UNKNOWN;out.earlyAbort=UNKNOWN;return;}out.flags|=8;stable=true;
 out.status=(confirmation&&early)?OK:(!confirmation?confirmationStatus:earlyStatus);
 // TRUE confirmation is a successfully observed boolean, but no action approval is emitted.
}
}
