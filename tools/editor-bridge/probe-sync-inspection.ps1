param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
function Call([string]$op){
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+($r|ConvertTo-Json -Depth 12 -Compress))}
    return $r
}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before.json')
    $null=Call 'inspect-sync-graphs'
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-after.json')
    if((Get-FileHash (Join-Path $dir 'catalog-before.json')).Hash -ne (Get-FileHash (Join-Path $dir 'catalog-after.json')).Hash){throw 'CATALOG_CHANGED_DURING_INSPECTION'}
    @{ok=$true;catalogUnchanged=$true;sentToGame=$false;playtestVerified=$false;persistentSaveVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'inspection-verification.json') -Encoding utf8
}catch{
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
}finally{
    try{$null=Call 'stop'}catch{}
}
