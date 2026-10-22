using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;
internal sealed partial class EditorAdapter
{
    const string FactionModel71="fgsmUXXt93YjoS00CsAk.KeuK67XtVRpNXTQBpRTg";
    const string FactionDirectory71="y6jlRGXtWYAydsQXQ38q.Qb1Q0gXtl2xwUWZDqnKH";
    const string FactionPolicy71="E4chM0XF4DxTkANMrQ9I.STkmw4XFJT9BrkDCxFbU";
    const string FactionParent71="xAHHdTXFDUuCPGRx5nUE.LBdbe2XczO4J38PQ2iYH";
    const string FactionPolicyWrapper71="Ss3WKuXZVPQoP5I07YO3.oaMXDuXZ6XQHCebtV4iO`1";
    const string EntityKind71="fWAOEwZOfnXEj7Ot5yS9.OEMSxbZOTRB79YVvftOi";
    const string UIntWrapper71="sGSkeTXZnJ86i9h8AAF9.MoivF7XZA3MetiaLJVSU`1";
    sealed class FactionExperiment
    {
        internal required string ProbeId;
        internal required CrudEntity Target;
        internal required uint Original, Selected;
        internal required object Directory, Parent, PolicyWrapper, Policy, SelectedModel;
        internal object? OriginalModel;
        internal bool SetSpent, RestoreSpent;
    }
    FactionExperiment? factionExperiment;

    uint FactionUInt(object owner,string name)
    {
        var wrapper=Editor().GetType(UIntWrapper71,true)!.MakeGenericType(typeof(uint));
        var field=owner.GetType().GetField(name,Fields|BindingFlags.DeclaredOnly);
        var valueField=wrapper.GetField("PIWXZgk5Tyr",Fields|BindingFlags.DeclaredOnly);
        if(field==null||field.IsStatic||field.FieldType!=wrapper||valueField==null||valueField.FieldType!=typeof(uint)||valueField.IsStatic)
            throw new InvalidOperationException("FACTION_UINT_CONTRACT_MISMATCH");
        var value=field.GetValue(owner)??throw new InvalidOperationException("FACTION_UINT_NOT_MATERIALIZED");
        if(value.GetType()!=wrapper)throw new InvalidOperationException("FACTION_UINT_RUNTIME_TYPE_MISMATCH");
        return (uint)valueField.GetValue(value)!;
    }

    // Fixed tags are the actual UI Registry contracts. Read only existing node maps;
    // never call the parent/policy getters: they allocate when storage is absent.
    object FactionTagOwner(object root,uint first,uint second,Type ownerType)
    {
        var node=root;
        foreach(var segment in new[]{first,second}) {
            var children=(IDictionary)Field(node,B("pIxYiE5REC8"));
            if(!children.Contains(segment)||children[segment] is not object next)
                throw new InvalidOperationException("FACTION_CURRENT_PROVIDERS_NOT_MATERIALIZED");
            if(next.GetType()!=root.GetType())throw new InvalidOperationException("FACTION_REGISTRY_NODE_TYPE_MISMATCH");
            node=next;
        }
        var items=(IDictionary)Field(node,B("JkmYibSuDZr"));
        if(items.Count==0)throw new InvalidOperationException("FACTION_CURRENT_PROVIDERS_NOT_MATERIALIZED");
        if(items.Count!=1)throw new InvalidOperationException("FACTION_TAG_OWNER_NOT_UNIQUE");
        foreach(DictionaryEntry row in items) {
            if(row.Key is not uint||row.Value==null||row.Value.GetType()!=ownerType)
                throw new InvalidOperationException("FACTION_TAG_OWNER_TYPE_MISMATCH");
            return row.Value;
        }
        throw new InvalidOperationException("FACTION_CURRENT_PROVIDERS_NOT_MATERIALIZED");
    }

    object FactionPolicyStorage(object parent,Type policyType,out object wrapper)
    {
        var wrapperType=Editor().GetType(FactionPolicyWrapper71,true)!.MakeGenericType(policyType);
        var slot=parent.GetType().GetField("v98XFotHeK2",Fields|BindingFlags.DeclaredOnly);
        var storage=wrapperType.GetField("t9gXZ38FrdQ",Fields|BindingFlags.DeclaredOnly);
        if(slot==null||slot.IsStatic||slot.FieldType!=wrapperType||storage==null||storage.IsStatic||storage.FieldType!=policyType)
            throw new InvalidOperationException("FACTION_POLICY_STORAGE_CONTRACT_MISMATCH");
        wrapper=slot.GetValue(parent)??throw new InvalidOperationException("FACTION_POLICY_WRAPPER_NOT_MATERIALIZED");
        if(wrapper.GetType()!=wrapperType)throw new InvalidOperationException("FACTION_POLICY_WRAPPER_RUNTIME_TYPE_MISMATCH");
        var policy=storage.GetValue(wrapper)??throw new InvalidOperationException("FACTION_POLICY_NOT_MATERIALIZED");
        if(policy.GetType()!=policyType)throw new InvalidOperationException("FACTION_POLICY_RUNTIME_TYPE_MISMATCH");
        return policy;
    }

