using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Read-only, one entity at a time. Resolves ONE entity by registry id, enumerates that
// entity's component collection off the live 7.1 editor model and returns (id, enabled,
// x, y) rows. No native command, no callback, no RPC, no local-model write, no custom
// enumerator and no arbitrary property getter.
//
// The member names below are ACTUAL BeyondEditor 7.1.0 names harvested from the pinned PE
// metadata dump (metadata-7.1.json, sha256 565DDA.../MVID 39031639-..., the same build the
// profile pins). They are deliberately kept as typed 71 consts with a member contract,
// exactly the AuthorEntityTag / EntityFactionProbe idiom, instead of being appended to
// EditorBindingProfile.Generated.cs: a wrong contract in the profile fails EVERY operation
// on the bridge closed (EditorBindingProfile.cs:314-327 ValidateContracts), while a wrong
// const here fails only this one op. The legacy names in the trailing comments are the
// resolved-corpus names the mining report cites; the two naming spaces are not the same.
internal sealed partial class EditorAdapter
{
    const string ComponentCollectionType71     = "vkNQubXLXRds8Ypg8CDv.WupssAXLwY5NGCQQMQWk`1"; // rgfCjhijuAbCoKxWU8Lu`1
    const string ComponentCollectionItems71    = "o26XLglnP6U";                                    // XnBijZjw7wg (private List<T>; profile maps this string identity)
    const string EntityComponentsField71       = "EDuXiXtiyvl";                                    // mUwiSNg4POZ
    const string ComponentType71               = "tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq";     // LudM06iCRNk4iFkwqKIW
    const string ComponentIdField71            = "OgoXdqFmidJ";                                    // OTQiCVjSfFs (boxed uint)
    const string ComponentEnabledField71       = "gKyXdGplIdw";                                    // fydiCJQHm3O (boxed bool)
    const string ComponentXField71             = "rNIXd7Mpstc";                                    // d8LiCZa1gcE (boxed double)
    const string ComponentYField71             = "f3VXda70g6Z";                                    // so7iCroxZbp (boxed double)
    const string BoxedValueType71              = "sGSkeTXZnJ86i9h8AAF9.MoivF7XZA3MetiaLJVSU`1"; // t7crdXiRQQTsF520oNMA`1
    // A component row is (componentId, enabled, x, y) and the editor set is small; a
    // collection bigger than this is malformed, not merely long, so it refuses instead of
    // truncating -- a truncated list must never read back as an authoritative component set.
    const int ComponentCap = 1024;

    sealed class ComponentModel
    {
        internal required Type ComponentType;
        internal required Type CollectionType;
        internal required Type ItemsType;
        internal required FieldInfo Collection;   // entity -> component collection
        internal required FieldInfo Items;        // collection -> List<component>
        internal required FieldInfo Id, Enabled, X, Y; // component -> boxed value handle
    }

    // Refuses unknown or duplicate request fields before any reflection runs. Only the
    // entity id is accepted; the probe never takes a target, a name, or a path.
    internal static void ValidateEntityComponentProbe(JsonElement request)
    {
        var allowed = new HashSet<string> { "id", "op", "nonce", "entityId" };
        var seen = new HashSet<string>();
        foreach (var property in request.EnumerateObject())
            if (!allowed.Contains(property.Name) || !seen.Add(property.Name))
                throw new InvalidOperationException("COMPONENT_PROBE_UNKNOWN_OR_DUPLICATE_FIELD:" + property.Name);
        if (!request.TryGetProperty("entityId", out var value) || !value.TryGetUInt32(out var id) || id == 0)
            throw new InvalidOperationException("COMPONENT_PROBE_REQUIRED_UINT:entityId");
    }

    // Closed 7.1 metadata contract, checked after Editor() has already enforced the full
    // source-DLL SHA + MVID gate. Every expected FieldType is a concrete closed type, so a
    // build that renamed or re-typed any of them refuses here rather than reading garbage.
    static ComponentModel ComponentModelContract(Assembly editor)
    {
        var entity = editor.GetType(CrudEntityType, true) ?? throw new InvalidOperationException("COMPONENT_ENTITY_TYPE_MISSING");
        var component = editor.GetType(ComponentType71, true) ?? throw new InvalidOperationException("COMPONENT_TYPE_MISSING");
        var collection = editor.GetType(ComponentCollectionType71, true) ?? throw new InvalidOperationException("COMPONENT_COLLECTION_TYPE_MISSING");
        var boxed = editor.GetType(BoxedValueType71, true) ?? throw new InvalidOperationException("COMPONENT_BOXED_TYPE_MISSING");
        if (!collection.IsGenericTypeDefinition || collection.GetGenericArguments().Length != 1 ||
            !boxed.IsGenericTypeDefinition || boxed.GetGenericArguments().Length != 1)
            throw new InvalidOperationException("COMPONENT_GENERIC_ARITY_MISMATCH");
        var collectionOfComponent = collection.MakeGenericType(component);
        var itemsType = typeof(List<>).MakeGenericType(component);
        FieldInfo Exact(Type owner, string name, Type expected)
        {
            var field = owner.GetField(name, Fields | BindingFlags.DeclaredOnly);
            if (field == null || field.IsStatic || field.FieldType != expected)
                throw new InvalidOperationException("COMPONENT_MEMBER_CONTRACT_MISMATCH:" + owner.Name + "." + name);
            return field;
        }
        var collectionField = Exact(entity, EntityComponentsField71, collectionOfComponent);
        var itemsField = Exact(collectionOfComponent, ComponentCollectionItems71, itemsType);
        var idField = Exact(component, ComponentIdField71, boxed.MakeGenericType(typeof(uint)));
        var enabledField = Exact(component, ComponentEnabledField71, boxed.MakeGenericType(typeof(bool)));
        var xField = Exact(component, ComponentXField71, boxed.MakeGenericType(typeof(double)));
        var yField = Exact(component, ComponentYField71, boxed.MakeGenericType(typeof(double)));
        // The boxed handle's value member name is fixed for every T; validate it once.
        Exact(boxed.MakeGenericType(typeof(uint)), B("VpIiRZgdEln"), typeof(uint));
        return new ComponentModel
        {
            ComponentType = component, CollectionType = collectionOfComponent, ItemsType = itemsType,
            Collection = collectionField, Items = itemsField,
            Id = idField, Enabled = enabledField, X = xField, Y = yField,
        };
    }

