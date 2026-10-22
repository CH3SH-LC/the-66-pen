"""Conversions using one independently verified terrain world-matrix receipt."""
from __future__ import annotations
import math
from terrain_model import require,uint,LIMIT

def finite_vector(value,length=3):
    require(type(value) in (list,tuple) and len(value)==length and all(type(x) in (int,float) and math.isfinite(x) for x in value),'FINITE_VECTOR_REQUIRED')
    return list(map(float,value))

def transform(matrix,point):
    m=finite_vector(matrix,16);v=finite_vector(point)
    require([m[i] for i in (3,7,11,15)]==[0.,0.,0.,1.],'AFFINE_MATRIX_REQUIRED')
    return [sum(m[4*j+i]*v[j] for j in range(3))+m[12+i] for i in range(3)]

def inverse_transform(matrix,point):
    m=finite_vector(matrix,16);p=finite_vector(point)
    require([m[i] for i in (3,7,11,15)]==[0.,0.,0.,1.],'AFFINE_MATRIX_REQUIRED')
    a,b,c=m[0],m[4],m[8];d,e,f=m[1],m[5],m[9];g,h,i=m[2],m[6],m[10]
    determinant=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    require(math.isfinite(determinant) and abs(determinant)>1e-8,'NONINVERTIBLE_WORLD_MATRIX')
    q=[p[j]-m[12+j] for j in range(3)]
    return [sum(v*w for v,w in zip(row,q))/determinant for row in
            ((e*i-f*h,c*h-b*i,b*f-c*e),(f*g-d*i,a*i-c*g,c*d-a*f),(d*h-e*g,b*g-a*h,a*e-b*d))]

def geometry(source):
    require(source.get('schema')=='native-terrain-material-source-v1' and source.get('cellSize')==[5.,2.5,5.],'NATIVE_CALIBRATION_REQUIRED')
    matrix=finite_vector(source['matrix'],16);inverse_transform(matrix,[0,0,0]);return matrix

def cell_to_world(source,x,z,height):
    m=geometry(source);x=uint(x,'x',LIMIT-1);z=uint(z,'z',LIMIT-1);height=uint(height,'height',LIMIT-1)
    top=transform(m,[x*5,height*2.5,z*5]);anchor=transform(m,[x*5,0,z*5])
    return dict(x=x,z=z,height=height,worldAnchor=anchor,worldTop=top,
                worldFootprint=[transform(m,[x*5+dx,height*2.5,z*5+dz]) for dx,dz in ((-2.5,-2.5),(2.5,-2.5),(2.5,2.5),(-2.5,2.5))],
                scope='logical column grid; slope/water/extra-field surface geometry not inferred')

def world_to_cell(source,point,quantization='exact'):
    require(quantization in ('exact','nearest'),'EXPLICIT_QUANTIZATION_EXACT_OR_NEAREST')
    local=inverse_transform(geometry(source),point);continuous=[local[0]/5,local[1]/2.5,local[2]/5]
    codes=[math.floor(x+0.5) for x in continuous]
    if quantization=='exact':require(all(abs(a-b)<1e-5 for a,b in zip(codes,continuous)),'WORLD_POINT_NOT_ON_NATIVE_GRID_AND_HEIGHT')
    for name,n in zip(('x','height','z'),codes):uint(n,name,LIMIT-1)
    result=cell_to_world(source,codes[0],codes[2],codes[1]);result.update(inputWorld=finite_vector(point),continuousCodes=continuous,
            quantization=quantization,residualWorld=[result['worldTop'][i]-point[i] for i in range(3)],halfwayRule='floor(code+0.5), towards positive code')
    return result

def world_edits(catalog,points,quantization='exact'):
    """Authoring consumer: points with worldTop and explicit material id/label."""
    import terrain_catalog
    require(type(points) is list and 0<len(points)<=131072,'WORLD_POINTS_1_TO_131072')
    result=[];mapping=[];seen=set()
    for point in points:
        require(type(point) is dict and set(point)=={'worldTop','material'},'WORLD_POINT_REQUIRES_TOP_AND_MATERIAL')
        row=world_to_cell(catalog['materialSource'],point['worldTop'],quantization);material=terrain_catalog.resolve_material(catalog,point['material'])
        identity=(row['x'],row['z']);require(identity not in seen,'WORLD_POINTS_COLLAPSE_TO_SAME_CELL');seen.add(identity)
        require(row['height']>0,'ZERO_COLUMN_REQUIRES_DELETE_NOT_NEW_CELL')
        result.append(dict(x=row['x'],z=row['z'],height=row['height'],material=material['id']));mapping.append(row)
    return dict(ok=True,edits=result,mapping=mapping,materialSource=catalog['materialSource'],
                nativeCalled=False,nativeSaveVerified=False,pixelAppearanceVerified=False)

def calibrate(run,points=None,quantization='exact'):
    import terrain_catalog
    catalog=terrain_catalog.catalog(run)
    if points is not None:return world_edits(catalog,points,quantization)
    source=catalog['materialSource'];m=geometry(source)
    return dict(ok=True,materialSource=source,worldOrigin=m[12:15],cellSize=source['cellSize'],worldMatrix=m,
                horizontalBasisX=[m[i]*5 for i in range(3)],horizontalBasisZ=[m[8+i]*5 for i in range(3)],
                heightStepVector=[m[4+i]*2.5 for i in range(3)],heightCodeRange=[0,LIMIT-1],coordinateRange=[0,LIMIT-1],
                sampleCell=cell_to_world(source,0,0,1),materialCatalog=catalog['materials'],
                observedCellMaterials=catalog['observedCellMaterials'],nativeCalled=False,
                warning='Calibration belongs to this exact level/terrain/session. Production writes recheck full catalog and actual matrix before first mutation.')
