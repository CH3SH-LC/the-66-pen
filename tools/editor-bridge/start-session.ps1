param(
    [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$TargetPid,
    [Parameter(Mandatory=$true)][ValidateSet('observe','inspect-sync','backup-course','restore-route')][string]$Action
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$helpers=@{
    'observe'='probe-log-observer.ps1'
    'inspect-sync'='probe-sync-inspection.ps1'
    'backup-course'='backup-live-course.ps1'
    'restore-route'='probe-tiled-route.ps1'
}
$target=Get-Process -Id $TargetPid
if($target.ProcessName -ne 'BeyondEditor'){throw 'EXISTING_EDITOR_REQUIRED'}
$helper=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot $helpers[$Action])).Path
$scope=(& (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $TargetPid | ConvertFrom-Json)
$runId=([Guid]$scope.runId).ToString('D')
$receipt=Join-Path $PSScriptRoot ('../../.runtime/editor-bridge/runs/'+$runId+'/session-launch.json')
$state=@{runId=$runId;targetPid=$TargetPid;action=$Action;status='launch-pending';helperPid=$null;helperStartUtcTicks=$null}
$state|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding utf8
try {
    $helperProcess=Start-Process 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -Verb RunAs -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$helper+'"'),'-RunId',$runId)
    $state.helperPid=$helperProcess.Id
    $state.helperStartUtcTicks=[string]$helperProcess.StartTime.ToUniversalTime().Ticks
    $state.status='helper-started-result-pending'
} catch {
    $state.status='launch-failed-no-automatic-retry'
    $state|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding utf8
    throw
}
$state|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding utf8
$state|ConvertTo-Json -Compress
