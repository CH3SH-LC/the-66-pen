"""Independent catalog/calibration consumption. No process or native calls here."""
from __future__ import annotations
import json,math,struct
from pathlib import Path
from terrain_model import ROOT,require,digest,uint

SIZE=47312
CAPACITY=512
ROW=struct.Struct('<QQ6I48s')
HEADER='size version status stage root configDictionary configCount configVersion styleDictionary styleCount styleVersion materialCount decoderTable decoderKey stable reserved'.split()
TEXTMAP=Path('D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/TextMap/CHS')

def decode(raw):
    require(len(raw)==SIZE,'CATALOG_ABI')
    h=dict(zip(HEADER,struct.unpack_from('<16Q',raw)));reasons=[]
    def check(c,r):
        if not c:reasons.append(r)
    check(h['size']==SIZE and h['version']==1 and h['status']==0 and h['stage']==4 and h['stable']==1 and h['reserved']==0,'CATALOG_STATUS')
    check(all(h[x] for x in ('root','configDictionary','styleDictionary','decoderTable')),'CATALOG_ROOTS')
    check(0<h['materialCount']<=CAPACITY and h['materialCount']<=h['configCount']<=262144 and h['styleCount']<=8192 and h['decoderKey']<=0xffffffff,'CATALOG_COUNTS')
    matrix=list(struct.unpack_from('<16f',raw,128));steps=list(struct.unpack_from('<4f',raw,192));table=raw[208:2256]
    check(steps==[5.,2.5,5.,0.] and all(math.isfinite(x) and abs(x)<=1e7 for x in matrix),'CATALOG_GRID_OR_MATRIX')
    check([matrix[i] for i in (3,7,11,15)]==[0.,0.,0.,1.],'CATALOG_AFFINE_MATRIX')
    rows=[]
    for i in range(min(h['materialCount'],CAPACITY)):
        obj,style,key,encoded,ident,name,category,reserved,fields=ROW.unpack_from(raw,2256+ROW.size*i)
        value=(encoded^h['decoderKey'])&0xffffffff
        calculated=sum(table[(0x400+0x100*j)|((value>>(24-8*j))&255)]<<(24-8*j) for j in range(4))
        check(obj!=0 and category==2 and reserved==0 and ident==calculated and ident<=0x7fffffff,'CATALOG_MATERIAL_ID')
        check(struct.unpack_from('<I',fields,0x14)[0]==encoded and struct.unpack_from('<I',fields,0x1c)[0]==name and struct.unpack_from('<I',fields,0x24)[0]==category,'CATALOG_RECORD_FIELDS')
        rows.append(dict(id=ident,nameHash=name,configObject=obj,renderStyle=style,dictionaryKey=key,encodedId=encoded,
                         category=category,rawFieldsHex=fields.hex(),renderStyleLoaded=bool(style),semanticLabel=None))
    check([x['id'] for x in rows]==sorted({x['id'] for x in rows}),'CATALOG_ID_ORDER')
    check(not any(raw[2256+ROW.size*len(rows):]),'CATALOG_UNUSED_ROWS')
    return dict(ok=not reasons,reasons=reasons,header=h,matrix=matrix,cellSize=steps[:3],materials=rows,
                materialCatalogVerified=not reasons,worldMatrixVerified=not reasons,rawSha256=digest(raw),
                pixelAppearanceVerified=False,materialNamesVerified=False)

def original(run):
    import terrain_native as native
    run,built=native.checked_run(run);require(built.get('catalogProbe') is True and built['inspectOnly'] is True,'CATALOG_READ_CARD_REQUIRED')
    result=native.decode(run);require(result['ok'] and result['safeToRelease'] and not result['called'],'CATALOG_ORIGINAL_NOT_ACCEPTED')
    record,_=native.ro.load_decoder().read_probe(run/'stdout.jsonl');raw=bytes.fromhex(record['terrainHex'])
    size=262584 if built['nativeSnapshotVersion']==2 else 33208;payload=raw[native.RECEIPT_BASE_SIZE+size:]
    catalog=decode(payload);require(catalog['ok'] and digest((run/'stdout.jsonl').read_bytes())==result['rawReceiptSha256'],'CATALOG_RECEIPT_CHANGED')
    rows=[list(struct.unpack_from('<6I',raw,256+24*i)) for i in range(result['header']['beforeCount'])]
    return run,built,result,catalog,payload,rows

