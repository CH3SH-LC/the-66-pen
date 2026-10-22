"""Offline guard profile verification and strict fixed-ABI decoder. No process access on import or call."""
from pathlib import Path
import hashlib,json,struct,re
import native_profiles as profiles
HERE=Path(__file__).resolve().parent
PROFILE=HERE/'profiles/genshin-cn-7.1.0-reopen-guards.json'
HEADER=HERE/'native/guard_profile.generated.h'
PROFILE_SHA256='e0d4f8a04134f400fecd3ecd3561e751924c4986934a446400a660352da53baa'
IMAGE_SHA256='7f89938da606c1281659607d464702cddb9a09a7d4320a196630f60a811ec38e'
HEADER_SHA256='c6b02e52099e23ded49a428ffdbfe67c0842fd52f5a6b667e374ef6057b67d38'
LEGACY_RESULT_BYTES=168
RESULT_BYTES=208
LOOKUP_STAGE={0:'none-recorded',1:'mode-comparer',2:'mode-capacity',3:'mode-counts',4:'mode-chain',5:'mode-visit-limit',6:'mode-key-not-found',7:'mode-read'}
STATUS={0:'evaluated',1:'input_refused',2:'anchor_mismatch',3:'unreadable',4:'invalid_structure',5:'limit',6:'unstable',7:'hotfix_active',8:'uninitialized',9:'unknown_branch'}
VALUE={0:'unknown',1:False,2:True}

def require(ok,reason):
    if not ok:raise ValueError(reason)

def load_profile(path=PROFILE):
    raw=Path(path).read_bytes();require(hashlib.sha256(raw).hexdigest()==PROFILE_SHA256,'PROFILE_CHANGED')
    require(hashlib.sha256(HEADER.read_bytes()).hexdigest()==HEADER_SHA256,'GENERATED_HEADER_CHANGED')
    p=json.loads(raw);require(p['imageSha256']==IMAGE_SHA256 and p['allowWrites'] is False and p['allowGameMethodCalls'] is False,'PROFILE_MODE')
    require(len(p['anchors'])==6 and p['limits']['dictionaryCapacity']==0x7fffffff and p['limits']['lookupVisitedEntries']==512,'PROFILE_BOUNDS')
    for a in p['anchors']:
        b=bytes.fromhex(a['bytes']);require(len(b)==a['length'] and 0<len(b)<=2048 and hashlib.sha256(b).hexdigest()==a['sha256'],'ANCHOR_BYTES')
    return p

def verify_disk_image(path):
    # Explicit disk-only operation, never a substituted live-module attestation.
    with Path(path).open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    require(sha==IMAGE_SHA256,'IMAGE_CHANGED');return {'diskImageSha256':sha,'liveImageVerified':False}

