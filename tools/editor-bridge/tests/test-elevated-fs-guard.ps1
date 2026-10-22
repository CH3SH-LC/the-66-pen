# Negative-first tests for the elevated helper's path policy.
#
# These run UNELEVATED on purpose. The guard is the only thing standing between a
# request file dropped in a plain directory and an arbitrary-path file operation
# running as Administrator, so its rejections are the product, not the edge cases.
# Each test below names the escape it is closing.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/editor-bridge/tests/test-elevated-fs-guard.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$guardPath = Join-Path $PSScriptRoot '../elevated-fs-guard.ps1'
. ([System.IO.Path]::GetFullPath($guardPath))

$script:Pass = 0
$script:Fail = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Name)
    if ($Condition) { $script:Pass++; Write-Host ("  PASS  " + $Name) }
    else { $script:Fail++; $script:Failures.Add($Name); Write-Host ("  FAIL  " + $Name) -ForegroundColor Red }
}

# Assert that $Body throws with a message starting with $Prefix.
function Assert-ThrowsLike {
    param(
        [Parameter(Mandatory)][scriptblock]$Body,
        [Parameter(Mandatory)][string]$Prefix,
        [Parameter(Mandatory)][string]$Name
    )
    try {
        & $Body | Out-Null
        $script:Fail++; $script:Failures.Add($Name)
        Write-Host ("  FAIL  " + $Name + "  (no throw; expected " + $Prefix + ")") -ForegroundColor Red
    } catch {
        $message = $_.Exception.Message
        if ($message.StartsWith($Prefix)) {
            $script:Pass++; Write-Host ("  PASS  " + $Name)
        } else {
            $script:Fail++; $script:Failures.Add($Name)
            Write-Host ("  FAIL  " + $Name + "  (threw '" + $message + "'; expected " + $Prefix + ")") -ForegroundColor Red
        }
    }
}

# --- scratch tree -----------------------------------------------------------
$scratch = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../.runtime/editor-bridge/guard-tests'))
if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
$insideRoot = Join-Path $scratch 'allowed'
$readOnlyRoot = Join-Path $scratch 'readonly'
$nestedInsideReadOnly = Join-Path $readOnlyRoot 'nested-writable'
foreach ($d in @($scratch, $insideRoot, $readOnlyRoot)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

$roots = @(
    [pscustomobject]@{ name = 'allowed'; path = $insideRoot; read = $true; write = $true },
    [pscustomobject]@{ name = 'readonly'; path = $readOnlyRoot; read = $true; write = $false },
    [pscustomobject]@{ name = 'readonly-nested'; path = $nestedInsideReadOnly; read = $true; write = $true }
)

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'FATAL: these tests must run UNELEVATED; their conclusions would not transfer.' -ForegroundColor Red
    exit 2
}

Write-Host 'Path-policy guard'
Write-Host ''

Write-Host 'Input rejection'
Assert-ThrowsLike -Name 'empty path rejected' -Prefix 'PATH_EMPTY' -Body { Resolve-GuardedPath -Path '' -Roots $roots }
Assert-ThrowsLike -Name 'whitespace-only path rejected' -Prefix 'PATH_EMPTY' -Body { Resolve-GuardedPath -Path '   ' -Roots $roots }
Assert-ThrowsLike -Name 'embedded NUL rejected' -Prefix 'PATH_HAS_NUL_CHARACTER' -Body {
    Resolve-GuardedPath -Path ("a" + [char]0 + "b") -Roots $roots
}

Write-Host ''
Write-Host 'Root containment'
$ok = Resolve-GuardedPath -Path (Join-Path $insideRoot 'file.txt') -Roots $roots -Access write
Assert-True -Name 'path inside a writable root resolves' -Condition ($ok.Root.name -eq 'allowed')

Assert-ThrowsLike -Name 'dot-dot escape rejected' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Resolve-GuardedPath -Path (Join-Path $insideRoot '../../Windows/System32/drivers/etc/hosts') -Roots $roots
}
Assert-ThrowsLike -Name 'absolute path outside every root rejected' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Resolve-GuardedPath -Path 'C:\Windows\System32\drivers\etc\hosts' -Roots $roots
}
Assert-ThrowsLike -Name 'sibling with matching prefix rejected' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    # 'allowed-sibling' shares the string prefix 'allowed' but is not under it.
    Resolve-GuardedPath -Path ($insideRoot + '-sibling/file.txt') -Roots $roots
}
Assert-ThrowsLike -Name 'the drive root itself rejected' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Resolve-GuardedPath -Path 'C:\' -Roots $roots
}

$rootItself = Resolve-GuardedPath -Path $insideRoot -Roots $roots
Assert-True -Name 'a configured root is readable as itself' -Condition ($rootItself.Root.name -eq 'allowed')

