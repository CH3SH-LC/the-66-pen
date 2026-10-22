"""Pinned read-only allocated lifecycle class binding; never a load-completion signal."""
from pathlib import Path
import hashlib,json,re,struct
import native_profiles as profiles
PROFILE=Path(__file__).with_name('profiles')/'genshin-cn-7.1.0-native-lifecycle-type.json'
PROFILE_SHA256='78cff58f0d938bebfaa209fbfbb87cdc575e0bfb61679f0981bbb5f3047bbc0e'
LIFECYCLE_TYPE_BYTES=2160
REQUIRED_FLAGS=255
STATUS={0:'ok',1:'baseline_refused',2:'anchor_mismatch',3:'unreadable',4:'structure_invalid',5:'limit',6:'unstable',7:'hotfix_active',8:'not_initialized',9:'function_not_found',10:'ambiguous_function'}

def load_profile():
    profiles.require(profiles.sha256(PROFILE)==PROFILE_SHA256,'LIFECYCLE_PROFILE_CHANGED')
    p=json.loads(PROFILE.read_text(encoding='utf-8-sig'));base=profiles.load_profile()
    profiles.require(p['imageSha256']==base['image']['sha256'] and p['allowWrites'] is False and p['maxSlots']==128,'LIFECYCLE_IMAGE_BINDING')
    for a in p['anchors']:
        raw=bytes.fromhex(a['bytes'])
        profiles.require(len(raw)==a['length'] and 0<len(raw)<=4096 and hashlib.sha256(raw).hexdigest()==a['sha256'],'LIFECYCLE_ANCHOR_INVALID')
    return p

def append_header(run,p):
    values={'HR_READ_LIFECYCLE_TYPE':1,'GLT_EXPECTED_LEVEL_ID':p['expectedLevelId'],**p['layout']}
    lines=['// Read-only lifecycle allocated-type binding; no method calls.']
    lines += ['#define '+name+' '+str(value)+'ULL' for name,value in values.items()]
    lines += ['#define GLT_ANCHOR_RVAS '+','.join(a['rva'] for a in p['anchors']),
        '#define GLT_ANCHOR_LENGTHS '+','.join(str(a['length']) for a in p['anchors']),
        '#define GLT_ANCHOR_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(a['bytes']))+'}' for a in p['anchors']),
        '#define GLT_HOTFIX_RVAS '+','.join(p['hotfixByteRvas'])]
    with (Path(run)/'target_config.h').open('a',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')

def decode(record,context,profile):
    encoded=record.get('lifecycleTypeHex')
    profiles.require(isinstance(encoded,str) and len(encoded)==LIFECYCLE_TYPE_BYTES*2 and re.fullmatch('[0-9a-fA-F]+',encoded) is not None,'LIFECYCLE_HEX')
    profiles.require(type(record.get('lifecycleTypeBytes')) is int and record['lifecycleTypeBytes']==LIFECYCLE_TYPE_BYTES,'LIFECYCLE_ABI_SIZE')
    raw=bytes.fromhex(encoded);size,version,status,flags=struct.unpack_from('<4I',raw)
    profiles.require(size==LIFECYCLE_TYPE_BYTES and version==1,'LIFECYCLE_ABI_VERSION')
    pnames=('moduleBase','classSlot','classPointer','functionsAddress','trailingWordsAddress','expectedFunction')
    ptr=dict(zip(pnames,struct.unpack_from('<6Q',raw,16)))
    cnames=('imageSize','levelId','initializedBefore','initializedAfter','slotCountBefore','slotCountAfter','matchCount','matchIndex','bytesRead','readCalls','parserError','reserved')
    c=dict(zip(cnames,struct.unpack_from('<12I',raw,64)))
    functions=struct.unpack_from('<128Q',raw,112);infos=struct.unpack_from('<128Q',raw,1136)
    errors=[]
    def check(ok,reason):
        if not ok:errors.append(reason)
    check(status==0 and record.get('lifecycleTypeStatus')==status,'LIFECYCLE_STATUS_'+STATUS.get(status,'unknown'))
    check(flags==REQUIRED_FLAGS and c['parserError']==0,'LIFECYCLE_FLAGS_OR_PARSER')
    check(c['reserved']==0,'LIFECYCLE_RESERVED')
    check(context.get('status',{}).get('value')==0 and context.get('levelObservation',{}).get('verified') is True,'LIFECYCLE_BASELINE')
    check(c['levelId']==profile['expectedLevelId']==context.get('levelObservation',{}).get('levelId'),'LIFECYCLE_LEVEL')
    try:context_base=int(context.get('pointers',{}).get('moduleBase',''),16)
    except (ValueError,TypeError):context_base=None
    check(ptr['moduleBase']==context_base and c['imageSize']==context.get('counts',{}).get('peImageSize'),'LIFECYCLE_IMAGE')
    def pointer(x):return 0x10000<=x<0x800000000000 and x%8==0
    check(all(pointer(ptr[k]) for k in ('moduleBase','classSlot','classPointer','functionsAddress','trailingWordsAddress')),'LIFECYCLE_POINTERS')
    layout={k:int(v,0) if isinstance(v,str) else v for k,v in profile['layout'].items()}
    n=c['slotCountBefore'];bounded=1<=n<=128
    check(bounded and n==c['slotCountAfter'],'LIFECYCLE_SLOT_COUNT')
    check(c['initializedBefore']==c['initializedAfter']==1,'LIFECYCLE_INITIALIZATION')
    check(ptr['classSlot']==ptr['moduleBase']+layout['GLT_CLASS_SLOT_RVA'] and layout['GLT_CLASS_SLOT_RVA']+8<=c['imageSize'] and
          ptr['functionsAddress']==ptr['classPointer']+layout['GLT_FUNCTIONS_OFFSET'] and ptr['trailingWordsAddress']==ptr['functionsAddress']+n*8,'LIFECYCLE_SPLIT_LAYOUT')
    check(ptr['expectedFunction']==ptr['moduleBase']+layout['GLT_TARGET_FUNCTION_RVA'] and layout['GLT_TARGET_FUNCTION_RVA']<c['imageSize'],'LIFECYCLE_TARGET')
    hits=[i for i,x in enumerate(functions[:n if bounded else 0]) if x==ptr['expectedFunction']]
    check(len(hits)==c['matchCount']==1 and c['matchIndex'] in hits,'LIFECYCLE_UNIQUE_BINDING')
    check(bounded and not any(functions[n:]) and not any(infos[n:]),'LIFECYCLE_UNUSED_SLOTS')
    check(0<c['bytesRead']<=1048576 and 0<c['readCalls']<=4096,'LIFECYCLE_READ_BUDGET')
    return {'ok':not errors,'reasons':errors,'status':STATUS.get(status,'unknown'),'flags':flags,'counts':c,
        'pointers':{k:hex(v) for k,v in ptr.items()},
        'slots':[{'index':i,'function':hex(functions[i]),'trailingWordOpaque':hex(infos[i])} for i in range(n if bounded else 0)],
        'source':'in-process-bounded-read-only-type-binding','gameMethodsCalled':0,'mutationAttempted':False,'allowWrites':False,
        'allocatedClassToCandidateFunctionVerified':not errors,'methodInfoSemanticsVerified':False,'reopenVerified':False,'completionVerified':False,
        'limits':'No coroutine instance was allocated or observed; adjacent words were copied without resolving their semantics; type binding does not prove a callable contract or load completion.'}
