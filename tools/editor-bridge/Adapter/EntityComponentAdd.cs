using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Bounded ADD of exactly ONE component to exactly ONE entity, over the editor's own
// entity-model loader path ("route A", docs/gameplan/ADD-COMPONENT-MODEL-PATH.md sec.Q5).
//
// ============================== UNVERIFIED (not yet run) ==============================
// Nothing in this file has been executed against a real editor. It is the mirror image of
// EntityComponentDelete.cs, and its read half reuses the SAME metadata-verified 7.1
// component contract the read op (EntityComponentProbe) and the delete op already use.
//
// THIS IS A LOCAL-MODEL WRITE, NOT A NATIVE COMMAND -- and that asymmetry is the whole
// point of the design:
//   * delete dispatches the native front-end command "DeleteComponentForEditObj", which
//     destroys a component in the native/authoring store. localModelWritten=false.
//   * add has NO such command (AddComponentForEditObj is 0-hit across every searched
//     surface; docs: CLAUDE.md sec.5). It appends to the entity's LOCAL, DERIVED component
//     collection -- exactly what the editor's own deserializer does at
//     resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587
//         ...WlJiSPfnM3R().X66ijdVvJ0k(component)
//     (the POSITIVE CONTROL for every step below). So this op reports
//     nativeMutationInvoked=false, localModelWritten=true, persistentSaveVerified=false.
//   * The collection is a MIRROR: on the entity's next load it is Clear(true)-rebuilt from
//     the data side (proto field 90), which has ZERO writers in the resolved corpus. The
//     added row therefore does NOT survive a reload and does NOT reach the game or the save
//     file. persistentSaveVerified=false is true BY CONSTRUCTION, not by omission.
// ======================================================================================
//
// ---------------------------------------------------------------------------------------
// SYMBOLS (7.1 real names; resolved-corpus names in comments). There is NO change to
// EditorBindingProfile.Generated.cs: the one new symbol this op needs -- the collection's
// ADD method -- goes in as a typed 71 const, house style (EntityComponentProbe.cs:17-21):
// a wrong contract in the profile fails EVERY operation on the bridge closed
// (EditorBindingProfile.cs ValidateContracts), while a wrong const here fails only this op.
// The component constructor cannot live in the profile at all -- RequireMemberName refuses
// ".ctor" (EditorBindingProfile.cs:412-413) -- so it is resolved at run time with a shape
// check (COMPONENT_ADD_CTOR_MISSING).
//
//   ADD method      : G2GXLQZkPlk  (resolved X66ijdVvJ0k(T,bool):void)
//                     7.1 sig (rNQIAcXLLH06fJhXrLPY,System.Boolean):System.Void
//                     on the open generic vkNQubXLXRds8Ypg8CDv.WupssAXLwY5NGCQQMQWk`1
//                     -- the SAME open generic the profile already contracts at
//                     EditorBindingProfile.Generated.cs:668 (its o26XLglnP6U field row).
//                     Locator: resolved/.../QAVTZKijY59YjpE1GYC0.rgfCjhijuAbCoKxWU8Lu_1.cs:81
//                     Positive control: entity loader ...AooSwxiSm6Ktx99ovmnr.cs:587.
//   value member    : B("VpIiRZgdEln") -> PIWXZgk5Tyr, the box class's protected value field
//                     (resolved QvaeNjiRTWDlMoJVxKu1.t7crdXiRQQTsF520oNMA_1.cs:16). The read
//                     half (ComponentValue, EntityComponentProbe.cs:119) reads exactly this
//                     field; this op writes exactly this field -- the read half's inverse.
//   the rest (entity type, entity->collection field EDuXiXtiyvl, collection->List field
//   o26XLglnP6U, component type CF9E4JXdL1Cq4xrMUnCq, id box field OgoXdqFmidJ) come from
//   ComponentModelContract, which is already pinned in tests (EntityComponentProbe).
// ---------------------------------------------------------------------------------------
internal sealed partial class EditorAdapter
{
    // The one NEW symbol this op introduces (see the header). Kept as a typed 71 const so a
    // wrong value fails only this op, never the whole bridge (house style, and the design's
    // chosen approach: EditorBindingProfile.Generated.cs is NOT touched).
    const string ComponentAddMethod71 = "G2GXLQZkPlk"; // resolved X66ijdVvJ0k (ADD)

    // Independent lease for the add direction. The delete direction keeps its own set; the
    // two budgets do not share a counter (deleting once must not lock adding once).
    readonly HashSet<string> entityComponentAddAttempts = new(StringComparer.Ordinal);

