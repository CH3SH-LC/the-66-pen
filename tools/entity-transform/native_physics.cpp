#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cmath>
#include <cstring>
#include "native_physics.h"
#if HR_ACTION != 15 || !PHYSICS_REVIEWED || TRANSFORM_WRITE != 0
#error "Read-only entity physics requires dedicated action15 / protocol19"
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
bool finite(const TransformVec3& p){return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
bool finite(const PhysicsMatrix& a){for(float v:a.m)if(!std::isfinite(v))return false;return true;}
bool isA(U klass,U expected){
    unsigned char depth=0,wanted=0;
    if(!read(klass+0xc5,depth)||!read(expected+0xc5,wanted)||wanted==0||wanted>64||depth<wanted)return false;
    const U hierarchy=ptr(klass+0x40);return hierarchy&&ptr(hierarchy+(wanted-1)*8)==expected;
}
bool code(U b,PhysicsReceipt* out){
    static constexpr unsigned rvas[]={PHYSICS_CODE_RVAS};
    static constexpr unsigned char expected[][32]={PHYSICS_CODE_BYTES};unsigned char bytes[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(*rvas);++i)if(!memory(b+rvas[i],bytes,sizeof(bytes))||std::memcmp(bytes,expected[i],sizeof(bytes))){out->failedRva=rvas[i];return false;}
    return true;
}
bool descendant(U b,U child,U root){
    U seen[64]{};
    for(unsigned i=0;child&&i<64;++i){if(child==root)return true;for(unsigned j=0;j<i;++j)if(seen[j]==child)return false;
        if(!ptr(child+0x10))return false;seen[i]=child;child=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x14374b0)(reinterpret_cast<void*>(child)));}
    return false;
}
void matrix(U b,U transform,PhysicsMatrix& out,bool inverse=false){
    reinterpret_cast<void(*)(void*,PhysicsMatrix*)>(b+(inverse?0x1437760:0x14377c0))(reinterpret_cast<void*>(transform),&out);
}
bool unchanged(U b,const TransformRow& row){
    TransformPose now{};using Get=void(*)(void*,TransformVec3*);
    reinterpret_cast<Get>(b+0x1436d90)(reinterpret_cast<void*>(row.unity),&now.localPosition);
    reinterpret_cast<Get>(b+0x1436d00)(reinterpret_cast<void*>(row.unity),&now.worldPosition);
    reinterpret_cast<Get>(b+0x1436f70)(reinterpret_cast<void*>(row.unity),&now.scale);
    return read(row.component+0xe0,now.rotationDegrees)&&!std::memcmp(&now,&row.before,sizeof(now))&&
        reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x14374b0)(reinterpret_cast<void*>(row.unity)))==row.parent;
}
bool add(U b,U root,U type,PhysicsEntity& row,PhysicsReceipt* out){
    if(!root||!ptr(root+0x10))return false;
    ++out->nativeCalls;
    // Proven Component.GetComponentsInChildren(Il2CppClassPointer, bool).
    const U array=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,U,bool)>(b+0x19cbcac0)(reinterpret_cast<void*>(root),type,true));
    U length=0;if(!array||!read(array+0x18,length)||length>kPhysicsColliders)return false;
    for(U i=0;i<length;++i){const U collider=ptr(array+0x20+i*8);if(!collider||!ptr(collider+0x10))return false;
        bool found=false;for(unsigned j=0;j<row.count;++j)if(row.colliders[j].collider==collider)found=true;
        if(found)continue;if(row.count>=kPhysicsColliders)return false;
        auto& c=row.colliders[row.count++];c.collider=collider;c.klass=ptr(collider);
        if(!c.klass||!isA(c.klass,type))return false;
        c.transform=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x1453c10)(reinterpret_cast<void*>(collider)));
        c.gameObject=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x1453c60)(reinterpret_cast<void*>(collider)));
        if(!c.klass||!c.transform||!c.gameObject||!descendant(b,c.transform,root))return false;c.belongs=1;
    }return true;
}
bool query(U b,PhysicsEntity& e,PhysicsCollider& c,PhysicsReceipt* out){
    using Bool=bool(*)(void*);using Bounds=void(*)(void*,PhysicsBounds*);
    auto obj=reinterpret_cast<void*>(c.collider);
    c.enabled=reinterpret_cast<Bool>(b+0x19d071c0)(obj)?1U:0U;
    c.isTrigger=reinterpret_cast<Bool>(b+0x19d071f0)(obj)?1U:0U;
    c.isSceneQuery=reinterpret_cast<Bool>(b+0x19d07210)(obj)?1U:0U;
    c.active=reinterpret_cast<Bool>(b+0x19c9b820)(reinterpret_cast<void*>(c.gameObject))?1U:0U;
    reinterpret_cast<Bounds>(b+0x19d07370)(obj,&c.bounds);matrix(b,c.transform,c.localToWorld);out->nativeCalls+=6;
    if(!finite(c.bounds.center)||!finite(c.bounds.extents)||!finite(c.localToWorld)||c.bounds.extents.x<0||c.bounds.extents.y<0||c.bounds.extents.z<0)return false;
    if(c.enabled&&c.active&&!c.isTrigger&&c.isSceneQuery){
        const auto& x=c.bounds.extents;const float radius=std::sqrt(x.x*x.x+x.y*x.y+x.z*x.z)*2.f+1.f;
        if(!std::isfinite(radius)||radius<=0||radius>10000.f)return false;
        for(unsigned i=0;i<kPhysicsRays;++i){auto& r=c.rays[i];const unsigned axis=i/2;const float sign=i%2?-1.f:1.f;
            TransformVec3 direction{e.localToWorld.m[axis*4],e.localToWorld.m[axis*4+1],e.localToWorld.m[axis*4+2]};
            const float length=std::sqrt(direction.x*direction.x+direction.y*direction.y+direction.z*direction.z);if(length<0.00001f||!std::isfinite(length))return false;
            direction.x*=sign/length;direction.y*=sign/length;direction.z*=sign/length;
            r.origin={c.bounds.center.x+radius*direction.x,c.bounds.center.y+radius*direction.y,c.bounds.center.z+radius*direction.z};
            r.direction={-direction.x,-direction.y,-direction.z};r.maxDistance=radius*2.f;
            struct Guarded {unsigned char before[16];alignas(8) unsigned char hit[80];unsigned char after[16];} guarded;
            std::memset(&guarded,0xa5,sizeof(guarded));std::memset(guarded.hit,0,sizeof(guarded.hit));
            using Raycast=bool(*)(void*,const TransformVec3*,void*,float);
            r.hit=reinterpret_cast<Raycast>(b+0x19d07450)(obj,&r.origin,guarded.hit,r.maxDistance)?1U:0U;++out->nativeCalls;
            for(unsigned j=0;j<16;++j)if(guarded.before[j]!=0xa5||guarded.after[j]!=0xa5)return false;
            std::memcpy(r.raw,guarded.hit,sizeof(r.raw));
        }
    }
    PhysicsBounds after{};PhysicsMatrix finalMatrix{};
    reinterpret_cast<Bounds>(b+0x19d07370)(obj,&after);matrix(b,c.transform,finalMatrix);out->nativeCalls+=2;
    c.stable=!std::memcmp(&after,&c.bounds,sizeof(after))&&!std::memcmp(&finalMatrix,&c.localToWorld,sizeof(finalMatrix))&&
        c.enabled==(reinterpret_cast<Bool>(b+0x19d071c0)(obj)?1U:0U)&&c.isTrigger==(reinterpret_cast<Bool>(b+0x19d071f0)(obj)?1U:0U)&&
        c.isSceneQuery==(reinterpret_cast<Bool>(b+0x19d07210)(obj)?1U:0U)&&
        c.active==(reinterpret_cast<Bool>(b+0x19c9b820)(reinterpret_cast<void*>(c.gameObject))?1U:0U)?1U:0U;
    out->nativeCalls+=4;return c.stable!=0;
}
void execute(const GameContextSnapshot& s,PhysicsReceipt* out){
    out->status=1;out->stage=1;out->count=TRANSFORM_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||out->count==0||out->count>kPhysicsEntities)return;
    if(!code(s.moduleBase,out))return;
    ExecuteTransform(&s,&out->transform);out->nativeCalls+=out->transform.nativeCalls;
    if(out->transform.status||out->transform.seh||out->transform.completed!=out->count||!out->transform.sceneUnchanged)return;
    out->stage=2;const U b=s.moduleBase;
    reinterpret_cast<void(*)(unsigned)>(b+0x524250)(PHYSICS_COLLIDER_USAGE);++out->nativeCalls;
    const U type=ptr(b+PHYSICS_COLLIDER_CLASS_SLOT);if(!type)return;
    for(unsigned i=0;i<out->count;++i){auto& e=out->entities[i];const auto& row=out->transform.rows[i];e.entityId=row.entityId;e.status=1;e.unity=row.unity;e.view=ptr(row.component+0x30);
        matrix(b,e.unity,e.localToWorld);matrix(b,e.unity,e.worldToLocal,true);out->nativeCalls+=2;
        reinterpret_cast<void(*)(void*,float*)>(b+0x19cb6e70)(reinterpret_cast<void*>(e.unity),e.actualLocalRotation);
        constexpr float radians=0.01745329251994329577f;
        const TransformVec3 angles{row.before.rotationDegrees.x*radians,row.before.rotationDegrees.y*radians,row.before.rotationDegrees.z*radians};
        reinterpret_cast<void(*)(const TransformVec3*,float*)>(b+0x1447b00)(&angles,e.expectedLocalRotation);out->nativeCalls+=2;
        if(!finite(e.localToWorld)||!finite(e.worldToLocal)||!add(b,e.unity,type,e,out))return;e.roots=1;
        if(e.view&&e.view!=e.unity){if(!add(b,e.view,type,e,out))return;++e.roots;}
        for(unsigned j=0;j<e.count;++j)if(!query(b,e,e.colliders[j],out))return;
        PhysicsMatrix finalMatrix{};float finalQuaternion[4]{};matrix(b,e.unity,finalMatrix);
        reinterpret_cast<void(*)(void*,float*)>(b+0x19cb6e70)(reinterpret_cast<void*>(e.unity),finalQuaternion);out->nativeCalls+=2;
        e.poseUnchanged=unchanged(b,row)&&!std::memcmp(&e.localToWorld,&finalMatrix,sizeof(finalMatrix))&&!std::memcmp(e.actualLocalRotation,finalQuaternion,sizeof(finalQuaternion))?1U:0U;
        if(!e.poseUnchanged)return;e.status=0;++out->completed;
    }
    out->stage=3;CaptureGameContextSnapshot(&out->transform.afterScene);
    const auto& a=out->transform.afterScene;
    out->sceneUnchanged=(a.status==GS_OK&&a.structSize==sizeof(a)&&a.global==s.global&&a.currentContext==s.currentContext&&a.reserved==s.reserved&&
        a.entityDictionary==s.entityDictionary&&a.entityCaptured==s.entityCaptured&&a.entityValidEntries==s.entityValidEntries&&!a.entityRejected&&
        a.entityVersionBefore==s.entityVersionBefore&&a.entityVersionAfter==s.entityVersionAfter&&!std::memcmp(a.origin,s.origin,sizeof(s.origin))&&
        !std::memcmp(a.entities,s.entities,s.entityCaptured*sizeof(s.entities[0])))?1U:0U;
    if(!out->sceneUnchanged)return;out->status=0;out->stage=4;
}
}
void ExecutePhysics(const GameContextSnapshot* s,PhysicsReceipt* out) noexcept {
    if(!s||!out)return;std::memset(out,0,sizeof(*out));out->size=sizeof(*out);out->version=1;
    __try{execute(*s,out);}__except(EXCEPTION_EXECUTE_HANDLER){out->seh=GetExceptionCode();out->status=2;}
}
