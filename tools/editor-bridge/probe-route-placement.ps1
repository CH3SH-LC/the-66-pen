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
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-route.json')
    $import=Call 'import-route-placement'
    $found=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        if(@($catalog.userGraphs|Where-Object {$_.name -eq $import.name -and $_.nodeCount -eq 12}).Count -gt 0){$found=$true;break}
    }
    if(-not $found){throw 'ROUTE_NOT_READ_BACK'}
    $export=Call 'export-route-placement'
    Start-Sleep -Seconds 35
    $catalog=Call 'catalog'
    $bound=@($catalog.entities|Where-Object {$_.graphBindings.id -contains $export.id}).Count -gt 0
    @{filePresent=(Test-Path -LiteralPath $export.path);path=$export.path;graphId=$export.id;bound=$bound;scaleApplied=$false;playabilityVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'route-observation.json') -Encoding utf8
    if($bound){throw 'UNEXPECTED_ROUTE_BINDING'}
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
