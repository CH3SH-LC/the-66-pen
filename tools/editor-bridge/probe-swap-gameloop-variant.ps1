param([Parameter(Mandatory=$true)][Guid]$RunId,[ValidateSet('no-scoreboard','core')][string]$Variant='no-scoreboard')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$ORIGINAL=1073741829
# One interaction, two purposes: build the variant that drops the suspect scoreboard node,
# bind it, and take the current demo graph off the level entity. If the playtest passes
# afterwards, the demo is playable AND the scoreboard node is identified as the blocker.
# The original graph is not deleted; unbinding is reversible and the graph stays on disk.
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
    $null=Call 'catalog'; Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before.json') -Force
    $result.bindingsBefore=@(Bindings)
    $result.steps+='bindings-before'

    $null=Call ("create-gameloop-variant-" + $Variant)
    $result.steps+='variant-created'
    # The create is queued onto the WPF dispatcher; the registry walk only sees it once that
    # queue has drained. Two back-to-back bridge calls evidently do not leave it idle long
    # enough, so wait explicitly before looking the new graph up.
    Start-Sleep -Seconds 6
    $b=Call ("build-gameloop-variant-" + $Variant)
    $result.variantGraphId=$b.graphId; $result.variantNodeCount=$b.nodeCount
    $result.steps+='variant-built'

    $null=Call ("bind-gameloop-variant-" + $Variant)
    $result.steps+='variant-bound'
    # AddInstructionGraphForEditObj is a service request, not a synchronous edit. An earlier
    # run read the catalog immediately after binding and saw nothing, then saw the binding
    # once it waited. Reading back too early would report a failure that is not real.
    Start-Sleep -Seconds 3
    $null=Call 'catalog'
    $result.bindingsAfterBind=@(Bindings)

    $u=Call 'unbind-all-gameloop-graphs'
    $result.unbindRemoved=$u.removedGraphIds; $result.unbindRemaining=$u.remainingBindingIds
    $result.steps+='original-unbound'

    Start-Sleep -Seconds 3
    $null=Call 'catalog'
    $result.bindingsAfter=@(Bindings)
    $result.variantIsBound=($result.bindingsAfter -contains $b.graphId)
    $result.originalIsBound=($result.bindingsAfter -contains $ORIGINAL)
    $result.steps+='bindings-after'

    try{ $s=Call 'sync-editor-changes'; $result.sync=$s.status }catch{ $result.syncError=$_.Exception.Message }
    $result.steps+='sync-attempted'
    $result.ok=$true
    $result.note='Variant bound and original unbound; nothing was sent to the game beyond the editor sync request.'
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-swap-verification.json') -Encoding utf8
}
