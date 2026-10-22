"""Immutable targeted menu callback cards. Preparation reads disk only."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import secrets,struct
from types import SimpleNamespace
import directory_build as d
from targeted_contract import plan,selected
import control_build as c
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=c.ROOT,c.HERE,c.OUTPUT,c.p,c.ro
OWN=('native_targeted.h','native_targeted.cpp','targeted_build.py','targeted_contract.py','targeted_receipt.py','targeted-profile.json')

def validate_card(card):
    require(card['mode']=='targeted-interact' and card['pageStart']==0,'TARGETED_CARD_MODE')
    p=card['targetPlan'];require(set(p)=={'targetId','editorGuid','runtimeId','optionIndex','label'},'TARGETED_PLAN_FIELDS')
    require(plan(SimpleNamespace(operation=card['mode'],target_id=p['targetId'],expected_editor_guid=p['editorGuid'],expected_runtime_id=p['runtimeId'],option_index=p['optionIndex'],label=p['label']))==p,'TARGETED_PLAN')
    if card['compileOnly']:require(not card['launchable'] and not card['lineage'] and not card['targetBaseline'],'TARGETED_COMPILE_ONLY');return
    require(card['anchorRun'] and card['lineage']['ancestors'] and card['lineage']['ancestors'][-1]['run']==card['anchorRun'],'TARGETED_ANCHOR')
    require('enter-start' in card['lineage']['attemptedOperations'] and 'exit-request' not in card['lineage']['attemptedOperations'],'TARGETED_ENTERED_LINEAGE')
    require(set(card['targetBinding'])=={'optionHex','avatar','avatarId','mainContext','view'} and len(bytes.fromhex(card['targetBinding']['optionHex']))==496,'TARGETED_BINDING')
    require(card['targetBaseline'] and set(card['targetBaseline']['hashes'])==set(c.PROOF_NAMES),'TARGETED_PROOF')

def baseline(value,anchor,session,level,requested):
    from receipt import manifest,decode
    from directory_contract import CONTACT_OFFSET
    from contact_contract import SAMPLES_OFFSET,OPTIONS_AT,OPTION_SIZE
    run,card,_=manifest(value);require(card['kind']=='playtest-control-prepared-v9' and card['mode']=='trial-entities' and card['anchorRun']==str(anchor) and card['session']==session and card['targetLevelId']==level,'TARGETED_BASELINE_TARGET')
    result=decode(run);row=selected(result,requested);raw=(run/'acceptance.bin').read_bytes();at=CONTACT_OFFSET+SAMPLES_OFFSET+OPTIONS_AT+requested['optionIndex']*OPTION_SIZE
    native=result['nativeReceipt']['contact'];state=native['control']['observation']['after'];s=native['first']
    binding=dict(optionHex=raw[at:at+OPTION_SIZE].hex(),avatar=state['avatar'],avatarId=state['avatarId'],mainContext=s['mainContext'],view=s['view'])
    return binding,dict(run=str(run),hashes={n:sha(run/n) for n in c.PROOF_NAMES})

def revalidate_proofs(card):
    lineage,binding=c.previous(card['anchorRun'],card['session'],card['targetLevelId'],'trial-frame')
    require(lineage==card['lineage'] and binding==card['binding'],'TARGETED_ANCHOR_CHANGED')
    values,proof=baseline(card['targetBaseline']['run'],card['anchorRun'],card['session'],card['targetLevelId'],card['targetPlan'])
    require(values==card['targetBinding'] and proof==card['targetBaseline'],'TARGETED_BASELINE_CHANGED')

def claim_write(run,card):
    write(Path(card['lineage']['rootRun'])/('targeted-'+card['targetPlan']['targetId']+'.claim'),dict(run=str(run),preparedSha256=sha(run/'prepared.json'),atUtc=datetime.now(timezone.utc).isoformat(),automaticReplayForbidden=True))

def copy_sources(run):
    hashes=d.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_targeted.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h';text=protocol.read_text(encoding='utf-8').replace('native_directory.h','native_targeted.h').replace('DirectoryReceipt','TargetedReceipt');protocol.write_text(text,encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=c.a.legacy.replace(hook.read_text(encoding='utf-8'),'ExecuteDirectory(&receipt->acceptance);','ExecuteTargeted(&receipt->acceptance);');hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp';text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_DIRECTORY','FIXED_PLAYTEST_TARGETED');probe.write_text(text,encoding='utf-8');return hashes

def prepare(args,*,compile_only=False):
    require(args.operation=='targeted-interact','TARGETED_OPERATION');page=getattr(args,'page_start',0);require(page==0,'TARGETED_HAS_NO_PAGE')
    if compile_only:
        args=SimpleNamespace(operation='targeted-interact',target_id='compile-only',expected_editor_guid=1002,expected_runtime_id=10,option_index=0,label='测试交互')
    requested=plan(args)
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');control=read(HERE/'control-profile.json');extra=read(HERE/'directory-profile.json');contact=read(HERE/'contact-profile.json');targeted=read(HERE/'targeted-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(all(x['imageSha256']==profile['image']['sha256'] and x['metadataSha256']==sha(metadata) for x in (runtime,control,extra,contact,targeted)),'TARGETED_PROFILE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    binding={};lineage={};anchor=None;target_binding={};proof=None
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'));target_binding=dict(optionHex='00'*496,avatar=0,avatarId=0,mainContext=0,view=0)
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
        require(args.previous_run is not None,'PROVEN_TRIAL_ANCHOR_REQUIRED');anchor=Path(args.previous_run).resolve();lineage,binding=c.previous(anchor,session,level,'trial-frame')
        require(args.target_baseline is not None,'TARGETED_BASELINE_REQUIRED');target_binding,proof=baseline(args.target_baseline,anchor,session,level,requested)
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.TargetedInteraction.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce);header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=c.a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define CONTROL_OPERATION 3U\n#define DIRECTORY_OPERATION 18U\n#define CONTACT_OPERATION 17U\n#define CONTACT_PAGE_START '+str(page)+'U\n'
    for prefix,data in [('PLAY',runtime),('CONTROL',control),('CONTACT',contact),('DIRECTORY',extra),('TARGETED',targeted)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
        text+=f'#define {prefix}_HOTFIX_RVAS '+','.join(data['hotfixZeroRvas'])+'\n'
    fields={'GLOBAL':'global','EDITOR':'editor','TASK':'task','TOKEN':'token','CACHE':'cache','DATA':'cacheEditData','INITIAL_TOKEN':'initialToken','INITIAL_DATA':'initialData','INITIAL_SETTLE':'initialSettleData','EXIT_SETTLE':'exitSettleBefore','SETTLE_CONTEXT':'settleContext','SETTLE_DATA':'settleData'}
    for macro,key in fields.items():text+=f'#define CONTROL_{macro} {binding.get(key,0)}ULL\n'
    text+='\n#define TARGETED_OPERATION 19U\n#define TARGETED_GUID '+str(requested['editorGuid'])+'U\n#define TARGETED_RUNTIME_ID '+str(requested['runtimeId'])+'U\n#define TARGETED_OPTION '+str(requested['optionIndex'])+'U\n#define TARGETED_OPTION_BYTES '+','.join(str(x) for x in bytes.fromhex(target_binding['optionHex']))+'\n'
    for macro,key in [('AVATAR','avatar'),('AVATAR_ID','avatarId'),('CONTEXT','mainContext'),('VIEW','view')]:text+=f'#define TARGETED_{macro} {target_binding[key]}ULL\n'
    header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/targeted_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    c.a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    proofs=lineage.get('ancestors',[])+([proof] if proof else [])
    for record in proofs:
        for name,digest in record['hashes'].items():require(sha(Path(record['run'])/name)==digest,'TARGETED_PROOF_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v10',run=str(run),action=19,receiptVersion=24,mode='targeted-interact',pageStart=page,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],lineage=lineage,binding=binding,anchorRun=str(anchor) if anchor else None,targetPlan=requested,targetBinding=target_binding,targetBaseline=proof)
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        for record in proofs:pins.update({str(Path(record['run'])/name):digest for name,digest in record['hashes'].items()})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_TARGETED').replace('playtest-control-build-v1','playtest-control-build-v10').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v10',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode='targeted-interact',readOnly=False,changesTrialMode=False,mutatesTemporaryRenderResources=False,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