    // One entity, by registry id. 0 matches and an id that names two distinct entity models
    // are both refusals with a named code; the registry walk (ReadCrudEntities) is what
    // proves id-uniqueness, so its conflict code is re-labelled here.
    CrudEntity ResolveComponentEntity(uint entityId)
    {
        Dictionary<uint, CrudEntity> entities;
        try { entities = ReadCrudEntities(); }
        catch (InvalidOperationException ex) when (ex.Message == "CRUD_DUPLICATE_ENTITY_ID_CONFLICT")
        { throw new InvalidOperationException("COMPONENT_ENTITY_ID_NOT_UNIQUE"); }
        if (!entities.TryGetValue(entityId, out var entity))
            throw new InvalidOperationException("COMPONENT_ENTITY_NOT_FOUND");
        return entity;
    }

    // The component's value lives in a boxed handle; read the handle's own value member. The
    // handle's generic instantiation differs per field (uint/bool/double), so the FieldInfo
    // is taken from the boxed instance's runtime type, never from one pruned instantiation.
    // A null handle or a null value is a distinct, named refusal -- never a default 0/false.
    static object ComponentValue(object component, FieldInfo handle)
    {
        var boxed = handle.GetValue(component) ?? throw new InvalidOperationException("COMPONENT_FIELD_NOT_MATERIALIZED:" + handle.Name);
        var value = boxed.GetType().GetField(B("VpIiRZgdEln"), Fields | BindingFlags.DeclaredOnly)
            ?? throw new InvalidOperationException("COMPONENT_VALUE_MEMBER_MISSING:" + handle.Name);
        return value.GetValue(boxed) ?? throw new InvalidOperationException("COMPONENT_FIELD_VALUE_NULL:" + handle.Name);
    }

    public object EntityComponentProbe(JsonElement request)
    {
        ValidateEntityComponentProbe(request);
        var entityId = request.GetProperty("entityId").GetUInt32();
        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");
        var target = ResolveComponentEntity(entityId);
        var model = ComponentModelContract(Editor());
        // Re-resolve immediately before reading so a registry change mid-request cannot leave
        // us reading components off a stale handle.
        var fresh = ResolveComponentEntity(entityId);
        if (!SameCrudIdentity(target, fresh))
            throw new InvalidOperationException("COMPONENT_ENTITY_CHANGED_DURING_PREPARATION");
        var raw = model.Collection.GetValue(fresh.Model)
            ?? throw new InvalidOperationException("COMPONENT_COLLECTION_NOT_MATERIALIZED");
        if (raw.GetType() != model.CollectionType)
            throw new InvalidOperationException("COMPONENT_COLLECTION_TYPE_MISMATCH");
        if (model.Items.GetValue(raw) is not IList items || items.GetType() != model.ItemsType)
            throw new InvalidOperationException("COMPONENT_ITEMS_TYPE_MISMATCH");
        if (items.Count > ComponentCap)
            throw new InvalidOperationException("COMPONENT_COLLECTION_CAP_EXCEEDED");
        var rows = new List<object>(items.Count);
        foreach (var item in items)
        {
            if (item == null || item.GetType() != model.ComponentType)
                throw new InvalidOperationException("COMPONENT_ELEMENT_TYPE_MISMATCH");
            rows.Add(new
            {
                id = (uint)ComponentValue(item, model.Id),
                enabled = (bool)ComponentValue(item, model.Enabled),
                x = (double)ComponentValue(item, model.X),
                y = (double)ComponentValue(item, model.Y),
            });
        }
        return new
        {
            ok = true,
            status = "entity-components-editor-model-read-only",
            entityId,
            entityName = Stored(fresh.Model, B("WAAiS5WkxlA")),
            componentType = ComponentType71,
            componentCount = rows.Count,
            components = rows.ToArray(),
            componentIdSpace = "editor-enum-value-or-native-index-UNVERIFIED",
            nativeMutationInvoked = false,
            localModelWritten = false,
            sentToGame = false,
            gameEffectVerified = false,
            persistentSaveVerified = false,
        };
    }
}
