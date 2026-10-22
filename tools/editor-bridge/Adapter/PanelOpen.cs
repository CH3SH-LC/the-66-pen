using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;

namespace Miliastra.EditorBridge;

// Open one of the editor's own panels, by invoking the very Action the editor's own
// Window menu would invoke.
//
// WHY THIS IS NOT UI AUTOMATION
//   The project forbids driving the editor by cursor, window focus, screenshot clicks
//   or UIAutomation. None of that happens here. The editor builds each menu entry as a
//   (label, Action) pair -- M9xFPCKX3nwCN5mCtXPs holds the label in MMGKX5coQC4 and the
//   callback in Te1KXhuGxBC. This reads that callback off the live menu item and invokes
//   it in-process. It is the editor's own entry point being called, not a synthetic
//   click arriving from outside, and it is the closest thing to "the editor's native
//   method" this bridge can reach.
//
//   It is deliberately narrow: it can only invoke a menu entry that already exists, and
//   only one whose label matches a caller-supplied string exactly.
//
// SIDE EFFECTS
//   Opening a panel changes what is on screen. Nothing else. No file is touched, no
//   model is mutated, and the panel can be closed by the user as usual.

internal sealed partial class EditorAdapter
{
    static string MenuLabelField => B("MMGKX5coQC4");
    static string MenuActionField => B("Te1KXhuGxBC");

    // The op takes no argument: the bridge's call path carries none, and a fixed target
    // keeps the reachable set auditable. Only labels from this list can ever be invoked.
    static readonly string[] PanelOpenTargets = { "节点管理器", "资源管理器" };

    public object OpenEditorPanel(bool resourceManager = false)
    {
        string label = PanelOpenTargets[resourceManager ? 1 : 0];
        var app = Application.Current ?? throw new InvalidOperationException("NO_APPLICATION");
        var candidates = new List<object>();
        object? chosen = null;
        string? chosenAction = null;
        // Diagnostics: without these, "0 candidates" cannot be told apart from "the walk
        // never saw a MenuItem" or "the label field was not found".
        int menuItemsSeen = 0;
        var diagnostics = new List<object>();

        {
            foreach (var (node, _) in WalkEditorGraph(200000, 14))
            {
                // NOT `node is MenuItem`: the editor's menu entries are a custom class
                // (M9xFPCKX3nwCN5mCtXPs : SmPcDVKQUDqwaIu1hmwZ) that does not derive from
                // MenuItem. They are only reachable as objects inside a MenuItem's Items
                // collection, so the test is for the label field, on any object at all.
                if (node is null) continue;
                var labelFieldInfo = node.GetType().GetField(MenuLabelField, Fields);
                if (labelFieldInfo == null) continue;
                menuItemsSeen++;
                string? text = null;
                var fieldNames = new List<string>();
                try
                {
                    foreach (var f2 in node.GetType().GetFields(Fields)) fieldNames.Add(f2.Name);
                    text = labelFieldInfo.GetValue(node) as string;
                }
                catch (Exception ex) { diagnostics.Add(new { type = node.GetType().FullName, error = ex.GetType().Name }); }
                if (diagnostics.Count < 12)
                    diagnostics.Add(new { type = node.GetType().FullName, label = text,
                                          hasLabelField = fieldNames.Contains(MenuLabelField),
                                          fieldCount = fieldNames.Count,
                                          fields = fieldNames.Take(14) });
                if (string.IsNullOrEmpty(text)) continue;

                var actionField = node.GetType().GetField(MenuActionField, Fields);
                var action = actionField?.GetValue(node) as Delegate;

                candidates.Add(new
                {
                    label = text,
                    actionPresent = action != null,
                    actionTarget = action?.Method?.DeclaringType?.FullName + "::" + action?.Method?.Name
                });

                if (chosen == null && string.Equals(text, label, StringComparison.Ordinal))
                {
                    chosen = node;
                    chosenAction = action?.Method?.DeclaringType?.FullName + "::" + action?.Method?.Name;
                    try { action?.DynamicInvoke(); } catch (Exception ex)
                    {
                        return new { ok = false, status = "panel-action-threw",
                                     label, error = ex.GetType().Name + ": " + ex.Message,
                                     invokedTarget = chosenAction, candidates };
                    }
                }
            }
        }

        if (chosen == null)
            return new { ok = false, status = "no-menu-entry-with-that-label", label,
                         menuItemsSeen, walkNodesVisited = LastWalkNodesVisited,
                         diagnostics, candidates };

        // Read back what the panel actually shows. Invoking an action and reporting
        // success proves only that a delegate ran; it does not prove the panel opened,
        // and it says nothing about what is in it.
        System.Threading.Thread.Sleep(600);
        var after = CurrentCaptions();

        return new
        {
            ok = true,
            status = "panel-action-invoked",
            label,
            invokedTarget = chosenAction,
            note = "invoked the editor's own menu Action in-process; no synthetic input was sent",
            captionsAfterOpen = after,
            captionCountAfterOpen = after.Count,
            candidates
        };
    }
}
