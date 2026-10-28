"""Exact source resolver with bounded multiblock-prefix index support.

The third index field is retained as an unknown span, not total bundle size.
An unequal span is accepted only at an actual compressed-block boundary; the
full header, exact asset key and physical range remain mandatory.
"""
from pathlib import Path
from common import ResourceIndex as BaseIndex,Store,Reader,asset_bundle,sha
from blb3_reference import read_header

class ResourceIndex(BaseIndex):
    def resolve(self,handle,store=None):
        store=store or Store();result=[]
        for original in self.lookup(handle):
            row=dict(original);row.update(matches=[],errors=[]);result.append(row)
            if row['block'] is None:row['errors'].append('NO_BLOCK_LOCATION');continue
            paths=self.block_paths(row['block']['id']);row['blockPaths']=paths
            if len(paths)!=1:row['errors'].append('BLOCK_PATH_NOT_UNIQUE');continue
            path=Path(paths[0]);header=read_header(path,row['block']['offset'])[0]
            end=header['bundleSize'];span=row['block']['size']
            boundaries={b['compressedOffset']+b['compressedSize']for b in header['blocks']}
            if not 0<end<=64*1024*1024 or row['block']['offset']+end>path.stat().st_size:raise ValueError('BUNDLE_RANGE')
            if span!=end and span not in boundaries:raise ValueError('INDEX_SPAN_NOT_BLOCK_BOUNDARY')
            row['bundleRangeEvidence']={'headerBundleBytes':end,'indexThirdU32':span,'indexThirdU32Semantic':'unknown',
                'relation':'full-bundle'if span==end else'compressed-block-prefix','blockEndOffsets':sorted(boundaries)}
            for ni,node in enumerate(header['nodes']):
                if not node['serializedAsset']:continue
                cab=node['path'].lower();n=store.acquire(cab,{'sourcePath':str(path),'bundleOffset':row['block']['offset'],'nodeIndex':ni,'bundleSize':end})
                for obj in n['metadata']['objects']:
                    data=n['raw'][obj['offset']:obj['offset']+obj['size']]
                    matches=[]
                    if obj['classId']==142:
                        for container in asset_bundle(data)['containers']:
                            key=container['key'];value=int(key)if key.lstrip('-').isdecimal()else None
                            if value is not None and value&0xffffffff==int(row['assetName'],16):matches.append((key,container['asset']))
                    elif obj['classId']==1210:
                        r=Reader(data);r.string()
                        for _ in range(r.count(100000)):
                            key=r.string();ptr=r.ptr();r.read('Q')
                            if key.lower()==row['assetName']:matches.append((key,ptr))
                        if r.p!=len(data):raise ValueError('UNPARSED_INDEX_OBJECT')
                    for key,ptr in matches:
                        row['matches'].append({'indexCab':cab,'indexPathId':obj['pathId'],'key':key,'pointer':ptr,
                            'targetCab':store.external_cab(cab,ptr['fileId']),'targetPathId':ptr['pathId'],
                            'indexNodeSha256':n['receipt']['nodeSha256'],'indexObjectSha256':sha(data)})
            if len(row['matches'])!=1:row['errors'].append('EXACT_HASHED_ASSET_NOT_UNIQUE')
        return result
