param([Parameter(Mandatory=$true)][Guid]$RunId,[ValidateSet('audio-runtime-node-catalog','inspect-entity-faction-probe','set-entity-faction-probe','restore-entity-faction-probe','inspect-entity-components','delete-entity-component','add-entity-component','delete-instruction-graph','delete-instruction-graph-force','delete-instruction-graph-dry-run','reflection-probe','reflection-probe-component','reflection-probe-template','reflection-probe-service','reflection-editor-add','reflection-editor-create','reflection-editor-services','reflection-editor-types','mine-process-strings','author-entity-tag','repair-finish-booleans','create-finish-graph','build-finish-graph','export-finish-graph','bind-finish-graph','unbind-finish-graph','strip-finish-classic-node','create-calibration-graph','build-calibration-graph','export-calibration-graph','runtime-evidence','inspect-reopen-content','profile-reopen-content-sample','inspect-sync-graphs','create-audit-graph','build-audit-graph','export-audit-graph','create-position-graph','build-position-graph','unbind-gameloop-graph','unbind-all-gameloop-graphs','create-gameloop-variant-no-scoreboard','create-gameloop-variant-core','build-gameloop-variant-no-scoreboard','build-gameloop-variant-core','bind-gameloop-variant-no-scoreboard','bind-gameloop-variant-core','create-mvp-course-graph','build-mvp-course-graph','bind-mvp-course-graph','export-mvp-course-graph','repair-gameloop-score-order','repair-gameloop-settlement-status','repair-gameloop-classic-teleport','begin-finish-minimal-diagnostic','restore-finish-minimal-diagnostic','begin-finish-settlement-diagnostic','restore-finish-settlement-diagnostic','create-gameloop-graph','build-gameloop-graph','export-gameloop-graph','bind-gameloop-graph','export-position-graph','bind-position-graph','bind-audit-graph','request-debug-logs','enable-debug-logging','enable-own-graph-logging','set-calibration-origin','rename-realtime-lab-tree','restore-realtime-lab-tree-name','begin-entity-crud-probe','inspect-entity-crud-probe','rename-entity-crud-probe','restore-entity-crud-probe-name','delete-entity-crud-probe','request-realtime-tree-prefab','request-realtime-lab-prefab','request-calibration-prefab','ping','describe','recover-client-script-probe','inspect-client-script-file-probe','create-client-script-file-probe','set-client-script-file-probe-path','begin-client-script-batch-probe','create-client-script-batch-probe','inspect-client-script-batch-probe','delete-client-script-batch-probe','export-client-script-probe','inspect-client-script-variables-probe','add-client-script-variable-probe','delete-client-script-variable-probe','add-client-script-int-variable-probe','reset-client-script-variable-type-probe','begin-client-script-probe','create-client-script-probe','inspect-client-script-probe','rename-client-script-probe','delete-client-script-probe','client-script-root','client-script-catalog','prefab-fields-page','prefab-fields','prefab-catalog','catalog','begin-owned-entity-cleanup','inspect-owned-entity-cleanup','delete-owned-entity-cleanup','inspect-self-connection-repair','repair-self-connection','command-probe','probe-archive-model','open-editor-panel','inspect-frontend-commands','open-scene-resource-folder','open-resource-manager','load-scene-resource-model','load-lab-cube-resource-model','focus-lab-cube-from-frontend','verify-interfaces','verify-channels','delete-owned-graph-ids-dry-run','delete-owned-graph-ids','delete-owned-entity-ids-dry-run','delete-owned-entity-ids','node-definitions','node-definition-variants','create-test-graph','add-test-print','wire-test-event','bind-calibration-graph','bind-test-graph','export-first','start-external-asset-observer','external-asset-evidence','retire-runtime-spawns','start-log-observer','log-observer-evidence','stop-log-observer','import-tiled-route','export-tiled-route','bind-tiled-route','import-route-placement','export-route-placement','sync-editor-changes','import-calibration-graph','import-verified-graph','export-imported-graph','stop')][string]$Operation='ping',[uint32[]]$Ids,[uint32]$EntityId,[string]$ComponentAction,[string]$ComponentProbeId,[uint32]$ComponentId,[string]$TagProbeId,[uint32]$TagEntityId,[uint32]$TagId,
      [ValidateSet('inspect','set')][string]$TagAction='inspect',[Nullable[bool]]$TagSelected,[string]$ExpectedTagsSha256,[string]$ClientScriptRelativePath,[string]$NameContains,[string]$MemberContains)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$runDir=Join-Path $projectRoot ('.runtime/editor-bridge/runs/'+$RunId.ToString('D'))
