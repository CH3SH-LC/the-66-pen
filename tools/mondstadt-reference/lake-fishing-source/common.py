"""Owned immutable lake/fishing extension. Disk-only source acquisitions."""
import hashlib, importlib.util, json, os, sqlite3, sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
BASE=ROOT/'tools/mondstadt-reference'
OLD=BASE/'template_geometry'
OUT=ROOT/'data/mondstadt/reference3d/lake-fishing-source-v1'
V5=ROOT/'data/mondstadt/reference3d/native-world-source-v5-final'
sys.path.insert(0,str(OLD))
from sources import NodeStore as BaseStore, DB, asset_bundle, Reader
from resource_index import ResourceIndex
from native_mesh_reference import read_mesh,local_matrix

def sha(data):return hashlib.sha256(data).hexdigest()
def rel(path):return str(Path(path).resolve().relative_to(ROOT))
def writable():
    if (OUT/'PACKAGE.json').exists():raise ValueError('Immutable extension package already frozen')
    OUT.mkdir(parents=True,exist_ok=True)
def save(path,obj):
    path=Path(path).resolve()
    if not path.is_relative_to(OUT):raise ValueError('Owned output only')
    writable();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class Store(BaseStore):
    """Reuse pure exact-CAB read implementation, capture only in this new scope."""
    def __init__(self):super().__init__(out=None)
    def acquire(self,cab,explicit=None):
        if cab.lower() in self.cache:return self.cache[cab.lower()]
        writable();folder=OUT/'raw'/cab.lower()
        existing=folder if (folder/'source.json').exists() else ROOT/'data/mondstadt/reference3d/template-geometry-v1/raw'/cab.lower()
        if (existing/'source.json').exists():
            receipt=json.loads((existing/'source.json').read_text(encoding='utf8'))
            if explicit and any(receipt[k]!=explicit[k]for k in ('sourcePath','bundleOffset','nodeIndex')):
                raise ValueError('Explicit source differs from captured CAB')
            raw=(existing/'node.bin').read_bytes()
            if sha(raw)!=receipt['nodeSha256']:raise ValueError('Existing raw source SHA changed')
            meta=json.loads((existing/'metadata.json').read_text(encoding='utf8'))
            result={'raw':raw,'receipt':receipt,'metadata':meta,'objects':{o['pathId']:o for o in meta['objects']}}
            self.cache[cab.lower()]=result
        else:result=super().acquire(cab,explicit)
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'node.bin').write_bytes(result['raw'])
        save(folder/'source.json',result['receipt']);save(folder/'metadata.json',result['metadata'])
        result['folder']=folder;return result

def mapping():
    path=V5/'source-index.json'
    return json.loads(path.read_text(encoding='utf8'))['declaredProductTransform']

def catalog():return sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)
