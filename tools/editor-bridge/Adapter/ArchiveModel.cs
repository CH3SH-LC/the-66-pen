using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows;

namespace Miliastra.EditorBridge;

// Does the editor process actually HOLD the archive/tab model, or does that live in
// the game process?
//
// This matters because it decides where a durable registration has to happen. The
// profile file (.gip) is rewritten from memory by whatever owns it -- an external
// file edit is simply overwritten. If the editor holds the model, it can be mutated
// in-process the same way the graph operations mutate graph models. If it does not,
// no amount of editor-side reflection will help and the work has to move to the game.
//
// The search key is a string that is known to exist in the stored data: the tab name
// "自定义页签_1" appears verbatim in the profile file. A process that renders that
// list must hold that string somewhere, so finding it finds the model.
//
// STRICTLY READ-ONLY. It enumerates fields and reads values. It never writes a field,
// never invokes a method, and never touches the dispatcher beyond reading objects
// already owned by it. Traversal is bounded on three axes (node count, depth, and a
// namespace filter) so a WPF object graph cannot turn this into a hang.

internal sealed partial class EditorAdapter
{
    // The tab name as it appears in the profile file. Two literals because the second
    // is what the editor labels an unnamed tab with; either one identifies the model.
    static readonly string[] ArchiveModelMarkers = { "自定义页签", "未命名页签" };

    // Second control, for the STRING path specifically.
    //
    // The id control proves the traversal reaches the models. It says nothing about
    // whether string scanning works on them. These are graph names this bridge itself
    // created, so they are demonstrably in the editor's models; a run that cannot find
    // one has a broken string path, and its silence about 自定义页签 would mean nothing.
    static readonly string[] ProbeKnownPresentMarkers = { "MW_Game_Loop", "MW_Course", "MW_Platform" };

    const int ArchiveProbeMaxNodes = 120000;
    const int ArchiveProbeMaxDepth = 14;
    const int ArchiveProbeMaxHits = 60;

    // Walking into framework internals is where the cost is, and the model is not there.
    static readonly string[] ArchiveProbeSkipNamespaces =
    {
        "System.", "Microsoft.", "MS.Internal", "WindowsBase", "PresentationCore",
        "PresentationFramework", "mscorlib", "netstandard", "Accessibility"
    };

    static bool ArchiveProbeShouldSkip(Type t)
    {
        var ns = t.Namespace;
        if (ns == null) return false;
        foreach (var skip in ArchiveProbeSkipNamespaces)
            if (ns.StartsWith(skip, StringComparison.Ordinal)) return true;
        return false;
    }

    // WPF stores every label, header and caption behind a DependencyProperty, whose
    // value lives in the property system -- NOT in a field. Reading fields alone makes
    // this probe blind to all UI text, which is very likely why it reported "not found"
    // for a string the user can see on screen. Read the DPs too.
    //
    // GetValue is a property read; it runs no user code and changes nothing.
    static readonly Dictionary<Type, List<DependencyProperty>> DpCache = new();

    static List<DependencyProperty> StringDependencyProperties(Type t)
    {
        lock (DpCache)
        {
            if (DpCache.TryGetValue(t, out var cached)) return cached;
            var list = new List<DependencyProperty>();
            for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
            {
                FieldInfo[] fields;
                try { fields = cur.GetFields(BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy); }
                catch { break; }
                foreach (var f in fields)
                {
                    if (f.FieldType != typeof(DependencyProperty)) continue;
                    try
                    {
                        if (f.GetValue(null) is DependencyProperty dp &&
                            (dp.PropertyType == typeof(string) || dp.PropertyType == typeof(object)))
                            list.Add(dp);
                    }
                    catch { }
                }
            }
            DpCache[t] = list;
            return list;
        }
    }

    static string? GetCaption(object? o)
    {
        if (o is not DependencyObject dob) return o as string;
        try
        {
            if (dob is System.Windows.Controls.MenuItem m && m.Header is string hs) return hs;
            if (dob is System.Windows.Controls.ContentControl c && c.Content is string cs) return cs;
            if (dob is System.Windows.Controls.TextBlock tb) return tb.Text;
        }
        catch { }
        return null;
    }

