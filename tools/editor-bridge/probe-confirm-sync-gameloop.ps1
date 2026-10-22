param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$GRAPH=1073741829
# Read the level entity's bindings back from the model. Only if the demo graph is really
# bound does this proceed to sync; a bind request that never landed must not be followed
# by a sync that would present the level as finished.
function Call([string]$op){
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+($r|ConvertTo-Json -Depth 12 -Compress))}
    return $r
}
$result=@{ok=$false;runId=$RunId.ToString('D');steps=@()}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $result.steps+='bridge-loaded'
    Start-Sleep -Seconds 3
    $cat=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-readback.json') -Force
    $d=Get-Content (Join-Path $dir 'catalog-readback.json') -Raw | ConvertFrom-Json
    $lvl=@($d.entities | Where-Object { $_.registryId -eq 1094713345 })
    $boundGraphs=@()
    foreach($e in $lvl){ foreach($g in @($e.graphBindings)){ $boundGraphs+=$g.id } }
    $boundGraphs=@($boundGraphs | Sort-Object -Unique)
    $result.boundGraphIds=$boundGraphs
    $result.gameloopBound=($boundGraphs -contains $GRAPH)
    $result.steps+='bindings-read-back'
    if($result.gameloopBound){
        $sync=Call 'sync-editor-changes'
        $result.sync=$sync
        $result.steps+='synced'
    } else {
        $result.steps+='sync-skipped-binding-absent'
    }
    $result.ok=$true
    $result.persistentSaveVerified=$false
    $result.playtestVerified=$false
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-confirm-sync-verification.json') -Encoding utf8
}
