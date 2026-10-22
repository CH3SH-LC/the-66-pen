#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "native_observe.h"
#include <cstring>
#include <cmath>
#if HR_ACTION != 17 || !PLAY_OBSERVE_REVIEWED || HR_READ_CONTEXT
#error "Dedicated read-only observation profile required"
#endif
namespace {
using U=std::uint64_t;
bool memory(U at,void* out,std::size_t n) noexcept {
    if(!out||!n||at<0x10000||at>=0x800000000000ULL||n>0x800000000000ULL-at)return false;
    std::size_t done=0;
    while(done<n){MEMORY_BASIC_INFORMATION r{};const auto p=at+done;
        if(VirtualQuery(reinterpret_cast<void*>(p),&r,sizeof(r))!=sizeof(r)||r.State!=MEM_COMMIT||(r.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return false;
        const auto left=r.RegionSize-static_cast<std::size_t>(p-reinterpret_cast<U>(r.BaseAddress));const auto part=n-done<left?n-done:left;
        __try{std::memcpy(static_cast<unsigned char*>(out)+done,reinterpret_cast<void*>(p),part);}__except(EXCEPTION_EXECUTE_HANDLER){return false;}done+=part;
    }return true;
}
template<class T> bool read(U p,T& v){return memory(p,&v,sizeof(v));}
U ptr(U p){U v=0;return read(p,v)&&v>=0x10000&&v<0x800000000000ULL?v:0;}
bool finite(const float* p){return std::isfinite(p[0])&&std::isfinite(p[1])&&std::isfinite(p[2]);}
bool code(U b,PlayReceipt* o){
    IMAGE_DOS_HEADER dos{};IMAGE_NT_HEADERS64 nt{};
    if(!read(b,dos)||dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<0||dos.e_lfanew>0x100000||!read(b+dos.e_lfanew,nt)||nt.Signature!=IMAGE_NT_SIGNATURE||nt.FileHeader.TimeDateStamp!=HR_GAME_TIMESTAMP||nt.OptionalHeader.SizeOfImage!=HR_GAME_IMAGE_SIZE)return false;
    static constexpr unsigned rvas[]={PLAY_CODE_RVAS};static constexpr unsigned char expected[][32]={PLAY_CODE_BYTES};unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){o->failedRva=rvas[i];return false;}
    static constexpr unsigned flags[]={PLAY_HOTFIX_RVAS};
    for(auto r:flags){unsigned char v=255;if(!read(b+r,v)||v){o->failedRva=r;o->failedValue=v;return false;}}
    return true;
}
// Transcription of 173770b0's default UInt32 comparer branch. Never invoke an
// arbitrary managed comparer. Bound allocation size and collision traversal.
unsigned avatar(U b,PlaySample& s){
    if(!s.avatarManager||!read(s.avatarManager+0x250,s.avatarId))return 0;
    if(!s.avatarId)return 1;
    s.dictionary=ptr(s.avatarManager+0x150);if(!s.dictionary)return 5;
    U comparer=0;if(!read(s.dictionary+0x30,comparer))return 5;if(comparer)return 3;
    U buckets=ptr(s.dictionary+0x20),entries=ptr(s.dictionary+0x28),bn=0,en=0;
    if(!buckets)return 1;
    if(!entries||!read(buckets+0x18,bn)||!read(entries+0x18,en)||!bn||bn>65536||en>65536)return 5;
    const auto hash=s.avatarId&0x7fffffffU;std::int32_t index=0;
    if(!read(buckets+0x20+(hash%bn)*4,index))return 5;--index;
    unsigned steps=0;
    while(index>=0&&static_cast<U>(index)<en){
        if(++steps>en+1||steps>65536)return 5;
        const U item=entries+0x20+static_cast<U>(index)*24;std::uint32_t key=0,h=0;
        if(!read(item,h)||!read(item+8,key))return 5;
        if(h==hash&&key==s.avatarId){s.avatar=ptr(item+16);if(!s.avatar)return 1;
            const U klass=ptr(b+0x57b1570);return klass&&ptr(s.avatar)==klass?2U:4U;}
        if(!read(item+4,index))return 5;
    }return index==-1?1U:5U;
}
void position(U b,PlaySample& s,PlayReceipt* o){
    s.positionStatus=1;unsigned char branch=0,initialized=0;
    if(!read(s.avatar+0x47d,branch))return;s.avatarBranch=branch;
    const U originClass=ptr(b+0x57a8ae8);
    if(!originClass||!read(originClass+0xc7,initialized)||!initialized){s.positionStatus=2;return;}
    if(branch){const U unityObject=ptr(s.avatar+0x38);if(!unityObject||!ptr(unityObject+0x10)){s.positionStatus=3;return;}
        ++o->nativeCalls;s.transform=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x1452da0)(reinterpret_cast<void*>(unityObject)));
    }else{
        if(ptr(ptr(s.avatar)+0x4c8)!=b+0x9a96970){s.positionStatus=4;return;}
        s.transform=ptr(s.avatar+0x1e8);
    }
    if(!s.transform||!ptr(s.transform+0x10)){s.positionStatus=3;return;}
    if(!read(b+0x57872a4,s.origin)||!finite(s.origin))return;
    ++o->nativeCalls;reinterpret_cast<void(*)(void*,float*)>(b+0x1436d00)(reinterpret_cast<void*>(s.transform),s.unity);
    if(!finite(s.unity))return;
    for(unsigned i=0;i<3;++i)s.world[i]=s.unity[i]+s.origin[i];
    if(finite(s.world))s.positionStatus=0;
}
unsigned sample(U b,PlaySample& s,PlayReceipt* o){
    s.rawMode=s.editing=0xffffffffU;s.positionStatus=1;
    s.global=ptr(b+0x5783de8);if(!s.global)return 0;unsigned mask=1;
    s.modeManager=ptr(s.global+0xa440);if(s.modeManager&&read(s.modeManager+0x1cc,s.rawMode))mask|=2;
    s.gateManager=ptr(s.global+0xa430);if(s.gateManager){U gate=0;if(read(s.gateManager+0x50,gate)){s.gateObject=gate;mask|=4;}}
    s.editorManager=ptr(s.global+0xa960);unsigned char editing=0;
    if(s.editorManager&&read(s.editorManager+0xc9,editing)&&read(s.editorManager+0x98,s.editorLevel)){s.editing=editing;mask|=8;}
    s.avatarManager=ptr(s.global+0x9d50);s.avatarStatus=avatar(b,s);
    if(s.avatarStatus==2)position(b,s,o);
    return mask;
}
bool stable(const PlaySample& a,const PlaySample& b){
    return a.global==b.global&&a.modeManager==b.modeManager&&a.gateManager==b.gateManager&&a.gateObject==b.gateObject&&a.editorManager==b.editorManager&&a.rawMode==b.rawMode&&a.editing==b.editing&&a.editorLevel==b.editorLevel&&a.avatarManager==b.avatarManager&&a.dictionary==b.dictionary&&a.avatarId==b.avatarId&&a.avatar==b.avatar&&a.avatarStatus==b.avatarStatus;
}
void execute(PlayReceipt* o){
    o->status=1;o->stage=1;o->targetLevel=PLAY_TARGET_LEVEL;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE)return;
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));if(!b||!code(b,o))return;
    o->stage=2;o->readableBefore=sample(b,o->before,o);o->readableAfter=sample(b,o->after,o);
    o->stable=stable(o->before,o->after)&&o->readableBefore==o->readableAfter?1U:0U;
    // A changing positive raw observation is a transition; unreadable does not
    // imply play. No unproven enum value is promoted to a play state.
    if(o->readableBefore==15&&o->readableAfter==15){
        if(o->before.rawMode!=o->after.rawMode||o->before.editing!=o->after.editing||o->before.editorLevel!=o->after.editorLevel)o->mode=2;
        else if(o->stable&&o->after.rawMode==0xb993&&o->after.gateObject&&o->after.editing)o->mode=1;
    }
    o->stage=3;o->status=0;
}
}
void ExecutePlayObservation(PlayReceipt* o) noexcept {
    if(!o)return;std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=1;
    __try{execute(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;}
}