    // Returns the first string caption found on this object, if any.
    static IEnumerable<string> Captions(object o)
    {
        if (o is not DependencyObject dob) yield break;
        foreach (var dp in StringDependencyProperties(o.GetType()))
        {
            object? v;
            try { v = dob.GetValue(dp); } catch { continue; }
            if (v is string s && s.Length > 0) yield return s;
        }
    }

    static IEnumerable<object> ArchiveProbeChildren(object o)
    {
        var t = o.GetType();
        FieldInfo[] fields;
        try { fields = t.GetFields(Fields); }
        catch { yield break; }

        foreach (var f in fields)
        {
            var ft = f.FieldType;
            if (ft.IsPrimitive || ft.IsEnum) continue;
            object? value;
            try { value = f.GetValue(o); }
            catch { continue; }
            if (value == null) continue;
            yield return value;

            // One level into collections: the model is very likely a list.
            //
            // ICollection, not IEnumerable. Enumerating an arbitrary IEnumerable runs
            // whatever the producer defined -- a LINQ query would execute, and this probe
            // must not cause anything to happen. ICollection covers arrays, List<T>,
            // Dictionary and HashSet, which is where a model list actually lives.
            if (value is ICollection seq && value is not string)
            {
                var taken = 0;
                foreach (var item in seq)
                {
                    if (item == null) continue;

                    // A Dictionary enumerates to KeyValuePair, and KeyValuePair lives in
                    // System.Collections.Generic -- which ArchiveProbeShouldSkip rejects.
                    // Without unwrapping it here the model objects behind a dictionary are
                    // discarded one level before they would be reached: the registry root
                    // alone yielded 20 nodes instead of thousands. The control marker
                    // (graph id 1073741825, known to live under that root) is what caught
                    // this; the probe reported "not found" for something demonstrably there.
                    var itemType = item.GetType();
                    if (itemType.IsGenericType &&
                        itemType.GetGenericTypeDefinition() == typeof(KeyValuePair<,>))
                    {
                        object? inner = null;
                        try { inner = itemType.GetProperty("Value")!.GetValue(item); } catch { }
                        if (inner != null) { yield return inner; if (++taken >= 2000) break; }
                        continue;
                    }
                    if (item is DictionaryEntry entry)
                    {
                        if (entry.Value != null) { yield return entry.Value; if (++taken >= 2000) break; }
                        continue;
                    }
                    if (itemType.IsPrimitive) continue;
                    yield return item;
                    if (++taken >= 2000) break;
                }
            }
        }
    }

    // Level ids that the profile file references. A process that lists or resolves an
    // archive holds its id somewhere, so these are markers too -- and unlike a display
    // name they cannot be reformatted away.
    static readonly long[] ArchiveModelIdMarkers = { 1073741824, 1073741825, 1073741828, 1073741829 };

    // The traversal the probe proved reaches the model layer AND the menu. Extracted so
    // that other operations use the same walk instead of a re-implementation: five
    // hand-written variants of this each failed to reach the menu while this one worked,
    // and a second copy is a second thing to keep right.
    internal int LastWalkNodesVisited;

