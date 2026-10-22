"""Independent v8 native contact/identity decoder. No target access."""
import struct
from contract import require
import control_contract as c
OPERATIONS={'contact-state':17}
ROW_CAPACITY=129;OPTION_CAPACITY=64;MAP_CAPACITY=8192
ROW_SIZE=48;OPTION_SIZE=496;MOTION_SIZE=184
SAMPLE_SIZE=333328;CONTROL_OFFSET=64;SAMPLES_OFFSET=CONTROL_OFFSET+c.SIZE
SIZE=SAMPLES_OFFSET+2*SAMPLE_SIZE
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','pageStart','pageEnd','count','stable')
POINTERS=('entityManager','dictionary','entries','beyondManager','map','mapEntries','reverseMap','reverseEntries','mainContext','view','panel')
NUMBERS=('entityCount','entityVersion','entityCapacity','avatarId','mapCount','mapCapacity','reverseCount','reverseCapacity','optionCount','mapStatus','optionsStatus','reserved')
MOTION_POINTERS=('manager','array','move','data','fsm','state','referenceEntity','referenceComponent','referenceCollider','dataCollider')
MOTION_NUMBERS=('status','motion','previousMotion','stateType','beneathResult','slopeFrame','referenceRuntimeId','referenceColliderIndex','downRayEntityId','downRayFrame','frameBefore','frameAfter')
OPTION_POINTERS=('item','button','event','invocation','wrapper','delegateObject','callbackTarget','callbackClass','callbackMethod','methodInfo')
ROWS_AT=480;OPTIONS_AT=6672;MAPS_AT=38416;REVERSE_AT=202256

def entity_row(raw,partial=False):
    if partial and not any(raw):return None
    r=dict(zip(('entity','klass'),struct.unpack_from('<2Q',raw)));r.update(zip(('runtimeId','configId','entityType','flags','status','localAvatar','entryIndex','reserved'),struct.unpack_from('<8I',raw,16)))
    require(r['entity'] and r['runtimeId'] and not r['reserved'] and r['flags']<=15 and r['status']<=1 and r['localAvatar']<=1,'CONTACT_ENTITY_ROW');return r

def getter_offset(head):
    require(len(head)==8,'CONTACT_GETTER_BYTES')
    if head[:2]==b'\x8b\x41' and head[3]==0xc3:value=head[2]
    elif head[:2]==b'\x8b\x81' and head[6]==0xc3:value=struct.unpack_from('<I',head,2)[0]
    else:raise ValueError('CONTACT_GETTER_NOT_PURE_FIELD_READ')
    require(0x10<=value<=0x400 and value%4==0,'CONTACT_GETTER_FIELD_RANGE');return value

def motion(raw):
    o=dict(zip(MOTION_POINTERS,struct.unpack_from('<10Q',raw)));o.update(zip(MOTION_NUMBERS,struct.unpack_from('<12I',raw,80)))
    require(o['status'] in (0,1) and not any(raw[180:184]),'CONTACT_MOTION_HEADER')
    o['slopeRaw']=raw[128:180].hex()
    if o['status']==0:require(all(o[k] for k in ('manager','array','move','data','fsm','state')) and o['frameBefore']==o['frameAfter'],'CONTACT_CONTROLLER_OWNERSHIP')
    return o

def option(raw,module_base):
    o=dict(zip(OPTION_POINTERS,struct.unpack_from('<10Q',raw)));o.update(zip(('status','panel','index','textLength'),struct.unpack_from('<4I',raw,80)))
    require(o['status']<=2 and o['panel']<=1 and o['index']<64 and o['textLength']<=127,'CONTACT_OPTION_BOUNDS')
    require(not any(raw[96+o['textLength']*2:352]),'CONTACT_OPTION_UNUSED_TEXT')
    try:o['text']=raw[96:96+o['textLength']*2].decode('utf-16-le',errors='strict')
    except UnicodeError as exc:raise ValueError('CONTACT_OPTION_TEXT') from exc
    if o['status']==0:require(all(o[k] for k in OPTION_POINTERS),'CONTACT_CALLBACK_ASSOCIATION')
    o.update(zip(('interfaceType','interfaceRecord','callbackSlot','ownerGetter','ownerMethodInfo','ownerData','ownerObject'),struct.unpack_from('<7Q',raw,352)))
    o.update(zip(('ownerStatus','interfaceOffset','virtualCount','fieldOffset','ownerRuntimeId','active','enabled','reserved'),struct.unpack_from('<8I',raw,408)))
    o['getterHead']=raw[440:448].hex();o['owner']=entity_row(raw[448:496],True)
    require(o['ownerStatus']<=1 and o['active']<=1 and o['enabled']<=1 and not o['reserved'],'CONTACT_OPTION_OWNER_HEADER')
    if o['ownerStatus']==0:
        require(o['status']==0 and o['active']==1 and all(o[k] for k in ('interfaceType','interfaceRecord','callbackSlot','ownerGetter','ownerMethodInfo','ownerData','ownerObject')),'CONTACT_OPTION_OWNER_POINTERS')
        require(module_base and o['callbackSlot']==module_base+o['callbackMethod'] and 0<o['callbackMethod']<0x20000000 and module_base<=o['ownerGetter']<module_base+0x20000000,'CONTACT_OPTION_VTABLE_BINDING')
        require(o['interfaceOffset']+6<o['virtualCount']<=4096 and getter_offset(raw[440:448])==o['fieldOffset'] and o['ownerData']==o['callbackTarget']+o['fieldOffset'],'CONTACT_OPTION_OWNER_GETTER')
        require(o['owner'] and o['owner']['entity']==o['ownerObject'] and o['owner']['runtimeId']==o['ownerRuntimeId'] and o['owner']['status']==0 and o['owner']['flags']==3,'CONTACT_OPTION_OWNER_ENTITY')
    return o

