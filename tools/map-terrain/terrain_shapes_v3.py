"""Current-build native slope/path operations, without invented terrain fields.

Type IDs are actual native brush selections. The association with the UI's
front/left/right names is NOT inferred from enum declaration order.
"""
from __future__ import annotations
import json
from pathlib import Path
import terrain_model as model

HERE=Path(__file__).resolve().parent
PROFILE=HERE/'shapes-profile-v3.json'
SCHEMA='native-terrain-plan-v3'
DIRECTIONS={'z+':0,'x+':1,'z-':2,'x-':3}
TYPES=(1,2,3)
PRE=1<<8
POST=1<<9
MASK=PRE|POST
require=model.require

def has_surface(edits):
    return type(edits) is list and any(type(edit) is dict and edit.get('op')=='surface' for edit in edits)

def binding():
    return dict(schema='native-terrain-shape-semantics-v3',profileSha256=model.digest(PROFILE.read_bytes()),
                pathField=5,slopeField=6,guardVersion=1,
                preserveWater=True,implicitPathDeletion=False,symbolicTypeLabelsVerified=False)

def decode_slope(value):
    model.uint(value,'slope code')
    if value==0:return None
    kind,direction=value>>4,value&15
    if kind not in TYPES or direction not in DIRECTIONS.values():
        return dict(raw=value,known=False)
    return dict(raw=value,known=True,type=kind,direction=next(k for k,v in DIRECTIONS.items() if v==direction),
                uiLabel=None,uiLabelVerified=False)

def encode_slope(value):
    require(type(value) is dict and set(value)=={'type','direction'},'SLOPE_REQUIRES_NATIVE_TYPE_AND_DIRECTION')
    require(type(value['type']) is int and value['type'] in TYPES,'SLOPE_TYPE_MUST_BE_NATIVE_1_2_3')
    require(type(value['direction']) is str and value['direction'] in DIRECTIONS,'SLOPE_DIRECTION_MUST_BE_LOCAL_X_OR_Z_AXIS')
    return value['type']<<4|DIRECTIONS[value['direction']]

def apply(before,k,edit,materials):
    require(set(edit)<={'x','z','op','height','material','slope','path'} and ('slope' in edit or 'path' in edit),
            'SURFACE_REQUIRES_SLOPE_OR_PATH_NO_RAW_FIELDS')
    require(before is not None or ('height' in edit and 'material' in edit),'NEW_SURFACE_REQUIRES_HEIGHT_AND_MATERIAL')
    after=list(before or [k,0,0,0,0,0])
    # A known operation must never normalize unknown existing semantics.
    require(after[4] in (0,1),'UNKNOWN_EXISTING_PATH_ENCODING')
    require(after[5]==0 or decode_slope(after[5])['known'],'UNKNOWN_EXISTING_SLOPE_ENCODING')
    if 'height' in edit:after[1]=model.uint(edit['height'],'height',model.LIMIT-1)
    if 'material' in edit:
        after[2]=model.uint(edit['material'],'material')
        require(after[2] in materials,'SURFACE_MATERIAL_NOT_OBSERVED_OR_CATALOGUED')
    require(after[1]>0,'SURFACE_REQUIRES_POSITIVE_BASE_HEIGHT')
    if 'slope' in edit:
        slope=0 if edit['slope'] is None else encode_slope(edit['slope'])
        if slope!=after[5]:
            # ba56790/ba56930 clear water/path; refuse implicit destruction.
            require(after[3]==0,'SLOPE_OPERATION_WOULD_CLEAR_WATER')
            require(after[4]==0 or edit.get('path') is False,'SLOPE_OPERATION_REQUIRES_EXPLICIT_PATH_REMOVAL')
            require(edit.get('path') is not True,'CREATE_PATH_IN_A_SEPARATE_ACCEPTED_CARD_AFTER_SLOPE')
            after[5]=slope
    if 'path' in edit:
        require(type(edit['path']) is bool,'PATH_MUST_BE_BOOLEAN')
        if edit['path']:require(after[3]==0,'NATIVE_PATH_CREATE_REJECTS_WATER')
        after[4]=int(edit['path'])
    require(after!=before,'NO_OP_CELL_EDIT')
    return after

def requirements(plan):
    """Only requested affected materials; no assumed numeric material meaning."""
    result={}
    for change in plan['changes']:
        if change['op']=='delete':continue
        after=change['after'];before=change.get('before')
        slot=result.setdefault(after[2],dict(material=after[2],slopeTypes=set(),path=False))
        if after[5]:
            slope=decode_slope(after[5]);require(slope['known'],'UNKNOWN_REQUESTED_SLOPE_ENCODING')
            slot['slopeTypes'].add(slope['type'])
        slot['path'] |= bool(after[4] or (before is not None and before[4]))
    return [dict(material=key,slopeTypeMask=sum(1<<i for i in row['slopeTypes']),path=row['path'])
            for key,row in sorted(result.items())]

def describe(rows=None):
    profile=json.loads(PROFILE.read_text('utf-8'))
    result=dict(ok=True,schema='native-terrain-shapes-v3',binding=binding(),semantics=profile['semantics'],
                operations=['surface.slope','surface.path'],
                slopeTypes=[dict(type=t,previewCreate=2*t+7,previewRemove=2*t+8,uiLabel=None,uiLabelVerified=False) for t in TYPES],
                heightSemantics='Shape brushes preserve height code; slope prefab is native, not arbitrary continuous terrain',
                materialSemantics='Slope uses base cell material; separate slope-only material is unsupported',
                liveShapeGeometryVerified=False,playerTraversalVerified=False,called=False)
    if rows is not None:
        result['cells']=[dict(x=r[0]&65535,z=r[0]>>16,height=r[1],material=r[2],waterType=r[3],
                             path=dict(raw=r[4],known=r[4] in (0,1),present=bool(r[4])),slope=decode_slope(r[5])) for r in rows]
    return result

def generate(spec):
    """Production consumers produce cell lists once; plan/batch enforce before."""
    require(type(spec) is dict and set(spec)=={'cells'} and type(spec['cells']) is list and 0<len(spec['cells'])<=2*model.MAX_CELLS,
            'SURFACE_SPEC_REQUIRES_CELLS')
    edits=[];seen=set()
    for item in spec['cells']:
        require(type(item) is dict and set(item)<={'x','z','slope','path','height','material'} and ('slope' in item or 'path' in item),
                'SURFACE_CELL_FIELDS')
        k=model.key(item.get('x'),item.get('z'));require(k not in seen,'DUPLICATE_SURFACE_COORDINATE');seen.add(k)
        if 'slope' in item and item['slope'] is not None:encode_slope(item['slope'])
        if 'path' in item:require(type(item['path']) is bool,'PATH_MUST_BE_BOOLEAN')
        if 'height' in item:model.uint(item['height'],'height',model.LIMIT-1)
        if 'material' in item:model.uint(item['material'],'material')
        edits.append(dict(item,op='surface'))
    return edits

def evidence(word,enabled):
    bits=word&MASK
    return dict(required=enabled,preflightVerified=bool(bits&PRE),postRebuildResourcesStable=bool(bits&POST),
                verified=bits==MASK if enabled else bits==0,
                slopePrefabLoadedVerified=enabled and bits==MASK,
                pathResourceDirectoryStable=enabled and bits==MASK,
                pathMeshCoverageVerified=False,visualShapeVerified=False,playerTraversalVerified=False)