def authority(run,terrain_id=None):
    run,built,result,catalog,payload,rows=original(run)
    require(terrain_id is None or built['terrainId']==terrain_id,'CATALOG_TERRAIN_MISMATCH')
    return dict(schema='native-terrain-material-source-v1',run=str(run),terrainId=built['terrainId'],levelId=built['levelId'],
                rawReceiptSha256=result['rawReceiptSha256'],catalogSha256=digest(payload),
                materialIds=[r['id'] for r in catalog['materials'] if r['renderStyleLoaded']],matrix=catalog['matrix'],cellSize=catalog['cellSize'])

def validate_authority(value,terrain_id=None):
    require(type(value) is dict and value.get('schema')=='native-terrain-material-source-v1','NATIVE_MATERIAL_SOURCE_REQUIRED')
    require(value==authority(value['run'],terrain_id),'MATERIAL_SOURCE_CHANGED')
    return value

def preparation(plan,session,level):
    value=plan.get('materialSource')
    if value is None:return {},None
    validate_authority(value,plan['terrainId']);run,built,result,catalog,payload,rows=original(value['run'])
    import terrain_save_verify as proof
    proof.same_session(session,built['session']);require(level==built['levelId'],'CATALOG_LEVEL_MISMATCH')
    names=('prepared.json','build-result.json','request.json','stdout.jsonl','exit.json','launch.claim','attempt.used','baseline-prepared.json','baseline-snapshot.bin')
    return {str(run/n):digest((run/n).read_bytes()) for n in names},payload

def installed_labels():
    """Same installed editor TextMap hash fields, never a guessed material name."""
    from terrain_model import parse_fields
    paths=list(TEXTMAP.glob('*.mihoyobin'));require(len(paths)==1,'INSTALLED_CHS_TEXTMAP_REQUIRED')
    raw=paths[0].read_bytes();require(len(raw)<=32*1024*1024,'TEXTMAP_LIMIT')
    data=bytes(x^0xe5 for x in raw);labels={}
    for f in parse_fields(data):
        if f.number!=2 or f.wire_type!=2:continue
        entry=parse_fields(f.data);keys=[p.value for p in entry if p.number==2 and p.wire_type==0];texts=[p.data.decode('utf-8') for p in entry if p.number==3 and p.wire_type==2]
        if len(keys)==len(texts)==1:
            require(keys[0] not in labels or labels[keys[0]]==texts[0],'TEXTMAP_HASH_COLLISION');labels[keys[0]]=texts[0]
    require(labels,'EMPTY_INSTALLED_TEXTMAP')
    return labels,dict(path=str(paths[0]),sha256=digest(raw),decodedSha256=digest(data),source='installed editor CHS TextMap hash field2 -> text field3')

def catalog(run):
    path,built,receipt,result,payload,rows=original(run);labels,source=installed_labels()
    for material in result['materials']:
        material['semanticLabel']=labels.get(material['nameHash']);material['labelHashMatched']=material['nameHash'] in labels
    result.update(run=str(path),terrainId=built['terrainId'],levelId=built['levelId'],session=built['session'],
                  rawReceiptSha256=receipt['rawReceiptSha256'],textMap=source,
                  materialNamesVerified=all(m['labelHashMatched'] for m in result['materials']),
                  materialSource=authority(run),observedCellMaterials=sorted({r[2] for r in rows}),
                  currentCells=len(rows),nativeCalled=False,worldOrigin=result['matrix'][12:15],
                  verticalEncoding='local top=(gridX*5, heightCode*2.5, gridZ*5); apply actual matrix; extras can alter shape')
    return result

def resolve_material(value,selector):
    require(value.get('ok') and value.get('materialCatalogVerified'),'VERIFIED_CATALOG_REQUIRED')
    if type(selector) is int:matches=[m for m in value['materials'] if m['id']==selector]
    elif type(selector) is str:matches=[m for m in value['materials'] if m.get('labelHashMatched') and m['semanticLabel']==selector]
    else:raise ValueError('MATERIAL_SELECTOR_ID_OR_EXACT_LABEL')
    require(len(matches)==1 and matches[0]['renderStyleLoaded'],'MATERIAL_NOT_UNIQUE_OR_NOT_RENDERABLE')
    return matches[0]
