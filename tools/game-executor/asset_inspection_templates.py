"""Disk-only selected-template provenance and executable existing-instance batches.

OfficialPrefab wire fields are deliberately not renamed to model IDs or bounds.
No resource loader, process API, game getter or placement is invoked here.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from asset_inspection_common import *
from asset_inspection_icons import png_info, INSTALLED_SHA, INNER_SHA

OFFICIAL=Path('D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/Resource/Json/Beyond/Official/OfficialPrefab')
PLAN_KIND='asset-inspection-template-plan-v1'
SESSION_FIELDS=('schemaVersion','pid','tid','window','windowClass','processCreation','threadCreation','image')

def same_session(a,b):
    return isinstance(a,dict) and isinstance(b,dict) and all(k in a and k in b and a[k]==b[k] for k in SESSION_FIELDS)

def digest_bytes(value):return hashlib.sha256(value).hexdigest()

def wire_module():
    path=ROOT/'tools/editor-catalog/decode-mihoyobin.py'
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('_asset_inspection_official_wire',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def wire_one(fields,number,wire,*,optional=False):
    found=[x for x in fields if x['f']==number]
    if optional and not found:return None
    require(len(found)==1 and found[0]['w']==wire,'OFFICIAL_FIELD_NOT_UNIQUE:'+str(number))
    return found[0]

def decode_official(raw,wire=None):
    require(0<len(raw)<=1024*1024,'OFFICIAL_FILE_SIZE')
    wire=wire or wire_module()
    plain=bytes(v^wire.XOR_KEY for v in raw)
    try:fields=wire.parse_message(plain)
    except wire.WireError as exc:raise ValueError('OFFICIAL_WIRE_INVALID:'+str(exc)) from exc
    return fields,plain

def unclassified_reference(fields):
    root=wire_one(fields,2,2,optional=True)
    if root is None or 'm' not in root:return None
    fields=root['m']
    node=wire_one(fields,22,2,optional=True)
    if node is None or 'm' not in node:return None
    node=wire_one(node['m'],1,2,optional=True)
    if node is None or 'm' not in node:return None
    node=wire_one(node['m'],1,0,optional=True)
    return node.get('v') if node else None

def no_reparse(path):
    for value in (path,*path.parents):
        if value.exists():require(not value.is_symlink() and not(getattr(value.stat(),'st_file_attributes',0)&0x400),'INPUT_REPARSE_REFUSED')

def official_index():
    """All current files bind the selected rows; duplicate IDs never pick a file."""
    no_reparse(OFFICIAL);files=sorted(OFFICIAL.glob('*.mihoyobin'))
    require(0<len(files)<=4096,'OFFICIAL_FILE_COUNT')
    wire=wire_module();indexed={};inventory=[]
    for path in files:
        no_reparse(path);require(0<path.stat().st_size<=1024*1024,'OFFICIAL_FILE_SIZE')
        raw=path.read_bytes();fields,plain=decode_official(raw,wire)
        tid=identifier(wire_one(fields,1,0)['v'])
        require(tid not in indexed,'OFFICIAL_DUPLICATE_ROOT1_ID:'+str(tid))
        record=dict(templateId=tid,path=str(path),sha256=digest_bytes(raw),decodedSha256=digest_bytes(plain),bytes=len(raw))
        indexed[tid]=dict(source=record,wireFields=fields,raw=raw)
        inventory.append(record)
    require(files==sorted(OFFICIAL.glob('*.mihoyobin')) and all(sha(x['path'])==x['sha256'] for x in inventory),'OFFICIAL_SOURCE_CHANGED_DURING_READ')
    encoded=json.dumps(inventory,sort_keys=True,separators=(',',':')).encode('utf-8')
    return indexed,dict(root=str(OFFICIAL),fileCount=len(files),sha256=digest_bytes(encoded),files=inventory,
        decoder=str(ROOT/'tools/editor-catalog/decode-mihoyobin.py'),decoderSha256=sha(ROOT/'tools/editor-catalog/decode-mihoyobin.py'))

def selection_rows(document,include_alternatives=False):
    require(document.get('schema')=='mw-city-role-selection-verified' and isinstance(document.get('roles'),dict),'SELECTION_SCHEMA')
    pending=document.get('pendingVerification',{}).get('roles',[])
    blocked=document.get('unrealizableByEvidence',{}).get('roles',{})
    require(isinstance(pending,list) and isinstance(blocked,dict),'SELECTION_BLOCKERS_SCHEMA')
    rows=[]
    for role,item in document['roles'].items():
        require(isinstance(role,str) and role and isinstance(item,dict),'SELECTION_ROLE_SCHEMA')
        tid=identifier(item.get('templateId'));alts=item.get('alternativesSameStyle',[])
        require(isinstance(alts,list),'SELECTION_ALTERNATIVES_SCHEMA')
        ids=[tid]+([identifier(x) for x in alts] if include_alternatives else [])
        require(len(set(ids))==len(ids),'SELECTION_DUPLICATE_ID_IN_ROLE')
        grade=item.get('grade',document.get('grade',document.get('evidenceClass','unknown')))
        reasons=[]
        if role in pending:reasons.append('ROLE_ALSO_PENDING_VERIFICATION')
        if role in blocked:reasons.append('ROLE_ALSO_DECLARED_UNREALIZABLE')
        if grade not in ('thumbnail-reviewed','visual-verified','runtime-model-verified'):reasons.append('ROLE_REVIEW_GRADE_UNSUPPORTED')
        if not isinstance(item.get('evidence'),str) or not item['evidence'].strip():reasons.append('ROLE_REVIEW_EVIDENCE_MISSING')
        for n,value in enumerate(ids):
            rows.append(dict(role=role,templateId=value,primary=n==0,declaredGrade=grade,
                declaredReview=item.get('evidence') if n==0 else item.get('alternativeEvidence'),
                selectionConflict=bool(reasons),selectionIssues=reasons,choiceApprovedByThisTool=False))
    require(rows,'SELECTION_EMPTY')
    return rows

def icon_evidence(manifest_path,template_ids,catalog):
    path=Path(manifest_path).resolve();before=sha(path);document=read(path)
    require(document.get('ok') is True and document.get('kind')=='asset-inspection-icons-v1','ICON_MANIFEST_NOT_COMPLETE')
    require(document.get('sourceBundleSha256')==INSTALLED_SHA and document.get('capturedBundleSha256')==INNER_SHA,'ICON_SOURCE_VERSION')
    by_id={}
    for row in document['rows']:
        tid=identifier(row['templateId']);require(tid not in by_id,'ICON_DUPLICATE_TEMPLATE_ID');by_id[tid]=row
    result={}
    for tid in template_ids:
        row=by_id.get(tid);require(row is not None and row.get('ok') is True and row.get('thumbnailPixelsVerified') is True,'SELECTED_ICON_MISSING:'+str(tid))
        entry=catalog[str(tid)]
        require(row.get('catalog',{}).get('sourceSha256')==CATALOG_SHA and row.get('exactZipMember')==entry['iconPath'] and row.get('assetBundleSha256')==INNER_SHA,'SELECTED_ICON_IDENTITY_MISMATCH')
        picture=Path(row['imagePath']).resolve();require(picture.is_relative_to(path.parent) and picture!=path.parent,'SELECTED_ICON_PATH_OUTSIDE_MANIFEST')
        no_reparse(Path(row['imagePath']));raw=picture.read_bytes()
        require(digest_bytes(raw)==row['imageSha256'],'SELECTED_ICON_BYTES_CHANGED')
        png_info(raw)
        result[str(tid)]=dict(imagePath=str(picture),imageSha256=row['imageSha256'],exactZipMember=row['exactZipMember'],
            thumbnailPixelsVerified=True,runtimeModelAppearanceVerified=False)
    require(sha(path)==before,'ICON_MANIFEST_CHANGED_DURING_READ')
    return result,dict(path=str(path),sha256=before)

def batches_for(snapshot,template_ids):
    """Preserve every observed instance of an exact selected ID, including siblings."""
    wanted=set(template_ids);seen=set();matches=[];present={}
    for row in snapshot['entities']:
        eid=identifier(row['id']);require(eid not in seen,'BASELINE_DUPLICATE_ENTITY_ID');seen.add(eid)
        if row['configId'] in wanted:
            matches.append(dict(entityId=eid,templateId=row['configId']))
            present.setdefault(str(row['configId']),[]).append(eid)
    batches=[dict(index=i//MAX_ENTITIES,entityIds=[x['entityId'] for x in matches[i:i+MAX_ENTITIES]],
        templateIds={str(x['entityId']):x['templateId'] for x in matches[i:i+MAX_ENTITIES]}) for i in range(0,len(matches),MAX_ENTITIES)]
    return batches,present,[v for v in template_ids if str(v) not in present]

def make_plan(selection_path,icons_path,out,*,baseline=None,include_alternatives=False):
    selection_path=Path(selection_path).resolve();selection_sha=sha(selection_path)
    selection=selection_rows(read(selection_path),include_alternatives)
    tids=list(dict.fromkeys(x['templateId'] for x in selection));catalog=catalog_evidence(tids)
    require(all(x['found'] for x in catalog.values()),'SELECTED_TEMPLATE_NOT_IN_FROZEN_CATALOG')
    icons,icon_source=icon_evidence(icons_path,tids,catalog);indexed,inventory=official_index()
    require(set(tids)<=indexed.keys(),'SELECTED_TEMPLATE_NOT_IN_OFFICIAL_FILES')
    batches=[];present={};missing=tids;session=None;level=None;baseline_source=None
    if baseline:
        import build as b
        session,snapshot,_=b.baseline(baseline,require_fresh=False)
        level=snapshot['levelObservation']['levelId'];batches,present,missing=batches_for(snapshot,tids)
        baseline_source=dict(run=str(Path(baseline).resolve()),evidence={name:sha(Path(baseline)/name) for name in ('prepared.json','build-result.json','stdout.jsonl','exit.json')})
    rows=[]
    for tid in tids:
        record=indexed[tid];roles=[x for x in selection if x['templateId']==tid]
        rows.append(dict(templateId=tid,catalog=catalog[str(tid)],roles=roles,thumbnail=icons[str(tid)],
            officialTemplateFile=record['source'],wireFields=record['wireFields'],
            unclassifiedField2_22_1_1=unclassified_reference(record['wireFields']),
            registryIdentityBasis='OfficialPrefab root field 1 equals exact catalog registryId; no name matching',
            templateResourceIdentityVerified=True,modelIdentityVerified=False,modelAssetPath=None,
            boundsRenderer=None,boundsCollider=None,originConvention='unknown',
            geometryMeasured=False,blocksSizeBasedPlacement=True,sampleEntityIds=present.get(str(tid),[]),
            measurementStatus=('existing-instances-require-native-measurement' if str(tid) in present else 'no-observed-instance'),
            needsPlacementToUseCurrentMeasurementInterface=str(tid) not in present,
            selectionConflict=any(x['selectionConflict'] for x in roles)))
    require(sha(selection_path)==selection_sha,'SELECTION_CHANGED_DURING_READ')
    out=guarded_output(out);require(not out.exists(),'TEMPLATE_PLAN_OUTPUT_MUST_BE_NEW');out.mkdir(parents=True)
    raw_dir=out/'official-files';raw_dir.mkdir()
    for row in rows:
        path=raw_dir/(str(row['templateId'])+'.mihoyobin')
        with path.open('xb') as stream:stream.write(indexed[row['templateId']]['raw'])
        row['capturedOfficialFile']=dict(path=str(path),sha256=sha(path))
    write(out/'official-source-inventory.json',inventory)
    for batch in batches:
        batch['prepareArgv']=['python','-B',str(HERE/'asset_inspection.py'),'prepare-batch','--plan',str(out/'plan.json'),'--batch',str(batch['index']),'--baseline','FRESH_BASELINE_RUN']
    result=dict(ok=True,kind=PLAN_KIND,out=str(out),selection=dict(path=str(selection_path),sha256=selection_sha,includeAlternatives=include_alternatives),
        icons=icon_source,officialInventory=dict(path=str(out/'official-source-inventory.json'),sha256=sha(out/'official-source-inventory.json')),
        baseline=baseline_source,session=session,levelId=level,rows=rows,templateCount=len(rows),
        batches=batches,entityCount=sum(len(x['entityIds']) for x in batches),missingTemplateIds=missing,
        measurementCoverageComplete=False,allSelectedTemplatesHaveObservedInstances=not missing,
        freshBaselineRequiredForPreparation=True,existingInstancesOnly=True,unplacedGeometryQueryAvailable=False,
        blockedRoles=list(dict.fromkeys(x['role'] for x in selection if x['selectionConflict'])),
        called=False,gameProcessAccessed=False,dispatchAttempted=False,gameWritesPerformed=False,
        note='A plan is not a measurement or placement authorization. Missing templates require a separately authorized sample-placement batch or a newly proven asset-only geometry reader.')
    write(out/'plan.json',result);return result

def prepare_batch(plan_path,batch_index,fresh_baseline):
    """Revalidate selections and associations, then build one normal read-only card."""
    import build as b
    from asset_inspection_build import prepare
    path=Path(plan_path).resolve();digest=sha(path);document=read(path)
    require(document.get('kind')==PLAN_KIND and document.get('ok') is True,'TEMPLATE_PLAN_SCHEMA')
    require(document.get('baseline') is not None,'TEMPLATE_PLAN_HAS_NO_OBSERVED_BASELINE')
    selection=document['selection'];require(sha(selection['path'])==selection['sha256'],'SELECTION_CHANGED_REPLAN_REQUIRED')
    fresh_selection=selection_rows(read(selection['path']),selection['includeAlternatives'])
    tids=list(dict.fromkeys(x['templateId'] for x in fresh_selection))
    require([x['templateId'] for x in document['rows']]==tids,'PLAN_SELECTION_ID_MISMATCH')
    require(sha(document['icons']['path'])==document['icons']['sha256'],'PLAN_ICON_MANIFEST_CHANGED')
    icon_evidence(document['icons']['path'],tids,catalog_evidence(tids))
    wire=wire_module()
    for row in document['rows']:
        for key in ('officialTemplateFile','capturedOfficialFile'):
            require(sha(row[key]['path'])==row[key]['sha256'],'PLAN_OFFICIAL_SOURCE_CHANGED')
            fields,_=decode_official(Path(row[key]['path']).read_bytes(),wire)
            require(wire_one(fields,1,0)['v']==row['templateId'],'PLAN_OFFICIAL_TEMPLATE_ID_MISMATCH')
    session,snapshot,_=b.baseline(fresh_baseline)
    require(same_session(session,document['session']) and snapshot['levelObservation']['levelId']==document['levelId'],'PLAN_SESSION_OR_LEVEL_CHANGED_REPLAN_REQUIRED')
    batches,_,_=batches_for(snapshot,tids)
    require(type(batch_index) is int and 0<=batch_index<len(batches),'PLAN_BATCH_INDEX')
    expected=[{k:x[k] for k in ('index','entityIds','templateIds')} for x in document['batches']]
    require(batches==expected,'PLAN_INSTANCE_SET_CHANGED_REPLAN_REQUIRED')
    require(sha(path)==digest and sha(selection['path'])==selection['sha256'],'PLAN_CHANGED_DURING_PREPARATION')
    binding=dict(plan=str(path),planSha256=digest,batchIndex=batch_index,selection=selection,
        templateIds=batches[batch_index]['templateIds'],scope='measurement only; selected roles or appearances are not approved')
    return prepare(SimpleNamespace(baseline=fresh_baseline,entity_id=batches[batch_index]['entityIds'],measurement_plan=binding))

def template_report(plan_path,runs):
    from asset_inspection_receipt import decode
    path=Path(plan_path).resolve();digest=sha(path);plan=read(path)
    require(plan.get('kind')==PLAN_KIND and plan.get('ok') is True,'TEMPLATE_PLAN_SCHEMA')
    require(sha(plan['selection']['path'])==plan['selection']['sha256'],'SELECTION_CHANGED_REPLAN_REQUIRED')
    allowed={eid:tid for batch in plan['batches'] for eid,tid in batch['templateIds'].items()}
    groups={};seen=set();receipts=[]
    for run in runs:
        report=decode(run)
        require(report.get('ok') is True and report.get('queryComplete') is True and report.get('sceneUnchanged') is True and report.get('cleanupVerified') is True,'TEMPLATE_REPORT_REQUIRES_COMPLETE_RAW_RUN')
        require(same_session(report['session'],plan['session']) and report['levelId']==plan['levelId'],'TEMPLATE_REPORT_SESSION_OR_LEVEL')
        binding=report.get('measurementPlan') or {}
        require(binding.get('planSha256')==digest and binding.get('plan')==str(path),'TEMPLATE_REPORT_CARD_PLAN_BINDING')
        for sample in report['measurements']:
            eid=sample['entityId'];tid=sample['templateId']
            require(eid not in seen and allowed.get(str(eid))==tid,'TEMPLATE_REPORT_UNKNOWN_OR_DUPLICATE_SAMPLE')
            seen.add(eid);groups.setdefault(tid,[]).append(dict(sample,sourceRun=report['run'],rawReceiptSha256=report['rawReceiptSha256']))
        receipts.append(dict(run=report['run'],rawReceiptSha256=report['rawReceiptSha256']))
    output=[]
    for row in plan['rows']:
        tid=row['templateId'];samples=groups.get(tid,[])
        complete=bool(row['sampleEntityIds']) and {x['entityId'] for x in samples}==set(row['sampleEntityIds'])
        if complete:summary=template_summary(samples)
        else:summary=dict(registryId=tid,nameZh=row['catalog']['name'],iconPath=row['catalog']['iconPath'],
            assetPath=None,boundsRenderer=None,boundsCollider=None,originConvention='unknown',sampleEntityIds=[x['entityId'] for x in samples],
            geometryMeasurementComplete=False,blocksSizeBasedPlacement=True)
        summary.update(selectedRoles=row['roles'],allPlannedInstancesMeasured=complete,selectionConflict=row['selectionConflict'],
            thumbnail=row['thumbnail'],officialTemplateFile=row['officialTemplateFile'],
            runtimeModelAppearanceVerified=False,modelIdentityVerified=False)
        summary['blocksSizeBasedPlacement']=summary['blocksSizeBasedPlacement'] or row['selectionConflict']
        output.append(summary)
    require(sha(path)==digest,'PLAN_CHANGED_DURING_REPORT')
    return dict(ok=True,kind='asset-inspection-template-report-v1',schema='mw-asset-inspection',cityTemplates=output,
        selection=plan['selection'],plan=dict(path=str(path),sha256=digest),evidence=receipts,
        measuredEntityCount=len(seen),missingTemplateIds=plan['missingTemplateIds'],
        allSelectedGeometryMeasured=bool(output) and all(x['allPlannedInstancesMeasured'] and x['geometryMeasurementComplete'] for x in output),
        allSelectedSizeEvidenceReady=bool(output) and all(not x['blocksSizeBasedPlacement'] for x in output),
        appearanceVerified=False,gameProcessAccessed=False,called=False)
