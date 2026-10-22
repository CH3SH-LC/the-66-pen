"""Offline tests for scene_cli's two elevated transports.

Everything here runs without a game, a session or an elevation prompt. The only
subprocess that is really executed is the fixed `python -I -S scene_cli.py --help`
bootstrap check; every other Windows API, session validator, review validator,
queue sender and Popen is mocked, so a mistake in this file cannot reach the live
sandbox. Test scratch space lives under the project .runtime tree because the
sender's own scope check deliberately refuses paths outside it.
"""
from __future__ import annotations

import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

EXECUTOR = Path(__file__).resolve().parents[1]
if str(EXECUTOR) not in sys.path:
    sys.path.insert(0, str(EXECUTOR))

import scene_cli  # noqa: E402
from scene_cli import NATIVE, ROOT  # noqa: E402

#: 2026-10-09: the template whitelist is gone, so there is no set to take a member from.
#: Any uint32 is a valid template id now; this one is a real catalogue entry.
TEMPLATE = 20001034
#: A short list to drive the payload case across more than one id.
SAMPLE_TEMPLATES = (20001034, 20001035, 20001200)
WORK_ROOT = ROOT / '.runtime/verification/update-repair-20260926/native-helper/test-work'


class FakeKernel:
    """The only part of windows_api() this module reads is the tick counter."""

    def __init__(self, tick):
        self.tick = tick

    def GetTickCount64(self):
        return self.tick


class FakeSender:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, payload, timeout=None, *, queue_dir=None):
        self.calls.append((payload, timeout))
        self.queue_dir = queue_dir
        if self.error is not None:
            raise self.error
        return self.reply



def actual_native_client():
    """Import the production client; its validation contract is never mocked."""
    spec=importlib.util.spec_from_file_location('_scene_native_contract_client',scene_cli.ELEVATED_REQUEST)
    client=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    return client

def windows_api_stub(tick=5):
    return (FakeKernel(tick), mock.MagicMock())


