param([Parameter(Mandatory=$true)][Guid]$RunId,
      [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')][string]$RequestId)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskDirectory=Join-Path $taskRoot ('.runtime/authoring/requests/'+$RequestId)
$taskResponse=Join-Path $taskDirectory 'elevated-response.json'
$taskHelper=Join-Path $PSScriptRoot 'graph-elevated-once.ps1'
try {
    # Inherit this process's actual host; PS7 does not contain powershell.exe.
    # Query the effective policy only. Never override it or select another host.
    $taskShell=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if(-not [IO.Path]::IsPathRooted($taskShell) -or -not [IO.File]::Exists($taskShell) -or [IO.Path]::GetFileName($taskShell) -notin @('pwsh.exe','powershell.exe')){throw 'NATIVE_POWERSHELL_HOST_INVALID'}
    if((Get-ExecutionPolicy).ToString() -notin @('RemoteSigned','Unrestricted')){throw 'NATIVE_POWERSHELL_HOST_POLICY_REFUSED'}
    if(Test-Path -LiteralPath $taskResponse){throw 'EXISTING_RESPONSE'}
    # Both identifiers have a strict alphabet. The only elevated entry point is
    # the fixed project helper, never caller-provided PowerShell or an eval body.
    $taskArguments='-NoProfile -File "'+$taskHelper+'" -RunId '+$RunId.ToString('D')+' -RequestId '+$RequestId
    $taskChild=Start-Process -FilePath $taskShell -Verb RunAs -WindowStyle Hidden -ArgumentList $taskArguments -PassThru
    $taskDeadline=[DateTimeOffset]::UtcNow.AddSeconds(90)
    while([DateTimeOffset]::UtcNow -lt $taskDeadline){
        if(Test-Path -LiteralPath $taskResponse){
            try { $taskText=[IO.File]::ReadAllText($taskResponse); $null=$taskText|ConvertFrom-Json; Write-Output $taskText; exit 0 } catch { }
        }
        if($taskChild.HasExited){throw 'NO_RESPONSE'}
        Start-Sleep -Milliseconds 150
    }
    throw 'WAIT_EXPIRED'
} catch {
    # No termination: delayed UAC/callback outcome remains uncertain. The claim
    # blocks another dispatch and lease validation in the child bounds late work.
    Write-Output '{"ok":false,"error":"ELEVATED_GRAPH_NO_RECEIPT","outcomeUncertain":true,"retryAttempted":false}'
    exit 2
}
