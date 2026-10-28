"""Sample an immutable native-ground reference package in named coordinates.

No editor writes. Native TerrainData is base terrain, not buildings/bridges. This
module does not fill missing terrain, invent lake beds, or bridge seam conflicts.
"""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
import numpy as np
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,ROOT,relative


def product_to_native_xz(points,mapping):
    p=np.asarray(points,dtype=float)
    if p.shape[-1]!=2 or not np.isfinite(p).all():raise ValueError('Finite XZ required')
    m=np.asarray(mapping['productToNativeMatrixColumnVector'],dtype=float)
    xyz=np.stack((p[...,0],np.zeros(p.shape[:-1]),p[...,1]),axis=-1)
    result=xyz@m[:3,:3].T+m[:3,3]
    return result[...,[0,2]]


def native_to_product_xz(points,mapping):
    p=np.asarray(points,dtype=float)
    if p.shape[-1]!=2 or not np.isfinite(p).all():raise ValueError('Finite XZ required')
    m=np.asarray(mapping['nativeToProductMatrixColumnVector'],dtype=float)
    xyz=np.stack((p[...,0],np.zeros(p.shape[:-1]),p[...,1]),axis=-1)
    result=xyz@m[:3,:3].T+m[:3,3]
    return result[...,[0,2]]


def interpolate(raw,local_x,local_z,step_x,step_z,row_axis='X'):
    if row_axis not in ('X','Z'):raise ValueError('Explicit registered row axis required')
    x=np.asarray(local_x,dtype=float)/step_x;z=np.asarray(local_z,dtype=float)/step_z
    row,col=(x,z) if row_axis=='X' else (z,x)
    if np.any(row<0) or np.any(col<0) or np.any(row>raw.shape[0]-1) or np.any(col>raw.shape[1]-1):raise ValueError('No terrain extrapolation')
    i=np.minimum(np.floor(row).astype(int),raw.shape[0]-2);j=np.minimum(np.floor(col).astype(int),raw.shape[1]-2);u=row-i;v=col-j
    return (1-u)*(1-v)*raw[i,j]+u*(1-v)*raw[i+1,j]+(1-u)*v*raw[i,j+1]+u*v*raw[i+1,j+1]


def interpolation_diagonal_bound(raw,local_x,local_z,step_x,step_z,row_axis):
    """Difference from bilinear for either planar diagonal of the same cell.

    This bounds these two interpolation choices only, not original game surface
    accuracy, mesh overlays, runtime deformation, or the editor's 5m reduction.
    """
    a,b=(local_x/step_x,local_z/step_z) if row_axis=='X' else (local_z/step_z,local_x/step_x)
    i=min(int(math.floor(a)),raw.shape[0]-2);j=min(int(math.floor(b)),raw.shape[1]-2);u=a-i;v=b-j
    h00,h10,h01,h11=map(float,(raw[i,j],raw[i+1,j],raw[i,j+1],raw[i+1,j+1]))
    bil=(1-u)*(1-v)*h00+u*(1-v)*h10+(1-u)*v*h01+u*v*h11
    first=h00+(h10-h00)*u+(h11-h10)*v if u>=v else h00+(h11-h01)*u+(h01-h00)*v
    second=h00+(h10-h00)*u+(h01-h00)*v if u+v<=1 else h11+(h01-h11)*(1-u)+(h10-h11)*(1-v)
    return max(abs(first-bil),abs(second-bil))


