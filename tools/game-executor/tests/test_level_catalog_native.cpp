#include "../native/game_level_catalog.h"
#include <cstdio>
#include <cstdlib>
struct Fixture {
 std::int32_t buckets[3]{1,0,0};LevelCatalogEntry entries[3]{{3,1,3,0,0x10000},{6,-1,6,0,0x20000},{-1,-1,99,0,0x30000}};
 std::int32_t count=3,free=1;std::uint32_t bcap=3,ecap=3;bool readFail=false,idMismatch=false;
 std::uint32_t Run(LevelCatalogSnapshot& out){return ParseLevelCatalog(buckets,bcap,entries,ecap,count,free,
  [this](std::uint64_t p,std::uint32_t& id)noexcept{if(readFail)return false;id=p==0x10000?3:6;if(idMismatch)++id;return true;},out);}
};
int main(){int count=0;auto check=[&](const char* name,Fixture f,std::uint32_t expected){LevelCatalogSnapshot out{};auto got=f.Run(out);if(got!=expected){std::printf("FAIL %s: %u != %u\n",name,got,expected);std::exit(1);}++count;};
 Fixture f;check("valid-full-chain-with-stale-free-slot",f,0);
 f=Fixture{};f.entries[1].next=0;check("cycle",f,4);
 f=Fixture{};f.buckets[0]=4;check("bucket-outside",f,3);
 f=Fixture{};f.entries[0].hash=-1;check("negative-hash",f,5);
 f=Fixture{};f.entries[0].next=-2;check("bad-next",f,5);
 f=Fixture{};f.idMismatch=true;check("record-id-mismatch",f,9);
 f=Fixture{};f.entries[0].value=0;check("null-record",f,6);
 f=Fixture{};f.entries[0].next=-1;check("occupancy-incomplete",f,11);
 f=Fixture{};f.free=4;check("free-count",f,2);
 f=Fixture{};f.count=1;f.free=0;check("outside-initialized-count",f,4);
 f=Fixture{};f.buckets[0]=0;f.count=0;f.free=0;check("empty",f,0);
 f=Fixture{};f.bcap=513;check("capacity",f,1);
 f=Fixture{};f.entries[1].key=3;check("duplicate-id",f,7);
 f=Fixture{};f.entries[1].value=0x10000;check("duplicate-record",f,7);
 f=Fixture{};f.entries[0].hash=1;check("wrong-bucket",f,5);
 f=Fixture{};f.entries[0].hash=9;check("custom-valid-hash-no-comparer-call",f,0);
 f=Fixture{};f.readFail=true;check("record-read-failure",f,8);
 std::printf("{\"ok\":true,\"checks\":%d,\"liveProcessOpened\":false}\n",count);return 0;
}
