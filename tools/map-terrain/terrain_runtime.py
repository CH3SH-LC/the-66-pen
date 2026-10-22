"""Independent runtime geometry receipt decoder; no native or process calls."""
from __future__ import annotations
import json,math,struct
from pathlib import Path
from terrain_model import require

CAPACITY=8192
TARGETS=4
HITS=128
COMPONENT=struct.Struct('<QQ4I6f')
TARGET_BYTES=12400
SIZE=967312
HEADER=('size version status stage readCalls root colliderClass rendererClass colliderArray rendererArray '
        'colliderCount rendererCount scannedColliders scannedRenderers targetCount reserved').split()

def cells(value):
    require(isinstance(value,list) and 1<=len(value)<=TARGETS,'RUNTIME_REQUIRES_ONE_TO_FOUR_CELLS')
    result=[]
    for row in value:
        require(isinstance(row,dict) and set(row)=={'x','z'},'RUNTIME_CELL_REQUIRES_X_Z_ONLY')
        require(all(type(row[a]) is int and 0<=row[a]<9999 for a in ('x','z')),'RUNTIME_CELL_COORDINATE')
        key=row['x']|(row['z']<<16)
        require(key not in result,'RUNTIME_DUPLICATE_CELL');result.append(key)
    return result

def read_probe(path):
    # Runtime arrays deliberately include the complete enumeration, including
    # misses/inactive objects. They exceed the shared ordinary 8 MiB envelope.
    with Path(path).open('rb') as stream:raw=stream.read(16*1024*1024+1)
    require(len(raw)<=16*1024*1024,'TERRAIN_RUNTIME_OUTPUT_LIMIT')
    text=raw.decode('utf-8-sig')
    try:rows=[json.loads(text)]
    except json.JSONDecodeError:rows=[json.loads(line) for line in text.splitlines() if line.strip()]
    require(len(rows)==1 and isinstance(rows[0],dict) and 'snapshotHex' in rows[0],'TERRAIN_RUNTIME_ONE_RECEIPT_REQUIRED')
    return rows[0],'utf-8'

def intersects(bounds,ray):
    low,high=0.,ray[3]
    for a in range(3):
        origin,direction=ray[a],ray[4+a];mn,mx=bounds[a]-bounds[3+a],bounds[a]+bounds[3+a]
        if abs(direction)<1e-8:
            if origin<mn or origin>mx:return False
            continue
        t1,t2=sorted(((mn-origin)/direction,(mx-origin)/direction))
        low,high=max(low,t1),min(high,t2)
        if high<low:return False
    return True