class GroundReference:
    def __init__(self,index_path):
        self.path=Path(index_path);self.index=json.loads(self.path.read_text(encoding='utf8'));self.tiles=[];self.cell_flags={}
        self.mapping=self.index['declaredProductTransform']
        forward=np.asarray(self.mapping['nativeToProductMatrixColumnVector'],float);inverse=np.asarray(self.mapping['productToNativeMatrixColumnVector'],float)
        if forward.shape!=(4,4) or inverse.shape!=(4,4) or not np.isfinite(forward).all() or not np.isfinite(inverse).all() or not np.allclose(forward@inverse,np.eye(4),atol=1e-10):raise ValueError('Explicit invertible native/product matrices required')
        if np.any(np.abs(forward[[0,2],1])>1e-10) or np.any(np.abs(forward[1,[0,2]])>1e-10):raise ValueError('Height sampling requires horizontal product plane')
        for tile in self.index['terrainTiles']:
            if tile['registration']['status'] not in ('source-transform-resolved','independently-corroborated-native-placement'):continue
            path=self.path.parent/tile['heightFile']
            if digest(path)!=tile['heightSha256']:raise ValueError('Height file SHA mismatch')
            with np.load(path,allow_pickle=False) as a:
                raw=a['rawHeights'];self.tiles.append((tile,raw))
                if 'customPerCellByteArray' in a:self.cell_flags[tile['id']]=a['customPerCellByteArray']
    def query_native(self,points):
        points=np.asarray(points,dtype=float)
        if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():raise ValueError('Finite N by2 native XZ points required')
        output=[]
        for x,z in points:
            candidates=[]
            for tile,raw in self.tiles:
                b=tile['nativeBounds']
                if not(b['xmin']<=x<=b['xmax'] and b['zmin']<=z<=b['zmax']):continue
                scale=tile['scaleXYZ'];local=interpolate(raw,x-b['xmin'],z-b['zmin'],scale[0],scale[2],tile['storageRowAxis'])
                y=float(local)/tile['heightIntegerDenominator']*scale[1]+tile['nativeYOrigin']
                diagonal=interpolation_diagonal_bound(raw,x-b['xmin'],z-b['zmin'],scale[0],scale[2],tile['storageRowAxis'])*scale[1]/tile['heightIntegerDenominator']
                flags=[]
                custom=self.cell_flags.get(tile['id']);custom_values=[]
                if custom is not None:
                    xi=min(int(math.floor((x-b['xmin'])/scale[0])),custom.shape[0]-1);zi=min(int(math.floor((z-b['zmin'])/scale[2])),custom.shape[1]-1)
                    # This custom array's independent axes/semantics are unknown.
                    # Exclude both plausible row/column interpretations, not just
                    # whichever interpretation would expose more ground.
                    custom_values=[int(custom[xi,zi]),int(custom[zi,xi])]
                    if any(custom_values):flags.append('custom-per-cell-nonzero-semantics-and-axes-unresolved')
                for band in tile.get('excludedBoundaryBands',[]):
                    if band['xmin']<=x<=band['xmax'] and band['zmin']<=z<=band['zmax']:flags.append(band['reason'])
                candidates.append({'tileId':tile['id'],'nativeY':y,'quantizationY':scale[1]/tile['heightIntegerDenominator'],'bilinearVsEitherCellDiagonalMaxDifferenceY':float(diagonal),'customCellValuesBothPossibleAxisOrders':custom_values,'flags':sorted(set(flags)),'placementEvidenceGrade':tile['registration']['grade']})
            row={'nativeXZ':[float(x),float(z)],'candidates':candidates,'surfaceKind':'native-TerrainData-base-heightmap','buildingsAndBridgesIncluded':False}
            if not candidates:row.update(status='missing-source',nativeY=None)
            elif any('custom-per-cell-nonzero-semantics-and-axes-unresolved' in c['flags'] for c in candidates):row.update(status='source-cell-semantics-uncertain',nativeY=None)
            elif any(c['flags'] for c in candidates):row.update(status='source-boundary-uncertain',nativeY=None)
            elif max(c['nativeY'] for c in candidates)-min(c['nativeY'] for c in candidates)>max(c['quantizationY'] for c in candidates)*2:row.update(status='source-overlap-conflict',nativeY=None)
            else:row.update(status='sampled',nativeY=candidates[0]['nativeY'])
            output.append(row)
        return output
    def query_product(self,points):
        native=product_to_native_xz(points,self.mapping);rows=self.query_native(native)
        m=np.asarray(self.mapping['nativeToProductMatrixColumnVector'])
        for row,p in zip(rows,points):
            product_y=None if row['nativeY'] is None else float(m[1,1]*row['nativeY']+m[1,3])
            row.update(productXZ=list(map(float,p)),productY=product_y,productTransformId=self.mapping['id'],editorVerticalOffsetApplied=False,verticalEditorConversionRequired=True)
        return rows


def generate_grid(index_path,out,bounds,step):
    if not(out.is_relative_to(SOURCE) or out.is_relative_to(ROOT)) or out.exists():raise ValueError('New owned reference output only')
    xmin,xmax,zmin,zmax=bounds
    if not all(math.isfinite(v) for v in bounds) or not xmin<=xmax or not zmin<=zmax or not math.isfinite(step) or step<=0:raise ValueError('Explicit ordered bounds and positive step required')
    xs=np.arange(xmin,xmax+step*1e-8,step);zs=np.arange(zmin,zmax+step*1e-8,step)
    if len(xs)*len(zs)>1000000:raise ValueError('Reference query limited to1million samples; not an editor cell allowance')
    points=np.array([(x,z) for z in zs for x in xs]);source=GroundReference(index_path);rows=source.query_product(points);heights=np.array([r['nativeY'] if r['nativeY'] is not None else np.nan for r in rows]).reshape(len(zs),len(xs));valid=np.isfinite(heights)
    product_heights=np.array([r['productY'] if r['productY'] is not None else np.nan for r in rows]).reshape(len(zs),len(xs))
    out.mkdir(parents=True);np.savez_compressed(out/'ground-samples.npz',productX=xs,productZ=zs,nativeHeight=heights,productHeight=product_heights,valid=valid)
    write_json(out/'ground-samples.json',{'schema':2,'sourceIndex':relative(index_path),'sourceIndexSha256':digest(index_path),'coordinateFrame':'declared-product-XYZ-and-separate-original-native-height',
        'bounds':{'xmin':float(xs[0]),'xmax':float(xs[-1]),'zmin':float(zs[0]),'zmax':float(zs[-1])},'requestedBounds':dict(zip(['xmin','xmax','zmin','zmax'],bounds)),
        'origin':{'x':float(xs[0]),'z':float(zs[0])},'step':step,'lastSample':{'x':float(xs[-1]),'z':float(zs[-1])},'shapeRowsZColumnsX':[len(zs),len(xs)],
        'validCount':int(valid.sum()),'missingOrUncertainCount':int((~valid).sum()),'samples':rows,'heightFile':'ground-samples.npz','heightSha256':digest(out/'ground-samples.npz'),
        'declaredProductTransform':source.mapping,'editorPlan':False,'nativeEditorTerrainCellLimitsMustBeRespected':True,'verticalEditorConversionRequired':True,
        'heightUsage':'editorY = productHeight + owner-selected single editorOffsetY; productHeight already includes scale and nativeYReference. Do not multiply or subtract native datum again.'})
    return {'samples':len(rows),'valid':int(valid.sum()),'missingOrUncertain':int((~valid).sum())}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--index',required=True);p.add_argument('--out',required=True);p.add_argument('--bounds',nargs=4,type=float,metavar=('XMIN','XMAX','ZMIN','ZMAX'),required=True);p.add_argument('--step',type=float,default=5);a=p.parse_args();print(json.dumps(generate_grid(project_path(a.index),project_path(a.out),a.bounds,a.step)))
