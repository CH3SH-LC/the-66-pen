# Offline regression: all process facts are fabricated and all file hashes mocked.
$ErrorActionPreference='Stop'
Import-Module Microsoft.PowerShell.Utility
$bridgeDir=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$projectRoot=[IO.Path]::GetFullPath((Join-Path $bridgeDir '../..'))
. (Join-Path $bridgeDir 'compatibility-guard.ps1')
$script:checks=0
function Check($condition,$name){if(-not $condition){throw ('FAILED:'+ $name)};$script:checks++}
function Refuses([scriptblock]$action,[string]$message){try{& $action|Out-Null;throw 'DID_NOT_REFUSE'}catch{Check ($_.Exception.Message -like ($message+'*')) ($message+' action='+$action.ToString()+' actual='+$_.Exception.Message)}}
$global:BridgeTestHash='565DDA11883F0220BAE050438FCF52B2288F26B61ED656E2B4CD6D69B41A678A'
$global:BridgeTestExists=$true
function Get-FileHash {param($LiteralPath,$Algorithm);[pscustomobject]@{Hash=$global:BridgeTestHash}}
function Test-Path {param($LiteralPath,$PathType);return $global:BridgeTestExists}
$editor='C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.exe'
$fixture=Join-Path $projectRoot 'tools/editor-bridge/TestHost/bin/Release/net8.0-windows/TestHost.exe'
$pin=Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $editor -StartUtcTicks 123
Check ($pin.dllSha256 -eq $global:BridgeTestHash) 'known adapted hash accepted'
$global:BridgeTestHash='D4B429A371505FF5252E5A869A8FC250CD0924440A648FDB844A0EEBED083841'
Refuses {Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $editor -StartUtcTicks 123} 'EDITOR_VERSION_UNSUPPORTED'
Refuses {Assert-MiliastraCompatibilityPin -Pin $pin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $editor -StartUtcTicks 123} 'EDITOR_VERSION_UNSUPPORTED'
$global:BridgeTestExists=$false
Refuses {Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $editor -StartUtcTicks 123} 'EDITOR_DLL_MISSING'
$hostPin=Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName TestHost -ImagePath $fixture -StartUtcTicks 123
Check (-not $hostPin.editorDllGateApplied) 'exact TestHost allowed without editor DLL'
Refuses {Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName TestHost -ImagePath 'C:\other\TestHost.exe' -StartUtcTicks 123} 'TARGET_NOT_ALLOWED'
Refuses {Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $fixture -StartUtcTicks 123} 'TARGET_NOT_ALLOWED'
$global:BridgeTestExists=$true
$global:BridgeTestHash='565DDA11883F0220BAE050438FCF52B2288F26B61ED656E2B4CD6D69B41A678A'
$pin.dllPath='C:\old-copy\BeyondEditor.dll'
Refuses {Assert-MiliastraCompatibilityPin -Pin $pin -ProjectRoot $projectRoot -ProcessName BeyondEditor -ImagePath $editor -StartUtcTicks 123} 'COMPATIBILITY_PIN_INVALID'
$global:BridgeTestHash='D4B429A371505FF5252E5A869A8FC250CD0924440A648FDB844A0EEBED083841'
$global:BridgeTestArtifactWrites=0
function Get-Process {param($Id);[pscustomobject]@{ProcessName='BeyondEditor';StartTime=[DateTime]::new(123,[DateTimeKind]::Utc);MainModule=[pscustomobject]@{FileName=$editor}}}
function New-Item {param($ItemType,$Path);$global:BridgeTestArtifactWrites++;throw 'UNEXPECTED_ARTIFACT_CREATION'}
Refuses {& (Join-Path $bridgeDir 'new-scope.ps1') -TargetPid 1} 'EDITOR_VERSION_UNSUPPORTED'
Check ($global:BridgeTestArtifactWrites -eq 0) 'new scope refuses before artifacts'
# Direct-call regression with fabricated process and scope; it must refuse before pipe construction.
$global:BridgeTestScope=@{pid=1;startUtcTicks='123';expiresUtc=[DateTimeOffset]::UtcNow.AddMinutes(1).ToString('o');expectedExe=$editor;pipeName='offline-never-connect';nonce='unused'}
function Get-Content {
 param($LiteralPath,[switch]$Raw)
 if($LiteralPath -like '*bridge-settings.json'){return ($global:BridgeTestScope|ConvertTo-Json)}
 return (Microsoft.PowerShell.Management\Get-Content -LiteralPath $LiteralPath -Raw:$Raw)
}
Refuses {& (Join-Path $bridgeDir 'call-bridge.ps1') -RunId '00000000-0000-0000-0000-000000000001' -Operation ping} 'EDITOR_VERSION_UNSUPPORTED'
$global:BridgeTestScope.expectedExe=$fixture
Refuses {& (Join-Path $bridgeDir 'call-bridge.ps1') -RunId '00000000-0000-0000-0000-000000000001' -Operation ping} 'TARGET_NOT_ALLOWED'
$global:BridgeTestScope.expectedExe=$editor
$global:BridgeTestScope.startUtcTicks='124'
Refuses {& (Join-Path $bridgeDir 'call-bridge.ps1') -RunId '00000000-0000-0000-0000-000000000001' -Operation ping} 'START_TIME_MISMATCH'
# Extract only the pure business parser by AST; do not execute verify-live's main body.
$tokens=$null;$errors=$null
$verifyAst=[Management.Automation.Language.Parser]::ParseFile((Join-Path $bridgeDir 'verify-live.ps1'),[ref]$tokens,[ref]$errors)
Check ($errors.Count -eq 0) 'verify-live parses on Windows PowerShell'
$functionAst=$verifyAst.Find({param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'ConvertFrom-MiliastraBusinessReply'},$true)
. ([scriptblock]::Create($functionAst.Extent.Text))
Check ((ConvertFrom-MiliastraBusinessReply '{"ok":true}').ok -eq $true) 'literal true accepted'
foreach($raw in @('{"ok":false}','{}','{"ok":"true"}','{"ok":1}','null','[{"ok":true}]')){Refuses {ConvertFrom-MiliastraBusinessReply $raw} 'BUSINESS_REPLY_NOT_SUCCESSFUL'}
Refuses {ConvertFrom-MiliastraBusinessReply 'broken'} 'BUSINESS_REPLY_INVALID_JSON'
# Parse the actual entrypoints and prove gates precede effectful operations.
foreach($name in @('compatibility-guard.ps1','new-scope.ps1','load-bridge.ps1','call-bridge.ps1')){
 $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $bridgeDir $name),[ref]$tokens,[ref]$errors)
 Check ($errors.Count -eq 0) ($name+' syntax')
 $source=$ast.Extent.Text
 if($name -eq 'call-bridge.ps1'){Check ($source.IndexOf('Get-MiliastraCompatibilityPin') -lt $source.IndexOf('[IO.Pipes.NamedPipeClientStream]')) 'call guard before pipe construction'}
 if($name -eq 'load-bridge.ps1'){Check ($source.IndexOf('Assert-MiliastraCompatibilityPin') -lt $source.IndexOf("'loader.claim'")) 'load guard before claim'}
}
@{ok=$true;checks=$script:checks;scope='offline mocks and parser only; no user process or game contact'}|ConvertTo-Json -Compress