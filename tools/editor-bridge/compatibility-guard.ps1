# Offline compatibility gate for the editor bridge.
#
# WHY THIS EXISTS
# The bridge reflects into the loaded BeyondEditor assembly; this gate checks its disk build. The 2026-09-24 game
# update replaced that file: the obfuscated core type/field names the whole Adapter
# depends on are simply gone from the new binary. Loading the bridge into the updated
# editor therefore does not fail loudly -- it resolves nothing and, in the old
# VerifyChannels, reported success on zero invocations. This guard makes the version
# boundary explicit and checked BEFORE any scope artifact is created or any injector
# is launched.
#
# WHAT IT KNOWS
# Exactly one supported fingerprint: the 7.1 ported BeyondEditor.dll, at the exact
# editor install path. Everything else is refused. There is deliberately no parameter
# that accepts a caller-supplied hash and no bypass switch: the only inputs are the
# process identity the caller already observed. Tests exercise it by replacing the
# file-reading cmdlets (Get-FileHash / Test-Path) or by passing fabricated process
# info, not by relaxing the gate.
#
# WHAT IT DOES NOT DO
# It only reads files (Get-FileHash / Test-Path). It never starts the game, the
# editor, an injector or a process; it never writes, moves or deletes anything.
#
# Dot-source this file; its functions then live in the caller's scope.

$script:MiliastraCompatibility = @{
    # The one adapted editor assembly this project's reflection mappings were built
    # against. 7.1 static mapping and 256 metadata contracts independently validated;
    # the loaded module MVID and signatures are also checked by EditorBindingProfile.
    SupportedEditorDllSha256 = '565DDA11883F0220BAE050438FCF52B2288F26B61ED656E2B4CD6D69B41A678A'
    # The editor executable the Adapter was verified against. Pinned as a full literal
    # path, not derived from any caller input, so a relocated copy is refused.
    EditorExePath            = 'C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.exe'
    EditorDllName            = 'BeyondEditor.dll'
    # Project-owned test double. Not an editor build, so the editor DLL gate cannot
    # apply to it; its identity is still pinned to this exact path.
    TestHostRelativePath     = 'tools/editor-bridge/TestHost/bin/Release/net8.0-windows/TestHost.exe'
    AllowedProcessNames      = @('TestHost', 'BeyondEditor')
    ErrorDllMissing          = 'EDITOR_DLL_MISSING'
    ErrorVersionUnsupported  = 'EDITOR_VERSION_UNSUPPORTED'
}

function Get-MiliastraCompatibilityPolicy {
    # A copy, so a caller cannot mutate the policy through the returned object.
    [ordered]@{
        supportedEditorDllSha256 = $script:MiliastraCompatibility.SupportedEditorDllSha256
        editorExePath            = $script:MiliastraCompatibility.EditorExePath
        editorDllPath            = (Get-MiliastraEditorDllPath)
        allowedProcessNames      = @($script:MiliastraCompatibility.AllowedProcessNames)
    }
}

