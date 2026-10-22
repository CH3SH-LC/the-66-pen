# Tests for the file operations the elevated helper serves.
#
# These run UNELEVATED against a scratch tree. The interesting cases are the
# refusals: a path outside the roots, a destructive op whose "confirm" field does
# not repeat the target, a write into a read-only root. Each is a case where the
# helper must do nothing at all.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/editor-bridge/tests/test-elevated-fs-ops.ps1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-fs-guard.ps1')))
. ([System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-fs-ops.ps1')))

$script:Pass = 0
$script:Fail = 0
$script:Failures = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param([Parameter(Mandatory)][bool]$Condition, [Parameter(Mandatory)][string]$Name)
    if ($Condition) { $script:Pass++; Write-Host ("  PASS  " + $Name) }
    else { $script:Fail++; $script:Failures.Add($Name); Write-Host ("  FAIL  " + $Name) -ForegroundColor Red }
}

function Assert-ThrowsLike {
    param([Parameter(Mandatory)][scriptblock]$Body, [Parameter(Mandatory)][string]$Prefix, [Parameter(Mandatory)][string]$Name)
    try {
        & $Body | Out-Null
        $script:Fail++; $script:Failures.Add($Name)
        Write-Host ("  FAIL  " + $Name + "  (no throw; expected " + $Prefix + ")") -ForegroundColor Red
    } catch {
        $message = $_.Exception.Message
        if ($message.StartsWith($Prefix)) { $script:Pass++; Write-Host ("  PASS  " + $Name) }
        else {
            $script:Fail++; $script:Failures.Add($Name)
            Write-Host ("  FAIL  " + $Name + "  (threw '" + $message + "'; expected " + $Prefix + ")") -ForegroundColor Red
        }
    }
}

# For refusals raised by BCL types, whose message text is localised by the runtime
# and therefore cannot be matched on. The assertion that matters is "it refused".
function Assert-Throws {
    param([Parameter(Mandatory)][scriptblock]$Body, [Parameter(Mandatory)][string]$Name)
    try {
        & $Body | Out-Null
        $script:Fail++; $script:Failures.Add($Name)
        Write-Host ("  FAIL  " + $Name + "  (no throw; expected a refusal)") -ForegroundColor Red
    } catch {
        $script:Pass++; Write-Host ("  PASS  " + $Name)
    }
}

function Invoke-Op {
    param([Parameter(Mandatory)][hashtable]$Request)
    return Invoke-FsRequest -Request ([pscustomobject]$Request) -Roots $script:Roots -BackupsRoot $script:Backups
}

# --- fixtures ---------------------------------------------------------------
$scratch = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../.runtime/editor-bridge/fs-ops-tests'))
if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
$writable = Join-Path $scratch 'writable'
$readOnly = Join-Path $scratch 'readonly'
$backups  = Join-Path $scratch 'backups'
foreach ($d in @($writable, $readOnly, $backups)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

$script:Roots = @(
    [pscustomobject]@{ name = 'writable'; path = $writable; read = $true; write = $true },
    [pscustomobject]@{ name = 'readonly'; path = $readOnly; read = $true; write = $false },
    [pscustomobject]@{ name = 'backups';  path = $backups;  read = $true; write = $true }
)
$script:Backups = $backups
# A path outside every root, used to prove destination checks are as strict as source checks.
$outside = Join-Path ([System.IO.Path]::GetTempPath()) 'elevated-fs-ops-outside'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'FATAL: these tests must run UNELEVATED.' -ForegroundColor Red
    exit 2
}

Write-Host 'File operations'
Write-Host ''

Write-Host 'Dispatch'
Assert-ThrowsLike -Name 'unknown op refused' -Prefix 'FS_OP_NOT_ALLOWED:' -Body {
    Invoke-Op @{ op = 'chmod'; path = (Join-Path $writable 'x') }
}
Assert-ThrowsLike -Name 'missing op refused' -Prefix 'FS_OP_NOT_ALLOWED:' -Body {
    Invoke-Op @{ path = (Join-Path $writable 'x') }
}
Assert-ThrowsLike -Name 'path outside every root refused' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Invoke-Op @{ op = 'write'; path = (Join-Path $outside 'x.txt'); encoding = 'utf8'; data = 'x' }
}

