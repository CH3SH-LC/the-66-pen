"""Review preparation tests with synthetic files and mocked native/session reads."""
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import copy
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import prepare_reopen_review as api
import native_profiles as profiles
import test_build_reopen_profile as fixtures
import test_native_reopen_acceptance as content_fixtures


class ReviewPreparationTests(unittest.TestCase):
    write=staticmethod(fixtures.ReopenReviewTests.write)
    save_review=fixtures.ReopenReviewTests.save_review
    save_manifest=fixtures.ReopenReviewTests.save_manifest

    def setUp(self):
        fixtures.ReopenReviewTests.setUp(self)
        self.addCleanup(patch.stopall)
        patch.object(api.acceptance,'ROOT',self.base).start()
        patch.object(profiles,'validate_session',side_effect=lambda v:v).start()
        patch.object(api,'now_utc',return_value=self.now).start()
        for root in (self.source,self.backup):(root/'Beyond_Local_Save_Player.gip').write_bytes(b'PLAYER')
        self.manifest['files'].append(dict(relativePath='Beyond_Local_Save_Player.gip',bytes=6,
                                          sha256=profiles.sha256(self.source/'Beyond_Local_Save_Player.gip')))
        for row in self.manifest['files']:row['mtimeNs']=(self.source/row['relativePath']).stat().st_mtime_ns
        self.manifest.update(fileCount=len(self.manifest['files']),totalBytes=sum(r['bytes'] for r in self.manifest['files']),createdUtc=self.now.isoformat())
        self.save_manifest()
        self.formal=dict(entities={17:dict(configurationReferenceId=20,templateId=20,transform={})},graphs={},bindings=[])
        self.baseline.update(baselineRun=str(self.runtime/'baseline'),context=dict(entities=[dict(id=17,dictionaryKey=17,configId=20)],levelCatalog=dict(counts=dict(dirtyByte=0))))
        patch.object(api.acceptance,'formal_content',return_value=self.formal).start()
        self.editor=content_fixtures.editor_fixture(self.formal)
        # Schema 2 carries one shared raw graph: rows refer to named roots in
        # its dictionary, preserving cross-row object identity for acceptance.
        entries=[]
        for entity in self.editor['content']['entities']:
            key='entity:'+str(entity['id'])
            entries.append(dict(key=key,value=entity['rawFields']['value']))
            entity['rawFields']={'rootKey':key}
        entries.append(dict(key='retained-init',value=self.editor['content']['retainedInitialization']['value']))
        self.editor['content']['retainedInitialization']={'rootKey':'retained-init'}
        self.editor['content']['rawFields']=content_fixtures.raw(dict(root={'refId':1},objects=[
            dict(objectId=1,type='System.Collections.Generic.Dictionary`2[System.String,System.Object]',
                 count=len(entries),entries=entries)]))
        self.editor.update(schemaVersion=2,scope='materialized-editor-business-fields-and-retained-initialization-shared-graph')
        self.editor.update(observedUtc=self.now.isoformat(),finishedUtc=self.now.isoformat())
        self.editor_path=self.runtime/'editor.json';self.write(self.editor_path,self.editor)
        self.observer=dict(ok=True,active=True,observerRegistered=True,originalReceiversPreserved=True,
            callbackErrors=0,contractRejectedCallbacks=0,observerCleanupError=None,
            levelInitialization=dict(started=True,active=True,managerSameReference=True,originalReceiverOrderPreserved=True,
                builtinBeforeOwnObserver=True,currentPayloadPresent=True,currentPayloadSameReference=True,ownReceiverCount=1,
                source='received-1022-packet-observer',overflow=False,parseErrors=0,evidenceErrors=0,threadErrors=0,droppedEvents=0,
                retainedEvents=0,sequence=0,events=[],currentLevelId=api.baseline_api.LEVEL,baselineLevelId=api.baseline_api.LEVEL,
                observationId='fixture-observation',initStartedUtc=self.now.isoformat()),
            observerTiming=dict(scope='current-observer-instance-only',registrationCompletedTick=10,
                registrationCompletedUtc=self.now.isoformat(),stoppedUtc=None,stoppedTick=None))
        self.observer_path=self.runtime/'observer.json';self.write(self.observer_path,self.observer)
        self.session_path=self.runtime/'session.json';self.write(self.session_path,self.session)
        self.output=self.runtime/'reviews'
        self.bridge_dir=self.runtime/'editor-bridge/runs'/self.review['bridgeRunId']
        self.bridge_dir.mkdir(parents=True)
        self.editor_path=self.bridge_dir/'inspect-reopen-content-response.json';self.write(self.editor_path,self.editor)
        self.observer_path=self.bridge_dir/'start-external-asset-observer-response.json';self.write(self.observer_path,self.observer)
        self.editor_image=str(Path(self.session['image']).resolve().parent/'BeyondAssets/BeyondAssistEditor/BeyondEditor.exe')
        self.scope=dict(pid=88,startUtcTicks=str(504911232000000000+66),expectedExe=self.editor_image,
            pipeName='miliastra-bridge-'+self.review['bridgeRunId'],expiresUtc=(self.now+timedelta(seconds=295)).isoformat())
        self.ready=dict(recordedUtc=(self.now-timedelta(seconds=5)).isoformat(),code=0,accepted=True,reason=None,
            hostPid=88,hostStartUtcTicks=self.scope['startUtcTicks'],hostExePath=self.editor_image,
            settingsPid=88,settingsStartUtcTicks=self.scope['startUtcTicks'],settingsExpectedExe=self.editor_image,
            settingsExpiresUtc=self.scope['expiresUtc'],pipeName=self.scope['pipeName'],readyWritten=True,readyWriteFailure=None)
        self.write(self.bridge_dir/'bridge-settings.json',self.scope);self.write(self.bridge_dir/'bridge-ready.json',self.ready)
        self.query_editor=patch.object(api,'query_editor_identity',return_value=dict(pid=88,creationFileTime=66,image=self.editor_image)).start()

    def prepare(self,**kwargs):
        return api.prepare(self.session_path,self.runtime/'baseline',self.manifest_path,self.editor_path,
            self.observer_path,self.review['bridgeRunId'],output_root=self.output,**kwargs)

    def standard_backup(self):
        standard_dir=self.runtime/'standard';standard_files=standard_dir/'files'
        for row in self.manifest['files']:
            path=standard_files/row['relativePath'];path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((self.backup/row['relativePath']).read_bytes())
        self.standard=dict(schemaVersion=1,createdUtc=self.now.isoformat(),label='synthetic',source=str(self.source),
            fileCount=self.manifest['fileCount'],totalBytes=self.manifest['totalBytes'],files=[
                dict(relpath=r['relativePath'],size=r['bytes'],sha256=r['sha256'],mtimeNs=r['mtimeNs']) for r in self.manifest['files']])
        self.manifest_path=standard_dir/'manifest.json';self.write(self.manifest_path,self.standard)

    def test_standard_backup_schema_produces_review_accepted_by_builder(self):
        self.standard_backup();original=self.manifest_path.read_bytes()
        result=self.prepare()
        self.assertTrue(result['ok']);self.assertFalse(result['executed']);self.assertFalse(result['businessVerified'])
        review=api.review_api.read_json(result['reviewPath'])
        self.assertEqual(review['allowedCalls'],1)
        self.assertEqual(review['reopenLifecycle']['accountBaselineSha256'],result['accountBaselineSha256'])
        normalized=api.review_api.read_json(result['accountBackupManifest'])
        self.assertEqual(normalized['backup'],str(self.manifest_path.parent/'files'))
        self.assertEqual(normalized['files'],self.manifest['files'])
        self.assertEqual(original,self.manifest_path.read_bytes())
        api.builder.validate_review(result['reviewPath'],self.session)
        api.acceptance.read_account(result['accountBackupManifest'])

    def test_legacy_manifest_supported_without_modifying_original(self):
        original=self.manifest_path.read_bytes();result=self.prepare()
        self.assertTrue(result['ok']);self.assertEqual(original,self.manifest_path.read_bytes())

    def test_each_preparation_gets_new_request_identity(self):
        one=self.prepare();two=self.prepare()
        self.assertNotEqual(one['requestId'],two['requestId']);self.assertNotEqual(one['reviewPath'],two['reviewPath'])

    def test_stale_source_or_backup_refused_before_review(self):
        for root in (self.source,self.backup):
            path=root/self.target_rel;original=path.read_bytes();path.write_bytes(b'changed')
            with self.subTest(root=root),self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_OR_BACKUP_CHANGED'):self.prepare()
            path.write_bytes(original)
        self.assertFalse(self.output.exists())

    def test_manifest_schema_and_totals_refused(self):
        original=copy.deepcopy(self.manifest)
        for key,value,reason in [('schemaVersion',2,'BACKUP_SCHEMA'),('fileCount',0,'BACKUP_TOTALS'),('totalBytes',0,'BACKUP_TOTALS')]:
            self.manifest=copy.deepcopy(original);self.manifest[key]=value;self.save_manifest()
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,reason):self.prepare()

    def test_path_escape_and_case_alias_duplicate_refused(self):
        original=copy.deepcopy(self.manifest)
        for rel in ('../escape',self.target_rel.upper()):
            self.manifest=copy.deepcopy(original);extra=dict(self.manifest['files'][0],relativePath=rel);self.manifest['files'].append(extra);self.save_manifest()
            with self.subTest(rel=rel),self.assertRaisesRegex(profiles.ProfileError,'BACKUP_PATH'):self.prepare()

    def test_extra_backup_file_refused(self):
        (self.backup/'unexpected').write_bytes(b'new')
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_FILE_SET_CHANGED'):self.prepare()

    def test_required_player_save_cannot_be_omitted(self):
        for root in (self.source,self.backup):(root/'Beyond_Local_Save_Player.gip').unlink()
        self.manifest['files']=self.manifest['files'][:-1];self.manifest['fileCount']-=1;self.manifest['totalBytes']-=6;self.save_manifest()
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_REQUIRED_FILES'):self.prepare()

    def test_review_binds_scope_ready_process_and_canonical_response_files(self):
        result=self.prepare();review=api.review_api.read_json(result['reviewPath'])
        bridge=review['bridgeEvidence']
        self.assertEqual(bridge['scope']['path'],str(self.bridge_dir/'bridge-settings.json'))
        self.assertEqual(bridge['editorProcess']['creationFileTime'],66)
        self.assertEqual(review['editorBaseline'],bridge['editorResponse'])
        self.assertEqual(review['observerBaseline'],bridge['observerResponse'])
        self.assertLessEqual(api.acceptance.utc(review['expiresUtc']),api.acceptance.utc(self.scope['expiresUtc']))
        self.query_editor.assert_called_with(88)

    def test_copied_business_json_does_not_prove_scope_membership(self):
        self.editor_path=self.runtime/'caller-editor-copy.json';self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_SCOPE_RESPONSE_PATH'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_other_uuid_cannot_borrow_valid_scope(self):
        self.review['bridgeRunId']='22222222-2222-2222-2222-222222222222'
        with self.assertRaises(OSError):self.prepare()
        self.query_editor.assert_not_called()

    def test_expired_closed_or_unaccepted_scope_refused(self):
        self.scope['expiresUtc']=(self.now-timedelta(seconds=1)).isoformat();self.write(self.bridge_dir/'bridge-settings.json',self.scope)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_EXPIRED'):self.prepare()
        self.scope['expiresUtc']=(self.now+timedelta(seconds=295)).isoformat();self.write(self.bridge_dir/'bridge-settings.json',self.scope)
        self.ready['accepted']=False;self.write(self.bridge_dir/'bridge-ready.json',self.ready)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_NOT_READY'):self.prepare()
        (self.bridge_dir/'lease-closed.json').write_text('{}')
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_SCOPE_CLOSED'):self.prepare()

    def test_ready_process_identity_or_pipe_mismatch_refused(self):
        original=copy.deepcopy(self.ready)
        for key,value in [('hostPid',89),('settingsStartUtcTicks','0'),('hostExePath','other.exe'),('pipeName','miliastra-bridge-other')]:
            self.ready=copy.deepcopy(original);self.ready[key]=value;self.write(self.bridge_dir/'bridge-ready.json',self.ready)
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_READY_BINDING'):self.prepare()

    def test_recycled_editor_pid_or_changed_image_refused(self):
        expected=dict(pid=88,creationFileTime=66,image=self.editor_image)
        for key,value in [('creationFileTime',67),('image','other.exe')]:
            self.query_editor.return_value=dict(expected,**{key:value})
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_EDITOR_PROCESS_CHANGED'):self.prepare()

    def test_capture_from_before_scope_was_ready_refused(self):
        self.editor['observedUtc']=(self.now-timedelta(seconds=6)).isoformat();self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_EVIDENCE_PRECEDES_SCOPE'):self.prepare()
        self.editor['observedUtc']=self.now.isoformat();self.write(self.editor_path,self.editor)
        self.observer['levelInitialization']['initStartedUtc']=(self.now-timedelta(seconds=6)).isoformat();self.write(self.observer_path,self.observer)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_EVIDENCE_PRECEDES_SCOPE'):self.prepare()

    def test_failed_final_scope_check_retains_only_nonexecutable_candidate(self):
        original=api.builder.validate_review
        def close_after_validation(*args):
            result=original(*args);(self.bridge_dir/'lease-closed.json').write_text('{}');return result
        with patch.object(api.builder,'validate_review',side_effect=close_after_validation),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_SCOPE_CLOSED'):self.prepare()
        self.assertEqual(list(self.output.glob('*/review.json')),[])
        candidates=list(self.output.glob('*/review.pending.json'));self.assertEqual(len(candidates),1)
        rejected=api.review_api.read_json(candidates[0]);self.assertEqual(rejected['schemaVersion'],0)
        self.assertEqual(rejected['candidate']['operation'],'level.reopen-current')
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_REVIEW_CONTRACT'):original(candidates[0],self.session)

    def test_scope_response_mutation_during_preparation_refused(self):
        original=api.acceptance.compare_content
        def mutate(*args):
            result=original(*args);self.ready['hostPid']=89;self.write(self.bridge_dir/'bridge-ready.json',self.ready);return result
        with patch.object(api.acceptance,'compare_content',side_effect=mutate),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BRIDGE_READY_BINDING'):self.prepare()

    def test_schema_one_editor_refused_before_review(self):
        self.editor=content_fixtures.editor_fixture(self.formal)
        self.editor.update(observedUtc=self.now.isoformat(),finishedUtc=self.now.isoformat())
        self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(profiles.ProfileError,'CURRENT_SHARED_EDITOR_SCHEMA_REQUIRED'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_schema_two_requires_real_shared_graph_contract(self):
        self.editor['content']['entities'][0]['rawFields']={'rootKey':'missing-root'}
        self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(ValueError,'EDITOR_SHARED_ROOT_KEY'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_partial_editor_capture_and_configuration_mismatch_refused(self):
        self.editor['complete']=False;self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(ValueError,'EDITOR_INCOMPLETE'):self.prepare()
        self.editor['complete']=True;self.editor['content']['entities'][0]['templateId']+=1;self.write(self.editor_path,self.editor)
        with self.assertRaisesRegex(ValueError,'FORMAL_CONFIGURATION_REFERENCES'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_backup_creation_time_is_required_aware_valid_and_not_future(self):
        for value in (None,'invalid',self.now.replace(tzinfo=None).isoformat(),(self.now+timedelta(seconds=1)).isoformat()):
            self.manifest['createdUtc']=value;self.save_manifest()
            with self.subTest(value=value),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BACKUP_TIME'):self.prepare()
        del self.manifest['createdUtc'];self.save_manifest()
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_BACKUP_TIME'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_observer_initialization_time_is_required_aware_valid_and_not_future(self):
        for value in (None,'invalid',self.now.replace(tzinfo=None).isoformat(),(self.now+timedelta(seconds=1)).isoformat()):
            self.observer['levelInitialization']['initStartedUtc']=value;self.write(self.observer_path,self.observer)
            with self.subTest(value=value),self.assertRaisesRegex(profiles.ProfileError,'REOPEN_OBSERVER_INIT_TIME'):self.prepare()
        del self.observer['levelInitialization']['initStartedUtc'];self.write(self.observer_path,self.observer)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_OBSERVER_INIT_TIME'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_observer_initialization_must_precede_registration(self):
        self.observer['observerTiming']['registrationCompletedUtc']=(self.now-timedelta(seconds=1)).isoformat()
        self.write(self.observer_path,self.observer)
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_OBSERVER_INIT_TIME'):self.prepare()

    def test_prepared_observer_before_fields_satisfy_final_acceptance_contract(self):
        self.prepare()
        started=self.now+timedelta(seconds=1);finished=started+timedelta(seconds=1)
        after=copy.deepcopy(self.observer)
        after['levelInitialization'].update(currentPayloadSameReference=False,retainedEvents=1,sequence=1,
            events=[dict(sequence=1,parsed=True,error=None,levelId=api.baseline_api.LEVEL,receivedUtc=started.isoformat())])
        result=api.acceptance.observer_evidence(self.observer,after,started,finished)
        self.assertTrue(result['freshInitializationBound'])
        self.assertFalse(result['loadProof'])

    def test_stale_editor_or_observer_refused(self):
        self.editor['observedUtc']=(self.now-timedelta(seconds=4)).isoformat();self.write(self.editor_path,self.editor)
        with patch.object(api,'now_utc',return_value=self.now+timedelta(seconds=180)),self.assertRaisesRegex(profiles.ProfileError,'EDITOR_NOT_FRESH'):self.prepare()
        self.editor['observedUtc']=self.now.isoformat();self.write(self.editor_path,self.editor)
        self.observer['observerTiming']['registrationCompletedUtc']=(self.now-timedelta(seconds=2)).isoformat()
        self.observer['levelInitialization']['initStartedUtc']=(self.now-timedelta(seconds=3)).isoformat();self.write(self.observer_path,self.observer)
        with patch.object(api,'now_utc',return_value=self.now+timedelta(seconds=9)),self.assertRaisesRegex(profiles.ProfileError,'OBSERVER_NOT_FRESH'):self.prepare()

    def test_inactive_or_dirty_observer_refused(self):
        original=copy.deepcopy(self.observer)
        for target,key,value,reason in [(None,'active',False,'OBSERVER_INACTIVE'),('levelInitialization','currentLevelId',99,'OBSERVER_LEVEL_IDENTITY'),('levelInitialization','sequence',1,'BASELINE_NOT_CLEAN'),(None,'callbackErrors',1,'OBSERVER_ERRORS')]:
            self.observer=copy.deepcopy(original);obj=self.observer if target is None else self.observer[target];obj[key]=value;self.write(self.observer_path,self.observer)
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,reason):self.prepare()

    def test_baseline_failure_and_mutation_refused(self):
        self.load.side_effect=profiles.ProfileError('REOPEN_TYPE_FAILED')
        with self.assertRaisesRegex(profiles.ProfileError,'REOPEN_TYPE_FAILED'):self.prepare()
        self.load.side_effect=[self.baseline,dict(self.baseline,evidenceHashes={})]
        with self.assertRaisesRegex(profiles.ProfileError,'BASELINE_CHANGED'):self.prepare()
        self.assertFalse(self.output.exists())

    def test_input_changed_during_content_check_refused(self):
        original=api.acceptance.compare_content
        def racing(*args):
            result=original(*args);self.session_path.write_text('{}');return result
        with patch.object(api.acceptance,'compare_content',side_effect=racing),self.assertRaisesRegex(profiles.ProfileError,'INPUT_CHANGED'):self.prepare()

    def test_ttl_bound_and_bridge_identity_refused(self):
        for ttl in (0,14,301,True):
            with self.subTest(ttl=ttl),self.assertRaisesRegex(profiles.ProfileError,'REVIEW_TTL'):self.prepare(ttl_seconds=ttl)
        self.review['bridgeRunId']='invalid'
        with self.assertRaisesRegex(profiles.ProfileError,'BRIDGE_ID'):self.prepare()


if __name__=='__main__':unittest.main(verbosity=2)