$scope=Get-Content -LiteralPath (Join-Path $runDir 'bridge-settings.json') -Raw | ConvertFrom-Json
if([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($scope.expiresUtc)){throw 'SCOPE_EXPIRED'}
. (Join-Path $PSScriptRoot 'compatibility-guard.ps1')
$target=Get-Process -Id ([int]$scope.pid)
$targetTicks=$target.StartTime.ToUniversalTime().Ticks
if($targetTicks -ne [long]$scope.startUtcTicks){throw 'START_TIME_MISMATCH'}
try{$targetImage=$target.MainModule.FileName}catch{throw 'TARGET_IMAGE_UNREADABLE'}
if($targetImage -ine $scope.expectedExe){throw 'TARGET_NOT_ALLOWED:scope-image-path'}
# Guard the observed process, not the scope's claimed executable. This also protects
# old valid scopes and direct callers before a named-pipe object is created.
$null=Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName $target.ProcessName -ImagePath $targetImage -StartUtcTicks $targetTicks
$pipe=[IO.Pipes.NamedPipeClientStream]::new('.', $scope.pipeName, [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
$reader=$null
$writer=$null
try {
    $pipe.Connect(5000)
    $writer=[IO.StreamWriter]::new($pipe,[Text.UTF8Encoding]::new($false),1024,$true)
    $reader=[IO.StreamReader]::new($pipe,[Text.UTF8Encoding]::new($false),$false,1024,$true)
    $writer.AutoFlush=$true
    $request=@{id=[Guid]::NewGuid().ToString('N');op=$Operation;nonce=$scope.nonce}
    if($PSBoundParameters.ContainsKey('ClientScriptRelativePath')) {
        if($Operation -cnotin @('create-client-script-file-probe','set-client-script-file-probe-path')){throw 'SCRIPT_FILE_PROBE_PATH_NOT_ALLOWED'}
        $request['relativePath']=$ClientScriptRelativePath
    }
    if($Operation -ceq 'author-entity-tag') {
        $request['action']=$TagAction
        $request['probeId']=$TagProbeId
        $request['entityId']=$TagEntityId
        if($TagAction -ceq 'set') {
            if($null -eq $TagSelected){throw 'ENTITY_TAG_SELECTED_REQUIRED'}
            $request['tagId']=$TagId
            $request['selected']=[bool]$TagSelected
            $request['expectedTagsSha256']=$ExpectedTagsSha256
        }
    }
    if($Operation -ceq 'inspect-entity-components') {
        if($EntityId -eq 0){throw 'ENTITY_COMPONENT_ID_REQUIRED'}
        $request['entityId']=$EntityId
    }
    # The read-only REFLECTION probe (ReflectionProbe.cs). nameContains is REQUIRED (the
    # adapter also refuses a <4 char needle, but a missing field is refused here first so the
    # caller gets a named refusal instead of an adapter-level one). memberContains is optional;
    # it is omitted when empty so the wire request mirrors a caller that never passed it.
    if($Operation -ceq 'reflection-probe') {
        if([string]::IsNullOrEmpty($NameContains)){throw 'REFLECTION_NAME_CONTAINS_REQUIRED'}
        $request['nameContains']=$NameContains
        if(-not [string]::IsNullOrEmpty($MemberContains)){$request['memberContains']=$MemberContains}
    }
    # The FIXED-NEEDLE siblings (reflection-probe-component/-template/-service). They are
    # deliberately NOT handled here: the needle lives in the adapter, not the request, so the
    # wire request stays {id,op,nonce} and passes a resident helper whose in-memory FIELD
    # allowlist predates these ops. Adding a nameContains field here would break exactly the
    # property that makes them callable at all. The op names above are in the ValidateSet so
    # the runner's per-request re-read of this file admits them.
    # The bounded component DELETE (EntityComponentDelete.cs). Same two-id shape as the
    # tag op: an entityId plus the componentId; `action` selects the adapter's self-owned
    # inspect read (no mutation) from the delete. probeId names the CRUD probe window the
    # target must belong to. The adapter re-derives every gate from these fields.
    if($Operation -ceq 'delete-entity-component') {
        if($EntityId -eq 0){throw 'ENTITY_COMPONENT_ID_REQUIRED'}
        $request['action']=$ComponentAction
        $request['probeId']=$ComponentProbeId
        $request['entityId']=$EntityId
        if($ComponentAction -ceq 'delete') {
            if($ComponentId -eq 0){throw 'COMPONENT_ID_REQUIRED'}
            $request['componentId']=$ComponentId
        }
    }
    # The bounded component ADD (EntityComponentAdd.cs). Same two-id shape as the delete op --
    # an entityId plus the componentId -- but `action` is 'inspect' or 'add' and the adapter
    # writes the editor's LOCAL component mirror instead of dispatching a native command.
    # probeId names the CRUD probe window the target must belong to; the adapter re-derives
    # every gate from these fields. componentId is carried ONLY for action=add.
    if($Operation -ceq 'add-entity-component') {
        if($EntityId -eq 0){throw 'ENTITY_COMPONENT_ID_REQUIRED'}
        $request['action']=$ComponentAction
        $request['probeId']=$ComponentProbeId
        $request['entityId']=$EntityId
        if($ComponentAction -ceq 'add') {
            if($ComponentId -eq 0){throw 'COMPONENT_ID_REQUIRED'}
            $request['componentId']=$ComponentId
        }
    }
    # The bounded INSTRUCTION-GRAPH delete (InstructionGraphDelete.cs). The graph id rides
    # the house `ids` field for graph resources; the edit-object id rides `entityId`. The
    # adapter re-derives every gate from these fields, and REFUSES at
    # INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED when entityId is absent -- which is exactly what a
    # runner whose closed schema predates this op will cause, since it admits no entityId.
    if($Operation -ceq 'delete-instruction-graph' -or $Operation -ceq 'delete-instruction-graph-force' -or $Operation -ceq 'delete-instruction-graph-dry-run') {
        if(-not $Ids -or $Ids.Count -ne 1){throw 'INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED'}
        if($EntityId -eq 0){throw 'INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED'}
        $request['entityId']=$EntityId
    }
    if($null -ne $Ids -and $Ids.Count -gt 0){$request['ids']=$Ids}
    $writer.WriteLine(($request|ConvertTo-Json -Compress))
    $readTask=$reader.ReadLineAsync()
    # Bounded catalog/node/prefab queries walk the shared registry before the server
    # writes its reply (observed 12.48s); 10s cut the client off mid-response.
    # Exact read-only op matches only; all writes keep the original 10s window.
    $responseTimeoutMs=if($Operation -ceq 'delete-owned-entity-ids' -or $Operation -ceq 'delete-owned-entity-ids-dry-run' -or $Operation -ceq 'delete-owned-graph-ids' -or $Operation -ceq 'delete-owned-graph-ids-dry-run' -or $Operation -ceq 'delete-instruction-graph' -or $Operation -ceq 'delete-instruction-graph-force' -or $Operation -ceq 'delete-instruction-graph-dry-run' -or $Operation -ceq 'inspect-reopen-content' -or $Operation -ceq 'profile-reopen-content-sample' -or $Operation -ceq 'catalog' -or $Operation -ceq 'node-definition-variants' -or $Operation -ceq 'node-definitions' -or $Operation -ceq 'prefab-catalog' -or $Operation -ceq 'prefab-fields' -or $Operation -ceq 'prefab-fields-page' -or $Operation -ceq 'client-script-catalog' -or $Operation -ceq 'client-script-root' -or $Operation -ceq 'reflection-probe' -or $Operation -ceq 'reflection-probe-component' -or $Operation -ceq 'reflection-probe-template' -or $Operation -ceq 'reflection-probe-service' -or $Operation -ceq 'reflection-editor-add' -or $Operation -ceq 'reflection-editor-create' -or $Operation -ceq 'reflection-editor-services' -or $Operation -ceq 'reflection-editor-types' -or $Operation -ceq 'mine-process-strings'){60000}else{10000}
    if(-not $readTask.Wait($responseTimeoutMs)){throw 'RESPONSE_TIMEOUT_NOT_PROOF_OF_NO_EFFECT'}
    $reply=$readTask.Result
    if($null -eq $reply){throw 'BRIDGE_CLOSED_WITHOUT_RESPONSE'}
    $reply | Set-Content -LiteralPath (Join-Path $runDir ($Operation+'-response.json')) -Encoding utf8
    Write-Output $reply
} finally {
    if($reader){$reader.Dispose()}; if($writer){$writer.Dispose()}; $pipe.Dispose()
}
