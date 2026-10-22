param([Parameter(Mandatory=$true)][Guid]$RunId,[switch]$ObserveExport,[switch]$CreateGraph,[switch]$AddPrint,[switch]$WireEvent,[switch]$BindGraph,[switch]$ReuseLoaded,[switch]$ImportGraph,[switch]$BindCalibration)
$ErrorActionPreference='Stop'
if(-not $ReuseLoaded){& (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $RunId}
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$dir=Join-Path $root ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
try {
    $ready=Get-Content (Join-Path $dir 'bridge-ready.json') -Raw | ConvertFrom-Json
    if(-not $ready.accepted){throw 'BRIDGE_NOT_ACCEPTED'}
    & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation ping
    & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog
    if($CreateGraph){
        Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-create.json')
        $create=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation create-test-graph | ConvertFrom-Json)
        if(-not $create.ok){throw ('CREATE_INVOCATION_FAILED: '+$create.error)}
        $found=$false
        for($attempt=0;$attempt -lt 10;$attempt++){
            Start-Sleep -Seconds 2
            $catalog=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog | ConvertFrom-Json)
            if(@($catalog.userGraphs | Where-Object {$_.name -eq $create.name}).Count -gt 0){$found=$true;break}
        }
        @{createdGraphReadBack=$found;name=$create.name}|ConvertTo-Json|Set-Content (Join-Path $dir 'create-observation.json') -Encoding utf8
        if(-not $found){throw 'CREATE_NOT_READ_BACK_NO_EXPORT_ATTEMPT'}
    }
    if($AddPrint){
        $edit=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation add-test-print | ConvertFrom-Json)
        if(-not $edit.ok){throw ('EDIT_INVOCATION_FAILED: '+$edit.error)}
        Start-Sleep -Seconds 3
        & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog
    }
    if($WireEvent){
        $edit=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation wire-test-event | ConvertFrom-Json)
        if(-not $edit.ok){throw ('WIRE_INVOCATION_FAILED: '+$edit.error)}
        Start-Sleep -Seconds 3
        & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog
    }
    if($BindGraph -or $BindCalibration){
        Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-bind.json')
        $bindOperation=if($BindCalibration){'bind-calibration-graph'}else{'bind-test-graph'}
        $bind=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $bindOperation | ConvertFrom-Json)
        if(-not $bind.ok){throw ('BIND_INVOCATION_FAILED: '+$bind.error)}
        $found=$false
        for($attempt=0;$attempt -lt 10;$attempt++){
            Start-Sleep -Seconds 2
            $catalog=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog | ConvertFrom-Json)
            $entity=@($catalog.entities | Where-Object {$_.registryId -eq $bind.entityId})
            if(@($entity.graphBindings | Where-Object {$_.id -eq $bind.graphId}).Count -gt 0){$found=$true;break}
        }
        @{bindingReadBack=$found;entityId=$bind.entityId;graphId=$bind.graphId}|ConvertTo-Json|Set-Content (Join-Path $dir 'bind-observation.json') -Encoding utf8
        if(-not $ObserveExport){& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation stop}
    }
    if($ImportGraph){
        Copy-Item (Join-Path $dir 'catalog-response.json') (Join-Path $dir 'catalog-before-import.json')
        $import=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation import-verified-graph | ConvertFrom-Json)
        if(-not $import.ok){throw ('IMPORT_INVOCATION_FAILED: '+$import.error)}
        $found=$false
        for($attempt=0;$attempt -lt 10;$attempt++){
            Start-Sleep -Seconds 2
            $catalog=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation catalog | ConvertFrom-Json)
            if(@($catalog.userGraphs | Where-Object {$_.name -eq $import.name -and $_.nodeCount -eq 2}).Count -gt 0){$found=$true;break}
        }
        @{importReadBack=$found;name=$import.name}|ConvertTo-Json|Set-Content (Join-Path $dir 'import-observation.json') -Encoding utf8
        if(-not $found){throw 'IMPORT_NOT_READ_BACK'}
    }
    if($ObserveExport){
        $operation=if($ImportGraph){'export-imported-graph'}else{'export-first'}
        $response=(& (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation $operation | ConvertFrom-Json)
        if(-not $response.ok){throw ('EXPORT_INVOCATION_FAILED: '+$response.error)}
        Start-Sleep -Seconds 35
        @{filePresent=(Test-Path -LiteralPath $response.path);replyPresent=(Test-Path -LiteralPath $response.replyPath);observedUtc=[DateTimeOffset]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content (Join-Path $dir 'export-observation.json') -Encoding utf8
        & (Join-Path $PSScriptRoot 'call-bridge.ps1') -RunId $RunId -Operation stop
    }
} catch {
    @{error=$_.Exception.Message}|ConvertTo-Json | Set-Content (Join-Path $dir 'probe-error.json') -Encoding utf8
    exit 2
}
