using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// One new self-owned CRUD entity only. Uses the real 7.1 outbound tag command;
// no local model setters, arbitrary target, callback, RPC or reflection arguments.
internal sealed partial class EditorAdapter
{
    const string TagDefinitionType71="Jt1m77XtPYMbFDIUFpJy.jDg3YOXtpW5eRF0HnQkO";
    const string TagListType71="IP7RdoXwe26RM9Pnjq3V.qknVfrXwms8uvpf8GYF6`1";
    const string TagListField71="K07Xiow3cj5", TagItemsField71="i4gXwUOgjxk";
    const string IntParamFactory71="ciuLb5no9QV";
    readonly HashSet<string> authorEntityTagAttempts=new(StringComparer.Ordinal);
    sealed record EntityTagDefinition(uint Id, object Model, string Name);

    internal static void ValidateAuthorEntityTag(JsonElement request)
    {
        string S(string key)=>request.TryGetProperty(key,out var v)&&v.ValueKind==JsonValueKind.String?v.GetString()!:throw new InvalidOperationException("ENTITY_TAG_REQUIRED_STRING:"+key);
        uint U(string key)=>request.TryGetProperty(key,out var v)&&v.TryGetUInt32(out var n)&&n!=0?n:throw new InvalidOperationException("ENTITY_TAG_REQUIRED_UINT:"+key);
        var action=S("action");
        if(action!="inspect"&&action!="set")throw new InvalidOperationException("ENTITY_TAG_ACTION_UNSUPPORTED");
        var allowed=new HashSet<string>{"id","op","nonce","action","probeId","entityId"};
        if(action=="set")allowed.UnionWith(new[]{"tagId","selected","expectedTagsSha256"});
        var seen=new HashSet<string>();
        foreach(var p in request.EnumerateObject())if(!allowed.Contains(p.Name)||!seen.Add(p.Name))throw new InvalidOperationException("ENTITY_TAG_UNKNOWN_OR_DUPLICATE_FIELD:"+p.Name);
        if(!Guid.TryParseExact(S("probeId"),"N",out _))throw new InvalidOperationException("ENTITY_TAG_PROBE_ID_INVALID");
        U("entityId");
        if(action=="set") {
            if(U("tagId")>int.MaxValue)throw new InvalidOperationException("ENTITY_TAG_ID_OUTSIDE_INT32");
            if(!request.TryGetProperty("selected",out var v)||(v.ValueKind!=JsonValueKind.True&&v.ValueKind!=JsonValueKind.False))throw new InvalidOperationException("ENTITY_TAG_REQUIRED_BOOL:selected");
            var sha=S("expectedTagsSha256");
            if(sha.Length!=64||sha.Any(c=>!((c>='0'&&c<='9')||(c>='a'&&c<='f'))))throw new InvalidOperationException("ENTITY_TAG_BASELINE_HASH_INVALID");
        }
    }

