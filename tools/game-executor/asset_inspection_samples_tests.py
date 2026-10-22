"""Offline synthetic acceptance for sample preparation and exact-ID recovery lists."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_inspection_samples as s
import asset_inspection_common as c
from asset_inspection_templates_tests import selection,session

class SampleTests(unittest.TestCase):
    def setUp(self):
        c.OUTPUT.mkdir(parents=True,exist_ok=True);self.root=Path(tempfile.mkdtemp(prefix='sample-contract-',dir=c.OUTPUT)).resolve()
        self.selected=self.root/'selection.json';c.write(self.selected,selection())
        self.plan=self.root/'plan.json';c.write(self.plan,dict(ok=True,kind=s.PLAN_KIND,baseline={'run':'historical'},
            session=session(),levelId=1843,selection=dict(path=str(self.selected),sha256=c.sha(self.selected)),
            missingTemplateIds=[99,100],rows=[{'templateId':99},{'templateId':100}]))
    def tearDown(self):
        if not self.root.is_relative_to(c.OUTPUT.resolve()):raise RuntimeError('Unsafe test cleanup')
        shutil.rmtree(self.root)
    def sequence(self):
        out=s.sample_plan(self.plan,[1.,2.,3.],self.root/'samples');return out,self.root/'samples/samples.json'
    def test_samples_use_explicit_anchor_unit_scale(self):
        out,_=self.sequence();self.assertEqual(out['stages'][0]['placement']['position'],[1,2,3]);self.assertEqual(out['stages'][0]['placement']['scale'],[1,1,1])
    def test_samples_are_sequential_not_guessed_grid(self):
        out,_=self.sequence();self.assertEqual(out['maxSimultaneousNewEntities'],1);self.assertEqual(out['stages'][0]['placement']['position'],out['stages'][1]['placement']['position']);self.assertTrue(out['stages'][1]['requiresPreviousSampleRecovery'])
    def test_sample_plan_never_claims_authorization_or_execution(self):
        out,_=self.sequence();self.assertTrue(out['requiresCoordinatorPlacementApproval']);self.assertFalse(out['gameWritesPerformed']);self.assertFalse(out['anchorClearanceVerified'])
    def test_nonfinite_anchor_rejected(self):
        with self.assertRaisesRegex(ValueError,'ANCHOR'):s.sample_plan(self.plan,[0,float('nan'),0],self.root/'out')
    def test_unchanged_selection_required(self):
        self.selected.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'SELECTION_CHANGED'):self.sequence()
    def test_sample_plan_never_overwrites(self):
        self.sequence()
        with self.assertRaisesRegex(ValueError,'MUST_BE_NEW'):self.sequence()
    def test_stage_index_rejected(self):
        _,path=self.sequence()
        with self.assertRaisesRegex(ValueError,'STAGE_INDEX'):s.load_sequence(path,-1)
    def test_changed_placement_rejected(self):
        out,path=self.sequence();Path(out['stages'][0]['placementPlan']['path']).write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'PLACEMENT_CHANGED'):s.load_sequence(path,0)
    def setup_bind(self):
        sequence,path=self.sequence();before=dict(entities=[],levelObservation={'levelId':1843},pointers={'currentContext':1},origin=[0,0,0])
        entity=dict(owner=101,config=102,context=1,dictionaryKey=7,id=7,configId=99)
        after=dict(before,entities=[entity]);run=self.root/'creation';run.mkdir();c.write(run/'prepared.json',{'session':session()})
        commit=self.root/'commit.json';c.write(commit,{'run':str(run)})
        baseline=self.root/'before';baseline.mkdir()
        for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json'):(baseline/name).write_text('{}',encoding='utf-8')
        return path,before,after,commit,baseline
    def test_binding_uses_only_native_returned_id(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(session(),before,b'')),patch.object(s.scale,'validate_commit',return_value=(after,[7])) as validate:
            out=s.bind_sample(path,0,commit,baseline)
        self.assertEqual(out['exactCreatedEntityIds'],[7]);self.assertFalse(out['removalAuthorizedByThisManifest']);self.assertEqual(validate.call_args.kwargs['expected_before'],before)
    def test_existing_template_cannot_be_called_new_sample(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(session(),after,b'')),self.assertRaisesRegex(ValueError,'PREVIOUS_SAMPLE_PRESENT'):s.bind_sample(path,0,commit,baseline)
    def test_prior_sample_must_be_removed(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(session(),after,b'')),self.assertRaisesRegex(ValueError,'PREVIOUS_SAMPLE_PRESENT'):s.bind_sample(path,1,commit,baseline)
    def test_multiple_created_ids_refused(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(session(),before,b'')),patch.object(s.scale,'validate_commit',return_value=(after,[7,8])),self.assertRaisesRegex(ValueError,'SINGLE_CREATED'):
            s.bind_sample(path,0,commit,baseline)
    def test_different_process_session_refused(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(dict(session(),processCreation=8),before,b'')),self.assertRaisesRegex(ValueError,'SESSION_OR_LEVEL'):
            s.bind_sample(path,0,commit,baseline)
    def recovery(self):
        path,before,after,commit,baseline=self.setup_bind()
        with patch.object(s.b,'baseline',return_value=(session(),before,b'')),patch.object(s.scale,'validate_commit',return_value=(after,[7])):
            out=s.bind_sample(path,0,commit,baseline)
        recovery=self.root/'recovery.json';c.write(recovery,out);return recovery,out,before,after
    def test_recovery_requires_target_absent(self):
        path,out,before,after=self.recovery()
        with patch.object(s,'bind_sample',return_value=out),patch.object(s.b,'baseline',side_effect=[(session(),after,b''),(session(),before,b'')]),self.assertRaisesRegex(ValueError,'STILL_PRESENT'):
            s.verify_recovery(path,self.root/'after')
    def test_recovery_exact_original_identity_set(self):
        path,out,before,after=self.recovery()
        with patch.object(s,'bind_sample',return_value=out),patch.object(s.b,'baseline',return_value=(session(),before,b'')):
            result=s.verify_recovery(path,self.root/'after')
        self.assertTrue(result['sampleAbsent']);self.assertFalse(result['persistentSaveVerified']);self.assertFalse(result['allTransformsPreservedVerified'])
    def test_recovery_unrelated_added_entity_refused(self):
        path,out,before,after=self.recovery();extra=copy.deepcopy(after);extra['entities'][0]['id']=8;extra['entities'][0]['dictionaryKey']=8
        with patch.object(s,'bind_sample',return_value=out),patch.object(s.b,'baseline',side_effect=[(session(),extra,b''),(session(),before,b'')]),self.assertRaisesRegex(ValueError,'SCENE_CHANGED'):
            s.verify_recovery(path,self.root/'after')

if __name__=='__main__':unittest.main()
