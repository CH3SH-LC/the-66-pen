#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <cstring>
#include <type_traits>
#include "binding_recovery_native_adapter.h"
#if HR_ACTION != 8 || !defined(TA_BINDING_RECOVERY_REVIEWED) || TA_BINDING_RECOVERY_REVIEWED != 1
#error "Dedicated reviewed binding recovery action 8 required"
#endif
namespace {
bool read_memory(void*, std::uint64_t address, void* target, std::size_t length) noexcept {
    if (!target || !length || address < 0x10000 || address >= 0x800000000000ULL || length > 0x800000000000ULL-address) return false;
    std::size_t done=0;
    while (done<length) {
        MEMORY_BASIC_INFORMATION region{}; const auto at=address+done;
        if (VirtualQuery(reinterpret_cast<void*>(at),&region,sizeof(region))!=sizeof(region) || region.State!=MEM_COMMIT || (region.Protect&(PAGE_NOACCESS|PAGE_GUARD))) return false;
        const auto begin=reinterpret_cast<std::uint64_t>(region.BaseAddress);
        if (at<begin || at-begin>=region.RegionSize) return false;
        const auto available=region.RegionSize-static_cast<std::size_t>(at-begin);
        const auto part=length-done<available ? length-done : available;
        __try {std::memcpy(static_cast<unsigned char*>(target)+done,reinterpret_cast<void*>(at),part);}
        __except(EXCEPTION_EXECUTE_HANDLER) {return false;}
        done+=part;
    }
    return true;
}
bool code_verified(const GameContextSnapshot& current) noexcept {
    if (current.moduleBase!=reinterpret_cast<std::uint64_t>(GetModuleHandleW(L"YuanShen.exe")) || current.peTimestamp!=HR_GAME_TIMESTAMP || current.peImageSize!=HR_GAME_IMAGE_SIZE) return false;
    constexpr std::uint32_t rvas[]={TA_BINDING_ANCHOR_RVAS};
    constexpr unsigned char anchors[][32]={TA_BINDING_ANCHOR_BYTES};
    static_assert(sizeof(rvas)/sizeof(rvas[0])==25 && sizeof(anchors)/sizeof(anchors[0])==25,"original binding edit anchors");
    unsigned char observed[32]{};
    for(std::size_t i=0;i<25;++i)
        if(!read_memory(nullptr,current.moduleBase+rvas[i],observed,32) || std::memcmp(observed,anchors[i],32)) return false;
    constexpr std::uint32_t flags[]={GS_PROFILE_HOTFIX_RVAS,TA_BINDING_HOTFIX_RVAS};
    for(auto rva:flags) {unsigned char flag=255; if(!read_memory(nullptr,current.moduleBase+rva,&flag,1)||flag) return false;}
    return true;
}
bool hash_verified(const unsigned char* bytes,std::size_t length,const unsigned char* expected) noexcept {
    BCRYPT_ALG_HANDLE algorithm=nullptr;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0) return false;
    unsigned char digest[32]{};
    const auto status=BCryptHash(algorithm,nullptr,0,const_cast<PUCHAR>(bytes),static_cast<ULONG>(length),digest,32);
    BCryptCloseAlgorithmProvider(algorithm,0);
    return status>=0 && std::memcmp(digest,expected,32)==0;
}
bool token_refusal_verified() noexcept {
    static_assert(sizeof(TA_RECOVERY_TOKEN_REFUSAL)==148552,"immutable v1 refusal ABI");
    if(!hash_verified(TA_RECOVERY_TOKEN_REFUSAL,sizeof(TA_RECOVERY_TOKEN_REFUSAL),TA_RECOVERY_TOKEN_REFUSAL_SHA256)) return false;
    std::uint32_t head[6]{};
    std::memcpy(head,TA_RECOVERY_TOKEN_REFUSAL,sizeof(head));
    // Only a clean v1 callback that refused before either write can authorize
    // this separately reviewed core-close strategy. Never reuse its token.
    return head[0]==148552 && head[1]==1 && head[2]==0 && head[3]==1 && head[4]==1 && head[5]==0;
}
std::uint64_t creation_time(bool thread) noexcept {
    FILETIME created{},ended{},kernel{},user{};
    const BOOL ok=thread ? GetThreadTimes(GetCurrentThread(),&created,&ended,&kernel,&user) : GetProcessTimes(GetCurrentProcess(),&created,&ended,&kernel,&user);
    return ok ? (static_cast<std::uint64_t>(created.dwHighDateTime)<<32)|created.dwLowDateTime : 0;
}
bool same_scene(const GameContextSnapshot& a,const GameContextSnapshot& b) noexcept {
    if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||a.version!=1||b.version!=1||a.status!=GS_OK||b.status!=GS_OK||(a.flags&1951)!=1951||(b.flags&1951)!=1951||((a.flags|b.flags)&96)||a.entityRejected||b.entityRejected||a.reserved!=b.reserved||a.global!=b.global||a.currentContext!=b.currentContext||a.entityCaptured!=b.entityCaptured||b.entityCaptured>kMaxEntities||a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter) return false;
    return std::memcmp(a.entities,b.entities,a.entityCaptured*sizeof(GameEntitySnapshot))==0;
}
void execute(const GameContextSnapshot* current,NativeBindingRecoveryReceipt* out) noexcept {
    using namespace ge::templates;
    static_assert(sizeof(TA_RECOVERY_PRIOR)==sizeof(NativeBindingReceipt),"prior receipt ABI");
    static_assert(offsetof(BindingRecoveryResult,recoveryVersion)==49800,"immutable v1 result prefix");
    std::memcpy(&out->expected,TA_EXPECTED_SNAPSHOT,sizeof(out->expected));
    out->priorHashVerified=hash_verified(TA_RECOVERY_PRIOR,sizeof(TA_RECOVERY_PRIOR),TA_RECOVERY_PRIOR_SHA256)?1U:0U;
    out->tokenRefusalHashVerified=token_refusal_verified()?1U:0U;
    BindingRecoveryReview review{};
    review.pid=HR_TARGET_PID;review.tid=HR_TARGET_TID;
    review.processCreation=HR_TARGET_CREATION;review.threadCreation=HR_TARGET_THREAD_CREATION;review.deadline=HR_DEADLINE;
    review.expected=&out->expected;review.prior=reinterpret_cast<const NativeBindingReceipt*>(TA_RECOVERY_PRIOR);
    review.identity={TA_BINDING_ENTITY_ID,TA_BINDING_TEMPLATE_ID,TA_RECOVERY_COMPONENT_ID,TA_RECOVERY_OWNER,TA_RECOVERY_WRAPPER,TA_RECOVERY_CONFIG,TA_RECOVERY_TOKEN};
    review.tokenRefusal=reinterpret_cast<const BindingRecoveryResult*>(TA_RECOVERY_TOKEN_REFUSAL+98752);
    static_assert(sizeof(TA_RECOVERY_PENDING_DIAGNOSTIC)==148560,"immutable current pending diagnostic ABI");
    static_assert(sizeof(ge::component_edit::EditState)==12416,"pending state ABI");
    review.reviewedPending=reinterpret_cast<const ge::component_edit::EditState*>(TA_RECOVERY_PENDING_DIAGNOSTIC+123720);
    BindingRecoveryRuntime runtime{};
    runtime.pid=GetCurrentProcessId();runtime.tid=GetCurrentThreadId();runtime.processCreation=creation_time(false);runtime.threadCreation=creation_time(true);
    runtime.now=GetTickCount64();runtime.codeVerified=code_verified(*current);runtime.priorReceiptHashVerified=out->priorHashVerified==1;runtime.tokenRefusalHashVerified=out->tokenRefusalHashVerified==1;
    runtime.reviewedPendingHashVerified=hash_verified(TA_RECOVERY_PENDING_DIAGNOSTIC,sizeof(TA_RECOVERY_PENDING_DIAGNOSTIC),TA_RECOVERY_PENDING_DIAGNOSTIC_SHA256);
#if TA_BINDING_RECOVERY_DIAGNOSTIC_ONLY
    // This reviewed build can only observe. It never receives native mutation pointers.
    ReadUnboundBagEditDiagnostic(current,review,runtime,{nullptr,read_memory},RecoveryNativeCalls{},&out->workspace,&out->result);
#else
    const RecoveryNativeCalls calls{reinterpret_cast<ge::component_edit::NotifyComponent>(current->moduleBase+0x9c26c70),reinterpret_cast<decltype(RecoveryNativeCalls::closeCore)>(current->moduleBase+0x9c270a0)};
    CloseUnboundBagAttachment(current,review,runtime,{nullptr,read_memory},calls,&out->workspace,&out->result);
#endif
}
}
void ExecuteNativeBindingRecovery(const GameContextSnapshot* current,NativeBindingRecoveryReceipt* out) noexcept {
    if(!current||!out||out->result.edit.notifyCalled||out->result.edit.closeCalled) return;
    static_assert(std::is_trivially_copyable<NativeBindingRecoveryReceipt>::value,"caller-owned bytes");
    std::memset(out,0,sizeof(*out));out->size=sizeof(*out);out->version=2;
    __try {execute(current,out);}
    __except(EXCEPTION_EXECUTE_HANDLER) {out->sehCode=GetExceptionCode();out->result.outcomeUncertain=out->result.outcomeUncertain||out->result.edit.notifyCalled||out->result.edit.closeCalled;}
    __try {CaptureGameContextSnapshot(&out->after);out->afterSceneUnchanged=same_scene(*current,out->after)?1U:0U;}
    __except(EXCEPTION_EXECUTE_HANDLER) {if(!out->sehCode)out->sehCode=GetExceptionCode();}
}
