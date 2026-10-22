param([Parameter(Mandatory=$true)][Guid]$RunId)
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
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-external-assets.json')
    $null=Call 'start-external-asset-observer'
    for($sample=0;$sample -lt 12;$sample++){
        Start-Sleep -Seconds 10
        $evidence=Call 'external-asset-evidence'
        if(@($evidence.ownAssets).Count -gt 0){break}
    }
    $null=Call 'log-observer-evidence'
    $null=Call 'catalog'
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop-log-observer'}catch{}
    try{$null=Call 'stop'}catch{}
}
