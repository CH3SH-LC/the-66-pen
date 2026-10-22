"""Synthetic on-disk receipts only; never opens a game process or formal save."""
from contextlib import contextmanager, redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE));sys.path.insert(0,str(Path(__file__).resolve().parent))
import terrain_native as native
import terrain_recovery as recovery
import terrain_save_verify as proof
import terrain_cli
import test_receipt_binding as receipt_fixtures
import test_terrain_model as fixtures
from gil_container import Field, Container, decode_container, parse_fields, encode_fields, encode_container

LEVEL=1073741900
SIBLING=1073741901

def put(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def with_roots(blob,changed=None):
    container=decode_container(blob)
    fields=parse_fields(container.payload)
    for number in (5,6,10):
        fields.append(Field(number,2,data=encode_fields([Field(1,0,value=number+(1 if number==changed else 0))])))
    return encode_container(Container(container.subtype,encode_fields(fields)))

def with_opaque46(blob,value):
    container=decode_container(blob);fields=parse_fields(container.payload)
    inner=encode_fields([Field(1,0,value=value),Field(2,0,value=1234567890123456)])
    fields.append(Field(46,2,data=encode_fields([Field(1,2,data=inner)])))
    return encode_container(Container(container.subtype,encode_fields(fields)))

def repin_terrain(run,built):
    put(run/'build-result.json',built)
    put(run/'prepared.json',{'kind':'native-terrain-prepared-v1','run':str(run),
                            'buildResultSha256':proof.sha(run/'build-result.json')})

def repin_save(run,profile):
    profile['hashes']={name:proof.sha(run/name) for name in profile['hashes']}
    put(run/'build-result.json',profile)

@contextmanager
def complete_fixture(root46=False):
    native.OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='save-proof-fixture-',dir=native.OUT) as directory:
        base=Path(directory).resolve();run=base/'terrain';run.mkdir();save_run=base/'save';save_run.mkdir()
        fake_home=base/'home'
        with patch.object(Path,'home',return_value=fake_home):
            receipt_fixtures.ReceiptTests().fixture(run)
            before=with_roots(fixtures.save([fixtures.cell(1,2,1)]))
            after=with_roots(fixtures.save([fixtures.cell(1,2,2)],stamp=101))
            if root46:before,after=with_opaque46(before,1234567890123),with_opaque46(after,1234567890124)
            folder=fake_home/'AppData/LocalLow/miHoYo/原神/BeyondLocal/123/Beyond_Local_Save_Level'
            source=folder/str(LEVEL)/f'{LEVEL}.gil';source.parent.mkdir(parents=True);source.write_bytes(before)
            sibling=folder/str(SIBLING)/f'{SIBLING}.gil';sibling.parent.mkdir();sibling.write_bytes(b'synthetic sibling protected byte-for-byte')
            built=proof.read(run/'build-result.json')
            session=dict(built['session'],schemaVersion=1,window='0x1234',windowClass='fixture-class')
            built.update(session=session,levelId=LEVEL,sourceSave=str(source))
            built['recovery']=recovery.capture(run,source,LEVEL,fixtures.tm.digest(before))
            put(run/'recovery.json',built['recovery']);(run/'before.gil').write_bytes(before)
            plan=fixtures.tm.make_plan(before,1001,[{'x':1,'z':2,'height':2}],str(source));put(run/'request.json',plan)
            original=proof.read(run/'baseline-prepared.json');original['session']=session;put(run/'baseline-prepared.json',original)
            # One complete entity is required by the shared native-save baseline gate.
            snapshot=bytearray((run/'baseline-snapshot.bin').read_bytes())
            struct.pack_into('<II',snapshot,104+7*4,1,1)
            decoder=native.ro.load_decoder()
            context=struct.unpack_from('<Q',snapshot,16+7*8)[0]
            decoder.ENTITY.pack_into(snapshot,decoder.ENTITIES_OFFSET,0x30000000,0x30001000,context,1,1,100,95,1.,2.,3.,0,0)
            (run/'baseline-snapshot.bin').write_bytes(snapshot)
            raw=proof.read(run/'stdout.jsonl');raw.update(snapshotHex=snapshot.hex())
            terrain=bytearray.fromhex(raw['terrainHex']);terrain[native.RECEIPT_BASE_SIZE:]=snapshot;raw['terrainHex']=terrain.hex()
            put(run/'stdout.jsonl',raw)
            put(run/'exit.json',{'executed':True,'exitCode':0,'stdoutSha256':proof.sha(run/'stdout.jsonl'),
                                 'startedUtc':'2026-10-15T12:00:00Z','finishedUtc':'2026-10-15T12:00:01Z'})
            repin_terrain(run,built)
            request={'action':'save','levelId':LEVEL};request_sha=proof.reviews.canonical_hash(request)
            review_path=base/'save-review.json';review_copy=base/'save-review-before.gil';review_copy.write_bytes(before)
            write_profile=proof.reviews.load_write_profile()
            review={'schemaVersion':1,'kind':'native-write-review-v1','state':'reviewed','reviewedBy':'coordinator',
                    'profileId':write_profile['profileId'],'writeProfileSha256':proof.reviews.WRITE_PROFILE_SHA256,
                    'readonlyProfileSha256':native.profiles.PROFILE_SHA256,'levelId':LEVEL,'requestSha256':request_sha,
                    'session':session,'reviewedAtUtc':'2026-10-15T12:00:01Z','expiresUtc':'2026-10-15T12:10:00Z',
                    'protectedGils':[str(sibling)],'recovery':{'source':str(source),'backup':str(review_copy),
                    'sha256':fixtures.tm.digest(before)}}
            put(review_path,review)
            prepared=dict(original,levelObservationProfileSha256=proof.reviews.level_api.LEVEL_PROFILE_SHA256,
                          request=request,allowWrites=True,writeProfileId=write_profile['profileId'],
                          writeProfileSha256=proof.reviews.WRITE_PROFILE_SHA256,reviewPath=str(review_path),reviewSha256=proof.sha(review_path))
            put(save_run/'prepared.json',prepared)
            values={'HR_NONCE':789,'HR_DEADLINE':999,'HR_ACTION':2,'HR_TARGET_PID':session['pid'],'HR_TARGET_TID':session['tid'],
                    'HR_TARGET_CREATION':session['processCreation'],'HR_TARGET_THREAD_CREATION':session['threadCreation'],
                    'HR_EXPECTED_LEVEL':LEVEL,'HR_EXPECTED_CONTEXT':context}
            header=''.join(f'#define {name} {value}ULL\n' for name,value in values.items())
            header+='#define HR_TARGET_IMAGE L'+json.dumps(session['image'])+'\n'
            (save_run/'target_config.h').write_text(header,encoding='utf-8')
            for name in ('hook_receipt.dll','hook_receipt_probe.exe','invoke-fixed-probe.ps1'):
                (save_run/name).write_bytes(b'Offline fixture only; not executable.')
            put(save_run/'baseline-context.json',decoder.decode_snapshot(dict(snapshotHex=snapshot.hex(),snapshotBytes=len(snapshot))))
            hashes={name:proof.sha(save_run/name) for name in ('hook_receipt.dll','hook_receipt_probe.exe','target_config.h',
                                                             'prepared.json','baseline-context.json','invoke-fixed-probe.ps1')}
            profile={'run':str(save_run),'action':'save','expectedLevelId':LEVEL,'hashes':hashes,'session':session,
                     'requestSha256':request_sha,'deadlineTick':999,'targetPid':session['pid'],'targetTid':session['tid'],
                     'targetGil':str(source),'protectedGils':[str(sibling)],'allowWrites':True}
            put(save_run/'build-result.json',profile)
            save_record={key:raw[key] for key in ('ok','selfTestOnly','probeElevatedHigh','pid','tid','callbackCount',
                         'activeCallbacks','unhooked','transportOk','snapshotStatus','snapshotBytes','snapshotHex')}
            save_record.update(scope='FIXED_SCENE_ACTION',receiptNonce='789',receiptDeadline='999',receiptProtocol=3,
                               afterSnapshotHex=snapshot.hex(),action={'kind':2,'status':0,'called':1,'nativeSaveStatus':0,
                               'levelId':LEVEL,'expectedLevelId':LEVEL})
            put(save_run/'stdout.jsonl',save_record)
            put(save_run/'exit.json',{'executed':True,'exitCode':0,'startedUtc':'2026-10-15T12:00:02Z',
                                     'finishedUtc':'2026-10-15T12:00:03Z'})
            reply={'ok':True,'action':'save','run':str(save_run)}
            for phase in ('before','after'):
                rows={}
                for level,path in ((LEVEL,source),(SIBLING,sibling)):
                    blob=after if phase=='after' and level==LEVEL else path.read_bytes()
                    copy=save_run/f'{phase}-{level}.gil';copy.write_bytes(blob)
                    rows[str(level)]={'source':str(path),'snapshot':str(copy),'sha256':fixtures.tm.digest(blob),
                                      'bytes':len(blob),'mtimeNs':1}
                put(save_run/f'{phase}-gils.json',rows);reply[phase+'Gils']=rows
            put(save_run/'result.json',reply)
            yield run,save_run,built,profile,reply

