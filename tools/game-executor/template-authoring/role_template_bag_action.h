#pragma once
#include "binding_action.h"

namespace ge::templates {
// Root4 player-role prefab domain; never the same-numbered root15 profession.
constexpr std::uint32_t kFarmingRolePrefabId = 1090519041;
constexpr std::uint32_t kFarmingRoleSceneId = 1090519041;
constexpr std::uint32_t kFarmingBagId = 1119879169;
constexpr std::uint32_t kRoleLookupChainLimit = 256;
enum class RoleOwnerCode : std::uint32_t { complete, invalid, unreadable, unstable };
struct RoleOwnerObservation {
    RoleOwnerCode code;
    std::uint32_t sceneId, prefabId, selectedIndex;
    std::uint64_t sceneOwner, prefabOwner, expectedClass, manager, dictionary, buckets, entries;
    std::uint64_t bucketCapacity, entryCapacity;
    unsigned char dictionaryHeader[0x48], templatePrefix[0xc0], scenePrefix[0xc0];
    std::int32_t bucketHead;
    std::uint32_t chainCount;
    std::uint32_t chainIndices[kRoleLookupChainLimit];
    TemplateNativeEntry chain[kRoleLookupChainLimit];
};
struct RoleTemplateBagRequest { std::uint32_t sceneEntityId, rolePrefabId, bagId; };
struct RoleTemplateBagWorkspace {
    BindingActionWorkspace binding;
    RoleOwnerObservation beforeOwner, afterOwner;
    ge::component_edit::EditState finalEditAfter; // Actual post-action state, including failure/SEH paths.
};
// Existing component field/capture result ABI is reused only as a C++ type;
// this is a separate action and never passes a fabricated scene to action7.
using RoleTemplateBagResult = BindingActionResult;
void CaptureRoleTemplateOwner(const GameContextSnapshot*, TemplateReadSource,
    std::uint64_t sceneOwner, const RoleTemplateBagRequest&, RoleOwnerObservation*) noexcept;
void ExecuteRoleTemplateBagAction(const GameContextSnapshot*, const BindingActionReview&,
    const BindingActionRuntime&, TemplateReadSource, const BindingActionCalls&,
    const RoleTemplateBagRequest&, RoleTemplateBagWorkspace*, RoleTemplateBagResult*) noexcept;
}
