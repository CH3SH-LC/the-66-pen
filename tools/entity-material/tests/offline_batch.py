"""One complete offline batch. No process inspection, native dispatch or queues."""
from pathlib import Path
import argparse,hashlib,json,os,struct,subprocess,sys,unittest
from datetime import datetime,timezone
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent))
import material_contract as c
import material_build as b
import material_receipt as receipt

DEFAULT=dict(material=0,enableMaterial=False,coverDecorationMaterial=False,coverDecorationColor=False,enableColor=False,argb=0xffffffff,blendMode=6700,rgb=0xffffff,alphaPercent=100.)
def observed(eid=77):
    return dict(entityId=eid,configId=10009002,component=65536,after=dict(DEFAULT),colorAllowed=1,nativeBlocked=0,allowedModes=[6700,6701],allowedMaterials=[6710,6711])
def request(patch):return dict(schemaVersion=1,levelId=c.LEVEL,entities=[dict(entityId=77,**patch)])

class ContractTests(unittest.TestCase):
    def test_exact_channels_and_alpha(self):
        self.assertEqual(c.pack_rgba([18,52,86,128]),0x80123456)
        out=c.merge(request(dict(rgba=[18,52,86,128],enableColor=True,coverDecorationColor=False)),{77:observed()})[0]
        self.assertEqual(out['desired']['argb'],0x80123456);self.assertEqual(out['desired']['rgb'],0x123456)
        self.assertEqual(out['desired']['alphaPercent'],c.f32(c.f32(128/255)*100))
        self.assertEqual(c.state_from_bytes(c.state_bytes(out['desired'])),out['desired'])
    def test_partial_preserves_material(self):
        row=observed();row['after'].update(material=6711,enableMaterial=True,coverDecorationMaterial=True)
        out=c.merge(request(dict(rgba=[255,0,1,255])),{77:row})[0]
        for key in ('material','enableMaterial','coverDecorationMaterial','coverDecorationColor','enableColor','blendMode'):
            self.assertEqual(out['desired'][key],row['after'][key])
    def test_enable_and_decoration_flags_are_independent(self):
        # Distinct bytes proven by c0e9920 and ed54450; do not mirror C++ names.
        active=dict(enableColor=True,coverDecorationColor=False,enableMaterial=True,coverDecorationMaterial=False,material=6711)
        state=c.merge(request(active),{77:observed()})[0]['desired']
        self.assertEqual(c.state_bytes(state)[4:8],bytes([1,0,0,1]))
        disabled=dict(enableColor=False,coverDecorationColor=True,enableMaterial=False,coverDecorationMaterial=True)
        row=observed();row['colorAllowed']=0;row['allowedMaterials']=[]
        state=c.merge(request(disabled),{77:row})[0]['desired']
        self.assertEqual(c.state_bytes(state)[4:8],bytes([0,1,1,0]))
        self.assertTrue(c.shader_matches(state,[dict(properties=1,enable=0.,keywords=0)]))
    def test_rejects_spec_errors(self):
        cases=[dict(rgba=[1,2,3]),dict(rgba=[True,2,3,4]),dict(rgba=[-1,2,3,4]),dict(material=1),dict(material=True),dict(blendMode=1),dict(coverDecorationColor=1),dict(alphaPercent=50)]
        for patch in cases:
            with self.subTest(patch=patch),self.assertRaises(ValueError):c.normalize(request(patch))
        for level in (1073741842,1):
            value=request(dict(material=6711));value['levelId']=level
            with self.assertRaises(ValueError):c.normalize(value)
    def test_runtime_template_catalog_required(self):
        patch=dict(material=6711,coverDecorationMaterial=False,enableMaterial=True)
        row=observed();row['allowedMaterials']=[6710]
        with self.assertRaises(ValueError):c.merge(request(patch),{77:row})
        row=observed();row['configId']=10005023
        with self.assertRaises(ValueError):c.merge(request(patch),{77:row})
        row=observed();row['colorAllowed']=0
        with self.assertRaises(ValueError):c.merge(request(dict(coverDecorationColor=False,enableColor=True)),{77:row})
        row=observed();row['nativeBlocked']=1
        with self.assertRaises(ValueError):c.merge(request(patch),{77:row})
    def test_batch_duplicate_and_bounds(self):
        value=request(dict(material=6711));value['entities']*=2
        with self.assertRaises(ValueError):c.normalize(value)
        for count in (0,33):
            with self.assertRaises(ValueError):c.normalize(dict(schemaVersion=1,levelId=c.LEVEL,entities=[dict(entityId=i+1,material=6711) for i in range(count)]))
    def test_shader_evidence_not_material_cache(self):
        s=dict(DEFAULT,coverDecorationColor=False,enableColor=True,argb=0x80123456,material=6711,coverDecorationMaterial=False,enableMaterial=True)
        slot=dict(properties=7,enable=1.,blend=0.,rgba=[v/255 for v in (18,52,86,128)],keywords=1)
        self.assertTrue(c.shader_matches(s,[slot]))
        for change in (dict(properties=5),dict(enable=0.),dict(blend=1.),dict(keywords=2),dict(rgba=[1.,1.,1.,1.])):
            with self.subTest(change=change),self.assertRaises(ValueError):c.shader_matches(s,[dict(slot,**change)])
    def test_raw_abi_and_unused_tail(self):
        for snapshot in (33208,262584):
            maximum=512 if snapshot==33208 else 4096
            raw=bytearray(64+32*8488+maximum*88+snapshot)
            struct.pack_into('<16I',raw,0,len(raw),1,1,1,0,1,0,0,0,0,0,0,0,0,0,0)
            for off in (64+72,64+96,64+120):raw[off:off+24]=c.state_bytes(DEFAULT)
            decoded,tail=c.decode_extension(raw,snapshot)
            self.assertEqual(len(decoded['rows']),1);self.assertEqual(len(tail),snapshot)
            raw[64+8488]=1
            with self.assertRaises(ValueError):c.decode_extension(raw,snapshot)
    def test_unsafe_roots_rejected(self):
        with self.assertRaises(ValueError):receipt.guarded_run(ROOT/'tools/entity-material')
    def test_no_direct_existing_component_writes(self):
        src=(HERE.parent/'native_material.cpp').read_text()
        self.assertIn('r.payload+0x18',src)
        self.assertIn('0xed54450',src)
        self.assertNotIn('0x19cbd760',src)
        self.assertIn('0x1607290',src)
        self.assertIn('MATERIAL_PRIVATE_TEST',src)
    def test_example_spec_semantics(self):
        spec=c.read(HERE.parent/'statue-material-spec.json')
        self.assertEqual(c.pack_rgba(spec['patch']['rgba']),int(spec['argbHex'],16))
        self.assertFalse(spec['gridRemovalClaim']);self.assertFalse(spec['nativeDispatched'])
        self.assertTrue(spec['patch']['enableMaterial']);self.assertTrue(spec['patch']['enableColor'])
        self.assertFalse(spec['patch']['coverDecorationMaterial']);self.assertFalse(spec['patch']['coverDecorationColor'])

