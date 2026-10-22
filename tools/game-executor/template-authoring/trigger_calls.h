#pragma once
#include <cstdint>

// Existing box region only. This does not create a trigger, map event 92,
// select a target entity type, notify an owner, save, or resolve native addresses.
namespace ge::trigger_region {
enum class ObjectKind : std::uint32_t { region = 40001, box = 13279, vector = 51608 };
constexpr std::uint32_t shape_hash = 0x99112b76;
constexpr std::uint32_t box_hash = 0x2c7679c2;
constexpr std::uint32_t vector_hashes[3] = {0x058c4484, 0x82971c71, 0xa5f4fd0a};
constexpr std::uint32_t axis_hashes[3] = {0xfd0c5087, 0xfc0c4ef4, 0xff0c53ad};
using GetUInt = std::uint32_t (__cdecl *)(void*, std::uint32_t, const void*);
using GetObject = void* (__cdecl *)(void*, std::uint32_t, const void*);
using GetFloat = float (__cdecl *)(void*, std::uint32_t, const void*);
// Windows x64: RCX=this, EDX=hash, XMM2=value, R9=null MethodInfo.
using SetFloat = void (__cdecl *)(void*, std::uint32_t, float, const void*);
struct NativeCalls {
    GetUInt shape = nullptr;         // 12ce17f0
    GetObject regionObject = nullptr;// 12ce1d20
    GetObject boxVector = nullptr;   // e375970
    GetFloat vectorAxis = nullptr;   // 1083a8a0
    SetFloat setVectorAxis = nullptr;// 1083b370
};
using VerifyObject = bool (*)(void*, void*, ObjectKind);
struct Evidence {
    void* owner = nullptr;
    void* region = nullptr;
    // Host verifies current ownership, class, installed build and callable heads.
    bool currentRegionAndOwnerVerified = false;
    void* context = nullptr;
    VerifyObject verifyObject = nullptr;
};
struct BoxValues {
    float center[3] = {};
    float scale[3] = {1, 1, 1};
    float rotate[3] = {};
};
enum class Code : std::uint32_t {
    read_returned, configured, invalid_evidence, missing_binding, invalid_values,
    unsupported_shape, unexpected_object, aliased_vectors, readback_mismatch,
    call_exception
};
enum class Stage : std::uint32_t { none, preflight, read, setter, readback };
struct Result {
    Code code = Code::invalid_evidence;
    Stage exceptionStage = Stage::none;
    void* box = nullptr;
    void* vectors[3] = {};
    BoxValues observed;
    std::uint32_t settersStarted = 0;
    std::uint32_t axesVerified = 0;
    bool readbackVerified = false;
    bool mutationCalled = false;
    bool outcomeUncertain = false;
    bool needsOwnerNotification = false;
};
// Caller owns progress before every native call, including an outer SEH fault.
// No rollback/retry/raw writes. Geometry readback never proves gameplay/save.
void read_box_into(const NativeCalls&, const Evidence&, Result*);
void configure_box_into(const NativeCalls&, const Evidence&, const BoxValues&, Result*);
}
