"""Independent raw runtime-vitals decoding; no process, graph or game writes."""
import math,struct
from contract import require
import control_contract as c
OPERATIONS={'vitals-state':13}
SIZE=c.SIZE+35168
CONTROL_OFFSET=96
CONTEXT_OFFSET=CONTROL_OFFSET+c.SIZE
TABLE_OFFSET=CONTEXT_OFFSET+32
ROWS_OFFSET=TABLE_OFFSET+6144
ROW_SIZE=112
ROW_CAPACITY=129
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','count','pageStart','pageEnd','dictionaryStable','samplesStable','tableStatus','reserved0','reserved1')
POINTERS=('dictionary','entries','table','avatar')
ROW_POINTERS=('entity','klass','component','properties')
ROW_NUMBERS=('id','configId','entityType','flags','status','hpStatus','lifeStatus','alive','localAvatar','entryIndex')

def decode_hp(raw,table):
    require(len(raw)==16 and len(table)==3072,'HP_INPUT_SIZE')
    if raw==bytes(16):return 0,0.0
    seed=sum(table[(8+i)*256+raw[i]]<<(8*i) for i in range(4))
    signed=seed if seed<2**31 else seed-2**32
    def remainder(x):return x%12 if x>=0 else -((-x)%12)
    start=remainder(signed);values=[]
    for group in range(3):
        value=0
        for i in range(4):
            index=remainder(start+i+group*4);word=int(index>=4);shift=(index*8+32)&63
            encoded=int.from_bytes(raw[word*8:word*8+8],'little')
            value|=table[(8+i)*256+((encoded>>shift)&255)]<<(8*i)
        values.append(value)
    bits=seed^values[1]
    if values[0]^bits!=values[2]:return 3,None
    value=struct.unpack('<f',struct.pack('<I',bits))[0]
    if not math.isfinite(value) or value<0:return 4,None
    return 0,value

def row(raw,*,partial=False):
    if partial and raw==bytes(ROW_SIZE):return None
    require(len(raw)==ROW_SIZE,'VITALS_ROW_SIZE');r=dict(zip(ROW_POINTERS,struct.unpack_from('<4Q',raw)))
    r.update(zip(ROW_NUMBERS,struct.unpack_from('<10I',raw,32)))
    r.update(zip(('currentHp','maxHp'),struct.unpack_from('<2f',raw,72)))
    r.update(currentEncoded=raw[80:96].hex(),maxEncoded=raw[96:112].hex())
    require(r['status']<=1 and r['hpStatus']<=5 and r['lifeStatus']<=1 and r['alive']<=1 and r['localAvatar']<=1 and r['flags']<=15,'VITALS_ROW_ENUM')
    require(r['entity'] and r['id'],'VITALS_ROW_IDENTITY')
    if r['lifeStatus']==0:require(r['status']==0 and r['flags']==3,'VITALS_LIFECYCLE_GUARD')
    if r['hpStatus']==0:require(r['status']==0 and r['component'] and r['properties'] and all(math.isfinite(r[k]) and r[k]>=0 for k in ('currentHp','maxHp')),'VITALS_HP_GUARD')
    for field in ('currentHp','maxHp'):
        if not math.isfinite(r[field]):r[field]=None
    return r

