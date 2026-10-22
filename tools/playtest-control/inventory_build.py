"""Immutable trial-bound read-only inventory cards. Preparation reads disk only."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import secrets
import control_build as c
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=c.ROOT,c.HERE,c.OUTPUT,c.p,c.ro
OWN=('native_inventory.h','native_inventory.cpp','inventory_build.py','inventory_contract.py','inventory_receipt.py','inventory_diff.py','inventory-profile.json')

def validate_card(card):
    require(card['mode']=='inventory-state' and type(card['pageStart']) is int and card['pageStart']==0,'INVENTORY_PLAN')
    if card['compileOnly']:require(not card['launchable'] and not card['lineage'] and not card['binding'] and card['anchorRun'] is None,'INVENTORY_COMPILE_ONLY');return
    require(card['anchorRun'] and card['lineage']['ancestors'] and card['lineage']['ancestors'][-1]['run']==card['anchorRun'],'INVENTORY_ANCHOR_SHAPE')
    require('enter-start' in card['lineage']['attemptedOperations'] and 'exit-request' not in card['lineage']['attemptedOperations'],'INVENTORY_ENTERED_LINEAGE')

def revalidate_proofs(card):
    lineage,binding=c.previous(card['anchorRun'],card['session'],card['targetLevelId'],'trial-frame')
    require(lineage==card['lineage'] and binding==card['binding'],'INVENTORY_ANCHOR_CHANGED')

def copy_sources(run):
    hashes=c.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_inventory.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h';text=protocol.read_text(encoding='utf-8').replace('native_control.h','native_inventory.h').replace('ControlReceipt','InventoryReceipt');protocol.write_text(text,encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=c.a.legacy.replace(hook.read_text(encoding='utf-8'),'ExecuteControl(&receipt->acceptance);','ExecuteInventory(&receipt->acceptance);');hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp';text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_CONTROL','FIXED_PLAYTEST_INVENTORY');probe.write_text(text,encoding='utf-8');return hashes

def prepare(args,*,compile_only=False):
    require(args.operation=='inventory-state','INVENTORY_OPERATION');page=getattr(args,'page_start',0);require(type(page) is int and page==0,'INVENTORY_PAGE_RANGE')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');control=read(HERE/'control-profile.json');extra=read(HERE/'inventory-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(all(x['imageSha256']==profile['image']['sha256'] and x['metadataSha256']==sha(metadata) for x in (runtime,control,extra)),'INVENTORY_PROFILE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    binding={};lineage={};anchor=None
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
        require(args.previous_run is not None,'PROVEN_TRIAL_ANCHOR_REQUIRED');anchor=Path(args.previous_run).resolve();lineage,binding=c.previous(anchor,session,level,'trial-frame')
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.RuntimeInventory.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce);header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=c.a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define CONTROL_OPERATION 3U\n#define INVENTORY_OPERATION 14U\n'
    for prefix,data in [('PLAY',runtime),('CONTROL',control),('INVENTORY',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
        text+=f'#define {prefix}_HOTFIX_RVAS '+','.join(data['hotfixZeroRvas'])+'\n'
    fields={'GLOBAL':'global','EDITOR':'editor','TASK':'task','TOKEN':'token','CACHE':'cache','DATA':'cacheEditData','INITIAL_TOKEN':'initialToken','INITIAL_DATA':'initialData','INITIAL_SETTLE':'initialSettleData','EXIT_SETTLE':'exitSettleBefore','SETTLE_CONTEXT':'settleContext','SETTLE_DATA':'settleData'}
    for macro,key in fields.items():text+=f'#define CONTROL_{macro} {binding.get(key,0)}ULL\n'
    header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/inventory_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    c.a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    for proof in lineage.get('ancestors',[]):
        for name,digest in proof['hashes'].items():require(sha(Path(proof['run'])/name)==digest,'INVENTORY_PROOF_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v6',run=str(run),action=19,receiptVersion=24,mode='inventory-state',pageStart=page,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],lineage=lineage,binding=binding,anchorRun=str(anchor) if anchor else None)
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        for proof in lineage['ancestors']:pins.update({str(Path(proof['run'])/name):digest for name,digest in proof['hashes'].items()})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_INVENTORY').replace('playtest-control-build-v1','playtest-control-build-v6').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v6',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode='inventory-state',readOnly=True,changesTrialMode=False,mutatesTemporaryRenderResources=False,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
