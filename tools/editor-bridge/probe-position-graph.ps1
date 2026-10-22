param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$ExportExisting)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$python='C:\Users\PUBLIC_USER\AppData\Local\Programs\Python\Python313\python.exe'
function Call([string]$op){
    $result=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $op | ConvertFrom-Json)
    if(-not $result.ok){throw ($op+': '+$result.error)}
    return $result
}
# Unbound-only probe: it authors and exports the position graph, then requires
# independent validation and an unbound readback. It has no bind flag, so it can
# never bind the graph or enable logging.
try {
    & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId
    $null=Call 'catalog'
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-position.json')
    if(-not $ExportExisting){
        $null=Call 'create-position-graph'
        Start-Sleep -Seconds 2
        # A rejected build is kept as diagnostics; the export below still runs so
        # its failure (or partial file) is reported rather than hidden.
        try{$null=Call 'build-position-graph'}catch{
            @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'build-error.json') -Encoding utf8
        }
    }
    $export=Call 'export-position-graph'
    # Written before any wait or existence check so the export receipt survives a
    # missing or partially written .gia.
    @{path=$export.path;graphId=$export.id;status=$export.status;replyPath=$export.replyPath;
      modelType=$export.modelType;observedUtc=[DateTime]::UtcNow}|ConvertTo-Json|Set-Content (Join-Path $dir 'position-export.json') -Encoding utf8
    Start-Sleep -Seconds 35
    if(-not (Test-Path -LiteralPath $export.path)){throw 'POSITION_EXPORT_MISSING'}
    $validationPath=Join-Path $dir 'position-validation.json'
    & $python (Join-Path $PSScriptRoot 'verify-position-graph.py') $export.path --output $validationPath | Set-Content (Join-Path $dir 'position-verifier-stdout.json') -Encoding utf8
    if($LASTEXITCODE -ne 0){throw 'POSITION_VALIDATION_FAILED'}
    $validation=Get-Content $validationPath -Raw|ConvertFrom-Json
    if(-not $validation.ok -or $validation.graphId -ne $export.id){throw 'POSITION_VALIDATION_ID_MISMATCH'}
    $catalog=Call 'catalog'
    $bound=@($catalog.entities|Where-Object {$_.graphBindings.id -contains $export.id}).Count -gt 0
    if($bound){throw 'POSITION_UNEXPECTEDLY_BOUND'}
    @{filePresent=$true;path=$export.path;graphId=$export.id;sha256=$validation.sha256;
      unbound=(-not $bound);validationOk=$validation.ok;runtimeVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'position-observation.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    try{$null=Call 'stop'}catch{}
}
