"""Bounded original texture extraction through the shared static BundleReader.

Pinned layout reference: Escartem/AnimeStudio e616e3f824f47dd68cfbd44977bf8584756ac446,
AnimeStudio/Classes/Texture2D.cs. Only the installed Genshin 2017 type hashes
explicitly described there are accepted. No heuristic field searching.
"""
from __future__ import annotations
import io
import struct
from PIL import Image
from catalog import read_object,sha
from serialized_reference import Reader,metadata

HASH_GNF='1d52bb98aa5f54c67c22c39e8b2e400f'
HASH_EXTERNAL='5390a985f58d5524f95db240e8789704'

def texture_record(raw,type_hash):
    if type_hash not in (HASH_GNF,HASH_EXTERNAL):raise ValueError('UNSUPPORTED_TEXTURE_TYPE_HASH')
    r=Reader(raw);name=r.string();fallback=r.read('i');downscale=r.read('B');r.align()
    width,height,complete,fmt,mips=[r.read('i') for _ in range(5)]
    readable=r.read('B')
    gnf=r.read('B') if type_hash==HASH_GNF else None
    r.align();group=r.read('i') if type_hash==HASH_GNF else None
    images=r.read('i');dimension=r.read('i')
    settings=[r.read('i'),r.read('i'),r.read('f'),r.read('i'),r.read('i'),r.read('i')]
    lightmap=r.read('i');color_space=r.read('i');image_size=r.read('i')
    if not 1<=width<=4096 or not 1<=height<=4096 or images!=1 or dimension!=2:
        raise ValueError('TEXTURE_DIMENSION_BOUNDS')
    if gnf:raise ValueError('GNF_TEXTURE_UNSUPPORTED')
    stream=None;inline=None
    if image_size==0:
        relative=r.read('I');offset=r.read('I');size=r.read('I');path=r.string()
        stream=dict(externalMipRelativeOffset=relative,offset=offset,size=size,path=path)
        if relative:raise ValueError('EXTERNAL_MIP_RELATIVE_UNSUPPORTED')
    elif 0<image_size<=64*1024**2:inline=r.take(image_size)
    else:raise ValueError('TEXTURE_DATA_SIZE')
    if r.p!=len(raw):raise ValueError('TEXTURE_TRAILING_BYTES')
    return dict(name=name,width=width,height=height,completeImageSize=complete,format=fmt,mips=mips,
                stream=stream,inline=inline,typeHash=type_hash,readable=readable,group=group,
                fallback=fallback,downscale=downscale,colorSpace=color_space,lightmapFormat=lightmap,
                settings=settings)

def decode_pixels(raw,width,height,fmt):
    if fmt in (10,12,25):
        block=8 if fmt==10 else 16
        n=((width+3)//4)*((height+3)//4)*block
        if len(raw)<n:raise ValueError('TRUNCATED_BLOCK_TEXTURE')
        fourcc=b'DXT1' if fmt==10 else b'DXT5' if fmt==12 else b'DX10'
        header=struct.pack('<7I',124,0x81007,height,width,n,0,1)+bytes(44)
        header+=struct.pack('<II4s5I',32,4,fourcc,0,0,0,0,0)
        header+=struct.pack('<5I',0x1000,0,0,0,0)
        if fmt==25:header+=struct.pack('<5I',98,3,0,1,0)
        image=Image.open(io.BytesIO(b'DDS '+header+raw[:n])).convert('RGBA')
    elif fmt in (3,4,5,14):
        mode={3:'RGB',4:'RGBA',5:'ARGB',14:'BGRA'}[fmt]
        n=width*height*(3 if fmt==3 else 4)
        if len(raw)<n:raise ValueError('TRUNCATED_RAW_TEXTURE')
        image=Image.frombytes('RGB' if fmt==3 else 'RGBA',(width,height),raw[:n],'raw',mode).convert('RGBA')
    else:raise ValueError('UNSUPPORTED_TEXTURE_FORMAT_'+str(fmt))
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

def extract(row,constants=None):
    if row['object']['classId']!=28:raise ValueError('TEXTURE_CLASS_REQUIRED')
    raw,b=read_object(row,constants);ni=row['nodeIndex'];header=b.read(ni,0,20)
    start=struct.unpack_from('>I',header,12)[0]
    if start>16*1024**2:raise ValueError('METADATA_BOUNDS')
    meta=metadata(b.read(ni,0,start),b.meta['nodes'][ni]['size'])
    if meta['unityVersion'].split('\n')[0]!='2017.4.30f1':raise ValueError('UNITY_VERSION_CHANGED')
    exact=next(x for x in meta['objects'] if x['pathId']==row['object']['pathId'])
    if any(exact[k]!=row['object'][k] for k in ('size','offset','classId','typeId')):raise ValueError('OBJECT_INDEX_CHANGED')
    data=texture_record(raw,meta['types'][exact['typeId']]['typeHash'])
    if data['name']!=row['object']['name']:raise ValueError('TEXTURE_NAME_CHANGED')
    stream=data['stream']
    if stream:
        node_path=stream['path'].replace('\\','/').split('/')[-1]
        matches=[(i,n) for i,n in enumerate(b.meta['nodes']) if n['path'].lower()==node_path.lower()]
        if len(matches)!=1:raise ValueError('STREAM_NOT_IN_EXACT_BUNDLE')
        stream_id,node=matches[0]
        pixels=b.read(stream_id,stream['offset'],stream['size'])
    else:pixels=data.pop('inline')
    data.pop('inline',None)
    if len(pixels)!=data['completeImageSize']:raise ValueError('IMAGE_SIZE_MISMATCH')
    image=decode_pixels(pixels,data['width'],data['height'],data['format'])
    rgba=image.tobytes()
    return image,dict(source=row,texture=data,textureObjectSha256=sha(raw),compressedPixelSha256=sha(pixels),
                      rgbaSha256=sha(rgba),rgbaBytes=len(rgba),orientation='top-left RGBA; source Unity Y flipped',
                      installationWrites=False,gameProcessAccess=False)
