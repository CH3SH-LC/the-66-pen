# start-elevated.ps1 -- raise the resident elevated helper, once, then leave it alone.
#
# This is the only place in the project that asks Windows for elevation. It asks
# once and the answer is reused for the whole session, so no unattended step later
# can raise a prompt of its own.
#
#   powershell -NoProfile -File tools/editor-bridge/start-elevated.ps1
#   powershell -NoProfile -File tools/editor-bridge/start-elevated.ps1 -Status
#   powershell -NoProfile -File tools/editor-bridge/start-elevated.ps1 -Stop
#
# -Status never elevates and never starts anything; it only reads the heartbeat.
# -Stop drops the STOP file the helper watches, so it exits without a prompt.
#
# If a UAC prompt is declined or simply never answered, this script reports that and
# exits non-zero. It does not retry: a retry loop would put a prompt back on screen
# every few seconds, which is exactly the behaviour this helper exists to avoid.

param(
  [int]$LifetimeMinutes = 1440,
  [switch]$Status,
  [switch]$Stop,
  [int]$WaitSeconds = 120,
  [string]$QueueDir = '',
  [string]$ConfigPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$queueRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot '.runtime/editor-bridge'))
if ([string]::IsNullOrWhiteSpace($QueueDir)) {
  $QueueDir = Join-Path $queueRoot 'elevated-queue'
} elseif (-not [IO.Path]::IsPathRooted($QueueDir)) {
  $QueueDir = Join-Path $projectRoot $QueueDir
}
$queueDir = [IO.Path]::GetFullPath($QueueDir).TrimEnd('\', '/')
if (-not $queueDir.StartsWith($queueRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw 'QUEUE_OUTSIDE_PROJECT_EDITOR_BRIDGE: QueueDir must be below .runtime/editor-bridge.'
}
# Check the queue and every existing parent, including parents above the project.
$queueAncestor = $queueDir
while (-not [string]::IsNullOrEmpty($queueAncestor)) {
  if (Test-Path -LiteralPath $queueAncestor) {
    $queueItem = Get-Item -LiteralPath $queueAncestor -Force
    if ($queueItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      throw ('QUEUE_REPARSE_POINT: ' + $queueAncestor)
    }
    if (-not $queueItem.PSIsContainer) { throw ('QUEUE_PARENT_NOT_DIRECTORY: ' + $queueAncestor) }
  }
  $queueAncestor = [IO.Path]::GetDirectoryName($queueAncestor)
}
if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
  $ConfigPath = Join-Path $PSScriptRoot 'elevated-config.json'
} elseif (-not [IO.Path]::IsPathRooted($ConfigPath)) {
  $ConfigPath = Join-Path $projectRoot $ConfigPath
}
$ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
$heartbeat   = Join-Path $queueDir 'runner.heartbeat'
$stopPath    = Join-Path $queueDir 'STOP'
$runner      = Join-Path $PSScriptRoot 'elevated-runner.ps1'
$utf8NoBom   = New-Object System.Text.UTF8Encoding($false)

$nativePowerShell = (Get-Process -Id $PID).Path
$nativePolicy = (Get-ExecutionPolicy).ToString()
if ($nativePolicy -notin @('RemoteSigned', 'Unrestricted')) { throw ('NATIVE_HOST_POLICY_REFUSED:' + $nativePolicy) }
$env:MILIASTRA_POWERSHELL_HOST = $nativePowerShell
Write-Output ('PowerShell host: ' + $nativePowerShell + '; version=' + $PSVersionTable.PSVersion + '; policy=' + $nativePolicy + '; sha256=' + (Get-FileHash -LiteralPath $nativePowerShell -Algorithm SHA256).Hash)

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Get-Heartbeat {
  if (-not (Test-Path -LiteralPath $heartbeat)) { return $null }
  try {
    $text = [IO.File]::ReadAllText($heartbeat, $utf8NoBom)
    # The heartbeat carries a trailing Z. [DateTime]::Parse converts that to LOCAL
    # time by default, and subtracting a Local value from [DateTime]::UtcNow compares
    # raw ticks across two different clocks -- an error of the whole UTC offset. On
    # this machine that made a heartbeat which stopped an hour ago compute as minus
    # seven hours, and "age <= 30" then reported ALIVE. AdjustToUniversal keeps both
    # sides on the same clock.
    $stamp = [DateTime]::Parse(
      ($text -split ' ')[0],
      [Globalization.CultureInfo]::InvariantCulture,
      [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal)
    return [pscustomobject]@{
      Text       = $text.Trim()
      StampUtc   = $stamp
      AgeSeconds = [Math]::Round(([DateTime]::UtcNow - $stamp).TotalSeconds, 1)
    }
  } catch { return $null }
}

if ($Stop) {
  New-Item -ItemType Directory -Force -Path $queueDir | Out-Null
  Set-Content -LiteralPath $stopPath -Value 'stop' -Encoding utf8
  Write-Output 'STOP file written; it remains until an explicit new start. The helper exits after its current operation and next loop check.'
  exit 0
}

$hb = Get-Heartbeat
if ($Status) {
  if ($null -eq $hb) { Write-Output 'heartbeat: absent (helper not running)'; exit 1 }
  Write-Output ('heartbeat: ' + $hb.Text)
  Write-Output ('age: ' + $hb.AgeSeconds + 's')
  # A negative age means the two clocks disagree, not that the helper is fresh.
  # Fail closed: an unattended run must not be told "alive" by a broken comparison.
  if ($hb.AgeSeconds -lt -5) {
    Write-Output 'verdict: UNKNOWN -- heartbeat timestamp is in the future; clocks disagree'
    exit 1
  }
  if ($hb.AgeSeconds -gt 30) { Write-Output 'verdict: STALE -- the helper may have exited'; exit 1 }
  Write-Output 'verdict: ALIVE'
  exit 0
}

if ($null -ne $hb -and $hb.AgeSeconds -le 30 -and $hb.AgeSeconds -ge -5) {
  Write-Output ('already running: ' + $hb.Text)
  exit 0
}

if (Test-Path -LiteralPath $stopPath) { Remove-Item -LiteralPath $stopPath -Force }

New-Item -ItemType Directory -Force -Path $queueDir | Out-Null

$argumentList = @(
  '-NoProfile'
  '-File', ('"' + $runner + '"')
  '-LifetimeMinutes', $LifetimeMinutes
  '-QueueDir', ('"' + $queueDir + '"')
  '-ConfigPath', ('"' + $ConfigPath + '"')
)

if ($isAdmin) {
  # Already elevated -- this is the path "Run as administrator" takes, and it is
  # the one to prefer: there is no second elevation request to get lost behind
  # another window. The helper is launched detached rather than run in this
  # process, so closing this console does not take the helper down with it.
  Write-Output 'this shell is already elevated; launching the helper detached (no second prompt)'
  Start-Process -FilePath $nativePowerShell -ArgumentList $argumentList -WindowStyle Hidden | Out-Null
} else {
  Write-Output 'requesting elevation once -- approve the Windows prompt; nothing else in this run will ask again'
  Write-Output 'if this hangs, the prompt is probably behind another window: check the taskbar,'
  Write-Output 'or close this and re-run start-elevated.cmd with "Run as administrator" instead.'
  Start-Process -FilePath $nativePowerShell -ArgumentList $argumentList -Verb RunAs -WindowStyle Hidden | Out-Null
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 750
  $hb = Get-Heartbeat
  if ($null -ne $hb -and $hb.AgeSeconds -le 30 -and $hb.AgeSeconds -ge -5) {
    Write-Output ('elevated helper is up: ' + $hb.Text)
    Write-Output ('lifetime: ' + $LifetimeMinutes + ' minutes from ' + $hb.StampUtc.ToString('o') + ' UTC')
    exit 0
  }
}

$startupErrorPath = Join-Path $queueDir 'runner.startup-error.txt'
if (Test-Path -LiteralPath $startupErrorPath) {
  Write-Output 'the helper DID start and then failed. It reported:'
  Get-Content -LiteralPath $startupErrorPath | ForEach-Object { Write-Output ('  ' + $_) }
  Write-Error ('the elevated helper failed at startup after ' + $WaitSeconds + 's')
  exit 1
}
if (Test-Path -LiteralPath (Join-Path $queueDir 'runner.log')) {
  Write-Output 'runner.log tail:'
  Get-Content -LiteralPath (Join-Path $queueDir 'runner.log') -Tail 20 | ForEach-Object { Write-Output ('  ' + $_) }
}
Write-Error ('the elevated helper did not come up within ' + $WaitSeconds + 's -- the UAC prompt was declined or left unanswered')
exit 1
