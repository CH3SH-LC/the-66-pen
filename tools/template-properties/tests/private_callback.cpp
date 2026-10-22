// OFFLINE ONLY. Every game callback and memory read is explicitly substituted.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <map>
#include <vector>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include "../native_properties.h"
#include "../../template-authoring/template_catalog_capture.h"
#undef PROPERTIES_EXPECTED
#undef PROPERTIES_REQUESTS
#undef PROPERTIES_CODE_RVAS
#undef PROPERTIES_CODE_BYTES
#undef PROPERTIES_HOTFIX_RVAS
#undef GS_PROFILE_HOTFIX_RVAS
#undef PROPERTIES_USAGE_GROUPS
#define PROPERTIES_PRIVATE_TEST 1
#define PROPERTIES_EXPECTED (&gExpected)
#define PROPERTIES_CODE_RVAS 0x1000
#define PROPERTIES_CODE_BYTES {0}
#define PROPERTIES_HOTFIX_RVAS 0x2000
#define GS_PROFILE_HOTFIX_RVAS 0x2001
#define PROPERTIES_USAGE_GROUPS 1
#define PROPERTIES_REQUESTS {0x42000001U,9,15,0,0x20000000ULL,0x20010000ULL,0x20020000ULL,{1,9999,1,3,{'O','l','d'}},{2,99,0,3,{'N','e','w'}}}
static GameContextSnapshot gExpected{};
static std::map<std::uint64_t,std::vector<unsigned char>> blocks;
static unsigned renameCalls,openCalls,setterCalls,unknownCalls;static int failMode;
static std::uint64_t allocation=0x50000000;
static constexpr std::uint64_t base=0x10000000,fixtureGlobal=0x30000000,manager=0x31000000,fixtureResource=0x20000000,fixtureCompanion=0x22000000,currency=0x23000000;
template<class T> static void put(std::uint64_t p,const T& v){for(auto& it:blocks)if(p>=it.first&&p+sizeof(v)<=it.first+it.second.size()){std::memcpy(it.second.data()+p-it.first,&v,sizeof(v));return;}std::abort();}
template<class T> static T get(std::uint64_t p){T v{};for(auto& it:blocks)if(p>=it.first&&p+sizeof(v)<=it.first+it.second.size()){std::memcpy(&v,it.second.data()+p-it.first,sizeof(v));return v;}std::abort();}
static void block(std::uint64_t p,std::size_t n=256){blocks[p]=std::vector<unsigned char>(n);}
bool PropertiesTestRead(std::uint64_t p,void* out,std::size_t n){for(auto& it:blocks)if(p>=it.first&&p+n<=it.first+it.second.size()){std::memcpy(out,it.second.data()+p-it.first,n);return true;}return false;}
static void* address(std::uint64_t x){return reinterpret_cast<void*>(x);}
static std::uint64_t number(void* p){return reinterpret_cast<std::uint64_t>(p);}
static std::uint64_t stringValue(const wchar_t* text){const auto p=allocation;allocation+=0x1000;block(p,512);const int n=static_cast<int>(wcslen(text));put(p+0x10,n);for(int i=0;i<n;++i)put(p+0x14+static_cast<unsigned>(i)*2,static_cast<std::uint16_t>(text[i]));return p;}
static void* stringNew(const char* text,int n){wchar_t out[128]{};if(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,n,out,127)<=0)return nullptr;return address(stringValue(out));}
static void* prop(void* owner,unsigned kind){const auto p=number(owner);if(kind==1)return address(p+0x10000);if(kind==39&&p==fixtureResource)return address(p+0x20000);if(kind==41&&p==currency)return address(p+0x20000);return nullptr;}
static unsigned getter(void* data,unsigned key){const auto p=number(data);if(key==0xc0154b8d)return get<unsigned>(p+(p==currency+0x30000?0x2c:0x3c));if(key==0x13abec4a)return get<unsigned>(p+0x40);std::abort();}
static bool tradeGet(void* data,unsigned key){if(key!=0xf4ce55d9)std::abort();return get<unsigned char>(number(data)+0x28)!=0;}
static void scalarSet(void* data,unsigned key,unsigned value){++setterCalls;const auto p=number(data);if(key==0xc0154b8d)put(p+(p==currency+0x30000?0x2c:0x3c),value);else if(key==0x13abec4a)put(p+0x40,value);else std::abort();}
static void tradeSet(void* data,unsigned key,bool value){++setterCalls;if(key!=0xf4ce55d9)std::abort();put(number(data)+0x28,static_cast<unsigned char>(value));}
static void initialize(unsigned group){if(group!=1)std::abort();}
static void* iconList(unsigned category){return address(category==9?0x41000000:0x42000000);}
static unsigned decodeIcon(unsigned* value){return *value;}
static bool stubRename(void* service,unsigned id,void* name,bool flag){++renameCalls;if(number(service)!=manager||id!=0x42000001||flag)std::abort();if(failMode==1)return false;put(fixtureResource+0x10030,number(name));put(fixtureCompanion+0x10030,number(name));return true;}
static void* stubOpen(void* label,bool a,bool b){++openCalls;if(label||a||b)std::abort();put(0x32000034,1);return address(0x33000000);}
static void snapshot(void* property,void* label,bool flag){if(label||flag)std::abort();put(0x32100018,1U);put(0x32200020,std::uint64_t(0x32300000));put(0x32300018,number(property));put(0x32300028,std::uint64_t(0x32400000));put(0x32300030,static_cast<unsigned char>(0));}
static void notify(void* editManager,void* property){if(number(editManager)!=0x32000000||get<std::uint64_t>(0x32300018)!=number(property))std::abort();if(failMode!=2)put(0x32300030,static_cast<unsigned char>(1));}
static void stubClose(void* transaction){if(number(transaction)!=0x33000000)std::abort();put(0x32000034,0);put(0x32100018,0U);if(failMode==3)put(currency+0x30028,77U);}
void* PropertiesTestNative(unsigned r){switch(r){case 0x8678480:return reinterpret_cast<void*>(prop);case 0xb840280:case 0x8b31880:case 0xebaae50:return reinterpret_cast<void*>(getter);case 0xeb7a3a0:return reinterpret_cast<void*>(tradeGet);case 0xb840d40:case 0x8b30d70:case 0xebabe30:return reinterpret_cast<void*>(scalarSet);case 0xeb7a7e0:return reinterpret_cast<void*>(tradeSet);case 0x524250:return reinterpret_cast<void*>(initialize);case 0x102e2180:return reinterpret_cast<void*>(iconList);case 0xbb2c5e0:return reinterpret_cast<void*>(decodeIcon);case 0x526de0:return reinterpret_cast<void*>(stringNew);case 0xb0a6ec0:return reinterpret_cast<void*>(stubRename);case 0xe827750:return reinterpret_cast<void*>(stubOpen);case 0x107abdf0:return reinterpret_cast<void*>(snapshot);case 0x9c26c70:return reinterpret_cast<void*>(notify);case 0xc7bab90:return reinterpret_cast<void*>(stubClose);default:++unknownCalls;std::abort();}}
void CaptureGameContextSnapshot(GameContextSnapshot* out) noexcept {*out=gExpected;}
namespace ge::templates {
void CaptureTemplateCatalog(const GameContextSnapshot*,TemplateReadSource,TemplateCatalogCaptureWorkspace*,TemplateCatalogCapture* out) noexcept {
 std::memset(out,0,sizeof(*out));out->code=TemplateCaptureCode::complete;out->level_id=1073741843;out->global=fixtureGlobal;out->manager=manager;out->primary.row_count=2;out->companion.row_count=1;
 out->primary_rows[0]={0x42000001,9,fixtureResource,0x70000000};out->primary_rows[1]={0x42800001,11,currency,0x70000008};out->companion_rows[0].key=0x42000001;out->companion_rows[0].resource=fixtureCompanion;out->companion_rows[0].klass=0x70000010;
}
}
#include "../native_properties.cpp"
static void setupResource(std::uint64_t owner,bool isCurrency,bool isCompanion){
 block(owner);block(owner+0x10000);block(owner+0x20000);block(owner+0x30000);block(owner+0x40000);block(owner+0x50000);block(owner+0x60000);block(owner+0x70000);block(owner+0x80000);
 put(owner+0x20,owner+0x60000);put(owner+0x60018,owner+0x70000);put(owner+0x60020,owner+0x80000);put(owner+0x70018,std::uint64_t(1));put(owner+0x80018,std::uint64_t(1));
 put(owner+0x10000,get<std::uint64_t>(base+0x57b5318));put(owner+0x10020,owner);put(owner+0x10030,stringValue(L"Old"));
 if(isCompanion)return;
 put(owner+0x20000,get<std::uint64_t>(base+(isCurrency?0x57e11b0:0x57b3608)));put(owner+0x20020,owner);put(owner+0x20030,owner+0x30000);put(owner+0x30000,get<std::uint64_t>(base+(isCurrency?0x57e8730:0x57e8af0)));
 put(owner+0x30000+(isCurrency?0x2c:0x3c),1U);
 if(!isCurrency){put(owner+0x30018,owner+0x40000);put(owner+0x30028,owner+0x50000);put(owner+0x40000,get<std::uint64_t>(base+0x57e83a8));put(owner+0x50000,get<std::uint64_t>(base+0x57dcfc0));put(owner+0x40018,owner+0x30000);put(owner+0x50020,owner+0x30000);put(owner+0x40040,9999U);put(owner+0x50028,static_cast<unsigned char>(1));}
}
static void reset(){blocks.clear();allocation=0x50000000;failMode=0;renameCalls=openCalls=setterCalls=unknownCalls=0;
 block(base+0x1000);block(base+0x2000);block(fixtureGlobal,0x10000);block(0x32000000);block(0x32100000);block(0x32200000);block(0x32300000);block(0x32400000);block(0x33000000);
 unsigned i=0;for(unsigned slot:{0x57b5318U,0x57b3608U,0x57e11b0U,0x57e8af0U,0x57e8730U,0x57e83a8U,0x57dcfc0U,0x5812cf8U}){block(base+slot,8);put(base+slot,0x70000000ULL+static_cast<std::uint64_t>(i++)*0x1000);}
 put(fixtureGlobal+0xecd0,std::uint64_t(0x32000000));put(0x32000018,std::uint64_t(0x32100000));put(0x32100010,std::uint64_t(0x32200000));put(0x32200018,std::uint64_t(8));put(0x32300000,get<std::uint64_t>(base+0x5812cf8));
 for(unsigned cat:{8U,9U}){const std::uint64_t list=cat==9?0x41000000:0x42000000;block(list);block(list+0x1000);block(list+0x2000);block(list+0x3000);put(list+0x10,list+0x1000);put(list+0x18,2U);put(list+0x1018,std::uint64_t(2));put(list+0x1020,list+0x2000);put(list+0x1028,list+0x3000);put(list+0x2024,cat);put(list+0x3024,cat);put(list+0x2034,1U);put(list+0x3034,2U);}
 setupResource(fixtureResource,false,false);setupResource(fixtureCompanion,false,true);setupResource(currency,true,false);
 gExpected={};gExpected.structSize=sizeof(gExpected);gExpected.version=1;gExpected.status=GS_OK;gExpected.flags=1951;gExpected.moduleBase=base;gExpected.global=fixtureGlobal;gExpected.currentContext=0x60000000;gExpected.reserved=1073741843;
}
static PropertyReceipt result;
static void check(bool condition,const char* label){if(!condition){std::fprintf(stderr,"FAIL %s status=%u stage=%u rowstage=%u\n",label,result.status,result.stage,result.rows[0].stage);std::exit(2);}std::printf("PASS %s\n",label);}
int main(int argc,char** argv){
 reset();ExecuteProperties(&gExpected,&result);check(result.status==0&&result.completed==1&&result.catalogUnchanged&&result.guardsUnchanged&&result.rows[0].closed&&renameCalls==1&&setterCalls==3&&unknownCalls==0,"full item stubRename fixtureCompanion icon stack trade transaction and independent guards");
 if(argc>1){FILE* file=nullptr;if(fopen_s(&file,argv[1],"wb")||!file)return 3;fwrite(&result,1,sizeof(result),file);fclose(file);}
 reset();put(fixtureResource+0x40040,12U);ExecuteProperties(&gExpected,&result);check(result.status!=0&&!renameCalls&&!openCalls,"stale expected value rejects before mutation");
 reset();put(0x41003034,3U);ExecuteProperties(&gExpected,&result);check(result.status!=0&&!renameCalls&&!openCalls,"wrong category icon membership rejects before mutation");
 reset();failMode=1;ExecuteProperties(&gExpected,&result);check(result.status!=0&&renameCalls==1&&!openCalls&&result.rows[0].uncertain,"stubRename rejection is not replayable success");
 reset();failMode=2;ExecuteProperties(&gExpected,&result);check(result.status!=0&&result.rows[0].closed&&result.rows[0].uncertain,"missing dirty mark closes owned transaction and remains uncertain");
 reset();failMode=3;ExecuteProperties(&gExpected,&result);check(result.status!=0&&!result.guardsUnchanged,"other currency scalar change caught by preservation guard");
 reset();put(0x32100018,1U);ExecuteProperties(&gExpected,&result);check(result.status!=0&&!renameCalls&&!openCalls,"existing undo transaction rejected");
 reset();PropertyRow row{};row.id=0x42800001;row.subtype=11;row.mask=2;row.resource=currency;check(capture(base,row,row.before),"currency raw capture plus native getter");row.desired=row.before;row.desired.iconId=2;PropertyReceipt receipt{};receipt.manager=manager;check(mutate(gExpected,receipt,row)&&row.after.iconId==2&&setterCalls==1&&row.closed,"currency icon uses currency setter and transaction");
 reset();PropertyRow stale{};stale.resource=fixtureResource;stale.subtype=9;stale.dataProperty=0x12340000;PropertyState state{};check(!capture(base,stale,state),"replaced property pointer rejected");
 reset();put(base+0x2000,static_cast<unsigned char>(1));ExecuteProperties(&gExpected,&result);check(result.status!=0&&result.failedRva==0x2000&&!renameCalls&&!openCalls,"active hotfix refuses before calls");
 return 0;
}