    // Strict envelope, in the shape of ValidateEntityComponentDelete (EntityComponentDelete.cs):
    // unknown or duplicate fields and malformed numbers are refused BEFORE any reflection.
    // componentId is admitted ONLY for action=="add" (an inspect probe never carries it).
    internal static void ValidateEntityComponentAdd(JsonElement request)
    {
        string S(string key) => request.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()! : throw new InvalidOperationException("COMPONENT_REQUIRED_STRING:" + key);
        uint U(string key) => request.TryGetProperty(key, out var v) && v.TryGetUInt32(out var n) && n != 0
            ? n : throw new InvalidOperationException("COMPONENT_REQUIRED_UINT:" + key);
        var action = S("action");
        if (action != "inspect" && action != "add") throw new InvalidOperationException("COMPONENT_ACTION_UNSUPPORTED");
        var allowed = new HashSet<string> { "id", "op", "nonce", "action", "probeId", "entityId" };
        if (action == "add") allowed.Add("componentId");
        var seen = new HashSet<string>();
        foreach (var p in request.EnumerateObject())
            if (!allowed.Contains(p.Name) || !seen.Add(p.Name))
                throw new InvalidOperationException("COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:" + p.Name);
        if (!Guid.TryParseExact(S("probeId"), "N", out _)) throw new InvalidOperationException("COMPONENT_PROBE_ID_INVALID");
        U("entityId");
        if (action == "add" && U("componentId") > int.MaxValue)
            throw new InvalidOperationException("COMPONENT_ID_OUTSIDE_INT32"); // keep the legacy int32 id space
    }

    // The ONE entity this run may mutate: the self-owned CRUD probe target, exactly as
    // ComponentOwnedTarget (EntityComponentDelete.cs:147) requires. Named entityId must equal
    // it; explicit naming of an arbitrary entity is refused.
    //
    // ComponentAddOwnedTarget -> CheckCrudTarget (EntityCrudProbe.cs:102) -> CheckCrudBaseline
    // (EntityCrudProbe.cs:88) refuses unless ALL of the following hold at once, in this order:
    //   * the CRUD probe exists and has not expired (180 s, EntityCrudProbe.cs:16);
    //   * the editor context and every baseline entity are unchanged;
    //   * exactly ONE entity was added since the baseline, and it IS the registered target
    //     (matched by key AND by model reference), native type 1402, kind 0;
    //   * no other entity wears the probe's name, and the target was not renamed;
    //   * the target carries no graph bindings;
    //   * the op's own spend bit AddSpent is false.
    // The predicate chain is pinned clause-by-clause in tests/test_component_add_safety.py.
    (CrudExperiment Probe, CrudEntity Target) ComponentAddOwnedTarget(uint entityId)
    {
        var current = CheckCrudTarget();
        if (current.Probe.AddSpent || current.Target.Key.Id != entityId
            || current.Target.EntityType != 1402 || current.Target.InstanceKind != 0
            || EntityBindings(current.Target.Model).Length != 0)
            throw new InvalidOperationException("COMPONENT_ADD_OWNED_UNBOUND_TARGET_REQUIRED");
        return current;
    }

    // The five steps of route A (ADD-COMPONENT-MODEL-PATH.md sec.Q5), verbatim, against the
    // ONE self-owned entity model. The ONLY side effect is add.Invoke on the LIVE collection;
    // no native command, no data-side (avWvR710hyW) list, no callback of our own.
    void AppendComponentToModel(object entityModel, ComponentModel contract, uint componentId)
    {
        // 2) construct a component (public parameterless ctor, resolved at run time because
        // the profile cannot express ".ctor"). Shape-checked, never faked.
        var ctor = contract.ComponentType.GetConstructor(
            BindingFlags.Public | BindingFlags.Instance, null, Type.EmptyTypes, null)
            ?? throw new InvalidOperationException("COMPONENT_ADD_CTOR_MISSING");
        var component = ctor.Invoke(Array.Empty<object>());
        // 3) set ONLY the id, exactly as the loader does (it never touches enabled / x / y).
        var handle = contract.Id.GetValue(component)
            ?? throw new InvalidOperationException("COMPONENT_ADD_ID_HANDLE_NOT_MATERIALIZED");
        var value = handle.GetType().GetField(B("VpIiRZgdEln"), Fields | BindingFlags.DeclaredOnly)
            ?? throw new InvalidOperationException("COMPONENT_VALUE_MEMBER_MISSING");
        value.SetValue(handle, componentId); // the box is a class: this writes the shared handle
        // 4) resolve ADD on the live collection and check its declared shape before invoking it.
        var add = contract.CollectionType.GetMethod(ComponentAddMethod71,
            BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly,
            null, new[] { contract.ComponentType, typeof(bool) }, null);
        if (add == null || add.ReturnType != typeof(void))
            throw new InvalidOperationException("COMPONENT_ADD_METHOD_CONTRACT_MISMATCH");
        // 5) append to the live collection (the loader's own line, ...AooSwxiSm6Ktx99ovmnr.cs:587).
        // withCallback:true fires HX3ijrsalOE(op=0) so the component panel rebuilds.
        var collection = contract.Collection.GetValue(entityModel)
            ?? throw new InvalidOperationException("COMPONENT_COLLECTION_NOT_MATERIALIZED");
        add.Invoke(collection, new object[] { component, true });
    }

