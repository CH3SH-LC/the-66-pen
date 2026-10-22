param(
    [int]$TargetPid = 143256,
    [int]$IdleThresholdSeconds = 30,
    [int]$TimeoutMinutes = 180,
    [int]$PollSeconds = 5,
    [string]$ProbeScript = 'probe-build-gameloop.ps1'
)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))

# A bridge scope lives five minutes. Launching the administrator prompt while nobody is at
# the keyboard just wastes the one approval the user has to give, and a stale modal prompt
# on screen is worse than no prompt. So wait until the user is actually present: Windows
# reports how long since the last keyboard or mouse input, and we launch on the first poll
# that looks like a person.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
public class UserIdle {
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
    public static uint Seconds() {
        LASTINPUTINFO info = new LASTINPUTINFO();
        info.cbSize = (uint)Marshal.SizeOf(info);
        if (!GetLastInputInfo(ref info)) return 0;
        return ((uint)Environment.TickCount - info.dwTime) / 1000u;
    }
}
"@

$report = Join-Path $root '.runtime/editor-bridge/await-user-gameloop.log'
function Note([string]$text) {
    $line = ('{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text)
    Add-Content -LiteralPath $report -Value $line -Encoding utf8
    Write-Output $line
}

$alive = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
if (-not $alive -or $alive.ProcessName -ne 'BeyondEditor') { Note "ABORT: pid $TargetPid is not a running BeyondEditor"; exit 2 }
Note "watching; waiting for user activity (idle < ${IdleThresholdSeconds}s), timeout ${TimeoutMinutes}m"

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
while ((Get-Date) -lt $deadline) {
    $idle = [UserIdle]::Seconds()
    if ($idle -lt $IdleThresholdSeconds) {
        Note "user present (idle ${idle}s); creating scope and requesting approval"
        $scope = (& (Join-Path $PSScriptRoot 'new-scope.ps1') -TargetPid $TargetPid | ConvertFrom-Json)
        Note ("runId=" + $scope.runId)
        Set-Content -LiteralPath (Join-Path $root '.runtime/editor-bridge/pending-gameloop-run.txt') -Value $scope.runId -Encoding utf8
        Start-Process 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList @(
            '-NoProfile','-ExecutionPolicy','Bypass','-File',
            ('"' + (Join-Path $PSScriptRoot $ProbeScript) + '"'), '-RunId', $scope.runId) | Out-Null
        Note 'approval requested; watcher done'
        exit 0
    }
    Start-Sleep -Seconds $PollSeconds
}
Note 'TIMEOUT: user never became active; nothing was launched'
exit 3
