using System.Text.Json;
using Miliastra.EditorBridge;
// Fixed session-specific read-only capture, no selectable process or game action.
if (args.Length != 0) { Console.Error.WriteLine("NO_ARGUMENTS_ACCEPTED"); return 2; }
string json=JsonSerializer.Serialize(NativeSaveCatalogEvidence.Capture());
Console.WriteLine(json);
using var document=JsonDocument.Parse(json);
return document.RootElement.GetProperty("ok").GetBoolean()?0:1;
