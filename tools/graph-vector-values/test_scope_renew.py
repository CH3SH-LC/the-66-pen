"""Private filesystem helper fixtures; production renew/release/queue paths execute.

No editor process, real queue, actual injection or game connection. The helper's
native outputs and process identity are explicit stubs; failed cleanup stays failed.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('production_scope_renew_tests', HERE / 'scope_renew.py')
renewal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renewal)


class RenewalTests(unittest.TestCase):
    def setUp(self):
        # Keep below Windows MAX_PATH even with nested production run/journal paths.
        parent = ROOT / '.runtime/gvt'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.here = self.root / 'tools/graph-vector-values'
        self.here.mkdir(parents=True)
        self.transport_path = self.root / 'tools/editor-bridge/elevated-request.py'
        self.transport_path.parent.mkdir(parents=True)
        for name in ('scope_renew.py', 'release.py'):
            shutil.copyfile(HERE / name, self.here / name)
        shutil.copyfile(ROOT / 'tools/editor-bridge/elevated-request.py', self.transport_path)
        self.runs = self.root / '.runtime/editor-bridge/runs'
        self.runs.mkdir(parents=True)
        self.base = self.root / '.runtime/graph-vector-values/renewals'
        self.queue = self.root / '.runtime/editor-bridge/private-queue'
        self.queue.mkdir()
        self.session = self.root / 'game-session.json'
        self.dump(self.session, dict(gamePid=456, gameStart='fixture-game-start'))
        self.bridge = self.root / 'bridge.dll'
        self.bridge.write_bytes(b'private identity fixture, not a PE assembly')
        self.bootstrap = self.root / 'bootstrap.dll'
        self.bootstrap.write_bytes(b'private bootstrap fixture')
        self.identity = dict(name='Miliastra.EditorBridge.Net8R300', mvid=str(uuid.uuid4()),
                             path=str(self.bridge), sha256=renewal._hash(self.bridge), graphVector3Contract=1)
        self.settings = dict(pid=123, startUtcTicks='987654321', expectedExe=str(self.root / 'TestHost.exe'),
                             expiresUtc=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat(),
                             nonce=uuid.uuid4().hex, pipeName='private-fixture-' + uuid.uuid4().hex)
        self.old = str(uuid.uuid4())
        self.write_scope(self.old, self.settings)
        releases = self.root / 'releases'
        releases.mkdir()
        for module, values in ((renewal, dict(ROOT=self.root, HERE=self.here, RUNS=self.runs,
                                             BASE=self.base, TRANSPORT=self.transport_path)),
                               (renewal.release, dict(ROOT=self.root, RELEASES=releases))):
            for name, value in values.items():
                p = patch.object(module, name, value)
                p.start()
                self.addCleanup(p.stop)
        p = patch.object(renewal.release, 'sources', return_value={'source.cs': 'private-fixture'})
        p.start()
        self.addCleanup(p.stop)
        self.dump(renewal.release.manifest_path(self.identity['sha256'], renewal.release.sources()),
                  dict(kind='graph-vector3-bridge-release-v2', graphVector3Contract=1,
                       bridge=self.identity, bootstrap=dict(path=str(self.bootstrap), sha256=renewal._hash(self.bootstrap)),
                       sourceHashes=renewal.release.sources(),
                       sourceSetSha256=renewal.release.source_digest(renewal.release.sources())))
        p = patch.object(renewal, '_process_identity', return_value={k: self.settings[k] for k in
                                                                   ('pid', 'startUtcTicks', 'expectedExe')})
        self.process = p.start()
        self.addCleanup(p.stop)
        self.args = dict(target_pid=123, target_start_ticks='987654321', queue_dir=str(self.queue),
                         game_session=str(self.session), owner_id='private-test-leader', exclusive=True, timeout=0)
        self.mode = 'ok'
        self.calls = []
        self.fresh = None
        self.pending = {}
        actual_module = renewal._module

        def module(path):
            tool = actual_module(path)
            if Path(path) == self.transport_path:
                actual_send = tool.send

                def send(payload, timeout, request_id):
                    # REAL production transport persists its single-use submission
                    # and request files in this isolated queue before helper stub runs.
                    actual_send(payload, timeout=0, request_id=request_id)
                    self.calls.append((payload, request_id))
                    self.helper(payload, request_id)
                    return tool.poll_request(request_id, timeout=0)
                tool.send = send
            return tool

        p = patch.object(renewal, '_module', side_effect=module)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def dump(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def write_scope(self, run, settings=None, identity=None):
        settings = settings or dict(self.settings, nonce=uuid.uuid4().hex, pipeName='private-new-' + uuid.uuid4().hex,
                                   expiresUtc=(datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat())
        path = self.runs / run
        path.mkdir(exist_ok=True)
        self.dump(path / 'bridge-settings.json', settings)
        self.dump(path / 'bridge-ready.json', dict(accepted=True, code=0,
                  hostPid=settings['pid'], settingsPid=settings['pid'],
                  hostStartUtcTicks=settings['startUtcTicks'], settingsStartUtcTicks=settings['startUtcTicks'],
                  pipeName=settings['pipeName'], settingsExpectedExe=settings['expectedExe'],
                  settingsExpiresUtc=settings['expiresUtc'], bridgeAssembly=identity or self.identity))
        self.dump(path / 'frozen.json', dict(bridge=self.identity['sha256'], bootstrap=renewal._hash(self.bootstrap)))
        return path

    def close(self, run=None, **changes):
        value = dict(pid=123, cleanupSucceeded=True, cleanupError=None, hostProcessTerminated=False)
        value.update(changes)
        self.dump(self.runs / (run or self.old) / 'lease-closed.json', value)

    def helper(self, payload, request_id):
        if payload['kind'] == 'call':
            self.assertEqual(payload, dict(kind='call', runId=self.old, op='stop'))
            reply = dict(ok=True, op='stop', stopped=True, cleanupComplete=False, hostProcessTerminated=False)
            if self.mode == 'cleanup_failed':
                self.close(cleanupSucceeded=False, cleanupError='real fixture failure remains failure')
            elif self.mode != 'no_cleanup':
                self.close()
            if self.mode == 'stop_rejected':
                reply = dict(ok=False, error='SCOPE_EXPIRED')
            if self.mode == 'stop_claim_unknown':
                # Simulate caller crash between intent/claim and helper submission.
                (self.queue / (request_id + '.request.json')).unlink()
            if self.mode in ('stop_unknown', 'stop_claim_unknown'):
                self.pending[request_id] = reply
                return
        else:
            self.assertEqual(payload, dict(kind='load', targetPid=123))
            self.fresh = str(uuid.uuid4())
            path = self.write_scope(self.fresh)
            reply = dict(kind='load', runId=self.fresh, readyFilePresent=True, accepted=True)
            if self.mode == 'load_rejected':
                reply['accepted'] = False
            elif self.mode == 'load_old_run':
                reply['runId'] = self.old
            elif self.mode == 'load_wrong_pid':
                self.write_scope(self.fresh, dict(self.settings, pid=124))
            elif self.mode == 'load_reused_nonce':
                data = renewal._read(path / 'bridge-settings.json')
                data['nonce'] = self.settings['nonce']
                self.dump(path / 'bridge-settings.json', data)
            elif self.mode == 'load_reused_pipe':
                data = renewal._read(path / 'bridge-settings.json')
                data['pipeName'] = self.settings['pipeName']
                self.write_scope(self.fresh, data)
            elif self.mode == 'load_wrong_mvid':
                self.write_scope(self.fresh, identity=dict(self.identity, mvid=str(uuid.uuid4())))
            elif self.mode == 'load_no_ready':
                (path / 'bridge-ready.json').unlink()
            elif self.mode == 'load_unknown':
                self.pending[request_id] = reply
                return
            elif self.mode == 'session_changed_on_load':
                self.dump(self.session, dict(changed=True))
        self.dump(self.queue / (request_id + '.response.json'), reply)

    def run_renew(self, **changes):
        return renewal.renew(self.old, **dict(self.args, **changes))

    def journal(self):
        return renewal._read(self.base / self.old / 'journal.json')

    def resolve_pending(self):
        for request_id, receipt in self.pending.items():
            self.dump(self.queue / (request_id + '.response.json'), receipt)
        self.pending.clear()

    def assertBlocked(self, code, **changes):
        result = self.run_renew(**changes)
        self.assertFalse(result['ok'], result)
        self.assertIn(code, result['code'], result)
        return result

    def test_active_scope_stop_cleanup_load_real_transport(self):
        before = self.session.read_bytes()
        result = self.run_renew()
        self.assertTrue(result['ok'], result)
        self.assertEqual([p['kind'] for p, _ in self.calls], ['call', 'load'])
        self.assertEqual(len(list(self.queue.glob('*.submission.json'))), 2)
        self.assertEqual(set(result['requestIds']), {'stop', 'load'})
        self.assertEqual(result['run'], self.fresh)
        self.assertEqual(result['runDirectory'], str(self.runs / self.fresh))
        ready = renewal._read(Path(result['readyPath']))
        self.assertEqual(result['bridgePipe'], ready['pipeName'])
        self.assertEqual(result['readyExpires'], ready['settingsExpiresUtc'])
        self.assertEqual(result['queue'], str(self.queue))
        self.assertEqual(result['session'], str(self.session))
        self.assertEqual(self.session.read_bytes(), before)
        self.assertFalse(result['runtimeVerified'])
        self.assertFalse(result['hostProcessTerminated'])
        self.assertEqual(self.journal()['requests']['load']['lastReceipt'].keys(),
                         {'kind', 'runId', 'readyFilePresent', 'accepted'})

    def test_closed_scope_only_load(self):
        self.close()
        result = self.run_renew()
        self.assertTrue(result['ok'], result)
        self.assertEqual([p['kind'] for p, _ in self.calls], ['load'])

    def test_stop_unknown_never_load_even_with_clean_closure_then_observe(self):
        self.mode = 'stop_unknown'
        first = self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        self.assertTrue(first['pending'])
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        self.assertEqual(len(self.calls), 1)
        self.resolve_pending()
        self.mode = 'ok'
        result = self.run_renew()
        self.assertTrue(result['ok'], result)
        self.assertEqual(first['requestIds'], result['requestIds'])
        self.assertEqual(len(self.calls), 2)

    def test_load_unknown_observes_same_request_no_second_scope(self):
        self.mode = 'load_unknown'
        first = self.assertBlocked('LOAD_OUTCOME_UNKNOWN')
        self.assertBlocked('LOAD_OUTCOME_UNKNOWN')
        self.assertEqual(len(self.calls), 2)
        self.resolve_pending()
        result = self.run_renew()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['requestIds'], first['requestIds'])
        self.assertEqual(len(self.calls), 2)

    def test_cleanup_pending_later_completes_without_second_stop(self):
        self.mode = 'no_cleanup'
        self.assertBlocked('CLEANUP_PENDING')
        self.assertBlocked('CLEANUP_PENDING')
        self.assertEqual(len(self.calls), 1)
        self.close()
        self.mode = 'ok'
        self.assertTrue(self.run_renew()['ok'])
        self.assertEqual(len(self.calls), 2)

    def test_cleanup_failed_refuses_load_and_is_not_mocked_success(self):
        self.mode = 'cleanup_failed'
        self.assertBlocked('CLEANUP_FAILED_OR_UNKNOWN')
        self.assertBlocked('CLEANUP_FAILED_OR_UNKNOWN')
        self.assertEqual(len(self.calls), 1)

    def test_already_failed_closure_no_dispatch(self):
        self.close(cleanupSucceeded=False, cleanupError='dispatcher failed')
        self.assertBlocked('CLEANUP_FAILED_OR_UNKNOWN')
        self.assertEqual(self.calls, [])

    def test_expired_without_closure_waits_without_stop_or_load(self):
        self.settings['expiresUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.write_scope(self.old, self.settings)
        self.assertBlocked('CLEANUP_PENDING')
        self.assertEqual(self.calls, [])
        self.close()
        self.assertTrue(self.run_renew()['ok'])
        self.assertEqual(len(self.calls), 1)

    def test_other_active_scope_refuses_stop(self):
        self.write_scope(str(uuid.uuid4()))
        self.assertBlocked('OTHER_SCOPE_NOT_CLEAN')
        self.assertEqual(self.calls, [])

    def test_other_unknown_loader_refuses(self):
        path = self.write_scope(str(uuid.uuid4()))
        (path / 'bridge-ready.json').unlink()
        (path / 'loader.claim').write_text('')
        self.assertBlocked('OTHER_LOAD_UNRESOLVED')
        self.assertEqual(self.calls, [])

    def test_other_closed_scope_allowed(self):
        other = str(uuid.uuid4())
        self.write_scope(other)
        self.close(other)
        self.assertTrue(self.run_renew()['ok'])

    def test_pending_other_queue_call_refuses(self):
        self.dump(self.queue / (uuid.uuid4().hex + '.submission.json'), dict(kind='call', runId=self.old, op='ping'))
        self.assertBlocked('QUEUE_OPERATION_UNRESOLVED')
        self.assertEqual(self.calls, [])

    def test_wrong_pid_start_rejected_before_dispatch(self):
        self.assertBlocked('OLD_HOST_BINDING_MISMATCH', target_pid=124)
        self.assertBlocked('OLD_HOST_BINDING_MISMATCH', target_start_ticks='987654322')
        self.assertEqual(self.calls, [])

    def test_live_pid_reuse_refused(self):
        self.process.return_value = dict(pid=123, startUtcTicks='999', expectedExe=self.settings['expectedExe'])
        self.assertBlocked('LIVE_PROCESS_IDENTITY_CHANGED')
        self.assertEqual(self.calls, [])

    def test_owner_assertion_required(self):
        self.assertBlocked('EXCLUSIVE_QUIESCED_OWNER_REQUIRED', exclusive=False)
        self.assertEqual(self.calls, [])

    def test_owner_change_refused_after_unknown(self):
        self.mode = 'load_unknown'
        self.assertBlocked('LOAD_OUTCOME_UNKNOWN')
        self.assertBlocked('OWNED_BY_ANOTHER_OWNER', owner_id='another-owner')
        self.assertEqual(len(self.calls), 2)

    def test_queue_binding_change_refused(self):
        self.mode = 'stop_unknown'
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        other = self.queue.with_name('other-private-queue')
        other.mkdir()
        self.assertBlocked('BINDING_CHANGED', queue_dir=str(other))
        self.assertEqual(len(self.calls), 1)

    def test_session_binding_change_refused(self):
        self.mode = 'stop_unknown'
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        self.dump(self.session, dict(changed=True))
        self.assertBlocked('BINDING_CHANGED')
        self.assertEqual(len(self.calls), 1)

    def test_source_change_refuses_resume(self):
        self.mode = 'stop_unknown'
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        with (self.here / 'scope_renew.py').open('a') as stream:
            stream.write('\n# fixture changed\n')
        self.assertBlocked('SOURCE_CHANGED')
        self.assertEqual(len(self.calls), 1)

    def test_same_owner_different_old_run_cannot_abandon_unknown(self):
        self.mode = 'load_unknown'
        self.assertBlocked('LOAD_OUTCOME_UNKNOWN')
        result = renewal.renew(self.fresh, **self.args)
        self.assertFalse(result['ok'])
        self.assertIn('HOST_HAS_OTHER_ATTEMPT', result['code'])
        self.assertEqual(len(self.calls), 2)

    def test_completed_reobservation_no_extra_dispatch(self):
        first = self.run_renew()
        second = self.run_renew()
        self.assertTrue(second['ok'], second)
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 2)

    def test_completed_but_fresh_later_expired_is_not_ok(self):
        self.assertTrue(self.run_renew()['ok'])
        path = self.runs / self.fresh
        settings = renewal._read(path / 'bridge-settings.json')
        settings['expiresUtc'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.write_scope(self.fresh, settings)
        self.assertBlocked('VECTOR_RUN_EXPIRED_OR_CLOSED')
        self.assertEqual(len(self.calls), 2)

    def test_completed_but_fresh_later_closed_is_not_ok(self):
        self.assertTrue(self.run_renew()['ok'])
        self.close(self.fresh)
        self.assertBlocked('VECTOR_RUN_EXPIRED_OR_CLOSED')
        self.assertEqual(len(self.calls), 2)

    def test_chained_renewal_same_owner_transfers_head(self):
        self.assertTrue(self.run_renew()['ok'])
        self.old = self.fresh
        self.settings = renewal._read(self.runs / self.old / 'bridge-settings.json')
        self.assertTrue(self.run_renew()['ok'])
        self.assertEqual(len(self.calls), 4)

    def test_chain_must_preserve_queue_and_game_session(self):
        self.assertTrue(self.run_renew()['ok'])
        self.old = self.fresh
        other = self.queue.with_name('other-chain-queue')
        other.mkdir()
        self.assertBlocked('CHAIN_BINDING_CHANGED', queue_dir=str(other))
        self.assertEqual(len(self.calls), 2)

    def test_completed_old_closure_changed_is_not_ok(self):
        self.assertTrue(self.run_renew()['ok'])
        self.close(extra='changed file bytes')
        self.assertBlocked('OLD_CLOSURE_CHANGED')
        self.assertEqual(len(self.calls), 2)

    def test_partial_closure_waits_without_sending_stop(self):
        (self.runs / self.old / 'lease-closed.json').write_text('{')
        self.assertBlocked('CLEANUP_PENDING')
        self.assertEqual(len(self.calls), 0)
        self.close()
        self.assertTrue(self.run_renew()['ok'])
        self.assertEqual(len(self.calls), 1)

    def test_process_changed_before_load_is_not_dispatched(self):
        expected = {k: self.settings[k] for k in ('pid', 'startUtcTicks', 'expectedExe')}
        self.process.side_effect = [expected, dict(expected, startUtcTicks='999')]
        self.assertBlocked('LIVE_PROCESS_IDENTITY_CHANGED')
        self.assertEqual([p['kind'] for p, _ in self.calls], ['call'])

    def test_relative_paths_always_resolve_from_project_root(self):
        result = self.run_renew(queue_dir=str(self.queue.relative_to(self.root)), game_session='game-session.json')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['queue'], str(self.queue))
        self.assertEqual(result['session'], str(self.session))

    def test_pre_submission_unknown_is_observed_not_replayed(self):
        self.mode = 'stop_claim_unknown'
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        self.assertBlocked('STOP_OUTCOME_UNKNOWN')
        self.assertEqual(len(self.calls), 1)

    def test_stop_rejected_does_not_load_or_repeat(self):
        self.mode = 'stop_rejected'
        self.assertBlocked('STOP_NOT_ACCEPTED')
        self.assertBlocked('STOP_NOT_ACCEPTED')
        self.assertEqual(len(self.calls), 1)

    def test_load_rejected_does_not_repeat(self):
        self.mode = 'load_rejected'
        self.assertBlocked('LOAD_NOT_ACCEPTED')
        self.assertBlocked('LOAD_NOT_ACCEPTED')
        self.assertEqual(len(self.calls), 2)

    def test_wrong_fresh_pid(self):
        self.mode = 'load_wrong_pid'
        self.assertBlocked('FRESH_HOST_CHANGED')

    def test_wrong_loaded_mvid(self):
        self.mode = 'load_wrong_mvid'
        self.assertBlocked('VECTOR_BRIDGE_LOADED_IDENTITY_MISMATCH')

    def test_old_run_returned(self):
        self.mode = 'load_old_run'
        self.assertBlocked('LOAD_RETURNED_OLD_RUN')

    def test_reused_nonce(self):
        self.mode = 'load_reused_nonce'
        self.assertBlocked('SCOPE_IDENTITY_REUSED')

    def test_reused_pipe(self):
        self.mode = 'load_reused_pipe'
        self.assertBlocked('SCOPE_IDENTITY_REUSED')

    def test_missing_actual_ready_never_guessed_from_load(self):
        self.mode = 'load_no_ready'
        self.assertBlocked('bridge-ready.json')

    def test_session_changed_during_load_blocks_return(self):
        self.mode = 'session_changed_on_load'
        self.assertBlocked('GAME_SESSION_CHANGED')

    def test_host_os_lock_refuses_concurrent_call(self):
        lock = self.base / 'hosts/123-987654321.lock'
        with renewal._host_lock(lock):
            self.assertBlocked('HOST_BUSY_NO_ACTION')
        self.assertEqual(self.calls, [])

    def test_uuid_not_path_and_timeout_are_strict(self):
        result = renewal.renew(str(self.runs / self.old), **self.args)
        self.assertFalse(result['ok'])
        self.assertBlocked('TIMEOUT_RANGE_0_TO_55', timeout=56)
        self.assertBlocked('TIMEOUT_RANGE_0_TO_55', timeout=float('nan'))
        self.assertEqual(self.calls, [])

    def test_private_current_process_read_only_identity(self):
        # Undo only the process stub for this PRIVATE Python PID, never inspect a game.
        spec = importlib.util.spec_from_file_location('renew_private_identity', HERE / 'scope_renew.py')
        actual = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(actual)
        identity = actual._process_identity(os.getpid())
        self.assertEqual(identity['pid'], os.getpid())
        self.assertTrue(int(identity['startUtcTicks']) > 504911232000000000)
        self.assertTrue(Path(identity['expectedExe']).is_file())


if __name__ == '__main__':
    unittest.main()
