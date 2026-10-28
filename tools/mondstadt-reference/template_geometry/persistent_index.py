"""Capture the exact manifest-declared persistent asset index; retain base version."""
import hashlib,json,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
from sources import NodeStore,INSTALL,OUTPUT,write_json
from resource_index import INDEX_CAB,INDEX,PATCH_INDEX,decode_to_sqlite,ResourceIndex

def main():
    if (OUTPUT/'PACKAGE.json').exists():raise ValueError('Frozen package')
    manifest=INSTALL/'YuanShen_Data/Persistent/res_versions_persist';raw=manifest.read_bytes();rows=[json.loads(line)for line in raw.splitlines()]
    entries=[x for x in rows if x['remoteName']=='blocks/00/31049740.blk']
    if len(entries)!=1 or entries[0].get('isPatch')is not True:raise ValueError('Exact persistent index entry missing')
    path=INSTALL/'YuanShen_Data/Persistent/AssetBundles'/entries[0]['localName'];before=path.stat();data=path.read_bytes()
    if len(data)!=entries[0]['fileSize']or hashlib.md5(data).hexdigest()!=entries[0]['md5']:raise ValueError('Persistent index manifest mismatch')
    proof={'manifest':str(manifest),'manifestSha256':hashlib.sha256(raw).hexdigest(),'entry':entries[0],'path':str(path),'containerSha256':hashlib.sha256(data).hexdigest()}
    store=NodeStore(OUTPUT/'raw-persistent-index');store.acquire(INDEX_CAB,{'sourcePath':str(path),'bundleOffset':0,'nodeIndex':0})
    if not PATCH_INDEX.exists():decode_to_sqlite(store,PATCH_INDEX,'resource-index-persistent-source.json')
    base=ResourceIndex(INDEX);patch=ResourceIndex(PATCH_INDEX);document=json.loads((OUTPUT/'template-identities.json').read_text(encoding='utf8'));comparison=[]
    for row in document['rows']:
        h=row['modelResourceHandle'];a=base.lookup(h);b=patch.lookup(h)
        def logical(rows):return [(x['language'],x['bundleIndex'],x['assetName'],x['block']['id'],x['block']['offset'],x['block']['size'])for x in rows]
        comparison.append({'templateId':row['templateId'],'handle':h,'base':a,'persistent':b,'sameLogicalBinding':logical(a)==logical(b)})
    proof.update(selectedComparison=comparison,allSelectedBindingsUnchanged=all(x['sameLogicalBinding']for x in comparison),
        persistentIndexSource=patch.source,streamingIndexSource=base.source)
    write_json(OUTPUT/'persistent-index-comparison.json',proof)
    print(json.dumps({'allSelectedBindingsUnchanged':proof['allSelectedBindingsUnchanged'],'patchPayloadBytes':patch.source['payloadBytes'],
        'patchAssets':patch.source['sections']['assets']['count']}))

if __name__=='__main__':os.environ['MONDSTADT_CODEC_ISOLATE']='1';main()
