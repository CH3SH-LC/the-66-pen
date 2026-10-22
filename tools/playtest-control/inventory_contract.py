"""Independent current-container decoder. Missing/unloaded data is never zero."""
import struct
from contract import require
import control_contract as c
OPERATIONS={'inventory-state':14}
LIMIT=4096
SIZE=c.SIZE+787136
CONTROL_OFFSET=96
CONTEXT_OFFSET=CONTROL_OFFSET+c.SIZE
CONTEXT_SIZE=304
ROWS_OFFSET=CONTEXT_OFFSET+2*CONTEXT_SIZE
ROW_SIZE=48
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','contextStable','samplesStable','totalCaptured','slotCaptured','reserved0','reserved1','reserved2','reserved3')
POINTERS=('avatar','component','module','bag')
CONTEXT_POINTERS=('avatar','component','modules','moduleEntries','moduleClass','module','bag','totalsList','totalsArray','slotsList','slotsArray','generationDictionary','generationEntries','templateKey')
CONTEXT_NUMBERS=('avatarId','avatarConfigId','moduleCapacity','totalCount','totalCapacity','totalVersion','slotCount','slotCapacity','slotVersion','bagCapacity','bagOccupied','generation','generationCapacity','generationIndex','status','reserved')
ROW_FIELDS=('object','item','key','quantity','index','instanceId','itemKind','reserved')

def context(raw):
    o=dict(zip(CONTEXT_POINTERS+CONTEXT_NUMBERS,struct.unpack_from('<14Q16I',raw)))
    o.update(moduleHeader=raw[176:240].hex(),generationHeader=raw[240:304].hex())
    require(o['status'] in (0,1) and not o['reserved'],'INVENTORY_CONTEXT_ENUM')
    if not o['status']:
        require(all(o[k] for k in CONTEXT_POINTERS) and o['templateKey']>>32 and o['avatarId'],'INVENTORY_OWNER_IDENTITY')
        require(o['moduleCapacity']<=1024 and o['totalCount']<=min(LIMIT,o['totalCapacity']) and o['totalCapacity']<=65536 and 0<o['slotCount']==o['bagCapacity']<=min(LIMIT,o['slotCapacity']) and o['slotCapacity']<=65536 and o['bagOccupied']<=o['slotCount'] and o['generationIndex']<o['generationCapacity']<=65536,'INVENTORY_CONTEXT_LIMITS')
        require(struct.unpack_from('<Q',raw,176+0x18)[0]==o['moduleEntries'] and struct.unpack_from('<Q',raw,240+0x20)[0]==o['generationEntries'],'INVENTORY_HEADER_POINTERS')
    return o

def rows(raw,count,source,*,complete):
    require(count<=LIMIT,'INVENTORY_ROW_LIMIT');out=[]
    for i in range(count):
        r=dict(zip(ROW_FIELDS,struct.unpack_from('<4Q4I',raw,i*ROW_SIZE)));out.append(r)
        if not complete:continue
        require(r['object'] and r['index']==i and not r['reserved'],'INVENTORY_ROW_IDENTITY')
        if source=='totals':require(not r['item'] and not r['instanceId'] and not r['itemKind'] and r['key']>>32,'INVENTORY_PAYMENT_ROW')
        elif r['item']:require(r['key']>>32 and r['instanceId'] and r['itemKind'] in (1,2) and r['quantity']<=0xffffffff,'INVENTORY_ITEM_ROW')
        else:require(not r['key'] and not r['quantity'] and not r['instanceId'] and not r['itemKind'],'INVENTORY_EMPTY_SLOT')
    if complete:
        require(not any(raw[count*ROW_SIZE:]),'INVENTORY_UNUSED_ROW')
        if source=='totals':require(len({r['key'] for r in out})==count,'INVENTORY_DUPLICATE_RESOURCE')
        else:
            occupied=[r for r in out if r['item']]
            require(len({r['instanceId'] for r in occupied})==len(occupied)==len({r['item'] for r in occupied}),'INVENTORY_DUPLICATE_ITEM')
    return out

