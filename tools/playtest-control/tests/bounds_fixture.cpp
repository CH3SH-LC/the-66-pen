// Private-process fixture; no game handles or target access.
#include "native_bounds.cpp"
#include <cstdio>
int main(){
    BoundsReceipt o{};o.beforeCached[0]=o.beforeCached[1]=o.beforeCached[2]=100;
    if(!baseline(&o))return 1;
    o.beforePrimary[0]=1;if(baseline(&o))return 2;
    o.beforePrimary[0]=0;o.beforeCached[1]=0;if(baseline(&o))return 3;
    alignas(8) unsigned char vec[40]{};const float input[3]={21,22,23};
    std::memcpy(vec+24,&input[2],4);std::memcpy(vec+28,&input[1],4);std::memcpy(vec+32,&input[0],4);
    float actual[3]{};if(!getVector(reinterpret_cast<U>(vec),actual)||!sameVector(input,actual))return 4;
    ExecuteAcceptance(&o);if(o.writeStarted||o.nativeCalls||o.status==0)return 5;
    std::puts("{\"ok\":true,\"checks\":5,\"gameAccess\":false,\"guardAndVectorOrderVerified\":true}");return 0;
}
