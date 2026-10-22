"""Bind visually reviewed installed icon selections into an existing v2 request.

Does not allocate definitions, choose names, dispatch, or bypass the later fresh
native category allowlist in v2. A review binds the exact transparent RGBA pixels.
"""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
from PIL import Image
from catalog import ROOT,sha

CONTRACT=ROOT/'tools/template-properties/v2/contract.py'
_spec=importlib.util.spec_from_file_location('template_properties_v2_icon_contract',CONTRACT)
_contract=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)

def validate_catalog(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('PROJECT_CATALOG_REQUIRED')
    raw=path.read_bytes();data=json.loads(raw)
    if data.get('kind')!='template-icon-original-catalog':raise ValueError('CATALOG_KIND')
    if len({r['iconId'] for r in data['rows']})!=len(data['rows']):raise ValueError('DUPLICATE_ICON_ID')
    return data,sha(raw)

def bind_request(request,catalog,review,roles):
    """roles maps product role to *actual* fresh configId; review supplied by owner.

    review={catalogSha256, rows:[{role, iconId, name, rgbaSha256,
    observedSubject, match:'exact'|'representative', semanticDecision}]}.
    Representative matches require an explicit nonempty product decision. This
    is a traceable product choice and is never relabelled as exact fidelity.
    """
    data,digest=validate_catalog(catalog)
    if review.get('catalogSha256')!=digest:raise ValueError('REVIEW_CATALOG_CHANGED')
    request=_contract.normalize(request)
    definitions=request['definitions']
    byid={r['id']:r for r in definitions}
    index={r['iconId']:r for r in data['rows']};result=copy.deepcopy(request)
    targets={r['id']:r for r in result['definitions']};seen=set();evidence=[]
    for choice in review.get('rows',[]):
        role=choice['role']
        if role in seen or role not in roles:raise ValueError('ROLE_MAPPING')
        seen.add(role);actual=roles[role]
        if type(actual) is not int or actual not in byid:
            raise ValueError('ACTUAL_FRESH_ID_REQUIRED')
        target=targets.get(actual)
        if not target or target['kind'] not in ('item','currency'):raise ValueError('DEFINITION_KIND')
        icon=index.get(choice['iconId'])
        if not icon or icon['kind']!=target['kind']:raise ValueError('ICON_CATEGORY_MISMATCH')
        if not icon.get('originalPixelsResolved'):raise ValueError('ORIGINAL_PIXELS_UNRESOLVED')
        if not choice.get('observedSubject') or choice.get('match') not in ('exact','representative'):
            raise ValueError('SEMANTIC_REVIEW_REQUIRED')
        if choice['match']=='representative' and not choice.get('semanticDecision'):
            raise ValueError('REPRESENTATIVE_CHOICE_NEEDS_PRODUCT_DECISION')
        if choice['name']!=target.get('set',{}).get('name'):raise ValueError('REVIEW_NAME_DIFFERS')
        image_path=(ROOT/icon['preview']).resolve()
        if not image_path.is_relative_to(ROOT):raise ValueError('PREVIEW_OUTSIDE_PROJECT')
        png=image_path.read_bytes()
        if sha(png)!=icon['pngSha256']:raise ValueError('PREVIEW_FILE_CHANGED')
        with Image.open(image_path) as im:rgba=sha(im.convert('RGBA').tobytes())
        if rgba!=icon['rgbaSha256'] or rgba!=choice['rgbaSha256']:raise ValueError('REVIEW_PIXEL_CHANGED')
        target['set']['iconId']=icon['iconId']
        evidence.append(dict(role=role,id=actual,name=choice['name'],iconId=icon['iconId'],kind=target['kind'],
                             resourcePath=icon['resourcePath'],rgbaSha256=rgba,pngSha256=icon['pngSha256'],
                             observedSubject=choice['observedSubject'],semanticMatch=choice['match'],
                             semanticDecision=choice.get('semanticDecision'),preview=icon['preview']))
    if not evidence:raise ValueError('NO_REVIEWED_SELECTIONS')
    result=_contract.normalize(result)
    return result,dict(schemaVersion=1,kind='template-icon-binding',catalogSha256=digest,bindings=evidence,
                       v2ContractSha256=sha(CONTRACT.read_bytes()),
                       nonIconRequestFieldsPreserved=True,allocatedIds=False,nativeDispatched=False,
                       playerPixelsVerified=False,requiresFreshV2NativeInspection=True)
