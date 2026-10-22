#define HR_READ_CONTEXT 1
#define HR_ACTION 1
#define GS_REVIEWED_ACTION_PROFILE 1
#define HR_ACTION_PROFILE_REVIEWED 1
#include "../native/hook_receipt_protocol.h"
#include <cstdio>
static_assert(HR_READ_LEVEL_CATALOG==0,"catalog absent from legacy actions");
static_assert(kReceiptVersion==3,"legacy action version unchanged");
static_assert(sizeof(Receipt)==64+sizeof(GameContextSnapshot)+sizeof(GameSceneActionResult),"legacy action layout unchanged");
int main(){std::printf("{\"ok\":true,\"receiptVersion\":%lu,\"receiptBytes\":%zu,\"catalogPresent\":false,\"gameActionCalled\":false}\n",kReceiptVersion,sizeof(Receipt));return 0;}
