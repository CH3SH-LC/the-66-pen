"""Pure ABI, classification and source contract checks; no process connection."""
import copy,importlib.util,json,struct,sys,tempfile,unittest
from pathlib import Path
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
import contract as c
import build
class ObservationTests(unittest.TestCase):
    def sample(self):
        s={k:i+0x10000 for i,k in enumerate(c.POINTERS)};s.update(rawMode=0xb993,editing=1,editorLevel=1843,avatarId=7,avatarStatus=2,positionStatus=0,avatarBranch=0,unityPosition=[1.,2.,3.],origin=[10.,20.,30.],worldPosition=[11.,22.,33.]);return s
    def evidence(self):
        return dict(bytes=336,version=1,status=0,seh=0,stage=3,failedRva=0,failedValue=0,nativeCalls=2,mode=1,stable=1,readableBefore=15,readableAfter=15,targetLevel=1843,reserved0=0,reserved1=0,reserved2=0,before=self.sample(),after=self.sample())
    def raw(self,e):
        out=bytearray(struct.pack('<16I',*(e[k] for k in c.HEADER)))
        for name in ('before','after'):
            s=e[name];out+=struct.pack('<9Q7I9f',*(s[k] for k in c.POINTERS),*(s[k] for k in c.NUMBERS),*s['unityPosition'],*s['origin'],*s['worldPosition'])
        return bytes(out)
    def test_valid_abi(self):self.assertEqual(c.extension(self.raw(self.evidence()))['after']['worldPosition'],[11.,22.,33.])
    def test_editor_no_player_attribution(self):
        x=c.interpretation(self.evidence(),1843);self.assertEqual(x['mode'],'editor');self.assertIs(x['playerBelongsToTargetLevel'],False);self.assertFalse(x['playerContactVerified'])
    def test_other_editor_level(self):self.assertFalse(c.interpretation(self.evidence(),1842)['editorIsTargetLevel'])
    def test_unknown_is_not_play(self):
        e=self.evidence();e['mode']=0;e['before']['rawMode']=e['after']['rawMode']=0xb990
        x=c.interpretation(e,1843);self.assertEqual(x['mode'],'unknown');self.assertIsNone(x['playerBelongsToTargetLevel']);self.assertFalse(x['playStateProven'])
    def test_missing_guard_not_play(self):
        e=self.evidence();e.update(mode=0,readableBefore=1,readableAfter=1);self.assertEqual(c.interpretation(e,1843)['mode'],'unknown')
    def test_transition_requires_changed_values(self):
        e=self.evidence();e.update(mode=2,stable=0);e['after']['editing']=0
        x=c.interpretation(e,1843);self.assertEqual(x['mode'],'transition');self.assertIsNone(x['rawLocalAvatarWorldPosition'])
    def test_absent_avatar(self):
        e=self.evidence()
        for key in ('before','after'):e[key].update(avatarStatus=1,positionStatus=1,avatar=0,transform=0)
        self.assertIsNone(c.interpretation(e,1843)['rawLocalAvatarWorldPosition'])
    def test_no_cached_fallback(self):
        e=self.evidence();e['before']['positionStatus']=e['after']['positionStatus']=3
        self.assertIsNone(c.interpretation(e,1843)['rawLocalAvatarWorldPosition'])
    def test_stability_mismatch(self):
        e=self.evidence();e['after']['avatarId']=8
        with self.assertRaisesRegex(ValueError,'STABILITY'):c.interpretation(e,1843)
    def test_mode_mismatch(self):
        e=self.evidence();e['mode']=0
        with self.assertRaisesRegex(ValueError,'MODE_RECEIPT'):c.interpretation(e,1843)
    def test_short(self):
        with self.assertRaisesRegex(ValueError,'ABI_SIZE'):c.extension(b'')
    def test_abi_version(self):
        e=self.evidence();e['version']=2
        with self.assertRaisesRegex(ValueError,'ABI_VERSION'):c.extension(self.raw(e))
    def test_reserved(self):
        e=self.evidence();e['reserved1']=1
        with self.assertRaisesRegex(ValueError,'RESERVED'):c.extension(self.raw(e))
    def test_nan_position(self):
        e=self.evidence();e['after']['worldPosition'][0]=float('nan')
        with self.assertRaisesRegex(ValueError,'NONFINITE'):c.extension(self.raw(e))
    def test_origin_relation(self):
        e=self.evidence();e['after']['worldPosition'][0]=999
        with self.assertRaisesRegex(ValueError,'ORIGIN_RELATION'):c.extension(self.raw(e))
    def test_position_requires_avatar(self):
        e=self.evidence();e['after']['avatarStatus']=1
        with self.assertRaisesRegex(ValueError,'LIVE_AVATAR'):c.extension(self.raw(e))
    def test_duplicate_json(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):json.loads('{"a":1,"a":2}',object_pairs_hook=c.unique)
    def test_control_unavailable(self):
        x=c.interpretation(self.evidence(),1843);self.assertFalse(x['enterSupported']);self.assertFalse(x['exitSupported'])
    def test_candidate_protocol_and_probe(self):
        parent=ROOT/'.runtime/playtest-control-20261016/tests';parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            run=Path(directory);build.copy_sources(run)
            probe=(run/'candidate-source/native/hook_receipt_probe.cpp').read_text();protocol=(run/'candidate-source/native/hook_receipt_protocol.h').read_text()
            self.assertIn('constexpr DWORD kReceiptVersion=21;',protocol);self.assertIn('sizeof(Receipt)==400',protocol)
            self.assertIn('"FIXED_PLAYTEST_OBSERVATION"',probe);self.assertIn('std::memset(receipt, 0, sizeof(*receipt));',probe);self.assertIn('observationHex',probe)
    def test_prepare_no_live_identity_query(self):
        source=(HERE/'build.py').read_text();self.assertNotIn('p.validate_session(',source);self.assertNotIn('p.discover(',source)
    def test_no_write_or_control_entry(self):
        source=(HERE/'native_observe.cpp').read_text();self.assertNotIn('WriteProcessMemory',source);self.assertNotIn('0x1293ab30)',source);self.assertNotIn('+0x410',source)
if __name__=='__main__':unittest.main()
