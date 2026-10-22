#include "native_tabs.h"
#include <cstdio>
#include <cstddef>
int main(){
    std::printf("{\"NativeTabReceipt\":%zu,\"hosts\":%zu,\"TabHostResult\":%zu,\"options\":%zu,\"TabRow\":%zu,\"text\":%zu,\"radius\":%zu,\"colliderShape\":%zu,\"readbackVerified\":%zu}",
        sizeof(NativeTabReceipt),offsetof(NativeTabReceipt,hosts),sizeof(TabHostResult),offsetof(TabHostResult,options),sizeof(TabRow),offsetof(TabRow,text),offsetof(TabHostResult,radius),offsetof(TabHostResult,colliderShape),offsetof(TabHostResult,readbackVerified));
}
