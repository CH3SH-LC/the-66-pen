# elevated-runner.ps1 -- one-time elevation, then a narrow standing helper.
#
# WHY THIS EXISTS
#   The editor runs elevated. Loading the bridge into it needs elevation, and the
#   bridge's pipe is created with PipeOptions.CurrentUserOnly from that elevated
#   process, so a non-elevated client is refused. That made every load *and* every
#   call raise a UAC prompt. This helper is elevated ONCE and then, for as long as
#   it is asked to, performs only those fixed actions on request.
#
# WHAT IT WILL AND WILL NOT DO
#   It accepts closed request kinds; no caller selects a command or script:
#     native-scene -> fixed pinned scene_cli data-only action/review protocol
#     author-graph -> fixed pinned graph dispatcher with runId/requestId only
#     native-map -> fixed terrain/transform/playtest-observation dispatcher, one prepared run only
#     {"kind":"status"}                                  -> its own state, no side effects
#     {"kind":"load", "targetPid":<int>}                 -> runs new-scope.ps1 + load-bridge.ps1
#     {"kind":"call", "runId":"<guid>", "op":"<name>"}   -> runs call-bridge.ps1
#       node-definitions additionally requires ids: 1..64 nonzero uint32 values
#     {"kind":"call", "runId":"<guid>", "op":"node-definitions", "ids":[1,2,3]}
#                                                        -> same, with ids forwarded
#     {"kind":"fs",   "op":"<name>", ...}                -> see FILE OPERATIONS below
#   It never executes a command supplied in a request. The bridge operation name must
#   match the ValidateSet already declared inside call-bridge.ps1, which is re-read
#   per request so the two cannot drift. The runId must be a GUID naming an existing
#   run directory under .runtime/editor-bridge/runs. File operations are implemented
#   in elevated-fs-ops.ps1 and policed by elevated-fs-guard.ps1.
#
#   A call request carries a closed set of fields -- kind, runId, op and ids, nothing
#   else. ids is forwarded to call-bridge.ps1 -Ids for exactly one operation, the
#   literally-spelled node-definitions, and is refused for every other op and every
#   other request kind, including a null or empty ids. See REQUEST SHAPE VALIDATION
#   below. Unlike the fs ops, no call field is ever operation-specific payload.
#
#   Native-scene calls only the fixed reviewed scene CLI. The helper does not manage
#   or terminate game/editor processes, and never retries an uncertain operation.
#
# FILE OPERATIONS (kind "fs")
#   Ops: stat, list, read, write, mkdir, copy, move, delete, hash, snapshot.
#   Every path -- source AND destination -- is put through Resolve-GuardedPath in
#   elevated-fs-guard.ps1, which canonicalises it, requires it to sit under a root
#   from elevated-config.json on a separator boundary, refuses any component that is
#   a junction or symlink, and checks that the matched root grants the access kind.
#   The allow-list is read ONCE, before the loop starts: widening it deliberately
#   costs one UAC prompt, so a caller holding only the queue directory cannot expand
#   its own reach. delete and move additionally require "confirm" to repeat the
#   target path exactly, so a mangled or truncated request cannot silently destroy
#   something.
#
# LIFETIME
#   Stops on: a file named STOP in the queue directory, the deadline below, or Ctrl-C.
#   The default deadline is 24 hours -- deliberately longer than a night's sleep, so
#   nothing expires mid-run and raises a prompt while the user is away. It is still
#   bounded, and it does not survive a reboot.
#
# QUEUE PROTOCOL (all under .runtime/editor-bridge/elevated-queue/)
#   <id>.request.json   written by the caller
#   <id>.response.json  written by this helper (the bridge's raw reply, or fs result)
#   <id>.error.txt      written by this helper on failure
#   runner.log          append-only log of every request handled
#   runner.heartbeat    rewritten every loop; proves the helper is still alive

param(
  [int]$LifetimeMinutes = 1440,
  [string]$QueueDir = '',
  [string]$ConfigPath = '',
  [string]$DeadlineUtc = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This helper runs with a hidden window, so a fatal error during startup is
# otherwise indistinguishable from "the user never answered the UAC prompt": both
# look like a process that never appeared. Record it where the unprivileged
# launcher can find it. Every root is recomputed from $PSScriptRoot so this works
# even if the failure happens before the parameters below are resolved.
trap {
  $message = $_.Exception.GetType().FullName + ': ' + $_.Exception.Message +
             [Environment]::NewLine + $_.ScriptStackTrace
  try {
    $fallbackRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $fallbackQueue = if ([string]::IsNullOrWhiteSpace($QueueDir)) {
      Join-Path $fallbackRoot '.runtime/editor-bridge/elevated-queue'
    } else { [IO.Path]::GetFullPath($QueueDir) }
    New-Item -ItemType Directory -Force -Path $fallbackQueue | Out-Null
    [IO.File]::WriteAllText(
      (Join-Path $fallbackQueue 'runner.startup-error.txt'),
      $message,
      (New-Object System.Text.UTF8Encoding($false))
    )
  } catch { }
  exit 1
}

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if ([string]::IsNullOrWhiteSpace($QueueDir)) {
  $QueueDir = Join-Path $projectRoot '.runtime/editor-bridge/elevated-queue'
}
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $PSScriptRoot 'elevated-config.json'
}
$runsRoot    = Join-Path $projectRoot '.runtime/editor-bridge/runs'
$backupsRoot = Join-Path $projectRoot '.runtime/editor-bridge/backups'
New-Item -ItemType Directory -Force -Path $QueueDir | Out-Null

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'RUNNER_NOT_ELEVATED' }

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'elevated-fs-guard.ps1')))
. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'elevated-fs-ops.ps1')))
. (Join-Path $PSScriptRoot 'reopen-lifecycle.ps1')

# The allow-list is resolved before the loop so a bad config fails loudly at launch,
# in front of the user who just clicked through UAC, rather than at 3am.
$fsRoots = Import-ElevatedConfig -ConfigPath ([IO.Path]::GetFullPath($ConfigPath))

# Operation whitelist is taken from call-bridge.ps1 itself, so it cannot drift.
# call-bridge.ps1 on disk remains the single source of truth; nothing here widens
# what may run.
$callScript = Join-Path $PSScriptRoot 'call-bridge.ps1'
function Get-AllowedOps {
  $text  = [IO.File]::ReadAllText($callScript, $utf8NoBom)
  $match = [regex]::Match($text, "ValidateSet\((?<set>[^)]*)\)")
  if (-not $match.Success) { throw 'CANNOT_READ_OPERATION_WHITELIST' }
  return @([regex]::Matches($match.Groups['set'].Value, "'([^']+)'") | ForEach-Object { $_.Groups[1].Value })
}
$allowedOps = Get-AllowedOps

$fsOps = @('stat', 'list', 'read', 'write', 'mkdir', 'copy', 'move', 'delete', 'hash', 'snapshot')

$logPath       = Join-Path $QueueDir 'runner.log'
$heartbeatPath = Join-Path $QueueDir 'runner.heartbeat'
$stopPath      = Join-Path $QueueDir 'STOP'
# Both sides of the deadline comparison must be on the same clock.
#
# $deadline is derived from UtcNow, so it is UTC. Get-Date returns LOCAL time. Comparing
# them directly compares raw ticks across two clocks, which on this machine is an error
# of the whole UTC offset -- and the helper shut down eight hours early (started
# 09-17T17:03Z, exited 09-18T09:03Z with a 1440-minute lifetime). The same mistake was
# fixed in start-elevated.ps1's heartbeat check and missed here.
$startedUtc    = [DateTime]::UtcNow
$deadline      = $startedUtc.AddMinutes($LifetimeMinutes)
if (-not [string]::IsNullOrWhiteSpace($DeadlineUtc)) {
  $absoluteDeadline = [DateTimeOffset]::Parse($DeadlineUtc).UtcDateTime
  if ($absoluteDeadline -le $startedUtc) { throw 'HELPER_ABSOLUTE_DEADLINE_EXPIRED' }
  if ($absoluteDeadline -lt $deadline) { $deadline = $absoluteDeadline }
}

function Write-Log([string]$message) {
  $line = '{0} {1}' -f (Get-Date).ToUniversalTime().ToString('o'), $message
  Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}

function Read-JsonFile([string]$Path) {
  return ([IO.File]::ReadAllText($Path, $utf8NoBom) | ConvertFrom-Json)
}

function Write-JsonFile([string]$Path, $Object) {
  # A native call can outlast the 30-second client freshness window. Refresh
  # before publishing its reply, so the next serial request does not see the
  # pre-call heartbeat during the outer loop's 700 ms pause. This does not
  # release native-active or change any outcome/cleanup decision.
  [IO.File]::WriteAllText($heartbeatPath, ([DateTime]::UtcNow.ToString('o') + " pid=$PID handled=$handled"), $utf8NoBom)
  [IO.File]::WriteAllText($Path, ($Object | ConvertTo-Json -Depth 64), $utf8NoBom)
}

