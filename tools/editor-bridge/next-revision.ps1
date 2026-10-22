# next-revision.ps1 -- bump the bridge revision and rebuild it.
#
# WHY THIS EXISTS
#   Assembly.LoadFrom can return an already loaded assembly rather than changed
#   bytes at the same path. A NEW IMPLEMENTATION therefore needs a new assembly
#   identity in an existing host. This script keeps all loader names in sync.
#
#   It is NOT a lease-renewal command. Entry.Start resets its concurrent-call flag
#   in finally. Once the prior worker has completed cleanup and export quiescence,
#   the SAME revision accepts a fresh settings path, pipe and nonce. An active or
#   cleanup-failed worker and every reused accepted scope are still refused.
#   Bootstrap logs the actual payload return code; do not infer success from load.
#
#   Every scope remains bounded to five minutes, and accepted scope identities
#   remain recorded (up to 256 per revision). Never bump to evade an active worker,
#   failed cleanup, or a scope-limit refusal. Routine clean renewal neither builds
#   a revision nor restarts the helper. Changed pinned sources need a fresh helper
#   under its existing lifecycle. Neither operation restarts the editor/game.
#
#   powershell -File tools/editor-bridge/next-revision.ps1            # show current, bump, rebuild
#   powershell -File tools/editor-bridge/next-revision.ps1 -DryRun    # show what would change
#   powershell -File tools/editor-bridge/next-revision.ps1 -Revision 71

