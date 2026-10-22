"""Assembly of a ``runtime-evidence-bundle`` from raw bridge response copies.

WHY THIS MODULE EXISTS
======================
``backend/runtime_observation.py`` *consumes* a decoded ``runtime-evidence-bundle``.  Until
now nothing in the project *produced* one from the artefacts that actually exist on disk --
the raw request/response files under ``.runtime/editor-bridge/**``.  The consumer therefore
had to be handed a hand-shaped bundle, which is exactly the step where a fabricator would
slip an editor-state list or a self-asserted "live" marker in.

This module is the missing producer.  It maps a named set of *original* artefacts -- each one
a byte-for-byte copy of a bridge response, tagged with the bridge operation that produced it
-- onto the lanes the projection reads, and refuses anything it cannot prove:

* an operation this project never exposed on the bridge      -> ``BUNDLE_PART_OP_UNPROVEN``
* a response offered for the wrong lane                       -> ``BUNDLE_PART_ROLE_MISMATCH``
* a response missing a field the operation is known to emit    -> ``BUNDLE_PART_FIELD_MISSING``
* a response whose ``ok`` is not ``true``                      -> ``BUNDLE_PART_NOT_OK``
* an editor-state catalog offered as runtime objects           -> ``EDIT_STATE_NOT_RUNTIME``
* a runtime-object readback with no generation carrier         -> ``CORRELATION_GENERATION_UNBOUND``
* a control record claiming an automated run                   -> ``BUNDLE_CONTROL_AUTOMATED_UNPROVEN``

WHAT IT CANNOT DO
=================
It has no subprocess, no socket, no helper, no queue, no bridge, no game.  Every field it
writes is copied out of a document the caller supplied; it never mints a timestamp, never
substitutes "now", and never promotes a document.  The one lane it *cannot* fill today is
``runtime-objects``: the declared reader ``runtime-scene-object-readback`` has no
implemented producer anywhere in this project (a repository-wide search for that token
finds only ``backend/runtime_observation.py`` itself), so the lane is refused rather than
improvised.  The lane may only ever be filled by a document whose reader id is one of
``backend.runtime_observation.RUNTIME_OBJECT_SOURCES`` and which carries the run generation.

The operation table below is *measured from the sources*, not invented: the operation names
are the ``[ValidateSet(...)]`` of ``tools/editor-bridge/call-bridge.ps1``, and the required
field sets are read off ``EditorAdapter.cs``'s ``RuntimeEvidence()`` / ``LogObserverEvidence()``
/ ``ExternalAssetEvidence()`` and re-checked against the real receipts kept under
``evidence/originals/``.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from backend import control_source_guard
from backend import runtime_observation as ro

__all__ = (
    'ASSEMBLY_CONTRACT_ID',
    'BUNDLE_CONTRACT_ID',
    'ASSEMBLY_MANIFEST_CONTRACT_ID',
    'EXECUTION_SURFACE',
    'CLI_SURFACE',
    'PROVEN_BRIDGE_OPS',
    'CONTRACT_RECORD_OPS',
    'IDENTITY_RECORDS',
    'EDITOR_STATE_OPS',
    'PART_ROLES',
    'ASSEMBLY_REFUSAL_CODES',
    'POST_RUN_READBACK_SOURCE',
    'RUN_CONTROL_GAP',
    'AssemblyError',
    'assemble_runtime_bundle',
    'main',
)

#: Version of the *assembly* document this module emits (the record of one assembly run).
ASSEMBLY_CONTRACT_ID = 'runtime-bundle-assembly/1'
#: The bundle contract the projection consumes.  Kept equal to
#: ``runtime_observation.input_kind``'s accepted marker so the two halves cannot drift.
BUNDLE_CONTRACT_ID = 'runtime-evidence-bundle'
#: Shape of the on-disk manifest the ``main()`` shell reads.
ASSEMBLY_MANIFEST_CONTRACT_ID = 'runtime-bundle-assembly/manifest/v1'

#: Machine-checkable statement of what this module can reach.  All false, by construction.
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

#: What the command-line shell may open.  It reads response copies and writes one file.
CLI_SURFACE = {
    'reads': ('the manifest named by --assembly-manifest',
              'the documents that manifest names'),
    'writes': ('exactly one file: the path given to --output',),
    'subprocess': False,
    'network': False,
    'game': False,
    'overwritesExistingOutput': False,
    'outputInsideInputDirectory': False,
}

# --------------------------------------------------------------------------- #
# the proven artefact table
# --------------------------------------------------------------------------- #

#: Bridge operations this project actually exposes, with the response fields the Adapter
#: handler is known to emit.  Operation names are the ``call-bridge.ps1`` ValidateSet;
#: field sets are read off the Adapter.  A response missing one of these is not the
#: response it claims to be.
PROVEN_BRIDGE_OPS = {
    'runtime-evidence': (
        'ok', 'observedUtc', 'editorLevelState', 'logModelPresent', 'logRecordCount',
        'scannedRecordLimit', 'ownMarkers', 'markerScanObjects', 'markerScanLimited',
        'playtestVerified', 'notice',
    ),
    'log-observer-evidence': (
        'ok', 'observerTiming', 'levelInitialization', 'observedPackets', 'packetKinds',
        'scenePacketSnapshots', 'ownMarkers', 'observerCleanupError', 'callbackErrors',
        'originalReceiversPreserved', 'observerRegistered', 'playtestVerified', 'notice',
    ),
    'external-asset-evidence': (
        'ok', 'captured', 'snapshots', 'totalEntriesScanned', 'sentToGame', 'scope',
    ),
    'catalog': ('ok',),
}

#: Operations that are *editor state*, not a run observation.  Named here so an editor-state
#: list offered in the runtime-object lane is refused by operation, not by its self-report.
EDITOR_STATE_OPS = ('catalog',)

#: Non-bridge contract records.  ``runtime-control/1`` is DS-02's frozen shape.
CONTRACT_RECORD_OPS = ('runtime-control/1',)

#: Identity documents the assembler copies through verbatim, with only a whitelisted field
#: set.  These are NOT produced by this module and it never claims to have read them: their
#: provenance is recorded as ``caller-supplied`` and the projection applies its own binding.
IDENTITY_RECORDS = {
    'game-session': ('pid', 'tid', 'processCreation', 'image'),
    'editor-session': ('pid', 'image', 'creationFileTime'),
    'level-observation': ('verified', 'levelId', 'source'),
}

#: role -> (accepted kind, accepted op, bundle lane).  A part whose op is not the one the
#: role accepts is refused; a role with an empty accepted set can never be filled today.
PART_ROLES = {
    'observer-evidence': ('bridge-response', 'log-observer-evidence', 'logObserverEvidence'),
    'editor-evidence': ('bridge-response', 'runtime-evidence', 'editorEvidence'),
    'post-run-readback': ('bridge-response', 'runtime-evidence', 'postRunReadback'),
    'external-assets': ('bridge-response', 'external-asset-evidence', 'externalAssets'),
    'editor-catalog': ('bridge-response', 'catalog', 'editorCatalog'),
    'runtime-objects': ('declared-reader', 'runtime-scene-object-readback', 'runtimeObjects'),
    'run-control': ('contract-record', 'runtime-control/1', 'runControl'),
    'game-session': ('identity-record', 'game-session', 'session'),
    'editor-session': ('identity-record', 'editor-session', 'editorSession'),
    'level-observation': ('identity-record', 'level-observation', 'levelObservation'),
}

#: Closed refusal vocabulary of this module.
ASSEMBLY_REFUSAL_CODES = frozenset({
    'ASSEMBLY_MANIFEST_INVALID',
    'BUNDLE_PART_INVALID',
    'BUNDLE_PART_OP_UNPROVEN',
    'BUNDLE_PART_ROLE_MISMATCH',
    'BUNDLE_PART_FIELD_MISSING',
    'BUNDLE_PART_NOT_OK',
    'EDIT_STATE_NOT_RUNTIME',
    'CORRELATION_GENERATION_UNBOUND',
    'RUNTIME_OBJECT_SOURCE_UNSUPPORTED',
    'RUN_IDENTITY_LEVEL_MISMATCH',
    'BUNDLE_CONTROL_AUTOMATED_UNPROVEN',
    'TRIGGER_ACTOR_MISMATCH',
    'CONTROL_COMMAND_NOT_REPRESENTABLE',
    'OUTPUT_PATH_REFUSED',
})

#: The source id a post-run readback must carry.  ``runtime-evidence`` is the only proven op
#: that reads the editor's level state, so it is the only accepted source.  Naming it here
#: lets the reader refuse a readback that came from anywhere else.
POST_RUN_READBACK_SOURCE = 'editor-runtime-evidence-readback'

#: Generation carriers a run-scope readback must carry one of, so a same-level readback from
#: a *previous* run can never be read as this run.  Kept identical to the projection's own
#: carrier set -- see ``backend.runtime_observation``'s correlation code.
GENERATION_CARRIER_FIELDS = ('observationId', 'registrationCompletedTick', 'sequence')

#: The minimal gap to a *programmable* start/stop, as data.  This module does not implement
#: start/stop and does not invent a command name; it records why the lane cannot be closed
#: from the artefacts and what a future pack would have to obtain first.
RUN_CONTROL_GAP = {
    'findingKind': 'measured-negative',
    'runControl': 'RUN_CONTROL_UNAVAILABLE',
    'provenInterfacesSearched': [
        'tools/editor-bridge/call-bridge.ps1 ValidateSet (the full bridge route set)',
        'tools/editor-bridge/ManagedBridge/BridgeServer.cs dispatch table',
        'tools/editor-bridge/Adapter/*.cs (every observer/log entry pins startsPlaytest=false)',
    ],
    'onlyProvenStartStopPath': 'the official editor UI, pressed by a human',
    'minimalMissingInput': (
        'a *named* editor level-state enumeration (or a contrast sample whose states are '
        'recorded: one in edit state, one in a non-edit state inside one bridge scope). The '
        'level-state value is observed only as 3 and 5, in different sessions with no '
        'recorded state for either, so it cannot be named. Without this neither a start/stop '
        'command can be synthesised nor can "the editor is back in edit state" be decided -- '
        'the two gaps share one root cause.'),
    'observedLevelStates': [3, 5],
    'explicitlyNotClaimed': (
        'the game process internals were not ruled out: global-metadata.dat is MHY-encrypted '
        'and a zero-hit scan on that carrier proves nothing (DS-02).'),
    'notImplementedHere': ['start', 'stop', 'playtest', 'a start-playtest command name'],
}


class AssemblyError(RuntimeError):
    """A refusal with a stable code, for manifest/shape violations only.

    Evidence problems -- an unproven operation, an editor-state list in the runtime lane, a
    readback with no generation -- are returned in the assembly document, so a caller cannot
    mistake a refusal for a successful empty assembly.
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


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=str).encode('utf-8')


