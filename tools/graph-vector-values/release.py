"""Offline bridge freeze and exact in-process revision verification, no injection."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = ROOT / '.runtime/graph-vector-values'
RELEASES = BASE / 'releases'
IDENTITY_DLL = BASE / 'identity/Identity.dll'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(path):
    p = Path(path).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError('VECTOR_RELEASE_PATH_OUTSIDE_PROJECT')
    return p


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sources():
    paths = list((ROOT / 'tools/editor-bridge/Adapter').glob('*.cs'))
    paths += list((ROOT / 'tools/editor-bridge/ManagedBridge').glob('*.cs'))
    paths += list((ROOT / 'tools/editor-bridge/Bootstrap').glob('*.cs'))
    paths += [ROOT / p for p in (
        'tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj',
        'tools/editor-bridge/Bootstrap/Bootstrap.csproj',
        'tools/editor-bridge/bridge_host.py', 'tools/editor-bridge/new-scope.ps1',
        'tools/editor-bridge/load-bridge.ps1', 'tools/editor-bridge/next-revision.ps1',
        'tools/graph-vector-values/release.py', 'tools/graph-vector-values/identity/Program.cs',
        'tools/graph-vector-values/identity/Identity.csproj')]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def source_digest(source_hashes):
    return hashlib.sha256(json.dumps(source_hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def manifest_path(bridge_sha, source_hashes):
    # Comments or loader-only changes may leave the deterministic DLL identical.
    # Preserve every prior freeze instead of overwriting it or claiming its old
    # source set matches. Both dimensions identify this immutable release.
    return RELEASES / (bridge_sha + '-' + source_digest(source_hashes)[:16] + '.json')


def identity(path):
    """Compile the tiny metadata-only reader locally if absent, then read PE."""
    env = os.environ.copy()
    tmp = BASE / 'build-temp'
    tmp.mkdir(parents=True, exist_ok=True)
    env.update(TEMP=str(tmp), TMP=str(tmp), DOTNET_CLI_HOME=str(BASE / 'dotnet-home'),
        DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false',
        DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1')
    reader_sources = {str(p.relative_to(ROOT)): sha(p) for p in (HERE / 'identity').glob('*') if p.is_file()}
    stamp = IDENTITY_DLL.parent / 'source-hashes.json'
    if not IDENTITY_DLL.is_file() or not stamp.is_file() or read(stamp) != reader_sources:
        result = subprocess.run(['dotnet', 'build', str(HERE / 'identity/Identity.csproj'),
            '--ignore-failed-sources', '-p:NuGetAudit=false', '-o', str(IDENTITY_DLL.parent), '--nologo'],
            cwd=ROOT, env=env, capture_output=True, timeout=120)
        IDENTITY_DLL.parent.mkdir(parents=True, exist_ok=True)
        (IDENTITY_DLL.parent / 'build.stdout').write_bytes(result.stdout)
        (IDENTITY_DLL.parent / 'build.stderr').write_bytes(result.stderr)
        if result.returncode or not IDENTITY_DLL.is_file():
            raise ValueError('VECTOR_IDENTITY_READER_BUILD_FAILED')
        stamp.write_text(json.dumps(reader_sources, sort_keys=True), encoding='utf-8')
    result = subprocess.run(['dotnet', str(IDENTITY_DLL), str(local(path))],
        cwd=ROOT, env=env, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('VECTOR_IDENTITY_READER_FAILED')
    return json.loads(result.stdout.decode('utf-8-sig'))


def freeze(bridge, bootstrap):
    bridge, bootstrap = local(bridge), local(bootstrap)
    before = sources()
    b, boot = identity(bridge), identity(bootstrap)
    if sources() != before:
        raise ValueError('VECTOR_RELEASE_SOURCE_CHANGED_DURING_FREEZE')
    if sorted(b['vectorMethods']) != sorted(['AuthorVectorPayload', 'AuthorWriteVector3', 'AuthorReadVector3', 'AuthorRunVectorWrite']):
        raise ValueError('VECTOR_RELEASE_METHODS_MISSING')
    project = (ROOT / 'tools/editor-bridge/ManagedBridge/Miliastra.EditorBridge.csproj').read_text(encoding='utf-8')
    name = re.search(r'<AssemblyName>([^<]+)</AssemblyName>', project).group(1)
    if b['name'] != name or not re.fullmatch(r'Miliastra\.EditorBridge\.Net8R[0-9]+', name):
        raise ValueError('VECTOR_RELEASE_REVISION_MISMATCH')
    if boot['name'] != name.replace('EditorBridge', 'Bootstrap'):
        raise ValueError('VECTOR_RELEASE_BOOTSTRAP_REVISION_MISMATCH')
    if sha(bridge) != b['sha256'] or sha(bootstrap) != boot['sha256']:
        raise ValueError('VECTOR_RELEASE_BINARY_CHANGED')
    value = {'kind': 'graph-vector3-bridge-release-v2', 'graphVector3Contract': 1,
        'bridge': b, 'bootstrap': boot, 'sourceHashes': before,
        'sourceSetSha256': source_digest(before),
        'frozenUtc': datetime.now(timezone.utc).isoformat(),
        'loaded': False, 'runtimeVerified': False}
    RELEASES.mkdir(parents=True, exist_ok=True)
    path = manifest_path(b['sha256'], before)
    if path.exists():
        old = read(path)
        if any(old.get(k) != value[k] for k in ('bridge', 'bootstrap', 'sourceHashes')):
            raise ValueError('VECTOR_RELEASE_MANIFEST_CONFLICT')
    else:
        with path.open('x', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
    return {'ok': True, 'manifest': str(path), 'bridge': b, 'bootstrap': boot,
            'loaded': False, 'runtimeVerified': False}


def _verify_run(run_dir, *, allow_closed=False):
    """No IPC/process probe: verify a fresh native-ready receipt against frozen PE.

    The ordinary author transport separately rechecks live process identity,
    lease and nonce. This adds code-version evidence before a vector dispatch.
    """
    run_dir = local(run_dir)
    runs = ROOT / '.runtime/editor-bridge/runs'
    if run_dir.parent != runs or str(uuid.UUID(run_dir.name)) != run_dir.name:
        raise ValueError('VECTOR_RUN_PATH_INVALID')
    settings = read(run_dir / 'bridge-settings.json')
    ready = read(run_dir / 'bridge-ready.json')
    frozen = read(run_dir / 'frozen.json')
    expiry = datetime.fromisoformat(settings['expiresUtc'].replace('Z', '+00:00'))
    if expiry.tzinfo is None or (not allow_closed and
            (expiry <= datetime.now(timezone.utc) or (run_dir / 'lease-closed.json').exists())):
        raise ValueError('VECTOR_RUN_EXPIRED_OR_CLOSED')
    if ready.get('accepted') is not True or ready.get('code') != 0:
        raise ValueError('VECTOR_BRIDGE_NOT_ACCEPTED')
    if ready.get('hostPid') != settings['pid'] or str(ready.get('hostStartUtcTicks')) != str(settings['startUtcTicks']):
        raise ValueError('VECTOR_BRIDGE_HOST_IDENTITY_MISMATCH')
    if (ready.get('pipeName') != settings['pipeName'] or ready.get('settingsPid') != settings['pid'] or
            str(ready.get('settingsStartUtcTicks')) != str(settings['startUtcTicks']) or
            ready.get('settingsExpectedExe') != settings['expectedExe'] or
            datetime.fromisoformat(ready['settingsExpiresUtc'].replace('Z', '+00:00')) != expiry):
        raise ValueError('VECTOR_BRIDGE_SCOPE_MISMATCH')
    actual = ready.get('bridgeAssembly')
    if not isinstance(actual, dict) or actual.get('graphVector3Contract') != 1:
        raise ValueError('VECTOR_BRIDGE_CAPABILITY_NOT_LOADED')
    digest = str(actual.get('sha256', '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('VECTOR_BRIDGE_HASH_INVALID')
    current_sources = sources()
    release_path = manifest_path(digest, current_sources)
    if not release_path.exists() and list(RELEASES.glob(digest + '*.json')):
        raise ValueError('VECTOR_BRIDGE_SOURCE_CHANGED_REBUILD_REQUIRED')
    manifest = read(release_path)
    if (manifest.get('kind') != 'graph-vector3-bridge-release-v2' or manifest.get('graphVector3Contract') != 1 or
            manifest.get('sourceSetSha256') != source_digest(current_sources)):
        raise ValueError('VECTOR_RELEASE_MANIFEST_INVALID')
    expected = manifest['bridge']
    if any(actual.get(k) != expected.get(k) for k in ('name', 'mvid')) or local(actual['path']) != local(expected['path']):
        raise ValueError('VECTOR_BRIDGE_LOADED_IDENTITY_MISMATCH')
    if (str(frozen.get('bridge', '')).lower() != digest or expected['sha256'] != digest or
            sha(local(expected['path'])) != digest or
            str(frozen.get('bootstrap', '')).lower() != manifest['bootstrap']['sha256'] or
            sha(local(manifest['bootstrap']['path'])) != manifest['bootstrap']['sha256']):
        raise ValueError('VECTOR_BRIDGE_FROZEN_BINARY_MISMATCH')
    if current_sources != manifest['sourceHashes']:
        raise ValueError('VECTOR_BRIDGE_SOURCE_CHANGED_REBUILD_REQUIRED')
    return {'ok': True, 'evidence': 'native-ready-loaded-assembly-identity',
            'runId': run_dir.name, 'bridge': actual,
            'persistentSaveVerified': False, 'runtimeVerified': False}


def verify_run(run_dir):
    return _verify_run(run_dir)


def _clean_closure(path, pid):
    closed = read(path)
    return (closed.get('pid') == pid and closed.get('cleanupSucceeded') is True and
            closed.get('hostProcessTerminated') is False and closed.get('cleanupError') is None)


def renewal_status(run_dir):
    """Read-only prerequisites for an exclusive owner's one fresh-scope load.

    This does not stop a worker, wait, mint a scope, load code, or bypass Entry's
    final IsCompleted check. Closure-file publication precedes that final flag;
    the native Start result is authoritative. Unknown outcomes are not replayed.
    """
    identity = _verify_run(run_dir, allow_closed=True)
    run_dir = local(run_dir)
    settings = read(run_dir / 'bridge-settings.json')
    closure = run_dir / 'lease-closed.json'
    if not closure.exists():
        raise ValueError('VECTOR_RENEWAL_CLEANUP_NOT_RECORDED')
    if not _clean_closure(closure, settings['pid']):
        raise ValueError('VECTOR_RENEWAL_CLEANUP_FAILED_OR_UNKNOWN')
    for other in run_dir.parent.iterdir():
        if other == run_dir or not other.is_dir():
            continue
        try:
            sibling = read(other / 'bridge-settings.json')
        except FileNotFoundError:
            continue
        if (sibling.get('pid') != settings['pid'] or
                str(sibling.get('startUtcTicks')) != str(settings['startUtcTicks'])):
            continue
        ready_path = other / 'bridge-ready.json'
        if not ready_path.exists():
            if (other / 'loader.claim').exists():
                raise ValueError('VECTOR_RENEWAL_OTHER_LOAD_UNRESOLVED:' + other.name)
            continue
        ready = read(ready_path)
        if ready.get('accepted') is False:
            continue
        if ready.get('accepted') is not True:
            raise ValueError('VECTOR_RENEWAL_OTHER_LOAD_UNRESOLVED:' + other.name)
        closed_path = other / 'lease-closed.json'
        if not closed_path.exists() or not _clean_closure(closed_path, settings['pid']):
            raise ValueError('VECTOR_RENEWAL_OTHER_SCOPE_NOT_CLEAN:' + other.name)
    return dict(identity, evidence='clean-closure-and-frozen-code-prerequisites-only',
        previousRunId=run_dir.name, cleanupRecorded=True, sameRevisionReusable=True,
        exclusiveOwnerRequired=True, nativeStartStillRequired=True, actualProcessProbed=False,
        targetPid=settings['pid'], targetStartUtcTicks=str(settings['startUtcTicks']),
        loadArgv=['python', '-B', str(ROOT / 'tools/editor-bridge/elevated-request.py'),
                  'load', '--target-pid', str(settings['pid'])],
        nextStep='One load request under the existing exclusive owner, then verify its fresh runId; do not replay uncertain loads')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--bridge', required=True)
    p.add_argument('--bootstrap', required=True)
    p = sub.add_parser('verify-run')
    p.add_argument('--run-id', required=True)
    p = sub.add_parser('renewal-status')
    p.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'freeze':
            value = freeze(args.bridge, args.bootstrap)
        else:
            run_dir = ROOT / '.runtime/editor-bridge/runs' / str(uuid.UUID(args.run_id))
            value = verify_run(run_dir) if args.command == 'verify-run' else renewal_status(run_dir)
        print(json.dumps(value, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
