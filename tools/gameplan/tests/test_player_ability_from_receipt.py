"""Offline skill assembly, including one real raw-acceptor integration fixture."""
import contextlib
import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.gameplan.demo import player_ability_from_receipt as ability

SCRATCH = ability.ROOT / '.runtime/scratch/overnight-features-20261013/task-bk/tests'
CHARACTER, SKILL = 1090519041, 0x41800001
SESSION = {'schemaVersion': 1, 'pid': 9009, 'tid': 8008, 'window': 7007,
           'windowClass': 'UnityWndClass', 'processCreation': 12345, 'threadCreation': 23456,
           'image': 'D:/games/Genshin Impact Game/YuanShen.exe'}


class PlayerAbilityFromReceiptTests(unittest.TestCase):
    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(temp.cleanup)
        self.run = Path(temp.name).resolve()
        self.prepared = {'levelId': 1073741842, 'session': SESSION}
        (self.run/'prepared.json').write_text(json.dumps(self.prepared), encoding='utf-8')
        (self.run/'stdout.jsonl').write_text('SYNTHETIC DEPENDENCY FIXTURE', encoding='utf-8')
        (self.run/'baseline-snapshot.bin').write_bytes(b'SYNTHETIC SCENE')
        (self.run/'skill-acceptance.json').write_text('{"ok":true,"createdId":999}', encoding='utf-8')
        self.report = dict(ok=True, action='create-skill', run=str(self.run), levelId=1073741842,
            catalogRegisteredVerified=True, createdId=SKILL, requestSha256='a'*64, reviewSha256='b'*64,
            acceptorSha256='c'*64, decoderHashes={'skill_receipt.py':'d'*64, 'receipt.py':'e'*64},
            inputHashes={n:hashlib.sha256((self.run/n).read_bytes()).hexdigest()
                         for n in ('prepared.json','stdout.jsonl','baseline-snapshot.bin')})
        self.scene = {'entities':[{'id':CHARACTER, 'dictionaryKey':CHARACTER, 'configId':CHARACTER}]}
        real = ability._acceptor()
        self.acceptor = SimpleNamespace(validate_run=Mock(side_effect=lambda run: copy.deepcopy(self.report)),
            requests=real.requests, profiles=SimpleNamespace(load_profile=lambda:{}),
            scene=Mock(side_effect=lambda *args:copy.deepcopy(self.scene)))
        self.enterContext(patch.object(ability, '_acceptor', return_value=self.acceptor))
        self.args = dict(skill_run=self.run, character_id=CHARACTER, skill_id_slot='uint',
                         skill_slot=3, replace_policy=1)

    def result(self, **changes):
        return ability.compile_from_receipt(**dict(self.args, **changes))

    def test_actual_71_809_806_graph_reuses_created_instance_and_character(self):
        with patch.object(ability.GraphBuilder, 'build_batch', side_effect=AssertionError('no dispatch')):
            result = self.result()
        self.acceptor.validate_run.assert_called_once_with(self.run)
        self.assertEqual([n['definitionId'] for n in result['plan']['nodes']], [71,809,806])
        edges = {(e['from'],e['fromKind'],e['fromIndex'],e['to'],e['toKind'],e['toIndex'])
                 for e in result['plan']['edges']}
        self.assertEqual(edges, {(0,2,0,1,1,0),(1,2,0,2,1,0),
                                (0,4,0,1,3,0),(0,4,0,2,3,0),(1,4,0,2,3,1)})
        values = {(v['node'],v['portIndex']):(v['slot'],v['value']) for v in result['plan']['values']}
        self.assertEqual(values, {(1,1):('uint',{'uint':SKILL}),
                                  (2,2):('enum',{'uint':3}), (2,3):('enum',{'uint':1})})
        self.assertEqual(result['bindingTarget']['entityId'], CHARACTER)
        self.assertEqual(result['createdSkillId'], SKILL)  # Cached 999 is ignored.
        self.assertEqual(result['summary'], {'nodes':3,'edges':5,'consts':3})
        for key in ('deploymentReady','editorDispatchAttempted','persistentSaveVerified',
                    'gameRuntimeVerified','farmingSkillTriggerVerified'):
            self.assertFalse(result[key])
        self.assertFalse(result['prerequisites']['skillSlotEnum']['verified'])

    def test_failed_raw_validation_cannot_be_replaced_by_cached_success(self):
        self.acceptor.validate_run.side_effect = ValueError('RAW_RECEIPT_REFUSED')
        with self.assertRaisesRegex(ValueError,'RAW_RECEIPT_REFUSED'):
            self.result()

    def test_changed_inputs_and_unregistered_or_wrong_action_refuse(self):
        for field,value in (('action','create-item'), ('catalogRegisteredVerified',False)):
            old = self.report[field]; self.report[field] = value
            with self.assertRaisesRegex(ValueError,'REGISTERED_SKILL_REQUIRED'):
                self.result()
            self.report[field] = old
        (self.run/'stdout.jsonl').write_bytes(b'CHANGED')
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):
            self.result()

    def test_character_must_be_present_exactly_and_match_recorded_identity(self):
        with self.assertRaisesRegex(ValueError,'CHARACTER_NOT_IN_RECORDED_SCENE'):
            self.result(character_id=CHARACTER+1)
        self.scene['entities'][0]['dictionaryKey'] = CHARACTER+1
        with self.assertRaisesRegex(ValueError,'CHARACTER_NOT_IN_RECORDED_SCENE'):
            self.result()

    def test_parameters_are_explicit_and_invalid_values_refuse(self):
        for change in ({'character_id':0},{'skill_id_slot':'auto'}, {'skill_slot':-1},
                       {'replace_policy':True},{'skill_run':ability.ROOT/'GOAL.md'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.result(**change)
        for name in ('character_id','skill_id_slot','skill_slot','replace_policy'):
            args = dict(self.args); del args[name]
            with self.assertRaises(TypeError):
                ability.compile_from_receipt(**args)
        with self.assertRaises(ability.PlanError):
            self.result(name='invalid graph name')

    def test_main_compiles_without_execute_or_side_effect_output(self):
        argv = []
        for name,value in self.args.items():
            argv.extend(['--'+name.replace('_','-'),str(value)])
        before = {p.name:p.read_bytes() for p in self.run.iterdir()}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(ability.main(argv),0)
        self.assertEqual(json.loads(output.getvalue())['createdSkillId'],SKILL)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.run.iterdir()})
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ability.build_parser().parse_args(argv+['--execute'])


