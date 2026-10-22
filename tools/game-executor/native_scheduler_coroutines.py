"""Fixed read-only scheduler sample. No attribution, running state or completion claim."""
from pathlib import Path
import hashlib,json,re,struct
import native_profiles as profiles
PROFILE=Path(__file__).with_name('profiles')/'genshin-cn-7.1.0-scheduler-coroutines.json'
PROFILE_SHA256='dd74b97ae74ca8098448ef8e17651d816aaba4432491cb50210600170deec19d'
SCHEDULER_COROUTINES_BYTES=13472
REQUIRED_FLAGS=255
BOUNDS_OBSERVED_FAILURE=256
CAPACITY_SATURATED_FAILURE=512
STATUS={0:'ok',1:'baseline_refused',2:'anchor_mismatch',3:'unreadable',4:'structure_invalid',5:'limit',6:'unstable',7:'hotfix_active',8:'identity_or_initialization_changed'}
DISPOSITION={0:'null_handle',1:'null_holder',2:'released_holder',3:'unsupported_reference_kind',4:'null_iterator',5:'other_class',6:'other_owner',7:'target_iterator',8:'unavailable_holder_state',9:'other_handle_class'}

def load_profile():
    profiles.require(profiles.sha256(PROFILE)==PROFILE_SHA256,'SCHEDULER_PROFILE_CHANGED')
    p=json.loads(PROFILE.read_text(encoding='utf-8-sig'));base=profiles.load_profile()
    profiles.require(p['imageSha256']==base['image']['sha256'] and p['allowWrites'] is False and p['maxHandles']==128,'SCHEDULER_IMAGE_BINDING')
    for a in p['anchors']:
        raw=bytes.fromhex(a['bytes']);profiles.require(len(raw)==a['length'] and 0<len(raw)<=4096 and hashlib.sha256(raw).hexdigest()==a['sha256'],'SCHEDULER_ANCHOR_INVALID')
    return p

