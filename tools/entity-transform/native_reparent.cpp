// The original converter's read-only guards and world-pose routines are reused
// verbatim. Its scene-to-accessory entry point is not called by this operation.
#define ExecuteAssembly ExecuteUnusedLegacyAssembly
#include "native_assembly.cpp"
#undef ExecuteAssembly
#include "native_reparent.h"
#if !REPARENT_REVIEWED || TRANSFORM_WRITE != 0
#error "Reparent requires a fixed reviewed card and read-only entity preflight"
#endif
namespace {
bool stableScene(const GameContextSnapshot& a,const GameContextSnapshot& b){
    if(a.structSize!=sizeof(a)||b.structSize!=sizeof(b)||a.status||b.status||
       (a.flags&1951)!=1951||(b.flags&1951)!=1951||(a.flags&96)||(b.flags&96)||
       a.reserved!=TRANSFORM_LEVEL||b.reserved!=TRANSFORM_LEVEL||
       a.entityRejected||b.entityRejected||a.entityCaptured!=b.entityCaptured||
       a.entityCaptured!=a.entityValidEntries||b.entityCaptured!=b.entityValidEntries||
       a.entityVersionBefore!=b.entityVersionBefore||a.entityVersionAfter!=b.entityVersionAfter||
       a.global!=b.global||a.currentContext!=b.currentContext||a.moduleBase!=b.moduleBase||
       a.entityDictionary!=b.entityDictionary||a.contextDictionary!=b.contextDictionary||
       std::memcmp(a.origin,b.origin,sizeof(a.origin)))return false;
    for(unsigned i=0;i<a.entityCaptured;++i){
        const auto& x=a.entities[i];const auto& y=b.entities[i];
        if(x.id!=y.id||x.owner!=y.owner||x.config!=y.config||x.context!=y.context||
           x.configId!=y.configId||x.dictionaryKey!=y.dictionaryKey)return false;
    }
    return true;
}
U findOwner(const GameContextSnapshot& s,unsigned id){
    U owner=0;
    for(unsigned i=0;i<s.entityCaptured;++i)if(s.entities[i].id==id){
        if(owner)return 0;owner=s.entities[i].owner;
    }
    return owner;
}
bool findRequestedChildren(const GameContextSnapshot& s,U owner,unsigned hostId,
                          ReparentReceipt* receipt){
    U c=0,items=0;unsigned count=0;
    if(!accessories(s,owner,c,count,items))return false;
    U owners[999]{};
    if(count&&!memory(items+0x20,owners,count*sizeof(U)))return false;
    for(unsigned i=0;i<count;++i){
        const U p=owners[i];unsigned actual=0;
        if(!p||!read(p+0x1c,actual))return false;
        for(unsigned j=0;j<receipt->common.count;++j){
            auto& r=receipt->transfers[j];
            if(r.oldHostId==hostId&&r.accessoryId==actual){
                if(r.accessory)return false;r.accessory=p;
            }
        }
    }
    for(unsigned j=0;j<receipt->common.count;++j)
        if(receipt->transfers[j].oldHostId==hostId&&!receipt->transfers[j].accessory)return false;
    return true;
}
bool membership(const GameContextSnapshot& s,U owner,U child,U childComponent,
                bool present,unsigned& count){
    U c=0,items=0;
    if(!accessories(s,owner,c,count,items))return false;
    const U ids=ptr(c+0x38),idItems=ptr(ids+0x10);
    unsigned id=0;U capacity=0;
    if(!read(childComponent+0x1c,id)||!id||ptr(childComponent+0x20)!=child||
       !idItems||!read(idItems+0x18,capacity)||capacity<count||capacity>4096)return false;
    // 104c9600 appends child component IDs to +38 and matching owners to +40.
    // 104c9970 removes the same index from both. Read each bounded list once;
    // require the target ID and pointer to occur at exactly the same index.
    unsigned componentIds[999]{};U owners[999]{};
    if(count&&(!memory(idItems+0x20,componentIds,count*sizeof(unsigned))||
               !memory(items+0x20,owners,count*sizeof(U))))return false;
    unsigned found=0;
    for(unsigned i=0;i<count;++i){
        if(!componentIds[i]||owners[i]<0x10000||owners[i]>=0x800000000000ULL||
           ((componentIds[i]==id)!=(owners[i]==child)))return false;
        if(componentIds[i]==id)++found;
    }
    return found==static_cast<unsigned>(present);
}
bool ownedScope(const GameContextSnapshot& s,ReparentReceipt* receipt){
    const U manager=ptr(s.global+0xecd0),list=ptr(manager+0x18),items=ptr(list+0x10);
    int base=-1,depth=-1;unsigned count=9999;U capacity=0;
    unsigned char flags[3]{};
    if(!receipt->batchOpened||receipt->batchClosed||!receipt->batchTransaction||
       !manager||!list||!items||!read(manager+0x30,base)||base!=receipt->baseDepth||
       !read(manager+0x34,depth)||depth!=base+1||!read(manager+0x28,flags)||
       flags[1]||flags[2]||!read(list+0x18,count)||count>4*receipt->common.count||
       count>256||!read(items+0x18,capacity)||capacity<count||capacity>4096)return false;
    U records[256]{},targets[256]{};
    if(count&&!memory(items+0x20,records,count*sizeof(U)))return false;
    const U expectedClass=ptr(s.moduleBase+0x5812cf8);
    if(!expectedClass)return false;
    for(unsigned i=0;i<count;++i){
        U target=0,before=0,klass=0;unsigned char block[0x38]{};
        if(!memory(records[i],block,sizeof(block)))return false;
        std::memcpy(&klass,block,8);std::memcpy(&target,block+0x18,8);
        std::memcpy(&before,block+0x28,8);
        if(klass!=expectedClass||target<0x10000||target>=0x800000000000ULL||
           before<0x10000||before>=0x800000000000ULL||block[0x30]>1)return false;
        bool allowed=false;
        for(unsigned j=0;j<receipt->common.count;++j){
            const auto& r=receipt->transfers[j];
            if(target==r.oldComponent||target==r.component||
               target==r.childComponent||target==r.transform)allowed=true;
        }
        if(!allowed)return false;
        for(unsigned j=0;j<i;++j)if(targets[j]==target)return false;
        targets[i]=target;
    }
    if(count>receipt->pendingPeak)receipt->pendingPeak=count;
    receipt->batchDepth=depth;
    return true;
}
bool closeBatch(const GameContextSnapshot& s,ReparentReceipt* receipt){
    if(!ownedScope(s,receipt))return false;
    reinterpret_cast<void(*)(void*)>(s.moduleBase+0xc7bab90)(
        reinterpret_cast<void*>(receipt->batchTransaction));
    unsigned pending=9999;int depth=-1;
    if(!undo(s,pending,depth)||depth!=receipt->baseDepth)return false;
    receipt->batchClosed=1;receipt->batchDepth=depth;
    for(unsigned i=0;i<receipt->common.count;++i){
        auto& r=receipt->transfers[i];
        if(r.opened){r.closed=1;r.pendingAfter=pending;r.depthAfter=depth;}
    }
    return true;
}
bool inBudget(ReparentReceipt* receipt){
    if(GetTickCount64()-receipt->startedTick<receipt->budgetMillis)return true;
    receipt->budgetExceeded=1;receipt->common.failedValue=309;return false;
}
bool transfer(const GameContextSnapshot& s,ReparentRow& r,ReparentReceipt* receipt){
    auto out=&receipt->common;
    AssemblyWorld now{},hostWorld{};
    U c=0,items=0;unsigned parent=0;
    if(!code(s,out)||!world(s,r.accessory,now)||!same(r.before,now)||
       !world(s,r.host,hostWorld)||
       std::fabs(hostWorld.scale.x-hostWorld.scale.y)>.0001f||
       std::fabs(hostWorld.scale.x-hostWorld.scale.z)>.0001f||
       !read(r.childComponent+0x48,parent)||parent!=r.oldComponentId||
       !membership(s,r.oldHost,r.accessory,r.childComponent,true,r.oldBefore)||
       !membership(s,r.host,r.accessory,r.childComponent,false,r.newBefore)||r.newBefore>=999||
       !accessories(s,r.host,c,r.newBefore,items)||c!=r.component||
       !ownedScope(s,receipt))return false;
    // The row boundaries describe the shared batch transaction. Pending work
    // inside it is checked against the exact planned components by ownedScope.
    r.opened=1;r.transaction=receipt->batchTransaction;
    // The existing native attach operation records its new host and child
    // relationship. Preserve the old host and transform in our outer undo scope.
    using Record=void(*)(void*,void*,int);
    reinterpret_cast<Record>(s.moduleBase+0x107abdf0)(
        reinterpret_cast<void*>(r.oldComponent),nullptr,0);
    reinterpret_cast<Record>(s.moduleBase+0x107abdf0)(
        reinterpret_cast<void*>(r.transform),nullptr,0);
    r.called=1;++out->mutationCalls;
    reinterpret_cast<void(*)(void*,void*,int)>(s.moduleBase+0x97ec2a0)(
        reinterpret_cast<void*>(r.host),reinterpret_cast<void*>(r.accessory),-1);
    bool attached=read(r.childComponent+0x48,r.parentAfter)&&r.parentAfter==r.componentId&&
        membership(s,r.oldHost,r.accessory,r.childComponent,false,r.oldAfter)&&r.oldAfter+1==r.oldBefore&&
        membership(s,r.host,r.accessory,r.childComponent,true,r.newAfter)&&r.newAfter==r.newBefore+1;
    if(attached){
        // These are the same world setters used by 97f7f90, with a positive
        // uniform destination scale. No gameplay field or raw memory write.
        auto target=reinterpret_cast<void*>(r.transform);
        reinterpret_cast<void(*)(void*,const TransformVec3*)>(s.moduleBase+0x74f1590)(
            target,&r.before.position);
        reinterpret_cast<void(*)(void*,const TransformVec3*)>(s.moduleBase+0x74ed750)(
            target,&r.before.rotation);
        TransformVec3 local{r.before.scale.x/hostWorld.scale.x,
                           r.before.scale.y/hostWorld.scale.y,
                           r.before.scale.z/hostWorld.scale.z};
        reinterpret_cast<void(*)(void*,const TransformVec3*,bool)>(s.moduleBase+0x74ecfc0)(
            target,&local,true);
    }
    using Dirty=void(*)(void*,void*);
    auto manager=reinterpret_cast<void*>(ptr(s.global+0xecd0));
    reinterpret_cast<Dirty>(s.moduleBase+0x9c26c70)(manager,reinterpret_cast<void*>(r.oldComponent));
    reinterpret_cast<Dirty>(s.moduleBase+0x9c26c70)(manager,reinterpret_cast<void*>(r.transform));
    return attached&&world(s,r.accessory,r.after)&&same(r.before,r.after)&&ownedScope(s,receipt);
}
void runReparent(const GameContextSnapshot& s,ReparentReceipt* receipt){
    auto o=&receipt->common;
    o->status=1;o->stage=1;o->mode=ASSEMBLY_WRITE;o->count=REPARENT_COUNT;
    if(GetCurrentProcessId()!=HR_TARGET_PID||GetCurrentThreadId()!=HR_TARGET_TID||
       GetTickCount64()>=HR_DEADLINE||o->count<1||o->count>64||
       TRANSFORM_LEVEL!=REPARENT_AUTHORIZED_LEVEL||!code(s,o))return;
    receipt->startedTick=GetTickCount64();receipt->budgetMillis=2000;
    ExecuteTransform(&s,&o->beforePose);
    if(o->beforePose.status||o->beforePose.seh||
       o->beforePose.completed!=TRANSFORM_COUNT||!o->beforePose.sceneUnchanged)return;
    constexpr unsigned groups[]={ASSEMBLY_USAGE_GROUPS};
    for(auto g:groups)reinterpret_cast<void(*)(unsigned)>(s.moduleBase+0x524250)(g);
    diagnoseUndo(s,o);
#if ASSEMBLY_WRITE
    // Same completed-property-record normalization as the existing converter.
    // Active or unrecognized undo work is still refused.
    if(o->undoCount){
        if(o->undoCount!=1||o->undoBase!=o->undoDepth||o->undoFlags||
           !o->undoTarget||!o->undoBefore||o->undoDirty>1||
           o->undoClass!=ptr(s.moduleBase+0x5812cf8)){o->failedValue=307;return;}
        o->undoReserved=1;
        const U transaction=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,bool,bool)>(
            s.moduleBase+0xe827750)(nullptr,false,false));
        if(!transaction)return;
        reinterpret_cast<void(*)(void*)>(s.moduleBase+0xc7bab90)(reinterpret_cast<void*>(transaction));
        unsigned pending=9999;int depth=-1;
        if(!undo(s,pending,depth)||depth!=static_cast<int>(o->undoDepth))return;
        o->undoReserved=2;
        ExecuteTransform(&s,&o->beforePose);
        if(o->beforePose.status||o->beforePose.seh||!o->beforePose.sceneUnchanged)return;
    }
