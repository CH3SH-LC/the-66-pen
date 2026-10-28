"""Read actual installed TerrainData heightmap substructures without game APIs.

The GI 7.1 outer TerrainData has custom fields. We do NOT pretend that the stock
Unity type tree describes its whole object. The fixed Unity heightmap sub-layout
is identified by an exact array/count/width/scale grammar and independent stored
patch extrema. Unparsed prefix/suffix bytes and location evidence stay explicit.
"""
from __future__ import annotations
import argparse,hashlib,json,math,os,struct
from pathlib import Path
import numpy as np
from serialized_reference import Reader
from acquire_reference_node import acquire
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def heightmap_candidates(data):
    candidates=[]
    for power in range(5,13):
        side=2**power+1;count=side*side;needle=struct.pack('<I',count);cursor=0
        while True:
            pos=data.find(needle,cursor)
            if pos<0:break
            cursor=pos+1
            if pos%4:continue
            try:
                r=Reader(data);r.p=pos;r.count(2**25);height_start=r.p
                raw=np.frombuffer(r.take(count*2),dtype='<i2').copy().reshape(side,side);r.align()
                error_count=r.count(2**20);errors=np.frombuffer(r.take(error_count*4),dtype='<f4').copy()
                pair_count=r.count(2**21);pairs=np.frombuffer(r.take(pair_count*4),dtype='<f4').copy()
                width,height=r.read('i'),r.read('i');thickness=r.read('f');levels=r.read('i');scale=[r.read('f') for _ in range(3)]
                if width!=side or height!=side or pair_count!=2*error_count or error_count!=(4**(power-3)-1)//3 or levels!=power-4:continue
                if not np.isfinite(errors).all() or not np.isfinite(pairs).all() or not all(math.isfinite(v) and v>0 for v in scale):continue
                if raw.min()<0 or raw.max()>32766 or not np.all(pairs[::2]<=pairs[1::2]+1e-7):continue
                low=float(raw.min())/32766;high=float(raw.max())/32766
                residual=max(abs(float(pairs.min())-low),abs(float(pairs.max())-high))
                if residual>1e-6:continue
                heights=raw.astype(np.float64)/32766*scale[1]
                end=r.p;custom_grid=None
                if end+4<=len(data):
                    n=struct.unpack_from('<I',data,end)[0]
                    if n==(side-1)**2 and end+4+n<=len(data):custom_grid=np.frombuffer(data,dtype=np.uint8,count=n,offset=end+4).copy().reshape(side-1,side-1)
                info={'heightmapObjectByteOffset':pos,'heightSamplesObjectByteOffset':height_start,'heightmapEndByteOffset':end,
                    'width':side,'height':side,'sampleOrder':'raw serialized order; row/column world axes must be independently resolved by registration evidence',
                    'scaleXYZ':scale,'localXRange':[0,scale[0]*(side-1)],'localZRange':[0,scale[2]*(side-1)],
                    'heightRange':[float(heights.min()),float(heights.max())],'quantizationY':scale[1]/32766,
                    'rawHeightRange':[int(raw.min()),int(raw.max())],'signedIntegerDenominator':32766,'thickness':thickness,'levels':levels,
                    'precomputedErrorCount':error_count,'minMaxPatchValueCount':pair_count,'storedPatchExtremaResidualNormalized':residual,
                    'stockUnitySchemaPartialOnly':True,'unparsedPrefixBytes':pos,'unparsedSuffixBytes':len(data)-end,
                    'unparsedPrefixSha256':hashlib.sha256(data[:pos]).hexdigest(),'unparsedSuffixSha256':hashlib.sha256(data[end:]).hexdigest(),
                    'customPerCellByteArrayPresent':custom_grid is not None,'customPerCellByteArraySemantics':'unknown; not interpreted as holes or ground',
                    'parentTransformResolved':False,'worldPlacementEligible':False}
                if custom_grid is not None:
                    v,c=np.unique(custom_grid,return_counts=True);info['customPerCellByteValueCounts']={str(int(a)):int(b) for a,b in zip(v,c)}
                candidates.append((info,{'rawHeights':raw,'localHeights':heights,'precomputedError':errors,'minMaxPatchHeights':pairs,**({'customPerCellByteArray':custom_grid} if custom_grid is not None else {})}))
            except (ValueError,OverflowError,struct.error):continue
    return candidates


def decode_node(node_dir,out):
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output only')
    m=json.loads((node_dir/'metadata.json').read_text(encoding='utf8'));data=(node_dir/'node.bin').read_bytes();source=json.loads((node_dir/'source.json').read_text(encoding='utf8'))
    if digest(node_dir/'node.bin')!=source['nodeSha256']:raise ValueError('Decoded node source SHA changed')
    objects=[o for o in m['objects'] if o['classId']==156]
    out.mkdir(parents=True);rows=[]
    for obj in objects:
        payload=data[obj['offset']:obj['offset']+obj['size']];name=Reader(payload).string();candidates=heightmap_candidates(payload)
        row={'name':name,'pathId':obj['pathId'],'objectSize':obj['size'],'objectSha256':hashlib.sha256(payload).hexdigest(),'candidateCount':len(candidates),'sourceNode':relative(node_dir),'sourceNodeSha256':source['nodeSha256']}
        if len(candidates)==1:
            info,arrays=candidates[0];target=out/('height-'+str(obj['pathId'])+'.npz');np.savez_compressed(target,**arrays);row.update(info,npz=relative(target),npzSha256=digest(target))
        else:row['status']='heightmap-grammar-ambiguous-or-absent'
        rows.append(row)
    write_json(out/'terrain-reference.json',{'schema':1,'sourceReadMode':'rb','gameProcessAccess':False,'worldPlacementEligible':False,'terrains':rows})
    return rows


if __name__=='__main__':
    os.environ['MONDSTADT_CODEC_ISOLATE']='1'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--node-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    print(json.dumps(decode_node(project_path(a.node_dir),project_path(a.out))))
