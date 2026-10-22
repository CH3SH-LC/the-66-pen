// Private memory only; complete production hook/callback, actual HP decoder.
#include <windows.h>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cstdint>
#include <initializer_list>
#pragma comment(lib,"User32.lib")
using F=std::uint64_t;
static F fixtureBase=0,fixtureTick=100;static unsigned fixtureFrame=1;
static MSG fixtureMessage{};
static DWORD fixtureIdentity(){return 1;}
static ULONGLONG fixtureClock(){return fixtureTick;}
static HMODULE fixtureModule(LPCWSTR name){return std::wcscmp(name,L"YuanShen.exe")==0?reinterpret_cast<HMODULE>(fixtureBase):nullptr;}
#undef HR_DEADLINE
#define HR_DEADLINE 1000000ULL
#undef HR_GAME_TIMESTAMP
#define HR_GAME_TIMESTAMP 0U
#undef HR_GAME_IMAGE_SIZE
#define HR_GAME_IMAGE_SIZE 0x1a000000U
#undef PLAY_CODE_RVAS
#undef PLAY_CODE_BYTES
#undef PLAY_HOTFIX_RVAS
#define PLAY_CODE_RVAS 0x1000U
#define PLAY_CODE_BYTES {0}
#define PLAY_HOTFIX_RVAS 0x1080U
#undef CONTROL_CODE_RVAS
#undef CONTROL_CODE_BYTES
#undef CONTROL_HOTFIX_RVAS
#define CONTROL_CODE_RVAS 0x1000U
#define CONTROL_CODE_BYTES {0}
#define CONTROL_HOTFIX_RVAS 0x1080U
#undef INVENTORY_CODE_RVAS
#undef INVENTORY_CODE_BYTES
#undef INVENTORY_HOTFIX_RVAS
#define INVENTORY_CODE_RVAS 0x1000U
#define INVENTORY_CODE_BYTES {0}
#define INVENTORY_HOTFIX_RVAS 0x1080U
#undef CONTROL_GLOBAL
#undef CONTROL_EDITOR
#undef CONTROL_TASK
#undef CONTROL_TOKEN
#undef CONTROL_CACHE
#undef CONTROL_DATA
#define CONTROL_GLOBAL (fixtureBase+0x20000)
#define CONTROL_EDITOR (fixtureBase+0x35000)
#define CONTROL_TASK (fixtureBase+0x36000)
#define CONTROL_TOKEN 7U
#define CONTROL_CACHE (fixtureBase+0x38000)
#define CONTROL_DATA (fixtureBase+0x39000)
#define GetCurrentProcessId fixtureIdentity
#define GetCurrentThreadId fixtureIdentity
#define GetTickCount64 fixtureClock
#define GetModuleHandleW fixtureModule
#undef SHOP_CODE_RVAS
#undef SHOP_CODE_BYTES
#undef SHOP_HOTFIX_RVAS
#define SHOP_CODE_RVAS 0x1000U
#define SHOP_CODE_BYTES {0}
#define SHOP_HOTFIX_RVAS 0x1080U
#undef SHOP_EXPECTED_UI
static unsigned char expectedUi[43424]{};
#define SHOP_EXPECTED_UI expectedUi
#undef SHOP_AVATAR
#undef SHOP_BAG
#define SHOP_AVATAR (fixtureBase+0x44000)
#define SHOP_BAG (fixtureBase+0x90800)
#include "native_shop.cpp"
#include "../native/hook_receipt.cpp"
#undef GetCurrentProcessId
#undef GetCurrentThreadId
#undef GetTickCount64
#undef GetModuleHandleW
namespace {
void commit(F at,SIZE_T n=4096){const F start=at&~0xfffULL;const SIZE_T length=static_cast<SIZE_T>((at+n-start+4095)&~4095ULL);if(!VirtualAlloc(reinterpret_cast<void*>(start),length,MEM_COMMIT,PAGE_EXECUTE_READWRITE))ExitProcess(30);}
template<class T>void put(F at,T value){commit(at,sizeof(T));std::memcpy(reinterpret_cast<void*>(at),&value,sizeof(value));}
void q(F at,F value){put(at,value);}void u(F at,unsigned value){put(at,value);}void byteValue(F at,unsigned char value){put(at,value);}
void jump(F at,F target){commit(at);unsigned char bytes[12]={0x48,0xb8,0,0,0,0,0,0,0,0,0xff,0xe0};std::memcpy(bytes+2,&target,8);std::memcpy(reinterpret_cast<void*>(at),bytes,12);FlushInstructionCache(GetCurrentProcess(),reinterpret_cast<void*>(at),12);}
bool active(void*){return true;}
void enginePosition(void*,float* value){value[0]=0;value[1]=0;value[2]=0;}
unsigned frame(){return fixtureFrame;}
void setup(){
    fixtureBase=reinterpret_cast<F>(VirtualAlloc(nullptr,0x1a000000,MEM_RESERVE,PAGE_NOACCESS));if(!fixtureBase)ExitProcess(31);
    commit(fixtureBase,0x2000);commit(fixtureBase+0x20000,0x43000);
    IMAGE_DOS_HEADER dos{};dos.e_magic=IMAGE_DOS_SIGNATURE;dos.e_lfanew=0x100;std::memcpy(reinterpret_cast<void*>(fixtureBase),&dos,sizeof(dos));
    IMAGE_NT_HEADERS64 nt{};nt.Signature=IMAGE_NT_SIGNATURE;nt.OptionalHeader.SizeOfImage=HR_GAME_IMAGE_SIZE;std::memcpy(reinterpret_cast<void*>(fixtureBase+0x100),&nt,sizeof(nt));
    const F b=fixtureBase,g=b+0x20000;
    q(b+0x5783de8,g);q(g+0xa440,b+0x31000);q(g+0xa430,b+0x32000);q(b+0x32050,b+0x33000);q(b+0x33030,b+0x34000);u(b+0x34070,5);
    q(g+0xa960,b+0x35000);u(b+0x35098,PLAY_TARGET_LEVEL);q(b+0x35090,b+0x36000);u(b+0x36050,7);u(b+0x36054,1);u(b+0x3605c,10);
    q(g+0xa150,b+0x37000);q(b+0x37090,b+0x38000);q(b+0x37068,b+0x38000);q(b+0x38020,b+0x39000);byteValue(b+0x38030,1);
    q(g+0xf390,b+0x3a000);q(b+0x3a070,b+0x3b000);q(b+0x3b010,b+0x3c000);u(b+0x3c024,7);q(g+0xaa40,b+0x3d000);byteValue(b+0x3d0e5,1);q(g+0xad80,b+0x3e000);
    q(b+0x31118,b+0x3f000);u(b+0x3f158,123);u(b+0x31230,123);u(b+0x311cc,47504);
    q(g+0x9d50,b+0x40000);q(b+0x40150,b+0x41000);u(b+0x40250,7);q(b+0x41020,b+0x42000);q(b+0x41028,b+0x43000);q(b+0x42018,1);u(b+0x42020,1);q(b+0x43018,1);u(b+0x43020,7);u(b+0x43024,0xffffffffU);u(b+0x43028,7);q(b+0x43030,b+0x44000);
    q(b+0x44000,b+0x47000);q(b+0x57b1570,b+0x47000);q(b+0x474c8,b+0x9a96970);q(b+0x441e8,b+0x45000);q(b+0x45010,0x10000);q(b+0x44038,b+0x46000);q(b+0x46010,0x10000);byteValue(b+0x4449b,1);
    q(b+0x57a8ae8,b+0x48000);byteValue(b+0x480c7,1);commit(b+0x57872a4,12);

    commit(b+0x59196f0,8);
    q(b+0x57dbd80,b+0x47000);byteValue(b+0x470c5,1);
    q(b+0x57d4e40,b+0x70000);byteValue(b+0x700c5,1);q(b+0x583b038,b+0x71000);byteValue(b+0x710c5,1);
    q(g+0x36520,b+0x72000);q(b+0x72010,b+0x73000);q(b+0x72018,3072);q(b+0x73000,12);q(b+0x73010,256);
    for(unsigned i=0;i<3072;++i)byteValue(b+0x72020+i,static_cast<unsigned char>(i&255));
    q(b+0x401e8,b+0x74000);q(b+0x74028,b+0x75000);u(b+0x74038,3);u(b+0x7403c,9);q(b+0x75018,3);
    u(b+0x75020,7);u(b+0x75028,7);q(b+0x75030,b+0x44000);
    u(b+0x75038,0xffffffffU);u(b+0x75050,9);u(b+0x75058,9);q(b+0x75060,b+0x76000);
    for(unsigned i=0;i<2;++i){
        const F entity=i?b+0x76000:b+0x44000,manager=b+0x78000+i*0x1000,array=b+0x7a000+i*0x1000,component=b+0x7c000+i*0x1000,properties=b+0x7e000+i*0x1000;
        q(entity,b+0x47000);u(entity+0x3a8,i?9U:7U);u(entity+0x4dc,i?21010101U:10000001U);u(entity+0x458,i?2U:1U);byteValue(entity+0x49b,i?0U:1U);byteValue(entity+0x42f,1);byteValue(entity+0x482,1);q(entity+0x1a0,b+0x77000);
        q(entity+0x2d0,manager);q(manager+0x68,array);q(array+0x18,14);q(array+0x20+13*8,component);q(component,b+0x70000);q(component+0x28,entity);q(component+0x138,properties);q(properties,b+0x71000);
        // Fixed independently specified IEEE-754 encodings with identity rows.
        static constexpr unsigned char current[16]={0,0,0,0,0,0,0,0,0,0,0xc8,0x42,0,0,0xc8,0x42};
        static constexpr unsigned char maximum[16]={0,0,0,0,0,0,0,0,0,0,0xf0,0x42,0,0,0xf0,0x42};
        commit(properties,4096);if(!i)std::memcpy(reinterpret_cast<void*>(properties+0x5e0),current,16);std::memcpy(reinterpret_cast<void*>(properties+0x570),maximum,16);
    }
    // Actual inventory production layout, owned private heap only.
    const F component=b+0x90000,module=b+0x90700,bag=b+0x90800;
    q(b+0x7a018,18);q(b+0x7a020+17*8,component);q(component,b+0x90100);q(b+0x57d1b10,b+0x90100);q(component+0x28,b+0x44000);
    q(b+0x58e83c0,b+0x90200);q(b+0x90210,b+0x90300);q(b+0x90318,b+0x90400);byteValue(b+0x904c8,1);
    q(component+0x180,b+0x90500);q(b+0x90518,b+0x90600);q(b+0x90618,2);u(b+0x90620,0xffffffffU);u(b+0x90638,7);q(b+0x90640,b+0x99900);q(b+0x90648,module);
    q(module,b+0x90400);q(module+0x10,component);q(module+0x58,bag);q(bag,b+0x91000);q(b+0x57d7e30,b+0x91000);q(bag+0x10,module);
    q(bag+0x18,b+0x90900);q(b+0x90910,b+0x90a00);u(b+0x90918,2);u(b+0x9091c,4);q(b+0x90a18,2);
    q(bag+0x30,b+0x90b00);q(b+0x90b10,b+0x90c00);u(b+0x90b18,3);u(b+0x90b1c,8);q(b+0x90c18,3);
    u(bag+0x50,3);u(bag+0x54,2);q(bag+0x58,(99ULL<<32)|5);u(bag+0x60,23);
    q(b+0x5816978,b+0x91100);q(b+0x5834880,b+0x91200);q(b+0x57ed678,b+0x91300);
    q(g+0xa410,b+0x91600);q(b+0x916a0,b+0x91400);q(b+0x91420,b+0x91500);q(b+0x91518,2);u(b+0x91520,0xffffffffU);u(b+0x91534,7);u(b+0x9153c,7);u(b+0x91544,23);
    for(unsigned i=0;i<2;++i){
        const F total=b+0x92000+i*0x1000,slot=b+0x94000+i*0x1000,item=b+0x97000+i*0x1000;
        q(b+0x90a20+i*8,total);q(total,b+0x91100);q(total+0x10,i?9:25);q(total+0x18,((i?1115684866ULL:1115684865ULL)<<32)|13);
        q(b+0x90c20+i*8,slot);q(slot,b+0x91200);q(slot+0x10,item);u(slot+0x18,i);
        q(item,b+0x91300);q(item+0x20,(1107296258ULL<<32)|12);u(item+0x28,100+i);u(item+0x30,3+i);u(item+0x38,1);
    }
    q(b+0x90c30,b+0x96000);q(b+0x96000,b+0x91200);u(b+0x96018,2);
    jump(b+0x1436d00,reinterpret_cast<F>(&enginePosition));jump(b+0x19c9b820,reinterpret_cast<F>(&active));jump(b+0x19c9de20,reinterpret_cast<F>(&frame));
}
}
namespace {
F cursor=0,pageUi=0,buyUi=0,itemUi=0,sellUi=0,hudUi=0,topArray=0,goodsButton=0,bagButton=0,shopMod=0,bagMod=0,confirmBuy=0,confirmSell=0,sellOpen=0,sliderBuy=0,sliderSell=0;
unsigned pressed=0,sliderSet=0;
F alloc(){const F x=cursor;cursor+=0x1000;commit(x);return x;}
F cls(unsigned slot){const F x=alloc();q(fixtureBase+slot,x);return x;}
F list(unsigned count){const F x=alloc(),a=alloc();q(x+0x10,a);u(x+0x18,count);q(a+0x18,count);return x;}
void itemList(F x,unsigned index,F item){q(ptr(x+0x10)+0x20+8ULL*index,item);}
F textObject(const wchar_t* value){const F t=alloc(),s=alloc();q(t,ptr(fixtureBase+0x579f540));q(t+0xe0,s);u(s+0x10,static_cast<unsigned>(wcslen(value)));std::memcpy(reinterpret_cast<void*>(s+0x14),value,wcslen(value)*2);return t;}
F eventFor(unsigned callback,F target,bool slider=false){const F e=alloc(),calls=alloc(),persistent=alloc();q(e+0x10,calls);q(e+0x18,persistent);q(calls+0x10,list(0));q(persistent+0x10,list(0));const F runtimes=list(1);q(calls+0x18,runtimes);const F invoke=alloc(),wrapper=alloc(),wrapperObject=alloc(),original=alloc();itemList(runtimes,0,invoke);q(invoke+0x10,wrapper);q(wrapper+0x18,fixtureBase+(slider?0x11b178b0:0x14058e50));q(wrapper+0x40,wrapperObject);q(wrapperObject+0x10,original);q(original+0x18,fixtureBase+callback);q(original+0x10,fixtureBase+callback);q(original+0x40,target);return e;}
F button(unsigned callback,F target){const F x=alloc();q(x,ptr(fixtureBase+0x579f538));q(x+0x10,0x10000);byteValue(x+0xb0,1);byteValue(x+0xc0,1);q(x+0xd8,eventFor(callback,target));return x;}
F monoFor(F x){const F mono=alloc(),gameObject=alloc();q(mono+0x10,0x10000);q(gameObject+0x10,0x10000);q(mono+0x68,gameObject);q(gameObject+0x20,x);return mono;}
F component(void* v,void*){return ptr(reinterpret_cast<F>(v)+0x20);}
F getA(void* v){return ptr(reinterpret_cast<F>(v)+0x300);}
F getB(void* v){return ptr(reinterpret_cast<F>(v)+0x308);}
F bagIndex(void* bag,unsigned category,unsigned index){if(category||index>=3)return 0;return ptr(ptr(ptr(reinterpret_cast<F>(bag)+0x30)+0x10)+0x20+index*8)?ptr(ptr(ptr(ptr(reinterpret_cast<F>(bag)+0x30)+0x10)+0x20+index*8)+0x10):0;}
void top(F value){q(topArray+0x20,value==pageUi?fixtureBase+0x20000:pageUi);q(topArray+0x28,value);}
void bought(void*){++pressed;top(pageUi);}void sold(void*){++pressed;top(itemUi);}void openGoods(void*){++pressed;top(buyUi);}void openBag(void*){++pressed;top(itemUi);}void openSell(void*){++pressed;top(sellUi);}void returnUi(void* context){++pressed;top(reinterpret_cast<F>(context)==pageUi?hudUi:pageUi);if(reinterpret_cast<F>(context)==pageUi)q(topArray+0x20,fixtureBase+0x20000);}
void press(void* v){const F event=ptr(reinterpret_cast<F>(v)+0xd8),listPtr=ptr(ptr(event+0x10)+0x18),invoke=ptr(ptr(listPtr+0x10)+0x20),wrapper=ptr(invoke+0x10),original=ptr(ptr(wrapper+0x40)+0x10);reinterpret_cast<void(*)(void*)>(ptr(original+0x18))(reinterpret_cast<void*>(ptr(original+0x40)));}
void quantityBuy(void* target,float value,void*){u(reinterpret_cast<F>(target)+0x250,static_cast<unsigned>(value));}
void quantitySell(void* target,float value,void*){u(reinterpret_cast<F>(target)+0x230,static_cast<unsigned>(value));}
void sliderValue(void* v,float value,void*){++sliderSet;const F x=reinterpret_cast<F>(v);put(x+0xf8,value);const F event=ptr(x+0x100),ls=ptr(ptr(event+0x10)+0x18),invoke=ptr(ptr(ls+0x10)+0x20),wrapper=ptr(invoke+0x10),original=ptr(ptr(wrapper+0x40)+0x10);reinterpret_cast<void(*)(void*,float,void*)>(ptr(original+0x18))(reinterpret_cast<void*>(ptr(original+0x40)),value,nullptr);}
F slider(F context,bool sell,unsigned quantity){const F x=alloc();q(x,ptr(fixtureBase+0x57a5bf0));q(x+0x10,0x10000);put(x+0xec,1.0f);put(x+0xf0,5.0f);put(x+0xf8,static_cast<float>(quantity));byteValue(x+0xf4,1);q(x+0x100,eventFor(sell?0x10f25f80:0x13a58b00,context,true));return x;}
F view(unsigned slot){const F x=alloc();q(x,ptr(fixtureBase+slot));q(x+0x10,0x10000);return x;}
void setupUi(){
    cursor=fixtureBase+0x100000;for(unsigned slot:{0x579f538U,0x579f540U,0x57a5bf0U,0x57ee1d0U,0x5800130U,0x582fae0U,0x5803818U,0x5841d70U,0x583c498U,0x583c4b0U,0x57edbd0U,0x582fb10U,0x57ebf40U,0x580b100U,0x57d0f30U,0x57b3288U})cls(slot);
    q(ptr(fixtureBase+0x57a5bf0)+0x260,fixtureBase+0x19dd0320);q(ptr(fixtureBase+0x57a5bf0)+0x280,fixtureBase+0x19dd0b90);
    pageUi=view(0x57ee1d0);buyUi=view(0x582fae0);itemUi=view(0x5841d70);sellUi=view(0x583c4b0);hudUi=view(0x57b3288);const F manager=alloc(),stack=alloc();topArray=alloc();q(fixtureBase+0x20000+0x9c70,manager);q(manager+0x1a8,stack);q(stack+0x10,topArray);u(stack+0x20,2);q(topArray+0x18,2);q(topArray+0x20,pageUi);top(pageUi);
    // Page appears once in the real stack; top equality represents only one slot.
    q(topArray+0x20,view(0x579f540));
    const F modules=list(2);q(pageUi+0x100,modules);shopMod=alloc();bagMod=alloc();itemList(modules,0,shopMod);itemList(modules,1,bagMod);
    for(unsigned i=0;i<2;++i){const F method=alloc(),ctx=alloc(),klass=alloc(),mod=i?bagMod:shopMod;q(fixtureBase+(i?0x5902538:0x5902540),method);q(method+0x10,ctx);q(ctx+0x10,klass);byteValue(klass+0xc8,1);q(mod,klass);q(mod+0x18,pageUi);}
    u(shopMod+0x6c,88);u(shopMod+0x64,9);u(bagMod+0x78,88);u(bagMod+0x74,9);
    const F pv=view(0x5800130);q(pageUi+0x268,pv);q(pv+0x300,monoFor(button(0xa4df480,pageUi)));
    const F goodsView=view(0x582fb10),bagView=view(0x57ebf40);q(shopMod+0x38,goodsView);q(bagMod+0x38,bagView);
    const F goodsCategories=list(1),bagCategories=list(1);q(shopMod+0x50,goodsCategories);u(ptr(goodsCategories+0x10)+0x20,1);q(bagMod+0x40,bagCategories);u(ptr(bagCategories+0x10)+0x20,0);
    const F goodsModel=list(1),dict=alloc(),entries=alloc();q(shopMod+0x58,dict);q(dict+0x28,entries);q(entries+0x18,1);u(entries+0x20,1);u(entries+0x28,1);q(entries+0x30,goodsModel);const F data=ptr(goodsModel+0x10);u(data+0x20,25);q(data+0x24,(1107296258ULL<<32)|12);
    for(unsigned i=0;i<2;++i){const F grid=alloc(),dictRows=alloc(),rows=alloc(),transform=alloc(),object=view(i?0x57d0f30:0x580b100),closure=alloc();q((i?bagView:goodsView)+(i?0x60:0x68),grid);q(grid+0x78,dictRows);q(dictRows+0x30,rows);q(rows+0x18,1);u(rows+0x20,0);u(rows+0x28,0);q(rows+0x30,transform);q(transform+0x10,0x10000);q(transform+0x20,object);
        if(i){q(closure+0x10,fixtureBase+0x97000);q(closure+0x18,bagMod);u(closure+0x20,0);}else{q(closure+0x10,shopMod);u(closure+0x18,25);q(closure+0x1c,(1107296258ULL<<32)|12);}
        const F bt=button(i?0xd5935f0:0xc5f4050,closure);q(object+0x48,bt);q(object+(i?0x88:0x70),textObject(i?L"苹果":L"10"));if(i)bagButton=bt;else goodsButton=bt;
    }
    for(unsigned i=0;i<3;++i){const F context=i==0?buyUi:i==1?itemUi:sellUi,v=view(i==0?0x5803818:i==1?0x583c498:0x57edbd0);q(context+(i==1?0x220:0x228),v);
        if(i==0){u(context+0x24c,88);u(context+0x254,9);u(context+0x250,SHOP_ACTION==3?3:1);u(context+0x268,5);u(context+0x258,25);q(context+0x25c,(1107296258ULL<<32)|12);confirmBuy=button(0x13a58420,context);q(v+0x300,monoFor(confirmBuy));q(v+0x48,button(0x10b98a70,context));q(v+0x90,textObject(L"苹果"));sliderBuy=slider(context,false,SHOP_ACTION==3?3:1);q(v+0x58,monoFor(sliderBuy));}
        if(i==1){u(context+0x254,88);u(context+0x26c,9);u(context+0x250,23);u(context+0x258,100);q(context+0x25c,(1107296258ULL<<32)|12);u(context+0x268,3);sellOpen=button(0xe4cfdb0,context);q(v+0x300,monoFor(sellOpen));q(v+0x308,monoFor(button(0xe4ce740,context)));q(v+0x58,textObject(L"苹果"));}
        if(i==2){u(context+0x234,6);u(context+0x240,88);u(context+0x248,9);u(context+0x230,1);u(context+0x238,3);u(context+0x244,100);confirmSell=button(0x10f24e50,context);q(v+0x300,monoFor(confirmSell));q(v+0x308,monoFor(button(0x10f258c0,context)));q(v+0x60,textObject(L"出售"));sliderSell=slider(context,true,1);q(v+0x58,monoFor(sliderSell));}
    }
    if constexpr(SHOP_ACTION>=3){q(topArray+0x20,pageUi);top(SHOP_ACTION==5?itemUi:SHOP_ACTION==6?sellUi:buyUi);}
    jump(fixtureBase+0x1455060,reinterpret_cast<F>(&active));jump(fixtureBase+0x1452740,reinterpret_cast<F>(&component));jump(fixtureBase+0x1453d40,reinterpret_cast<F>(&component));jump(fixtureBase+0x10f1da50,reinterpret_cast<F>(&bagIndex));
    for(unsigned rva:{0x13bfd510U,0x116856e0U,0xabd63b0U,0x12ec22f0U})jump(fixtureBase+rva,reinterpret_cast<F>(&getA));for(unsigned rva:{0xabd6880U,0x12ec20a0U})jump(fixtureBase+rva,reinterpret_cast<F>(&getB));
    jump(fixtureBase+0x19dc6600,reinterpret_cast<F>(&press));jump(fixtureBase+0x19dd0320,reinterpret_cast<F>(&sliderValue));jump(fixtureBase+0xc5f4050,reinterpret_cast<F>(&openGoods));jump(fixtureBase+0xd5935f0,reinterpret_cast<F>(&openBag));jump(fixtureBase+0x13a58420,reinterpret_cast<F>(&bought));jump(fixtureBase+0x10f24e50,reinterpret_cast<F>(&sold));jump(fixtureBase+0xe4cfdb0,reinterpret_cast<F>(&openSell));for(unsigned rva:{0x10b98a70U,0xe4ce740U,0x10f258c0U,0xa4df480U})jump(fixtureBase+rva,reinterpret_cast<F>(&returnUi));jump(fixtureBase+0x13a58b00,reinterpret_cast<F>(&quantityBuy));jump(fixtureBase+0x10f25f80,reinterpret_cast<F>(&quantitySell));
}
}
DWORD WINAPI pipeline(void*){
    setup();setupUi();auto scratch=static_cast<ShopReceipt*>(HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,sizeof(ShopReceipt)));if(!scratch)return 1;
    ExecuteInventory(&scratch->inventory);if(scratch->inventory.status)return 2;if(!uiSnapshot(fixtureBase,scratch,scratch->before)){const auto& failed=scratch->before;std::printf("{\"uiSetupFailed\":true,\"kind\":%u,\"rows\":%u,\"context\":%llu,\"page\":%llu,\"shopModule\":%llu,\"bagModule\":%llu,\"backReady\":%u,\"row0Handler\":%u,\"row1Handler\":%u}\n",failed.kind,failed.rowCount,failed.context,failed.page,failed.shopModule,failed.bagModule,failed.backReady,failed.row[0].handlerVerified,failed.row[1].handlerVerified);return 3;}std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));
    fixtureTick=1000000;ExecuteShop(scratch);if(scratch->stage!=1||scratch->actionAttempted||scratch->nativeCalls||scratch->seh)return 4;fixtureTick=100;
    HANDLE mapping=CreateFileMappingW(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,sizeof(Receipt),HR_MAPPING);if(!mapping||GetLastError()==ERROR_ALREADY_EXISTS)return 5;auto receipt=static_cast<Receipt*>(MapViewOfFile(mapping,FILE_MAP_ALL_ACCESS,0,0,sizeof(Receipt)));if(!receipt)return 6;
    auto initialize=[&](){std::memset(receipt,0,sizeof(*receipt));receipt->magic=0x31524847;receipt->version=kReceiptVersion;receipt->nonce=HR_NONCE;receipt->deadline=HR_DEADLINE;receipt->expectedPid=HR_TARGET_PID;receipt->expectedTid=HR_TARGET_TID;fixtureMessage.message=HR_MESSAGE_ID;fixtureMessage.wParam=HR_NONCE;fixtureMessage.lParam=1;};
    initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));const auto& o=receipt->acceptance;
    std::printf("{\"stage\":%u,\"status\":%u,\"seh\":%u,\"action\":%u,\"beforeKind\":%u,\"afterKind\":%u,\"uiStable\":%u,\"pressed\":%u,\"sliderSet\":%u}\n",o.stage,o.status,o.seh,o.action,o.before.kind,o.after.kind,o.uiStable,pressed,sliderSet);
    if(receipt->claim!=2||receipt->active||receipt->callbacks!=1||o.status||o.seh||o.stage!=3||!o.resourcesReleased||!o.uiStable||!o.afterReadable)return 7;
    if constexpr(SHOP_OPERATION==15){if(o.actionAttempted||pressed||sliderSet||o.before.rowCount!=2||!o.before.row[0].handlerVerified||!o.before.row[1].handlerVerified)return 8;}
    else {if(!o.actionAttempted||!o.actionReturned||pressed+sliderSet!=1)return 9;if constexpr(SHOP_ACTION==1){if(o.after.kind!=2)return 10;}if constexpr(SHOP_ACTION==2){if(o.after.kind!=3)return 11;}if constexpr(SHOP_ACTION==3){if(o.after.quantity!=1)return 12;}if constexpr(SHOP_ACTION==5){if(o.after.kind!=4)return 13;}}
    const unsigned count=pressed+sliderSet;const F selectedButton=o.button;ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(count!=pressed+sliderSet||receipt->claim!=2||receipt->callbacks!=1)return 14;
    HANDLE file=CreateFileW(L"shop-pipeline.bin",GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);if(file==INVALID_HANDLE_VALUE)return 15;DWORD written=0;const bool saved=WriteFile(file,&o,sizeof(o),&written,nullptr)!=FALSE&&written==sizeof(o);CloseHandle(file);if(!saved)return 16;
    // Restore the observed UI; corrupt each independent identity before the full hook.
    top(SHOP_ACTION>=3?(SHOP_ACTION==5?itemUi:SHOP_ACTION==6?sellUi:buyUi):pageUi);if constexpr(SHOP_ACTION==3){u(buyUi+0x250,3);put(sliderBuy+0xf8,3.0f);} 
    const F b=fixtureBase;unsigned checks=4;
    u(bagMod+0x78,89);initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||pressed+sliderSet!=count||!receipt->acceptance.status)return 17;u(bagMod+0x78,88);++checks;
    q(b+0x90028,b+0x76000);initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status)return 18;q(b+0x90028,b+0x44000);++checks;
    const F oldTop=ptr(topArray+0x28);top(b+0x20000);initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status)return 19;top(oldTop);++checks;
    if constexpr(SHOP_OPERATION==16){expectedUi[0]^=1;initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status)return 20;expectedUi[0]^=1;++checks;}
    if constexpr(SHOP_OPERATION==16){
        // Advance the immutable fixture baseline as well: these exercise the
        // actual selected-button guards, not merely baseline-byte inequality.
        const F selected=selectedButton;const F event=ptr(selected+(SHOP_ACTION==3?0x100:0xd8));const F calls=ptr(event+0x10),runtime=ptr(calls+0x18),invoke=ptr(ptr(runtime+0x10)+0x20),wrapper=ptr(invoke+0x10),original=ptr(ptr(wrapper+0x40)+0x10);
        const F oldMethod=ptr(original+0x18);q(original+0x18,oldMethod+16);ExecuteInventory(&scratch->inventory);if(!uiSnapshot(b,scratch,scratch->before))return 22;std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status||pressed+sliderSet!=count)return 23;q(original+0x18,oldMethod);++checks;
        if constexpr(SHOP_ACTION!=3){byteValue(selected+0xb0,0);if(!uiSnapshot(b,scratch,scratch->before))return 24;std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status||pressed+sliderSet!=count)return 25;byteValue(selected+0xb0,1);++checks;}
        u(runtime+0x18,0);if(!uiSnapshot(b,scratch,scratch->before))return 26;std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status)return 27;u(runtime+0x18,1);++checks;
    }
    if constexpr(SHOP_ACTION==4||SHOP_ACTION==6){u(oldTop+(SHOP_ACTION==4?0x250:0x230),2);put((SHOP_ACTION==4?sliderBuy:sliderSell)+0xf8,2.0f);if(!uiSnapshot(b,scratch,scratch->before))return 28;std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));if(receipt->acceptance.actionAttempted||!receipt->acceptance.status)return 29;++checks;}
    if constexpr(SHOP_ACTION==3||SHOP_ACTION==7){
        const unsigned variants=SHOP_ACTION==3?1U:3U;
        for(unsigned i=0;i<variants;++i){
            top(SHOP_ACTION==3?sellUi:i==0?pageUi:i==1?itemUi:sellUi);
            if constexpr(SHOP_ACTION==3){u(sellUi+0x230,3);put(sliderSell+0xf8,3.0f);}
            ExecuteInventory(&scratch->inventory);if(!uiSnapshot(b,scratch,scratch->before))return 32;std::memcpy(expectedUi,&scratch->before,sizeof(ShopUi));const unsigned beforeCalls=pressed+sliderSet;initialize();ReceiptHook(HC_ACTION,PM_REMOVE,reinterpret_cast<LPARAM>(&fixtureMessage));const auto& variant=receipt->acceptance;
            if(variant.status||!variant.actionReturned||!variant.afterReadable||pressed+sliderSet!=beforeCalls+1)return 33;
            if constexpr(SHOP_ACTION==3){if(variant.before.kind!=4||variant.after.quantity!=1)return 34;}else {if(variant.after.context==variant.before.context||variant.after.kind!=(i==0?5U:1U))return 35;}
            wchar_t name[64]{};swprintf_s(name,L"shop-variant-%u.bin",i);HANDLE extra=CreateFileW(name,GENERIC_WRITE,FILE_SHARE_READ,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);if(extra==INVALID_HANDLE_VALUE)return 36;DWORD bytes=0;const bool complete=WriteFile(extra,&variant,sizeof(variant),&bytes,nullptr)!=FALSE&&bytes==sizeof(variant);CloseHandle(extra);if(!complete)return 37;++checks;
        }
    }
    std::printf("{\"ok\":true,\"gameAccess\":false,\"desktopAccess\":false,\"productionHookAndCallback\":true,\"engineEndpointsAreStandins\":true,\"gameplayVerified\":false,\"checks\":%u,\"callbackStackReserve\":65536}\n",checks);
    HeapFree(GetProcessHeap(),0,scratch);UnmapViewOfFile(receipt);CloseHandle(mapping);VirtualFree(reinterpret_cast<void*>(fixtureBase),0,MEM_RELEASE);return 0;
}
int main(){HANDLE t=CreateThread(nullptr,65536,pipeline,nullptr,STACK_SIZE_PARAM_IS_A_RESERVATION,nullptr);if(!t)return 30;if(WaitForSingleObject(t,30000)!=WAIT_OBJECT_0)return 31;DWORD r=99;GetExitCodeThread(t,&r);CloseHandle(t);return static_cast<int>(r);}
