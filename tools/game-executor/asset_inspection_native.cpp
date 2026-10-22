#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cmath>
#include <cstring>
#include "asset_inspection_native.h"
#if HR_ACTION != 18 || !ASSET_INSPECTION_REVIEWED || TRANSFORM_WRITE != 0
#error "Read-only asset inspection requires dedicated action18 / protocol23"
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
bool finite(const AssetMatrix& a){for(float v:a.m)if(!std::isfinite(v))return false;return true;}
bool finite(const AssetBounds& a){return finite(a.center)&&finite(a.extents)&&a.extents.x>=0&&a.extents.y>=0&&a.extents.z>=0;}
bool isA(U klass,U expected){
    unsigned char depth=0,wanted=0;
    if(!read(klass+0xc5,depth)||!read(expected+0xc5,wanted)||wanted==0||wanted>64||depth<wanted)return false;
    const U hierarchy=ptr(klass+0x40);return hierarchy&&ptr(hierarchy+(wanted-1)*8)==expected;
}
bool code(U b,AssetReceipt* out){
    static constexpr unsigned rvas[]={ASSET_CODE_RVAS};static constexpr unsigned char expected[][32]={ASSET_CODE_BYTES};unsigned char bytes[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(*rvas);++i)if(!memory(b+rvas[i],bytes,sizeof(bytes))||std::memcmp(bytes,expected[i],sizeof(bytes))){out->failedRva=rvas[i];return false;}
    return true;
}
void matrix(U b,U transform,AssetMatrix& out,bool inverse=false){
    reinterpret_cast<void(*)(void*,AssetMatrix*)>(b+(inverse?0x1437760:0x14377c0))(reinterpret_cast<void*>(transform),&out);
}
bool descendant(U b,U child,U root){
    U seen[64]{};for(unsigned i=0;child&&i<64;++i){if(child==root)return true;for(unsigned j=0;j<i;++j)if(seen[j]==child)return false;
        if(!ptr(child+0x10))return false;seen[i]=child;child=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x14374b0)(reinterpret_cast<void*>(child)));}return false;
}
void name(U b,U object,wchar_t* text,unsigned& length,unsigned& status,AssetReceipt* out){
    // Object.get_name returns an IL2CPP string; names are not asset paths or pixels.
    const U value=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x19cb2e60)(reinterpret_cast<void*>(object)));++out->nativeCalls;
    int count=0;status=2;length=0;if(!value||!read(value+0x10,count)||count<0)return;
    const unsigned total=static_cast<unsigned>(count);length=total<kAssetNameChars?total:kAssetNameChars;
    if(length&&!memory(value+0x14,text,length*sizeof(wchar_t))){length=0;return;}
    status=total<=kAssetNameChars?1U:3U;
}
bool add(U b,U root,U type,unsigned kind,AssetEntity& row,AssetReceipt* out){
    if(!root||!ptr(root+0x10))return false;++out->nativeCalls;
    const U array=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,U,bool)>(b+0x19cbcac0)(reinterpret_cast<void*>(root),type,true));
    U length=0;if(!array||!read(array+0x18,length)||length>kAssetObjects){out->failedValue=1;return false;}
    for(U i=0;i<length;++i){const U object=ptr(array+0x20+i*8);if(!object||!ptr(object+0x10))return false;
        bool found=false;for(unsigned j=0;j<row.count;++j)if(row.objects[j].object==object&&row.objects[j].kind==kind)found=true;
        if(found)continue;if(row.count>=kAssetObjects){out->failedValue=1;return false;}
        auto& c=row.objects[row.count++];c.object=object;c.klass=ptr(object);c.kind=kind;
        if(!c.klass||!isA(c.klass,type))return false;
        c.transform=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x1453c10)(reinterpret_cast<void*>(object)));
        c.gameObject=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x1453c60)(reinterpret_cast<void*>(object)));out->nativeCalls+=2;
        if(!c.transform||!c.gameObject||!descendant(b,c.transform,root))return false;c.belongs=1;
    }return true;
}
bool query(U b,U meshType,U meshRendererType,AssetObject& c,AssetReceipt* out){
    using Bool=bool(*)(void*);using Bounds=void(*)(void*,AssetBounds*);auto obj=reinterpret_cast<void*>(c.object);
    c.active=reinterpret_cast<Bool>(b+0x19c9b820)(reinterpret_cast<void*>(c.gameObject))?1U:0U;
    matrix(b,c.transform,c.localToWorld);out->nativeCalls+=2;
    if(!finite(c.localToWorld))return false;
    name(b,c.object,c.name,c.nameLength,c.nameStatus,out);
    if(c.kind==1){
        c.enabled=reinterpret_cast<Bool>(b+0x19cd26c0)(obj)?1U:0U;
        reinterpret_cast<Bounds>(b+0x19cd25d0)(obj,&c.worldBounds);out->nativeCalls+=2;
    }else if(c.kind==2){
        c.enabled=reinterpret_cast<Bool>(b+0x19d071c0)(obj)?1U:0U;
        c.isTrigger=reinterpret_cast<Bool>(b+0x19d071f0)(obj)?1U:0U;
        c.isSceneQuery=reinterpret_cast<Bool>(b+0x19d07210)(obj)?1U:0U;
        reinterpret_cast<Bounds>(b+0x19d07370)(obj,&c.worldBounds);out->nativeCalls+=4;
    }
    if(c.kind==1&&isA(c.klass,meshRendererType)){
        c.mesh=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x19ca1d70)(obj));++out->nativeCalls;
        if(c.mesh){if(!ptr(c.mesh+0x10)||!isA(ptr(c.mesh),meshType))return false;
            reinterpret_cast<Bounds>(b+0x19ca0300)(reinterpret_cast<void*>(c.mesh),&c.localGeometryBounds);++out->nativeCalls;
            if(!finite(c.localGeometryBounds))return false;c.geometry=1;name(b,c.mesh,c.meshName,c.meshNameLength,c.meshNameStatus,out);}
    }
    if(!finite(c.worldBounds))return false;
    AssetMatrix finalMatrix{};matrix(b,c.transform,finalMatrix);++out->nativeCalls;
    c.stable=!std::memcmp(&c.localToWorld,&finalMatrix,sizeof(finalMatrix))&&
        c.active==(reinterpret_cast<Bool>(b+0x19c9b820)(reinterpret_cast<void*>(c.gameObject))?1U:0U)?1U:0U;++out->nativeCalls;
    if(c.kind==1&&isA(c.klass,meshRendererType)){
        const U finalMesh=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x19ca1d70)(obj));++out->nativeCalls;
        if(finalMesh!=c.mesh)c.stable=0;
        if(c.mesh){AssetBounds bounds{};reinterpret_cast<Bounds>(b+0x19ca0300)(reinterpret_cast<void*>(c.mesh),&bounds);++out->nativeCalls;
            if(std::memcmp(&bounds,&c.localGeometryBounds,sizeof(bounds)))c.stable=0;}
    }
    {
        AssetBounds bounds{};reinterpret_cast<Bounds>(b+(c.kind==1?0x19cd25d0:0x19d07370))(obj,&bounds);++out->nativeCalls;
        const bool enabled=reinterpret_cast<Bool>(b+(c.kind==1?0x19cd26c0:0x19d071c0))(obj);++out->nativeCalls;
        if(std::memcmp(&bounds,&c.worldBounds,sizeof(bounds))||c.enabled!=(enabled?1U:0U))c.stable=0;
        if(c.kind==2){const bool trigger=reinterpret_cast<Bool>(b+0x19d071f0)(obj),queryable=reinterpret_cast<Bool>(b+0x19d07210)(obj);out->nativeCalls+=2;
            if(c.isTrigger!=(trigger?1U:0U)||c.isSceneQuery!=(queryable?1U:0U))c.stable=0;}
    }return c.stable!=0;
}
bool poseUnchanged(U b,const TransformRow& row){
    TransformPose now{};using Get=void(*)(void*,TransformVec3*);
    reinterpret_cast<Get>(b+0x1436d90)(reinterpret_cast<void*>(row.unity),&now.localPosition);
    reinterpret_cast<Get>(b+0x1436d00)(reinterpret_cast<void*>(row.unity),&now.worldPosition);
    reinterpret_cast<Get>(b+0x1436f70)(reinterpret_cast<void*>(row.unity),&now.scale);
    return read(row.component+0xe0,now.rotationDegrees)&&!std::memcmp(&now,&row.before,sizeof(now))&&
        reinterpret_cast<U>(reinterpret_cast<void*(*)(void*)>(b+0x14374b0)(reinterpret_cast<void*>(row.unity)))==row.parent;
}
void execute(const GameContextSnapshot& s,AssetReceipt* out){
    out->status=1;out->stage=1;out->count=TRANSFORM_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE||out->count==0||out->count>kAssetEntities)return;
    if(!code(s.moduleBase,out))return;ExecuteTransform(&s,&out->transform);out->nativeCalls+=out->transform.nativeCalls;
    if(out->transform.status||out->transform.seh||out->transform.completed!=out->count||!out->transform.sceneUnchanged)return;
    out->stage=2;const U b=s.moduleBase;
    reinterpret_cast<void(*)(unsigned)>(b+0x524250)(0x4c1b1);++out->nativeCalls;
    const U renderer=ptr(b+0x57a11e8),collider=ptr(b+0x57a1da0),meshRendererType=ptr(b+ASSET_MESH_RENDERER_CLASS_SLOT),meshType=ptr(b+ASSET_MESH_CLASS_SLOT);
    if(!renderer||!collider||!meshRendererType||!meshType)return;
    const U types[]={renderer,collider};
    for(unsigned i=0;i<out->count;++i){auto& e=out->entities[i];const auto& row=out->transform.rows[i];e.entityId=row.entityId;e.status=1;e.unity=row.unity;e.view=ptr(row.component+0x30);
        matrix(b,e.unity,e.localToWorld);matrix(b,e.unity,e.worldToLocal,true);out->nativeCalls+=2;
        if(!finite(e.localToWorld)||!finite(e.worldToLocal))return;
        for(unsigned kind=1;kind<=2;++kind){if(!add(b,e.unity,types[kind-1],kind,e,out))return;
            if(e.view&&e.view!=e.unity&&!add(b,e.view,types[kind-1],kind,e,out))return;}
        e.roots=e.view&&e.view!=e.unity?2U:1U;
        for(unsigned j=0;j<e.count;++j)if(!query(b,meshType,meshRendererType,e.objects[j],out))return;
        AssetMatrix finalMatrix{};matrix(b,e.unity,finalMatrix);++out->nativeCalls;
        e.poseUnchanged=poseUnchanged(b,row)&&!std::memcmp(&e.localToWorld,&finalMatrix,sizeof(finalMatrix))?1U:0U;out->nativeCalls+=4;
        if(!e.poseUnchanged)return;e.status=0;++out->completed;
    }
    out->stage=3;CaptureGameContextSnapshot(&out->transform.afterScene);const auto& a=out->transform.afterScene;
    out->sceneUnchanged=(a.status==GS_OK&&a.structSize==sizeof(a)&&a.global==s.global&&a.currentContext==s.currentContext&&a.reserved==s.reserved&&
        a.entityDictionary==s.entityDictionary&&a.entityCaptured==s.entityCaptured&&a.entityValidEntries==s.entityValidEntries&&!a.entityRejected&&
        a.entityVersionBefore==s.entityVersionBefore&&a.entityVersionAfter==s.entityVersionAfter&&!std::memcmp(a.origin,s.origin,sizeof(s.origin))&&
        !std::memcmp(a.entities,s.entities,s.entityCaptured*sizeof(s.entities[0])))?1U:0U;
    if(!out->sceneUnchanged)return;out->status=0;out->stage=4;
}
}
void ExecuteAssetInspection(const GameContextSnapshot* s,AssetReceipt* out) noexcept {
    if(!s||!out)return;std::memset(out,0,sizeof(*out));out->size=sizeof(*out);out->version=1;
    __try{execute(*s,out);}__except(EXCEPTION_EXECUTE_HANDLER){out->seh=GetExceptionCode();out->status=2;}
}
