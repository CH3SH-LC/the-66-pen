"""v10 atomic native menu target. Raw identity and source membership are required."""
import re,struct
import directory_contract as d
import contact_contract as c
from contract import require
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','actionAttempted','actionReturned','guardVerified','optionOrdinal','editorGuid','runtimeId','stopReason','reserved')
INPUT_POINTERS=('avatar','manager','component','inputState','context','view','componentClass','expectedClass','componentOwner','managedAvatar','strengthSlot','activeSlot')
INPUT_NUMBERS=('avatarId','disabled','owned','blocked','sourceActive','valid','frame','reserved')
DIRECTORY_AT=96;OPTION_AT=DIRECTORY_AT+d.SIZE;SOURCE_AT=OPTION_AT+496;INPUT_AT=SOURCE_AT+32;SIZE=INPUT_AT+128

def plan(args):
    require(args.operation=='targeted-interact','TARGETED_OPERATION')
    key=getattr(args,'target_id',None);guid=getattr(args,'expected_editor_guid',None);runtime=getattr(args,'expected_runtime_id',None);ordinal=getattr(args,'option_index',None);label=getattr(args,'label',None)
    require(isinstance(key,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',key),'TARGETED_ID')
    require(type(guid) is int and 1<=guid<=0xffffffff and type(runtime) is int and 1<=runtime<=0xffffffff,'TARGETED_IDENTITIES')
    require(type(ordinal) is int and 0<=ordinal<64,'TARGETED_ORDINAL')
    require(isinstance(label,str) and 0<len(label.encode('utf-16-le'))<=254 and '\x00' not in label,'TARGETED_LABEL')
    return dict(targetId=key,editorGuid=guid,runtimeId=runtime,optionIndex=ordinal,label=label)

def selected(result,p):
    require(result.get('ok') is True and result.get('safeToRelease') is True and result.get('outcomeUncertain') is False and result.get('trialIdentityBound') is True and result.get('sourceDirectoryKnown') is True and result.get('interactionOptionsKnown') is True,'TARGETED_BASELINE_NOT_CLEAN')
    require(p['optionIndex']<len(result['interactionOptions']),'TARGETED_OPTION_MISSING');row=result['interactionOptions'][p['optionIndex']]
    require(row['active']==1 and row['enabled']==1 and row['text']==p['label'] and row['hostRuntimeIdentityVerified'] and row['hostIdentityVerified'] and row['hostTrialMembershipVerified'],'TARGETED_OPTION_UNKNOWN')
    require(row['host']['editorEntityGuid']==p['editorGuid'] and row['ownerRuntimeId']==row['host']['runtimeId']==p['runtimeId'],'TARGETED_HOST_MISMATCH')
    return row

def parse(raw):
    require(len(raw)==SIZE,'TARGETED_ABI_SIZE');o=dict(zip(HEADER,struct.unpack_from('<16I',raw)));o.update(zip(('moduleBase','checkedTick','callTick','reserved64'),struct.unpack_from('<4Q',raw,64)))
    require(o['bytes']==SIZE and o['version']==9 and o['operation']==19,'TARGETED_ABI_VERSION')
    require(o['status']<=2 and 1<=o['stage']<=3 and o['resourcesReleased']==1 and o['nativeCalls']<=67 and o['optionOrdinal']<64 and o['editorGuid'] and o['runtimeId'] and o['stopReason']<=8 and not o['reserved'] and not o['reserved64'],'TARGETED_HEADER')
    require(all(o[k] in (0,1) for k in ('actionAttempted','actionReturned','guardVerified')) and o['actionReturned']<=o['actionAttempted']<=o['guardVerified'],'TARGETED_ACTION_ORDER')
    o['directory']=d.parse(raw[DIRECTORY_AT:OPTION_AT]);o['immediate']=c.option(raw[OPTION_AT:SOURCE_AT],o['moduleBase']);o['immediateHex']=raw[OPTION_AT:SOURCE_AT].hex()
    o['source']=dict(zip(('record','klass','editorGuid','templateId','templateRecord'),struct.unpack_from('<QQIIQ',raw,SOURCE_AT)))
    o['input']=dict(zip(INPUT_POINTERS,struct.unpack_from('<12Q',raw,INPUT_AT)));o['input'].update(zip(INPUT_NUMBERS,struct.unpack_from('<8I',raw,INPUT_AT+96)))
    if o['guardVerified']:
        directory=o['directory'];contact=directory['contact'];s=contact['first'];i=o['input'];b=o['moduleBase'];state=contact['control']['observation']['after']
        require(not directory['status'] and directory['stable']==1 and not directory['first']['status'] and not contact['status'] and contact['stable']==1 and b==directory['moduleBase'] and s['optionsStatus']==0 and o['optionOrdinal']<s['optionCount'],'TARGETED_DIRECTORY_GUARD')
        require(o['immediate']==s['options'][o['optionOrdinal']] and o['immediate']['ownerRuntimeId']==o['runtimeId'] and o['immediate']['ownerStatus']==0 and o['immediate']['enabled']==1,'TARGETED_ATOMIC_ASSOCIATION')
        require(all(i[k] for k in INPUT_POINTERS) and i['valid']==1 and i['disabled']==i['blocked']==i['reserved']==0 and i['owned']==1 and i['sourceActive']<=1,'TARGETED_INPUT_GUARD')
        require(i['avatar']==i['componentOwner']==i['managedAvatar']==state['avatar'] and i['avatarId']==state['avatarId'] and i['componentClass']==i['expectedClass'] and i['strengthSlot']==b+0x12b51c50 and i['activeSlot']==b+0x12b526e0 and i['context']==s['mainContext'] and i['view']==s['view'],'TARGETED_INPUT_IDENTITY')
        require(o['checkedTick']>0 and o['callTick']>=o['checkedTick'],'TARGETED_CALL_TIMING')
    if o['status']==0:require(o['stage']==3 and o['actionReturned']==1 and o['stopReason']==0,'TARGETED_SUCCESS_WITHOUT_ACTION')
    return o

def interpretation(o,card):
    p=card['targetPlan'];require(o['optionOrdinal']==p['optionIndex'] and o['editorGuid']==p['editorGuid'] and o['runtimeId']==p['runtimeId'],'TARGETED_PLAN_BINDING')
    base=d.interpretation(o['directory'],dict(card,mode='trial-entities'))
    base.update(ok=True,safeToRelease=True,outcomeUncertain=False);row=selected(base,p)
    require(o['guardVerified']==1 and o['immediateHex']==card['targetBinding']['optionHex'] and o['source']==row['host']['sourceInstance'],'TARGETED_EXPECTED_BINDING')
    state=o['directory']['contact']['control']['observation']['after'];b=card['targetBinding']
    require(state['avatar']==b['avatar'] and state['avatarId']==b['avatarId'] and o['input']['context']==b['mainContext'] and o['input']['view']==b['view'],'TARGETED_BASELINE_IDENTITY')
    base.update(operation='targeted-interact',readOnly=False,actionAttempted=bool(o['actionAttempted']),actionReturned=bool(o['actionReturned']),atomicTargetIdentityVerified=True,invokedEditorEntityGuid=p['editorGuid'],invokedRuntimeId=p['runtimeId'],invokedLabel=p['label'],invokedOption=row,businessEffectVerified=False,targetNpcIdentityVerified=False,collisionVerified=False,playerContactVerified=False)
    return base
