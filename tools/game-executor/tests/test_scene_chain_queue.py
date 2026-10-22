"""Offline chain transport checks: no game, helper, compiler or elevation."""
from __future__ import annotations
import io
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

EXECUTOR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(EXECUTOR))
import scene_chain
import scene_cli

class ChainQueueTests(unittest.TestCase):
    def setUp(self):
        root=scene_cli.ROOT/'.runtime/verification/update-repair-20260926/native-helper/scene-cli/chain-tests'
        root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name)
        self.plan=self.work/'plan.json'
        # 2026-10-09: scene_cli.TEMPLATES is gone with the whitelist; any uint32 id is valid.
        self.placements=[dict(template_id=20001034,position=[1,2,3],scale=[1,1,1],label='existing plan metadata')]
        self.plan.write_text(json.dumps(dict(placements=self.placements)),encoding='utf-8')
        self.session=self.work/'session.json';self.session.write_text('{}',encoding='utf-8')
        self.review=self.work/'review.json';self.review.write_text('{}',encoding='utf-8')

    def run_chain(self,extra):
        stdout=io.StringIO()
        args=['scene_chain.py',str(self.plan),'--session',str(self.session),'--level-id','7','--review',str(self.review),*extra]
        with mock.patch.object(sys,'argv',args),redirect_stdout(stdout):
            code=scene_chain.main()
        return code,json.loads(stdout.getvalue())

    def test_real_cli_stdout_is_utf8_even_with_cp936_environment(self):
        # Exercise the real entry point with a harmless pre-dispatch file error.
        missing=self.work/'测试关卡不存在.json'
        env=dict(os.environ,PYTHONIOENCODING='cp936',PYTHONUTF8='0')
        result=subprocess.run([sys.executable,'-B',str(EXECUTOR/'scene_chain.py'),
                               str(missing),'--level-id','7'],
                              capture_output=True,env=env,timeout=30)
        self.assertEqual(result.returncode,2,result.stderr)
        payload=json.loads(result.stdout.decode('utf-8'))
        self.assertFalse(payload['ok'])
        self.assertIn('测试关卡不存在.json',payload['error'])
        self.assertFalse(payload['retryAttempted'])
        self.assertEqual(payload['steps'],[])

    def test_queue_batch_uses_same_closed_payload_without_build_or_retry(self):
        reply=dict(ok=False,pending=True,outcomeUncertain=True,requestId='f'*32,run='original-run',retryAttempted=False)
        with mock.patch.object(scene_chain,'send_queued_scene',return_value=reply) as send, \
             mock.patch.object(scene_chain,'build_profile') as build, \
             mock.patch.object(scene_chain,'run_profile') as run:
            code,result=self.run_chain(['--elevated-queue',str(self.work)])
        self.assertEqual(code,2)
        self.assertTrue(result['outcomeUncertain'])
        self.assertEqual(result['requestId'],'f'*32)
        self.assertEqual(result['run'],'original-run')
        self.assertEqual(result['steps'],[reply])
        self.assertEqual(send.call_count,1)
        payload,action,queue=send.call_args.args
        self.assertEqual(action,'create-batch');self.assertEqual(queue,self.work)
        self.assertEqual(set(payload),{'kind','action','sessionPath','reviewPath','levelId','placements'})
        self.assertEqual(payload['placements'][0]['rotation'],[0.,0.,0.])
        self.assertNotIn('label',payload['placements'][0])
        build.assert_not_called();run.assert_not_called()


    def test_chain_request_passes_actual_client_without_json_conversion(self):
        spec=importlib.util.spec_from_file_location('_chain_actual_client',scene_cli.ELEVATED_REQUEST)
        client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
        validated=[]
        def contract_sender(payload,timeout,*,queue_dir):
            canonical=client.validate_native_scene_request(payload)
            self.assertEqual(payload,canonical)
            validated.append(payload)
            return dict(ok=True,action='create-batch',requestId='b'*32)
        with mock.patch.object(scene_cli,'load_native_sender',return_value=contract_sender), \
             mock.patch.object(scene_chain,'build_profile') as build, \
             mock.patch.object(scene_chain,'run_profile') as run:
            code,result=self.run_chain(['--elevated-queue',str(self.work)])
        self.assertEqual(code,0,result)
        self.assertEqual(len(validated),1)
        self.assertEqual(result['placementCount'],1)
        for field in ('position','rotation','scale'):
            self.assertIs(type(validated[0]['placements'][0][field]),list)
        self.assertNotIn('label',validated[0]['placements'][0])
        build.assert_not_called();run.assert_not_called()

    def test_prepare_queue_combination_refuses_before_dispatch(self):
        with mock.patch.object(scene_chain,'send_queued_scene') as send, \
             mock.patch.object(scene_chain,'build_profile') as build:
            code,result=self.run_chain(['--prepare-only','--elevated-queue',str(self.work)])
        self.assertEqual(code,2);self.assertIn('--prepare-only',result['error'])
        send.assert_not_called();build.assert_not_called()

    def test_default_transport_keeps_local_build_and_run(self):
        profile=dict(run=str(self.work/'run'))
        with mock.patch.object(scene_chain,'build_profile',return_value=profile) as build, \
             mock.patch.object(scene_chain,'run_profile',return_value=dict(ok=True,run=profile['run'])) as run, \
             mock.patch.object(scene_chain,'send_queued_scene') as send:
            code,result=self.run_chain([])
        self.assertEqual(code,0);self.assertTrue(result['ok'])
        self.assertEqual(build.call_count,1);run.assert_called_once_with(profile);send.assert_not_called()

if __name__=='__main__':unittest.main()
