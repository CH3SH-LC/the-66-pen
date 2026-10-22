using System;
using System.Collections;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Miliastra.EditorBridge;

// Read-only capture of the inbound 1020 external-asset list metadata.
// Source evidence, all static (nothing here was derived from a live call):
//   .runtime/editor-bridge/static-entity-research/external-list-packet.cs
//     vEnHOtazXHPsyyGjXSsD.MA16RWazQ9LeDPlTWK57 carries the repeated list field
//     ayMaz6Bampw (vcEKrVqwvSALUvyXdfF<UD6ZHGazfrqu5g0SUAsK>), which enumerates
//     as the entry sequence.
//   .runtime/editor-bridge/static-entity-research/external-list-entry.cs
//     GQKbJvazpE0KVC2xt3LB.UD6ZHGazfrqu5g0SUAsK has meta field HDqazeUfov9
//     (BOIKY5aZWJCjXkdfV8yp.BEJlt3aZgH4St3CZLsQ9) and source string yqeazItH1Lb.
//   .runtime/editor-bridge/static-entity-research/native-asset-proto.cs
//     BOIKY5aZWJCjXkdfV8yp.BEJlt3aZgH4St3CZLsQ9 has name field eh6arSOsY6i
//     (string) and kind field crWar27aWRf (enum tESw8rafXJKSRHUPAUIM).
//
// Deliberate scope limits enforced in this file:
//   * The entry source field yqeazItH1Lb is never read at all -- it is a
//     path/handle, and this evidence must not carry paths.
//   * Only whitelisted names are ever retained. Every other name that appears in
//     the list is folded into an aggregate per-kind count and then dropped; no
//     other name or text is stored anywhere.
//   * Kind text is only ever taken from an Enum, so a drifted contract cannot
//     smuggle arbitrary native text into the counts.
//   * Reading this metadata is not import acceptance. verified and importAllowed
//     stay false. This partial never sends to the game, never writes, never saves.
internal sealed partial class EditorAdapter
{
    static string ExternalListPacketType => B("vEnHOtazXHPsyyGjXSsD.MA16RWazQ9LeDPlTWK57");
    static string ExternalListField => B("ayMaz6Bampw");
    static string ExternalListEntryType => B("GQKbJvazpE0KVC2xt3LB.UD6ZHGazfrqu5g0SUAsK");
    static string ExternalListEntryMetaField => B("HDqazeUfov9");
    static string ExternalAssetMetaType => B("BOIKY5aZWJCjXkdfV8yp.BEJlt3aZgH4St3CZLsQ9");
    static string ExternalAssetMetaNameField => B("eh6arSOsY6i");
    static string ExternalAssetMetaKindField => B("crWar27aWRf");

    const string ExternalAssetCourseName = "MW_Static_Course_20260916";
    const int ExternalAssetSnapshotLimit = 8;
    const int ExternalAssetScanLimit = 4096;
    const int ExternalAssetOwnLimit = 64;

    static readonly Regex ExternalAssetTileName =
        new(@"\AMW_Static_P[0-5]_Tile[0-8]\z", RegexOptions.CultureInvariant);

    // Latest snapshot only; each accepted capture replaces the previous one.
    int externalAssetSnapshots;
    bool externalAssetSnapshotLimited;
    bool externalAssetTruncated;
    int externalAssetGeneration;
    DateTime? externalAssetObservedUtc;
    int externalAssetTotalEntriesScanned;
    Dictionary<string,int> externalAssetTypeCounts = new();
    List<object> externalAssetOwnAssets = new();

