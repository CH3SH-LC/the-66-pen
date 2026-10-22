"""Build one reviewed currency action and its dedicated launch wrapper. Never execute it.

The generated wrapper is a new entry point requiring its own normal authorized
launch; it is not compatible with, or submitted to, an existing helper action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import subprocess

import build_candidate as candidate
import template_review as reviews
import snapshot_abi as abi

profiles, requests, readonly = candidate.profiles, candidate.requests, candidate.readonly
OUTPUT = candidate.ROOT / '.runtime/template-authoring/prepared-currency'
TTL_SECONDS = 180


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def emit_header(run, request, raw, runtime, profile, session, deadline, message_id, nonce):
    # Generate in the new run only. No previous candidate or live native file is edited.
    candidate.emit_header(run, request, raw, runtime, profile)
    path = run / 'target_config.h'
    text = path.read_text(encoding='utf-8')
    old = {'HR_TARGET_PID': '1ULL', 'HR_TARGET_TID': '1ULL', 'HR_TARGET_CREATION': '1ULL',
           'HR_TARGET_THREAD_CREATION': '1ULL', 'HR_DEADLINE': '1ULL', 'HR_NONCE': '1ULL',
           'HR_MESSAGE_ID': '49153ULL',
           'HR_TARGET_IMAGE': 'L' + json.dumps(str(run / 'compile-only-target.invalid'))}
    new = {'HR_TARGET_PID': str(session['pid']) + 'ULL', 'HR_TARGET_TID': str(session['tid']) + 'ULL',
           'HR_TARGET_CREATION': str(session['processCreation']) + 'ULL',
           'HR_TARGET_THREAD_CREATION': str(session['threadCreation']) + 'ULL',
           'HR_DEADLINE': str(deadline) + 'ULL', 'HR_NONCE': str(nonce) + 'ULL',
           'HR_MESSAGE_ID': str(message_id) + 'ULL', 'HR_TARGET_IMAGE': 'L' + json.dumps(session['image'])}
    for key in old:
        text = candidate.replace_once(text, '#define ' + key + ' ' + old[key] + '\n',
                                      '#define ' + key + ' ' + new[key] + '\n')
    text = candidate.replace_once(text,
        '// Compile-only expired candidate; review markers are not dispatch authorization.',
        '// Dedicated currency action: coordinator-reviewed request and fixed session, one 180-second attempt.')
    path.write_text(text, encoding='utf-8')


def emit_wrapper(run, artifacts, validated):
    review = validated['review']
    local_checks = ',\n'.join('        @(' + ps_literal(name) + ',' + ps_literal(digest) + ')'
                             for name, digest in artifacts.items())
    external = {validated['reviewPath']: validated['reviewSha256'],
        validated['requestPath']: review['requestSha256'],
        validated['runtimeProfilePath']: review['runtimeProfileSha256'],
        validated['targetGil']: review['recovery']['sha256'], validated['backup']: review['recovery']['sha256'],
        str(profiles.TARGET_IMAGE): profiles.load_profile()['image']['sha256']}
    external.update({str(candidate.ROOT / name): digest for name, digest in review['sourceHashes'].items()})
    external.update({str(Path(validated['baselineRun']) / name): digest for name, digest in review['evidenceHashes'].items()})
    external_checks = ',\n'.join('        @(' + ps_literal(path) + ',' + ps_literal(digest) + ')'
                                for path, digest in external.items())
    text = r'''$ErrorActionPreference = 'Stop'
$taskRun = $PSScriptRoot
$taskResult = [ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');wrapperPid=$PID;executed=$false;exitCode=$null;error=$null;scope='FIXED_TEMPLATE_CURRENCY_ACTION';persistentSaveVerified=$false}
$taskOwnedClaim = $false
try {
    $taskClaim = [IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskClaim.Dispose()
    $taskOwnedClaim = $true
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'NOT_ELEVATED' }
    $taskExpires = [DateTimeOffset]::Parse(__EXPIRES__).UtcDateTime
    if ([DateTime]::UtcNow -ge $taskExpires) { throw 'CURRENCY_REVIEW_EXPIRED' }
    foreach ($taskArtifact in @(
__LOCAL_CHECKS__
    )) {
        if ((Get-FileHash -LiteralPath (Join-Path $taskRun $taskArtifact[0]) -Algorithm SHA256).Hash -ine $taskArtifact[1]) { throw ('ARTIFACT_CHANGED:' + $taskArtifact[0]) }
    }
    foreach ($taskExternal in @(
__EXTERNAL_CHECKS__
    )) {
        if ((Get-FileHash -LiteralPath $taskExternal[0] -Algorithm SHA256).Hash -ine $taskExternal[1]) { throw ('REVIEW_INPUT_CHANGED:' + $taskExternal[0]) }
    }
    # The coordinator also checks build-result.json and this wrapper hash before launch.
    $taskBuild = Get-Content -LiteralPath (Join-Path $taskRun 'build-result.json') -Raw | ConvertFrom-Json
    if ($taskBuild.kind -ne 'template-currency-build-v1' -or -not $taskBuild.launchable -or $taskBuild.compileOnly -or $taskBuild.wrapperName -ne 'invoke-currency-probe.ps1') { throw 'DEDICATED_BUILD_REQUIRED' }
    if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ine $taskBuild.hashes.'invoke-currency-probe.ps1') { throw 'WRAPPER_CHANGED' }
    if ([DateTime]::UtcNow -ge $taskExpires) { throw 'CURRENCY_REVIEW_EXPIRED' }
    $taskStdout = [IO.File]::Open((Join-Path $taskRun 'stdout.jsonl'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $taskStderr = $null
    $taskProbe = $null
    try {
        $taskStderr = [IO.File]::Open((Join-Path $taskRun 'stderr.txt'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $taskStart = New-Object Diagnostics.ProcessStartInfo
        $taskStart.FileName = Join-Path $taskRun 'hook_receipt_probe.exe'
        $taskStart.WorkingDirectory = $taskRun
        $taskStart.UseShellExecute = $false
        $taskStart.CreateNoWindow = $true
        $taskStart.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
        $taskStart.RedirectStandardOutput = $true
        $taskStart.RedirectStandardError = $true
        $taskProbe = New-Object Diagnostics.Process
        $taskProbe.StartInfo = $taskStart
        if (-not $taskProbe.Start()) { throw 'CURRENCY_PROBE_START_FAILED' }
        $taskResult.executed = $true
        $taskOutputCopy = $taskProbe.StandardOutput.BaseStream.CopyToAsync($taskStdout)
        $taskErrorCopy = $taskProbe.StandardError.BaseStream.CopyToAsync($taskStderr)
        [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($taskOutputCopy,$taskErrorCopy))
        $taskProbe.WaitForExit()
        $taskResult.exitCode = $taskProbe.ExitCode
    } finally {
        if ($null -ne $taskProbe) { $taskProbe.Dispose() }
        if ($null -ne $taskStderr) { $taskStderr.Dispose() }
        $taskStdout.Dispose()
    }
} catch { $taskResult.error = $_.Exception.Message }
finally {
    $taskResult['finishedUtc'] = [DateTime]::UtcNow.ToString('o')
    # A repeated launcher cannot overwrite the first attempt's receipt.
    if ($taskOwnedClaim) {
        $taskExit = [IO.File]::Open((Join-Path $taskRun 'exit.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        $taskWriter = New-Object IO.StreamWriter($taskExit,(New-Object Text.UTF8Encoding($false)))
        try { $taskWriter.Write(($taskResult | ConvertTo-Json)) } finally { $taskWriter.Dispose() }
    }
}
if ($taskResult.error -or $taskResult.exitCode -ne 0) { exit 1 }
'''
    text = text.replace('__EXPIRES__', ps_literal(review['expiresUtc'])).replace('__LOCAL_CHECKS__', local_checks).replace('__EXTERNAL_CHECKS__', external_checks)
    path = run / 'invoke-currency-probe.ps1'
    with path.open('x', encoding='utf-8-sig', newline='\n') as stream:
        stream.write(text)
    return path


def prepare(review_path):
    validated = reviews.validate_review(review_path, minimum_remaining=TTL_SECONDS)
    review, request = validated['review'], validated['request']
    value, raw, runtime, profile, disk, inputs = candidate.load_inputs(
        validated['requestPath'], validated['baselineRun'], validated['runtimeProfilePath'])
    profiles.require(value == request, 'VALIDATED_REQUEST_CHANGED')
    # Identity queries are read-only and happen only in this explicit prepare call.
    session = profiles.validate_session(review['session'])
    kernel, user = profiles.windows_api()
    now = reviews.utc_now()
    reviews.time_window(review, now, minimum_remaining=TTL_SECONDS)
    deadline = int(kernel.GetTickCount64()) + TTL_SECONDS * 1000
    message_id = int(user.RegisterWindowMessageW('Miliastra.Currency.' + secrets.token_hex(16)))
    profiles.require(0xc000 <= message_id <= 0xffff, 'CURRENCY_REGISTER_MESSAGE_FAILED')
    nonce = secrets.randbits(63) | 1
    run = readonly.output_directory(OUTPUT)
    claim = reviews.claim_review(validated, run)
    originals = candidate.source_copies(run)
    emit_header(run, request, raw, runtime, profile, session, deadline, message_id, nonce)
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    (run / 'request.json').write_bytes(requests.canonical_bytes(request))
    (run / 'review.json').write_bytes(Path(validated['reviewPath']).read_bytes())
    contract = {'schemaVersion': 1, 'kind': 'template-currency-build-contract-v1', 'action': 'create-currency',
        'actionCode': 5, 'receiptVersion': 9, 'compileOnly': False, 'launchable': False,
        'allowWrites': True, 'reviewed': True, 'nativeCalled': False, 'session': session,
        'levelId': request['levelId'], 'nonce': nonce, 'deadline': deadline, 'messageId': message_id,
        # 2026-10-17 双 ABI：把本次编译所用基线的快照 ABI 写进契约（随 dict(contract) 进 prepared.json），
        # 供 build / accept 绑定。v1 时是 (33208, 1, 0)，既有行为不变；v2 是 (262584, 2, 1)。
        'snapshotBytes': len(raw), 'snapshotVersion': abi.version_for_size(len(raw)),
        'largeScene': abi.large_scene_for_size(len(raw)),
        'ttlSeconds': TTL_SECONDS, 'reviewId': review['reviewId'], 'reviewSha256': validated['reviewSha256'],
        'reviewClaimPath': str(claim), 'reviewExpiresUtc': review['expiresUtc'],
        'requestSha256': review['requestSha256'], 'inputs': inputs, 'disk': disk,
        'sourceHashes': review['sourceHashes'], 'originalNativeSourceHashes': originals,
        'limits': 'Build contract only; group lookup may create state. No probe execution or persisted result.'}
    readonly.write_json(run / 'build-contract.json', contract)
    compiler = candidate.compile_sources(run)
    current = reviews.validate_review(review_path)
    profiles.require(current['reviewSha256'] == validated['reviewSha256'], 'REVIEW_CHANGED_DURING_BUILD')
    current_session = profiles.validate_session(review['session'])
    profiles.require(current_session == session, 'SESSION_CHANGED_DURING_BUILD')
    profiles.require(int(kernel.GetTickCount64()) < deadline, 'CURRENCY_BUILD_DEADLINE_EXPIRED')
    # The copied source bytes must correspond to the exact reviewed originals.
    for relative, digest in originals.items():
        key = 'tools/game-executor/' + relative
        profiles.require(review['sourceHashes'][key] == digest, 'COPIED_SOURCE_NOT_REVIEWED:' + key)
    prepared = dict(contract, kind='template-currency-prepared-v1', launchable=True, compiled=True,
                    compiler=compiler, preparedAtUtc=datetime.now(timezone.utc).isoformat(),
                    wrapperName='invoke-currency-probe.ps1')
    readonly.write_json(run / 'prepared.json', prepared)
    hashes = {str(p.relative_to(run)).replace('\\', '/'): profiles.sha256(p)
              for p in sorted(run.rglob('*')) if p.is_file()}
    wrapper = emit_wrapper(run, hashes, validated)
    hashes[wrapper.name] = profiles.sha256(wrapper)
    result = {'ok': True, 'schemaVersion': 1, 'kind': 'template-currency-build-v1',
        'run': str(run), 'action': 'create-currency', 'actionCode': 5, 'compiled': True,
        'compileOnly': False, 'launchable': True, 'allowWrites': True, 'reviewed': True,
        'nativeCalled': False, 'probeExecuted': False, 'requestSha256': review['requestSha256'],
        'reviewSha256': validated['reviewSha256'], 'deadline': deadline, 'nonce': nonce,
        'wrapperName': wrapper.name, 'hashes': hashes}
    readonly.write_json(run / 'build-result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True, help='Existing coordinator-issued currency review under .runtime')
    args = parser.parse_args(argv)
    try:
        result = prepare(args.review)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'launchable': False, 'nativeCalled': False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
