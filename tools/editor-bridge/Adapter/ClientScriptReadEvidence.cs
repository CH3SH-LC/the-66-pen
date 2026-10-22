using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Reads only client-script models already materialized in the editor's resource
// registry. It deliberately does not enumerate folders or open model paths.
internal sealed partial class EditorAdapter
{
    const string ClientScriptModel = "EngUDvX1xc7DWWwYrrw1.vVUju1X1mM5GsVZX9XiF";
    const int ClientScriptRegistryNodeLimit = 4096;
    const int ClientScriptRegistryDepthLimit = 6;

    public object ClientScriptRootReadOnly()
    {
        RequireInitDispatcher();
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var manager = ExistingSingleton(Editor(), binding.Resolve("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var value = Field(manager, binding.Resolve("ejHXanGppqr"));
        if (value is not string root) throw new InvalidOperationException("CLIENT_SCRIPT_ROOT_TYPE");
        return new { ok = true, status = "client-script-root", configured = root.Length != 0,
            configuredRoot = root, fullyQualified = System.IO.Path.IsPathFullyQualified(root),
            storage = "existing-manager-field", directoryEnumerated = false,
            fileContentRead = false, sentToGame = false };
    }

    sealed record ClientScriptRow(uint Id, object Model, string? Name, string? Path);

    List<ClientScriptRow> ReadClientScriptRows(EditorBindingProfile.ReopenContentReadBinding binding, out int visited)
    {
        RequireInitDispatcher();
        var symbols = new Dictionary<string, string>(StringComparer.Ordinal);
        string Resolve(string legacy)
        {
            if (!symbols.TryGetValue(legacy, out var resolved))
                symbols.Add(legacy, resolved = binding.Resolve(legacy));
            return resolved;
        }

        var editor = Editor();
        string modelType = Resolve(ClientScriptModel);
        var root = Field(ExistingSingleton(editor,
            Resolve("ACE1cmiYtEdXg5frDhMg.Lpts7HiY2aTvYryR0pre")), Resolve("bwbixDw3yob"));
        var items = new List<ClientScriptRow>();
        var modelsById = new Dictionary<uint, object>();
        int nodeCount = 0;

        object? Stored(object model, string fieldLegacy, Type expected)
        {
            var wrapper = Field(model, Resolve(fieldLegacy));
            var storage = wrapper.GetType().GetField(Resolve("VpIiRZgdEln"), Fields)
                ?? throw new InvalidOperationException("CLIENT_SCRIPT_STORAGE_MISSING");
            var value = storage.GetValue(wrapper);
            if (value != null && !expected.IsInstanceOfType(value))
                throw new InvalidOperationException("CLIENT_SCRIPT_FIELD_TYPE:" + fieldLegacy);
            return value;
        }

        void Visit(object node, int depth)
        {
            if (++nodeCount > ClientScriptRegistryNodeLimit || depth > ClientScriptRegistryDepthLimit)
                throw new InvalidOperationException("CLIENT_SCRIPT_REGISTRY_LIMIT");

            var entries = Field(node, Resolve("JkmYibSuDZr"));
            if (entries is not IDictionary registry)
                throw new InvalidOperationException("CLIENT_SCRIPT_REGISTRY_DICTIONARY_TYPE");
            foreach (DictionaryEntry entry in registry)
            {
                if (entry.Value == null) throw new InvalidOperationException("CLIENT_SCRIPT_REGISTRY_NULL_MODEL");
                var model = entry.Value;
                if (!string.Equals(model.GetType().FullName, modelType, StringComparison.Ordinal)) continue;

                var wrappedId = Field(model, Resolve("eaRX1uExKei"));
                var rawId = Field(wrappedId, Resolve("VpIiRZgdEln"));
                var id = (uint)Field(rawId, Resolve("namiwGPRyPS"));
                if (entry.Key is not uint)
                    throw new InvalidOperationException("CLIENT_SCRIPT_REGISTRY_KEY_TYPE");
                if (modelsById.TryGetValue(id, out var prior))
                {
                    if (!ReferenceEquals(prior, model))
                        throw new InvalidOperationException("CLIENT_SCRIPT_DUPLICATE_ID_DIFFERENT_MODEL");
                    continue;
                }
                modelsById.Add(id, model);

                var name = (string?)Stored(model, "s2CX155XQre", typeof(string));
                var path = (string?)Stored(model, "vO3X1lCpaGJ", typeof(string));
                items.Add(new ClientScriptRow(id, model, name, path));
            }

            var children = Field(node, Resolve("pIxYiE5REC8"));
            if (children is not IDictionary childMap)
                throw new InvalidOperationException("CLIENT_SCRIPT_CHILD_DICTIONARY_TYPE");
            foreach (DictionaryEntry child in childMap)
            {
                if (child.Value == null) throw new InvalidOperationException("CLIENT_SCRIPT_NULL_CHILD");
                Visit(child.Value, depth + 1);
            }
        }

        Visit(root, 0);
        items.Sort((a, b) => a.Id.CompareTo(b.Id));
        visited = nodeCount;
        return items;
    }

    public object ClientScriptsReadOnly()
    {
        using var binding = EditorBindingProfile.ReopenContentReadBinding.Begin();
        var items = ReadClientScriptRows(binding, out int nodeCount);
        return new
        {
            ok = true,
            status = "client-script-catalog",
            scope = "materialized-editor-client-script-registry-models",
            directoryReadComplete = true,
            directoryReadErrors = Array.Empty<string>(),
            count = items.Count,
            items = items.Select(row => new { resourceId = row.Id, name = row.Name, path = row.Path, modelType = ClientScriptModel,
                nameStored = row.Name != null, pathStored = row.Path != null }).ToArray(),
            codeStoredInModel = false,
            contentRead = false,
            pathsUnresolved = true,
            emptySemantics = items.Count == 0 ? "materialized-registry-empty" : (string?)null,
            diskAbsenceProven = false,
            sentToGame = false,
            registryNodesVisited = nodeCount,
            registryTraversal = "existing-lazy-singleton;bounded-dictionary-fields-only"
        };
    }
}
