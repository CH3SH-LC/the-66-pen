$ErrorActionPreference='Stop'
$taskRun=$PSScriptRoot
$taskClaimed=$false
$taskResult=[ordered]@{scope='FIXED_ENTITY_MATERIAL_ACTION';executed=$false;exitCode=$null;error=$null;saveInvoked=$false;startedUtc=[DateTime]::UtcNow.ToString('o')}
try {
    $claim=[IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $claim.Dispose()
    $taskClaimed=$true
    if(-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'NORMAL_ADMIN_APPROVAL_REQUIRED'}
    if([DateTimeOffset]::UtcNow -ge [DateTimeOffset]::Parse(@@EXPIRES@@)){throw 'MATERIAL_PREPARATION_EXPIRED'}
    foreach($pin in @(
@@PINS@@
    )) {
        if((Get-FileHash -LiteralPath $pin[0] -Algorithm SHA256).Hash -ine $pin[1]){throw ('PIN_CHANGED:'+$pin[0])}
    }
    $build=Get-Content -LiteralPath (Join-Path $taskRun 'build-result.json') -Raw|ConvertFrom-Json
    if($build.kind -cne 'entity-material-build-v1' -or -not $build.launchable -or (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ine $build.wrapperSha256){throw 'WRAPPER_CHANGED'}
    $stdout=[IO.File]::Open((Join-Path $taskRun 'stdout.jsonl'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $stderr=$null
    $probe=$null
    try {
        $stderr=[IO.File]::Open((Join-Path $taskRun 'stderr.txt'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $start=[Diagnostics.ProcessStartInfo]::new()
        $start.FileName=Join-Path $taskRun 'hook_receipt_probe.exe'
        $start.WorkingDirectory=$taskRun
        $start.UseShellExecute=$false
        $start.CreateNoWindow=$true
        $start.WindowStyle=[Diagnostics.ProcessWindowStyle]::Hidden
        $start.RedirectStandardOutput=$true
        $start.RedirectStandardError=$true
        $probe=[Diagnostics.Process]::new()
        $probe.StartInfo=$start
        # Mark before Start: a launch exception after process creation is uncertain.
        $taskResult.executed=$true
        if(-not $probe.Start()){throw 'MATERIAL_PROBE_START_FAILED'}
        $outputCopy=$probe.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errorCopy=$probe.StandardError.BaseStream.CopyToAsync($stderr)
        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($outputCopy,$errorCopy))
        $probe.WaitForExit()
        $taskResult.exitCode=$probe.ExitCode
    } finally {
        if($probe){$probe.Dispose()}
        if($stderr){$stderr.Dispose()}
        $stdout.Dispose()
    }
} catch {$taskResult.error=$_.Exception.Message}
finally {
    if($taskClaimed) {
        $taskResult.finishedUtc=[DateTime]::UtcNow.ToString('o')
        $stream=[IO.File]::Open((Join-Path $taskRun 'exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $writer=[IO.StreamWriter]::new($stream,[Text.UTF8Encoding]::new($false))
        try {$writer.Write(($taskResult|ConvertTo-Json -Depth 10))}finally{$writer.Dispose()}
    }
}
if($taskResult.error -or $taskResult.exitCode -ne 0){exit 1}
