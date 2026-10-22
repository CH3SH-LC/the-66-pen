"""Pure water operations over proven native terrain fields; never edits a GIL."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/map-terrain'))
from terrain_model import (MAX_CELLS,MAX_EDITS,LIMIT,require,digest,uint,key,present,decode_save,select,
    parse_fields,encode_fields,verify_expected_save)
SCHEMA='native-terrain-water-plan-v1'
# 1845 is the user's explicitly authorized new Mondstadt save, independently
# observed on 2026-10-22. Keep a bounded allowlist plus exact cross-source identity.
AUTHORIZED_LEVELS=frozenset((1073741843,1073741845))

def authorized_level(value):
    require(type(value) is int and value in AUTHORIZED_LEVELS,'WATER_LEVEL_NOT_AUTHORIZED')
    return value
def artifact_path(value):
    from terrain_model import artifact_path as base
    path=Path(value)
    return base(path if path.is_absolute() else ROOT/path)
def apply_edits(rows,edits,water_types=None):
    require(type(edits) is list and 0<len(edits)<=MAX_EDITS,'WATER_EDITS_1_TO_4096')
    require(type(water_types) is list and water_types,'NATIVE_WATER_CATALOG_REQUIRED')
    pairs={(uint(r['materialId'],'materialId'),uint(r['typeId'],'typeId')) for r in water_types if r['renderable'] is True}
    current={r[0]:list(r) for r in rows};changes=[];seen=set()
    for edit in edits:
        require(type(edit) is dict and set(edit)<= {'x','z','op','waterType','material'},'UNKNOWN_WATER_EDIT_FIELD')
        k=key(edit.get('x'),edit.get('z'));require(k not in seen,'DUPLICATE_EDIT_COORDINATE');seen.add(k)
        before=current.get(k);op=edit.get('op');after=list(before or [k,0,0,0,0,0])
        require(op in ('replace-top','restore-top','change-water-type','create-water-only','remove-water'),'UNKNOWN_WATER_OPERATION')
        if op=='create-water-only':
            require(before is None and set(edit)=={'op','x','z','waterType','material'},'WATER_ONLY_REQUIRES_EMPTY_CELL_AND_MATERIAL')
            after[2]=uint(edit['material'],'material');after[3]=uint(edit['waterType'],'waterType')
        else:
            require(before is not None and 'material' not in edit,'WATER_OPERATION_REQUIRES_EXISTING_CELL')
            # Native water brush clears these. Reject incompatible cells rather than
            # silently discard either opaque field or pretend their combination works.
            require(before[4]==before[5]==0,'OPAQUE_EXTRA_B_C_CONFLICT_WITH_WATER')
            if op in ('replace-top','change-water-type'):
                require(set(edit)=={'op','x','z','waterType'},'WATER_TYPE_REQUIRED')
                after[3]=uint(edit['waterType'],'waterType')
                if op=='replace-top':
                    require(before[3]==0 and before[1]>0,'REPLACE_TOP_REQUIRES_DRY_NONZERO_COLUMN');after[1]-=1
                else:require(before[3]>0,'CHANGE_REQUIRES_EXISTING_WATER')
            else:
                require(set(edit)=={'op','x','z'} and before[3]>0,'REMOVE_REQUIRES_EXISTING_WATER_NO_VALUES')
                after[3]=0
                if op=='restore-top':
                    require(before[1]+1<LIMIT,'RESTORE_TOP_EXCEEDS_HEIGHT_RANGE');after[1]+=1
        if op in ('create-water-only','replace-top','change-water-type'):
            require(after[3]>0,'WATER_TYPE_MUST_BE_NONZERO')
        if before and before[3]:require((before[2],before[3]) in pairs,'EXISTING_WATER_TYPE_NOT_IN_NATIVE_CATALOG')
        if after[3]:require((after[2],after[3]) in pairs,'WATER_TYPE_NOT_RENDERABLE_FOR_MATERIAL')
        require(after!=before,'NO_OP_WATER_EDIT')
        if present(after):current[k]=after;native_op='set'
        else:current.pop(k,None);native_op='delete'
        changes.append(dict(op=native_op,key=k,before=before,after=after))
    require(len(current)<=MAX_CELLS,'TERRAIN_CAPTURE_CAPACITY')
    return changes,sorted(current.values())
def make_plan(blob,terrain_id,edits,source=None,material_source=None):
    import water_catalog
    model=decode_save(blob);target=select(model,uint(terrain_id,'terrainId'))
    require(not target['unknownCellFields'],'UNKNOWN_CELL_FIELDS_REQUIRE_RESEARCH_BEFORE_WRITE')
    water_catalog.validate_authority(material_source,terrain_id)
    level=authorized_level(material_source['levelId'])
    identity=model['otherRoot'].get('1',[])
    require(len(identity)==1,'LEVEL_ID_REQUIRED')
    fields=parse_fields(bytes.fromhex(identity[0]));require(len(fields)==1 and fields[0].wire_type==0 and fields[0].value==level,'WATER_SOURCE_CATALOG_LEVEL_MISMATCH')
    changes,expected=apply_edits(target['cells'],edits,material_source['waterTypes'])
    return dict(schema=SCHEMA,terrainId=terrain_id,source=source,sourceSha256=digest(blob),before=target['cells'],
        edits=edits,changes=changes,expected=expected,materialSource=material_source,
        capabilities=['native-water-type','water-only-empty-cell','native-top-layer-conversion','water-removal','world-matrix-guard'],
        unprovenSemantics=['pixel-appearance','player-swimming','water-surface-pixel-height','unknown-lakebed'],saveInvoked=False)
def validate_plan(plan,blob):
    require(plan.get('schema')==SCHEMA and plan.get('sourceSha256')==digest(blob),'PLAN_SOURCE_CHANGED')
    require(plan==make_plan(blob,plan['terrainId'],plan['edits'],plan.get('source'),plan.get('materialSource')),'PLAN_CONTENT_CHANGED')
    return plan
def verify_save(before_blob,after_blob,plan):
    validate_plan(plan,before_blob)
    return verify_expected_save(before_blob,after_blob,plan['terrainId'],plan['expected'],{c['key'] for c in plan['changes']})