# REQUEST SHAPE VALIDATION
#   The queue directory is writable by whoever can reach it, so a request body is
#   untrusted input. What a body may say is therefore decided BEFORE any branch runs.
#   Deciding it inside each branch instead would let an ids field that the branch does
#   not understand be silently ignored rather than refused, which is exactly how an
#   ids meant for one operation ends up attached to another.
#
#   Both functions are deliberately self-contained: they call nothing defined in this
#   file and read no script-scope variable, so an AST extractor can lift them out and
#   exercise them in isolation.
function Assert-RequestIdsScope {
  param([object]$Request)
  if ($null -eq $Request) { return }

  # Ordinal keys: the documented names are lowerCamelCase and the real caller
  # (tools/editor-bridge/elevated-request.py) writes them that way.
  $props = [System.Collections.Hashtable]::new([System.StringComparer]::Ordinal)
  if ($Request -is [System.Collections.IDictionary]) {
    foreach ($key in @($Request.Keys)) { $props[[string]$key] = $Request[$key] }
  } else {
    foreach ($p in @($Request.PSObject.Properties)) { $props[[string]$p.Name] = $p.Value }
  }

  foreach($name in @($props.Keys)) {
    if([string]$name -ieq 'relativePath') {
      if(-not $props.ContainsKey('kind') -or $props['kind'] -isnot [string] -or $props['kind'] -cne 'call' -or -not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cnotin @('create-client-script-file-probe','set-client-script-file-probe-path')){throw 'SCRIPT_FILE_PROBE_PATH_NOT_ALLOWED'}
    }
  }

  # Tag fields belong only to the exact fixed call operation, including null presence.
  $tagFields=@('tagAction','tagProbeId','tagEntityId','tagId','tagSelected','expectedTagsSha256')
  foreach($name in @($props.Keys)) {
    if($tagFields -icontains [string]$name) {
      if(-not $props.ContainsKey('kind') -or $props['kind'] -isnot [string] -or $props['kind'] -cne 'call' -or -not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cne 'author-entity-tag'){throw 'ENTITY_TAG_FIELDS_NOT_ALLOWED'}
    }
  }

  # entityId belongs only to the ops that own it -- the compiled inspect-entity-components
  # probe and its two mutation siblings delete-entity-component / add-entity-component,
  # plus the delete-instruction-graph family whose edit-object id rides entityId --
  # matching the allowlist narrowing in Get-ValidatedCallArguments. Handled exactly like
  # relativePath above: it is refused by name on any other kind or op rather than silently
  # ignored, so a field meant for one operation cannot ride along unseen on another.
  # Presence, not value: the name is matched without case, and the value is not inspected
  # here, so even a null or zero entityId on a foreign request is still refused.
  foreach($name in @($props.Keys)) {
    if([string]$name -ieq 'entityId') {
      if(-not $props.ContainsKey('kind') -or $props['kind'] -isnot [string] -or $props['kind'] -cne 'call' -or -not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cnotin @('inspect-entity-components','delete-entity-component','add-entity-component','delete-instruction-graph','delete-instruction-graph-force','delete-instruction-graph-dry-run')){throw 'ENTITY_COMPONENT_ID_NOT_ALLOWED'}
    }
  }

  # probeId and componentId belong only to the two component mutation ops (delete and its
  # add sibling), exactly like entityId above.
  $componentDeleteFields=@('probeId','componentId')
  foreach($name in @($props.Keys)) {
    if($componentDeleteFields -icontains [string]$name) {
      if(-not $props.ContainsKey('kind') -or $props['kind'] -isnot [string] -or $props['kind'] -cne 'call' -or -not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cnotin @('delete-entity-component','add-entity-component')){throw 'COMPONENT_DELETE_FIELDS_NOT_ALLOWED'}
    }
  }

  # The read-only reflection probe's two name needles belong ONLY to a call for the
  # literally-spelled op 'reflection-probe'. Gated exactly like relativePath above, so a
  # nameContains meant for this op cannot ride along, unseen, on any other kind or op.
  $reflectionFields=@('nameContains','memberContains')
  foreach($name in @($props.Keys)) {
    if($reflectionFields -icontains [string]$name) {
      if(-not $props.ContainsKey('kind') -or $props['kind'] -isnot [string] -or $props['kind'] -cne 'call' -or -not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cne 'reflection-probe'){throw 'REFLECTION_PROBE_FIELDS_NOT_ALLOWED'}
    }
  }

  # `action` is the component mutation ops' own field, but a `native-scene` body legitimately
  # carries an `action` too (kind='native-scene', not 'call'). So this gate is CALL-scoped: an
  # `action` on a `call` for any op but delete-entity-component / add-entity-component is
  # refused by name rather than being silently ignored by a branch that never reads it.
  # Non-call kinds are left untouched so the native-scene `action` keeps working.
  foreach($name in @($props.Keys)) {
    if([string]$name -ieq 'action') {
      if($props.ContainsKey('kind') -and $props['kind'] -is [string] -and $props['kind'] -ceq 'call' -and (-not $props.ContainsKey('op') -or $props['op'] -isnot [string] -or $props['op'] -cnotin @('delete-entity-component','add-entity-component'))){throw 'COMPONENT_ACTION_NOT_ALLOWED'}
    }
  }

  # Presence, not value: an ids field that is null or empty still announces intent, so
  # it is still refused for every kind but "call". The name is matched without case so
  # a casing variant cannot slip past this gate.
  $hasIds = $false
  foreach ($key in @($props.Keys)) { if ([string]$key -ieq 'ids') { $hasIds = $true; break } }
  if (-not $hasIds) { return }

  $kind = $null
  foreach ($key in @($props.Keys)) { if ([string]$key -ieq 'kind') { $kind = $props[$key]; break } }
  if (-not ($kind -is [string]) -or ([string]$kind -cne 'call')) { throw 'IDS_NOT_ALLOWED' }
}

