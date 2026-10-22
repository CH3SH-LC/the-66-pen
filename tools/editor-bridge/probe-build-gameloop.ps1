param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))

# One approval, everything it needs:
#   1. read the pin definitions we have never read from this build (read-only)
#   2. prove that read changed nothing (catalog byte-identical)
#   3. create + build the demo graph UNBOUND, then export it for independent checking
# The graph is deliberately left unbound: binding is a separate, later decision.
# Nothing here sends to the game, saves the level, or touches the existing four graphs
# or the running play session.
$ids=@(1,2,9,14,71,73,77,79,80,81,82,83,99,128,142,180,200,202,204,206,216,224,
       225,226,230,231,232,233,244,248,258,259,260,270,272,276,278,279,288,289,
       310,311,313,315,509,647,650,651,652,653,803,804,805)

function Call([string]$op,[uint32[]]$nodeIds){
    $callArgs=@{RunId=$RunId;Operation=$op}
    if($nodeIds){$callArgs['Ids']=$nodeIds}
    $r=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') @callArgs|ConvertFrom-Json)
    if(-not $r.ok){throw ($op+': '+($r|ConvertTo-Json -Depth 12 -Compress))}
    return $r
}
function HashOf([string]$name){ if(Test-Path (Join-Path $dir $name)){ return (Get-FileHash (Join-Path $dir $name)).Hash } return $null }

$result=@{ok=$false;runId=$RunId.ToString('D');steps=@()}
try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $result.steps+= 'bridge-loaded'

    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before.json') -Force

    $defs=Call 'node-definitions' $ids
    if($defs.nodeCount -ne $ids.Count){throw ('NODE_DEFINITION_COUNT_MISMATCH:'+$defs.nodeCount)}
    $result.definitionCount=$defs.nodeCount
    $result.steps+= 'node-definitions-read'

    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-after-definitions.json') -Force
    if((HashOf 'catalog-before.json') -ne (HashOf 'catalog-after-definitions.json')){throw 'CATALOG_CHANGED_DURING_DEFINITION_READ'}
    $result.definitionsChangedNothing=$true
    $result.steps+= 'definitions-read-only-confirmed'

    $created=Call 'create-gameloop-graph'
    $result.createStatus=$created.status
    $result.steps+= 'gameloop-created'

    $built=Call 'build-gameloop-graph'
    $result.graphId=$built.graphId
    $result.nodeCount=$built.nodeCount
    $result.steps+= 'gameloop-built-unbound'

    $exported=Call 'export-gameloop-graph'
    $result.export=$exported
    $result.steps+= 'gameloop-exported'

    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-after-build.json') -Force
    $result.steps+= 'catalog-after-build-captured'

    $result.ok=$true
    $result.bound=$false
    $result.sentToGame=$false
    $result.persistentSaveVerified=$false
    $result.playtestVerified=$false
}catch{
    $result.error=$_.Exception.Message
}finally{
    try{$null=Call 'stop'}catch{}
    $result|ConvertTo-Json -Depth 12|Set-Content (Join-Path $dir 'gameloop-build-verification.json') -Encoding utf8
}
