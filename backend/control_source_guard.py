"""Explicit control-source attribution for one automatic playtest round (D24.01.03).

REQUIREMENT (docs/ds-handoff/18-DS-GPTSOL-BASIC4H-SCOPE-20261005.json, leaf D24.01.03)
    basicBehavior : 为一次自动测试逐步记录控制来源，人工步骤显式标注
    positiveCheck : 对照真实控制回执与运行变化；若任何关键操作由人完成则自动控制项不通过
    original      : 人工参与必须明记，不冒充自动控制完成

WHAT THE MAIN TREE DOES WITH THIS MODULE
    ``backend/runtime_observation._control_status`` and ``backend/runtime_bundle.
    _check_run_control`` are the two halves of the frozen ``runtime-control/1`` contract.
    Both call :func:`audit_control_record` here so the two halves decide *where control came
    from* in exactly one place and cannot drift:

    * the projection half reports the per-step ledger in ``runControl.controlSource`` /
      ``runControl.controlSteps`` and refuses a mislabelled record *before* any capability;
    * the assembly half refuses the same mislabelled record at assembly time.

    Before this module the halves disagreed: a caller-supplied ``startStopMode='automated'``
    record was refused by the assembly half (``BUNDLE_CONTROL_AUTOMATED_UNPROVEN``) but the
    projection half accepted it and reported ``capability='automated'`` with no refusal --
    i.e. a fabricated "automated control" was laundered into a capability, which is exactly
    人工参与冒充自动控制完成.

DESIGN
    Pure stdlib, self-contained, no I/O, no game, no import outside the standard library.
    The refusal vocabulary is CLOSED: an unknown situation is a refusal, never an approval.
    ``autonomousGateComplete`` is never True: while DS-02's measured negative (no programmable
    start/stop entry exists in this project; ten surfaces searched) stands, no record --
    however complete -- may report that the autonomous gate closed.
"""
from __future__ import annotations

__all__ = (
    'CONTRACT_ID',
    'MODE_MANUAL',
    'MODE_AUTOMATED',
    'SOURCE_HUMAN',
    'SOURCE_AUTOMATION',
    'HUMAN_ACTORS',
    'FORBIDDEN_FIELDS',
    'REFUSAL_CODES',
    'CONTROL_STEPS',
    'audit_control_record',
    'control_source_of',
    'annotate_steps',
)

CONTRACT_ID = 'runtime-control/1'

MODE_MANUAL = 'manual'
MODE_AUTOMATED = 'automated'

#: The two admissible values of a step's control source.  There is no third.
SOURCE_HUMAN = 'human'
SOURCE_AUTOMATION = 'automation'

#: ``triggeredBy`` tokens that mean a person pressed the button.  Everything else means the
#: step was driven by tooling/agent -- which, while DS-02's measured negative stands, cannot
#: be a start/stop of the playtest and is therefore only representable as an *unproven*
#: automated claim, not as an accepted one.
HUMAN_ACTORS = frozenset({'human-ui', 'user', 'player'})

#: Fields a control record may never carry a non-null value in (no start/stop command exists).
FORBIDDEN_FIELDS = ('startCommand', 'stopCommand')

#: The control actions a single run records as its steps, in order.  Kept as data so a
#: caller can assert the ledger's shape rather than hope for it.
CONTROL_STEPS = ('start', 'stop')

#: Closed refusal vocabulary.  Anything not listed here must not be produced.
REFUSAL_CODES = frozenset({
    'CONTROL_CONTRACT_MISMATCH',      # not runtime-control/1 / unknown field / bad mode value
    'FORBIDDEN_CONTROL_FIELD',        # names a start/stop command
    'CONTROL_AUTOMATED_UNPROVEN',     # claims automated while no entry was ever measured
    'TRIGGER_ACTOR_MISMATCH',         # the actor disagrees with the claimed mode
    'CONTROL_STEP_INCOMPLETE',        # a recorded step has no timestamp/attribution
})


def _refusal(code: str, message: str, **detail) -> dict:
    entry = {'code': code, 'message': message}
    if detail:
        entry['detail'] = detail
    return entry


def control_source_of(triggered_by) -> str:
    """Map an actor token to the control source, fail-closed on anything unknown.

    An unrecognised actor is NOT silently treated as human: the whole point of this item is
    that human participation must be *explicitly* recorded, so an unrecognised token becomes
    the automation side (i.e. it must then satisfy the automated-claim rules) and is refused
    downstream rather than laundered into 'human'.
    """
    if isinstance(triggered_by, str) and triggered_by.strip() in HUMAN_ACTORS:
        return SOURCE_HUMAN
    return SOURCE_AUTOMATION