param(
  [int]$Revision = 0,
  [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$bridgeRoot = $PSScriptRoot
$projectRoot = [IO.Path]::GetFullPath((Join-Path $bridgeRoot '../..'))
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# Every file that names a revision. new-scope.ps1 hashes both DLLs and load-bridge.ps1
# injects both, so a bump that misses one produces a frozen.json hash mismatch --
# ARTIFACT_HASH_MISMATCH -- at the next load, long after the cause.
$targets = @(
  'Bootstrap/Bootstrap.csproj',
  'Bootstrap/Entry.cs',
  'load-bridge.ps1',
  'new-scope.ps1',
  'ManagedBridge/Miliastra.EditorBridge.csproj',
  'verify-fixture.ps1',
  'verify-fixture-gameloop.ps1',
  'bridge_host.py'
)

$pattern = 'Net8R(\d+)'

function Get-Revisions {
  $found = @{}
  foreach ($rel in $targets) {
    $path = Join-Path $bridgeRoot $rel
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $text = [IO.File]::ReadAllText($path, $utf8NoBom)
    foreach ($m in [regex]::Matches($text, $pattern)) {
      $n = [int]$m.Groups[1].Value
      if (-not $found.ContainsKey($n)) { $found[$n] = @() }
      $found[$n] += $rel
    }
  }
  return $found
}

$found = Get-Revisions
if ($found.Count -eq 0) { throw 'NO_REVISION_FOUND: none of the target files name a Net8R<number>' }

$current = ($found.Keys | Sort-Object)[-1]
# More than one revision in play means a previous bump was applied to some files and
# not others. That is exactly the drift this script exists to prevent, so stop.
if ($found.Count -gt 1) {
  Write-Output 'MIXED REVISIONS -- a previous bump was applied inconsistently:'
  foreach ($n in ($found.Keys | Sort-Object)) {
    Write-Output ("  R{0}: {1}" -f $n, ($found[$n] -join ', '))
  }
  throw 'MIXED_REVISIONS'
}
Write-Output ("current revision: R{0} (in {1} files)" -f $current, $found[$current].Count)

$target = if ($Revision -gt 0) { $Revision } else { $current + 1 }
if ($target -le $current) { throw ("TARGET_NOT_A_BUMP: R{0} is not above R{1}" -f $target, $current) }

Write-Output ("target revision:  R$target")
$oldToken = "Net8R$current"
$newToken = "Net8R$target"

$changes = @()
foreach ($rel in $targets) {
  $path = Join-Path $bridgeRoot $rel
  if (-not (Test-Path -LiteralPath $path)) { continue }
  $text = [IO.File]::ReadAllText($path, $utf8NoBom)
  if ($text -notmatch $oldToken) { continue }
  $count = ([regex]::Matches($text, $oldToken)).Count
  $changes += [pscustomobject]@{ File = $rel; Occurrences = $count }
}

foreach ($c in $changes) { Write-Output ("  {0,-45} {1} occurrence(s)" -f $c.File, $c.Occurrences) }

if ($DryRun) {
  Write-Output 'dry run -- no files changed, nothing built'
  exit 0
}

foreach ($rel in $targets) {
  $path = Join-Path $bridgeRoot $rel
  if (-not (Test-Path -LiteralPath $path)) { continue }
  $text = [IO.File]::ReadAllText($path, $utf8NoBom)
  if ($text -notmatch $oldToken) { continue }
  [IO.File]::WriteAllText($path, $text.Replace($oldToken, $newToken), $utf8NoBom)
}
Write-Output 'version strings updated'

# Build order matters: both projects must exist under the new name before the
# bootstrap is copied next to the payload, because the bootstrap resolves the
# payload by name at run time.
foreach ($proj in @('ManagedBridge/Miliastra.EditorBridge.csproj', 'Bootstrap/Bootstrap.csproj')) {
  Write-Output ("building $proj ...")
  $out = & dotnet build (Join-Path $bridgeRoot $proj) -c Release --nologo 2>&1
  if ($LASTEXITCODE -ne 0) {
    # Print only the diagnostics. Dumping the whole build log buries the one line that
    # matters, and a new Adapter/*.cs file that nobody added to the explicit <Compile>
    # list in Miliastra.EditorBridge.csproj fails exactly this way.
    $errors = @($out | Select-String -Pattern 'error [A-Z]+\d+|错误 [A-Z]+\d+|error CS')
    if ($errors.Count -eq 0) { $out | Select-Object -Last 15 | ForEach-Object { Write-Output ('  ' + $_) } }
    else { $errors | Select-Object -First 10 | ForEach-Object { Write-Output ('  ' + $_.Line.Trim()) } }
    throw ("BUILD_FAILED: $proj")
  }
  $summary = ($out | Select-String -Pattern '已成功生成|Build succeeded' | Select-Object -First 1)
  Write-Output ('  ' + ($summary -replace '^\s+', ''))
}

$payloadDir = Join-Path $bridgeRoot 'ManagedBridge/bin/Release/net8.0-windows'
$bootstrapOut = Join-Path $bridgeRoot ("Bootstrap/bin/Release/net8.0/Miliastra.Bootstrap.Net8R$target.dll")
$bootstrapDst = Join-Path $payloadDir ("Miliastra.Bootstrap.Net8R$target.dll")
if (-not (Test-Path -LiteralPath $bootstrapOut)) { throw ("BOOTSTRAP_NOT_BUILT: $bootstrapOut") }
Copy-Item -LiteralPath $bootstrapOut -Destination $bootstrapDst -Force

$payloadDst = Join-Path $payloadDir ("Miliastra.EditorBridge.Net8R$target.dll")
foreach ($p in @($bootstrapDst, $payloadDst)) {
  if (-not (Test-Path -LiteralPath $p)) { throw ("ARTIFACT_MISSING: $p") }
  Write-Output ("  {0}  {1} bytes" -f (Split-Path $p -Leaf), (Get-Item -LiteralPath $p).Length)
}

# Bind the newly built bytes/MVID to the source set. No injection occurs here.
# Vector authoring will require this manifest plus the actual in-process ready
# receipt; a stale cached R300 assembly is not accepted as the new revision.
$freezeTool = Join-Path $projectRoot 'tools/graph-vector-values/release.py'
& python -B $freezeTool freeze --bridge $payloadDst --bootstrap $bootstrapDst
if ($LASTEXITCODE -ne 0) { throw 'VECTOR_BRIDGE_RELEASE_FREEZE_FAILED' }

Write-Output ''
Write-Output ("R$target is ready. Inject it with: python tools/editor-bridge/elevated-request.py load --target-pid <pid>")
Write-Output 'New implementation requires this new revision. After clean closure, renew with a fresh scope on the same revision; never reuse a scope or bypass an active worker.'