    internal IEnumerable<(object Node, string Path)> WalkEditorGraph(int maxNodes, int maxDepth, bool includePrivateBaseFields = false, string? rootType = null)
    {
        var roots = new List<(string, object)>();
        var app = Application.Current;
        if (app != null)
        {
            roots.Add(("Application.Current", app));
            if (app.Resources != null) roots.Add(("Application.Resources", app.Resources));
            foreach (Window w in app.Windows)
            {
                roots.Add(("Window:" + w.GetType().Name, w));
                if (w.DataContext != null) roots.Add(("Window.DataContext@" + w.GetType().Name, w.DataContext));
                if (w.Content != null) roots.Add(("Window.Content@" + w.GetType().Name, w.Content));
            }
        }
        // Registry.root is deliberately NOT a root here.
        //
        // Walking that subtree with every field reaches ~120,000 nodes on its own and
        // exhausts any sensible budget before the menu is ever seen -- which is exactly
        // why six attempts at this op returned zero candidates: the walk was spending
        // everything inside the registry. The probe keeps the registry in a separate,
        // Resources()-shaped phase for the same reason.
        try { roots.Add(("Producer", ExistingSingleton(Editor(), Producer))); } catch { }

        if (rootType != null) roots.RemoveAll(entry => entry.Item2.GetType().FullName != rootType);
        var graphAssembly = includePrivateBaseFields ? Editor() : null;
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance);
        var queue = new Queue<(object Node, string Path, int Depth)>();
        foreach (var (label, value) in roots) queue.Enqueue((value, label, 0));
        int visited = 0;