class ActualRawSkillReceiptTests(unittest.TestCase):
    def test_full_raw_validation_compiles_then_detects_tampered_summary(self):
        # Native/session/compiler producers are synthetic; validate_run and its
        # full raw receipt checks are the real production implementation.
        accept = ability._acceptor()
        sys.path.insert(0,str(ability.AUTHORING/'tests'))
        fixture_module = importlib.import_module('test_accept_skill')
        fixture = fixture_module.AcceptSkillTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        run = fixture.run.resolve()
        (run/'skill-acceptance.json').write_text('{"ok":true,"createdId":999}',encoding='utf-8')
        scene = accept.scene(fixture.scene,accept.profiles.load_profile(),99)
        character = scene['entities'][0]['id']
        args = dict(skill_run=run,character_id=character,skill_id_slot='uint',skill_slot=3,replace_policy=1)
        with patch.object(accept.profiles,'windows_api',side_effect=AssertionError('no Windows API')):
            result = ability.compile_from_receipt(**args)
        self.assertEqual(result['createdSkillId'],0x41800001)
        self.assertTrue(result['rawReceiptRevalidated'])
        self.assertFalse(result['farmingSkillTriggerVerified'])
        fixture.record['skillResult']['createdId']=999;fixture.save()
        with self.assertRaisesRegex(ValueError,'SKILL_RAW_SUMMARY_MISMATCH:createdId'):
            ability.compile_from_receipt(**args)


if __name__ == '__main__':
    unittest.main()
