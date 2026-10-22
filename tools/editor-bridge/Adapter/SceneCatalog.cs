using System;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

// Read-only scene snapshot over the models already materialized by Resources().
// Must be called after Resources() has populated entityModels/prefabModels.
// Field reads only: no method is invoked on a native object, and nothing is
// sent, serialized, imported, constructed or persisted. Transform members keep
// their native names because their position/rotation/scale roles are not
// established; the vector layout is proven by
// .runtime/editor-bridge/static-entity-research/vector3-native.cs.
internal sealed partial class EditorAdapter
{
    const int SceneEntityLimit = 128;
    const int SceneKind1PrefabLimit = 64;
    static string SceneTransformField => B("hTjiSreIlqL");

    public object SceneCatalogSnapshot()
    {
        var entitySeen = new HashSet<uint>();
        var entityAll = entityModels
            .Select(e => new {id=(uint)Field(Stored(e,B("Qi8iCzKCkTt"))!,B("namiwGPRyPS")), model=e})
            .Where(e => entitySeen.Add(e.id)).ToArray();
        var prefabSeen = new HashSet<uint>();
        var prefabAll = prefabModels
            .Select(p => new {id=(uint)Field(Stored(p,B("atbiBHcMllT"))!,B("namiwGPRyPS")),
                kind=Convert.ToInt32(Stored(p,B("qgriBv1ZZtL"))), model=p})
            .Where(p => prefabSeen.Add(p.id)).ToArray();
        var kind1 = prefabAll.Where(p => p.kind == 1).ToArray();
        return new {ok=true,status="scene-catalog-snapshot-read-only",
            entityTotal=entityAll.Length,entityTruncated=entityAll.Length>SceneEntityLimit,
            entities=entityAll.Take(SceneEntityLimit).Select(e => new {
                id=e.id,name=Stored(e.model,B("WAAiS5WkxlA")),prefabId=Stored(e.model,B("TuuiS94iUgu")),
                prefabIdSource="editor-prefab-association-cache",prefabIdIsTemplateId=false,
                templateId=ReadSceneTemplateId(e.model),templateIdSource="editor-entity-config-reference",
                nativeEntityType=Convert.ToInt32(Stored(e.model,B("yEpiSj6okKa"))),
                nativeInstanceKind=Convert.ToInt32(Stored(e.model,B("d4siSoaFICf"))),
                transform=TransformSnapshot(Field(e.model,SceneTransformField))}).ToArray(),
            prefabTotal=prefabAll.Length,
            prefabKindCounts=prefabAll.GroupBy(p => p.kind).OrderBy(g => g.Key)
                .Select(g => new {nativeKind=g.Key,count=g.Count()}).ToArray(),
            kind1Total=kind1.Length,kind1Truncated=kind1.Length>SceneKind1PrefabLimit,
            kind1Prefabs=kind1.Take(SceneKind1PrefabLimit)
                .Select(p => new {id=p.id,name=Stored(p.model,B("PChiBEHqYMS"))}).ToArray(),
            nativeMethodsInvoked=false,sentToGame=false,persistentSaveVerified=false,playtestVerified=false};
    }

    // The entity's protocol template reference: the entity model holds a reference object and
    // the template id lives on that referenced object. The older build exposed the pair as
    // dmhiSVca7Ew / pgfitPOV3oW; the current build exposes the same pair as
    // JN6Xiq5xY5w / c9hXtzxPgoq, so the legacy names are resolved through the binding profile
    // rather than hardcoded. Raw field reads only: no native getter is invoked, no conversion
    // of the id is attempted, and a zero id stays a zero instead of being reported as absent.
    uint ReadSceneTemplateId(object model) => ReadSceneTemplateIdCore(model, (obj, legacy) => Field(obj, B(legacy)));

    static uint ReadSceneTemplateIdCore(object model, Func<object,string,object> read)
    {
        var reference = read(model, "dmhiSVca7Ew");
        var raw = read(reference, "pgfitPOV3oW");
        if (raw is not uint templateId)
            throw new InvalidOperationException("SCENE_TEMPLATE_ID_TYPE_MISMATCH");
        return templateId;
    }