def _part_digest(document) -> str:
    """The same canonical digest the projection uses for ``binding.sourceSha256``."""
    return hashlib.sha256(_canonical(document)).hexdigest()


def _refusal(code: str, message: str, **detail) -> dict:
    entry = {'code': code, 'message': message}
    if detail:
        entry['detail'] = detail
    return entry


def _missing_fields(document: Mapping, required: Sequence) -> list:
    return sorted(f for f in required if f not in document)


def _whitelist(document: Mapping, fields: Sequence) -> dict:
    return {f: document[f] for f in fields if f in document}


# --------------------------------------------------------------------------- #
# per-lane validation (fail closed)
# --------------------------------------------------------------------------- #

def _check_bridge_response(role, part, refusals):
    """A document claiming a bridge op must carry every field that op is known to emit."""
    document = part.get('document')
    if not isinstance(document, Mapping):
        refusals.append(_refusal('BUNDLE_PART_INVALID', 'a part document must be a JSON object',
                                 role=role, observedType=type(document).__name__))
        return None
    op = part.get('op')
    missing = _missing_fields(document, PROVEN_BRIDGE_OPS[op])
    if missing:
        refusals.append(_refusal(
            'BUNDLE_PART_FIELD_MISSING',
            'the document does not carry every field operation %r is known to emit; it is '
            'not the response it claims to be' % op,
            role=role, op=op, missingFields=missing))
        return None
    if document.get('ok') is not True:
        refusals.append(_refusal(
            'BUNDLE_PART_NOT_OK',
            'the bridge reported the operation as not ok; a failed call is not evidence',
            role=role, op=op, ok=document.get('ok')))
        return None
    return document


