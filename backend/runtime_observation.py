"""Runtime-run identity, observation window, run-object correlation and return-to-editor.

NARROW CONTRACT
===============
The *library* half of this module is a pure function library over an already-decoded
runtime-evidence bundle that the execution layer hands in as a mapping.  Its whole
reachable surface is ``json``/``hashlib``/``base64``/``math``/``datetime`` and mapping
arithmetic: no subprocess, no socket, no queue, no helper, no bridge, no game.  It cannot
start a playtest, stop one, or forward a command, and there is no parameter anywhere that
could carry one -- ``EXECUTION_SURFACE`` below states that in machine-checkable form and
``backend/tests/test_runtime_observation.py`` enforces it structurally (AST, not grep).
The *only* file I/O in this module lives inside ``main()``; ``CLI_SURFACE`` declares
exactly what that shell may open, and the test asserts no other function may do so.

WHAT IT IS FOR
==============
The S09 evidence items (``current-run-identity`` · ``start-and-stop`` ·
``runtime-object-correlation`` · ``runtime-observation`` · ``return-to-editor``) are the
five pieces of a *run* observation, and this project has repeatedly confused four
different things for them:

* a **cached editor log** that still contains the marker from a previous day's run
  (``EditorAdapter.cs`` says so itself: *"Markers may originate from historical debug
  logs; absence is not proof of nonexecution."*),
* an **editor-state entity catalog**, which lists what the editor holds right now and
  says nothing about what a run created,
* an **empty window**, which means "not observed" and never "did not run",
* a **derived declaration** -- a flag on a file, a tool's self-report, a screenshot.

So every answer this module produces is one of: the run identity it can actually
establish from observed fields, or a named refusal.  Absence of evidence is never upgraded
to evidence of absence anywhere in this file.

RUN IDENTITY IS NOT A RUN ID
============================
The game side assigns no named run id (G03 §1.6 U7).  Identity is therefore the
*combination* of observed fields, exactly as G03 §7 specifies: editor session identity,
game session identity, level id, observer registration id, observation id, and the 1022
event cursor -- the only carrier of a generation, because it is monotonic and only
increments on an actual ``Receive``.  ``derivedGenerationId`` is a digest *over* those
observed fields and is labelled ``derived: true``, ``isGameAssignedId: false``.  It is a
label for comparison, never a minted identifier, and it does not exist unless the event
cursor does.

CONSUMER OF A FROZEN CONTROL INTERFACE, BOUND TO A MEASURED NEGATIVE
===================================================================
The ``start-and-stop`` item needs a run-control entry that this project does not have, and
that is now a **measured fact rather than an absence of a file**.  DS-02
(``t12-ds02-run-control-contract/1``, recorded in ``DS02_EVIDENCE`` with digests) disproved
a programmable start/stop across ten surfaces -- the bridge route whitelist (128 cases), the
adapter log/observer entries (every one of which declares ``startsPlaytest=false``), the
closed five-action helper set, the reviewed-write allowlist, the 7.0 and 7.1 game-side
command scans, the message-number table, the editor frontend feature table
(``feature:75 playtest`` reachable = no), the editor label set, and the official UI -- and
its adjudicator returns ``RUN_CONTROL_UNAVAILABLE`` fail-closed with a verdict vocabulary
that deliberately contains no "pass".  The scope of that finding is stated as well as its
result: the game process internals were **not** ruled out, because ``global-metadata.dat``
is MHY-encrypted and a zero-hit scan on that carrier proves nothing.

What is still frozen here is ``runtime-control/1`` (see ``CONTROL_FIELDS`` and
``manifest_template``), the shape DS-02's adjudicator feeds.  Two properties are hard, not
stylistic:

* ``startCommand`` and ``stopCommand`` **must be null**.  A non-null value is refused with
  ``CONTROL_COMMAND_NOT_REPRESENTABLE``.  There is no start-playtest command in this
  project, DS-02 measured that, and this pack does not invent one.
* ``startsPlaytest`` is a module constant, ``False``, and it is emitted on every
  projection.  This module never starts or stops a playtest.

Three verdicts are kept apart on purpose, because collapsing them is how "a person pressed
the button" becomes "the tooling can run a playtest":

* ``runControl`` -- the *capability* of the project's control entry.  Always
  ``RUN_CONTROL_UNAVAILABLE``, in every case, including the case where a manual run was
  recorded.
* ``manualStepRequired`` / ``autonomyVerified`` -- DS-02's field names and values, carried
  through unchanged so a consumer comparing the two sees the same numbers.
* the ``start-and-stop`` item's ``status`` -- G01 D10's closed set, where **no "pass" is
  reachable**: a recorded run can only ever be a human one.  DS-02's own token
  (``manual-step-required`` / ``blocked``) is carried beside it in ``capability`` and
  ``ds02ItemToken``, and ``ds02Agreement`` names the vocabulary difference rather than
  rewriting one into the other.

WHAT IT REFUSES (each has a positive and a negative test)
=========================================================
``RUNTIME_LOG_STALE``        a record dated before the observation window; still returned,
                             marked historical, and excluded from pass evidence.
``RUN_IDENTITY_LEVEL_MISMATCH`` / ``RUN_IDENTITY_GENERATION_MISMATCH``
                             the right log for the wrong level or the wrong run.
``RUNTIME_WINDOW_TRUNCATED`` ``retainedEvents != sequence``, an overflow, a dropped event,
                             a scan that hit its own limit.
``RUNTIME_CLOCK_ROLLBACK``   stop before start, a decreasing sequence, a decreasing
                             timestamp, an event received after the observer stopped.
``EDIT_STATE_NOT_RUNTIME``   an editor-state catalog offered as a run observation.
``RUNTIME_MIXED_RUNS``       two different run identities inside one bundle.
``FIXTURE_CLAIMS_LIVE``      a document marked as a fixture that claims to be live.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import math
from collections.abc import Mapping, Sequence

from backend import control_source_guard

__all__ = (
    'SCHEMA_VERSION',
    'CONTRACT_ID',
    'CONTROL_CONTRACT_ID',
    'MANIFEST_CONTRACT_ID',
    'SUPPORTED_INPUTS',
    'EXECUTION_SURFACE',
    'CLI_SURFACE',
    'EVIDENCE_MODES',
    'STAGE_STATUSES',
    'REFUSAL_CODES',
    'AUTHORIZED_TARGET_LEVEL_ID',
    'BINDING_FIELDS',
    'FORBIDDEN_BINDING_FIELDS',
    'CONTROL_FIELDS',
    'FORBIDDEN_CONTROL_FIELDS',
    'CONTROL_CAPABILITIES',
    'DS02_CONTROL_CONTRACT_ID',
    'DS02_EVIDENCE',
    'DS02_START_STOP_TOKENS',
    'S09_EVIDENCE_ITEMS',
    'EVIDENCE_PRODUCERS',
    'RUNTIME_OBJECT_SOURCES',
    'EDIT_STATE_SOURCES',
    'GENERATION_CARRIER_FIELDS',
    'RETURN_TO_EDITOR_SOURCES',
    'EDIT_STATE_PREDICATE',
    'STARTS_PLAYTEST',
    'ObservationError',
    'input_kind',
    'runtime_identity',
    'observation_window',
    'correlate_objects',
    'return_to_editor',
    's09_responsibility',
    'normalize_runtime_evidence',
    'manifest_template',
)

#: Version of the projection document this module emits and consumes.
SCHEMA_VERSION = 1
#: Stable contract id, carried by every projection so a consumer cannot mix versions.
CONTRACT_ID = 'runtime-observation/projection/v1'
#: Frozen control interface this module consumes.  DS-02 implements it; see CONTROL_FIELDS.
CONTROL_CONTRACT_ID = 'runtime-control/1'
#: Shape of the on-disk manifest the ``main()`` shell reads.
MANIFEST_CONTRACT_ID = 'runtime-observation/manifest/v1'

#: Input kinds this module actually implements.  Nothing else is accepted.
SUPPORTED_INPUTS = ('runtime-evidence-bundle',)

#: Machine-checkable statement of what the *library* can reach.  All false, by construction.
EXECUTION_SURFACE = {
    'subprocess': False,
    'shell': False,
    'filesystem': False,
    'network': False,
    'processControl': False,
    'arbitraryCommandParameter': False,
    'forwardableScriptOrPlan': False,
    'startsPlaytest': False,
}

#: Machine-checkable statement of what the optional command-line shell may open.  It decodes
#: raw copies and nothing else; it never reaches a game, an editor, a bridge or a queue.
CLI_SURFACE = {
    'reads': ('the manifest named by --evidence-manifest',
              'the documents that manifest names'),
    'writes': ('exactly one file: the path given to --output',),
    'subprocess': False,
    'network': False,
    'game': False,
    'overwritesExistingOutput': False,
    'outputInsideInputDirectory': False,
}

#: Closed set of evidence modes.  The default is ``offline`` and it only becomes ``live``
#: through the derivation in ``normalize_runtime_evidence`` -- never by a caller's say-so.
EVIDENCE_MODES = ('offline', 'live')

#: Stage statuses, the closed six-value set of G01 D10.  ``failed`` is not a token here.
STAGE_STATUSES = ('pass', 'fail', 'blocked', 'unknown', 'not-run', 'not-applicable')

#: The target level this project is authorised against (G03 §7, rejection condition 2).
#: This is NOT a default: a binding must state its own ``expectedLevelId``, and this constant
#: is used only to report drift against the recorded authorised value.
AUTHORIZED_TARGET_LEVEL_ID = 1073741840

#: Hard, non-negotiable: this module never starts a playtest.
STARTS_PLAYTEST = False

#: Closed field set of the binding.  Anything outside it is refused, so a caller cannot
#: smuggle an execution-layer knob (queue, helper pid, script, timeout) into this layer.
BINDING_FIELDS = (
    'caseId',
    'expectedLevelId',
    'expectedGameSession',
    'expectedEditorSession',
    'expectedRunGeneration',
    'expectedEntityIds',
    'sourceSha256',
    'evidenceMode',
)

#: Field names that are refused by name with their own code, so the refusal says *why*.
FORBIDDEN_BINDING_FIELDS = (
    'runId', 'helperPid', 'pinsDigest', 'deadlineUtc', 'elevatedQueue', 'queueDir',
    'sessionPath', 'reviewPath', 'baselineRun', 'recoveryDir', 'scriptPath', 'exe',
    'executable', 'command', 'argv', 'cwd', 'plan', 'timeout', 'startCommand',
    'stopCommand', 'pid', 'tid',
)

#: Frozen field set of the ``runtime-control/1`` record (DS-02's deliverable).
CONTROL_FIELDS = (
    'contract',
    'caseId',
    'startStopMode',
    'startedUtc',
    'stoppedUtc',
    'triggeredBy',
    'startRequestId',
    'stopRequestId',
    'gameSession',
    'levelId',
    'startCommand',
    'stopCommand',
    'startsPlaytest',
)

#: Control fields that must be absent or null.  A non-null command is a fabricated entry.
FORBIDDEN_CONTROL_FIELDS = ('startCommand', 'stopCommand')

#: Closed set of what the project's run-control *capability* can be.  ``RUN_CONTROL_UNAVAILABLE``
#: is the measured fact, not a default: no programmable entry exists.  ``manual-step-required``
#: means the start/stop happened and was recorded, but a human pressed the button.
CONTROL_CAPABILITIES = ('RUN_CONTROL_UNAVAILABLE', 'manual-step-required', 'automated')

#: The delivered adjudicator this freeze is bound to.  DS-02 disproved a programmable
#: start/stop across ten surfaces (bridge route whitelist, adapter log/observer entries,
#: the closed five-action helper set, the reviewed-write allowlist, the 7.0 and 7.1 game-side
#: command scans, the message-number table, the editor frontend feature table, the editor
#: label set, and the official UI).  Its adjudicator returns ``RUN_CONTROL_UNAVAILABLE``
#: fail-closed and its verdict vocabulary contains no "pass".
#:
#: These digests are RECORDED EVIDENCE, not live reads.  If DS-02 re-delivers, they go stale
#: and this block must be re-frozen deliberately -- the same rule the run verifier applies to
#: the frozen checklist digest.  ``test_the_recorded_ds02_digests_still_match_the_delivered_files``
#: re-checks them against disk whenever the files are present, read-only.
DS02_CONTROL_CONTRACT_ID = 't12-ds02-run-control-contract/1'
DS02_EVIDENCE = {
    'contract': DS02_CONTROL_CONTRACT_ID,
    'root': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002',
    'handoff': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/handoff.md',
    'adjudicator': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/candidates/control/'
                   'run_control_contract.py',
    'adjudicatorSha256':
        '0ecaa8370b8691f0fdd6887c5dc4f9cba6cee02c404207346913bcb8ba6ded36',
    'tests': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/checks/control/'
             'test_run_control_contract.py',
    'testsSha256': '1b0030dc271e7d807123854a329b5d98679e4a1b13363fac3e9b8b9d71fb5947',
    'surfaceCatalog': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/checks/control/'
                      'surface-catalog.json',
    'surfaceCatalogSha256':
        'a8277ff92da3c54e511b55861e177cd71eaccf9b8bd2b9bcb1783063301a73f7',
    'verdictManualPositive': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/checks/'
                             'control/verdict-claim-manual-positive.json',
    'verdictManualPositiveSha256':
        '850e7dc6b01e89003bcc5783954591a6a8f5e9a98d315194286af0e4b6eea748',
    'verdictRouteNegative': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/checks/'
                            'control/verdict-claim-route-negative.json',
    'verdictRouteNegativeSha256':
        '70613699faf1492b24c844a91941abdea007f66241c7b95640d4beaa3a2de1e2',
    'surfacesSearched': 10,
    'surfaceCatalogEntries': 24,
    'verdict': 'RUN_CONTROL_UNAVAILABLE',
    'manualStepRequired': True,
    'autonomyVerified': False,
    'notFoundIsNotAbsent': True,
    'findingKind': 'measured-negative',
    'finding': 'no programmable start/stop playtest entry exists in this project; the only '
               'way to start or stop a playtest is the in-game manual button. This is a '
               'source-level measurement over ten surfaces, not an absence of a file and not '
               'a search that failed.',
    'explicitlyNotClaimed': 'the game process internals were not ruled out: '
                            'global-metadata.dat is MHY-encrypted, so a zero-hit scan on that '
                            'carrier cannot prove non-existence and is recorded as not-found.',
}

#: The adjudicator's own item token for ``start-and-stop``.  Kept beside our closed-set stage
#: status because the two vocabularies are genuinely different and neither may be silently
#: rewritten into the other.
DS02_START_STOP_TOKENS = ('manual-step-required', 'blocked', 'rejected', 'evidence-insufficient')

#: The five S09 evidence items, in the order the frozen checklist lists them.
S09_EVIDENCE_ITEMS = (
    'current-run-identity',
    'start-and-stop',
    'runtime-object-correlation',
    'runtime-observation',
    'return-to-editor',
)

#: Who produces each S09 item today.  This is the answer to "哪一项由本模块生产 / 哪一项依赖
#: DS-02 的控制入口 / 哪一项当前无生产者" and it is data, not prose, so it can be asserted.
EVIDENCE_PRODUCERS = {
    'current-run-identity': {
        'producer': 'backend/runtime_observation.py',
        'status': 'implemented-offline',
        'needs': 'a decoded runtime-evidence bundle carrying the observer registration, the '
                 '1022 event cursor and both session identities',
        'liveOnly': True,
        'autonomous': False,
    },
    'start-and-stop': {
        'producer': None,
        'adjudicatedBy': 'DS-02 backend candidate run_control_contract.py '
                         '(t12-ds02-run-control-contract/1)',
        'status': 'manual-step-required',
        'code': 'RUN_CONTROL_UNAVAILABLE',
        'measuredNegativeFinding': True,
        'negativeFindingBasis': '.runtime/cordis-plan-work/T12-ds02-parallel-20261002/'
                                'handoff.md §1 (ten surfaces) and checks/control/',
        'needs': 'a runtime-control/1 record. It can only ever be filled in by a human: DS-02 '
                 'measured that no programmable start/stop entry exists, so there is no '
                 'automated producer to wait for. This pack does not implement start/stop and '
                 'does not invent a command name.',
        'liveOnly': True,
        'autonomous': False,
    },
    'runtime-object-correlation': {
        'producer': 'backend/runtime_observation.py',
        'status': 'consumer-ready-producer-missing',
        'needs': 'a runtime-scope object readback whose source is one of '
                 'RUNTIME_OBJECT_SOURCES.  No such reader exists yet; an editor-state '
                 'catalog is explicitly not a substitute.',
        'liveOnly': True,
        'autonomous': False,
    },
    'runtime-observation': {
        'producer': 'backend/runtime_observation.py',
        'status': 'implemented-offline',
        'needs': 'an observer window (packet kinds + dated records) captured in this run',
        'liveOnly': True,
        'autonomous': False,
    },
    'return-to-editor': {
        'producer': None,
        'status': 'unavailable',
        'needs': 'a contracted reader for "the editor is back in edit state".  The official '
                 'documentation does not cover the return path and no reader is implemented, '
                 'so this item has NO producer and is reported unknown, not faked.'
                 ,
        'code': 'RETURN_TO_EDITOR_READER_UNCONTRACTED',
        'liveOnly': True,
        'autonomous': False,
    },
}

#: Object-readback sources this layer will accept as *run-time* evidence.  The set is
#: deliberately narrow and currently has no implemented producer on this machine.
RUNTIME_OBJECT_SOURCES = ('runtime-scene-object-readback',)

#: Sources that prove an editor-state list and therefore prove nothing about a run.
EDIT_STATE_SOURCES = (
    'editor-entity-catalog',
    'edit-time-entity-list',
    'editor-level-catalog',
    'formal-save-parse',
)

#: Generation carriers a run-scope readback must carry at least one of.  An entity id is
#: reused across levels AND across runs of the same level, so a readback that is only
#: level-matched can still belong to a *previous* run of that level.  Every carrier the
#: readback does carry must equal this run's; a readback that carries none is refused rather
#: than accepted on the strength of the level alone.
GENERATION_CARRIER_FIELDS = ('observationId', 'registrationCompletedTick', 'sequence')

#: The only source id accepted for a post-run editor readback.  ``runtime-evidence`` is the
#: single proven editor operation that returns the editor's level state, so a readback that
#: names any other source is refused rather than compared.
RETURN_TO_EDITOR_SOURCES = ('editor-runtime-evidence-readback',)

#: The predicate that would decide "the editor is back in edit state", as data.  It is NOT
#: contracted, and the reader refuses to guess: the editor level-state value has no named
#: meaning on this machine.  The decompiled level-state enum exposes only a ``None`` member
#: (INTERFACE-INVENTORY §7.3), and the only values ever observed are 3 and 5 -- recorded in
#: different sessions with **no recorded state for either**, so the pair is not a usable
#: contrast and neither value can be named "edit state".  A predicate only counts once it
#: carries an ``authority``; until then the item is reported unknown and no input can make
#: it pass.
EDIT_STATE_PREDICATE = {
    'contracted': False,
    'reads': 'editorLevelState',
    'expectedValue': None,
    'authority': None,
    'why': 'the editor level-state value has no contracted meaning: the decompiled '
           'level-state enum exposes only a `None` member (INTERFACE-INVENTORY §7.3), and '
           'the only values ever observed on this machine are 3 and 5. They come from '
           'different sessions and neither carries a recorded state, so the pair is not a '
           'usable contrast and neither value can be named "edit state". Reading a mapping '
           'into them would be a guess, which is exactly what this layer refuses to make.',
    'basis': 'docs/editor-catalog/INTERFACE-INVENTORY.md §7.3 (level-state enum unnamed) '
             'and .runtime/editor-bridge/** (editorLevelState observed only as 3 and 5, in '
             'different sessions, with no recorded state for either)',
    'observedValues': [3, 5],
    'wouldNeed': ['a named enumeration for the level-state field, or',
                  'a contrast sample whose *states are recorded* (one in edit state, one in '
                  'a non-edit state inside one bridge scope), or',
                  'a contracted predicate carrying its own authority'],
}

#: Closed refusal vocabulary.  Every refusal this module can emit is named here.
REFUSAL_CODES = frozenset({
    'INPUT_KIND_UNSUPPORTED',
    'BINDING_INVALID',
    'BINDING_FORBIDDEN_FIELD',
    'BINDING_CONTRACT_MISMATCH',
    'SOURCE_DIGEST_MISMATCH',
    'RUN_IDENTITY_EVIDENCE_INSUFFICIENT',
    'RUN_IDENTITY_SESSION_MISMATCH',
    'RUN_IDENTITY_LEVEL_MISMATCH',
    'RUN_IDENTITY_GENERATION_MISMATCH',
    'RUNTIME_MIXED_RUNS',
    'RUNTIME_LOG_STALE',
    'RUNTIME_WINDOW_TRUNCATED',
    'RUNTIME_CLOCK_ROLLBACK',
    'EDIT_STATE_NOT_RUNTIME',
    'RUNTIME_OBJECT_SOURCE_UNSUPPORTED',
    'CORRELATION_NOT_A_RUNTIME_OBSERVATION',
    'CORRELATION_TEXT_ONLY',
    'CORRELATION_GENERATION_UNBOUND',
    'RETURN_TO_EDITOR_READER_UNCONTRACTED',
    'RETURN_TO_EDITOR_SOURCE_UNSUPPORTED',
    'RETURN_TO_EDITOR_NOT_AFTER_RUN',
    'RETURN_TO_EDITOR_LEVEL_STATE_UNREADABLE',
    'CONTROL_CONTRACT_MISMATCH',
    'CONTROL_COMMAND_NOT_REPRESENTABLE',
    'FIXTURE_CLAIMS_LIVE',
    'MANIFEST_INVALID',
    'MANIFEST_FORBIDDEN_KEY',
    'OUTPUT_PATH_REFUSED',
})

#: Which source layer each identity field comes from.  Reported verbatim on the projection.
FIELD_SOURCES = {
    'editorIdentity': ('bridge-settings.json / bridge-ready.json + a read-only process query',
                       'realtime-query'),
    'gameSessionIdentity': ('session.json (query-only-window-process-thread-identity)',
                            'realtime-query'),
    'levelId': ('native level observation, else the parsed 1022 event payload',
                'realtime-observed'),
    'observerRegistrationId': ('observer registration receipt (current-observer-instance-only)',
                               'realtime-observed'),
    'observationId': ('LevelInitObservation registration', 'realtime-observed'),
    'eventCursor': ('the 1022 packet stream; monotonic, incremented only on a real Receive',
                    'realtime-observed'),
    'window': ('the observer registration receipt start/stop stamps', 'realtime-observed'),
}

_RECEIPT_FIELDS = ('ownMarkers', 'logRecordCount', 'observedPackets', 'packetKinds')
_EVENT_LIMIT = 4096
_MAX_WINDOW_RECORDS = 512


class ObservationError(RuntimeError):
    """A refusal with a stable code, for contract/shape violations only.

    Raised when the *caller's* input is malformed: a binding outside the closed field set, a
    source digest that does not match, a projection of another contract version.  Evidence
    problems -- a stale log, a truncated window, a level mismatch -- are NOT exceptions:
    they are reported in the returned document, so a caller can never mistake a refusal for
    a successful empty observation.
    """

    def __init__(self, code: str, message: str, **detail) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def as_dict(self) -> dict:
        return {'code': self.code, 'message': self.message, 'detail': self.detail}

    def __str__(self) -> str:
        return '%s: %s' % (self.code, self.message)


# --------------------------------------------------------------------------- #
# small deterministic helpers
# --------------------------------------------------------------------------- #

def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=str).encode('utf-8')


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _utc(value):
    """A comparable UTC instant, or ``None``.

    A timestamp this layer cannot parse -- or one with no timezone at all -- is ``None``,
    never midnight, never "now".  An unparseable stamp therefore drops out of every
    window comparison instead of silently sorting to the epoch.
    """
    if not _is_str(value):
        return None
    text = value.strip()
    if text[-1] in 'Zz':
        text = text[:-1] + '+00:00'
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(datetime.timezone.utc)


def _iso(moment) -> str | None:
    if moment is None:
        return None
    return moment.isoformat().replace('+00:00', 'Z')


def _refusal(code: str, message: str, **detail) -> dict:
    entry = {'code': code, 'message': message}
    if detail:
        entry['detail'] = detail
    return entry


def _paths_of(bundle):
    """Every sub-document of a bundle that carries the same run, in a fixed order."""
    for key in ('editorEvidence', 'logObserverEvidence', 'levelInitialization', 'session',
                'editorSession', 'runControl', 'runtimeObjects', 'editorCatalog',
                'postRunReadback', 'levelObservation'):
        value = bundle.get(key)
        if isinstance(value, Mapping):
            yield key, value


# --------------------------------------------------------------------------- #
# input classification
# --------------------------------------------------------------------------- #

def input_kind(document) -> str:
    """Classify an input without trusting it: see ``SUPPORTED_INPUTS``."""
    if not isinstance(document, Mapping):
        return 'not-a-mapping'
    if document.get('kind') == 'runtime-evidence-bundle' or (
            'levelInitialization' in document or len(set(document) & {
                'observerEvidence', 'editorEvidence', 'runControl', 'runtimeObjects'}) >= 2):
        return 'runtime-evidence-bundle'
    if isinstance(document.get('_fixture'), Mapping):
        return 'runtime-evidence-bundle'
    if 'ok' in document and any(field in document for field in _RECEIPT_FIELDS):
        return 'bare-runtime-receipt'
    return 'unknown'


# --------------------------------------------------------------------------- #
# binding
# --------------------------------------------------------------------------- #

def _validate_session(value, code_what):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ObservationError('BINDING_INVALID',
                               '%s must be a JSON object' % code_what,
                               observedType=type(value).__name__)
    out = {}
    for key in ('pid', 'tid', 'processCreation', 'image'):
        if key in value:
            out[key] = value[key]
    return out


def _validate_binding(binding):
    if not isinstance(binding, Mapping):
        raise ObservationError('BINDING_INVALID', 'binding must be a JSON object',
                               observedType=type(binding).__name__)
    forbidden = sorted(set(binding) & set(FORBIDDEN_BINDING_FIELDS))
    if forbidden:
        raise ObservationError(
            'BINDING_FORBIDDEN_FIELD',
            'the binding names execution-layer fields; this layer takes business and '
            'identity fields only and has no code path that could use them',
            fields=forbidden)
    unknown = sorted(set(binding) - set(BINDING_FIELDS))
    if unknown:
        raise ObservationError('BINDING_INVALID',
                               'the binding carries fields outside the closed set',
                               unrecognizedKeys=unknown, allowed=sorted(BINDING_FIELDS))
    case_id = binding.get('caseId')
    if not _is_str(case_id):
        raise ObservationError('BINDING_INVALID', 'binding.caseId must be a non-empty string')
    level_id = binding.get('expectedLevelId')
    if not _is_int(level_id) or level_id <= 0:
        raise ObservationError('BINDING_INVALID',
                               'binding.expectedLevelId must be a positive integer')
    mode = binding.get('evidenceMode', 'offline')
    if mode not in EVIDENCE_MODES:
        raise ObservationError('BINDING_INVALID', 'binding.evidenceMode must be one of %s'
                               % (EVIDENCE_MODES,), evidenceMode=mode)
    expected_ids = binding.get('expectedEntityIds')
    if expected_ids is not None:
        if not isinstance(expected_ids, Sequence) or isinstance(expected_ids, (str, bytes)):
            raise ObservationError('BINDING_INVALID',
                                   'binding.expectedEntityIds must be a list of positive ints')
        if any(not _is_int(v) or v <= 0 for v in expected_ids):
            raise ObservationError('BINDING_INVALID',
                                   'binding.expectedEntityIds must be a list of positive ints',
                                   expectedEntityIds=list(expected_ids))
        expected_ids = sorted(set(expected_ids))
    sha = binding.get('sourceSha256')
    if sha is not None and (not _is_str(sha) or len(sha) != 64 or
                            any(c not in '0123456789abcdef' for c in sha.lower())):
        raise ObservationError('BINDING_INVALID',
                               'binding.sourceSha256 must be 64 lowercase hex characters')
    return {
        'caseId': case_id.strip(),
        'expectedLevelId': level_id,
        'expectedGameSession': _validate_session(binding.get('expectedGameSession'),
                                                 'expectedGameSession'),
        'expectedEditorSession': _validate_session(binding.get('expectedEditorSession'),
                                                   'expectedEditorSession'),
        'expectedRunGeneration': binding.get('expectedRunGeneration'),
        'expectedEntityIds': expected_ids,
        'sourceSha256': sha.lower() if sha else None,
        'evidenceMode': mode,
    }


def _session_differences(expected, observed, fields):
    """Field names where an expected session value is present and does not match.

    A field the expectation does not name is not compared.  A field the expectation *does*
    name but the observation does not carry is reported as ``unverified`` -- fail closed,
    because "we did not look" is not "it matched".
    """
    differs, unverified = [], []
    if not expected:
        return differs, unverified
    if not observed:
        return [], sorted(f for f in fields if f in expected)
    for field in fields:
        if field not in expected:
            continue
        want, got = expected[field], observed.get(field)
        if got is None:
            unverified.append(field)
        elif isinstance(want, str) and isinstance(got, str):
            if want.replace('\\', '/').lower() != got.replace('\\', '/').lower():
                differs.append(field)
        elif want != got:
            differs.append(field)
    return sorted(differs), sorted(unverified)


# --------------------------------------------------------------------------- #
# run identity (G03 §7)
# --------------------------------------------------------------------------- #

def _registration(bundle):
    for key, doc in _paths_of(bundle):
        timing = doc.get('observerTiming')
        if isinstance(timing, Mapping):
            return doc, timing, key
    return None, None, None


def _outside_observation_window(moment, start, stop):
    """True when ``moment`` cannot be placed inside the window ``[start, stop]``.

    Mirrors ``observation_window``'s own taxonomy: a record before ``start`` is historical
    and a record after ``stop`` was received after the observer stopped.  Either is outside
    the window and may not carry this run's generation.  A record whose timestamp cannot be
    placed (``moment is None``) is outside too: an unplaceable stamp is not a licence to
    place it.  A bound the receipt does not name is not applied -- an open window has a
    start and an unbounded future, and its records are still inside it -- so this predicate
    is exactly ``observation_window``'s ``in_window`` test and nothing stricter.
    """
    if moment is None:
        return True
    if start is not None and moment < start:
        return True
    if stop is not None and moment > stop:
        return True
    return False


def _build_window(timing, window_seconds):
    if not isinstance(timing, Mapping):
        return {'startUtc': None, 'stopUtc': None, 'windowSeconds': None, 'windowOpen': None,
                'stopReason': None, 'source': 'unavailable'}
    start, stop = _utc(timing.get('startedUtc')), _utc(timing.get('stoppedUtc'))
    seconds = window_seconds
    if seconds is None and start is not None and stop is not None:
        seconds = (stop - start).total_seconds()
    return {
        'startUtc': _iso(start),
        'stopUtc': _iso(stop),
        'startTick': timing.get('startedTick'),
        'stopTick': timing.get('stoppedTick'),
        'windowSeconds': seconds,
        'windowOpen': stop is None,
        'stopReason': timing.get('stopReason'),
        'lastCallbackUtc': _iso(_utc(timing.get('lastCallbackUtc'))),
        'registrationCompletedUtc': _iso(_utc(timing.get('registrationCompletedUtc'))),
        'registrationCompletedTick': timing.get('registrationCompletedTick'),
        'scope': timing.get('scope'),
        'stopwatchFrequency': timing.get('stopwatchFrequency'),
        'historical1022Inferred': timing.get('historical1022Inferred'),
        'source': 'observer-registration-receipt',
    }


def runtime_identity(bundle, *, binding):
    """The run identity this bundle can actually establish, or a named refusal.

    Never invents one.  ``derivedGenerationId`` is a digest over observed fields and is
    labelled as derived; it does not exist without the event cursor, because the cursor is
    the only monotonic carrier of a generation this project has.
    """
    binding = _validate_binding(binding)
    if not isinstance(bundle, Mapping):
        raise ObservationError('INPUT_KIND_UNSUPPORTED',
                               'the bundle must be a JSON object',
                               observedType=type(bundle).__name__)
    refusals = []
    timing_doc, timing, _timing_key = _registration(bundle)

    editor_raw = bundle.get('editorSession')
    if not isinstance(editor_raw, Mapping):
        editor_raw = bundle.get('editorIdentity')
    if not isinstance(editor_raw, Mapping) and isinstance(bundle.get('editorEvidence'), Mapping):
        editor_raw = bundle['editorEvidence'].get('editorIdentity')
    editor_identity = (
        {'pid': editor_raw.get('pid'), 'image': editor_raw.get('image'),
         'creationFileTime': editor_raw.get('creationFileTime')}
        if isinstance(editor_raw, Mapping) else None)

    session_raw = bundle.get('session')
    game_session = None
    if isinstance(session_raw, Mapping):
        game_session = {k: session_raw.get(k)
                        for k in ('pid', 'tid', 'processCreation', 'image')}
        if not any(v is not None for v in game_session.values()):
            game_session = None

    # level id: a verified native observation first, else the parsed 1022 payload.
    level_observation = bundle.get('levelObservation')
    level_id, level_source = None, 'unavailable'
    if isinstance(level_observation, Mapping) and level_observation.get('verified') is True \
            and _is_int(level_observation.get('levelId')) \
            and level_observation['levelId'] > 0:
        level_id = level_observation['levelId']
        level_source = 'native-level-observation-verified'

    level_init = bundle.get('levelInitialization')
    if not isinstance(level_init, Mapping):
        level_init = {}
    events = level_init.get('events')
    events = list(events) if isinstance(events, Sequence) and \
        not isinstance(events, (str, bytes)) else []
    if len(events) > _EVENT_LIMIT:
        events = events[:_EVENT_LIMIT]

    # An event is usable as a cursor only if it parsed AND carries a placeable timestamp.
    # A cursor that cannot be placed in a window cannot be checked against one, and a naive
    # stamp is not quietly resolved to UTC: it is missing, not midnight.
    usable_events = [e for e in events if isinstance(e, Mapping)
                     and e.get('parsed') is True and e.get('error') is None
                     and _utc(e.get('receivedUtc')) is not None]
    # The cursor is the *only* monotonic carrier of a generation this project has, so a
    # cursor additionally requires an integer ``sequence``.  An event that parsed and is
    # dated but whose sequence is null, a string, a float or a bool is retained and still
    # reported above, but it cannot carry a generation: that value is not monotonic, cannot
    # be ordered against another sequence, and was never assigned by the 1022 stream.
    # Reading one as a cursor would mint a generation out of a field the stream never
    # placed, which is exactly the "absence of evidence upgraded to evidence" this module
    # refuses everywhere else.
    #
    # The generation *source* is window-scoped (R16).  A 1022 record dated before the
    # window opened is a cached log from an earlier run -- ``EditorAdapter.cs`` says exactly
    # that -- and it may not mint a generation here.  Filtering it out of the display list
    # (``observation_window``'s ``historicalRecords``) is not enough: the digest and the
    # correlation carriers are read from this cursor, so the exclusion has to happen where
    # the cursor is chosen.  Otherwise a bundle whose only 1022 records predate the window
    # still yields a non-null ``derivedGenerationId`` and a readback carrying that stale
    # sequence correlates as ``pass``.  The boundary is the same one ``observation_window``
    # uses: in-window is ``start <= receivedUtc <= stop``; before-start and after-stop are
    # both outside.  When the receipt names no bound, there is no window to place a record
    # in, so nothing is drawn from it either -- which is the existing "no cursor" refusal,
    # not a new one.
    window_start = _utc(timing.get('startedUtc')) if isinstance(timing, Mapping) else None
    window_stop = _utc(timing.get('stoppedUtc')) if isinstance(timing, Mapping) else None
    cursor_events = [e for e in usable_events
                     if _is_int(e.get('sequence'))
                     and not _outside_observation_window(_utc(e.get('receivedUtc')),
                                                         window_start, window_stop)]
    # Retained for the projection: how many otherwise-usable cursor candidates were dropped
    # because they predate (or postdate) the window.  A nonzero value is the machine-readable
    # trace that the exclusion happened at the source and not only in the display list.
    cursor_events_outside_window = [
        e.get('sequence') for e in usable_events
        if _is_int(e.get('sequence'))
        and _outside_observation_window(_utc(e.get('receivedUtc')),
                                        window_start, window_stop)]
    cursor = None
    if cursor_events:
        newest = max(cursor_events, key=lambda e: e.get('sequence'))
        cursor = {
            'sequence': newest.get('sequence'),
            'receivedUtc': _iso(_utc(newest.get('receivedUtc'))),
            'receivedTick': newest.get('receivedTick'),
            'stopwatchTick': newest.get('receivedTick'),
            'managedThreadId': newest.get('managedThreadId'),
            'levelId': newest.get('levelId') if _is_int(newest.get('levelId')) else None,
            'parsed': True,
            'source': 'received-1022-packet-observer',
        }
        if level_id is None and cursor['levelId']:
            level_id, level_source = cursor['levelId'], 'received-1022-packet-observer'

    observation_id = level_init.get('observationId') if _is_str(level_init.get('observationId')) \
        else None
    registration = None
    if isinstance(timing, Mapping):
        registration = {
            'registrationCompletedUtc': _iso(_utc(timing.get('registrationCompletedUtc'))),
            'registrationCompletedTick': timing.get('registrationCompletedTick'),
            'scope': timing.get('scope'),
        }
    window = _build_window(timing, binding.get('windowSeconds'))

    missing = []
    if editor_identity is None or editor_identity.get('pid') is None:
        missing.append('editorIdentity')
    if game_session is None:
        missing.append('gameSessionIdentity')
    if level_id is None:
        missing.append('levelId')
    if observation_id is None:
        missing.append('observationId')
    if registration is None or registration.get('registrationCompletedTick') is None:
        missing.append('observerRegistrationId')
    if cursor is None:
        missing.append('eventCursor')
    if missing:
        refusals.append(_refusal(
            'RUN_IDENTITY_EVIDENCE_INSUFFICIENT',
            'the run identity of G03 §7 is a combination of observed fields, and this bundle '
            'does not carry all of them; without the event cursor in particular no generation '
            'can be claimed and no run id may be minted',
            missing=missing,
            note='this is the "evidence-insufficient" case of G03 §7 rejection 6, not a '
                 'statement that no run happened'))

    differs, unverified = _session_differences(binding['expectedEditorSession'], editor_identity,
                                               ('pid', 'image', 'creationFileTime'))
    if differs or unverified:
        refusals.append(_refusal(
            'RUN_IDENTITY_SESSION_MISMATCH',
            'the editor session in this bundle is not the expected one',
            which='editor', differingFields=differs, unverifiedFields=unverified))
    differs, unverified = _session_differences(binding['expectedGameSession'], game_session,
                                               ('pid', 'tid', 'processCreation', 'image'))
    if differs or unverified:
        refusals.append(_refusal(
            'RUN_IDENTITY_SESSION_MISMATCH',
            'the game session in this bundle is not the expected one',
            which='game', differingFields=differs, unverifiedFields=unverified))

    if level_id is not None and level_id != binding['expectedLevelId']:
        refusals.append(_refusal(
            'RUN_IDENTITY_LEVEL_MISMATCH',
            'the observed level is not the level this case is bound to',
            observedLevelId=level_id, expectedLevelId=binding['expectedLevelId'],
            authorizedTargetLevelId=AUTHORIZED_TARGET_LEVEL_ID))

    derived_generation = None
    if cursor is not None and observation_id is not None and registration is not None \
            and registration.get('registrationCompletedTick') is not None and level_id:
        derived_generation = hashlib.sha256(_canonical({
            'observationId': observation_id,
            'registrationCompletedTick': registration['registrationCompletedTick'],
            'sequence': cursor['sequence'],
            'levelId': level_id,
        })).hexdigest()[:32]

    expected_generation = binding['expectedRunGeneration']
    if isinstance(expected_generation, Mapping):
        want_obs = expected_generation.get('observationId')
        want_seq = expected_generation.get('sequence')
        want_tick = expected_generation.get('registrationCompletedTick')
        generation_differs = sorted(
            name for name, want, got in (
                ('observationId', want_obs, observation_id),
                ('sequence', want_seq, cursor.get('sequence') if cursor else None),
                ('registrationCompletedTick', want_tick,
                 registration.get('registrationCompletedTick') if registration else None),
            ) if want is not None and want != got)
        if generation_differs:
            refusals.append(_refusal(
                'RUN_IDENTITY_GENERATION_MISMATCH',
                'this bundle belongs to a different run generation than the one this case '
                'was already bound to; a previous run of the same level is not this run',
                differingFields=generation_differs,
                expectedRunGeneration=dict(expected_generation),
                observedRunGeneration={'observationId': observation_id,
                                       'sequence': cursor.get('sequence') if cursor else None,
                                       'registrationCompletedTick':
                                           registration.get('registrationCompletedTick')
                                           if registration else None}))
    elif expected_generation is not None:
        refusals.append(_refusal(
            'RUN_IDENTITY_GENERATION_MISMATCH',
            'binding.expectedRunGeneration must be an object of observed fields or null',
            observedType=type(expected_generation).__name__))

    return {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'caseId': binding['caseId'],
        'established': not refusals,
        'state': 'refused' if refusals else 'established',
        'editorIdentity': editor_identity,
        'gameSessionIdentity': game_session,
        'levelId': level_id,
        'levelIdSource': level_source,
        'observerRegistrationId': registration,
        'observationId': observation_id,
        'eventCursor': cursor,
        'derivedGenerationId': derived_generation,
        'derivedGenerationIdMeaning': (
            'a digest over observed fields (observationId, registrationCompletedTick, '
            'sequence, levelId). It is a comparison label for this run, is not assigned by '
            'the game, and is not a run id this layer minted. It is null when the event '
            'cursor is missing, because no generation can then be claimed. The cursor is '
            'sourced only from 1022 records received inside the observation window, so a '
            'cached pre-window log cannot mint one.'),
        # The generation-source exclusion, made visible (R16).  A nonzero count is the
        # machine-readable trace that the pre-window records were dropped where the cursor
        # is *chosen*, not merely filtered out of the window's display list downstream.
        'cursorCandidatesExcludedByWindow': sorted(cursor_events_outside_window),
        'cursorCandidatesExcludedByWindowMeaning': (
            'otherwise-usable 1022 sequences rejected as cursor candidates because their '
            'receivedUtc is outside the observation window (before start or after stop). '
            'They are the cached-log records the generation source refuses to mint from.'),
        'window': window,
        'events': [
            {'sequence': e.get('sequence'),
             'receivedUtc': _iso(_utc(e.get('receivedUtc'))),
             'managedThreadId': e.get('managedThreadId'),
             'levelId': e.get('levelId'),
             'parsed': e.get('parsed'),
             'error': e.get('error')}
            for e in events if isinstance(e, Mapping)],
        'unparsedEventCount': len(events) - len(usable_events),
        'unparsedEventMeaning': 'events that did not parse, carried an error, or carried a '
                                'timestamp this layer cannot place. They are retained above '
                                'and are excluded from pass evidence.',
        'fieldProvenance': {name: {'source': src, 'sourceKind': kind}
                            for name, (src, kind) in FIELD_SOURCES.items()},
        'refusals': refusals,
    }


# --------------------------------------------------------------------------- #
# observation window and cursor
# --------------------------------------------------------------------------- #

def _harvest(bundle, identity):
    records = []
    level_init = bundle.get('levelInitialization')
    if isinstance(level_init, Mapping):
        events = level_init.get('events')
        if isinstance(events, Sequence) and not isinstance(events, (str, bytes)):
            for event in events:
                if not isinstance(event, Mapping):
                    continue
                records.append({'kind': 'level-init-1022', 'utc': _iso(_utc(event.get('receivedUtc'))),
                                'sequence': event.get('sequence'),
                                'levelId': event.get('levelId'),
                                'parsed': event.get('parsed'), 'error': event.get('error'),
                                'source': 'received-1022-packet-observer'})
    for key, doc in _paths_of(bundle):
        if key in ('levelInitialization', 'postRunReadback'):
            continue
        for field in ('observedUtc', 'debugLogReplyUtc', 'syncInvocationUtc',
                      'syncRequestObservedUtc', 'debugLogRpcReplyUtc', 'capturedUtc',
                      'createdUtc', 'observedAt'):
            if field in doc:
                records.append({'kind': '%s.%s' % (key, field),
                                'utc': _iso(_utc(doc.get(field))),
                                'source': doc.get('source') if _is_str(doc.get('source'))
                                else key})
        snapshots = doc.get('scenePacketSnapshots')
        if isinstance(snapshots, Sequence) and not isinstance(snapshots, (str, bytes)):
            for snap in snapshots:
                if isinstance(snap, Mapping):
                    records.append({'kind': '%s.scenePacketSnapshot' % key,
                                    'utc': _iso(_utc(snap.get('utc'))), 'id': snap.get('id'),
                                    'source': 'scene-packet-snapshot'})
    return records


def observation_window(bundle, *, identity, windowSeconds=None):
    """The observed window, its cursor and its defects.  Never infers "it did not run".

    An empty window reports ``not-observed``.  A truncated window keeps every gap field.
    Records dated before the window are returned as ``historical`` and are excluded from
    pass evidence -- that is the rejection of a cached log that still carries the marker.
    """
    if not isinstance(identity, Mapping) or identity.get('contract') != CONTRACT_ID:
        raise ObservationError('BINDING_CONTRACT_MISMATCH',
                               'identity must be a runtime_identity projection of this contract')
    window = dict(identity.get('window') or {})
    if windowSeconds is not None:
        if not _is_int(windowSeconds) or windowSeconds < 1:
            raise ObservationError('BINDING_INVALID',
                                   'windowSeconds must be a positive integer')
        window['windowSeconds'] = windowSeconds
    start, stop = _utc(window.get('startUtc')), _utc(window.get('stopUtc'))

    records = _harvest(bundle, identity)[:_MAX_WINDOW_RECORDS]
    truncation_reasons, rollback, out_of_order = [], [], []

    level_init = bundle.get('levelInitialization') or {}
    if isinstance(level_init, Mapping):
        sequence = level_init.get('sequence')
        retained = level_init.get('retainedEvents')
        limit = level_init.get('eventLimit')
        if _is_int(sequence) and _is_int(retained) and retained != sequence:
            truncation_reasons.append(
                'retainedEvents (%s) != sequence (%s): the event ring lost records'
                % (retained, sequence))
        if _is_int(limit) and _is_int(retained) and retained >= limit:
            truncation_reasons.append('the event ring is full (retained == eventLimit)')
        if _is_int(level_init.get('droppedEvents')) and level_init['droppedEvents'] > 0:
            truncation_reasons.append('droppedEvents=%s' % level_init['droppedEvents'])
        if level_init.get('overflow') is True:
            truncation_reasons.append('the observer reported overflow')
    for key, doc in _paths_of(bundle):
        if doc.get('observerScanLimited') is True:
            truncation_reasons.append('%s.observerScanLimited is true' % key)
        if doc.get('markerScanLimited') is True:
            truncation_reasons.append('%s.markerScanLimited is true' % key)
        if isinstance(doc.get('observerCleanupError'), str) and doc['observerCleanupError']:
            truncation_reasons.append('%s.observerCleanupError=%s'
                                      % (key, doc['observerCleanupError']))
        count, scan_limit = doc.get('logRecordCount'), doc.get('scannedRecordLimit')
        if _is_int(count) and _is_int(scan_limit) and count > scan_limit:
            truncation_reasons.append(
                '%s: %d log records present but only %d scanned' % (key, count, scan_limit))
        rows = doc.get('debugLogReply')
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) and rows:
            truncation_reasons.append(
                '%s.debugLogReply carries %d undated rows: a cached reply cannot be placed '
                'in the window' % (key, len(rows)))

    # sequence monotonicity and timestamp monotonicity
    sequenced = [r for r in records if r['kind'] == 'level-init-1022' and _is_int(r['sequence'])]
    for previous, current in zip(sequenced, sequenced[1:]):
        if current['sequence'] <= previous['sequence']:
            out_of_order.append({'field': 'sequence', 'before': previous['sequence'],
                                 'after': current['sequence']})
    dated = [r for r in records if _utc(r['utc']) is not None]
    # Monotonicity is checked *per stream*: the 1022 stream, the editor-evidence stamp and
    # each packet snapshot are separate clocks of interest, and comparing one against
    # another would invent an ordering the receipt never claimed.
    streams = {}
    for record in dated:
        streams.setdefault(record['kind'], []).append(record)
    for kind in sorted(streams):
        items = streams[kind]
        for previous, current in zip(items, items[1:]):
            if _utc(current['utc']) < _utc(previous['utc']):
                out_of_order.append({'field': 'receivedUtc', 'stream': kind,
                                     'before': previous['utc'], 'after': current['utc']})
    if out_of_order:
        rollback.append({'reason': 'observed records are not in monotonic order',
                         'detail': out_of_order[:16]})

    if start is not None and stop is not None and stop < start:
        rollback.append({'reason': 'the observer stop stamp precedes its start stamp',
                         'startUtc': window.get('startUtc'), 'stopUtc': window.get('stopUtc')})
    last_callback = _utc(window.get('lastCallbackUtc'))
    if start is not None and last_callback is not None and last_callback < start:
        rollback.append({'reason': 'the last callback stamp precedes the observer start stamp',
                         'lastCallbackUtc': window.get('lastCallbackUtc')})
    if isinstance(level_init, Mapping):
        prev_tick = None
        for event in level_init.get('events') or []:
            tick = event.get('receivedTick') if isinstance(event, Mapping) else None
            if _is_int(tick) and _is_int(prev_tick) and tick < prev_tick:
                rollback.append({'reason': 'receivedTick decreased between events',
                                 'before': prev_tick, 'after': tick})
                break
            prev_tick = tick if _is_int(tick) else prev_tick
    if stop is not None:
        for record in dated:
            if _utc(record['utc']) > stop:
                rollback.append({'reason': 'a record is dated after the observer stopped',
                                 'record': record['kind'], 'utc': record['utc'],
                                 'stopUtc': window.get('stopUtc')})
                break

    in_window, historical, after_stop, undated = [], [], [], []
    for record in records:
        moment = _utc(record['utc'])
        if moment is None:
            undated.append(record)
        elif start is not None and moment < start:
            historical.append(dict(record, historicalBecause='received before the window opened'))
        elif stop is not None and moment > stop:
            after_stop.append(dict(record, excludedBecause='received after the window closed'))
        else:
            in_window.append(record)

    # "undated" and "empty-window" are different failures and are kept apart: undated means
    # there is no clock at all to place anything against, empty-window means the clock is
    # fine and nothing landed in it.  Collapsing them would turn "we cannot date this" into
    # "the run produced nothing".
    #
    # A window is usable only when it is *positively closed*: a receipt that carries a stop
    # stamp.  Stopping is what closes an observation.  An observer receipt with no stop
    # stamp is the receipt's own statement that the observer had not stopped -- the run may
    # still be producing records -- so the window is "open-window".  A window whose receipt
    # is absent altogether is "unbounded-window": there is no window to place records in.
    # Both are kept out of ``usable``, so neither can be read as ``observed`` and neither
    # can promote the sample to pass or the evidence to live (``windowOpen`` is what gates).
    # This is a refusal to over-read, not a claim that no run happened.
    window_datable = start is not None or stop is not None
    window_open = window.get('windowOpen')
    window_closed = window_open is False
    if rollback:
        state, usable = 'refused', False
        refusals = [_refusal('RUNTIME_CLOCK_ROLLBACK',
                             'the observation window is not internally ordered; a clock that '
                             'moves backwards cannot date a run',
                             evidence=rollback[:16])]
    elif not dated and not window_datable:
        state, usable = 'undated', False
        refusals = []
    elif truncation_reasons:
        state, usable = 'truncated', False
        refusals = [_refusal('RUNTIME_WINDOW_TRUNCATED',
                             'the window lost records; a truncated window cannot be read as a '
                             'complete observation, and its gaps are kept',
                             reasons=sorted(set(truncation_reasons)))]
    elif not window_closed:
        state, usable = ('open-window' if window_open is True else 'unbounded-window'), False
        refusals = []
    elif not in_window:
        state, usable = 'empty-window', False
        refusals = []
    else:
        state, usable = 'observed', True
        refusals = []

    return {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'caseId': identity.get('caseId'),
        'state': state,
        'usable': usable,
        'window': window,
        'windowOpen': window.get('windowOpen'),
        'windowClosed': window_closed,
        'cursor': identity.get('eventCursor'),
        'cursorMeaning': 'the cursor is the newest parsed 1022 event. It is monotonic and '
                         'increments only on a real Receive, which is why it is the only '
                         'generation carrier this project has.',
        'inWindowRecords': in_window,
        'inWindowCount': len(in_window),
        'historicalRecords': historical,
        'historicalCount': len(historical),
        'afterStopRecords': after_stop,
        'undatedRecords': [r for r in undated],
        'undatedCount': len(undated),
        'truncated': bool(truncation_reasons),
        'truncationReasons': sorted(set(truncation_reasons)),
        'outOfOrder': out_of_order,
        'clockRollback': bool(rollback),
        'clockRollbackEvidence': rollback,
        'packetKinds': (bundle.get('logObserverEvidence') or {}).get('packetKinds')
        if isinstance(bundle.get('logObserverEvidence'), Mapping) else None,
        'errors': {
            'callbackErrors': (bundle.get('logObserverEvidence') or {}).get('callbackErrors')
            if isinstance(bundle.get('logObserverEvidence'), Mapping) else None,
            'observerCleanupError': (bundle.get('logObserverEvidence') or {}).get(
                'observerCleanupError')
            if isinstance(bundle.get('logObserverEvidence'), Mapping) else None,
            'parseErrors': level_init.get('parseErrors') if isinstance(level_init, Mapping)
            else None,
            'evidenceErrors': level_init.get('evidenceErrors') if isinstance(level_init, Mapping)
            else None,
            'threadErrors': level_init.get('threadErrors') if isinstance(level_init, Mapping)
            else None,
        },
        'emptyMeaning': ('not-observed: the window holds no dated record. That is not '
                         '"it did not run" -- the adapter itself says absence is not proof '
                         'of nonexecution.')
        if state in ('empty-window', 'undated') else None,
        'unclosedMeaning': ('not-observed-as-a-complete-window: the observer receipt does '
                            'not carry a stop stamp, so the window is not closed. The run '
                            'may still be producing records, so this is an incomplete '
                            'observation, not a failed or absent one. `usable` is false and '
                            'the window cannot promote the sample to pass or the evidence '
                            'to live.')
        if state in ('open-window', 'unbounded-window') else None,
        'refusals': refusals,
    }


# --------------------------------------------------------------------------- #
# run-object correlation
# --------------------------------------------------------------------------- #

def _run_generation(identity):
    """The run generation this identity can supply, field by field (``None`` if absent)."""
    registration = identity.get('observerRegistrationId')
    cursor = identity.get('eventCursor')
    return {
        'observationId': identity.get('observationId'),
        'registrationCompletedTick': (registration or {}).get('registrationCompletedTick')
        if isinstance(registration, Mapping) else None,
        'sequence': (cursor or {}).get('sequence') if isinstance(cursor, Mapping) else None,
    }


def _readback_generation(readback):
    """The generation carriers a readback actually carries, and whether it carries none."""
    carried = {field: readback[field] for field in GENERATION_CARRIER_FIELDS
               if readback.get(field) is not None}
    return carried, not carried


def _generation_differences(carried, identity):
    """(differing, unverifiable) carriers.

    A carrier the readback names but the *run* cannot supply is ``unverifiable``, not a
    match: "we could not compare it" is not "it agreed", and this layer fails closed on
    that exactly as it does for session fields.
    """
    run = _run_generation(identity)
    differing, unverifiable = [], []
    for field in GENERATION_CARRIER_FIELDS:
        if field not in carried:
            continue
        if run.get(field) is None:
            unverifiable.append(field)
        elif carried[field] != run[field]:
            differing.append(field)
    return sorted(differing), sorted(unverifiable)


def correlate_objects(bundle, *, identity, expectedEntityIds=None):
    """Correlate this round's saved entity ids with objects read inside the run.

    An editor-state catalog is refused, not reinterpreted: it lists what the editor holds,
    which is a different layer from what a run contains.  Matching is by entity id only; a
    label is not an identity, so a text-only match is refused rather than accepted.
    """
    if not isinstance(identity, Mapping) or identity.get('contract') != CONTRACT_ID:
        raise ObservationError('BINDING_CONTRACT_MISMATCH',
                               'identity must be a runtime_identity projection of this contract')
    expected = sorted({v for v in (expectedEntityIds or []) if _is_int(v) and v > 0})
    base = {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'caseId': identity.get('caseId'),
        'expectedEntityIds': expected,
        'matchesIdentityLevel': None,
        'matchesIdentityGeneration': None,
        'matched': [], 'missing': [], 'unexpected': [], 'ambiguous': [],
        'code': None, 'requiredReader': None, 'refusals': [],
    }
    if not expected:
        return dict(base, status='not-run', usable=False,
                    reason='no expected entity ids were supplied, so there is nothing to '
                           'correlate; an empty expectation is not an empty observation')

    runtime_objects = bundle.get('runtimeObjects')
    if not isinstance(runtime_objects, Mapping):
        catalog = bundle.get('editorCatalog')
        if isinstance(catalog, Mapping):
            return dict(base, status='fail', usable=False, code='EDIT_STATE_NOT_RUNTIME',
                        refusals=[_refusal(
                            'EDIT_STATE_NOT_RUNTIME',
                            'an editor-state catalog was offered as a run observation. The '
                            'editor lists what it holds now and says nothing about what this '
                            'run created; the two are different layers and this layer will '
                            'not substitute one for the other.',
                            source=catalog.get('source'),
                            sourceKind=catalog.get('sourceKind'),
                            targetEntityCount=len(catalog.get('entities') or [])
                            if isinstance(catalog.get('entities'), Sequence) else None)],
                        reason='an edit-state list cannot stand in for a runtime observation')
        return dict(base, status='blocked', usable=False,
                    code='CORRELATION_NOT_A_RUNTIME_OBSERVATION',
                    requiredReader={
                        'mustCarry': sorted(RUNTIME_OBJECT_SOURCES),
                        'mustBeDatedInsideWindow': True,
                        'mustCarryEntityId': True,
                        'note': 'no runtime-scope object reader is implemented, so this item '
                                'has no producer yet; the consumer (this function) is ready ',
                    },
                    reason='no runtime-scope object readback was supplied')

    source = runtime_objects.get('source')
    if source not in RUNTIME_OBJECT_SOURCES:
        return dict(base, status='fail', usable=False,
                    code='RUNTIME_OBJECT_SOURCE_UNSUPPORTED',
                    refusals=[_refusal(
                        'RUNTIME_OBJECT_SOURCE_UNSUPPORTED',
                        'the supplied object readback is not from a run-time source',
                        source=source, accepted=list(RUNTIME_OBJECT_SOURCES),
                        editStateSources=list(EDIT_STATE_SOURCES))],
                    reason='the object readback source is not accepted as run-time evidence')

    level_id = runtime_objects.get('levelId')
    if level_id != identity.get('levelId'):
        return dict(base, status='fail', usable=False, code='RUN_IDENTITY_LEVEL_MISMATCH',
                    matchesIdentityLevel=False,
                    refusals=[_refusal('RUN_IDENTITY_LEVEL_MISMATCH',
                                       'the object readback is from another level',
                                       observedLevelId=level_id,
                                       runLevelId=identity.get('levelId'))],
                    reason='the object readback is not from this run level')

    # Same *generation* as well as same level.  Entity ids are reused across levels AND
    # across runs of the same level, so a level match on its own does not make a readback
    # this run's: a readback from the previous run of the same level would pass a level-only
    # check.  The readback must carry at least one of the run's generation carriers, and
    # every carrier it does carry must agree with this run.
    carried, unbound = _readback_generation(runtime_objects)
    if unbound:
        return dict(base, status='blocked', usable=False, matchesIdentityLevel=True,
                    matchesIdentityGeneration=None,
                    code='CORRELATION_GENERATION_UNBOUND',
                    requiredGenerationCarrier=sorted(GENERATION_CARRIER_FIELDS),
                    refusals=[_refusal(
                        'CORRELATION_GENERATION_UNBOUND',
                        'the readback carries no generation carrier, so a same-level readback '
                        'from a previous run of this level cannot be told apart from this run',
                        observedLevelId=level_id,
                        requiredAny=sorted(GENERATION_CARRIER_FIELDS))],
                    reason='the object readback is level-matched but not generation-bound')
    differing, unverifiable = _generation_differences(carried, identity)
    if differing or unverifiable:
        return dict(base, status='fail', usable=False, matchesIdentityLevel=True,
                    matchesIdentityGeneration=False,
                    code='RUN_IDENTITY_GENERATION_MISMATCH',
                    observedGeneration=dict(carried),
                    refusals=[_refusal(
                        'RUN_IDENTITY_GENERATION_MISMATCH',
                        'the object readback belongs to a different run generation than this '
                        'run; a previous run of the same level is not this run, and a carrier '
                        'that cannot be compared is not a match',
                        observedLevelId=level_id, observedGeneration=dict(carried),
                        differingFields=differing, unverifiableFields=unverifiable,
                        runGeneration=_run_generation(identity))],
                    reason='the object readback is not bound to this run generation')

    rows = runtime_objects.get('objects')
    rows = list(rows) if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
    start = _utc((identity.get('window') or {}).get('startUtc'))
    stop = _utc((identity.get('window') or {}).get('stopUtc'))
    stale, text_only, indexed = [], [], {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        moment = _utc(row.get('observedUtc'))
        if moment is None or (start is not None and moment < start) or \
                (stop is not None and moment > stop):
            stale.append({'entityId': row.get('entityId'), 'observedUtc': row.get('observedUtc')})
            continue
        entity_id = row.get('entityId')
        if not _is_int(entity_id) or entity_id <= 0:
            if _is_str(row.get('label')) or _is_str(row.get('name')):
                text_only.append({'label': row.get('label') or row.get('name'),
                                  'observedUtc': row.get('observedUtc')})
            continue
        indexed.setdefault(entity_id, []).append(row)

    if stale:
        return dict(base, status='fail', usable=False, matchesIdentityLevel=True,
                    code='RUNTIME_LOG_STALE', staleRows=stale,
                    refusals=[_refusal('RUNTIME_LOG_STALE',
                                       'the object readback carries rows dated outside the '
                                       'observation window; a stale readback is not this run',
                                       rows=stale[:16])],
                    reason='the object readback is not bound to this window')
    if text_only and not indexed:
        return dict(base, status='fail', usable=False, matchesIdentityLevel=True,
                    code='CORRELATION_TEXT_ONLY', textOnlyRows=text_only,
                    refusals=[_refusal('CORRELATION_TEXT_ONLY',
                                       'objects were matched by label only; a label is not an '
                                       'identity and two objects can share one',
                                       rows=text_only[:16])],
                    reason='text-only correlation is refused')

    ambiguous = sorted(eid for eid, hits in indexed.items() if len(hits) > 1)
    matched = sorted(eid for eid in expected if eid in indexed and eid not in ambiguous)
    missing = sorted(eid for eid in expected if eid not in indexed)
    unexpected = sorted(eid for eid in indexed if eid not in expected)
    ok = not missing and not ambiguous and bool(matched)
    return dict(
        base, status='pass' if ok else 'fail', usable=ok, matchesIdentityLevel=True,
        matchesIdentityGeneration=True, observedGeneration=dict(carried),
        matched=matched, missing=missing, unexpected=unexpected, ambiguous=ambiguous,
        matchedCount=len(matched), missingCount=len(missing),
        code=None if ok else ('CORRELATION_INCOMPLETE' if missing else 'CORRELATION_AMBIGUOUS'),
        refusals=[] if ok else [_refusal(
            'CORRELATION_NOT_A_RUNTIME_OBSERVATION',
            'the expected saved entities were not all observed inside this run',
            missing=missing, ambiguous=ambiguous)],
        reason=None if ok else 'expected entities were not observed in the run readback')


# --------------------------------------------------------------------------- #
# return to editor
# --------------------------------------------------------------------------- #

def return_to_editor(bundle, *, identity, window=None):
    """Read back whether the run returned to edit state -- verdict still ``unknown``.

    The *reader* is implemented here: it accepts a readback only from the one proven editor
    operation that reports the editor's level state (``RETURN_TO_EDITOR_SOURCES``), requires
    it to be dated strictly after the observation window closed, requires it to name this
    run's level, requires it to carry an integer level state, and then evaluates a
    *contracted* edit-state predicate.  What it refuses to do is invent the predicate: no
    named level-state enumeration exists in this project (see ``EDIT_STATE_PREDICATE`` and
    its ``basis``), so the verdict stays ``unknown`` and the item can never reach ``pass``
    until a predicate carrying its own ``authority`` is frozen in.  A supplied readback is
    retained and reported field by field -- never promoted to a pass.
    """
    if not isinstance(identity, Mapping) or identity.get('contract') != CONTRACT_ID:
        raise ObservationError('BINDING_CONTRACT_MISMATCH',
                               'identity must be a runtime_identity projection of this contract')
    stop = _utc((identity.get('window') or {}).get('stopUtc'))
    raw = bundle.get('postRunReadback')
    observed, refusals, accepted = None, [], False
    if isinstance(raw, Mapping):
        moment = _utc(raw.get('observedUtc'))
        source = raw.get('source')
        level_id = raw.get('levelId')
        level_state = raw.get('editorLevelState')
        observed = {
            'observedUtc': _iso(moment),
            'afterWindowStop': bool(moment is not None and stop is not None and moment >= stop),
            'levelId': level_id,
            'matchesRunLevel': level_id == identity.get('levelId'),
            'editorLevelState': level_state,
            'editorLevelStateIsInteger': _is_int(level_state),
            'source': source,
            'sourceAccepted': source in RETURN_TO_EDITOR_SOURCES,
            'independentReadback': bool(raw.get('independentReadback') is True),
        }
        if source not in RETURN_TO_EDITOR_SOURCES:
            refusals.append(_refusal(
                'RETURN_TO_EDITOR_SOURCE_UNSUPPORTED',
                'the readback does not name an editor operation this project has proven; a '
                'readback from anywhere else is refused rather than compared',
                source=source, accepted=list(RETURN_TO_EDITOR_SOURCES),
                observedPostRunReadback=observed))
        elif not observed['afterWindowStop']:
            refusals.append(_refusal(
                'RETURN_TO_EDITOR_NOT_AFTER_RUN',
                'the readback is not dated strictly after the observation window closed, so '
                'it cannot show what happened after the run',
                observedUtc=observed['observedUtc'],
                windowStopUtc=_iso(stop), observedPostRunReadback=observed))
        elif not observed['matchesRunLevel']:
            refusals.append(_refusal(
                'RUN_IDENTITY_LEVEL_MISMATCH',
                'the readback is from another level, so it says nothing about this run '
                'returning to edit state',
                observedLevelId=level_id, runLevelId=identity.get('levelId'),
                observedPostRunReadback=observed))
        elif not _is_int(level_state):
            refusals.append(_refusal(
                'RETURN_TO_EDITOR_LEVEL_STATE_UNREADABLE',
                'the readback carries no integer editor level state to compare against a '
                'predicate',
                editorLevelState=level_state, observedPostRunReadback=observed))
        else:
            accepted = True

    predicate = dict(EDIT_STATE_PREDICATE)
    contracted = bool(predicate.get('contracted')) and _is_str(predicate.get('authority')) \
        and predicate.get('expectedValue') is not None
    if accepted and contracted and observed['editorLevelState'] == predicate['expectedValue']:
        status, usable = 'pass', True
    else:
        status, usable = 'unknown', False
    if not accepted and observed is None:
        refusals.append(_refusal('RETURN_TO_EDITOR_READER_UNCONTRACTED',
                                 'reported unknown: no post-run readback was supplied',
                                 observedPostRunReadback=None))
    elif status != 'pass':
        refusals.append(_refusal(
            'RETURN_TO_EDITOR_READER_UNCONTRACTED',
            'reported unknown: no contracted reader exists for "the editor is back in edit '
            'state", so a readback cannot be turned into a verdict',
            acceptedReadback=accepted,
            blockedBy='edit-state-predicate-not-contracted',
            predicateContracted=contracted,
            observedPostRunReadback=observed))
    return {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'caseId': identity.get('caseId'),
        'status': status,
        'usable': usable,
        'code': None if status == 'pass' else 'RETURN_TO_EDITOR_READER_UNCONTRACTED',
        'producer': None,
        'reason': 'no contracted reader exists for "the editor is back in edit state". The '
                  'readback is accepted and parsed, but the observed field a reader would '
                  'compare (`editorLevelState`) has no contracted value, so no readback can '
                  'make this item pass.',
        'readbackAccepted': accepted,
        'reader': {
            'implemented': True,
            'reads': predicate['reads'],
            'predicateContracted': contracted,
            'blockedBy': None if contracted else 'edit-state-predicate-not-contracted',
            'predicateBasis': predicate['basis'],
            'whyNotContracted': predicate['why'],
            'wouldNeed': list(predicate['wouldNeed']),
        },
        'requiredReader': {
            'mustProvide': ['a readback from %s' % (RETURN_TO_EDITOR_SOURCES,),
                            'a readback performed strictly after the window stop stamp',
                            'the same level identity',
                            'a contracted edit-state predicate carrying its own authority'],
            'mustNotProvide': ['a screenshot', 'a human narrative', 'an editor catalog '
                               'standing in for the run'],
        },
        'observedPostRunReadback': observed,
        'countsTowardPass': False,
        'countsTowardPassReason': 'a supplied readback is retained but cannot make this item '
                                  'pass until a contracted predicate exists',
        'refusals': refusals,
    }


# --------------------------------------------------------------------------- #
# S09 responsibility
# --------------------------------------------------------------------------- #

def _control_status(bundle, identity):
    control = bundle.get('runControl')
    out = {
        'contract': CONTROL_CONTRACT_ID,
        'present': False,
        # ``runControl`` is the *capability* of the project's control entry, not the outcome
        # of this run.  DS-02 measured that no programmable entry exists, so it is
        # RUN_CONTROL_UNAVAILABLE in every case -- including the case where a human did run
        # the playtest and it was recorded.  Keeping these apart is what stops "we recorded
        # a manual run" from reading as "we can control runs".
        'runControl': 'RUN_CONTROL_UNAVAILABLE',
        'autonomyVerified': False,
        'manualStepRequired': False,
        'ds02Evidence': dict(DS02_EVIDENCE),
        'startsPlaytestByThisModule': STARTS_PLAYTEST,
        'startStopMode': None,
        'triggeredBy': None,
        'startedUtc': None,
        'stoppedUtc': None,
        'autonomousGateComplete': False,
        'refusals': [],
    }
    if control is None:
        out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
        out['ds02ItemToken'] = 'blocked'
        out['manualStepRequired'] = True
        out['note'] = ('no runtime-control/1 record was supplied. DS-02 measured that no '
                       'programmable start/stop playtest entry exists in this project, so '
                       'there is no automated producer to wait for; a human must press the '
                       'button. The honest answer is RUN_CONTROL_UNAVAILABLE, and this pack '
                       'does not invent a start-playtest command.')
        return out
    if not isinstance(control, Mapping):
        out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
        out['ds02ItemToken'] = 'blocked'
        out['refusals'].append(_refusal('CONTROL_CONTRACT_MISMATCH',
                                        'runControl must be a runtime-control/1 object',
                                        observedType=type(control).__name__))
        return out
    out['present'] = True
    unknown = sorted(set(control) - set(CONTROL_FIELDS))
    if control.get('contract') != CONTROL_CONTRACT_ID or unknown:
        out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
        out['refusals'].append(_refusal(
            'CONTROL_CONTRACT_MISMATCH',
            'the control record is not runtime-control/1 as frozen',
            contract=control.get('contract'), expectedContract=CONTROL_CONTRACT_ID,
            unrecognizedKeys=unknown))
        return out
    for field in FORBIDDEN_CONTROL_FIELDS:
        if control.get(field) is not None:
            out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
            out['refusals'].append(_refusal(
                'CONTROL_COMMAND_NOT_REPRESENTABLE',
                'this project has no start/stop playtest command; a control record naming one '
                'is refused rather than forwarded',
                field=field))
    if control.get('startsPlaytest') is True:
        out['refusals'].append(_refusal(
            'CONTROL_COMMAND_NOT_REPRESENTABLE',
            'a control record may not claim that the observing layer started the playtest',
            field='startsPlaytest'))
    if out['refusals']:
        return out
    mode = control.get('startStopMode')
    if mode not in ('manual', 'automated'):
        out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
        out['refusals'].append(_refusal('CONTROL_CONTRACT_MISMATCH',
                                        'startStopMode must be "manual" or "automated"',
                                        startStopMode=mode))
        return out
    # D24.01.03 -- record the control SOURCE of every step explicitly, and refuse a
    # mislabelled record *before* any capability is reported.  The assembly half already
    # refuses an automated claim (``BUNDLE_CONTROL_AUTOMATED_UNPROVEN``); calling the same
    # shared guard here keeps the two halves of runtime-control/1 from disagreeing.  Without
    # this, a caller-supplied startStopMode='automated' record was reported as
    # capability='automated' with no refusal -- the very masquerade this item forbids.
    source_audit = control_source_guard.audit_control_record(dict(control))
    out['controlSource'] = source_audit['source']
    out['controlSteps'] = source_audit['steps']
    if source_audit['refusals']:
        out['capability'] = 'RUN_CONTROL_UNAVAILABLE'
        out['manualStepRequired'] = True
        out['ds02ItemToken'] = 'blocked'
        out['refusals'].extend(source_audit['refusals'])
        return out
    started, stopped = _utc(control.get('startedUtc')), _utc(control.get('stoppedUtc'))
    out.update(startStopMode=mode, triggeredBy=control.get('triggeredBy'),
               startedUtc=_iso(started), stoppedUtc=_iso(stopped),
               caseIdMatches=control.get('caseId') == identity.get('caseId'),
               levelIdMatches=control.get('levelId') == identity.get('levelId'),
               capability='manual-step-required')
    # DS-02's own item token for this item: a recorded human run is `manual-step-required`,
    # and its verdict vocabulary deliberately contains no "pass".
    out['ds02ItemToken'] = 'manual-step-required'
    out['manualStepRequired'] = True
    # A human-triggered run is recorded precisely but the autonomous gate stays incomplete.
    out['autonomousGateComplete'] = False
    out['autonomousGateReason'] = (
        'the start and stop were recorded, but the run was triggered by a human step. S09 '
        'records this precisely and the autonomous gate stays incomplete.')
    return out


def _ds02_agreement(control):
    """Compare this projection's control verdict with DS-02's on the decisive fields.

    The two vocabularies are not the same and are not silently rewritten into each other:
    DS-02's adjudicator reports ``RUN_CONTROL_UNAVAILABLE`` / ``manual-step-required`` /
    ``observed-manual`` and has no "pass"; this projection keeps G01 D10's closed stage set
    for ``status`` and carries DS-02's token beside it.  What must agree is the *decisive*
    fact -- whether an automated control entry exists and whether autonomy was verified --
    and that is what this block checks.
    """
    ours_run_control = control.get('runControl', 'RUN_CONTROL_UNAVAILABLE')
    ours_manual = bool(control.get('manualStepRequired'))
    ours_autonomy = bool(control.get('autonomyVerified'))
    return {
        'basis': DS02_EVIDENCE['adjudicator'] + ' (sha256 '
                 + DS02_EVIDENCE['adjudicatorSha256'] + ')',
        'ds02RunControl': DS02_EVIDENCE['verdict'],
        'ourRunControl': ours_run_control,
        'runControlAgrees': ours_run_control == DS02_EVIDENCE['verdict'],
        'ds02ManualStepRequired': DS02_EVIDENCE['manualStepRequired'],
        'ourManualStepRequired': ours_manual,
        'ds02AutonomyVerified': DS02_EVIDENCE['autonomyVerified'],
        'ourAutonomyVerified': ours_autonomy,
        'autonomyAgrees': ours_autonomy is DS02_EVIDENCE['autonomyVerified'],
        'ourItemToken': control.get('ds02ItemToken'),
        'ds02ItemTokenVocabulary': list(DS02_START_STOP_TOKENS),
        'tokenVocabularyDifference': (
            "DS-02's artifactStatus for start-and-stop is 'manual-step-required' (manual) or "
            "'blocked' (no record); neither is in G01 D10's closed stage set "
            "(not-run/pass/fail/blocked/unknown/not-applicable). This projection therefore "
            "keeps `status` inside the closed set and carries DS-02's token in `capability` "
            "and `ds02ItemToken`. That is the one place the two vocabularies differ, and it "
            "is named here rather than hidden. Both agree start-and-stop is not closed."),
        'agreesThatStartAndStopIsNotClosed': True,
    }


def s09_responsibility(bundle, *, identity=None, window=None, correlation=None,
                       returnToEditor=None):
    """Which of the five S09 items this pack can carry, and who the producer is."""
    control = _control_status(bundle, identity or {})
    items = {}
    for name in S09_EVIDENCE_ITEMS:
        items[name] = dict(EVIDENCE_PRODUCERS[name])
    if identity is not None:
        items['current-run-identity'].update(
            status='pass' if identity.get('established') else 'fail',
            usable=bool(identity.get('established')),
            detail=identity.get('refusals'))
    if window is not None:
        if window.get('usable'):
            window_status = 'pass'
        elif window.get('state') in ('undated', 'empty-window', 'open-window',
                                     'unbounded-window'):
            # Not a failure of the observation: the window simply is not closed (or holds
            # nothing), so the item cannot be concluded yet.  Saying 'fail' here would read
            # an in-progress observation as a defective one.
            window_status = 'blocked'
        else:
            window_status = 'fail'
        items['runtime-observation'].update(
            status=window_status, usable=bool(window.get('usable')),
            detail=window.get('refusals'), state=window.get('state'))
    if correlation is not None:
        items['runtime-object-correlation'].update(
            status=correlation.get('status'), usable=bool(correlation.get('usable')),
            detail=correlation.get('refusals'))
    if returnToEditor is not None:
        items['return-to-editor'].update(status='unknown', usable=False)
    start_stop = items['start-and-stop']
    # No "pass" is reachable for this item: DS-02 measured that no programmable start/stop
    # entry exists, so a recorded run can only ever be a human one -- `manual-step-required`,
    # never closed.  Saying `pass` here would upgrade "a person pressed the button" into
    # "the tooling can run a playtest", which is exactly the reading 07 §8 forbids.
    if control.get('refusals'):
        start_stop.update(status='fail', usable=False, detail=control['refusals'])
    elif not control.get('present'):
        start_stop.update(status='blocked', usable=False, capability=control['capability'],
                          reason='RUN_CONTROL_UNAVAILABLE: no control record, and DS-02 '
                                 'measured that no automated entry can produce one')
    elif control.get('caseIdMatches') and control.get('levelIdMatches') \
            and control.get('startedUtc') and control.get('stoppedUtc'):
        start_stop.update(status='blocked', usable=False,
                          capability=control['capability'],
                          reason='manual-step-required: the start and stop were recorded '
                                 'precisely, but a human pressed the button and the '
                                 'autonomous gate stays incomplete')
    else:
        start_stop.update(status='fail', usable=False,
                          reason='the control record does not name this case and level')
    start_stop['ds02ItemToken'] = control.get('ds02ItemToken')
    passed = [n for n in S09_EVIDENCE_ITEMS if items[n].get('status') == 'pass']
    return {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'items': items,
        'passedItems': passed,
        'missingItems': [n for n in S09_EVIDENCE_ITEMS if n not in passed],
        'status': 'pass' if len(passed) == len(S09_EVIDENCE_ITEMS) else 'fail',
        'autonomous': False,
        'runControl': control,
        'ds02Agreement': _ds02_agreement(control),
        'producerSummary': {
            'producedByThisModule': ['current-run-identity', 'runtime-object-correlation',
                                     'runtime-observation'],
            # NOT "blocked on a dependency": DS-02 measured that no automated producer
            # exists, and the measurement is the finding.  A human is the only producer.
            'noAutomatedProducerMeasured': ['start-and-stop'],
            'humanOnlyProducer': ['start-and-stop'],
            'noProducer': ['return-to-editor'],
        },
        'startStopFinding': {
            'kind': 'measured-negative',
            'statement': DS02_EVIDENCE['finding'],
            'explicitlyNotClaimed': DS02_EVIDENCE['explicitlyNotClaimed'],
            'surfacesSearched': DS02_EVIDENCE['surfacesSearched'],
            'basis': DS02_EVIDENCE['handoff'],
            'provenStartStopPath': 'the official editor UI, pressed by a human',
            'minimalGap': {
                'kind': 'measured-negative',
                'missingInput':
                    'a *named* editor level-state enumeration, or a contrast sample whose '
                    'states are recorded (one in edit state, one in a non-edit state inside '
                    'one bridge scope)',
                'whyThisIsTheMinimum':
                    'the same uncontracted level-state value that blocks return-to-editor also '
                    'blocks any synthesis of a start/stop command: without a name for the '
                    'playtest state there is nothing a command could be checked against, and '
                    'the two gaps share one root cause rather than being two separate bugs',
                'notClosedByThisModule': ['start', 'stop', 'playtest',
                                          'a start-playtest command name'],
                'stillReachableOnlyBy': 'a human pressing the button, recorded as '
                                        'manual-step-required',
            },
        },
    }


# --------------------------------------------------------------------------- #
# the projection
# --------------------------------------------------------------------------- #

def _fixture_marker(raw):
    marker = raw.get('_fixture') if isinstance(raw, Mapping) else None
    return marker if isinstance(marker, Mapping) else None


def normalize_runtime_evidence(raw, binding):
    """The projection: strictly bound to a case id, a run identity and a source digest.

    Mixing two runs in one bundle is refused, not merged.  ``evidenceMode`` defaults to
    ``offline`` and only becomes ``live`` through ``liveEvidence.derived`` below; a fixture
    that claims to be live is refused outright, because a document cannot promote itself.
    """
    binding = _validate_binding(binding)
    kind = input_kind(raw)
    if kind != 'runtime-evidence-bundle':
        raise ObservationError(
            'INPUT_KIND_UNSUPPORTED',
            'this layer projects a decoded runtime-evidence bundle; a bare receipt or an '
            'unknown document is refused rather than guessed at',
            inputKind=kind, supported=list(SUPPORTED_INPUTS))

    if binding['sourceSha256'] is not None:
        actual = _digest(raw)
        if actual != binding['sourceSha256']:
            raise ObservationError(
                'SOURCE_DIGEST_MISMATCH',
                'the bundle does not match the source digest this case is bound to',
                expectedSourceSha256=binding['sourceSha256'], actualSourceSha256=actual)

    refusals = []
    fixture = _fixture_marker(raw)
    if fixture is not None and fixture.get('live') is True:
        refusals.append(_refusal(
            'FIXTURE_CLAIMS_LIVE',
            'a document marked as a fixture claimed to be a live observation; a document '
            'cannot promote itself',
            fixture=dict(fixture)))

    identity = runtime_identity(raw, binding=binding)
    refusals += identity['refusals']

    # mixed runs: two distinct run identities inside one bundle is a merge of two runs.
    generations = set()
    for key, doc in _paths_of(raw):
        if key == 'levelInitialization':
            if _is_str(doc.get('observationId')):
                generations.add(('observationId', doc['observationId']))
            timing = doc.get('observerTiming')
            if isinstance(timing, Mapping) and timing.get('registrationCompletedTick') \
                    is not None:
                generations.add(('registrationCompletedTick',
                                 timing['registrationCompletedTick']))
        timing = doc.get('observerTiming')
        if isinstance(timing, Mapping) and timing.get('registrationCompletedTick') is not None:
            generations.add(('registrationCompletedTick', timing['registrationCompletedTick']))
    observation_ids = {v for k, v in generations if k == 'observationId'}
    ticks = {v for k, v in generations if k == 'registrationCompletedTick'}
    if len(observation_ids) > 1 or len(ticks) > 1:
        refusals.append(_refusal(
            'RUNTIME_MIXED_RUNS',
            'this bundle carries more than one run generation; two runs may not be merged '
            'into one observation',
            observationIds=sorted(observation_ids), registrationTicks=sorted(ticks)))

    window = observation_window(raw, identity=identity)
    refusals += window['refusals']
    correlation = correlate_objects(raw, identity=identity,
                                   expectedEntityIds=binding['expectedEntityIds'])
    if correlation.get('status') == 'fail':
        refusals += correlation.get('refusals', [])
    back = return_to_editor(raw, identity=identity, window=window)

    fixture_locked = fixture is not None and fixture.get('live') is False
    why_not_live = []
    if fixture_locked:
        why_not_live.append('the document carries a fixture marker with live=false')
    if fixture is not None and fixture.get('live') is True:
        why_not_live.append('the document is a fixture and may not claim to be live')
    if binding['evidenceMode'] != 'live':
        why_not_live.append('the binding declares evidenceMode=%r' % binding['evidenceMode'])
    if not identity.get('established'):
        why_not_live.append('the run identity is not established')
    if not window.get('usable'):
        why_not_live.append('the observation window is not usable (state=%s)'
                            % window.get('state'))
    if window.get('historicalCount'):
        why_not_live.append('%d record(s) in this bundle predate the window'
                            % window['historicalCount'])
    if correlation.get('status') != 'pass':
        why_not_live.append('no run-scope object correlation (status=%s)'
                            % correlation.get('status'))
    if refusals:
        why_not_live.append('the projection carries refusals: %s'
                            % sorted({r['code'] for r in refusals}))

    # The control record is a separate lane from the observation: a malformed control
    # record is a refusal, but it does not turn a correctly observed sample into a failed
    # observation.  They are reported side by side rather than merged into one verdict.
    s09 = s09_responsibility(raw, identity=identity, window=window, correlation=correlation,
                             returnToEditor=back)
    observation_refusals = list(refusals)
    control_refusals = list(s09['runControl'].get('refusals') or [])
    if control_refusals:
        why_not_live.append('the runtime-control record carries refusals: %s'
                            % sorted({r['code'] for r in control_refusals}))
        refusals = refusals + control_refusals

    derived_live = not why_not_live
    evidence_mode = 'live' if derived_live else 'offline'

    sample_status, sample_reason = 'not-run', None
    if not identity.get('established'):
        sample_status = 'blocked'
        sample_reason = 'no run identity: the observed fields do not add up to one run'
    elif window.get('state') == 'undated':
        sample_status = 'blocked'
        sample_reason = ('the observer window carries no dated record, so nothing can be '
                         'placed in this run')
    elif window.get('clockRollback'):
        sample_status = 'fail'
        sample_reason = 'the window clock is not internally ordered'
    elif window.get('truncated'):
        sample_status = 'fail'
        sample_reason = 'the window lost records and is not a complete observation'
    elif window.get('state') in ('open-window', 'unbounded-window'):
        sample_status = 'blocked'
        sample_reason = window.get('unclosedMeaning')
    elif not window.get('inWindowCount'):
        sample_status = 'blocked'
        sample_reason = window.get('emptyMeaning')
    elif correlation.get('status') == 'blocked':
        sample_status = 'blocked'
        sample_reason = ('no runtime-scope object readback exists, so the sample cannot be '
                         'correlated to this run; the consumer is ready and the producer is '
                         'missing')
    elif correlation.get('status') != 'pass':
        sample_status = 'fail'
        sample_reason = correlation.get('reason')
    else:
        sample_status = 'pass'
        sample_reason = ('one static sample of this round is observed inside a newly '
                         'identified run; scope is deliberately one sample')
    if observation_refusals and sample_status == 'pass':
        sample_status = 'fail'
        sample_reason = 'the projection carries refusals: %s' % sorted({r['code']
                                                                        for r in observation_refusals})

    return {
        'contract': CONTRACT_ID,
        'schemaVersion': SCHEMA_VERSION,
        'controlContract': CONTROL_CONTRACT_ID,
        'caseId': binding['caseId'],
        'evidenceMode': evidence_mode,
        'liveEvidence': {
            'claimed': binding['evidenceMode'] == 'live',
            'derived': derived_live,
            'whyNotLive': why_not_live,
            'note': 'live is derived from the receipt facts (identity established, usable '
                    'window, in-window records, run-scope correlation) and can never be '
                    'asserted by the caller alone. The default is offline.',
        },
        'startsPlaytest': STARTS_PLAYTEST,
        'runIdentity': identity,
        'observationWindow': window,
        'objectCorrelation': correlation,
        'returnToEditor': back,
        'sampleObserved': {
            'status': sample_status,
            'reason': sample_reason,
            'scope': 'at least one visible static sample in a newly identified run; no '
                     'universal behaviour claim',
            'evidenceRef': [{'kind': 'run-identity', 'derivedGenerationId':
                             identity.get('derivedGenerationId')},
                            {'kind': 'observation-window',
                             'inWindowCount': window.get('inWindowCount')},
                            {'kind': 'object-correlation',
                             'matchedEntityIds': correlation.get('matched')}]
            if sample_status == 'pass' else [],
        },
        'gameplay': {
            'status': 'not-run',
            'reason': 'this pack observes one static sample inside a run. It says nothing '
                      'about the game actually playing, and a static sample cannot be read '
                      'as gameplay verification.',
        },
        's09': s09,
        'refusals': refusals,
        'refusalCodes': sorted({r['code'] for r in refusals}),
        'observationRefusals': observation_refusals,
        'controlRefusals': control_refusals,
        'laneSeparation': 'observationRefusals are about this run observation; '
                          'controlRefusals are about the run-control record. A malformed '
                          'control record does not turn a correct observation into a failed '
                          'one, and a correct control record does not promote an unobserved '
                          'sample.',
        'fixture': dict(fixture) if fixture is not None else None,
        'io': {
            'openedAnyFile': False,
            'performedAnyNativeAction': False,
            'startedPlaytest': False,
            'startsPlaytestConstant': STARTS_PLAYTEST,
        },
    }


# --------------------------------------------------------------------------- #
# frozen interfaces (data only; nothing here executes)
# --------------------------------------------------------------------------- #

def manifest_template(caseId: str, *, expectedLevelId=AUTHORIZED_TARGET_LEVEL_ID):
    """The frozen ``runtime-control/1`` and manifest shapes, as data.

    DS-02 implements the control record against this.  There is no start/stop command field
    that can carry a value: both are pinned to ``None`` here and refused if non-null when a
    record is read.
    """
    return {
        'manifestContract': MANIFEST_CONTRACT_ID,
        'controlContract': CONTROL_CONTRACT_ID,
        'binding': {
            'caseId': caseId,
            'expectedLevelId': expectedLevelId,
            'expectedGameSession': {'pid': None, 'tid': None, 'processCreation': None,
                                    'image': None},
            'expectedEditorSession': {'pid': None, 'image': None, 'creationFileTime': None},
            'expectedRunGeneration': None,
            'expectedEntityIds': [],
            'sourceSha256': None,
            'evidenceMode': 'offline',
        },
        'runControl': {
            'contract': CONTROL_CONTRACT_ID,
            'caseId': caseId,
            'startStopMode': 'manual',
            'startedUtc': None,
            'stoppedUtc': None,
            'triggeredBy': 'human-ui',
            'startRequestId': None,
            'stopRequestId': None,
            'gameSession': {'pid': None, 'tid': None, 'processCreation': None, 'image': None},
            'levelId': expectedLevelId,
            'startCommand': None,
            'stopCommand': None,
            'startsPlaytest': False,
        },
        'note': 'startCommand and stopCommand are null by contract. A non-null value is '
                'refused with CONTROL_COMMAND_NOT_REPRESENTABLE. This is a measured '
                'negative, not a placeholder: DS-02 disproved a programmable start/stop '
                'across ten surfaces (' + DS02_EVIDENCE['adjudicator'] + ', sha256 '
                + DS02_EVIDENCE['adjudicatorSha256'] + '), so there is no automated '
                'producer this pack could wait for and none that it may invent.',
        'findingKind': DS02_EVIDENCE['findingKind'],
        'startStopModeMeaning': 'manual means a human pressed the button; automated is '
                                'unreachable until a programmable entry is measured to exist.',
    }


# --------------------------------------------------------------------------- #
# command-line shell -- the ONLY file I/O in this module
# --------------------------------------------------------------------------- #

def _manifest_error(code, message, **detail):
    return ObservationError(code, message, **detail)


def main(argv=None):  # pragma: no cover - exercised by the test as a subprocess-free call
    """Decode raw copies into one projection.  Never touches a game, helper or queue.

    The shell reads the manifest and the documents that manifest names, and writes exactly
    one file.  It refuses to overwrite, refuses an output inside any input directory, and
    refuses a manifest that names an execution-layer knob.

    Exit codes follow the project convention: 0 accepted, 2 a named refusal (the message
    goes to stderr), 1 anything unexpected.
    """
    import sys

    try:
        return _decode(argv)
    except ObservationError as refusal:
        sys.stderr.write('refused: %s\n' % json.dumps(refusal.as_dict(),
                                                      ensure_ascii=False, sort_keys=True))
        return 2


def _decode(argv):
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(prog='python -B -m backend.runtime_observation')
    parser.add_argument('--evidence-manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--task-run-root', default=None,
                        help='when given, --output must be inside it')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)

    manifest_path = pathlib.Path(args.evidence_manifest).resolve()
    output_path = pathlib.Path(args.output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise _manifest_error('MANIFEST_INVALID', 'the manifest must be a JSON object')
    if manifest.get('manifestContract') != MANIFEST_CONTRACT_ID:
        raise _manifest_error('MANIFEST_INVALID', 'unexpected manifest contract',
                              manifestContract=manifest.get('manifestContract'),
                              expected=MANIFEST_CONTRACT_ID)
    forbidden = sorted(set(manifest) & set(FORBIDDEN_BINDING_FIELDS))
    if forbidden:
        raise _manifest_error('MANIFEST_FORBIDDEN_KEY',
                              'the manifest names execution-layer fields',
                              fields=forbidden)
    documents = manifest.get('documents')
    if not isinstance(documents, dict) or not documents:
        raise _manifest_error('MANIFEST_INVALID', 'the manifest must name its documents')
    inputs = {}
    input_dirs = set()
    for key, value in sorted(documents.items()):
        if not isinstance(value, str):
            raise _manifest_error('MANIFEST_INVALID', 'document paths must be strings',
                                  key=key)
        path = pathlib.Path(value).resolve()
        input_dirs.add(path.parent)
        inputs[key] = json.loads(path.read_text(encoding='utf-8-sig'))

    if output_path.exists():
        raise _manifest_error('OUTPUT_PATH_REFUSED', 'refusing to overwrite an existing file',
                              output=str(output_path))
    if output_path.parent in input_dirs:
        raise _manifest_error('OUTPUT_PATH_REFUSED',
                              'the output may not sit in an input directory',
                              output=str(output_path))
    if args.task_run_root:
        root = pathlib.Path(args.task_run_root).resolve()
        if root not in output_path.parents:
            raise _manifest_error('OUTPUT_PATH_REFUSED',
                                  'the output is outside the declared task run root',
                                  output=str(output_path), taskRunRoot=str(root))

    projection = normalize_runtime_evidence(inputs.get('bundle') or inputs,
                                            manifest['binding'])
    if args.dry_run:
        return 0
    output_path.write_text(json.dumps(projection, ensure_ascii=False, sort_keys=True,
                                      indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
