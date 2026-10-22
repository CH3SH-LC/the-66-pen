param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))

# Candidate gameplay nodes for the timed-challenge demo. Read-only definition query:
# no constructor, no graph mutation, no send. The catalog is read before and after and
# must be byte-identical, which is what proves this probe changed nothing.
#
# The list is deliberately wide (<= the adapter's 64 cap) so that ONE administrator
# approval answers every open pin question, instead of one approval per node.
#   flow/logic : 1 print, 2 branch, 14 equal, 9 split-vector, 128 list-index, 142 list-count, 180 convert
#   math       : 200 add, 202 sub, 204 mul, 206 div, 216 abs, 224 round
#   compare    : 230 lt, 231 le, 232 gt, 233 ge
#   entity     : 71 on-created, 73 self, 99 position, 225 make-vector, 244 distance, 260 entity-type, 270 preset-point
#   player     : 248 list, 258 roles, 259 role->player, 272 activate-respawn, 276/278 respawn counts,
#                279 respawn, 288 teleport-overlimit, 289 teleport-done, 803 respawn-active, 804 active-role, 805 teleport-classic
#   timer      : 79 start, 80 pause, 81 resume, 82 stop, 83 tick, 310 global-timer-now, 311 start-global,
#                313 stop-global, 315 global-timer-fired
#   settle     : 77 settle-stage, 647 settlement-scoreboard, 650 rank-value, 651 get-rank, 652 settlement-success, 653 get-success
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

try{
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before.json')
    $defs=Call 'node-definitions' $ids
    if($defs.nodeCount -ne $ids.Count){throw ('NODE_DEFINITION_COUNT_MISMATCH:'+$defs.nodeCount)}
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-after.json')
    if((Get-FileHash (Join-Path $dir 'catalog-before.json')).Hash -ne (Get-FileHash (Join-Path $dir 'catalog-after.json')).Hash){throw 'CATALOG_CHANGED_DURING_DEFINITION_READ'}
    @{ok=$true;requestedIds=$ids;nodeCount=$defs.nodeCount;catalogUnchanged=$true;
      graphModified=$false;sentToGame=$false;playtestVerified=$false;
      persistentSaveVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'definitions-verification.json') -Encoding utf8
}catch{
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
}finally{
    try{$null=Call 'stop'}catch{}
}
