using System;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    private ClientScriptProbeState? clientScriptFileProbeOwner;
    private bool clientScriptFilePathEditSpent;
    private string? clientScriptFileCreatedPath;
    private string? clientScriptFileRequestedPath;

    // A basename only. No directories, absolute paths, ADS, device names, or implicit
    // normalization. This narrow probe changes a native resource reference, never disk.
    internal static string ValidateClientScriptFilePath(string value)
    {
        if (value.Length < 5 || value.Length > 128 || !value.EndsWith(".lua", StringComparison.Ordinal) ||
            value[0] == '.' || value.Contains("..", StringComparison.Ordinal))
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_INVALID");
        foreach (char c in value)
            if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') && !(c >= '0' && c <= '9') &&
                c != '_' && c != '-' && c != '.')
                throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_INVALID");
        var stem = value.Split('.')[0];
        if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase) ||
            (stem.Length == 4 && (stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) ||
                                 stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase)) && stem[3] >= '1' && stem[3] <= '9'))
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_INVALID");
        return value;
    }

    // Reject malformed explicit values; omission alone preserves the old default.
    internal static string? ReadClientScriptRelativePath(JsonElement request)
    {
        if (!request.TryGetProperty("relativePath", out var path)) return null;
        if (path.ValueKind != JsonValueKind.String)
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_TYPE");
        return ValidateClientScriptFilePath(path.GetString()!);
    }

    public object CreateClientScriptFileProbe(string? relativePath = null)
    {
        if (relativePath != null) ValidateClientScriptFilePath(relativePath);
        var (probe, rows, manager) = CheckClientScriptProbe();
        if (probe.CreateSpent || probe.DeleteSpent || rows.Count != 0)
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_CREATE_REFUSED");
        var path = relativePath ?? ValidateClientScriptFilePath(probe.Name + ".lua");
        var enumType = Editor().GetType(B("lsHpqNE7FeZinkCwmxHT.Bsw5mlE7cjIORHoZyCnp"), true)!;
        var method = manager.GetType().GetMethod(B("YOIXorEOgyd"), Fields, null,
            new[] { typeof(string), typeof(uint), enumType, typeof(string) }, null)
            ?? throw new InvalidOperationException("SCRIPT_FILE_PROBE_CREATE_METHOD_MISSING");
        clientScriptFileProbeOwner = probe;
        clientScriptFilePathEditSpent = false;
        clientScriptFileCreatedPath = path;
        clientScriptFileRequestedPath = path;
        probe.CreateSpent = true;
        method.Invoke(manager, new object[] { probe.Name, probe.FolderId, Enum.ToObject(enumType, probe.ScriptType), path });
        return new { ok = true, status = "client-script-create-file-invoked-not-confirmed",
            probeName = probe.Name, folderId = probe.FolderId, scriptType = probe.ScriptType,
            relativePath = path, gameConfirmed = false, saved = false, runtimeVerified = false };
    }

    public object SetClientScriptFileProbePath(string? relativePath = null)
    {
        if (relativePath != null) ValidateClientScriptFilePath(relativePath);
        var (probe, rows, manager) = CheckClientScriptProbe();
        var originalPath = clientScriptFileCreatedPath;
        if (!ReferenceEquals(clientScriptFileProbeOwner, probe) || !probe.CreateSpent || probe.DeleteSpent ||
            probe.Target == null || clientScriptFilePathEditSpent || rows.Count != 1 ||
            rows[0].Id != probe.Target.Id || rows[0].Name != probe.Name ||
            originalPath == null || !StringComparer.Ordinal.Equals(rows[0].Path, originalPath))
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_EDIT_REFUSED");
        var editedPath = relativePath ?? ValidateClientScriptFilePath(probe.Name + "_edited.lua");
        if (StringComparer.OrdinalIgnoreCase.Equals(editedPath, originalPath))
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_UNCHANGED");
        var method = manager.GetType().GetMethod(B("eduXoFyhNqC"), Fields, null,
            new[] { typeof(uint), typeof(string) }, null)
            ?? throw new InvalidOperationException("SCRIPT_FILE_PROBE_PATH_METHOD_MISSING");
        clientScriptFilePathEditSpent = true;
        clientScriptFileRequestedPath = editedPath;
        method.Invoke(manager, new object[] { rows[0].Id, editedPath });
        return new { ok = true, status = "client-script-path-edit-invoked-not-confirmed",
            resourceId = rows[0].Id, originalRelativePath = originalPath, requestedRelativePath = editedPath,
            gameConfirmed = false, saved = false, runtimeVerified = false };
    }

    public object InspectClientScriptFileProbe()
    {
        var (probe, rows, _) = CheckClientScriptProbe();
        if (!ReferenceEquals(clientScriptFileProbeOwner, probe) || !probe.CreateSpent || probe.DeleteSpent ||
            rows.Count != 1 || probe.Target == null || rows[0].Id != probe.Target.Id || rows[0].Name != probe.Name)
            throw new InvalidOperationException("SCRIPT_FILE_PROBE_OBSERVE_REFUSED");
        return new { ok = true, status = "client-script-file-editor-observation", resourceId = rows[0].Id,
            createdRelativePath = clientScriptFileCreatedPath, requestedRelativePath = clientScriptFileRequestedPath,
            observedRelativePath = rows[0].Path, pathEditInvoked = clientScriptFilePathEditSpent,
            editorPathObserved = StringComparer.Ordinal.Equals(rows[0].Path, clientScriptFileRequestedPath),
            gameConfirmed = false, saved = false, runtimeVerified = false };
    }
}
