"""Independent fixed trial-card decoding and bounded provenance, no live calls."""
import struct
from contract import require,extension,interpretation
OPERATIONS={'trial-state':3,'enter-request':4,'enter-start':5,'exit-request':6,'exit-return':7,'trial-frame':8}
PNG_OFFSET=864
CAPACITY=8*1024*1024
SIZE=PNG_OFFSET+CAPACITY
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','actionAttempted','actionReturned','stateStable','precondition')
HEADER+=('frameBefore','frameAfter','renderedBefore','renderedAfter','width','height','pngBytes','frameStatus')
POINTERS=('global','editor','task','room','cache','data','settleManager','settleContext','settleData','model','settings','loadTask','cacheEditData','taskEditData','coroutine')
NUMBERS=('editorLevel','sceneId','taskType','taskPhase','token','roomToken','ownerUid','localUid','editing','isTrial','cacheIsTrial','currentIsTrial','multi','loadPhase','remakeCount','settleTrial','settleHidden','sceneType','readable','entryReady','trialReady','exitReady','avatarActive','reserved')

def parse(raw):
    require(len(raw)==SIZE,'CONTROL_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<20I',raw)))
    require(o['bytes']==SIZE and o['version']==2 and o['operation'] in OPERATIONS.values(),'CONTROL_ABI_VERSION')
    require(not any(raw[80:96]),'CONTROL_RESERVED')
    require(all(o[k] in (0,1) for k in ('resourcesReleased','actionAttempted','actionReturned','stateStable')),'CONTROL_ENUM')
    require(o['actionReturned']<=o['actionAttempted'],'ACTION_RETURN_WITHOUT_ATTEMPT')
    require(o['operation'] not in (3,8) or o['actionAttempted']==0,'OBSERVATION_MUTATION')
    require(o['pngBytes']<=CAPACITY,'FRAME_CAPACITY')
    if o['operation']!=8:require(not any(raw[48:80]),'NONFRAME_HEADER_DATA')
    require(not any(raw[PNG_OFFSET+o['pngBytes']:]),'UNUSED_FRAME_DATA')
    o['png']=raw[PNG_OFFSET:PNG_OFFSET+o['pngBytes']]
    o['observation']=extension(raw[96:432])
    for key,at in (('before',432),('after',648)):
        s=dict(zip(POINTERS,struct.unpack_from('<15Q',raw,at)));s.update(zip(NUMBERS,struct.unpack_from('<24I',raw,at+120)))
        require(s['reserved']==0 and s['readable']<=1023,'TRIAL_STATE_RESERVED')
        require(all(s[k] in (0,1) for k in ('isTrial','cacheIsTrial','currentIsTrial','multi','settleTrial','settleHidden','entryReady','trialReady','exitReady','avatarActive')),'TRIAL_STATE_ENUM')
        o[key]=s
    if o['stage']==3:require(o['stateStable']==int(o['before']==o['after']),'TRIAL_STABILITY_MISMATCH')
    return o

def origin_matches(state,binding):
    return all(state[k]==binding[k] for k in ('global','editor','task'))

def trial_matches(state,binding):
    return origin_matches(state,binding) and state['token']==state['roomToken']==binding['token'] and state['cache']==binding['cache'] and state['cacheEditData']==binding['cacheEditData']

def validate_state(s,target):
    for bit,fields in ((1,('task',)),(2,('room',)),(4,('localUid',)),(16,('cache','cacheEditData')),(32,('data',)),(256,('settleManager','settleContext','settleData'))):
        if s['readable']&bit:require(all(s[x] for x in fields),'TRIAL_READABLE_POINTER_MISMATCH')
    host=bool(s['readable']&4 and s['ownerUid']==s['localUid'])
    entry=bool(s['readable']&31==31 and s['editing']==1 and s['sceneId']==0xb993 and s['editorLevel']==target and not s['coroutine'] and s['taskType']==1 and s['taskPhase']==9 and s['token'] and s['token']==s['roomToken'] and not s['multi'] and host and s['cacheIsTrial'] and s['model'] and s['settings'])
    play=bool(s['readable']&0x27e==0x27e and s['sceneType']==5 and s['editing']==0 and s['isTrial'] and s['currentIsTrial'] and s['cacheIsTrial'] and s['cache']==s['data'] and s['token'] and s['roomToken']==s['token'] and not s['multi'] and host and (not s['loadTask'] or s['loadPhase']==10) and s['avatarActive'])
    settle=bool(s['readable']&256 and s['settleTrial'] and not s['settleHidden'] and s['isTrial'] and s['data']==s['cache'] and s['token'] and s['token']==s['roomToken'] and not s['multi'])
    require((s['entryReady'],s['trialReady'],s['exitReady'])==(int(entry),int(play),int(settle)),'TRIAL_POSITIVE_GUARD_MISMATCH')

