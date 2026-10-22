"""Pure binary and PNG validation. No process, queue or desktop API."""
import binascii,hashlib,math,struct,zlib
from contract import require,extension,interpretation
CAPACITY=8*1024*1024
PAGE=128
PNG_OFFSET=96+336+160+PAGE*128
SIZE=PNG_OFFSET+CAPACITY
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','frameBefore','frameAfter','renderedBefore','renderedAfter','width','height','pngBytes','frameStatus','pageStart','pageEnd','count','enumerationStatus','entryCapacity','dictionaryStable','reserved0','reserved1')
CONTEXT_POINTERS=('levelManager','levelData','levelGuid','trialTask','dictionary','entries')
CONTEXT_NUMBERS=('readable','isTrial','serverVersion','taskType','taskState','dictionaryCount','dictionaryVersion','reserved')
ENTITY_POINTERS=('entity','klass','transform','gameObject')
ENTITY_NUMBERS=('id','entryIndex','positionStatus','activeStatus','active','localAvatar','worldGetterRva','reserved')
ENTITY_NUMBERS+=('configId','entityType','isTickable','isEntityReady','isLoaded','runtimeIdentityStatus')
def png_info(data,width,height):
    require(data[:8]==b'\x89PNG\r\n\x1a\n','PNG_SIGNATURE');offset=8;chunks=[];compressed=[];info=None
    while offset<len(data):
        require(offset+12<=len(data),'PNG_TRUNCATED_CHUNK');size=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8]
        require(size<=CAPACITY and offset+12+size<=len(data),'PNG_CHUNK_LENGTH');body=data[offset+8:offset+8+size]
        crc=struct.unpack_from('>I',data,offset+8+size)[0];require(binascii.crc32(kind+body)&0xffffffff==crc,'PNG_CRC')
        if kind==b'IHDR':
            require(not chunks and size==13,'PNG_IHDR_ORDER');w,h,bits,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',body)
            require(w==width and h==height and 0<w<=4096 and 0<h<=4096,'PNG_DIMENSIONS')
            require(bits==8 and color in (2,6) and compression==filtering==interlace==0,'PNG_UNSUPPORTED_ENCODING');info=(w,h,color)
        elif kind==b'IDAT':
            require(info is not None and b'IEND' not in chunks,'PNG_IDAT_ORDER');compressed.append(body)
        elif kind==b'IEND':require(size==0 and offset+12==len(data) and compressed,'PNG_IEND')
        else:require(kind[0]&32,'PNG_UNKNOWN_CRITICAL_CHUNK')
        chunks.append(kind);offset+=12+size
    require(info is not None and chunks[-1:]==[b'IEND'],'PNG_MISSING_IEND')
    stride=width*(3 if info[2]==2 else 4)+1;limit=stride*height
    decoder=zlib.decompressobj()
    try:pixels=decoder.decompress(b''.join(compressed),limit+1)
    except zlib.error as exc:raise ValueError('PNG_DEFLATE_INVALID') from exc
    require(len(pixels)==limit and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'PNG_DEFLATE_SIZE')
    require(all(pixels[i]<=4 for i in range(0,len(pixels),stride)),'PNG_ROW_FILTER')
    return dict(width=width,height=height,colorType=info[2],encodedBytes=len(data),sha256=hashlib.sha256(data).hexdigest())