#endif
    unsigned pending=9999;int depth=-1;
    if(!undo(s,pending,depth)){o->failedValue=301;return;}
    struct Request{
        unsigned accessoryId,oldHostId,hostId,modelId;
        TransformVec3 position,scale;
        double rotation[4];
    };
    constexpr Request requests[]={REPARENT_REQUESTS};
    o->stage=2;
    for(unsigned i=0;i<o->count;++i){
        auto& r=receipt->transfers[i];const auto& q=requests[i];
        r.accessoryId=q.accessoryId;r.oldHostId=q.oldHostId;r.hostId=q.hostId;
        r.modelId=q.modelId;r.status=1;
        if(r.oldHostId==r.hostId||r.accessoryId==r.hostId||r.accessoryId==r.oldHostId)return;
        for(unsigned j=0;j<i;++j)if(receipt->transfers[j].accessoryId==r.accessoryId)return;
    }
    for(unsigned i=0;i<o->count;++i){
        if(!inBudget(receipt))return;
        auto& r=receipt->transfers[i];const auto& q=requests[i];
        r.oldHost=findOwner(s,r.oldHostId);r.host=findOwner(s,r.hostId);
        if(!r.oldHost||!r.host||!scenery(s,r.oldHost)||!scenery(s,r.host)){o->failedValue=302;return;}
        if(!r.accessory&&!findRequestedChildren(s,r.oldHost,r.oldHostId,receipt)){
            o->failedValue=303;return;
        }
        U items=0;unsigned children=0;
        if(!r.accessory||!accessories(s,r.accessory,r.childComponent,children,items)||children||
           !accessories(s,r.oldHost,r.oldComponent,r.oldBefore,items)||
           !accessories(s,r.host,r.component,r.newBefore,items)||
           !read(r.oldComponent+0x1c,r.oldComponentId)||!r.oldComponentId||
           !read(r.component+0x1c,r.componentId)||!r.componentId||
           r.oldComponentId==r.componentId||
           !read(r.childComponent+0x48,r.parentBefore)||r.parentBefore!=r.oldComponentId||
           !membership(s,r.host,r.accessory,r.childComponent,false,r.newBefore)){o->failedValue=303;return;}
        r.transform=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,int)>(s.moduleBase+0x867f250)(
            reinterpret_cast<void*>(r.accessory),1));
        AssemblyWorld hostWorld{};
        if(!r.transform||ptr(r.transform)!=ptr(s.moduleBase+0x57c8eb8)||
           ptr(r.transform+0x20)!=r.accessory||!world(s,r.accessory,r.before)||
           !world(s,r.host,hostWorld)||
           std::fabs(hostWorld.scale.x-hostWorld.scale.y)>.0001f||
           std::fabs(hostWorld.scale.x-hostWorld.scale.z)>.0001f){o->failedValue=304;return;}
        double actualQuaternion[4],dot=0;
        quaternion(r.before.rotation,actualQuaternion);
        for(unsigned k=0;k<4;++k)dot+=q.rotation[k]*actualQuaternion[k];
        if(!nearVec(r.before.position,q.position)||!nearVec(r.before.scale,q.scale)||
           std::fabs(dot)<.999999){o->failedValue=306;return;}
        int capacity=static_cast<int>(r.newBefore);
        for(unsigned j=0;j<i;++j){
            if(requests[j].hostId==r.hostId)++capacity;
            if(requests[j].oldHostId==r.hostId)--capacity;
        }
        if(capacity<0||capacity>=999){o->failedValue=305;return;}
        r.after=r.before;r.oldAfter=r.oldBefore;r.newAfter=r.newBefore;
        r.parentAfter=r.parentBefore;r.depthBefore=depth;r.depthAfter=depth;
    }
    receipt->preflightDoneTick=GetTickCount64();
    receipt->baseDepth=depth;receipt->batchDepth=depth;
    o->stage=3;
