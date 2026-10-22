using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// This WPF bridge exposes cached inspection only. The proven 7.1 numeric-panel
// transaction belongs to the game process, not this editor model. Production
// transform inspection/writes use tools/entity-transform/cli.py (action 13),
// including full before-pose checks, native undo/dirty notification and readback.
// Keep this adapter explicit so callers never mistake a cached-model field write
// for a persisted native edit. See tools/entity-transform/README.md.
internal sealed partial class EditorAdapter
{
    // Entity transform field and its three cached vectors, resolved through the binding profile
    // (see SceneCatalog.cs:18/71). Roles of the three vectors are NOT established, so they are
    // reported under their native names and never re-labelled as position/rotation/scale.
    static string TransformField => SceneTransformField;
    const string TransformWriteBlocker = "TRANSFORM_NATIVE_ROUTE_REQUIRED:author.py entity-transform";

    // Strict envelope, in the shape of AuthorEntityTag.ValidateAuthorEntityTag: unknown or
    // duplicate fields and malformed numbers are refused BEFORE any native call.
    internal static void ValidateEntityTransform(JsonElement request)
    {
        var action = request.TryGetProperty("action", out var actionValue) && actionValue.ValueKind == JsonValueKind.String
            ? actionValue.GetString()! : "inspect";
        if (action != "inspect" && action != "set") throw new InvalidOperationException("TRANSFORM_ACTION_UNSUPPORTED");
        var allowed = new HashSet<string> { "id", "op", "nonce", "action", "entityId" };
        if (action == "set") allowed.UnionWith(new[] { "position", "rotation", "scale", "positionSpace", "rotationUnit" });
        var seen = new HashSet<string>();
        foreach (var property in request.EnumerateObject())
            if (!allowed.Contains(property.Name) || !seen.Add(property.Name))
                throw new InvalidOperationException("TRANSFORM_UNKNOWN_OR_DUPLICATE_FIELD:" + property.Name);
        if (!request.TryGetProperty("entityId", out var idValue) || !idValue.TryGetUInt32(out var entityId) || entityId == 0)
            throw new InvalidOperationException("TRANSFORM_REQUIRED_UINT:entityId");
        if (action == "set")
        {
            var changed = false;
            foreach (var name in new[] { "position", "rotation", "scale" })
                if (request.TryGetProperty(name, out _)) { Vector(request, name); changed = true; }
            if (!changed) throw new InvalidOperationException("TRANSFORM_EMPTY_CHANGE");
            if (!request.TryGetProperty("positionSpace", out var space) || space.ValueKind != JsonValueKind.String ||
                (space.GetString() != "world" && space.GetString() != "local"))
                throw new InvalidOperationException("TRANSFORM_POSITION_SPACE_REQUIRED");
            if (!request.TryGetProperty("rotationUnit", out var unit) || unit.ValueKind != JsonValueKind.String ||
                (unit.GetString() != "degrees" && unit.GetString() != "radians"))
                throw new InvalidOperationException("TRANSFORM_ROTATION_UNIT_REQUIRED");
        }
    }

    static float[] Vector(JsonElement request, string key)
    {
        if (!request.TryGetProperty(key, out var value) || value.ValueKind != JsonValueKind.Array || value.GetArrayLength() != 3)
            throw new InvalidOperationException("TRANSFORM_REQUIRED_VECTOR3:" + key);
        var components = new float[3];
        var index = 0;
        foreach (var component in value.EnumerateArray())
        {
            if (component.ValueKind != JsonValueKind.Number || !component.TryGetSingle(out var single) ||
                float.IsNaN(single) || float.IsInfinity(single))
                throw new InvalidOperationException("TRANSFORM_VECTOR_COMPONENT_INVALID:" + key);
            components[index++] = single;
        }
        return components;
    }

    // Bounded registry walk: every materialized scene entity model whose key id == entityId.
    // Same bounds and shape as EntityCrudProbe.ReadCrudEntities (nodes<=4096, depth<=6,
    // slots<=50000, same registry/child field bindings) but it RETURNS the matching models, so
    // the probe enforces count==1 with its own named codes instead of translating the CRUD
    // probe's generic ones. A model reachable twice is de-duplicated by reference; two distinct
    // models under one id stay two matches and are refused as ambiguous.
    List<object> TransformEntityMatches(uint entityId)
    {
        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");
        var matches = new List<object>();
        int nodes = 0, slots = 0;
        void Visit(object node, int depth)
        {
            if (++nodes > 4096 || depth > 6) throw new InvalidOperationException("TRANSFORM_REGISTRY_LIMIT");
            foreach (DictionaryEntry entry in (IDictionary)Field(node, B("JkmYibSuDZr")))
            {
                if (++slots > 50000) throw new InvalidOperationException("TRANSFORM_REGISTRY_SLOT_LIMIT");
                var model = entry.Value!;
                if (model.GetType().FullName != CrudEntityType) continue;
                if (ReadCrudKey(model).Id != entityId) continue;
                if (matches.Any(m => ReferenceEquals(m, model))) continue;
                matches.Add(model);
            }
            foreach (DictionaryEntry child in (IDictionary)Field(node, B("pIxYiE5REC8"))) Visit(child.Value!, depth + 1);
        }
        Visit(Field(ExistingSingleton(Editor(), Registry), B("bwbixDw3yob")), 0);
        return matches;
    }

    public object EntityTransform(JsonElement request)
    {
        ValidateEntityTransform(request);
        var action = request.TryGetProperty("action", out var actionValue) && actionValue.ValueKind == JsonValueKind.String
            ? actionValue.GetString()! : "inspect";
        var entityId = request.GetProperty("entityId").GetUInt32();

        var matches = TransformEntityMatches(entityId);
        if (matches.Count == 0) throw new InvalidOperationException("TRANSFORM_ENTITY_NOT_FOUND");
        if (matches.Count > 1) throw new InvalidOperationException("TRANSFORM_ENTITY_AMBIGUOUS");
        var model = matches[0];
        var key = ReadCrudKey(model);
        if (key.Id != entityId) throw new InvalidOperationException("TRANSFORM_ENTITY_ID_CONFLICT");

        object transform;
        try { transform = TransformSnapshot(Field(model, TransformField)); }
        catch (InvalidOperationException) { throw new InvalidOperationException("TRANSFORM_FIELD_UNAVAILABLE"); }

        if (action == "inspect")
            return new
            {
                ok = true, status = "entity-transform-cached-read-only", entityId, identity = key,
                entityType = Convert.ToInt32(Stored(model, B("yEpiSj6okKa")) ?? throw new InvalidOperationException("TRANSFORM_ENTITY_TYPE_MISSING")),
                instanceKind = Convert.ToInt32(Stored(model, B("d4siSoaFICf")) ?? throw new InvalidOperationException("TRANSFORM_INSTANCE_KIND_MISSING")),
                transform,
                vectorRolesVerified = false,
                roleMapping = "unestablished: maSidNtJUim/MtbidjteDd3/OStidFtjJdR order is not proven to be position/rotation/scale",
                nativeField = TransformField,
                nativeTransformRoute = "author.py entity-transform inspect|prepare|dispatch|decode|verify-save",
                localModelWritten = false, nativeMutationInvoked = false, sentToGame = false,
                gameEffectVerified = false, persistentSaveVerified = false
            };

        // Native calls need the game's verified callback and its independently
        // prepared card. A WPF dispatcher cannot satisfy that calling contract.
        throw new InvalidOperationException(TransformWriteBlocker);
    }
}
