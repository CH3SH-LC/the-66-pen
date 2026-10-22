using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Controls.Primitives;
using System.Windows.Input;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    sealed class SceneFolderResolution
    {
        internal bool Ok, Complete;
        internal string Status = "scene-folder-not-resolved";
        internal int Matches, NodesVisited, ManagerCount, RegistryModelCount;
        internal uint FolderId;
        internal object? Node, Resource, Manager;
        internal object Evidence() => new { ok = Ok, status = Status, complete = Complete,
            matches = Matches, nodesVisited = NodesVisited, managerCount = ManagerCount,
            registryModelCount = RegistryModelCount, folderId = FolderId,
            semanticTagPath = new uint[] { 40000, 40003, 41101, 40004 }, containerType = 3,
            identity = "registry tag owner reference and current runtime resource key", invoked = false };
    }

    // The scene folder registers at [40000,40003,41101,40004] (HLIXMePaMI6).
    // [40000,40003] is only a tag prefix with no direct owner. Its owner object ID is
    // session allocated, not the terminal tag number. Read the exact registry path and
    // complete category tree; never search captions or invoke native getters/enumerators.
    static SceneFolderResolution ResolveSceneFolderCore(object registryRoot, IReadOnlyList<object> managers,
        Func<object, string, object?> read, Type folderType, Type modelType, int nodeLimit = 4096)
    {
        var result = new SceneFolderResolution { ManagerCount = managers.Count };
        SceneFolderResolution Fail(string status) { result.Status = status; return result; }
        if (managers.Count != 1) return Fail("scene-resource-manager-not-unique");
        object registryNode = registryRoot;
        foreach (uint tag in new uint[] { 40000, 40003, 41101, 40004 })
        {
            if (read(registryNode, "pIxYiE5REC8") is not IDictionary children || !children.Contains(tag) || children[tag] == null)
                return Fail("scene-category-tag-missing");
            registryNode = children[tag]!;
        }
        if (read(registryNode, "JkmYibSuDZr") is not IDictionary owners)
            return Fail("scene-category-owners-invalid");
        result.RegistryModelCount = owners.Count;
        if (owners.Count != 1) return Fail("scene-category-owner-not-unique");
        object? owner = null;
        foreach (DictionaryEntry entry in owners)
        {
            result.FolderId = Convert.ToUInt32(entry.Key);
            owner = entry.Value;
        }
        if (owner == null || owner.GetType() != modelType || result.FolderId == 0)
            return Fail("scene-category-owner-invalid");
        result.Manager = managers[0];
        var category = read(result.Manager, "lleKeqZguxf");
        var root = category == null ? null : read(category, "JiLKB1xsFfb");
        if (root == null) return Fail("scene-category-tree-missing");
        var queue = new Queue<object>(); queue.Enqueue(root);
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance);
        while (queue.Count != 0)
        {
            if (result.NodesVisited >= nodeLimit) return Fail("scene-category-tree-node-limit");
            var node = queue.Dequeue();
            if (!seen.Add(node)) return Fail("scene-category-tree-repeated-node");
            result.NodesVisited++;
            if (node.GetType() != folderType) return Fail("scene-category-tree-node-type-mismatch");
            var value = read(node, "vQPKy8Qu9ev");
            var key = value == null ? null : read(value, "y30KBtqRTpg");
            if (value == null || key == null) return Fail("scene-category-tree-resource-missing");
            if (Convert.ToInt32(read(value, "containerType")) != 3)
                return Fail("scene-category-tree-container-mismatch");
            var raw = read(node, "DKWKyl77ARt");
            uint id = Convert.ToUInt32(read(key, "ol3iwzG1HRm"));
            bool sameOwner = ReferenceEquals(raw, owner);
            if (sameOwner || id == result.FolderId)
            {
                if (!sameOwner || id != result.FolderId || Convert.ToInt32(read(key, "yKiiwIS6frK")) != 1)
                    return Fail("scene-category-owner-key-mismatch");
                result.Matches++; result.Node = node; result.Resource = value;
            }
            var items = read(node, "gnkKXFN3UAC");
            if (items == null) return Fail("scene-category-items-missing");
            var childList = read(items, "jN4igqhC7U3");
            // The native lifecycle leaves a null backing list for an empty collection.
            if (childList == null) continue;
            if (childList is not IList list || !childList.GetType().IsGenericType ||
                childList.GetType().GetGenericTypeDefinition() != typeof(List<>))
                return Fail("scene-category-items-list-invalid");
            if (list.Count > nodeLimit - result.NodesVisited - queue.Count)
                return Fail("scene-category-tree-node-limit");
            foreach (var child in list)
            {
                if (child == null) return Fail("scene-category-tree-null-child");
                queue.Enqueue(child);
            }
        }
        result.Complete = true;
        if (result.Matches != 1) return Fail("scene-folder-not-unique");
        result.Ok = true; result.Status = "scene-folder-resolved";
        return result;
    }

    SceneFolderResolution ResolveSceneResourceFolder()
    {
        try
        {
            var assembly = Editor();
            string rootName = B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH");
            var managers = new List<object>();
            var seen = new HashSet<object>(ReferenceEqualityComparer.Instance);
            var app = System.Windows.Application.Current;
            if (app != null)
                foreach (System.Windows.Window window in app.Windows)
                    if (window.DataContext is object panel && panel.GetType().FullName == rootName && seen.Add(panel))
                        managers.Add(Field(panel, B("l66ueROUqVn")));
            object? Read(object target, string name)
            {
                string mapped = name == "containerType" ? name : B(name);
                for (var type = target.GetType(); type != null; type = type.BaseType)
                    if (type.GetField(mapped, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly) is FieldInfo field)
                        return field.GetValue(target);
                throw new MissingFieldException(mapped);
            }
            return ResolveSceneFolderCore(Field(ExistingSingleton(assembly, Registry), B("bwbixDw3yob")), managers, Read,
                assembly.GetType(B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7"), true)!,
                assembly.GetType(B("eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF"), true)!);
        }
        catch (Exception ex)
        {
            return new SceneFolderResolution { Status = "scene-folder-observation-failed:" + ex.GetType().Name };
        }
    }

    // Calls only the native navigation method on the proven current scene node.
    public object OpenSceneResourceFolder()
    {
        var resolution = ResolveSceneResourceFolder();
        if (!resolution.Ok)
            return new { ok = false, status = resolution.Status, matches = resolution.Matches,
                invoked = false, resolution = resolution.Evidence() };
        var chosen = resolution.Node!;
        var method = chosen.GetType().GetMethod(B("SyTKwRXfIBP"), BindingFlags.Instance | BindingFlags.Public)!;
        var result = method.Invoke(chosen, Array.Empty<object>());
        return new { ok = true, status = "native-folder-navigation-invoked", matches = resolution.Matches,
            folderId = resolution.FolderId, containerType = 3, nativeResult = result,
            resolution = resolution.Evidence(), invoked = true,
            pendingSelection = chosen.GetType().GetField(B("VLvKyWo9ys1"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(chosen),
            notice = "Invocation only; requires independent frontend readback." };
    }

    public object LoadSceneResourceModel(bool labCube = false)
    {
        string rootName = B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH");
        uint folderId = 313584u; // Historical lab-cube route remains pinned to its own object.
        object? manager = null, resource = null;
        int matches = 0;
        SceneFolderResolution? resolution = null;
        if (!labCube)
        {
            resolution = ResolveSceneResourceFolder();
            if (!resolution.Ok)
                return new { ok = false, status = resolution.Status, invoked = false, resolution = resolution.Evidence() };
            manager = resolution.Manager; resource = resolution.Resource;
            folderId = resolution.FolderId; matches = resolution.Matches;
        }
        else foreach (var (node, path) in WalkEditorGraph(20000, 14, true, rootName))
        {
            var type = node.GetType();
            if (type.FullName == rootName)
                manager = type.GetField(B("l66ueROUqVn"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node);
            if (type.FullName != (labCube ? B("kJ49ujK21bL1R4fN9jpN.NNwa8GK28oPifmneADs0") : B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7"))) continue;
            var value = type.GetField(labCube ? B("nDdKtzI6RIf") : B("vQPKy8Qu9ev"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node)!;
            var key = value.GetType().GetField(B("y30KBtqRTpg"))!.GetValue(value)!;
            if (Convert.ToInt32(value.GetType().GetField("containerType")!.GetValue(value)) != 3 ||
                Convert.ToInt32(key.GetType().GetField(B("yKiiwIS6frK"))!.GetValue(key)) != 1 ||
                (uint)key.GetType().GetField(B("ol3iwzG1HRm"))!.GetValue(key)! != folderId) continue;
            matches++; resource = value;
        }
        if (matches != 1 || manager == null || resource == null)
            return new { ok = false, status = "resource-model-not-unique", matches, invoked = false };
        var assembly = Editor();
        var baseType = assembly.GetType(B("tfJMcmKyJVG5gS88nDsv.MLx0fWKyr4g90EjGRFNN"), true)!;
        var lifeType = assembly.GetType(B("ECtXhyiqQOjd5sDAJFrf.n7sVVSiqWIIk9pSX0G7q"), true)!;
        var list = baseType.GetField(B("fLBKeg6yjy3"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(manager);
        var stateField = lifeType.GetField(B("TiyighrQs5J"), BindingFlags.Instance | BindingFlags.NonPublic)!;
        int managerState = Convert.ToInt32(stateField.GetValue(manager));
        int listState = list == null ? -1 : Convert.ToInt32(stateField.GetValue(list));
        if (managerState != 1 || listState != 1)
            return new { ok = false, status = "resource-model-not-active", managerState, listState, invoked = false };
        var method = manager.GetType().GetMethod(B("vF1Yj4iJnve"), BindingFlags.Instance | BindingFlags.NonPublic,
            null, new[] { resource.GetType() }, null)!;
        method.Invoke(manager, new[] { resource });
        return new { ok = true, status = "native-resource-model-load-invoked", managerState, listState,
            folderId, invoked = true, resolution = resolution?.Evidence(), notice = "Requires independent resource-path readback." };
    }

    public object FocusLabCubeFromFrontend()
    {
        object? chosen = null, resource = null;
        int matches = 0;
        foreach (var (node, path) in WalkEditorGraph(20000, 14, true,
                     B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH")))
        {
            var type = node.GetType();
            if (type.FullName != B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7")) continue;
            var value = Field(node, B("vQPKy8Qu9ev"));
            var key = Field(value, B("y30KBtqRTpg"));
            if (Convert.ToInt32(Field(value, "containerType")) != 4 ||
                Convert.ToInt32(Field(key, B("yKiiwIS6frK"))) != 1 ||
                (uint)Field(key, B("ol3iwzG1HRm")) != 313584u) continue;
            var raw = Field(node, B("DKWKyl77ARt"));
            var reference = Field(Field(Field(raw, B("q5nie3xqPAT")), B("VpIiRZgdEln")), B("w8Yiy4sBsZi"));
            if ((uint)Field(reference, B("namiwGPRyPS")) != 1077936130u ||
                (uint)Field(reference, B("oLyiwZX255H")) != 10007u)
                return new { ok = false, status = "lab-cube-reference-mismatch", invoked = false };
            chosen = node; resource = value; matches++;
        }
        if (matches != 1 || chosen == null || resource == null)
            return new { ok = false, status = "lab-cube-front-end-not-unique", matches, invoked = false };
        var method = resource.GetType().GetMethod(B("sM5KBF555gu"), BindingFlags.Instance | BindingFlags.Public)!;
        var result = method.Invoke(resource, new[] { chosen });
        return new { ok = true, status = "native-focus-path-invoked", entityId = 1077936130u,
            nativeResult = result, invokedUtc = DateTimeOffset.UtcNow,
            notice = "Game focus effect and RPC delivery require independent verification; no transform or save requested." };
    }

    // Observation only: no delegate invocation, command execution, CanExecute,
    // application property getters, RPC, or model field writes.
    public object InspectFrontendCommands()
    {
        var sceneFolderResolution = ResolveSceneResourceFolder().Evidence();
        const int nodeLimit = 20000, depthLimit = 14, recordLimit = 128, fieldLimit = 16;
        var records = new List<object>();
        var resourcePaths = new List<object>();
        var resourceFolders = new List<object>();
        var folderDetails = new List<object>();
        var externalImportModels = new List<object>();
        int externalImportModelsSeen = 0;
        int resourcePathsSeen = 0;
        var errors = new Dictionary<string, int>();
        var signatures = new HashSet<string>();
        int frameworkTargetsSkipped = 0, duplicatesSkipped = 0;
        var editorAssembly = Editor();
        var watch = Stopwatch.StartNew();
        int matched = 0, limitedFields = 0, seen = 0;
        bool timeLimited = false, recordsLimited = false;
        void Error(Exception ex)
        {
            var name = ex.GetType().Name;
            errors[name] = errors.TryGetValue(name, out int n) ? n + 1 : 1;
        }
        static string Clip(string? text, int limit = 240)
            => text == null ? "" : text.Length <= limit ? text : text.Substring(0, limit);

        foreach (var (node, path) in WalkEditorGraph(nodeLimit, depthLimit, includePrivateBaseFields: true, rootType: B("gyj3OSueTNTdJeQL0yyH.tyZNMjueXM5Cae1EUsbH")))
        {
            seen++;
            if (watch.ElapsedMilliseconds > 2500) { timeLimited = true; break; }
            var type = node.GetType();
            if (type.FullName == B("j6TdHcKsbueiEjwxIuIh.XyJDNjKsOwEHhOe9s362"))
            {
                externalImportModelsSeen++;
                if (externalImportModels.Count < 32)
                {
                    try { externalImportModels.Add(new { path = Clip(path, 700),
                        kind = DescribeFrontendFields(Field(node, B("oOmKsYEg9Sf")), 2),
                        nativeIndex = DescribeFrontendFields(Field(node, B("VqcKsDD1ovV")), 2),
                        reference = DescribeFrontendFields(Field(node, B("JkCKs76rIZR")), 3),
                        name = DescribeFrontendFields(Field(node, B("QkYKsxMS8Ay")), 2) }); }
                    catch (Exception ex) { Error(ex); }
                }
            }
            if (type.FullName == B("oNrycNKwYdnl6qddxTWS.uFMyy7Kw7Pe8xVfHEqF7") && resourceFolders.Count < 128)
            {
                try
                {
                    var value = type.GetField(B("vQPKy8Qu9ev"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node)!;
                    var key = value.GetType().GetField(B("y30KBtqRTpg"))!.GetValue(value)!;
                    var caption = type.GetField(B("PrbKyKOvNnD"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node);
                    var textField = Editor().GetType(B("O1XvBAKJpNB6IglU2s7G.MvMDsBKJfguRrUWndHFQ"), true)!
                        .GetField(B("WYHKJIbqTvC"), BindingFlags.Instance | BindingFlags.NonPublic)!;
                    uint folderNumber = (uint)key.GetType().GetField(B("ol3iwzG1HRm"))!.GetValue(key)!;
                    if (folderNumber == 313584 && folderDetails.Count < 4)
                        folderDetails.Add(new { path = Clip(path, 700),
                            rawFolder = DescribeFrontendFields(type.GetField(B("DKWKyl77ARt"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node), 4) });
                    resourceFolders.Add(new { path = Clip(path, 700),
                        name = Clip(caption == null ? null : textField.GetValue(caption) as string),
                        containerType = Convert.ToInt32(value.GetType().GetField("containerType")!.GetValue(value)),
                        objectKind = Convert.ToInt32(key.GetType().GetField(B("yKiiwIS6frK"))!.GetValue(key)),
                        objectId = (uint)key.GetType().GetField(B("ol3iwzG1HRm"))!.GetValue(key)! });
                }
                catch (Exception ex) { Error(ex); }
            }
            if (type.FullName == B("VJ8TQEKBWBew1bEgiZHx.kg9jHSKBgsfObR2IXdPf"))
            {
                resourcePathsSeen++;
                if (resourcePaths.Count < 256)
                try
                {
                    var key = type.GetField(B("y30KBtqRTpg"))!.GetValue(node)!;
                    var keyType = key.GetType();
                    resourcePaths.Add(new { path = Clip(path, 700),
                        containerType = Convert.ToInt32(type.GetField("containerType")!.GetValue(node)),
                        objectKind = Convert.ToInt32(keyType.GetField(B("yKiiwIS6frK"))!.GetValue(key)),
                        objectId = (uint)keyType.GetField(B("ol3iwzG1HRm"))!.GetValue(key)! });
                }
                catch (Exception ex) { Error(ex); }
            }
            var fields = new List<object>();
            int matchingFields = 0;
            string label = "";
            for (var current = type; current != null && current.Assembly == editorAssembly;
                 current = current.BaseType)
            {
                FieldInfo[] declared;
                try { declared = current.GetFields(BindingFlags.Instance | BindingFlags.Public |
                    BindingFlags.NonPublic | BindingFlags.DeclaredOnly); }
                catch (Exception ex) { Error(ex); continue; }
                foreach (var field in declared)
                {
                    // Read only the known menu label, not arbitrary user strings.
                    if (field.Name == MenuLabelField && field.FieldType == typeof(string))
                    {
                        try { label = Clip(field.GetValue(node) as string); }
                        catch (Exception ex) { Error(ex); }
                    }
                    if (!typeof(Delegate).IsAssignableFrom(field.FieldType) &&
                        !typeof(ICommand).IsAssignableFrom(field.FieldType) &&
                        field.FieldType.FullName != B("fJUttEisYVpWIYUDJRG6.C2p9m0is7AqTMLMShDni")) continue;
                    object? value;
                    try { value = field.GetValue(node); }
                    catch (Exception ex) { Error(ex); continue; }
                    if (value == null) continue;
                    string wrapperType = "";
                    if (value.GetType().FullName == B("fJUttEisYVpWIYUDJRG6.C2p9m0is7AqTMLMShDni"))
                    {
                        wrapperType = value.GetType().FullName!;
                        try { value = value.GetType().GetField(B("g8visd0mvj6"), BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(value); }
                        catch (Exception ex) { Error(ex); continue; }
                        if (value == null) continue;
                    }
                    if (fields.Count >= fieldLimit) { matchingFields++; continue; }
                    if (value is Delegate callback)
                    {
                        var targets = new List<object>();
                        var invocationList = callback.GetInvocationList();
                        for (int i = 0; i < invocationList.Length && i < 32; i++)
                        {
                            var d = invocationList[i];
                            var method = d.Method;
                            if (method.DeclaringType?.Assembly != editorAssembly) { frameworkTargetsSkipped++; continue; }
                            string signature = type.FullName + "|" + field.Name + "|" + method.DeclaringType.FullName + "|" + method.Name;
                            if (!signatures.Add(signature)) { duplicatesSkipped++; continue; }
                            if (targets.Count >= 4) break;
                            targets.Add(new { declaringType = method.DeclaringType?.FullName,
                                method = method.Name, targetType = d.Target?.GetType().FullName,
                                returnType = method.ReturnType.FullName });
                        }
                        if (targets.Count == 0) continue;
                        matchingFields++;
                        fields.Add(new { field = field.Name, declaredOn = current.FullName,
                            kind = "delegate", wrapperType, targets, invocationCount = invocationList.Length,
                            targetsTruncated = invocationList.Length > 4 });
                    }
                    else fields.Add(new { field = field.Name, declaredOn = current.FullName,
                        kind = "command-metadata-only", commandType = value.GetType().FullName });
                }
            }
            if (type.FullName == B("z6bJHqKCG1FwPiBJfDLJ.M2bF6wKCnSaAHlvJtY0X") && folderDetails.Count < 8)
                folderDetails.Add(new { path = Clip(path, 700),
                    filter = DescribeFrontendFields(type.GetField(B("S6dKSIVxp0g"), BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(node), 2) });
            object? selection = null;
            if (node is Selector selector)
            {
                try { selection = new { selectedIndex = selector.SelectedIndex,
                    selectedType = selector.SelectedItem?.GetType().FullName }; }
                catch (Exception ex) { Error(ex); }
            }
            if (fields.Count == 0 && label.Length == 0 && selection == null) continue;
            matched++;
            if (matchingFields > fieldLimit) limitedFields++;
            if (records.Count >= recordLimit) { recordsLimited = true; continue; }
            records.Add(new { path = Clip(path, 700), type = type.FullName, label,
                fields, fieldsTruncated = matchingFields > fieldLimit, selection });
        }
        // External import models can remain outside the visible resource subtree.
        // Follow only the proven registry dictionaries; never instantiate models.
        var registryExternalModels = new List<object>();
        var registryExternalFolders = new List<object>();
        int registryNodes = 0, registryEntries = 0, registryExternalSeen = 0;
        bool registryLimited = false;
        var registryWatch = Stopwatch.StartNew();
        try
        {
            void VisitExternalRegistry(object node, int depth, string path)
            {
                if (++registryNodes > 4096 || depth > 6 || registryWatch.ElapsedMilliseconds > 1500)
                { registryLimited = true; return; }
                foreach (System.Collections.DictionaryEntry entry in (System.Collections.IDictionary)Field(node, B("JkmYibSuDZr")))
                {
                    if (++registryEntries > 20000 || registryWatch.ElapsedMilliseconds > 1500)
                    { registryLimited = true; return; }
                    var model = entry.Value;
                    if (model == null) continue;
                    if (model.GetType().FullName == B("j6TdHcKsbueiEjwxIuIh.XyJDNjKsOwEHhOe9s362"))
                    {
                        registryExternalSeen++;
                        if (registryExternalModels.Count < 64)
                            registryExternalModels.Add(new { path, registryId = entry.Key,
                                kind = DescribeFrontendFields(Field(model, B("oOmKsYEg9Sf")), 2),
                                nativeIndex = DescribeFrontendFields(Field(model, B("VqcKsDD1ovV")), 2),
                                reference = DescribeFrontendFields(Field(model, B("JkCKs76rIZR")), 3),
                                name = DescribeFrontendFields(Field(model, B("QkYKsxMS8Ay")), 2) });
                    }
                    if (model.GetType().FullName == B("eFwIefiyuoKqF5Xvj0lt.vZll0FiyKKPTI3JUkFjF") &&
                        Convert.ToUInt32(entry.Key) == 40004u && registryExternalFolders.Count < 16)
                        registryExternalFolders.Add(new { path, registryId = entry.Key,
                            fields = DescribeFrontendFields(model, 3) });
                }
                foreach (System.Collections.DictionaryEntry entry in (System.Collections.IDictionary)Field(node, B("pIxYiE5REC8")))
                {
                    if (registryLimited) return;
                    if (entry.Value != null) VisitExternalRegistry(entry.Value, depth + 1, path + "/" + entry.Key);
                }
            }
            VisitExternalRegistry(Field(ExistingSingleton(editorAssembly, Registry), B("bwbixDw3yob")), 0, "registry");
        }
        catch (Exception ex) { Error(ex); }
        return new { ok = true, status = "frontend-command-metadata-observed",
            scope = "BeyondEditor resource-manager subtree and bounded external-asset registry fields; no command/delegate invoked and no game request sent",
            sceneFolderResolution, registryExternalModels, registryExternalFolders, registryNodes, registryEntries, registryExternalSeen, registryLimited,
            nodesVisited = seen, matchedNodes = matched, records, folderDetails, externalImportModels, externalImportModelsSeen, externalImportModelsLimited = externalImportModelsSeen > 32, resourceFolders, resourcePaths, resourcePathsSeen, resourcePathsLimited = resourcePathsSeen > 256,
            nodeLimit, depthLimit, recordLimit, fieldLimit, limitedFields,
            nodeLimitReached = LastWalkNodesVisited >= nodeLimit,
            depthLimitApplied = true, depthCompletenessKnown = false,
            timeLimited, recordsLimited, frameworkTargetsSkipped, duplicatesSkipped, elapsedMs = watch.ElapsedMilliseconds, errors };
    }
    static object DescribeFrontendFields(object? value, int depth)
    {
        if (value == null) return new { kind = "null" };
        var type = value.GetType();
        if (value is string text) return new { type = "string", text = text.Length > 160 ? text.Substring(0,160) : text };
        if (type.IsEnum) return new { type = type.FullName, numericValue = Convert.ToInt64(value) };
        if (type.IsPrimitive) return new { type = type.FullName, value };
        if (value is System.Collections.IDictionary dictionary && type.FullName != null &&
            type.FullName.Contains(B("cvefc3iyArmG3tLLwKkM.uYNSX5iy0Di9w8cukMIj")) && depth > 0)
        {
            var entries = new List<object>();
            foreach (System.Collections.DictionaryEntry entry in dictionary)
            {
                if (entries.Count >= 8) break;
                entries.Add(new { key = DescribeFrontendFields(entry.Key, depth - 1),
                    value = DescribeFrontendFields(entry.Value, depth - 1) });
            }
            return new { type = type.FullName, count = dictionary.Count, entries, limited = dictionary.Count > 8 };
        }
        if (value is System.Collections.ICollection collection)
            return new { type = type.FullName, count = collection.Count };
        if (depth <= 0 || type.Assembly.GetName().Name != "BeyondEditor") return new { type = type.FullName };
        var fields = new List<object>();
        foreach (var field in type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
        {
            if (fields.Count >= 24) break;
            try { fields.Add(new { field = field.Name, value = DescribeFrontendFields(field.GetValue(value), depth - 1) }); }
            catch (Exception ex) { fields.Add(new { field = field.Name, error = ex.GetType().Name }); }
        }
        return new { type = type.FullName, fields, maxFields = 24, depth };
    }

}