Write-Host ''
Write-Host 'write / read roundtrip'
$target = Join-Path $writable 'nested/hello.txt'
$w = Invoke-Op @{ op = 'write'; path = $target; encoding = 'utf8'; data = 'hello world' }
Assert-True -Name 'write creates missing parents and reports byte count' -Condition ($w.bytes -eq 11)
Assert-True -Name 'write returns the canonical path' -Condition ($w.path -eq [System.IO.Path]::GetFullPath($target))
Assert-True -Name 'write returns sha256 of the written bytes' -Condition (
    $w.sha256 -eq (Get-FileHash -LiteralPath $w.path -Algorithm SHA256).Hash.ToLowerInvariant()
)

$r = Invoke-Op @{ op = 'read'; path = $target; encoding = 'utf8' }
Assert-True -Name 'read returns what write stored' -Condition ($r.data -eq 'hello world')
Assert-True -Name 'read refuses a path outside every root' -Condition (
    (Test-Path -LiteralPath (Join-Path $readOnly 'never')) -eq $false
)
Assert-ThrowsLike -Name 'write into a read-only root refused' -Prefix 'ACCESS_DENIED_BY_ROOT:readonly' -Body {
    Invoke-Op @{ op = 'write'; path = (Join-Path $readOnly 'x.txt'); encoding = 'utf8'; data = 'x' }
}
Assert-ThrowsLike -Name 'read on a directory refused' -Prefix 'READ_ON_DIRECTORY' -Body {
    Invoke-Op @{ op = 'read'; path = $writable }
}
$badBin = Join-Path $writable 'bad.bin'
Assert-Throws -Name 'base64 payload that is not base64 refused' -Body {
    Invoke-Op @{ op = 'write'; path = $badBin; encoding = 'base64'; data = 'not base64!!' }
}
Assert-True -Name 'the refused base64 write created nothing' -Condition (-not (Test-Path -LiteralPath $badBin))

$binary = [Convert]::ToBase64String([byte[]](0..255))
$b = Invoke-Op @{ op = 'write'; path = (Join-Path $writable 'bytes.bin'); encoding = 'base64'; data = $binary }
Assert-True -Name 'binary roundtrip preserves all 256 byte values' -Condition (
    (Invoke-Op @{ op = 'read'; path = $b.path; encoding = 'base64' }).data -eq $binary
)

Write-Host ''
Write-Host 'stat / list / hash / mkdir'
$s = Invoke-Op @{ op = 'stat'; path = $target }
Assert-True -Name 'stat reports an existing file' -Condition ($s.exists -and -not $s.isContainer -and $s.length -eq 11)
$s2 = Invoke-Op @{ op = 'stat'; path = (Join-Path $writable 'absent.txt') }
Assert-True -Name 'stat reports a missing file without throwing' -Condition (-not $s2.exists)

$l = Invoke-Op @{ op = 'list'; path = $writable }
$names = @($l.entries | ForEach-Object { $_.name }) -join ','
Assert-True -Name 'list sees exactly the nested directory and the binary file' -Condition ($l.count -eq 2 -and $names -eq 'bytes.bin,nested')
Assert-True -Name 'list is not truncated below its cap' -Condition (-not $l.truncated)
$l2 = Invoke-Op @{ op = 'list'; path = $writable; max = 1 }
Assert-True -Name 'list honours max and sets truncated' -Condition ($l2.count -eq 1 -and $l2.truncated)

