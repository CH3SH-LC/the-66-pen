"""Installed icon evidence, original pixels and role selections; never dispatches."""
from __future__ import annotations
import argparse
import html
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]

CONFIG_SOURCE=ROOT/'.runtime/template-properties-20261017/icons/native-excel-catalog-source/catalog-00.json'
CATALOG_OBJECT_SHA='4e9bd8e6074138fd81d49a4c7abce986eac41bfef9ea3f162f485dc9406a9a58'
CATALOG_PAYLOAD_SHA='306835af3048b18fd7adbac2a04ea140efd331e52e62f21f58a9e8b249ce4529'

def new_output(value):
    p=Path(value)
    if not p.is_absolute():p=ROOT/p
    p=p.resolve()
    if not p.is_relative_to(ROOT) or p==ROOT or p.exists():raise ValueError('NEW_PROJECT_OUTPUT_REQUIRED')
    for q in (p,*p.parents):
        if q.exists() and (q.is_symlink() or getattr(q.stat(),'st_file_attributes',0)&0x400):
            raise ValueError('OUTPUT_REPARSE_REFUSED')
        if q==ROOT:break
    p.mkdir(parents=True);return p

def relative(path):return str(Path(path).resolve().relative_to(ROOT)).replace('\\','/')
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def load_config(path=CONFIG_SOURCE):
    """Reread exact installed object and independently decode, rejecting stale JSON."""
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('PROJECT_CONFIG_EVIDENCE_REQUIRED')
    record=json.loads(path.read_text(encoding='utf8'));raw,_=read_object(record['source'])
    import struct
    n=struct.unpack_from('<I',raw)[0];payload=raw[4:4+n]
    if sha(raw)!=record['objectSha256'] or sha(payload)!=record['payloadSha256']:raise ValueError('CONFIG_SOURCE_CHANGED')
    if sha(raw)!=CATALOG_OBJECT_SHA or sha(payload)!=CATALOG_PAYLOAD_SHA:raise ValueError('PINNED_NATIVE_CATALOG_CHANGED')
    rows=decode_config(payload)
    if rows!=record['rows']:raise ValueError('CONFIG_JSON_DIFFERS_FROM_BINARY')
    return rows,dict(evidence=relative(path),evidenceSha256=sha(path.read_bytes()),source=record['source'],
                     objectSha256=record['objectSha256'],payloadSha256=record['payloadSha256'])