def _check_runtime_objects(role, document, refusals):
    """The runtime-object lane is the one lane an editor-state list keeps trying to fill."""
    source = document.get('source')
    if source not in ro.RUNTIME_OBJECT_SOURCES:
        refusals.append(_refusal(
            'RUNTIME_OBJECT_SOURCE_UNSUPPORTED',
            'the readback is not from a declared run-time reader; an editor-state list proves '
            'what the editor holds, never what a run produced',
            role=role, source=source, accepted=list(ro.RUNTIME_OBJECT_SOURCES),
            editStateSources=list(ro.EDIT_STATE_SOURCES)))
        return None
    carriers = {f: document.get(f) for f in GENERATION_CARRIER_FIELDS
                if document.get(f) is not None}
    if not carriers:
        refusals.append(_refusal(
            'CORRELATION_GENERATION_UNBOUND',
            'the readback carries no generation carrier, so a same-level readback from a '
            'previous run of the same level could be read as this run',
            role=role, requiredAny=sorted(GENERATION_CARRIER_FIELDS)))
        return None
    return document


def _check_run_control(role, document, refusals):
    """A control record may not claim an automated run, and may not name a command."""
    if document.get('contract') != 'runtime-control/1':
        refusals.append(_refusal('BUNDLE_PART_INVALID',
                                 'a control record must be runtime-control/1',
                                 role=role, contract=document.get('contract')))
        return None
    for field in ro.FORBIDDEN_CONTROL_FIELDS:
        if document.get(field) is not None:
            refusals.append(_refusal(
                'CONTROL_COMMAND_NOT_REPRESENTABLE',
                'this project has no start/stop playtest command; a record naming one is '
                'refused at assembly rather than forwarded',
                role=role, field=field))
            return None
    # D24.01.03 -- the control-SOURCE decision lives in one shared guard so the assembly
    # half and the projection half cannot drift.  Only the two D24.01.03 codes are acted
    # on here; every other guard refusal is left to the caller's own checks, so no
    # unrelated behaviour changes.  The lane document is returned UNCHANGED: the
    # projection refuses a runtime-control/1 record carrying any field outside
    # CONTROL_FIELDS, so this half must not decorate the record it hands on.
    audit = control_source_guard.audit_control_record(dict(document))
    mapping = {'CONTROL_AUTOMATED_UNPROVEN': 'BUNDLE_CONTROL_AUTOMATED_UNPROVEN',
               'TRIGGER_ACTOR_MISMATCH': 'TRIGGER_ACTOR_MISMATCH'}
    for refusal in audit['refusals']:
        code = mapping.get(refusal['code'])
        if code is None:
            continue
        detail = dict(refusal.get('detail') or {})
        if code == 'BUNDLE_CONTROL_AUTOMATED_UNPROVEN':
            detail['measured'] = ro.DS02_EVIDENCE['verdict']
        refusals.append(_refusal(code, refusal['message'], role=role, **detail))
        return None
    return document