def annotate_steps(record):
    """Build the explicit per-step control-source ledger for one run.

    Returns a list of ``{'step','source','actor','at'}`` for each action in CONTROL_STEPS,
    or an empty list when the record is not a usable runtime-control/1 object; the caller
    checks ``audit_control_record`` first.  A step whose timestamp is missing is still
    listed with ``at=None`` so the ledger shape never depends on the record's completeness.
    """
    if not isinstance(record, dict):
        return []
    source = control_source_of(record.get('triggeredBy'))
    actor = record.get('triggeredBy')
    stamps = {'start': record.get('startedUtc'), 'stop': record.get('stoppedUtc')}
    return [{'step': step, 'source': source, 'actor': actor, 'at': stamps[step]}
            for step in CONTROL_STEPS]


def audit_control_record(record):
    """Adjudicate one ``runtime-control/1`` record for D24.01.03.  Fail closed.

    Returns::

        {
          'ok': bool,                 # no refusals == the record may be used
          'source': 'human'|'automation',
          'manualStepRequired': bool,
          'autonomousGateComplete': bool,   # NEVER True -- see below
          'steps': [...],             # the explicit per-step ledger
          'refusals': [ {code, message, detail?}, ... ],
        }

    ``autonomousGateComplete`` is False unconditionally.  While DS-02's measured negative
    (no programmable start/stop entry exists in this project; 10 surfaces searched) stands,
    no record -- however complete -- may report that the autonomous gate closed.  A complete
    record whose start/stop was done by a person is exactly ``manual-step-required``.
    """
    refusals: list = []
    out = {
        'ok': False,
        'source': None,
        'manualStepRequired': True,
        'autonomousGateComplete': False,
        'steps': [],
        'refusals': refusals,
    }
    if not isinstance(record, dict):
        refusals.append(_refusal('CONTROL_CONTRACT_MISMATCH',
                                 'a control record must be a JSON object',
                                 observedType=type(record).__name__))
        return out

    if record.get('contract') != CONTRACT_ID:
        refusals.append(_refusal('CONTROL_CONTRACT_MISMATCH',
                                 'the control record is not runtime-control/1',
                                 contract=record.get('contract'), expected=CONTRACT_ID))
        return out

    for field in FORBIDDEN_FIELDS:
        if record.get(field) is not None:
            refusals.append(_refusal('FORBIDDEN_CONTROL_FIELD',
                                     'this project has no start/stop playtest command; a '
                                     'record naming one is refused rather than forwarded',
                                     field=field))
    if refusals:
        return out

    mode = record.get('startStopMode')
    if mode not in (MODE_MANUAL, MODE_AUTOMATED):
        refusals.append(_refusal('CONTROL_CONTRACT_MISMATCH',
                                 'startStopMode must be "manual" or "automated"',
                                 startStopMode=mode))
        return out

    source = control_source_of(record.get('triggeredBy'))
    out['source'] = source
    out['steps'] = annotate_steps(record)

    # (1) An automated claim is refused while the measurement stands.  The assembly half
    #     refuses it already; this makes the projection half agree instead of reporting
    #     capability='automated'.
    if mode == MODE_AUTOMATED:
        refusals.append(_refusal(
            'CONTROL_AUTOMATED_UNPROVEN',
            'the record claims an automated run, but no programmable start/stop entry was '
            'ever measured to exist in this project; a manual run may not be re-labelled '
            'automatic',
            startStopMode=mode, triggeredBy=record.get('triggeredBy')))
        return out

    # (2) mode says a human pressed the button; the actor must agree.
    if source != SOURCE_HUMAN:
        refusals.append(_refusal(
            'TRIGGER_ACTOR_MISMATCH',
            'a manual run must be attributed to a human actor; an agent/tool actor may not '
            'be recorded as a human step',
            startStopMode=mode, triggeredBy=record.get('triggeredBy'),
            acceptedActors=sorted(HUMAN_ACTORS)))
        return out

    # (3) A manual run that names no time for a step is not a usable ledger entry.
    missing = [s['step'] for s in out['steps'] if s['at'] is None]
    if missing:
        refusals.append(_refusal('CONTROL_STEP_INCOMPLETE',
                                 'a manual run must record when each control step happened',
                                 missingSteps=missing))
        return out

    out['ok'] = True
    out['manualStepRequired'] = True
    out['autonomousGateComplete'] = False
    return out
