param([Parameter(Mandatory=$true)][Guid]$RunId)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$python='C:\Users\PUBLIC_USER\AppData\Local\Programs\Python\Python313\python.exe'
function Call([string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
function CheckBindings($catalog,$calibrationId,$tiledId){
    $level=@($catalog.entities|Where-Object registryId -eq 1094713345)
    if($level.Count -eq 0){throw 'LEVEL_MISSING'}
    foreach($entity in $level){
        if($entity.graphBindings.id -notcontains $calibrationId -or $entity.graphBindings.id -notcontains $tiledId){throw 'COURSE_BINDING_MISSING'}
    }
}
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $before=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-backup.json')
    $exports=@{}
    foreach($entry in @(@{operation='export-calibration-graph';name='calibration';verifier='verify-calibration.py'},@{operation='export-tiled-route';name='tiled';verifier='verify-tiled-route.py'})){
        $entry.export=Call $entry.operation
        $exports[$entry.name]=$entry.export
        # Native export did not produce the second file for adjacent requests.
        # Complete and verify one export before requesting the next.
        Start-Sleep -Seconds 35
        if(-not (Test-Path -LiteralPath $entry.export.path)){throw ('EXPORT_MISSING: '+$entry.name)}
        $validationPath=Join-Path $dir ($entry.name+'-validation.json')
        & $python (Join-Path $PSScriptRoot $entry.verifier) $entry.export.path --output $validationPath | Set-Content (Join-Path $dir ($entry.name+'-verifier-stdout.json')) -Encoding utf8
        if($LASTEXITCODE -ne 0){throw ('EXPORT_VALIDATION_FAILED: '+$entry.name)}
        $validation=Get-Content $validationPath -Raw | ConvertFrom-Json
        if(-not $validation.ok -or $validation.graphId -ne $entry.export.id){throw 'EXPORT_ID_MISMATCH'}
    }
    $calibration=$exports.calibration
    $tiled=$exports.tiled
    CheckBindings $before $calibration.id $tiled.id
    $after=Call 'catalog'
    CheckBindings $after $calibration.id $tiled.id
    $backup=Join-Path $dir 'course-backup'
    New-Item -ItemType Directory -Path $backup | Out-Null
    $assets=@()
    foreach($entry in @(@{export=$calibration;name='calibration'},@{export=$tiled;name='tiled'})){
        $target=Join-Path $backup ($entry.name+'.gia')
        Copy-Item -LiteralPath $entry.export.path -Destination $target
        $assets+=@{name=$entry.name;file=($entry.name+'.gia');graphId=$entry.export.id;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash;source=$entry.export.path}
    }
    @{schema=1;observedUtc=[DateTime]::UtcNow.ToString('o');assets=$assets;levelEntityId=1094713345;requiredGraphIds=@($calibration.id,$tiled.id);order=@('calibration','tiled');bothBindingsReadBack=$true;nativeRoundtripVerified=$true;durableGameSaveVerified=$false;restoreOfThisBundleVerified=$false;playabilityVerified=$false} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $backup 'manifest.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
