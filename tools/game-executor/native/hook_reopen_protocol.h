#pragma once
#include <windows.h>
#include "reopen_action.h"
namespace ge::observation {
constexpr std::uint32_t maxSamples=200,intervalMs=50,maxDurationMs=10000;
constexpr LPARAM messageBase=0x10000;
enum Status:std::uint32_t {DISABLED=0,NO_INITIAL_TARGET=1,INITIAL_STAGE_PROVEN=2,OBSERVING=3,FOLLOWUP_STAGE_PROVEN=4,TIMEOUT_UNKNOWN=5,LIMIT_UNKNOWN=6,DEADLINE_UNKNOWN=7,POST_FAILED_UNKNOWN=8};
struct Header {
 std::uint32_t size,version;volatile LONG status;std::uint32_t flags;
 std::uint64_t invocation,startTick,endTick;
 std::uint64_t handle,holder,iterator,iteratorClass,owner;
 volatile LONG requested,completed,callbacks,rejected;
 std::uint32_t proofSequence,lastSnapshotStatus,overflow,reserved;
};
static_assert(sizeof(Header)==112&&offsetof(Header,requested)==80,"observation header v1");
struct Evidence {
 Header header;volatile LONG reading;std::uint32_t reserved;
 SchedulerCoroutinesSnapshot proof,last;
};
inline bool Complete(const SchedulerCoroutinesSnapshot& s) noexcept {
 if(s.structSize!=sizeof(s)||s.version!=1||s.status||s.flags!=255||s.rowCount>128||
    s.rowCount!=s.listCountBefore||s.rowCount!=s.listCountAfter||s.versionBefore!=s.versionAfter||
    s.referencePolicyBefore!=s.referencePolicyAfter||!ValidSchedulerListBounds(static_cast<std::int32_t>(s.rowCount),s.listCapacity))return false;
 std::uint32_t target=0,unavailable=0,other=0,nulls=0;
 for(std::uint32_t i=0;i<s.rowCount;++i){const auto& row=s.rows[i];
  if(row.index!=i||row.reserved||row.disposition!=ClassifySchedulerRow(row,s.targetClass,s.lifecycleOwner,s.coroutineClass))return false;
  for(std::uint32_t j=0;j<i;++j)if(row.handle&&row.handle==s.rows[j].handle)return false;
  if(row.disposition==SC_TARGET)++target;else if(row.disposition==SC_NULL_HANDLE)++nulls;
  else if(row.disposition==SC_OTHER_CLASS||row.disposition==SC_OTHER_OWNER)++other;else ++unavailable;
 }
 return target==s.targetCount&&unavailable==s.unavailableCount&&other==s.otherCount&&nulls==s.nullHandleCount;
}
inline bool SameRoots(const SchedulerCoroutinesSnapshot& before,const SchedulerCoroutinesSnapshot& after) noexcept {
 return before.moduleBase==after.moduleBase&&before.global==after.global&&before.lifecycleOwner==after.lifecycleOwner&&
  before.targetClass==after.targetClass&&before.classSlot==after.classSlot&&before.coroutineClass==after.coroutineClass&&before.levelId==after.levelId;
}
inline const SchedulerCoroutineRow* UniqueTarget(const SchedulerCoroutinesSnapshot& s) noexcept {
 if(!Complete(s)||s.targetCount!=1)return nullptr;
 for(std::uint32_t i=0;i<s.rowCount;++i)if(s.rows[i].disposition==SC_TARGET)return &s.rows[i];
 return nullptr;
}
inline const SchedulerCoroutineRow* InitialTarget(const ReopenActionSnapshot& a) noexcept {
 if(a.action.status!=ge::reopen::RETURNED_PENDING||a.action.call.nativeCallAttempted!=1||
    a.action.call.nativeCallReturned!=1||a.action.call.businessPending!=1||
    !Complete(a.scheduler)||a.scheduler.targetCount||!SameRoots(a.scheduler,a.postScheduler))return nullptr;
 const auto* row=UniqueTarget(a.postScheduler);if(!row)return nullptr;
 for(std::uint32_t i=0;i<a.scheduler.rowCount;++i){const auto& b=a.scheduler.rows[i];
  if(row->handle==b.handle||row->holder==b.holder||row->iterator==b.iterator)return nullptr;}
 return row;
}
inline bool Stage(const SchedulerCoroutineRow& r) noexcept{return r.state>=4&&r.state<=7;}
inline bool SameCandidate(const Header& h,const SchedulerCoroutineRow& r) noexcept {
 return r.handle==h.handle&&r.holder==h.holder&&r.iterator==h.iterator&&r.iteratorClass==h.iteratorClass&&r.iteratorOwner==h.owner;
}
inline void Initialize(Evidence& e,const ReopenActionSnapshot& a,std::uint64_t now) noexcept {
 e={};auto& h=e.header;h.size=sizeof(h);h.version=1;h.invocation=a.action.invocation;h.startTick=h.endTick=now;
 if(a.action.call.nativeCallReturned!=1)return;
 h.status=NO_INITIAL_TARGET;const auto* row=InitialTarget(a);if(!row)return;
 h.flags=1;h.handle=row->handle;h.holder=row->holder;h.iterator=row->iterator;h.iteratorClass=row->iteratorClass;h.owner=row->iteratorOwner;
 h.status=Stage(*row)?INITIAL_STAGE_PROVEN:OBSERVING;if(Stage(*row))h.flags|=2;
}
inline bool Eligible(const Header& h,LONG sequence,std::uint64_t now,std::uint64_t nonce) noexcept {
 return h.size==112&&h.version==1&&h.invocation==nonce&&h.status==OBSERVING&&h.flags==1&&
  now>=h.startTick&&now-h.startTick<maxDurationMs&&sequence>=1&&sequence<=static_cast<LONG>(maxSamples)&&
  h.requested==sequence&&h.completed==sequence-1&&h.callbacks==sequence-1&&!h.rejected&&!h.overflow&&!h.reserved;
}
inline void Accept(Evidence& e,const ReopenActionSnapshot& a,LONG sequence,std::uint64_t now) noexcept {
 auto& h=e.header;h.endTick=now;h.lastSnapshotStatus=e.last.status;
 // No sampled state may overwrite immutable action/post evidence or convert timeout into proof.
 if(h.status!=OBSERVING||now<h.startTick||now-h.startTick>=maxDurationMs)return;
 const auto* row=UniqueTarget(e.last);
 if(row&&SameRoots(a.scheduler,e.last)&&SameCandidate(h,*row)&&Stage(*row)){
  e.proof=e.last;
  if(InterlockedCompareExchange(&h.status,FOLLOWUP_STAGE_PROVEN,OBSERVING)==OBSERVING){
   h.proofSequence=static_cast<std::uint32_t>(sequence);h.flags|=2;
  }else e.proof={}; // A concurrent terminal refusal wins; no proof is published.
 }
}
}
struct Receipt {
 DWORD magic,version;std::uint64_t nonce,deadline;DWORD expectedPid,expectedTid;
 volatile LONG claim,pid,tid,callbacks,active,hostPings,hostPid,hostTid;
 ReopenActionSnapshot reopen;
 ge::observation::Evidence observation;
};
static_assert(sizeof(void*)==8&&offsetof(Receipt,reopen)==64&&offsetof(Receipt,observation)==71000,"original action/post prefix retained");
static_assert(sizeof(Receipt)==98064,"dedicated observation receipt v10");
constexpr DWORD kReceiptVersion=10;