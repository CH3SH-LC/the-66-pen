using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Bounded DELETE of exactly ONE component from exactly ONE entity, over the
// beyondEditObjService command "DeleteComponentForEditObj".
//
// ============================== UNVERIFIED ==============================
// UNVERIFIED until compiled and run against the real editor. Nothing in this
// file has been executed. The request is built by mirroring, line for line, the
// two sibling mutations the bridge ALREADY dispatches:
//   * tools/editor-bridge/Adapter/EntityFactionProbe.cs:152
//         producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(
//             producer,new object?[]{"beyondEditObjService","ModifyFactionForEditObj",null,args});
//   * tools/editor-bridge/Adapter/AuthorEntityTag.cs:127
//         producer.GetType().GetMethod(B("Ikci0qkvMZX"),Fields)!.Invoke(
//             producer,new object?[]{"beyondEditObjService","ModifyEditobjTag",null,args});
// The service string, the callback null, and the List<Param> arg construction
// (EntityFactionProbe.cs:139-143) are copied EXACTLY; only the command name and
// the two uint args differ. The command name / param shape come from the mine
// docs/research/reverse-eng-20261010/COMPONENT-WRITER-MINE.md sec.3 and the
// backend command_route id4 ("(int32 entityId, int32 componentId)").
//
// THIS IS A MUTATION. It must NEVER be pointed at an entity this run did not
// create or explicitly name. The owned-target gate below (mirroring
// EntityFactionProbe.cs:103-109) refuses everything except the single self-owned
// CRUD probe entity, so a stray id cannot delete a component on a user's save.
// =========================================================================
//
// ---------------------------------------------------------------------------
// READER (this build): the read half resolves through the SAME metadata-verified
// 7.1 component contract the read op already uses -- EntityComponentProbe.
// ComponentModelContract: the entity field EDuXiXtiyvl, the component collection
// box's own private List<component> field o26XLglnP6U, and the component model
// class tpPbY7XdXPTGZ4wNXSWn.CF9E4JXdL1Cq4xrMUnCq with its boxed uint id
// OgoXdqFmidJ. Those are the ACTUAL BeyondEditor 7.1.0 names harvested from the
// pinned PE metadata dump (metadata-7.1.json; see EntityComponentProbe.cs:24-32).
//
// The legacy pair this file used to request from the binding profile --
// JdaiSnpkbfl (entity: public List<Component>) and b1EiCj8P44N (component -> uint
// id) -- is NOT registered there (EditorBindingProfile.Generated.cs: 0 hits for
// both), and the profile's own source map (merged-symbols-7.1.json) has no entry
// for either, so any hand-added binding would be INVENTED, not read off a pinned
// corpus. Worse, the by-shape modern counterpart of the legacy JdaiSnpkbfl public
// field -- W8QXivS0WCh, the entity's List<component> -- is NOT the live
// collection: JdaiSnpkbfl has ZERO readers across the 12375-file resolved corpus,
// while every component mutation goes through the wrapper accessor WlJiSPfnM3R()
// (= 7.1 EDuXiXtiyvl; e.g. resolved/Uf6GwkiSOYHgqiqgQlC5.AooSwxiSm6Ktx99ovmnr.cs:587
// calls WlJiSPfnM3R().X66ijdVvJ0k(component)). Binding the delete to that dead
// list would have pointed a MUTATION's before-list at a non-authoritative set, so
// both halves now read ONE collection, through the read op's verified contract.
//
// Failure to resolve that contract still REFUSES, with the named code
// COMPONENT_MODEL_READER_UNBOUND -- it NEVER returns an empty list as if the
// entity had no components. Deleting a component REQUIRES the before-list (for
// the "not found" refusal), so both actions stay fail-closed until it resolves.
// ---------------------------------------------------------------------------
internal sealed partial class EditorAdapter
{
    // Command/service pair. "DeleteComponentForEditObj" is the literal the front
    // end dispatches (COMPONENT-WRITER-MINE.md sec.2.3, yn34VuuuO5tEgsICYDBW.cs:107)
    // and the backend command_route id4 handler.
    const string ComponentDeleteService = "beyondEditObjService";
    const string ComponentDeleteCommand = "DeleteComponentForEditObj";

    // The read half carries no symbol of its own: it reuses EntityComponentProbe's
    // typed, metadata-verified 71 contract (same partial class). A component set
    // bigger than this is malformed, not merely long, so it refuses instead of
    // truncating -- a truncated list must never read back as an authoritative set.
    const int ComponentListLimit = 256;

    readonly HashSet<string> entityComponentDeleteAttempts = new(StringComparer.Ordinal);

