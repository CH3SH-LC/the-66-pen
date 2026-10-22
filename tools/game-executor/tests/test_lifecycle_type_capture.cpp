// Runs the production capture core only against this test process's owned pages.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#ifndef DIAGNOSTIC_READONLY
#error "Compile with DIAGNOSTIC_READONLY=0 or 1"
#endif
#define GS_BOOTSTRAP_READONLY DIAGNOSTIC_READONLY
#define HR_READ_LIFECYCLE_TYPE 1
#if DIAGNOSTIC_READONLY
#define HR_ACTION 0
#else
#define HR_ACTION 4
#define GS_REVIEWED_ACTION_PROFILE 1
#define HR_ACTION_PROFILE_REVIEWED 1
#define HR_REOPEN_ACTION_REVIEWED 1
#endif
#define GLT_CLASS_SLOT_RVA 0x108
#define GLT_INITIALIZED_RVA 0x110
#define GLT_SLOT_COUNT_OFFSET 0xbe
#define GLT_FUNCTIONS_OFFSET 0xd0
#define GLT_TARGET_FUNCTION_RVA 0x300
#define GLT_EXPECTED_LEVEL_ID 1073741839
#define GLT_ANCHOR_RVAS 0x180
#define GLT_ANCHOR_LENGTHS 1
#define GLT_ANCHOR_BYTES {0x90}
#define GLT_HOTFIX_RVAS 0x181
#define GS_GLOBAL_SLOT_RVA 0x100
#define GS_SAVE_MANAGER_OFFSET 0x8
#define GS_LEVEL_MANAGER_OFFSET 0x10
#define GS_LEVEL_GATE_MANAGER_OFFSET 0x18
#define GS_LEVEL_GATE_OBJECT_OFFSET 0x8
#define GS_LEVEL_MODE_MANAGER_OFFSET 0x20
#define GS_LEVEL_MODE_OFFSET 0x8
#define GS_LEVEL_MODE_REQUIRED 0xb993
#define GS_LEVEL_ID_OFFSET 0x8
#define GS_LEVEL_EDITING_OFFSET 0xc
static unsigned char* ownedImage=nullptr;
static int slotReads=0,flagReads=0;
static bool mutateFunctions=false,mutateFlag=false,unreadableSlot=false;
static SIZE_T TestVirtualQuery(LPCVOID address,PMEMORY_BASIC_INFORMATION info,SIZE_T bytes) {
 if(address==ownedImage+GLT_CLASS_SLOT_RVA) {
  ++slotReads;
  if(unreadableSlot)return 0;
  if(mutateFunctions && slotReads==2) {
   const std::uint64_t changed=reinterpret_cast<std::uint64_t>(ownedImage)+0x400;
   std::memcpy(ownedImage+0x2000+GLT_FUNCTIONS_OFFSET+8,&changed,sizeof(changed));
  }
 }
 if(address==ownedImage+GLT_INITIALIZED_RVA) {
  ++flagReads;
  if(mutateFlag && flagReads==2)ownedImage[GLT_INITIALIZED_RVA]=1;
 }
 return ::VirtualQuery(address,info,bytes);
}
#define VirtualQuery TestVirtualQuery
#if DIAGNOSTIC_READONLY
#include "../native/game_lifecycle_type.cpp"
#else
#include "../native/game_lifecycle_type_action.cpp"
#endif
#undef VirtualQuery
static int checks=0;
static void Check(bool condition,const char* label) {
 if(!condition){std::printf("FAIL %s\n",label);std::exit(1);}++checks;
}
template<class T>static void Store(std::size_t offset,T value){std::memcpy(ownedImage+offset,&value,sizeof(value));}
static std::uint64_t Address(std::size_t offset){return reinterpret_cast<std::uint64_t>(ownedImage+offset);}
static GameContextSnapshot Reset(unsigned char lazy) {
 std::memset(ownedImage,0,0x4000);slotReads=0;flagReads=0;mutateFunctions=false;mutateFlag=false;unreadableSlot=false;
 Store<std::uint64_t>(GS_GLOBAL_SLOT_RVA,Address(0x1000));
 Store<std::uint64_t>(0x1000+GS_SAVE_MANAGER_OFFSET,Address(0x1100));
 Store<std::uint64_t>(0x1000+GS_LEVEL_MANAGER_OFFSET,Address(0x1200));
 Store<std::uint64_t>(0x1000+GS_LEVEL_GATE_MANAGER_OFFSET,Address(0x1300));
 Store<std::uint64_t>(0x1300+GS_LEVEL_GATE_OBJECT_OFFSET,Address(0x1400));
 Store<std::uint64_t>(0x1000+GS_LEVEL_MODE_MANAGER_OFFSET,Address(0x1500));
 Store<std::uint32_t>(0x1500+GS_LEVEL_MODE_OFFSET,GS_LEVEL_MODE_REQUIRED);
 Store<std::uint32_t>(0x1200+GS_LEVEL_ID_OFFSET,GLT_EXPECTED_LEVEL_ID);
 ownedImage[0x1200+GS_LEVEL_EDITING_OFFSET]=1;
 ownedImage[GLT_INITIALIZED_RVA]=lazy;ownedImage[0x180]=0x90;
 Store<std::uint64_t>(GLT_CLASS_SLOT_RVA,Address(0x2000));
 Store<std::uint16_t>(0x2000+GLT_SLOT_COUNT_OFFSET,3);
 Store<std::uint64_t>(0x2000+GLT_FUNCTIONS_OFFSET,Address(0x400));
 Store<std::uint64_t>(0x2000+GLT_FUNCTIONS_OFFSET+8,Address(GLT_TARGET_FUNCTION_RVA));
 Store<std::uint64_t>(0x2000+GLT_FUNCTIONS_OFFSET+16,Address(0x500));
 GameContextSnapshot b{};b.status=GS_OK;b.flags=1951;b.moduleBase=Address(0);b.global=Address(0x1000);
 b.saveManager=Address(0x1100);b.peImageSize=0x4000;b.reserved=GLT_EXPECTED_LEVEL_ID;
 b.entityCaptured=1;b.entityValidEntries=1;return b;
}
int main(){
 ownedImage=static_cast<unsigned char*>(VirtualAlloc(nullptr,0x4000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE));
 Check(ownedImage!=nullptr,"owned-memory");LifecycleTypeSnapshot s{};
 auto b=Reset(1);CaptureGameLifecycleType(&b,&s);
 Check(s.status==0 && s.flags==255,"flag-one-legacy-success");
 Check(s.initializedBefore==1 && s.initializedAfter==1 && s.matchCount==1 && s.matchIndex==1,"legacy-binding");
 Check(slotReads==2 && s.classPointer==Address(0x2000),"legacy-slot-double-read");
 b=Reset(0);CaptureGameLifecycleType(&b,&s);
#if DIAGNOSTIC_READONLY
 Check(s.status==8 && s.flags==503,"flag-zero-stable-nonsuccess");
 Check(s.initializedBefore==0 && s.initializedAfter==0 && !(s.flags&8),"no-initialized-success-flag");
 Check(slotReads==2 && s.matchCount==1 && s.matchIndex==1 && s.slotCountBefore==3 && s.slotCountAfter==3,"diagnostic-type-double-read");
 Check(s.classPointer==Address(0x2000) && s.functions[1]==Address(GLT_TARGET_FUNCTION_RVA),"diagnostic-real-binding");
 b=Reset(0);Store<std::uint64_t>(GLT_CLASS_SLOT_RVA,0);CaptureGameLifecycleType(&b,&s);
 Check(s.status==8 && s.flags==263 && slotReads==1,"null-slot-observed");
 Check(s.classPointer==0 && s.functionsAddress==0 && s.slotCountBefore==0 && s.slotCountAfter==0 && s.matchCount==0 && s.matchIndex==0xffffffffu,"null-is-not-binding");
 b=Reset(0);unreadableSlot=true;CaptureGameLifecycleType(&b,&s);
 Check(s.status==3 && s.flags==7 && s.classPointer==0 && slotReads==1,"unreadable-slot-is-unknown");
 b=Reset(0);Store<std::uint64_t>(GLT_CLASS_SLOT_RVA,1);CaptureGameLifecycleType(&b,&s);
 Check(s.status==4 && s.flags==263 && s.classPointer==1,"noncanonical-slot-rejected");
 b=Reset(0);mutateFunctions=true;CaptureGameLifecycleType(&b,&s);
 Check(s.status==6 && s.flags==279 && slotReads==2 && !(s.flags&32),"unstable-functions-rejected");
 b=Reset(0);mutateFlag=true;CaptureGameLifecycleType(&b,&s);
 Check(s.status==6 && s.initializedBefore==0 && s.initializedAfter==1 && !(s.flags&32),"unstable-lazy-flag-rejected");
 b=Reset(0);Store<std::uint16_t>(0x2000+GLT_SLOT_COUNT_OFFSET,129);CaptureGameLifecycleType(&b,&s);
 Check(s.status==5 && s.flags==263 && s.slotCountBefore==129,"bounded-slot-count");
 b=Reset(0);Store<std::uint64_t>(0x2000+GLT_FUNCTIONS_OFFSET+8,Address(0x400));CaptureGameLifecycleType(&b,&s);
 Check(s.status==9 && s.matchCount==0 && !(s.flags&16),"missing-target-rejected");
 b=Reset(0);Store<std::uint64_t>(0x2000+GLT_FUNCTIONS_OFFSET,Address(GLT_TARGET_FUNCTION_RVA));CaptureGameLifecycleType(&b,&s);
 Check(s.status==10 && s.matchCount==2 && !(s.flags&16),"ambiguous-target-rejected");
#else
 Check(s.status==8 && s.flags==7 && s.classPointer==0 && slotReads==0,"action4-flag-zero-original-refusal");
 b=Reset(0);Store<std::uint64_t>(GLT_CLASS_SLOT_RVA,0);CaptureGameLifecycleType(&b,&s);
 Check(s.status==8 && s.flags==7 && slotReads==0,"action4-null-slot-never-read");
 b=Reset(0);mutateFunctions=true;CaptureGameLifecycleType(&b,&s);
 Check(s.status==8 && s.flags==7 && slotReads==0,"action4-no-diagnostic-path");
#endif
 b=Reset(2);CaptureGameLifecycleType(&b,&s);
 Check(s.status==8 && s.flags==7 && slotReads==0,"flag-two-original-refusal");
 Check(VirtualFree(ownedImage,0,MEM_RELEASE)!=FALSE,"owned-memory-released");
 std::printf("{\"ok\":true,\"checks\":%d,\"readonly\":%s,\"productionCaptureCoreExecuted\":true,\"memoryScope\":\"test-process-owned-pages-only\",\"gameProcessAccessed\":false,\"gameMethodsCalled\":0}\n",checks,DIAGNOSTIC_READONLY?"true":"false");
 return 0;
}
