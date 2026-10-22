"""Fixed native range edit; current save backup and immutable one-use card."""
from datetime import datetime,timezone,timedelta
import secrets,sys
from pathlib import Path
import acceptance_build as a
from contract import read,write,sha,require
ROOT,HERE,OUTPUT,p,ro=a.ROOT,a.HERE,a.OUTPUT,a.p,a.ro
sys.path.insert(0,str(ROOT/'tools/map-terrain'))
from terrain_recovery import formal_source as validate_source
def formal_source(level):
    return validate_source(Path.home()/f'AppData/LocalLow/miHoYo/原神/BeyondLocal/100000001/Beyond_Local_Save_Level/{level}/{level}.gil',level)
OWN=('native_bounds.h','native_bounds.cpp','bounds_build.py','bounds_receipt.py','bounds-profile.json')
OPERATIONS={'bounds-state':1,'bounds-expand':2}
def copy_sources(run):
    hashes=a.copy_sources(run);folder=run/'candidate-source/playtest-control'
    for name in OWN:
        source=HERE/name;hashes[str(source)]=sha(source);(folder/name).write_bytes(source.read_bytes())
    (folder/'native_acceptance.cpp').write_bytes((HERE/'native_bounds.cpp').read_bytes())
    protocol=run/'candidate-source/native/hook_receipt_protocol.h'
    protocol.write_text(protocol.read_text(encoding='utf-8').replace('native_acceptance.h','native_bounds.h').replace('AcceptanceReceipt','BoundsReceipt'),encoding='utf-8')
    probe=run/'candidate-source/native/hook_receipt_probe.cpp'
    probe.write_text(probe.read_text(encoding='utf-8').replace('FIXED_PLAYTEST_ACCEPTANCE','FIXED_PLAYTEST_BOUNDS'),encoding='utf-8')
    return hashes
def revalidate_proofs(card):
    backup=card['formalBackup'];source=formal_source(1073741845)
    require(card['targetLevelId']==1073741845 and backup['path']==str(source) and sha(source)==backup['sha256'],'BOUNDS_FORMAL_SAVE_CHANGED')