def _check_identity(role, document, refusals):
    fields = IDENTITY_RECORDS[role]
    if not any(document.get(f) is not None for f in fields):
        refusals.append(_refusal('BUNDLE_PART_INVALID',
                                 'an identity record carries none of its fields',
                                 role=role, allowed=sorted(fields)))
        return None
    return _whitelist(document, fields)


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #

def _provenance(part, kind, op, document):
    entry = {'kind': kind, 'op': op, 'sha256': _part_digest(document)}
    if kind == 'declared-reader':
        # The lane exists in the contract; no producer implements it in this project.
        entry['producerImplemented'] = False
    elif kind == 'identity-record':
        entry['source'] = 'caller-supplied'
    else:
        entry['source'] = 'bridge-response-copy'
    return entry


def _post_run_readback(document, level_source):
    """A readback from the proven ``runtime-evidence`` op, plus a level from another part.

    The response of ``runtime-evidence`` carries no level id (verified against the real
    receipt under ``evidence/originals/``), so a readback can only be bound to a level when
    a *second* supplied part -- an observer-evidence copy -- provides one.  The level is
    copied from that part's retained 7.1 payload; it is never invented here.
    """
    readback = {
        'observedUtc': document.get('observedUtc'),
        'editorLevelState': document.get('editorLevelState'),
        'source': POST_RUN_READBACK_SOURCE,
        'independentReadback': True,
        'rawOp': 'runtime-evidence',
    }
    if level_source is not None:
        level_init = level_source.get('levelInitialization')
        if isinstance(level_init, Mapping):
            for field in ('currentLevelId', 'baselineLevelId'):
                if _is_int(level_init.get(field)):
                    readback['levelId'] = level_init[field]
                    readback['levelIdSource'] = 'log-observer-evidence.levelInitialization.%s' % field
                    break
    return readback


