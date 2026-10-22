// Existing client-owned data only. Never invoke lazy bag getters, pooled count
// queries, network handlers, graph execution or any inventory mutation.
#include "native_inventory.h"
#include "native_control.cpp"
#if INVENTORY_OPERATION != 14 || CONTROL_OPERATION != 3
#error "Dedicated bound read-only inventory card required"
#endif
namespace {
bool inventoryCode(U b,InventoryReceipt* o){
    static constexpr unsigned rvas[]={INVENTORY_CODE_RVAS};static constexpr unsigned char expected[][32]={INVENTORY_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->control.observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={INVENTORY_HOTFIX_RVAS};for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->control.observation.failedRva=r;return false;}}return true;
}
bool inventoryClass(U object,U wanted){return object&&wanted&&ptr(object)==wanted;}
bool inventoryList(U list,U& array,unsigned& count,unsigned& capacity,unsigned& version){
    U length=0;array=ptr(list+0x10);if(!list||!array||!read(list+0x18,count)||!read(list+0x1c,version)||!read(array+0x18,length)||count>kInventoryLimit||length<count||length>65536)return false;
    capacity=static_cast<unsigned>(length);return true;
}
bool inventoryContext(U b,const PlaySample& player,U global,InventoryContext& c){
    c.status=1;c.avatar=player.avatar;c.avatarId=player.avatarId;
    unsigned observed=0;unsigned char loaded=0,ready=0,cleared=1;
    if(!c.avatar||!c.avatarId||!read(c.avatar+0x3a8,observed)||observed!=c.avatarId||!read(c.avatar+0x4dc,c.avatarConfigId)||!read(c.avatar+0x42f,loaded)||loaded!=1||!read(c.avatar+0x482,ready)||ready!=1||!read(c.avatar+0x491,cleared)||cleared||!ptr(c.avatar+0x1a0))return false;
    const U array=ptr(ptr(c.avatar+0x2d0)+0x68);U length=0;
    if(!array||!read(array+0x18,length)||length<=17||length>4096)return false;
    c.component=ptr(array+0x20+17*8);if(!inventoryClass(c.component,ptr(b+0x57d1b10))||ptr(c.component+0x28)!=c.avatar)return false;
    // Exact initialized generic argument of BLNMDBHIPFD.JNEGIDCLCBL<52086>.
    const U method=ptr(b+0x58e83c0),context=ptr(method+0x10);c.moduleClass=ptr(context+0x18);unsigned char initialized=0;
    if(!c.moduleClass||!read(c.moduleClass+0xc8,initialized)||!(initialized&1))return false;
    c.modules=ptr(c.component+0x180);c.moduleEntries=ptr(c.modules+0x18);
    if(!c.modules||!c.moduleEntries||!memory(c.modules,c.moduleHeader,64)||!read(c.moduleEntries+0x18,length)||length>1024)return false;c.moduleCapacity=static_cast<unsigned>(length);
    // Enumerate actual occupied entries, not a guessed hash/comparer. Unused
    // zero entries have null keys/values; free entries carry a negative hash.
    for(unsigned i=0;i<c.moduleCapacity;++i){
        if(GetTickCount64()>=HR_DEADLINE)return false;const U at=c.moduleEntries+0x20+24ULL*i;std::int32_t hash=-1;
        if(!read(at,hash))return false;if(hash<0)continue;const U value=ptr(at+16);if(!value)continue;
        if(inventoryClass(value,c.moduleClass)){if(c.module||!ptr(at+8)||ptr(value+0x10)!=c.component)return false;c.module=value;}
    }
    if(!c.module)return false;c.bag=ptr(c.module+0x58);
    if(!inventoryClass(c.bag,ptr(b+0x57d7e30))||ptr(c.bag+0x10)!=c.module||!read(c.bag+0x58,c.templateKey)||!(c.templateKey>>32)||!read(c.bag+0x50,c.bagCapacity)||!c.bagCapacity||c.bagCapacity>kInventoryLimit||!read(c.bag+0x54,c.bagOccupied)||c.bagOccupied>c.bagCapacity||!read(c.bag+0x60,c.generation))return false;
    // Same owner-generation guard as e8291a0/e829a70; read existing +a0 map
    // rather than calling f848610, which can allocate a missing dictionary.
    c.generationDictionary=ptr(ptr(global+0xa410)+0xa0);c.generationEntries=ptr(c.generationDictionary+0x20);
    if(!c.generationDictionary||!c.generationEntries||!memory(c.generationDictionary,c.generationHeader,64)||!read(c.generationEntries+0x18,length)||length>65536)return false;c.generationCapacity=static_cast<unsigned>(length);
    bool found=false;
    for(unsigned i=0;i<c.generationCapacity;++i){
        if(GetTickCount64()>=HR_DEADLINE)return false;const U at=c.generationEntries+0x20+20ULL*i;std::int32_t hash=-1;unsigned key=0,value=0;
        if(!read(at,hash))return false;if(hash<0)continue;if(!read(at+8,key))return false;if(key!=c.avatarId)continue;
        if(found||!read(at+16,value)||value!=c.generation)return false;found=true;c.generationIndex=i;
    }
    if(!found)return false;
    c.totalsList=ptr(c.bag+0x18);c.slotsList=ptr(c.bag+0x30);
    if(!inventoryList(c.totalsList,c.totalsArray,c.totalCount,c.totalCapacity,c.totalVersion)||!inventoryList(c.slotsList,c.slotsArray,c.slotCount,c.slotCapacity,c.slotVersion)||c.slotCount!=c.bagCapacity)return false;
    c.status=0;return true;
}
bool inventoryRows(U b,const InventoryContext& c,InventoryRow* totals,InventoryRow* slots){
    for(unsigned i=0;i<c.totalCount;++i){
        if(GetTickCount64()>=HR_DEADLINE)return false;auto& r=totals[i];r.index=i;r.object=ptr(c.totalsArray+0x20+8ULL*i);
        if(!inventoryClass(r.object,ptr(b+0x5816978))||!read(r.object+0x18,r.key)||!(r.key>>32)||!read(r.object+0x10,r.quantity))return false;
        for(unsigned j=0;j<i;++j)if(totals[j].key==r.key)return false;
    }
    unsigned occupied=0;
    for(unsigned i=0;i<c.slotCount;++i){
        if(GetTickCount64()>=HR_DEADLINE)return false;auto& r=slots[i];r.index=i;r.object=ptr(c.slotsArray+0x20+8ULL*i);unsigned slotIndex=0;
        if(!inventoryClass(r.object,ptr(b+0x5834880))||!read(r.object+0x18,slotIndex)||slotIndex!=i||!read(r.object+0x10,r.item))return false;
        if(!r.item)continue;++occupied;unsigned quantity=0;
        if(!inventoryClass(r.item,ptr(b+0x57ed678))||!read(r.item+0x20,r.key)||!(r.key>>32)||!read(r.item+0x30,quantity)||!read(r.item+0x28,r.instanceId)||!r.instanceId||!read(r.item+0x38,r.itemKind)||r.itemKind<1||r.itemKind>2)return false;r.quantity=quantity;
        for(unsigned j=0;j<i;++j)if(slots[j].item&&(slots[j].item==r.item||slots[j].instanceId==r.instanceId))return false;
    }
    return occupied==c.bagOccupied;
}
void inventory(InventoryReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!inventoryCode(b,o))return;
    ExecuteControl(&o->control);const auto& control=o->control;
    if(control.status||!control.stateStable||!control.observation.stable||!control.after.trialReady||control.after.exitReady||!bound(control.after)||control.observation.after.avatarStatus!=2)return;
    o->stage=2;if(!inventoryContext(b,control.observation.after,control.after.global,o->before))return;
    o->avatar=o->before.avatar;o->component=o->before.component;o->module=o->before.module;o->bag=o->before.bag;
    if(!inventoryRows(b,o->before,o->totals[0],o->slots[0]))return;o->totalCaptured=o->before.totalCount;o->slotCaptured=o->before.slotCount;
    if(!inventoryContext(b,control.observation.after,control.after.global,o->after)||!inventoryRows(b,o->after,o->totals[1],o->slots[1]))return;
    o->contextStable=std::memcmp(&o->before,&o->after,sizeof(InventoryContext))==0?1U:0U;
    o->samplesStable=o->contextStable&&!std::memcmp(o->totals[0],o->totals[1],sizeof(InventoryRow)*o->totalCaptured)&&!std::memcmp(o->slots[0],o->slots[1],sizeof(InventoryRow)*o->slotCaptured)?1U:0U;
    InventoryContext finishContext{};if(!inventoryContext(b,control.observation.after,control.after.global,finishContext)||std::memcmp(&o->after,&finishContext,sizeof(finishContext)))return;
    PlaySample last{};const unsigned readable=sample(b,last,&o->control.observation);
    if(readable!=control.observation.readableAfter||!stable(control.observation.after,last))return;
    TrialState finish{};state(b,last,finish,&o->control);if(std::memcmp(&control.after,&finish,sizeof(finish))||!bound(finish))return;
    o->stage=3;o->status=o->contextStable&&o->samplesStable?0U:2U;
}
}
void ExecuteInventory(InventoryReceipt* o) noexcept {
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=5;o->status=1;o->stage=1;o->operation=INVENTORY_OPERATION;o->resourcesReleased=1;o->before.status=o->after.status=1;
    auto& c=o->control;c.bytes=sizeof(c);c.version=2;c.status=1;c.stage=1;c.operation=3;c.resourcesReleased=1;c.observation.bytes=sizeof(PlayReceipt);c.observation.version=1;c.observation.status=1;c.observation.targetLevel=PLAY_TARGET_LEVEL;c.observation.before.positionStatus=c.observation.after.positionStatus=1;
    __try{inventory(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