def decode_raw(raw,*,invocation,module_base,global_root,current_record,scheduler_status,scheduler_flags):
    p=load_profile();require(type(raw) is bytes and len(raw) in (LEGACY_RESULT_BYTES,RESULT_BYTES),'GUARD_ABI_SIZE')
    prefix=dict(zip(('size','version','status','flags','confirmation','earlyAbort','confirmationReason','earlyReason'),struct.unpack_from('<8I',raw)))
    ptr=dict(zip(('invocation','moduleBase','global','currentRecord','modeRecord','modeDictionary','table'),struct.unpack_from('<7Q',raw,32)))
    cnt=dict(zip(('levelId','modeId','modeEncoded','xorKey','decoded','tableLength','modeLiveEntries','parserError','schedulerTargetCount','schedulerUnavailableCount','schedulerRows','readCalls','readBytes','recheckCalls','recheckBytes','reserved','schedulerStatus','schedulerFlags','schedulerComplete','reserved2'),struct.unpack_from('<20I',raw,88)))
    require((prefix['size'],prefix['version'],len(raw)) in ((LEGACY_RESULT_BYTES,1,LEGACY_RESULT_BYTES),(RESULT_BYTES,2,RESULT_BYTES)),'GUARD_ABI_VERSION')
    require(prefix['status'] in STATUS and prefix['flags']&~15==0 and prefix['confirmation'] in VALUE and prefix['earlyAbort'] in VALUE,'GUARD_ENUM')
    require(not cnt['reserved'] and not cnt['reserved2'],'GUARD_RESERVED')
    errors=[]
    def check(ok,why):
        if not ok:errors.append(why)
    check(type(invocation) is int and invocation>0 and ptr['invocation']==invocation,'INVOCATION_MISMATCH')
    check(ptr['moduleBase']==module_base and ptr['global']==global_root and ptr['currentRecord']==current_record,'INPUT_POINTER_BINDING')
    check(cnt['levelId']==p['expectedLevelId'],'LEVEL_BINDING')
    check(cnt['schedulerStatus']==scheduler_status and cnt['schedulerFlags']==scheduler_flags,'SCHEDULER_RECEIPT_BINDING')
    check(cnt['schedulerComplete']==int(scheduler_status==0),'SCHEDULER_COMPLETENESS_BINDING')
    check(0<=cnt['schedulerStatus']<=8 and cnt['schedulerFlags']&~1023==0 and (not cnt['schedulerFlags']&768 or cnt['schedulerStatus']==5 and cnt['schedulerFlags'] in (263,775)),'SCHEDULER_DIAGNOSTIC_FLAGS')
    check(cnt['readCalls']<=2048 and cnt['readBytes']<=131072 and cnt['recheckCalls']<=cnt['readCalls'] and cnt['recheckBytes']<=cnt['readBytes'],'READ_BUDGET')
    stable=prefix['flags']==15
    if stable:
        check(0<cnt['readCalls']==cnt['recheckCalls'] and 0<cnt['readBytes']==cnt['recheckBytes'],'STABILITY_RECHECK')
        check(prefix['status'] in (0,8,9),'STABLE_STATUS')
    else:
        check(prefix['confirmation']==prefix['earlyAbort']==0,'UNVERIFIED_BOOLEAN')
    complete=stable and prefix['status']==0
    if complete:
        check(prefix['confirmation'] in (1,2) and prefix['earlyAbort']==1,'COMPLETE_DECISION')
        check(cnt['modeId']==0xb993 and cnt['decoded']!=0 and 0x800<=cnt['tableLength']<=65536 and (1<=cnt['modeLiveEntries']<=512 if prefix['version']==1 else cnt['modeLiveEntries']==0) and not cnt['parserError'],'FAST_FALSE_INPUTS')
    diagnostic=None
    if prefix['version']==2:
        names=('observed','lookupRefusalStage','bucketCapacity','entryCapacity','count','freeCount','version','visitedEntries')
        d=dict(zip(names,struct.unpack_from('<IIQQiiII',raw,168)))
        check(d['observed'] in (0,1) and d['lookupRefusalStage'] in LOOKUP_STAGE and d['visitedEntries']<=512,'MODE_DIAGNOSTIC_HEADER')
        if complete:check(d['observed']==1 and d['lookupRefusalStage']==0 and 1<=d['bucketCapacity']<=0x7fffffff and 1<=d['entryCapacity']<=0x7fffffff and 0<=d['freeCount']<=d['count']<=d['entryCapacity'] and 1<=d['visitedEntries']<=512,'MODE_COMPLETE_METADATA')
        if not d['observed']:check(not any(raw[168:]),'MODE_DIAGNOSTIC_NOT_OBSERVED')
        else:
            if d['lookupRefusalStage']==2:
                check(prefix['status']==5 and prefix['flags']==7 and not cnt['recheckCalls'] and not cnt['recheckBytes'] and
                    (not d['bucketCapacity'] or not d['entryCapacity'] or d['bucketCapacity']>0x7fffffff or d['entryCapacity']>0x7fffffff),'MODE_CAPACITY_DIAGNOSTIC')
            if d['lookupRefusalStage']==3:
                check(prefix['status']==4 and prefix['flags']==7 and 1<=d['bucketCapacity']<=0x7fffffff and 1<=d['entryCapacity']<=0x7fffffff and
                    (d['count']<0 or d['freeCount']<0 or d['freeCount']>d['count'] or d['count']>d['entryCapacity']),'MODE_COUNTS_DIAGNOSTIC')
            if complete:check(d['lookupRefusalStage']==0 and 1<=d['visitedEntries']<=512,'MODE_LOOKUP_COMPLETENESS')
            if d['lookupRefusalStage']==5:check(prefix['status']==5 and d['visitedEntries']==512,'MODE_LOOKUP_VISIT_LIMIT')
            diagnostic={k:v for k,v in d.items() if k!='observed'}
            diagnostic['lookupRefusalStage']=LOOKUP_STAGE.get(d['lookupRefusalStage'],'invalid')
            diagnostic['stabilityVerified']=stable and not errors
            diagnostic['contentsRead']=False if d['lookupRefusalStage'] in (1,2,3) else None
            diagnostic['scope']='already-read metadata and visited-chain count; not full dictionary completeness or permission'
    cf=VALUE[prefix['confirmation']] if stable and not errors else 'unknown' 
    ef=VALUE[prefix['earlyAbort']] if stable and not errors else 'unknown'
    return {'receiptValid':not errors,'errors':errors,'status':STATUS[prefix['status']],'stableReadback':stable and not errors,
            'modeLookup':{'complete':complete and not errors,'fullDictionaryVerified':False,'method':'bounded-default-comparer-target-bucket-chain' if prefix['version']==2 else 'legacy-full-dictionary-walk'},'guardAbiVersion':prefix['version'],'modeDictionaryDiagnostic':diagnostic,'confirmation':cf,'earlyAbort':ef,'bothFalseProven':complete and not errors and cf is False and ef is False,
            'scheduler':{'status':cnt['schedulerStatus'],'flags':cnt['schedulerFlags'],'complete':bool(cnt['schedulerComplete']),
                         'targetCount':cnt['schedulerTargetCount'],'unavailableCount':cnt['schedulerUnavailableCount'],'absenceProven':False},
            'counts':cnt,'pointers':{k:hex(v) for k,v in ptr.items()},'confirmationReason':prefix['confirmationReason'],'earlyReason':prefix['earlyReason'],
            'gameMethodsCalled':0,'mutationAttempted':False,'allowWrites':False,'reopenInvoked':False,'reopenVerified':False,
            'limitation':'Same-callback capture bundle provides input provenance. Stable repeated reads are not an atomic snapshot or permission to act.'}


