"""One complete offline batch; never loads/dispatches a game card."""
from __future__ import annotations
import argparse,copy,json,os,struct,subprocess,sys,unittest
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent))
import contract as c
import build as b
import receipt
STATE=dict(iconId=1,stackLimit=9999,isTradeable=True,name='苹果')
def request(change,kind='item',identifier=0x42000001):return dict(schemaVersion=1,levelId=c.LEVEL,definitions=[dict(id=identifier,kind=kind,set=change)])
def row():return dict(id=0x42000001,subtype=9,resource=0x20000000,nameProperty=0x20010000,dataProperty=0x20020000,after=dict(STATE))
class Contracts(unittest.TestCase):
    def test_unicode_wire_state(self):self.assertEqual(c.state_from(c.state_bytes(STATE)),STATE)
    def test_real_id_bands(self):
        c.normalize(request({'name':'摩拉'},'currency',0x42800001))
        for kind,identifier in [('item',0x42800001),('currency',0x42000001),('item',1),('item',True)]:
            with self.subTest(kind=kind,id=identifier),self.assertRaises(ValueError):c.normalize(request({'name':'a'},kind,identifier))
    def test_field_types_and_currency_limits(self):
        for changes in ({'stackLimit':0},{'stackLimit':True},{'iconId':-1},{'isTradeable':1},{'name':'x\0y'},{'name':'中'*43},{'price':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):c.normalize(request(changes))
        with self.assertRaises(ValueError):c.normalize(request({'stackLimit':2},'currency',0x42800001))
    def test_unrequested_values_preserved(self):
        merged=c.merge(request({'stackLimit':99}),{0x42000001:row()})[0]
        self.assertEqual(merged['mask'],4);self.assertEqual(merged['desired'],dict(STATE,stackLimit=99));self.assertEqual(merged['expected'],STATE)
    def test_noop_is_zero_mask(self):self.assertEqual(c.merge(request({'name':'苹果'}),{0x42000001:row()})[0]['mask'],0)
    def test_stale_or_missing_inspection(self):
        with self.assertRaises(ValueError):c.merge(request({'iconId':2}),{})
        wrong=row();wrong['subtype']=11
        with self.assertRaises(ValueError):c.merge(request({'iconId':2}),{0x42000001:wrong})
    def test_level_and_batch(self):
        wrong=request({'iconId':2});wrong['levelId']=1073741842
        with self.assertRaises(ValueError):c.normalize(wrong)
        wrong=request({'iconId':2});wrong['definitions']*=2
        with self.assertRaises(ValueError):c.normalize(wrong)
        wrong['definitions']=[]
        with self.assertRaises(ValueError):c.normalize(wrong)
    def test_invalid_name_padding(self):
        raw=bytearray(c.state_bytes(STATE));raw[-1]=1
        with self.assertRaises(ValueError):c.state_from(raw)
    def test_explicit_output_roots(self):
        for path in (ROOT/'tools',b.OUTPUT,b.OUTPUT.parent/'outside'):
            with self.assertRaises(ValueError):receipt.guarded_run(path)
    def test_native_field_evidence(self):
        evidence=HERE.parent/'evidence'
        for name,fragments in {'b840d40':['0xc0154b8d','[rdx + 0x3c]'],'8b30d70':['0xc0154b8d','[rdx + 0x2c]'],'ebabe30':['0x13abec4a','[rdx + 0x40]'],'eb7a7e0':['0xf4ce55d9','[rdx + 0x28]'],'b0a6ec0':['0x107abdf0','0x9c26c70','0xc7bab90','0xa717810']}.items():
            text=(evidence/(name+'.asm')).read_text()
            for fragment in fragments:self.assertIn(fragment,text)
    def test_nonlauncher_sources(self):
        text=(HERE.parent/'native_properties.cpp').read_text()
        self.assertIn('PROPERTIES_PRIVATE_TEST',text);self.assertIn('0x526de0',text);self.assertNotIn('0x526e90',text)
        self.assertNotIn('WriteProcessMemory',text);self.assertNotIn('0x107abfa0',text)
    def test_independent_verification_mismatch(self):
        from unittest.mock import patch
        a=dict(ok=True,mode='set',session={},origin=[],rows=[dict(row(),data=4,companion=5,desired=STATE)])
        z=copy.deepcopy(a);z['mode']='inspect';z['rows'][0]['after']['iconId']=2
        with patch.object(receipt,'decode',side_effect=[a,z]),patch.object(receipt,'read',side_effect=[{'finishedUtc':'2026-10-17T01:00:00+00:00'},{'startedUtc':'2026-10-17T01:01:00+00:00'}]),self.assertRaises(ValueError):receipt.verify('write','inspect')

def private_callbacks(card,out):
    run=Path(card['run']);target=run/'candidate-source/template-properties/tests';target.mkdir();source=target/'private_callback.cpp';source.write_bytes((HERE/'private_callback.cpp').read_bytes())
    vswhere=Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
    vs=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip();vc=Path(vs)/'VC/Auxiliary/Build/vcvars64.bat'
    command=out/'private-build.cmd';exe=out/'private-callback.exe'
    command.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\ncl /nologo /std:c++17 /EHsc /W4 /WX /O2 /MD /utf-8 /FI"'+str(run/'target_config.h')+'" "'+str(source)+'" /Fo:"'+str(out/'private.obj')+'" /Fe:"'+str(exe)+'" /link User32.lib\nexit /b %errorlevel%\n',encoding='utf8')
    built=subprocess.run(['cmd.exe','/d','/c',str(command)],cwd=out,capture_output=True,text=True,timeout=180);(out/'private-build.log').write_text(built.stdout+built.stderr,encoding='utf8');c.require(built.returncode==0,'PRIVATE_COMPILE_FAILED')
    result=subprocess.run([str(exe),str(out/'private-receipt.bin')],cwd=out,capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));(out/'private.log').write_text(result.stdout+result.stderr,encoding='utf8');c.require(result.returncode==0,'PRIVATE_CALLBACK_FAILED')
    raw=(out/'private-receipt.bin').read_bytes();wire,tail=c.decode_extension(raw,262584)
    c.require(wire['status']==0 and wire['rows'][0]['after']==dict(iconId=2,stackLimit=99,isTradeable=False,name='New') and len(tail)==262584,'RAW_RECEIPT_DECODE')
    c.require(wire['rows'][0]['beforeBlob']!=0 and wire['catalogBefore']==wire['catalogAfter'] and all(x['before']==x['after'] for x in wire['guards']),'RAW_TRANSACTION_AND_GUARDS')
    return dict(ok=True,checks=result.stdout.count('PASS '),nativeCallbacksExplicitlyStubbed=True,gameConnected=False,rawReceiptBytes=len(raw),nativeFieldEffectsProven=False)
