param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
# Targeted repair of one integer constant, then re-export so the independent verifier can
# re-check the whole graph. The graph stays unbound and is never sent to the game.
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
    $rep=Call 'repair-gameloop-score-order'
    $result.repairStatus=$rep.status
    $result.readback=$rep.readback
    $result.steps+='score-order-repaired'
    $exp=Call 'export-gameloop-graph'
    $result.exportPath=$exp.path
    $result.steps+='re-exported'
    $result.ok=$true
    $result.bound=$false
    $result.sentToGame=$false
    $result.playtestVerified=$false
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-repair-verification.json') -Encoding utf8
}
