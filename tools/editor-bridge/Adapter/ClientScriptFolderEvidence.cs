using System;
using System.Collections;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    (object Model, uint Id, int ScriptType) ReadClientScriptProbeFolder(EditorBindingProfile.ReopenContentReadBinding binding, bool requireEmpty = false)
    {
        string Resolve(string symbol) => binding.Resolve(symbol);
        var manager = ExistingSingleton(Editor(), Resolve("VpuuVGLgPg1T2WVOOaB3.rxEh1kLgpmbIxPxJtEbY"));
        var categories = Field(manager, Resolve("mHNLglmulVB")) as IDictionary
            ?? throw new InvalidOperationException("SCRIPT_FOLDER_STORAGE_TYPE");
        if (categories.Count > 256) throw new InvalidOperationException("SCRIPT_FOLDER_STORAGE_LIMIT");
        var data = categories[69] ?? throw new InvalidOperationException("SCRIPT_FOLDER_CATEGORY_NOT_LOADED");
        if (data.GetType().FullName != Resolve("QMk3w3LWa1H071tYYMsy.EMWIS2LW7gimYorCSAJZ"))
            throw new InvalidOperationException("SCRIPT_FOLDER_DATA_TYPE");
        var kind = Field(data, Resolve("EVeLg2urAZj"));
        if (kind.GetType().FullName != Resolve("tkvOndLluGfYKDDusXdN.k8YsY8LlfZTdUYkZusUJ") || Convert.ToInt32(kind) != 69)
            throw new InvalidOperationException("SCRIPT_FOLDER_CATEGORY_MISMATCH");
        var allItems = Field(data, Resolve("yJFLgBq6IsW")) as IDictionary
            ?? throw new InvalidOperationException("SCRIPT_FOLDER_ITEMS_TYPE");
        if (requireEmpty && allItems.Count != 0)
            throw new InvalidOperationException("SCRIPT_PROBE_NATIVE_BASELINE_NOT_EMPTY");
        // Official unclassified AS1 root. syLXPpN7ppA copies its ID to RaTgn;
        // xqrjtg40smf passes that exact value to kqaXokY6uBT. No UI initialization.
        var folder = Field(data, Resolve("JU3LgZ016RD"));
        if (folder.GetType().FullName != Resolve("rOCVlkLlzJruRpo9aO9F.AS1EsmLl3djOTOaRlwB9") ||
            !ReferenceEquals(Field(folder, Resolve("ewWLWpQnWdu")), data))
            throw new InvalidOperationException("SCRIPT_FOLDER_OWNER_MISMATCH");
        if (Field(folder, Resolve("xQoLWQReGSf")) is not uint id)
            throw new InvalidOperationException("SCRIPT_FOLDER_ID_TYPE");
        return (folder, id, 0); // ClientScriptUI configuration selects script type 0.
    }
}