def sample(raw,count,partial=False,module_base=0):
    o=dict(zip(POINTERS,struct.unpack_from('<11Q',raw)));o.update(zip(NUMBERS,struct.unpack_from('<12I',raw,88)))
    require(not o['reserved'] and o['entityCount']<=o['entityCapacity']<=65536 and o['mapCount']<=MAP_CAPACITY and o['reverseCount']<=MAP_CAPACITY and o['optionCount']<=OPTION_CAPACITY and o['mapStatus']<=1 and o['optionsStatus']<=1,'CONTACT_SAMPLE_BOUNDS')
    o['mapHeader']=raw[136:216].hex();o['reverseHeader']=raw[216:296].hex();o['motion']=motion(raw[296:ROWS_AT]);o['rows']=[]
    for i in range(count):
        at=ROWS_AT+i*ROW_SIZE;x=raw[at:at+ROW_SIZE]
        if partial and not any(x):o['rows'].append(None);continue
        o['rows'].append(entity_row(x))
    require(not any(raw[ROWS_AT+count*ROW_SIZE:OPTIONS_AT]),'CONTACT_UNUSED_ENTITY_ROWS')
    o['options']=[option(raw[OPTIONS_AT+i*OPTION_SIZE:OPTIONS_AT+(i+1)*OPTION_SIZE],module_base) for i in range(o['optionCount'])]
    require(not any(raw[OPTIONS_AT+o['optionCount']*OPTION_SIZE:MAPS_AT]),'CONTACT_UNUSED_OPTIONS')
    o['mappings']=[dict(zip(('hash','next','runtimeId','editorGuid','beyondId'),struct.unpack_from('<iiIII',raw,MAPS_AT+i*20))) for i in range(o['mapCount'])]
    o['reverse']=[dict(zip(('hash','next','editorGuid','runtimeId'),struct.unpack_from('<iiII',raw,REVERSE_AT+i*16))) for i in range(o['reverseCount'])]
    require(not any(raw[MAPS_AT+o['mapCount']*20:REVERSE_AT]) and not any(raw[REVERSE_AT+o['reverseCount']*16:]),'CONTACT_UNUSED_MAP_ENTRIES')
    if o['mapStatus']==0:
        require(all(o[k] for k in ('beyondManager','map','mapEntries','reverseMap','reverseEntries')) and o['mapCount']<=o['mapCapacity']<=65536 and o['reverseCount']<=o['reverseCapacity']<=65536,'CONTACT_MAP_POINTERS')
        require(struct.unpack_from('<I',raw,136+0x44)[0]==o['mapCount'] and struct.unpack_from('<Q',raw,136+0x20)[0]==o['mapEntries'],'CONTACT_MAP_HEADER')
        require(struct.unpack_from('<I',raw,216+0x40)[0]==o['reverseCount'] and struct.unpack_from('<Q',raw,216+0x10)[0]==o['reverseEntries'],'CONTACT_REVERSE_HEADER')
    return o