    (object Directory,object Parent,object Wrapper,object Policy,Dictionary<uint,object> Definitions,uint[] Allowed) FactionData(int entityType)
    {
        var editor=Editor();var directoryType=editor.GetType(FactionDirectory71,true)!;var policyType=editor.GetType(FactionPolicy71,true)!;
        var root=Field(ExistingSingleton(editor,Registry),B("bwbixDw3yob"));
        var directory=FactionTagOwner(root,10003,50011,directoryType);
        var parent=FactionTagOwner(root,10005,53100,editor.GetType(FactionParent71,true)!);
        var policy=FactionPolicyStorage(parent,policyType,out var wrapper);
        var modelType=editor.GetType(FactionModel71,true)!;
        var map=Field(Field(directory,"OMrXtSFVJ69"),"MZXXXPVwoVh");
        if(map.GetType()!=typeof(Dictionary<,>).MakeGenericType(typeof(uint),modelType))throw new InvalidOperationException("FACTION_DIRECTORY_MAP_TYPE_MISMATCH");
        var definitions=new Dictionary<uint,object>();
        foreach(DictionaryEntry row in (IDictionary)map) {
            if(definitions.Count>=1024||row.Key is not uint id||id==0||row.Value==null||row.Value.GetType()!=modelType||FactionUInt(row.Value,"Hq5XtFmokMF")!=id)
                throw new InvalidOperationException("FACTION_DEFINITION_INVALID");
            definitions.Add(id,row.Value);
        }
        var kind=editor.GetType(EntityKind71,true)!;
        if(!kind.IsEnum||Enum.GetUnderlyingType(kind)!=typeof(int))throw new InvalidOperationException("FACTION_ENTITY_KIND_TYPE_MISMATCH");
        var method=policyType.GetMethod("i0yXFsgOxqA",Fields|BindingFlags.DeclaredOnly,null,new[]{kind,typeof(List<uint>).MakeByRefType()},null);
        if(method==null||method.IsStatic||method.ReturnType!=typeof(bool))throw new InvalidOperationException("FACTION_POLICY_METHOD_CONTRACT_MISMATCH");
        object?[] args={Enum.ToObject(kind,entityType),null};
        if(method.Invoke(policy,args) is not true||args[1] is not List<uint> allowed||allowed.GetType()!=typeof(List<uint>)||allowed.Count>1024||allowed.Distinct().Count()!=allowed.Count)
            throw new InvalidOperationException("FACTION_TYPE_POLICY_UNAVAILABLE");
        return (directory,parent,wrapper,policy,definitions,allowed.ToArray());
    }

    (CrudExperiment Probe,CrudEntity Target) FactionOwnedTarget()
    {
        var current=CheckCrudTarget();
        if(current.Probe.DeleteSpent||current.Target.EntityType!=1402||current.Target.InstanceKind!=0||EntityBindings(current.Target.Model).Length!=0)
            throw new InvalidOperationException("FACTION_OWNED_UNBOUND_TARGET_REQUIRED");
        return current;
    }

