"""Capture five explicitly requested template identities and actual static mesh."""
from common import *
from geometry_extension import Extractor
sys.path.insert(0,str(ROOT/'tools/npc-appearance'))
from official_models import Catalog
IDS=[20001946,20002987,20002811,20002321,20001019]
LABELS=['钓竿','绳索','漂浮球','木质酒箱','木质酒桶']

def capture():
    writable();out=OUT/'template-identities.json'
    if out.exists():document=json.loads(out.read_text(encoding='utf8'))
    else:
        document=Catalog().resolve(IDS)
        for row in document['rows']:
            raw=Path(row['officialSource']['path']).read_bytes()
            if sha(raw)!=row['officialSource']['sha256']:raise ValueError('Official prefab source changed')
            path=OUT/'official'/(str(row['templateId'])+'.mihoyobin');path.parent.mkdir(exist_ok=True);path.write_bytes(raw)
            row['capturedOfficialFile']=rel(path);row['requestedLabel']=LABELS[IDS.index(row['templateId'])]
        save(out,document)
    store=Store();extractor=Extractor(store=store);rows=[]
    projections=module('lake_fishing_projections',OLD/'projections.py');images=[]
    for row in document['rows']:
        try:
            geometry=extractor.extract(row);path=OUT/'templates'/str(row['templateId'])/'geometry.json'
            image=OUT/'projections'/(str(row['templateId'])+'.png');image.parent.mkdir(exist_ok=True)
            images.append(projections.draw(geometry,image))
            result={'templateId':row['templateId'],'status':'captured','geometry':rel(path),'staticGeometryComplete':geometry['staticGeometryComplete'],
                'bounds':geometry['nonShadowEnabledStaticBounds'],'parts':len(geometry['parts']),'unresolved':geometry['unresolved']}
        except Exception as exc:result={'templateId':row['templateId'],'status':'unresolved','error':type(exc).__name__+': '+str(exc)}
        rows.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    save(OUT/'geometry-index.json',{'schema':'template-geometry-index-v1','rows':rows,'installationReadBytes':store.read_bytes,'runtimeAcceptance':False})
    save(OUT/'projections.json',{'rows':images,'originalMesh':True,'textured':False,'gameScreenshot':False})
    return rows

if __name__=='__main__':os.environ['MONDSTADT_CODEC_ISOLATE']='1';capture()
