using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    sealed class ClientScriptProbeState
    {
        public required object Context;
        public required int ContextState;
        public required object Folder;
        public required uint FolderId;
        public required int ScriptType;
        public required string Root;
        public string Name = "MW_Lua_" + Guid.NewGuid().ToString("N")[..12];
        public readonly Stopwatch Clock = Stopwatch.StartNew();
        public bool CreateSpent, RenameSpent, DeleteSpent;
        public ClientScriptRow? Target;
    }
    ClientScriptProbeState? clientScriptProbe;

    string ReadScriptRoot(EditorBindingProfile.ReopenContentReadBinding binding)
    {
        var manager = ExistingSingleton(Editor(), binding.Resolve("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        return Field(manager, binding.Resolve("ejHXanGppqr")) as string
            ?? throw new InvalidOperationException("SCRIPT_PROBE_ROOT_TYPE");
    }

    public object BeginClientScriptProbe()
    {
        RequireInitDispatcher();
        if (clientScriptProbe != null) throw new InvalidOperationException("SCRIPT_PROBE_ALREADY_BEGUN");
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var rows = ReadClientScriptRows(binding, out _);
        if (rows.Count != 0) throw new InvalidOperationException("SCRIPT_PROBE_REQUIRES_EMPTY_BASELINE");
        var context = CrudContext();
        var folder = ReadClientScriptProbeFolder(binding, requireEmpty: true);
        var root = ReadScriptRoot(binding);
        if (!System.IO.Path.IsPathFullyQualified(root)) throw new InvalidOperationException("SCRIPT_PROBE_ROOT_NOT_ABSOLUTE");
        clientScriptProbe = new ClientScriptProbeState { Context = context.Context, ContextState = context.State,
            Folder = folder.Model, FolderId = folder.Id, ScriptType = folder.ScriptType, Root = root };
        return ScriptProbeEvidence(clientScriptProbe, rows);
    }

    // Recover only the single object whose create request is preserved in R206 evidence.
    public object RecoverClientScriptProbe()
    {
        RequireInitDispatcher();
        if (clientScriptProbe != null) throw new InvalidOperationException("SCRIPT_PROBE_ALREADY_BEGUN");
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        const string ownedName = "MW_Lua_0110d986f8fb";
        var rows = ReadClientScriptRows(binding, out _);
        if (rows.Count != 1 || rows[0].Id == 0 || rows[0].Name != ownedName)
            throw new InvalidOperationException("SCRIPT_RECOVERY_NOT_OWNED");
        var context = CrudContext();
        var folder = ReadClientScriptProbeFolder(binding);
        if (folder.Id != 2 || folder.ScriptType != 0) throw new InvalidOperationException("SCRIPT_RECOVERY_FOLDER_CHANGED");
        var root = ReadScriptRoot(binding);
        if (!System.IO.Path.IsPathFullyQualified(root)) throw new InvalidOperationException("SCRIPT_PROBE_ROOT_NOT_ABSOLUTE");
        clientScriptProbe = new ClientScriptProbeState { Context = context.Context, ContextState = context.State,
            Folder = folder.Model, FolderId = folder.Id, ScriptType = folder.ScriptType, Root = root,
            Name = ownedName, CreateSpent = true, Target = rows[0] };
        return ScriptProbeEvidence(clientScriptProbe, rows);
    }

    (ClientScriptProbeState Probe, List<ClientScriptRow> Rows, object Manager) CheckClientScriptProbe()
    {
        RequireInitDispatcher();
        var probe = clientScriptProbe ?? throw new InvalidOperationException("SCRIPT_PROBE_NOT_BEGUN");
        if (probe.Clock.Elapsed.TotalSeconds >= 180) throw new InvalidOperationException("SCRIPT_PROBE_EXPIRED");
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var context = CrudContext();
        var folder = ReadClientScriptProbeFolder(binding);
        if (!ReferenceEquals(context.Context, probe.Context) || context.State != probe.ContextState ||
            !ReferenceEquals(folder.Model, probe.Folder) || folder.Id != probe.FolderId || folder.ScriptType != probe.ScriptType ||
            !StringComparer.Ordinal.Equals(ReadScriptRoot(binding), probe.Root))
            throw new InvalidOperationException("SCRIPT_PROBE_CONTEXT_CHANGED");
        var rows = ReadClientScriptRows(binding, out _);
        if (rows.Count > 1) throw new InvalidOperationException("SCRIPT_PROBE_FOREIGN_SCRIPT_ADDED");
        if (rows.Count == 1)
        {
            var row = rows[0];
            if (!probe.CreateSpent || row.Id == 0 || (row.Name != probe.Name && (!probe.RenameSpent || row.Name != probe.Name + "_R")))
                throw new InvalidOperationException("SCRIPT_PROBE_TARGET_NOT_OWNED");
            if (probe.Target is ClientScriptRow prior && (prior.Id != row.Id || !ReferenceEquals(prior.Model, row.Model)))
                throw new InvalidOperationException("SCRIPT_PROBE_TARGET_REPLACED");
            probe.Target ??= row;
        }
        else if (probe.Target != null && !probe.DeleteSpent)
            throw new InvalidOperationException("SCRIPT_PROBE_TARGET_REMOVED_EXTERNALLY");
        return (probe, rows, context.Manager);
    }

    static object ScriptProbeEvidence(ClientScriptProbeState probe, List<ClientScriptRow> rows) => new
    {
        ok = true, status = "client-script-probe-observation", probeName = probe.Name,
        renamedName = probe.Name + "_R", configuredRoot = probe.Root, folderId = probe.FolderId,
        scriptType = probe.ScriptType, createInvoked = probe.CreateSpent, renameInvoked = probe.RenameSpent,
        deleteInvoked = probe.DeleteSpent, count = rows.Count,
        createdObserved = probe.Target != null, deleteObserved = probe.DeleteSpent && rows.Count == 0,
        items = rows.Select(x => new { resourceId = x.Id, name = x.Name, path = x.Path }).ToArray()
    };

    public object InspectClientScriptProbe()
    {
        var (probe, rows, _) = CheckClientScriptProbe();
        return ScriptProbeEvidence(probe, rows);
    }

    public object CreateClientScriptProbe()
    {
        var (probe, rows, manager) = CheckClientScriptProbe();
        if (probe.CreateSpent || rows.Count != 0) throw new InvalidOperationException("SCRIPT_PROBE_CREATE_REFUSED");
        var type = Editor().GetType(B("lsHpqNE7FeZinkCwmxHT.Bsw5mlE7cjIORHoZyCnp"), true)!;
        probe.CreateSpent = true;
        manager.GetType().GetMethod(B("kqaXokY6uBT"), Fields)!.Invoke(manager,
            new object[] { probe.Name, probe.FolderId, Enum.ToObject(type, probe.ScriptType) });
        return new { ok = true, status = "client-script-create-invoked-not-confirmed", probeName = probe.Name };
    }

    public object RenameClientScriptProbe()
    {
        var (probe, rows, manager) = CheckClientScriptProbe();
        if (!probe.CreateSpent || probe.RenameSpent || probe.DeleteSpent || rows.Count != 1 || rows[0].Name != probe.Name)
            throw new InvalidOperationException("SCRIPT_PROBE_RENAME_REFUSED");
        probe.RenameSpent = true;
        manager.GetType().GetMethod(B("OtFXociSjVD"), Fields)!.Invoke(manager,
            new object[] { rows[0].Id, probe.Name + "_R" });
        return new { ok = true, status = "client-script-rename-invoked-not-confirmed", resourceId = rows[0].Id };
    }

    public object DeleteClientScriptProbe()
    {
        var (probe, rows, manager) = CheckClientScriptProbe();
        if (!probe.CreateSpent || probe.Target == null || probe.DeleteSpent || rows.Count != 1)
            throw new InvalidOperationException("SCRIPT_PROBE_DELETE_REFUSED");
        probe.DeleteSpent = true;
        manager.GetType().GetMethod(B("IMMXoYC9rQd"), Fields)!.Invoke(manager, new object[] { rows[0].Id });
        return new { ok = true, status = "client-script-delete-invoked-not-confirmed", resourceId = rows[0].Id };
    }
}
