"""Explicit, source-locked native -> official map -> declared product frame.

The editor mapping is a product design choice, not a measured unit calibration.
The owner adds one editor offset after this transform, identically for terrain,
city geometry, water, NPCs and gameplay positions.
"""
import math
import numpy as np
from reference_cli import digest
from regional_registration import read,relative


def build_mapping(shared_path,coordinate_evidence_path,native_y_reference):
    shared=read(shared_path);source=read(coordinate_evidence_path)
    s=float(shared['scale']['value']);origin=[float(shared['originPx'][c]) for c in ('x','y')]
    if not math.isfinite(s) or s<=0 or not math.isfinite(native_y_reference):raise ValueError('Finite positive scale and explicit height reference required')
    if shared['rotationDeg']!=0 or source['officialInfo']['detail']['origin']!=origin:raise ValueError('Changed product/map frame requires new explicit derivation')
    # Source formula: official origin + (-749.75-nativeZ, 2322-nativeX).
    native_to_pixel=np.array([[0.,0.,-1.,origin[0]-749.75],[0.,1.,0.,0.],[-1.,0.,0.,origin[1]+2322.],[0.,0.,0.,1.]])
    pixel_to_product=np.array([[s,0.,0.,-s*origin[0]],[0.,s,0.,-s*native_y_reference],[0.,0.,-s,s*origin[1]],[0.,0.,0.,1.]])
    product=pixel_to_product@native_to_pixel
    return {'id':'native-source-to-declared-product-v5','sourceNativeFrame':'native-game-XYZ','officialPixelIntermediateAxes':['pixelX','nativeY','pixelY'],
        'sharedTransformSource':relative(shared_path),'sharedTransformSha256':digest(shared_path),'sharedTransformId':shared['transformId'],
        'coordinateEvidenceSource':relative(coordinate_evidence_path),'coordinateEvidenceSha256':digest(coordinate_evidence_path),'bgiCommit':source['bgiCommit'],
        'scale':s,'scaleStatus':shared['scale']['status'],'nativeYReference':native_y_reference,
        'nativeToOfficialPixelWithHeightMatrixColumnVector':native_to_pixel.tolist(),'officialPixelWithHeightToProductMatrixColumnVector':pixel_to_product.tolist(),
        'nativeToProductMatrixColumnVector':product.tolist(),'productToNativeMatrixColumnVector':np.linalg.inv(product).tolist(),
        'formula':{'productX':'s * (-749.75 - nativeZ)','productY':'s * (nativeY - nativeYReference)','productZ':'s * (nativeX - 2322)',
                   'editorY':'productY + owner-selected editorOffsetY','editorXYZ':'productXYZ + owner-selected single editorOffsetXYZ'},
        'verticalReferenceStatus':'declared product datum; not measured editor ground','defaultReferenceMeaning':'nativeYReference=0 preserves native zero; any changed reference requires changing the one shared editorOffsetY by s*deltaReference',
        'allConsumersMustUseSameMatrix':True,'editorOffsetApplied':False,'nativeToEditorMetricCalibrationEstablished':False,
        'heightAlreadyScaled':True,'warning':'Never multiply productY by scale again, subtract the native datum again, or add terrain origin more than once. NativeY remains separately available.'}


def transform_xyz(points,mapping):
    xyz=np.asarray(points,float);m=np.asarray(mapping['nativeToProductMatrixColumnVector'],float)
    if xyz.shape[-1]!=3 or not np.isfinite(xyz).all():raise ValueError('Finite XYZ required')
    return xyz@m[:3,:3].T+m[:3,3]
