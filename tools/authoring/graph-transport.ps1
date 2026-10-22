param([Parameter(Mandatory=$true)][string]$SettingsPath,
      [Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)

# How long to wait for the bridge's reply, per op.
#
# A fixed 15000 used to live inline at the read below. call-bridge.ps1 -- the transport
# this one is a copy of -- had already measured the shared-registry walk behind `catalog`
# at ~12.48s and raised ITS window to 60000ms for exactly these ops, recording the reason
# in its own source ("10s cut the client off mid-response"). This copy never received
# that correction, so a 15s ceiling survived here and a real `graph catalog` call hit it.
#
# Why not simply 60000, to match call-bridge.ps1? Because the two transports do NOT sit
# under the same outer deadline. call-bridge.ps1 is reached through elevated-request.py's
# `call`, whose client timeout defaults to 300s. This file is reached through
# elevated_graph_call, whose client timeout is 60s -- a 60s inner wait would let the
# helper write its reply to a client that has already given up, which is the same defect
# in the other direction.
#
# 45000 sits far above the measured walk and below that 60s ceiling. Both ops get it:
# the graph ops share the server process, and for a WRITE the dangerous direction is a
# window that is too short, because a lost reply then reads as "nothing happened".
function Get-GraphResponseWindowMs([string]$Op) {
    return 45000
}

$pipe = $null
$reader = $null
$writer = $null
$stage = 'scope'
try {
    $scope = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if ([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse($scope.expiresUtc)) { throw 'EXPIRED' }
    if (Test-Path -LiteralPath (Join-Path (Split-Path $SettingsPath) 'lease-closed.json')) { throw 'CLOSED' }
    $stage = 'identity'
    $target = Get-Process -Id ([int]$scope.pid) -ErrorAction Stop
    if ($target.StartTime.ToUniversalTime().Ticks -ne [long]$scope.startUtcTicks) { throw 'SESSION_CHANGED' }
    try { $targetImage = $target.MainModule.FileName } catch { throw 'TARGET_IMAGE_UNREADABLE' }
    if ($targetImage -ine $scope.expectedExe) { throw 'IMAGE_CHANGED' }
    $stage = 'compatibility'
    $projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    . (Join-Path $projectRoot 'tools/editor-bridge/compatibility-guard.ps1')
    # Identity comes from this observation, never from the scope's claimed name/path.
    $null = Get-MiliastraCompatibilityPin -ProjectRoot $projectRoot -ProcessName $target.ProcessName -ImagePath $targetImage -StartUtcTicks $target.StartTime.ToUniversalTime().Ticks
    $stage = 'request'
    $request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($request.op -cne 'author-graph' -and $request.op -cne 'catalog') { throw 'OP_NOT_ALLOWED' }
    $request | Add-Member -NotePropertyName nonce -NotePropertyValue $scope.nonce
    $line = $request | ConvertTo-Json -Compress -Depth 12
    if ([Text.Encoding]::UTF8.GetByteCount($line) -gt 16000) { throw 'REQUEST_TOO_LARGE' }
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', $scope.pipeName, [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
    $stage = 'connect'
    $pipe.Connect(5000)
    $writer = [IO.StreamWriter]::new($pipe, [Text.UTF8Encoding]::new($false), 1024, $true)
    $reader = [IO.StreamReader]::new($pipe, [Text.UTF8Encoding]::new($false), $false, 1024, $true)
    $writer.AutoFlush = $true
    $stage = 'send'
    $writer.WriteLine($line)
    # The stage is deliberately NOT advanced past 'send' here. The catch below keys
    # `outcomeUncertain` off it, and "the request was written and no reply arrived" is
    # exactly the uncertain case: if the op was a write it may have landed, so the
    # caller must not treat the timeout as proof of no effect. Renaming the stage would
    # silently turn a lost-reply write into a certain failure.
    $responseTimeoutMs = Get-GraphResponseWindowMs $request.op
    $taskRead = $reader.ReadLineAsync()
    if (-not $taskRead.Wait($responseTimeoutMs)) { throw 'RESPONSE_TIMEOUT' }
    if ($null -eq $taskRead.Result) { throw 'RESPONSE_MISSING' }
    Write-Output $taskRead.Result
} catch {
    # Do not disclose settings, nonce, pipe name or raw privileged exception.
    $errorCode = if ($stage -eq 'compatibility') { 'incompatible-version' } else { 'BRIDGE_TRANSPORT_FAILED' }
    @{ok=$false;code=$errorCode;error=$errorCode;stage=$stage;exceptionType=$_.Exception.GetType().Name;outcomeUncertain=($stage -eq 'send')} | ConvertTo-Json -Compress
    exit 2
} finally {
    if ($reader) { $reader.Dispose() }
    if ($writer) { $writer.Dispose() }
    if ($pipe) { $pipe.Dispose() }
}