def run_cli(argv):
    """Drive main() in-process and capture the JSON it prints."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, 'argv', ['scene_cli.py'] + list(argv)):
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = scene_cli.main()
            except SystemExit as exit_error:
                code = exit_error.code
    return code, stdout.getvalue(), stderr.getvalue()


def cli_json(output):
    return json.loads(output)


class SceneElevatedTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        # The host probe is separately tested against real policy; these transport
        # tests replace every process boundary, including the new host query.
        host = str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
        host_probe = mock.patch.object(scene_cli.profile_api, 'powershell_host',
            return_value=dict(path=host, version='synthetic', policy='RemoteSigned',
                              policyOverride=False, fallbackAttempted=False))
        host_probe.start(); self.addCleanup(host_probe.stop)
        self.work = Path(tempfile.mkdtemp(prefix='case-', dir=str(WORK_ROOT)))
        self.addCleanup(shutil.rmtree, str(self.work), ignore_errors=True)

    # -- fixtures ---------------------------------------------------------------
    def session_file(self, name='session.json', directory=None):
        path = Path(directory or self.work) / name
        path.write_text(json.dumps({field: 1 for field in scene_cli.SESSION_FIELDS}),
                        encoding='utf-8')
        return path

    def review_file(self, name='review.json'):
        path = (self.work / name).resolve()
        path.write_text('{}', encoding='utf-8')
        return path

    def plan_file(self, placements, name='plan.json'):
        path = self.work / name
        path.write_text(json.dumps({'placements': placements}), encoding='utf-8')
        return path

    def queue_create_argv(self, session, review, extra=()):
        return ['create', '--elevated-queue', str(self.work), '--session', str(session), '--level-id', '7',
                '--review', str(review), '--template-id', str(TEMPLATE),
                '--position', '1', '2', '3', *extra]

    def queue_batch_argv(self, session, review, plan, extra=()):
        return ['create-batch', '--elevated-queue', str(self.work), '--session', str(session), '--level-id', '7',
                '--review', str(review), '--plan', str(plan), *extra]

    def make_direct_profile(self, name='direct'):
        run = self.work / name
        run.mkdir()
        wrapper = run / 'invoke-fixed-probe.ps1'
        wrapper.write_text('# fixed wrapper\n', encoding='utf-8')
        sources = {source: scene_cli.digest(NATIVE / source)
                   for source in (*scene_cli.readonly.SOURCES, 'game_scene_action.cpp', 'game_scene_action.h', 'scene_calls.cpp', 'scene_calls.h')}
        request = {'action': 'create', 'levelId': 7}
        (run / 'prepared.json').write_text(json.dumps({'sources': sources, 'request': request, 'session': {'schemaVersion':1, 'pid':11}, 'reviewSha256':'a'*64}),
                                           encoding='utf-8')
        review_path = self.review_file(name + '-review.json')
        profile = dict(run=str(run), action='create', wrapperName='invoke-fixed-probe.ps1',
                       hashes={'invoke-fixed-probe.ps1': scene_cli.digest(wrapper),
                               'prepared.json': scene_cli.digest(run / 'prepared.json')},
                       deadlineTick=10_000_000_000, targetPid=11, targetTid=12, expectedLevelId=7,
                       session={'schemaVersion': 1, 'pid': 11}, reviewPath=str(review_path),
                       reviewId='11111111-1111-1111-1111-111111111111',
                       profileId='reviewed-write-profile',
                       requestSha256=scene_cli.native_write_review.canonical_hash(request))
        return profile, run, review_path, request

    def direct_patches(self, profile, review_path, request, *, admin=True, tick=5,
                       session_side_effect=None, reviewed=None, validate_side_effect=None):
        """Every real dependency of the direct path, except Popen."""
        if validate_side_effect is not None:
            validate_mock = mock.patch.object(scene_cli.native_write_review, 'validate_review',
                                              side_effect=validate_side_effect)
        else:
            validate_mock = mock.patch.object(
                scene_cli.native_write_review, 'validate_review',
                return_value=reviewed if reviewed is not None else
                dict(reviewId=profile['reviewId'], writeProfile={'profileId': profile['profileId']},
                     reviewPath=str(review_path), request=request, reviewSha256='a'*64))
        session_kwargs = (dict(side_effect=session_side_effect) if session_side_effect is not None
                          else dict(return_value=profile['session']))
        return [
            mock.patch.object(scene_cli, 'is_admin_token', return_value=admin),
            mock.patch.object(scene_cli, 'windows_api', return_value=windows_api_stub(tick)),
            mock.patch.object(scene_cli.profile_api, 'validate_session', **session_kwargs),
            validate_mock,
        ]

    # -- 1. bootstrap: real isolated --help, no game contact ---------------------
    def test_isolated_help_bootstraps_siblings_and_ignores_cwd(self):
        """python -I -S drops the script directory from sys.path.

        The decoy below is a sibling module name planted in the working directory:
        if the bootstrap ever imported CWD or user modules instead of the fixed
        directory, it would run and leave its marker behind.
        """
        marker = self.work / 'decoy-ran.txt'
        (self.work / 'build_scene_profile.py').write_text(
            'from pathlib import Path\nPath(%r).write_text("ran")\n' % str(marker), encoding='utf-8')
        for argv in (['--help'], ['inspect', '--help'], ['create', '--help'],
                     ['create-batch', '--help'], ['save', '--help']):
            done = subprocess.run([sys.executable, '-B', '-I', '-S', str(scene_cli.__file__), *argv],
                                  cwd=str(self.work), capture_output=True, text=True, timeout=180)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn('--elevated-queue', done.stdout)
            self.assertIn('--direct-elevated', done.stdout)
        self.assertFalse(marker.exists(), 'the isolated bootstrap imported a CWD module')

    # -- 2. flag contract -------------------------------------------------------
    def test_transport_flags_are_mutually_exclusive(self):
        code, _, err = run_cli(['inspect', '--elevated-queue', str(self.work), '--direct-elevated',
                                '--level-id', '7'])
        self.assertEqual(code, 2)
        self.assertIn('not allowed with', err)

    def test_prepare_only_refused_before_build_queue_or_admin_check(self):
        for flag in ('--elevated-queue', '--direct-elevated'):
            with self.subTest(flag=flag):
                with mock.patch.object(scene_cli, 'build_profile') as build, \
                        mock.patch.object(scene_cli, 'is_admin_token') as admin, \
                        mock.patch.object(scene_cli, 'load_native_sender') as sender:
                    code, out, _ = run_cli(['create', '--prepare-only', flag, *([str(self.work)] if flag == '--elevated-queue' else []), '--level-id', '7',
                                            '--template-id', str(TEMPLATE),
                                            '--position', '0', '0', '0'])
                self.assertEqual(code, 2)
                self.assertIn('--prepare-only', cli_json(out)['error'])
                build.assert_not_called()
                sender.assert_not_called()
                admin.assert_not_called()


    def test_cli_payloads_pass_actual_client_before_json_serialization(self):
        client=actual_native_client()
        # 2026-10-09: the whitelist is gone; nothing narrows the client's id set any more.
        self.assertFalse(hasattr(client,'NATIVE_TEMPLATES'))
        session,review=self.session_file(),self.review_file()
        plan=self.plan_file([dict(template_id=TEMPLATE,position=[0.1,-2,3],scale=[1.25,1,1],label='metadata')]*256)
        cases=[['inspect','--elevated-queue',str(self.work),'--session',str(session),'--level-id','7'],
               ['save','--elevated-queue',str(self.work),'--session',str(session),'--level-id','7','--review',str(review)],
               self.queue_batch_argv(session,review,plan)]
        cases.extend(self.queue_create_argv(session,review,extra=['--template-id',str(template),
                     '--position','-10','0.1','-20','--scale','1.25','1','1']) for template in SAMPLE_TEMPLATES)
        for argv in cases:
            with self.subTest(action=argv[0],template=argv[-10:]):
                received=[]
                def contract_sender(payload,timeout,*,queue_dir):
                    # No json.dumps/loads here: that would hide tuple-vs-list defects.
                    canonical=client.validate_native_scene_request(payload)
                    self.assertEqual(payload,canonical)
                    self.assertEqual(payload,json.loads(json.dumps(payload)))
                    received.append(payload)
                    return dict(ok=True,action=payload['action'],requestId='a'*32)
                with mock.patch.object(scene_cli,'load_native_sender',return_value=contract_sender), \
                     mock.patch.object(scene_cli,'build_profile') as build, \
                     mock.patch.object(scene_cli.native_write_review,'claim_review') as claim:
                    code,out,_=run_cli(argv)
                self.assertEqual(code,0,out)
                self.assertEqual(len(received),1)
                build.assert_not_called();claim.assert_not_called()

    def test_actual_client_and_local_guard_reject_tuples_for_each_transform(self):
        client=actual_native_client()
        session,review=self.session_file(),self.review_file()
        plan=self.plan_file([dict(template_id=TEMPLATE,position=[0,0,0],scale=[1,1,1])])
        for argv in (self.queue_create_argv(session,review),self.queue_batch_argv(session,review,plan)):
            payload=scene_cli.queue_request(scene_cli.build_parser().parse_args(argv))
            client.validate_native_scene_request(payload)
            for field in ('position','rotation','scale'):
                bad=json.loads(json.dumps(payload))
                placement=bad if bad['action']=='create' else bad['placements'][0]
                self.assertIs(type(placement[field]),list)
                placement[field]=tuple(placement[field])
                with self.subTest(action=bad['action'],field=field):
                    with self.assertRaisesRegex(ValueError,'NATIVE_SCENE_VECTOR_INVALID'):
                        client.validate_native_scene_request(bad)
                    with self.assertRaisesRegex(ValueError,'tuple'):
                        scene_cli.assert_queue_data_only(bad)

    def test_queue_baseline_refused_not_ignored(self):
        baseline = self.work / 'baseline.json'
        baseline.write_text('{}', encoding='utf-8')
        session, review = self.session_file(), self.review_file()
        with mock.patch.object(scene_cli, 'build_profile') as build, \
                mock.patch.object(scene_cli, 'load_native_sender') as sender:
            code, out, _ = run_cli(self.queue_create_argv(session, review,
                                                          extra=['--baseline', str(baseline)]))
        self.assertEqual(code, 2)
        self.assertIn('--baseline', cli_json(out)['error'])
        build.assert_not_called()
        sender.assert_not_called()

    # -- 3. queue transport -----------------------------------------------------
    def test_queue_sends_closed_data_only_and_never_builds_or_claims(self):
        session, review = self.session_file(), self.review_file()
        reply = {'ok': True, 'run': 'RUN-1', 'requestId': 'REQ-1', 'helper': {'id': 'helper-1'}, 'entityId': 1077936001, 'placedIds':[1077936001], 'called':1}
        sender = FakeSender(reply=reply)
        with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender), \
                mock.patch.object(scene_cli, 'build_profile') as build, \
                mock.patch.object(scene_cli.native_write_review, 'claim_review') as claim:
            code, out, _ = run_cli(self.queue_create_argv(session, review))
        result = cli_json(out)
        self.assertEqual(code, 0, out)
        self.assertTrue(result['ok'])
        payload, timeout = sender.calls[0]
        self.assertEqual(timeout, 300.0)
        self.assertEqual(set(payload), {'kind', 'action', 'sessionPath', 'levelId', 'reviewPath',
                                        'templateId', 'position', 'rotation', 'scale'})
        self.assertEqual(payload['kind'], 'native-scene')
        self.assertEqual(payload['action'], 'create')
        self.assertEqual(payload['levelId'], 7)
        self.assertEqual(payload['templateId'], TEMPLATE)
        for key in ('sessionPath', 'reviewPath'):
            self.assertTrue(os.path.isabs(payload[key]), key)
            self.assertTrue(Path(payload[key]).is_relative_to(ROOT / '.runtime'), key)
        # The reply is preserved verbatim and every local side effect is absent.
        self.assertTrue(all(result[key] == value for key,value in reply.items()))
        self.assertEqual(sender.queue_dir, self.work)
        self.assertEqual((result['run'], result['requestId'], result['helper']),
                         ('RUN-1', 'REQ-1', {'id': 'helper-1'}))
        self.assertIs(result['outcomeUncertain'], False)
        build.assert_not_called()
        claim.assert_not_called()

    def test_queue_payload_carries_no_plan_path_or_command(self):
        session, review = self.session_file(), self.review_file()
        plan = self.plan_file([{'template_id': TEMPLATE, 'position': [0, 0, 0], 'scale': [1, 1, 1]}])
        sender = FakeSender(reply={'ok': True})
        with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender):
            code, _, _ = run_cli(self.queue_batch_argv(session, review, plan))
        self.assertEqual(code, 0)
        payload = sender.calls[0][0]
        # The real client validates Python types before writing JSON.
        wire = actual_native_client().validate_native_scene_request(payload)
        self.assertEqual(set(wire), {'kind', 'action', 'sessionPath', 'levelId', 'reviewPath',
                                     'placements'})
        rendered = json.dumps(wire)
        self.assertNotIn(str(plan), rendered)
        self.assertNotIn('plan', rendered)
        # Missing rotation normalises to zeros rather than being forwarded as absent.
        self.assertEqual(wire['placements'],
                         [{'template_id': TEMPLATE, 'position': [0.0, 0.0, 0.0],
                           'rotation': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0]}])
        for key in scene_cli.FORBIDDEN_PAYLOAD_KEYS:
            self.assertNotIn(key, wire)

    def test_queue_payload_guard_rejects_smuggled_keys(self):
        with self.assertRaises(ValueError):
            scene_cli.assert_queue_data_only({'kind': 'native-scene', 'planPath': 'x'})
        with self.assertRaises(ValueError):
            scene_cli.assert_queue_data_only({'kind': 'native-scene',
                                              'placements': [{'template_id': 1, 'run': 'cmd.exe'}]})
        with self.assertRaises(ValueError):
            scene_cli.assert_queue_data_only({'kind': 'native-scene', 'levelId': float('nan')})
        scene_cli.assert_queue_data_only({'kind': 'native-scene', 'levelId': 7, 'scale': [1.0, 2.0, 3.0]})

    def test_queue_reply_shape_gate_and_no_resubmit(self):
        session, review = self.session_file(), self.review_file()
        for label, reply in (('string true', {'ok': 'true'}), ('missing ok', {'run': 'R'}),
                             ('not an object', 'nope'), ('null', None)):
            with self.subTest(label=label):
                sender = FakeSender(reply=reply)
                with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender):
                    code, out, _ = run_cli(self.queue_create_argv(session, review))
                self.assertEqual(code, 2, out)
                self.assertEqual(len(sender.calls), 1, 'the queue request must be sent exactly once')
        timeout_sender = FakeSender(error=SystemExit('timeout waiting for the elevated runner'))
        with mock.patch.object(scene_cli, 'load_native_sender', return_value=timeout_sender):
            code, out, _ = run_cli(self.queue_create_argv(session, review))
        result = cli_json(out)
        self.assertEqual(code, 2)
        self.assertIs(result['outcomeUncertain'], True)
        self.assertEqual(len(timeout_sender.calls), 1, 'a sender failure must never be resubmitted')

    def test_queue_refuses_invalid_placements(self):
        session, review = self.session_file(), self.review_file()
        good = {'template_id': TEMPLATE, 'position': [0, 0, 0], 'scale': [1, 1, 1]}
        long_batch = [dict(good) for _ in range(257)]
        cases = (
            ('bool template', [{'template_id': True, 'position': [0, 0, 0], 'scale': [1, 1, 1]}]),
            ('unexpected field', [dict(good, extra=1)]),
            ('missing scale', [{'template_id': TEMPLATE, 'position': [0, 0, 0]}]),
            ('nan position', [dict(good, position=[float('nan'), 0, 0])]),
            ('infinite position', [dict(good, position=[float('inf'), 0, 0])]),
            ('bool position', [dict(good, position=[True, 0, 0])]),
            ('string position', [dict(good, position=['0', 0, 0])]),
            ('short position', [dict(good, position=[0, 0])]),
            ('zero scale', [dict(good, scale=[0, 1, 1])]),
            ('negative scale', [dict(good, scale=[1, -1, 1])]),
            # 2026-10-09: the whitelist is gone, so "unlisted" no longer refuses. What still
            # refuses is a value that is not a uint32 at all.
            ('template_id that is not a uint32', [dict(good, template_id=2 ** 32)]),
            ('empty batch', []),
            ('oversized batch', long_batch),
            ('non-object entry', [1]),
        )
        sender = FakeSender(reply={'ok': True})
        for label, placements in cases:
            with self.subTest(label=label):
                plan = self.plan_file(placements, name='plan-%s.json' % label.replace(' ', '-'))
                with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender), \
                        mock.patch.object(scene_cli, 'build_profile') as build:
                    code, out, _ = run_cli(self.queue_batch_argv(session, review, plan))
                self.assertEqual(code, 2, out)
                self.assertTrue(cli_json(out)['error'])
                build.assert_not_called()
        self.assertEqual(sender.calls, [], 'no invalid batch may reach the helper')

    def test_queue_refuses_oversized_plan(self):
        session, review = self.session_file(), self.review_file()
        plan = self.work / 'huge-plan.json'
        plan.write_text(json.dumps({'placements': [
            {'template_id': TEMPLATE, 'position': [0, 0, 0], 'scale': [1, 1, 1], 'pad': 'x' * 40}] * 6000}),
            encoding='utf-8')
        self.assertGreater(plan.stat().st_size, scene_cli.MAX_PLAN_BYTES)
        sender = FakeSender(reply={'ok': True})
        with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender):
            code, out, _ = run_cli(self.queue_batch_argv(session, review, plan))
        self.assertEqual(code, 2)
        self.assertIn('byte bound', cli_json(out)['error'])
        self.assertEqual(sender.calls, [])

    def test_queue_path_scope_refusals(self):
        session, review = self.session_file(), self.review_file()
        # Reuse an existing source file outside .runtime. TEMP itself intentionally
        # lives inside project .runtime; no test may write an external fixture.
        outside_file = Path(__file__).resolve()
        cases = (
            ('missing session', self.queue_create_argv(self.work / 'absent.json', review),
             'SESSION_MISSING'),
            ('session outside runtime', self.queue_create_argv(outside_file, review),
             'SESSION_OUTSIDE_PROJECT_RUNTIME'),
            ('missing review', self.queue_create_argv(session, self.work / 'absent-review.json'),
             'REVIEW_MISSING'),
            ('review outside runtime', self.queue_create_argv(session, outside_file),
             'REVIEW_OUTSIDE_PROJECT_RUNTIME'),
            ('write without review', ['create', '--elevated-queue', str(self.work), '--session', str(session),
                                      '--level-id', '7', '--template-id', str(TEMPLATE),
                                      '--position', '0', '0', '0'],
             'NATIVE_WRITE_REVIEW_REQUIRED'),
            # 2026-10-09: --template-id no longer has argparse choices; a non-integer is still
            # an argument error.
            ('non-integer template id', self.queue_create_argv(session, review,
                                                               extra=['--template-id', 'not-an-int']),
             'invalid int value'),
        )
        sender = FakeSender(reply={'ok': True})
        for label, argv, expected in cases:
            with self.subTest(label=label):
                with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender), \
                        mock.patch.object(scene_cli, 'build_profile') as build:
                    code, out, err = run_cli(argv)
                self.assertEqual(code, 2, out or err)
                self.assertIn(expected, out + err)
                build.assert_not_called()
        self.assertEqual(sender.calls, [], 'no refused path may reach the helper')

    def test_queue_refuses_reparse_point_session(self):
        real = self.session_file()
        link = self.work / 'link-session.json'
        try:
            os.symlink(str(real), str(link))
        except (OSError, NotImplementedError) as error:  # needs a privilege we do not require
            self.skipTest('symlink creation unavailable: %s' % error)
        review = self.review_file()
        sender = FakeSender(reply={'ok': True})
        with mock.patch.object(scene_cli, 'load_native_sender', return_value=sender):
            code, out, _ = run_cli(self.queue_create_argv(link, review))
        self.assertEqual(code, 2)
        self.assertIn('SESSION_REPARSE_POINT', cli_json(out)['error'])
        self.assertEqual(sender.calls, [])
        self.assertTrue(scene_cli.ELEVATED_REQUEST.is_file(),
                        'the fixed helper must keep owning its own deeper path checks')

    # -- 4. direct elevated -----------------------------------------------------
    def test_direct_requires_real_token_before_build_and_claim(self):
        session, review = self.session_file(), self.review_file()
        with mock.patch.object(scene_cli, 'is_admin_token', return_value=False), \
                mock.patch.object(scene_cli, 'build_profile') as build, \
                mock.patch.object(scene_cli.native_write_review, 'claim_review') as claim:
            code, out, _ = run_cli(['create', '--direct-elevated', '--session', str(session),
                                    '--level-id', '7', '--review', str(review),
                                    '--template-id', str(TEMPLATE), '--position', '0', '0', '0'])
        self.assertEqual(code, 2)
        self.assertIn('elevated Windows token', cli_json(out)['error'])
        self.assertIs(cli_json(out)['safeToRelease'], True)
        self.assertIs(cli_json(out)['nativeStarted'], False)
        build.assert_not_called()
        claim.assert_not_called()

    def test_direct_runs_only_the_fixed_wrapper_without_runas(self):
        profile, run, review_path, request = self.make_direct_profile()
        exit_path = run / 'exit.json'

        def fake_popen(command, **kwargs):
            exit_path.write_text(json.dumps({'error': 'STOP-AFTER-LAUNCH', 'executed': False}),
                                 encoding='utf-8')
            return mock.MagicMock()

        popen = mock.MagicMock(side_effect=fake_popen)
        with ExitStack() as stack:
            for patcher in self.direct_patches(profile, review_path, request):
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(scene_cli.subprocess, 'Popen', popen))
            with self.assertRaises(scene_cli.SceneFailure) as caught:
                scene_cli.execute_profile(profile, direct_elevated=True)
        self.assertIn('Fixed probe failed', str(caught.exception))
        self.assertEqual(popen.call_count, 1)
        command = popen.call_args.args[0]
        self.assertIn('-File', command)
        self.assertNotIn('-ExecutionPolicy', command)
        self.assertEqual(Path(command[-1]), run / 'invoke-fixed-probe.ps1')
        for forbidden in ('-Verb', 'RunAs', 'launch-uac.ps1'):
            self.assertNotIn(forbidden, command)
        self.assertFalse((run / 'launch-uac.ps1').exists(), 'the direct path must not build a UAC launcher')
        self.assertEqual(popen.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
        self.assertEqual(popen.call_args.kwargs['cwd'], run)

    def test_direct_rejections_all_happen_before_popen(self):
        base, run, review_path, request = self.make_direct_profile()
        other_review = dict(reviewId='22222222-2222-2222-2222-222222222222',
                            writeProfile={'profileId': base['profileId']},
                            reviewPath=str(review_path), request=request, reviewSha256='a'*64)
        cases = (
            ('token dropped', {}, dict(admin=False)),
            ('artifact changed', {'hashes': {'invoke-fixed-probe.ps1': '0' * 64,
                                             'prepared.json': base['hashes']['prepared.json']}}, {}),
            ('deadline elapsed', {}, dict(tick=10 ** 12)),
            ('session changed', {}, dict(session_side_effect=RuntimeError('SESSION_CHANGED:pid'))),
            ('review expired', {},
             dict(validate_side_effect=RuntimeError('REVIEW_EXPIRED_OR_INVALID_TIME'))),
            ('review identity differs', {}, dict(reviewed=other_review)),
            ('sources missing', 'SOURCES', {}),
        )
        for label, overrides, patch_kwargs in cases:
            with self.subTest(label=label):
                profile, run, review_path, request = self.make_direct_profile(
                    name='case-' + label.replace(' ', '-'))
                if overrides == 'SOURCES':
                    (run / 'prepared.json').write_text(json.dumps({'request': request}),
                                                       encoding='utf-8')
                    profile['hashes']['prepared.json'] = scene_cli.digest(run / 'prepared.json')
                    patches = self.direct_patches(profile, review_path, request)
                else:
                    profile.update(overrides)
                    patches = self.direct_patches(profile, review_path, request, **patch_kwargs)
                popen = mock.MagicMock()
                with ExitStack() as stack:
                    for patcher in patches:
                        stack.enter_context(patcher)
                    stack.enter_context(mock.patch.object(scene_cli.subprocess, 'Popen', popen))
                    with self.assertRaises((scene_cli.SceneFailure, RuntimeError)):
                        scene_cli.execute_profile(profile, direct_elevated=True)
                popen.assert_not_called()

    def test_direct_source_hash_tamper_is_rejected(self):
        profile, run, review_path, request = self.make_direct_profile(name='source-tamper')
        prepared = json.loads((run / 'prepared.json').read_text(encoding='utf-8'))
        prepared['sources'][next(iter(prepared['sources']))] = 'f' * 64
        (run / 'prepared.json').write_text(json.dumps(prepared), encoding='utf-8')
        profile['hashes']['prepared.json'] = scene_cli.digest(run / 'prepared.json')
        popen = mock.MagicMock()
        with ExitStack() as stack:
            for patcher in self.direct_patches(profile, review_path, request):
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(scene_cli.subprocess, 'Popen', popen))
            with self.assertRaises(scene_cli.SceneFailure) as caught:
                scene_cli.execute_profile(profile, direct_elevated=True)
        self.assertIn('Prepared native source changed', str(caught.exception))
        popen.assert_not_called()


    def test_launch_intent_before_popen_prevents_false_safe_release(self):
        profile, run, review_path, request = self.make_direct_profile('intent')
        def fail_launch(*args, **kwargs):
            self.assertTrue((run/'direct-launch-intent.json').is_file())
            self.assertFalse((run/'launch.claim').exists())
            raise OSError('simulated boundary failure')
        with ExitStack() as stack:
            for patcher in self.direct_patches(profile, review_path, request):
                stack.enter_context(patcher)
            stack.enter_context(mock.patch.object(scene_cli, 'build_profile', return_value=profile))
            stack.enter_context(mock.patch.object(scene_cli, 'preserve_gils', return_value={}))
            popen=stack.enter_context(mock.patch.object(scene_cli.subprocess, 'Popen', side_effect=fail_launch))
            code,out,_=run_cli(['create','--direct-elevated','--level-id','7',
                               '--review',str(review_path),'--template-id',str(TEMPLATE),
                               '--position','0','0','0'])
        result=cli_json(out)
        self.assertEqual(code,2)
        self.assertTrue(result['outcomeUncertain'])
        self.assertIs(result['safeToRelease'],False)
        self.assertIsNone(result['nativeStarted'])
        self.assertEqual(popen.call_count,1)

    def test_direct_source_set_and_review_digest_are_revalidated(self):
        for variant in ('missing-source','extra-source','review-hash','session'):
            with self.subTest(variant=variant):
                profile,run,review_path,request=self.make_direct_profile(variant)
                prepared=json.loads((run/'prepared.json').read_text(encoding='utf-8'))
                if variant=='missing-source': prepared['sources'].pop(next(iter(prepared['sources'])))
                if variant=='extra-source': prepared['sources']['../scene_cli.py']='a'*64
                if variant=='review-hash': prepared['reviewSha256']='b'*64
                if variant=='session': prepared['session']['pid']=99
                (run/'prepared.json').write_text(json.dumps(prepared),encoding='utf-8')
                profile['hashes']['prepared.json']=scene_cli.digest(run/'prepared.json')
                with ExitStack() as stack:
                    for patcher in self.direct_patches(profile,review_path,request): stack.enter_context(patcher)
                    popen=stack.enter_context(mock.patch.object(scene_cli.subprocess,'Popen'))
                    with self.assertRaises(scene_cli.SceneFailure):
                        scene_cli.execute_profile(profile,direct_elevated=True)
                popen.assert_not_called()
                self.assertFalse((run/'direct-launch-intent.json').exists())

    def test_cleanup_signal_only_follows_verified_receipt(self):
        profile,run,review_path,request=self.make_direct_profile('cleanup')
        profile.update(action='inspect',expectedLevelId=7)
        record=dict(transportOk=True,ok=True,unhooked=True,activeCallbacks=0,
                    callbackCount=1,pid=11,tid=12)
        before=dict(status={'value':0},counts={'entityValidEntries':1},
                    levelObservation={'verified':True,'levelId':7})
        def fake_launch(*args,**kwargs):
            (run/'exit.json').write_text('{"exitCode":0}',encoding='utf-8')
            return mock.MagicMock()
        with mock.patch.object(scene_cli,'validate_direct_profile'), \
             mock.patch.object(scene_cli,'windows_api',return_value=windows_api_stub()), \
             mock.patch.object(scene_cli.subprocess,'Popen',side_effect=fake_launch), \
             mock.patch.object(scene_cli,'read_probe',return_value=(record,'utf-8')), \
             mock.patch.object(scene_cli,'decode_snapshot',return_value=before), \
             mock.patch.object(scene_cli.readonly,'validate_receipt',return_value={'ok':True,'reasons':[]}):
            result=scene_cli.run_profile(profile,direct_elevated=True)
        self.assertTrue(result['ok'])
        self.assertIs(result['cleanupVerified'],True)
        self.assertIs(result['nativeStarted'],True)
        self.assertNotIn('safeToRelease',result)

    def test_queue_pending_result_keeps_original_request_identity(self):
        reply={'ok':False,'pending':True,'outcomeUncertain':True,'requestId':'a'*32,
               'retryAttempted':False,'helper':{'kind':'native-scene'}}
        sender=FakeSender(reply=reply)
        with mock.patch.object(scene_cli,'load_native_sender',return_value=sender):
            result=scene_cli.send_queued_scene({'kind':'native-scene'},'save',self.work)
        self.assertTrue(result['pending'])
        self.assertTrue(result['outcomeUncertain'])
        self.assertEqual(result['requestId'],'a'*32)
        self.assertEqual(len(sender.calls),1)
        self.assertFalse(result['retryAttempted'])

    # -- 5. default transport is unchanged ---------------------------------------
    def test_standard_uac_path_still_uses_the_launcher(self):
        profile, run, review_path, request = self.make_direct_profile(name='standard')
        launch_result = run / 'launch-result.json'

        def fake_popen(command, **kwargs):
            launch_result.write_text(json.dumps({'started': False, 'cancelled': True}),
                                     encoding='utf-8')
            return mock.MagicMock()

        popen = mock.MagicMock(side_effect=fake_popen)
        with mock.patch.object(scene_cli, 'is_admin_token') as admin, \
                mock.patch.object(scene_cli, 'validate_direct_profile') as direct_check, \
                mock.patch.object(scene_cli, 'windows_api', return_value=windows_api_stub()), \
                mock.patch.object(scene_cli.subprocess, 'Popen', popen):
            with self.assertRaises(scene_cli.SceneFailure) as caught:
                scene_cli.execute_profile(profile)
        self.assertIn('UAC cancelled', str(caught.exception))
        self.assertEqual(Path(popen.call_args.args[0][-1]), run / 'launch-uac.ps1')
        script = (run / 'launch-uac.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('-Verb RunAs', script)
        self.assertIn('invoke-fixed-probe.ps1', script)
        admin.assert_not_called()
        direct_check.assert_not_called()

    def test_direct_elevated_keyword_defaults_to_false(self):
        self.assertEqual(scene_cli.execute_profile.__kwdefaults__, {'direct_elevated': False})
        self.assertEqual(scene_cli.run_profile.__kwdefaults__, {'direct_elevated': False})


if __name__ == '__main__':
    unittest.main(verbosity=2)
