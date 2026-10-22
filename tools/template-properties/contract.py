"""Strict actual-ID requests and action24/protocol30 wire decoder."""
from __future__ import annotations
import hashlib,json,struct
from pathlib import Path
LEVEL=1073741843
MAX_BATCH=16
MASKS={'name':1,'iconId':2,'stackLimit':4,'isTradeable':8}
STATE_KEYS=('iconId','stackLimit','isTradeable','name')
def require(condition,message):
    if not condition:raise ValueError(message)
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    with Path(path).open('x',encoding='utf-8',newline='\n') as out:json.dump(value,out,ensure_ascii=False,indent=2,allow_nan=False);out.write('\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def uint(value,label='uint32'):
    require(type(value) is int and 0<value<=0xffffffff,'INVALID_'+label);return value
def name(value):
    require(isinstance(value,str) and value and '\0' not in value and len(value.encode('utf-16-le'))<256 and len(value.encode('utf-8'))<=128,'NAME_1_TO_127_UTF16_AND_128_UTF8_REQUIRED');return value
def state_bytes(value):
    require(set(value)==set(STATE_KEYS),'STATE_KEYS')
    require(type(value['iconId']) is int and 0<=value['iconId']<=0xffffffff and type(value['stackLimit']) is int and 0<=value['stackLimit']<=0xffffffff,'STATE_UINT32')
    require(type(value['isTradeable']) is bool,'STATE_BOOLEAN')
    text=value['name'].encode('utf-16-le');require(len(text)<256 and '\0' not in value['name'],'STATE_NAME')
    return struct.pack('<4I',value['iconId'],value['stackLimit'],int(value['isTradeable']),len(text)//2)+text.ljust(256,b'\0')
def state_from(data):
    icon,stack,trade,n=struct.unpack_from('<4I',data);require(trade<=1 and n<128,'RECEIPT_STATE_BOUNDS');require(not any(data[16+n*2:272]),'RECEIPT_NAME_PADDING')
    return dict(iconId=icon,stackLimit=stack,isTradeable=bool(trade),name=data[16:16+n*2].decode('utf-16-le',errors='strict'))
def normalize(value):
    require(isinstance(value,dict) and set(value)=={'schemaVersion','levelId','definitions'} and value['schemaVersion']==1 and value['levelId']==LEVEL,'REQUEST_HEADER')
    rows=value['definitions'];require(isinstance(rows,list) and 1<=len(rows)<=MAX_BATCH,'BATCH_1_TO_16')
    seen=set();out=[]
    for row in rows:
        require(isinstance(row,dict) and set(row)=={'id','kind','set'},'ROW_KEYS')
        identifier=uint(row['id'],'DEFINITION_ID');kind=row['kind'];require(kind in ('item','currency'),'KIND_ITEM_OR_CURRENCY')
        require(identifier not in seen and identifier&0xe0000000==0x40000000 and ((identifier>>22)&127)==(8 if kind=='item' else 10),'ID_MUST_BE_ACTUAL_NATIVE_KIND_BAND');seen.add(identifier)
        changes=row['set'];require(isinstance(changes,dict) and changes and set(changes)<=set(MASKS),'SUPPORTED_FIELDS_ONLY')
        require(kind=='item' or not set(changes)&{'stackLimit','isTradeable'},'CURRENCY_HAS_NO_ITEM_STACK_OR_TRADE')
        for k,v in changes.items():
            if k=='name':name(v)
            elif k=='isTradeable':require(type(v) is bool,'TRADE_REQUIRES_BOOLEAN')
            else:uint(v,k)
        out.append(dict(id=identifier,kind=kind,set=dict(changes)))
    return dict(schemaVersion=1,levelId=LEVEL,definitions=out)
def merge(request,observed):
    result=[]
    for q in normalize(request)['definitions']:
        require(q['id'] in observed,'INSPECTION_TARGET_MISSING');r=observed[q['id']];require(r['subtype']==(9 if q['kind']=='item' else 11),'INSPECTION_KIND_CHANGED')
        before=r['after'];desired=dict(before);mask=0
        for k,v in q['set'].items():
            desired[k]=v
            if v!=before[k]:mask|=MASKS[k]
        result.append(dict(id=q['id'],subtype=r['subtype'],mask=mask,resource=r['resource'],nameProperty=r['nameProperty'],dataProperty=r['dataProperty'],expected=before,desired=desired))
    return result
ROW_KEYS=('id','subtype','mask','status','stage','renameCalled','openCalled','snapshotCalled','setterCalls','notifyCalled','closeCalled','closed','readbackVerified','uncertain','iconAllowed','companionNameVerified')
PTR_KEYS=('resource','nameProperty','dataProperty','data','basic','inter','companion','companionName','transaction','record','beforeBlob','guardBefore','guardAfter')
HEADER=('size','version','status','stage','seh','count','completed','sceneUnchanged','mode','catalogUnchanged','guardsUnchanged','guardCount','failedRva','failedValue','nativeCalls','reserved')
ROW_SIZE=1008
PREFIX_SIZE=96+8192*4+16*ROW_SIZE+8192*40
def decode_extension(raw,snapshot_size):
    require(len(raw)==PREFIX_SIZE+snapshot_size,'RECEIPT_SIZE')
    out=dict(zip(HEADER,struct.unpack_from('<16I',raw)));require(out['size']==len(raw) and out['version']==30 and 1<=out['count']<=16 and out['guardCount']<=8192,'RECEIPT_HEADER')
    out.update(zip(('manager','catalogBefore','catalogAfter'),struct.unpack_from('<3Q',raw,64)))
    counts=struct.unpack_from('<2I',raw,88);require(all(0<n<=4096 for n in counts),'ICON_COUNTS')
    out['itemIcons']=list(struct.unpack_from('<'+str(counts[0])+'I',raw,96));out['currencyIcons']=list(struct.unpack_from('<'+str(counts[1])+'I',raw,96+4096*4))
    out['rows']=[];pos=96+8192*4
    for i in range(out['count']):
        start=pos+i*ROW_SIZE;r=dict(zip(ROW_KEYS,struct.unpack_from('<16I',raw,start)));r.update(zip(PTR_KEYS,struct.unpack_from('<13Q',raw,start+64)))
        for j,key in enumerate(('before','desired','after')):r[key]=state_from(raw[start+168+j*272:start+440+j*272])
        r.update(zip(('pendingBefore','pendingSnapshot','pendingAfter','depthBefore','depthAfter','reserved'),struct.unpack_from('<6I',raw,start+984)));out['rows'].append(r)
    pos+=16*ROW_SIZE;out['guards']=[]
    for i in range(out['guardCount']):out['guards'].append(dict(zip(('id','subtype','target','companion','resource','before','after'),struct.unpack_from('<4I3Q',raw,pos+i*40))))
    return out,raw[PREFIX_SIZE:]