def interpretation_control(o,prepared):
    base=interpretation(o['observation'],prepared['targetLevelId']);s=o['after'];binding=prepared.get('binding',{})
    for state in (o['before'],s):validate_state(state,prepared['targetLevelId'])
    sample=o['observation']['after']
    for field,observed in (('global','global'),('editor','editorManager'),('editorLevel','editorLevel'),('sceneId','rawMode'),('editing','editing')):require(s[field]==sample[observed],'TRIAL_OBSERVER_IDENTITY_MISMATCH')
    coherent=o['stateStable']==1 and o['observation']['stable']==1
    bound=bool(binding and coherent and trial_matches(s,binding))
    play=bound and s['trialReady']==1
    settle=bound and s['exitReady']==1 and s['settleData']!=binding.get('initialSettleData',0)
    entered=bool(prepared.get('lineage') and 'enter-start' in prepared['lineage']['attemptedOperations'])
    if settle and entered:base.update(mode='settlement',modeEvidence='bound-trial-settlement-context-and-data',playerBelongsToTargetLevel=None)
    elif play and entered:
        base.update(mode='play',modeEvidence='official-single-trial-token-cache-chain-and-loaded-local-avatar',playStateProven=True,playerBelongsToTargetLevel=True,attribution='this official entry task exported target editor; server token and loaded trial cache remain bound')
    elif not coherent:base.update(mode='transition',modeEvidence='state-changed-between-independent-samples',playerBelongsToTargetLevel=None)
    base.update(enterSupported=True,exitSupported=True,controlBlocker=None,trialState=s,trialIdentityBound=bound,actionAttempted=bool(o['actionAttempted']),actionReturned=bool(o['actionReturned']),asynchronousActionComplete=False,playerContactVerified=False,naturalInteractionVerified=False,monsterHealthVerified=False,monsterAiVerified=False,officialTemporaryTrialUpload=prepared['mode']=='enter-request',publicationRequested=False)
    if prepared['mode']=='trial-state' and play and entered and not settle:base['asynchronousActionComplete']=True
    returned=base['mode']=='editor' and base['editorIsTargetLevel'] is True and binding and origin_matches(s,binding)
    exit_requested='exit-request' in prepared.get('lineage',{}).get('attemptedOperations',[])
    base['returnToOriginalEditorVerified']=bool(returned and exit_requested)
    base['businessPending']=bool(o['actionAttempted'] or ('enter-start' in prepared.get('lineage',{}).get('attemptedOperations',[]) and base['mode'] not in ('play','settlement','editor')))
    if prepared['mode']=='trial-frame':
        from acceptance_contract import png_info
        require(base['mode']=='play' and entered and o['frameStatus']==0 and o['resourcesReleased']==1,'TRIAL_FRAME_BINDING')
        base.update(renderFrameCaptured=True,frameSource='Unity ScreenCapture game backbuffer; superSize=1',frameFreshness='not-guaranteed; engine frame counters attached',frameCounters={k:o[k] for k in ('frameBefore','frameAfter','renderedBefore','renderedAfter')},png=png_info(o['png'],o['width'],o['height']),visualAcceptanceVerified=False)
    return base

def next_operation(direction,result,attempted):
    """No retry branch for an attempted mutation, including unknown outcomes."""
    require(direction in ('enter','exit'),'CONTROL_DIRECTION')
    require(result.get('ok') is True and result.get('safeToRelease') is True and result.get('outcomeUncertain') is False,'PRIOR_CARD_NOT_CLEAN')
    s=result.get('trialState',{});bound=result.get('trialIdentityBound') is True
    if direction=='enter':
        if result.get('mode')=='play' and bound:return 'complete'
        if 'enter-start' not in attempted and s.get('entryReady')==1:return 'enter-start'
        require(s.get('taskPhase') not in (11,12),'OFFICIAL_ENTRY_VALIDATION_OR_UPLOAD_FAILED')
        return 'trial-state'
    if result.get('returnToOriginalEditorVerified') is True:return 'complete'
    if 'exit-request' not in attempted:
        require(result.get('mode')=='play' and bound,'EXIT_REQUIRES_BOUND_LIVE_TRIAL')
        return 'exit-request'
    if result.get('mode')=='settlement' and bound and 'exit-return' not in attempted:return 'exit-return'
    return 'trial-state'