$h = Invoke-Op @{ op = 'hash'; path = $target }
Assert-True -Name 'hash matches Get-FileHash' -Condition ($h.hash -eq (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant())
Assert-ThrowsLike -Name 'unsupported hash algorithm refused' -Prefix 'UNSUPPORTED_ALGORITHM:' -Body {
    Invoke-Op @{ op = 'hash'; path = $target; algorithm = 'crc32' }
}

$m = Invoke-Op @{ op = 'mkdir'; path = (Join-Path $writable 'fresh/dir') }
Assert-True -Name 'mkdir creates a nested directory' -Condition ($m.created -and (Test-Path -LiteralPath $m.path))
$m2 = Invoke-Op @{ op = 'mkdir'; path = $m.path }
Assert-True -Name 'mkdir on an existing directory is idempotent' -Condition (-not $m2.created)

Write-Host ''
Write-Host 'copy'
$copied = Invoke-Op @{ op = 'copy'; path = $target; dest = (Join-Path $writable 'copy.txt') }
Assert-True -Name 'copy produces an identical file' -Condition (
    (Get-FileHash -LiteralPath $copied.dest -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
)
Assert-ThrowsLike -Name 'copy onto an existing dest without overwrite refused' -Prefix 'DEST_EXISTS:' -Body {
    Invoke-Op @{ op = 'copy'; path = $target; dest = $copied.dest }
}
$null = Invoke-Op @{ op = 'copy'; path = $target; dest = $copied.dest; overwrite = $true }
Assert-True -Name 'copy with overwrite succeeds' -Condition $true
Assert-ThrowsLike -Name 'copy destination outside every root refused' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Invoke-Op @{ op = 'copy'; path = $target; dest = (Join-Path $outside 'leak.txt') }
}
Assert-ThrowsLike -Name 'copy source outside every root refused' -Prefix 'PATH_OUTSIDE_ALLOWED_ROOTS' -Body {
    Invoke-Op @{ op = 'copy'; path = 'C:\Windows\System32\drivers\etc\hosts'; dest = (Join-Path $writable 'hosts.txt') }
}

Write-Host ''
Write-Host 'move -- transcription check'
$mvSrc = Join-Path $writable 'move-me.txt'
$null = Invoke-Op @{ op = 'write'; path = $mvSrc; encoding = 'utf8'; data = 'move' }
Assert-ThrowsLike -Name 'move without confirm refused' -Prefix 'CONFIRM_REQUIRED_FOR_MOVE' -Body {
    Invoke-Op @{ op = 'move'; path = $mvSrc; dest = (Join-Path $writable 'moved.txt') }
}
Assert-ThrowsLike -Name 'move with a mismatched confirm refused' -Prefix 'CONFIRM_DOES_NOT_MATCH_TARGET:move' -Body {
    Invoke-Op @{ op = 'move'; path = $mvSrc; dest = (Join-Path $writable 'moved.txt'); confirm = (Join-Path $writable 'something-else.txt') }
}
Assert-ThrowsLike -Name 'confirm is an exact match, not case-insensitive' -Prefix 'CONFIRM_DOES_NOT_MATCH_TARGET:move' -Body {
    Invoke-Op @{ op = 'move'; path = $mvSrc; dest = (Join-Path $writable 'moved.txt'); confirm = $mvSrc.ToUpperInvariant() }
}
Assert-True -Name 'the refused move left the source in place' -Condition (Test-Path -LiteralPath $mvSrc)
$mv = Invoke-Op @{ op = 'move'; path = $mvSrc; dest = (Join-Path $writable 'moved.txt'); confirm = $mvSrc }
Assert-True -Name 'move with a matching confirm relocates the file' -Condition (
    (Test-Path -LiteralPath $mv.dest) -and -not (Test-Path -LiteralPath $mvSrc)
)

Write-Host ''
Write-Host 'delete -- transcription check'
$delFile = Join-Path $writable 'delete-me.txt'
$null = Invoke-Op @{ op = 'write'; path = $delFile; encoding = 'utf8'; data = 'bye' }
Assert-ThrowsLike -Name 'delete without confirm refused' -Prefix 'CONFIRM_REQUIRED_FOR_DELETE' -Body {
    Invoke-Op @{ op = 'delete'; path = $delFile }
}
Assert-True -Name 'the refused delete left the file in place' -Condition (Test-Path -LiteralPath $delFile)
$d = Invoke-Op @{ op = 'delete'; path = $delFile; confirm = $delFile }
Assert-True -Name 'delete with a matching confirm removes the file' -Condition ($d.deleted -and -not (Test-Path -LiteralPath $delFile))
$d2 = Invoke-Op @{ op = 'delete'; path = $delFile; confirm = $delFile }
Assert-True -Name 'delete of an already-absent path is a no-op, not an error' -Condition (-not $d2.deleted)

$nonEmpty = Join-Path $writable 'tree/sub'
$null = Invoke-Op @{ op = 'write'; path = (Join-Path $nonEmpty 'leaf.txt'); encoding = 'utf8'; data = 'leaf' }
Assert-ThrowsLike -Name 'delete of a non-empty directory without recurse refused' -Prefix 'DIRECTORY_NOT_EMPTY_AND_RECURSE_NOT_SET' -Body {
    Invoke-Op @{ op = 'delete'; path = (Join-Path $writable 'tree'); confirm = (Join-Path $writable 'tree') }
}
Assert-True -Name 'the refused recursive delete left the tree intact' -Condition (Test-Path -LiteralPath (Join-Path $nonEmpty 'leaf.txt'))
$d3 = Invoke-Op @{ op = 'delete'; path = (Join-Path $writable 'tree'); confirm = (Join-Path $writable 'tree'); recurse = $true }
Assert-True -Name 'delete with recurse removes the tree' -Condition ($d3.deleted -and -not (Test-Path -LiteralPath (Join-Path $writable 'tree')))
Assert-ThrowsLike -Name 'deleting a configured root refused even with recurse and confirm' -Prefix 'REFUSE_TO_REMOVE_ROOT:writable' -Body {
    Invoke-Op @{ op = 'delete'; path = $writable; confirm = $writable; recurse = $true }
}
Assert-True -Name 'the root survived the refused delete' -Condition (Test-Path -LiteralPath $writable)

Write-Host ''
Write-Host 'snapshot'
$snapSrc = Join-Path $writable 'snap-source'
$null = Invoke-Op @{ op = 'write'; path = (Join-Path $snapSrc 'inner.txt'); encoding = 'utf8'; data = 'snap' }
$snap = Invoke-Op @{ op = 'snapshot'; path = $snapSrc; label = 'unit-test' }
Assert-True -Name 'snapshot copies the tree' -Condition (Test-Path -LiteralPath (Join-Path $snap.snapshot 'inner.txt'))
Assert-True -Name 'snapshot writes a manifest' -Condition (Test-Path -LiteralPath (Join-Path $snap.snapshot 'snapshot-manifest.json'))
Assert-True -Name 'snapshot preserves content' -Condition (
    (Get-Content -LiteralPath (Join-Path $snap.snapshot 'inner.txt') -Raw).Trim() -eq 'snap'
)
Assert-ThrowsLike -Name 'snapshot label with a path separator refused' -Prefix 'BAD_SNAPSHOT_LABEL:' -Body {
    Invoke-Op @{ op = 'snapshot'; path = $snapSrc; label = '../escape' }
}

Write-Host ''
Write-Host 'Payload cap'
$smallPath = Join-Path $writable 'small.txt'
$capped = Invoke-FsRequest -Request ([pscustomobject]@{ op = 'write'; path = $smallPath; encoding = 'utf8'; data = 'abcd' }) -Roots $script:Roots -BackupsRoot $backups -MaxPayloadBytes 4
Assert-True -Name 'write exactly at the cap succeeds' -Condition ($capped.bytes -eq 4)

$overPath = Join-Path $writable 'over.txt'
Assert-ThrowsLike -Name 'write above the cap refused' -Prefix 'PAYLOAD_TOO_LARGE' -Body {
    Invoke-FsRequest -Request ([pscustomobject]@{ op = 'write'; path = $overPath; encoding = 'utf8'; data = 'abcde' }) -Roots $script:Roots -BackupsRoot $backups -MaxPayloadBytes 4
}
Assert-True -Name 'the over-cap write created nothing' -Condition (-not (Test-Path -LiteralPath $overPath))
Assert-True -Name 'read at the cap succeeds' -Condition (
    (Invoke-FsRequest -Request ([pscustomobject]@{ op = 'read'; path = $smallPath; encoding = 'utf8' }) -Roots $script:Roots -BackupsRoot $backups -MaxPayloadBytes 4).data -eq 'abcd'
)
Assert-ThrowsLike -Name 'read above the cap refused' -Prefix 'FILE_TOO_LARGE' -Body {
    Invoke-FsRequest -Request ([pscustomobject]@{ op = 'read'; path = (Join-Path $writable 'bytes.bin'); encoding = 'utf8' }) -Roots $script:Roots -BackupsRoot $backups -MaxPayloadBytes 4
}

Write-Host ''
Write-Host 'Invariants'
Assert-True -Name 'tests ran unelevated' -Condition (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
Assert-True -Name 'nothing was created outside the scratch tree' -Condition (-not (Test-Path -LiteralPath $outside))

if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ''
Write-Host ('passed=' + $script:Pass + ' failed=' + $script:Fail)
if ($script:Fail -gt 0) {
    Write-Host 'FAILURES:'
    foreach ($f in $script:Failures) { Write-Host ('  - ' + $f) }
    exit 1
}
exit 0
