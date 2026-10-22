param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
# Restore the demo graph's binding. It was unbound only to run the control experiment that
# established the playtest upload failure is unrelated to this project's content.
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
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-rebind-verification.json') -Encoding utf8
}
