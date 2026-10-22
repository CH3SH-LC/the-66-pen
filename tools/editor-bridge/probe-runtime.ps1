param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
function Call([string]$op){
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+$r.error)}
    return $r
}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $before=Call 'runtime-evidence'
    Copy-Item (Join-Path $dir 'runtime-evidence-response.json') (Join-Path $dir 'runtime-evidence-before.json')
    if($before.logModelPresent){
        $null=Call 'request-debug-logs'
        Start-Sleep -Seconds 5
        $null=Call 'runtime-evidence'
    }
}catch{
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
}finally{
    try{$null=Call 'stop'}catch{}
}
