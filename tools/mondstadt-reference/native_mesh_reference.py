"""GI Unity 2017.4 static mesh and parent-chain geometry reference reader."""
from __future__ import annotations
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
from serialized_reference import Reader
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def packed(r,floating):
    n=r.count(12000000);span,start=(r.read('f'),r.read('f')) if floating else (None,None)
    b=r.take(r.count(64*1024**2));r.align();bits=r.read('B');r.align()
    if bits>32 or n*bits>len(b)*8:raise ValueError('Invalid packed-vector bit bounds')
    if n and not bits:values=np.zeros(n,dtype=np.uint32)
    elif n:
        raw=np.frombuffer(b,dtype=np.uint8);unpacked=np.unpackbits(raw,bitorder='little')[:n*bits].reshape(n,bits)
        values=(unpacked.astype(np.uint32)*(np.uint32(1)<<np.arange(bits,dtype=np.uint32))).sum(axis=1,dtype=np.uint32)
    else:values=np.array([],dtype=np.uint32)
    if floating:return values.astype(float)*(span/(2**bits-1) if bits else 0)+start
    return values


FORMATS={0:('<f4',1),1:('<f2',1),2:('u1',255),3:('u1',255),4:('i1',127),5:('<u2',65535),6:('<i2',32767),7:('u1',1),8:('i1',1),9:('<u2',1),10:('<i2',1),11:('<u4',1),12:('<i4',1)}
def read_mesh(data):
    r=Reader(data);name=r.string();submeshes=[]
    for _ in range(r.count(10000)):
        first,count,topology,base,fv,vc=[r.read('I') for _ in range(6)];bounds=[r.read('f') for _ in range(6)]
        submeshes.append({'firstByte':first,'indexCount':count,'topology':topology,'baseVertex':base,'firstVertex':fv,'vertexCount':vc,'aabbCenterExtent':bounds})
    r.take(r.count()*40);r.take(r.count()*12)
    for _ in range(r.count()):r.string();r.take(12)
    r.take(r.count()*4);r.take(r.count()*64);r.take(r.count()*4);r.read('I')
    compression,readable,keepv,keepi=[r.read('B') for _ in range(4)];r.align()
    pack_skin=r.read('B');r.align();index_format=r.read('i')
    if index_format not in (0,1):raise ValueError('Unsupported mesh index format')
    width=2 if index_format==0 else 4;raw_indices=r.take(r.count(64*1024**2));r.align()
    if len(raw_indices)%width:raise ValueError('Index buffer size alignment')
    indices=np.frombuffer(raw_indices,dtype='<u2' if width==2 else '<u4').astype(np.uint32)
    r.take(r.count()*32);current=r.read('I');vertex_count=r.read('I')
    if vertex_count>4000000:raise ValueError('Vertex count limit')
    channels=[]
    for _ in range(r.count(32)):
        stream,offset,fmt,dim=[r.read('B') for _ in range(4)];dim&=15
        if dim and fmt not in FORMATS:raise ValueError('Unsupported vertex format')
        channels.append({'stream':stream,'offset':offset,'format':fmt,'dimension':dim})
    vertex_data=r.take(r.count(256*1024**2));r.align();streams={};offset=0
    for stream in range(max((c['stream'] for c in channels),default=-1)+1):
        stride=sum(c['dimension']*np.dtype(FORMATS[c['format']][0]).itemsize for c in channels if c['stream']==stream and c['dimension'])
        streams[stream]=(offset,stride);offset=(offset+stride*vertex_count+15)&~15
    arrays={}
    for ci,c in enumerate(channels):
        if not c['dimension']:continue
        fmt,denom=FORMATS[c['format']];dtype=np.dtype(fmt);start,stride=streams[c['stream']];start+=c['offset'];dim=c['dimension']
        if vertex_count and start+(vertex_count-1)*stride+dim*dtype.itemsize>len(vertex_data):raise ValueError('Vertex channel exceeds vertex buffer')
        a=np.ndarray((vertex_count,dim),dtype=dtype,buffer=vertex_data,offset=start,strides=(stride,dtype.itemsize)).astype(float)/denom
        arrays[ci]=np.maximum(a,-1) if c['format'] in (4,6) else a
    pv=packed(r,True);uv=packed(r,True);pn=packed(r,True);pt=packed(r,True)
    pw=packed(r,False);pns=packed(r,False);pts=packed(r,False);pc=packed(r,True);pb=packed(r,False);pi=packed(r,False);uvinfo=r.read('I')
    vertices=pv.reshape(-1,3) if len(pv) else arrays.get(0,np.empty((0,3)))
    if len(pi):indices=pi
    local_aabb=[r.read('f') for _ in range(6)];usage=r.read('i')
    r.take(r.count(64*1024**2));r.align();r.take(r.count(64*1024**2));r.align()
    metrics=[r.read('f') for _ in range(2)];dirty=r.read('B');r.align();dynamic=r.read('B');r.align();streaming=r.read('B');r.align()
    if r.p!=len(data):raise ValueError(f'Unparsed mesh suffix {len(data)-r.p} bytes; refusing schema assumption')
    if vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all():raise ValueError('Invalid positions')
    faces=[];face_submesh=[]
    for si,sub in enumerate(submeshes):
        start=sub['firstByte']//width;stop=start+sub['indexCount'];idx=indices[start:stop].astype(np.int64)+sub['baseVertex']
        if stop>len(indices):raise ValueError('Submesh index range')
        if sub['topology']==0:
            if len(idx)%3:raise ValueError('Triangle index count')
            tri=idx.reshape(-1,3)
        elif sub['topology']==2:
            if len(idx)%4:raise ValueError('Quad index count')
            q=idx.reshape(-1,4);tri=np.concatenate((q[:,[0,1,2]],q[:,[0,2,3]]))
        else:raise ValueError('Only triangle/quad reference topology supported')
        if len(tri) and (tri.min()<0 or tri.max()>=len(vertices)):raise ValueError('Triangle vertex outside bounds')
        faces.append(tri);face_submesh.extend([si]*len(tri))
    triangles=np.concatenate(faces) if faces else np.empty((0,3),dtype=np.int64)
    info={'name':name,'fullyParsedBytes':r.p,'vertexCount':len(vertices),'triangleCount':len(triangles),'meshCompression':compression,
          'localAabbCenterExtent':local_aabb,'localBoundsMin':vertices.min(axis=0).tolist() if len(vertices) else None,'localBoundsMax':vertices.max(axis=0).tolist() if len(vertices) else None,
          'submeshes':submeshes,'channels':channels,'indexFormat':index_format,'parentTransformResolved':False,'worldPlacementEligible':False}
    return info,{'vertices':vertices,'triangles':triangles,'faceSubmesh':np.array(face_submesh,dtype=np.int32)}


