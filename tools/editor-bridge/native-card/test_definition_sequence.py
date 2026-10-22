"""Whole-module lifecycle batch. Explicit private adapters, no native calls."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('definition_sequence', HERE / 'definition_sequence.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
OUT = m.RUNTIME / 'defseq-checks' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
OUT.mkdir(parents=True)


class PrivateCommands:
    def __init__(self, root, fault=None):
        self.root, self.fault, self.calls, self.requests, self.count = root, fault, [], {}, 0

    def call(self, script, args, stage, **kw):
        args = list(map(str, args)); self.calls.append((Path(script).name, args))
        get = lambda name: args[args.index(name)+1]
        key = stage.parent.name
        if self.fault == 'dispatch-timeout' and key.startswith('001') and stage.name == '05-dispatch':
            raise subprocess.TimeoutExpired('PRIVATE_DISPATCH', 1)
        if stage.name == '01-request':
            request = self.root / f'{key}-request.json'
            m.write(request, {'action': args[0], 'name': get('--name')})
            self.requests[key] = {'hash': m.sha(request), 'action': args[0]}
            return dict(ok=True, requestPath=str(request), requestSha256=m.sha(request))
        if stage.name == '02-review':
            p = Path(get('--out')); m.write(p, {'privateFixture': True})
            return dict(ok=True, reviewPath=str(p))
        if stage.name == '03-build':
            source = self.root / f'{key}-source'; source.mkdir()
            (source / 'stdout.jsonl').write_bytes(b'PRIVATE_NON_NATIVE_FIXTURE\n')
            self.requests[key]['source'] = source
            return dict(ok=True, run=str(source), action=self.requests[key]['action'],
                        launchable=True, compileOnly=False)
        if stage.name == '04-card':
            p = self.root / f'{key}-card'; p.mkdir(); self.requests[key]['card'] = p
            return dict(ok=True, run=str(p))
        if stage.name == '05-dispatch':
            self.count += 1
            row = self.requests[key]; row['id'] = 1000 + self.count
            if self.fault == 'duplicate-id': row['id'] = 1001
            result = dict(ok=True, tool=args[0], levelId=m.LEVEL, catalogRegisteredVerified=True,
                          cleanupVerified=True, safeToRelease=True, outcomeUncertain=False,
                          nativeStarted=True, sourceRun=str(row['source']), run=str(row['card']),
                          createdId=row['id'], rawSha256=m.sha(row['source'] / 'stdout.jsonl'))
            if self.fault == 'uncertain': result['outcomeUncertain'] = True
            if self.fault == 'foreign-run': result['sourceRun'] = str(self.root)
            return result
        if stage.name == '06-accept':
            row = self.requests[key]
            result = dict(ok=True, action=row['action'], levelId=m.LEVEL, catalogRegisteredVerified=True,
                          requestSha256=row['hash'], run=str(row['source']), createdId=row['id'],
                          outcomeUncertain=True, privateFixture=True)
            if self.fault == 'wrong-id': result['createdId'] += 1
            if self.fault == 'wrong-kind': result['action'] = 'create-skill'
            if self.fault == 'wrong-request': result['requestSha256'] = '0' * 64
            if self.fault == 'changed-backup': (self.root / 'backup.gil').write_bytes(b'changed')
            return result
        raise AssertionError(stage)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.root = OUT / m.hashlib.sha256(self._testMethodName.encode()).hexdigest()[:8]; self.root.mkdir()
        m.write(self.root/'case.json',{'name':self._testMethodName})
        self.session = self.root / 'session.json'; m.write(self.session, {'privateFixture': True})
        self.target, self.backup = self.root / 'target.gil', self.root / 'backup.gil'
        self.target.write_bytes(b'PRIVATE_TEST_BYTES'); self.backup.write_bytes(self.target.read_bytes())
        self.queue = m.RUNTIME / 'editor-bridge' / 'definition-sequence-offline' / self.root.name / OUT.name
        self.queue.mkdir(parents=True)
        self.plan = {'schemaVersion': 1, 'levelId': m.LEVEL, 'definitions': [
            {'key': 'currency.coins', 'kind': 'currency', 'name': '蒙德币'},
            {'key': 'item.apple', 'kind': 'item', 'name': '苹果'},
            {'key': 'item.ore', 'kind': 'item', 'name': '铁矿石'}]}
        self.bases = []

    def baseline(self, key):
        p = self.root / ('baseline-' + key); p.mkdir()
        m.write(p / 'exit.json', {'finishedUtc': m.now()})
        self.bases.append(p)
        return {'ok': True, 'run': str(p)}

    def run_sequence(self, fault=None, baseline=None, operation=None):
        self.commands = PrivateCommands(self.root, fault)
        with patch.object(m, 'OUTPUT', self.root / 'sequences'):
            return m.register(self.plan, operation_id=operation or uuid.uuid4().hex,
                session_file=self.session, target_gil=self.target, backup=self.backup, queue=self.queue,
                reviewed_source_sets={'template-item': 'a'*64, 'template-currency': 'b'*64},
                fresh_baseline=baseline or self.baseline, _commands=self.commands)

    def test_full_typed_routing_and_real_id_consumption(self):
        r = self.run_sequence()
        self.assertTrue(r['ok']); self.assertEqual(r['semanticIds'], {'currency.coins':1001,'item.apple':1002,'item.ore':1003})
        self.assertEqual([n for n,a in self.commands.calls if n.startswith('prepare_')],
                         ['prepare_currency.py','prepare_item.py','prepare_item.py'])
        self.assertEqual(len(self.bases),3)
        self.assertFalse(r['propertiesVerified']); self.assertFalse(r['gameplayVerified'])
        self.assertEqual(self.target.read_bytes(), b'PRIVATE_TEST_BYTES')

    def test_late_invalid_definition_prevents_first_callback(self):
        self.plan['definitions'][-1]['configId'] = 1107296259
        with self.assertRaisesRegex(m.SequenceError,'DEFINITION_ROW_FIELDS'): self.run_sequence()
        self.assertFalse(self.bases)

    def test_undefined_kind_rejected_before_native_work(self):
        self.plan['definitions'][-1]['kind'] = 'shop'
        with self.assertRaisesRegex(m.SequenceError,'DEFINITION_KIND'): self.run_sequence()
        self.assertFalse(self.bases)

    def test_unknown_second_stops_and_preserves_first(self):
        r = self.run_sequence('dispatch-timeout')
        self.assertFalse(r['ok']); self.assertTrue(r['outcomeUncertain'])
        self.assertEqual(len(r['registeredDefinitions']),1); self.assertEqual(len(self.bases),2)
        self.assertNotIn('semanticIds',r)
        self.assertTrue((Path(r['run'])/'001/dispatch-intent.json').is_file())

    def test_consumed_operation_never_replays(self):
        r = self.run_sequence('dispatch-timeout',operation='fixed-operation')
        self.assertFalse(r['ok'])
        with self.assertRaises(FileExistsError): self.run_sequence(operation='fixed-operation')
        self.assertEqual(len(self.bases),2)

    def test_stale_baseline_rejected(self):
        p = self.root / 'old'; p.mkdir()
        m.write(p/'exit.json',{'finishedUtc':(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()})
        r = self.run_sequence(baseline=lambda _:dict(ok=True,run=str(p)))
        self.assertFalse(r['ok']); self.assertFalse(self.commands.calls)

    def test_reused_baseline_rejected(self):
        def callback(key):
            return self.baseline(key) if not self.bases else dict(ok=True,run=str(self.bases[0]))
        r = self.run_sequence(baseline=callback)
        self.assertFalse(r['ok']); self.assertIn('BASELINE_REUSED',r['error'])
        self.assertEqual(len(r['registeredDefinitions']),1)

    def test_independent_acceptance_identity_mismatch_stops(self):
        for fault in ('wrong-id','wrong-kind','wrong-request','foreign-run','uncertain'):
            # Each fault gets its own operation/input directories, no reused mocks.
            original = self.root
            self.root = original / fault; self.root.mkdir()
            r = self.run_sequence(fault)
            self.assertFalse(r['ok'],fault); self.assertTrue(r['outcomeUncertain'],fault)
            self.assertFalse(r['registeredDefinitions']); self.root = original

    def test_backup_changed_after_dispatch_cannot_continue(self):
        r = self.run_sequence('changed-backup')
        self.assertFalse(r['ok']); self.assertIn('SOURCE_CHANGED',r['error'])
        self.assertEqual(len(self.bases),1); self.assertTrue(r['outcomeUncertain'])

    def test_duplicate_allocated_id_stops(self):
        r = self.run_sequence('duplicate-id')
        self.assertFalse(r['ok']); self.assertIn('DUPLICATE_ALLOCATED_ID',r['error'])
        self.assertEqual(len(r['registeredDefinitions']),1)

    def test_missing_review_digest_prevents_callback(self):
        with patch.object(m, 'OUTPUT', self.root/'sequences'):
            with self.assertRaisesRegex(m.SequenceError,'REVIEWED_SOURCE_SETS_REQUIRED'):
                m.register(self.plan, operation_id='invalid', session_file=self.session,
                    target_gil=self.target,backup=self.backup,queue=self.queue,
                    reviewed_source_sets={},fresh_baseline=self.baseline)
        self.assertFalse(self.bases)

    def test_command_timeout_keeps_intent_and_failure(self):
        stage = self.root/'command'; stage.mkdir()
        with patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired('private',1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                m.Commands().call(m.HERE/'dispatch.py',['template-item'],stage)
        self.assertTrue((stage/'command.json').is_file()); self.assertTrue((stage/'failure.json').is_file())

    def test_arbitrary_script_cannot_run(self):
        stage = self.root/'command'; stage.mkdir()
        with self.assertRaisesRegex(m.SequenceError,'NON_FIXED_COMMAND'):
            m.Commands().call(self.root/'arbitrary.py',[],stage)

    def test_unreviewed_and_duplicate_names_rejected(self):
        cases = [True, '1073741843', 1073741842]
        for bad in cases:
            d=copy.deepcopy(self.plan);d['levelId']=bad
            with self.assertRaises(m.SequenceError): m.validate_plan(d)
        d=copy.deepcopy(self.plan);d['definitions'][1]['name']=d['definitions'][0]['name']
        with self.assertRaisesRegex(m.SequenceError,'DUPLICATE_DEFINITION'):m.validate_plan(d)


if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Lifecycle)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'ok':result.wasSuccessful(),'tests':result.testsRun,'failures':len(result.failures),
             'errors':len(result.errors),'evidenceClass':'PRIVATE_OFFLINE_ADAPTER_LIFECYCLE',
             'gameAccessed':False,'nativeCalled':False,'desktopControlled':False,
             'sources':{str(p.relative_to(m.ROOT)):m.sha(p) for p in (HERE/'definition_sequence.py',Path(__file__))}}
    m.write(OUT/'summary.json',summary)
    print(json.dumps(dict(summary,path=str(OUT/'summary.json')),ensure_ascii=False))
    raise SystemExit(0 if summary['ok'] else 1)