function Get-ValidatedCallArguments {
  param([object]$Request)
  if ($null -eq $Request) { throw 'CALL_REQUEST_INVALID' }

  $props = [System.Collections.Hashtable]::new([System.StringComparer]::Ordinal)
  if ($Request -is [System.Collections.IDictionary]) {
    foreach ($key in @($Request.Keys)) { $props[[string]$key] = $Request[$key] }
  } else {
    foreach ($p in @($Request.PSObject.Properties)) { $props[[string]$p.Name] = $p.Value }
  }

  # Closed schema. Refusing an unknown field by name keeps whatever an untrusted queue
  # entry carries from being mistaken for something a branch is meant to consume.
  $allowedFields = @('kind', 'runId', 'op', 'ids')
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -cin @('create-client-script-file-probe','set-client-script-file-probe-path')){$allowedFields+='relativePath'}
  # entityId is permitted for exactly two ops: the compiled inspect-entity-components probe
  # and its mutation sibling delete-entity-component. Each list is REPLACED here, never
  # widened -- exactly as the author-entity-tag branch below does. The generic list carries
  # `ids` for the node-query ops, and each of these ops early-returns (its branch below)
  # before the node-query validation that would otherwise refuse `ids`, so a widening would
  # let an ids field ride along unchecked. Narrowing to a list WITHOUT ids refuses it at the
  # closed-schema check directly below, preserving the pre-plumbing refusal: an ids field
  # never reaches call-bridge.ps1 for either op.
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -ceq 'inspect-entity-components'){$allowedFields=@('kind','runId','op','entityId')}
  # delete-entity-component: REPLACED (never widened) list, exactly like
  # the inspect-entity-components list above, for the same early-return reason.
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -ceq 'delete-entity-component'){$allowedFields=@('kind','runId','op','entityId','action','probeId','componentId')}
  # add-entity-component: REPLACED (never widened) list, exactly like the delete list above.
  # Its adapter (EntityComponentAdd.cs) reads the SAME four op-owned fields the delete does
  # (entityId + action + probeId + componentId); only the action vocabulary differs
  # ('inspect'|'add' rather than 'inspect'|'delete'). Same early-return reason: the branch
  # below returns before the node-query validation, so `ids` must never ride along here.
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -ceq 'add-entity-component'){$allowedFields=@('kind','runId','op','entityId','action','probeId','componentId')}
  # delete-instruction-graph family: REPLACED (never widened) list. Its adapter
  # (InstructionGraphDelete.cs) reads exactly two payload fields -- `ids` (one graph id) and
  # `entityId` (the edit-object id) -- and has NO `action` field: the read-only form is the
  # separate -dry-run op NAME. Same early-return reason as the lists above.
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -cin @('delete-instruction-graph','delete-instruction-graph-force','delete-instruction-graph-dry-run')){$allowedFields=@('kind','runId','op','ids','entityId')}
  # reflection-probe: REPLACED (never widened) list, exactly like the two component lists
  # above and for the same early-return reason -- `ids` must never ride along on it.
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -ceq 'reflection-probe'){$allowedFields=@('kind','runId','op','nameContains','memberContains')}
  if($props.ContainsKey('op') -and $props['op'] -is [string] -and $props['op'] -ceq 'author-entity-tag') {
    $allowedFields=@('kind','runId','op','tagAction','tagProbeId','tagEntityId')
    if($props.ContainsKey('tagAction') -and $props['tagAction'] -is [string] -and $props['tagAction'] -ceq 'set') {$allowedFields+=@('tagId','tagSelected','expectedTagsSha256')}
  }
  foreach ($name in @($props.Keys)) {
    if ($allowedFields -cnotcontains ([string]$name)) { throw ('CALL_FIELD_NOT_ALLOWED:' + [string]$name) }
  }

  # The three required fields must be real strings, not numbers, arrays or null.
  foreach ($name in @('kind', 'runId', 'op')) {
    if (-not $props.ContainsKey($name)) { throw 'CALL_REQUEST_INVALID' }
    if (-not ($props[$name] -is [string])) { throw 'CALL_REQUEST_INVALID' }
  }
  if ([string]$props['kind'] -cne 'call') { throw 'CALL_REQUEST_INVALID' }
  $runId = [string]$props['runId']
  $op    = [string]$props['op']

  # Unchanged from the branch this replaces: a well-formed GUID here, the run directory
  # checked later. The operation whitelist stays in the branch because it is read from
  # call-bridge.ps1 and so is not a pure function of the request.
  $parsedGuid = [Guid]::Empty
  if (-not [Guid]::TryParse($runId, [ref]$parsedGuid)) { throw 'BAD_RUN_ID' }

  $callArguments = @{ RunId = $runId; Operation = $op }
  if($props.ContainsKey('relativePath')) {
    $path=$props['relativePath']
    if($path -isnot [string] -or $path.Length -lt 5 -or $path.Length -gt 128 -or -not $path.EndsWith('.lua',[StringComparison]::Ordinal) -or $path.StartsWith('.') -or $path.Contains('..') -or $path -cnotmatch '^[A-Za-z0-9_.-]+$' -or $path.Split('.')[0] -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$'){throw 'SCRIPT_FILE_PROBE_PATH_INVALID'}
    $callArguments['ClientScriptRelativePath']=$path
  }

  if($op -ieq 'author-entity-tag' -and $op -cne 'author-entity-tag'){throw 'CALL_REQUEST_INVALID'}
  if($op -ieq 'reflection-probe' -and $op -cne 'reflection-probe'){throw 'CALL_REQUEST_INVALID'}
  if($op -ceq 'author-entity-tag') {
    if(-not $props.ContainsKey('tagAction') -or $props['tagAction'] -isnot [string] -or $props['tagAction'] -cnotin @('inspect','set')){throw 'ENTITY_TAG_ACTION_INVALID'}
    if(-not $props.ContainsKey('tagProbeId') -or $props['tagProbeId'] -isnot [string] -or $props['tagProbeId'] -cnotmatch '^[0-9a-f]{32}$'){throw 'ENTITY_TAG_PROBE_ID_INVALID'}
    $callArguments['TagAction']=$props['tagAction'];$callArguments['TagProbeId']=$props['tagProbeId']
    $idNames=@('tagEntityId');if($props['tagAction'] -ceq 'set'){$idNames+='tagId'}
    foreach($name in $idNames) {
      if(-not $props.ContainsKey($name) -or $null -eq $props[$name]){throw ('ENTITY_TAG_ID_INVALID:'+ $name)}
      $value=$props[$name];$type=$value.GetType()
      if($type -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw ('ENTITY_TAG_ID_INVALID:'+ $name)}
      $maximum=4294967295;if($name -ceq 'tagId'){$maximum=2147483647}
      if([decimal]$value -lt 1 -or [decimal]$value -gt $maximum){throw ('ENTITY_TAG_ID_INVALID:'+ $name)}
      if($name -ceq 'tagId'){$callArguments['TagId']=[uint32]$value}else{$callArguments['TagEntityId']=[uint32]$value}
    }
    if($props['tagAction'] -ceq 'set') {
      if(-not $props.ContainsKey('tagSelected') -or $props['tagSelected'] -isnot [bool]){throw 'ENTITY_TAG_SELECTED_INVALID'}
      if(-not $props.ContainsKey('expectedTagsSha256') -or $props['expectedTagsSha256'] -isnot [string] -or $props['expectedTagsSha256'] -cnotmatch '^[0-9a-f]{64}$'){throw 'ENTITY_TAG_BASELINE_HASH_INVALID'}
      $callArguments['TagSelected']=$props['tagSelected'];$callArguments['ExpectedTagsSha256']=$props['expectedTagsSha256']
    }
    return $callArguments
  }

  # entityId belongs only to the fixed inspect-entity-components call, matching the
  # allowlist narrowing above (which is why `ids` cannot reach this return). Optional
  # like relativePath: when absent the call still reaches call-bridge.ps1, whose
  # non-zero check refuses a missing -EntityId.
  if($op -ceq 'inspect-entity-components') {
    if($props.ContainsKey('entityId')) {
      if($null -eq $props['entityId']){throw 'ENTITY_COMPONENT_ID_INVALID'}
      $value=$props['entityId'];$type=$value.GetType()
      if($type -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'ENTITY_COMPONENT_ID_INVALID'}
      if([decimal]$value -lt 1 -or [decimal]$value -gt 4294967295){throw 'ENTITY_COMPONENT_ID_INVALID'}
      $callArguments['EntityId']=[uint32]$value
    }
    return $callArguments
  }

  # delete-entity-component carries four op-owned fields (entityId + action + probeId +
  # componentId). entityId/action/probeId are required for both actions; componentId is
  # required, and bounded to int32 (the backend's param_shape), only for the delete action.
  # The splat keys match call-bridge.ps1's parameters exactly.
  if($op -ceq 'delete-entity-component') {
    if(-not $props.ContainsKey('action') -or $props['action'] -isnot [string] -or $props['action'] -cnotin @('inspect','delete')){throw 'COMPONENT_ACTION_INVALID'}
    if(-not $props.ContainsKey('probeId') -or $props['probeId'] -isnot [string] -or $props['probeId'] -cnotmatch '^[0-9a-f]{32}$'){throw 'COMPONENT_PROBE_ID_INVALID'}
    if(-not $props.ContainsKey('entityId') -or $null -eq $props['entityId']){throw 'ENTITY_COMPONENT_ID_INVALID'}
    $eid=$props['entityId'];$eidType=$eid.GetType()
    if($eidType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'ENTITY_COMPONENT_ID_INVALID'}
    if([decimal]$eid -lt 1 -or [decimal]$eid -gt 4294967295){throw 'ENTITY_COMPONENT_ID_INVALID'}
    $callArguments['ComponentAction']=$props['action']
    $callArguments['ComponentProbeId']=$props['probeId']
    $callArguments['EntityId']=[uint32]$eid
    if($props['action'] -ceq 'delete') {
      if(-not $props.ContainsKey('componentId') -or $null -eq $props['componentId']){throw 'COMPONENT_ID_INVALID'}
      $cid=$props['componentId'];$cidType=$cid.GetType()
      if($cidType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'COMPONENT_ID_INVALID'}
      if([decimal]$cid -lt 1 -or [decimal]$cid -gt 2147483647){throw 'COMPONENT_ID_INVALID'}
      $callArguments['ComponentId']=[uint32]$cid
    }
    return $callArguments
  }

  # add-entity-component carries the SAME four op-owned fields as its delete sibling above
  # (entityId + action + probeId + componentId); only the action vocabulary differs
  # ('inspect'|'add' rather than 'inspect'|'delete'). entityId/action/probeId are required
  # for both actions; componentId is required, and bounded to int32 (the backend's
  # param_shape), only for the add action. The splat keys match call-bridge.ps1's parameters
  # exactly -- the two component ops share the same -ComponentAction/-ComponentProbeId/...
  # parameter set.
  if($op -ceq 'add-entity-component') {
    if(-not $props.ContainsKey('action') -or $props['action'] -isnot [string] -or $props['action'] -cnotin @('inspect','add')){throw 'COMPONENT_ACTION_INVALID'}
    if(-not $props.ContainsKey('probeId') -or $props['probeId'] -isnot [string] -or $props['probeId'] -cnotmatch '^[0-9a-f]{32}$'){throw 'COMPONENT_PROBE_ID_INVALID'}
    if(-not $props.ContainsKey('entityId') -or $null -eq $props['entityId']){throw 'ENTITY_COMPONENT_ID_INVALID'}
    $eid=$props['entityId'];$eidType=$eid.GetType()
    if($eidType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'ENTITY_COMPONENT_ID_INVALID'}
    if([decimal]$eid -lt 1 -or [decimal]$eid -gt 4294967295){throw 'ENTITY_COMPONENT_ID_INVALID'}
    $callArguments['ComponentAction']=$props['action']
    $callArguments['ComponentProbeId']=$props['probeId']
    $callArguments['EntityId']=[uint32]$eid
    if($props['action'] -ceq 'add') {
      if(-not $props.ContainsKey('componentId') -or $null -eq $props['componentId']){throw 'COMPONENT_ID_INVALID'}
      $cid=$props['componentId'];$cidType=$cid.GetType()
      if($cidType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'COMPONENT_ID_INVALID'}
      if([decimal]$cid -lt 1 -or [decimal]$cid -gt 2147483647){throw 'COMPONENT_ID_INVALID'}
      $callArguments['ComponentId']=[uint32]$cid
    }
    return $callArguments
  }

  # delete-instruction-graph family (InstructionGraphDelete.cs) carries exactly two
  # op-owned fields: `ids` (exactly ONE graph id) and `entityId` (the edit-object id,
  # REQUIRED because the native payload shape is unrecovered). Like the component branches
  # above this early-returns, so the node-query `ids` scope below never sees these ops and
  # an `ids` field on them is never silently ignored. The named refusals mirror the
  # adapter's own (INSTRUCTION_GRAPH_*), so the queue and the adapter agree.
  if($op -ceq 'delete-instruction-graph' -or $op -ceq 'delete-instruction-graph-force' -or $op -ceq 'delete-instruction-graph-dry-run') {
    if(-not $props.ContainsKey('ids') -or $null -eq $props['ids'] -or -not ($props['ids'] -is [Array])){throw 'INSTRUCTION_GRAPH_IDS_REQUIRED'}
    $array=[Array]$props['ids']
    if($array.Rank -ne 1){throw 'INSTRUCTION_GRAPH_IDS_REQUIRED'}
    if($array.Length -eq 0){throw 'INSTRUCTION_GRAPH_IDS_REQUIRED'}
    if($array.Length -ne 1){throw 'INSTRUCTION_GRAPH_SINGLE_ID_REQUIRED'}
    $element=$array.GetValue(0)
    if($null -eq $element){throw 'INSTRUCTION_GRAPH_ID_INVALID'}
    $elementType=$element.GetType()
    if($elementType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'INSTRUCTION_GRAPH_ID_INVALID'}
    $graphId=[decimal]$element
    if($graphId -lt 1 -or $graphId -gt 4294967295){throw 'INSTRUCTION_GRAPH_ID_INVALID'}
    if(-not $props.ContainsKey('entityId') -or $null -eq $props['entityId']){throw 'INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED'}
    $editObj=$props['entityId'];$editType=$editObj.GetType()
    if($editType -notin @([int],[long],[uint32],[uint64],[int16],[uint16],[byte],[sbyte])){throw 'INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED'}
    if([decimal]$editObj -lt 1 -or [decimal]$editObj -gt 4294967295){throw 'INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED'}
    $instructionGraphIds=New-Object 'System.UInt32[]' 1
    $instructionGraphIds[0]=[uint32]$graphId
    $callArguments['Ids']=$instructionGraphIds
    $callArguments['EntityId']=[uint32]$editObj
    return $callArguments
  }

  # reflection-probe carries its two name needles. nameContains is REQUIRED and
  # shape-checked here (a real 4..200 char string -- the same floor the adapter enforces,
  # so a wildcard-everything 1..3 char scan is refused before it is ever queued);
  # memberContains is optional and, like relativePath, OMITTED from the splat when empty,
  # so a caller that never passed it leaves every other call byte-for-byte unchanged.
  if($op -ceq 'reflection-probe')
  {
    if(-not $props.ContainsKey('nameContains') -or $props['nameContains'] -isnot [string] -or [string]::IsNullOrEmpty($props['nameContains'])){throw 'REFLECTION_NAME_CONTAINS_REQUIRED'}
    $name=$props['nameContains']
    if($name.Length -lt 4 -or $name.Length -gt 200){throw 'REFLECTION_NAME_CONTAINS_INVALID'}
    $callArguments['NameContains']=$name
    if($props.ContainsKey('memberContains') -and $null -ne $props['memberContains'])
    {
      $member=$props['memberContains']
      if($member -isnot [string] -or $member.Length -gt 200){throw 'REFLECTION_MEMBER_CONTAINS_INVALID'}
      if(-not [string]::IsNullOrEmpty($member)){$callArguments['MemberContains']=$member}
    }
    return $callArguments
  }


  # The two owned-delete ops take the SAME bounded shape as a node query (1..64 exact
  # integers), so they reuse this validation rather than getting a weaker one of their own.
  $nodeQueryOps = @('delete-owned-graph-ids-dry-run','delete-owned-graph-ids','delete-owned-entity-ids-dry-run','delete-owned-entity-ids','node-definitions','node-definition-variants')
  if ($nodeQueryOps -icontains $op -and -not ($nodeQueryOps -ccontains $op)) { throw 'CALL_REQUEST_INVALID' }
  if (-not ($nodeQueryOps -ccontains $op)) {
    # Spelled exactly: a differently-cased op is a different operation as far as ids
    # are concerned and gets none, as does every other op.
    if ($props.ContainsKey('ids')) { throw 'IDS_NOT_ALLOWED' }
    return $callArguments
  }

  if (-not $props.ContainsKey('ids')) { throw 'NODE_QUERY_IDS_REQUIRED' }
  $raw = $props['ids']
  if ($null -eq $raw) { throw 'NODE_QUERY_IDS_INVALID' }
  # A JSON array arrives as Object[]. A scalar, a string, true/false or an object all
  # fail this test, and a ragged or nested shape fails the rank test.
  if (-not ($raw -is [Array])) { throw 'NODE_QUERY_IDS_INVALID' }
  $array = [Array]$raw
  if ($array.Rank -ne 1) { throw 'NODE_QUERY_IDS_INVALID' }
  $count = $array.Length
  if ($count -lt 1 -or $count -gt 64) { throw 'NODE_QUERY_IDS_INVALID' }

  # Order is preserved and duplicates are allowed: this is a selection, not a set, and
  # the bridge answers in the order asked.
  $ids = New-Object 'System.UInt32[]' $count
  for ($i = 0; $i -lt $count; $i++) {
    $element = $array.GetValue($i)
    if ($null -eq $element) { throw 'NODE_QUERY_IDS_INVALID' }
    # Test the CLR type itself, before any coercion. A JSON 1.0 arrives as Double (or
    # Decimal) and true as Boolean; neither is an integer id, and a [uint32] cast here
    # would have silently accepted both.
    $type = $element.GetType()
    $isInteger = (
      $type -eq [int] -or $type -eq [long] -or $type -eq [uint32] -or $type -eq [uint64] -or
      $type -eq [int16] -or $type -eq [uint16] -or $type -eq [byte] -or $type -eq [sbyte]
    )
    if (-not $isInteger) { throw 'NODE_QUERY_IDS_INVALID' }
    # Every type accepted above fits in decimal, so this range test is exact and cannot
    # overflow. The widening is a comparison domain only: the value is not narrowed to
    # an integer type until it has been proven to be in range.
    $asDecimal = [decimal]$element
    if ($asDecimal -lt 1 -or $asDecimal -gt 4294967295) { throw 'NODE_QUERY_IDS_INVALID' }
    $ids[$i] = [uint32]$asDecimal
  }
  $callArguments['Ids'] = $ids
  return $callArguments
}