def prepare(args,*,compile_only=False):
    operation=args.operation;require(operation in OPERATIONS and args.page_start==0,'BOUNDS_OPERATION')
    profile=p.load_profile();p.verify_disk(profile);runtime=read(HERE/'runtime-profile.json');extra=read(HERE/'bounds-profile.json')
    metadata=p.TARGET_IMAGE.parent/'YuanShen_Data/Managed/Metadata/global-metadata.dat'
    require(runtime['imageSha256']==extra['imageSha256']==profile['image']['sha256'] and sha(metadata)==runtime['metadataSha256']==extra['metadataSha256'],'BOUNDS_SOURCE_DRIFT')
    level=1073741845 if compile_only else args.target_level
    require(type(level) is int and 1<=level<=0xffffffff,'TARGET_LEVEL_UINT32')
    require(level==1073741845,'BOUNDS_ONLY_FOR_MONDSTADT_1845')
    if compile_only:session=dict(pid=1,tid=1,processCreation=1,threadCreation=1,image=str(OUTPUT/'compile-only.invalid'))
    else:
        session=read(args.session)
        require(all(type(session.get(k)) is int and session[k]>0 for k in ('pid','tid','processCreation','threadCreation')),'SESSION_SHAPE')
        require(Path(session['image']).resolve()==p.TARGET_IMAGE.resolve(),'SESSION_IMAGE')
    run=ro.output_directory(OUTPUT);hashes=copy_sources(run);hashes[str(metadata)]=runtime['metadataSha256']
    if compile_only:deadline,message=1,0xc001
    else:
        kernel,user=p.windows_api();deadline=int(kernel.GetTickCount64())+600000
        message=int(user.RegisterWindowMessageW('Miliastra.Bounds.'+secrets.token_hex(12)));require(message!=0,'REGISTER_MESSAGE_FAILED')
    nonce=secrets.randbits(63)|1;ro.emit_header(profile,session,run,deadline=deadline,message_id=message,nonce=nonce)
    header=run/'target_config.h';text=header.read_text(encoding='utf-8')
    for old,new in [('#define HR_READ_CONTEXT 1ULL','#define HR_READ_CONTEXT 0ULL'),('#define HR_ACTION 0ULL','#define HR_ACTION 19ULL'),('#define GS_BOOTSTRAP_READONLY 1ULL','#define GS_BOOTSTRAP_READONLY 0ULL')]:text=a.legacy.replace(text,old,new)
    text+='\n#define GS_REVIEWED_ACTION_PROFILE 1\n#define HR_ACTION_PROFILE_REVIEWED 1\n#define PLAY_OBSERVE_REVIEWED 1\n#define PLAY_ACCEPTANCE_REVIEWED 1\n#define PLAY_BOUNDS_REVIEWED 1\n'
    text+=f'#define PLAY_TARGET_LEVEL {level}U\n#define BOUNDS_OPERATION {OPERATIONS[operation]}U\n'
    for prefix,data in [('PLAY',runtime),('BOUNDS',extra)]:
        text+=f'#define {prefix}_CODE_RVAS '+','.join(x['rva'] for x in data['functions'])+'\n'
        text+=f'#define {prefix}_CODE_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(x['head32']))+'}' for x in data['functions'])+'\n'
    text+='#define BOUNDS_HOTFIX_RVAS '+','.join(extra['hotfixZeroRvas'])+'\n'
    text+='#define PLAY_HOTFIX_RVAS '+','.join(runtime['hotfixZeroRvas'])+'\n';header.write_text(text,encoding='utf-8')
    if compile_only:
        fixture=HERE/'tests/bounds_fixture.cpp';hashes[str(fixture)]=sha(fixture);(run/'candidate-source/playtest-control/acceptance_fixture.cpp').write_bytes(fixture.read_bytes())
    a.compile_card(run,fixture=compile_only)
    for source,digest in hashes.items():require(sha(source)==digest,'SOURCE_CHANGED_DURING_BUILD')
    backup={}
    if not compile_only:
        source=formal_source(level);backup={'path':str(source),'sha256':sha(source)};(run/'before.gil').write_bytes(source.read_bytes())
    card=dict(formalBackup=backup,schemaVersion=1,kind='playtest-control-prepared-v12',run=str(run),action=19,receiptVersion=24,mode=operation,pageStart=0,targetLevelId=level,launchable=not compile_only,compileOnly=compile_only,session=session,sourceHashes=hashes,deadlineTick=deadline,nonce=str(nonce),expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=8)).isoformat(),createdUtc=datetime.now(timezone.utc).isoformat(),imagePath=str(p.TARGET_IMAGE),imageSha256=profile['image']['sha256'])
    card['artifacts']={x.relative_to(run).as_posix():sha(x) for x in run.rglob('*') if x.is_file()};write(run/'prepared.json',card)
    if not compile_only:
        pins=dict(hashes);pins.update({str(run/name):digest for name,digest in card['artifacts'].items()});pins[str(run/'prepared.json')]=sha(run/'prepared.json');pins[str(p.TARGET_IMAGE)]=profile['image']['sha256']
        quote=lambda x:"'"+str(x).replace("'","''")+"'"
        wrapper=(HERE/'invoke.template.ps1').read_text(encoding='utf-8').replace('FIXED_PLAYTEST_OBSERVATION','FIXED_PLAYTEST_BOUNDS').replace('playtest-control-build-v1','playtest-control-build-v12').replace('@@EXPIRES@@',quote(card['expiresUtc'])).replace('@@PINS@@',',\n'.join('    @('+quote(path)+','+quote(digest)+')' for path,digest in sorted(pins.items())))
        require('@@' not in wrapper,'WRAPPER_PLACEHOLDER');(run/'invoke-observe.ps1').write_text(wrapper,encoding='utf-8-sig')
    result=dict(ok=True,kind='playtest-control-build-v12',run=str(run),compiled=True,launchable=not compile_only,actionCode=19,receiptVersion=24,mode=operation,readOnly=operation=='bounds-state',changesTrialMode=False,persistentWorldWriteRequested=operation=='bounds-expand',called=False,nativeStarted=False,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True,preparedSha256=sha(run/'prepared.json'),wrapperSha256=sha(run/'invoke-observe.ps1') if not compile_only else None)
    write(run/'build-result.json',result);return result
