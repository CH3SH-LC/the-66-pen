#pragma once
#include "native_transform.h"
constexpr unsigned kPhysicsEntities=8, kPhysicsColliders=16, kPhysicsRays=6;
struct PhysicsMatrix { float m[16]; }; // Unity column-major Matrix4x4.
struct PhysicsBounds { TransformVec3 center,extents; };
struct PhysicsRay {
    TransformVec3 origin,direction;
    float maxDistance;
    unsigned hit;
    // This build's RaycastHit contains a managed Collider pointer, unlike stock Unity.
    // Keep bounded raw evidence; its exact offsets are pinned in physics-profile.json.
    alignas(8) unsigned char raw[80];
};
struct PhysicsCollider {
    std::uint64_t collider,klass,transform,gameObject;
    unsigned enabled,active,isTrigger,belongs,stable,isSceneQuery;
    PhysicsBounds bounds;
    PhysicsMatrix localToWorld;
    PhysicsRay rays[kPhysicsRays];
};
struct PhysicsEntity {
    unsigned entityId,status,count,roots,poseUnchanged,reserved;
    std::uint64_t unity,view;
    PhysicsMatrix localToWorld,worldToLocal;
    float actualLocalRotation[4],expectedLocalRotation[4];
    PhysicsCollider colliders[kPhysicsColliders];
};
struct PhysicsReceipt {
    unsigned size,version,status,stage,seh,count,completed,nativeCalls;
    unsigned sceneUnchanged,mutationCalls,failedRva,failedValue;
    TransformReceipt transform;
    PhysicsEntity entities[kPhysicsEntities];
};
static_assert(sizeof(PhysicsRay)==112 && sizeof(PhysicsCollider)==816 && sizeof(PhysicsEntity)==13256,"physics query ABI");
void ExecutePhysics(const GameContextSnapshot*,PhysicsReceipt*) noexcept;
