param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
function RunDir([Guid]$id){Join-Path $root ('.runtime/editor-bridge/runs/'+$id.ToString('D'))}
$dir=RunDir $RunId
$activeRun=$RunId
$completed=$false
function Call([Guid]$id,[string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $id -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
function WaitClosed([Guid]$id){
    $path=Join-Path (RunDir $id) 'lease-closed.json'
    for($i=0;$i -lt 50;$i++){
        if(Test-Path -LiteralPath $path){
            try{$closed=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json}catch{Start-Sleep -Milliseconds 100;continue}
            if(-not $closed.cleanupSucceeded -or $closed.hostProcessTerminated){throw 'LEASE_CLEANUP_FAILED'}
            if($closed.cleanupEvidence.observer.observerRegistered -or -not $closed.cleanupEvidence.observer.originalReceiversPreserved){throw 'OBSERVER_CLEANUP_FAILED'}
            Start-Sleep -Milliseconds 100
            return
        }
        Start-Sleep -Milliseconds 100
    }
    throw 'LEASE_CLOSURE_NOT_CONFIRMED'
}
function ObserveAndClose([Guid]$id){
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $id
    $null=Call $id 'ping'
    $null=Call $id 'catalog'
    $null=Call $id 'start-log-observer'
    $null=Call $id 'request-debug-logs'
    Start-Sleep -Seconds 3
    $null=Call $id 'log-observer-evidence'
    # Deliberately rely on lease cleanup, without explicit stop-log-observer.
    $null=Call $id 'stop'
    WaitClosed $id
}
try {
    $scope=Get-Content (Join-Path $dir 'bridge-settings.json') -Raw|ConvertFrom-Json
    ObserveAndClose $RunId
    $second=(& (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $scope.pid | ConvertFrom-Json)
    $activeRun=[Guid]$second.runId
    @{firstRun=$RunId.ToString('D');secondRun=$activeRun.ToString('D');pid=$scope.pid;completed=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'reuse-pair.json') -Encoding utf8
    ObserveAndClose $activeRun
    $firstFrozen=Get-Content (Join-Path $dir 'frozen.json') -Raw|ConvertFrom-Json
    $secondFrozen=Get-Content (Join-Path (RunDir $activeRun) 'frozen.json') -Raw|ConvertFrom-Json
    if($firstFrozen.bridge -ne $secondFrozen.bridge -or $firstFrozen.bootstrap -ne $secondFrozen.bootstrap){throw 'REUSE_ARTIFACT_CHANGED'}
    $proc=Get-Process -Id $scope.pid
    if($proc.StartTime.ToUniversalTime().Ticks -ne [long]$scope.startUtcTicks -or -not $proc.Responding){throw 'EDITOR_IDENTITY_OR_RESPONSE_CHANGED'}
    @{firstRun=$RunId.ToString('D');secondRun=$activeRun.ToString('D');pid=$scope.pid;completed=$true;sameBridgeHash=$firstFrozen.bridge;sameBootstrapHash=$firstFrozen.bootstrap;editorResponding=$proc.Responding;hostRestarted=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'reuse-pair.json') -Encoding utf8
    $completed=$true
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    if(-not $completed){try{$null=Call $activeRun 'stop'}catch{}}
}