Write-Host ''
Write-Host 'Access kind'
$readOnly = Resolve-GuardedPath -Path (Join-Path $readOnlyRoot 'a.txt') -Roots $roots -Access read
Assert-True -Name 'read on read-only root resolves' -Condition ($readOnly.Root.name -eq 'readonly')
Assert-ThrowsLike -Name 'write on read-only root rejected' -Prefix 'ACCESS_DENIED_BY_ROOT:readonly' -Body {
    Resolve-GuardedPath -Path (Join-Path $readOnlyRoot 'a.txt') -Roots $roots -Access write
}

$nested = Resolve-GuardedPath -Path (Join-Path $nestedInsideReadOnly 'b.txt') -Roots $roots -Access write
Assert-True -Name 'nested writable root wins over enclosing read-only root' -Condition ($nested.Root.name -eq 'readonly-nested')

Write-Host ''
Write-Host 'Nonexistent targets'
$future = Resolve-GuardedPath -Path (Join-Path $insideRoot 'not/created/yet.txt') -Roots $roots -Access write
Assert-True -Name 'nonexistent path under a writable root accepted' -Condition ($future.Canonical.EndsWith('yet.txt'))
Assert-ThrowsLike -Name 'nonexistent path outside every root still rejected' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Resolve-GuardedPath -Path (Join-Path $scratch 'elsewhere/yet.txt') -Roots $roots -Access write
}

Write-Host ''
Write-Host 'Reparse points (junction escape)'
$junction = Join-Path $insideRoot 'escape'
$junctionMade = $false
try {
    $null = & cmd.exe /c mklink /J "`"$junction`"" "`"$scratch`"" 2>&1
    $junctionMade = Test-Path -LiteralPath $junction
} catch { $junctionMade = $false }

if ($junctionMade) {
    Assert-ThrowsLike -Name 'junction inside a writable root cannot be traversed' -Prefix 'REPARSE_POINT_IN_PATH:' -Body {
        Resolve-GuardedPath -Path (Join-Path $junction 'target.txt') -Roots $roots -Access write
    }
    Assert-ThrowsLike -Name 'the junction entry itself is refused' -Prefix 'REPARSE_POINT_IN_PATH:' -Body {
        Resolve-GuardedPath -Path $junction -Roots $roots -Access write
    }
} else {
    Assert-True -Name 'junction fixture could not be created (mklink /J unavailable)' -Condition $false
}

Write-Host ''
Write-Host 'Root removal'
Assert-ThrowsLike -Name 'deleting a configured root refused' -Prefix 'REFUSE_TO_REMOVE_ROOT:allowed' -Body {
    Assert-NotARoot -Canonical $insideRoot -Roots $roots
}
try {
    Assert-NotARoot -Canonical (Join-Path $insideRoot 'x.txt') -Roots $roots
    Assert-True -Name 'deleting a path below a root is not refused here' -Condition $true
} catch {
    Assert-True -Name 'deleting a path below a root is not refused here' -Condition $false
}

Write-Host ''
Write-Host 'Live config'
$configPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-config.json'))
$liveRoots = Import-ElevatedConfig -ConfigPath $configPath
Assert-True -Name ('live config loads (' + $liveRoots.Count + ' roots)') -Condition ($liveRoots.Count -ge 4)
foreach ($r in $liveRoots) {
    Assert-True -Name ('live root exists: ' + $r.name) -Condition (Test-Path -LiteralPath $r.path)
}
$gameRoot = $liveRoots | Where-Object { $_.name -eq 'game-install' }
Assert-True -Name 'game install root is read-only' -Condition ($null -ne $gameRoot -and -not $gameRoot.write)
Assert-ThrowsLike -Name 'live config refuses a write into the game install' -Prefix 'ACCESS_DENIED_BY_ROOT:game-install' -Body {
    Resolve-GuardedPath -Path (Join-Path $gameRoot.path 'YuanShen.exe') -Roots $liveRoots -Access write
}
$dataRoot = $liveRoots | Where-Object { $_.name -eq 'game-data-locallow' }
Assert-True -Name 'game data root is read-only' -Condition ($null -ne $dataRoot -and $dataRoot.read -and -not $dataRoot.write)
$probe = Join-Path $dataRoot.path 'BeyondLocal'
Assert-True -Name 'game data root reaches the real BeyondLocal directory' -Condition (
    (Resolve-GuardedPath -Path $probe -Roots $liveRoots).Root.name -eq 'game-data-locallow'
)

Write-Host ''
Write-Host 'Security invariants of this test file itself'
Assert-True -Name 'tests ran unelevated' -Condition (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

# --- cleanup ----------------------------------------------------------------
if ($junctionMade -and (Test-Path -LiteralPath $junction)) {
    # Remove the junction without following it.
    & cmd.exe /c rmdir "`"$junction`"" | Out-Null
}
if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ''
Write-Host ('passed=' + $script:Pass + ' failed=' + $script:Fail)
if ($script:Fail -gt 0) {
    Write-Host 'FAILURES:'
    foreach ($f in $script:Failures) { Write-Host ('  - ' + $f) }
    exit 1
}
exit 0