def assemble_runtime_bundle(parts, *, caseId=None):
    """Assemble a ``runtime-evidence-bundle`` from named original artefacts.

    ``parts`` maps a role from ``PART_ROLES`` to ``{'kind': ..., 'op': ..., 'document': ...}``.
    Returns an *assembly document*: ``{'contract','assembled','bundle','refusals','provenance'}``.
    The bundle is emitted only when there are no refusals, so a partial assembly can never be
    fed to the projection as if it were complete.
    """
    refusals, provenance = [], {}
    if not isinstance(parts, Mapping):
        refusals.append(_refusal('BUNDLE_PART_INVALID', 'parts must be a JSON object',
                                 observedType=type(parts).__name__))
        return {'contract': ASSEMBLY_CONTRACT_ID, 'assembled': False, 'bundle': None,
                'caseId': caseId, 'provenance': provenance, 'refusals': refusals}

    lanes, level_source = {}, None
    for role in sorted(parts):
        part = parts[role]
        if role not in PART_ROLES:
            refusals.append(_refusal('BUNDLE_PART_INVALID',
                                     'unknown assembly role', role=role,
                                     allowed=sorted(PART_ROLES)))
            continue
        if not isinstance(part, Mapping):
            refusals.append(_refusal('BUNDLE_PART_INVALID', 'a part must be a JSON object',
                                     role=role, observedType=type(part).__name__))
            continue
        kind, op, lane = PART_ROLES[role]
        if part.get('kind') != kind or part.get('op') != op:
            # An editor-state operation offered for a runtime lane is refused by name, so the
            # refusal says *what* it was rather than "wrong op".
            if role == 'runtime-objects' and part.get('op') in EDITOR_STATE_OPS:
                refusals.append(_refusal(
                    'EDIT_STATE_NOT_RUNTIME',
                    'an editor-state catalog was offered as a run observation; the editor '
                    'lists what it holds now and says nothing about what this run created',
                    role=role, op=part.get('op')))
                continue
            known = part.get('op') in PROVEN_BRIDGE_OPS or \
                part.get('op') in CONTRACT_RECORD_OPS or \
                part.get('op') in IDENTITY_RECORDS or \
                part.get('op') == PART_ROLES['runtime-objects'][1]
            refusals.append(_refusal(
                'BUNDLE_PART_ROLE_MISMATCH' if known else 'BUNDLE_PART_OP_UNPROVEN',
                'the operation is not the one this role accepts' if known else
                'this project exposes no such operation; a document cannot name its own '
                'provenance',
                role=role, op=part.get('op'), acceptedKind=kind, acceptedOp=op))
            continue

        if kind == 'bridge-response':
            document = _check_bridge_response(role, part, refusals)
            if document is None:
                continue
            if role == 'observer-evidence':
                lanes[lane] = document
                level_init = document.get('levelInitialization')
                if isinstance(level_init, Mapping):
                    lanes['levelInitialization'] = level_init
                    level_source = document
            elif role == 'editor-evidence':
                lanes[lane] = document
            elif role == 'post-run-readback':
                level_source = level_source or None
                lanes[lane] = _post_run_readback(document, level_source)
                if 'levelId' not in lanes[lane]:
                    # Kept visible: the readback is real but not level-bound, and the reader
                    # will refuse it rather than guess a level.
                    lanes[lane]['levelBound'] = False
            else:
                lanes[lane] = document
        elif kind == 'declared-reader':
            document = _check_runtime_objects(role, part.get('document'), refusals)
            if document is None:
                continue
            lanes[lane] = document
        elif kind == 'contract-record':
            document = _check_run_control(role, part.get('document'), refusals)
            if document is None:
                continue
            lanes[lane] = document
        else:  # identity-record
            document = _check_identity(role, part.get('document'), refusals)
            if document is None:
                continue
            lanes[lane] = document
        provenance[role] = _provenance(part, kind, op, part.get('document'))

    # A post-run readback named before its level source was seen still gets its level.
    if lanes.get('postRunReadback') is not None and 'levelId' not in lanes['postRunReadback'] \
            and level_source is not None:
        lanes['postRunReadback'] = _post_run_readback(
            {'observedUtc': lanes['postRunReadback'].get('observedUtc'),
             'editorLevelState': lanes['postRunReadback'].get('editorLevelState')},
            level_source)

    assembled = not refusals
    bundle = None
    if assembled:
        bundle = {'kind': BUNDLE_CONTRACT_ID, 'schemaVersion': ro.SCHEMA_VERSION}
        if _is_str(caseId):
            bundle['caseId'] = caseId.strip()
        bundle.update(lanes)
        bundle['assembledBy'] = 'backend/runtime_bundle.py'
        bundle['provenance'] = dict(provenance)
        bundle['assemblyRefusals'] = []
    return {
        'contract': ASSEMBLY_CONTRACT_ID,
        'assembled': assembled,
        'caseId': caseId,
        'bundle': bundle,
        'provenance': dict(provenance),
        'refusals': refusals,
    }


