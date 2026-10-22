"""Bundle already-reviewed template actions for one normal administrator launch.

This does not issue reviews, compile, execute, elevate, or submit to the old helper.
Every action keeps its own one-shot wrapper and short native deadline. A failed
action stops the batch; earlier successful actions are never undone or repeated.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import prepare_currency

requests = prepare_currency.requests
profiles = prepare_currency.profiles
readonly = prepare_currency.readonly
OUTPUT = prepare_currency.candidate.ROOT / '.runtime/template-authoring/batches'
KINDS = {
    'create-currency': ('currency', 5),
    'create-item': ('item', 6),
    'bind-shop': ('binding', 7),
    'bind-bag': ('binding', 7),
    'create-skill': ('skill', 9),
}


def inspect_run(directory):
    run = requests.runtime_path(directory)
    result_path = run / 'build-result.json'
    result = requests.read_json(result_path)
    action = result.get('action')
    requests.require(action in KINDS, 'BATCH_UNSUPPORTED_ACTION')
    family, code = KINDS[action]
    wrapper = f'invoke-{family}-probe.ps1'
    requests.require(result.get('kind') == f'template-{family}-build-v1' and
        result.get('actionCode') == code and result.get('ok') is True and
        result.get('compiled') is True and result.get('launchable') is True and
        result.get('allowWrites') is True and result.get('reviewed') is True and
        result.get('compileOnly') is False and result.get('probeExecuted') is False and
        result.get('nativeCalled') is False and result.get('wrapperName') == wrapper,
        'BATCH_REVIEWED_BUILD_REQUIRED')
    requests.require(Path(result['run']).resolve() == run, 'BATCH_RUN_IDENTITY')
    hashes = result.get('hashes')
    requests.require(type(hashes) is dict and wrapper in hashes and
                     'build-contract.json' in hashes and 'prepared.json' in hashes,
                     'BATCH_INCOMPLETE_ARTIFACT_HASHES')
    for name, digest in hashes.items():
        path = (run / name).resolve()
        requests.require(path.is_relative_to(run) and path != run and
                         profiles.sha256(path) == digest, 'BATCH_ARTIFACT_CHANGED:' + name)
    contract = requests.read_json(run / 'build-contract.json')
    requests.require(contract['action'] == action and contract['actionCode'] == code and
        contract['reviewSha256'] == result['reviewSha256'] and
        contract['requestSha256'] == result['requestSha256'], 'BATCH_CONTRACT_MISMATCH')
    requests.require(not any((run / name).exists() for name in
        ('launch.claim', 'stdout.jsonl', 'stderr.txt', 'exit.json')), 'BATCH_ACTION_ALREADY_ATTEMPTED')
    return {'run': str(run), 'action': action, 'wrapper': wrapper,
            'wrapperSha256': hashes[wrapper], 'buildResultSha256': profiles.sha256(result_path),
            'requestSha256': result['requestSha256'], 'reviewId': contract['reviewId'],
            'levelId': contract['levelId'], 'session': contract['session']}


def bundle(directories):
    requests.require(1 <= len(directories) <= 8, 'BATCH_SIZE_1_TO_8')
    rows = [inspect_run(path) for path in directories]
    requests.require(len({row['run'] for row in rows}) == len(rows) and
        len({row['requestSha256'] for row in rows}) == len(rows) and
        len({row['reviewId'] for row in rows}) == len(rows), 'BATCH_DUPLICATE_ACTION')
    requests.require(all(row['levelId'] == rows[0]['levelId'] and row['session'] == rows[0]['session']
                         for row in rows), 'BATCH_MIXED_LEVEL_OR_SESSION')
    run = readonly.output_directory(OUTPUT)
    quote = prepare_currency.ps_literal
    fixed_rows = '\n'.join('    $taskRows.Add(@(' + ','.join(quote(row[key]) for key in
        ('run', 'wrapper', 'wrapperSha256', 'buildResultSha256')) + '))' for row in rows)
    script = r'''$ErrorActionPreference = 'Stop'
$taskBatch = $PSScriptRoot
$taskLog = [ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');steps=@();error=$null;saveVerified=$false;gameplayVerified=$false}
$taskClaimed = $false
try {
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'NOT_ELEVATED' }
    $taskClaim = [IO.File]::Open((Join-Path $taskBatch 'batch-launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskClaim.Dispose()
    $taskClaimed = $true
    $taskRows = New-Object 'System.Collections.Generic.List[object]'
__ROWS__
    # Validate every wrapper before the first action. Each wrapper separately
    # validates its complete artifact set, exact review and native deadline.
    foreach ($taskRow in $taskRows) {
        if ((Get-FileHash -LiteralPath (Join-Path $taskRow[0] $taskRow[1]) -Algorithm SHA256).Hash -ine $taskRow[2]) { throw 'BATCH_WRAPPER_CHANGED' }
        if ((Get-FileHash -LiteralPath (Join-Path $taskRow[0] 'build-result.json') -Algorithm SHA256).Hash -ine $taskRow[3]) { throw 'BATCH_BUILD_CHANGED' }
    }
    $taskShell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    foreach ($taskRow in $taskRows) {
        $taskWrapper = Join-Path $taskRow[0] $taskRow[1]
        if ((Get-FileHash -LiteralPath $taskWrapper -Algorithm SHA256).Hash -ine $taskRow[2]) { throw 'BATCH_WRAPPER_CHANGED' }
        if ((Get-FileHash -LiteralPath (Join-Path $taskRow[0] 'build-result.json') -Algorithm SHA256).Hash -ine $taskRow[3]) { throw 'BATCH_BUILD_CHANGED' }
        $taskChild = Start-Process -FilePath $taskShell -ArgumentList @('-NoProfile','-NonInteractive','-File',('"' + $taskWrapper + '"')) -WorkingDirectory $taskRow[0] -WindowStyle Hidden -Wait -PassThru
        try { $taskCode = $taskChild.ExitCode } finally { $taskChild.Dispose() }
        $taskLog.steps += [ordered]@{run=$taskRow[0];exitCode=$taskCode}
        if ($taskCode -ne 0) { throw 'BATCH_ACTION_FAILED_NO_RETRY' }
    }
} catch { $taskLog.error = $_.Exception.Message }
finally {
    $taskLog['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
    if ($taskClaimed) {
        $taskFile = [IO.File]::Open((Join-Path $taskBatch 'batch-exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $taskWriter = New-Object IO.StreamWriter($taskFile,(New-Object Text.UTF8Encoding($false)))
        try { $taskWriter.Write(($taskLog | ConvertTo-Json -Depth 5)) } finally { $taskWriter.Dispose() }
    }
}
if ($taskLog.error) { exit 1 }
'''.replace('__ROWS__', fixed_rows)
    wrapper = run / 'invoke-template-batch.ps1'
    with wrapper.open('x', encoding='utf-8-sig') as stream:
        stream.write(script)
    manifest = {'kind': 'template-reviewed-batch-v1', 'run': str(run), 'actions': rows,
        'wrapper': wrapper.name, 'wrapperSha256': profiles.sha256(wrapper),
        'executed': False, 'elevationRequested': False, 'persistentSaveVerified': False,
        'limits': 'One normal administrator launch of existing reviewed actions. Partial failure stops; no retry or rollback. Independent per-action raw acceptance remains required.'}
    readonly.write_json(run / 'batch.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='append', required=True)
    args = parser.parse_args(argv)
    try:
        result = bundle(args.run)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'executed': False}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
