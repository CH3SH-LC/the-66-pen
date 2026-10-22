"""Decode fresh, complete reopen prerequisites from raw receipts. Never executes an action."""
from datetime import datetime, timezone
from pathlib import Path
import native_profiles as profiles
import native_write_review as review
import build_readonly_profile as readonly
import native_level_catalog as catalog
import native_lifecycle_type as lifecycle
import native_scheduler_coroutines as scheduler
import native_reopen_guards as guards

LEVEL = 1073741840
SESSION_FIELDS = review.SESSION_FIELDS
REQUIRED_ARTIFACTS=frozenset(('prepared.json','target_config.h','hook_receipt.dll','hook_receipt_probe.exe','invoke-readonly-probe.ps1'))
REQUIRED_SOURCES=frozenset(readonly.SOURCES)|frozenset(
    name for stem in ('game_level_catalog','game_lifecycle_type','game_scheduler_coroutines')
    for name in (stem+'.cpp',stem+'.h',stem+'_core.inc'))|frozenset(
    ('game_reopen_guards.cpp','game_reopen_guards.h','game_reopen_guards_capture.cpp','game_reopen_guards_capture_core.inc','guard_profile.generated.h'))


def validate_file_bindings(run, prepared, built):
    hashes=built.get('hashes');sources=prepared.get('sources')
    profiles.require(type(hashes) is dict and REQUIRED_ARTIFACTS<=set(hashes),'REOPEN_ARTIFACT_PIN_SET')
    profiles.require(type(sources) is dict and REQUIRED_SOURCES<=set(sources),'REOPEN_SOURCE_PIN_SET')
    profiles.require(Path(built.get('run','')).resolve()==run and built.get('targetPid')==prepared['session']['pid'] and built.get('targetTid')==prepared['session']['tid'],'REOPEN_BUILD_RUN_BINDING')
    native=Path(__file__).with_name('native').resolve()
    for name,digest in hashes.items():
        item=(run/name).resolve()
        profiles.require(item.parent==run and profiles.sha256(item)==digest,'REOPEN_ARTIFACT_CHANGED:'+name)
    for name,digest in sources.items():
        item=(native/name).resolve()
        profiles.require(item.parent==native and profiles.sha256(item)==digest,'REOPEN_NATIVE_SOURCE_CHANGED:'+name)


def load(run_path, session, *, now=None, max_age_seconds=180):
    run=review.project_evidence(run_path)
    p=review.read_json(run/'prepared.json'); b=review.read_json(run/'build-result.json')
    profiles.require(type(max_age_seconds) is int and 0<max_age_seconds<=300,'REOPEN_BASELINE_AGE_BOUND')
    profiles.require(p.get('launchable') is True and p.get('compileOnly') is False and p.get('allowWrites') is False,'REOPEN_BASELINE_NOT_READONLY')
    profiles.require(p.get('profileSha256')==profiles.PROFILE_SHA256,'REOPEN_BASELINE_PROFILE')
    for key in SESSION_FIELDS:
        profiles.require(p.get('session',{}).get(key)==session.get(key),'REOPEN_SESSION_BINDING:'+key)
    validate_file_bindings(run,p,b)
    x=review.read_json(run/'exit.json')
    profiles.require(x.get('executed') is True and x.get('exitCode')==0 and x.get('error') is None,'REOPEN_BASELINE_EXECUTION_FAILED')
    finished=datetime.fromisoformat(x['finishedUtc'].replace('Z','+00:00'))
    current=now or datetime.now(timezone.utc)
    profiles.require(finished.tzinfo is not None and current.tzinfo is not None and 0<=(current-finished).total_seconds()<=max_age_seconds,'REOPEN_BASELINE_EXPIRED')
    dec=readonly.load_decoder();record,_=dec.read_probe(run/'stdout.jsonl');context=dec.decode_snapshot(record)
    base=readonly.validate_receipt(record,context,p,profiles.load_profile())
    profiles.require(base['ok'] and base['baselineNonempty'] and context['levelObservation']['levelId']==LEVEL,'REOPEN_BASELINE_CONTEXT_FAILED')
    profiles.require(p.get('levelCatalogProfileSha256')==catalog.PROFILE_SHA256,'REOPEN_CATALOG_PROFILE')
    context['levelCatalog']=catalog.decode(record,context,catalog.load_profile())
    profiles.require(context['levelCatalog']['ok'],'REOPEN_CATALOG_FAILED')
    profiles.require(p.get('lifecycleTypeProfileSha256')==lifecycle.PROFILE_SHA256,'REOPEN_TYPE_PROFILE')
    context['lifecycleType']=lifecycle.decode(record,context,lifecycle.load_profile())
    profiles.require(context['lifecycleType']['ok'],'REOPEN_TYPE_FAILED')
    profiles.require(p.get('schedulerCoroutinesProfileSha256')==scheduler.PROFILE_SHA256 and p.get('schedulerCoroutinesDecoderSha256')==profiles.sha256(Path(scheduler.__file__)),'REOPEN_SCHEDULER_BINDING')
    context['schedulerCoroutines']=scheduler.decode(record,context,scheduler.load_profile())
    s=context['schedulerCoroutines']
    profiles.require(s['ok'] and s['logicalListComplete'] and s['counts']['targetCount']==0,'REOPEN_SCHEDULER_FAILED_OR_TARGET_PRESENT')
    # Released holders are not active reloads. Unknown live/reference layouts remain refused.
    profiles.require(all(row['classification'] in ('null_handle','released_holder','other_class') for row in s['rows']),'REOPEN_SCHEDULER_UNKNOWN_REFERENCE')
    profiles.require(p.get('reopenGuardsProfileSha256')==guards.PROFILE_SHA256 and p.get('reopenGuardsHeaderSha256')==guards.HEADER_SHA256 and p.get('reopenGuardsDecoderSha256')==profiles.sha256(Path(guards.__file__)),'REOPEN_GUARD_BINDING')
    context['reopenGuards']=guards.decode(record,context,guards.load_profile(),p)
    g=context['reopenGuards']
    profiles.require(g['ok'] and g['bothFalseProven'] and g['confirmation'] is False and g['earlyAbort'] is False,'REOPEN_GUARDS_NOT_FALSE')
    profiles.require(context['levelCatalog']['counts']['dirtyByte']==0,'REOPEN_UNSAVED_CHANGES')
    return {'ok':True,'scope':'reopen-prerequisites-only','baselineRun':str(run),'prepared':p,'context':context,
            'finishedUtc':x['finishedUtc'],'reopenInvoked':False,'businessVerified':False,
            'evidenceHashes':{n:profiles.sha256(run/n) for n in ('prepared.json','build-result.json','stdout.jsonl','exit.json')}}
