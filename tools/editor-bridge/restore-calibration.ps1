param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$VerifyExisting)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
function Call([string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-restore.json')
    if(-not $VerifyExisting){
    $import=Call 'import-calibration-graph'
    $found=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        $graphs=@($catalog.userGraphs|Where-Object name -eq $import.name)
        if($graphs.Count -gt 0){$found=$true;break}
    }
    if(-not $found){throw 'IMPORT_NOT_READ_BACK'}
    }
    $bind=Call 'bind-calibration-graph'
    $bound=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        $bound=@($catalog.entities|Where-Object {$_.registryId -eq $bind.entityId -and $_.graphBindings.id -contains $bind.graphId}).Count -gt 0
        if($bound){break}
    }
    if(-not $bound){throw 'BIND_NOT_READ_BACK'}
    $export=Call 'export-calibration-graph'
    Start-Sleep -Seconds 35
    @{filePresent=(Test-Path -LiteralPath $export.path);path=$export.path;graphId=$bind.graphId;bound=$bound;persistentSaveVerified=$false;playtestVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'restore-observation.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
