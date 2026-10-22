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
    $saved='C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level/1073741825.gil'
    if((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne '33e579847a10a71f9c5f951f89c38e36080529830d27d01a2d0bc1b79a13aa0d'){throw 'VERIFIED_STATIC_SAVE_CHANGED'}
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-retirement.json')
    $null=Call 'retire-runtime-spawns'
    $null=Call 'sync-editor-changes'
    Start-Sleep -Seconds 3
    $null=Call 'inspect-sync-graphs'
    $calibration=Call 'export-calibration-graph'
    Start-Sleep -Seconds 35
    $route=Call 'export-tiled-route'
    Start-Sleep -Seconds 35
    if(-not (Test-Path -LiteralPath $calibration.path) -or -not (Test-Path -LiteralPath $route.path)){throw 'RETIREMENT_EXPORT_MISSING'}
    $null=Call 'catalog'
    @{calibration=$calibration.path;route=$route.path;independentValidationPending=$true;saveVerified=$false;playtestVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'retirement-exports.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