    // Native entity conversion starts with default(Transform) and only populates this
    // cached field when the optional transform component is present in its input protocol.
    // This field alone cannot establish component presence, freshness or authoritative geometry.
    // Preserve the raw vectors without inferring their roles or validity from zero values.
    object TransformSnapshot(object transform) => new {source="editor-registry-transform-cache",
        authoritative=false,validity="unknown",componentPresenceVerified=false,
        nativeField=SceneTransformField,
        maSidNtJUim=NativeVector(transform,B("maSidNtJUim")),
        MtbidjteDd3=NativeVector(transform,B("MtbidjteDd3")),
        OStidFtjJdR=NativeVector(transform,B("OStidFtjJdR"))};

    object NativeVector(object transform,string field)
    {
        var vector = Field(transform,field);
        var x = (float)Field(vector,B("xYKidoTpamf"));
        var y = (float)Field(vector,B("MDTidUcgOhj"));
        var z = (float)Field(vector,B("LSnidRDCRwE"));
        // A non-finite component would poison the JSON payload, so the whole
        // vector is reported unavailable rather than coerced or dropped.
        if(float.IsNaN(x) || float.IsInfinity(x) || float.IsNaN(y) || float.IsInfinity(y) ||
            float.IsNaN(z) || float.IsInfinity(z))
            return new {nativeField=field,available=false};
        return new {nativeField=field,available=true,xYKidoTpamf=x,MDTidUcgOhj=y,LSnidRDCRwE=z};
    }

    // The editor's materialized registry contains prefab models; Catalog() only ever
    // exposed a hand-filtered slice of it (names containing 平台/方块/立方/石板/木板, capped at
    // 80). That slice is fine for "what does this project use" and useless for "what could I
    // build with", which is what decorating a level needs. This is the same read-only walk
    // with no filter, so the answer comes from the registry rather than from a guess about
    // which names sound decorative.
    //
    // Reads materialized registry models. Shared Resources also invokes its known binding
    // getter and enumerates collections; no game send or serialization path is entered.
    const int PrefabCatalogLimit = 4000;

    public object PrefabCatalog()
    {
        Resources();
        var seen = new HashSet<uint>();
        var items = new List<object>();
        foreach (var model in prefabModels)
        {
            var id = (uint)Field(Stored(model,B("atbiBHcMllT"))!,B("namiwGPRyPS"));
            if (!seen.Add(id)) continue;
            // The prefab carries its own library icon path. That is what makes this catalog
            // usable for choosing what to build with: the icon is the actual artwork, so a
            // decoration can be picked by looking at the art rather than by guessing what
            // 石质路灯 means. Field name read off a real model, same accessor pattern as the
            // name field above.
            items.Add(new {registryId=id, name=Stored(model,B("PChiBEHqYMS")),
                iconPath=Stored(model,B("gTdiBiGNG2a")),
                nativeKind=Convert.ToInt32(Stored(model,B("qgriBv1ZZtL")))});
        }
        var ordered = items.OrderBy(x => (uint)x.GetType().GetProperty("registryId")!.GetValue(x)!).ToArray();
        return new {ok=true, status="prefab-catalog-read-only",
            total=ordered.Length,
            truncated=ordered.Length>PrefabCatalogLimit,
            prefabs=ordered.Take(PrefabCatalogLimit).ToArray(),
            nativeMethodsInvoked=entityModels.Count!=0,
            nativeMethodsInvocationScope="shared Resources reflected EntityBindings getter; collection enumeration disclosed separately",
            resourceReadBehavior=new {existingSingletonLazyValueAccessed=true,
                entityBindingGetterCalls=entityModels.Count,registryAndBindingCollectionsEnumerated=true},
            sentToGame=false,
            persistentSaveVerified=false, playtestVerified=false};
    }

