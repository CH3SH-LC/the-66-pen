"""v9 source-directory evidence. Recompute membership from raw rows."""
import struct
import contact_contract as c
from contract import require
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','stable','reserved0','reserved1','reserved2')
POINTERS=('global','levelManager','levelData','editData','commonData','container','containerClass','list','entries','enumerator','enumeratorMethodInfo','capacity','editClass','commonClass','expectedEditClass','expectedCommonClass','expectedContainerClass')
NUMBERS=('status','count','listVersion','virtualCount','recordCount','reserved0','reserved1','reserved2')
CAPACITY=8192;ROW_SIZE=32;ROWS_AT=232;SAMPLE_SIZE=262376;CONTACT_OFFSET=64;SAMPLES_OFFSET=64+c.SIZE;SIZE=SAMPLES_OFFSET+2*SAMPLE_SIZE
def sample(raw):
    s=dict(zip(POINTERS,struct.unpack_from('<17Q',raw)));s.update(zip(NUMBERS,struct.unpack_from('<8I',raw,136)))
    require(s['status']<=1 and s['count']<=CAPACITY and s['recordCount']<=s['count'] and not any(s[x] for x in NUMBERS[-3:]),'DIRECTORY_SAMPLE_BOUNDS')
    s['containerHeaderHex']=raw[168:200].hex();s['listHeaderHex']=raw[200:232].hex()
    s['rows']=[dict(zip(('record','klass','editorGuid','templateId','templateRecord'),struct.unpack_from('<QQIIQ',raw,ROWS_AT+i*ROW_SIZE))) for i in range(s['count'])]
    require(not any(raw[ROWS_AT+s['count']*ROW_SIZE:]),'DIRECTORY_UNUSED_ROWS')
    if not s['status']:
        require(s['recordCount']==s['count'] and s['count']<=s['capacity']<=65536 and 35<s['virtualCount']<=4096,'DIRECTORY_COMPLETE')
        require(all(s[k] for k in POINTERS if k!='capacity'),'DIRECTORY_POINTERS')
        require(s['editClass']==s['expectedEditClass'] and s['commonClass']==s['expectedCommonClass'] and s['containerClass']==s['expectedContainerClass'],'DIRECTORY_EXACT_TYPES')
        require(struct.unpack_from('<QQ',raw,168)[0]==s['containerClass'] and struct.unpack_from('<Q',raw,184)[0]==s['list'],'DIRECTORY_CONTAINER_HEADER')
        require(struct.unpack_from('<QII',raw,216)==(s['entries'],s['count'],s['listVersion']),'DIRECTORY_LIST_HEADER')
        require(all(r['record'] and r['klass'] and r['editorGuid'] and r['templateRecord'] for r in s['rows']),'DIRECTORY_RECORD')
    return s
def parse(raw):
    require(len(raw)==SIZE,'DIRECTORY_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<12I',raw)));o['moduleBase']=struct.unpack_from('<Q',raw,48)[0]
    require(o['bytes']==SIZE and o['version']==8 and o['operation']==18,'DIRECTORY_ABI_VERSION')
    require(o['status']<=2 and 1<=o['stage']<=3 and o['nativeCalls']==0 and o['resourcesReleased']==1 and o['stable']<=1 and not any(o[k] for k in HEADER[-3:]) and not any(raw[56:64]),'DIRECTORY_HEADER')
    o['contact']=c.parse(raw[CONTACT_OFFSET:SAMPLES_OFFSET])
    for i,key in enumerate(('first','second')):o[key]=sample(raw[SAMPLES_OFFSET+i*SAMPLE_SIZE:SAMPLES_OFFSET+(i+1)*SAMPLE_SIZE])
    if o['stage']==3:
        require(o['moduleBase']==o['contact']['moduleBase'] and o['stable']==int(raw[SAMPLES_OFFSET:SAMPLES_OFFSET+SAMPLE_SIZE]==raw[SAMPLES_OFFSET+SAMPLE_SIZE:]),'DIRECTORY_STABILITY')
        for s in (o['first'],o['second']):
            if s['status']:continue
            state=o['contact']['control']['after'];require(s['global']==state['global'] and s['levelData']==state['data']==state['cache'] and s['editData']==state['cacheEditData'],'DIRECTORY_TRIAL_SOURCE_BINDING')
            require(s['enumerator']==o['moduleBase']+0x1713e080,'DIRECTORY_ENUMERATOR')
    return o
def interpretation(o,card):
    require(o['stable']==1 and not o['status'],'DIRECTORY_UNSTABLE');r=c.interpretation(o['contact'],card);s=o['first'];index={}
    for i,row in enumerate(s['rows']):index.setdefault(row['editorGuid'],[]).append((i,row))
    valid=s['status']==0 and all(g and len(rows)==1 for g,rows in index.items()) and len({x['record'] for x in s['rows']})==s['count']
    def augment(e):
        match=index.get(e.get('editorEntityGuid'),[]) if valid and e['identityMappingVerified'] else []
        verified=len(match)==1 and not e['localAvatar'];e.update(targetLevelSpawnMembershipVerified=verified,sourceDirectoryIndex=match[0][0] if verified else None,sourceInstance=match[0][1] if verified else None)
        if not e['localAvatar']:e['belongsToBoundTrial']=True if verified else None
        return e
    r['entities']=[augment(e) for e in r['entities']]
    for option in r['interactionOptions']:
        if option['host']:augment(option['host'])
        option['hostTrialMembershipVerified']=bool(option['host'] and option['host']['targetLevelSpawnMembershipVerified'])
    ordinary=[e for e in r['entities'] if not e['localAvatar']]
    r.update(operation='trial-entities',sourceDirectoryKnown=valid,sourceDirectory=s,targetLevelSpawnMembershipVerified=bool(ordinary) and all(e['targetLevelSpawnMembershipVerified'] for e in ordinary),membershipEvidence='Bound active trial cache/editData source directory; exact native container/enumerator plus full stable directory and unique runtime/editor bidirectional mapping',collisionVerified=False,playerContactVerified=False,grounded=None)
    return r