def local_matrix(identity):
    x,y,z,w=identity['localRotation'];q=np.array([x,y,z,w]);norm=float(q@q)
    if not math.isfinite(norm) or abs(norm-1)>0.005:raise ValueError('Invalid transform quaternion norm')
    q/=math.sqrt(norm);x,y,z,w=q
    rot=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    m=np.eye(4);m[:3,:3]=rot@np.diag(identity['localScale']);m[:3,3]=identity['localPosition'];return m


def resolve_local_hierarchy(meta):
    transforms={o['pathId']:o for o in meta['objects'] if o['classId']==4 and 'identity' in o};cache={}
    def visit(pid,trail):
        if pid in cache:return cache[pid]
        if pid in trail:raise ValueError('Transform parent cycle')
        obj=transforms.get(pid)
        if obj is None:raise ValueError('Missing local parent transform '+str(pid))
        ident=obj['identity'];father=ident['father'];m=local_matrix(ident)
        if father['fileId']!=0:raise ValueError('External parent unresolved')
        if father['pathId']!=0:m=visit(father['pathId'],trail+[pid])@m
        cache[pid]=m;return m
    result=[]
    for pid,obj in transforms.items():
        row={'pathId':pid,'gameObject':obj['identity']['gameObject']}
        try:row.update(nativeMatrixColumnVector=visit(pid,[]).tolist(),parentChainResolved=True)
        except ValueError as e:row.update(parentChainResolved=False,error=str(e))
        result.append(row)
    return result


def decode(node_dir,out):
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned output only')
    meta=json.loads((node_dir/'metadata.json').read_text(encoding='utf8'));source=json.loads((node_dir/'source.json').read_text(encoding='utf8'));data=(node_dir/'node.bin').read_bytes()
    if hashlib.sha256(data).hexdigest()!=source['nodeSha256']:raise ValueError('Source node SHA changed')
    out.mkdir(parents=True);rows=[]
    for obj in meta['objects']:
        if obj['classId']!=43:continue
        payload=data[obj['offset']:obj['offset']+obj['size']];info,arrays=read_mesh(payload);path=out/(str(obj['pathId'])+'.npz');np.savez_compressed(path,**arrays)
        rows.append(dict(info,pathId=obj['pathId'],objectSha256=hashlib.sha256(payload).hexdigest(),npz=relative(path),npzSha256=digest(path)))
    result={'schema':1,'sourceNode':relative(node_dir),'sourceNodeSha256':source['nodeSha256'],'meshes':rows,'localHierarchy':resolve_local_hierarchy(meta)}
    write_json(out/'geometry.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--node-dir',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(json.dumps(decode(project_path(a.node_dir),project_path(a.out))))
