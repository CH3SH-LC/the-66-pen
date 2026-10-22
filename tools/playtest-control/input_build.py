"""Fixed native input card; immutable plans and an existing proven trial anchor."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import secrets,struct,subprocess
from types import SimpleNamespace
import control_build as c
from contract import read,write,sha,require
from input_contract import OPERATIONS,plan
ROOT,HERE,OUTPUT,p,ro=c.ROOT,c.HERE,c.OUTPUT,c.p,c.ro
OWN=('native_input.h','native_input.cpp','input_build.py','input_contract.py','input_receipt.py','input-profile.json')
def validate_card(card):
    p=card['inputPlan'];require(set(p)=={'inputId','angle','strength','durationMs','maxDistance','label','optionIndex'},'INPUT_PLAN_FIELDS')
    requested=plan(SimpleNamespace(operation=card['mode'],input_id=p['inputId'],angle=p['angle'],strength=p['strength'],duration_ms=p['durationMs'],max_distance=p['maxDistance'],label=p['label'],option_index=p['optionIndex']))
    require(p==requested,'INPUT_PLAN_CONTRACT')
    if card['compileOnly']:require(not card['launchable'] and not card['lineage'] and not card['inputBaseline'],'INPUT_COMPILE_ONLY');return
    require(card['anchorRun'] and card['lineage']['ancestors'] and card['lineage']['ancestors'][-1]['run']==card['anchorRun'],'INPUT_ANCHOR_SHAPE')
    require('enter-start' in card['lineage']['attemptedOperations'] and 'exit-request' not in card['lineage']['attemptedOperations'],'INPUT_ENTERED_LINEAGE')
    if card['mode']=='input-state':require(not card['inputBinding'] and card['inputBaseline'] is None,'INPUT_READ_ONLY_PLAN')
    else:
        require(card['inputBaseline'] and set(card['inputBaseline']['hashes'])==set(c.PROOF_NAMES),'INPUT_BASELINE_PROOF')
        require(all(type(card['inputBinding'][k]) is int and card['inputBinding'][k]>0 for k in ('avatar','avatarId','component','mainContext','view')),'INPUT_BINDING_SHAPE')
def revalidate_proofs(card):
    lineage,binding=c.previous(card['anchorRun'],card['session'],card['targetLevelId'],'trial-frame')
    require(lineage==card['lineage'] and binding==card['binding'],'INPUT_ANCHOR_CHANGED')
    if card['inputBaseline']:
        values,proof=baseline(card['inputBaseline']['run'],card['anchorRun'],card['session'],card['targetLevelId'],card['mode'],card['inputPlan'])
        require(values==card['inputBinding'] and proof==card['inputBaseline'],'INPUT_BASELINE_CHANGED')
def baseline(value,anchor,session,level,operation,requested):
    from receipt import manifest,decode
    at,card,_=manifest(value);require(card['kind']=='playtest-control-prepared-v4' and card['mode']=='input-state' and card['anchorRun']==str(anchor) and card['session']==session and card['targetLevelId']==level,'INPUT_BASELINE_TARGET')
    result=decode(at);require(result.get('ok') is True and result.get('safeToRelease') is True and result.get('trialIdentityBound') is True,'INPUT_BASELINE_NOT_CLEAN')
    native=result['nativeReceipt'];binding={k:native[k] for k in ('avatar','avatarId','component','mainContext','view','button','attackSlot')}
    if operation=='move-pulse':require(native['sourceIdle']==1,'EXISTING_INPUT_SOURCE_ACTIVE')
    if operation=='attack-tap':require(result['attackAvailable'] is True and native['attackAction']==0x167,'ATTACK_MAPPING_UNAVAILABLE')
    if operation=='interact-option':
        require(result['optionsComplete'] is True and requested['optionIndex']<len(result['options']),'OPTION_LIST_INCOMPLETE')
        row=result['options'][requested['optionIndex']];require(row['active'] and row['enabled'] and row['text']==requested['label'],'OPTION_NOT_CURRENTLY_AVAILABLE')
        binding.update(item=row['item'],button=row['button'])
    return binding,dict(run=str(at),hashes={n:sha(at/n) for n in c.PROOF_NAMES})
def claim_write(run,card):
    if card['mode']=='input-state':return
    root=Path(card['lineage']['rootRun']);write(root/('input-'+card['inputPlan']['inputId']+'.claim'),dict(run=str(run),preparedSha256=sha(run/'prepared.json'),atUtc=datetime.now(timezone.utc).isoformat(),automaticReplayForbidden=True))
def copy_sources(run):
    hashes=c.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_input.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h';text=protocol.read_text(encoding='utf-8').replace('native_control.h','native_input.h').replace('ControlReceipt','InputReceipt');protocol.write_text(text,encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=hook.read_text(encoding='utf-8')
    text=c.a.legacy.replace(text,'if (InterlockedCompareExchange(&receipt->claim, 1, 0) == 0) {','if (InterlockedCompareExchange(&receipt->claim,3,0)==0 || InterlockedCompareExchange(&receipt->claim,3,1)==1) {')
    text=c.a.legacy.replace(text,'ExecuteControl(&receipt->acceptance);','const bool inputDone=StepInput(&receipt->acceptance);')
    text=c.a.legacy.replace(text,'InterlockedExchange(&receipt->claim, 2);','InterlockedExchange(&receipt->claim,inputDone?2:1);')
    # A message queued immediately before completion must not inflate either
    # callback counter after the terminal receipt has been committed.
    text=c.a.legacy.replace(text,'receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID) {','receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID &&\n                InterlockedCompareExchange(&receipt->claim,0,0)<2) {')
    hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp';text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_CONTROL','FIXED_PLAYTEST_INPUT')
    old='while (posted && InterlockedCompareExchange(&receipt->claim, 0, 0) != 2 && GetTickCount64() < waitDeadline && GetTickCount64() <= HR_DEADLINE) Sleep(10);'
    new='''while (posted && InterlockedCompareExchange(&receipt->claim, 0, 0) != 2 && GetTickCount64() < waitDeadline && GetTickCount64() <= HR_DEADLINE) {
                Sleep(16);
                if(InterlockedCompareExchange(&receipt->claim,0,0)!=2 && !PostThreadMessageW(HR_TARGET_TID,HR_MESSAGE_ID,HR_NONCE,1)) break;
            }'''
    text=c.a.legacy.replace(text,old,new)
    text=c.a.legacy.replace(text,'!continued || receipt->callbacks != 1','!continued || receipt->callbacks<1 || receipt->callbacks>4096 || receipt->callbacks!=static_cast<LONG>(receipt->acceptance.callbacks)')
    probe.write_text(text,encoding='utf-8');return hashes
def compile_pipeline_fixture(run):
    lines=(run/'build.cmd').read_text(encoding='utf-8').splitlines()
    command=next(x for x in lines if 'acceptance_fixture.cpp' in x)
    command=command.replace('acceptance_fixture.cpp','input_pipeline_fixture.cpp').replace('fixture.obj','pipeline-fixture.obj').replace('acceptance_fixture.exe','input_pipeline_fixture.exe')+' /link User32.lib'
    batch=run/'pipeline-build.cmd';batch.write_text('\n'.join(lines[:3]+[command,'if errorlevel 1 exit /b 1','exit /b 0'])+'\n',encoding='utf-8')
    result=subprocess.run(['cmd.exe','/d','/c',str(batch)],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'pipeline-build.log').write_text((result.stdout or '')+(result.stderr or ''),encoding='utf-8');require(result.returncode==0,'PIPELINE_BUILD_FAILED:'+str(run/'pipeline-build.log'))
def prepare(args,*,compile_only=False):
    operation=args.operation;requested=plan(args);require(getattr(args,'page_start',0)==0,'INPUT_HAS_NO_ENTITY_PAGE')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');control=read(HERE/'control-profile.json');extra=read(HERE/'input-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(all(x['imageSha256']==profile['image']['sha256'] and x['metadataSha256']==sha(metadata) for x in (runtime,control,extra)),'INPUT_PROFILE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    binding={};input_binding={};lineage={};proof=None;anchor=None
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
        anchor=args.previous_run;require(anchor is not None,'PROVEN_TRIAL_ANCHOR_REQUIRED');anchor=Path(anchor).resolve()
        lineage,binding=c.previous(anchor,session,level,'trial-frame')
        if operation=='input-state':require(getattr(args,'input_baseline',None) is None,'INPUT_STATE_HAS_NO_BASELINE')
        else:
            require(getattr(args,'input_baseline',None) is not None,'INPUT_BASELINE_REQUIRED');input_binding,proof=baseline(args.input_baseline,anchor,session,level,operation,requested)
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.NativeInput.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce);header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=c.a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define CONTROL_OPERATION 3U\n#define INPUT_OPERATION '+str(OPERATIONS[operation])+'U\n'
    for prefix,data in [('PLAY',runtime),('CONTROL',control),('INPUT',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
        text+=f'#define {prefix}_HOTFIX_RVAS '+','.join(data['hotfixZeroRvas'])+'\n'
    fields={'GLOBAL':'global','EDITOR':'editor','TASK':'task','TOKEN':'token','CACHE':'cache','DATA':'cacheEditData','INITIAL_TOKEN':'initialToken','INITIAL_DATA':'initialData','INITIAL_SETTLE':'initialSettleData','EXIT_SETTLE':'exitSettleBefore','SETTLE_CONTEXT':'settleContext','SETTLE_DATA':'settleData'}
    for macro,key in fields.items():text+=f'#define CONTROL_{macro} {binding.get(key,0)}ULL\n'
    for macro,key in {'AVATAR':'avatar','AVATAR_ID':'avatarId','COMPONENT':'component','CONTEXT':'mainContext','VIEW':'view','BUTTON':'button','SLOT':'attackSlot','ITEM':'item'}.items():text+=f'#define INPUT_{macro} {input_binding.get(key,0)}ULL\n'
    for macro,key in [('ANGLE','angle'),('STRENGTH','strength'),('MAX_DISTANCE','maxDistance')]:text+=f'#define INPUT_{macro} {requested[key]:.9f}f\n'
    label=(requested['label'] or '').encode('utf-16-le');chars=struct.unpack('<'+'H'*(len(label)//2),label)
    text+=f'#define INPUT_DURATION_MS {requested["durationMs"]}ULL\n#define INPUT_OPTION {requested["optionIndex"] or 0}U\n#define INPUT_LABEL_LENGTH {len(chars)}U\n#define INPUT_LABEL_UTF16 '+','.join(str(x) for x in (*chars,0))+'\n'
    header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/input_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
        pipeline=HERE/'tests/input_pipeline_fixture.cpp';hashes[str(pipeline)]=sha(pipeline);(run/'candidate-source/playtest-control/input_pipeline_fixture.cpp').write_bytes(pipeline.read_bytes())
    c.a.compile_card(run,fixture=compile_only)
    if compile_only:compile_pipeline_fixture(run)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    proofs=lineage.get('ancestors',[])+([proof] if proof else [])
    for record in proofs:
        for name,digest in record['hashes'].items():require(sha(Path(record['run'])/name)==digest,'INPUT_PROOF_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v4',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=0,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],lineage=lineage,binding=binding,anchorRun=str(anchor) if anchor else None,inputBinding=input_binding,inputBaseline=proof,inputPlan=requested)
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        for record in proofs:pins.update({str(Path(record['run'])/name):digest for name,digest in record['hashes'].items()})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_INPUT').replace('playtest-control-build-v1','playtest-control-build-v4').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v4',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='input-state',changesTrialMode=False,mutatesTemporaryRenderResources=False,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