def contact_sheets(out,records):
    from PIL import Image,ImageDraw,ImageFont
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',16)
    sheets=[]
    for batch in range(0,len(records),24):
        part=records[batch:batch+24];cols=6;cellw=220;cellh=206
        im=Image.new('RGB',(cols*cellw,4*cellh),(35,39,47));draw=ImageDraw.Draw(im)
        for i,record in enumerate(part):
            x=(i%cols)*cellw;y=(i//cols)*cellh
            preview=record.get('preview')
            if preview:
                src=Image.open(ROOT/preview).convert('RGBA');src.thumbnail((160,160))
                im.paste(src,(x+(cellw-src.width)//2,y+4),src)
            else:
                label={'MULTIPLE_PIXEL_VARIANTS':'多个像素版本，待确认','DECODE_FAILED':'存在未解码版本','TEXTURE_INDEX_MISS':'索引未找到原图'}.get(record.get('unresolvedReason'),'原图待确认')
                draw.text((x+12,y+65),label,font=font,fill='orange')
            draw.text((x+10,y+165),str(record['iconId']),font=font,fill='white')
            suffix=record['assetName'].replace('UI_ItemIcon_','').replace('UI_UGCItemIcon_','UGC_').replace('UI_EquipIcon_','')
            draw.text((x+10,y+185),suffix[:25],font=font,fill=(200,207,215))
        p=out/f'contact-{batch//24+1:02d}.png';im.save(p)
        sheets.append(dict(path=relative(p),sha256=sha(p.read_bytes())))
    return sheets

def build(out,locations=None,config=CONFIG_SOURCE):
    rows,source=load_config(config)
    selected=[r for r in rows if r['category'] in (8,9)]
    if locations:
        location_file=Path(locations).resolve()
        if not location_file.is_relative_to(ROOT):raise ValueError('PROJECT_LOCATIONS_REQUIRED')
        lookup=json.loads(location_file.read_text(encoding='utf8'));found=lookup['names'];lookup_proof=lookup['proof']
    else:found,lookup_proof=find_textures(r['string10'] for r in selected)
    out=new_output(out);(out/'originals').mkdir();constants=tables();records=[];cache={}
    for row in selected:
        name=row['string10']
        if not re.fullmatch('[A-Za-z0-9_]+',name):raise ValueError('UNSUPPORTED_ASSET_NAME')
        entry=dict(iconId=row['iconId'],category=row['category'],kind='item' if row['category']==9 else 'currency',
                   assetName=name,resourcePath=row['string18']+name,configOffset=row['offset'],
                   configBytes=row['size'],opaqueNativeValues={k:row[k] for k in ('value20','value28','value2c','value30')},
                   variants=[],preview=None,semanticReviewed=False,playerPixelsVerified=False)
        if name not in cache:
            variants=[]
            for j,location in enumerate(found.get(name,[])):
                try:
                    im,proof=extract(location,constants);p=out/'originals'/f'{name}-{j:02d}.png';im.save(p)
                    variants.append(dict(preview=relative(p),pngSha256=sha(p.read_bytes()),**proof))
                except (ValueError,OSError,StopIteration) as e:variants.append(dict(source=location,error=str(e)))
            cache[name]=variants
        entry['variants']=cache[name]
        decoded=[v for v in entry['variants'] if 'error' not in v]
        unique={v['rgbaSha256'] for v in decoded}
        if len(unique)==1 and len(decoded)==len(entry['variants']):
            entry['preview']=decoded[0]['preview'];entry['rgbaSha256']=decoded[0]['rgbaSha256'];entry['pngSha256']=decoded[0]['pngSha256']
            entry['originalPixelsResolved']=True
        else:
            entry['originalPixelsResolved']=False
            entry['unresolvedReason']='TEXTURE_INDEX_MISS' if not entry['variants'] else 'DECODE_FAILED' if len(decoded)!=len(entry['variants']) else 'MULTIPLE_PIXEL_VARIANTS'
        records.append(entry)
    manifest=dict(schemaVersion=1,kind='template-icon-original-catalog',source=source,lookupProof=lookup_proof,rows=records,
                  nativeCall=False,installationWrites=False,gameProcessAccess=False,
                  category8Count=sum(r['category']==8 for r in selected),category9Count=sum(r['category']==9 for r in selected),
                  originalPixelUniquenessScope='completed indexes available at lookup time, not a whole-install uniqueness proof',
                  nativeTableComplete=True,resourceIdToContainerHashVerified=False,
                  semanticSelectionComplete=False,playerPixelsVerified=False)
    manifest['contactSheets']=contact_sheets(out,records)
    write(out/'catalog.json',manifest)
    cards=[]
    for r in records:
        image=''
        if r['preview']:
            image='<img src="originals/'+html.escape(Path(r['preview']).name)+'" alt="'+html.escape(r['assetName'])+'">'
        elif r['variants']:
            for v in r['variants']:
                if v.get('preview'):
                    image+='<img src="originals/'+html.escape(Path(v['preview']).name)+'" alt="未确定原生选用版本">'
        cards.append('<article>'+image+'<b>'+str(r['iconId'])+'</b><code>'+html.escape(r['assetName'])+'</code><small>'+html.escape(r.get('unresolvedReason','原始像素已提取，语义待核实'))+'</small></article>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>原生图标原图目录</title><style>body{background:#23272f;color:#eee;font:15px system-ui}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}article{padding:12px;background:#303742;display:flex;flex-direction:column;gap:8px}img{width:160px;height:160px;object-fit:contain}code{overflow-wrap:anywhere}small{color:#ddd}</style><h1>原生图标原图目录</h1><p>实际安装资源；类别 8 为货币，类别 9 为普通道具。图标 ID 与资源文件后缀不同。此页不代表玩家实机显示验收。</p><main>'+''.join(cards)+'</main>',encoding='utf8')
    return dict(manifest=relative(out/'catalog.json'),rows=len(records),resolved=sum(r['originalPixelsResolved'] for r in records),
                unresolved=[dict(iconId=r['iconId'],assetName=r['assetName'],reason=r.get('unresolvedReason')) for r in records if not r['originalPixelsResolved']])

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('--out',required=True);b.add_argument('--locations');b.add_argument('--config',default=str(CONFIG_SOURCE))
    l=s.add_parser('locate-config');l.add_argument('--out',required=True);l.add_argument('--indexed-source',required=True)
    f=s.add_parser('find-textures');f.add_argument('--out',required=True);f.add_argument('--previous');f.add_argument('--config',default=str(CONFIG_SOURCE))
    q=s.add_parser('bind');q.add_argument('--catalog',required=True);q.add_argument('--request',required=True);q.add_argument('--review',required=True);q.add_argument('--roles',required=True);q.add_argument('--out',required=True)
    a=p.parse_args()
    global sha,decode_config,read_object,tables,find_textures,locate_config,extract
    from catalog import sha,decode_config,read_object,tables,find_textures,locate_config
    from texture import extract
    if a.command=='build':result=build(a.out,a.locations,a.config)
    elif a.command=='locate-config':result=locate_config(a.out,a.indexed_source)
    elif a.command=='find-textures':
        rows,source=load_config(a.config)
        previous=None
        if a.previous:
            path=Path(a.previous).resolve()
            if not path.is_relative_to(ROOT):raise ValueError('PROJECT_PREVIOUS_INDEX_REQUIRED')
            previous=json.loads(path.read_text(encoding='utf8'))
        names,proof=find_textures((r['string10'] for r in rows if r['category'] in (8,9)),previous)
        out=new_output(a.out);write(out/'texture-locations.json',dict(names=names,proof=proof,config=source))
        result=dict(locations=relative(out/'texture-locations.json'),names=len(names),found=sum(bool(v) for v in names.values()))
    else:
        from bind import bind_request
        def read(path):
            path=Path(path).resolve()
            if not path.is_relative_to(ROOT):raise ValueError('PROJECT_INPUT_REQUIRED')
            return json.loads(path.read_text(encoding='utf8'))
        request,evidence=bind_request(read(a.request),a.catalog,read(a.review),read(a.roles))
        out=new_output(a.out);write(out/'request.json',request);write(out/'binding.json',evidence)
        result=dict(request=relative(out/'request.json'),evidence=relative(out/'binding.json'))
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
