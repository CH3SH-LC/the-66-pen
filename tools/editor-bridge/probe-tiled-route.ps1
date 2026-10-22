param([Parameter(Mandatory=$true)][Guid]$RunId)
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
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-tiled-route.json')
    $import=Call 'import-tiled-route'
    $found=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        if(@($catalog.userGraphs|Where-Object {$_.name -eq $import.name -and $_.nodeCount -eq 39}).Count -gt 0){$found=$true;break}
    }
    if(-not $found){throw 'TILED_ROUTE_NOT_READ_BACK'}
    $export=Call 'export-tiled-route'
    Start-Sleep -Seconds 35
    if(-not (Test-Path -LiteralPath $export.path)){throw 'TILED_EXPORT_MISSING'}
    & 'C:\Users\PUBLIC_USER\AppData\Local\Programs\Python\Python313\python.exe' (Join-Path $PSScriptRoot 'verify-tiled-route.py') $export.path --output (Join-Path $dir 'tiled-validation.json') | Set-Content (Join-Path $dir 'verifier-stdout.json') -Encoding utf8
    if($LASTEXITCODE -ne 0){throw 'TILED_EXPORT_VALIDATION_FAILED'}
    $validation=Get-Content (Join-Path $dir 'tiled-validation.json') -Raw | ConvertFrom-Json
    if(-not $validation.ok -or $validation.graphId -ne $export.id){throw 'TILED_VALIDATION_ID_MISMATCH'}
    $bind=Call 'bind-tiled-route'
    $bound=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        $bound=@($catalog.entities|Where-Object {$_.registryId -eq $bind.entityId -and $_.graphBindings.id -contains $export.id}).Count -gt 0
        if($bound){break}
    }
    if(-not $bound){throw 'TILED_BIND_NOT_READ_BACK'}
    $null=Call 'sync-editor-changes'
    Start-Sleep -Seconds 3
    $null=Call 'catalog'
    $null=Call 'runtime-evidence'
    @{filePresent=$true;path=$export.path;graphId=$export.id;bound=$bound;syncInvoked=$true;physicalCollisionVerified=$false;playabilityVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'tiled-observation.json') -Encoding utf8

} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