    // Called from ObservePacket for packet id 1020 only. A payload of any other
    // type, or null, leaves every evidence field exactly as it was.
    internal void CaptureExternalAssets(object? payload)
    {
        if (payload == null || payload.GetType().FullName != ExternalListPacketType) return;

        // Per-adapter snapshot budget: past the limit we stop processing and only
        // record that we stopped.
        if (externalAssetSnapshots >= ExternalAssetSnapshotLimit){externalAssetSnapshotLimited = true;return;}

        var entries = ExternalAssetField(payload, ExternalListField, "packet");
        if (entries is not IEnumerable list)
            throw new InvalidOperationException("EXTERNAL_ASSET_LIST_NOT_ENUMERABLE:" + ExternalListField);

        // The snapshot is built locally and published only once complete, so a
        // rejected or malformed payload never leaves a half-written snapshot.
        var typeCounts = new Dictionary<string,int>();
        var own = new List<object>();
        int scanned = 0;
        bool truncated = false;
        foreach (var entry in list)
        {
            if (scanned >= ExternalAssetScanLimit || own.Count >= ExternalAssetOwnLimit){truncated = true;break;}
            if (entry == null) throw new InvalidOperationException("EXTERNAL_ASSET_ENTRY_NULL");
            if (entry.GetType().FullName != ExternalListEntryType)
                throw new InvalidOperationException("EXTERNAL_ASSET_ENTRY_TYPE_MISMATCH:" + entry.GetType().FullName);

            var meta = ExternalAssetField(entry, ExternalListEntryMetaField, "entry");
            if (meta.GetType().FullName != ExternalAssetMetaType)
                throw new InvalidOperationException("EXTERNAL_ASSET_META_TYPE_MISMATCH:" + meta.GetType().FullName);

            // yqeazItH1Lb (entry source) is intentionally never read.
            var rawName = ExternalAssetField(meta, ExternalAssetMetaNameField, "meta");
            if (rawName is not string name)
                throw new InvalidOperationException("EXTERNAL_ASSET_NAME_NOT_STRING:" + ExternalAssetMetaNameField);
            var rawKind = ExternalAssetField(meta, ExternalAssetMetaKindField, "meta");
            if (rawKind is not Enum kind)
                throw new InvalidOperationException("EXTERNAL_ASSET_KIND_NOT_ENUM:" + ExternalAssetMetaKindField);

            scanned++;
            var kindName = kind.ToString();
            typeCounts[kindName] = typeCounts.GetValueOrDefault(kindName) + 1;
            // Zero-based index of the entry inside the actual native list.
            if (IsOwnExternalAsset(name)) own.Add(new {index = scanned - 1, name, type = kindName, typeValue = Convert.ToInt32(kind)});
        }

        externalAssetSnapshots++;
        externalAssetGeneration++;
        externalAssetObservedUtc = DateTime.UtcNow;
        externalAssetTotalEntriesScanned = scanned;
        externalAssetTypeCounts = typeCounts;
        externalAssetOwnAssets = own;
        externalAssetTruncated = truncated;
    }

    static bool IsOwnExternalAsset(string name) =>
        string.Equals(name, ExternalAssetCourseName, StringComparison.Ordinal) || ExternalAssetTileName.IsMatch(name);

    // Wraps the existing Field helper so a missing required field surfaces with its
    // role and name instead of being silently replaced by a fallback.
    object ExternalAssetField(object obj, string name, string role)
    {
        try{return Field(obj, name);}
        catch(Exception ex) when (ex is MissingFieldException or InvalidOperationException)
        {throw new InvalidOperationException("EXTERNAL_ASSET_REQUIRED_FIELD_MISSING:" + role + ":" + name, ex);}
    }

    public object ExternalAssetEvidence()
    {
        return new
        {
            ok = true,
            // List metadata is not import acceptance.
            verified = false,
            importAllowed = false,
            captured = externalAssetSnapshots > 0,
            generation = externalAssetGeneration,
            observedUtc = externalAssetObservedUtc,
            snapshots = externalAssetSnapshots,
            snapshotLimit = ExternalAssetSnapshotLimit,
            snapshotLimited = externalAssetSnapshotLimited,
            truncated = externalAssetTruncated,
            totalEntriesScanned = externalAssetTotalEntriesScanned,
            scanLimit = ExternalAssetScanLimit,
            ownAssetLimit = ExternalAssetOwnLimit,
            typeCounts = externalAssetTypeCounts,
            ownAssets = externalAssetOwnAssets.ToArray(),
            nameRule = "MW_Static_Course_20260916 or ^MW_Static_P[0-5]_Tile[0-8]$",
            payloadType = ExternalListPacketType,
            pathsCaptured = false,
            sentToGame = false,
            scope = "external-asset-metadata-only",
            notice = "Metadata presence and name/type only; verified and importAllowed stay false until the game accepts an import."
        };
    }
}
