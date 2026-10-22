#pragma once
#include <cstdint>

// Internal Windows-x64 contracts. The host supplies reviewed addresses and
// current owner/config/template evidence; this layer resolves no addresses.
namespace ge::component_binding {
enum class Kind : std::int32_t { bag = 33, shop = 35 };
constexpr std::uint32_t shop_reference_hash = 0xf6589f9c;
constexpr std::uint32_t bag_reference_hash = 0x14ae9e6c;

// Legacy host callback, retained for historical failure/recovery fixtures.
// Native binding uses the typed pool route below: 1013f680 rejects bag/shop.
using CreateReference = void* (__cdecl *)(std::uint32_t template_id);
using CreateTypedReference = void* (__cdecl *)(void* managed_type_name); // 95f6410
using InitializeReferenceId = void (__cdecl *)(void* reference, std::uint32_t id); // 1013f9f0
using AddShopEntry = void* (__cdecl *)(void* config);                 // 8250bf0
using SetReference = void (__cdecl *)(void* target, std::uint32_t field_hash,
                                     void* reference);              // 8a3a760 / 10ed3110
// V's native caller sets RCX=config, EDX=0, R8=0 for virtual+378.
// Shop body82514f0 and bag body10ed3250 consume the first two arguments.
using RefreshDependencies = void (__cdecl *)(void* config, std::int32_t flag,
                                            void* zero_context);
struct NativeCalls {
    CreateReference createReference = nullptr;
    AddShopEntry addShopEntry = nullptr;
    SetReference setShopReference = nullptr;
    SetReference setBagReference = nullptr;
    RefreshDependencies refreshShopDependencies = nullptr;
    RefreshDependencies refreshBagDependencies = nullptr;
    CreateTypedReference createTypedReference = nullptr;
    InitializeReferenceId initializeReferenceId = nullptr;
    void* referenceTypeName = nullptr;
};

// These are host read operations, NOT native getters. They must read the actual
// returned entry/reference and installed field. No inferred/cached success.
using ReadReferenceId = bool (*)(void* context, void* reference, std::uint32_t* id);
using ReadEntryIndex = bool (*)(void* context, void* entry, std::int32_t* index);
using ReadBoundId = bool (*)(void* context, void* target, std::uint32_t field_hash,
                            std::uint32_t* id);
struct Readbacks {
    void* context = nullptr;
    ReadReferenceId referenceId = nullptr;
    ReadEntryIndex entryIndex = nullptr;
    ReadBoundId boundId = nullptr;
};
struct Evidence {
    void* owner = nullptr;
    void* config = nullptr;
    std::uint32_t templateId = 0;
    Kind kind = Kind::bag;
    bool ownerAndConfigVerified = false;
    // Includes the intended template's kind, not merely generic record existence.
    bool templateExistsAndKindVerified = false;
};
enum class BindCode : std::uint32_t {
    returned, invalid_evidence, missing_binding, null_reference,
    reference_readback_failed, reference_id_mismatch, null_entry,
    entry_index_readback_failed, invalid_entry_index,
    binding_readback_failed, binding_id_mismatch, call_exception
};
enum class BindStage : std::uint32_t { none, reference_factory, shop_add, setter, dependency_refresh, reference_initialize };
struct BindResult {
    BindCode code = BindCode::invalid_evidence;
    BindStage exceptionStage = BindStage::none;
    void* reference = nullptr;
    void* entry = nullptr; // Shop only; bag has a single config reference.
    std::int32_t shopIndex = 0; // Meaningful only if entryIndexReadbackVerified.
    bool referenceFactoryCalled = false;
    bool referenceReadbackVerified = false;
    bool addCalled = false;
    bool entryIndexReadbackVerified = false;
    bool setterCalled = false;
    bool fieldReadbackVerified = false; // Observed immediately after setter.
    bool dependencyRefreshCalled = false;
    bool needsDependencyRefresh = false;
    bool mutationCalled = false; // Component add/set invoked, even if it failed.
    // Remains true after any component mutation. Field readback does not prove
    // owner notification, export, save or gameplay. Caller must not auto-retry.
    bool outcomeUncertain = false;
    bool needsOwnerNotification = false;
};

// Calls each native operation at most once; no raw field writes, rollback,
// retry, +3c0 call or owner notification. Missing refresh is reported as pending.
// C++ exceptions return call_exception preserving prior call flags; native SEH
// handling and game-thread enforcement remain the host adapter's responsibility.
BindResult bind_shop(const NativeCalls&, const Readbacks&, const Evidence&);
BindResult bind_bag(const NativeCalls&, const Readbacks&, const Evidence&);
// Progress belongs to the caller and is stored BEFORE native entry. An outer
// SEH handler can recover called flags even when the native call never returns.
void bind_shop_into(const NativeCalls&, const Readbacks&, const Evidence&, BindResult*);
void bind_bag_into(const NativeCalls&, const Readbacks&, const Evidence&, BindResult*);
// Native edit transaction owns the one full refresh+notification after these
// setters. Legacy APIs above retain their existing standalone refresh behavior.
void bind_shop_fields_into(const NativeCalls&, const Readbacks&, const Evidence&, BindResult*);
void bind_bag_fields_into(const NativeCalls&, const Readbacks&, const Evidence&, BindResult*);
}
