# Synthetic refusal regression for tools/authoring/graph-transport.ps1.
#
# Every external fact is fabricated here: Get-Process, Get-FileHash and Test-Path are
# shadowed by mocks backed by one fixture object, so no real process is looked up, no
# game/editor DLL is hashed and no named pipe is opened. The request file is
# deliberately absent and doubles as a sentinel: if the guard let a case reach the
# request step, graph-transport.ps1 would fail while READING it, and the recorded
# stage would read 'request' instead of the expected refusal stage.
#
# Import the Windows PowerShell modules BEFORE installing the doubles. Utility
# exports Get-FileHash as a function; its first automatic import (e.g. by
# ConvertTo-Json) otherwise replaces a previously installed mock. The test checks
# command identity before every child-script invocation as well as call counts.
# One global fixture object carries mock state across nested script scopes and is
# removed on completion. Advanced doubles accept the real cmdlets' common arguments.
#
# The intentionally rejected child script leaves $LASTEXITCODE=2, which a parent shell
# could wrongly inherit, so success is set explicitly after cleanup. Output is
# structured and sanitized: case name, expected/observed stage and code, hash-consult
# counter and outcomeUncertain only. Settings, nonce, pipe name and paths are never
# echoed.
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Management/Microsoft.PowerShell.Management.psd1') -ErrorAction Stop
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$entry = Join-Path $projectRoot 'tools/authoring/graph-transport.ps1'

$editorExe = 'C:\Games\Genshin Impact Game\BeyondAssets\BeyondAssistEditor\BeyondEditor.exe'
$editorDll = Join-Path (Split-Path -Parent $editorExe) 'BeyondEditor.dll'
$unsupportedSha = 'F' * 64

$global:MiliastraTransportFixture = @{
    Entry           = $entry
    EditorDll       = $editorDll
    SettingsPath    = $null
    MissingRequest  = $null
    Image           = $editorExe
    StartTime       = [DateTime]::SpecifyKind([DateTime]::new(2026, 1, 1), [DateTimeKind]::Utc)
    UnreadableImage = $false
    DllExists       = $true
    Hash            = $unsupportedSha
    LeaseClosed     = $false
    HashCalls       = 0
}

function Get-Process {
    [CmdletBinding()]
    param([int]$Id)
    $state = $global:MiliastraTransportFixture
    $proc = [pscustomobject]@{ ProcessName = 'BeyondEditor'; StartTime = $state.StartTime }
    if ($state.UnreadableImage) {
        $proc | Add-Member -MemberType ScriptProperty -Name MainModule `
            -Value { throw [System.UnauthorizedAccessException]::new('synthetic-image-unreadable') }
    } else {
        $proc | Add-Member -MemberType NoteProperty -Name MainModule `
            -Value ([pscustomobject]@{ FileName = $state.Image })
    }
    return $proc
}

function Get-FileHash {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$Algorithm)
    $global:MiliastraTransportFixture.HashCalls++
    return [pscustomobject]@{ Hash = $global:MiliastraTransportFixture.Hash }
}

function Test-Path {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$PathType)
    $state = $global:MiliastraTransportFixture
    if ($LiteralPath -ieq $state.EditorDll) { return [bool]$state.DllExists }
    if ($LiteralPath -like '*lease-closed.json') { return [bool]$state.LeaseClosed }
    return Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath
}

function Write-Scope {
    param([Parameter(Mandatory = $false)][hashtable]$Override)
    $scope = [ordered]@{
        pid           = 4242
        startUtcTicks = [string]$global:MiliastraTransportFixture.StartTime.Ticks
        expiresUtc    = [DateTimeOffset]::UtcNow.AddMinutes(2).ToString('o')
        expectedExe   = $editorExe
        pipeName      = 'MUST-NOT-CONNECT'
        nonce         = 'SYNTHETIC'
    }
    if ($Override) {
        foreach ($key in @($Override.Keys)) { $scope[$key] = $Override[$key] }
    }
    [IO.File]::WriteAllText($global:MiliastraTransportFixture.SettingsPath,
        ($scope | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}

function Invoke-Transport {
    param(
        [Parameter(Mandatory = $true)][string]$SettingsPath,
        [Parameter(Mandatory = $true)][string]$RequestPath
    )
    foreach ($mockName in @('Get-Process', 'Get-FileHash', 'Test-Path')) {
        $mock = Get-Command $mockName
        if ($mock.CommandType -ne 'Function' -or $mock.ModuleName -or
            $mock.Definition -notmatch 'MiliastraTransportFixture') {
            throw ('SYNTHETIC_MOCK_NOT_ACTIVE:' + $mockName)
        }
    }
    $raw = & $global:MiliastraTransportFixture.Entry -SettingsPath $SettingsPath -RequestPath $RequestPath
    return (($raw -join [Environment]::NewLine) | ConvertFrom-Json)
}

function Invoke-Case {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $false)][hashtable]$Override,
        [Parameter(Mandatory = $false)][string]$ObservedImage,
        [Parameter(Mandatory = $false)][switch]$UnreadableImage,
        [Parameter(Mandatory = $false)][switch]$LeaseClosed,
        [Parameter(Mandatory = $true)][string]$ExpectedStage,
        [Parameter(Mandatory = $true)][string]$ExpectedCode,
        [Parameter(Mandatory = $true)][int]$ExpectedHashCalls
    )
    $state = $global:MiliastraTransportFixture
    if (-not $ObservedImage) { $ObservedImage = $editorExe }
    $state.Image           = $ObservedImage
    $state.UnreadableImage = [bool]$UnreadableImage
    $state.LeaseClosed     = [bool]$LeaseClosed
    $state.DllExists       = $true
    $state.Hash            = $unsupportedSha
    $state.HashCalls       = 0
    Write-Scope -Override $Override

    $payload = $null
    $parsed = $false
    try {
        $payload = Invoke-Transport -SettingsPath $state.SettingsPath -RequestPath $state.MissingRequest
        $parsed = $true
    } catch {
        $parsed = $false
    }

    $stage = ''
    $code = ''
    $uncertain = $false
    if ($parsed -and ($null -ne $payload)) {
        $stage = [string]$payload.stage
        $code = [string]$payload.code
        $uncertain = [bool]$payload.outcomeUncertain
    }

    $pass = $parsed -and ($null -ne $payload) -and
            ($payload.ok -eq $false) -and
            ($stage -ceq $ExpectedStage) -and
            ($code -ceq $ExpectedCode) -and
            (-not $uncertain) -and
            ([int]$state.HashCalls -eq $ExpectedHashCalls) -and
            (@('request', 'connect', 'send') -notcontains $stage)

    [void]$script:results.Add([ordered]@{
        case             = $Name
        pass             = [bool]$pass
        expectedStage    = $ExpectedStage
        stage            = $stage
        expectedCode     = $ExpectedCode
        code             = $code
        hashCalls        = [int]$state.HashCalls
        outcomeUncertain = $uncertain
    })
}

