using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

namespace Miliastra.EditorBridge;

internal sealed record PrefabScalarRow(string path, string type, string? value);

// Bounded projection only. Custom IEnumerable implementations are never executed.
internal sealed class PrefabFieldRead
{
    internal const int MaxDepth = 3, MaxCollectionItems = 4, MaxScalarRows = 90;
    const BindingFlags Fields = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
    internal readonly List<PrefabScalarRow> Rows = new();
    internal bool DepthLimitReached, CollectionLimitReached;
    internal int FieldReadErrorCount, CollectionReadErrorCount;
    internal int BclCollectionEnumerationCount, UnknownEnumerableFieldWalkCount;
    internal bool RowLimitReached => Rows.Count >= MaxScalarRows;
    internal bool Truncated => RowLimitReached || DepthLimitReached || CollectionLimitReached ||
        FieldReadErrorCount != 0 || CollectionReadErrorCount != 0 || UnknownEnumerableFieldWalkCount != 0;

    internal static bool IsVerifiedBclCollection(Type type)
    {
        if (type.IsArray) return true;
        if (!type.IsGenericType) return false;
        var definition = type.GetGenericTypeDefinition();
        return definition == typeof(List<>) || definition == typeof(Dictionary<,>) || definition == typeof(HashSet<>);
    }

    internal void Read(object? value) => Walk(value, "m", 0);

    void Walk(object? value, string path, int depth)
    {
        if (value == null || RowLimitReached) return;
        var type = value.GetType();
        if (type.IsPrimitive || type == typeof(string) || type.IsEnum || value is decimal)
        {
            // This whitelist has only runtime scalar implementations, no user override.
            Rows.Add(new PrefabScalarRow(path, type.Name, value.ToString()));
            return;
        }
        if (depth >= MaxDepth) { DepthLimitReached = true; return; }
        if (IsVerifiedBclCollection(type))
        {
            BclCollectionEnumerationCount++;
            try
            {
                int index = 0;
                foreach (var item in (IEnumerable)value)
                {
                    if (index >= MaxCollectionItems) { CollectionLimitReached = true; break; }
                    Walk(item, path + "[" + index + "]", depth + 1);
                    index++;
                    if (RowLimitReached) break;
                }
            }
            catch (Exception) { CollectionReadErrorCount++; }
            return;
        }
        // Includes subclasses of BCL collections: their enumerators may be overridden.
        // Report incomplete logical collection coverage even when field reads succeed.
        if (value is IEnumerable) UnknownEnumerableFieldWalkCount++;
        foreach (var field in type.GetFields(Fields))
        {
            object? child;
            try { child = field.GetValue(value); }
            catch (Exception) { FieldReadErrorCount++; continue; }
            Walk(child, path + "." + field.Name, depth + 1);
            if (RowLimitReached) return;
        }
    }
}
