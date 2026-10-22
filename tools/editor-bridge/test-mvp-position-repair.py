"""Regression checks using saved fixtures and disposable project-local files only."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('repair',Path(__file__).with_name('repair-mvp-position.py'))
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
FIXTURE=r.ROOT/'.runtime/verification/mvp-position-repair-20260922-01'

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.original_live=r.LIVE
        self.original_bytes=r.LIVE.read_bytes()
        self.tmp=tempfile.TemporaryDirectory(prefix='mvp-repair-test-',dir=r.ROOT/'.runtime/verification')
        self.base=Path(self.tmp.name)
        r.LIVE=self.base/'1073741833.gil'
        r.LIVE.write_bytes((FIXTURE/'before.gil').read_bytes())

    def tearDown(self):
        r.LIVE=self.original_live
        self.assertEqual(r.LIVE.read_bytes(),self.original_bytes,'Real game save must remain unchanged')
        self.tmp.cleanup()

    def test_prepare_apply_verify_repeat(self):
        out=self.base/'run'
        r.prepare_run(out);r.verify_run(out)
        self.assertEqual(r.inspect_state(r.LIVE.read_bytes())['state'],'needs_repair')
        with self.assertRaises(ValueError):r.apply_run(out)
        self.assertFalse((out/'apply-attempt.json').exists())
        self.assertTrue(r.apply_run(out,True)['diskReadbackVerified'])
        before=r.LIVE.read_bytes()
        self.assertFalse(r.apply_run(out,True)['changed'])
        self.assertEqual(r.LIVE.read_bytes(),before)

    def test_stale_baseline_refused(self):
        out=self.base/'run';r.prepare_run(out)
        changed=(FIXTURE/'candidate.gil').read_bytes();r.LIVE.write_bytes(changed)
        with self.assertRaises(ValueError):r.apply_run(out,True)
        self.assertEqual(r.LIVE.read_bytes(),changed)

    def test_tampered_candidate_refused(self):
        out=self.base/'run';r.prepare_run(out)
        candidate=out/'candidate.gil';candidate.write_bytes(candidate.read_bytes()[:-4])
        with self.assertRaises(ValueError):r.apply_run(out,True)
        self.assertEqual(r.LIVE.read_bytes(),(out/'before.gil').read_bytes())

    def test_uncertain_attempt_not_replayed(self):
        out=self.base/'run';r.prepare_run(out);(out/'apply-attempt.json').write_text('{}')
        with self.assertRaises(FileExistsError):r.apply_run(out,True)
        self.assertEqual(r.LIVE.read_bytes(),(out/'before.gil').read_bytes())

    def test_native_zero_omission_and_noop_prepare(self):
        data=(FIXTURE/'candidate.gil').read_bytes()
        container=r.codec.decode_container(data);root=r.fields(container.payload)
        section=r.single(root,5,2);entries=r.fields(section.data)
        for entry in entries:
            if entry.number!=1 or entry.wire_type!=2:continue
            entity=r.fields(entry.data)
            if r.single(entity,1,0).value not in r.TARGETS:continue
            for comp in entity:
                if comp.number==6 and comp.wire_type==2 and r.single(r.fields(comp.data),1,0).value==1:
                    comp.data=r.replace_nested(comp.data,(11,1),lambda raw:r.codec.encode_fields([
                        f for f in r.fields(raw) if not(f.wire_type==5 and f.value==0)]))
            entry.data=r.codec.encode_fields(entity)
        section.data=r.codec.encode_fields(entries)
        native=r.codec.encode_container(r.codec.Container(container.subtype,r.codec.encode_fields(root),
                                         container.version,container.magic,container.trailer))
        self.assertNotEqual(native,data)
        self.assertEqual(r.inspect_state(native)['state'],'repaired')
        r.LIVE.write_bytes(native)
        self.assertFalse(r.prepare_run(self.base/'noop')['changed'])
        self.assertFalse((self.base/'noop').exists())

if __name__=='__main__':unittest.main()
