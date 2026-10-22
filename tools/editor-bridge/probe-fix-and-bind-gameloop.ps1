param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
# Order matters: the repair guards on the graph being unbound, so it runs BEFORE the bind.
# After repairing, the graph is exported so the fixed pin can be checked from real exported
# bytes rather than from the repair's own readback. Only then is it bound and synced.
function Call([string]$op){
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+($r|ConvertTo-Json -Depth 12 -Compress))}
    return $r
}
function Bindings(){
    $d=Get-Content (Join-Path $dir 'catalog-response.json') -Raw | ConvertFrom-Json
    $ids=@()
    foreach($e in @($d.entities | Where-Object { $_.registryId -eq 1094713345 })){
        foreach($g in @($e.graphBindings)){ $ids+=$g.id }
    }
    return @($ids | Sort-Object -Unique)
}
$result=@{ok=$false;runId=$RunId.ToString('D');steps=@()}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $result.steps+='bridge-loaded'
    $null=Call 'catalog'; $result.bindingsBefore=@(Bindings); $result.steps+='bindings-before'

    $r=Call 'repair-gameloop-score-order'
    $result.repairStatus=$r.status; $result.repairReadback=$r.readback
    $result.steps+='score-order-repaired'

    $e=Call 'export-gameloop-graph'
    $result.exportPath=$e.path
    $result.steps+='exported'

    $b=Call 'bind-gameloop-graph'
    $result.bindStatus=$b.status
    $result.steps+='gameloop-bound'
    Start-Sleep -Seconds 4
    $null=Call 'catalog'; $result.bindingsAfter=@(Bindings); $result.steps+='readback'

    try{ $s=Call 'sync-editor-changes'; $result.sync=$s.status }catch{ $result.syncError=$_.Exception.Message }
    $result.steps+='sync-attempted'
    $result.ok=$true
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-fix-bind-verification.json') -Encoding utf8
}
