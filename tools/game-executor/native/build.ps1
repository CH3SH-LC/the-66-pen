[CmdletBinding()]
param(
    [switch]$TestHostOnly,
    [switch]$SceneCallsOnly,
    [string]$LogPath
)
$ErrorActionPreference = 'Stop'
if ($TestHostOnly -and $SceneCallsOnly) { throw 'Choose only one targeted build mode.' }
$nativeDirectory = Split-Path -Parent $PSCommandPath
$repoDirectory = (Resolve-Path -LiteralPath (Join-Path $nativeDirectory '../../..')).Path
$outputDirectory = Join-Path $repoDirectory '.runtime/game-executor/build'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio discovery tool is not installed.' }
$selectionJson = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json
if ($LASTEXITCODE -ne 0) { throw 'Visual Studio discovery failed.' }
$selection = @($selectionJson | ConvertFrom-Json)
if ($selection.Count -ne 1) { throw 'No existing C++ x64 toolchain found.' }
if (-not $LogPath) {
    $suffix = (Get-Date).ToString('yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
    $LogPath = Join-Path $repoDirectory ".runtime/game-executor/build-logs/$suffix.log"
}
$LogPath = [IO.Path]::GetFullPath($LogPath)
if (Test-Path -LiteralPath $LogPath) { throw "Refuse to overwrite build log: $LogPath" }
$logDirectory = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$mode = if ($SceneCallsOnly) { 'scene call contract only; preserve DLL and existing test host' } elseif ($TestHostOnly) { 'test host only; preserve DLL and import library' } else { 'DLL and independent test host' }
@(
    "Mode: $mode",
    "Visual Studio: $($selection[0].installationPath)",
    "Version: $($selection[0].installationVersion)",
    'Target: x64; flags: /std:c++17 /EHsc /W4 /WX /O2 /MD',
    "Output: $outputDirectory",
    'No game/editor discovery, loading, injection or IPC is performed.'
) | Set-Content -LiteralPath $LogPath -Encoding utf8
Get-Content -LiteralPath $LogPath
$buildArguments = @()
if ($TestHostOnly) { $buildArguments += '--test-host-only' }
if ($SceneCallsOnly) { $buildArguments += '--scene-calls-only' }
& (Join-Path $nativeDirectory 'build.cmd') @buildArguments 2>&1 | Tee-Object -FilePath $LogPath -Append
$buildExit = $LASTEXITCODE
"Exit code: $buildExit" | Add-Content -LiteralPath $LogPath -Encoding utf8
if ($buildExit -ne 0) { throw "Native build failed with code $buildExit; see $LogPath" }
Write-Output "Build log: $LogPath"
