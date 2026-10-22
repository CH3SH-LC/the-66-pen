"""Fixed deferred frame capture; no process mutation during preparation."""
from datetime import datetime,timezone,timedelta
import secrets
from pathlib import Path
import acceptance_build as a
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=a.ROOT,a.HERE,a.OUTPUT,a.p,a.ro
OWN=('native_scene_frame.h','native_scene_frame.cpp','scene_frame_build.py','scene_frame_receipt.py','scene-frame-profile.json')
OPERATIONS={'scene-frame':1,'scene-overview':2,'scene-cleanup-state':3}
def copy_sources(run):
    hashes=a.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_scene_frame.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h'
    protocol.write_text(protocol.read_text(encoding='utf-8').replace('native_acceptance.h','native_scene_frame.h').replace('AcceptanceReceipt','SceneFrameReceipt'),encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=hook.read_text(encoding='utf-8')
    for old,new in [
        ('if (InterlockedCompareExchange(&receipt->claim, 1, 0) == 0) {','if (InterlockedCompareExchange(&receipt->claim,3,0)==0 || InterlockedCompareExchange(&receipt->claim,3,1)==1) {'),
        ('ExecuteAcceptance(&receipt->acceptance);','const bool sceneDone=StepSceneFrame(&receipt->acceptance);'),
        ('InterlockedExchange(&receipt->claim, 2);','InterlockedExchange(&receipt->claim,sceneDone?2:1);'),
        ('receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID) {','receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID && InterlockedCompareExchange(&receipt->claim,0,0)<2) {')]:
        text=a.legacy.replace(text,old,new)
    hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp'
    text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_ACCEPTANCE','FIXED_PLAYTEST_SCENE_FRAME')
    text=a.legacy.replace(text,'while (posted && InterlockedCompareExchange(&receipt->claim, 0, 0) != 2 && GetTickCount64() < waitDeadline && GetTickCount64() <= HR_DEADLINE) Sleep(10);',
        '''while (posted && InterlockedCompareExchange(&receipt->claim,0,0)!=2 && GetTickCount64()<waitDeadline && GetTickCount64()<=HR_DEADLINE) {
            Sleep(16);
            if(InterlockedCompareExchange(&receipt->claim,0,0)!=2 && !PostThreadMessageW(HR_TARGET_TID,HR_MESSAGE_ID,HR_NONCE,1))break;
        }''')
    text=a.legacy.replace(text,'!continued || receipt->callbacks != 1','!continued || receipt->callbacks<1 || receipt->callbacks>4096 || receipt->callbacks!=static_cast<LONG>(receipt->acceptance.callbacks)')
    probe.write_text(text,encoding='utf-8')
    return hashes
def prepare(args,*,compile_only=False):
    operation=args.operation;require(operation in OPERATIONS and args.page_start==0,'SCENE_FRAME_OPERATION')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');extra=read(HERE/'scene-frame-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==extra['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256']==extra['metadataSha256'],'SCENE_FRAME_SOURCE_DRIFT')
    level=1 if compile_only else args.target_level
    require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    require(operation!='scene-overview' or compile_only or level==1073741845,'OVERVIEW_PRESET_ONLY_FOR_MONDSTADT_1845')
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session)
        require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE')
        require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
    previous=None
    if operation=='scene-cleanup-state' and not compile_only:
        from receipt import manifest
        from scene_frame_receipt import decode_bound
        prior_run,prior_card,_=manifest(args.previous_run)
        require(prior_card['kind']=='playtest-control-prepared-v11' and prior_card['mode'] in ('scene-frame','scene-overview'),'PREVIOUS_CAPTURE_REQUIRED')
        proof=decode_bound(prior_run,prior_card);native=proof['nativeReceipt'];transport=read(prior_run/'stdout.jsonl')
        require(prior_card['session']==session and prior_card['targetLevelId']==level,'PREVIOUS_SESSION_CHANGED')
        require(transport['unhooked'] is True and transport['activeCallbacks']==0 and transport['transportOk'] is True,'PREVIOUS_CALLBACK_NOT_TERMINAL')
        require(native['seh']==native['guardStatus']==0 and native['stage']==3 and
                native['destroyQueued']==native['handleReleased']==native['cameraRestored']==1 and
                native['texture'] and native['handle'],'PREVIOUS_RESOURCE_NOT_RELEASE_PENDING')
        previous=dict(run=str(prior_run),texture=native['texture'],cachedBefore=native['cachedBefore'],
                      handle=native['handle'],frameBefore=native['frameBefore'],
                      evidence={str(prior_run/n):sha(prior_run/n) for n in ('prepared.json','acceptance.bin','stdout.jsonl','exit.json')})
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if previous:hashes.update(previous['evidence'])
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000
        message=int(user.RegisterWindowMessageW('Miliastra.SceneFrame.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_SCENE_FRAME_REVIEWED 1\n'
    text+=f'#define PLAY_TARGET_LEVEL {level}U\n#define SCENE_OPERATION {OPERATIONS[operation]}U\n'
    if previous:
        for key,name in [('texture','TEXTURE'),('cachedBefore','CACHED'),('handle','HANDLE'),('frameBefore','FRAME')]:
            text+=f'#define SCENE_PREVIOUS_{name} {previous[key]}ULL\n'
    for prefix,data in [('PLAY',runtime),('SCENE',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
    text+='#define PLAY_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n';header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/scene_frame_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v11',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=0,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'])
    if previous:card['previousCapture']=previous
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_SCENE_FRAME').replace('playtest-control-build-v1','playtest-control-build-v11').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v11',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='scene-cleanup-state',changesTrialMode=False,mutatesTemporaryRenderResources=operation!='scene-cleanup-state',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
