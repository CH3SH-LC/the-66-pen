param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$CompleteExisting)
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
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-calibration.json')
    if($CompleteExisting){
        $null=Call 'set-calibration-origin'
    }else{
    $create=Call 'create-calibration-graph'
    $found=$false
    for($i=0;$i -lt 10;$i++){
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        if(@($catalog.userGraphs|Where-Object name -eq $create.name).Count -gt 0){$found=$true;break}
    }
    if(-not $found){throw 'CREATE_NOT_READ_BACK'}
    $null=Call 'build-calibration-graph'
    }
    Start-Sleep -Seconds 3
    $catalog=Call 'catalog'
    $export=Call 'export-calibration-graph'
    Start-Sleep -Seconds 35
    $bound=@($catalog.entities|Where-Object {$_.graphBindings.id -contains $export.id}).Count -gt 0
    @{filePresent=(Test-Path -LiteralPath $export.path);path=$export.path;bound=$bound;playtestVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'calibration-observation.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
