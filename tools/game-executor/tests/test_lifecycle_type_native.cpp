#include "../native/game_lifecycle_type.h"
#include <cstdio>
#include <cstdlib>
int main() {
 int checks=0;std::uint64_t slots[128]{};slots[2]=0x1409037840ULL;
 auto check=[&](const char* name,const std::uint64_t* data,std::uint32_t count,std::uint64_t target,std::uint32_t status,std::uint32_t matches,std::uint32_t index){
  std::uint32_t gotMatches=99,gotIndex=99;const auto got=MatchLifecycleFunction(data,count,target,gotMatches,gotIndex);
  if(got!=status || gotMatches!=matches || gotIndex!=index){std::printf("FAIL %s: %u/%u/%u\n",name,got,gotMatches,gotIndex);std::exit(1);}++checks;
 };
 check("unique",slots,4,0x1409037840ULL,0,1,2);
 check("all-slots",slots,128,0x1409037840ULL,0,1,2);
 check("null-array",nullptr,4,0x1409037840ULL,1,0,0xffffffffu);
 check("zero-count",slots,0,0x1409037840ULL,1,0,0xffffffffu);
 check("over-count",slots,129,0x1409037840ULL,1,0,0xffffffffu);
 check("null-target",slots,4,0,2,0,0xffffffffu);
 check("noncanonical-target",slots,4,0x800000000000ULL,2,0,0xffffffffu);
 check("no-match",slots,4,0x1409037841ULL,3,0,0xffffffffu);
 check("ignore-unused",slots,2,0x1409037840ULL,3,0,0xffffffffu);
 slots[3]=slots[2];check("ambiguous",slots,4,0x1409037840ULL,4,2,0xffffffffu);
 slots[3]=0;slots[2]=0x1409037841ULL;check("code-need-not-be-eight-aligned",slots,4,slots[2],0,1,2);
 std::printf("{\"ok\":true,\"checks\":%d,\"liveProcessOpened\":false}\n",checks);
}
