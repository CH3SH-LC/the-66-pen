"""Create, verify and bind both complete native option graphs once.

Only the named two graphs and two existing visual hosts are writable. Every
request has a journal; any partial/unknown operation stops without replay.
"""
from pathlib import Path
import argparse,json,sys,time,uuid,importlib.util
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from tools.authoring import author
from tools.gameplan.demo import farming_tabs as tabs
from tools.gameplan.demo.farming_manual import verify_plan_export

def deploy(queue,run_id,out,resume=False):
    out=Path(out).resolve()
    if not out.is_relative_to(ROOT/'.runtime'):raise ValueError('PROJECT_OUTPUT_REQUIRED')
    out.mkdir(parents=True,exist_ok=resume);run_id=str(uuid.UUID(run_id));token=uuid.uuid4().hex[:12]
    initial=author.read_json(author.RUNS/run_id/'bridge-settings.json');editor_pid=initial['pid']
    spec=importlib.util.spec_from_file_location('native_tabs_queue',ROOT/'tools/editor-bridge/elevated-request.py')
    transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(transport);transport.QUEUE=Path(queue).resolve()
    summaries=[]
    for label,plan,host in [('shop',tabs.shop_plan(),tabs.SHOP_HOST),('farm',tabs.farm_plan(),tabs.FARM_HOST)]:
        folder=out/label;folder.mkdir(exist_ok=resume);artifact=tabs.package(plan,host)
        for key,data in artifact.items():(folder/(key+'.json')).write_text(json.dumps(data,ensure_ascii=True,indent=2),encoding='utf-8')
        seq=0
        def call(action,extra=()):
            nonlocal seq,run_id
            seq+=1;rid=f'native-tabs-{token}-{label}-{seq}-{action}'
            receipt_path=folder/f'{seq:02}-{action}.json'
            if resume and receipt_path.is_file():
                cached=json.loads(receipt_path.read_text(encoding='utf-8'))
                if cached.get('ok') is not True:raise RuntimeError('PRIOR_RESULT_REQUIRES_RECONCILIATION')
                print(label,action,'using completed receipt; no replay',flush=True);return cached['backend']
            settings=author.read_json(author.RUNS/run_id/'bridge-settings.json')
            remaining=(datetime.fromisoformat(settings['expiresUtc'].replace('Z','+00:00'))-datetime.now(timezone.utc)).total_seconds()
            if remaining<100:
                if remaining>0:
                    print('Finishing current bounded bridge lease before replacement',flush=True)
                    time.sleep(remaining+1)
                closed=author.RUNS/run_id/'lease-closed.json';close_deadline=time.monotonic()+20
                while not closed.is_file() and time.monotonic()<close_deadline:time.sleep(.5)
                if not closed.is_file() or not author.read_json(closed).get('cleanupSucceeded'):raise RuntimeError('OLD_SCOPE_CLEANUP_REQUIRED')
                loaded=transport.send({'kind':'load','targetPid':editor_pid},timeout=60,request_id=uuid.uuid4().hex)
                (folder/f'{seq:02}-fresh-scope.json').write_text(json.dumps(loaded,indent=2),encoding='utf-8')
                if loaded.get('accepted') is not True:raise RuntimeError('FRESH_SCOPE_NOT_ACCEPTED')
                run_id=str(uuid.UUID(loaded['runId']))
                (out/'bridge-session.json').write_text(json.dumps({'runId':run_id}),encoding='utf-8')
            argv=['--elevated-queue',str(queue),'graph',action,'--request-id',rid,'--run-id',run_id,'--name',plan.name,*map(str,extra)]
            command=author.command_from_args(author.parser().parse_args(argv));author.lease(run_id)
            result=author.execute(command,rid);receipt_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(label,action,result.get('ok'),result.get('error'),flush=True)
            if result.get('ok') is not True:raise RuntimeError('STOP_WITHOUT_REPLAY:'+rid+':'+str(result.get('error')))
            return result['backend']
        prior=call('lookup')
        # Missing graph is represented by found:false; any preexisting name
        # requires an evidence-based resume instead of a duplicate create.
        if prior.get('found') is True or prior.get('graphId'):raise RuntimeError('GRAPH_ALREADY_EXISTS')
        call('create',['--graph-kind',20000])
        found=None
        for _ in range(12):
            found=call('lookup')
            if found.get('graphId'):break
            time.sleep(.5)
        if not found or not found.get('graphId') or found.get('nodeCount')!=0:raise RuntimeError('GRAPH_CREATION_UNCONFIRMED')
        gid=found['graphId'];built=call('build-plan',['--graph-id',gid,'--expected-node-count',0,'--plan-file',folder/'batchPlan.json'])
        if built.get('nodeCount')!=len(plan.nodes) or len(built.get('nodes',[]))!=len(plan.nodes):raise RuntimeError('GRAPH_BATCH_SHAPE')
        if any(n.definition_id!=row['definitionId'] for n,row in zip(plan.nodes,built['nodes'])):raise RuntimeError('GRAPH_DEFINITION_DRIFT')
        mapping={n.alias:row['nodeId'] for n,row in zip(plan.nodes,built['nodes'])}
        receipt=dict(ok=True,graphId=gid,nodeIds=mapping);(folder/'mapping.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        values=[]
        for source in artifact['followups']:
            row=dict(source);alias=row.pop('nodeAlias');row.pop('node');row.pop('action');row.update(nodeId=mapping[alias],definitionId=plan.aliases()[alias].definition_id);values.append(row)
        for start in range(0,len(values),24):
            path=folder/f'values-{start}.json';path.write_text(json.dumps(values[start:start+24],ensure_ascii=True),encoding='utf-8')
            call('values',['--graph-id',gid,'--expected-node-count',len(plan.nodes),'--values-file',path])
        exported=call('export',['--graph-id',gid]);path=Path(exported['path']);deadline=time.monotonic()+35
        while not path.is_file() and time.monotonic()<deadline:time.sleep(.5)
        verified=verify_plan_export(path,plan,artifact,build_receipt=receipt)
        (folder/'export-verified.json').write_text(json.dumps(verified,indent=2),encoding='utf-8')
        if not verified.get('ok'):raise RuntimeError('GRAPH_EXPORT_NOT_VERIFIED')
        call('bind',['--graph-id',gid,'--expected-node-count',len(plan.nodes),'--entity-id',host])
        binding=call('lookup')
        if binding.get('boundEntityIds')!=[host]:raise RuntimeError('HOST_BINDING_NOT_EXACT')
        summaries.append(dict(label=label,graphId=gid,hostId=host,name=plan.name,exportPath=str(path),mapping=receipt))
    result=dict(ok=True,graphs=summaries,nativeSaveVerified=False,playVerified=False)
    (out/'deployed.json').write_text(json.dumps(result,indent=2),encoding='utf-8');return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--queue',required=True);ap.add_argument('--run-id',required=True);ap.add_argument('--out',required=True);ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();print(json.dumps(deploy(args.queue,args.run_id,args.out,args.resume)))
