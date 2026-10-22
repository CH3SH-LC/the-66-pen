param([Parameter(Mandatory=$true)][Guid]$RunId,
      [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')][string]$RequestId)
$ErrorActionPreference='Stop'
$taskRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$taskDirectory=Join-Path $taskRoot ('.runtime/authoring/requests/'+$RequestId)
$taskResponse=Join-Path $taskDirectory 'elevated-response.json'
try {
    # Inherit this process's actual host; PS7 does not contain powershell.exe.
    # Query the effective policy only. Never override it or select another host.
    $taskShell=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if(-not [IO.Path]::IsPathRooted($taskShell) -or -not [IO.File]::Exists($taskShell) -or [IO.Path]::GetFileName($taskShell) -notin @('pwsh.exe','powershell.exe')){throw 'NATIVE_POWERSHELL_HOST_INVALID'}
    if((Get-ExecutionPolicy).ToString() -notin @('RemoteSigned','Unrestricted')){throw 'NATIVE_POWERSHELL_HOST_POLICY_REFUSED'}
    $taskIdentity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $taskPrincipal=[Security.Principal.WindowsPrincipal]::new($taskIdentity)
    if(-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'ADMIN_REQUIRED'}
    if(-not (Test-Path -LiteralPath (Join-Path $taskDirectory 'claim.json'))){throw 'CLAIM_REQUIRED'}
    $taskClaim=Get-Content -LiteralPath (Join-Path $taskDirectory 'claim.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if($taskClaim.command.backend -cne 'graph' -or $taskClaim.command.runId -cne $RunId.ToString('D')){throw 'CLAIM_MISMATCH'}
    $taskRequestPath=Join-Path $taskDirectory 'bridge-request.json'
    $taskRequest=Get-Content -LiteralPath $taskRequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if($taskRequest.id -cne $RequestId -or ($taskRequest.op -cne 'author-graph' -and $taskRequest.op -cne 'catalog')){throw 'REQUEST_MISMATCH'}
    # Exclusive attempt marker precedes any pipe operation. Reinvocation cannot
    # send twice, even if the first invocation has not produced its reply yet.
    $taskMarker=[IO.File]::Open((Join-Path $taskDirectory 'elevated-attempt.used'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskMarker.Dispose()
    $taskSettings=Join-Path $taskRoot ('.runtime/editor-bridge/runs/'+$RunId.ToString('D')+'/bridge-settings.json')
    $taskTransport=Join-Path $PSScriptRoot 'graph-transport.ps1'
    # Child process contains transport's exit statement; this helper always gets
    # a chance to preserve its response instead of exiting inside dot-sourcing.
    $taskPreviousOutputEncoding=[Console]::OutputEncoding
    try {
        [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
        $taskReply=& $taskShell -NoProfile -File $taskTransport -SettingsPath $taskSettings -RequestPath $taskRequestPath
    } finally {
        [Console]::OutputEncoding=$taskPreviousOutputEncoding
    }
    $taskText=$taskReply -join [Environment]::NewLine
    $null=$taskText|ConvertFrom-Json
} catch {
    $taskText='{"ok":false,"error":"ELEVATED_GRAPH_FAILED","outcomeUncertain":true,"retryAttempted":false}'
}
# Preserve only this request's result. No overwrite of an existing receipt.
try {
    $taskStream=[IO.File]::Open($taskResponse,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $taskWriter=[IO.StreamWriter]::new($taskStream,[Text.UTF8Encoding]::new($false))
    try {$taskWriter.Write($taskText)} finally {$taskWriter.Dispose()}
} catch { exit 2 }