    // Strict envelope, in the shape of AuthorEntityTag.ValidateAuthorEntityTag
    // (AuthorEntityTag.cs:24-42): unknown or duplicate fields and malformed numbers
    // are refused BEFORE any native call.
    internal static void ValidateEntityComponentDelete(JsonElement request)
    {
        string S(string key) => request.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()! : throw new InvalidOperationException("COMPONENT_REQUIRED_STRING:" + key);
        uint U(string key) => request.TryGetProperty(key, out var v) && v.TryGetUInt32(out var n) && n != 0
            ? n : throw new InvalidOperationException("COMPONENT_REQUIRED_UINT:" + key);
        var action = S("action");
        if (action != "inspect" && action != "delete") throw new InvalidOperationException("COMPONENT_ACTION_UNSUPPORTED");
        var allowed = new HashSet<string> { "id", "op", "nonce", "action", "probeId", "entityId" };
        if (action == "delete") allowed.Add("componentId");
        var seen = new HashSet<string>();
        foreach (var p in request.EnumerateObject())
            if (!allowed.Contains(p.Name) || !seen.Add(p.Name))
                throw new InvalidOperationException("COMPONENT_UNKNOWN_OR_DUPLICATE_FIELD:" + p.Name);
        if (!Guid.TryParseExact(S("probeId"), "N", out _)) throw new InvalidOperationException("COMPONENT_PROBE_ID_INVALID");
        U("entityId");
        if (action == "delete" && U("componentId") > int.MaxValue)
            throw new InvalidOperationException("COMPONENT_ID_OUTSIDE_INT32"); // backend param_shape is int32
    }

    // Read-only. Returns the component ids of ONE entity's editor model through the
    // read op's verified contract (ComponentModelContract, above). Any unresolvable
    // contract refuses with the single named code below -- this NEVER invents an
    // empty list, and never falls back to a second, unverified field.
    List<uint> ComponentIds(object model)
    {
        ComponentModel contract;
        try { contract = ComponentModelContract(Editor()); }
        catch (InvalidOperationException) { throw new InvalidOperationException("COMPONENT_MODEL_READER_UNBOUND"); }
        catch (TypeLoadException) { throw new InvalidOperationException("COMPONENT_MODEL_READER_UNBOUND"); }
        var raw = contract.Collection.GetValue(model)
            ?? throw new InvalidOperationException("COMPONENT_COLLECTION_NOT_MATERIALIZED");
        if (raw.GetType() != contract.CollectionType)
            throw new InvalidOperationException("COMPONENT_MODEL_READER_CONTRACT_MISMATCH");
        if (contract.Items.GetValue(raw) is not IList items || items.GetType() != contract.ItemsType)
            throw new InvalidOperationException("COMPONENT_COLLECTION_NOT_MATERIALIZED");
        if (items.Count > ComponentListLimit) throw new InvalidOperationException("COMPONENT_LIST_LIMIT");
        var ids = new List<uint>();
        foreach (var item in items)
        {
            if (item == null || item.GetType() != contract.ComponentType)
                throw new InvalidOperationException("COMPONENT_ROW_NULL");
            ids.Add((uint)ComponentValue(item, contract.Id));
        }
        return ids;
    }

    // The ONE entity this run may mutate: the self-owned CRUD probe target, exactly as
    // EntityFactionProbe.FactionOwnedTarget (EntityFactionProbe.cs:103-109) requires.
    // Named entityId must equal it; explicit naming of an arbitrary entity is refused.
    //
    // The gate is deliberately narrow. ComponentOwnedTarget -> CheckCrudTarget
    // (EntityCrudProbe.cs:102-114) -> CheckCrudBaseline (EntityCrudProbe.cs:88-100)
    // refuses unless ALL of the following hold at once, in this order:
    //   * the CRUD probe exists and has not expired (180 s, EntityCrudProbe.cs:16);
    //   * the editor context and every baseline entity are unchanged;
    //   * exactly ONE entity was added since the baseline, and it IS the registered
    //     target (matched by key AND by model reference), native type 1402, kind 0;
    //   * no other entity wears the probe's name, and the target was not renamed;
    //   * the target carries no graph bindings.
    // The gate feeds the mutation lease: at most one dispatch per (probe, entity,
    // component), at most 16 per run, and the before-list is re-read immediately
    // before the send, so a baseline that moved during preparation refuses.
    // Anything else is refused BEFORE any native dispatch. The predicate chain is
    // pinned clause-by-clause in tests/test_component_delete_safety.py.
    (CrudExperiment Probe, CrudEntity Target) ComponentOwnedTarget(uint entityId)
    {
        var current = CheckCrudTarget();
        if (current.Probe.DeleteSpent || current.Target.Key.Id != entityId
            || current.Target.EntityType != 1402 || current.Target.InstanceKind != 0
            || EntityBindings(current.Target.Model).Length != 0)
            throw new InvalidOperationException("COMPONENT_OWNED_UNBOUND_TARGET_REQUIRED");
        return current;
    }

