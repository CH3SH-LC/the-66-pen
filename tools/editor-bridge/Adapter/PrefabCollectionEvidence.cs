using System;
using System.IO;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Miliastra.EditorBridge;

// Bounded, forward-only reads over the prefab models materialized by the reviewed
// reopen-content resource path. Each call runs on the adapter dispatcher.
internal sealed partial class EditorAdapter
{
    sealed record PrefabPageItem(uint ResourceId, object Value);
    readonly List<(uint Id, object Model)> prefabPageModels = new();
    readonly Dictionary<uint, object> prefabPageItems = new();
    readonly Dictionary<uint, object> prefabPageFailures = new();
    readonly Dictionary<int, object> prefabPageCache = new();
    string? prefabPageSnapshotId;
    DateTime prefabPageStartedUtc;
    int prefabPageNextOffset;
    bool prefabPageInitialized;
    int prefabPageCatalogTotal;
    int prefabPageReusedCount;
    bool prefabPageResumeApplied;
    const int PrefabPageMaxSize = 128;
    const int PrefabPageTimeSliceMs = 2000;

    // Internal argument-taking entry point is also used by isolated contract checks.
    internal object PrefabFieldsPage(uint[] args) => PrefabFieldsPageCore(args, null);

    object PrefabFieldsPageCore(uint[] args, string? resumePath)
    {
        RequireInitDispatcher();
        if (args == null || args.Length != 2) throw new InvalidOperationException("PREFAB_PAGE_ARGS");
        uint rawOffset = args[0], rawSize = args[1];
        if (rawSize < 1 || rawSize > PrefabPageMaxSize) throw new InvalidOperationException("PREFAB_PAGE_SIZE");
        if (rawOffset > int.MaxValue) throw new InvalidOperationException("PREFAB_PAGE_OFFSET");
        int offset = (int)rawOffset, pageSize = (int)rawSize;