def bundle_digest(bundle) -> str:
    """The digest a caller binds ``binding.sourceSha256`` to for this exact bundle."""
    return _part_digest(bundle)


# --------------------------------------------------------------------------- #
# command-line shell -- the ONLY file I/O in this module
# --------------------------------------------------------------------------- #

def main(argv=None):  # pragma: no cover - exercised by the test as a subprocess-free call
    """Assemble one bundle from a manifest of response copies.  Never reaches a game.

    Exit codes follow the project convention: 0 assembled and written, 2 a named refusal
    (the message goes to stderr), 1 anything unexpected.
    """
    import sys
    try:
        return _assemble(argv)
    except AssemblyError as refusal:
        sys.stderr.write('refused: %s\n' % json.dumps(refusal.as_dict(),
                                                      ensure_ascii=False, sort_keys=True))
        return 2
    except ro.ObservationError as refusal:  # the projection's own contract refusals
        sys.stderr.write('refused: %s\n' % json.dumps(refusal.as_dict(),
                                                      ensure_ascii=False, sort_keys=True))
        return 2


def _assemble(argv):
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(prog='python -B -m backend.runtime_bundle')
    parser.add_argument('--assembly-manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--task-run-root', default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)

    manifest_path = pathlib.Path(args.assembly_manifest).resolve()
    output_path = pathlib.Path(args.output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if not isinstance(manifest, dict):
        raise AssemblyError('ASSEMBLY_MANIFEST_INVALID', 'the manifest must be a JSON object')
    if manifest.get('manifestContract') != ASSEMBLY_MANIFEST_CONTRACT_ID:
        raise AssemblyError('ASSEMBLY_MANIFEST_INVALID', 'unexpected manifest contract',
                            manifestContract=manifest.get('manifestContract'),
                            expected=ASSEMBLY_MANIFEST_CONTRACT_ID)
    forbidden = sorted(set(manifest) & set(ro.FORBIDDEN_BINDING_FIELDS))
    if forbidden:
        raise AssemblyError('ASSEMBLY_MANIFEST_INVALID',
                            'the manifest names execution-layer fields', fields=forbidden)
    declared = manifest.get('parts')
    if not isinstance(declared, dict) or not declared:
        raise AssemblyError('ASSEMBLY_MANIFEST_INVALID', 'the manifest must name its parts')

    parts, input_dirs = {}, set()
    for role, spec in sorted(declared.items()):
        if not isinstance(spec, dict) or not _is_str(spec.get('path')):
            raise AssemblyError('ASSEMBLY_MANIFEST_INVALID',
                                'each part must name a path', role=role)
        path = pathlib.Path(spec['path']).resolve()
        input_dirs.add(path.parent)
        parts[role] = {'kind': spec.get('kind'), 'op': spec.get('op'),
                       'document': json.loads(path.read_text(encoding='utf-8-sig'))}

    if output_path.exists():
        raise AssemblyError('OUTPUT_PATH_REFUSED', 'refusing to overwrite an existing file',
                            output=str(output_path))
    if output_path.parent in input_dirs:
        raise AssemblyError('OUTPUT_PATH_REFUSED', 'the output may not sit in an input directory',
                            output=str(output_path))
    if args.task_run_root:
        root = pathlib.Path(args.task_run_root).resolve()
        if root not in output_path.parents:
            raise AssemblyError('OUTPUT_PATH_REFUSED',
                                'the output is outside the declared task run root',
                                output=str(output_path), taskRunRoot=str(root))

    assembly = assemble_runtime_bundle(parts, caseId=manifest.get('caseId'))
    if not assembly['assembled']:
        raise AssemblyError(assembly['refusals'][0]['code'],
                            'assembly refused: %s' % assembly['refusals'][0]['message'],
                            refusals=assembly['refusals'])
    if args.dry_run:
        return 0
    output_path.write_text(json.dumps(assembly['bundle'], ensure_ascii=False, sort_keys=True,
                                      indent=1, allow_nan=False) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
