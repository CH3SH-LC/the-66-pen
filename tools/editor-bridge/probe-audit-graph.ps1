param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$ExportExisting,[switch]$BindVerified)
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
    Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-audit.json')
    if(-not $ExportExisting){
        $null=Call 'create-audit-graph'
        Start-Sleep -Seconds 2
        try{$null=Call 'build-audit-graph'}catch{
            @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'build-error.json') -Encoding utf8
        }
    }
    $export=Call 'export-audit-graph'
    Start-Sleep -Seconds 35
    if(-not (Test-Path -LiteralPath $export.path)){throw 'AUDIT_EXPORT_MISSING'}
    $catalog=Call 'catalog'
    if($BindVerified){
        $validationPath=Join-Path $dir 'audit-validation.json'
        & 'C:\Users\PUBLIC_USER\AppData\Local\Programs\Python\Python313\python.exe' (Join-Path $PSScriptRoot 'verify-runtime-audit.py') $export.path --output $validationPath | Set-Content (Join-Path $dir 'audit-verifier-stdout.json') -Encoding utf8
        if($LASTEXITCODE -ne 0){throw 'AUDIT_VALIDATION_FAILED'}
        $validation=Get-Content $validationPath -Raw|ConvertFrom-Json
        if(-not $validation.ok -or $validation.graphId -ne $export.id){throw 'AUDIT_VALIDATION_ID_MISMATCH'}
        $null=Call 'start-log-observer'
        $null=Call 'enable-debug-logging'
        $bind=Call 'bind-audit-graph'
        Start-Sleep -Seconds 2
        $catalog=Call 'catalog'
        if(-not @($catalog.entities|Where-Object {$_.registryId -eq 1094713345 -and $_.graphBindings.id -contains $export.id}).Count){throw 'AUDIT_BIND_NOT_READ_BACK'}
        $null=Call 'sync-editor-changes'
        Start-Sleep -Seconds 10
        $null=Call 'log-observer-evidence'
        $catalog=Call 'catalog'
    }
    $bound=@($catalog.entities|Where-Object {$_.graphBindings.id -contains $export.id}).Count -gt 0
    if(-not $BindVerified -and $bound){throw 'AUDIT_UNEXPECTEDLY_BOUND'}
    @{filePresent=$true;path=$export.path;graphId=$export.id;unbound=(-not $bound);runtimeVerified=$false}|ConvertTo-Json|Set-Content (Join-Path $dir 'audit-observation.json') -Encoding utf8
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json|Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
} finally {
    if($BindVerified){try{$null=Call 'stop-log-observer'}catch{}}
    try{$null=Call 'stop'}catch{}
}