    public object EntityComponentAdd(JsonElement request)
    {
        ValidateEntityComponentAdd(request);
        var action = request.GetProperty("action").GetString()!;
        var entityId = request.GetProperty("entityId").GetUInt32();
        if (!System.Windows.Application.Current.Dispatcher.CheckAccess())
            throw new InvalidOperationException("WRONG_THREAD");

        // Resolve EXACTLY ONE entity by id, off the compiled sibling probe's resolver, so this
        // add and the read probe resolve a given id identically. Throws
        // COMPONENT_ENTITY_NOT_FOUND / COMPONENT_ENTITY_ID_NOT_UNIQUE.
        var resolved = ResolveComponentEntity(entityId);
        var model = resolved.Model;
        var key = resolved.Key;

        // Before-state. Throws COMPONENT_MODEL_READER_UNBOUND if the 7.1 component contract
        // cannot be resolved on this build -- it NEVER invents an empty list.
        var before = ComponentIds(model);

        if (action == "inspect")
        {
            var componentAlreadyPresent = request.TryGetProperty("componentId", out var cv)
                && cv.TryGetUInt32(out var cid) && before.Contains(cid);
            return new
            {
                ok = true, status = "entity-components-editor-model-read-only", entityId, identity = key,
                componentIds = before.ToArray(), componentCount = before.Count,
                componentListSource = "entity-components-field(" + EntityComponentsField71 + ")-metadata-verified-name",
                componentIdSpace = "jaUof90C3Ncl5BAJri4x-enum-value-or-native-index-UNVERIFIED",
                componentAlreadyPresent,
                nativeMutationInvoked = false, localModelWritten = false,
                gameEffectVerified = false, persistentSaveVerified = false
            };
        }

        var componentId = request.GetProperty("componentId").GetUInt32();

        // Mutation gate: owned target, named probe, same model reference.
        var (probe, target) = ComponentAddOwnedTarget(entityId);
        if (request.GetProperty("probeId").GetString() != probe.Id || !ReferenceEquals(target.Model, model))
            throw new InvalidOperationException("COMPONENT_ADD_OWNED_TARGET_MISMATCH");
        // De-duplication, not the delete's "present exactly once": adding an id already in the
        // set is refused rather than silently producing a second row.
        if (before.Contains(componentId))
            throw new InvalidOperationException("COMPONENT_ADD_ALREADY_PRESENT");

        var attempt = probe.Id + ":" + entityId + ":" + componentId;
        if (entityComponentAddAttempts.Contains(attempt))
            throw new InvalidOperationException("COMPONENT_ADD_ALREADY_ATTEMPTED");
        if (entityComponentAddAttempts.Count >= 16)
            throw new InvalidOperationException("COMPONENT_LEASE_MUTATION_LIMIT");

        // Re-check immediately before the write (baseline discipline; mirrors the delete's
        // EntityComponentDelete.cs:224-226).
        var fresh = ComponentAddOwnedTarget(entityId);
        if (!ReferenceEquals(fresh.Target.Model, model) || !ComponentIds(model).SequenceEqual(before))
            throw new InvalidOperationException("COMPONENT_ADD_BASELINE_CHANGED_DURING_PREPARATION");

        // Both leases are consumed BEFORE the write, exactly as the delete does
        // (EntityComponentDelete.cs:228-233: "consumed even if the native send throws"). A
        // second add against the same probe window is then refused by the gate (AddSpent), and
        // a repeat of the same triplet by COMPONENT_ADD_ALREADY_ATTEMPTED.
        entityComponentAddAttempts.Add(attempt);
        probe.AddSpent = true;
        AppendComponentToModel(model, ComponentModelContract(Editor()), componentId);

        // Same-turn re-read of the editor model. The mirror is local and synchronous, but this
        // is reported only as a before/after pair -- never as proof (doctrine: ok:true alone
        // does not prove anything persisted).
        var after = ComponentIds(model);
        return new
        {
            ok = true, status = "entity-component-added-editor-model-only",
            probeId = probe.Id, entityId, componentId,
            beforeComponentIds = before.ToArray(), beforeComponentCount = before.Count,
            afterComponentIdsSameTurn = after.ToArray(), afterComponentCountSameTurn = after.Count,
            afterReadback = "same-turn-reread-non-authoritative; this op dispatches NO native command",
            invokedUtc = DateTime.UtcNow, retryAllowed = false,
            nativeMutationInvoked = false, localModelWritten = true,
            sentToGame = false, gameEffectVerified = false, persistentSaveVerified = false,
            notice = "Editor-memory mirror only. The local collection (EDuXiXtiyvl) is Clear(true)-rebuilt "
                + "from the data side (proto field 90, zero writers) on this entity's next load, and NO native "
                + "component object is created. This add cannot persist; diff the .gil only AFTER a save the "
                + "editor itself performs."
        };
    }
}
