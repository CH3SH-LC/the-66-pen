"""Original native water catalogue decoder and immutable authority binding."""
from pathlib import Path
import math,struct
from water_model import ROOT,require,digest,uint
SIZE=53456;CAPACITY=512;ROW=struct.Struct('<6Q6IfI24s')
HEADER='size version status stage root styleDictionary styleCount styleVersion materialCount waterTypeCount stable reserved reserved2 reserved3 reserved4 reserved5'.split()
def decode(raw):
    require(len(raw)==SIZE,'WATER_CATALOG_ABI')
    h=dict(zip(HEADER,struct.unpack_from('<16Q',raw)));reasons=[]
    def check(c,r):
        if not c:reasons.append(r)
    check(h['size']==SIZE and h['version']==1 and h['status']==0 and h['stage']==4 and h['stable']==1,'WATER_CATALOG_STATUS')
    check(not any(h[x] for x in HEADER[11:]),'WATER_CATALOG_RESERVED')
    check(h['root']>0 and h['styleDictionary']>0 and 0<h['materialCount']<=h['styleCount']<=8192 and 0<h['waterTypeCount']<=CAPACITY,'WATER_CATALOG_COUNTS')
    matrix=list(struct.unpack_from('<16f',raw,128));steps=list(struct.unpack_from('<4f',raw,192))
    check(all(math.isfinite(x) and abs(x)<=1e7 for x in matrix) and [matrix[i] for i in (3,7,11,15)]==[0.,0.,0.,1.] and steps==[5.,2.5,5.,0.],'WATER_MATRIX_OR_STEPS')
    try:
        from terrain_calibration import inverse_transform
        inverse_transform(matrix,[0,0,0])
    except (ValueError,ZeroDivisionError):reasons.append('WATER_MATRIX_SINGULAR')
    rows=[]
    for i in range(min(CAPACITY,h['waterTypeCount'])):
        style,config,lst,obj,prefab,native,material,ident,index,count,version,reserved,scale,reserved2,fields=ROW.unpack_from(raw,208+ROW.size*i)
        check(all(x>0 for x in (style,config,lst,obj)) and 0<ident<=0xffffffff and index<count<=CAPACITY and reserved==reserved2==0,'WATER_TYPE_ROW')
        check(math.isfinite(scale) and 0<scale<=10000 and struct.unpack_from('<I',fields)[0]==ident and struct.unpack_from('<Q',fields,8)[0]==prefab and struct.unpack_from('<f',fields,16)[0]==scale,'WATER_TYPE_FIELDS')
        check(bool(prefab) or not native,'WATER_PREFAB_NATIVE_WITHOUT_OBJECT')
        rows.append(dict(materialId=material,typeId=ident,style=style,waterConfig=config,list=lst,typeConfig=obj,prefab=prefab,
            prefabNative=native,listIndex=index,listCount=count,listVersion=version,scaleY=scale,rawTypeHex=fields.hex(),renderable=bool(prefab and native)))
    pairs=[(r['materialId'],r['typeId']) for r in rows]
    check(pairs==sorted(set(pairs)),'WATER_TYPE_ORDER_OR_DUPLICATES')
    check(len({r['materialId'] for r in rows})==h['materialCount'],'WATER_MATERIAL_COUNT')
    for material in {r['materialId'] for r in rows}:
        group=[r for r in rows if r['materialId']==material]
        check(len({(r['style'],r['waterConfig'],r['list'],r['listCount'],r['listVersion']) for r in group})==1 and
              sorted(r['listIndex'] for r in group)==list(range(group[0]['listCount'])),'WATER_LIST_COMPLETENESS')
    check(not any(raw[208+ROW.size*len(rows):]),'WATER_CATALOG_UNUSED_ROWS')
    return dict(ok=not reasons,reasons=reasons,header=h,matrix=matrix,cellSize=steps[:3],types=rows,
        materialCatalogVerified=not reasons,worldMatrixVerified=not reasons,waterCatalogVerified=not reasons,rawSha256=digest(raw),
        pixelAppearanceVerified=False,playerSwimmingVerified=False,surfaceElevationVerified=False)
def original(run):
    import water_native as native
    run,built=native.checked_run(run);require(built.get('catalogProbe') is True and built['inspectOnly'] is True,'WATER_CATALOG_CARD_REQUIRED')
    result=native.decode(run);require(result['ok'] and result['safeToRelease'] and not result['called'],'WATER_CATALOG_ORIGINAL_NOT_ACCEPTED')
    record,_=native.ro.load_decoder().read_probe(run/'stdout.jsonl');raw=bytes.fromhex(record['terrainHex'])
    size=262584 if built['nativeSnapshotVersion']==2 else 33208;payload=raw[native.RECEIPT_BASE_SIZE+size:]
    catalog=decode(payload);require(catalog['ok'] and digest((run/'stdout.jsonl').read_bytes())==result['rawReceiptSha256'],'WATER_CATALOG_RECEIPT_CHANGED')
    rows=[list(struct.unpack_from('<6I',raw,256+24*i)) for i in range(result['header']['beforeCount'])]
    return run,built,result,catalog,payload,rows
def authority(run,terrain_id=None):
    run,built,result,catalog,payload,rows=original(run)
    require(terrain_id is None or built['terrainId']==terrain_id,'WATER_CATALOG_TERRAIN_MISMATCH')
    return dict(schema='native-water-source-v1',run=str(run),terrainId=built['terrainId'],levelId=built['levelId'],
        rawReceiptSha256=result['rawReceiptSha256'],catalogSha256=digest(payload),
        waterTypes=[dict(materialId=r['materialId'],typeId=r['typeId'],scaleY=r['scaleY'],renderable=r['renderable']) for r in catalog['types']],
        matrix=catalog['matrix'],cellSize=catalog['cellSize'])
def validate_authority(value,terrain_id=None):
    require(type(value) is dict and value.get('schema')=='native-water-source-v1','NATIVE_WATER_SOURCE_REQUIRED')
    require(value==authority(value['run'],terrain_id),'WATER_SOURCE_CHANGED')
    return value
def preparation(plan,session,level):
    value=plan.get('materialSource')
    if value is None:return {},None
    validate_authority(value,plan['terrainId']);run,built,result,catalog,payload,rows=original(value['run'])
    import terrain_save_verify as proof
    from water_model import authorized_level
    proof.same_session(session,built['session']);require(authorized_level(level)==built['levelId'],'WATER_CATALOG_LEVEL_MISMATCH')
    names=('prepared.json','build-result.json','request.json','stdout.jsonl','exit.json','launch.claim','attempt.used','baseline-prepared.json','baseline-snapshot.bin')
    return {str(run/n):digest((run/n).read_bytes()) for n in names},payload
def catalog(run):
    path,built,receipt,result,payload,rows=original(run)
    result.update(run=str(path),terrainId=built['terrainId'],levelId=built['levelId'],session=built['session'],rawReceiptSha256=receipt['rawReceiptSha256'],
        materialSource=authority(run),currentCells=len(rows),nativeCalled=False,worldOrigin=result['matrix'][12:15],
        semantics='native water type in field4; water transform base localY=heightCode*2.5; scaleY is prefab scale, not measured depth or surface height')
    return result
def resolve_type(value,material_id,type_id):
    require(value.get('ok') and value.get('waterCatalogVerified'),'VERIFIED_WATER_CATALOG_REQUIRED')
    matches=[r for r in value['types'] if r['materialId']==material_id and r['typeId']==type_id and r['renderable']]
    require(len(matches)==1,'WATER_TYPE_NOT_UNIQUE_OR_RENDERABLE');return matches[0]
