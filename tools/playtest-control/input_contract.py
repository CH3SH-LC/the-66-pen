"""Bounded native player input. Binary parsing is independent of dispatch."""
import math,re,struct
from control_contract import SIZE as CONTROL_SIZE,parse as parse_control,trial_matches,validate_state,interpretation_control
from contract import require
OPERATIONS={'input-state':9,'move-pulse':10,'attack-tap':11,'interact-option':12}
SIZE=CONTROL_SIZE+26312
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','actionAttempted','actionReturned','callbacks','points','options','stopReason','released','releaseAttempted')
POINTERS=('avatar','manager','component','inputState','mainContext','view','actionPanel','inteePanel','button')
NUMBERS=('avatarId','attackSlot','attackAction','optionIndex','optionComplete','inputEnabled','sourceIdle','reserved1')
def plan(args):
    operation=args.operation;require(operation in OPERATIONS,'INPUT_OPERATION')
    identity=getattr(args,'input_id',None)
    if operation!='input-state':require(isinstance(identity,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',identity),'INPUT_ID_REQUIRED')
    else:require(identity is None,'READ_ONLY_INPUT_HAS_NO_ID')
    angle=getattr(args,'angle',0.0);strength=getattr(args,'strength',0.5);duration=getattr(args,'duration_ms',500);distance=getattr(args,'max_distance',2.0)
    require(all(type(x) in (int,float) and math.isfinite(x) for x in (angle,strength,distance)),'FINITE_INPUT_PLAN')
    require(-180<=angle<=180 and 0.1<=strength<=1 and type(duration) is int and 16<=duration<=3000 and 0.1<=distance<=8,'BOUNDED_INPUT_PLAN')
    label=getattr(args,'label',None);index=getattr(args,'option_index',None)
    if operation=='interact-option':
        require(type(index) is int and 0<=index<64 and isinstance(label,str) and label and '\x00' not in label and len(label.encode('utf-16-le'))<=254,'EXACT_OPTION_LABEL_AND_INDEX_REQUIRED')
    else:require(label is None and index is None,'OPTION_ARGUMENT_FOR_WRONG_ACTION')
    return dict(inputId=identity,angle=float(angle),strength=float(strength),durationMs=duration,maxDistance=float(distance),label=label,optionIndex=index)
def parse(raw):
    require(len(raw)==SIZE,'INPUT_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<16I',raw)))
    require(o['bytes']==SIZE and o['version']==3 and o['operation'] in OPERATIONS.values(),'INPUT_ABI_VERSION')
    o.update(zip(('startedTick','lastTick','firstFrame','lastFrame','pressAccepted','reserved'),struct.unpack_from('<2Q4I',raw,64)))
    require(o['reserved']==0 and o['points']<=192 and o['options']<=64 and o['callbacks']<=4096,'INPUT_BOUNDS')
    require(all(o[x] in (0,1) for x in ('resourcesReleased','actionAttempted','actionReturned','released','releaseAttempted','pressAccepted')),'INPUT_ENUM')
    require(o['actionReturned']<=o['actionAttempted'],'INPUT_RETURN_WITHOUT_ATTEMPT')
    require(o['operation']!=9 or o['actionAttempted']==0,'READ_ONLY_INPUT_MUTATION')
    at=96;o['control']=parse_control(raw[at:at+CONTROL_SIZE]);at+=CONTROL_SIZE
    require(o['control']['operation']==3 and not o['control'].pop('png'),'INPUT_HAS_NO_RENDER_PAYLOAD')
    o.update(zip(POINTERS,struct.unpack_from('<9Q',raw,at)));at+=72;o.update(zip(NUMBERS,struct.unpack_from('<8I',raw,at)));at+=32
    require(not o['reserved1'] and o['sourceIdle'] in (0,1) and o['optionComplete'] in (0,1) and o['inputEnabled'] in (0,1),'INPUT_METADATA_RESERVED')
    options=[]
    for i in range(64):
        row=raw[at:at+288];at+=288
        if i>=o['options']:continue # Partial reads retain the rejected row for diagnosis.
        item,button,index,active,enabled,n=struct.unpack_from('<2Q4I',row)
        require(index==i and active in (0,1) and enabled in (0,1) and n<=127,'INPUT_OPTION_SHAPE')
        text=row[32:32+2*n].decode('utf-16-le',errors='strict');require(not any(row[32+2*n:]),'INPUT_OPTION_PADDING')
        options.append(dict(item=item,button=button,index=index,active=bool(active),enabled=bool(enabled),text=text))
    points=[]
    for i in range(192):
        row=raw[at:at+40];at+=40
        if i>=o['points']:require(not any(row),'INPUT_POINT_PADDING');continue
        tick,frame,flags,x,y,z,strength,angle,reserved=struct.unpack('<Q2I5fI',row)
        require(reserved==0 and flags in (0,1) and all(math.isfinite(q) for q in (x,y,z,strength,angle)),'INPUT_POINT_FINITE')
        require(not points or tick>=points[-1]['tick'],'INPUT_POINT_TIME_ORDER')
        points.append(dict(tick=tick,frame=frame,flags=flags,world=[x,y,z],strength=strength,angle=angle))
    o['optionRows']=options;o['trajectory']=points;return o
