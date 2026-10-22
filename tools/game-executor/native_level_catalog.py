"""Version-pinned, read-only catalog profile and independent receipt decoder."""
from pathlib import Path
import json
import struct
import native_profiles as profiles
PROFILE=Path(__file__).with_name('profiles')/'genshin-cn-7.1.0-native-level-catalog.json'
PROFILE_SHA256='16a390037674406084fab526e814edcac5cc25c971c795318ea2719e226ffb09'
CATALOG_BYTES=8312
STATUS={0:'ok',1:'baseline_refused',2:'anchor_mismatch',3:'unreadable',4:'structure_invalid',5:'limit',6:'unstable',7:'hotfix_active',8:'state_mismatch'}

def load_profile():
    profiles.require(profiles.sha256(PROFILE)==PROFILE_SHA256,'CATALOG_PROFILE_CHANGED')
    p=json.loads(PROFILE.read_text(encoding='utf-8-sig'))
    profiles.require(p['imageSha256']==profiles.load_profile()['image']['sha256'] and p['allowWrites'] is False,'CATALOG_IMAGE_BINDING')
    return p

def append_header(run,p):
    values={'HR_READ_LEVEL_CATALOG':1,'GSL_EXPECTED_LEVEL_ID':p['expectedLevelId'],**p['layout']}
    lines=['// Read-only catalog extension; no scene action linked.']
    lines += ['#define '+name+' '+str(value)+'ULL' for name,value in values.items()]
    anchors=p['anchors']
    lines += ['#define GSL_ANCHOR_RVAS '+','.join(a['rva'] for a in anchors),
        '#define GSL_ANCHOR_LENGTHS '+','.join(str(a['length']) for a in anchors),
        '#define GSL_ANCHOR_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(a['bytes']))+'}' for a in anchors),
        '#define GSL_HOTFIX_RVAS '+','.join(p['hotfixByteRvas'])]
    with (Path(run)/'target_config.h').open('a',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')

def decode(record,context,profile):
    raw=bytes.fromhex(record.get('catalogHex',''))
    profiles.require(len(raw)==CATALOG_BYTES and record.get('catalogBytes')==CATALOG_BYTES,'CATALOG_ABI_SIZE')
    size,version,status,flags=struct.unpack_from('<4I',raw)
    profiles.require(size==CATALOG_BYTES and version==1,'CATALOG_ABI_VERSION')
    names=('archive','dictionary','buckets','entries','levelManager','comparer')
    pointers=dict(zip(names,struct.unpack_from('<6Q',raw,16)))
    names=('levelId','selectedId','initializedCount','freeCount','bucketCapacity','entryCapacity','versionBefore','versionAfter','bytesRead','readCalls','dirtyByte','recordCount','parserError','reserved')
    counters=dict(zip(names,struct.unpack_from('<14I',raw,64)))
    n=counters['recordCount'];profiles.require(n<=512,'CATALOG_RECORD_COUNT')
    rows=[dict(zip(('id','key','record'),struct.unpack_from('<IIQ',raw,120+i*16))) for i in range(n)]
    errors=[]
    def check(ok,reason):
        if not ok:errors.append(reason)
    check(status==0 and record.get('catalogStatus')==status,'CATALOG_STATUS_'+STATUS.get(status,'unknown'))
    check(flags==31 and counters['parserError']==0,'CATALOG_FLAGS_OR_PARSER')
    check(counters['reserved']==0 and not any(raw[120+n*16:]),'CATALOG_UNUSED_FIELDS')
    check(context['status']['value']==0 and context.get('levelObservation',{}).get('verified') is True,'CATALOG_BASELINE')
    check(counters['levelId']==counters['selectedId']==profile['expectedLevelId']==context.get('levelObservation',{}).get('levelId'),'CATALOG_LEVEL_ID')
    check(0<=counters['freeCount']<=counters['initializedCount']<=counters['entryCapacity']<=512 and
          n==counters['initializedCount']-counters['freeCount'] and 1<=counters['bucketCapacity']<=512,'CATALOG_COMPLETE_COUNT')
    check(counters['versionBefore']==counters['versionAfter'],'CATALOG_VERSION')
    check(0<counters['bytesRead']<=1048576 and 0<counters['readCalls']<=4096 and counters['dirtyByte']<=1,'CATALOG_BUDGET_OR_STATE')
    def pointer(p):return type(p) is int and 0x10000<=p<0x800000000000 and p%8==0
    check(all(pointer(p) for k,p in pointers.items() if k!='comparer') and (pointers['comparer']==0 or pointer(pointers['comparer'])),'CATALOG_ROOT_POINTERS')
    check(all(row['id']==row['key'] and row['id']>0 and pointer(row['record']) for row in rows) and
          len({row['id'] for row in rows})==n and len({row['record'] for row in rows})==n,'CATALOG_ROW_IDENTITY')
    check(counters['levelId'] in {row['id'] for row in rows},'CATALOG_ACTIVE_RECORD')
    return {'ok':not errors,'reasons':errors,'status':STATUS.get(status,'unknown'),'flags':flags,'counts':counters,
            'pointers':{k:hex(v) for k,v in pointers.items()},'levels':sorted(rows,key=lambda r:r['id']),
            'source':'in-process-bounded-read-only-snapshot','gameMethodsCalled':0,'mutationAttempted':False,
            'allowWrites':False,'reopenVerified':False,'dirtyFlagMeaning':'save-manager +0xa2 as used by the pinned default save-before-transition branch'}
