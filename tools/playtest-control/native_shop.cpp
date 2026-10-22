// Only existing bounded native UI. Never construct dialogs or call transaction,
// inventory, graph, currency, damage, or desktop/input injection endpoints.
#include "native_shop.h"
#include "native_inventory.cpp"
#if (SHOP_OPERATION != 15 && SHOP_OPERATION != 16) || INVENTORY_OPERATION != 14
#error "Fixed trial-bound shop card required"
#endif
namespace {
bool shopCode(U b,ShopReceipt* o){
    static constexpr unsigned rvas[]={SHOP_CODE_RVAS};static constexpr unsigned char bytes[][32]={SHOP_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,bytes[i],32)){o->inventory.control.observation.failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={SHOP_HOTFIX_RVAS};for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->inventory.control.observation.failedRva=r;return false;}}return true;
}
bool uiExact(U b,U x,unsigned slot){return x&&ptr(b+slot)&&ptr(x)==ptr(b+slot);}
bool uiDerives(U klass,U base){if(!klass||!base)return false;if(klass==base)return true;unsigned char depth=0,total=0;if(!read(base+0xc5,depth)||!depth||depth>64||!read(klass+0xc5,total)||total<depth||total>64)return false;return ptr(ptr(klass+0x40)+8ULL*(depth-1))==base;}
bool uiList(U list,U& array,unsigned& n,unsigned max=4096){U cap=0;array=ptr(list+0x10);return list&&read(list+0x18,n)&&n<=max&&array&&read(array+0x18,cap)&&cap>=n&&cap<=65536;}
bool uiText(U b,U object,std::uint16_t* out,unsigned& n){
    if(!object)return true;if(!uiDerives(ptr(object),ptr(b+0x579f540)))return false;const U s=ptr(object+0xe0);if(!s)return true;
    int count=-1;if(!read(s+0x10,count)||count<0||count>127)return false;n=static_cast<unsigned>(count);return !n||memory(s+0x14,out,n*2);
}
bool uiLive(U b,U x,ShopReceipt* o){if(!x||!ptr(x+0x10))return false;++o->nativeCalls;return reinterpret_cast<bool(*)(void*)>(b+0x1455060)(reinterpret_cast<void*>(x));}
U uiComponent(U b,U object,unsigned slot,bool gameObject,ShopReceipt* o){if(!object||!ptr(object+0x10)||!ptr(b+slot))return 0;++o->nativeCalls;return reinterpret_cast<U(*)(void*,void*)>(b+(gameObject?0x1452740:0x1453d40))(reinterpret_cast<void*>(object),reinterpret_cast<void*>(ptr(b+slot)));}
U uiMonoButton(U b,U mono,ShopReceipt* o){return uiComponent(b,ptr(mono+0x68),0x579f538,true,o);}
U uiGetter(U b,U view,unsigned rva,ShopReceipt* o){if(!view||!ptr(view+0x10))return 0;++o->nativeCalls;return reinterpret_cast<U(*)(void*)>(b+rva)(reinterpret_cast<void*>(view));}
// ea33bb0 registers one runtime InvokableCall wrapping 14058e50, which in
// turn invokes the original UI callback. Refuse extra or persistent handlers.
U uiEventHandler(U b,U event,unsigned wrapperRva,unsigned wanted){
    const U calls=ptr(event+0x10),persistent=ptr(event+0x18);U a=0;unsigned n=0;
    if(!uiList(ptr(calls+0x10),a,n,8)||n||!uiList(ptr(persistent+0x10),a,n,8)||n||!uiList(ptr(calls+0x18),a,n,8)||n!=1)return 0;
    const U invocation=ptr(a+0x20),wrapper=ptr(invocation+0x10);if(ptr(wrapper+0x18)!=b+wrapperRva)return 0;
    const U original=ptr(ptr(wrapper+0x40)+0x10);if(ptr(original+0x18)!=b+wanted||ptr(original+0x10)!=b+wanted)return 0;
    return ptr(original+0x40);
}
U uiHandler(U b,U button,unsigned wanted,ShopReceipt* o){(void)o;return uiExact(b,button,0x579f538)?uiEventHandler(b,ptr(button+0xd8),0x14058e50,wanted):0;}
bool uiButton(U b,U button,unsigned callback,U target,ShopReceipt* o){unsigned char enabled=0,groups=0;return button&&uiHandler(b,button,callback,o)==target&&read(button+0xb0,enabled)&&enabled==1&&read(button+0xc0,groups)&&groups==1&&uiLive(b,button,o);}
U uiModule(U b,U page,unsigned methodSlot){
    const U klass=ptr(ptr(ptr(b+methodSlot)+0x10)+0x10);unsigned char initialized=0;if(!klass||!read(klass+0xc8,initialized)||!(initialized&1))return 0;
    U a=0,found=0;unsigned n=0;if(!uiList(ptr(page+0x100),a,n,64))return 0;
    for(unsigned i=0;i<n;++i){const U m=ptr(a+0x20+8ULL*i);if(ptr(m)!=klass)continue;if(found||ptr(m+0x18)!=page)return 0;found=m;}return found;
}
U uiDictionaryValue(U dictionary,unsigned entriesOffset,unsigned key){const U a=ptr(dictionary+entriesOffset);U n=0;if(!a||!read(a+0x18,n)||n>4096)return 0;U found=0;for(unsigned i=0;i<n;++i){const U at=a+0x20+24ULL*i;int hash=-1;unsigned k=0;if(!read(at,hash)||!read(at+8,k))return 0;if(hash<0||k!=key)continue;if(found)return 0;found=ptr(at+16);}return found;}
bool uiCategory(U module,unsigned listOffset,unsigned indexOffset,unsigned& value){U a=0;unsigned n=0,index=0;return uiList(ptr(module+listOffset),a,n,128)&&read(module+indexOffset,index)&&index<n&&read(a+0x20+4ULL*index,value);}
U uiItem(const InventoryReceipt& inv,unsigned id){for(unsigned i=0;i<inv.slotCaptured;++i){const auto& r=inv.slots[0][i];if(r.item&&r.instanceId==id)return r.item;}return 0;}
bool uiRows(U b,ShopReceipt* o,ShopUi& s,U module,bool goods){
    if(!module)return true;const U view=ptr(module+0x38);if(!uiExact(b,view,goods?0x582fb10:0x57ebf40))return false;
    unsigned category=0;if(!uiCategory(module,goods?0x50:0x40,goods?0x68:0x80,category))return false;
    U goodsArray=0;unsigned goodsCount=0;if(goods&&!uiList(uiDictionaryValue(ptr(module+0x58),0x28,category),goodsArray,goodsCount,4096))return false;
    const U grid=ptr(view+(goods?0x68:0x60)),entries=ptr(ptr(grid+0x78)+0x30);U cap=0;
    if(!grid||!entries||!read(entries+0x18,cap)||cap>4096)return false;
    for(unsigned i=0;i<cap;++i){if(GetTickCount64()>=HR_DEADLINE)return false;const U at=entries+0x20+24ULL*i;int hash=-1;unsigned index=0;if(!read(at,hash))return false;if(hash<0)continue;const U transform=ptr(at+16);if(!transform)continue;
        if(!read(at+8,index)||index>=4096)return false;const U object=uiComponent(b,transform,goods?0x580b100:0x57d0f30,false,o);if(!object)return false;
        const U button=ptr(object+0x48);if(!uiExact(b,button,0x579f538))return false;if(!uiLive(b,button,o))continue;
        if(s.rowCount>=kShopRows)return false;auto& r=s.row[s.rowCount++];r.object=object;r.button=button;r.index=index;r.role=goods?1:2;r.active=1;
        unsigned char enabled=0,groups=0;if(!read(button+0xb0,enabled)||enabled>1||!read(button+0xc0,groups)||groups>1)return false;r.enabled=enabled&&groups;
        r.callbackTarget=uiHandler(b,button,goods?0xc5f4050:0xd5935f0,o);
        if(goods){if(index>=goodsCount||!read(goodsArray+0x20+16ULL*index,r.key0)||!read(goodsArray+0x24+16ULL*index,r.key)||!read(goodsArray+0x2c+16ULL*index,r.key3))return false;
            unsigned k0=0,k3=0;U key=0;r.handlerVerified=r.callbackTarget&&ptr(r.callbackTarget+0x10)==module&&read(r.callbackTarget+0x18,k0)&&read(r.callbackTarget+0x1c,key)&&read(r.callbackTarget+0x24,k3)&&k0==r.key0&&key==r.key&&k3==r.key3;
            if(!uiText(b,ptr(object+0x70),r.text,r.textLength))return false;
        }else{
            ++o->nativeCalls;r.item=reinterpret_cast<U(*)(void*,unsigned,unsigned)>(b+0x10f1da50)(reinterpret_cast<void*>(o->inventory.bag),category,index);
            if(!r.item){--s.rowCount;std::memset(&r,0,sizeof(r));continue;}
            if(!read(r.item+0x28,r.instanceId)||uiItem(o->inventory,r.instanceId)!=r.item||!read(r.item+0x20,r.key))return false;
            unsigned selected=0;r.handlerVerified=r.callbackTarget&&ptr(r.callbackTarget+0x18)==module&&ptr(r.callbackTarget+0x10)==r.item&&read(r.callbackTarget+0x20,selected)&&selected==index;
            if(!uiText(b,ptr(object+0x88),r.text,r.textLength))return false;
        }
        if(!(r.key>>32))return false;
    }return true;
}
bool uiSnapshot(U b,ShopReceipt* o,ShopUi& s){
    std::memset(&s,0,sizeof(s));s.status=1;const auto& inv=o->inventory;const U global=inv.control.after.global;
    const U stack=ptr(ptr(global+0x9c70)+0x1a8),array=ptr(stack+0x10);unsigned n=0;U cap=0;if(!stack||!array||!read(stack+0x20,n)||!n||n>128||!read(array+0x18,cap)||cap<n||cap>128)return false;
    s.context=ptr(array+0x20+8ULL*(n-1));
    for(unsigned i=0;i<n;++i){const U x=ptr(array+0x20+8ULL*i);if(uiExact(b,x,0x57ee1d0)){if(s.page)return false;s.page=x;}}
    if(uiExact(b,s.context,0x57b3288)){s.kind=5;s.status=0;s.complete=1;return true;}
    if(!s.page)return false;s.shopModule=uiModule(b,s.page,0x5902540);s.bagModule=uiModule(b,s.page,0x5902538);
    if(s.shopModule){if(!read(s.shopModule+0x6c,s.ownerId)||!read(s.shopModule+0x64,s.shopId))return false;}
    if(s.bagModule){unsigned owner=0,shop=0;if(!read(s.bagModule+0x78,owner)||!read(s.bagModule+0x74,shop))return false;if(s.shopModule&&(owner!=s.ownerId||shop!=s.shopId))return false;s.ownerId=owner;s.shopId=shop;}
    s.generation=inv.before.generation;
    if(s.context==s.page){s.kind=1;s.view=ptr(s.context+0x268);if(!uiExact(b,s.view,0x5800130))return false;
        s.backButton=uiMonoButton(b,uiGetter(b,s.view,0x13bfd510,o),o);s.backReady=uiButton(b,s.backButton,0xa4df480,s.context,o);
        if(!uiRows(b,o,s,s.shopModule,true)||!uiRows(b,o,s,s.bagModule,false))return false;
    }else if(uiExact(b,s.context,0x582fae0)){
        s.kind=2;s.view=ptr(s.context+0x228);unsigned owner=0,shop=0;if(!uiExact(b,s.view,0x5803818)||!read(s.context+0x24c,owner)||!read(s.context+0x254,shop)||owner!=s.ownerId||shop!=s.shopId||!owner||!shop||!read(s.context+0x250,s.quantity)||!read(s.context+0x268,s.maximum)||!read(s.context+0x258,s.key0)||!read(s.context+0x25c,s.key)||!read(s.context+0x264,s.key3)||!(s.key>>32))return false;
        s.confirmButton=uiMonoButton(b,uiGetter(b,s.view,0x116856e0,o),o);s.confirmReady=uiButton(b,s.confirmButton,0x13a58420,s.context,o);
        // The dialog's original direct background/cancel button is +48.
        s.backButton=ptr(s.view+0x48);s.backReady=uiButton(b,s.backButton,0x10b98a70,s.context,o);
        if(!uiText(b,ptr(s.view+0x90),s.text,s.textLength))return false;
    }else if(uiExact(b,s.context,0x5841d70)){
        s.kind=3;s.view=ptr(s.context+0x220);unsigned owner=0,shop=0,generation=0;U itemKey=0;if(!uiExact(b,s.view,0x583c498)||!read(s.context+0x254,owner)||!read(s.context+0x26c,shop)||owner!=s.ownerId||shop!=s.shopId||!read(s.context+0x250,generation)||generation!=s.generation||!read(s.context+0x258,s.instanceId)||!read(s.context+0x25c,s.key)||!read(s.context+0x268,s.maximum))return false;s.item=uiItem(inv,s.instanceId);if(!s.item||!read(s.item+0x20,itemKey)||itemKey!=s.key)return false;
        s.sellButton=uiMonoButton(b,uiGetter(b,s.view,0xabd63b0,o),o);s.sellReady=s.ownerId&&s.shopId&&uiButton(b,s.sellButton,0xe4cfdb0,s.context,o);
        s.backButton=uiMonoButton(b,uiGetter(b,s.view,0xabd6880,o),o);s.backReady=uiButton(b,s.backButton,0xe4ce740,s.context,o);if(!uiText(b,ptr(s.view+0x58),s.text,s.textLength))return false;
    }else if(uiExact(b,s.context,0x583c4b0)){
        s.kind=4;s.view=ptr(s.context+0x228);unsigned owner=0,shop=0,mode=0;if(!uiExact(b,s.view,0x57edbd0)||!read(s.context+0x234,mode)||mode!=6||!read(s.context+0x240,owner)||!read(s.context+0x248,shop)||owner!=s.ownerId||shop!=s.shopId||!owner||!shop||!read(s.context+0x230,s.quantity)||!read(s.context+0x238,s.maximum)||!read(s.context+0x244,s.instanceId))return false;s.item=uiItem(inv,s.instanceId);if(!s.item||!read(s.item+0x20,s.key))return false;
        s.confirmButton=uiMonoButton(b,uiGetter(b,s.view,0x12ec22f0,o),o);s.confirmReady=uiButton(b,s.confirmButton,0x10f24e50,s.context,o);s.backButton=uiMonoButton(b,uiGetter(b,s.view,0x12ec20a0,o),o);s.backReady=uiButton(b,s.backButton,0x10f258c0,s.context,o);if(!uiText(b,ptr(s.view+0x60),s.text,s.textLength))return false;
    }else return false;
    if(s.kind==2||s.kind==4){const U mono=ptr(s.view+0x58);s.slider=uiComponent(b,ptr(mono+0x68),0x57a5bf0,true,o);float low=0,high=0,value=0;unsigned char whole=0;
        s.sliderReady=uiExact(b,s.slider,0x57a5bf0)&&ptr(ptr(s.slider)+0x260)==b+0x19dd0320&&ptr(ptr(s.slider)+0x280)==b+0x19dd0b90&&uiEventHandler(b,ptr(s.slider+0x100),0x11b178b0,s.kind==2?0x13a58b00:0x10f25f80)==s.context&&read(s.slider+0xec,low)&&read(s.slider+0xf0,high)&&read(s.slider+0xf8,value)&&read(s.slider+0xf4,whole)&&whole==1&&std::isfinite(low)&&std::isfinite(high)&&low<=1&&high>=1&&std::isfinite(value)&&value==static_cast<float>(s.quantity)&&s.quantity<=s.maximum&&uiLive(b,s.slider,o);
    }
    s.complete=1;s.status=0;return true;
}
bool shopStillBound(U b,ShopReceipt* o){auto& c=o->inventory.control;PlaySample last{};const unsigned readable=sample(b,last,&c.observation);if(readable!=c.observation.readableAfter||!stable(c.observation.after,last))return false;TrialState finish{};state(b,last,finish,&c);return !std::memcmp(&c.after,&finish,sizeof(finish))&&bound(finish);}
void shop(ShopReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!shopCode(b,o))return;
    ExecuteInventory(&o->inventory);if(o->inventory.status||o->inventory.stage!=3)return;o->avatar=o->inventory.avatar;o->bag=o->inventory.bag;o->stage=2;
    if(!uiSnapshot(b,o,o->before)||!uiSnapshot(b,o,o->second))return;o->uiStable=!std::memcmp(&o->before,&o->second,sizeof(ShopUi));if(!o->uiStable||!shopStillBound(b,o))return;
    if constexpr(SHOP_OPERATION==16){
        if(std::memcmp(SHOP_EXPECTED_UI,&o->before,sizeof(ShopUi))||o->avatar!=SHOP_AVATAR||o->bag!=SHOP_BAG)return;
        const auto& s=o->before;U button=0;bool slider=false;
        if constexpr(SHOP_ACTION==1||SHOP_ACTION==2){if(s.kind!=1||SHOP_ROW>=s.rowCount)return;const auto& r=s.row[SHOP_ROW];if(r.role!=SHOP_ACTION||!r.active||!r.enabled||!r.handlerVerified||(r.key>>32)!=SHOP_CONFIG_ID)return;button=r.button;}
        else if constexpr(SHOP_ACTION==3){if((s.kind!=2&&s.kind!=4)||!s.sliderReady)return;button=s.slider;slider=true;}
        else if constexpr(SHOP_ACTION==4){if(s.kind!=2||s.quantity!=1||!s.confirmReady)return;button=s.confirmButton;}
        else if constexpr(SHOP_ACTION==5){if(s.kind!=3||!s.sellReady)return;button=s.sellButton;}
        else if constexpr(SHOP_ACTION==6){if(s.kind!=4||s.quantity!=1||!s.confirmReady)return;button=s.confirmButton;}
        else if constexpr(SHOP_ACTION==7){if(!s.backReady)return;button=s.backButton;}else return;
        if constexpr(SHOP_ACTION>=3&&SHOP_ACTION<=6){if((s.key>>32)!=SHOP_CONFIG_ID)return;}
        if(GetTickCount64()>=HR_DEADLINE)return;o->button=button;o->callback=b+(slider?0x19dd0320:0x19dc6600);o->actionAttempted=1;++o->nativeCalls;
        if(slider)reinterpret_cast<void(*)(void*,float,void*)>(o->callback)(reinterpret_cast<void*>(button),1.0f,nullptr);else reinterpret_cast<void(*)(void*)>(o->callback)(reinterpret_cast<void*>(button));o->actionReturned=1;
    }
    o->afterReadable=uiSnapshot(b,o,o->after)&&shopStillBound(b,o);o->stage=3;o->status=0;
}
}
void ExecuteShop(ShopReceipt* o) noexcept {if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=6;o->status=1;o->stage=1;o->operation=SHOP_OPERATION;o->resourcesReleased=1;o->action=SHOP_ACTION;o->row=SHOP_ROW;__try{shop(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}}