def interpretation(o,card):
    observed=interpretation_control(o['control'],card)
    require(observed.get('mode')=='play' and observed.get('playStateProven') is True,'INPUT_TRIAL_BINDING')
    state=o['control']['after'];validate_state(state,card['targetLevelId'])
    require(o['control']['status']==0 and o['control']['stateStable']==1 and o['control']['observation']['stable']==1 and state['trialReady']==1 and state['exitReady']==0 and trial_matches(state,card['binding']),'INPUT_TRIAL_BINDING')
    sample=o['control']['observation']['after'];require(o['avatar']==sample['avatar'] and o['avatarId']==sample['avatarId'] and sample['avatarStatus']==2 and sample['positionStatus']==0,'INPUT_AVATAR_BINDING')
    require('enter-start' in card['lineage']['attemptedOperations'] and 'exit-request' not in card['lineage']['attemptedOperations'],'INPUT_REQUIRES_ENTERED_TRIAL')
    require(o['inputEnabled']==1,'INPUT_DISABLED')
    if card['mode']!='input-state':
        old=card['inputBinding'];require(all(o[k]==old[k] for k in ('avatar','avatarId','component','mainContext','view')),'INPUT_BASELINE_IDENTITY')
        require(o['actionAttempted']==o['actionReturned']==o['released']==1,'INPUT_CALL_OR_RELEASE_INCOMPLETE')
    if card['mode']=='attack-tap':require(o['attackAction']==0x167 and o['pressAccepted']==1 and o['button']==card['inputBinding']['button'],'ATTACK_INPUT_NOT_ACCEPTED')
    if card['mode']=='move-pulse':require(o['sourceIdle']==1,'MOVEMENT_SOURCE_NOT_RELEASED')
    if card['mode']=='interact-option':
        p=card['inputPlan'];require(o['optionComplete']==1 and p['optionIndex']<len(o['optionRows']),'OPTION_LIST_INCOMPLETE')
        row=o['optionRows'][p['optionIndex']];require(row['text']==p['label'] and row['item']==card['inputBinding']['item'] and row['button']==card['inputBinding']['button'] and row['active'] and row['enabled'],'EXACT_OPTION_CHANGED')
    trajectory=o['trajectory'];displacement=None
    if len(trajectory)>1:displacement=[trajectory[-1]['world'][i]-trajectory[0]['world'][i] for i in range(3)]
    return dict(mode='play',trialIdentityBound=True,playerBelongsToTargetLevel=True,inputEnabled=True,inputSourceIdle=bool(o['sourceIdle']),avatarId=o['avatarId'],worldPosition=sample['worldPosition'],options=o['optionRows'],optionsComplete=bool(o['optionComplete']),attackAvailable=bool(o['button'] and o['attackAction']==0x167),trajectory=trajectory,displacement=displacement,nativeInputSubmitted=bool(o['actionReturned']),inputReleased=bool(o['released']),actualPlayerMotionObserved=bool(displacement and sum(q*q for q in displacement)>0.0001),playerContactVerified=False,damageVerified=False,naturalInteractionVerified=False,interactionCallbackSubmitted=card['mode']=='interact-option' and bool(o['actionReturned']),movementSource='normal joystick delegate and engine input Tick; no transform writes',inputEvidenceOnly=True)
