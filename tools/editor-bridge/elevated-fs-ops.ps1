# elevated-fs-ops.ps1 -- the file operations the resident elevated helper serves.
#
# Kept apart from elevated-runner.ps1 so that everything except the elevation
# wrapper itself can be exercised unelevated. The runner dot-sources this file and
# passes its own resolved roots in; nothing here reads global state.
#
# Every path -- source AND destination -- goes through Resolve-GuardedPath in
# elevated-fs-guard.ps1. Ops that destroy or relocate data additionally require the
# request to repeat the target path in a "confirm" field: not a permission check
# (the guard already did that) but a transcription check, so a truncated or
# hand-edited request fails instead of removing a path nobody actually named.

Set-StrictMode -Version Latest

# ConvertFrom-Json imposes no schema, so every field read has to tolerate absence.
function Get-JsonField {
    param($Object, [Parameter(Mandatory)][string]$Name, $Default)
    if ($null -eq $Object) { return $Default }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) { return $Default }
    return $prop.Value
}

function Assert-ConfirmMatches {
    param($Body, [Parameter(Mandatory)][AllowEmptyString()][string]$RawPath, [Parameter(Mandatory)][string]$Op)
    $confirm = [string](Get-JsonField $Body 'confirm' '')
    if ([string]::IsNullOrWhiteSpace($confirm)) { throw ('CONFIRM_REQUIRED_FOR_' + $Op.ToUpperInvariant()) }
    if (-not [string]::Equals($confirm, $RawPath, [System.StringComparison]::Ordinal)) {
        throw ('CONFIRM_DOES_NOT_MATCH_TARGET:' + $Op)
    }
}