def main():
    out=ROOT/'.runtime/template-properties-20261017/offline'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');out.mkdir(parents=True)
    report=dict(kind='template-properties-offline-batch-v1',startedUtc=datetime.now(timezone.utc).isoformat(),gameConnected=False,dispatched=False,liveAccepted=False)
    try:
        with (out/'contract-tests.log').open('w',encoding='utf8') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Contracts))
        report['contractChecks']=result.testsRun;c.require(result.wasSuccessful(),'CONTRACT_TESTS_FAILED')
        cards=[]
        for mode,large in [('inspect',False),('set',True)]:
            card=b.prepare(argparse.Namespace(mode=mode,large_scene=large),compile_only=True);receipt.manifest(card['run']);c.require(card['compiled'] and not card['launchable'] and not card['called'],'COMPILE_ONLY_GATE');cards.append(card)
            with self_raises():receipt.decode(card['run'])
        report['productionCards']=cards;report['privateCallbacks']=private_callbacks(cards[-1],out)
        report['sourceHashes']={str(x.relative_to(ROOT)):c.sha(x) for x in sorted(HERE.parent.rglob('*')) if x.is_file() and '__pycache__' not in x.parts};report['ok']=True
    except Exception as exc:report.update(ok=False,error=str(exc))
    report['finishedUtc']=datetime.now(timezone.utc).isoformat();c.write(out/'report.json',report)
    print(json.dumps(dict(report=str(out/'report.json'),ok=report['ok'],error=report.get('error')),ensure_ascii=False));return 0 if report['ok'] else 2
class self_raises:
    def __enter__(self):return self
    def __exit__(self,typ,value,tb):
        if typ is None:raise AssertionError('compile card unexpectedly accepted as live')
        return issubclass(typ,ValueError)
if __name__=='__main__':raise SystemExit(main())