def append_header(run,p):
    values={'HR_READ_SCHEDULER_COROUTINES':1,'GSC_EXPECTED_LEVEL_ID':p['expectedLevelId'],**p['layout']}
    lines=['// Read-only scheduler sample; unavailable holders remain unavailable.']
    lines += ['#define '+k+' '+str(v)+'ULL' for k,v in values.items()]
    lines += ['#define GSC_ANCHOR_RVAS '+','.join(a['rva'] for a in p['anchors']),
        '#define GSC_ANCHOR_LENGTHS '+','.join(str(a['length']) for a in p['anchors']),
        '#define GSC_ANCHOR_BYTES '+','.join('{'+','.join(hex(b) for b in bytes.fromhex(a['bytes']))+'}' for a in p['anchors']),
        '#define GSC_HOTFIX_RVAS '+','.join(p['hotfixByteRvas'])]
    with (Path(run)/'target_config.h').open('a',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')

def _observation(record, context, raw, status, flags, counts, pointers, accepted):
    """Explain failed evidence without converting zeroed ABI fields into reads."""
    outer_matches = type(record.get('schedulerCoroutinesStatus')) is int and record['schedulerCoroutinesStatus'] == status
    entry_refused = outer_matches and status == 1 and flags == 0 and not any(raw[16:])
    dependencies = []
    if entry_refused:
        if context.get('status', {}).get('value') != 0 or context.get('levelObservation', {}).get('verified') is not True:
            dependencies.append({'component': 'context', 'reason': 'baseline_not_verified'})
        binding = context.get('lifecycleType', {})
        if binding.get('ok') is not True or binding.get('allocatedClassToCandidateFunctionVerified') is not True:
            dependencies.append({'component': 'lifecycleType', 'reason': 'type_binding_not_verified',
                                 'reportedStatus': binding.get('status', 'unknown')})
        if not dependencies:
            dependencies.append({'component': 'nativePrerequisites', 'reason': 'additional_native_input_check_refused'})
    # The native implementation publishes root pointers only after RootsRead succeeds.
    # Before then, even positive readCalls may only describe code/anchor reads.
    roots_published = outer_matches and bool(flags & 8) and 0 < counts['readCalls'] <= 4096 and 0 < counts['bytesRead'] <= 1048576
    root_fields_observed = roots_published and all(type(v) is int and 0x10000 <= v < 0x800000000000 and v % 8 == 0 for v in pointers.values())
    if entry_refused:
        state, measurement, reason = 'blocked', 'not_observed', 'prerequisite_rejected_before_scheduler_reads'
    elif accepted:
        state, measurement, reason = 'accepted', 'observed', 'complete_stable_sample'
    elif not outer_matches or (status == 1 and (flags != 0 or any(raw[16:]))):
        state, measurement, reason = 'invalid', 'unverified', 'inconsistent_receipt'
        root_fields_observed = False
    else:
        state, measurement, reason = 'failed', 'partial_or_unverified', 'scheduler_capture_' + STATUS.get(status, 'unknown')
    return {'state': state, 'measurement': measurement, 'reason': reason,
            'blockingDependencies': dependencies, 'readCalls': counts['readCalls'], 'bytesRead': counts['bytesRead'],
            'schedulerPointer': {'observed': root_fields_observed, 'value': hex(pointers['scheduler']) if root_fields_observed else None},
            'initializationState': 'validated_for_sample' if accepted else 'unknown',
            'rawPointersMeaning': 'zero_initialized_unobserved_output' if entry_refused else 'partial_abi_fields_not_individually_proven',
            'absenceProven': accepted and counts['targetCount'] == 0 and counts['unavailableCount'] == 0,
            'reopenAllowed': False, 'reopenVerified': False}


def diagnose_prerequisites(record, context, profile=None):
    """Pure offline diagnosis from one raw receipt; never grants action permission.

    The caller owns receipt provenance/freshness checks. This function redecodes
    both extensions and does not trust earlier JSON summaries or relax their gates.
    """
    import native_lifecycle_type as lifecycle_api
    lifecycle_profile = lifecycle_api.load_profile()
    local = dict(context)
    lifecycle = lifecycle_api.decode(record, local, lifecycle_profile)
    local['lifecycleType'] = lifecycle
    scheduler = decode(record, local, profile or load_profile())
    c = lifecycle['counts']; p = lifecycle['pointers']
    layout = {key: int(value, 0) if isinstance(value, str) else value for key, value in lifecycle_profile['layout'].items()}
    try:
        module_base = int(local.get('pointers', {}).get('moduleBase', ''), 16)
    except (TypeError, ValueError):
        module_base = None
    prefix_bound = (
        type(record.get('lifecycleTypeStatus')) is int and record['lifecycleTypeStatus'] == 8 and
        lifecycle['status'] == 'not_initialized' and
        local.get('status', {}).get('value') == 0 and local.get('levelObservation', {}).get('verified') is True and
        c['levelId'] == lifecycle_profile['expectedLevelId'] == local.get('levelObservation', {}).get('levelId') and
        c['imageSize'] == local.get('counts', {}).get('peImageSize') and
        module_base is not None and p['moduleBase'] == hex(module_base) and
        p['classSlot'] == hex(module_base + layout['GLT_CLASS_SLOT_RVA']) and
        p['expectedFunction'] == hex(module_base + layout['GLT_TARGET_FUNCTION_RVA']) and
        0 < c['readCalls'] <= 4096 and 0 < c['bytesRead'] <= 1048576 and
        0 <= c['initializedBefore'] <= 255 and c['initializedBefore'] != 1)
    unread_type_fields = (
        all(c[key] == 0 for key in ('initializedAfter', 'slotCountBefore', 'slotCountAfter', 'matchCount', 'parserError', 'reserved')) and
        c['matchIndex'] == 0xffffffff and all(p[key] == '0x0' for key in ('classPointer', 'functionsAddress', 'trailingWordsAddress')) and
        not any(bytes.fromhex(record['lifecycleTypeHex'])[112:]))
    # Bit 256 belongs only to the readonly metadata diagnostic: it never replaces
    # the initialization-ready bit 8 or permits the status-0 writer contract.
    slot_null_observed = prefix_bound and lifecycle['flags'] == 263 and c['initializedBefore'] == 0 and unread_type_fields
    type_binding_observed_only = (
        prefix_bound and lifecycle['flags'] == 503 and c['initializedBefore'] == c['initializedAfter'] == 0 and
        set(lifecycle['reasons']) == {'LIFECYCLE_STATUS_not_initialized', 'LIFECYCLE_FLAGS_OR_PARSER', 'LIFECYCLE_INITIALIZATION'})
    initialization_observed = prefix_bound and lifecycle['flags'] == 7 and unread_type_fields
    initialization_observed = initialization_observed or slot_null_observed or type_binding_observed_only
    type_slot_read = lifecycle['ok'] or slot_null_observed or type_binding_observed_only
    lifecycle_observation = {
        'state': 'accepted' if lifecycle['ok'] else 'failed',
        'reportedStatus': lifecycle['status'],
        'initializationFlag': {'observed': initialization_observed or lifecycle['ok'],
                               'value': c['initializedBefore'] if initialization_observed or lifecycle['ok'] else None},
        'classPointer': {'observed': type_slot_read, 'value': p['classPointer'] if type_slot_read else None},
        'allocatorLazyFlagObserved': initialization_observed or lifecycle['ok'],
        'typeSlotRead': type_slot_read, 'typeBindingObservedOnly': type_binding_observed_only,
        'stableReadback': lifecycle['ok'] or type_binding_observed_only,
        'readCalls': c['readCalls'], 'bytesRead': c['bytesRead'],
        'reason': 'wrapper_metadata_flag_not_set' if initialization_observed else ('type_binding_verified' if lifecycle['ok'] else 'type_binding_not_verified'),
        'fieldMeaning': 'wrapper_lazy_metadata_initialization_flag',
        'flagRva': lifecycle_profile['layout']['GLT_INITIALIZED_RVA'],
        'wrapperRva': '0x77c9d70',
        'limits': 'The wrapper metadata flag is not global lifecycle or scheduler initialization. Its value does not prove a null class pointer or why the flag is unset.'}
    scheduler_observation = scheduler['observation']
    root_causes = []
    if initialization_observed:
        root_causes.append({'component': 'lifecycleType', 'reason': 'wrapper_metadata_flag_not_set', 'observedValue': c['initializedBefore']})
    elif not lifecycle['ok']:
        root_causes.append({'component': 'lifecycleType', 'reason': 'type_binding_not_verified', 'reportedStatus': lifecycle['status']})
    if not scheduler['ok'] and scheduler_observation['state'] != 'blocked':
        root_causes.append({'component': 'schedulerCoroutines', 'reason': scheduler_observation['reason']})
    elif scheduler_observation['state'] == 'blocked' and not root_causes:
        root_causes.extend(scheduler_observation['blockingDependencies'])
    return {'schemaVersion': 1, 'scope': 'offline_prerequisite_diagnosis_only',
            'rootCauses': root_causes, 'lifecycleType': lifecycle_observation,
            'schedulerCoroutines': scheduler_observation,
            'checks': {'lifecycleAccepted': lifecycle['ok'], 'schedulerAccepted': scheduler['ok']},
            'reasons': lifecycle['reasons'] + scheduler['reasons'],
            'mutationAttempted': False, 'reopenAllowed': False, 'reopenVerified': False,
            'currentSessionVerified': False,
            'limits': 'Historical receipts explain that capture only. Recheck identity, freshness, complete prerequisites and review before any action.'}


def decode(record,context,profile):
    encoded=record.get('schedulerCoroutinesHex')
    profiles.require(isinstance(encoded,str) and len(encoded)==SCHEDULER_COROUTINES_BYTES*2 and re.fullmatch('[0-9a-fA-F]+',encoded) is not None,'SCHEDULER_HEX')
    profiles.require(type(record.get('schedulerCoroutinesBytes')) is int and record['schedulerCoroutinesBytes']==SCHEDULER_COROUTINES_BYTES,'SCHEDULER_ABI_SIZE')
    raw=bytes.fromhex(encoded);size,version,status,flags=struct.unpack_from('<4I',raw)
    profiles.require(size==SCHEDULER_COROUTINES_BYTES and version==1,'SCHEDULER_ABI_VERSION')
    pn=('moduleBase','global','scheduler','list','array','lifecycleOwner','targetClass','classSlot','managedTypesRoot','coroutineClass')
    ptr=dict(zip(pn,struct.unpack_from('<10Q',raw,16)))
    cn=('levelId','listCountBefore','listCountAfter','listCapacity','versionBefore','versionAfter','rowCount','targetCount','nullHandleCount','unavailableCount','otherCount','bytesRead','readCalls','typeSlotCount','referencePolicyBefore','referencePolicyAfter')
    c=dict(zip(cn,struct.unpack_from('<16I',raw,96)));n=c['rowCount'];profiles.require(n<=128,'SCHEDULER_ROW_COUNT')
    qn=('handle','handleClass','holder','iterator','iteratorClass','iteratorOwner','currentYield','holderNativeOwner','gcTokenOpaque')
    rn=('index','disposition','referenceKind','referenceCount','retainedByWrapper','released','state','reserved')
    rows=[]
    for i in range(n):
        row=dict(zip(qn,struct.unpack_from('<9Q',raw,160+i*104)));row.update(zip(rn,struct.unpack_from('<IIIiIIiI',raw,160+i*104+72)));rows.append(row)
    errors=[]
    def check(ok,reason):
        if not ok:errors.append(reason)
    def ptrvalid(x):return type(x) is int and 0x10000<=x<0x800000000000 and x%8==0
    def parsed(x):
        try:return int(x,16)
        except (ValueError,TypeError):return None
    observed_bounds=None
    if flags&BOUNDS_OBSERVED_FAILURE:
        saturated=bool(flags&CAPACITY_SATURATED_FAILURE)
        signed_count=struct.unpack_from('<i',raw,100)[0]
        refused_bounds=not 0<=signed_count<=128 or c['listCapacity']>0x7fffffff or signed_count>c['listCapacity']
        diagnostic_valid=(status==5 and record.get('schedulerCoroutinesStatus')==5 and
            flags==(7|BOUNDS_OBSERVED_FAILURE|(CAPACITY_SATURATED_FAILURE if saturated else 0)) and
            n==0 and not any(raw[160:]) and c['listCountAfter']==0 and c['versionAfter']==0 and
            c['referencePolicyAfter']==0 and c['referencePolicyBefore']<=255 and refused_bounds and
            (not saturated or c['listCapacity']==0xffffffff))
        check(diagnostic_valid,'SCHEDULER_FAILURE_DIAGNOSTIC_INVALID')
        if diagnostic_valid:
            observed_bounds={'source':'failure-only-first-pass-values','listCount':signed_count,
                'capacity':None if saturated else c['listCapacity'],'capacitySaturated':saturated,
                'capacityLowerBound':0x100000000 if saturated else c['listCapacity'],
                'capacityStoredUint32':c['listCapacity'],'listVersion':c['versionBefore'],
                'configuredMaxHandles':128,'stabilityVerified':False,'arrayEntriesRead':False}
    elif flags&CAPACITY_SATURATED_FAILURE:check(False,'SCHEDULER_FAILURE_DIAGNOSTIC_INVALID')
    binding=context.get('lifecycleType',{})
    check(status==0 and record.get('schedulerCoroutinesStatus')==status,'SCHEDULER_STATUS_'+STATUS.get(status,'unknown'))
    check(flags==REQUIRED_FLAGS and c['referencePolicyBefore']==c['referencePolicyAfter'] and c['referencePolicyBefore']<=255,'SCHEDULER_FLAGS_OR_RESERVED')
    check(context.get('status',{}).get('value')==0 and context.get('levelObservation',{}).get('verified') is True,'SCHEDULER_BASELINE')
    check(binding.get('ok') is True and binding.get('allocatedClassToCandidateFunctionVerified') is True,'SCHEDULER_CURRENT_TYPE_BINDING')
    check(c['levelId']==profile['expectedLevelId']==context.get('levelObservation',{}).get('levelId'),'SCHEDULER_LEVEL')
    check(ptr['moduleBase']==parsed(context.get('pointers',{}).get('moduleBase')) and ptr['global']==parsed(context.get('pointers',{}).get('global')),'SCHEDULER_ROOT_CONTEXT')
    check(ptr['targetClass']==parsed(binding.get('pointers',{}).get('classPointer')) and c['typeSlotCount']==binding.get('counts',{}).get('slotCountBefore') and 1<=c['typeSlotCount']<=128,'SCHEDULER_CLASS_BINDING')
    check(all(ptrvalid(v) for v in ptr.values()),'SCHEDULER_ROOT_POINTERS')
    check(ptr['classSlot']==ptr['moduleBase']+int(profile['layout']['GSC_CLASS_SLOT_RVA'],0),'SCHEDULER_CLASS_SLOT')
    check(n==c['listCountBefore']==c['listCountAfter'] and 0<=n<=128 and n<=c['listCapacity']<=0x7fffffff and c['versionBefore']==c['versionAfter'],'SCHEDULER_LIST_STABLE_COMPLETE')
    check(not any(raw[160+n*104:]),'SCHEDULER_UNUSED_ROWS')
    check(0<c['bytesRead']<=1048576 and 0<c['readCalls']<=4096,'SCHEDULER_READ_BUDGET')
    disposition_counts={i:0 for i in DISPOSITION}
    for i,row in enumerate(rows):
        check(row['index']==i and row['reserved']==0 and row['released']<=255,'SCHEDULER_ROW_HEADER_'+str(i))
        if not row['handle']:expected=0
        elif row['handleClass']!=ptr['coroutineClass']:expected=9
        elif not row['holder']:expected=1
        elif row['released']:expected=2
        elif row['referenceKind']!=2:expected=3
        elif row['retainedByWrapper']!=1 or row['referenceCount']<=0 or row['holder']==row['handle'] or (row['iterator'] and row['iterator'] in (row['handle'],row['holder'])):expected=8
        elif not row['iterator']:expected=4
        elif row['iteratorClass']!=ptr['targetClass']:expected=5
        elif row['iteratorOwner']!=ptr['lifecycleOwner']:expected=6
        else:expected=7
        check(row['disposition']==expected,'SCHEDULER_ROW_CLASSIFICATION_'+str(i));disposition_counts[expected]+=1
        if row['handle']:check(ptrvalid(row['handle']),'SCHEDULER_HANDLE_POINTER_'+str(i))
        if row['holder']:check(ptrvalid(row['holder']),'SCHEDULER_HOLDER_POINTER_'+str(i))
        if expected==0:check(all(row[k]==0 for k in qn) and all(row[k]==0 for k in rn if k!='index'),'SCHEDULER_NULL_HANDLE_FIELDS_'+str(i))
        if expected==1:check(all(row[k]==0 for k in qn if k not in ('handle','handleClass')) and all(row[k]==0 for k in rn if k not in ('index','disposition')),'SCHEDULER_NULL_HOLDER_FIELDS_'+str(i))
        if expected==9:check(all(row[k]==0 for k in qn if k not in ('handle','handleClass')) and all(row[k]==0 for k in rn if k not in ('index','disposition')),'SCHEDULER_UNKNOWN_HANDLE_FIELDS_'+str(i))
        if expected in (2,3,4,8):check(all(row[k]==0 for k in ('iteratorClass','iteratorOwner','currentYield','state')),'SCHEDULER_UNAVAILABLE_DEREFERENCE_'+str(i))
        if expected in (5,6,7):check(ptrvalid(row['iterator']) and ptrvalid(row['iteratorClass']),'SCHEDULER_ITERATOR_POINTER_'+str(i))
        if expected==5:check(all(row[k]==0 for k in ('iteratorOwner','currentYield','state')),'SCHEDULER_OTHER_CLASS_FIELDS_'+str(i))
    check(c['targetCount']==disposition_counts[7] and c['nullHandleCount']==disposition_counts[0] and
          c['unavailableCount']==sum(disposition_counts[i] for i in (1,2,3,4,8,9)) and c['otherCount']==disposition_counts[5]+disposition_counts[6] and
          n==c['targetCount']+c['nullHandleCount']+c['unavailableCount']+c['otherCount'],'SCHEDULER_SUMMARIES')
    displayed=[]
    for row in rows:
        entry={k:hex(row[k]) for k in qn};entry.update({k:row[k] for k in rn});entry['classification']=DISPOSITION.get(row['disposition'],'unknown')
        entry['stageObserved']=not errors and row['disposition']==7 and 0<=row['state']<=7
        entry['stateMeaning']='yield-stage-only' if entry['stageObserved'] else 'unavailable-or-unknown-no-completion-inference'
        displayed.append(entry)
    observation=_observation(record,context,raw,status,flags,c,ptr,not errors)
    return {'ok':not errors,'reasons':errors,'status':STATUS.get(status,'unknown'),'flags':flags,'counts':c,'pointers':{k:hex(v) for k,v in ptr.items()},'rows':displayed,'observedBounds':observed_bounds,
        'observation':observation,
        'instanceObserved':not errors and c['targetCount']>0,'targetMatchRows':c['targetCount'],
        'uniqueTargetIterators':len({row['iterator'] for row in rows if row['disposition']==7}),
        'duplicateNonNullHandles':len([row['handle'] for row in rows if row['handle']])-len({row['handle'] for row in rows if row['handle']}),
        'duplicateTargetIteratorRows':c['targetCount']-len({row['iterator'] for row in rows if row['disposition']==7}),'allListedReferencesInterpretable':not errors and c['unavailableCount']==0,
        'sampleStable':not errors,'logicalListComplete':not errors,'unusedCapacityRead':False,'source':'in-process-bounded-read-only-scheduler-sample','gameMethodsCalled':0,'allowWrites':False,'mutationAttempted':False,
        'completionVerified':False,'requestAttributionVerified':False,'reopenVerified':False,
        'limits':'Stable sample of the first listCount logical handles only (maximum 128); unused allocated capacity is not read. Unknown or released holders are unavailable; no GC token is resolved. Absence, state -1/7, release and list disappearance do not prove completion or a particular request.'}
