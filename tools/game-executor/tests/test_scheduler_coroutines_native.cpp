#include "../native/game_scheduler_coroutines.h"
#include <cstdio>
#include <cstdlib>
int main(){int checks=0;auto check=[&](bool ok){if(!ok)std::exit(1);++checks;};
 check(ValidSchedulerListBounds(0,0));check(ValidSchedulerListBounds(0,128));check(ValidSchedulerListBounds(128,128));
 check(!ValidSchedulerListBounds(-1,128));check(!ValidSchedulerListBounds(129,129));check(!ValidSchedulerListBounds(2,1));check(ValidSchedulerListBounds(0,129));
 check(ValidSchedulerListBounds(3,1600));check(ValidSchedulerListBounds(0,1600));check(ValidSchedulerListBounds(128,1600));check(ValidSchedulerListBounds(128,INT32_MAX));
 check(!ValidSchedulerListBounds(129,1600));check(!ValidSchedulerListBounds(-1,1600));check(!ValidSchedulerListBounds(3,2));check(!ValidSchedulerListBounds(0,static_cast<std::uint64_t>(INT32_MAX)+1));check(!ValidSchedulerListBounds(3,UINT64_MAX));
 SchedulerCoroutinesSnapshot diagnostic{};diagnostic.flags=7;diagnostic.status=5;
 RecordSchedulerBoundsDiagnostic(diagnostic,3,256,11);check(diagnostic.flags==263);check(diagnostic.status==5);check(diagnostic.listCountBefore==3 && diagnostic.listCapacity==256 && diagnostic.versionBefore==11);check(diagnostic.rowCount==0 && diagnostic.listCountAfter==0);
 diagnostic={};diagnostic.flags=7;RecordSchedulerBoundsDiagnostic(diagnostic,-1,UINT64_MAX,2);check(diagnostic.flags==775);check(diagnostic.listCountBefore==UINT32_MAX);check(diagnostic.listCapacity==UINT32_MAX);check(diagnostic.versionBefore==2);check(diagnostic.rowCount==0);
 diagnostic={};diagnostic.flags=7;RecordSchedulerBoundsDiagnostic(diagnostic,3,UINT32_MAX,2);check(diagnostic.flags==263);check(diagnostic.listCapacity==UINT32_MAX);
 SchedulerCoroutineRow row{};check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_NULL_HANDLE);
 row.handle=0x10000;row.handleClass=0x90000;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_NULL_HOLDER);
 row.handleClass=1;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_OTHER_HANDLE_CLASS);row.handleClass=0x90000;
 row.holder=0x20000;row.released=1;row.iterator=1;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_RELEASED);
 row.released=0;row.referenceKind=1;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_UNKNOWN_REFERENCE_KIND);
 row.referenceKind=2;row.referenceCount=1;row.retainedByWrapper=1;row.iterator=0;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_NULL_ITERATOR);
 row.iterator=0x30000;row.iteratorClass=0x40000;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_OTHER_CLASS);
 row.iteratorClass=0x50000;row.iteratorOwner=0x70000;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_OTHER_OWNER);
 row.iteratorOwner=0x60000;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_TARGET);
 row.state=-1;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_TARGET);
 row.referenceCount=0;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_UNAVAILABLE_HOLDER_STATE);row.referenceCount=1;
 row.retainedByWrapper=0;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_UNAVAILABLE_HOLDER_STATE);row.retainedByWrapper=1;
 row.iterator=row.holder;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_UNAVAILABLE_HOLDER_STATE);row.iterator=0x30000;
 row.released=255;check(ClassifySchedulerRow(row,0x50000,0x60000,0x90000)==SC_RELEASED);
 std::printf("{\"ok\":true,\"checks\":%d,\"liveProcessOpened\":false}\n",checks);
}