    // Two prefabs tell us the scale convention: 20001875 (通常立方体) occupies exactly one
    // world unit at scale 1, and 20001034 (石质元素立方体) exactly five -- both confirmed
    // against real placed geometry in the saved levels. If some field on the prefab model
    // carries those two numbers, it carries the size of every other prefab too, and a
    // decoration can be built from numbers instead of from guesses about how big a 乔木 is.
    //
    // The id list is fixed rather than a parameter because the bridge's request envelope
    // carries no free-form argument; callers reach it through a fixed op whitelist. The list
    // is therefore exactly "the two known sizes" plus "the objects this project actually
    // intends to place", which is the comparison the question needs.
    //
    // Read-only: bounded field walk over already-materialized models, numeric and string
    // leaves only. Shared Resources getter/collection calls are disclosed below. Unknown
    // model enumerators are not invoked; nothing is sent to the game or serialized.
    static readonly uint[] PrefabFieldCalibration = {
        20001875, // 通常立方体      -- known 1.0 world unit at scale 1 (newdemo tiles)
        20001224, // 木质箱子        -- known 1.0 (newdemo pads)
        20001034, // 石质元素立方体  -- known 5.0 (MVP pads, measured)
        20001001, // 乔木
        20001004, // 灌木
        20001014, // 石质路灯
        20001012, // 石柱
        20001042, // 岩石
        20001030, // 石质地板
        20001047, // 木质围栏
        20001055, // 木质火炬
    };
    const int PrefabFieldRowLimit = PrefabFieldRead.MaxScalarRows;

    public object PrefabFields()
    {
        Resources();
        var perPrefab = new List<object>();
        foreach (var id in PrefabFieldCalibration)
        {
            var model = prefabModels.FirstOrDefault(m => (uint)Field(Stored(m,B("atbiBHcMllT"))!,B("namiwGPRyPS")) == id);
            if (model == null) { perPrefab.Add(new {prefabId=id, found=false}); continue; }
            var read = new PrefabFieldRead();
            read.Read(model);
            perPrefab.Add(new {prefabId=id, found=true, name=Stored(model,B("PChiBEHqYMS")),
                nativeKind=Stored(model,B("qgriBv1ZZtL")), rowCount=read.Rows.Count,
                truncated=read.Truncated,rowLimitReached=read.RowLimitReached,
                depthLimitReached=read.DepthLimitReached,collectionLimitReached=read.CollectionLimitReached,
                fieldReadErrorCount=read.FieldReadErrorCount,collectionReadErrorCount=read.CollectionReadErrorCount,
                bclCollectionEnumerationCount=read.BclCollectionEnumerationCount,
                unknownEnumerableFieldWalkCount=read.UnknownEnumerableFieldWalkCount,
                unknownEnumerableItemsNotEnumerated=read.UnknownEnumerableFieldWalkCount!=0,rows=read.Rows});
        }
        return new {ok=true, status="prefab-fields-read-only", prefabs=perPrefab,
            limits=new {maxDepth=PrefabFieldRead.MaxDepth,maxCollectionItems=PrefabFieldRead.MaxCollectionItems,maxScalarRows=PrefabFieldRowLimit},
            completeModelVerified=false,geometryVerified=false,
            nativeMethodsInvoked=entityModels.Count!=0,
            nativeMethodsInvocationScope="shared Resources reflected EntityBindings getter; collection enumeration disclosed separately",
            resourceReadBehavior=new {existingSingletonLazyValueAccessed=true,
                entityBindingGetterCalls=entityModels.Count,registryAndBindingCollectionsEnumerated=true},
            fieldReadBehavior=new {arbitraryGettersInvoked=false,arbitraryEnumeratorsInvoked=false,
                allowedEnumerableTypes=new[]{"System.Array","exact List<T>","exact Dictionary<K,V>","exact HashSet<T>"},
                unknownEnumerableHandling="instance fields only; logical items not enumerated; marks truncated"},
            sentToGame=false};
    }
}