def append_header(run,p):
    require(p['imageSha256']==IMAGE_SHA256,'REOPEN_IMAGE_BINDING')
    with (Path(run)/'target_config.h').open('a',encoding='utf-8',newline='\n') as f:
        f.write('// Same-callback read-only reopen guard bundle.\n#define HR_READ_REOPEN_GUARDS 1ULL\n')

def decode(record,context,profile,prepared):
    encoded=record.get('reopenGuardsHex')
    require(isinstance(encoded,str) and len(encoded) in (LEGACY_RESULT_BYTES*2,RESULT_BYTES*2) and re.fullmatch('[0-9a-fA-F]+',encoded),'REOPEN_GUARDS_HEX')
    require(type(record.get('reopenGuardsBytes')) is int and record['reopenGuardsBytes'] in (LEGACY_RESULT_BYTES,RESULT_BYTES) and record['reopenGuardsBytes']*2==len(encoded),'REOPEN_GUARDS_ABI_SIZE')
    raw=bytes.fromhex(encoded);catalog=context.get('levelCatalog',{});lifecycle=context.get('lifecycleType',{});scheduler=context.get('schedulerCoroutines',{})
    rows=[r for r in catalog.get('levels',[]) if r.get('id')==profile['expectedLevelId']]
    def pointer(value):
        try:return int(value,16)
        except (ValueError,TypeError):return 0
    value=decode_raw(raw,invocation=prepared.get('nativeDefinitions',{}).get('HR_NONCE'),
        module_base=pointer(context.get('pointers',{}).get('moduleBase')),global_root=pointer(context.get('pointers',{}).get('global')),
        current_record=rows[0]['record'] if len(rows)==1 else 0,
        scheduler_status=record.get('schedulerCoroutinesStatus'),scheduler_flags=scheduler.get('flags'))
    errors=value['errors']
    def check(ok,reason):
        if not ok:errors.append(reason)
    session=prepared.get('session',{});defs=prepared.get('nativeDefinitions',{})
    check(session.get('pid')==profile['expectedProcessId']==record.get('pid')==defs.get('HR_TARGET_PID') and
          session.get('processCreation')==profile['expectedProcessCreation']==defs.get('HR_TARGET_CREATION') and
          session.get('tid')==record.get('tid')==defs.get('HR_TARGET_TID'),'REOPEN_IDENTITY_BINDING')
    check(context.get('status',{}).get('value')==0 and catalog.get('ok') is True and lifecycle.get('ok') is True and len(rows)==1,'REOPEN_PREREQUISITE_BINDING')
    check(record.get('reopenGuardsStatus')==struct.unpack_from('<I',raw,8)[0],'REOPEN_STATUS_BINDING')
    check(record.get('schedulerCoroutinesStatus')!=0 or scheduler.get('ok') is True,'REOPEN_SCHEDULER_SUCCESS_BINDING')
    if errors:
        value['receiptValid']=False;value['stableReadback']=False;value['confirmation']='unknown';value['earlyAbort']='unknown';value['bothFalseProven']=False
    value['ok']=value['receiptValid'] and value['stableReadback'] and value['status']=='evaluated'
    value['reasons']=list(errors)
    if not value['ok'] and not errors:value['reasons'].append('REOPEN_GUARDS_'+value['status'].upper())
    return value
