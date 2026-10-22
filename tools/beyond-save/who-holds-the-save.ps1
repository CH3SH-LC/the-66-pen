# who-holds-the-save.ps1 -- ask Windows which process has the save files open.
#
# WHY THIS EXISTS
#   The profile (.gip) is rewritten from some process's memory, and an external edit is
#   overwritten. Knowing WHICH process owns it decides where a durable registration has
#   to happen: in the editor's model, or the game's. Static analysis could not answer it
#   -- the editor's strings are ConfuserEx-encrypted, so "the string is not in the file"
#   says nothing -- and a 90-second mtime watch saw no periodic writer, which only shows
#   writes are event-driven, not who makes them.
#
#   The Restart Manager API answers it directly: register the files, ask which processes
#   are using them. It is the same mechanism Windows uses to find what blocks a reboot.
#
#   Read-only. It opens no file for writing, starts nothing, and stops nothing.

param(
  [string[]]$Path,
  [string]$Uid = '100000001'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Path -or $Path.Count -eq 0) {
  # The game's data directory has a non-ASCII name. Do NOT write it as a literal in
  # this file: Windows PowerShell 5.1 reads .ps1 as ANSI when there is no BOM, so the
  # literal is silently mangled and every path below it becomes "not found". Find the
  # directory by shape instead -- the one miHoYo subfolder that holds BeyondLocal.
  $mihoyo = Join-Path $env:USERPROFILE 'AppData\LocalLow\miHoYo'
  $gameData = Get-ChildItem -LiteralPath $mihoyo -Directory |
              ForEach-Object { Join-Path $_.FullName 'BeyondLocal' } |
              Where-Object { Test-Path -LiteralPath $_ } |
              Select-Object -First 1
  if (-not $gameData) { throw "no BeyondLocal directory under $mihoyo" }
  $root = Join-Path $gameData $Uid
  $Path = @((Join-Path $root 'Beyond_Local_Save_Player.gip')) +
          @(Get-ChildItem -LiteralPath (Join-Path $root 'Beyond_Local_Save_Level') -Filter '*.gil' |
            ForEach-Object { $_.FullName })
}

$sig = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class RestartManagerQuery
{
    [StructLayout(LayoutKind.Sequential)]
    struct RM_UNIQUE_PROCESS
    {
        public int dwProcessId;
        public System.Runtime.InteropServices.ComTypes.FILETIME ProcessStartTime;
    }

    const int RmRebootReasonNone = 0;
    const int CCH_RM_MAX_APP_NAME = 255;
    const int CCH_RM_MAX_SVC_NAME = 63;

    enum RM_APP_TYPE
    {
        RmUnknownApp = 0, RmMainWindow = 1, RmOtherWindow = 2,
        RmService = 3, RmExplorer = 4, RmConsole = 5,
        RmCritical = 1000
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct RM_PROCESS_INFO
    {
        public RM_UNIQUE_PROCESS Process;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = CCH_RM_MAX_APP_NAME + 1)]
        public string strAppName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = CCH_RM_MAX_SVC_NAME + 1)]
        public string strServiceShortName;
        public RM_APP_TYPE ApplicationType;
        public uint AppStatus;
        public uint TSSessionId;
        [MarshalAs(UnmanagedType.Bool)]
        public bool bRestartable;
    }

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    static extern int RmStartSession(out uint pSessionHandle, int dwSessionFlags, string strSessionKey);

    [DllImport("rstrtmgr.dll")]
    static extern int RmEndSession(uint pSessionHandle);

    [DllImport("rstrtmgr.dll", CharSet = CharSet.Unicode)]
    static extern int RmRegisterResources(uint pSessionHandle, uint nFiles, string[] rgsFilenames,
        uint nApplications, [In] RM_UNIQUE_PROCESS[] rgApplications, uint nServices, string[] rgsServiceNames);

    [DllImport("rstrtmgr.dll")]
    static extern int RmGetList(uint dwSessionHandle, out uint pnProcInfoNeeded,
        ref uint pnProcInfo, [In, Out] RM_PROCESS_INFO[] rgAffectedApps, ref uint lpdwRebootReasons);

    public static List<string> Who(string[] files)
    {
        var result = new List<string>();
        uint session;
        string key = Guid.NewGuid().ToString();
        int rv = RmStartSession(out session, 0, key);
        if (rv != 0) { result.Add("RmStartSession failed: " + rv); return result; }
        try
        {
            rv = RmRegisterResources(session, (uint)files.Length, files, 0, null, 0, null);
            if (rv != 0) { result.Add("RmRegisterResources failed: " + rv); return result; }

            uint needed = 0, count = 0, reasons = 0;
            rv = RmGetList(session, out needed, ref count, null, ref reasons);
            if (rv == 234 && needed > 0)
            {
                count = needed;
                var arr = new RM_PROCESS_INFO[count];
                rv = RmGetList(session, out needed, ref count, arr, ref reasons);
                if (rv == 0)
                {
                    for (int i = 0; i < count; i++)
                    {
                        result.Add(arr[i].Process.dwProcessId + "|" + arr[i].strAppName + "|" +
                                   arr[i].ApplicationType + "|" + arr[i].bRestartable);
                    }
                }
                else result.Add("RmGetList(2) failed: " + rv);
            }
            else if (rv == 0)
            {
                result.Add("(no process holds these files)");
            }
            else result.Add("RmGetList failed: " + rv);
        }
        finally { RmEndSession(session); }
        return result;
    }
}
'@

Add-Type -TypeDefinition $sig -Language CSharp

Write-Output 'files queried:'
foreach ($p in $Path) { Write-Output ("  " + $p) }
Write-Output ''
Write-Output 'processes holding them (pid | app | type | restartable):'
$who = [RestartManagerQuery]::Who($Path)
foreach ($w in $who) {
  $parts = $w -split '\|'
  if ($parts.Count -ge 4 -and $parts[0] -match '^\d+$') {
    $proc = Get-Process -Id ([int]$parts[0]) -ErrorAction SilentlyContinue
    $exe = if ($proc) { $proc.ProcessName } else { '?' }
    Write-Output ("  pid={0,-8} exe={1,-16} app={2,-28} type={3} restartable={4}" -f $parts[0], $exe, $parts[1], $parts[2], $parts[3])
  } else {
    Write-Output ("  " + $w)
  }
}