        // A repeated page is an idempotent read from our detached DTO cache. Still
        // run the profile scope so source identity is checked on every call.
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var symbols = new Dictionary<string,string>(StringComparer.Ordinal);
        string Resolve(string legacy) { if (!symbols.TryGetValue(legacy, out var value)) symbols.Add(legacy, value = binding.Resolve(legacy)); return value; }
        if (prefabPageCache.TryGetValue(offset, out var cached)) return cached;
        if (!prefabPageInitialized)
        {
            if (offset != 0) throw new InvalidOperationException("PREFAB_PAGE_MUST_START_AT_ZERO");
            prefabPageStartedUtc = DateTime.UtcNow;
            prefabPageSnapshotId = Guid.NewGuid().ToString("N");
            ResourcesForReopenContent(binding); // one registry scan for this snapshot
            var seen = new HashSet<uint>();
            foreach (var model in prefabModels)
            {
                var keyWrapper = Field(model, Resolve("atbiBHcMllT"));
                var key = ContentFieldReader.Raw(keyWrapper, Resolve("VpIiRZgdEln")) ?? throw new InvalidOperationException("PREFAB_RESOURCE_KEY_NULL");
                var id = (uint)Field(key, Resolve("namiwGPRyPS"));
                if (seen.Add(id)) prefabPageModels.Add((id, model));
            }
            prefabPageModels.Sort((a, b) => a.Id.CompareTo(b.Id));
            prefabPageCatalogTotal = prefabPageModels.Count;
            if (resumePath != null && File.Exists(resumePath))
            {
                var idsText = string.Join(",", prefabPageModels.Select(row => row.Id.ToString(CultureInfo.InvariantCulture)));
                var expectedHash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(idsText))).ToLowerInvariant();
                using var manifest = JsonDocument.Parse(File.ReadAllText(resumePath, Encoding.UTF8));
                var root = manifest.RootElement;
                if (root.ValueKind != JsonValueKind.Object) throw new InvalidOperationException("PREFAB_RESUME_OBJECT");
                var propertyNames = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in root.EnumerateObject())
                    if (!propertyNames.Add(property.Name) || property.Name is not ("schema" or "catalogIdsSha256" or "completedIds")) throw new InvalidOperationException("PREFAB_RESUME_PROPERTY");
                if (propertyNames.Count != 3) throw new InvalidOperationException("PREFAB_RESUME_PROPERTY");
                if (!root.TryGetProperty("schema", out var schema) || schema.ValueKind != JsonValueKind.Number || !schema.TryGetInt32(out var schemaValue) || schemaValue != 1) throw new InvalidOperationException("PREFAB_RESUME_SCHEMA");
                if (!root.TryGetProperty("catalogIdsSha256", out var hashNode) || hashNode.ValueKind != JsonValueKind.String || !string.Equals(hashNode.GetString(), expectedHash, StringComparison.Ordinal)) throw new InvalidOperationException("PREFAB_RESUME_CATALOG_HASH");
                if (!root.TryGetProperty("completedIds", out var idsNode) || idsNode.ValueKind != JsonValueKind.Array) throw new InvalidOperationException("PREFAB_RESUME_IDS");
                var catalogIds = prefabPageModels.Select(row => row.Id).ToHashSet();
                var completed = new HashSet<uint>();
                foreach (var node in idsNode.EnumerateArray())
                {
                    if (node.ValueKind != JsonValueKind.Number || !node.TryGetUInt32(out var id)) throw new InvalidOperationException("PREFAB_RESUME_ID_TYPE");
                    if (!completed.Add(id)) throw new InvalidOperationException("PREFAB_RESUME_DUPLICATE_ID");
                    if (!catalogIds.Contains(id)) throw new InvalidOperationException("PREFAB_RESUME_UNKNOWN_ID");
                }
                prefabPageReusedCount = completed.Count;
                prefabPageResumeApplied = true;
                prefabPageModels.RemoveAll(row => completed.Contains(row.Id));
            }
            prefabPageInitialized = true;
        }
        if (offset != prefabPageNextOffset) throw new InvalidOperationException("PREFAB_PAGE_OUT_OF_ORDER");
        if (offset > prefabPageModels.Count) throw new InvalidOperationException("PREFAB_PAGE_OFFSET");

        var editor = Editor();
        var timer = Stopwatch.StartNew();
        int end = Math.Min(prefabPageModels.Count, checked(offset + pageSize));
        for (int index = offset; index < end; index++)
        {
            var (id, model) = prefabPageModels[index];
            if (!prefabPageItems.ContainsKey(id) && !prefabPageFailures.ContainsKey(id))
            {
                try
                {
                    object? ReadStored(string legacy)
                    {
                        try
                        {
                            var wrapper = Field(model, Resolve(legacy));
                            return ContentFieldReader.Raw(wrapper, Resolve("VpIiRZgdEln"));
                        }
                        catch (InvalidOperationException) { return null; }
                    }

                    var name = ReadStored("PChiBEHqYMS");
                    var icon = ReadStored("gTdiBiGNG2a");
                    var kind = Convert.ToInt32(ReadStored("qgriBv1ZZtL"));
                    var reader = new ContentFieldReader(editor);
                    var content = reader.Read(model);
                    prefabPageItems[id] = new
                    {
                        resourceId = id, name, iconPath = icon, nativeKind = kind,
                        content, readSummary = reader.Summary()
                    };
                }
                catch (Exception ex)
                {
                    prefabPageFailures[id] = new
                    {
                        resourceId = id, name = (object?)null, iconPath = (object?)null,
                        nativeKind = (int?)null,
                        content = (object?)new { unavailable = true, reason = "PREFAB_FIELD_READ:" + ex.GetType().Name },
                        readSummary = new { complete = false, truncated = false, errorCount = 1,
                            errors = new[] { "PREFAB_FIELD_READ:" + ex.GetType().Name } }
                    };
                }
            }
            prefabPageNextOffset = index + 1;
            // Yield to WPF after a complete resource. A single reader retains its own
            // bounded ten-second field budget and reports partial data explicitly.
            if (timer.ElapsedMilliseconds >= PrefabPageTimeSliceMs) break;
        }

        var items = prefabPageModels.Skip(offset).Take(prefabPageNextOffset - offset)
            .Select(row => prefabPageItems.TryGetValue(row.Id, out var item) ? item : prefabPageFailures[row.Id])
            .ToArray();
        int next = prefabPageNextOffset;
        bool done = next >= prefabPageModels.Count;
        var result = new
        {
            ok = true, status = "prefab-fields-page", snapshotId = prefabPageSnapshotId,
            snapshotStartedUtc = prefabPageStartedUtc, offset, nextOffset = next,
            total = prefabPageModels.Count, catalogTotal = prefabPageCatalogTotal, reusedResourceCount = prefabPageReusedCount,
            resumeApplied = prefabPageResumeApplied, reusedFieldsRevalidated = false, done, items,
            scope = "materialized-editor-prefab-business-fields", geometryVerified = false,
            sentToGame = false,
            resourceReadBehavior = new { existingSingletonLazyValueAccessed = true,
                editorResourceBindingGetterCalls = entityModels.Count,
                editorResourceBindingGetter = Resolve("t6ViSxlgnQ3"),
                excludedRuntimeBase = "hnRX5SXOfpHoFMcisZBH.sSJI8CXOTXcMB9gP3URF", registryAndBindingCollectionsEnumerated = true }
        };
        prefabPageCache.Add(offset, result);
        return result;
    }

    // Bridge entry point: each request advances exactly one page. Callers must poll
    // the same bridge request id after transport uncertainty.
    public object PrefabFieldsNext(string? resumePath = null)
    {
        if (prefabPageInitialized && prefabPageNextOffset >= prefabPageModels.Count && prefabPageCache.Count != 0)
        {
            using var identityCheck = EditorBindingProfile.ReopenContentReadBinding.Begin();
            return prefabPageCache.Values.Last();
        }
        uint offset = checked((uint)prefabPageNextOffset);
        return PrefabFieldsPageCore(new[] { offset, (uint)PrefabPageMaxSize }, resumePath);
    }
}
