# Offline-drafted fixed reopen lifecycle only. Dot-sourcing defines functions; it starts nothing.
# Caller holds the existing pinned-source lease. No function launches a process or calls the game.
Set-StrictMode -Version Latest
function Assert-ReopenExact($Object,[string[]]$Names) {
 if($null -eq $Object){throw 'REOPEN_OBJECT_REQUIRED'}
 $keys=@(if($Object -is [Collections.IDictionary]){$Object.Keys}elseif($Object -is [Management.Automation.PSCustomObject]){$Object.PSObject.Properties.Name}else{throw 'REOPEN_OBJECT_REQUIRED'})
 if($keys.Count -ne $Names.Count -or @($keys|Where-Object {$_ -cnotin $Names}).Count){throw 'REOPEN_FIELDS_INVALID'}
}
function Assert-ReopenId($Value) {if(-not($Value -is [string]) -or $Value -cnotmatch '^[0-9a-f]{32}$'){throw 'REOPEN_REQUEST_ID_INVALID'}}
function Assert-ReopenHash($Value) {if(-not($Value -is [string]) -or $Value -cnotmatch '^[0-9a-f]{64}$'){throw 'REOPEN_HASH_INVALID'}}
function Assert-ReopenOrdinary([string]$Path) {
 $full=[IO.Path]::GetFullPath($Path);$item=$full
 while($item){if([IO.File]::Exists($item) -or [IO.Directory]::Exists($item)){if(([IO.File]::GetAttributes($item)-band[IO.FileAttributes]::ReparsePoint)-ne0){throw 'REOPEN_REPARSE'}};$parent=[IO.Path]::GetDirectoryName($item);if($parent -eq $item){break};$item=$parent}
 return $full
}
function Get-ReopenPaths([string]$Store,[string]$RequestId) {
 Assert-ReopenId $RequestId;$root=Assert-ReopenOrdinary $Store
 if(-not[IO.Directory]::Exists($root)){throw 'REOPEN_STORE_MISSING'}
 $work=Join-Path $root $RequestId
 return @{root=$root;work=$work;active=(Join-Path $root 'native-active.json');claim=(Join-Path $work 'reopen-claim.json');dispatch=(Join-Path $work 'reopen-dispatch.json');acceptance=(Join-Path $work 'reopen-acceptance.json');evidence=(Join-Path $work 'reopen-evidence-manifest.json');release=(Join-Path $work 'reopen-release.json');archive=(Join-Path $work 'reopen-released-active.json')}
}
function Get-ReopenArtifact([string]$Path,[int]$MaxBytes=65536) {
 $path=Assert-ReopenOrdinary $Path
 $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
 try {
  if($stream.Length -lt 2 -or $MaxBytes -notin @(65536,1048576) -or $stream.Length -gt $MaxBytes){throw 'REOPEN_ARTIFACT_SIZE'}
  $bytes=[byte[]]::new([int]$stream.Length);$offset=0
  while($offset -lt $bytes.Length){$n=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($n -le 0){throw 'REOPEN_ARTIFACT_PARTIAL'};$offset+=$n}
  $sha=[Security.Cryptography.SHA256]::Create();try{$hash=([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
  $value=[Text.UTF8Encoding]::new($false,$true).GetString($bytes)|ConvertFrom-Json
  return @{sha256=$hash;value=$value;bytes=$bytes}
 }finally{$stream.Dispose()}
}
function Write-ReopenExclusive([string]$Path,$Value) {
 $path=Assert-ReopenOrdinary $Path
 $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
 try {$bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 16 -Compress));$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}
function Invoke-ReopenStoreGate([string]$Store,[scriptblock]$Body) {
 $root=Assert-ReopenOrdinary $Store;$gate=Join-Path $root 'reopen-store.gate'
 $stream=[IO.File]::Open($gate,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 try {& $Body}finally{$stream.Dispose()}
}
function Assert-ReopenLease($Lease) {
 Assert-ReopenExact $Lease @('schema','action','requestId','levelId','sessionPath','sessionSha256','bridgeRunId','reviewSha256','accountBaselineSha256','acceptanceVerifierSha256','pinsDigest','createdUtc')
 if($Lease.schema -ne 1 -or $Lease.action -cne 'reopen-current' -or $Lease.levelId -ne 1073741840){throw 'REOPEN_LEASE_CONTRACT'}
 Assert-ReopenId $Lease.requestId
 foreach($key in @('sessionSha256','reviewSha256','accountBaselineSha256','acceptanceVerifierSha256','pinsDigest')){Assert-ReopenHash $Lease.$key}
 if(-not($Lease.sessionPath -is [string]) -or -not[IO.Path]::IsPathRooted($Lease.sessionPath)){throw 'REOPEN_SESSION_PATH'}
 $guid=[Guid]::Empty;if(-not[Guid]::TryParseExact($Lease.bridgeRunId,'D',[ref]$guid) -or $guid.ToString('D') -cne $Lease.bridgeRunId){throw 'REOPEN_BRIDGE_RUN_ID'}
}
function New-ReopenPending([string]$Store,[string]$RequestId,$Binding) {
 # Binding is internal: copied from the already validated request/review/session and pinned helper.
 Assert-ReopenExact $Binding @('sessionPath','sessionSha256','bridgeRunId','reviewSha256','accountBaselineSha256','acceptanceVerifierSha256','pinsDigest')
 $paths=Get-ReopenPaths $Store $RequestId
 Invoke-ReopenStoreGate $Store {
  if(Test-Path -LiteralPath $paths.active){throw 'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED'}
  if(Test-Path -LiteralPath $paths.claim){throw 'REOPEN_ALREADY_CLAIMED_NO_REPLAY'}
  $lease=[ordered]@{schema=1;action='reopen-current';requestId=$RequestId;levelId=1073741840;sessionPath=$Binding.sessionPath;sessionSha256=$Binding.sessionSha256;bridgeRunId=$Binding.bridgeRunId;reviewSha256=$Binding.reviewSha256;accountBaselineSha256=$Binding.accountBaselineSha256;acceptanceVerifierSha256=$Binding.acceptanceVerifierSha256;pinsDigest=$Binding.pinsDigest;createdUtc=[DateTime]::UtcNow.ToString('o')}
  Assert-ReopenLease $lease
  $session=Get-ReopenArtifact $lease.sessionPath;if($session.sha256 -cne $lease.sessionSha256){throw 'REOPEN_SESSION_CHANGED'}
  [IO.Directory]::CreateDirectory($paths.work)|Out-Null;Assert-ReopenOrdinary $paths.work|Out-Null
  Write-ReopenExclusive $paths.claim $lease
  # Keep active immutable. Same serialized bytes permit exact identity checks and crash recovery.
  $claim=Get-ReopenArtifact $paths.claim
  $file=[IO.File]::Open($paths.active,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  try{$file.Write($claim.bytes,0,$claim.bytes.Length);$file.Flush($true)}finally{$file.Dispose()}
  return @{requestId=$RequestId;leaseSha256=$claim.sha256;businessPending=$true;retryAttempted=$false}
 }
}
function Get-ReopenActive([string]$Store) {
 $active=Join-Path (Assert-ReopenOrdinary $Store) 'native-active.json'
 if(-not(Test-Path -LiteralPath $active)){return $null}
 $a=Get-ReopenArtifact $active;Assert-ReopenLease $a.value
 $paths=Get-ReopenPaths $Store $a.value.requestId;$claim=Get-ReopenArtifact $paths.claim
 if($a.sha256 -cne $claim.sha256){throw 'REOPEN_ACTIVE_CLAIM_MISMATCH'}
 return $a
}
function Assert-ReopenDispatch($Dispatch,$Lease,[string]$LeaseSha256) {
 Assert-ReopenExact $Dispatch @('schema','requestId','leaseSha256','nativeReceiptSha256','preflightPassed','nativeCallAttempted','nativeCallReturned','callExceptionCode','hookCleanupVerified','status','businessPending','businessVerified','reopenVerified','retryAttempted')
 if($Dispatch.schema -ne 1 -or $Dispatch.requestId -cne $Lease.requestId -or $Dispatch.leaseSha256 -cne $LeaseSha256){throw 'REOPEN_DISPATCH_BINDING'}
 Assert-ReopenHash $Dispatch.nativeReceiptSha256
 foreach($key in @('preflightPassed','nativeCallAttempted','nativeCallReturned','hookCleanupVerified','businessPending','businessVerified','reopenVerified','retryAttempted')){if(-not($Dispatch.$key -is [bool])){throw 'REOPEN_DISPATCH_BOOLEAN'}}
 if(-not$Dispatch.businessPending -or $Dispatch.businessVerified -or $Dispatch.reopenVerified -or $Dispatch.retryAttempted){throw 'REOPEN_DISPATCH_PREMATURE_SUCCESS'}
 if(-not($Dispatch.callExceptionCode -is [int] -or $Dispatch.callExceptionCode -is [long] -or $Dispatch.callExceptionCode -is [uint32]) -or $Dispatch.callExceptionCode -lt 0 -or $Dispatch.callExceptionCode -gt 4294967295){throw 'REOPEN_EXCEPTION_CODE'}
 if($Dispatch.nativeCallReturned -and (-not$Dispatch.nativeCallAttempted -or $Dispatch.callExceptionCode -ne 0)){throw 'REOPEN_DISPATCH_RETURN_INVALID'}
 if($Dispatch.nativeCallAttempted -and -not$Dispatch.preflightPassed){throw 'REOPEN_DISPATCH_CALL_INVALID'}
 $expected=if($Dispatch.nativeCallReturned){'dispatch-returned-business-pending'}elseif($Dispatch.nativeCallAttempted){'dispatch-uncertain-business-pending'}else{'dispatch-refused-no-call'}
 if($Dispatch.status -cne $expected){throw 'REOPEN_DISPATCH_STATUS'}
}
function Save-ReopenDispatch([string]$Store,[string]$RequestId,$Dispatch) {
 $paths=Get-ReopenPaths $Store $RequestId
 Invoke-ReopenStoreGate $Store {
  $active=Get-ReopenActive $Store;if($null -eq $active -or $active.value.requestId -cne $RequestId){throw 'REOPEN_ACTIVE_ID_MISMATCH'}
  Assert-ReopenDispatch $Dispatch $active.value $active.sha256
  Write-ReopenExclusive $paths.dispatch $Dispatch
  # Hook cleanup never clears native-active, even when the dispatcher returned normally.
  return @{requestId=$RequestId;status=$Dispatch.status;hookCleanupVerified=$Dispatch.hookCleanupVerified;businessPending=$true;safeToRelease=$false}
 }
}
function Get-ReopenPendingSummary([string]$Store) {
 $a=Get-ReopenActive $Store;if($null -eq $a){return $null}
 $paths=Get-ReopenPaths $Store $a.value.requestId;$clean=$false;$status='dispatch-outcome-unrecorded'
 if(Test-Path -LiteralPath $paths.dispatch){$d=Get-ReopenArtifact $paths.dispatch;Assert-ReopenDispatch $d.value $a.value $a.sha256;$clean=$d.value.hookCleanupVerified;$status=$d.value.status}
 return @{action='reopen-current';requestId=$a.value.requestId;levelId=1073741840;sessionPath=$a.value.sessionPath;hookCleanupVerified=$clean;status=$status;businessPending=$true}
}
function Test-ReopenPendingRequest([string]$Store,$Request) {
 $activePath=Join-Path $Store 'native-active.json'
 if(-not(Test-Path -LiteralPath $activePath)){return $true}
 # Existing ordinary validators still run. These are only additional pending-write restrictions.
 if($Request.kind -ceq 'status'){Assert-ReopenExact $Request @('kind');return $true}
 if($Request.kind -ceq 'fs' -and $Request.op -cin @('stat','list','read','hash')){return $true}
 $a=Get-ReopenActive $Store;if($null -eq $a){throw 'REOPEN_ACTIVE_CHANGED'};$lease=$a.value
 if($Request.kind -ceq 'call'){
  Assert-ReopenExact $Request @('kind','runId','op')
  return ($Request.runId -ceq $lease.bridgeRunId -and $Request.op -cin @('log-observer-evidence','inspect-reopen-content'))
 }
 if($Request.kind -ceq 'native-scene'){
  if($Request.action -cne 'inspect'){return $false}
  $keys=@(if($Request -is [Collections.IDictionary]){$Request.Keys}else{$Request.PSObject.Properties.Name})
  $fields=@('kind','action','sessionPath','levelId')
  if($keys -ccontains 'reopenPrerequisites'){
    if(-not($Request.reopenPrerequisites -is [bool]) -or $Request.reopenPrerequisites -ne $true){throw 'REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY'}
    $fields+='reopenPrerequisites'
  }
  Assert-ReopenExact $Request $fields
  if($Request.levelId -ne 1073741840 -or $Request.sessionPath -cne $lease.sessionPath){return $false}
  $current=Get-ReopenArtifact $lease.sessionPath;if($current.sha256 -cne $lease.sessionSha256){throw 'REOPEN_SESSION_CHANGED'}
  if(Test-Path -LiteralPath (Join-Path $Store 'reopen-inspect-active.json')){return $false}
  $summary=Get-ReopenPendingSummary $Store
  return ($summary.hookCleanupVerified -is [bool] -and $summary.hookCleanupVerified)
 }
 if($Request.kind -ceq 'native-reopen-reconcile'){
  Assert-ReopenExact $Request @('kind','requestId','acceptanceSha256');Assert-ReopenId $Request.requestId;Assert-ReopenHash $Request.acceptanceSha256
  return $Request.requestId -ceq $lease.requestId
 }
 return $false
}
function Test-ReopenLegacyTerminalRelease([string]$Action,$Reply) {
 # Add this as the FIRST guard inside Test-NativeTerminalSafe, with action supplied by the helper.
 # Do not infer dispatch action from the untrusted reply.
 if($Action -ceq 'reopen-current'){return $false}
 return $true # Caller continues existing legacy cleanup validation; this is not release approval.
}
function Complete-ReopenReconciliation([string]$Store,[string]$RequestId,[string]$AcceptanceSha256) {
 $paths=Get-ReopenPaths $Store $RequestId;Assert-ReopenHash $AcceptanceSha256
 Invoke-ReopenStoreGate $Store {
  if(Test-Path -LiteralPath (Join-Path $Store 'reopen-inspect-active.json')){throw 'REOPEN_READONLY_PROBE_UNRESOLVED'}
  $already=-not(Test-Path -LiteralPath $paths.active)
  if($already){
   if(-not(Test-Path -LiteralPath $paths.release)){throw 'REOPEN_RELEASE_MISSING'}
   $a=Get-ReopenArtifact $paths.archive;Assert-ReopenLease $a.value
   $claim=Get-ReopenArtifact $paths.claim;if($a.sha256 -cne $claim.sha256){throw 'REOPEN_ARCHIVE_CLAIM_MISMATCH'}
  }else{$a=Get-ReopenActive $Store}
  if($a.value.requestId -cne $RequestId){throw 'REOPEN_ACTIVE_ID_MISMATCH'}
  $d=Get-ReopenArtifact $paths.dispatch;Assert-ReopenDispatch $d.value $a.value $a.sha256
  if(-not$d.value.nativeCallAttempted -or -not$d.value.nativeCallReturned -or -not$d.value.hookCleanupVerified -or $d.value.callExceptionCode -ne 0){throw 'REOPEN_DISPATCH_NOT_RECONCILABLE'}
  $v=Get-ReopenArtifact $paths.acceptance;if($v.sha256 -cne $AcceptanceSha256){throw 'REOPEN_ACCEPTANCE_HASH'}
  $v=$v.value
  Assert-ReopenExact $v @('schema','operation','scope','requestId','levelId','leaseSha256','dispatchSha256','nativeReceiptSha256','reviewSha256','accountBaselineSha256','verifierSourceSha256','inputsSha256','dependenciesSha256','verificationResultSha256','businessVerified','reopenRoundtripVerified','formalParameterMappingVerified','formalGeometryMappingVerified','internalCoroutineCompletionVerified','checks')
  if($v.schema -ne 2 -or $v.operation -cne 'level.reopen-current' -or $v.scope -cne 'fixed-1839-reopen-roundtrip' -or $v.levelId -ne 1073741840 -or $v.requestId -cne $RequestId -or $v.leaseSha256 -cne $a.sha256 -or
     $v.dispatchSha256 -cne $d.sha256 -or $v.nativeReceiptSha256 -cne $d.value.nativeReceiptSha256 -or $v.reviewSha256 -cne $a.value.reviewSha256 -or
     $v.accountBaselineSha256 -cne $a.value.accountBaselineSha256 -or $v.verifierSourceSha256 -cne $a.value.acceptanceVerifierSha256){throw 'REOPEN_ACCEPTANCE_BINDING'}
  foreach($key in @('businessVerified','reopenRoundtripVerified')){if(-not($v.$key -is [bool]) -or -not$v.$key){throw 'REOPEN_BUSINESS_NOT_VERIFIED'}}
  foreach($key in @('formalParameterMappingVerified','formalGeometryMappingVerified','internalCoroutineCompletionVerified')){if(-not($v.$key -is [bool]) -or $v.$key){throw 'REOPEN_UNSUPPORTED_ACCEPTANCE_CLAIM'}}
  $checks=@('dispatchExactlyOnce','loadOccurredAfterDispatch','freshInitializationBound','nativeEntitySetMatchesFormal','editorRoundtripPreserved','formalEntityGraphStructureMatches','bindingsMatch','protectedFilesAndMetadataUnchanged','ipcIdentityPreserved','noObserverErrors','hookCleanupVerified')
  Assert-ReopenExact $v.checks $checks
  foreach($key in $checks){if(-not($v.checks.$key -is [bool]) -or -not$v.checks.$key){throw ('REOPEN_ACCEPTANCE_CHECK:'+ $key)}}
  foreach($key in @('inputsSha256','dependenciesSha256','verificationResultSha256')){Assert-ReopenHash $v.$key}
  foreach($pair in @(@('reopen-inputs.json','inputsSha256'),@('reopen-verifier-dependencies.json','dependenciesSha256'),@('reopen-verification.json','verificationResultSha256'))){
   $proof=Get-ReopenArtifact (Join-Path $paths.work $pair[0]) 1048576
   if($proof.sha256 -cne $v.($pair[1])){throw ('REOPEN_PROOF_CHANGED:'+ $pair[0])}
  }
  # Always recompute raw decisions. An artifact hash or its booleans cannot release ownership.
  $fresh=Invoke-ReopenIndependentVerifier $paths.work $AcceptanceSha256 $a.value.acceptanceVerifierSha256
  Assert-ReopenExact $fresh @('ok','schema','requestId','scope','acceptanceSha256','inputsSha256')
  if(-not($fresh.ok -is [bool]) -or -not$fresh.ok -or $fresh.schema -ne 2 -or $fresh.requestId -cne $RequestId -or $fresh.scope -cne $v.scope -or $fresh.acceptanceSha256 -cne $AcceptanceSha256 -or $fresh.inputsSha256 -cne $v.inputsSha256){throw 'REOPEN_INDEPENDENT_VERIFIER_REFUSED'}

  $record=[ordered]@{schema=1;requestId=$RequestId;leaseSha256=$a.sha256;dispatchSha256=$d.sha256;acceptanceSha256=$AcceptanceSha256;inputsSha256=$v.inputsSha256;scope=$v.scope;businessVerified=$true;formalParameterMappingVerified=$false}
  if(Test-Path -LiteralPath $paths.release){$old=Get-ReopenArtifact $paths.release;foreach($key in $record.Keys){if($old.value.$key -cne $record[$key]){throw 'REOPEN_RELEASE_CONFLICT'}}}
  else{Write-ReopenExclusive $paths.release $record}
  # Last mutation: an atomic in-directory rename archives ownership rather than deleting evidence.
  # Both resolved paths are constructed by Get-ReopenPaths under this fixed store; no caller path.
  if(-not$already){[IO.File]::Move($paths.active,$paths.archive)}
  return @{requestId=$RequestId;status='reopen-roundtrip-verified';scope='fixed-1839-reopen-roundtrip';businessVerified=$true;reopenRoundtripVerified=$true;formalParameterMappingVerified=$false;lockReleased=$true;alreadyReconciled=$already;retryAttempted=$false}
 }
}

function New-ReopenInspectionClaim([string]$Store,[string]$OriginalRequestId,[string]$InspectionRequestId) {
 Assert-ReopenId $OriginalRequestId;Assert-ReopenId $InspectionRequestId
 if($OriginalRequestId -ceq $InspectionRequestId){throw 'REOPEN_INSPECT_ID_REUSE'}
 $paths=Get-ReopenPaths $Store $InspectionRequestId
 Invoke-ReopenStoreGate $Store {
  $summary=Get-ReopenPendingSummary $Store
  if($null -eq $summary -or $summary.requestId -cne $OriginalRequestId -or -not$summary.hookCleanupVerified){throw 'REOPEN_INSPECT_CONTEXT'}
  $marker=Join-Path $Store 'reopen-inspect-active.json'
  if(Test-Path -LiteralPath $marker){throw 'REOPEN_READONLY_PROBE_UNRESOLVED'}
  [IO.Directory]::CreateDirectory($paths.work)|Out-Null
  $value=@{schema=1;action='inspect';requestId=$InspectionRequestId;originalRequestId=$OriginalRequestId}
  Write-ReopenExclusive (Join-Path $paths.work 'reopen-inspect-claim.json') $value
  Write-ReopenExclusive $marker $value
 }
}
function Complete-ReopenInspectionClaim([string]$Store,[string]$OriginalRequestId,[string]$InspectionRequestId,[bool]$TerminalSafe) {
 Assert-ReopenId $OriginalRequestId;Assert-ReopenId $InspectionRequestId
 if(-not$TerminalSafe){return $false}
 $paths=Get-ReopenPaths $Store $InspectionRequestId
 Invoke-ReopenStoreGate $Store {
  $a=Get-ReopenActive $Store
  if($null -eq $a -or $a.value.requestId -cne $OriginalRequestId){throw 'REOPEN_INSPECT_PARENT_CHANGED'}
  $marker=Join-Path $Store 'reopen-inspect-active.json';$m=Get-ReopenArtifact $marker
  Assert-ReopenExact $m.value @('schema','action','requestId','originalRequestId')
  if($m.value.schema -ne 1 -or $m.value.action -cne 'inspect' -or $m.value.requestId -cne $InspectionRequestId -or $m.value.originalRequestId -cne $OriginalRequestId){throw 'REOPEN_INSPECT_OWNER_CHANGED'}
  $claim=Get-ReopenArtifact (Join-Path $paths.work 'reopen-inspect-claim.json')
  if($claim.sha256 -cne $m.sha256){throw 'REOPEN_INSPECT_CLAIM_CHANGED'}
  [IO.File]::Move($marker,(Join-Path $paths.work 'reopen-inspect-released.json'))
  return $true
 }
}

function Get-ReopenAcceptancePinFiles([string]$Root,[string]$Python) {
 $files=[Collections.Generic.List[string]]::new()
 foreach($relative in @('tools/game-executor/native_reopen_acceptance.py','tools/game-executor/verify-created-save.py','tools/editor-bridge/audit-native-enums.py','tools/editor-bridge/build-newdemo-static.py','tools/editor-bridge/build-static-level-draft.py','tools/editor-bridge/connection-evidence.py','tools/beyond-save/gil_container.py')){$files.Add((Join-Path $Root $relative))}
 $site=Join-Path ([IO.Path]::GetDirectoryName($Python)) 'Lib/site-packages'
 $files.Add((Join-Path $site 'typing_extensions.py'))
 $directories=[Collections.Generic.List[string]]::new();$directories.Add((Join-Path $Root 'third_party/auto-miliastra/src/miliastra_agent'))
 foreach($package in @('google/protobuf','google/_upb','pydantic','pydantic_core','typing_inspection','annotated_types')){$directories.Add((Join-Path $site $package))}
 foreach($directory in $directories){
  $null=Assert-ReopenOrdinary $directory;if(-not[IO.Directory]::Exists($directory)){throw 'REOPEN_VERIFIER_DEPENDENCY_DIRECTORY'}
  foreach($file in Get-ChildItem -LiteralPath $directory -Recurse -File){if($file.Extension -in @('.py','.pyd','.dll') -and $file.FullName -notmatch '[\\/]__pycache__[\\/]'){$files.Add($file.FullName)}}
 }
 foreach($file in $files){$null=Assert-ReopenOrdinary $file;if(-not[IO.File]::Exists($file)){throw 'REOPEN_VERIFIER_DEPENDENCY_MISSING'}}
 return @($files.ToArray()|Sort-Object -Unique)
}
function Assert-ReopenProductionReconciliationEnabled {
 if($null -eq (Get-Variable nativePython -ErrorAction SilentlyContinue) -or $null -eq (Get-Variable dispatchPins -ErrorAction SilentlyContinue)){throw 'REOPEN_VERIFIER_RUNTIME_NOT_PINNED'}
 $scriptPath=Join-Path (Split-Path $PSScriptRoot -Parent) 'game-executor/native_reopen_acceptance.py'
 if(-not[IO.File]::Exists($scriptPath) -or -not$dispatchPins.ContainsKey([IO.Path]::GetFullPath($scriptPath))){throw 'REOPEN_BUSINESS_VERIFIER_NOT_PINNED'}
}
function Invoke-ReopenIndependentVerifier([string]$Work,[string]$AcceptanceSha256,[string]$VerifierSha256) {
 Assert-ReopenProductionReconciliationEnabled
 $scriptPath=Join-Path (Split-Path $PSScriptRoot -Parent) 'game-executor/native_reopen_acceptance.py'
 $scriptPath=Assert-ReopenOrdinary $scriptPath
 if((Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $VerifierSha256){throw 'REOPEN_VERIFIER_SOURCE_CHANGED'}
 $json=& $nativePython -B -I -S $scriptPath --verify-work $Work --acceptance-sha256 $AcceptanceSha256
 if($LASTEXITCODE -ne 0){throw ('REOPEN_INDEPENDENT_VERIFIER_FAILED: '+($json -join ' '))}
 return (($json -join [Environment]::NewLine)|ConvertFrom-Json)
}
