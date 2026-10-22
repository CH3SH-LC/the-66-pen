"""Exact catalog-path PNG extraction from the already captured current editor bundle."""
import hashlib
import html
import importlib.util
import struct
import zipfile
import zlib
from asset_inspection_common import *

CAPTURE=ROOT/'.runtime/verification/update-repair-20260925/catalog/assets-7.1'
INSTALLED=Path('D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/BeyondAssets/assets.bin')
INSTALLED_SHA='56192782880aface63b3a1fb476c697d338620c84e4e39bf8725300ba14b8bd2'
INNER_SHA='7732753516194687323a72bd28642ca9912320fad94634cb27762c1515ee4ac3'

# W3C PNG section 8.1: (first column, first row, column step, row step).
# Empty reduced images have no scanlines and therefore no filter bytes.
ADAM7=((0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2))
PNG_DECODE_BUDGET=64*1024*1024

def png_passes(width,height,channels,depth,interlace):
    passes=[]
    for number,(x,y,dx,dy) in enumerate(ADAM7 if interlace else ((0,0,1,1),),1):
        w=max(0,(width-x+dx-1)//dx);h=max(0,(height-y+dy-1)//dy)
        if not w or not h:continue
        stride=(w*channels*depth+7)//8
        passes.append(dict(passNumber=number,width=w,height=h,rowBytes=stride,filteredBytes=h*(stride+1)))
    return passes

def png_info(raw):
    require(len(raw)<=16*1024*1024 and raw.startswith(b'\x89PNG\r\n\x1a\n'),'ICON_NOT_BOUNDED_PNG')
    at=8;chunks=[];compressed=[];header=None;idat_closed=False
    while at<len(raw):
        require(at+12<=len(raw),'PNG_CHUNK_TRUNCATED')
        n=struct.unpack_from('>I',raw,at)[0];kind=raw[at+4:at+8];end=at+12+n
        require(end<=len(raw),'PNG_CHUNK_TRUNCATED');value=raw[at+8:at+8+n]
        require(zlib.crc32(kind+value)&0xffffffff==struct.unpack_from('>I',raw,at+8+n)[0],'PNG_CRC_MISMATCH')
        if kind==b'IHDR':require(not chunks and n==13,'PNG_IHDR');header=struct.unpack('>IIBBBBB',value)
        if kind==b'IDAT':
            require(not idat_closed,'PNG_IDAT_NOT_CONTIGUOUS');compressed.append(value)
        elif compressed:idat_closed=True
        chunks.append(kind);at=end
        if kind==b'IEND':require(n==0 and at==len(raw),'PNG_TRAILING_DATA');break
    require(header is not None and chunks[-1:]==[b'IEND'] and compressed,'PNG_STRUCTURE')
    w,h,depth,color,compression,filter_method,interlace=header
    require(0<w<=8192 and 0<h<=8192 and compression==filter_method==0,'PNG_HEADER')
    channels={0:1,2:3,3:1,4:2,6:4}.get(color)
    allowed={0:(1,2,4,8,16),2:(8,16),3:(1,2,4,8),4:(8,16),6:(8,16)}
    require(channels is not None and depth in allowed[color] and interlace in (0,1),'PNG_UNSUPPORTED_FORMAT')
    passes=png_passes(w,h,channels,depth,interlace);expected=sum(x['filteredBytes'] for x in passes)
    require(0<expected<=PNG_DECODE_BUDGET,'PNG_DECODE_LIMIT')
    decoder=zlib.decompressobj()
    try:pixels=decoder.decompress(b''.join(compressed),expected+1)
    except zlib.error as exc:raise ValueError('PNG_DEFLATE_INVALID') from exc
    require(len(pixels)==expected and decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,'PNG_DECODE_SIZE')
    offset=0
    for part in passes:
        stride=part['rowBytes']+1
        require(all(pixels[offset+y*stride]<=4 for y in range(part['height'])),'PNG_FILTER_TYPE')
        offset+=part['filteredBytes']
    require(offset==len(pixels),'PNG_PASS_LAYOUT_MISMATCH')
    return dict(width=w,height=h,bitDepth=depth,colorType=color,interlace=interlace,
        decodedScanlineBytes=len(pixels),passes=passes,crcVerified=True,decodedScanlinesVerified=True,
        validationScope='bounded filtered scanline lengths and filter bytes; no color rendering or appearance judgment')

def loader_password():
    # Reuse the established editor-loader decoder rather than invent credentials.
    path=ROOT/'tools/editor-catalog/extract-assets-bin.py'
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('_asset_inspection_existing_zip_loader',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.PASSWORD

def ids_from_role_catalog(path,include_alternatives=False):
    path=Path(path).resolve();digest=sha(path);document=read(path)
    require(document.get('schema')=='mw-role-catalog' and isinstance(document.get('roles'),list),'ROLE_CATALOG_SCHEMA')
    selected=[];associations=[]
    for row in document['roles']:
        require(isinstance(row,dict) and isinstance(row.get('role'),str),'ROLE_CATALOG_ROW')
        primary=identifier(row.get('templateId'));alternatives=row.get('alternativeIds',[])
        require(isinstance(alternatives,list),'ROLE_CATALOG_ALTERNATIVES')
        ids=[primary]+([identifier(x) for x in alternatives] if include_alternatives else [])
        selected.extend(ids);associations.append(dict(role=row['role'],selectedTemplateId=primary,previewTemplateIds=ids,
            roleChoiceVerified=False))
    require(selected and sha(path)==digest,'ROLE_CATALOG_EMPTY_OR_CHANGED')
    return list(dict.fromkeys(selected)),dict(path=str(path),sha256=digest,includeAlternatives=include_alternatives,
        associations=associations,scope='Preview declared IDs only; no name resolver, minimum-ID choice or approval of old role mapping')

def extract(template_ids,out):
    ids=[identifier(v) for v in template_ids]
    require(ids and len(ids)==len(set(ids)),'ICON_UNIQUE_TEMPLATE_IDS_REQUIRED')
    evidence=catalog_evidence(ids)
    require(sha(INSTALLED)==INSTALLED_SHA,'CURRENT_EDITOR_BUNDLE_CHANGED')
    manifest_path=CAPTURE/'assets-manifest.json';manifest=read(manifest_path)
    rows=[x for x in manifest['archives'] if x['output']=='assets.dec'];require(len(rows)==1,'ASSET_CAPTURE_MANIFEST')
    capture=rows[0];require(capture['sha256']==INSTALLED_SHA and capture['decrypted_sha256']==INNER_SHA,'ASSET_CAPTURE_NOT_CURRENT')
    bundle=CAPTURE/'assets.dec';require(sha(bundle)==INNER_SHA,'ASSET_CAPTURE_CHANGED')
    out=guarded_output(out);require(not out.exists(),'ICON_OUTPUT_MUST_BE_NEW');out.mkdir(parents=True);(out/'icons').mkdir()
    password=loader_password();results=[];cards=[]
    with zipfile.ZipFile(bundle) as archive:
        members=archive.infolist();require(len({x.filename for x in members})==len(members),'ASSET_DUPLICATE_MEMBER_NAMES')
        indexed={x.filename:x for x in members}
        for tid in ids:
            item=evidence[str(tid)];member=item['iconPath'];record=dict(templateId=tid,catalog=item,appearanceVerified=False,runtimeModelAppearanceVerified=False)
            if not member or member not in indexed:
                record.update(ok=False,error='EXACT_CATALOG_ICON_PATH_UNAVAILABLE',thumbnailPixelsVerified=False)
            else:
                entry=indexed[member];require(not entry.is_dir() and 0<entry.file_size<=16*1024*1024,'ICON_MEMBER_SIZE')
                raw=archive.read(entry,pwd=password);require(len(raw)==entry.file_size,'ICON_READ_LENGTH')
                detail=png_info(raw);digest=hashlib.sha256(raw).hexdigest();name=f'{tid}-{digest[:16]}.png'
                target=out/'icons'/name
                with target.open('xb') as stream:stream.write(raw)
                record.update(ok=True,thumbnailPixelsVerified=True,imagePath=str(target),imageSha256=digest,png=detail,
                    exactZipMember=entry.filename,zipCrc32=entry.CRC,assetBundleSha256=INNER_SHA,
                    visualReviewRequired=True,evidenceScope='Native catalog thumbnail pixels, not a runtime model render or full material inspection')
                cards.append('<article><img loading="lazy" src="icons/'+name+'" alt="'+html.escape(item['name'] or '')+'"><strong>'+str(tid)+' '+html.escape(item['name'] or '')+'</strong><code>'+html.escape(member)+'</code><p>真实目录缩略图；尚未判定蒙德风格适配，不能代替模型全貌与尺寸。</p></article>')
            results.append(record)
    require(sha(INSTALLED)==INSTALLED_SHA and sha(bundle)==INNER_SHA,'ASSET_SOURCE_CHANGED_DURING_READ')
    page='<!doctype html><meta charset="utf-8"><title>模板原生缩略图证据</title><style>body{font:16px sans-serif;background:#eee;color:#222;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}article{background:white;padding:12px}img{display:block;width:100%;height:256px;object-fit:contain;background:#333}strong,code{display:block;margin-top:8px}code{word-break:break-all;font-size:11px}p{font-size:13px}</style><h1>按模板 ID 精确关联的原生缩略图</h1><p>来源为当前安装版本资产的既有只读副本。未操作游戏或桌面；无名称猜测或最小 ID 选择。</p><main>'+''.join(cards)+'</main>'
    (out/'index.html').write_text(page,encoding='utf-8')
    result=dict(ok=all(x['ok'] for x in results),kind='asset-inspection-icons-v1',out=str(out),preview=str(out/'index.html'),
        sourceBundle=str(INSTALLED),sourceBundleSha256=INSTALLED_SHA,capturedBundle=str(bundle),capturedBundleSha256=INNER_SHA,
        captureManifest=str(manifest_path),captureManifestSha256=sha(manifest_path),rows=results,
        called=False,gameProcessAccessed=False,desktopAccessed=False,appearanceVerified=False)
    write(out/'manifest.json',result);return result