    static string EntityTagsHash(IEnumerable<int> tags)
        => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join(",",tags.OrderBy(x=>x).Select(x=>x.ToString(CultureInfo.InvariantCulture)))))).ToLowerInvariant();

    // Additional closed 7.1 metadata contracts, checked after Editor() has already
    // enforced the full source-DLL SHA/MVID gate. Never discover a writable member.
    static (FieldInfo Tags, FieldInfo Items, MethodInfo IntParam) EntityTagMembers(Assembly editor,Type entityType,Type param)
    {
        var list=editor.GetType(TagListType71,true)!.MakeGenericType(typeof(int));
        var tags=entityType.GetField(TagListField71,Fields|BindingFlags.DeclaredOnly);
        var items=list.GetField(TagItemsField71,Fields|BindingFlags.DeclaredOnly);
        var factory=param.GetMethod(IntParamFactory71,BindingFlags.Public|BindingFlags.Static|BindingFlags.DeclaredOnly,null,new[]{typeof(int)},null);
        if(tags==null||tags.FieldType!=list||tags.IsStatic||items==null||items.FieldType!=typeof(List<int>)||items.IsStatic||factory==null||factory.ReturnType!=param)
            throw new InvalidOperationException("ENTITY_TAG_NATIVE_MEMBER_CONTRACT_MISMATCH");
        return (tags,items,factory);
    }

    static int[] EntityTagValues(object entity,FieldInfo tags,FieldInfo items)
    {
        var collection=tags.GetValue(entity)??throw new InvalidOperationException("ENTITY_TAG_COLLECTION_NOT_MATERIALIZED");
        if(items.GetValue(collection) is not List<int> values||values.GetType()!=typeof(List<int>))throw new InvalidOperationException("ENTITY_TAG_ITEMS_TYPE_MISMATCH");
        if(values.Count>1024||values.Any(x=>x<=0)||values.Distinct().Count()!=values.Count)throw new InvalidOperationException("ENTITY_TAG_ITEMS_INVALID");
        return values.ToArray(); // exact BCL list, never execute a custom enumerator
    }

    Dictionary<uint,EntityTagDefinition> EntityTagDefinitions(Assembly editor)
    {
        var definitionType=editor.GetType(TagDefinitionType71,true)!;
        var root=Field(ExistingSingleton(editor,Registry),B("bwbixDw3yob"));
        var rows=new Dictionary<uint,EntityTagDefinition>();int nodes=0,slots=0;
        void Visit(object node,int depth) {
            if(++nodes>4096||depth>6)throw new InvalidOperationException("ENTITY_TAG_REGISTRY_LIMIT");
            foreach(DictionaryEntry entry in (IDictionary)Field(node,B("JkmYibSuDZr"))) {
                if(++slots>50000)throw new InvalidOperationException("ENTITY_TAG_REGISTRY_SLOT_LIMIT");
                var model=entry.Value!;if(model.GetType()!=definitionType)continue;
                var key=ReadCrudKey(model);
                if(entry.Key is not uint id||id!=key.Id||id==0||id>int.MaxValue||key.Category0!=10003||key.Category1!=50013)
                    throw new InvalidOperationException("ENTITY_TAG_DEFINITION_IDENTITY_MISMATCH");
                var name=Stored(model,B("WAAiS5WkxlA")) as string??throw new InvalidOperationException("ENTITY_TAG_DEFINITION_NAME_MISSING");
                if(rows.TryGetValue(id,out var old)&&!ReferenceEquals(old.Model,model))throw new InvalidOperationException("ENTITY_TAG_DEFINITION_IDENTITY_CONFLICT");
                rows[id]=new(id,model,name);
            }
            foreach(DictionaryEntry child in (IDictionary)Field(node,B("pIxYiE5REC8")))Visit(child.Value!,depth+1);
        }
        Visit(root,0);return rows;
    }

    public object AuthorEntityTag(JsonElement request)
    {
        ValidateAuthorEntityTag(request);
        var requestedProbe=request.GetProperty("probeId").GetString()!;var entityId=request.GetProperty("entityId").GetUInt32();
        var (probe,target)=CheckCrudTarget();
        if(probe.Id!=requestedProbe||target.Key.Id!=entityId||probe.DeleteSpent)throw new InvalidOperationException("ENTITY_TAG_OWNED_TARGET_MISMATCH");
        var editor=Editor();var param=editor.GetType(Param,true)!;
        var members=EntityTagMembers(editor,editor.GetType(CrudEntityType,true)!,param);
        var before=EntityTagValues(target.Model,members.Tags,members.Items);
        var definitions=EntityTagDefinitions(editor);
        var beforeSha=EntityTagsHash(before);
        if(request.GetProperty("action").GetString()=="inspect")return new {ok=true,status="entity-tags-editor-model-read-only",probeId=probe.Id,entityId,tags=before,tagsSha256=beforeSha,
            definitionCount=definitions.Count,definitionsTruncated=definitions.Count>64,
            definitions=definitions.Values.OrderBy(x=>x.Id).Take(64).Select(x=>new {tagId=x.Id,name=x.Name}).ToArray(),
            nativeMutationInvoked=false,localModelWritten=false,gameEffectVerified=false,persistentSaveVerified=false};
        var tagId=request.GetProperty("tagId").GetUInt32();var selected=request.GetProperty("selected").GetBoolean();
        if(request.GetProperty("expectedTagsSha256").GetString()!=beforeSha)throw new InvalidOperationException("ENTITY_TAG_BASELINE_CHANGED");
        if(!definitions.TryGetValue(tagId,out var definition))throw new InvalidOperationException("ENTITY_TAG_DEFINITION_NOT_FOUND");
        var attempt=probe.Id+":"+entityId+":"+tagId+":"+selected;
        if(authorEntityTagAttempts.Contains(attempt))throw new InvalidOperationException("ENTITY_TAG_MUTATION_ALREADY_ATTEMPTED");
        if(before.Contains((int)tagId)==selected && authorEntityTagAttempts.Contains(probe.Id+":"+entityId+":"+tagId+":"+(!selected)))
            throw new InvalidOperationException("ENTITY_TAG_OPPOSITE_ATTEMPT_READBACK_PENDING");
        if(before.Contains((int)tagId)==selected)return new {ok=true,status="entity-tag-already-matches-editor-model",probeId=probe.Id,entityId,tagId,selected,tags=before,tagsSha256=beforeSha,
            nativeMutationInvoked=false,localModelWritten=false,gameEffectVerified=false,persistentSaveVerified=false};
        if(authorEntityTagAttempts.Count>=16)throw new InvalidOperationException("ENTITY_TAG_LEASE_MUTATION_LIMIT");
        var manager=CrudContext().Manager;
        if(!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"),Fields)!.Invoke(manager,new object[]{false})!)throw new InvalidOperationException("EDITOR_NOT_READY");
        var args=(IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        object Wrap(string method,object data)=>param.GetMethod(B(method),BindingFlags.Public|BindingFlags.Static)!.Invoke(null,new[]{data})!;
        args.Add(Wrap("bKliA0tj1p1",entityId));args.Add(members.IntParam.Invoke(null,new object[]{(int)tagId})!);args.Add(Wrap("h8diA3iOGmJ",selected));
        var producer=ExistingSingleton(editor,Producer);
        var fresh=CheckCrudTarget();
        if(fresh.Probe.Id!=probe.Id||!SameCrudIdentity(target,fresh.Target)||fresh.Probe.DeleteSpent||EntityTagsHash(EntityTagValues(fresh.Target.Model,members.Tags,members.Items))!=beforeSha)
            throw new InvalidOperationException("ENTITY_TAG_TARGET_CHANGED_DURING_PREPARATION");
        var freshDefinition=EntityTagDefinitions(editor);
        if(!freshDefinition.TryGetValue(tagId,out var now)||!ReferenceEquals(now.Model,definition.Model))throw new InvalidOperationException("ENTITY_TAG_DEFINITION_CHANGED_DURING_PREPARATION");
        authorEntityTagAttempts.Add(attempt); // consumed even if native send throws
        producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(producer,new object?[]{"beyondEditObjService","ModifyEditobjTag",null,args});
        return new {ok=true,status="entity-tag-requested-readback-pending",probeId=probe.Id,entityId,tagId,selected,beforeTags=before,beforeTagsSha256=beforeSha,
            nativeMutationInvoked=true,localModelWritten=false,retryAllowed=false,gameEffectVerified=false,persistentSaveVerified=false};
    }
}
