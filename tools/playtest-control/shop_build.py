"""Immutable trial-bound native shop UI cards. Preparation reads disk only."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
import secrets
from types import SimpleNamespace
from shop_contract import OPERATIONS,ACTIONS,plan,validate_selection,UI_SIZE
import control_build as c
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=c.ROOT,c.HERE,c.OUTPUT,c.p,c.ro
OWN=('native_shop.h','native_shop.cpp','shop_build.py','shop_contract.py','shop_receipt.py','shop-profile.json')
def validate_card(card):
    p=card['uiPlan'];require(set(p)=={'action','id','row','configId','label'},'SHOP_PLAN_FIELDS')
    requested=plan(SimpleNamespace(operation=card['mode'],ui_action=p['action'],ui_id=p['id'],ui_row=p['row'],config_id=p['configId'],label=p['label']))
    require(requested==p and card['pageStart']==0,'SHOP_PLAN_CONTRACT')
    if card['compileOnly']:require(not card['launchable'] and not card['lineage'] and not card['uiBaseline'],'SHOP_COMPILE_ONLY');return
    require(card['anchorRun'] and card['lineage']['ancestors'][-1]['run']==card['anchorRun'],'SHOP_ANCHOR')
    require('enter-start' in card['lineage']['attemptedOperations'] and 'exit-request' not in card['lineage']['attemptedOperations'],'SHOP_ENTERED_LINEAGE')
    if card['mode']=='shop-state':require(card['uiBaseline'] is None and not card['uiBinding'],'SHOP_STATE_BINDING')
    else:require(card['uiBaseline'] and set(card['uiBaseline']['hashes'])==set(c.PROOF_NAMES) and len(bytes.fromhex(card['uiBinding']['uiBytesHex']))==UI_SIZE,'SHOP_BASELINE_SHAPE')
def baseline(value,anchor,session,level,requested):
    from receipt import manifest,decode
    at,card,_=manifest(value);require(card['kind']=='playtest-control-prepared-v7' and card['mode']=='shop-state' and card['anchorRun']==str(anchor) and card['session']==session and card['targetLevelId']==level,'SHOP_BASELINE_TARGET')
    result=decode(at);require(result.get('ok') is True and result.get('safeToRelease') is True and result.get('trialIdentityBound') is True,'SHOP_BASELINE_NOT_CLEAN')
    n=result['nativeReceipt'];validate_selection(n['before'],requested)
    return dict(avatar=n['avatar'],bag=n['bag'],uiBytesHex=n['uiBeforeBytesHex']),dict(run=str(at),hashes={name:sha(at/name) for name in c.PROOF_NAMES})
def revalidate_proofs(card):
    lineage,binding=c.previous(card['anchorRun'],card['session'],card['targetLevelId'],'trial-frame');require(lineage==card['lineage'] and binding==card['binding'],'SHOP_ANCHOR_CHANGED')
    if card['uiBaseline']:
        values,proof=baseline(card['uiBaseline']['run'],card['anchorRun'],card['session'],card['targetLevelId'],card['uiPlan']);require(values==card['uiBinding'] and proof==card['uiBaseline'],'SHOP_BASELINE_CHANGED')
def claim_write(run,card):
    if card['mode']=='shop-state':return
    # Both operation identity and the observation are one-use: changing ui-id
    # cannot replay an unknown purchase against the same stale observation.
    record=dict(run=str(run),preparedSha256=sha(run/'prepared.json'),atUtc=datetime.now(timezone.utc).isoformat(),automaticReplayForbidden=True)
    write(Path(card['lineage']['rootRun'])/('shop-'+card['uiPlan']['id']+'.claim'),record)
    write(Path(card['uiBaseline']['run'])/'shop-consumed.claim',record)

def copy_sources(run):
    import inventory_build
    hashes=inventory_build.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_shop.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h';text=protocol.read_text(encoding='utf-8').replace('native_inventory.h','native_shop.h').replace('InventoryReceipt','ShopReceipt');protocol.write_text(text,encoding='utf-8')
    hook=run/'candidate-source/native/hook_receipt.cpp';text=c.a.legacy.replace(hook.read_text(encoding='utf-8'),'ExecuteInventory(&receipt->acceptance);','ExecuteShop(&receipt->acceptance);')
    text=c.a.legacy.replace(text,'receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID) {','receipt->expectedPid == HR_TARGET_PID && receipt->expectedTid == HR_TARGET_TID && InterlockedCompareExchange(&receipt->claim,0,0)==0) {')
    hook.write_text(text,encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp';text=probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_INVENTORY','FIXED_PLAYTEST_SHOP');probe.write_text(text,encoding='utf-8');return hashes

def prepare(args,*,compile_only=False):
    requested=plan(args);operation=args.operation;require(getattr(args,'page_start',0)==0,'SHOP_HAS_NO_PAGE');page=0
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');control=read(HERE/'control-profile.json');inventory=read(HERE/'inventory-profile.json');extra=read(HERE/'shop-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(all(x['imageSha256']==profile['image']['sha256'] and x['metadataSha256']==sha(metadata) for x in (runtime,control,inventory,extra)),'SHOP_PROFILE_DRIFT')
    level=1 if compile_only else args.target_level;require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    binding={};lineage={};anchor=None;ui_binding={};proof=None
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session);require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE');require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
        require(args.previous_run is not None,'PROVEN_TRIAL_ANCHOR_REQUIRED');anchor=Path(args.previous_run).resolve();lineage,binding=c.previous(anchor,session,level,'trial-frame')
        if operation=='shop-ui':
            require(args.ui_baseline is not None,'SHOP_BASELINE_REQUIRED');ui_binding,proof=baseline(args.ui_baseline,anchor,session,level,requested)
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000;message=int(user.RegisterWindowMessageW('Miliastra.NativeShopUi.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce);header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=c.a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_TARGET_LEVEL '+str(level)+'U\n#define CONTROL_OPERATION 3U\n#define INVENTORY_OPERATION 14U\n'
    for prefix,data in [('PLAY',runtime),('CONTROL',control),('INVENTORY',inventory),('SHOP',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
        text+=f'#define {prefix}_HOTFIX_RVAS '+','.join(data['hotfixZeroRvas'])+'\n'
    fields={'GLOBAL':'global','EDITOR':'editor','TASK':'task','TOKEN':'token','CACHE':'cache','DATA':'cacheEditData','INITIAL_TOKEN':'initialToken','INITIAL_DATA':'initialData','INITIAL_SETTLE':'initialSettleData','EXIT_SETTLE':'exitSettleBefore','SETTLE_CONTEXT':'settleContext','SETTLE_DATA':'settleData'}
    for macro,key in fields.items():text+=f'#define CONTROL_{macro} {binding.get(key,0)}ULL\n'
    text+='\n#define SHOP_OPERATION '+str(OPERATIONS[operation])+'U\n#define SHOP_ACTION '+str(ACTIONS.get(requested['action'],0))+'U\n#define SHOP_ROW '+str(requested['row'] or 0)+'U\n#define SHOP_CONFIG_ID '+str(requested['configId'] or 0)+'U\n'
    text+='#define SHOP_AVATAR '+str(ui_binding.get('avatar',0))+'ULL\n#define SHOP_BAG '+str(ui_binding.get('bag',0))+'ULL\n'
    expected=bytes.fromhex(ui_binding['uiBytesHex']) if ui_binding else bytes(UI_SIZE)
    text+='static const unsigned char shopExpectedBytes['+str(UI_SIZE)+']={'+','.join(str(x) for x in expected)+'};\n#define SHOP_EXPECTED_UI shopExpectedBytes\n'
    header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/shop_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    c.a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    proofs=lineage.get('ancestors',[])+([proof] if proof else [])
    for entry in proofs:
        for name,digest in entry['hashes'].items():require(sha(Path(entry['run'])/name)==digest,'SHOP_PROOF_CHANGED_DURING_BUILD')
    card=dict(schemaVersion=1,kind='playtest-control-prepared-v7',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=page,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'],lineage=lineage,binding=binding,anchorRun=str(anchor) if anchor else None,uiPlan=requested,uiBinding=ui_binding,uiBaseline=proof)
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        for entry in proofs:pins.update({str(Path(entry['run'])/name):digest for name,digest in entry['hashes'].items()})
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_SHOP').replace('playtest-control-build-v1','playtest-control-build-v7').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v7',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='shop-state',changesTrialMode=False,mutatesTemporaryRenderResources=False,called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
