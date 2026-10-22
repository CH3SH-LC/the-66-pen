"""Native-helper client contracts, isolated files and fake health/queue only."""
from pathlib import Path
import contextlib, importlib.util, json, math, tempfile, unittest, uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
P=Path(__file__).resolve().parents[1]/'elevated-request.py'
spec=importlib.util.spec_from_file_location('native_queue_client',P)
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class NativeClientTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.queue=self.root/'.runtime/editor-bridge/q';self.queue.mkdir(parents=True)
  self.session=self.root/'.runtime/session.json';self.session.write_text('{}')
  self.review=self.root/'.runtime/review.json';self.review.write_text('{}')
  self.p1=patch.object(c,'ROOT',self.root);self.p2=patch.object(c,'QUEUE',self.queue);self.p1.start();self.p2.start()
 def tearDown(self):self.p2.stop();self.p1.stop();self.tmp.cleanup()
 def request(self,action='inspect'):
  d=dict(kind='native-scene',action=action,sessionPath=str(self.session),levelId=1073741839)
  if action!='inspect':d['reviewPath']=str(self.review)
  if action in ('create','creature-create'):d.update(templateId=30002002 if action=='creature-create' else 20001200,position=[1,2,3],rotation=[0,0,0],scale=[1,1,1])
  if action=='create-batch':d['placements']=[dict(template_id=20001200,position=[1,2,3],rotation=[0,0,0],scale=[1,1,1])]
  return d
 def test_all_actions(self):
  for a in c.NATIVE_ACTIONS:self.assertEqual(c.validate_native_scene_request(self.request(a))['action'],a)
 def test_required_and_unknown_fields(self):
  for field in ('kind','action','sessionPath','levelId'):
   q=self.request();del q[field]
   with self.assertRaises((ValueError,KeyError)):c.validate_native_scene_request(q)
  for field in ('run','wrapper','exe','script','hash','plan','baseline','command','timeout'):
   q=self.request();q[field]='anything'
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
 def test_bad_actions_and_ids(self):
  for a in ('CREATE','delete','run',None,{},True):
   q=self.request();q['action']=a
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
  for i in (0,-1,2**32,True,1.0,'1'):
   q=self.request();q['levelId']=i
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
 def test_mutation_needs_review(self):
  for a in ('create','creature-create','save','create-batch'):
   q=self.request(a);del q['reviewPath']
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
 def test_vector_finite_exact_and_positive(self):
  for v in ([],[1,2],[1,2,3,4],[True,1,1],['1',1,1],[math.nan,0,0],[math.inf,0,0],[1e100,0,0]):
   q=self.request('create');q['position']=v
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
  for v in ([0,1,1],[-1,1,1],[1e-100,1,1]):
   q=self.request('create');q['scale']=v
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
 def test_batch_bounds_and_closed_placement(self):
  q=self.request('create-batch');row=q['placements'][0]
  q['placements']=[row]*256;self.assertEqual(len(c.validate_native_scene_request(q)['placements']),256)
  # 2026-10-11: template_id=1 used to be refused by the (now-removed) whitelist; a create
  # accepts any uint32 templateId since 2026-10-09 (see test_template_id_unrestricted.py).
  # The closed-placement check is now a value that is not a uint32 at all.
  for rows in ([],[row]*257,{},[dict(row,command='x')],[dict(row,template_id=2**32)]):
   q['placements']=rows
   with self.assertRaises(ValueError):c.validate_native_scene_request(q)
 def test_paths_fixed_runtime_json_existing(self):
  for path in ('relative.json',str(self.root/'outside.json'),str(self.root/'.runtime/missing.json'),str(self.root/'.runtime/session.json:stream'),str(self.root/'.runtime/session.json.')):
   q=self.request();q['sessionPath']=path
   with self.assertRaises((ValueError,OSError)):c.validate_native_scene_request(q)
 def test_submit_once_timeout_then_poll(self):
  rid=uuid.uuid4().hex;p={'kind':'author-graph','runId':'x','requestId':'r'}
  first=c.send(p,timeout=0,request_id=rid);self.assertTrue(first['pending']);self.assertEqual(first['requestId'],rid)
  req=self.queue/f'{rid}.request.json';req.unlink()
  second=c.send(p,timeout=0,request_id=rid);self.assertTrue(second['pending']);self.assertFalse(req.exists())
  (self.queue/f'{rid}.response.json').write_text('{"ok":true,"native":"completed"}')
  self.assertEqual(c.poll_request(rid,timeout=0)['native'],'completed')
  self.assertFalse(req.exists())
 def test_same_id_different_payload_refuses(self):
  rid=uuid.uuid4().hex;c.send({'kind':'status'},timeout=0,request_id=rid)
  with self.assertRaisesRegex(ValueError,'PAYLOAD_MISMATCH'):c.send({'kind':'load'},timeout=0,request_id=rid)
 def test_bad_id_timeout_before_enqueue(self):
  for rid in ('../bad','X'*32,'1',''):
   with self.assertRaises(ValueError):c.send({'kind':'status'},timeout=0,request_id=rid)
  for t in (-1,math.nan,math.inf,1801):
   with self.assertRaises(ValueError):c.send({'kind':'status'},timeout=t,request_id='a'*32)
  self.assertEqual(list(self.queue.iterdir()),[])
 def test_error_and_partial_response_are_not_success(self):
  rid='a'*32;(self.queue/f'{rid}.error.txt').write_text('failed')
  r=c.poll_request(rid,timeout=0);self.assertFalse(r['ok']);self.assertTrue(r['outcomeUncertain'])
  rid='b'*32;(self.queue/f'{rid}.response.json').write_text('{')
  self.assertTrue(c.poll_request(rid,timeout=0)['pending'])
 def health(self):
  now=datetime.now(timezone.utc)
  (self.queue/'runner.heartbeat').write_text(now.isoformat()+' pid=123 handled=0')
  return {'kind':'status','elevated':True,'pid':123,'deadlineUtc':(now+timedelta(hours=1)).isoformat(),
   'nativeScene':{'schema':1,'enabled':True,'blocked':False,'actions':list(c.NATIVE_ACTIONS),'pinsDigest':'a'*64,'projectRoot':str(self.root)}}
 def test_health_success_then_native_explicit_id(self):
  health=self.health()
  with patch.object(c,'send',side_effect=[health,{'ok':True}]) as send:
   self.assertTrue(c.send_native_scene(self.request(),queue_dir=self.queue)['ok'])
   self.assertEqual(send.call_count,2);self.assertRegex(send.call_args.kwargs['request_id'],r'^[a-f0-9]{32}$')
 def test_bad_health_never_native_dispatch(self):
  for field,value in [('enabled',False),('blocked',True),('schema',2),('pinsDigest','bad'),('projectRoot','wrong')]:
   health=self.health();health['nativeScene'][field]=value
   with patch.object(c,'send',return_value=health) as send:
    with self.assertRaises(ValueError):c.send_native_scene(self.request(),queue_dir=self.queue)
    self.assertEqual(send.call_count,1)
 def test_bad_payload_before_health(self):
  with patch.object(c,'send') as send:
   with self.assertRaises(ValueError):c.send_native_scene(dict(self.request(),exe='x'),queue_dir=self.queue)
   send.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)
