"""One-shot wiring for the verify-interfaces operation (R67).

Registers the new adapter file in the csproj, adds the operation to the bridge
dispatch and its ternary arm, and extends the call-bridge whitelist. Idempotent.
"""
from pathlib import Path

NEW_FILE = '<Compile Include="../Adapter/GameLoopGraph.cs" Link="GameLoopGraph.cs" />'
NEW_FILE_WITH = NEW_FILE + '<Compile Include="../Adapter/InterfaceVerification.cs" Link="InterfaceVerification.cs" />'

p = Path("ManagedBridge/Miliastra.EditorBridge.csproj")
t = p.read_text(encoding="utf-8")
if "InterfaceVerification.cs" not in t:
    assert NEW_FILE in t, "anchor not found in csproj"
    p.write_text(t.replace(NEW_FILE, NEW_FILE_WITH, 1), encoding="utf-8")
    print("csproj: compile item added")
else:
    print("csproj: already present")

p = Path("ManagedBridge/BridgeServer.cs")
t = p.read_text(encoding="utf-8")
if "verify-interfaces" not in t:
    anchor = '                case "catalog":\n'
    assert anchor in t, "case anchor not found"
    t = t.replace(anchor, anchor + '                case "verify-interfaces":\n', 1)

    tern = 'op == "catalog"\n                            ? _adapter.Catalog()'
    assert tern in t, "ternary anchor not found"
    t = t.replace(tern, tern + '\n                            : op == "verify-interfaces" ? _adapter.VerifyInterfaces()', 1)
    p.write_text(t, encoding="utf-8")
    print("BridgeServer: op wired")
else:
    print("BridgeServer: already present")

p = Path("call-bridge.ps1")
t = p.read_text(encoding="utf-8")
if "verify-interfaces" not in t:
    anchor = "'catalog','node-definitions'"
    assert anchor in t, "ValidateSet anchor not found"
    p.write_text(t.replace(anchor, "'catalog','verify-interfaces','node-definitions'", 1), encoding="utf-8")
    print("call-bridge: ValidateSet updated")
else:
    print("call-bridge: already present")
