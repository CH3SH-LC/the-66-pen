"""Bounded read-only catalog/file sampling during a user-operated scene edit."""
import argparse,datetime,hashlib,json,pathlib,subprocess,time
ap=argparse.ArgumentParser();ap.add_argument('--run-id',required=True);a=ap.parse_args()
root=pathlib.Path(__file__).resolve().parents[2]
out=root/'.runtime/verification/realtime-injection-20260920'/('manual-'+a.run_id);out.mkdir(exist_ok=False)
base=pathlib.Path('C:/Users/PUBLIC_USER/AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001')
def call(op):
 p=subprocess.run(['python',str(root/'tools/editor-bridge/elevated-request.py'),'call','--op',op,'--run-id',a.run_id,'--timeout','15'],capture_output=True,encoding='utf-8')
 if p.returncode:raise RuntimeError(p.stderr or p.stdout)
 return json.loads(p.stdout)
def files():
 rows=[]
 for folder in ['Temp','Beyond_Local_Save_Level']:
  for p in sorted((base/folder).glob('*')):
   if not p.is_file():continue
   try:
    raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    rows.append({'path':str(p.relative_to(base)),'size':len(raw),'mtimeNs':p.stat().st_mtime_ns,'sha256':sha})
    if p.name=='1073741832.gil':
     copy=out/(folder+'-'+sha+'.gil')
     if not copy.exists():copy.write_bytes(raw)
   except OSError as e:rows.append({'path':str(p),'error':str(e)})
 return rows
try:
 initial={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files(),'catalog':call('catalog')}
 (out/'baseline.json').write_text(json.dumps(initial,ensure_ascii=False),encoding='utf-8')
 (out/'observer-start.json').write_text(json.dumps(call('start-external-asset-observer')),encoding='utf-8')
 print('READY '+str(out),flush=True)
 settings=json.loads((root/'.runtime/editor-bridge/runs'/a.run_id/'bridge-settings.json').read_text(encoding='utf-8-sig'))
 remaining=(datetime.datetime.fromisoformat(settings['expiresUtc'])-datetime.datetime.now(datetime.timezone.utc)).total_seconds()
 end=time.monotonic()+min(110,max(0,remaining-10))
 with (out/'samples.jsonl').open('w',encoding='utf-8') as log:
  while time.monotonic()<end:
   row={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files(),'catalog':call('catalog'),'observer':call('log-observer-evidence')}
   log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush();time.sleep(3)
 print('SAMPLING_COMPLETE',flush=True)
except Exception as e:
 (out/'error.txt').write_text(str(e),encoding='utf-8');raise
finally:
 try:(out/'stop.json').write_text(json.dumps(call('stop')),encoding='utf-8')
 except Exception as e:(out/'cleanup-error.txt').write_text(str(e),encoding='utf-8')
