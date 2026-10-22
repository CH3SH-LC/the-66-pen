"""Build project-local static calibration GIA using the existing local encoder."""
import hashlib
import json
from pathlib import Path
from mvp import generate_mvp as encoder

HERE=Path(__file__).resolve().parent
BASELINE=HERE.parent/'scene.json'
ROOT=HERE.parents[1]
OUT=ROOT/'.runtime/mvp/calibration'

def sha(b): return hashlib.sha256(b).hexdigest()
def build():
    original=BASELINE.read_bytes();scene=json.loads(original)
    results=[]
    for name,count in [('A-space',1),('B-motion',2)]:
        rows=[];changes=[]
        for source in scene['entities'][:count]:
            e={k:source[k] for k in ['name','template_id','position','rotation','scale']}
            e['entity_id']=scene['entity_id_start']+source['index']
            if name=='B-motion' and source['index']==1:
                changes.append({'entityIndex':1,'field':'template_id','from':e['template_id'],'to':scene['entities'][0]['template_id'],'reason':'same template as start to isolate geometry; material not game-verified'})
                e['template_id']=scene['entities'][0]['template_id']
            rows.append(e)
        payload=encoder.build_payload(rows);blob=encoder.wrap_gia(payload)
        source_hash=sha(original);encoder_hash=sha(Path(encoder.__file__).read_bytes())
        folder=OUT/name/sha(blob)
        manifest={'schema':'miliastra-calibration/1','experiment':name,'status':'static-candidate-not-game-verified','artifact':{'file':'platforms.gia','bytes':len(blob),'sha256':sha(blob)},'sources':{'baseline':'mvp/scene.json','baselineSha256':source_hash,'encoder':'mvp/generate_mvp.py','encoderSha256':encoder_hash,'entrypoint':'mvp/calibration/generate.py','entrypointSha256':sha(Path(__file__).read_bytes())},'entities':rows,'entityCount':len(rows),'changesFromBaseline':changes,'coordinateAndSizeEvidence':'inherited baseline assumptions; not measured in game','notIncluded':['spawn point','character','trigger','revival','node graph','settlement'],'deploymentAllowed':False,'notes':['Candidate entity IDs reuse baseline indices: use a separate experimental scene; do not merge into baseline blindly.','A and B are static platform assets, not complete runnable tests.']}
        folder.mkdir(parents=True,exist_ok=True)
        for file,data in [('platforms.gia',blob),('manifest.json',(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode())]:
            target=folder/file
            if target.exists() and target.read_bytes()!=data: raise ValueError('Conflicting existing calibration output; refusing overwrite')
            if not target.exists(): target.write_bytes(data)
        results.append({'experiment':name,'directory':str(folder.relative_to(ROOT)),'artifactSha256':sha(blob),'bytes':len(blob),'entityCount':len(rows)})
    if BASELINE.read_bytes()!=original: raise ValueError('Baseline changed during generation')
    return results

if __name__=='__main__':
    print(json.dumps(build(),ensure_ascii=False,indent=2))
