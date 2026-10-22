"""Immutable staged official trial cards; preparation reads disk only."""
from datetime import datetime,timezone,timedelta
import secrets
from pathlib import Path
import acceptance_build as a
from contract import read,write,sha,require
from control_contract import OPERATIONS,origin_matches,trial_matches
ROOT,HERE,OUTPUT,p,ro=a.ROOT,a.HERE,a.OUTPUT,a.p,a.ro
OWN=('native_control.h','native_control.cpp','control_build.py','control_contract.py','control_receipt.py','control-profile.json','control_flow.py')
PROOF_NAMES=('prepared.json','build-result.json','exit.json','stdout.jsonl','acceptance.bin')
MAX_CHAIN=64

def previous(value,session,level,operation):
    """Re-decode every ancestor binary; never trust only a result.json summary."""
    from receipt import manifest,decode
    run,card,_=manifest(value)
    require(card['kind']=='playtest-control-prepared-v3' and card['session']==session and card['targetLevelId']==level,'PREVIOUS_CARD_TARGET')
    lineage=card.get('lineage') or dict(rootRun=str(run),ancestors=[],attemptedOperations=[])
    ancestors=lineage['ancestors'];require(len(ancestors)<MAX_CHAIN,'CONTROL_CHAIN_LIMIT')
    require(len({x['run'] for x in ancestors})==len(ancestors) and str(run) not in {x['run'] for x in ancestors},'CONTROL_CHAIN_CYCLE')
    all_records=[]
    for proof in ancestors+[dict(run=str(run),hashes={n:sha(run/n) for n in PROOF_NAMES})]:
        at=Path(proof['run']);require(set(proof['hashes'])==set(PROOF_NAMES),'CONTROL_PROOF_SHAPE')
        for name,digest in proof['hashes'].items():require(sha(at/name)==digest,'CONTROL_ANCESTOR_CHANGED')
        _,past,_=manifest(at);require(past['kind']=='playtest-control-prepared-v3' and past['session']==session and past['targetLevelId']==level,'CONTROL_ANCESTOR_TARGET')
        result=decode(at);require(result.get('ok') is True and result.get('safeToRelease') is True and result.get('outcomeUncertain') is False,'CONTROL_ANCESTOR_INCOMPLETE')
        all_records.append((past,result,proof))
    require(all_records and all_records[0][0]['mode']=='enter-request' and all_records[0][0]['run']==lineage['rootRun'],'CONTROL_ROOT_REQUEST')
    attempted=[c['mode'] for c,r,_ in all_records if r.get('actionAttempted')]
    require(attempted[0:1]==['enter-request'] and len(attempted)==len(set(attempted)),'CONTROL_MUTATION_REPLAY')
    require([x for x in ('enter-request','enter-start','exit-request','exit-return') if x in attempted]==attempted,'CONTROL_MUTATION_ORDER')
    # Every ancestor's own ordered proof prefix must match this chain.
    for i,(past,_,proof) in enumerate(all_records):
        require(past.get('lineage',{}).get('ancestors',[])==[x[2] for x in all_records[:i]],'CONTROL_ANCESTOR_PREFIX')
    current=all_records[-1][1];state=current['trialState'];initial=all_records[0][1]['nativeReceipt']['before']
    binding=dict(global_=initial['global'],editor=initial['editor'],task=initial['task'],initialToken=initial['token'],initialData=initial['cacheEditData'],initialSettleData=initial['settleData'])
    binding['global']=binding.pop('global_')
    existing=card.get('binding',{})
    for key in ('token','cache','cacheEditData','exitSettleBefore'):binding[key]=existing.get(key,0)
    require(origin_matches(state,binding),'CONTROL_ORIGIN_CHANGED')
    if operation in ('enter-start','exit-request','exit-return'):require(operation not in attempted,'CONTROL_ACTION_ALREADY_ATTEMPTED')
    if operation=='enter-start':
        require(attempted==['enter-request'] and current['nativeReceipt']['stateStable']==1 and state['entryReady']==1,'ENTRY_NOT_READY')
        require(state['token'] and state['token']!=binding['initialToken'] and state['cacheEditData']!=binding['initialData'],'ENTRY_FRESH_TOKEN_AND_EXPORT_REQUIRED')
        binding.update(token=state['token'],cache=state['cache'],cacheEditData=state['cacheEditData'])
    if operation=='exit-request':
        require(attempted==['enter-request','enter-start'] and current['mode']=='play' and current['trialIdentityBound'] is True,'EXIT_REQUIRES_BOUND_TRIAL')
        binding['exitSettleBefore']=state['settleData']
    if operation=='trial-frame':require('enter-start' in attempted and 'exit-request' not in attempted and current['mode']=='play' and current['trialIdentityBound'] is True,'FRAME_REQUIRES_BOUND_TRIAL')
    if operation=='exit-return':
        require(attempted==['enter-request','enter-start','exit-request'] and current['mode']=='settlement' and current['trialIdentityBound'] is True,'RETURN_REQUIRES_BOUND_SETTLEMENT')
        require(state['settleData'] not in (binding['initialSettleData'],binding['exitSettleBefore']),'RETURN_REQUIRES_FRESH_SETTLEMENT')
        binding.update(settleContext=state['settleContext'],settleData=state['settleData'])
    if operation!='trial-state' and 'enter-start' in attempted and current['mode'] not in ('editor','transition'):
        require(trial_matches(state,binding),'CONTROL_TRIAL_IDENTITY_CHANGED')
    return dict(rootRun=lineage['rootRun'],ancestors=[x[2] for x in all_records],attemptedOperations=attempted),binding

