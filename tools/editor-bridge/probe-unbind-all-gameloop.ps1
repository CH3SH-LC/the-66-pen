param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
# Revert the level's bindings to the state that played successfully before this project
# added anything: only the four original graphs remain bound. This is the cleanest possible
# control for "does the playtest upload step fail because of this project's content, or for
# an unrelated reason". No graph is deleted, so every binding can be restored.
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
    $null=Call 'catalog'
    $result.bindingsBefore=@(Bindings)
    $result.steps+='bindings-before'

    $u=Call 'unbind-all-gameloop-graphs'
    $result.removedGraphIds=$u.removedGraphIds
    $result.remainingBindingIds=$u.remainingBindingIds
    $result.steps+='all-gameloop-unbound'

    Start-Sleep -Seconds 4
    $null=Call 'catalog'
    $result.bindingsAfter=@(Bindings)
    $result.steps+='readback'

    try{ $s=Call 'sync-editor-changes'; $result.sync=$s.status }catch{ $result.syncError=$_.Exception.Message }
    $result.steps+='sync-attempted'
    $result.ok=$true
    $result.note='Level bindings reverted to the four original graphs. All demo graphs still exist and can be rebound.'
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-unbind-all-verification.json') -Encoding utf8
}
