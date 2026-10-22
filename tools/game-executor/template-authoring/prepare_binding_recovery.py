"""Prepare one explicitly reviewed empty-bag transaction close; never launch it."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import uuid
import build_binding_recovery_candidate as candidate
profiles, requests, readonly = candidate.profiles, candidate.requests, candidate.readonly
OUTPUT = candidate.ROOT / '.runtime/template-authoring/prepared-binding-recovery'
CLAIMS = candidate.ROOT / '.runtime/template-authoring/recovery-review-claims'
TTL_SECONDS = 180
FIELDS = {'schemaVersion', 'kind', 'reviewId', 'reviewerRole', 'action', 'priorRun',
    'tokenRefusalRun', 'tokenRefusalEvidenceHashes', 'diagnosticOnly',
    'pendingDiagnosticRun', 'pendingDiagnosticEvidenceHashes',
    'priorEvidenceHashes', 'priorStdoutSha256', 'priorRawSha256', 'baselineRun',
    'evidenceHashes', 'levelId', 'session', 'sourceHashes', 'runtimeProfilePath',
    'runtimeProfileSha256', 'recovery', 'issuedUtc', 'expiresUtc'}
source_hashes = candidate.source_hashes


def utc_now():
    return datetime.now(timezone.utc)


def time_window(review, now=None, *, minimum_remaining=0):
    current = utc_now() if now is None else now
    start = datetime.fromisoformat(review['issuedUtc'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(review['expiresUtc'].replace('Z', '+00:00'))
    profiles.require(start.tzinfo is not None and end.tzinfo is not None and current.tzinfo is not None,
        'RECOVERY_REVIEW_TIMEZONE_REQUIRED')
    profiles.require(start <= current < end and 0 < (end-start).total_seconds() <= 3600 and
        (end-current).total_seconds() >= minimum_remaining, 'RECOVERY_REVIEW_EXPIRED_OR_WINDOW_TOO_SHORT')
    return end


def equal_files(first, second):
    with Path(first).open('rb') as a, Path(second).open('rb') as b:
        while True:
            left, right = a.read(1024*1024), b.read(1024*1024)
            if left != right: return False
            if not left: return True


def validate_review(review_path, *, now=None, minimum_remaining=0):
    path = requests.runtime_path(review_path)
    digest = profiles.sha256(path)
    review = requests.read_json(path)
    requests.exact_fields(review, FIELDS, 'binding-recovery-review')
    profiles.require(type(review['diagnosticOnly']) is bool, 'RECOVERY_DIAGNOSTIC_ONLY_BOOL_REQUIRED')
    profiles.require(type(review['schemaVersion']) is int and review['schemaVersion'] == 1 and
        review['kind'] == 'template-binding-recovery-review-v2' and review['reviewerRole'] == 'coordinator' and
        review['action'] == candidate.ACTION, 'RECOVERY_COORDINATOR_REVIEW_REQUIRED')
    identifier = uuid.UUID(review['reviewId'])
    profiles.require(identifier.int != 0 and str(identifier) == review['reviewId'], 'RECOVERY_REVIEW_ID')
    time_window(review, now, minimum_remaining=minimum_remaining)
    profiles.require(review['sourceHashes'] == source_hashes(), 'RECOVERY_REVIEW_SOURCE_CHANGED')
    value, raw, runtime, profile, disk, inputs = candidate.load_inputs(
        review['priorRun'], review['baselineRun'], review['runtimeProfilePath'], review['tokenRefusalRun'],
        review['pendingDiagnosticRun'])
    for name in ('priorEvidenceHashes', 'priorStdoutSha256', 'priorRawSha256', 'runtimeProfileSha256',
                 'tokenRefusalRun', 'tokenRefusalEvidenceHashes', 'pendingDiagnosticRun', 'pendingDiagnosticEvidenceHashes'):
        profiles.require(review[name] == inputs[name], 'RECOVERY_REVIEW_INPUT_CHANGED:' + name)
    profiles.require(review['evidenceHashes'] == inputs['baselineEvidenceHashes'] and
        review['levelId'] == value['levelId'] and review['session'] == value['session'], 'RECOVERY_REVIEW_IDENTITY')
    prior_exit = requests.read_json(Path(inputs['pendingDiagnosticRun'])/'exit.json')
    baseline_exit = requests.read_json(Path(inputs['baselineRun'])/'exit.json')
    profiles.require(datetime.fromisoformat(baseline_exit['startedUtc'].replace('Z','+00:00')) >
        datetime.fromisoformat(prior_exit['finishedUtc'].replace('Z','+00:00')), 'RECOVERY_BASELINE_NOT_AFTER_PENDING_DIAGNOSTIC')
    recovery = review['recovery']
    requests.exact_fields(recovery, {'source', 'backup', 'sha256'}, 'recovery')
    official = (Path(os.environ['USERPROFILE'])/'AppData/LocalLow/miHoYo/原神/BeyondLocal').resolve()
    profiles.require(Path(recovery['source']).is_absolute(), 'RECOVERY_SOURCE_ABSOLUTE_REQUIRED')
    target = Path(recovery['source']).resolve()
    relative = target.relative_to(official) if target.is_relative_to(official) else None
    level = str(value['levelId'])
    profiles.require(relative is not None and len(relative.parts) == 4 and relative.parts[0].isdigit() and
        relative.parts[1:] == ('Beyond_Local_Save_Level', level, level+'.gil'), 'RECOVERY_FORMAL_LEVEL_PATH')
    backup = requests.runtime_path(recovery['backup'])
    profiles.require(equal_files(target, backup) and profiles.sha256(target) == recovery['sha256'] and
        profiles.sha256(backup) == recovery['sha256'], 'RECOVERY_BYTES_CHANGED')
    profiles.require(digest == profiles.sha256(path), 'RECOVERY_REVIEW_CHANGED_DURING_VALIDATION')
    return {'review':review, 'reviewPath':str(path), 'reviewSha256':digest, 'value':value,
        'baselineRun':inputs['baselineRun'], 'runtimeProfilePath':inputs['runtimeProfilePath'],
        'targetGil':str(target), 'backup':str(backup), 'inputs':inputs}


def claim_review(validated, run):
    CLAIMS.mkdir(parents=True, exist_ok=True)
    review = validated['review']
    path = CLAIMS/(review['reviewId']+'.json')
    readonly.write_json(path, {'reviewId':review['reviewId'], 'reviewSha256':validated['reviewSha256'],
        'priorRawSha256':review['priorRawSha256'], 'action':candidate.ACTION, 'run':str(run),
        'tokenRefusalRawSha256':candidate.TOKEN_REFUSAL_RAW_SHA256,
        'pendingDiagnosticRawSha256':candidate.PENDING_DIAGNOSTIC_RAW_SHA256,
        'diagnosticOnly': review['diagnosticOnly'],
        'claimedUtc':utc_now().isoformat(), 'claim':'single-recovery-compilation-no-auto-retry'})
    return path


def prepare(review_path):
    validated = validate_review(review_path, minimum_remaining=TTL_SECONDS)
    review = validated['review']
    value, raw, runtime, profile, disk, inputs = candidate.load_inputs(
        review['priorRun'], review['baselineRun'], review['runtimeProfilePath'], review['tokenRefusalRun'],
        review['pendingDiagnosticRun'])
    prior, identity, original, _ = candidate.read_prior(review['priorRun'])
    refusal, _ = candidate.read_token_refusal(review['tokenRefusalRun'], prior, identity, original)
    pending, _ = candidate.read_pending_diagnostic(review['pendingDiagnosticRun'], prior, identity, original)
    session = profiles.validate_session(review['session'])
    kernel, user = profiles.windows_api()
    time_window(review, minimum_remaining=TTL_SECONDS)
    deadline = int(kernel.GetTickCount64()) + TTL_SECONDS * 1000
    message_id = int(user.RegisterWindowMessageW('Miliastra.BindingRecovery.' + secrets.token_hex(16)))
    profiles.require(0xc000 <= message_id <= 0xffff, 'RECOVERY_REGISTER_MESSAGE_FAILED')
    nonce = secrets.randbits(63) | 1
    run = readonly.output_directory(OUTPUT)
    claim = claim_review(validated, run)
    originals = candidate.source_copies(run)
    emit_header(run, value, raw, runtime, profile, prior, refusal, pending, session, deadline, message_id, nonce,
        diagnostic_only=review['diagnosticOnly'])
    (run / 'baseline-snapshot.bin').write_bytes(raw)
    (run / 'prior-receipt.bin').write_bytes(prior)
    (run / 'token-refusal-receipt.bin').write_bytes(refusal)
    (run / 'pending-diagnostic-receipt.bin').write_bytes(pending)
    (run / 'review.json').write_bytes(Path(validated['reviewPath']).read_bytes())
    contract = {'schemaVersion': 1, 'kind': 'template-binding-recovery-build-contract-v2',
        'action': candidate.ACTION, 'actionCode': 8, 'receiptVersion': 12,
        'compileOnly': False, 'launchable': False, 'allowWrites': not review['diagnosticOnly'], 'reviewed': True,
        'diagnosticOnly': review['diagnosticOnly'],
        'nativeCalled': False, 'probeExecuted': False, 'session': session, 'levelId': value['levelId'],
        'identity': value['identity'], 'nonce': nonce, 'deadline': deadline, 'messageId': message_id,
        'ttlSeconds': TTL_SECONDS, 'reviewId': review['reviewId'], 'reviewSha256': validated['reviewSha256'],
        'reviewClaimPath': str(claim), 'reviewExpiresUtc': review['expiresUtc'],
        'inputs': inputs, 'disk': disk, 'sourceHashes': review['sourceHashes'],
        'originalNativeSourceHashes': originals,
        'limits': ('Only capture the exact failed empty bag and edit state. No notify, close, token reuse or game writes.'
            if review['diagnosticOnly'] else 'Only notify and close the exact failed empty bag edit. No reattach, reference creation, setter, save or gameplay claim.')}
    readonly.write_json(run / 'build-contract.json', contract)
    compiler = candidate.compile_sources(run)
    current = validate_review(review_path)
    profiles.require(current['reviewSha256'] == validated['reviewSha256'], 'RECOVERY_REVIEW_CHANGED_DURING_BUILD')
    profiles.require(profiles.validate_session(review['session']) == session, 'RECOVERY_SESSION_CHANGED_DURING_BUILD')
    profiles.require(int(kernel.GetTickCount64()) < deadline, 'RECOVERY_BUILD_DEADLINE_EXPIRED')
    for relative, digest in originals.items():
        key = 'tools/game-executor/' + relative
        profiles.require(review['sourceHashes'][key] == digest, 'RECOVERY_COPIED_SOURCE_NOT_REVIEWED:' + key)
    prepared = dict(contract, kind='template-binding-recovery-prepared-v2', launchable=True, compiled=True,
        compiler=compiler, preparedAtUtc=utc_now().isoformat(), wrapperName='invoke-binding-recovery-probe.ps1')
    readonly.write_json(run / 'prepared.json', prepared)
    hashes = {str(p.relative_to(run)).replace('\\', '/'): profiles.sha256(p)
        for p in sorted(run.rglob('*')) if p.is_file()}
    wrapper = emit_wrapper(run, hashes, validated)
    hashes[wrapper.name] = profiles.sha256(wrapper)
    result = {'ok': True, 'schemaVersion': 1, 'kind': 'template-binding-recovery-build-v2',
        'run': str(run), 'action': candidate.ACTION, 'actionCode': 8, 'receiptVersion': 12,
        'compiled': True, 'compileOnly': False, 'launchable': True, 'allowWrites': not review['diagnosticOnly'],
        'diagnosticOnly': review['diagnosticOnly'],
        'reviewed': True, 'nativeCalled': False, 'probeExecuted': False,
        'reviewSha256': validated['reviewSha256'], 'deadline': deadline, 'nonce': nonce,
        'wrapperName': wrapper.name, 'hashes': hashes}
    readonly.write_json(run / 'build-result.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.review)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False, 'error':str(exc), 'launchable':False, 'nativeCalled':False}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def emit_header(run, request, raw, runtime, profile, prior_raw, token_refusal_raw, pending_diagnostic_raw, session, deadline, message_id, nonce,
                *, diagnostic_only=False):
    # Generate in the new run only. No previous candidate or live native file is edited.
    candidate.emit_header(run, request, raw, runtime, profile, prior_raw, token_refusal_raw, pending_diagnostic_raw,
        diagnostic_only=diagnostic_only)
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
        '// Dedicated exact partial-bag recovery: coordinator-reviewed evidence and fixed session, one 180-second attempt.')
    path.write_text(text, encoding='utf-8')


def emit_wrapper(run, artifacts, validated):
    review = validated['review']
    local_checks = ',\n'.join('        @(' + ps_literal(name) + ',' + ps_literal(digest) + ')'
                             for name, digest in artifacts.items())
    external = {validated['reviewPath']: validated['reviewSha256'],
        
        validated['runtimeProfilePath']: review['runtimeProfileSha256'],
        validated['targetGil']: review['recovery']['sha256'], validated['backup']: review['recovery']['sha256'],
        str(profiles.TARGET_IMAGE): profiles.load_profile()['image']['sha256']}
    external.update({str(candidate.ROOT / name): digest for name, digest in review['sourceHashes'].items()})
    external.update({str(Path(validated['baselineRun']) / name): digest for name, digest in review['evidenceHashes'].items()})
    external.update({str(Path(review['priorRun']) / name): digest for name, digest in review['priorEvidenceHashes'].items()})
    external.update({str(Path(review['tokenRefusalRun']) / name): digest for name, digest in review['tokenRefusalEvidenceHashes'].items()})
    external.update({str(Path(review['pendingDiagnosticRun']) / name): digest for name, digest in review['pendingDiagnosticEvidenceHashes'].items()})
    external_checks = ',\n'.join('        @(' + ps_literal(path) + ',' + ps_literal(digest) + ')'
                                for path, digest in external.items())
    text = r'''$ErrorActionPreference = 'Stop'
$taskRun = $PSScriptRoot
$taskDiagnosticOnly = __DIAGNOSTIC_ONLY__
$taskResult = [ordered]@{startedUtc=[DateTime]::UtcNow.ToString('o');wrapperPid=$PID;executed=$false;exitCode=$null;error=$null;scope=__SCOPE__;diagnosticOnly=$taskDiagnosticOnly;allowWrites=(-not $taskDiagnosticOnly);persistentSaveVerified=$false}
$taskOwnedClaim = $false
try {
    $taskClaim = [IO.File]::Open((Join-Path $taskRun 'launch.claim'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    $taskClaim.Dispose()
    $taskOwnedClaim = $true
    $taskPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $taskPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'NOT_ELEVATED' }
    $taskExpires = [DateTimeOffset]::Parse(__EXPIRES__).UtcDateTime
    if ([DateTime]::UtcNow -ge $taskExpires) { throw 'BINDING_REVIEW_EXPIRED' }
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
    if ($taskBuild.kind -ne 'template-binding-recovery-build-v2' -or -not $taskBuild.launchable -or $taskBuild.compileOnly -or $taskBuild.wrapperName -ne 'invoke-binding-recovery-probe.ps1') { throw 'DEDICATED_BUILD_REQUIRED' }
    if ($taskBuild.diagnosticOnly -isnot [bool] -or $taskBuild.diagnosticOnly -ne $taskDiagnosticOnly -or $taskBuild.allowWrites -isnot [bool] -or $taskBuild.allowWrites -ne (-not $taskDiagnosticOnly)) { throw 'RECOVERY_DIAGNOSTIC_CONTRACT_MISMATCH' }
    if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ine $taskBuild.hashes.'invoke-binding-recovery-probe.ps1') { throw 'WRAPPER_CHANGED' }
    if ([DateTime]::UtcNow -ge $taskExpires) { throw 'BINDING_REVIEW_EXPIRED' }
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
        if (-not $taskProbe.Start()) { throw 'BINDING_PROBE_START_FAILED' }
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
    text = text.replace('__DIAGNOSTIC_ONLY__', '$true' if review['diagnosticOnly'] else '$false')
    text = text.replace('__SCOPE__', ps_literal('FIXED_BINDING_RECOVERY_DIAGNOSTIC' if review['diagnosticOnly'] else 'FIXED_BINDING_RECOVERY_ACTION'))
    path = run / 'invoke-binding-recovery-probe.ps1'
    with path.open('x', encoding='utf-8-sig', newline='\n') as stream:
        stream.write(text)
    return path



if __name__ == '__main__':
    raise SystemExit(main())
