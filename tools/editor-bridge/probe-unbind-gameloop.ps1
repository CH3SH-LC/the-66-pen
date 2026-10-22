param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
# Controlled experiment: remove this project's own demo graph from the level entity's
# bindings so the user can re-run the playtest check. Reversible - the graph is not
# deleted and BindGameLoopGraph restores the binding. Changes nothing else in the level.
function Call([string]$op){
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+($r|ConvertTo-Json -Depth 12 -Compress))}
    return $r
}
$result=@{ok=$false;runId=$RunId.ToString('D');steps=@()}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $result.steps+='bridge-loaded'
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before.json') -Force
    $u=Call 'unbind-gameloop-graph'
    $result.unbindStatus=$u.status
    $result.remainingBindingIds=$u.remainingBindingIds
    $result.steps+='gameloop-unbound'
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-after.json') -Force
    $d=Get-Content (Join-Path $dir 'catalog-after.json') -Raw | ConvertFrom-Json
    $ids=@()
    foreach($e in @($d.entities | Where-Object { $_.registryId -eq 1094713345 })){
        foreach($g in @($e.graphBindings)){ $ids+=$g.id }
    }
    $result.bindingsAfterReadback=@($ids | Sort-Object -Unique)
    $result.steps+='readback-after-unbind'
    $sync=Call 'sync-editor-changes'
    $result.sync=$sync.status
    $result.steps+='synced'
    $result.ok=$true
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-unbind-verification.json') -Encoding utf8
}
