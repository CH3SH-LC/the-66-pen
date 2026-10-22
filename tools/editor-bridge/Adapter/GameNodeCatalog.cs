using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

// Read-only node-definition catalogue for an explicitly requested, bounded id list.
//
// Same category filter and the same proven field readers as FinishNodeCatalog.cs, and the
// same snapshot shape, so a caller can compare a definition across requests. No native
// constructor, no graph mutation, no send, no file write.
//
// This exists because the finish-node catalogue is deliberately limited to the ids the
// finish graph already uses. Building a different gameplay graph needs the real pin
// signatures of other nodes; guessing them is exactly the failure this project keeps
// recording. Reading them is bounded and side-effect free.
internal sealed partial class EditorAdapter
{
    // Lexical discovery over actual graph definitions, not playback or a claim
    // that a matching node has any particular runtime semantics. Full category
    // identity is essential: client/server domains can reuse the same node id.
    public object AudioRuntimeNodeCatalog()
    {
        const int limit = 64;
        string[] terms = { "音效", "音乐", "声音", "特效", "Sound", "Music", "Audio", "Effect" };
        var domain = Resources().Where(r => r.Kind == 6 && r.Category.Length == 4 &&
            r.Category[0] == 10001 && r.Category[2] == 22000 && r.Category[3] == 0).ToArray();
        int unreadLabelCount = 0;
        var matches = new List<Resource>();
        foreach (var resource in domain)
        {
            var name = Stored(resource.Model, B("DsBKEwvlwAl"));
            var description = Stored(resource.Model, B("HM9KEypghgm"));
            if (name is not string && description is not string) { unreadLabelCount++; continue; }
            if (!terms.Any(term => (name as string)?.Contains(term, StringComparison.OrdinalIgnoreCase) == true ||
                (description as string)?.Contains(term, StringComparison.OrdinalIgnoreCase) == true)) continue;
            if (resource.Id == 0) throw new InvalidOperationException("AUDIO_NODE_ID_INVALID");
            matches.Add(resource);
        }
        // ResourcesCore already deduplicates kind/category/id before returning.
        // Raw registry aliases and conflicting model references are not observable here.
        var ordered = matches.OrderBy(r => string.Join(",", r.Category), StringComparer.Ordinal)
            .ThenBy(r => r.Id).ToArray();
        return new {
            ok = true, status = "audio-runtime-node-catalog-read-only",
            selectionTerms = terms, selectionIsSemanticProof = false,
            selectionMeaning = "lexical candidates from existing runtime graph definitions; inspect actual pins before authoring",
            deduplicatedDomainCount = domain.Length, unreadLabelCount,
            rawRegistryAliasValidation = "unknown", rawModelConflictValidation = "unknown",
            total = ordered.Length, limit, truncated = ordered.Length > limit,
            nodeCount = Math.Min(ordered.Length, limit),
            nodes = ordered.Take(limit).Select(r => new {
                category = r.Category, id = r.Id,
                definition = FinishNodeSnapshot(r, 256) }).ToArray(),
            nativeConstructorsInvoked = false, graphModified = false, sentToGame = false,
            nativeReadScope = "shared Resources binding getter and existing pin-definition getter; collection enumeration",
            runtimeVerified = false, persistentSaveVerified = false, playtestVerified = false
        };
    }

    const int NodeDefinitionQueryLimit = 64;

    public object NodeDefinitions(uint[] ids)
    {
        if (ids == null || ids.Length == 0)
            throw new InvalidOperationException("NODE_QUERY_EMPTY");
        if (ids.Length > NodeDefinitionQueryLimit)
            throw new InvalidOperationException("NODE_QUERY_TOO_LARGE:" + ids.Length);

        var unique = ids.Distinct().ToArray();
        var byId = Resources().Where(r => r.Kind == 6 && r.Category.SequenceEqual(FinishCategory))
            .GroupBy(r => r.Id).ToDictionary(g => g.Key, g => g.First());
        var missing = unique.Where(id => !byId.ContainsKey(id)).ToArray();
        if (missing.Length != 0)
            throw new InvalidOperationException("NODE_DEFINITION_MISSING:" + string.Join(",", missing));

        return new
        {
            ok = true,
            status = "node-definitions-read-only",
            requestedIds = unique,
            nodeCount = unique.Length,
            nodes = unique.Select(id => FinishNodeSnapshot(byId[id])).ToArray(),
            nativeConstructorsInvoked = false,
            graphModified = false,
            sentToGame = false,
            persistentSaveVerified = false,
            playtestVerified = false
        };
    }
    // Full category identity is retained: client definition IDs are shared across
    // graph domains. This query never chooses one variant as a server definition.
    public object NodeDefinitionVariants(uint[] ids)
    {
        if (ids == null || ids.Length == 0)
            throw new InvalidOperationException("NODE_QUERY_EMPTY");
        if (ids.Length > NodeDefinitionQueryLimit || ids.Any(id => id == 0))
            throw new InvalidOperationException("NODE_QUERY_IDS_INVALID");
        var unique = ids.Distinct().ToArray();
        var selected = Resources().Where(r => r.Kind == 6 &&
            r.Category.Length == 4 && r.Category[0] == 10001 &&
            r.Category[2] == 22000 && r.Category[3] == 0 && unique.Contains(r.Id)).ToArray();
        var missing = unique.Where(id => !selected.Any(r => r.Id == id)).ToArray();
        if (missing.Length != 0)
            throw new InvalidOperationException("NODE_DEFINITION_MISSING:" + string.Join(",", missing));
        var variants = selected.GroupBy(r => string.Join(",", r.Category) + ":" + r.Id).ToArray();
        // Multiple registry paths may alias one object. Different objects with the
        // same identity require reconciliation instead of silently selecting First().
        if (variants.Any(g => g.Any(r => !ReferenceEquals(r.Model, g.First().Model))))
            throw new InvalidOperationException("NODE_DEFINITION_IDENTITY_CONFLICT");
        if (variants.Length > 256)
            throw new InvalidOperationException("NODE_VARIANT_QUERY_TOO_LARGE");
        return new {
            ok = true, status = "node-definition-variants-read-only",
            requestedIds = unique, requestedIdCount = unique.Length,
            variantCount = variants.Length, registryMatchCount = selected.Length,
            variants = variants.OrderBy(g => g.First().Id).ThenBy(g => g.Key)
                .Select(g => new { category = g.First().Category, id = g.First().Id,
                    registryReferences = g.Count(), definition = FinishNodeSnapshot(g.First(), 256) }).ToArray(),
            nativeConstructorsInvoked = false, graphModified = false, sentToGame = false,
            persistentSaveVerified = false, playtestVerified = false
        };
    }

}