#if ASSEMBLY_WRITE
    if(!inBudget(receipt))return;
    receipt->batchTransaction=reinterpret_cast<U>(reinterpret_cast<void*(*)(void*,bool,bool)>(
        s.moduleBase+0xe827750)(nullptr,false,false));
    if(!receipt->batchTransaction)return;
    receipt->batchOpened=1;
    if(!ownedScope(s,receipt))return;
#endif
    bool complete=true;
    for(unsigned i=0;i<o->count;++i){
        auto& r=receipt->transfers[i];
#if ASSEMBLY_WRITE
        if(!inBudget(receipt)||!transfer(s,r,receipt)){complete=false;break;}
#endif
        r.status=0;++o->completed;
    }
    receipt->mutationDoneTick=GetTickCount64();
#if ASSEMBLY_WRITE
    // Also close a recognized owned scope after a normal guard/budget failure.
    // An unrecognized scope or SEH leaves an uncertain receipt and blocks replay.
    if(!closeBatch(s,receipt))return;
#endif
    const bool prefix=!complete&&receipt->budgetExceeded&&o->failedValue==309&&
        o->completed>0&&o->completed==o->mutationCalls&&receipt->batchClosed;
    if(!complete&&!prefix)return;
    o->stage=4;
    CaptureGameContextSnapshot(&o->afterScene);
    if(!stableScene(s,o->afterScene))return;
    // Verify every completed transfer again after all callbacks in the batch.
    for(unsigned i=0;i<o->count;++i){
        auto& r=receipt->transfers[i];AssemblyWorld w{};unsigned parent=0;
        if(!world(s,r.accessory,w)||!same(r.before,w)||
           !read(r.childComponent+0x48,parent)||
           parent!=((ASSEMBLY_WRITE&&i<o->completed)?r.componentId:r.oldComponentId))return;
    }
    o->sceneUnchanged=1;o->status=0;o->stage=5;
}
}
void ExecuteReparent(const GameContextSnapshot* s,ReparentReceipt* o) noexcept{
    if(!s||!o)return;
    std::memset(o,0,sizeof(*o));o->common.size=sizeof(*o);o->common.version=3;
    __try{runReparent(*s,o);}__except(EXCEPTION_EXECUTE_HANDLER){
        o->common.seh=GetExceptionCode();o->common.status=2;
    }
    if(o->startedTick)o->finishedTick=GetTickCount64();
}