    public object EntityFactionProbe(string action)
    {
        if(action!="inspect"&&action!="set"&&action!="restore")throw new InvalidOperationException("FACTION_ACTION_UNSUPPORTED");
        var current=FactionOwnedTarget();var observed=FactionUInt(current.Target.Model,"wCGXiPk8NaS");var data=FactionData(current.Target.EntityType);
        if(factionExperiment==null) {
            if(action!="inspect")throw new InvalidOperationException("FACTION_INSPECT_REQUIRED");
            if(observed!=0&&!data.Definitions.ContainsKey(observed))throw new InvalidOperationException("FACTION_ORIGINAL_DEFINITION_MISSING");
            var next=data.Allowed.Where(id=>id!=0&&id!=observed&&data.Definitions.ContainsKey(id)).OrderBy(id=>id).FirstOrDefault();
            if(next==0)throw new InvalidOperationException("FACTION_NO_DISTINCT_ALLOWED_DEFINITION");
            factionExperiment=new FactionExperiment{ProbeId=current.Probe.Id,Target=current.Target,Original=observed,Selected=next,
                Directory=data.Directory,Parent=data.Parent,PolicyWrapper=data.Wrapper,Policy=data.Policy,SelectedModel=data.Definitions[next],OriginalModel=observed==0?null:data.Definitions[observed]};
        }
        var probe=factionExperiment;
        if(probe.ProbeId!=current.Probe.Id||!SameCrudIdentity(probe.Target,current.Target)||!ReferenceEquals(probe.Directory,data.Directory)||!ReferenceEquals(probe.Parent,data.Parent)||!ReferenceEquals(probe.PolicyWrapper,data.Wrapper)||!ReferenceEquals(probe.Policy,data.Policy)||
           !data.Definitions.TryGetValue(probe.Selected,out var definition)||!ReferenceEquals(definition,probe.SelectedModel)||!data.Allowed.Contains(probe.Selected)||
           (probe.Original!=0&&(!data.Definitions.TryGetValue(probe.Original,out var originalModel)||!ReferenceEquals(originalModel,probe.OriginalModel)||!data.Allowed.Contains(probe.Original))))
            throw new InvalidOperationException("FACTION_TARGET_OR_POLICY_CHANGED");
        if(action=="inspect")return new {ok=true,status="entity-faction-editor-model-read-only",probeId=probe.ProbeId,entityId=current.Target.Key.Id,
            originalFaction=probe.Original,selectedFaction=probe.Selected,observedFaction=observed,
            setAttempted=probe.SetSpent,restoreAttempted=probe.RestoreSpent,
            selectedObserved=probe.SetSpent&&observed==probe.Selected,originalObserved=observed==probe.Original,
            readbackScope="auxiliary-editor-model; not a game acknowledgement",localModelWritten=false,gameEffectVerified=false,persistentSaveVerified=false};
        bool restore=action=="restore";
        if(restore?probe.RestoreSpent||!probe.SetSpent:probe.SetSpent)throw new InvalidOperationException("FACTION_ATTEMPT_ALREADY_SPENT_OR_SET_REQUIRED");
        var expected=restore?probe.Selected:probe.Original;var requested=restore?probe.Original:probe.Selected;
        if(observed!=expected)throw new InvalidOperationException("FACTION_SOURCE_READBACK_REQUIRED");
        var manager=CrudContext().Manager;
        if(!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"),Fields)!.Invoke(manager,new object[]{false})!)throw new InvalidOperationException("EDITOR_NOT_READY");
        var param=Editor().GetType(Param,true)!;
        var uintFactory=param.GetMethod(B("bKliA0tj1p1"),BindingFlags.Public|BindingFlags.Static|BindingFlags.DeclaredOnly,null,new[]{typeof(uint)},null);
        if(uintFactory==null||uintFactory.ReturnType!=param)throw new InvalidOperationException("FACTION_UINT_FACTORY_CONTRACT_MISMATCH");
        var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        args.Add(uintFactory.Invoke(null,new object[]{current.Target.Key.Id}));args.Add(uintFactory.Invoke(null,new object[]{requested}));
        var producer=ExistingSingleton(Editor(),Producer);
        var fresh=FactionOwnedTarget();var freshData=FactionData(fresh.Target.EntityType);
        if(fresh.Probe.Id!=probe.ProbeId||!SameCrudIdentity(current.Target,fresh.Target)||FactionUInt(fresh.Target.Model,"wCGXiPk8NaS")!=expected||
           !ReferenceEquals(freshData.Directory,probe.Directory)||!ReferenceEquals(freshData.Parent,probe.Parent)||!ReferenceEquals(freshData.Wrapper,probe.PolicyWrapper)||!ReferenceEquals(freshData.Policy,probe.Policy)||!freshData.Allowed.Contains(probe.Selected)||
           !freshData.Definitions.TryGetValue(probe.Selected,out var freshModel)||!ReferenceEquals(freshModel,probe.SelectedModel)||
           (requested!=0&&!freshData.Allowed.Contains(requested))||
           (probe.Original!=0&&(!freshData.Definitions.TryGetValue(probe.Original,out var freshOriginal)||!ReferenceEquals(freshOriginal,probe.OriginalModel))))throw new InvalidOperationException("FACTION_PRE_DISPATCH_CHANGED");
        if(restore)probe.RestoreSpent=true;else probe.SetSpent=true; // consumed also on exception/timeout
        producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,new object?[]{"beyondEditObjService","ModifyFactionForEditObj",null,args});
        return new {ok=true,status="entity-faction-requested-readback-pending",probeId=probe.ProbeId,entityId=current.Target.Key.Id,before=expected,requestedFaction=requested,
            restore,invokedUtc=DateTime.UtcNow,retryAllowed=false,localModelWritten=false,gameEffectVerified=false,persistentSaveVerified=false};
    }
}
