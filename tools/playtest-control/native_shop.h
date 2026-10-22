#pragma once
#include "native_inventory.h"
constexpr unsigned kShopRows=128;
#pragma pack(push,8)
struct ShopRow {
    std::uint64_t object,button,item,key,callbackTarget;
    std::uint32_t role,index,instanceId,key0,key3,active,enabled,handlerVerified,textLength,reserved;
    std::uint16_t text[128];
};
struct ShopUi {
    std::uint64_t context,view,page,shopModule,bagModule,backButton,confirmButton,sellButton,slider,item,key;
    std::uint32_t kind,status,ownerId,shopId,quantity,maximum,instanceId,generation,key0,key3,rowCount,complete,backReady,confirmReady,sellReady,sliderReady,textLength,reserved;
    std::uint16_t text[128];
    ShopRow row[kShopRows];
};
struct ShopReceipt {
    std::uint32_t bytes,version,status,seh,stage,operation,nativeCalls,resourcesReleased,uiStable,actionAttempted,actionReturned,afterReadable,action,row,reserved0,reserved1;
    std::uint64_t avatar,bag,button,callback;
    InventoryReceipt inventory;
    ShopUi before,second,after;
};
#pragma pack(pop)
static_assert(sizeof(ShopRow)==336,"shop row ABI");
static_assert(sizeof(ShopUi)==43424,"shop UI ABI");
static_assert(sizeof(ShopReceipt)==sizeof(InventoryReceipt)+130368,"shop ABI");
void ExecuteShop(ShopReceipt*) noexcept;
