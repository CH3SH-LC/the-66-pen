[CmdletBinding()]
param([switch]$RunTests)
$ErrorActionPreference = 'Stop'
$templateDirectory = Split-Path -Parent $PSCommandPath
$repoDirectory = (Resolve-Path -LiteralPath (Join-Path $templateDirectory '../../..')).Path
$outputDirectory = Join-Path $repoDirectory '.runtime/game-executor/template-authoring/build'
$logDirectory = Join-Path $repoDirectory '.runtime/game-executor/template-authoring/build-logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$suffix = (Get-Date).ToString('yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$logPath = Join-Path $logDirectory "$suffix.log"
@('Mode: host-only template call static library and stub tests',
  'No DLL, game discovery, injection, IPC, helper changes or native calls.',
  "Output: $outputDirectory") | Set-Content -LiteralPath $logPath -Encoding utf8
& (Join-Path $templateDirectory 'build.cmd') 2>&1 | Tee-Object -FilePath $logPath -Append
$buildExit = $LASTEXITCODE
"Build exit: $buildExit" | Add-Content -LiteralPath $logPath -Encoding utf8
if ($buildExit -ne 0) { throw "Host build failed ($buildExit): $logPath" }
if ($RunTests) {
    foreach ($testName in @('template_calls_test.exe','template_catalog_test.exe','component_binding_calls_test.exe','item_calls_test.exe','skill_calls_test.exe','template_catalog_capture_test.exe','currency_action_test.exe','component_attachment_test.exe','item_action_test.exe','binding_action_test.exe','trigger_calls_test.exe','item_properties_capture_test.exe','trigger_region_add_test.exe','binding_edit_test.exe','skill_action_test.exe','trigger_parent_calls_test.exe')) {
        & (Join-Path $outputDirectory $testName) 2>&1 | Tee-Object -FilePath $logPath -Append
        $testExit = $LASTEXITCODE
        "$testName exit: $testExit" | Add-Content -LiteralPath $logPath -Encoding utf8
        if ($testExit -ne 0) { throw "Host stub tests failed ($testExit): $logPath" }
    }
}
Write-Output "Build log: $logPath"
