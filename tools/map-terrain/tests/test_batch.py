"""Serial multi-card fixtures. Raw receipts below are synthetic, never live."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import argparse,copy,json,struct,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/'tests'))
import terrain_batch as batch
import terrain_native as native
import terrain_model as model
import terrain_recovery as recovery
import terrain_save_verify as saveproof
import test_receipt_binding as receipts
import test_save_proof as saving
from test_terrain_model import save,cell

def put(path,value):path.write_text(json.dumps(value),encoding='utf-8')
def ns(**kwargs):return argparse.Namespace(**kwargs)

class Fixture:
    def __init__(self,root,source=None,edits=None,template_record=None,template_built=None,catalog_run=None):
        self.root=root;self.clock=datetime.now(timezone.utc)-timedelta(seconds=120);self.sequence=0
        self.template_record=template_record;self.template_built=template_built
        if source is None:
            source=root/'home/AppData/LocalLow/miHoYo/原神/BeyondLocal/123/Beyond_Local_Save_Level/1073741900/1073741900.gil'
            source.parent.mkdir(parents=True);source.write_bytes(save([cell(1,2)]))
            sibling=source.parent.parent/'1073741901/1073741901.gil';sibling.parent.mkdir();sibling.write_bytes(b'preserve sibling')
        self.source=source
        path=root/'edits.json';put(path,edits or [{'x':1,'z':2,'height':2},{'x':1,'z':2,'height':3}])
        self.directory=Path(batch.create(ns(save=str(source),terrain_id=1001,edits=str(path),chunk_size=1,catalog_run=catalog_run))['batch'])
        self.plan=batch.load(self.directory)[1]

    def raw(self,before,after,card=None,inspect=False,run=None,source_record=None,source_built=None):
        self.sequence+=1
        source_record=source_record or self.template_record;source_built=source_built or self.template_built
        if run is None:run=native.OUT/f'fixture-{self.sequence}';run.mkdir(parents=True)
        receipts.ReceiptTests().fixture(run)
        built=batch.read(run/'build-result.json') if source_built is None else copy.deepcopy(source_built)
        record=batch.read(run/'stdout.jsonl') if source_record is None else copy.deepcopy(source_record)
        built['session']=dict(built['session'],schemaVersion=1,window='0x1234',windowClass='fixture-class')
        baseline=batch.read(run/'baseline-prepared.json');baseline['session']=built['session'];put(run/'baseline-prepared.json',baseline)
        built.update(run=str(run),levelId=1073741900,sourceSave=str(self.source),batch=card.get('batch') if card else None,
                     materialSource=card.get('materialSource') if card else None,catalogGuard=bool(card and card.get('materialSource')),
                     inspectOnly=inspect,refreshOnly=False,requiresRenderRebuild=not inspect,renderRebuildEvidenceVersion=1 if not inspect else None)
        if source_record is not None:
            snapshot=bytes.fromhex(record['snapshotHex']);(run/'baseline-snapshot.bin').write_bytes(snapshot)
            baseline=batch.read(run/'baseline-prepared.json');baseline['session']=built['session'];put(run/'baseline-prepared.json',baseline)
            if not inspect:
                built['recovery']=recovery.capture(run,self.source,1073741900,batch.sha(self.source));put(run/'recovery.json',built['recovery'])
        data=bytearray.fromhex(record['terrainHex']);head=dict(zip(native.HEADER_NAMES,struct.unpack_from('<32Q',data)))
        head.update(beforeCount=len(before),afterCount=len(after),reserved=0 if inspect else 31)
        if inspect:
            for key in ('mutationCalls','completed','openCalled','snapshotCalled','notifyCalled','closeCalled','snapshotVerified','notificationVerified','closeVerified'):head[key]=0
        struct.pack_into('<32Q',data,0,*[head[k] for k in native.HEADER_NAMES])
        for offset,rows in ((256,before),(256+24*model.MAX_CELLS,after)):
            for i,row in enumerate(rows):struct.pack_into('<6I',data,offset+i*24,*row)
        record['terrainHex']=data.hex();put(run/'stdout.jsonl',record)
        put(run/'request.json',card or dict(terrainId=1001,before=[],expected=[],changes=[]))
        (run/'before.gil').write_bytes(self.source.read_bytes())
        put(run/'exit.json',dict(executed=True,exitCode=0,stdoutSha256=batch.sha(run/'stdout.jsonl'),
                                startedUtc=(self.clock+timedelta(seconds=self.sequence*4)).isoformat(),
                                finishedUtc=(self.clock+timedelta(seconds=self.sequence*4+1)).isoformat()))
        put(run/'build-result.json',built);saving.repin_terrain(run,built)
        return run

    def inspection(self,rows=None):
        state=batch.status(ns(batch=self.directory));index=state['acceptedCards']
        rows=self.plan['steps'][index]['before'] if rows is None else rows
        run=self.raw(rows,rows,inspect=True);observed=batch.original(run)
        baseline=self.root/f'baseline-{self.sequence}';baseline.mkdir()
        put(baseline/'exit.json',dict(finishedUtc=(batch.utc(observed['exit']['finishedUtc'])+timedelta(seconds=1)).isoformat()))
        return ns(batch=str(self.directory),baseline=str(baseline),inspection=str(run)),observed

    def next(self,rows=None,prelaunch=False):
        args,inspected=self.inspection(rows)
        def fake_prepare(request):
            card=batch.plan_for_prepare(request,inspected['built']['session'],inspected['scene'])
            run=native.OUT/f'card-{self.sequence}';run.mkdir(parents=True);request._run_started(run)
            self.raw(card['before'],card['expected'],card=card,run=run)
            built=batch.read(run/'build-result.json');built['pins']=dict(request._batch_pins)
            saving.repin_terrain(run,built)
            if prelaunch:
                for name in ('launch.claim','attempt.used','stdout.jsonl','exit.json'):(run/name).unlink()
            return dict(ok=True,run=str(run),called=False)
        with patch.object(native,'prepare',side_effect=fake_prepare):result=batch.prepare(args)
        return Path(result['run'])

@contextmanager
def fixture():
    with tempfile.TemporaryDirectory(dir=model.ROOT/'.runtime') as tmp:
        root=Path(tmp);(root/'prepared').mkdir()
        with patch.object(Path,'home',return_value=root/'home'),patch.object(batch,'OUT',root/'batches'),patch.object(native,'OUT',root/'prepared'):
            yield Fixture(root)

class BatchTests(unittest.TestCase):
    def test_twenty_thousand_edits_respect_each_card_and_full_capacity(self):
        blob=save([cell(1,2)])
        edits=[dict(x=i%200,z=10+i//200,height=1+i%4,material=0) for i in range(20000)]
        p=batch.compile_plan(blob,1001,edits,'source.gil',1073741900)
        self.assertEqual(len(p['steps']),5);self.assertEqual(len(p['expected']),20001)
        self.assertTrue(all(len(s['changes'])<=4096 for s in p['steps']))
        for left,right in zip(p['steps'],p['steps'][1:]):self.assertEqual(left['expected'],right['before'])

    def test_capacity_and_material_guards_are_not_bypassed(self):
        blob=save([cell(1,2)])
        for kwargs in ({'chunk_size':4097},{'edits':[{'x':2,'z':3,'height':1,'material':99}]},{'level':1}):
            values=dict(blob=blob,terrain_id=1001,edits=[{'x':1,'z':2,'height':2}],source='source.gil',level=1073741900)
            values.update(kwargs)
            with self.assertRaises(ValueError):batch.compile_plan(**values)

    def test_two_cards_continue_from_accepted_native_after_not_disk(self):
        with fixture() as f:
            initial=f.source.read_bytes();first=f.next();one=batch.accept(ns(batch=f.directory,run=first))
            self.assertEqual(one['acceptedCards'],1);self.assertEqual(f.source.read_bytes(),initial)
            second=f.next();card=batch.read(second/'request.json')
            self.assertEqual(card['before'][0][1],2);self.assertEqual(model.decode_save(initial)['terrains'][0]['cells'][0][1],1)
            two=batch.accept(ns(batch=f.directory,run=second));self.assertTrue(two['complete'])
            self.assertEqual(batch.status(ns(batch=f.directory))['acceptedCards'],2)
            self.assertTrue(batch.accept(ns(batch=f.directory,run=second))['alreadyAccepted'])
            self.assertEqual(f.source.read_bytes(),initial)

    def test_new_inspection_must_match_all_accepted_cells_even_with_same_disk_hash(self):
        with fixture() as f:
            first=f.next();batch.accept(ns(batch=f.directory,run=first));initial=f.source.read_bytes()
            with self.assertRaisesRegex(ValueError,'BATCH_NATIVE_FULL_TERRAIN_DIFFERS'):
                f.next(rows=f.plan['initial'])
            self.assertEqual(f.source.read_bytes(),initial)
            self.assertEqual(batch.status(ns(batch=f.directory))['acceptedCards'],1)

    def test_unsaved_difference_before_first_card_is_rejected(self):
        with fixture() as f:
            with self.assertRaisesRegex(ValueError,'BATCH_NATIVE_FULL_TERRAIN_DIFFERS'):
                f.next(rows=[[model.key(1,2),9,0,0,0,0]])

    def test_pending_attempt_blocks_next_and_confirmed_prelaunch_can_be_abandoned(self):
        with fixture() as f:
            first=f.next(prelaunch=True)
            with self.assertRaisesRegex(ValueError,'BATCH_PENDING_CARD'):f.next()
            result=batch.abandon(ns(batch=f.directory));self.assertTrue(result['ok'])
            with self.assertRaisesRegex(ValueError,'BATCH_CARD_NOT_ACTIVE'):
                with batch.dispatch_guard(batch.read(first/'request.json')):pass
            second=f.next();self.assertNotEqual(first,second)
            self.assertEqual(batch.accept(ns(batch=f.directory,run=second))['acceptedCards'],1)

    def test_called_or_unknown_outcome_cannot_be_abandoned(self):
        with fixture() as f:
            run=f.next()
            with self.assertRaisesRegex(ValueError,'BATCH_CANNOT_ABANDON'):batch.abandon(ns(batch=f.directory))
            (run/'stdout.jsonl').write_bytes(b'')
            with self.assertRaises(ValueError):batch.abandon(ns(batch=f.directory))
            self.assertIsNotNone(batch.status(ns(batch=f.directory))['pendingAttempt'])

    def test_failed_prepare_can_be_explicitly_retired_without_replaying_any_card(self):
        with fixture() as f:
            with self.assertRaises(ValueError):f.next(rows=[])
            self.assertTrue(batch.abandon(ns(batch=f.directory))['ok'])
            self.assertTrue(batch.accept(ns(batch=f.directory,run=f.next()))['ok'])

    def test_abandon_and_dispatch_share_one_exclusive_operation_lock(self):
        with fixture() as f:
            run=f.next(prelaunch=True);card=batch.read(run/'request.json')
            with batch.dispatch_guard(card):
                with self.assertRaises(FileExistsError):batch.abandon(ns(batch=f.directory))

    def test_changed_accepted_raw_receipt_stops_continuation(self):
        with fixture() as f:
            run=f.next();batch.accept(ns(batch=f.directory,run=run))
            with (run/'stdout.jsonl').open('ab') as stream:stream.write(b' ')
            with self.assertRaises(ValueError):batch.status(ns(batch=f.directory))

    def test_changed_protected_formal_sibling_stops_new_card(self):
        with fixture() as f:
            first=f.next();batch.accept(ns(batch=f.directory,run=first))
            sibling=f.source.parent.parent/'1073741901/1073741901.gil';sibling.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'BATCH_FORMAL_FILE_CHANGED'):f.next()

    def test_stale_and_other_session_inspection_are_rejected(self):
        with fixture() as f:
            args,observed=f.inspection();index=0;attempt=batch.step_path(f.directory,index)/'attempts/test';attempt.mkdir(parents=True)
            batch.write(attempt/'intent.json',dict(batch=str(f.directory),index=index,inspectionRun=args.inspection,baseline=args.baseline))
            args._batch_attempt=str(attempt)
            wrong=dict(observed['built']['session'],pid=9999)
            with self.assertRaisesRegex(ValueError,'SAVE_SESSION_CHANGED'):batch.plan_for_prepare(args,wrong,observed['scene'])
            exit_record=batch.read(Path(args.inspection)/'exit.json');exit_record['finishedUtc']='2020-01-01T00:00:00Z';put(Path(args.inspection)/'exit.json',exit_record)
            with self.assertRaisesRegex(ValueError,'BATCH_FRESH_INSPECTION'):batch.plan_for_prepare(args,observed['built']['session'],observed['scene'])

    def test_final_file_proof_requires_complete_chain_and_all_protected_fields(self):
        with fixture() as f:
            one=f.next();batch.accept(ns(batch=f.directory,run=one));card=batch.read(one/'request.json')
            with self.assertRaisesRegex(ValueError,'BATCH_COMPLETE_ACCEPTED_CHAIN'):
                batch.saved_content(card,f.source.read_bytes(),save([cell(1,2,2)]))
            two=f.next();batch.accept(ns(batch=f.directory,run=two));card=batch.read(two/'request.json')
            proof=batch.saved_content(card,f.source.read_bytes(),save([cell(1,2,3)],stamp=101))
            self.assertTrue(proof['ok']);self.assertTrue(proof['completeChainVerified']);self.assertFalse(proof['nativeSaveVerified'])
            wrong=batch.saved_content(card,f.source.read_bytes(),save([cell(1,2,3)],root_extra=99))
            self.assertFalse(wrong['ok']);self.assertIn('UNRELATED_LEVEL_FIELDS_CHANGED',wrong['failures'])

    def test_batch_original_sources_are_never_synthetic_saves(self):
        with fixture() as f:
            run=f.next();batch.accept(ns(batch=f.directory,run=run));second=f.next()
            self.assertEqual((second/'before.gil').read_bytes(),(f.directory/'initial.gil').read_bytes())
            self.assertEqual(batch.read(second/'request.json')['sourceSha256'],batch.sha(f.source))
            self.assertNotEqual(batch.read(second/'request.json')['before'],model.decode_save(f.source.read_bytes())['terrains'][0]['cells'])

    def test_native_save_proof_covers_all_cards_and_original_disk_bytes(self):
        with saving.complete_fixture() as (old,saved,built,profile,reply):
            root=old.parent;prepared=root/'batch-prepared';prepared.mkdir()
            with patch.object(batch,'OUT',root/'batches'),patch.object(native,'OUT',prepared):
                f=Fixture(root,source=Path(built['sourceSave']),
                          edits=[{'x':2,'z':2,'height':1,'material':0},{'x':1,'z':2,'height':2}],
                          template_record=batch.read(old/'stdout.jsonl'),template_built=built)
                first=f.next();batch.accept(ns(batch=f.directory,run=first))
                final=f.next();batch.accept(ns(batch=f.directory,run=final))
                # Native save fixture persists both cards in one real-form reply.
                after=saving.with_roots(save([cell(1,2,2),cell(2,2,1)],stamp=101))
                saving.update_copy(saved,reply,'after',1073741900,after)
                now=datetime.now(timezone.utc);saved_exit=batch.read(saved/'exit.json')
                saved_exit.update(startedUtc=(now-timedelta(seconds=20)).isoformat(),finishedUtc=(now-timedelta(seconds=19)).isoformat());put(saved/'exit.json',saved_exit)
                sp=batch.read(saved/'prepared.json');review_path=Path(sp['reviewPath']);review=batch.read(review_path)
                review.update(reviewedAtUtc=(now-timedelta(seconds=60)).isoformat(),expiresUtc=(now+timedelta(minutes=5)).isoformat());put(review_path,review)
                sp['reviewSha256']=batch.sha(review_path);put(saved/'prepared.json',sp);saving.repin_save(saved,profile)
                result=batch.verify_save(ns(batch=f.directory,save_run=saved))
                self.assertTrue(result['nativeSaveVerified']);self.assertTrue(result['persistentSaveVerified'])
                self.assertEqual(result['acceptedCards'],2);self.assertTrue(result['completeChainVerified'])
                self.assertEqual(result['cellCount'],2);self.assertEqual(result['protectedLevels'],[1073741901])
                self.assertEqual(result['beforeSha256'],batch.sha(f.source));self.assertEqual(result['run'],str(final))
                self.assertFalse(result['reopenVerified'])
                for path in (first/'stdout.jsonl',batch.step_path(f.directory,0)/'accepted.json',f.directory/'manifest.json'):
                    self.assertEqual(result['evidence']['artifactSha256'][str(path)],batch.sha(path))
                original_check=saveproof.check_unchanged
                def change_intermediate_only_at_final_check(pins):
                    with (first/'stdout.jsonl').open('ab') as stream:stream.write(b' ')
                    original_check(pins)
                with patch.object(saveproof,'check_unchanged',side_effect=change_intermediate_only_at_final_check),self.assertRaisesRegex(ValueError,'SAVE_EVIDENCE_CHANGED_DURING_VERIFY'):
                    batch.verify_save(ns(batch=f.directory,save_run=saved))

if __name__=='__main__':unittest.main()
