param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$EnableLogging,[switch]$EnableOwnGraphs)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
function Call([string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-observer.json')
    $null=Call 'runtime-evidence'
    Copy-Item (Join-Path $dir 'runtime-evidence-response.json') (Join-Path $dir 'runtime-before-observer.json')
    $null=Call 'start-log-observer'
    if($EnableOwnGraphs){$null=Call 'enable-own-graph-logging'}
    elseif($EnableLogging){$null=Call 'enable-debug-logging'}
    $null=Call 'request-debug-logs'
    Start-Sleep -Seconds 10
    $null=Call 'log-observer-evidence'
    Copy-Item (Join-Path $dir 'log-observer-evidence-response.json') (Join-Path $dir 'observer-ten-seconds.json')
    Start-Sleep -Seconds 17
    $null=Call 'log-observer-evidence'
    $null=Call 'catalog'
    $null=Call 'runtime-evidence'
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop-log-observer'}catch{}
    try{$null=Call 'stop'}catch{}
}