# Windows PowerShell 5.1 has no [IO.Path]::IsPathFullyQualified, so this project keeps
# its own: rooted AND carrying a drive-qualified prefix, which excludes "C:foo".
function Test-MiliastraFullyQualifiedPath {
    param([Parameter(Mandatory=$false)][AllowEmptyString()][string]$LiteralPath)
    if ([string]::IsNullOrWhiteSpace($LiteralPath)) { return $false }
    if (-not [IO.Path]::IsPathRooted($LiteralPath)) { return $false }
    return ($LiteralPath.Length -ge 3 -and $LiteralPath[1] -eq ':' -and
            ($LiteralPath[2] -eq '\' -or $LiteralPath[2] -eq '/'))
}

function Get-MiliastraEditorDllPath {
    $exe = $script:MiliastraCompatibility.EditorExePath
    return (Join-Path (Split-Path -Parent $exe) ($script:MiliastraCompatibility.EditorDllName))
}

function Get-MiliastraTestHostPath {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    return [IO.Path]::GetFullPath((Join-Path $ProjectRoot $script:MiliastraCompatibility.TestHostRelativePath))
}

# The single place this project reads a file hash. Kept as its own thin function so
# the offline tests can substitute it and so no hash is ever parsed inline.
function Get-MiliastraFileSha256 {
    param([Parameter(Mandatory=$true)][string]$LiteralPath)
    if ([string]::IsNullOrWhiteSpace($LiteralPath)) { throw 'HASH_PATH_EMPTY' }
    $hash = (Get-FileHash -LiteralPath $LiteralPath -Algorithm SHA256).Hash
    if ([string]::IsNullOrWhiteSpace($hash)) { throw ('HASH_UNREADABLE:' + $LiteralPath) }
    return $hash.ToUpperInvariant()
}

# Identity of the target process, as the caller observed it. Name/path/ticks only:
# nothing here touches the process or the game.
function Assert-MiliastraTargetIdentity {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$ProcessName,
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$ImagePath,
        [Parameter(Mandatory=$false)][long]$StartUtcTicks = 0
    )
    if ($script:MiliastraCompatibility.AllowedProcessNames -notcontains $ProcessName) {
        throw ('TARGET_NOT_ALLOWED:process-name:' + $ProcessName)
    }
    if (-not (Test-MiliastraFullyQualifiedPath -LiteralPath $ImagePath)) {
        throw 'TARGET_IMAGE_MISSING'
    }
    if ($ProcessName -eq 'BeyondEditor') {
        $expected = $script:MiliastraCompatibility.EditorExePath
    } else {
        $expected = Get-MiliastraTestHostPath -ProjectRoot $ProjectRoot
    }
    if ($ImagePath -ine $expected) { throw ('TARGET_NOT_ALLOWED:image-path:' + $ImagePath) }
    if ($StartUtcTicks -le 0) { throw 'START_TICKS_MISSING' }
    return $expected
}

# The gate itself. Returns a pin describing what was verified, or throws. For the game
# editor the pin is only produced when the disk assembly is the one supported hash;
# an unknown or missing assembly is refused here, before the caller has created any
# run directory or touched an injector.
function Get-MiliastraCompatibilityPin {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$ProcessName,
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$ImagePath,
        [Parameter(Mandatory=$false)][long]$StartUtcTicks = 0
    )
    $expected = Assert-MiliastraTargetIdentity -ProjectRoot $ProjectRoot -ProcessName $ProcessName `
        -ImagePath $ImagePath -StartUtcTicks $StartUtcTicks

    $pin = [ordered]@{
        kind                 = $ProcessName
        imagePath            = $ImagePath
        expectedImagePath    = $expected
        startUtcTicks        = [string]$StartUtcTicks
        supportedDllSha256   = $script:MiliastraCompatibility.SupportedEditorDllSha256
        dllPath              = $null
        dllSha256            = $null
        editorDllGateApplied = $false
        verdict              = 'testhost-compatibility-gate-not-applicable'
        checkedUtc           = [DateTimeOffset]::UtcNow.ToString('o')
    }

    if ($ProcessName -eq 'TestHost') {
        # Project-owned test double, pinned to its exact path above. It does not load
        # the editor assembly, so applying the editor DLL gate to it would block the
        # only offline target this project has.
        return $pin
    }

    $dllPath = Get-MiliastraEditorDllPath
    $pin['editorDllGateApplied'] = $true
    $pin['dllPath'] = $dllPath
    if (-not (Test-Path -LiteralPath $dllPath -PathType Leaf)) {
        throw ($script:MiliastraCompatibility.ErrorDllMissing + ':' + $dllPath)
    }
    $actual = Get-MiliastraFileSha256 -LiteralPath $dllPath
    $pin['dllSha256'] = $actual
    if ($actual -ne $script:MiliastraCompatibility.SupportedEditorDllSha256) {
        throw ($script:MiliastraCompatibility.ErrorVersionUnsupported + ':disk=' + $actual +
               ':supported=' + $script:MiliastraCompatibility.SupportedEditorDllSha256)
    }
    $pin['verdict'] = 'editor-assembly-supported'
    return $pin
}

# Re-check for the load step: the editor may have been updated (or the file swapped)
# between scope creation and injection. Re-reads the disk assembly and compares it to
# both the supported hash and the hash pinned at scope time.
function Assert-MiliastraCompatibilityPin {
    param(
        [Parameter(Mandatory=$true)]$Pin,
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [Parameter(Mandatory=$true)][string]$ProcessName,
        [Parameter(Mandatory=$true)][string]$ImagePath,
        [Parameter(Mandatory=$true)][long]$StartUtcTicks
    )
    $current = Get-MiliastraCompatibilityPin -ProjectRoot $ProjectRoot -ProcessName $ProcessName -ImagePath $ImagePath -StartUtcTicks $StartUtcTicks
    if ($Pin.kind -ne $current.kind -or $Pin.imagePath -ine $current.imagePath -or
        [string]$Pin.startUtcTicks -ne [string]$current.startUtcTicks -or
        $Pin.dllPath -ine $current.dllPath -or $Pin.dllSha256 -ine $current.dllSha256) {
        throw 'COMPATIBILITY_PIN_INVALID:identity-or-build-mismatch'
    }
    if ($null -eq $Pin) { throw 'COMPATIBILITY_PIN_INVALID:missing' }
    if ([string]::IsNullOrWhiteSpace([string]$Pin.kind)) { throw 'COMPATIBILITY_PIN_INVALID:kind' }
    if ([string]::IsNullOrWhiteSpace([string]$Pin.imagePath)) { throw 'COMPATIBILITY_PIN_INVALID:imagePath' }
    if ([string]::IsNullOrWhiteSpace([string]$Pin.startUtcTicks)) { throw 'COMPATIBILITY_PIN_INVALID:startUtcTicks' }

    if ($Pin.kind -eq 'TestHost') {
        if ($Pin.editorDllGateApplied -eq $true) { throw 'COMPATIBILITY_PIN_INVALID:testhost-gate' }
        if ($Pin.imagePath -notlike '*\TestHost.exe') { throw 'COMPATIBILITY_PIN_INVALID:testhost-image' }
        return [ordered]@{ ok = $true; kind = 'TestHost'; check = 'editor-dll-gate-not-applicable'; dllSha256 = $null }
    }

    if ($Pin.editorDllGateApplied -ne $true) { throw 'COMPATIBILITY_PIN_INVALID:editor-gate-skipped' }
    if ([string]::IsNullOrWhiteSpace([string]$Pin.dllPath)) { throw 'COMPATIBILITY_PIN_INVALID:dllPath' }
    if ([string]::IsNullOrWhiteSpace([string]$Pin.dllSha256)) { throw 'COMPATIBILITY_PIN_INVALID:dllSha256' }
    if (-not (Test-Path -LiteralPath ([string]$Pin.dllPath) -PathType Leaf)) {
        throw ($script:MiliastraCompatibility.ErrorDllMissing + ':' + [string]$Pin.dllPath)
    }
    $actual = Get-MiliastraFileSha256 -LiteralPath ([string]$Pin.dllPath)
    if ($actual -ne ([string]$Pin.dllSha256)) {
        throw ($script:MiliastraCompatibility.ErrorVersionUnsupported +
               ':editor-changed-since-scope:disk=' + $actual + ':pinned=' + [string]$Pin.dllSha256)
    }
    if ($actual -ne $script:MiliastraCompatibility.SupportedEditorDllSha256) {
        throw ($script:MiliastraCompatibility.ErrorVersionUnsupported + ':disk=' + $actual)
    }
    return [ordered]@{ ok = $true; kind = 'BeyondEditor'; check = 'editor-assembly-supported'; dllSha256 = $actual }
}
