"""World conversion for the native water prefab base, never inferred surface height."""
import math
from water_model import require,key,LIMIT
from terrain_calibration import transform,inverse_transform

def valid_geometry(source):
    require(source.get('schema')=='native-water-source-v1','NATIVE_WATER_SOURCE_REQUIRED')
    matrix=source.get('matrix');steps=source.get('cellSize')
    require(type(matrix) is list and len(matrix)==16 and all(type(x) in (int,float) and math.isfinite(x) for x in matrix),'WATER_MATRIX_INVALID')
    require([matrix[i] for i in (3,7,11,15)]==[0,0,0,1] and steps==[5,2.5,5],'WATER_MATRIX_OR_STEPS')
    # This also rejects singular affine transforms.
    inverse_transform(matrix,[0,0,0])
    return matrix

def locate(source,points):
    matrix=valid_geometry(source)
    require(type(points) is list and 0<len(points)<=65536,'WATER_BASE_POINTS_1_TO_65536')
    rows=[];seen=set()
    for point in points:
        require(type(point) is list and len(point)==3 and all(type(x) in (int,float) and math.isfinite(x) and abs(x)<=1e7 for x in point),'WATER_BASE_POINT_INVALID')
        local=inverse_transform(matrix,point);units=[local[i]/source['cellSize'][i] for i in range(3)]
        integers=[round(v) for v in units]
        require(all(abs(v-n)<=1e-5 for v,n in zip(units,integers)),'WATER_BASE_NOT_EXACTLY_ON_NATIVE_GRID')
        x,h,z=integers;cell=key(x,z);require(0<=h<LIMIT,'WATER_BASE_HEIGHT_OUT_OF_RANGE')
        require(cell not in seen,'DUPLICATE_WATER_BASE_COORDINATE');seen.add(cell)
        rows.append(dict(x=x,z=z,heightCode=h,worldBase=transform(matrix,[x*5,h*2.5,z*5]),emptyCellWaterOnlyPossible=h==0))
    return dict(ok=True,kind='native-water-base-locations-v1',points=rows,
        semantics='coordinates locate native water prefab bases; visible surface and trigger extent require real runtime acceptance',
        surfaceElevationVerified=False,playerSwimmingVerified=False,called=False)