def decode(raw,keys,before,version=1):
    require(len(raw)==SIZE,'TERRAIN_RUNTIME_ABI')
    head=dict(zip(HEADER,struct.unpack_from('<16Q',raw)))
    reasons=[]
    def check(condition,reason):
        if not condition:reasons.append(reason)
    check(version in (1,2) and head['size']==SIZE and head['version']==version and head['status']==0 and head['stage']==4,'RUNTIME_STATUS')
    check(head['targetCount']==len(keys)<=TARGETS,'RUNTIME_TARGET_COUNT')
    check(all(head[k] for k in ('root','colliderClass','rendererClass','colliderArray','rendererArray')),'RUNTIME_OBJECT_ROOTS')
    check(head['reserved'] in (1,3) if version==2 else head['reserved']==0,'RUNTIME_RESERVED')
    matrix=list(struct.unpack_from('<16f',raw,128));steps=list(struct.unpack_from('<4f',raw,192))
    check(all(math.isfinite(x) and abs(x)<=1e7 for x in matrix),'RUNTIME_MATRIX')
    check(steps==[5.,2.5,5.,0.],'RUNTIME_CELL_SIZE')
    groups={}
    for index,name in enumerate(('collider','renderer')):
        count=head[name+'Count'];check(count<=CAPACITY,'RUNTIME_COMPONENT_CAPACITY')
        check(head['scanned'+name.title()+'s']==count,'RUNTIME_INCOMPLETE_ENUMERATION')
        rows=[]
        for i in range(min(count,CAPACITY)):
            values=COMPONENT.unpack_from(raw,208+index*CAPACITY*COMPONENT.size+i*COMPONENT.size)
            obj,game,active,enabled,visible,reserved,*bounds=values
            check(bool(obj and game) and active in (0,1) and enabled in (0,1) and visible in (0,1) and reserved==0,'RUNTIME_COMPONENT_FIELDS')
            check(all(math.isfinite(x) and abs(x)<=1e7 for x in bounds) and all(x>=0 for x in bounds[3:]),'RUNTIME_BOUNDS')
            rows.append(dict(object=obj,gameObject=game,active=bool(active),enabled=bool(enabled),isVisible=bool(visible),bounds=bounds))
        check(len({r['object'] for r in rows})==len(rows),'RUNTIME_DUPLICATE_COMPONENT')
        groups[name+'s']=rows
    present={r[0] for r in before};targets=[]
    start=208+2*CAPACITY*COMPONENT.size
    for i,key in enumerate(keys):
        offset=start+i*TARGET_BYTES
        values=struct.unpack_from('<8Q12f',raw,offset)
        observed,cell,state,transform,dirty,logical,test_count,hit_count,*vectors=values
        center=vectors[:4];ray=vectors[4:]
        captured=(center[3]==1) if version==2 else (head['stage']==4 or ray[3]>0)
        if not captured:
            reasons.append('RUNTIME_TARGET_NOT_CAPTURED')
            targets.append(dict(x=key&0xffff,z=key>>16,key=key,captured=False))
            continue
        check(observed==key and logical==int(key in present),'RUNTIME_CELL_BINDING')
        check(dirty==0 and (not logical or bool(cell and state and transform)),'RUNTIME_CELL_NOT_REBUILT')
        check(all(math.isfinite(x) and abs(x)<=1e7 for x in vectors) and ray[3]>0 and center[3]==(1 if version==2 else 0) and ray[7]==0,'RUNTIME_RAY_FINITE')
        expected=[matrix[a]*(key&0xffff)*steps[0]+matrix[8+a]*(key>>16)*steps[2]+matrix[12+a] for a in range(3)]
        check(all(abs(center[a]-expected[a])<0.005 for a in range(3)),'RUNTIME_WORLD_CENTER')
        up=matrix[4:7];length=math.sqrt(sum(x*x for x in up))
        check(length>1e-5,'RUNTIME_UP_VECTOR')
        if length>1e-5:
            check(all(abs(ray[4+a]+up[a]/length)<1e-5 for a in range(3)),'RUNTIME_RAY_DIRECTION')
            # Verify the actual query spans all active terrain Collider bounds;
            # no negative result can be manufactured by a short ray.
            projections=[]
            for c in groups['colliders']:
                if not(c['active'] and c['enabled']):continue
                b=c['bounds'];mid=sum((b[a]-center[a])*up[a]/length for a in range(3));extent=sum(b[3+a]*abs(up[a]/length) for a in range(3))
                projections.append((mid-extent,mid+extent))
            low=min((p[0] for p in projections),default=-steps[1]*length)
            high=max((p[1] for p in projections),default=steps[1]*length)
            check(abs(ray[3]-(high-low+2))<0.02 and all(abs(ray[a]-(center[a]+up[a]/length*(high+1)))<0.02 for a in range(3)),'RUNTIME_RAY_RANGE')
        candidates=[j for j,c in enumerate(groups['colliders']) if c['active'] and c['enabled'] and intersects(c['bounds'],ray)]
        check(test_count==len(candidates),'RUNTIME_RAY_ENUMERATION')
        check(hit_count<=HITS and hit_count<=test_count,'RUNTIME_HIT_COUNT')
        hits=[]
        for j in range(min(hit_count,HITS)):
            where=offset+112+j*96;collider,index=struct.unpack_from('<2Q',raw,where);hit=raw[where+16:where+96]
            hit_object=struct.unpack_from('<Q',hit)[0];point=list(struct.unpack_from('<3f',hit,8));normal=list(struct.unpack_from('<3f',hit,20));distance=struct.unpack_from('<f',hit,40)[0]
            check(index in candidates and index<len(groups['colliders']) and collider==hit_object==groups['colliders'][index]['object'],'RUNTIME_HIT_OBJECT_BINDING')
            check(not any(hit[56:]),'RUNTIME_HIT_LAYOUT_DRIFT')
            check(all(math.isfinite(v) for v in point+normal+[distance]) and 0<=distance<=ray[3]+0.01,'RUNTIME_HIT_RANGE')
            check(all(abs(point[a]-(ray[a]+ray[4+a]*distance))<0.03 for a in range(3)),'RUNTIME_HIT_POINT')
            if index<len(groups['colliders']):
                b=groups['colliders'][index]['bounds'];check(all(abs(point[a]-b[a])<=b[3+a]+0.03 for a in range(3)),'RUNTIME_HIT_BOUNDS')
            hits.append(dict(collider=collider,index=index,point=point,normal=normal,distance=distance,rawHex=hit.hex()))
        check(len({h['collider'] for h in hits})==len(hits),'RUNTIME_DUPLICATE_HIT')
        rendering=[j for j,c in enumerate(groups['renderers']) if c['active'] and c['enabled'] and intersects(c['bounds'],ray)]
        nearest=min(hits,key=lambda h:h['distance']) if hits else None
        # Source code proves the grid pivot, not the prefab outline. Establish
        # that the current query is safely inside its actual bounds before a
        # caller labels a later neighbor hit as stale deleted-cell geometry.
        vertical=abs(ray[4])<1e-5 and abs(ray[6])<1e-5 and abs(abs(ray[5])-1)<1e-5
        interior_hits=[]
        if nearest and vertical:
            # Each cell has a core collider and quadrant colliders. A quadrant
            # can share the pivot boundary, while the co-height core proves an
            # interior hit. Keep all actual contributors and do not shift rays.
            for hit in hits:
                if hit['index']>=len(groups['colliders']) or abs(hit['distance']-nearest['distance'])>0.03:continue
                b=groups['colliders'][hit['index']]['bounds']
                if all(abs(center[a]-b[a])+0.02<b[3+a] for a in (0,2)):interior_hits.append(hit['collider'])
        targets.append(dict(x=key&0xffff,z=key>>16,key=key,captured=True,cell=cell,renderState=state,cellTransform=transform,
                            dirty=dirty,logicalPresent=bool(logical),worldAnchor=center[:3],ray=ray,rayTests=test_count,hits=hits,
                            nearestHit=nearest,anchorInteriorVerified=bool(interior_hits),interiorHitColliders=interior_hits,rendererIndices=rendering))
    return dict(ok=not reasons,reasons=reasons,header=head,matrix=matrix,cellSize=steps[:3],**groups,targets=targets,
                tickGateKnown=version==2 and head['reserved'] in (1,3),tickGateActive=bool(head['reserved']&2) if version==2 and head['reserved'] in (1,3) else None,
                physicalQueryVerified=not reasons,rendererStateVerified=not reasons,pixelAppearanceVerified=False,
                playerBlockingVerified=False,scope='terrain-owned Collider center-column queries; Renderer bounds/state, not pixels or player contact')