def compile_fixture(run,out):
    # Reuse exactly the source snapshot compiled for the nonlaunchable card.
    source=run/'candidate-source/entity-material/private_callback.cpp'
    source.write_bytes((HERE/'private_callback.cpp').read_bytes())
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
    vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    command=out/'private-callback-build.cmd'
    command.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\ncl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"'+str(run/'target_config.h')+'" "'+str(source)+'" /Fo:"'+str(out/'private-callback.obj')+'" /Fe:"'+str(out/'private-callback.exe')+'" /link User32.lib "'+str(run/'game_context_snapshot.obj')+'"\nexit /b %errorlevel%\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(command)],cwd=out,capture_output=True,text=True,timeout=180)
    (out/'private-callback-build.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    c.require(result.returncode==0,'PRIVATE_CALLBACK_COMPILE_FAILED')
    # This executable's every native resolver target is explicitly stubbed.
    run_result=subprocess.run([str(out/'private-callback.exe')],cwd=out,capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (out/'private-callback.jsonl').write_text(run_result.stdout+run_result.stderr,encoding='utf-8')
    c.require(run_result.returncode==0,'PRIVATE_CALLBACK_TEST_FAILED')
    data=json.loads(run_result.stdout);c.require(data['ok'] and data['nativeCallbacksExplicitlyStubbed'] and not data['gameConnected'],'PRIVATE_CALLBACK_EVIDENCE')
    return data

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=ROOT/'.runtime/entity-material-20261017/final-offline'/stamp;out.mkdir(parents=True)
    report=dict(kind='entity-material-offline-batch-v1',startedUtc=datetime.now(timezone.utc).isoformat(),gameConnected=False,dispatched=False,liveAccepted=False)
    try:
        with (out/'contract-tests.log').open('w',encoding='utf-8') as stream:
            result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests))
        report['contractChecks']=result.testsRun;c.require(result.wasSuccessful(),'CONTRACT_TESTS_FAILED')
        cards=[]
        for mode,large,count in (('inspect',False,1),('set',True,32)):
            args=argparse.Namespace(mode=mode,large_scene=large,fixture_count=count)
            card=b.prepare(args,compile_only=True);c.require(card['compiled'] and not card['launchable'] and not card['called'],'COMPILE_ONLY_GATE')
            receipt.manifest(card['run']);cards.append(card)
        report['cards']=cards
        report['privateCallbacks']=compile_fixture(Path(cards[-1]['run']),out)
        # Source snapshot frozen for delivery and root's shared route checks.
        report['sourceHashes']={str(x.relative_to(ROOT)):c.sha(x) for x in sorted((HERE.parent).rglob('*')) if x.is_file() and '__pycache__' not in x.parts}
        report['ok']=True
    except Exception as exc:
        report.update(ok=False,error=str(exc))
    report['finishedUtc']=datetime.now(timezone.utc).isoformat();c.write(out/'report.json',report)
    print(json.dumps(dict(report=str(out/'report.json'),**report),ensure_ascii=False))
    return 0 if report['ok'] else 2

if __name__=='__main__':raise SystemExit(main())
