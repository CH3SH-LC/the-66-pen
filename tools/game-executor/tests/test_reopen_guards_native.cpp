#include "game_reopen_guards.h"
#include "guard_profile.generated.h"
#include <map>
#include <vector>
#include <functional>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include <string>
#include <cstring>
using namespace guarddraft;using U=std::uint64_t;
constexpr U B=0x140000000,G=0x10000000,SAVE=0x20000000,LEVEL=0x21000000,GATE=0x22000000,GATEOBJ=0x23000000,MODE=0x24000000,ARCHIVE=0x25000000;
constexpr U LD=0x26000000,LB=0x27000000,LE=0x28000000,LR=0x29000000,OWNER=0x30000000,SCHED=0x31000000,LIST=0x32000000,ARRAY=0x33000000,TYPE=0x34000000;
constexpr U CC=0x35000000,EC=0x36000000,CM=0x37000000,CTX=0x38000000,OBJ=0x39000000,TT=0x40000000,AC=0x41000000,HIER=0x42000000;
constexpr U MD=0x43000000,MB=0x44000000,ME=0x45000000,MR=0x46000000,TABLE=0x47000000,COROUTINE=0x48000000,HANDLE=0x49000000;
struct Memory {
 std::map<U,std::vector<unsigned char>> blocks;std::map<U,int> calls;U deny=0,changeAddress=0;int changeAt=0;std::function<void(Memory&)> mutation;
 void add(U a,std::size_t n){blocks[a]=std::vector<unsigned char>(n);}
 void raw(U a,const void* p,std::size_t n){auto x=blocks.upper_bound(a);if(x==blocks.begin())throw std::runtime_error("write missing");--x;if(a-x->first+n>x->second.size())throw std::runtime_error("write range");std::memcpy(x->second.data()+a-x->first,p,n);}
 template<class T>void put(U a,T v){raw(a,&v,sizeof(v));}
 template<class T>void field(U a,U off,T v){put<T>(a+off,v);}
 static bool read(void* u,U a,void* p,std::size_t n) noexcept {
  auto& m=*static_cast<Memory*>(u);try{const int c=++m.calls[a];if(a==m.deny)return false;if(a==m.changeAddress&&c==m.changeAt)m.mutation(m);
   auto x=m.blocks.upper_bound(a);if(x==m.blocks.begin())return false;--x;if(a-x->first+n>x->second.size())return false;std::memcpy(p,x->second.data()+a-x->first,n);return true;
  }catch(...){return false;}
 }
};
struct Fixture {
 Memory m;GameContextSnapshot b{};LevelCatalogSnapshot c{};LifecycleTypeSnapshot t{};SchedulerCoroutinesSnapshot s{};Inputs i{};Scratch scratch{};Result out{};
 Fixture(){
  for(const auto& a:kAnchors){m.add(B+a.rva,a.size);m.raw(B+a.rva,a.bytes,a.size);}for(auto x:kHotfix)m.add(B+x,1);
  for(U x:{0x5783de8ULL,0x5826620ULL,0x57cc7f8ULL,0x57af200ULL,0x5808090ULL})m.add(B+x,8);
  m.add(B+0x5aa8dd1,1);m.add(B+0x5aab638,1);m.add(B+0x578bd50,4);
  m.add(G,0x26000);for(U x:{SAVE,LEVEL,GATE,GATEOBJ,MODE,ARCHIVE,LD,LB,LE,LR,OWNER,SCHED,LIST,ARRAY,TYPE,CC,EC,CM,CTX,OBJ,TT,AC,HIER,MD,MB,ME,MR,COROUTINE,HANDLE})m.add(x,0x1000);m.add(TABLE,0x820);
  m.put<U>(B+0x5783de8,G);m.put<U>(B+0x5826620,TYPE);m.put<U>(B+0x57cc7f8,CC);m.put<U>(B+0x57af200,EC);m.put<U>(B+0x5808090,TT);
  m.put<unsigned char>(B+0x5aa8dd1,1);m.put<unsigned char>(B+0x5aab638,1);m.put<unsigned char>(CC+0xc7,1);m.put<unsigned char>(EC+0xc7,1);
  for(auto x:std::vector<std::pair<U,U>>{{0xdb50,SAVE},{0xa960,LEVEL},{0xa430,GATE},{0xa440,MODE},{0xbfd0,OWNER},{0xa040,SCHED},{0xf390,CM},{0x24b50,MD},{0xf620,TABLE}})m.put<U>(G+x.first,x.second);
  m.put<U>(GATE+0x50,GATEOBJ);m.put<std::uint32_t>(MODE+0x1cc,0xb993);m.put<std::uint32_t>(LEVEL+0x98,kLevel);m.put<unsigned char>(LEVEL+0xc9,1);m.put<U>(SAVE+0x48,ARCHIVE);m.put<U>(ARCHIVE+0x28,LD);m.put<std::uint32_t>(ARCHIVE+0x38,kLevel);
  dictionary(LD,LB,LE,kLevel,LR);m.put<std::uint32_t>(LR+0x2c,kLevel);
  m.put<U>(SCHED+0x20,LIST);m.put<U>(LIST+0x10,ARRAY);m.put<U>(ARRAY+0x18,1);
  m.put<std::uint16_t>(TYPE+0xbe,9);for(int n=0;n<9;++n)m.put<U>(TYPE+0xd0+n*8,n==6?B+0x9037840:B+0x1000+n*8);
  m.put<U>(CM+0x30,CTX);m.put<U>(CTX+0x18,OBJ);m.put<U>(OBJ,AC);m.put<unsigned char>(TT+0xc5,2);m.put<unsigned char>(AC+0xc5,2);m.put<U>(AC+0x40,HIER);m.put<U>(HIER+8,TYPE);
  dictionary(MD,MB,ME,0xb993,MR);m.put<std::uint32_t>(MR+0x84,0x12345678);m.put<std::uint32_t>(B+0x578bd50,0x01020304);m.put<std::uint32_t>(TABLE+0x18,0x800);
  m.put<unsigned char>(TABLE+0x20+0x413,1); // XOR high byte 0x13 => nonzero decoded; other selected bytes zero.
  b.structSize=sizeof(b);b.version=1;b.flags=1951;b.moduleBase=B;b.global=G;b.saveManager=SAVE;b.peTimestamp=kTimestamp;b.peImageSize=kImageSize;b.reserved=kLevel;b.entityCaptured=b.entityValidEntries=1;
  c.structSize=sizeof(c);c.version=1;c.flags=31;c.archive=ARCHIVE;c.dictionary=LD;c.buckets=LB;c.entries=LE;c.levelManager=LEVEL;c.levelId=c.selectedId=kLevel;c.initializedCount=c.recordCount=1;c.bucketCapacity=c.entryCapacity=3;c.versionBefore=c.versionAfter=7;c.rows[0]={kLevel,kLevel,LR};
  t.structSize=sizeof(t);t.version=1;t.flags=255;t.moduleBase=B;t.imageSize=kImageSize;t.classSlot=B+0x5826620;t.classPointer=TYPE;t.functionsAddress=TYPE+0xd0;t.trailingWordsAddress=TYPE+0xd0+72;t.expectedFunction=B+0x9037840;t.levelId=kLevel;t.initializedBefore=t.initializedAfter=1;t.slotCountBefore=t.slotCountAfter=9;t.matchCount=1;t.matchIndex=6;
  for(int n=0;n<9;++n)t.functions[n]=n==6?B+0x9037840:B+0x1000+n*8;
  s.structSize=sizeof(s);s.version=1;s.flags=255;s.moduleBase=B;s.global=G;s.scheduler=SCHED;s.list=LIST;s.array=ARRAY;s.lifecycleOwner=OWNER;s.targetClass=TYPE;s.classSlot=t.classSlot;s.coroutineClass=COROUTINE;s.typeSlotCount=9;s.levelId=kLevel;s.listCapacity=1;
  i.current={77,kCreation,kPid,0};i.contextStamp=i.catalogStamp=i.typeStamp=i.schedulerStamp=i.current;std::memcpy(i.diskImageSha256,kImageSha,32);i.context=&b;i.catalog=&c;i.type=&t;i.scheduler=&s;
 }
 void dictionary(U d,U bucket,U e,std::uint32_t key,U value){m.put<U>(d+0x20,bucket);m.put<U>(d+0x28,e);m.put<std::int32_t>(d+0x38,1);m.put<std::uint32_t>(d+0x3c,7);m.put<U>(bucket+0x18,3);m.put<U>(e+0x18,3);m.put<std::int32_t>(bucket+0x20+(key%3)*4,1);LevelCatalogEntry row{static_cast<std::int32_t>(key),-1,key,0,value};m.raw(e+0x20,&row,sizeof(row));}
 Result run(){Evaluate(i,Memory::read,&m,scratch,out);return out;}
 void unavailable(){s.listCountBefore=s.listCountAfter=s.rowCount=1;s.unavailableCount=1;s.rows[0].index=0;s.rows[0].handle=HANDLE;s.rows[0].handleClass=COROUTINE;s.rows[0].disposition=SC_NULL_HOLDER;m.put<std::int32_t>(LIST+0x18,1);m.put<U>(ARRAY+0x20,HANDLE);}
};
int main(int argc,char** argv){int count=0;auto test=[&](const char* name,const std::function<void(Fixture&)>& change,std::uint32_t status,std::uint32_t cf=UNKNOWN,std::uint32_t ef=UNKNOWN,std::uint32_t decoded=0){
 Fixture f;change(f);auto r=f.run();if(r.status!=status||r.confirmation!=cf||r.earlyAbort!=ef||(decoded&&r.decoded!=decoded))throw std::runtime_error(std::string(name)+" status="+std::to_string(r.status)+" cf="+std::to_string(r.confirmation)+" ef="+std::to_string(r.earlyAbort));std::cout<<"PASS "<<name<<"\n";++count;
 if(argc>1&&(std::string(name)=="valid"||std::string(name)=="cache_null"||std::string(name)=="unavailable_scheduler"||std::string(name)=="partial_scheduler"||std::string(name)=="confirmation_true")){std::ofstream of(std::string(argv[1])+"/"+name+".bin",std::ios::binary);of.write(reinterpret_cast<const char*>(&r),sizeof(r));}
 };
 try{
 test("valid",[](auto&){},OK,FALSE_VALUE,FALSE_VALUE);
 test("manager_null",[](auto& f){f.m.template put<U>(G+0xf390,0);},OK,FALSE_VALUE,FALSE_VALUE);
 test("value_null",[](auto& f){f.m.template put<U>(CTX+0x18,0);},OK,FALSE_VALUE,FALSE_VALUE);
 test("shallower_type",[](auto& f){f.m.template put<unsigned char>(AC+0xc5,1);},OK,FALSE_VALUE,FALSE_VALUE);
 test("actual_depth_zero_native_false",[](auto& f){f.m.template put<unsigned char>(AC+0xc5,0);},OK,FALSE_VALUE,FALSE_VALUE);
 test("four_byte_decode",[](auto& f){f.m.template put<unsigned char>(TABLE+0x20+0x413,0x12);f.m.template put<unsigned char>(TABLE+0x20+0x536,0x34);f.m.template put<unsigned char>(TABLE+0x20+0x655,0x56);f.m.template put<unsigned char>(TABLE+0x20+0x77c,0x78);},OK,FALSE_VALUE,FALSE_VALUE,0x12345678);
 test("confirmation_true",[](auto& f){f.m.template put<U>(HIER+8,TT);},OK,TRUE_VALUE,FALSE_VALUE);
 test("cache_null",[](auto& f){f.m.template put<U>(CM+0x30,0);},UNKNOWN_BRANCH,UNKNOWN,FALSE_VALUE);
 test("decode_zero",[](auto& f){f.m.template put<unsigned char>(TABLE+0x433,0);},UNKNOWN_BRANCH,FALSE_VALUE,UNKNOWN);
 test("unavailable_scheduler",[](auto& f){f.unavailable();},OK,FALSE_VALUE,FALSE_VALUE);
 test("mode_value_not_level_record",[](auto& f){f.m.template put<std::uint32_t>(MR+0x2c,0xdeadbeef);},OK,FALSE_VALUE,FALSE_VALUE);
 test("stale_stamp",[](auto& f){f.i.catalogStamp.invocation=76;},INPUT_REFUSED);
 test("wrong_identity",[](auto& f){f.i.current.processId=1;},INPUT_REFUSED);
 test("wrong_hash",[](auto& f){f.i.diskImageSha256[0]^=1;},INPUT_REFUSED);
 test("partial_context",[](auto& f){f.b.flags|=32;},INPUT_REFUSED);
 test("catalog_dirty",[](auto& f){f.c.dirtyByte=1;},INPUT_REFUSED);
 test("type_not_complete",[](auto& f){f.t.matchCount=0;},INPUT_REFUSED);
 test("partial_scheduler",[](auto& f){f.s.status=5;f.s.flags=7;f.s.moduleBase=f.s.global=f.s.targetClass=f.s.classSlot=f.s.lifecycleOwner=f.s.scheduler=f.s.list=f.s.array=0;f.s.levelId=0;},OK,FALSE_VALUE,FALSE_VALUE);
 test("scheduler_large_capacity_prefix",[](auto& f){f.s.listCapacity=1600;f.s.listCountBefore=f.s.listCountAfter=f.s.rowCount=f.s.nullHandleCount=3;for(unsigned n=0;n<3;++n)f.s.rows[n].index=n;f.m.template put<U>(ARRAY+0x18,1600);f.m.template put<std::int32_t>(LIST+0x18,3);},OK,FALSE_VALUE,FALSE_VALUE);
 test("scheduler_capacity_overflow",[](auto& f){f.s.listCapacity=0x80000000;},INPUT_REFUSED);
 test("scheduler_count_diagnostic",[](auto& f){f.s.status=5;f.s.flags=263;f.s.listCountBefore=129;f.s.listCapacity=1600;},OK,FALSE_VALUE,FALSE_VALUE);
 test("scheduler_saturated_diagnostic",[](auto& f){f.s.status=5;f.s.flags=775;f.s.listCountBefore=3;f.s.listCapacity=UINT32_MAX;},OK,FALSE_VALUE,FALSE_VALUE);
 test("scheduler_invalid_diagnostic",[](auto& f){f.s.status=5;f.s.flags=775;f.s.listCapacity=1600;},INPUT_REFUSED);
 test("scheduler_success_with_failure_bits",[](auto& f){f.s.flags=511;},INPUT_REFUSED);
 test("stale_scheduler_stamp",[](auto& f){f.i.schedulerStamp.invocation=76;},INPUT_REFUSED);
 test("scheduler_inconsistent_count",[](auto& f){f.s.targetCount=1;},INPUT_REFUSED);
 test("live_dirty",[](auto& f){f.m.template put<unsigned char>(SAVE+0xa2,1);},STRUCTURE);
 test("catalog_membership_changed",[](auto& f){f.m.template put<U>(LE+0x30,MR);},STRUCTURE);
 test("class_uninitialized",[](auto& f){f.m.template put<unsigned char>(CC+0xc7,0);},UNINITIALIZED,UNKNOWN,FALSE_VALUE);
 test("early_uninitialized",[](auto& f){f.m.template put<unsigned char>(B+0x5aab638,0);},UNINITIALIZED,FALSE_VALUE,UNKNOWN);
 test("type_zero_depth",[](auto& f){f.m.template put<unsigned char>(TT+0xc5,0);},LIMIT);
 test("type_depth_limit",[](auto& f){f.m.template put<unsigned char>(AC+0xc5,129);},LIMIT);
 test("custom_comparer",[](auto& f){f.m.template put<U>(MD+0x30,TYPE);},UNKNOWN_BRANCH,FALSE_VALUE,UNKNOWN);
 test("entry_capacity_over_512_is_metadata",[](auto& f){f.m.template put<U>(ME+0x18,1600);},OK,FALSE_VALUE,FALSE_VALUE);
 test("dictionary_bad_count",[](auto& f){f.m.template put<std::int32_t>(MD+0x38,4);},STRUCTURE);
 test("empty_target_bucket_unknown",[](auto& f){f.m.template put<std::int32_t>(MB+0x20+(0xb993%3)*4,0);},UNKNOWN_BRANCH,FALSE_VALUE,UNKNOWN);
 test("matched_next_is_not_followed",[](auto& f){f.m.template put<std::int32_t>(ME+0x24,0);},OK,FALSE_VALUE,FALSE_VALUE);
 test("nonmatching_hash_unknown",[](auto& f){f.m.template put<std::int32_t>(ME+0x20,0xb994);},UNKNOWN_BRANCH,FALSE_VALUE,UNKNOWN);
 test("dictionary_missing_key",[](auto& f){f.m.template put<std::int32_t>(ME+0x20,0xb990);f.m.template put<std::uint32_t>(ME+0x28,0xb990);},UNKNOWN_BRANCH,FALSE_VALUE,UNKNOWN);
 test("table_small",[](auto& f){f.m.template put<std::uint32_t>(TABLE+0x18,0x7ff);},LIMIT);
 test("table_limit",[](auto& f){f.m.template put<std::uint32_t>(TABLE+0x18,65537);},LIMIT);
 test("unreadable",[](auto& f){f.m.deny=MR+0x84;},UNREADABLE);
 test("anchor_changed",[](auto& f){f.m.template put<unsigned char>(B+kAnchors[0].rva,0);},ANCHOR);
 test("hotfix_active",[](auto& f){f.m.template put<unsigned char>(B+kHotfix[0],1);},HOTFIX);
 for(auto row:std::vector<std::pair<const char*,U>>{{"root_changed",B+0x5783de8},{"key_changed",B+0x578bd50},{"version_changed",MD+0x3c},{"rows_changed",ME+0x20},{"table_changed",TABLE+0x420},{"metadata_changed",B+0x5aab638},{"post_anchor_changed",B+kAnchors[0].rva},{"post_hotfix_changed",B+kHotfix[0]}}){test(row.first,[=](auto& f){f.m.changeAddress=row.second;f.m.changeAt=2;f.m.mutation=[=](auto& m){auto it=m.blocks.upper_bound(row.second);--it;it->second[static_cast<std::size_t>(row.second-it->first)]^=1;};},UNSTABLE);}
 auto check=[&](bool value,const char* name){if(!value)throw std::runtime_error(name);++count;std::cout<<"PASS "<<name<<"\n";};
 {Fixture f;f.m.put<U>(MB+0x18,0x100000001ULL);f.m.put<U>(ME+0x18,0x200000005ULL);f.m.put<std::int32_t>(MD+0x38,7);f.m.put<std::int32_t>(MD+0x40,2);f.m.put<std::uint32_t>(MD+0x3c,123);auto r=f.run();check(r.structSize==208&&r.version==2&&r.status==LIMIT&&r.confirmation==UNKNOWN&&r.earlyAbort==UNKNOWN&&r.modeDiagnostic.observed==1&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_CAPACITY&&r.modeDiagnostic.bucketCapacity==0x100000001ULL&&r.modeDiagnostic.entryCapacity==0x200000005ULL&&r.modeDiagnostic.count==7&&r.modeDiagnostic.freeCount==2&&r.modeDiagnostic.version==123&&!r.recheckCalls&&!r.modeDiagnostic.visitedEntries,"exact_uint64_capacity_metadata");}
 {Fixture f;f.m.put<std::int32_t>(MD+0x38,-2);f.m.put<std::int32_t>(MD+0x40,-7);auto r=f.run();check(r.status==STRUCTURE&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_COUNTS&&r.modeDiagnostic.count==-2&&r.modeDiagnostic.freeCount==-7&&r.confirmation==UNKNOWN&&r.earlyAbort==UNKNOWN,"signed_metadata_refusal");}
 {Fixture f;f.m.blocks[MB].resize(0x20+1600*4);f.m.put<U>(MB+0x18,1600);f.m.put<U>(ME+0x18,1600);f.m.put<std::int32_t>(MB+0x20+(0xb993%1600)*4,1);auto r=f.run();check(r.status==OK&&r.modeDiagnostic.bucketCapacity==1600&&r.modeDiagnostic.entryCapacity==1600&&r.modeDiagnostic.visitedEntries==1&&r.modeLiveEntries==0,"large_capacity_single_target");}
 {Fixture f;LevelCatalogEntry first{1,1,1,0,0},second{0xb993,-1,0xb993,0,MR};f.m.raw(ME+0x20,&first,sizeof(first));f.m.raw(ME+0x38,&second,sizeof(second));f.m.put<std::int32_t>(MD+0x38,2);auto r=f.run();check(r.status==OK&&r.modeDiagnostic.visitedEntries==2,"collision_chain_first_match");}
 {Fixture f;f.m.put<std::int32_t>(ME+0x24,INT32_MAX);f.m.deny=ME+0x38;auto r=f.run();check(r.status==OK&&r.modeDiagnostic.visitedEntries==1&&!f.m.calls[ME+0x38],"damaged_successor_not_read_after_match");}
 {Fixture f;f.m.put<std::int32_t>(ME+0x20,1);f.m.put<std::int32_t>(ME+0x24,0);auto r=f.run();check(r.status==STRUCTURE&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_CHAIN&&r.modeDiagnostic.visitedEntries==1,"visited_chain_cycle_refused");}
 {Fixture f;f.m.put<std::int32_t>(MB+0x20+(0xb993%3)*4,4);auto r=f.run();check(r.status==STRUCTURE&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_CHAIN&&!r.modeDiagnostic.visitedEntries,"head_out_of_capacity_refused");}
 {Fixture f;f.m.put<std::int32_t>(ME+0x20,1);f.m.put<std::int32_t>(ME+0x24,99);auto r=f.run();check(r.status==STRUCTURE&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_CHAIN&&r.modeDiagnostic.visitedEntries==1,"next_out_of_capacity_refused");}
 {Fixture f;f.m.blocks[ME].resize(0x20+513*24);f.m.put<U>(ME+0x18,513);f.m.put<std::int32_t>(MD+0x38,513);for(int n=0;n<513;++n){LevelCatalogEntry row{1,n==512?-1:n+1,1,0,0};f.m.raw(ME+0x20+static_cast<U>(n)*24,&row,sizeof(row));}auto r=f.run();check(r.status==LIMIT&&r.modeDiagnostic.lookupRefusalStage==LOOKUP_VISIT_LIMIT&&r.modeDiagnostic.visitedEntries==512&&!f.m.calls[ME+0x20+512*24],"visit_limit_512_no_tail_read");}
 {Fixture f;f.m.changeAddress=MB+0x18;f.m.changeAt=2;f.m.mutation=[](auto& m){m.template put<U>(MB+0x18,4);};auto r=f.run();check(r.status==UNSTABLE&&r.confirmation==UNKNOWN&&r.earlyAbort==UNKNOWN,"metadata_recheck_change_refused");}
 std::cout<<"TOTAL "<<count<<"\n";return 0;
 }catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<"\n";return 1;}
}