$script:results = New-Object System.Collections.ArrayList
$script:harnessError = $null
$script:sentinelAbsent = $false

$testDir = Join-Path ([IO.Path]::GetTempPath()) ('miliastra-transport-guard-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testDir) | Out-Null
$global:MiliastraTransportFixture.SettingsPath = Join-Path $testDir 'settings.json'
$global:MiliastraTransportFixture.MissingRequest = Join-Path $testDir 'missing-request.json'

try {
    # 1. Unknown editor DLL: observed editor identity is accepted, but the disk assembly
    #    hash is unsupported. Must refuse as incompatible-version at the compatibility
    #    stage after exactly one hash consult, before the request is read and before any
    #    NamedPipe object exists.
    Invoke-Case -Name 'unknown-editor-dll-refused-before-request' `
        -ExpectedStage 'compatibility' -ExpectedCode 'incompatible-version' -ExpectedHashCalls 1

    # 2. Observed process image differs from the leased expectedExe: identity refusal,
    #    no hash consult.
    Invoke-Case -Name 'observed-image-mismatch-refused' `
        -ObservedImage 'D:\unrelated\BeyondEditor.exe' `
        -ExpectedStage 'identity' -ExpectedCode 'BRIDGE_TRANSPORT_FAILED' -ExpectedHashCalls 0

    # 3. Observed start ticks differ from the leased ticks: identity refusal, no hash.
    $laterTicks = [string]([long]$global:MiliastraTransportFixture.StartTime.Ticks + 1)
    Invoke-Case -Name 'start-ticks-mismatch-refused' -Override @{ startUtcTicks = $laterTicks } `
        -ExpectedStage 'identity' -ExpectedCode 'BRIDGE_TRANSPORT_FAILED' -ExpectedHashCalls 0

    # 4. Expired lease: refused at the scope stage, before identity or compatibility.
    $past = [DateTimeOffset]::UtcNow.AddMinutes(-1).ToString('o')
    Invoke-Case -Name 'expired-lease-refused' -Override @{ expiresUtc = $past } `
        -ExpectedStage 'scope' -ExpectedCode 'BRIDGE_TRANSPORT_FAILED' -ExpectedHashCalls 0

    # 5. Closed lease marker present: refused at the scope stage, before compatibility.
    Invoke-Case -Name 'closed-lease-refused' -LeaseClosed `
        -ExpectedStage 'scope' -ExpectedCode 'BRIDGE_TRANSPORT_FAILED' -ExpectedHashCalls 0

    # 6. Process image unreadable: fail closed at identity, no hash consult, no pipe.
    Invoke-Case -Name 'unreadable-image-fails-closed' -UnreadableImage `
        -ExpectedStage 'identity' -ExpectedCode 'BRIDGE_TRANSPORT_FAILED' -ExpectedHashCalls 0

    # The sentinel request must still not exist: every case refused before reading it.
    $script:sentinelAbsent = -not (Microsoft.PowerShell.Management\Test-Path `
        -LiteralPath $global:MiliastraTransportFixture.MissingRequest)
} catch {
    # Sanitize: a harness failure is reported by exception type only, never its message.
    $script:harnessError = $_.Exception.GetType().Name
} finally {
    $resolved = [IO.Path]::GetFullPath($testDir)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'test cleanup outside temp' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

$passed = @($script:results | Where-Object { $_.pass }).Count
$total = 6
$allPass = ($null -eq $script:harnessError) -and ($script:results.Count -eq $total) -and
           ($passed -eq $total) -and $script:sentinelAbsent

[ordered]@{
    ok                    = [bool]$allPass
    passed                = [int]$passed
    total                 = $total
    cases                 = @($script:results)
    harnessError          = $script:harnessError
    sentinelRequestAbsent = [bool]$script:sentinelAbsent
    realProcessLookup     = $false
    realDllRead           = $false
    pipeConnected         = $false
} | ConvertTo-Json -Compress -Depth 6

Remove-Variable -Name MiliastraTransportFixture -Scope Global -ErrorAction SilentlyContinue

if ($allPass) { exit 0 } else { exit 1 }
