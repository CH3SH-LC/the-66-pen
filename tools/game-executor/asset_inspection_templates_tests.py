"""Unified-gate-only tests for unplaced-template evidence and measurement batches."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import asset_inspection_templates as t
import asset_inspection_common as c
import asset_inspection as cli
from asset_inspection_tests import png,fixture

def selection():return dict(schema='mw-city-role-selection-verified',grade='thumbnail-reviewed',roles={
    'house':dict(templateId=99,alternativesSameStyle=[100],evidence='Declared human thumbnail review; not runtime')})

def catalog(tid=99):return dict(found=True,templateId=tid,name='same-name',iconPath=str(tid)+'.png',nativeKind=0,sourceSha256=c.CATALOG_SHA)
def session():return dict(schemaVersion=1,pid=1,tid=2,window=3,windowClass='fixture',processCreation=4,threadCreation=5,image='fixture.invalid')

def wire_bytes(tid):
    out=bytearray([8])
    while tid>=128:out.append((tid&127)|128);tid>>=7
    out.append(tid);return bytes(v^229 for v in out)

class PureTemplateTests(unittest.TestCase):
    def test_selected_exact_id_not_name(self):self.assertEqual(t.selection_rows(selection())[0]['templateId'],99)
    def test_alternatives_are_opt_in(self):self.assertEqual([x['templateId'] for x in t.selection_rows(selection(),True)],[99,100])
    def test_alternatives_never_approved(self):self.assertFalse(t.selection_rows(selection(),True)[1]['choiceApprovedByThisTool'])
    def test_pending_overlap_reported(self):
        d=selection();d['pendingVerification']={'roles':['house']};self.assertTrue(t.selection_rows(d)[0]['selectionConflict'])
    def test_unrealizable_overlap_reported(self):
        d=selection();d['unrealizableByEvidence']={'roles':{'house':'unknown'}};self.assertTrue(t.selection_rows(d)[0]['selectionConflict'])
    def test_unreviewed_grade_is_not_promoted(self):
        d=selection();d['grade']='sourced';self.assertIn('ROLE_REVIEW_GRADE_UNSUPPORTED',t.selection_rows(d)[0]['selectionIssues'])
    def test_missing_review_is_not_promoted(self):
        d=selection();del d['roles']['house']['evidence'];self.assertTrue(t.selection_rows(d)[0]['selectionConflict'])
    def test_duplicate_alternative_rejected(self):
        d=selection();d['roles']['house']['alternativesSameStyle']=[99]
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):t.selection_rows(d,True)
    def test_invalid_template_id_rejected(self):
        d=selection();d['roles']['house']['templateId']=True
        with self.assertRaises(ValueError):t.selection_rows(d)
    def test_reference_stays_unclassified(self):
        fields=[dict(f=2,w=2,m=[dict(f=22,w=2,m=[dict(f=1,w=2,m=[dict(f=1,w=0,v=123)])])])]
        self.assertEqual(t.unclassified_reference(fields),123)
    def test_top_level_22_is_not_the_same_reference(self):
        self.assertIsNone(t.unclassified_reference([dict(f=22,w=2,m=[dict(f=1,w=2,m=[dict(f=1,w=0,v=123)])])]))
    def test_no_reference_is_unknown(self):self.assertIsNone(t.unclassified_reference([]))
    def test_duplicate_wire_identity_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNIQUE'):t.wire_one([dict(f=1,w=0,v=1),dict(f=1,w=0,v=2)],1,0)
    def test_wire_payload_not_json_guess(self):
        fields,_=t.decode_official(wire_bytes(99));self.assertEqual(t.wire_one(fields,1,0)['v'],99)
    def test_malformed_wire_is_structured_error(self):
        with self.assertRaisesRegex(ValueError,'OFFICIAL_WIRE_INVALID'):t.decode_official(b'\xe5')
    def test_empty_wire_rejected(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):t.decode_official(b'')
    def test_every_existing_instance_retained(self):
        s={'entities':[{'id':900,'configId':99},{'id':100,'configId':99},{'id':99,'configId':2}]}
        batches,present,missing=t.batches_for(s,[99,100]);self.assertEqual(batches[0]['entityIds'],[900,100]);self.assertEqual(missing,[100])
    def test_more_than_eight_is_chunked(self):
        s={'entities':[{'id':i,'configId':99} for i in range(1,18)]};b,_,_=t.batches_for(s,[99]);self.assertEqual([len(x['entityIds']) for x in b],[8,8,1])
    def test_duplicate_instance_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):t.batches_for({'entities':[{'id':1,'configId':99}]*2},[99])
    def test_missing_template_does_not_guess_instance(self):
        b,p,m=t.batches_for({'entities':[{'id':99,'configId':2}]},[99]);self.assertEqual((b,p,m),([],{},[99]))
    def test_session_auxiliary_note_can_change(self):
        a=session();b=dict(a,source='new observation');self.assertTrue(t.same_session(a,b))
    def test_session_recycled_pid_rejected(self):
        a=session();b=dict(a,processCreation=9);self.assertFalse(t.same_session(a,b))
    def test_missing_session_identity_rejected(self):self.assertFalse(t.same_session({},{}))

class FileTemplateTests(unittest.TestCase):
    def setUp(self):
        c.OUTPUT.mkdir(parents=True,exist_ok=True);self.root=Path(tempfile.mkdtemp(prefix='template-contract-',dir=c.OUTPUT)).resolve()
        self.selection=self.root/'selection.json';c.write(self.selection,selection())
        self.picture=self.root/'icon.png';self.picture.write_bytes(png())
        self.icons=self.root/'icons.json';self.icon_doc=dict(ok=True,kind='asset-inspection-icons-v1',sourceBundleSha256=t.INSTALLED_SHA,capturedBundleSha256=t.INNER_SHA,rows=[
            dict(templateId=99,ok=True,thumbnailPixelsVerified=True,catalog={'sourceSha256':c.CATALOG_SHA},exactZipMember='99.png',assetBundleSha256=t.INNER_SHA,imagePath=str(self.picture),imageSha256=c.sha(self.picture))])
        c.write(self.icons,self.icon_doc)
    def tearDown(self):
        if not self.root.is_relative_to(c.OUTPUT.resolve()):raise RuntimeError('Unsafe cleanup')
        shutil.rmtree(self.root)
    def test_exact_icon_bytes_bound(self):
        rows,_=t.icon_evidence(self.icons,[99],{'99':catalog()});self.assertTrue(rows['99']['thumbnailPixelsVerified']);self.assertFalse(rows['99']['runtimeModelAppearanceVerified'])
    def test_changed_icon_rejected(self):
        self.picture.write_bytes(png()+b'x')
        with self.assertRaisesRegex(ValueError,'BYTES_CHANGED'):t.icon_evidence(self.icons,[99],{'99':catalog()})
    def test_wrong_icon_full_path_rejected(self):
        item=catalog();item['iconPath']='other/99.png'
        with self.assertRaisesRegex(ValueError,'IDENTITY'):t.icon_evidence(self.icons,[99],{'99':item})
    def test_unselected_icon_missing_rejected(self):
        with self.assertRaisesRegex(ValueError,'MISSING'):t.icon_evidence(self.icons,[100],{'100':catalog(100)})
    def test_official_duplicate_id_refused(self):
        official=self.root/'official';official.mkdir();(official/'a.mihoyobin').write_bytes(wire_bytes(99));(official/'b.mihoyobin').write_bytes(wire_bytes(99))
        with patch.object(t,'OFFICIAL',official),self.assertRaisesRegex(ValueError,'DUPLICATE'):t.official_index()
    def plan(self):
        official=self.root/'official';official.mkdir();source=official/'a.mihoyobin';source.write_bytes(wire_bytes(99))
        with patch.object(t,'OFFICIAL',official),patch.object(t,'catalog_evidence',return_value={'99':catalog()}):return t.make_plan(self.selection,self.icons,self.root/'plan')
    def test_unplaced_plan_has_no_geometry_or_dispatch(self):
        result=self.plan();row=result['rows'][0]
        self.assertEqual(result['missingTemplateIds'],[99]);self.assertEqual(result['batches'],[]);self.assertIsNone(row['boundsRenderer']);self.assertFalse(row['modelIdentityVerified']);self.assertFalse(result['dispatchAttempted'])
    def test_original_template_bytes_preserved(self):
        row=self.plan()['rows'][0];self.assertEqual(Path(row['capturedOfficialFile']['path']).read_bytes(),wire_bytes(99))
    def test_no_baseline_plan_cannot_prepare(self):
        result=self.plan()
        with self.assertRaisesRegex(ValueError,'NO_OBSERVED_BASELINE'):t.prepare_batch(Path(result['out'])/'plan.json',0,self.root/'absent')
    def test_plan_does_not_overwrite_original(self):
        self.plan()
        with patch.object(t,'OFFICIAL',self.root/'official'),patch.object(t,'catalog_evidence',return_value={'99':catalog()}),self.assertRaisesRegex(ValueError,'MUST_BE_NEW'):
            t.make_plan(self.selection,self.icons,self.root/'plan')
    def test_report_missing_samples_stays_blocked(self):
        result=self.plan();out=t.template_report(Path(result['out'])/'plan.json',[])
        self.assertFalse(out['allSelectedSizeEvidenceReady']);self.assertFalse(out['allSelectedGeometryMeasured']);self.assertIsNone(out['cityTemplates'][0]['boundsRenderer'])
    def test_report_changed_selection_requires_replan(self):
        result=self.plan();self.selection.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'SELECTION_CHANGED'):t.template_report(Path(result['out'])/'plan.json',[])
    def test_nonmatching_receipt_plan_rejected(self):
        result=self.plan();path=Path(result['out'])/'plan.json';result['session']=session();path.write_text(json.dumps(result),encoding='utf-8')
        report=dict(ok=True,queryComplete=True,sceneUnchanged=True,cleanupVerified=True,session=session(),levelId=None,measurementPlan={})
        with patch('asset_inspection_receipt.decode',return_value=report),self.assertRaisesRegex(ValueError,'PLAN_BINDING'):t.template_report(Path(result['out'])/'plan.json',[self.root/'run'])
    def observed_plan(self):
        result=self.plan();path=Path(result['out'])/'plan.json';result.update(session=session(),levelId=1843,baseline={'run':'historical'},missingTemplateIds=[])
        result['rows'][0]['sampleEntityIds']=[1];result['batches']=[dict(index=0,entityIds=[1],templateIds={'1':99})]
        path.write_text(json.dumps(result),encoding='utf-8');return result,path
    def test_prepare_uses_selected_batch_and_pins_plan(self):
        result,path=self.observed_plan();snapshot={'entities':[{'id':1,'configId':99}],'levelObservation':{'levelId':1843}}
        with patch('build.baseline',return_value=(session(),snapshot,b'')),patch.object(t,'catalog_evidence',return_value={'99':catalog()}),patch('asset_inspection_build.prepare',return_value={'ok':True}) as build:
            self.assertTrue(t.prepare_batch(path,0,self.root/'fresh')['ok'])
        args=build.call_args.args[0];self.assertEqual(args.entity_id,[1]);self.assertEqual(args.measurement_plan['planSha256'],c.sha(path))
    def test_new_existing_instance_requires_replan(self):
        result,path=self.observed_plan();snapshot={'entities':[{'id':1,'configId':99},{'id':2,'configId':99}],'levelObservation':{'levelId':1843}}
        with patch('build.baseline',return_value=(session(),snapshot,b'')),patch.object(t,'catalog_evidence',return_value={'99':catalog()}),self.assertRaisesRegex(ValueError,'INSTANCE_SET_CHANGED'):
            t.prepare_batch(path,0,self.root/'fresh')
    def test_invalid_batch_never_builds(self):
        result,path=self.observed_plan();snapshot={'entities':[{'id':1,'configId':99}],'levelObservation':{'levelId':1843}}
        with patch('build.baseline',return_value=(session(),snapshot,b'')),patch.object(t,'catalog_evidence',return_value={'99':catalog()}),self.assertRaisesRegex(ValueError,'BATCH_INDEX'):
            t.prepare_batch(path,1,self.root/'fresh')
    def complete_report(self,path):
        sample=c.measure(fixture());sample.update(templateId=99,catalog=catalog())
        return dict(ok=True,queryComplete=True,sceneUnchanged=True,cleanupVerified=True,session=session(),levelId=1843,
            measurementPlan={'planSha256':c.sha(path),'plan':str(path)},measurements=[sample],run='synthetic-readonly',rawReceiptSha256='fixture')
    def test_complete_geometry_does_not_claim_model_appearance(self):
        _,path=self.observed_plan()
        with patch('asset_inspection_receipt.decode',return_value=self.complete_report(path)):out=t.template_report(path,[self.root/'run'])
        self.assertTrue(out['allSelectedSizeEvidenceReady']);self.assertFalse(out['appearanceVerified']);self.assertFalse(out['cityTemplates'][0]['modelIdentityVerified'])
    def test_duplicate_raw_observations_refused(self):
        _,path=self.observed_plan()
        with patch('asset_inspection_receipt.decode',return_value=self.complete_report(path)),self.assertRaisesRegex(ValueError,'DUPLICATE'):
            t.template_report(path,[self.root/'run',self.root/'run'])
    def test_invalid_template_plan_arguments_are_json(self):
        with patch('sys.stdout') as stdout:self.assertEqual(cli.main(['template-plan']),2)
        self.assertTrue(stdout.write.called)

if __name__=='__main__':unittest.main()