    // The invoke. Copied from EntityFactionProbe.cs:137-152 (identical producer, service
    // string, callback null and List<Param> construction); only the command and the two
    // uint args differ. Never builds a callback, RPC or reflection argument bag.
    void DispatchComponentDelete(uint entityId, uint componentId)
    {
        var manager = CrudContext().Manager;
        if (!(bool)manager.GetType().GetMethod(B("wAXirPMXQCJ"), Fields)!.Invoke(manager, new object[] { false })!)
            throw new InvalidOperationException("EDITOR_NOT_READY");
        var param = Editor().GetType(Param, true)!;
        var factory = param.GetMethod(B("bKliA0tj1p1"), BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly, null, new[] { typeof(uint) }, null);
        if (factory == null || factory.ReturnType != param) throw new InvalidOperationException("COMPONENT_UINT_FACTORY_CONTRACT_MISMATCH");
        var args = (IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(param))!;
        args.Add(factory.Invoke(null, new object[] { entityId })!);    // uint(entityId)
        args.Add(factory.Invoke(null, new object[] { componentId })!); // uint(componentId)
        var producer = ExistingSingleton(Editor(), Producer);
        producer.GetType().GetMethod(B("Ikci0qkvMZX"), Fields)!.Invoke(
            producer, new object?[] { ComponentDeleteService, ComponentDeleteCommand, null, args });
    }

    public object EntityComponentDelete(JsonElement request)
    {
        ValidateEntityComponentDelete(request);
        var action = request.GetProperty("action").GetString()!;
        var entityId = request.GetProperty("entityId").GetUInt32();

        // Resolve EXACTLY ONE entity by id. Reuses the compiled sibling probe's resolver
        // (EntityComponentProbe.cs:101-110 ResolveComponentEntity) -- the same registry walk
        // and the same id-uniqueness proof, so this delete and the read probe resolve a given
        // id identically. It throws COMPONENT_ENTITY_NOT_FOUND / COMPONENT_ENTITY_ID_NOT_UNIQUE
        // and only ever returns a model whose key id equals entityId, so no separate
        // conflict check is needed.
        var resolved = ResolveComponentEntity(entityId);
        var model = resolved.Model;
        var key = resolved.Key;

        // Before-state. Throws COMPONENT_MODEL_READER_UNBOUND if the 7.1 component
        // contract cannot be resolved on this build (see the READER note above).
        var before = ComponentIds(model);

        if (action == "inspect")
            return new
            {
                ok = true, status = "entity-components-editor-model-read-only", entityId, identity = key,
                componentIds = before.ToArray(), componentCount = before.Count,
                componentListSource = "entity-components-field(" + EntityComponentsField71 + ")-metadata-verified-name",
                componentIdSpace = "jaUof90C3Ncl5BAJri4x-enum-value-or-native-index-UNVERIFIED",
                nativeMutationInvoked = false, localModelWritten = false,
                gameEffectVerified = false, persistentSaveVerified = false
            };

        var componentId = request.GetProperty("componentId").GetUInt32();

        // Mutation gate: owned target, named probe, same model, present exactly once.
        var (probe, target) = ComponentOwnedTarget(entityId);
        if (request.GetProperty("probeId").GetString() != probe.Id || !ReferenceEquals(target.Model, model))
            throw new InvalidOperationException("COMPONENT_OWNED_TARGET_MISMATCH");
        if (before.Count(id => id == componentId) != 1)
            throw new InvalidOperationException("COMPONENT_NOT_FOUND_OR_NOT_UNIQUE");

        var attempt = probe.Id + ":" + entityId + ":" + componentId;
        if (entityComponentDeleteAttempts.Contains(attempt))
            throw new InvalidOperationException("COMPONENT_DELETE_ALREADY_ATTEMPTED");
        if (entityComponentDeleteAttempts.Count >= 16)
            throw new InvalidOperationException("COMPONENT_LEASE_MUTATION_LIMIT");

        // Re-check immediately before the dispatch (baseline discipline; mirrors
        // AuthorEntityTag.cs:121-125 / EntityFactionProbe.cs:145-150).
        var fresh = ComponentOwnedTarget(entityId);
        if (!ReferenceEquals(fresh.Target.Model, model) || !ComponentIds(model).SequenceEqual(before))
            throw new InvalidOperationException("COMPONENT_BASELINE_CHANGED_DURING_PREPARATION");

        entityComponentDeleteAttempts.Add(attempt); // consumed even if the native send throws
        DispatchComponentDelete(entityId, componentId);

        // Same-turn re-read of the editor model. The native delete is async, so this is NOT
        // authoritative -- reported only so the caller has a before/after pair; a real
        // decision needs a later inspect and a .gil byte diff (doctrine: ok:true alone does
        // not prove persistence).
        var after = ComponentIds(model);
        return new
        {
            ok = true, status = "entity-component-delete-requested-readback-pending",
            probeId = probe.Id, entityId, componentId,
            beforeComponentIds = before.ToArray(), beforeComponentCount = before.Count,
            afterComponentIdsSameTurn = after.ToArray(), afterComponentCountSameTurn = after.Count,
            afterReadback = "same-turn-reread-non-authoritative; native dispatch is asynchronous",
            invokedUtc = DateTime.UtcNow, retryAllowed = false,
            nativeMutationInvoked = true, localModelWritten = false,
            gameEffectVerified = false, persistentSaveVerified = false,
            notice = "A dispatch return value is not persistence. Re-run inspect later and diff the .gil bytes before claiming success."
        };
    }
}
