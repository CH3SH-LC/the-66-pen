"""Pure, bounded observation contract. Unknown is never promoted to play."""
import hashlib,json,math,struct
from pathlib import Path
def require(value,reason):
    if not value:raise ValueError(reason)
def unique(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'DUPLICATE_KEY:'+key);out[key]=value
    return out
def read(path):
    data=Path(path).read_bytes();require(len(data)<=8*1024*1024,'JSON_TOO_LARGE')
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=unique)
def write(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
HEADER=('bytes','version','status','seh','stage','failedRva','failedValue','nativeCalls','mode','stable','readableBefore','readableAfter','targetLevel','reserved0','reserved1','reserved2')
POINTERS=('global','modeManager','gateManager','gateObject','editorManager','avatarManager','dictionary','avatar','transform')
NUMBERS=('rawMode','editing','editorLevel','avatarId','avatarStatus','positionStatus','avatarBranch')
def extension(raw):
    require(len(raw)==336,'OBSERVATION_ABI_SIZE')
    out=dict(zip(HEADER,struct.unpack_from('<16I',raw)))
    require(out['bytes']==336 and out['version']==1,'OBSERVATION_ABI_VERSION')
    require(all(out[k]==0 for k in HEADER[-3:]),'OBSERVATION_RESERVED')
    require(out['mode'] in (0,1,2) and out['stable'] in (0,1),'OBSERVATION_ENUM')
    for n,at in [('before',64),('after',200)]:
        s=dict(zip(POINTERS,struct.unpack_from('<9Q',raw,at)));s.update(zip(NUMBERS,struct.unpack_from('<7I',raw,at+72)))
        values=struct.unpack_from('<9f',raw,at+100)
        for i,key in enumerate(('unityPosition','origin','worldPosition')):s[key]=list(values[3*i:3*i+3])
        require(s['avatarStatus'] in range(6) and s['positionStatus'] in range(5),'SAMPLE_ENUM')
        if s['positionStatus']==0:
            require(s['avatarStatus']==2 and s['avatar'] and s['transform'],'POSITION_REQUIRES_LIVE_AVATAR')
            require(all(math.isfinite(x) for x in values),'POSITION_NONFINITE')
            require(all(abs(s['worldPosition'][i]-s['unityPosition'][i]-s['origin'][i])<=0.02 for i in range(3)),'WORLD_ORIGIN_RELATION')
        out[n]=s
    return out
def interpretation(e,target):
    a,b=e['before'],e['after'];keys=POINTERS[:8]+('rawMode','editing','editorLevel','avatarId','avatarStatus')
    stable=all(a[k]==b[k] for k in keys) and e['readableBefore']==e['readableAfter']
    require(e['stable']==int(stable),'STABILITY_RECEIPT_MISMATCH')
    complete=e['readableBefore']==e['readableAfter']==15
    changed=complete and any(a[k]!=b[k] for k in ('rawMode','editing','editorLevel'))
    editor=complete and stable and b['rawMode']==0xb993 and bool(b['gateObject']) and b['editing'] not in (0,0xffffffff)
    mode='transition' if changed else 'editor' if editor else 'unknown'
    require(e['mode']=={'unknown':0,'editor':1,'transition':2}[mode],'MODE_RECEIPT_MISMATCH')
    position=b['worldPosition'] if stable and a['avatarStatus']==b['avatarStatus']==2 and a['positionStatus']==b['positionStatus']==0 and a['transform']==b['transform'] and a['origin']==b['origin'] else None
    return dict(mode=mode,modeEvidence='positive-editing-guard' if editor else 'raw-state-changed-during-capture' if changed else 'no-proven-play-state-contract',
        editorLevelId=b['editorLevel'] if editor else None,editorIsTargetLevel=b['editorLevel']==target if editor else None,
        localAvatarObserved=bool(stable and b['avatarStatus']==2),localAvatarId=b['avatarId'] if stable and b['avatarStatus']==2 else None,
        rawLocalAvatarWorldPosition=position,positionEvidence='live-unity-transform-plus-world-origin' if position is not None else 'unavailable',
        playerBelongsToTargetLevel=False if editor else None,playerContactVerified=False,
        attribution='editor local avatar is not evidence of a player inside the target trial' if editor else 'runtime trial level identity is not proven',
        enterSupported=False,exitSupported=False,playStateProven=False,controlBlocker='trial task save/check/upload/enter and exit-request lifecycle contracts are not proven')