def parse(raw):
    require(len(raw)==SIZE,'ACCEPTANCE_ABI_SIZE');out=dict(zip(HEADER,struct.unpack_from('<24I',raw)))
    require(out['bytes']==SIZE and out['version']==1,'ACCEPTANCE_ABI_VERSION')
    require(out['operation'] in (1,2) and out['resourcesReleased'] in (0,1) and out['dictionaryStable'] in (0,1),'ACCEPTANCE_ENUM')
    require(out['reserved0']==out['reserved1']==0,'ACCEPTANCE_RESERVED');require(out['count']<=PAGE and out['pngBytes']<=CAPACITY,'ACCEPTANCE_CAPACITY')
    out['observation']=extension(raw[96:432]);out['entities']=[]
    for name,at in [('before',432),('after',512)]:
        c=dict(zip(CONTEXT_POINTERS,struct.unpack_from('<6Q',raw,at)));c.update(zip(CONTEXT_NUMBERS,struct.unpack_from('<8I',raw,at+48)))
        require(c['reserved']==0 and c['isTrial'] in (0,1) and c['readable']<=7,'RUNTIME_CONTEXT');out[name]=c
    seen=set();previous=-1
    for i in range(out['count']):
        at=592+128*i;r=dict(zip(ENTITY_POINTERS,struct.unpack_from('<4Q',raw,at)));r.update(zip(ENTITY_NUMBERS,struct.unpack_from('<14I',raw,at+32)))
        vectors=struct.unpack_from('<9f',raw,at+88)
        for j,key in enumerate(('unityPosition','origin','worldPosition')):r[key]=list(vectors[j*3:j*3+3])
        require(r['reserved']==0 and struct.unpack_from('<I',raw,at+124)[0]==0,'ENTITY_RESERVED')
        require(r['id'] and r['id'] not in seen and r['entity'] and r['klass'],'ENTITY_IDENTITY');seen.add(r['id'])
        require(out['pageStart']<=r['entryIndex']<out['pageEnd'] and r['entryIndex']>previous,'ENTITY_ENTRY_ORDER');previous=r['entryIndex']
        require(r['positionStatus'] in range(5) and r['activeStatus'] in (0,1) and r['active'] in (0,1) and r['localAvatar'] in (0,1),'ENTITY_ENUM')
        require(r['runtimeIdentityStatus']==0 and all(r[k] in (0,1) for k in ('isTickable','isEntityReady','isLoaded')),'ENTITY_RUNTIME_STATE')
        if r['positionStatus']==0:
            require(r['transform'] and all(math.isfinite(x) for x in vectors),'ENTITY_POSITION')
            require(all(abs(r['worldPosition'][j]-r['unityPosition'][j]-r['origin'][j])<=0.02 for j in range(3)),'ENTITY_WORLD_ORIGIN_RELATION')
        out['entities'].append(r)
    require(not any(raw[592+out['count']*128:PNG_OFFSET]),'UNUSED_ENTITY_DATA')
    require(not any(raw[PNG_OFFSET+out['pngBytes']:]),'UNUSED_PNG_DATA')
    out['png']=raw[PNG_OFFSET:PNG_OFFSET+out['pngBytes']]
    if out['operation']==1:require(out['pngBytes']==0,'RUNTIME_CONTAINS_FRAME')
    return out
def interpret(e,target,page):
    base=interpretation(e['observation'],target)
    same=e['before']==e['after'];require(e['dictionaryStable']==int(same),'RUNTIME_STABILITY_MISMATCH')
    base.update(runtimeLevelContext=e['after'],runtimeTrialAttributionProven=False,monsterHealthVerified=False,monsterAiVerified=False,visualAcceptanceVerified=False)
    if e['operation']==1:
        require(e['pageStart']==page and page<=e['pageEnd']<=e['before']['dictionaryCount']<=e['entryCapacity']<=65536,'RUNTIME_PAGE_BOUNDS')
        require(e['before']['readable']&4 and same and not e['enumerationStatus'],'RUNTIME_ENUMERATION_INCOMPLETE')
        base['entities']=[dict(r,runtimeKind='local-avatar' if r['localAvatar'] else 'unclassified-runtime-entity',actualWorldPosition=r['worldPosition'] if r['positionStatus']==0 else None,activeInHierarchy=bool(r['active']) if r['activeStatus']==0 else None,belongsToTargetTrial=False if base['mode']=='editor' else None,health=None,aiState=None) for r in e['entities']]
        base.update(runtimeCollection='native EntityManager EntityMap (+0x1e8); runtimeID matched to entity+0x3a8',entityTypeSemantics='native numeric enum; monster label not yet mapped',pageStart=page,pageEnd=e['pageEnd'],nextPageStart=e['pageEnd'] if e['pageEnd']<e['before']['dictionaryCount'] else None,pageComplete=True,allEntriesCovered=page==0 and e['pageEnd']==e['before']['dictionaryCount'],snapshotAcrossPages=False)
    else:
        require(base['mode']=='editor' and base['editorIsTargetLevel'] and e['frameStatus']==0 and e['resourcesReleased']==1,'FRAME_TARGET_OR_RESOURCE_CONTRACT')
        base.update(renderFrameCaptured=True,frameSource='Unity ScreenCapture game backbuffer; superSize=1',frameFreshness='not-guaranteed; engine frame counters attached',frameCounters={k:e[k] for k in ('frameBefore','frameAfter','renderedBefore','renderedAfter')},png=png_info(e['png'],e['width'],e['height']))
    return base
