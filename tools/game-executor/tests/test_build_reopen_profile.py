"""Synthetic review/launch-gate regression tests; never access the game process."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_reopen_profile as builder
import native_profiles as profiles


class ReopenReviewTests(unittest.TestCase):
    def setUp(self):
        parent = profiles.ROOT / '.runtime/reopen-review-tests'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base / '.runtime'
        self.runtime.mkdir()
        self.user = self.base / 'user'
        self.source = self.user / 'AppData/LocalLow/miHoYo/\u539f\u795e/BeyondLocal/12345'
        self.backup = self.runtime / 'backup'
        self.target_rel = f'Beyond_Local_Save_Level/{builder.baseline_api.LEVEL}/{builder.baseline_api.LEVEL}.gil'
        self.files = {self.target_rel: b'SYNTHETIC_CURRENT_GIL_NOT_A_GAME_SAVE', 'config/other.dat': b'OTHER'}
        for rel, data in self.files.items():
            for root in (self.source, self.backup):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        self.manifest_path = self.runtime / 'manifest.json'
        self.manifest = dict(source=str(self.source), backup=str(self.backup), files=[
            dict(relativePath=rel, bytes=len(data), sha256=profiles.sha256(self.source/rel))
            for rel, data in self.files.items()])
        self.write(self.manifest_path, self.manifest)
        self.session = dict(schemaVersion=1, pid=9, tid=8, window=7, windowClass='UnityWndClass',
                            processCreation=6, threadCreation=5, image='synthetic.invalid')
        self.baseline = dict(evidenceHashes={'stdout.jsonl': 'a'*64}, context={'entities': []})
        self.now = datetime.now(timezone.utc)
        self.review = dict(schemaVersion=1, operation='level.reopen-current', allowedCalls=1,
            levelId=builder.baseline_api.LEVEL, requestId='b'*32, createdUtc=self.now.isoformat(),
            expiresUtc=(self.now+timedelta(seconds=290)).isoformat(), session=copy.deepcopy(self.session),
            baselineRun=str(self.runtime/'baseline'), baselineHashes=self.baseline['evidenceHashes'],
            accountBackupManifest=str(self.manifest_path), accountBaselineSha256=profiles.sha256(self.manifest_path),
            bridgeRunId='11111111-1111-1111-1111-111111111111')
        for key in ('editorBaseline', 'observerBaseline'):
            path=self.runtime/(key+'.json');self.write(path, {'synthetic': key})
            self.review[key]=dict(path=str(path), sha256=profiles.sha256(path))
        self.review_path=self.runtime/'review.json'
        self.save_review()
        stack=ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(profiles,'ROOT',self.base))
        stack.enter_context(patch.object(builder,'ROOT',self.base))
        stack.enter_context(patch.dict(os.environ,{'USERPROFILE':str(self.user)}))
        self.load=stack.enter_context(patch.object(builder.baseline_api,'load',return_value=self.baseline))

    @staticmethod
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')

    def save_review(self): self.write(self.review_path,self.review)
    def save_manifest(self):
        self.write(self.manifest_path,self.manifest)
        self.review['accountBaselineSha256']=profiles.sha256(self.manifest_path)
        self.save_review()
    def validate(self):return builder.validate_review(self.review_path,self.session)

    def test_current_saved_hash_is_bound_without_historical_digest(self):
        reviewed,baseline,binding=self.validate()
        self.assertEqual(binding['recovery'],dict(source=str((self.source/self.target_rel).resolve()),
            backup=str((self.backup/self.target_rel).resolve()),sha256=profiles.sha256(self.source/self.target_rel)))
        self.assertEqual(binding['accountManifestSha256'],self.review['accountBaselineSha256'])
        self.assertEqual(baseline,self.baseline)
        self.load.assert_called_once_with(self.review['baselineRun'],self.session)

    def test_normal_save_requires_a_new_matching_manifest_and_review(self):
        for root in (self.source,self.backup): (root/self.target_rel).write_bytes(b'NEW_SAVE_CONTENT')
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_OR_BACKUP_CHANGED'):self.validate()
        row=self.manifest['files'][0];row['bytes']=len(b'NEW_SAVE_CONTENT');row['sha256']=profiles.sha256(self.source/self.target_rel)
        self.save_manifest()
        self.assertEqual(self.validate()[2]['recovery']['sha256'],row['sha256'])

    def test_missing_target_refused_even_with_valid_full_account_copy(self):
        for root in (self.source,self.backup):(root/self.target_rel).unlink()
        self.manifest['files']=self.manifest['files'][1:];self.save_manifest()
        with self.assertRaisesRegex(profiles.ProfileError,'TARGET_MISSING_FROM_BACKUP'):self.validate()

    def test_stale_or_modified_formal_and_backup_refused(self):
        for root in (self.source,self.backup):
            path=root/self.target_rel;before=path.read_bytes();path.write_bytes(b'x'*len(before))
            with self.subTest(root=root),self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_OR_BACKUP_CHANGED'):self.validate()
            path.write_bytes(before)

    def test_missing_backup_refused(self):
        (self.backup/self.target_rel).unlink()
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_OR_BACKUP_CHANGED'):self.validate()

    def test_changed_manifest_refused(self):
        self.manifest_path.write_text('{}')
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_MANIFEST_CHANGED'):self.validate()

    def test_new_account_file_refused(self):
        (self.source/'new.dat').write_bytes(b'new')
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_FILE_SET_CHANGED'):self.validate()

    def test_duplicate_or_escape_path_refused(self):
        original=copy.deepcopy(self.manifest)
        for row in (copy.deepcopy(original['files'][0]),dict(relativePath='../escape',bytes=1,sha256='a'*64)):
            self.manifest=copy.deepcopy(original);self.manifest['files'].append(row);self.save_manifest()
            with self.subTest(row=row),self.assertRaisesRegex(profiles.ProfileError,'BACKUP_PATH'):self.validate()

    def test_wrong_account_root_refused(self):
        self.manifest['source']=str(self.user/'Elsewhere/12345');self.save_manifest()
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_ROOT'):self.validate()

    def test_review_contract_and_identity_remain_required(self):
        original=copy.deepcopy(self.review)
        for key,value,reason in [('allowedCalls',2,'CONTRACT'),('levelId',99,'CONTRACT'),('requestId','not-single-use','REQUEST_ID'),('bridgeRunId','bad','BRIDGE_ID'),('baselineHashes',{},'RAW_BINDING')]:
            self.review=copy.deepcopy(original);self.review[key]=value;self.save_review()
            with self.subTest(key=key),self.assertRaisesRegex(profiles.ProfileError,reason):self.validate()
        self.review=original;self.review['session']['processCreation']+=1;self.save_review()
        with self.assertRaisesRegex(profiles.ProfileError,'REVIEW_SESSION'):self.validate()

    def test_expired_future_and_overlong_review_refused(self):
        for start,end in [(self.now-timedelta(seconds=300),self.now-timedelta(seconds=1)),(self.now+timedelta(seconds=1),self.now+timedelta(seconds=100)),(self.now,self.now+timedelta(seconds=301))]:
            self.review.update(createdUtc=start.isoformat(),expiresUtc=end.isoformat());self.save_review()
            with self.subTest(start=start),self.assertRaisesRegex(profiles.ProfileError,'REVIEW_EXPIRED'):self.validate()

    def test_mutated_editor_evidence_refused(self):
        Path(self.review['editorBaseline']['path']).write_text('{}')
        with self.assertRaisesRegex(profiles.ProfileError,'EVIDENCE_CHANGED'):self.validate()

    def test_review_or_manifest_changed_during_validation_refused(self):
        original_reader=builder.review_api.read_json
        for changed,reason in [(self.review_path,'REVIEW_CHANGED'),(self.manifest_path,'ACCOUNT_MANIFEST_CHANGED')]:
            before=changed.read_bytes()
            def racing_read(path):
                value=original_reader(path)
                if Path(path)==changed:changed.write_bytes(before+b' ')
                return value
            with self.subTest(changed=changed),patch.object(builder.review_api,'read_json',side_effect=racing_read),self.assertRaisesRegex(profiles.ProfileError,reason):self.validate()
            changed.write_bytes(before)

    def prepare(self,*,compile_effect=None):
        session_path=self.runtime/'session.json';self.write(session_path,self.session)
        self.write(self.runtime/'editor-bridge/current-elevated-session.json',dict(deadlineUtc=(self.now+timedelta(minutes=5)).isoformat()))
        native=self.runtime/'native';native.mkdir(exist_ok=True);(native/'fixture.cpp').write_text('// synthetic')
        def header(run,*args,**kwargs):
            (run/'target_config.h').write_text('// synthetic')
            return {'HR_NONCE':1}
        def compile_stub(run):
            for name in ('hook_reopen_receipt.dll','hook_reopen_probe.exe'):(run/name).write_bytes(b'NEVER_EXECUTE_SYNTHETIC')
            if compile_effect:compile_effect()
            return 'synthetic-toolchain'
        with patch.object(profiles,'validate_session',side_effect=lambda v:v),patch.object(profiles,'load_profile',return_value={}),patch.object(profiles,'verify_disk',return_value={'sha256':'a'*64}),patch.object(profiles,'windows_api',return_value=(SimpleNamespace(GetTickCount64=lambda:100),SimpleNamespace(RegisterWindowMessageW=lambda _:42))),patch.object(builder,'NATIVE',native),patch.object(builder,'emit_header',side_effect=header),patch.object(builder,'compile_probe',side_effect=compile_stub),patch.object(builder.readonly,'ROOT',self.base):
            return builder.prepare(session_path,self.review_path,output_root=self.runtime/'builds')

    def test_review_changed_during_compile_refuses_before_claim(self):
        def change():self.review['coordinatorNote']='changed';self.save_review()
        with self.assertRaisesRegex(profiles.ProfileError,'REVIEW_CHANGED_DURING_BUILD'):self.prepare(compile_effect=change)
        self.assertFalse((self.runtime/'game-executor/reopen-claims'/('b'*32+'.json')).exists())

    def test_saved_content_changed_during_compile_refuses_before_claim(self):
        with self.assertRaisesRegex(profiles.ProfileError,'ACCOUNT_OR_BACKUP_CHANGED'):
            self.prepare(compile_effect=lambda:(self.source/self.target_rel).write_bytes(b'CHANGED'))
        self.assertFalse((self.runtime/'game-executor/reopen-claims'/('b'*32+'.json')).exists())

    def test_prepare_keeps_one_shot_claim_and_emits_final_launch_checks(self):
        result=self.prepare();self.assertFalse(result['executed']);self.assertFalse(result['businessVerified'])
        wrapper=Path(result['wrapper']).read_text(encoding='utf-8-sig')
        self.assertIn(builder.emit_recovery_checks(self.validate()[2]),wrapper)
        self.assertLess(wrapper.index('REOPEN_RECOVERY_COPY_CHANGED'),wrapper.index('$taskResult.executed=$true'))
        self.assertIn("[IO.FileMode]::CreateNew",wrapper)
        with self.assertRaises(FileExistsError):self.prepare()

    @unittest.skipUnless(os.name=='nt','PowerShell launch-gate check uses Windows')
    def test_real_powershell_gate_accepts_bound_files_and_refuses_each_mutation(self):
        binding=self.validate()[2]
        script=self.runtime/'launch-check-only.ps1'
        script.write_text("$ErrorActionPreference='Stop'\n"+builder.emit_recovery_checks(binding)+"\nWrite-Output 'BOUND'\n",encoding='utf-8-sig')
        shell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        env=os.environ.copy();env['PSModulePath']=str(shell.parent/'Modules')
        def run():return subprocess.run([str(shell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,text=True,env=env)
        good=run();self.assertEqual(good.returncode,0,good.stderr);self.assertIn('BOUND',good.stdout)
        for path,reason in [(self.review_path,'REOPEN_REVIEW_CHANGED'),(self.manifest_path,'REOPEN_ACCOUNT_MANIFEST_CHANGED'),(self.source/self.target_rel,'REOPEN_SAVED_BASELINE_CHANGED'),(self.backup/self.target_rel,'REOPEN_RECOVERY_COPY_CHANGED')]:
            before=path.read_bytes();path.write_bytes(before+b'changed')
            bad=run()
            with self.subTest(path=path):self.assertNotEqual(bad.returncode,0);self.assertIn(reason,bad.stderr);self.assertNotIn('BOUND',bad.stdout)
            path.write_bytes(before)


if __name__=='__main__':unittest.main(verbosity=2)