def parse(raw):
    require(len(raw)==SIZE,'VITALS_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<16I',raw)));o.update(zip(POINTERS,struct.unpack_from('<4Q',raw,64)))
    require(o['bytes']==SIZE and o['version']==4 and o['operation']==13,'VITALS_ABI_VERSION')
    require(o['status']<=2 and 1<=o['stage']<=3 and o['nativeCalls']==0,'VITALS_READ_ONLY_HEADER')
    require(not o['reserved0'] and not o['reserved1'] and o['count']<=ROW_CAPACITY and 0<=o['pageStart']<=o['pageEnd']<=65536 and o['tableStatus']<=2,'VITALS_LIMITS')
    require(all(o[k] in (0,1) for k in ('resourcesReleased','dictionaryStable','samplesStable')),'VITALS_FLAGS')
    o['control']=c.parse(raw[CONTROL_OFFSET:CONTEXT_OFFSET]);require(o['control']['operation']==3 and not o['control']['actionAttempted'] and not o['control']['actionReturned'] and not o['control']['pngBytes'],'VITALS_CONTROL_READONLY');o['control'].pop('png')
    for key,at in [('before',CONTEXT_OFFSET),('after',CONTEXT_OFFSET+16)]:
        o[key]=dict(zip(('count','version','capacity','avatarId'),struct.unpack_from('<4I',raw,at)))
        require(o[key]['count']<=o[key]['capacity']<=65536,'VITALS_DICTIONARY_BOUNDS')
    o['tables']=[raw[TABLE_OFFSET+i*3072:TABLE_OFFSET+(i+1)*3072].hex() for i in range(2)]
    o['first']=[];o['second']=[]
    for sample,key in enumerate(('first','second')):
        at=ROWS_OFFSET+sample*ROW_CAPACITY*ROW_SIZE
        o[key]=[row(raw[at+i*ROW_SIZE:at+(i+1)*ROW_SIZE],partial=o['stage']!=3) for i in range(o['count'])]
        require(not any(raw[at+o['count']*ROW_SIZE:at+ROW_CAPACITY*ROW_SIZE]),'UNUSED_VITALS_ROW')
    if o['stage']==3:
        require(o['pageEnd']<=o['before']['count'] and o['dictionary'] and (o['before']['count']==0 or o['entries']),'VITALS_PAGE_BOUNDS')
        require(o['count']>=1 and o['first'][0]['localAvatar']==1 and o['first'][0]['entity']==o['avatar'],'VITALS_LOCAL_AVATAR')
        require(o['first'][0]['id']==o['before']['avatarId']==o['after']['avatarId']==o['control']['observation']['after']['avatarId'],'VITALS_AVATAR_ID')
        require(o['dictionaryStable']==int(o['before']==o['after']),'VITALS_DICTIONARY_STABILITY')
        require(o['samplesStable']==int(raw[ROWS_OFFSET:ROWS_OFFSET+o['count']*ROW_SIZE]==raw[ROWS_OFFSET+ROW_CAPACITY*ROW_SIZE:ROWS_OFFSET+ROW_CAPACITY*ROW_SIZE+o['count']*ROW_SIZE]),'VITALS_SAMPLE_STABILITY')
        require(len({x['id'] for x in o['first']})==o['count'],'DUPLICATE_VITALS_ID')
        for r in o['first'][1:]:require(not r['localAvatar'] and o['pageStart']<=r['entryIndex']<o['pageEnd'],'VITALS_ROW_PAGE')
        require([r['entryIndex'] for r in o['first'][1:]]==sorted(r['entryIndex'] for r in o['first'][1:]),'VITALS_ROW_ORDER')
    if o['tableStatus']==0 and o['stage']==3:require(o['table'] and o['tables'][0]==o['tables'][1],'VITALS_TABLE_STABILITY')
    for sample,key in enumerate(('first','second')):
        for r in o[key]:
            if r and r['hpStatus']==0:
                require(o['table'] and o['tableStatus']!=1,'HP_WITHOUT_TABLE')
                for field,encoded in [('currentHp','currentEncoded'),('maxHp','maxEncoded')]:
                    status,value=decode_hp(bytes.fromhex(r[encoded]),bytes.fromhex(o['tables'][sample]))
                    require(status==0 and value==r[field],'HP_RAW_DECODE_MISMATCH')
    return o

def interpretation(o,card):
    result=c.interpretation_control(o['control'],dict(card,mode='trial-state'))
    require(result['mode']=='play' and result['trialIdentityBound'] is True and o['dictionaryStable']==o['samplesStable']==1,'VITALS_UNBOUND_TRIAL')
    require(o['avatar']==o['control']['observation']['after']['avatar'],'VITALS_AVATAR_CHANGED')
    result.update(operation='vitals-state',readOnly=True,inventoryQuantitiesVerified=False,inventoryBlocker='runtime inventory ownership and quantity chain not yet proven',damageVerified=False,killVerified=False)
    records=[]
    for r in o['first']:
        hp=r['hpStatus']==0 and o['tableStatus']==0;life=r['lifeStatus']==0
        records.append(dict(runtimeId=r['id'],configId=r['configId'] if r['status']==0 else None,entityType=r['entityType'] if r['status']==0 else None,entityKind='local-avatar' if r['localAvatar'] else 'monster' if r['status']==0 and r['entityType']==2 else 'other-or-unknown',runtimeObject=r['entity'],runtimeClass=r['klass'],component=r['component'],properties=r['properties'],localAvatar=bool(r['localAvatar']),observedDuringBoundTrial=True,belongsToBoundTrial=True if r['localAvatar'] else None,configuredSpawnIdentityVerified=False,currentHp=r['currentHp'] if hp else None,maxHp=r['maxHp'] if hp else None,hpKnown=hp,hpStatus=r['hpStatus'],nativeAlive=bool(r['alive']) if r['status']==0 else None,alive=bool(r['alive']) if life else None,dead=not bool(r['alive']) if life else None,lifeState=('alive' if r['alive'] else 'dead') if life else 'unknown',lifeStateEvidence='native Entity.isAlive; loaded, ready, not cleared or recycled' if life else 'lifecycle incomplete or unreadable',hpDepleted=r['currentHp']==0 if hp else None,loaded=bool(r['flags']&1),ready=bool(r['flags']&2),cleared=bool(r['flags']&4),recycled=bool(r['flags']&8),recordStatus=r['status'],entryIndex=r['entryIndex']))
    result.update(entities=records,localAvatarVitals=records[0],monsterHealthVerified=any(r['entityKind']=='monster' and r['hpKnown'] for r in records),page=dict(start=o['pageStart'],end=o['pageEnd'],next=o['pageEnd'] if o['pageEnd']<o['before']['count'] else None,dictionaryCount=o['before']['count'],dictionaryVersion=o['before']['version']),monsterTargetLevelProvenanceVerified=False,attribution='controlled avatar is trial-bound; other rows are current EntityMap members during that trial, not proven target editor spawn IDs; config ID is raw, no species guessed')
    return result