def parse(raw):
    require(len(raw)==SIZE,'INVENTORY_ABI_SIZE');o=dict(zip(HEADER+POINTERS,struct.unpack_from('<16I4Q',raw)))
    require(o['bytes']==SIZE and o['version']==5 and o['operation']==14,'INVENTORY_ABI_VERSION')
    require(o['status'] in (0,1,2) and 1<=o['stage']<=3 and not o['nativeCalls'] and not any(o[k] for k in HEADER[12:]),'INVENTORY_READONLY_HEADER')
    require(all(o[k] in (0,1) for k in ('resourcesReleased','contextStable','samplesStable')) and o['totalCaptured']<=LIMIT and o['slotCaptured']<=LIMIT,'INVENTORY_HEADER_LIMITS')
    o['control']=c.parse(raw[CONTROL_OFFSET:CONTEXT_OFFSET]);require(o['control']['operation']==3 and not o['control']['actionAttempted'] and not o['control']['actionReturned'] and not o['control']['pngBytes'],'INVENTORY_CONTROL_READONLY');o['control'].pop('png')
    for i,key in enumerate(('before','after')):o[key]=context(raw[CONTEXT_OFFSET+i*CONTEXT_SIZE:CONTEXT_OFFSET+(i+1)*CONTEXT_SIZE])
    complete=o['stage']==3
    for i,(name,count,source) in enumerate((('totalsFirst',o['totalCaptured'],'totals'),('totalsSecond',o['totalCaptured'],'totals'),('slotsFirst',o['slotCaptured'],'slots'),('slotsSecond',o['slotCaptured'],'slots'))):
        start=ROWS_OFFSET+i*LIMIT*ROW_SIZE;o[name]=rows(raw[start:start+LIMIT*ROW_SIZE],count,source,complete=complete)
    if complete:
        a,z=o['before'],o['after'];require(not a['status'] and not z['status'],'INVENTORY_CONTEXT_INCOMPLETE')
        require(all(o[k]==a[k] for k in POINTERS) and o['avatar']==o['control']['observation']['after']['avatar'] and a['avatarId']==o['control']['observation']['after']['avatarId'],'INVENTORY_AVATAR_BINDING')
        require(o['totalCaptured']==a['totalCount'] and o['slotCaptured']==a['slotCount'],'INVENTORY_CAPTURE_COUNT')
        require(o['contextStable']==int(a==z),'INVENTORY_CONTEXT_STABILITY')
        require(o['samplesStable']==int(a==z and o['totalsFirst']==o['totalsSecond'] and o['slotsFirst']==o['slotsSecond']),'INVENTORY_SAMPLE_STABILITY')
        require(sum(bool(r['item']) for r in o['slotsFirst'])==a['bagOccupied'],'INVENTORY_OCCUPIED_COUNT')
    return o

def aggregate(rows,source):
    result={}
    for r in rows:
        if source=='slots' and not r['item']:continue
        key=r['key'];result[key]=result.get(key,0)+r['quantity'];require(result[key]<=0xffffffffffffffff,'INVENTORY_SUM_OVERFLOW')
    return [dict(resourceType=k&0xffffffff,configId=k>>32,quantity=str(v),source=source) for k,v in sorted(result.items())]

def interpretation(o,card):
    result=c.interpretation_control(o['control'],dict(card,mode='trial-state'))
    require(result['mode']=='play' and result['trialIdentityBound'] is True and o['stage']==3 and not o['status'] and o['contextStable']==o['samplesStable']==1,'INVENTORY_UNBOUND_OR_UNSTABLE')
    require(not o['before']['status'],'INVENTORY_UNKNOWN_CONTAINER')
    result.update(operation='inventory-state',readOnly=True,inventoryQuantitiesVerified=True,inventoryComplete=True,quantityEncoding='unsigned decimal string',runtimeOwner=dict(avatar=o['avatar'],avatarId=o['before']['avatarId'],avatarConfigId=o['before']['avatarConfigId'],component=o['component'],module=o['module'],bag=o['bag'],ownerGeneration=o['before']['generation'],bagTemplateKey=str(o['before']['templateKey'])),physicalItemCounts=aggregate(o['slotsFirst'],'slots'),paymentResourceCounts=aggregate(o['totalsFirst'],'payment-resources'),inventoryLimits=dict(maxPhysicalSlots=LIMIT,maxPaymentResources=LIMIT),inventorySemantics='Current client synchronized bag. Slots are native item-count query inputs; payment resources are native shop affordability inputs. Raw resourceType is preserved; no enum name or static template quantity is inferred.',gameplayEffectVerified=False,naturalInteractionVerified=False)
    return result
