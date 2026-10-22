"""Version-gate fixtures, wholly under the repository; no process/IPC calls."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vector_release_tests', Path(__file__).with_name('release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / '.runtime/graph-vector-values/tests'
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.releases = self.root / 'releases'
        self.releases.mkdir()
        self.run = self.root / '.runtime/editor-bridge/runs' / str(uuid.uuid4())
        self.run.mkdir(parents=True)
        self.bridge = self.root / 'bridge.dll'
        self.bridge.write_bytes(b'offline fixture bridge, not an assembly')
        self.boot = self.root / 'bootstrap.dll'
        self.boot.write_bytes(b'offline fixture bootstrap, not an assembly')
        self.identity = dict(path=str(self.bridge), name='Miliastra.EditorBridge.Net8R999',
                             mvid=str(uuid.uuid4()), sha256=release.sha(self.bridge))
        self.settings = dict(pid=123, startUtcTicks='987654321', pipeName='fixture-only',
                             expectedExe=str(self.root / 'fixture.exe'),
                             expiresUtc=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())
        self.ready = dict(accepted=True, code=0, hostPid=123, hostStartUtcTicks='987654321',
                          settingsPid=123, settingsStartUtcTicks='987654321', pipeName='fixture-only',
                          settingsExpectedExe=self.settings['expectedExe'],
                          settingsExpiresUtc=self.settings['expiresUtc'],
                          bridgeAssembly=dict(self.identity, graphVector3Contract=1))
        self.frozen = dict(bridge=self.identity['sha256'], bootstrap=release.sha(self.boot))
        self.manifest = dict(kind='graph-vector3-bridge-release-v2', graphVector3Contract=1,
                             bridge=self.identity, bootstrap=dict(path=str(self.boot), sha256=release.sha(self.boot)),
                             sourceHashes={'source.cs': 'fixture-source-sha'},
                             sourceSetSha256=release.source_digest({'source.cs': 'fixture-source-sha'}))
        for name, value in [('ROOT', self.root), ('RELEASES', self.releases)]:
            p = patch.object(release, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(release, 'sources', return_value={'source.cs': 'fixture-source-sha'})
        self.sources = p.start()
        self.addCleanup(p.stop)

    def write(self):
        for name, data in [('bridge-settings.json', self.settings), ('bridge-ready.json', self.ready), ('frozen.json', self.frozen)]:
            (self.run / name).write_text(json.dumps(data), encoding='utf-8')
        release.manifest_path(self.identity['sha256'], self.manifest['sourceHashes']).write_text(json.dumps(self.manifest), encoding='utf-8')

    def rejected(self, code):
        self.write()
        with self.assertRaisesRegex(ValueError, code):
            release.verify_run(self.run)

    def test_valid_receipt_does_not_claim_gameplay(self):
        self.write()
        with patch.object(release.subprocess, 'run', side_effect=AssertionError('No subprocess or game calls allowed')):
            result = release.verify_run(self.run)
        self.assertTrue(result['ok'])
        self.assertFalse(result['runtimeVerified'])
        self.assertFalse(result['persistentSaveVerified'])

    def test_old_bridge_has_no_capability(self):
        self.ready.pop('bridgeAssembly')
        self.rejected('VECTOR_BRIDGE_CAPABILITY_NOT_LOADED')

    def test_loaded_old_mvid_despite_new_bytes(self):
        self.ready['bridgeAssembly']['mvid'] = str(uuid.uuid4())
        self.rejected('VECTOR_BRIDGE_LOADED_IDENTITY_MISMATCH')

    def test_replaced_disk_bytes(self):
        self.bridge.write_bytes(b'replaced newer bytes do not identify the loaded code')
        self.rejected('VECTOR_BRIDGE_FROZEN_BINARY_MISMATCH')

    def test_wrong_frozen_bootstrap(self):
        self.frozen['bootstrap'] = '0' * 64
        self.rejected('VECTOR_BRIDGE_FROZEN_BINARY_MISMATCH')

    def test_changed_source_requires_rebuild(self):
        self.sources.return_value = {'source.cs': 'changed'}
        self.rejected('VECTOR_BRIDGE_SOURCE_CHANGED_REBUILD_REQUIRED')

    def test_wrong_process_start_identity(self):
        self.ready['hostStartUtcTicks'] = '987654322'
        self.rejected('VECTOR_BRIDGE_HOST_IDENTITY_MISMATCH')

    def test_copied_ready_from_another_pipe(self):
        self.ready['pipeName'] = 'other-run'
        self.rejected('VECTOR_BRIDGE_SCOPE_MISMATCH')

    def test_expired_lease(self):
        self.settings['expiresUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.rejected('VECTOR_RUN_EXPIRED_OR_CLOSED')

    def test_closed_lease(self):
        (self.run / 'lease-closed.json').write_text('{}')
        self.rejected('VECTOR_RUN_EXPIRED_OR_CLOSED')

    def test_unaccepted_ready(self):
        self.ready['accepted'] = False
        self.rejected('VECTOR_BRIDGE_NOT_ACCEPTED')

    def test_missing_frozen_manifest(self):
        self.write()
        release.manifest_path(self.identity['sha256'], self.manifest['sourceHashes']).unlink()
        with self.assertRaises(FileNotFoundError):
            release.verify_run(self.run)

    def test_alias_run_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'VECTOR_RUN_PATH_INVALID'):
            release.verify_run(self.root / 'fake-run')

    def closure(self, run=None, **updates):
        value = dict(pid=123, cleanupSucceeded=True, cleanupError=None, hostProcessTerminated=False)
        value.update(updates)
        ((run or self.run) / 'lease-closed.json').write_text(json.dumps(value), encoding='utf-8')

    def test_clean_renewal_returns_load_contract_without_dispatch(self):
        self.settings['expiresUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.ready['settingsExpiresUtc'] = self.settings['expiresUtc']
        self.write()
        self.closure()
        with patch.object(release.subprocess, 'run', side_effect=AssertionError('Do not load')):
            result = release.renewal_status(self.run)
        self.assertTrue(result['sameRevisionReusable'])
        self.assertTrue(result['nativeStartStillRequired'])
        self.assertTrue(result['exclusiveOwnerRequired'])
        self.assertEqual(result['loadArgv'][-3:], ['load', '--target-pid', '123'])

    def test_expiry_without_cleanup_is_not_renewable(self):
        self.settings['expiresUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.ready['settingsExpiresUtc'] = self.settings['expiresUtc']
        self.write()
        with self.assertRaisesRegex(ValueError, 'VECTOR_RENEWAL_CLEANUP_NOT_RECORDED'):
            release.renewal_status(self.run)

    def test_failed_cleanup_is_not_renewable(self):
        self.write()
        self.closure(cleanupSucceeded=False, cleanupError='InvalidOperationException')
        with self.assertRaisesRegex(ValueError, 'VECTOR_RENEWAL_CLEANUP_FAILED_OR_UNKNOWN'):
            release.renewal_status(self.run)

    def sibling(self, *, ready=True, same_host=True):
        path = self.run.parent / str(uuid.uuid4())
        path.mkdir()
        settings = dict(self.settings)
        if not same_host:
            settings['startUtcTicks'] = 'other-host-start'
        (path / 'bridge-settings.json').write_text(json.dumps(settings), encoding='utf-8')
        if ready:
            (path / 'bridge-ready.json').write_text(json.dumps({'accepted': True}), encoding='utf-8')
        else:
            (path / 'loader.claim').write_text('')
        return path

    def test_another_active_scope_blocks_renewal(self):
        self.write()
        self.closure()
        self.sibling()
        with self.assertRaisesRegex(ValueError, 'VECTOR_RENEWAL_OTHER_SCOPE_NOT_CLEAN'):
            release.renewal_status(self.run)

    def test_unknown_load_blocks_renewal(self):
        self.write()
        self.closure()
        self.sibling(ready=False)
        with self.assertRaisesRegex(ValueError, 'VECTOR_RENEWAL_OTHER_LOAD_UNRESOLVED'):
            release.renewal_status(self.run)

    def test_malformed_ready_is_unknown_not_rejected(self):
        self.write()
        self.closure()
        other = self.sibling()
        (other / 'bridge-ready.json').write_text('{"accepted":null}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'VECTOR_RENEWAL_OTHER_LOAD_UNRESOLVED'):
            release.renewal_status(self.run)

    def test_old_clean_scopes_and_other_hosts_are_not_active(self):
        self.write()
        self.closure()
        self.closure(self.sibling())
        self.sibling(same_host=False)
        self.assertTrue(release.renewal_status(self.run)['ok'])

    def test_manifest_identity_includes_source_set(self):
        a = release.manifest_path(self.identity['sha256'], {'code': 'a'})
        b = release.manifest_path(self.identity['sha256'], {'code': 'b'})
        self.assertNotEqual(a, b)


if __name__ == '__main__':
    unittest.main()
