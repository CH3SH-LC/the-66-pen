"""Regression cases for associating real native save evidence with a transform."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from contract import write,sha
from save_verify import bind_session_and_time,bind_native_card,bind_gil_evidence
from build import ROOT

SESSION=dict(schemaVersion=1,pid=12,tid=34,window=56,windowClass='UnityWndClass',processCreation=78,threadCreation=90,image='game.exe')

class SaveBindingTests(unittest.TestCase):
    def timing(self):
        prepared=dict(levelId=123,session=SESSION)
        save_prepared=dict(session=copy.deepcopy(SESSION))
        built=dict(session=copy.deepcopy(SESSION),createdUtc='2026-10-15T10:00:02+00:00')
        record=dict(pid=12,tid=34)
        transform_exit=dict(startedUtc='2026-10-15T10:00:00+00:00',finishedUtc='2026-10-15T10:00:01+00:00')
        save_exit=dict(startedUtc='2026-10-15T10:00:03+00:00',finishedUtc='2026-10-15T10:00:04+00:00')
        return prepared,save_prepared,built,record,transform_exit,save_exit

    def test_same_session_and_monotonic_save_sequence(self):
        result=bind_session_and_time(*self.timing())
        self.assertEqual(result['saveStartedUtc'],'2026-10-15T10:00:03+00:00')

    def test_reused_pid_with_different_process_creation_rejected(self):
        values=list(self.timing());values[1]['session']['processCreation']+=1
        with self.assertRaisesRegex(ValueError,'SAVE_SESSION_MISMATCH'):
            bind_session_and_time(*values)

    def test_save_prepared_before_transform_completed_rejected(self):
        values=list(self.timing());values[2]['createdUtc']='2026-10-15T09:59:59+00:00'
        with self.assertRaisesRegex(ValueError,'SAVE_MUST_FOLLOW'):
            bind_session_and_time(*values)

    def test_raw_save_receipt_requires_matching_card_nonce_and_deadline(self):
        constants=dict(HR_ACTION=2,HR_EXPECTED_LEVEL=123,HR_TARGET_PID=12,HR_TARGET_TID=34,
                       HR_TARGET_CREATION=78,HR_TARGET_THREAD_CREATION=90,HR_NONCE=111,HR_DEADLINE=222)
        header='\n'.join(f'#define {key} {value}ULL' for key,value in constants.items())+'\n'
        record=dict(receiptNonce='111',receiptDeadline='222',receiptProtocol=3)
        self.assertEqual(bind_native_card(header,record,dict(levelId=123,session=SESSION))['nonce'],'111')
        for key,value in (('receiptNonce','999'),('receiptDeadline','999'),('receiptProtocol',17)):
            broken=dict(record);broken[key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'SAVE_RAW_RECEIPT'):
                bind_native_card(header,broken,dict(levelId=123,session=SESSION))

    def make_files(self,folder):
        run=folder/'save';run.mkdir()
        sources=[folder/'Beyond_Local_Save_Level'/str(eid)/(str(eid)+'.gil') for eid in (123,124)]
        recovery=[];phases={}
        for i,source in enumerate(sources):
            source.parent.mkdir(parents=True);source.write_bytes(bytes([i+1]))
            recovery.append(dict(source=str(source),target=i==0,sha256=sha(source)))
        for phase in ('before','after'):
            values={}
            for source in sources:
                dest=run/f'{phase}-{source.stem}.gil';dest.write_bytes(source.read_bytes())
                values[source.stem]=dict(source=str(source),snapshot=str(dest),sha256=sha(dest),bytes=dest.stat().st_size,mtimeNs=0)
            phases[phase]=values
            write(run/(phase+'-gils.json'),values)
        return run,dict(run=str(folder/'transform'),recovery=recovery),dict(targetGil=str(sources[0]),protectedGils=[str(sources[1])]),dict(run=str(run),receipt=str(run/'stdout.jsonl'),beforeGils=phases['before'],afterGils=phases['after'])

    def temp(self):
        folder=ROOT/'.runtime/map-foundation-20261015/transform/test-temp';folder.mkdir(parents=True,exist_ok=True)
        return tempfile.TemporaryDirectory(dir=folder)

    def test_both_gil_copies_are_bound_to_source_set_and_this_save_run(self):
        with self.temp() as temp:
            values=self.make_files(Path(temp))
            result=bind_gil_evidence(*values)
            self.assertEqual(set(result['before']),{'123','124'})

    def test_equal_hash_after_copy_from_other_run_is_rejected(self):
        with self.temp() as temp:
            values=list(self.make_files(Path(temp)));run,prepared,built,reply=values
            other=Path(temp)/'elsewhere.gil';other.write_bytes((run/'after-123.gil').read_bytes())
            reply['afterGils']['123']['snapshot']=str(other)
            # Make the JSON and summary agree: path binding must still reject.
            (run/'after-gils.json').unlink();write(run/'after-gils.json',reply['afterGils'])
            with self.assertRaisesRegex(ValueError,'SAVE_COPY_PATH_OR_SOURCE'):
                bind_gil_evidence(*values)

    def test_missing_protected_source_is_rejected(self):
        with self.temp() as temp:
            values=list(self.make_files(Path(temp)));values[2]['protectedGils']=[]
            with self.assertRaisesRegex(ValueError,'SAVE_SOURCE_ENUMERATION'):
                bind_gil_evidence(*values)

    def test_changed_before_copy_is_rejected_even_when_after_is_correct(self):
        with self.temp() as temp:
            values=list(self.make_files(Path(temp)));run,prepared,built,reply=values
            (run/'before-123.gil').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SAVE_COPY_HASH_OR_SIZE'):
                bind_gil_evidence(*values)

    def with_upgrade(self,folder):
        values=list(self.make_files(folder));prepared=values[1]
        source=folder/'Beyond_Local_Save_Level/UpgradeBackup/123.gil'
        source.parent.mkdir();source.write_bytes(b'older-upgrade-backup')
        backup=Path(prepared['run'])/'recovery/UpgradeBackup-123.gil'
        backup.parent.mkdir(parents=True);backup.write_bytes(source.read_bytes())
        prepared['recovery'].append(dict(source=str(source),backup=str(backup),sha256=sha(backup),target=False))
        return values,source,backup

    def test_legacy_upgrade_backup_is_independent_of_same_id_formal_level(self):
        with self.temp() as temp:
            values,source,backup=self.with_upgrade(Path(temp))
            result=bind_gil_evidence(*values)
            self.assertEqual(set(result['before']),{'123','124'})
            self.assertEqual(len(result['auxiliaryBackups']),1)
            self.assertFalse(result['auxiliaryBackups'][0]['afterSaveSnapshotAvailable'])

    def test_changed_upgrade_source_or_recovery_is_rejected(self):
        for which in ('source','backup'):
            with self.subTest(which=which),self.temp() as temp:
                values,source,backup=self.with_upgrade(Path(temp))
                (source if which=='source' else backup).write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'AUXILIARY_.*CHANGED'):
                    bind_gil_evidence(*values)

    def test_unknown_extra_or_mislabelled_source_is_not_ignored(self):
        for mode in ('unknown','kind'):
            with self.subTest(mode=mode),self.temp() as temp:
                values,source,backup=self.with_upgrade(Path(temp))
                item=values[1]['recovery'][-1]
                if mode=='unknown':item['source']=str(source.parent.parent/'OtherBackup/123.gil')
                else:item['sourceKind']='formal-level'
                with self.assertRaisesRegex(ValueError,'UNCLASSIFIED_RECOVERY|RECOVERY_SOURCE_KIND'):
                    bind_gil_evidence(*values)

    def test_upgrade_backup_cannot_replace_a_formal_save_source(self):
        with self.temp() as temp:
            values,source,backup=self.with_upgrade(Path(temp))
            values[2]['protectedGils'].append(str(source))
            with self.assertRaisesRegex(ValueError,'SAVE_SOURCE_ENUMERATION'):
                bind_gil_evidence(*values)

    def test_upgrade_recovery_copy_must_belong_to_transform_run(self):
        with self.temp() as temp:
            values,source,backup=self.with_upgrade(Path(temp))
            other=Path(temp)/'other.gil';other.write_bytes(backup.read_bytes())
            values[1]['recovery'][-1]['backup']=str(other)
            with self.assertRaisesRegex(ValueError,'AUXILIARY_RECOVERY_PATH'):
                bind_gil_evidence(*values)

    def test_new_backup_manifest_labels_formal_and_upgrade_sources(self):
        from build import backups
        with self.temp() as temp:
            folder=Path(temp);values,source,backup=self.with_upgrade(folder)
            run=folder/'new';run.mkdir()
            result=backups(run,values[2]['targetGil'],123)
            self.assertEqual([v['sourceKind'] for v in result].count('formal-level'),2)
            self.assertEqual([v['sourceKind'] for v in result].count('auxiliary-upgrade-backup'),1)

if __name__=='__main__':
    unittest.main()