def claim_write(run,card):
    """One write per stage across all cards derived from the same entry root."""
    if card['mode'] in ('trial-state','trial-frame'):return
    root=run if card['mode']=='enter-request' else Path(card['lineage']['rootRun'])
    write(root/('control-'+card['mode']+'.claim'),dict(run=str(run),preparedSha256=sha(run/'prepared.json'),atUtc=datetime.now(timezone.utc).isoformat(),automaticReplayForbidden=True))

def copy_sources(run):
    hashes=a.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h'
    text=protocol.read_text(encoding='utf-8').replace('native_acceptance.h','native_control.h').replace('AcceptanceReceipt','ControlReceipt');protocol.write_text(text,encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=hook.read_text(encoding='utf-8');text=a.legacy.replace(text,'ExecuteAcceptance(&receipt->acceptance);','ExecuteControl(&receipt->acceptance);');hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp';text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_ACCEPTANCE','FIXED_PLAYTEST_CONTROL');probe.write_text(text,encoding='utf-8')
    # The fixed compiler input is a private, hash-recorded generated copy.
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_control.cpp').read_bytes())
    return hashes

def prepare(args,*,compile_only=False):
    operation=args.operation;require(operation in OPERATIONS,'CONTROL_OPERATION')
    require(getattr(args,'page_start',0)==0,'CONTROL_HAS_NO_ENTITY_PAGE')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');extra=read(HERE/'control-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==extra['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256']==extra['metadataSha256'],'RUNTIME_SOURCE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
    lineage={};binding={};prior=getattr(args,'previous_run',None)
    if not compile_only:
        if operation=='enter-request':require(prior is None,'INITIAL_REQUEST_HAS_NO_PREVIOUS_CARD')
        else:
            require(prior is not None,'CONTROL_PREVIOUS_RECEIPT_REQUIRED');lineage,binding=previous(prior,session,level,operation)
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.TrialControl.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define CONTROL_OPERATION '+str(OPERATIONS[operation])+'U\n'
    for prefix,data in [('PLAY',runtime),('CONTROL',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
        text+=f'#define {prefix}_HOTFIX_RVAS '+','.join(data['hotfixZeroRvas'])+'\n'
    fields={'GLOBAL':'global','EDITOR':'editor','TASK':'task','TOKEN':'token','CACHE':'cache','DATA':'cacheEditData','INITIAL_TOKEN':'initialToken','INITIAL_DATA':'initialData','INITIAL_SETTLE':'initialSettleData','EXIT_SETTLE':'exitSettleBefore','SETTLE_CONTEXT':'settleContext','SETTLE_DATA':'settleData'}
    for macro,key in fields.items():text+=f'#define CONTROL_{macro} {binding.get(key,0)}ULL\n'
    header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/control_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    if lineage:
        for proof in lineage['ancestors']:
            for name,digest in proof['hashes'].items():require(sha(Path(proof['run'])/name)==digest,'ANCESTOR_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v3',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=0,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],lineage=lineage,binding=binding)
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        for proof in lineage.get('ancestors',[]):pins.update({str(Path(proof['run'])/name):digest for name,digest in proof['hashes'].items()})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_CONTROL').replace('playtest-control-build-v1','playtest-control-build-v3').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v3',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='trial-state',changesTrialMode=operation not in ('trial-state','trial-frame'),mutatesTemporaryRenderResources=operation=='trial-frame',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
