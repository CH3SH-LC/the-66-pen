# Synthetic regression: permissive roots cannot authorize formal-save mutations.
# No elevation, helper, game, editor, queue or real userdata is accessed.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module Microsoft.PowerShell.Utility
. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-fs-guard.ps1')))
. ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../elevated-fs-ops.ps1')))
$project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$parent = Join-Path $project '.runtime/fs-guard-fixtures'
$scratch = [IO.Path]::GetFullPath((Join-Path $parent ([Guid]::NewGuid().ToString('N').Substring(0, 8))))
if (-not $scratch.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'TEST_PATH_OUTSIDE_WORKSPACE' }
$oldProfile = $env:USERPROFILE
$script:passed = 0
function Check([bool]$condition, [string]$name) {
    if (-not $condition) { throw ('ASSERT:' + $name) }
    $script:passed++
    Write-Output ('PASS ' + $name)
}
function Refuses([hashtable]$request, [string]$name, [string]$expectedPrefix = 'FORMAL_SAVE_') {
    $message = ''
    try { Invoke-FsRequest -Request ([pscustomobject]$request) -Roots $roots -BackupsRoot $backups | Out-Null }
    catch { $message = $_.Exception.Message }
    Check ($message.Length -gt 0 -and $message.StartsWith($expectedPrefix)) $name
    Check ([IO.File]::ReadAllText($save) -eq 'synthetic-save') ($name + ' leaves original bytes')
}
try {
    $env:USERPROFILE = Join-Path $scratch 'u'
    $data = Join-Path $env:USERPROFILE 'AppData/LocalLow/miHoYo'
    $locale = Join-Path $data 'SyntheticGame'
    $beyond = Join-Path $locale 'BeyondLocal'
    $uid = Join-Path $beyond '123456'
    $saveDir = Join-Path $uid 'Beyond_Local_Save_Level'
    $save = Join-Path $saveDir '1073741999.gil'
    $profile = Join-Path $uid 'Beyond_Local_Save_Player.gip'
    $export = Join-Path $beyond 'Beyond_Local_Export'
    $backups = Join-Path $scratch 'project-backups'
    $source = Join-Path $scratch 'candidate.gil'
    foreach ($dir in @($saveDir, $export, $backups)) { [IO.Directory]::CreateDirectory($dir) | Out-Null }
    [IO.File]::WriteAllText($save, 'synthetic-save')
    [IO.File]::WriteAllText($profile, 'synthetic-profile')
    [IO.File]::WriteAllText($source, 'synthetic-candidate')
    # Deliberately grant the whole fixture and an even more specific save root.
    $roots = @(
        [pscustomobject]@{name='permissive';path=$scratch;read=$true;write=$true},
        [pscustomobject]@{name='explicit-save';path=$saveDir;read=$true;write=$true}
    )
    Refuses @{op='write';path=$save;encoding='utf8';data='bad'} 'write existing GIL'
    Refuses @{op='write';path=$profile;encoding='utf8';data='bad'} 'write player GIP'
    Refuses @{op='write';path=(Join-Path $saveDir 'new.tmp');encoding='utf8';data='bad'} 'temporary filename cannot bypass save policy'
    Refuses @{op='write';path=$save.ToUpperInvariant();encoding='utf8';data='bad'} 'case-insensitive save path'
    Refuses @{op='write';path=(Join-Path $export '../123456/Beyond_Local_Save_Level/1073741999.gil');encoding='utf8';data='bad'} 'export traversal cannot reach save'
    Refuses @{op='copy';path=$source;dest=$save;overwrite=$true} 'copy destination save'
    Refuses @{op='copy';path=$source;dest=$locale;overwrite=$true} 'copy destination save ancestor'
    Refuses @{op='move';path=$save;dest=(Join-Path $backups 'moved.gil');confirm=$save} 'move source save'
    Refuses @{op='move';path=$source;dest=$save;confirm=$source;overwrite=$true} 'move destination save'
    Refuses @{op='delete';path=$save;confirm=$save} 'delete save'
    Refuses @{op='delete';path=$uid;confirm=$uid;recurse=$true} 'delete UID directory'
    Refuses @{op='delete';path=$locale;confirm=$locale;recurse=$true} 'delete save ancestor'
    Refuses @{op='delete';path=$data;confirm=$data;recurse=$true} 'delete userdata root'
    Refuses @{op='mkdir';path=(Join-Path $saveDir 'new-directory')} 'mkdir cannot enter formal save tree'
    Refuses @{op='write';path=(Join-Path $beyond 'Beyond_Local_Export_evil/new.tmp');encoding='utf8';data='bad'} 'export prefix is not exception'
    Refuses @{op='write';path=(Join-Path $locale 'BeyondLocal./123456/evil.gil');encoding='utf8';data='bad'} 'trailing-dot alias refused'
    Refuses @{op='write';path=(Join-Path $locale 'BEYOND~1/123456/evil.gil');encoding='utf8';data='bad'} 'short-name alias refused'
    Refuses @{op='write';path=($save + ':stream');encoding='utf8';data='bad'} 'alternate stream refused by path parser or policy' ''
    $savedBackups = $backups
    $backups = Join-Path $saveDir 'not-created-backup'
    Refuses @{op='snapshot';path=$uid} 'snapshot parent checked before creation'
    Check (-not [IO.Directory]::Exists($backups)) 'refused snapshot created no parent'
    $backups = $savedBackups
    Check (-not [IO.File]::Exists((Join-Path $saveDir 'new.tmp'))) 'refused write created no temp'
    Check ([IO.File]::ReadAllText($source) -eq 'synthetic-candidate') 'refused move preserved source'
    $read = Invoke-FsRequest -Request ([pscustomobject]@{op='read';path=$save;encoding='utf8'}) -Roots $roots -BackupsRoot $backups
    Check ($read.data -eq 'synthetic-save') 'formal save remains readable'
    $backup = Join-Path $backups 'copy.gil'
    $null = Invoke-FsRequest -Request ([pscustomobject]@{op='copy';path=$save;dest=$backup}) -Roots $roots -BackupsRoot $backups
    Check ([IO.File]::ReadAllText($backup) -eq 'synthetic-save') 'read-only source backup remains available'
    $snapshot = Invoke-FsRequest -Request ([pscustomobject]@{op='snapshot';path=$uid;label='formal-readonly'}) -Roots $roots -BackupsRoot $backups
    Check ([IO.File]::Exists((Join-Path $snapshot.snapshot 'Beyond_Local_Save_Player.gip'))) 'directory snapshot remains available'
    $normal = Join-Path $backups 'candidate.gil'
    $null = Invoke-FsRequest -Request ([pscustomobject]@{op='write';path=$normal;encoding='utf8';data='candidate'}) -Roots $roots -BackupsRoot $backups
    Check ([IO.File]::ReadAllText($normal) -eq 'candidate') 'project candidate writes remain available'
    $gia = Join-Path $export 'isolated.gia'
    $null = Invoke-FsRequest -Request ([pscustomobject]@{op='write';path=$gia;encoding='utf8';data='fixture-gia'}) -Roots $roots -BackupsRoot $backups
    Check ([IO.File]::ReadAllText($gia) -eq 'fixture-gia') 'explicit export subtree remains outside formal-save policy'
    $config = [IO.File]::ReadAllText((Join-Path $PSScriptRoot '../elevated-config.json')) | ConvertFrom-Json
    $entry = $config.roots | Where-Object name -eq 'game-data-locallow'
    Check ($entry.read -eq $true -and $entry.write -eq $false) 'default actual userdata config is read-only'
    Check ([IO.File]::ReadAllText($profile) -eq 'synthetic-profile') 'player profile remains unchanged'
    Write-Output ('passed=' + $script:passed + ' failed=0')
} finally {
    $env:USERPROFILE = $oldProfile
    if ([IO.Directory]::Exists($scratch)) {
        $resolved = [IO.Path]::GetFullPath($scratch)
        if (-not $resolved.StartsWith($parent + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'UNSAFE_TEST_CLEANUP' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
