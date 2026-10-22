param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$dir=Join-Path $PSScriptRoot ('../../.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
function Read-Result([string]$name){
    $path=Join-Path $dir $name
    if(Test-Path -LiteralPath $path){return Get-Content -LiteralPath $path -Raw|ConvertFrom-Json}
    return $null
}
$launch=Read-Result 'session-launch.json'
if($null -eq $launch){throw 'SESSION_LAUNCH_RECEIPT_MISSING'}
$alive=$null
if($launch.helperPid -and $launch.helperStartUtcTicks){
    $p=Get-Process -Id $launch.helperPid -ErrorAction SilentlyContinue
    $alive=($null -ne $p -and [string]$p.StartTime.ToUniversalTime().Ticks -eq $launch.helperStartUtcTicks)
}
$closed=Read-Result 'lease-closed.json'
$failure=Read-Result 'probe-error.json'
$resultName=switch($launch.action){
    'observe' {'log-observer-evidence-response.json'}
    'inspect-sync' {'inspection-verification.json'}
    'backup-course' {'course-backup/manifest.json'}
    'restore-route' {'tiled-observation.json'}
    default {throw 'UNKNOWN_SESSION_ACTION'}
}
$result=Read-Result $resultName
$status='outcome-unknown-do-not-retry'
if($failure){$status='action-failed'}
elseif($closed -and $closed.cleanupSucceeded -eq $true -and $result){$status='helper-finished-evidence-available'}
elseif($closed -and $closed.cleanupSucceeded -ne $true){$status='cleanup-failed'}
elseif($alive -eq $true){$status='helper-running'}
$catalog=Read-Result 'catalog-response.json'
$graphs=@()
if($catalog){$graphs=@($catalog.userGraphs|Select-Object id,name,nodeCount -Unique)}
[ordered]@{
    runId=$RunId.ToString('D');action=$launch.action;targetPid=$launch.targetPid
    status=$status;helperAlive=$alive;cleanupSucceeded=$(if($closed){$closed.cleanupSucceeded}else{$null})
    error=$(if($failure){$failure.error}else{$null});graphs=$graphs;result=$result
    notice='Helper completion is not durable save, scene visibility or playtest acceptance. Evidence may be a historical snapshot.'
}|ConvertTo-Json -Depth 12
