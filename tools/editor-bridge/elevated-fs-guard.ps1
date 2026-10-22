# elevated-fs-guard.ps1 -- pure path-policy layer for the resident elevated helper.
#
# WHY THIS FILE IS SEPARATE
#   The elevated runner is the only privileged component in this project, so its
#   security decisions have to be reviewable and testable *without* elevation.
#   Everything here is a decision function over strings and file attributes; it
#   never creates, writes, moves or deletes anything. tests/test-elevated-fs-guard.ps1
#   exercises it unelevated.
#
# FAIL-CLOSED RULES, APPLIED IN ORDER
#   1. Reject empty / NUL-bearing input; canonicalise with [IO.Path]::GetFullPath,
#      which collapses "." and ".." -- so "..\..\Windows" cannot survive step 2.
#   2. The canonical path must sit under a configured root, on a separator
#      boundary ("C:\Games\Genshin Impact GameX" must not match root
#      "C:\Games\Genshin Impact Game").
#   3. No component between the root and the target may be a reparse point.
#      A junction or symlink placed inside an allowed root is the one way a
#      string-prefix check can be true while the bytes land outside the root.
#   4. The matched root must grant the requested access kind (read or write).
#   5. A configured root itself may never be deleted.
#
# KNOWN AND ACCEPTED LIMITS
#   - Hard links are not detected. A hard link inside a root shares content with a
#     file outside it. Creating one needs write access to the root already, so this
#     does not widen the reach of a non-elevated caller that only holds the queue
#     directory, but it is not defended against.
#   - Comparisons are ordinal-ignore-case. Windows paths are case-insensitive, so
#     this is the correct predicate; it does mean the guard accepts a differently
#     cased spelling of an allowed path, which Windows then resolves to the same file.

Set-StrictMode -Version Latest

function Get-GuardComparer {
    return [System.StringComparison]::OrdinalIgnoreCase
}

# Canonicalise caller input. Returns the absolute path; throws on anything that
# cannot be reduced to one.
function Get-CanonicalPath {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'PATH_EMPTY' }
    if ($Path.IndexOf([char]0) -ge 0) { throw 'PATH_HAS_NUL_CHARACTER' }

    $trimmed = $Path.Trim()
    if ($trimmed.Length -eq 0) { throw 'PATH_EMPTY_AFTER_TRIM' }

    $full = [System.IO.Path]::GetFullPath($trimmed)
    if (-not [System.IO.Path]::IsPathRooted($full)) { throw 'PATH_NOT_ABSOLUTE' }
    return $full
}