function Get-Sha256Lower {
    param([Parameter(Mandatory)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# Independent of the configured allow-list: a permissive custom root must not
# turn this general file helper into a formal-save writer. Reads and project
# backups remain available; only the explicit export subtree is outside saves.
function Resolve-FormalSafeWritePath {
    param(
        [Parameter(Mandatory)][AllowEmptyString()][string]$Path,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Roots
    )
    $canonical = Get-CanonicalPath -Path $Path
    # These spellings can alias normal paths while defeating component matching.
    # Generic mutation requests fail closed instead of attempting to interpret them.
    if ($canonical -match '^\\\\[?.]\\' -or $canonical -match '~[0-9]' -or $canonical -match '[. ](?:\\|$)' -or
        $canonical.Substring([Math]::Min(2, $canonical.Length)).Contains(':')) {
        throw ('FORMAL_SAVE_PATH_ALIAS_UNSUPPORTED:' + $canonical)
    }
    $g = Resolve-GuardedPath -Path $canonical -Roots $Roots -Access write
    $anchors = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $anchors.Add((Get-CanonicalPath -Path (Join-Path $env:USERPROFILE 'AppData/LocalLow/miHoYo')))
    }
    foreach ($entry in $Roots) {
        if ($null -ne $entry -and $entry.name -eq 'game-data-locallow') {
            $anchors.Add((Get-CanonicalPath -Path $entry.path))
        }
    }
    # Also recognize another user's standard data path, independent of root names.
    if ($canonical -match '^(?<data>.+\\AppData\\LocalLow\\miHoYo)(?:\\|$)') {
        $anchors.Add($Matches.data)
    }
    foreach ($anchor in $anchors) {
        if (Test-PathUnderRoot -FullPath $anchor -Root $canonical) {
            throw ('FORMAL_SAVE_MUTATION_FORBIDDEN:' + $canonical)
        }
        if (-not (Test-PathUnderRoot -FullPath $canonical -Root $anchor)) { continue }
        $relative = $canonical.Substring($anchor.TrimEnd('\').Length).TrimStart('\')
        $parts = @($relative -split '\\')
        # A locale/game folder is an ancestor of its BeyondLocal save tree.
        if ($parts.Count -le 1) { throw ('FORMAL_SAVE_MUTATION_FORBIDDEN:' + $canonical) }
        if ($parts[1] -ine 'BeyondLocal') { continue }
        if ($parts.Count -ge 3 -and $parts[2] -ieq 'Beyond_Local_Export') { continue }
        throw ('FORMAL_SAVE_MUTATION_FORBIDDEN:' + $canonical)
    }
    return $g
}

function Invoke-FsRequest {
    param(
        [Parameter(Mandatory)]$Request,
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Roots,
        [Parameter(Mandatory)][string]$BackupsRoot,
        [long]$MaxPayloadBytes = 8MB
    )

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    $op = [string](Get-JsonField $Request 'op' '')
    $allowed = @('stat', 'list', 'read', 'write', 'mkdir', 'copy', 'move', 'delete', 'hash', 'snapshot')
    if ($allowed -notcontains $op) { throw ('FS_OP_NOT_ALLOWED:' + $op) }

    $rawPath = [string](Get-JsonField $Request 'path' '')
    $rawDest = [string](Get-JsonField $Request 'dest' '')

    switch ($op) {
        'stat' {
            $g = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            if (-not (Test-Path -LiteralPath $g.Canonical)) {
                return @{ op = 'stat'; exists = $false; path = $g.Canonical; root = $g.Root.name }
            }
            $item = Get-Item -LiteralPath $g.Canonical -Force
            $isDir = [bool]$item.PSIsContainer
            return @{
                op = 'stat'; exists = $true; path = $g.Canonical; root = $g.Root.name
                isContainer = $isDir
                length = $(if ($isDir) { $null } else { $item.Length })
                lastWriteUtc = $item.LastWriteTimeUtc.ToString('o')
                attributes = $item.Attributes.ToString()
            }
        }

        'list' {
            $g = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            if (-not (Test-Path -LiteralPath $g.Canonical)) { throw ('PATH_NOT_FOUND:' + $g.Canonical) }
            $max = [int](Get-JsonField $Request 'max' 1000)
            if ($max -le 0 -or $max -gt 20000) { throw ('BAD_MAX:' + $max) }
            $entries = @()
            $truncated = $false
            foreach ($item in (Get-ChildItem -LiteralPath $g.Canonical -Force | Sort-Object Name)) {
                if ($entries.Count -ge $max) { $truncated = $true; break }
                $isDir = [bool]$item.PSIsContainer
                $entries += @{
                    name = $item.Name
                    isContainer = $isDir
                    length = $(if ($isDir) { $null } else { $item.Length })
                    lastWriteUtc = $item.LastWriteTimeUtc.ToString('o')
                    reparse = [bool]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
                }
            }
            return @{ op = 'list'; path = $g.Canonical; root = $g.Root.name;
                      count = $entries.Count; truncated = $truncated; entries = $entries }
        }

        'read' {
            $g = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            if (-not (Test-Path -LiteralPath $g.Canonical)) { throw ('PATH_NOT_FOUND:' + $g.Canonical) }
            $info = Get-Item -LiteralPath $g.Canonical -Force
            if ($info.PSIsContainer) { throw 'READ_ON_DIRECTORY' }
            $encoding = [string](Get-JsonField $Request 'encoding' 'base64')
            $digest = Get-Sha256Lower -Path $g.Canonical
            if ($encoding -eq 'base64') {
                if ($info.Length -gt $MaxPayloadBytes) { throw ('FILE_TOO_LARGE:' + $info.Length) }
                $bytes = [System.IO.File]::ReadAllBytes($g.Canonical)
                return @{ op = 'read'; path = $g.Canonical; root = $g.Root.name; encoding = 'base64';
                          length = $bytes.Length; sha256 = $digest; data = [Convert]::ToBase64String($bytes) }
            }
            if ($encoding -eq 'utf8') {
                if ($info.Length -gt $MaxPayloadBytes) { throw ('FILE_TOO_LARGE:' + $info.Length) }
                return @{ op = 'read'; path = $g.Canonical; root = $g.Root.name; encoding = 'utf8';
                          length = $info.Length; sha256 = $digest;
                          data = [System.IO.File]::ReadAllText($g.Canonical, $utf8NoBom) }
            }
            throw ('UNSUPPORTED_ENCODING:' + $encoding)
        }

        'write' {
            $g = Resolve-FormalSafeWritePath -Path $rawPath -Roots $Roots
            $encoding = [string](Get-JsonField $Request 'encoding' 'base64')
            $data = [string](Get-JsonField $Request 'data' '')
            $bytes = if ($encoding -eq 'base64') { [Convert]::FromBase64String($data) }
                     elseif ($encoding -eq 'utf8') { $utf8NoBom.GetBytes($data) }
                     else { throw ('UNSUPPORTED_ENCODING:' + $encoding) }
            if ($bytes.Length -gt $MaxPayloadBytes) { throw ('PAYLOAD_TOO_LARGE:' + $bytes.Length) }
            if ([bool](Get-JsonField $Request 'createParents' $true)) {
                $parent = [System.IO.Path]::GetDirectoryName($g.Canonical)
                if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                    $null = Resolve-FormalSafeWritePath -Path $parent -Roots $Roots
                    New-Item -ItemType Directory -Force -Path $parent | Out-Null
                }
            }
            [System.IO.File]::WriteAllBytes($g.Canonical, $bytes)
            return @{ op = 'write'; path = $g.Canonical; root = $g.Root.name;
                      bytes = $bytes.Length; sha256 = (Get-Sha256Lower -Path $g.Canonical) }
        }

        'mkdir' {
            $g = Resolve-FormalSafeWritePath -Path $rawPath -Roots $Roots
            if (Test-Path -LiteralPath $g.Canonical) {
                if (-not (Get-Item -LiteralPath $g.Canonical -Force).PSIsContainer) { throw 'PATH_IS_A_FILE' }
                return @{ op = 'mkdir'; path = $g.Canonical; root = $g.Root.name; created = $false }
            }
            New-Item -ItemType Directory -Force -Path $g.Canonical | Out-Null
            return @{ op = 'mkdir'; path = $g.Canonical; root = $g.Root.name; created = $true }
        }

        'copy' {
            $src = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            $dst = Resolve-FormalSafeWritePath -Path $rawDest -Roots $Roots
            if (-not (Test-Path -LiteralPath $src.Canonical)) { throw ('PATH_NOT_FOUND:' + $src.Canonical) }
            $overwrite = [bool](Get-JsonField $Request 'overwrite' $false)
            if ((Test-Path -LiteralPath $dst.Canonical) -and -not $overwrite) { throw ('DEST_EXISTS:' + $dst.Canonical) }
            if ([bool](Get-JsonField $Request 'createParents' $true)) {
                $parent = [System.IO.Path]::GetDirectoryName($dst.Canonical)
                if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                    $null = Resolve-FormalSafeWritePath -Path $parent -Roots $Roots
                    New-Item -ItemType Directory -Force -Path $parent | Out-Null
                }
            }
            Copy-Item -LiteralPath $src.Canonical -Destination $dst.Canonical -Recurse -Force:$overwrite
            return @{ op = 'copy'; source = $src.Canonical; dest = $dst.Canonical;
                      root = $dst.Root.name; overwrite = $overwrite }
        }

        'move' {
            Assert-ConfirmMatches -Body $Request -RawPath $rawPath -Op 'move'
            $src = Resolve-FormalSafeWritePath -Path $rawPath -Roots $Roots
            $dst = Resolve-FormalSafeWritePath -Path $rawDest -Roots $Roots
            Assert-NotARoot -Canonical $src.Canonical -Roots $Roots
            if (-not (Test-Path -LiteralPath $src.Canonical)) { throw ('PATH_NOT_FOUND:' + $src.Canonical) }
            $overwrite = [bool](Get-JsonField $Request 'overwrite' $false)
            if ((Test-Path -LiteralPath $dst.Canonical) -and -not $overwrite) { throw ('DEST_EXISTS:' + $dst.Canonical) }
            $parent = [System.IO.Path]::GetDirectoryName($dst.Canonical)
            if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                $null = Resolve-FormalSafeWritePath -Path $parent -Roots $Roots
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            $crossVolume = $false
            try { Move-Item -LiteralPath $src.Canonical -Destination $dst.Canonical -Force:$overwrite }
            catch {
                # Move-Item cannot cross volumes. Fall back to copy-then-delete; both
                # halves have already been path-checked above.
                $crossVolume = $true
                Copy-Item -LiteralPath $src.Canonical -Destination $dst.Canonical -Recurse -Force
                Remove-Item -LiteralPath $src.Canonical -Recurse -Force
            }
            return @{ op = 'move'; source = $src.Canonical; dest = $dst.Canonical;
                      root = $dst.Root.name; crossVolumeFallback = $crossVolume }
        }

        'delete' {
            Assert-ConfirmMatches -Body $Request -RawPath $rawPath -Op 'delete'
            $g = Resolve-FormalSafeWritePath -Path $rawPath -Roots $Roots
            Assert-NotARoot -Canonical $g.Canonical -Roots $Roots
            if (-not (Test-Path -LiteralPath $g.Canonical)) {
                return @{ op = 'delete'; path = $g.Canonical; deleted = $false; reason = 'not found' }
            }
            $recurse = [bool](Get-JsonField $Request 'recurse' $false)
            if ((Get-Item -LiteralPath $g.Canonical -Force).PSIsContainer -and -not $recurse) {
                if (@(Get-ChildItem -LiteralPath $g.Canonical -Force).Count -gt 0) {
                    throw ('DIRECTORY_NOT_EMPTY_AND_RECURSE_NOT_SET:' + $g.Canonical)
                }
            }
            Remove-Item -LiteralPath $g.Canonical -Recurse:$recurse -Force
            return @{ op = 'delete'; path = $g.Canonical; root = $g.Root.name; deleted = $true; recurse = $recurse }
        }

        'hash' {
            $g = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            if (-not (Test-Path -LiteralPath $g.Canonical)) { throw ('PATH_NOT_FOUND:' + $g.Canonical) }
            $algorithm = ([string](Get-JsonField $Request 'algorithm' 'sha256')).ToUpperInvariant()
            if (@('SHA256', 'SHA1', 'MD5') -notcontains $algorithm) { throw ('UNSUPPORTED_ALGORITHM:' + $algorithm) }
            $info = Get-Item -LiteralPath $g.Canonical -Force
            $isDir = [bool]$info.PSIsContainer
            return @{ op = 'hash'; path = $g.Canonical; root = $g.Root.name; algorithm = $algorithm;
                      length = $(if ($isDir) { $null } else { $info.Length });
                      hash = (Get-FileHash -LiteralPath $g.Canonical -Algorithm $algorithm).Hash.ToLowerInvariant() }
        }

        'snapshot' {
            $src = Resolve-GuardedPath -Path $rawPath -Roots $Roots -Access read
            if (-not (Test-Path -LiteralPath $src.Canonical)) { throw ('PATH_NOT_FOUND:' + $src.Canonical) }
            $label = [string](Get-JsonField $Request 'label' 'snapshot')
            if ($label -notmatch '^[A-Za-z0-9._-]{1,64}$') { throw ('BAD_SNAPSHOT_LABEL:' + $label) }
            $null = Resolve-FormalSafeWritePath -Path $BackupsRoot -Roots $Roots
            New-Item -ItemType Directory -Force -Path $BackupsRoot | Out-Null
            $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
            $dst = Resolve-FormalSafeWritePath -Path (Join-Path $BackupsRoot ($stamp + '-' + $label)) -Roots $Roots
            Copy-Item -LiteralPath $src.Canonical -Destination $dst.Canonical -Recurse -Force
            $manifest = @{
                op = 'snapshot'; source = $src.Canonical; snapshot = $dst.Canonical
                label = $label; createdAtUtc = (Get-Date).ToUniversalTime().ToString('o')
            }
            $manifestPath = Join-Path $dst.Canonical 'snapshot-manifest.json'
            $null = Resolve-FormalSafeWritePath -Path $manifestPath -Roots $Roots
            [System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 4), $utf8NoBom)
            return $manifest
        }

        default { throw ('FS_OP_NOT_ALLOWED:' + $op) }
    }
}
