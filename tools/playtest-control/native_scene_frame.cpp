// Dedicated frame capture. Only the returned screenshot texture is destroyed.
// A normal GCHandle roots that managed object until a subsequent engine frame
// confirms its cached native pointer is zero. Camera changes are restored in
// the same callback, including the failure path.
#include "native_scene_frame.h"
#include "native_observe.cpp"
#if HR_ACTION != 19 || !PLAY_SCENE_FRAME_REVIEWED
#error "Dedicated scene frame profile required"
#endif
namespace {
#ifndef SCENE_PREVIOUS_TEXTURE
#define SCENE_PREVIOUS_TEXTURE 0ULL
#define SCENE_PREVIOUS_CACHED 0ULL
#define SCENE_PREVIOUS_HANDLE 0U
#define SCENE_PREVIOUS_FRAME 0U
#endif
bool sceneCode(U b,SceneFrameReceipt* o){
    static constexpr unsigned rvas[]={SCENE_CODE_RVAS};
    static constexpr unsigned char expected[][32]={SCENE_CODE_BYTES};
    unsigned char actual[32]{};
    for(unsigned i=0;i<sizeof(rvas)/sizeof(rvas[0]);++i)
        if(!memory(b+rvas[i],actual,32)||std::memcmp(actual,expected[i],32)){
            o->observation.failedRva=rvas[i];return false;
        }
    return true;
}
bool finiteN(const float* p,unsigned n){
    for(unsigned i=0;i<n;++i)if(!std::isfinite(p[i]))return false;
    return true;
}
bool closeN(const float* p,const float* q,unsigned n){
    for(unsigned i=0;i<n;++i)if(!std::isfinite(p[i])||std::fabs(p[i]-q[i])>0.001f)return false;
    return true;
}
void getPose(U b,SceneFrameReceipt* o,float* p,float* q){
    ++o->nativeCalls;reinterpret_cast<void(*)(U,float*)>(b+0x19cb62b0)(o->transform,p);
    ++o->nativeCalls;reinterpret_cast<void(*)(U,float*)>(b+0x19cb6e50)(o->transform,q);
}
void setPose(U b,SceneFrameReceipt* o,const float* p,const float* q){
    ++o->nativeCalls;reinterpret_cast<void(*)(U,const float*)>(b+0x19cb62d0)(o->transform,p);
    ++o->nativeCalls;reinterpret_cast<void(*)(U,const float*)>(b+0x19cb6e60)(o->transform,q);
}
void captureScene(U b,SceneFrameReceipt* o){
    o->frameStatus=1;o->cameraRestored=1;o->resourcesReleased=1;o->handleReleased=1;
    __try{
        ++o->nativeCalls;const unsigned w=reinterpret_cast<unsigned(*)()>(b+0x19cc2fd0)();
        ++o->nativeCalls;const unsigned h=reinterpret_cast<unsigned(*)()>(b+0x19cc2fe0)();
        if(!w||!h||w>4096||h>4096){o->frameStatus=2;return;}
        ++o->nativeCalls;o->frameBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
        ++o->nativeCalls;o->renderedBefore=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
        if constexpr(SCENE_OPERATION==2){
            // Render() is forbidden while another camera is rendering.
            ++o->nativeCalls;if(reinterpret_cast<U(*)()>(b+0x19cac420)()){o->frameStatus=6;return;}
            ++o->nativeCalls;o->camera=reinterpret_cast<U(*)()>(b+0x19cac410)();
            if(!o->camera||!ptr(o->camera+0x10)){o->frameStatus=6;return;}
            ++o->nativeCalls;o->transform=reinterpret_cast<U(*)(U)>(b+0x19cbc860)(o->camera);
            if(!o->transform||!ptr(o->transform+0x10)){o->frameStatus=6;return;}
            getPose(b,o,o->originalPosition,o->originalRotation);
            ++o->nativeCalls;o->fieldOfView=reinterpret_cast<float(*)(U)>(b+0x19cab280)(o->camera);
            if(!finiteN(o->originalPosition,3)||!finiteN(o->originalRotation,4)||
               !std::isfinite(o->fieldOfView)||o->fieldOfView<20||o->fieldOfView>110||
               o->observation.after.positionStatus!=0){o->frameStatus=6;return;}
            // Fixed Mondstadt overview, in Unity coordinates after origin shift.
            const float world[3]={-140.0f,430.0f,50.0f};
            for(unsigned i=0;i<3;++i)o->capturePosition[i]=world[i]-o->observation.after.origin[i];
            o->captureRotation[0]=0.7071067812f;o->captureRotation[3]=0.7071067812f;
            o->cameraRestored=0;
            setPose(b,o,o->capturePosition,o->captureRotation);
            ++o->nativeCalls;reinterpret_cast<void(*)(U)>(b+0x19cac540)(o->camera);
        }
        // Capture(1) reads the game's backbuffer; no desktop capture APIs.
        o->resourcesReleased=0;
        ++o->nativeCalls;o->texture=reinterpret_cast<U(*)(int)>(b+0x19d141e0)(1);
        if(!o->texture){o->resourcesReleased=1;return;}
        o->cachedBefore=ptr(o->texture+0x10);
        // GCHandle.Alloc(object) is the current-build Normal(2) overload.
        ++o->nativeCalls;o->handle=reinterpret_cast<unsigned(*)(U)>(b+0x195d3a90)(o->texture);
        o->handleReleased=o->handle?0U:1U;
        if(!o->handle||!o->cachedBefore){o->frameStatus=7;return;}
        ++o->nativeCalls;if(reinterpret_cast<U(*)(unsigned)>(b+0x195d38b0)(o->handle)!=o->texture){o->frameStatus=7;return;}
        ++o->nativeCalls;o->width=reinterpret_cast<unsigned(*)(U)>(b+0x19cae530)(o->texture);
        ++o->nativeCalls;o->height=reinterpret_cast<unsigned(*)(U)>(b+0x19cae5a0)(o->texture);
        if(!o->width||!o->height||o->width>4096||o->height>4096){o->frameStatus=2;return;}
        ++o->nativeCalls;const U png=reinterpret_cast<U(*)(U)>(b+0x19cd3610)(o->texture);U bytes=0;
        if(png&&read(png+0x18,bytes)&&bytes>=57&&bytes<=kSceneFrameCapacity&&memory(png+0x20,o->png,static_cast<std::size_t>(bytes))){
            o->pngBytes=static_cast<unsigned>(bytes);o->frameStatus=0;
        }else o->frameStatus=3;
    }__finally{
        // Restore even if capture throws or rejects its dimensions/GC handle.
        if(!o->cameraRestored&&o->transform){
            __try{
                setPose(b,o,o->originalPosition,o->originalRotation);
                getPose(b,o,o->restoredPosition,o->restoredRotation);
                o->cameraRestored=closeN(o->originalPosition,o->restoredPosition,3)&&
                    closeN(o->originalRotation,o->restoredRotation,4)?1U:0U;
            }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();}
        }
        if(o->texture){
            __try{
                ++o->nativeCalls;reinterpret_cast<void(*)(U,float)>(b+0x19cb2d70)(o->texture,0.0f);
                o->destroyQueued=1;
            }__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();}
        }
    }
}
bool collectScene(U b,SceneFrameReceipt* o,bool timeout){
    ++o->nativeCalls;o->frameAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
    ++o->nativeCalls;o->renderedAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
    o->frameAdvanced=o->frameAfter>o->frameBefore?1U:0U;
    if(o->handle&&!o->handleReleased){
        ++o->nativeCalls;const U rooted=reinterpret_cast<U(*)(unsigned)>(b+0x195d38b0)(o->handle);
        U cached=~0ULL;
        if(rooted==o->texture&&read(rooted+0x10,cached)){
            o->cachedAfter=cached;
            if(o->destroyQueued&&o->frameAdvanced&&!cached)o->resourcesReleased=1;
        }else o->guardStatus=3;
        if(o->resourcesReleased||timeout||o->guardStatus){
            ++o->nativeCalls;reinterpret_cast<void(*)(unsigned)>(b+0x195d3b40)(o->handle);o->handleReleased=1;
        }
    }
    return o->resourcesReleased||timeout||o->guardStatus||!o->handle;
}
void finishScene(U b,SceneFrameReceipt* o){
    PlayReceipt after{};ExecutePlayObservation(&after);
    if(after.status||!after.stable||after.mode!=1||after.after.editorLevel!=PLAY_TARGET_LEVEL||
       !stable(o->observation.before,after.after))o->guardStatus=4;
    // Keep the independently valid initial observation; the end guard is explicit.
    o->stage=3;
    o->status=o->seh||o->guardStatus||o->frameStatus||!o->resourcesReleased||
        !o->cameraRestored||!o->handleReleased?2U:0U;
    (void)b;
}
bool stepScene(SceneFrameReceipt* o){
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||GetTickCount64()>=HR_DEADLINE){o->guardStatus=1;return true;}
    const U b=reinterpret_cast<U>(GetModuleHandleW(L"YuanShen.exe"));
    if(!b||!code(b,&o->observation)||!sceneCode(b,o)){o->guardStatus=2;return true;}
    if(o->stage==1){
        ExecutePlayObservation(&o->observation);
        if(o->observation.status||!o->observation.stable||o->observation.mode!=1||
           o->observation.after.editorLevel!=PLAY_TARGET_LEVEL){o->guardStatus=4;return true;}
        if constexpr(SCENE_OPERATION==3){
            // Read-only follow-up of one receipt-bound, already destroyed and
            // unrooted screenshot. Never recaptures, destroys or frees again.
            o->texture=SCENE_PREVIOUS_TEXTURE;o->cachedBefore=SCENE_PREVIOUS_CACHED;
            o->handle=SCENE_PREVIOUS_HANDLE;o->frameBefore=SCENE_PREVIOUS_FRAME;
            o->destroyQueued=o->handleReleased=o->cameraRestored=1;
            ++o->nativeCalls;o->frameAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de20)();
            ++o->nativeCalls;o->renderedAfter=reinterpret_cast<unsigned(*)()>(b+0x19c9de30)();
            o->frameAdvanced=o->frameAfter>o->frameBefore?1U:0U;
            U cached=~0ULL;
            if(!read(o->texture+0x10,cached)){o->guardStatus=5;o->resourcesReleased=0;}
            else{o->cachedAfter=cached;o->resourcesReleased=o->frameAdvanced&&!cached?1U:0U;}
            finishScene(b,o);return true;
        }else{
            o->startedTick=GetTickCount64();captureScene(b,o);o->stage=2;
        }
    }
    const bool done=collectScene(b,o,GetTickCount64()-o->startedTick>=30000);
    if(done)finishScene(b,o);
    return done;
}
}
bool StepSceneFrame(SceneFrameReceipt* o) noexcept{
    if(!o)return true;
    if(!o->stage){
        std::memset(o,0,sizeof(*o));o->bytes=sizeof(*o);o->version=1;o->status=1;
        o->stage=1;o->operation=SCENE_OPERATION;o->resourcesReleased=o->handleReleased=o->cameraRestored=1;
        o->observation.bytes=sizeof(PlayReceipt);o->observation.version=1;o->observation.status=1;
        o->observation.targetLevel=PLAY_TARGET_LEVEL;
        o->observation.before.positionStatus=o->observation.after.positionStatus=1;
    }
    ++o->callbacks;
    __try{return stepScene(o);}__except(EXCEPTION_EXECUTE_HANDLER){o->seh=GetExceptionCode();o->status=2;return true;}
}