        LastWalkNodesVisited = 0;
        while (queue.Count > 0 && visited < maxNodes)
        {
            var (node, path, depth) = queue.Dequeue();
            if (node == null || !seen.Add(node)) continue;
            visited++;
            LastWalkNodesVisited = visited;
            yield return (node, path);
            if (depth >= maxDepth) continue;

            void Push(object? o, string p) { if (o != null) queue.Enqueue((o, p, depth + 1)); }

            // The menu: a submenu lives in mi.Items, not the visual tree.
            if (node is System.Windows.Controls.MenuItem mi)
                foreach (var item in mi.Items) Push(item, path + ".Item");

            if (node is System.Windows.DependencyObject vd)
            {
                int n = 0;
                try { n = System.Windows.Media.VisualTreeHelper.GetChildrenCount(vd); } catch { n = 0; }
                for (int i = 0; i < n && i < 256; i++)
                {
                    System.Windows.DependencyObject? c = null;
                    try { c = System.Windows.Media.VisualTreeHelper.GetChild(vd, i); } catch { }
                    Push(c, path + "[" + i + "]");
                }
            }
            if (node is System.Windows.FrameworkElement fe)
            {
                Push(fe.DataContext, path + ".DataContext");
                if (node is System.Windows.Controls.ContentControl cc) Push(cc.Content, path + ".Content");
            }
            var ty = node.GetType();
            if (ArchiveProbeShouldSkip(ty)) continue;

            var walkFields = new List<FieldInfo>(ty.GetFields(Fields));
            if (includePrivateBaseFields)
                for (var parent = ty.BaseType; parent != null && parent.Assembly == graphAssembly; parent = parent.BaseType)
                    foreach (var extra in parent.GetFields(BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly))
                        if (extra.IsPrivate) walkFields.Add(extra);
            foreach (var f in walkFields)
            {
                if (f.FieldType.IsPrimitive || f.FieldType.IsEnum) continue;
                object? v;
                try { v = f.GetValue(node); } catch { continue; }
                if (v == null || v is string) continue;
                Push(v, path + "." + f.Name);
                if (v is ICollection seq)
                {
                    int taken = 0;
                    foreach (var item in seq)
                    {
                        if (item == null) continue;
                        var it = item.GetType();
                        if (it.IsGenericType && it.GetGenericTypeDefinition() == typeof(KeyValuePair<,>))
                        {
                            object? inner = null;
                            try { inner = it.GetProperty("Value")!.GetValue(item); } catch { }
                            Push(inner, path + "." + f.Name + "[]");
                            if (++taken >= 2000) break;
                            continue;
                        }
                        if (item is DictionaryEntry de)
                        {
                            Push(de.Value, path + "." + f.Name + "[]");
                            if (++taken >= 2000) break;
                            continue;
                        }
                        if (it.IsPrimitive) continue;
                        Push(item, path + "." + f.Name + "[]");
                        if (++taken >= 2000) break;
                    }
                }
            }
        }
    }

    // Every caption currently on screen, from the windows' visual trees.
    // Used to read back what a panel shows right after it is opened.
    internal List<string> CurrentCaptions()
    {
        var found = new List<string>();
        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance);
        var stack = new Stack<System.Windows.DependencyObject>();
        var app = Application.Current;
        if (app == null) return found;
        foreach (Window w in app.Windows) stack.Push(w);

        int budget = 120000;
        while (stack.Count > 0 && budget-- > 0)
        {
            var n = stack.Pop();
            if (n == null || !seen.Add(n)) continue;
            foreach (var c in Captions(n))
                if (c.Length > 0 && !found.Contains(c)) found.Add(c);
            int k = 0;
            try { k = System.Windows.Media.VisualTreeHelper.GetChildrenCount(n); } catch { k = 0; }
            for (int i = 0; i < k && i < 256; i++)
            {
                System.Windows.DependencyObject? ch = null;
                try { ch = System.Windows.Media.VisualTreeHelper.GetChild(n, i); } catch { }
                if (ch != null) stack.Push(ch);
            }
        }
        return found;
    }

    public object ProbeArchiveModel()
    {
        var roots = new List<(string Label, object Value)>();
        var app = Application.Current;
        if (app != null)
        {
            roots.Add(("Application.Current", app));
            if (app.Resources != null) roots.Add(("Application.Resources", app.Resources));
            foreach (Window w in app.Windows)
            {
                roots.Add(("Window:" + w.GetType().Name, w));
                if (w.DataContext != null) roots.Add(("Window.DataContext@" + w.GetType().Name, w.DataContext));
                if (w.Content != null) roots.Add(("Window.Content@" + w.GetType().Name, w.Content));
            }
        }
        // The editor's model singletons are static objects inside the BeyondEditor
        // assembly, not reachable by walking fields down from the window tree. Seed from
        // the two singletons the rest of this bridge already resolves, using the same
        // accessor -- so the seeding itself is on a proven path.
        //
        // The registry root is the control. The editor demonstrably holds graph ids
        // 1073741825.. under it (Catalog reads them from here), so a probe that cannot
        // find one of those ids under this root is not working, and its silence about
        // the archive model would mean nothing.
        var seedErrors = new List<string>();
        try
        {
            var producer = ExistingSingleton(Editor(), Producer);
            roots.Add(("Producer", producer));
        }
        catch (Exception ex) { seedErrors.Add("Producer: " + ex.GetType().Name + ": " + ex.Message); }

        // Phase A -- the control, on the proven path.
        //
        // Resources() reaches the graph models by following exactly two container fields
        // (JkmYibSuDZr holds the models, pIxYiE5REC8 the child nodes) and stops at 4096
        // nodes. Walking every field instead explodes: the same root produced 119,673
        // nodes and was truncated before reaching any graph, so the control marker was
        // still not found and the run proved nothing. Mirror the proven traversal, then
        // examine each model it yields.
        var controlHits = new List<object>();
        var knownPresentHits = new List<object>();
        // Every caption reached, marker or not. Without this the run cannot tell
        // "the panel is not open" from "dependency-property reading does not work":
        // both look like zero hits. Window.Title is a DependencyProperty, and the
        // main window's title is known, so a non-empty sample validates the instrument.
        var captionSample = new List<object>();
        var captionTotal = 0;
        var liveStrings = new List<string>();
        var liveSet = new HashSet<string>(StringComparer.Ordinal);
        var menuTree = new List<object>();
        var controlModels = 0;
        var controlScanNodes = 0;
        var controlErrors = new List<string>();
        try
        {
            var registry = ExistingSingleton(Editor(), Registry);
            var root = Field(registry, B("bwbixDw3yob"))!;
            void VisitRegistry(object node, int depth, string path)
            {
                if (depth > 6 || controlModels > 20000) return;
                foreach (DictionaryEntry entry in (IDictionary)Field(node, B("JkmYibSuDZr")))
                {
                    var model = entry.Value;
                    if (model == null) continue;
                    controlModels++;
                    var id = Convert.ToInt64(entry.Key);
                    if (ArchiveModelIdMarkers.Contains(id))
                        controlHits.Add(new { where = "registryKey", path, id, modelType = model.GetType().FullName });
                    // Scan the model's whole sub-structure, not just its direct fields.
                    // Direct fields alone found every id but not one tab name, which is
                    // what a name nested one message deeper looks like. Budgeted globally
                    // so a wide registry cannot turn this into a stall.
                    void ScanDeep(object o, int depth, string where)
                    {
                        if (depth > 4 || controlScanNodes > 400000 || controlHits.Count > ArchiveProbeMaxHits) return;
                        controlScanNodes++;
                        foreach (var f in o.GetType().GetFields(Fields))
                        {
                            object? v;
                            try { v = f.GetValue(o); } catch { continue; }
                            if (v is string sv0)
                            {
                                if (sv0.Length >= 4 && sv0.Length <= 200 &&
                                    liveStrings.Count < 60000 && liveSet.Add(sv0))
                                    liveStrings.Add(sv0);
                                continue;
                            }
                            if (v == null) continue;
                            if (v is string vs)
                            {
                                foreach (var m in ArchiveModelMarkers)
                                    if (vs.Contains(m, StringComparison.Ordinal))
                                        controlHits.Add(new { where = "registryModelString", path,
                                                              at = where + "." + f.Name, value = vs,
                                                              modelType = model.GetType().FullName });
                                foreach (var m in ProbeKnownPresentMarkers)
                                    if (vs.Contains(m, StringComparison.Ordinal))
                                        knownPresentHits.Add(new { at = where + "." + f.Name, value = vs,
                                                                   modelType = model.GetType().FullName });
                            }
                            else if (v is int || v is uint)
                            {
                                var lv = Convert.ToInt64(v);
                                if (ArchiveModelIdMarkers.Contains(lv))
                                    controlHits.Add(new { where = "registryModelId", path,
                                                          at = where + "." + f.Name, id = lv,
                                                          modelType = model.GetType().FullName });
                            }
                            else if (!f.FieldType.IsPrimitive && !f.FieldType.IsEnum &&
                                     !(v is ICollection))
                            {
                                ScanDeep(v, depth + 1, where + "." + f.Name);
                            }
                        }
                    }
                    ScanDeep(model, 0, "");
                    if (controlHits.Count > ArchiveProbeMaxHits) return;
                }
                foreach (DictionaryEntry entry in (IDictionary)Field(node, B("pIxYiE5REC8")))
                    if (entry.Value != null) VisitRegistry(entry.Value!, depth + 1, path + "/" + entry.Key);
            }
            VisitRegistry(root, 0, "root");
        }
        catch (Exception ex) { controlErrors.Add(ex.GetType().Name + ": " + ex.Message); }

        var rootLabels = roots.Select(r => r.Label).ToArray();

        var seen = new HashSet<object>(ReferenceEqualityComparer.Instance);
        var queue = new Queue<(object Node, string Path, int Depth, string Root)>();
        foreach (var (label, value) in roots) queue.Enqueue((value, label, 0, label));

        var hits = new List<object>();
        var visitedTypes = new HashSet<string>(StringComparer.Ordinal);
        var perRoot = new Dictionary<string, int>(StringComparer.Ordinal);
        int visited = 0;
        bool truncated = false;

        while (queue.Count > 0)
        {
            if (visited >= ArchiveProbeMaxNodes) { truncated = true; break; }
            var (node, path, depth, root) = queue.Dequeue();
            if (!seen.Add(node)) continue;
            visited++;
            perRoot[root] = perRoot.GetValueOrDefault(root) + 1;
            visitedTypes.Add(node.GetType().FullName ?? "?");

            // Numeric markers: an archive id survives in the model even if the name does not.
            if (node is int || node is uint || node is long || node is ulong)
            {
                long asLong;
                try { asLong = Convert.ToInt64(node); } catch { asLong = long.MinValue; }
                if (ArchiveModelIdMarkers.Contains(asLong) && hits.Count < ArchiveProbeMaxHits)
                    hits.Add(new { path, value = asLong.ToString(), holder = path, kind = "id" });
                continue;
            }

            // A string hit is the marker itself.
            if (node is string s)
            {
                foreach (var marker in ArchiveModelMarkers)
                {
                    if (s.Contains(marker, StringComparison.Ordinal))
                    {
                        if (hits.Count < ArchiveProbeMaxHits)
                            hits.Add(new { path, value = s, holder = path });
                        break;
                    }
                }
                continue;
            }

            // Every string encountered, dumped whole.
            //
            // ConfuserEx encrypts string literals on disk, so searching the DLL is useless
            // -- but at runtime those literals are ordinary managed strings, and this walk
            // reads live objects. A dump of what is actually in memory therefore sees the
            // command names that the file hides.
            if (node is string live && live.Length >= 4 && live.Length <= 200)
            {
                if (liveStrings.Count < 40000 && !liveSet.Contains(live))
                {
                    liveSet.Add(live);
                    liveStrings.Add(live);
                }
                continue;
            }

            var type = node.GetType();

            // UI captions first: this is the only place the archive/organise strings a
            // user can actually see would be reachable at all.
            foreach (var caption in Captions(node))
            {
                captionTotal++;
                if (captionSample.Count < 600)
                    captionSample.Add(new { path, value = caption, owner = type.FullName });
                foreach (var m in ArchiveModelMarkers)
                {
                    if (caption.Contains(m, StringComparison.Ordinal) && hits.Count < ArchiveProbeMaxHits)
                        hits.Add(new { where = "uiCaption", path, value = caption, holder = type.FullName });
                }
                foreach (var m in ProbeKnownPresentMarkers)
                {
                    if (caption.Contains(m, StringComparison.Ordinal) && knownPresentHits.Count < 40)
                        knownPresentHits.Add(new { at = path + "[caption]", value = caption,
                                                   modelType = type.FullName, kind = "caption" });
                }
            }

            // WPF visual-tree children are System.Windows.* types, so the namespace
            // filter skips them for descent -- which meant the walk never entered the
            // visual tree at all and never saw a panel's DataContext. The archive list,
            // if the editor holds one, hangs off exactly such a DataContext. So: for a
            // framework element, read DataContext and Content before skipping the type.
            // Two fields, not a descent -- cheap, and aimed at the one place the model
            // could hide behind a framework type.
            // Menu structure. A MenuItem's Items collection is data, not interaction --
            // reading it opens nothing and clicks nothing. Panel entry points live here,
            // and this is the one place the archive command could be named without
            // having to open anything first.
            if (node is System.Windows.Controls.MenuItem mi)
            {
                var children = new List<object>();
                try
                {
                    foreach (var item in mi.Items)
                    {
                        string? header = null;
                        try { header = GetCaption(item as System.Windows.DependencyObject); } catch { }
                        var typeName = item?.GetType().FullName;

                        // The header came back null: these are a custom MenuItem subclass
                        // that keeps its label somewhere other than MenuItem.Header. Read
                        // its own fields so the label is visible, and read the two
                        // properties that would carry the action.
                        var fieldStrings = new List<object>();
                        string? commandType = null, tag = null;
                        if (item != null)
                        {
                            foreach (var f in item.GetType().GetFields(Fields))
                            {
                                object? fv;
                                try { fv = f.GetValue(item); } catch { continue; }
                                if (fv is string fs && fs.Length > 0 && fs.Length < 200)
                                    fieldStrings.Add(new { field = f.Name, value = fs });
                            }
                            try
                            {
                                if (item is System.Windows.Controls.MenuItem m2)
                                {
                                    commandType = m2.Command?.GetType().FullName;
                                    tag = m2.Tag as string;
                                }
                            }
                            catch { }
                        }
                        children.Add(new { header, type = typeName, commandType, tag, fieldStrings });
                    }
                }
                catch { }
                if (children.Count > 0)
                    menuTree.Add(new { path, header = GetCaption(mi), items = children });
            }

            // Visual-tree descent.
            //
            // Reading fields never enters the visual tree: children live behind
            // Panel.Children / ContentPresenter, reached through VisualTreeHelper. Only
            // five captions were reachable without this (the two window titles among
            // them), which is far too few for a UI of this size. GetChildrenCount and
            // GetChild are pure reads with no side effects.
            if (node is System.Windows.DependencyObject vd && depth < ArchiveProbeMaxDepth)
            {
                int n = 0;
                try { n = System.Windows.Media.VisualTreeHelper.GetChildrenCount(vd); }
                catch { n = 0; }
                for (int i = 0; i < n && i < 256; i++)
                {
                    System.Windows.DependencyObject? child = null;
                    try { child = System.Windows.Media.VisualTreeHelper.GetChild(vd, i); }
                    catch { }
                    if (child != null)
                        queue.Enqueue((child, path + "[" + i + "]", depth + 1, root));
                }
            }

            if (node is System.Windows.FrameworkElement fe && depth < ArchiveProbeMaxDepth)
            {
                if (fe.DataContext != null)
                    queue.Enqueue((fe.DataContext, path + "[" + type.Name + "].DataContext",
                                   depth + 1, root));
            }
            if (node is System.Windows.Controls.ContentControl cc && cc.Content != null &&
                depth < ArchiveProbeMaxDepth)
            {
                queue.Enqueue((cc.Content, path + "[" + type.Name + "].Content", depth + 1, root));
            }

            if (ArchiveProbeShouldSkip(type)) continue;
            if (depth >= ArchiveProbeMaxDepth) continue;

            foreach (var child in ArchiveProbeChildren(node))
            {
                var childPath = path + "." + child.GetType().Name;
                if (child is string cs)
                {
                    foreach (var marker in ArchiveModelMarkers)
                    {
                        if (cs.Contains(marker, StringComparison.Ordinal))
                        {
                            if (hits.Count < ArchiveProbeMaxHits)
                                hits.Add(new { path = childPath, value = cs, holder = type.FullName });
                            break;
                        }
                    }
                    continue;
                }
                if (child is int || child is uint || child is long || child is ulong)
                {
                    long cv;
                    try { cv = Convert.ToInt64(child); } catch { cv = long.MinValue; }
                    if (ArchiveModelIdMarkers.Contains(cv) && hits.Count < ArchiveProbeMaxHits)
                        hits.Add(new { path = childPath, value = cv.ToString(), holder = type.FullName, kind = "id" });
                    continue;
                }
                queue.Enqueue((child, childPath, depth + 1, root));
            }
        }

        return new
        {
            ok = true,
            status = hits.Count > 0 ? "archive-model-found-in-editor" : "archive-model-not-found-in-editor",
            scope = "read-only enumeration of fields; no value written, no method invoked",
            markers = ArchiveModelMarkers,
            nodesVisited = visited,
            distinctTypesVisited = visitedTypes.Count,
            menuTree,
            liveStringCount = liveStrings.Count,
            liveStrings,
            captionInstrument = new
            {
                what = "every dependency-property caption reached; Window.Title is a DP and " +
                       "the main window's title is known, so a non-empty sample proves the " +
                       "instrument works",
                total = captionTotal,
                sample = captionSample
            },
            control = new
            {
                what = "Resources()-style walk of the registry; graph models live there",
                modelsSeen = controlModels,
                scanNodes = controlScanNodes,
                stringPathControl = new
                {
                    what = "graph names this bridge created; they are definitely in the editor",
                    hitCount = knownPresentHits.Count,
                    hits = knownPresentHits.Take(10).ToArray(),
                    passed = knownPresentHits.Count > 0
                },
                hitCount = controlHits.Count,
                hits = controlHits,
                errors = controlErrors,
                passed = controlHits.Count > 0
            },
            roots = rootLabels,
            seedErrors,
            controlExpectation = "graph id 1073741825 is known to live under Registry.root; "+
                                 "a run that does not report it has not reached the model layer and its "+
                                 "silence about the archive model means nothing",
            perRootNodeCount = perRoot,
            truncated,
            hitCount = hits.Count,
            hits
        };
    }
}
