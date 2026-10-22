"""Single complete-module offline batch. No native/process/helper access."""
from __future__ import annotations
import argparse,copy,json,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from catalog import ROOT,sha,decode_config,tables
from cli import new_output,write,load_config
from texture import extract,decode_pixels,texture_record
from bind import bind_request
from selection import OBSERVED,SPECS
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    out=new_output(a.out);checks=[]
    def check(name,fn):
        fn();checks.append(dict(name=name,passed=True))
    def reject(name,fn):
        def run():
            try:fn()
            except (ValueError,UnicodeError):return
            raise AssertionError('did not reject '+name)
        check(name,run)
    def equal(a,b):
        if a!=b:raise AssertionError((a,b))
    cat=Path(a.catalog).resolve();assert cat.is_relative_to(ROOT)
    manifest=json.loads(cat.read_text(encoding='utf8'));rows,source=load_config()
    check('native_catalog_658_complete_rows',lambda:equal(len(rows),658))
    check('native_item_currency_counts',lambda:equal((sum(r['category']==9 for r in rows),sum(r['category']==8 for r in rows)),(135,8)))
    record=json.loads((ROOT/source['evidence']).read_text(encoding='utf8'))
    payload=(ROOT/source['evidence']).with_suffix('.bin').read_bytes()
    check('independent_cached_payload_sha',lambda:equal(sha(payload),source['payloadSha256']))
    check('independent_cached_payload_decode',lambda:equal(decode_config(payload),record['rows']))
    reject('truncated_catalog',lambda:decode_config(payload[:-1]))
    reject('trailing_catalog',lambda:decode_config(payload+b'\0'))
    reject('unknown_catalog_mask',lambda:decode_config(payload[:4]+struct.pack('<H',0x9a7a^256)+payload[6:]))
    check('native_apple_mapping',lambda:equal(next(r for r in rows if r['iconId']==90001)['string10'],'UI_ItemIcon_100001'))
    check('native_iron_mapping',lambda:equal(next(r for r in rows if r['iconId']==90036)['string10'],'UI_ItemIcon_101001'))
    check('native_gold_coin_mapping',lambda:equal(next(r for r in rows if r['iconId']==100005)['string10'],'UI_UGCItemIcon_Currency_5'))
    check('all_final_rows_match_native_config',lambda:equal({r['iconId']:r['resourcePath'] for r in manifest['rows']},{r['iconId']:r['string18']+r['string10'] for r in rows if r['category'] in (8,9)}))
    def reviewed_pixels():
        for icon,(digest,description) in OBSERVED.items():
            row=next(r for r in manifest['rows'] if r['iconId']==icon)
            equal(row['rgbaSha256'],digest);assert row['originalPixelsResolved'] and description
    check('all_nine_visual_observations_bound_to_original_pixels',reviewed_pixels)
    check('no_medaka_native_category9_entry',lambda:equal(any(r['category']==9 and r['string10']=='UI_ItemIcon_131000' for r in rows),False))
    check('semantic_gaps_not_promoted_to_exact',lambda:equal({r[0] for r in SPECS if r[3]=='exact'},{'item.apple','item.ore'}))
    decoded={};constants=tables()
    for row in manifest['rows']:
        if not row['originalPixelsResolved']:continue
        path=ROOT/row['preview']
        if path not in decoded:
            assert path.resolve().is_relative_to(ROOT)
            with Image.open(path) as im:pixel=sha(im.convert('RGBA').tobytes())
            equal(sha(path.read_bytes()),row['pngSha256']);equal(pixel,row['rgbaSha256'])
            for variant in row['variants']:
                if 'error' in variant:raise AssertionError('resolved variant contains error')
                im,proof=extract(variant['source'],constants)
                equal(proof['rgbaSha256'],pixel);equal(proof['compressedPixelSha256'],variant['compressedPixelSha256'])
                equal(proof['textureObjectSha256'],variant['textureObjectSha256'])
            decoded[path]=pixel
    check('all_resolved_originals_independently_read_and_decoded',lambda:equal(len(decoded),len({r['preview'] for r in manifest['rows'] if r['originalPixelsResolved']})))
    alpha=decode_pixels(bytes([255,0,0,1,0,255,0,128]),1,2,4)
    check('rgba_alpha_and_unity_y_orientation',lambda:equal(list(alpha.getdata()),[(0,255,0,128),(255,0,0,1)]))
    reject('unknown_texture_type',lambda:texture_record(b'','0'*32))
    reject('unknown_texture_format',lambda:decode_pixels(b'',1,1,777))
    reject('truncated_bc7',lambda:decode_pixels(b'\0'*15,4,4,25))
    freeze=json.loads((ROOT/'.runtime/template-properties-20261017/v2-final-freeze.json').read_text(encoding='utf8'))
    def frozen():
        equal(len(freeze['sourceHashes']),100)
        for rel,digest in freeze['sourceHashes'].items():equal(sha((ROOT/rel).read_bytes()),digest)
    check('v2_all_100_frozen_sources_unchanged',frozen)
    for src in sorted(Path(__file__).resolve().parents[1].rglob('*.py')):compile(src.read_text(encoding='utf8'),str(src),'exec')
    check('all_python_sources_compile',lambda:None)
    item=next(r for r in manifest['rows'] if r['kind']=='item' and r['originalPixelsResolved'])
    coin=next(r for r in manifest['rows'] if r['kind']=='currency' and r['originalPixelsResolved'])
    request=dict(schemaVersion=1,levelId=1073741843,definitions=[dict(id=0x42000001,kind='item',set=dict(name='离线道具',stackLimit=99,isTradeable=True)),dict(id=0x42800001,kind='currency',set=dict(name='离线货币'))])
    roles={'offline.item':0x42000001,'offline.currency':0x42800001}
    review=dict(catalogSha256=sha(cat.read_bytes()),rows=[dict(role=role,iconId=row['iconId'],name=name,rgbaSha256=row['rgbaSha256'],observedSubject='离线夹具，仅检查约束',match='exact') for role,row,name in [('offline.item',item,'离线道具'),('offline.currency',coin,'离线货币')]])
    result,evidence=bind_request(request,cat,review,roles)
    clean=copy.deepcopy(result)
    for row in clean['definitions']:del row['set']['iconId']
    check('bind_preserves_all_non_icon_request_fields',lambda:equal(clean,request))
    check('bind_does_not_claim_runtime_acceptance',lambda:equal((evidence['nativeDispatched'],evidence['playerPixelsVerified']),(False,False)))
    def changed_review(field,value):
        other=copy.deepcopy(review);other['rows'][0][field]=value;return bind_request(request,cat,other,roles)
    reject('wrong_kind_icon',lambda:changed_review('iconId',coin['iconId']))
    reject('unreviewed_pixel_change',lambda:changed_review('rgbaSha256','0'*64))
    reject('display_name_mismatch',lambda:changed_review('name','不同名字'))
    reject('unjustified_representative',lambda:changed_review('match','representative'))
    reject('missing_observation',lambda:changed_review('observedSubject',''))
    wrong=copy.deepcopy(request);wrong['definitions'][0]['id']=1120000001
    reject('fake_kind_band',lambda:bind_request(wrong,cat,review,roles))
    wrong=copy.deepcopy(request);wrong['levelId']=1073741842
    reject('protected_level_refused',lambda:bind_request(wrong,cat,review,roles))
    wrong=copy.deepcopy(review);wrong['catalogSha256']='0'*64
    reject('catalog_review_binding',lambda:bind_request(request,cat,wrong,roles))
    wrong=copy.deepcopy(review);wrong['rows'][0].update(match='representative',semanticDecision='测试明确保留代表性差异')
    _,rep=bind_request(request,cat,wrong,roles)
    check('representative_status_preserved',lambda:equal(rep['bindings'][0]['semanticMatch'],'representative'))
    result=dict(kind='template-icon-offline-batch',passed=True,checks=checks,originalTexturesIndependentlyDecoded=len(decoded),
                unresolved=[r['iconId'] for r in manifest['rows'] if not r['originalPixelsResolved']],
                catalog=str(cat.relative_to(ROOT)),catalogSha256=sha(cat.read_bytes()),v2FrozenSourcesPreserved=100,
                privateNativeCallbacksApplicable=False,nativeCodeAdded=False,gameConnected=False,helperStarted=False,queueDispatched=False,
                playerDisplayVerified=False,syntheticBindIdsWereNeverDispatched=True)
    write(out/'result.json',result);print(json.dumps(dict(passed=True,checks=len(checks),textures=len(decoded),result=str(out/'result.json')),ensure_ascii=False))
if __name__=='__main__':main()