# Get-ValidatedNativeSceneRequest - pure request validator for native-scene calls.
#
# Takes an untrusted request envelope (PSCustomObject or IDictionary) plus the
# project root and returns a canonical hashtable of pure data. It writes nothing,
# reads no file contents, runs no script and touches no process, session, network
# or credential resource: existence, attributes and CLR types are all it inspects.
# Every failure throws a NATIVE_SCENE_* code. This file defines the function only.
function Get-ValidatedNativeSceneRequest {
  param([object]$Request, [string]$ProjectRoot)

  # Only a PSCustomObject or an IDictionary is a request. Keys are copied into an
  # ordinal (case-sensitive) table so "Action" cannot satisfy "action" and no later
  # lookup can be fooled by casing.
  function Get-NativePropertyBag {
    param([object]$Value, [string]$Code)
    if ($null -eq $Value) { throw $Code }
    $bag = [System.Collections.Hashtable]::new([System.StringComparer]::Ordinal)
    if ($Value -is [System.Collections.IDictionary]) {
      foreach ($key in @($Value.Keys)) { $bag[[string]$key] = $Value[$key] }
    } elseif ($Value -is [System.Management.Automation.PSCustomObject]) {
      foreach ($property in @($Value.PSObject.Properties)) { $bag[[string]$property.Name] = $property.Value }
    } else {
      throw $Code
    }
    return $bag
  }

  # Integer fields: CLR integral types only. Bool, float, decimal and string are
  # rejected by testing the CLR type before any coercion, so a JSON 1.0 or true is
  # never mistaken for an id. The range test is exact because every accepted type
  # fits in decimal; the value is not narrowed until it has been proven in range.
  function ConvertTo-NativeId {
    param([object]$Value, [string]$Name)
    if ($null -eq $Value) { throw ('NATIVE_SCENE_ID_INVALID:' + $Name) }
    $type = $Value.GetType()
    $isInteger = (
      $type -eq [int] -or $type -eq [long] -or $type -eq [uint32] -or $type -eq [uint64] -or
      $type -eq [int16] -or $type -eq [uint16] -or $type -eq [byte] -or $type -eq [sbyte]
    )
    if (-not $isInteger) { throw ('NATIVE_SCENE_ID_INVALID:' + $Name) }
    $asDecimal = [decimal]$Value
    if ($asDecimal -lt 1 -or $asDecimal -gt 4294967295) { throw ('NATIVE_SCENE_ID_INVALID:' + $Name) }
    return [uint32]$asDecimal
  }

  # Exactly three JSON numeric primitives: int/long/uint/float/double/decimal. A
  # string, bool, null or nested shape fails. Values are normalised through [single]
  # so anything float32 cannot represent (rounds to infinity) is refused, then
  # stored as [double]. The leading comma stops the typed array being unrolled.
  function ConvertTo-NativeVector {
    param([object]$Value, [string]$Name)
    if ($null -eq $Value -or -not ($Value -is [Array])) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
    $array = [Array]$Value
    if ($array.Rank -ne 1 -or $array.Length -ne 3) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
    $vector = [double[]]::new(3)
    for ($i = 0; $i -lt 3; $i++) {
      $element = $array.GetValue($i)
      if ($null -eq $element) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
      $type = $element.GetType()
      $isNumber = (
        $type -eq [int] -or $type -eq [long] -or $type -eq [uint32] -or
        $type -eq [single] -or $type -eq [double] -or $type -eq [decimal]
      )
      if (-not $isNumber) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
      $asDouble = [double]$element
      if ([double]::IsNaN($asDouble) -or [double]::IsInfinity($asDouble)) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
      $asSingle = [single]$asDouble
      if ([single]::IsNaN($asSingle) -or [single]::IsInfinity($asSingle)) { throw ('NATIVE_SCENE_VECTOR_INVALID:' + $Name) }
      $vector[$i] = [double]$asSingle
    }
    return ,$vector
  }

  # \\?\, \\.\ and \??\ name volumes and devices rather than ordinary files.
  function Test-NativeDeviceNamespace {
    param([string]$Path)
    return (
      $Path.StartsWith('\\?\', [StringComparison]::Ordinal) -or
      $Path.StartsWith('\\.\', [StringComparison]::Ordinal) -or
      $Path.StartsWith('\??\', [StringComparison]::Ordinal)
    )
  }

  # A path field must be a string naming an existing ordinary .json file inside
  # <ProjectRoot>/.runtime. Alias forms are rejected on the raw text, before any
  # normalisation could quietly accept them: device namespaces, alternate data
  # streams, and segments with a trailing space or dot (which also drops "." and
  # "..", so the boundary test only ever sees a normalised real path). Then the
  # fully resolved path is checked lexically against the runtime boundary, and the
  # file plus every ancestor up to the drive root is refused if it is a reparse
  # point, so a symlinked or junctioned file cannot alias its way inside.
  function Resolve-NativeJsonPath {
    param([object]$Value, [string]$Name, [string]$Root)
    if ($null -eq $Value -or -not ($Value -is [string])) { throw ('NATIVE_SCENE_PATH_INVALID:' + $Name) }
    $raw = [string]$Value
    if ($raw.Length -gt 2048 -or [string]::IsNullOrWhiteSpace($raw)) { throw ('NATIVE_SCENE_PATH_INVALID:' + $Name) }
    if (Test-NativeDeviceNamespace $raw) { throw ('NATIVE_SCENE_PATH_DEVICE:' + $Name) }
    $tail = $raw
    if ($raw -match '^[A-Za-z]:') { $tail = $raw.Substring(2) }
    if ($tail.Contains(':')) { throw ('NATIVE_SCENE_PATH_ADS:' + $Name) }
    foreach ($segment in $tail.Split([char[]]@('\', '/'))) {
      if ($segment.Length -eq 0) { continue }
      if ($segment -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw ('NATIVE_SCENE_PATH_DEVICE:' + $Name) }
      if ($segment.EndsWith(' ') -or $segment.EndsWith('.')) { throw ('NATIVE_SCENE_PATH_ALIAS:' + $Name) }
    }
    # Drive-letter with a separator, or a UNC share. "C:file.json" is drive-relative
    # and every relative form is refused here rather than resolved against the
    # process working directory.
    if (-not ($raw -match '^([A-Za-z]:[\\/]|\\\\)')) { throw ('NATIVE_SCENE_PATH_INVALID:' + $Name) }
    if (-not [string]::Equals([IO.Path]::GetExtension($raw), '.json', [StringComparison]::OrdinalIgnoreCase)) {
      throw ('NATIVE_SCENE_PATH_INVALID:' + $Name)
    }
    $full = $null
    try { $full = [IO.Path]::GetFullPath($raw) } catch { throw ('NATIVE_SCENE_PATH_INVALID:' + $Name) }
    $boundary = [IO.Path]::Combine($Root, '.runtime') + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
      throw ('NATIVE_SCENE_PATH_OUTSIDE:' + $Name)
    }
    if (-not [IO.File]::Exists($full)) {
      if ([IO.Directory]::Exists($full)) { throw ('NATIVE_SCENE_PATH_NOT_FILE:' + $Name) }
      throw ('NATIVE_SCENE_PATH_MISSING:' + $Name)
    }
    $current = $full
    while (-not [string]::IsNullOrEmpty($current)) {
      try { $attributes = [IO.File]::GetAttributes($current) } catch { throw ('NATIVE_SCENE_PATH_INVALID:' + $Name) }
      if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('NATIVE_SCENE_PATH_REPARSE:' + $Name) }
      $parent = [IO.Path]::GetDirectoryName($current)
      if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { break }
      $current = $parent
    }
    return $full
  }

  # Closed schema. The action selects exactly which fields exist, so hash, exe,
  # run, wrapper, plan and baseline paths are not merely unused but unrepresentable.
  $actionFields = @{
    'inspect'      = @('kind', 'action', 'sessionPath', 'levelId')
    'create'       = @('kind', 'action', 'sessionPath', 'levelId', 'reviewPath', 'templateId', 'position', 'rotation', 'scale')
    'save'         = @('kind', 'action', 'sessionPath', 'levelId', 'reviewPath')
    'reopen-current' = @('kind', 'action', 'sessionPath', 'levelId', 'reviewPath')
    'create-batch' = @('kind', 'action', 'sessionPath', 'levelId', 'reviewPath', 'placements')
    'creature-create' = @('kind', 'action', 'sessionPath', 'levelId', 'reviewPath', 'templateId', 'position', 'rotation', 'scale')
  }
  $placementFields = @('template_id', 'position', 'rotation', 'scale')
  # 2026-10-09: the template whitelist is REMOVED by user directive ($templateWhitelist and
  # $creatureTemplateWhitelist used to live here, mirrored in elevated-request.py and
  # build_scene_profile.py). A create accepts any uint32 templateId. Do not reintroduce one.  )


  $props = Get-NativePropertyBag -Value $Request -Code 'NATIVE_SCENE_REQUEST_INVALID'

  if (-not $props.ContainsKey('kind')) { throw 'NATIVE_SCENE_FIELD_MISSING:kind' }
  $kind = $props['kind']
  if (-not ($kind -is [string])) { throw 'NATIVE_SCENE_REQUEST_INVALID' }
  if ([string]$kind -cne 'native-scene') { throw 'NATIVE_SCENE_KIND_INVALID' }

  if (-not $props.ContainsKey('action')) { throw 'NATIVE_SCENE_FIELD_MISSING:action' }
  $action = $props['action']
  if (-not ($action -is [string])) { throw 'NATIVE_SCENE_ACTION_INVALID' }
  $action = [string]$action
  # Spelled exactly: a differently-cased action is a different operation and gets
  # no field map at all.
  if (-not ($action -cin @('inspect', 'create', 'save', 'create-batch', 'reopen-current', 'creature-create'))) { throw 'NATIVE_SCENE_ACTION_INVALID' }
  $allowedFields = [string[]]$actionFields[$action]
  $reopenPrerequisites = $props.ContainsKey('reopenPrerequisites')
  $largeScene = $props.ContainsKey('largeScene')
  if($largeScene){
    if($action -cne 'inspect' -or -not($props['largeScene'] -is [bool]) -or $props['largeScene'] -ne $true){throw 'LARGE_SCENE_INSPECT_TRUE_ONLY'}
    if($reopenPrerequisites){throw 'LARGE_SCENE_REOPEN_NOT_SUPPORTED'}
    $allowedFields += 'largeScene'
  }
  if($reopenPrerequisites){
    if($action -cne 'inspect' -or -not($props['reopenPrerequisites'] -is [bool]) -or $props['reopenPrerequisites'] -ne $true){throw 'REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY'}
    $allowedFields += 'reopenPrerequisites'
  }

  foreach ($name in @($props.Keys)) {
    if ($allowedFields -cnotcontains ([string]$name)) { throw ('NATIVE_SCENE_FIELD_NOT_ALLOWED:' + [string]$name) }
  }
  foreach ($name in $allowedFields) {
    if (-not $props.ContainsKey($name)) { throw ('NATIVE_SCENE_FIELD_MISSING:' + $name) }
  }

  if ([string]::IsNullOrWhiteSpace($ProjectRoot)) { throw 'NATIVE_SCENE_PROJECT_ROOT_INVALID' }
  $root = $null
  try { $root = [IO.Path]::GetFullPath($ProjectRoot) } catch { throw 'NATIVE_SCENE_PROJECT_ROOT_INVALID' }
  if (Test-NativeDeviceNamespace $root) { throw 'NATIVE_SCENE_PROJECT_ROOT_INVALID' }

  # Canonical keys only, fixed by the action map above. Every field is validated
  # before anything is returned, so a failure never escapes as partial data.
  $canonical = @{}
  $canonical['kind'] = [string]$kind
  $canonical['action'] = $action
  if($reopenPrerequisites){$canonical['reopenPrerequisites']=$true}
  if($largeScene){$canonical['largeScene']=$true}
  $canonical['levelId'] = ConvertTo-NativeId -Value $props['levelId'] -Name 'levelId'
  $canonical['sessionPath'] = Resolve-NativeJsonPath -Value $props['sessionPath'] -Name 'sessionPath' -Root $root

  if ($allowedFields -ccontains 'reviewPath') {
    $canonical['reviewPath'] = Resolve-NativeJsonPath -Value $props['reviewPath'] -Name 'reviewPath' -Root $root
  }

  if ($allowedFields -ccontains 'templateId') {
    $templateId = ConvertTo-NativeId -Value $props['templateId'] -Name 'templateId'
    # 2026-10-09: no membership test -- any uint32 templateId is accepted here.
    $canonical['templateId'] = $templateId
    $canonical['position'] = ConvertTo-NativeVector -Value $props['position'] -Name 'position'
    $canonical['rotation'] = ConvertTo-NativeVector -Value $props['rotation'] -Name 'rotation'
    $scale = ConvertTo-NativeVector -Value $props['scale'] -Name 'scale'
    foreach ($component in $scale) { if ($component -le 0) { throw 'NATIVE_SCENE_SCALE_INVALID' } }
    $canonical['scale'] = $scale
  }

  if ($allowedFields -ccontains 'placements') {
    $raw = $props['placements']
    if ($null -eq $raw -or -not ($raw -is [Array])) { throw 'NATIVE_SCENE_PLACEMENTS_INVALID' }
    $array = [Array]$raw
    if ($array.Rank -ne 1) { throw 'NATIVE_SCENE_PLACEMENTS_INVALID' }
    $count = $array.Length
    if ($count -lt 1 -or $count -gt 256) { throw 'NATIVE_SCENE_PLACEMENTS_INVALID' }
    # Order preserved and never unrolled: a typed slot array written by index.
    $placements = [object[]]::new($count)
    for ($i = 0; $i -lt $count; $i++) {
      $entry = Get-NativePropertyBag -Value $array.GetValue($i) -Code ('NATIVE_SCENE_PLACEMENT_INVALID:' + $i)
      foreach ($name in @($entry.Keys)) {
        if ($placementFields -cnotcontains ([string]$name)) {
          throw ('NATIVE_SCENE_PLACEMENT_FIELD_NOT_ALLOWED:' + $i + ':' + [string]$name)
        }
      }
      foreach ($name in $placementFields) {
        if (-not $entry.ContainsKey($name)) { throw ('NATIVE_SCENE_PLACEMENT_FIELD_MISSING:' + $i + ':' + $name) }
      }
      $placement = @{}
      $id = ConvertTo-NativeId -Value $entry['template_id'] -Name ('placements[' + $i + '].template_id')
      $placement['template_id'] = $id
      $placement['position'] = ConvertTo-NativeVector -Value $entry['position'] -Name ('placements[' + $i + '].position')
      $placement['rotation'] = ConvertTo-NativeVector -Value $entry['rotation'] -Name ('placements[' + $i + '].rotation')
      $placementScale = ConvertTo-NativeVector -Value $entry['scale'] -Name ('placements[' + $i + '].scale')
      foreach ($component in $placementScale) { if ($component -le 0) { throw 'NATIVE_SCENE_SCALE_INVALID' } }
      $placement['scale'] = $placementScale
      $placements[$i] = $placement
    }
    $canonical['placements'] = $placements
  }

  return $canonical
}

# Fixed-entry dispatch functions. No request field selects an executable or script.
function Assert-DispatchOrdinaryPath([string]$Path) {
  $current=[IO.Path]::GetFullPath($Path)
  while(-not [string]::IsNullOrEmpty($current)) {
    if(([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint)-ne 0){throw 'DISPATCH_REPARSE_PATH'}
    $parent=[IO.Path]::GetDirectoryName($current)
    if($parent -eq $current){break}; $current=$parent
  }
}
function Get-DispatchPinFiles([string]$Root,[string]$Python) {
  $paths=[Collections.Generic.List[string]]::new()
  foreach($name in @('tools/editor-bridge/elevated-runner.ps1','tools/editor-bridge/reopen-lifecycle.ps1','tools/editor-bridge/elevated-request.py','tools/authoring/graph-elevated-once.ps1','tools/authoring/graph-transport.ps1','tools/editor-bridge/compatibility-guard.ps1')) {
    $paths.Add([IO.Path]::GetFullPath((Join-Path $Root $name)))
  }
  foreach($name in @('scene_cli.py','build_reopen_profile.py','reopen_dispatch.py','native_reopen_acceptance.py','native_reopen_result.py','native_reopen_baseline.py','build_scene_profile.py','build_readonly_profile.py','native_profiles.py','native_write_review.py','native_level_observation.py','native_level_catalog.py','native_lifecycle_type.py','native_scheduler_coroutines.py','native_reopen_guards.py','decode_context_snapshot.py','discover_current_level.py','check_reopen_prerequisites.py','prepare_reopen_review.py','cleanup_owned_entities.py')) {$paths.Add((Join-Path $Root ('tools/game-executor/'+$name)))}
  foreach($name in @('game_context_snapshot.cpp','game_context_snapshot.h','game_level_catalog.cpp','game_level_catalog.h','game_lifecycle_type.cpp','game_lifecycle_type.h','game_scheduler_coroutines.cpp','game_scheduler_coroutines.h','game_reopen_guards.h','game_reopen_guards.cpp','game_reopen_guards_capture.cpp','guard_profile.generated.h','hook_receipt.cpp','hook_receipt_probe.cpp','hook_receipt_protocol.h','game_scene_action.cpp','game_scene_action.h','scene_calls.cpp','scene_calls.h')) {$paths.Add((Join-Path $Root ('tools/game-executor/native/'+$name)))}
  foreach($file in Get-ChildItem -LiteralPath (Join-Path $Root 'tools/game-executor/native') -File){if($file.Extension -cin @('.cpp','.h','.inc') -and -not $paths.Contains($file.FullName)){$paths.Add($file.FullName)}}
  # Map cards execute through fixed source entries. Pin the complete small source
  # trees too; adding/changing an imported module requires a fresh helper session.
  foreach($file in Get-ChildItem -LiteralPath (Join-Path $Root 'tools/game-executor') -Filter 'asset_inspection*' -File){
    if($file.Extension -cin @('.py','.json','.ps1','.cpp','.h','.inc')){$paths.Add($file.FullName)}
  }
  $mapPending=[Collections.Generic.Queue[string]]::new()
  foreach($name in @('tools/entity-transform','tools/entity-material','tools/map-terrain','tools/terrain-water','tools/template-properties','tools/playtest-control','tools/graph-vector-values','tools/beyond-save','tools/editor-bridge/native-card','tools/game-executor/native-options','tools/game-executor/template-authoring','tools/mondstadt/life/dropstuff','tools/mondstadt/combat/native')){$mapPending.Enqueue((Join-Path $Root $name))}
  while($mapPending.Count){
    $base=$mapPending.Dequeue();Assert-DispatchOrdinaryPath $base
    foreach($item in Get-ChildItem -LiteralPath $base){
      if($item.PSIsContainer){if($item.Name -notin @('__pycache__','.runtime')){$mapPending.Enqueue($item.FullName)}}
      elseif($item.Extension -in @('.py','.cpp','.h','.inc','.json','.ps1')){$paths.Add($item.FullName)}
    }
  }
  foreach($name in @('genshin-cn-7.1.0-level-observation.json','genshin-cn-7.1.0-native-level-catalog.json','genshin-cn-7.1.0-native-lifecycle-type.json','genshin-cn-7.1.0-scheduler-coroutines.json','genshin-cn-7.1.0-reopen-guards.json','genshin-cn-7.1.0-readonly.json','genshin-cn-7.1.0-reviewed-write.json')) {$paths.Add((Join-Path $Root ('tools/game-executor/profiles/'+$name)))}
  $paths.Add($fixedPowerShell)
  $paths.Add($Python)
  $pythonHome=[IO.Path]::GetDirectoryName($Python)
  foreach($file in Get-ChildItem -LiteralPath $pythonHome -File) {
    if($file.Extension -in @('.dll','.zip')){$paths.Add($file.FullName)}
  }
  # Runtime source and binaries are stable inputs; caches and third-party packages
  # are outside the isolated (-I -S -B) execution chain and are never enumerated.
  $pending=[Collections.Generic.Queue[string]]::new()
  foreach($directory in @('DLLs','Lib')) {$pending.Enqueue((Join-Path $pythonHome $directory))}
  while($pending.Count) {
    $base=$pending.Dequeue()
    Assert-DispatchOrdinaryPath $base
    foreach($item in Get-ChildItem -LiteralPath $base) {
      if($item.PSIsContainer) {
        if($item.Name -notin @('site-packages','__pycache__')){$pending.Enqueue($item.FullName)}
      } elseif($item.Extension -in @('.py','.pyd','.dll')) {$paths.Add($item.FullName)}
    }
  }
  foreach($path in Get-ReopenAcceptancePinFiles $Root $Python){$paths.Add($path)}
  return @($paths.ToArray() | Sort-Object -Unique)
}
function Get-StreamSha256([IO.Stream]$Stream) {
  $sha=[Security.Cryptography.SHA256]::Create()
  try {$Stream.Position=0; return ([BitConverter]::ToString($sha.ComputeHash($Stream))).Replace('-','').ToLowerInvariant()}
  finally{$sha.Dispose()}
}
function New-DispatchPins([string]$Root,[string]$Python) {
  $pins=@{}
  foreach($path in Get-DispatchPinFiles $Root $Python) {
    Assert-DispatchOrdinaryPath $path
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {$pins[$path]=Get-StreamSha256 $stream} finally{$stream.Dispose()}
  }
  return $pins
}
function Lock-DispatchPins([string]$Root,[string]$Python,[hashtable]$Pins) {
  $held=[Collections.Generic.List[IDisposable]]::new()
  try {
    $files=@(Get-DispatchPinFiles $Root $Python)
    if($files.Count -ne $Pins.Count){throw 'DISPATCH_SOURCE_SET_CHANGED'}
    foreach($path in $files) {
      if(-not $Pins.ContainsKey($path)){throw 'DISPATCH_SOURCE_SET_CHANGED'}
      Assert-DispatchOrdinaryPath $path
      $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
      $held.Add($stream)
      if((Get-StreamSha256 $stream) -cne $Pins[$path]){throw ('DISPATCH_PIN_CHANGED:'+ $path)}
    }
    return ,$held
  } catch {foreach($stream in $held){$stream.Dispose()};throw}
}
function Write-ExclusiveDispatchJson([string]$Path,$Value) {
  $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false))
  try{$writer.Write(($Value|ConvertTo-Json -Depth 12 -Compress))}finally{$writer.Dispose()}
}
function Get-AuthorGraphDispatch([object]$Request,[string]$Root) {
  $props=@($Request.PSObject.Properties.Name)
  if($Request -is [Collections.IDictionary]){$props=@($Request.Keys)}
  if($props.Count -ne 3 -or @($props|Where-Object {$_ -cnotin @('kind','runId','requestId')}).Count){throw 'AUTHOR_GRAPH_FIELDS_INVALID'}
  foreach($key in @('kind','runId','requestId')){if(-not($Request.$key -is [string])){throw 'AUTHOR_GRAPH_FIELDS_INVALID'}}
  if($Request.kind -cne 'author-graph'){throw 'AUTHOR_GRAPH_KIND_INVALID'}
  $guid=[Guid]::Empty
  if(-not[Guid]::TryParseExact($Request.runId,'D',[ref]$guid) -or $guid.ToString('D') -cne $Request.runId){throw 'AUTHOR_GRAPH_RUN_ID_INVALID'}
  if($Request.requestId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'){throw 'AUTHOR_GRAPH_REQUEST_ID_INVALID'}
  $journal=Join-Path $Root ('.runtime/authoring/requests/'+$Request.requestId)
  Assert-DispatchOrdinaryPath $journal
  foreach($name in @('claim.json','bridge-request.json')){Assert-DispatchOrdinaryPath (Join-Path $journal $name)}
  foreach($name in @('elevated-attempt.used','elevated-response.json')){if(Test-Path -LiteralPath (Join-Path $journal $name)){throw 'AUTHOR_GRAPH_ALREADY_ATTEMPTED'}}
  return @{RunId=$guid.ToString('D');RequestId=$Request.requestId;Journal=$journal;Script=(Join-Path $Root 'tools/authoring/graph-elevated-once.ps1')}
}
function Get-NativeSceneArguments([hashtable]$Data,[string]$Root,[string]$PlanPath='',[string]$RequestId='',[string]$LeaseSha256='') {
  $arguments=[Collections.Generic.List[string]]::new()
  foreach($value in @('-B','-I','-S',(Join-Path $Root 'tools/game-executor/scene_cli.py'),$Data.action,'--direct-elevated','--session',$Data.sessionPath,'--level-id',([string]$Data.levelId))){$arguments.Add([string]$value)}
  if($Data.ContainsKey('reopenPrerequisites')){
    if($Data.action -cne 'inspect' -or -not($Data.reopenPrerequisites -is [bool]) -or $Data.reopenPrerequisites -ne $true){throw 'REOPEN_PREREQUISITES_INSPECT_TRUE_ONLY'}
    $arguments.Add('--reopen-prerequisites')
  }
  if($Data.ContainsKey('largeScene')){
    if($Data.action -cne 'inspect' -or -not($Data.largeScene -is [bool]) -or $Data.largeScene -ne $true){throw 'LARGE_SCENE_INSPECT_TRUE_ONLY'}
    $arguments.Add('--large-scene')
  }
  if($Data.action -ne 'inspect'){$arguments.Add('--review');$arguments.Add($Data.reviewPath)}
  if($Data.action -eq 'create' -or $Data.action -eq 'creature-create') {
    $arguments.Add('--template-id');$arguments.Add([string]$Data.templateId)
    foreach($key in @('position','rotation','scale')) {
      $arguments.Add('--'+$key)
      foreach($value in $Data[$key]){$arguments.Add(([double]$value).ToString('R',[Globalization.CultureInfo]::InvariantCulture))}
    }
  }
  if($Data.action -eq 'create-batch') {
    if([string]::IsNullOrEmpty($PlanPath)){throw 'NATIVE_SCENE_PLAN_PATH_INTERNAL_MISSING'}
    $arguments.Add('--plan');$arguments.Add($PlanPath)
  }
  if($Data.action -ceq 'reopen-current'){Assert-ReopenId $RequestId;Assert-ReopenHash $LeaseSha256;foreach($v in @('--reopen-request-id',$RequestId,'--reopen-lease-sha256',$LeaseSha256)){$arguments.Add($v)}}
  return ,$arguments.ToArray()
}
function Test-NativeTerminalSafe($Reply,[string]$Action='') {
  if($Action -ceq 'reopen-current' -or (Get-JsonField $Reply 'action' '') -ceq 'reopen-current'){return $false}
  if($null -eq $Reply){return $false}
  $uncertain=Get-JsonField $Reply 'outcomeUncertain' $null
  if($null -ne $uncertain -and (-not($uncertain -is [bool]) -or $uncertain)){return $false}
  $cleanup=Get-JsonField $Reply 'cleanupVerified' $null
  $safe=Get-JsonField $Reply 'safeToRelease' $null
  return (($cleanup -is [bool] -and $cleanup) -or ($safe -is [bool] -and $safe))
}
function Get-NativeMapDispatch([object]$Request,[string]$Root) {
  if($null -eq $Request){throw 'NATIVE_MAP_REQUEST_INVALID'}
  $keys=@(if($Request -is [Collections.IDictionary]){$Request.Keys}elseif($Request -is [Management.Automation.PSCustomObject]){$Request.PSObject.Properties.Name}else{throw 'NATIVE_MAP_REQUEST_INVALID'})
  if($keys.Count -ne 4 -or @($keys|Where-Object {$_ -cnotin @('kind','tool','runPath','preparedSha256')}).Count){throw 'NATIVE_MAP_FIELDS_INVALID'}
  foreach($key in @('kind','tool','runPath','preparedSha256')){if(-not($Request.$key -is [string])){throw 'NATIVE_MAP_FIELDS_INVALID'}}
  if($Request.preparedSha256 -cnotmatch '^[0-9a-f]{64}$'){throw 'NATIVE_MAP_PREPARED_HASH_INVALID'}
  if($Request.kind -cne 'native-map' -or $Request.tool -cnotin @('entity-transform','terrain','playtest-control','asset-inspection','template-item','template-currency','generalized-tabs','mondstadt-dropstuff','mondstadt-combat','entity-material','terrain-water','template-properties','role-template-bag')){throw 'NATIVE_MAP_TOOL_INVALID'}
  $raw=$Request.runPath
  if([string]::IsNullOrWhiteSpace($raw) -or $raw.Length -gt 2048 -or $raw -notmatch '^[A-Za-z]:[\\/]'){throw 'NATIVE_MAP_RUN_INVALID'}
  $tail=$raw.Substring(2)
  if($tail.Contains(':')){throw 'NATIVE_MAP_RUN_ALIAS'}
  foreach($part in $tail.Split([char[]]@('\','/'))){
    if($part.EndsWith(' ') -or $part.EndsWith('.') -or $part -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)'){throw 'NATIVE_MAP_RUN_ALIAS'}
  }
  $run=[IO.Path]::GetFullPath($raw)
  $boundary=[IO.Path]::GetFullPath((Join-Path $Root '.runtime')).TrimEnd('\')+'\'
  if(-not $run.StartsWith($boundary,[StringComparison]::OrdinalIgnoreCase) -or -not [IO.Directory]::Exists($run)){throw 'NATIVE_MAP_RUN_OUTSIDE_RUNTIME'}
  Assert-DispatchOrdinaryPath $run
  $manifest=Join-Path $run 'prepared.json'
  if(-not [IO.File]::Exists($manifest)){throw 'NATIVE_MAP_PREPARED_MISSING'}
  Assert-DispatchOrdinaryPath $manifest
  if($Request.tool -ceq 'terrain'){$script=Join-Path $Root 'tools/map-terrain/terrain_cli.py';$action='execute';$preparedRoot='.runtime/map-foundation-20261015/terrain/prepared'}
  elseif($Request.tool -ceq 'entity-transform'){$script=Join-Path $Root 'tools/entity-transform/cli.py';$action='dispatch';$preparedRoot='.runtime/map-foundation-20261015/transform/prepared'}
  elseif($Request.tool -ceq 'entity-material'){$script=Join-Path $Root 'tools/entity-material/cli.py';$action='dispatch';$preparedRoot='.runtime/entity-material-20261017/prepared'}
  elseif($Request.tool -ceq 'terrain-water'){$script=Join-Path $Root 'tools/terrain-water/cli.py';$action='execute';$preparedRoot='.runtime/terrain-water-20261017/prepared'}
  elseif($Request.tool -ceq 'template-properties'){$script=Join-Path $Root 'tools/template-properties/v2/cli.py';$action='dispatch';$preparedRoot='.runtime/template-properties-20261017/v2-prepared'}
  elseif($Request.tool -ceq 'asset-inspection'){$script=Join-Path $Root 'tools/game-executor/asset_inspection.py';$action='dispatch';$preparedRoot='.runtime/asset-inspection-20261017/prepared'}
  elseif($Request.tool -cin @('template-item','template-currency','generalized-tabs','mondstadt-dropstuff','mondstadt-combat','role-template-bag')){$script=Join-Path $Root 'tools/editor-bridge/native-card/dispatch.py';$action=$Request.tool;$preparedRoot='.runtime/native-card-20261017/prepared/'+$Request.tool}
  else{$script=Join-Path $Root 'tools/playtest-control/cli.py';$action='dispatch';$preparedRoot='.runtime/playtest-control-20261016/prepared'}
  $toolBoundary=[IO.Path]::GetFullPath((Join-Path $Root $preparedRoot)).TrimEnd('\')+'\'
  if(-not $run.StartsWith($toolBoundary,[StringComparison]::OrdinalIgnoreCase)){throw 'NATIVE_MAP_RUN_WRONG_TOOL_ROOT'}
  Assert-DispatchOrdinaryPath $script
  if((Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Request.preparedSha256){throw 'NATIVE_MAP_PREPARED_CHANGED'}
  return @{Tool=$Request.tool;Run=$run;Script=$script;Action=$action;Prepared=$manifest;PreparedSha256=$Request.preparedSha256}
}
function Invoke-FixedNativeMap([object]$Request,[string]$RequestId) {
  if($RequestId -cnotmatch '^[0-9a-f]{32}$'){throw 'NATIVE_MAP_QUEUE_ID_INVALID'}
  $route=Get-NativeMapDispatch $Request $projectRoot
  if(Test-Path -LiteralPath $nativeActivePath){throw 'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED'}
  $held=Lock-DispatchPins $projectRoot $nativePython $dispatchPins
  try{
    $card=[IO.File]::Open($route.Prepared,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $held.Add($card)
    if((Get-StreamSha256 $card) -cne $route.PreparedSha256){throw 'NATIVE_MAP_PREPARED_CHANGED'}
    $work=Join-Path $nativeDispatchRoot $RequestId
    if(Test-Path -LiteralPath $work){throw 'NATIVE_MAP_ALREADY_ATTEMPTED'}
    New-Item -ItemType Directory -Path $work | Out-Null
    Assert-DispatchOrdinaryPath $work
    Write-ExclusiveDispatchJson $nativeActivePath @{requestId=$RequestId;pid=$PID;startedUtc=[DateTime]::UtcNow.ToString('o');action='native-map';tool=$route.Tool;runPath=$route.Run}
    $arguments=@('-B','-I','-S',$route.Script,$route.Action,'--run',$route.Run,'--direct-elevated')
    $errorFile=Join-Path $work 'stderr.txt'
    $previousOutputEncoding=[Console]::OutputEncoding
    try{[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$text=& $nativePython @arguments 2> $errorFile;$exitCode=$LASTEXITCODE}
    finally{[Console]::OutputEncoding=$previousOutputEncoding}
    $raw=$text -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $work 'stdout.json'),$raw,$utf8NoBom)
    try{$reply=$raw|ConvertFrom-Json}catch{throw 'NATIVE_MAP_REPLY_INVALID'}
    if(-not($reply -is [Management.Automation.PSCustomObject])){throw 'NATIVE_MAP_REPLY_INVALID'}
    $ok=Get-JsonField $reply 'ok' $null
    if(-not($ok -is [bool]) -or ($exitCode -ne 0 -and $ok)){throw 'NATIVE_MAP_REPLY_INVALID'}
    $terminal=Test-NativeTerminalSafe $reply
    if($ok -and -not $terminal){throw 'NATIVE_MAP_CLEANUP_EVIDENCE_MISSING'}
    if($terminal){Remove-Item -LiteralPath $nativeActivePath -Force}
    $reply|Add-Member -NotePropertyName helper -NotePropertyValue @{kind='native-map';schema=1;pid=$PID;requestId=$RequestId;tool=$route.Tool} -Force
    return $reply
  }finally{foreach($stream in $held){$stream.Dispose()}}
}
function Invoke-FixedNativeScene([object]$Request,[string]$RequestId) {
  if($RequestId -cnotmatch '^[0-9a-f]{32}$'){throw 'NATIVE_SCENE_QUEUE_ID_INVALID'}
  $data=Get-ValidatedNativeSceneRequest $Request $projectRoot
  $pendingRead=$false;$parentId='';$reopenState=$null
  if(Test-Path -LiteralPath $nativeActivePath){
    if($data.action -cne 'inspect' -or -not(Test-ReopenPendingRequest $nativeDispatchRoot $Request)){throw 'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED'}
    $pendingRead=$true;$parentId=(Get-ReopenActive $nativeDispatchRoot).value.requestId
  }
  $held=Lock-DispatchPins $projectRoot $nativePython $dispatchPins
  try {
    # Shared across helper lifetimes; never auto-clear an uncertain previous attempt.
    $work=Join-Path $nativeDispatchRoot $RequestId
    if(Test-Path -LiteralPath $work){throw 'NATIVE_SCENE_ALREADY_ATTEMPTED'}
    New-Item -ItemType Directory -Path $work | Out-Null
    Assert-DispatchOrdinaryPath $work
    if($pendingRead){New-ReopenInspectionClaim $nativeDispatchRoot $parentId $RequestId}
    elseif($data.action -ceq 'reopen-current'){
      $review=Get-ReopenArtifact $data.reviewPath
      $policy=$review.value.reopenLifecycle
      Assert-ReopenExact $policy @('bridgeRunId','accountBaselineSha256','acceptanceVerifierSha256')
      $binding=@{sessionPath=$data.sessionPath;sessionSha256=(Get-ReopenArtifact $data.sessionPath).sha256;bridgeRunId=$policy.bridgeRunId;reviewSha256=$review.sha256;accountBaselineSha256=$policy.accountBaselineSha256;acceptanceVerifierSha256=$policy.acceptanceVerifierSha256;pinsDigest=$dispatchPinsDigest}
      $reopenState=New-ReopenPending $nativeDispatchRoot $RequestId $binding
    }else{Write-ExclusiveDispatchJson $nativeActivePath @{requestId=$RequestId;pid=$PID;startedUtc=[DateTime]::UtcNow.ToString('o');action=$data.action}}
    $plan=''
    if($data.action -eq 'create-batch') {
      $plan=Join-Path $work 'placements.json'
      Write-ExclusiveDispatchJson $plan @{placements=$data.placements}
    }
    $leaseHash=if($null -ne $reopenState){$reopenState.leaseSha256}else{''}
    $arguments=Get-NativeSceneArguments $data $projectRoot $plan $RequestId $leaseHash
    $errorFile=Join-Path $work 'stderr.txt'
    # Synchronous fixed Python inherits this helper's existing token; no RunAs.
    $previousOutputEncoding=[Console]::OutputEncoding
    try {
      [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
      $text=& $nativePython @arguments 2> $errorFile
      $exitCode=$LASTEXITCODE
    } finally {
      [Console]::OutputEncoding=$previousOutputEncoding
    }
    $raw=$text -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $work 'stdout.json'),$raw,$utf8NoBom)
    try {$reply=$raw|ConvertFrom-Json} catch {throw 'NATIVE_SCENE_REPLY_INVALID'}
    if(-not($reply -is [Management.Automation.PSCustomObject])){throw 'NATIVE_SCENE_REPLY_INVALID'}
    $ok=Get-JsonField $reply 'ok' $null
    if(-not($ok -is [bool])){throw 'NATIVE_SCENE_REPLY_INVALID'}
    if($exitCode -ne 0 -and $ok){throw 'NATIVE_SCENE_EXIT_REPLY_MISMATCH'}
    if($data.action -ceq 'reopen-current'){
      if($reply.requestId -cne $RequestId){throw 'REOPEN_REPLY_ID_MISMATCH'}
      $receiptPath=[IO.Path]::GetFullPath([string]$reply.receipt)
      if(-not$receiptPath.StartsWith((Join-Path $projectRoot '.runtime')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'REOPEN_RECEIPT_OUTSIDE_RUNTIME'}
      $rawReceipt=Get-ReopenArtifact $receiptPath 1048576
      if($reply.nativeReceiptSha256 -cne $rawReceipt.sha256){throw 'REOPEN_RECEIPT_HASH_MISMATCH'}
      $dispatch=[ordered]@{schema=1;requestId=$RequestId;leaseSha256=$reopenState.leaseSha256;nativeReceiptSha256=$rawReceipt.sha256}
      foreach($key in @('preflightPassed','nativeCallAttempted','nativeCallReturned','callExceptionCode','hookCleanupVerified','status','businessPending','businessVerified','reopenVerified','retryAttempted')){$dispatch[$key]=$reply.$key}
      Save-ReopenDispatch $nativeDispatchRoot $RequestId $dispatch|Out-Null
      # Never invoke legacy release for reopen, even if the child has cleanupVerified=true.
    }else{
      $terminal=Test-NativeTerminalSafe $reply $data.action
      if($ok -and -not$terminal){throw 'NATIVE_SCENE_CLEANUP_EVIDENCE_MISSING'}
      if($pendingRead){
        $null=Complete-ReopenInspectionClaim $nativeDispatchRoot $parentId $RequestId $terminal
        $reply|Add-Member -NotePropertyName observedDuringReopenRequestId -NotePropertyValue $parentId -Force
      }elseif($terminal){Remove-Item -LiteralPath $nativeActivePath -Force}
    }
    $reply|Add-Member -NotePropertyName helper -NotePropertyValue @{kind='native-scene';schema=1;pid=$PID;startedUtc=$startedUtc.ToString('o');requestId=$RequestId} -Force
    return $reply
  } finally {foreach($stream in $held){$stream.Dispose()}}
}
function Invoke-FixedAuthorGraph([object]$Request) {
  if(Test-Path -LiteralPath $nativeActivePath){throw 'NATIVE_SCENE_PREVIOUS_OUTCOME_UNRESOLVED'}
  $route=Get-AuthorGraphDispatch $Request $projectRoot
  $held=Lock-DispatchPins $projectRoot $nativePython $dispatchPins
  try {
    & $fixedPowerShell -NoProfile -File $route.Script -RunId $route.RunId -RequestId $route.RequestId | Out-Null
    $exitCode=$LASTEXITCODE
    $response=Join-Path $route.Journal 'elevated-response.json'
    Assert-DispatchOrdinaryPath $response
    $reply=[IO.File]::ReadAllText($response,$utf8NoBom)|ConvertFrom-Json
    if(-not($reply -is [Management.Automation.PSCustomObject])){throw 'AUTHOR_GRAPH_REPLY_INVALID'}
    $ok=Get-JsonField $reply 'ok' $null
    if(-not($ok -is [bool])){throw 'AUTHOR_GRAPH_REPLY_INVALID'}
    if($exitCode -ne 0 -and $ok){throw 'AUTHOR_GRAPH_EXIT_REPLY_MISMATCH'}
    return $reply
  } finally {foreach($stream in $held){$stream.Dispose()}}
}

# Native and graph capabilities are fixed at helper startup, not supplied by requests.
$nativePython=$env:MILIASTRA_PYTHON
if([string]::IsNullOrWhiteSpace($nativePython) -or -not [IO.File]::Exists($nativePython)){throw 'CONFIGURE_MILIASTRA_PYTHON_REQUIRED'}
$fixedPowerShell=(Get-Process -Id $PID).Path
$nativePolicy=(Get-ExecutionPolicy).ToString()
if($nativePolicy -notin @('RemoteSigned','Unrestricted')){throw ('NATIVE_HOST_POLICY_REFUSED:'+$nativePolicy)}
$env:MILIASTRA_POWERSHELL_HOST=$fixedPowerShell
$queueBoundary=[IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime/editor-bridge')).TrimEnd('\')+'\'
$QueueDir=[IO.Path]::GetFullPath($QueueDir)
if(-not $QueueDir.StartsWith($queueBoundary,[StringComparison]::OrdinalIgnoreCase)){throw 'QUEUE_OUTSIDE_PROJECT_EDITOR_BRIDGE'}
Assert-DispatchOrdinaryPath $QueueDir
$nativeDispatchRoot=Join-Path $projectRoot '.runtime/editor-bridge/native-dispatch'
New-Item -ItemType Directory -Path $nativeDispatchRoot -Force | Out-Null
Assert-DispatchOrdinaryPath $nativeDispatchRoot
$nativeActivePath=Join-Path $nativeDispatchRoot 'native-active.json'
$dispatchPins=New-DispatchPins $projectRoot $nativePython
$pinText=(@($dispatchPins.Keys|Sort-Object|ForEach-Object {$_+'|'+$dispatchPins[$_]}) -join "`n")
$pinStream=[IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($pinText))
try{$dispatchPinsDigest=Get-StreamSha256 $pinStream}finally{$pinStream.Dispose()}
$nativeCapability=@{powershellHost=@{path=$fixedPowerShell;version=$PSVersionTable.PSVersion.ToString();policy=$nativePolicy;sha256=(Get-FileHash -LiteralPath $fixedPowerShell -Algorithm SHA256).Hash.ToLowerInvariant();policyOverride=$false;fallbackAttempted=$false};schema=1;enabled=$true;actions=@('inspect','create','save','create-batch','reopen-current','creature-create');projectRoot=$projectRoot;pinsDigest=$dispatchPinsDigest;python=$nativePython;pinCount=$dispatchPins.Count;blocked=(Test-Path -LiteralPath $nativeActivePath)}

# Startup succeeded; clear any stale failure record from an earlier attempt so the
# launcher never reports a problem that has since been fixed.
Remove-Item -LiteralPath (Join-Path $QueueDir 'runner.startup-error.txt') -Force -ErrorAction SilentlyContinue

Write-Log ("runner started; pid={0}; user={1}; elevated={2}; ops={3}; fsOps={4}; fsRoots={5}; lifetime={6}min" -f `
  $PID, $identity.Name, $isAdmin, $allowedOps.Count, $fsOps.Count, $fsRoots.Count, $LifetimeMinutes)
foreach ($r in $fsRoots) {
  Write-Log ("  root {0} read={1} write={2} path={3}" -f $r.name, $r.read, $r.write, $r.path)
}

$handled = 0
while ([DateTime]::UtcNow -lt $deadline) {
  if (Test-Path -LiteralPath $stopPath) { Write-Log 'STOP file seen; exiting'; break }

  [IO.File]::WriteAllText($heartbeatPath, ([DateTime]::UtcNow.ToString('o') + " pid=$PID handled=$handled"), $utf8NoBom)

  $requests = @(Get-ChildItem -LiteralPath $QueueDir -Filter '*.request.json' -ErrorAction SilentlyContinue | Sort-Object Name)
  foreach ($req in $requests) {
    if ([DateTime]::UtcNow -ge $deadline) { break }
    $base = $req.FullName -replace '\.request\.json$', ''
    $id   = [IO.Path]::GetFileName($base)
    $responsePath = "$base.response.json"
    $errorPath    = "$base.error.txt"
    try {
      $body = Read-JsonFile $req.FullName
      # Before dispatch, so ids on status/load/fs cannot reach their operations at
      # all -- those branches never see a body that carries one.
      Assert-RequestIdsScope -Request $body
      $kind = [string](Get-JsonField $body 'kind' '')
      if(-not(Test-ReopenPendingRequest $nativeDispatchRoot $body)){throw 'REOPEN_PENDING_WRITE_BLOCKED'}

      if ($kind -eq 'status') {
        $nativeCapability.blocked=Test-Path -LiteralPath $nativeActivePath
        $nativeCapability.pendingReopen=$null
        if($nativeCapability.blocked){try{$nativeCapability.pendingReopen=Get-ReopenPendingSummary $nativeDispatchRoot}catch{$nativeCapability.pendingReopen=@{status='unresolved-legacy-or-invalid-lock'}}}
        Write-JsonFile $responsePath ([ordered]@{
          kind = 'status'
          nativeScene = $nativeCapability
          nativeMap = @{schema=1;enabled=$true;tools=@('entity-transform','terrain','playtest-control','asset-inspection','template-item','template-currency','generalized-tabs','mondstadt-dropstuff','mondstadt-combat','entity-material','terrain-water','template-properties','role-template-bag');projectRoot=$projectRoot;pinsDigest=$dispatchPinsDigest}
          authorGraph = @{schema=1;enabled=$true;pinsDigest=$dispatchPinsDigest}
          pid = $PID
          elevated = $isAdmin
          user = $identity.Name
          startedUtc = $startedUtc.ToString('o')
          nowUtc = [DateTime]::UtcNow.ToString('o')
          deadlineUtc = $deadline.ToString('o')
          lifetimeMinutes = $LifetimeMinutes
          handled = $handled
          bridgeOpCount = $allowedOps.Count
          fsOps = $fsOps
          fsRoots = @($fsRoots | ForEach-Object { [ordered]@{ name = $_.name; path = $_.path; read = $_.read; write = $_.write } })
        })
      }
      elseif ($kind -eq 'load') {
        $targetPid = [int](Get-JsonField $body 'targetPid' 0)
        if ($targetPid -le 0) { throw 'BAD_TARGET_PID' }
        $scopeJson = & (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $targetPid | ConvertFrom-Json
        $runId = $scopeJson.runId
        & (Join-Path $PSScriptRoot 'load-bridge.ps1') -RunId $runId | Out-Null
        $ready = Join-Path (Join-Path $runsRoot $runId) 'bridge-ready.json'
        for ($i = 0; $i -lt 30 -and -not (Test-Path -LiteralPath $ready); $i++) { Start-Sleep -Milliseconds 500 }
        $readyPresent = Test-Path -LiteralPath $ready
        $payload = [ordered]@{ kind = 'load'; runId = $runId; readyFilePresent = $readyPresent; accepted = $null }
        if ($readyPresent) { $payload.accepted = (Read-JsonFile $ready).accepted }
        Write-JsonFile $responsePath $payload
        Write-Log ("load pid={0} runId={1} accepted={2}" -f $targetPid, $runId, $payload.accepted)
      }
      elseif ($kind -eq 'call') {
        # Shape and ids scope are settled before anything runs; the splat below carries
        # only the keys this function returned, so no caller-supplied key can reach
        # call-bridge.ps1 as a parameter.
        $callArguments = Get-ValidatedCallArguments -Request $body
        $runId  = $callArguments['RunId']
        $op     = $callArguments['Operation']
        $parsed = [Guid]::Empty
        if (-not [Guid]::TryParse($runId, [ref]$parsed)) { throw 'BAD_RUN_ID' }
        $allowedOps = Get-AllowedOps   # re-read per request; see the comment at the top
        if ($allowedOps -notcontains $op) { throw ('OP_NOT_ALLOWED:' + $op) }
        if (-not (Test-Path -LiteralPath (Join-Path $runsRoot $runId))) { throw 'RUN_DIR_NOT_FOUND' }
        $idsCount = 0
        if ($callArguments.ContainsKey('Ids')) { $idsCount = $callArguments['Ids'].Length }
        $reply = & $callScript @callArguments
        $reply | Out-File -LiteralPath $responsePath -Encoding utf8
        Write-Log ("call op={0} runId={1} ids={2} bytes={3}" -f $op, $runId, $idsCount, ($reply | Out-String).Length)
      }
      elseif ($kind -ceq 'native-scene') {
        $result=Invoke-FixedNativeScene -Request $body -RequestId $id
        Write-JsonFile $responsePath $result
        Write-Log ("native-scene id={0} action={1} ok={2}" -f $id,(Get-JsonField $body 'action' ''),$result.ok)
      }
      elseif ($kind -ceq 'native-map') {
        $result=Invoke-FixedNativeMap -Request $body -RequestId $id
        Write-JsonFile $responsePath $result
        Write-Log ("native-map id={0} tool={1} ok={2}" -f $id,$body.tool,$result.ok)
      }
      elseif ($kind -ceq 'native-reopen-reconcile') {
        Assert-ReopenProductionReconciliationEnabled
        Assert-ReopenExact $body @('kind','requestId','acceptanceSha256')
        $held=Lock-DispatchPins $projectRoot $nativePython $dispatchPins
        try{$result=Complete-ReopenReconciliation $nativeDispatchRoot $body.requestId $body.acceptanceSha256;Write-JsonFile $responsePath $result}
        finally{foreach($stream in $held){$stream.Dispose()}}
      }
      elseif ($kind -ceq 'author-graph') {
        $result=Invoke-FixedAuthorGraph -Request $body
        Write-JsonFile $responsePath $result
        Write-Log ("author-graph id={0} requestId={1}" -f $id,$body.requestId)
      }
      elseif ($kind -eq 'fs') {
        $result = Invoke-FsRequest -Request $body -Roots $fsRoots -BackupsRoot $backupsRoot
        Write-JsonFile $responsePath $result
        Write-Log ("fs op={0} path={1} -> {2}" -f (Get-JsonField $body 'op' ''), (Get-JsonField $body 'path' ''), ($result | ConvertTo-Json -Compress -Depth 3))
      }
      else {
        throw ('UNSUPPORTED_KIND:' + $kind)
      }
    } catch {
      ($_.Exception.GetType().FullName + ': ' + $_.Exception.Message) | Out-File -LiteralPath $errorPath -Encoding utf8
      Write-Log ("error id={0} : {1}" -f $id, $_.Exception.Message)
    } finally {
      Remove-Item -LiteralPath $req.FullName -Force -ErrorAction SilentlyContinue
      $handled++
    }
  }
  Start-Sleep -Milliseconds 700
}

Write-Log ("runner exiting; handled={0}" -f $handled)
