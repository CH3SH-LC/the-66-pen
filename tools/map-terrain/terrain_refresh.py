"""Explicit rendering rebuild cards. Never encode a no-op cell edit."""
from terrain_model import decode_save,select,uint,digest,require

def make_plan(blob,terrain_id,source):
    model=decode_save(blob);target=select(model,uint(terrain_id,'terrainId'))
    require(not target['unknownCellFields'],'UNKNOWN_CELL_FIELDS_REQUIRE_RESEARCH_BEFORE_REBUILD')
    return dict(schema='native-terrain-refresh-plan-v1',refreshOnly=True,terrainId=terrain_id,source=source,
                sourceSha256=digest(blob),before=target['cells'],expected=target['cells'],changes=[],edits=[],
                scope='native owner rendering/collider rebuild; logical terrain data must remain identical',saveInvoked=False)

def validate(plan,blob):
    require(plan==make_plan(blob,plan.get('terrainId'),plan.get('source')),'REFRESH_PLAN_SOURCE_OR_CONTENT_CHANGED')
    return plan

def evidence(word):
    low=word&0xffffffff
    return dict(called=bool(low&1),returned=bool(low&2),allDirtyCellsCleared=bool(low&4),logicalRowsPreserved=bool(low&8),
                tickGateKnown=bool(low&16),tickGateBefore=bool(low&32),tickGateAfter=bool(low&64),
                dirtyBeforeCount=word>>32,verified=(low&31)==31 and not low&~127 and bool(low&32)==bool(low&64))
