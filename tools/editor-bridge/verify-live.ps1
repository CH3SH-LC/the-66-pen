param(
    [Parameter(Mandatory=$true)][int]$TargetPid,
    [string]$Operation = 'verify-interfaces'
)
$ErrorActionPreference = 'Stop'

function ConvertFrom-MiliastraBusinessReply {
    param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Raw)
    try { $result = ConvertFrom-Json -InputObject $Raw -ErrorAction Stop }
    catch { throw 'BUSINESS_REPLY_INVALID_JSON' }
    if ($null -eq $result -or $result -is [array] -or
        $result.ok -isnot [bool] -or $result.ok -ne $true) {
        throw 'BUSINESS_REPLY_NOT_SUCCESSFUL'
    }
    return $result
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runRoot = Join-Path $projectRoot '.runtime/editor-bridge/runs'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$log = [ordered]@{elevated=$elevated;pid=$PID;targetPid=$TargetPid;callPhase='not-started';ok=$false}
# new-scope refuses unsupported versions before creating any scope artifacts.
$scopeJson = & (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $TargetPid | ConvertFrom-Json
$runId = $scopeJson.runId
$log.runId = $runId
$runDir = Join-Path $runRoot $runId
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $runId | Out-Null
    $loaderResult = Get-Content -LiteralPath (Join-Path $runDir 'loader-result.json') -Raw | ConvertFrom-Json
    $log.loadPhase = $loaderResult.phase
    if ($loaderResult.phase -ne 'loader-returned' -or $loaderResult.exitCode -ne 0) { throw 'LOADER_NOT_SUCCESSFUL' }
    $readyPath = Join-Path $runDir 'bridge-ready.json'
    for ($i=0; $i -lt 20 -and -not (Test-Path -LiteralPath $readyPath); $i++) { Start-Sleep -Milliseconds 500 }
    $log.readyFilePresent = Test-Path -LiteralPath $readyPath
    if (-not $log.readyFilePresent) { throw 'BRIDGE_NOT_READY' }
    $ready = Get-Content -LiteralPath $readyPath -Raw | ConvertFrom-Json
    if ($ready.accepted -isnot [bool] -or $ready.accepted -ne $true) { throw 'BRIDGE_READY_NOT_ACCEPTED' }
    $reply = & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $runId -Operation $Operation
    $raw = $reply | Out-String
    $log.replyBytes = $raw.Length
    # Preserve the response even when the business result or JSON is invalid.
    $raw | Out-File -LiteralPath (Join-Path $runDir ($Operation+'-out.json')) -Encoding utf8
    $result = ConvertFrom-MiliastraBusinessReply -Raw $raw
    $log.callPhase = 'ok'
    $log.ok = $true
} catch {
    $log.callPhase = 'failed'
    $log.callError = $_.Exception.Message
}
$log | ConvertTo-Json -Depth 4 | Out-File -LiteralPath (Join-Path $runDir 'verify-live.json') -Encoding utf8
Write-Output ($log | ConvertTo-Json -Depth 4)
if (-not $log.ok) { exit 2 }