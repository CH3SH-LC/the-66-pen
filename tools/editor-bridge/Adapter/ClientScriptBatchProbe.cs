using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    private sealed class ClientScriptBatchProbeState
    {
        public required object Context;
        public required int ContextState;
        public required object Folder;
        public required uint FolderId;
        public required int ScriptType;
        public required string Root;
        public required string[] Names;
        public required string[] Paths;
        public readonly Stopwatch Clock = Stopwatch.StartNew();
        public readonly Dictionary<uint, object> ModelsById = new();
        public readonly Dictionary<string, uint> IdsByName = new(StringComparer.Ordinal);
        public bool CreateSpent;
        public bool DeleteSpent;
    }

    private ClientScriptBatchProbeState? clientScriptBatchProbe;

    public object BeginClientScriptBatchProbe()
    {
        RequireInitDispatcher();
        if (clientScriptBatchProbe != null)
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_ALREADY_BEGUN");

        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var rows = ReadClientScriptRows(binding, out _);
        if (rows.Count != 0)
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_REQUIRES_EMPTY_REGISTRY");

        var context = CrudContext();
        var folder = ReadClientScriptProbeFolder(binding, requireEmpty: true);
        var root = ReadScriptRoot(binding);
        if (!System.IO.Path.IsPathFullyQualified(root))
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_ROOT_NOT_ABSOLUTE");

        var stem = "MW_LuaBatch_" + Guid.NewGuid().ToString("N")[..12];
        var names = new[] { stem + "_A", stem + "_B" };
        var paths = names.Select(name => name + ".lua").ToArray();
        clientScriptBatchProbe = new ClientScriptBatchProbeState
        {
            Context = context.Context,
            ContextState = context.State,
            Folder = folder.Model,
            FolderId = folder.Id,
            ScriptType = folder.ScriptType,
            Root = root,
            Names = names,
            Paths = paths
        };
        return ClientScriptBatchEvidence(clientScriptBatchProbe, rows);
    }

    private (ClientScriptBatchProbeState Probe, List<ClientScriptRow> Rows, object Manager)
        CheckClientScriptBatchProbe()
    {
        RequireInitDispatcher();
        var probe = clientScriptBatchProbe
            ?? throw new InvalidOperationException("SCRIPT_BATCH_PROBE_NOT_BEGUN");
        if (probe.Clock.Elapsed.TotalSeconds >= 180)
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_EXPIRED");

        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var context = CrudContext();
        var folder = ReadClientScriptProbeFolder(binding);
        if (!ReferenceEquals(context.Context, probe.Context) || context.State != probe.ContextState ||
            !ReferenceEquals(folder.Model, probe.Folder) || folder.Id != probe.FolderId ||
            folder.ScriptType != probe.ScriptType ||
            !StringComparer.Ordinal.Equals(ReadScriptRoot(binding), probe.Root))
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_CONTEXT_CHANGED");

        var rows = ReadClientScriptRows(binding, out _);
        if (rows.Count > 2)
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_FOREIGN_ROW_PRESENT");

        var presentIds = new HashSet<uint>();
        var presentModels = new HashSet<object>(ReferenceEqualityComparer.Instance);
        var presentNames = new HashSet<string>(StringComparer.Ordinal);
        foreach (var row in rows)
        {
            if (!probe.Names.Contains(row.Name, StringComparer.Ordinal) || row.Id == 0 ||
                !presentNames.Add(row.Name!) || !presentIds.Add(row.Id) || !presentModels.Add(row.Model))
                throw new InvalidOperationException("SCRIPT_BATCH_PROBE_FOREIGN_OR_DUPLICATE_ROW");

            if (!probe.CreateSpent)
                throw new InvalidOperationException("SCRIPT_BATCH_PROBE_ROW_BEFORE_CREATE");
            if (probe.ModelsById.TryGetValue(row.Id, out var priorModel))
            {
                if (!ReferenceEquals(priorModel, row.Model) ||
                    !probe.IdsByName.TryGetValue(row.Name!, out var priorId) || priorId != row.Id)
                    throw new InvalidOperationException("SCRIPT_BATCH_PROBE_TARGET_REPLACED");
            }
            else
            {
                if (probe.IdsByName.ContainsKey(row.Name!) || probe.DeleteSpent)
                    throw new InvalidOperationException("SCRIPT_BATCH_PROBE_UNCAPTURED_ID");
                probe.ModelsById.Add(row.Id, row.Model);
                probe.IdsByName.Add(row.Name!, row.Id);
            }
        }

        foreach (var pair in probe.IdsByName)
        {
            bool stillPresent = rows.Any(row => row.Id == pair.Value &&
                StringComparer.Ordinal.Equals(row.Name, pair.Key));
            if (!stillPresent && !probe.DeleteSpent)
                throw new InvalidOperationException("SCRIPT_BATCH_PROBE_TARGET_REMOVED_EXTERNALLY");
        }

        return (probe, rows, context.Manager);
    }

    private static object ClientScriptBatchEvidence(ClientScriptBatchProbeState probe,
        List<ClientScriptRow> rows) => new
    {
        ok = true,
        count = rows.Count,
        configuredRoot = probe.Root,
        folderId = probe.FolderId,
        scriptType = probe.ScriptType,
        createInvoked = probe.CreateSpent,
        deleteInvoked = probe.DeleteSpent,
        createdObserved = rows.Count == 2 && probe.IdsByName.Count == 2,
        deleteObserved = probe.DeleteSpent && rows.Count == 0,
        expectedItems = probe.Names.Select((name, index) => new { name, path = probe.Paths[index] }).ToArray(),
        items = rows.Select(row => new { resourceId = row.Id, name = row.Name, path = row.Path }).ToArray()
    };

    public object CreateClientScriptBatchProbe()
    {
        var (probe, rows, manager) = CheckClientScriptBatchProbe();
        if (probe.CreateSpent || probe.DeleteSpent || rows.Count != 0)
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_CREATE_REFUSED");

        var enumType = Editor().GetType(B("lsHpqNE7FeZinkCwmxHT.Bsw5mlE7cjIORHoZyCnp"), true)!;
        var pairs = new List<(string, string)>
        {
            (probe.Names[0], probe.Paths[0]),
            (probe.Names[1], probe.Paths[1])
        };
        probe.CreateSpent = true;
        manager.GetType().GetMethod(B("EiZXoHTupWQ"), Fields)!.Invoke(manager,
            new object[] { probe.FolderId, Enum.ToObject(enumType, probe.ScriptType), pairs });
        return new { ok = true, status = "client-script-batch-create-invoked-not-confirmed" };
    }

    public object InspectClientScriptBatchProbe()
    {
        var (probe, rows, _) = CheckClientScriptBatchProbe();
        return ClientScriptBatchEvidence(probe, rows);
    }

    public object DeleteClientScriptBatchProbe()
    {
        var (probe, rows, manager) = CheckClientScriptBatchProbe();
        if (!probe.CreateSpent || probe.DeleteSpent || rows.Count is < 1 or > 2 ||
            probe.ModelsById.Count == 0 || rows.Any(row => !probe.ModelsById.TryGetValue(row.Id, out var model) ||
                !ReferenceEquals(model, row.Model)))
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_DELETE_REFUSED");

        var ids = rows.Select(row => row.Id).ToList();
        if (ids.Distinct().Count() != ids.Count || ids.Any(id => id == 0))
            throw new InvalidOperationException("SCRIPT_BATCH_PROBE_DELETE_IDS_INVALID");
        probe.DeleteSpent = true;
        manager.GetType().GetMethod(B("sZGXo0LTqly"), Fields)!.Invoke(manager, new object[] { ids });
        return new { ok = true, status = "client-script-batch-delete-invoked-not-confirmed" };
    }
}
