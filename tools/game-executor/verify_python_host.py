"""Independent DLL/ctypes integration checks in this Python host, not Genshin."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import gc
import hashlib
import json
from pathlib import Path
import threading
import time
import unittest

from client import (DLL, ROOT, Adapter, AdapterResult, ExecutorError, NativeExecutor,
                    Request, Result, request)

OUT = None


def create(number=1, revision=11, **kw):
    return request(request_id=number, scene_id=7, scene_revision=revision,
                   operation='create_instance', template_id=42, **kw)


class HostTests(unittest.TestCase):
    def error(self, reason, fn):
        with self.assertRaises(ExecutorError) as caught:fn()
        self.assertEqual(caught.exception.reason, reason)

    def test_no_adapter_and_missing_operation_are_unavailable(self):
        with NativeExecutor() as x:
            self.error('unavailable', lambda:x.submit(create()))
            self.error('not_found', lambda:x.result(1))
            x.bind_callbacks(read_scene=lambda:(7,11))
            self.error('unavailable', lambda:x.submit(create()))
            self.error('unavailable', lambda:x.submit(request(
                request_id=2,scene_id=7,scene_revision=11,operation='save_level')))

    def test_cross_thread_create_save_and_readback_in_python_fixture(self):
        owner = threading.get_ident()
        state = {'scene_id':7,'revision':11,'entities':[]}
        calls = []
        save_path = OUT/'python-host-fixture.json'
        def add(r):
            self.assertEqual(threading.get_ident(),owner)
            calls.append('create')
            state['entities'].append({'entity_id':1001,'template_id':r.template_id,
                'position':list(r.position),'rotation':list(r.rotation),'scale':list(r.scale)})
            state['revision'] += 1
            return 1001
        def save(r):
            self.assertEqual(threading.get_ident(),owner)
            calls.append('save')
            with save_path.open('x',encoding='utf-8') as f:json.dump(state,f)
            return 0
        with NativeExecutor() as x, ThreadPoolExecutor(max_workers=1) as worker:
            x.bind_callbacks(read_scene=lambda:(state['scene_id'],state['revision']),
                             create_instance=add,save_level=save)
            r = create(position=(1,2,3),rotation=(0,90,0),scale=(2,2,2))
            self.assertEqual(worker.submit(x.submit,r).result()['state'],'queued')
            self.assertEqual(worker.submit(x.submit,r).result()['state'],'queued')
            self.assertEqual(state['entities'],[])
            self.error('wrong_thread',lambda:worker.submit(x.pump).result())
            self.assertEqual(x.pump(),1)
            receipt=x.result(1)
            self.assertEqual(receipt['state'],'completed')
            self.assertEqual(receipt['entity_id'],1001)
            self.assertFalse(receipt['game_runtime_verified'])
            self.assertFalse(receipt['gil_save_verified'])
            self.assertEqual(x.submit(r)['state'],'completed')
            s=request(request_id=2,scene_id=7,scene_revision=12,operation='save_level')
            worker.submit(x.submit,s).result()
            self.assertEqual(x.pump(),1)
            self.assertEqual(x.submit(s)['state'],'completed')
            self.assertEqual(calls,['create','save'])
            saved=json.loads(save_path.read_text())
            self.assertEqual(saved,state)
            self.assertEqual(saved['entities'][0]['position'],[1,2,3])

    def test_scene_revision_changed_after_queue_rejects(self):
        stamp=[7,11];calls=[]
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=lambda:tuple(stamp),create_instance=lambda r:calls.append(r) or 1)
            x.submit(create());stamp[1]=12
            self.assertEqual(x.pump(),1)
            self.assertEqual(x.result(1)['state'],'scene_changed')
            self.assertEqual(x.result(1)['scene_revision'],12)
            stamp[1]=11
            self.assertEqual(x.submit(create())['state'],'scene_changed')
            self.assertEqual(x.pump(),0)
            self.assertEqual(calls,[])

    def test_expired_request_does_not_run_and_is_not_refreshed(self):
        calls=[]
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:calls.append(r) or 1)
            r=create(ttl_ms=5);x.submit(r);time.sleep(.03)
            x.submit(r);x.pump()
            self.assertEqual(x.result(1)['state'],'expired')
            self.assertEqual(calls,[])

    def test_expiry_during_scene_callback_prevents_operation(self):
        calls=[];reads=[]
        def read():reads.append(1);time.sleep(.03);return 7,11
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=read,create_instance=lambda r:calls.append(r) or 1)
            x.submit(create(ttl_ms=10));x.pump()
            self.assertEqual(x.result(1)['state'],'expired')
            self.assertEqual(calls,[])
            self.assertEqual(len(reads),1)

    def test_failure_after_side_effect_never_retries(self):
        effects=[]
        def partial(r):effects.append(r.request_id);raise ValueError('after effect')
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=partial)
            r=create();x.submit(r);x.pump()
            self.assertEqual(x.result(1)['state'],'failed')
            self.assertEqual(x.submit(r)['state'],'failed')
            self.assertEqual(x.pump(),0)
            self.assertEqual(effects,[1])

    def test_id_conflict_and_unbind_cancel(self):
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:1)
            x.submit(create())
            self.error('id_conflict',lambda:x.submit(create(position=(4,0,0))))
            x.unbind()
            self.assertEqual(x.result(1)['state'],'unavailable')
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:1)
            self.assertEqual(x.submit(create())['state'],'unavailable')
            self.assertEqual(x.pump(),0)

    def test_callback_reentry_is_busy_without_destroying_handle(self):
        seen=[]
        with NativeExecutor() as x:
            def add(r):
                self.assertEqual(x.result(r.request_id)['state'],'running')
                self.error('busy',x.pump)
                self.error('busy',x.unbind)
                self.error('busy',x.close)
                seen.append(r.request_id)
                return 100
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=add)
            x.submit(create());x.pump()
            self.assertEqual(x.result(1)['state'],'completed')
            self.assertEqual(seen,[1])

    def test_worker_reads_during_owner_callback_without_python_lock_deadlock(self):
        with NativeExecutor() as x, ThreadPoolExecutor(max_workers=1) as worker:
            def add(r):
                observed=worker.submit(x.result,r.request_id).result(timeout=2)
                self.assertEqual(observed['state'],'running')
                self.error('busy',lambda:worker.submit(x.close).result(timeout=2))
                return 1001
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=add)
            x.submit(create());x.pump()
            self.assertEqual(x.result(1)['state'],'completed')

    def test_retained_callback_request_has_owned_memory(self):
        retained=[]
        with NativeExecutor() as x:
            x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:retained.append(r) or 100)
            x.submit(create(1));x.submit(create(2,position=(5,6,7)));x.pump()
            self.assertEqual([r.request_id for r in retained],[1,2])
            self.assertEqual(list(retained[0].position),[0,0,0])
            self.assertEqual(list(retained[1].position),[5,6,7])
            retained[0].request_id=99
            self.assertEqual(x.result(1)['request_id'],1)

    def test_unbind_reference_release_is_atomic_with_next_thread_bind(self):
        after_native_unbind=threading.Event();release_unbind=threading.Event()
        bind_attempt=threading.Event();bound=threading.Event();run_second=threading.Event()
        with NativeExecutor() as x, ThreadPoolExecutor(max_workers=2) as workers:
            original=x._dll.GE_Unbind
            def interposed(handle):
                code=original(handle)
                after_native_unbind.set()
                if not release_unbind.wait(timeout=3):raise RuntimeError('test release timed out')
                return code
            x._dll.GE_Unbind=interposed
            def first():
                x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:111)
                x.unbind()
            def second():
                bind_attempt.set()
                x.bind_callbacks(read_scene=lambda:(7,11),create_instance=lambda r:222)
                bound.set()
                if not run_second.wait(timeout=3):raise RuntimeError('test pump timed out')
                x.submit(create());x.pump();answer=x.result(1);x.close()
                return answer
            a=workers.submit(first)
            self.assertTrue(after_native_unbind.wait(timeout=2))
            b=workers.submit(second)
            try:
                self.assertTrue(bind_attempt.wait(timeout=2))
                self.assertFalse(bound.wait(timeout=.03))
            finally:
                release_unbind.set()
            a.result(timeout=2)
            self.assertTrue(bound.wait(timeout=2))
            gc.collect();run_second.set()
            self.assertEqual(b.result(timeout=2)['entity_id'],222)

    def test_input_validation_prevents_wrap_or_nonfinite(self):
        for kwargs in [{'request_id':True},{'request_id':1<<64},{'position':(float('nan'),0,0)},
                       {'position':(1e100,0,0)},{'scale':(1,0,1)}]:
            base=dict(request_id=1,scene_id=7,scene_revision=11,operation='create_instance',template_id=42)
            base.update(kwargs)
            with self.assertRaises(ValueError):request(**base)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    OUT=Path(args.out).resolve()
    allowed=(ROOT/'.runtime/game-executor/verification').resolve()
    if not OUT.is_relative_to(allowed) or OUT==allowed:
        raise SystemExit('Use a new child directory under .runtime/game-executor/verification')
    OUT.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(HostTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary={'scope':'Native DLL in independent Python host; no game attached',
             'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
             'gameRuntimeVerified':False,'gilSaveVerified':False,
             'dllSha256':hashlib.sha256(DLL.read_bytes()).hexdigest(),
             'abiSizes':{c.__name__:C.sizeof(c) for c in (Request,Result,Adapter,AdapterResult)}}
    (OUT/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