# True when $FullPath is $Root itself or a descendant of it, on a separator boundary.
# Both arguments must already be canonical.
function Test-PathUnderRoot {
    param(
        [Parameter(Mandatory)][string]$FullPath,
        [Parameter(Mandatory)][string]$Root
    )

    $rootTrim = $Root.TrimEnd('\')
    $cmp = Get-GuardComparer

    if ($FullPath.Length -eq $rootTrim.Length) {
        return [string]::Equals($FullPath, $rootTrim, $cmp)
    }
    if ($FullPath.Length -lt $rootTrim.Length) { return $false }
    if (-not [string]::Equals($FullPath.Substring(0, $rootTrim.Length), $rootTrim, $cmp)) {
        return $false
    }
    return $FullPath[$rootTrim.Length] -eq '\'
}

# Walk from the root down to the deepest component of $FullPath that exists, and
# refuse if any of those components is a reparse point. Components that do not
# exist yet are fine -- a caller cannot pre-create a junction with no write access.
function Assert-NoReparseInChain {
    param(
        [Parameter(Mandatory)][string]$FullPath,
        [Parameter(Mandatory)][string]$Root
    )

    $rootTrim = $Root.TrimEnd('\')
    $reparseFlag = [System.IO.FileAttributes]::ReparsePoint

    $chain = New-Object System.Collections.Generic.List[string]
    $chain.Add($rootTrim)
    if ($FullPath.Length -gt $rootTrim.Length) {
        $rel = $FullPath.Substring($rootTrim.Length).TrimStart('\')
        if ($rel.Length -gt 0) {
            $current = $rootTrim
            foreach ($part in ($rel -split '\\')) {
                if ($part.Length -eq 0) { continue }
                $current = Join-Path $current $part
                $chain.Add($current)
            }
        }
    }

    foreach ($candidate in $chain) {
        if (-not (Test-Path -LiteralPath $candidate -ErrorAction SilentlyContinue)) { break }
        $item = Get-Item -LiteralPath $candidate -Force -ErrorAction Stop
        if ($item.Attributes -band $reparseFlag) {
            throw ('REPARSE_POINT_IN_PATH:' + $candidate)
        }
    }
}

# Resolve a canonical path against the configured roots.
# $Roots is an array of PSCustomObject with .name .path .read .write
# Returns @{ Root = <root object>; Canonical = <string> }
function Resolve-GuardedPath {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Path,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Roots,
        [ValidateSet('read', 'write')][string]$Access = 'read'
    )

    $canonical = Get-CanonicalPath -Path $Path

    $matches = @()
    foreach ($root in $Roots) {
        if ($null -eq $root) { continue }
        if (Test-PathUnderRoot -FullPath $canonical -Root $root.path) { $matches += $root }
    }
    if ($matches.Count -eq 0) { throw ('PATH_OUTSIDE_ALLOWED_ROOTS:' + $canonical) }

    # Longest root wins, so a nested writable root can sit inside a read-only one.
    $chosen = $matches | Sort-Object -Property @{ Expression = { $_.path.Length } } -Descending | Select-Object -First 1

    $allowed = if ($Access -eq 'write') { $chosen.write } else { $chosen.read }
    if (-not $allowed) { throw ('ACCESS_DENIED_BY_ROOT:' + $chosen.name + ':' + $Access) }

    Assert-NoReparseInChain -FullPath $canonical -Root $chosen.path

    return [pscustomobject]@{ Root = $chosen; Canonical = $canonical }
}

# Load and canonicalise the allow-list. Read once, at helper startup.
# Reads as explicit UTF-8 rather than via Get-Content: the game data root contains
# non-ASCII path components and Windows PowerShell 5.1 would decode a BOM-less
# UTF-8 file as ANSI, silently mangling them into a root that never matches.
function Import-ElevatedConfig {
    param([Parameter(Mandatory)][string]$ConfigPath)

    if (-not (Test-Path -LiteralPath $ConfigPath)) { throw ('CONFIG_NOT_FOUND:' + $ConfigPath) }
    $text = [System.IO.File]::ReadAllText($ConfigPath, (New-Object System.Text.UTF8Encoding($false)))
    $parsed = $text | ConvertFrom-Json

    $projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
    $roots = @()
    foreach ($entry in $parsed.roots) {
        $raw = [string]$entry.path
        $raw = $raw.Replace('%USERPROFILE%', $env:USERPROFILE).Replace('%PROJECT_ROOT%', $projectRoot)
        $canonical = Get-CanonicalPath -Path $raw
        if (-not (Test-Path -LiteralPath $canonical)) { throw ('ROOT_DOES_NOT_EXIST:' + $entry.name + ':' + $canonical) }
        $roots += [pscustomobject]@{
            name  = [string]$entry.name
            path  = $canonical
            read  = [bool]$entry.read
            write = [bool]$entry.write
        }
    }
    if ($roots.Count -eq 0) { throw 'CONFIG_HAS_NO_ROOTS' }
    return $roots
}

# Refuse to remove a configured root, even if some root happened to grant write.
function Assert-NotARoot {
    param(
        [Parameter(Mandatory)][string]$Canonical,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Roots
    )
    foreach ($root in $Roots) {
        if ($null -eq $root) { continue }
        if ([string]::Equals($Canonical.TrimEnd('\'), $root.path.TrimEnd('\'), (Get-GuardComparer))) {
            throw ('REFUSE_TO_REMOVE_ROOT:' + $root.name)
        }
    }
}