def parse(raw):
    require(len(raw)==SIZE,'CONTACT_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<12I',raw)));o['moduleBase']=struct.unpack_from('<Q',raw,48)[0]
    require(o['bytes']==SIZE and o['version']==7 and o['operation']==17,'CONTACT_ABI_VERSION')
    require(o['status']<=2 and 1<=o['stage']<=3 and o['count']<=ROW_CAPACITY and 0<=o['pageStart']<=o['pageEnd']<=65536 and o['resourcesReleased']==1 and o['stable']<=1 and not any(raw[56:64]),'CONTACT_HEADER')
    require(0<=o['nativeCalls']<=2*OPTION_CAPACITY+4,'CONTACT_NATIVE_CALLS')
    o['control']=c.parse(raw[CONTROL_OFFSET:SAMPLES_OFFSET]);require(o['control']['operation']==3 and not o['control']['actionAttempted'] and not o['control']['actionReturned'] and not o['control']['pngBytes'],'CONTACT_CONTROL_READONLY');o['control'].pop('png')
    for i,key in enumerate(('first','second')):o[key]=sample(raw[SAMPLES_OFFSET+i*SAMPLE_SIZE:SAMPLES_OFFSET+(i+1)*SAMPLE_SIZE],o['count'],o['stage']<3,o['moduleBase'])
    if o['stage']==3:
        require(o['stable']==int(raw[SAMPLES_OFFSET:SAMPLES_OFFSET+SAMPLE_SIZE]==raw[SAMPLES_OFFSET+SAMPLE_SIZE:]),'CONTACT_RAW_STABILITY')
        s=o['first'];require(o['count']>=1 and s['rows'][0]['localAvatar']==1 and s['rows'][0]['runtimeId']==s['avatarId']==o['control']['observation']['after']['avatarId'] and s['rows'][0]['entity']==o['control']['observation']['after']['avatar'],'CONTACT_AVATAR')
        require(o['pageEnd']<=s['entityCount'] and len({r['runtimeId'] for r in s['rows']})==o['count'],'CONTACT_ENTITY_IDENTITIES')
        require(all(not r['localAvatar'] and o['pageStart']<=r['entryIndex']<o['pageEnd'] for r in s['rows'][1:]),'CONTACT_PAGE_ROWS')
    return o

def identities(s,rows=None):
    # Duplicate forward/reverse keys or a mismatched reverse value cannot prove
    # an identity. Never merge rows merely because they share configId.
    forward={};byguid={};reverse={}
    if s['mapStatus']==0:
        for i,r in enumerate(s['mappings']):
            if r['hash']<0:continue
            forward.setdefault(r['runtimeId'],[]).append((i,r));byguid.setdefault(r['editorGuid'],[]).append(r)
        for i,r in enumerate(s['reverse']):
            if r['hash']>=0:reverse.setdefault(r['editorGuid'],[]).append((i,r))
    out=[]
    for e in s['rows'] if rows is None else rows:
        f=forward.get(e['runtimeId'],[]);candidate=f[0][1] if len(f)==1 else None;g=candidate['editorGuid'] if candidate else 0;r=reverse.get(g,[])
        matched=bool(e['status']==0 and e['flags']==3 and candidate and candidate['beyondId'] and g and len(byguid.get(g,[]))==1 and len(r)==1 and r[0][1]['runtimeId']==e['runtimeId'])
        out.append(dict(runtimeId=e['runtimeId'],runtimeObject=e['entity'],configId=e['configId'] if e['status']==0 else None,entityType=e['entityType'] if e['status']==0 else None,localAvatar=bool(e['localAvatar']),editorEntityGuid=g if matched else None,beyondEntityId=candidate['beyondId'] if candidate else None,identityMappingVerified=matched,mappingIndex=f[0][0] if len(f)==1 else None,reverseIndex=r[0][0] if len(r)==1 else None,mappingStatus='unique-native-bidirectional-map' if matched else 'unknown',belongsToBoundTrial=True if e['localAvatar'] else None,entryIndex=e['entryIndex']))
    return out

def interpretation(o,card):
    r=c.interpretation_control(o['control'],dict(card,mode='trial-state'));require(r['mode']=='play' and r['trialIdentityBound'] is True and o['stable']==1,'CONTACT_UNBOUND_TRIAL')
    s=o['first'];m=s['motion'];entities=identities(s)
    options=[]
    for item in s['options']:
        mapped=identities(s,[item['owner']])[0] if item['ownerStatus']==0 else None
        options.append(dict(item,host=mapped,hostIdentityVerified=bool(mapped and mapped['identityMappingVerified']),hostRuntimeIdentityVerified=item['ownerStatus']==0))
    r.update(operation='contact-state',readOnly=True,entities=entities,page=dict(start=o['pageStart'],end=o['pageEnd'],next=o['pageEnd'] if o['pageEnd']<s['entityCount'] else None,dictionaryCount=s['entityCount'],dictionaryVersion=s['entityVersion']),controllerStateKnown=m['status']==0,controllerState=m if m['status']==0 else None,grounded=None,collisionVerified=False,playerContactVerified=False,contactEvidence='unknown: controller state, ground-probe cache and reference collider are not a solver contact manifold',interactionOptions=options,interactionOptionsKnown=s['optionsStatus']==0,targetNpcIdentityVerified=False,interactionHostIdentityVerified=bool(options) and all(x['hostIdentityVerified'] for x in options if x['active']) and any(x['active'] for x in options),optionOwnerEvidence='UI binder interface slot6 supplies EntityManager runtime ID; same model slot4 owns the actual button callback; pure getter bytes and native bidirectional map are independently decoded',mappingEvidence='current Beyond runtimeId to (editor instance guid, gameplay entity id) plus unique reverse mapping; no configId merging',targetLevelSpawnMembershipVerified=False)
    return r