def update_copy(save_run,reply,phase,level,blob):
    item=reply[phase+'Gils'][str(level)];Path(item['snapshot']).write_bytes(blob)
    item.update(sha256=fixtures.tm.digest(blob),bytes=len(blob))
    put(save_run/f'{phase}-gils.json',reply[phase+'Gils']);put(save_run/'result.json',reply)

class SaveProofTests(unittest.TestCase):
    def test_complete_native_save_chain_and_repeated_read_are_accepted(self):
        with complete_fixture() as (run,saved,built,profile,reply):
            result=proof.verify(run,saved)
            self.assertTrue(result['nativeSaveVerified']);self.assertTrue(result['persistentSaveVerified'])
            self.assertTrue(result['allSaveDomainsVerified']);self.assertTrue(result['allOtherSavedFieldsPreserved'])
            self.assertEqual(result['protectedLevels'],[SIBLING]);self.assertFalse(result['reopenVerified'])
            self.assertFalse(result['visualRebuildVerified']);self.assertEqual(result,proof.verify(run,saved))

    def test_after_cli_is_only_file_content_proof(self):
        with complete_fixture() as (run,saved,built,profile,reply):
            output=io.StringIO()
            with redirect_stdout(output):code=terrain_cli.main(['verify-save','--run',str(run),'--after',str(saved/f'after-{LEVEL}.gil')])
            self.assertEqual(code,0,output.getvalue());result=json.loads(output.getvalue())
            self.assertTrue(result['fileContentVerified']);self.assertFalse(result['nativeSaveVerified'])
            self.assertFalse(result['persistentSaveVerified'])

    def test_missing_or_wrong_raw_card_values_are_rejected(self):
        for field,value in [('receiptNonce',None),('receiptNonce','790'),('receiptDeadline','998'),('receiptProtocol',18)]:
            with self.subTest(field=field,value=value),complete_fixture() as (run,saved,*_):
                raw=proof.read(saved/'stdout.jsonl');raw[field]=value;put(saved/'stdout.jsonl',raw)
                with self.assertRaisesRegex(ValueError,'SAVE_RAW_CARD_BINDING_REQUIRED'):proof.verify(run,saved)

    def test_changed_session_or_pinned_header_rejected(self):
        with complete_fixture() as (run,saved,built,profile,reply):
            prepared=proof.read(saved/'prepared.json');prepared['session']['window']='0x9999'
            put(saved/'prepared.json',prepared);repin_save(saved,profile)
            with self.assertRaisesRegex(ValueError,'SAVE_SESSION_CHANGED:window'):proof.verify(run,saved)
        with complete_fixture() as (run,saved,*_):
            with (saved/'target_config.h').open('a') as f:f.write('#define HR_NONCE 790ULL\n')
            with self.assertRaisesRegex(ValueError,'BASELINE_ARTIFACT_CHANGED:target_config.h'):proof.verify(run,saved)

    def test_missing_compiled_artifact_pin_rejected(self):
        with complete_fixture() as (run,saved,built,profile,reply):
            del profile['hashes']['target_config.h'];put(saved/'build-result.json',profile)
            with self.assertRaisesRegex(ValueError,'SAVE_COMPILED_ARTIFACT_SET_REQUIRED'):proof.verify(run,saved)

    def test_changed_full_scene_position_rejected(self):
        with complete_fixture() as (run,saved,*_):
            raw=proof.read(saved/'stdout.jsonl');snapshot=bytearray.fromhex(raw['afterSnapshotHex'])
            struct.pack_into('<f',snapshot,native.ro.load_decoder().ENTITIES_OFFSET+40,4.)
            raw['afterSnapshotHex']=snapshot.hex();put(saved/'stdout.jsonl',raw)
            with self.assertRaisesRegex(ValueError,'SAVE_SCENE_ENTITIES_CHANGED'):proof.verify(run,saved)

    def test_stale_before_and_changed_sibling_rejected(self):
        for phase,level in [('before',LEVEL),('after',SIBLING)]:
            with self.subTest(phase=phase,level=level),complete_fixture() as (run,saved,built,profile,reply):
                update_copy(saved,reply,phase,level,b'changed but self-consistent hashes')
                with self.assertRaisesRegex(ValueError,'SAVE_BASELINE_OR_SIBLING_CHANGED'):proof.verify(run,saved)

    def test_missing_sibling_source_substitution_and_copy_tamper_rejected(self):
        with complete_fixture() as (run,saved,built,profile,reply):
            del reply['afterGils'][str(SIBLING)];put(saved/'after-gils.json',reply['afterGils']);put(saved/'result.json',reply)
            with self.assertRaisesRegex(ValueError,'SAVE_GIL_SET_MISMATCH'):proof.verify(run,saved)
        with complete_fixture() as (run,saved,built,profile,reply):
            item=reply['afterGils'][str(LEVEL)];item['source']=item['source'].replace('BeyondLocal\\123','BeyondLocal\\999')
            put(saved/'after-gils.json',reply['afterGils']);put(saved/'result.json',reply)
            with self.assertRaisesRegex(ValueError,'SAVE_GIL_SOURCE_CHANGED'):proof.verify(run,saved)
        with complete_fixture() as (run,saved,*_):
            (saved/f'after-{LEVEL}.gil').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'SAVE_GIL_COPY_CHANGED'):proof.verify(run,saved)

    def test_entity_directory_and_graph_root_changes_rejected(self):
        for number in (5,6,10):
            with self.subTest(root=number),complete_fixture() as (run,saved,built,profile,reply):
                after=with_roots(fixtures.save([fixtures.cell(1,2,2)],stamp=101),changed=number)
                update_copy(saved,reply,'after',LEVEL,after)
                with self.assertRaisesRegex(ValueError,'UNRELATED_LEVEL_FIELDS_CHANGED'):proof.verify(run,saved)

    def test_old_write_without_recovery_and_tampered_recovery_rejected(self):
        with complete_fixture() as (run,saved,built,*_):
            del built['recovery'];repin_terrain(run,built)
            with self.assertRaisesRegex(ValueError,'NATIVE_SAVE_REQUIRES_PREWRITE_RECOVERY'):proof.verify(run,saved)
        with complete_fixture() as (run,saved,built,*_):
            Path(built['recovery']['entries'][0]['backup']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'RECOVERY_BACKUP_CHANGED'):proof.verify(run,saved)

    def test_save_before_write_and_failed_cleanup_rejected(self):
        with complete_fixture() as (run,saved,*_):
            record=proof.read(saved/'exit.json');record['startedUtc']='2026-10-15T11:59:59Z';put(saved/'exit.json',record)
            with self.assertRaisesRegex(ValueError,'NATIVE_SAVE_NOT_AFTER_TERRAIN_WRITE'):proof.verify(run,saved)
        with complete_fixture() as (run,saved,*_):
            record=proof.read(saved/'stdout.jsonl');record['unhooked']=False;put(saved/'stdout.jsonl',record)
            with self.assertRaises(ValueError):proof.verify(run,saved)

    def test_recovery_capture_includes_siblings_and_rejects_arbitrary_file(self):
        with complete_fixture() as (run,saved,built,*_):
            data=recovery.validate(run,built['recovery'],LEVEL,built['sourceSave'])
            self.assertEqual(set(data),{str(LEVEL),str(SIBLING)})
            with self.assertRaisesRegex(ValueError,'FORMAL_LEVEL_SAVE_REQUIRED'):recovery.formal_source(run/'before.gil',LEVEL)

    def test_backup_and_misnamed_extra_are_not_formal_levels(self):
        with complete_fixture() as (run,saved,built,*_):
            source=Path(built['sourceSave']);folder=source.parent.parent
            backup=folder/'UpgradeBackup';backup.mkdir();(backup/f'{SIBLING}.gil').write_bytes(b'backup is not the formal level')
            (folder/str(SIBLING)/f'{LEVEL}.gil').write_bytes(b'misnamed extra is not a formal level')
            self.assertEqual({str(p) for p in recovery.sibling_files(source)},
                             {item['source'] for item in built['recovery']['entries']})
            fresh=run.parent/'fresh-recovery';fresh.mkdir()
            captured=recovery.capture(fresh,source,LEVEL,fixtures.tm.digest(source.read_bytes()))
            self.assertEqual({item['levelId'] for item in captured['entries']},{LEVEL,SIBLING})
            with self.assertRaisesRegex(ValueError,'FORMAL_LEVEL_SAVE_REQUIRED'):recovery.formal_source(backup/f'{SIBLING}.gil',SIBLING)

    def test_observed_root46_difference_is_not_all_domain_success(self):
        with complete_fixture(root46=True) as (run,saved,*_):
            result=proof.verify(run,saved)
            self.assertTrue(result['nativeSaveVerified']);self.assertTrue(result['fileContentVerified'])
            self.assertFalse(result['allSaveDomainsVerified']);self.assertFalse(result['allOtherSavedFieldsPreserved'])
            self.assertEqual([item['rootField'] for item in result['unclassifiedSaveDifferences']],[46])
            item=result['unclassifiedSaveDifferences'][0]
            self.assertFalse(item['semanticsVerified']);self.assertFalse(item['preservationVerified'])
            self.assertNotEqual(item['beforeEncodedFields'],item['afterEncodedFields'])

    def test_arbitrary_root46_shape_is_not_exempted(self):
        before=with_opaque46(fixtures.save([fixtures.cell(1,2,1)]),123)
        plan=fixtures.tm.make_plan(before,1001,[{'x':1,'z':2,'height':2}])
        plain=fixtures.save([fixtures.cell(1,2,2)])
        for extra in ([],[Field(46,0,value=123)],[Field(46,2,data=b'\x08\x01')]):
            container=decode_container(plain);after=encode_container(Container(container.subtype,encode_fields(parse_fields(container.payload)+extra)))
            with self.subTest(extra=extra):
                result=fixtures.tm.verify_save(before,after,plan)
                self.assertFalse(result['ok']);self.assertFalse(result['allSaveDomainsVerified'])
                self.assertIn('UNRELATED_LEVEL_FIELDS_CHANGED',result['failures'])

if __name__=='__main__':unittest.main()
