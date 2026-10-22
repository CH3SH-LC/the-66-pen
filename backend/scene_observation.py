"""Structured, read-only projection over one captured scene receipt.

NARROW CONTRACT
===============
This module is a *pure function library* over an already-decoded observation document
that the execution layer hands in as a mapping.  It imports nothing but the standard
library's ``json``/``hashlib``/``base64``/``math`` and it opens nothing.  There is no
parameter anywhere in this file that names a command, a queue, a helper, a process, a
path to execute, or a script/plan/executable to forward, and there is no code path that
could carry one: the whole module cannot reach a game, an editor, a bridge, a subprocess
or the filesystem.  ``EXECUTION_SURFACE`` below states that in machine-checkable form and
``backend/test_scene_observation.py`` enforces it by scanning this file.

What it therefore CANNOT do, and reports as unsupported rather than guessing:

* decode the raw probe hex.  That is owned by the pinned
  ``tools/game-executor/build_readonly_profile.py`` decoder (it has to zero the
  level-observation field before decoding and extend the status/flag tables, so a second
  implementation here would be a divergent copy of a pinned tool).  A raw probe record is
  refused with ``INPUT_KIND_UNSUPPORTED``.
* read a snapshot file, run a probe, or fetch a fresh entity set.  Input is the decoded
  document only; where no document was supplied, every answer here is ``unavailable``.

WHAT IT GUARANTEES
==================
Absence of evidence is never upgraded to evidence of absence.

* ``readable`` is false when the receipt's own status says the read did not produce rows
  at all; a diff over such a receipt returns ``state="unknown"`` with
  ``added``/``removed`` set to ``None`` -- never an empty list, and never "everything was
  removed".  A read that stopped short (``limit_exceeded``, ``partial_entities``) stays
  readable and incomplete, and its diff is reported with ``authoritative: false``.
* ``complete`` is true only when the receipt itself proves a whole set (required snapshot
  flags, no truncation, no read failure, no rejected entities, and
  ``captured == valid == len(entities)``, the same conjunction the native read-only
  acceptance uses).  ``trusted`` is narrower: it is about identity alone.
* Refusal codes are surfaced verbatim in ``refusals``; nothing is swallowed and nothing
  is de-duplicated away (a duplicated entity id refuses the set's trust instead of
  collapsing into one row).
* Every attribute carries ``source``/``sourceKind``/``observedAt``/``derived``, and each
  attribute keeps its OWN observation time, so geometry taken from a formal-save parse can
  never be read as an edit-time native value.
* A null position stays ``unknown``.  It is never reported as ``0``, and a value that
  arrives without its read flag is refused outright.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping, Sequence

__all__ = (
    'SCHEMA_VERSION',
    'CONTRACT_ID',
    'SUPPORTED_INPUTS',
    'EXECUTION_SURFACE',
    'STATUS_NAMES',
    'SNAPSHOT_FLAGS',
    'ENTITY_FLAGS',
    'REQUIRED_SNAPSHOT_FLAGS',
    'IDENTITY_FLAGS',
    'DECLARED_ATTRIBUTES',
    'UNSOURCED_ATTRIBUTES',
    'SUBSYSTEM_NAMES',
    'SUBSYSTEM_STATUS_NAMES',
    'ObservationError',
    'input_kind',
    'project_snapshot',
    'get_entity',
    'page_entities',
    'diff_snapshots',
)

#: Version of the projection document this module emits and consumes.
SCHEMA_VERSION = 1
#: Stable contract id, carried by every projection so a consumer cannot mix versions.
CONTRACT_ID = 'scene-observation/projection/v1'

#: Input kinds this module actually implements.  Nothing else is accepted.
SUPPORTED_INPUTS = ('decoded-context-document',)

#: Machine-checkable statement of what this module can reach.  All false, by construction.
EXECUTION_SURFACE = {
    'subprocess': False,
    'shell': False,
    'filesystem': False,
    'network': False,
    'processControl': False,
    'arbitraryCommandParameter': False,
    'forwardableScriptOrPlan': False,
}

#: Status names of the native snapshot structure.  0..8 mirror
#: tools/game-executor/decode_context_snapshot.py; 9 and 10 are added by
#: build_readonly_profile.load_decoder before it decodes.
STATUS_NAMES = {
    0: 'ok', 1: 'build_mismatch', 2: 'module_unavailable', 3: 'unreadable',
    4: 'invalid_structure', 5: 'limit_exceeded', 6: 'context_not_found', 7: 'unstable',
    8: 'partial_entities', 9: 'stack_mismatch', 10: 'hotfix_active',
}

#: Snapshot flag bits.  1..128 mirror the pinned decoder; 256..1024 are added by
#: build_readonly_profile.load_decoder.  Measured against the real receipt
#: .runtime/game-executor/scene-cli/inspect/20260929-153108-edb0fcdf3e/before-context.json
#: (flags value 1951 = these nine names, in this order).
SNAPSHOT_FLAGS = {
    1: 'build_verified', 2: 'origin_read', 4: 'contexts_complete', 8: 'entities_complete',
    16: 'structure_rechecked', 32: 'entities_truncated', 64: 'entity_read_failure',
    128: 'stack_captured', 256: 'stack_verified', 512: 'hotfix_default_confirmed',
    1024: 'level_observed',
}

#: Per-entity flag bits (pinned decoder ENTITY_FLAGS).
ENTITY_FLAGS = {
    1: 'id_read', 2: 'config_id_read', 4: 'context_match', 8: 'key_match',
    16: 'position_read', 32: 'config_null', 64: 'context_read',
}

#: The snapshot flag conjunction asserted by the native read-only acceptance
#: (build_readonly_profile.validate_receipt: ``f & 927 == 927``).
REQUIRED_SNAPSHOT_FLAGS = 927
#: Bits that mean "this entity set is not provably whole".
TRUNCATION_FLAG = 32
READ_FAILURE_FLAG = 64
#: Statuses under which the reader actually produced entity rows.  ``limit_exceeded``
#: (5) and ``partial_entities`` (8) are reads that stopped short -- they are readable and
#: incomplete, which is a different thing from a read that never happened (1,2,3,4,6,7,
#: 9,10).  Only status 0 can ever be complete.
READABLE_STATUSES = (0, 5, 8)
#: Bits required on every entity -- ``row['flags']['value'] & 79 == 79`` in the same
#: acceptance, i.e. owner/config/context/key were all read and matched.
IDENTITY_FLAGS = 79
POSITION_FLAG = 16

#: Bits that make the entity set's identity unusable if missing.
TRUST_REFUSAL_CODES = frozenset({
    'DUPLICATE_ENTITY_IDENTITY',
    'DUPLICATE_DICTIONARY_KEY',
    'ENTITY_KEY_ID_MISMATCH',
    'ENTITY_IDENTITY_UNREAD',
    'ENTITY_ID_INVALID',
    'ENTITY_OWNER_CONFIG_CONTEXT_UNVERIFIED',
    'FLAG_NAMES_MISMATCH',
})

#: Refusals that stop the entity set from being *proven complete* even when its identity
#: is trustworthy.  An attribute-level conflict (``ATTRIBUTE_SOURCE_CONFLICT``) is
#: deliberately NOT here: one contested attribute does not make the set incomplete, and
#: the conflict is surfaced under both ``conflicts`` and ``refusals`` plus a ``contested``
#: marker on that attribute's provenance.
INVALIDATING_REFUSAL_CODES = TRUST_REFUSAL_CODES | frozenset({
    'SNAPSHOT_STATUS_NOT_OK',
    'DOCUMENT_STATUS_NAME_MISMATCH',
    'ENTITIES_TRUNCATED',
    'ENTITY_READ_FAILURE',
    'ENTITY_REJECTED_BY_READER',
    'ENTITY_SET_SHORT_OF_VALID_ENTRIES',
    'ENTITY_SET_COUNT_MISMATCH',
    'SNAPSHOT_REQUIRED_FLAGS_MISSING',
    'NATIVE_ACCEPTANCE_REJECTED',
})

#: Attributes with no verified source at all.  These are reported as unknown for every
#: entity and listed once at snapshot level as ``unsupportedAttributes``.  They are
#: deliberately not filled by scanning memory, guessing a reflection path or reusing a
#: create-request input as if it were a read.
UNSOURCED_ATTRIBUTES = {
    'rotation': 'no rotation field exists in the native entity record and no reader is '
                'implemented; a value written by a create request is an input, not a read',
    'scale': 'no scale field exists in the native entity record and no reader is '
             'implemented; a value written by a create request is an input, not a read',
    'name': 'the native entity record carries no name; entity names live in the editor '
            'and in the formal save, neither of which this layer reads',
    'graphBindings': 'graph/node binding is not present in the entity record and no '
                     'verified reader exists for it',
    'customVariables': 'per-entity custom variables are not present in the entity record '
                       'and no verified reader exists for them',
}

#: Attribute names this projection talks about: the closed vocabulary, defined after
#: UNSOURCED_ATTRIBUTES because it includes them.  No attribute outside this tuple is
#: ever emitted, so the surface cannot grow by accident, and the unsourced ones are part
#: of it precisely so that they are reported as unknown for every entity rather than
#: being absent (an absent field reads like "not applicable").
DECLARED_ATTRIBUTES = (
    'entityId',
    'templateId',
    'configId',
    'dictionaryKey',
    'ownerRef',
    'configRef',
    'contextRef',
    'position',
    'label',
) + tuple(UNSOURCED_ATTRIBUTES)

#: Closed set of subsystems this projection can report.  Others are recorded as
#: unrecognised rather than silently dropped.
SUBSYSTEM_NAMES = ('lifecycleType', 'schedulerCoroutines')
#: Status names of the subsystem decoders (tools/game-executor/native_lifecycle_type.py
#: and native_scheduler_coroutines.py).  Only 'ok' is a successful read.
SUBSYSTEM_STATUS_NAMES = {
    'lifecycleType': ('ok', 'baseline_refused', 'anchor_mismatch', 'unreadable',
                      'structure_invalid', 'limit', 'unstable', 'hotfix_active',
                      'not_initialized', 'function_not_found', 'ambiguous_function'),
    'schedulerCoroutines': ('ok', 'baseline_refused', 'anchor_mismatch', 'unreadable',
                            'structure_invalid', 'limit', 'unstable', 'hotfix_active',
                            'identity_or_initialization_changed'),
}

DEFAULT_PAGE_ITEMS = 32
MAX_PAGE_ITEMS = 200
DEFAULT_PAGE_BYTES = 16384
MAX_PAGE_BYTES = 262144
MAX_DIFF_CHANGES = 200
MAX_LABEL_CHARS = 200

#: Bound on the cursor's own integrity, NOT a secret: it detects an edited cursor, it
#: does not authenticate one against a caller who has read this file.
CURSOR_PEPPER = 'scene-observation-cursor-pepper/v1'
CURSOR_KEYS = ('v', 'snapshotId', 'contentDigest', 'levelId', 'offset', 'check')

COUNT_KEYS = (
    'peTimestamp', 'peImageSize', 'activeKey', 'contextCapacity', 'contextValidEntries',
    'contextMatchingEntries', 'entityCapacity', 'entityValidEntries', 'entityCaptured',
    'entityRejected', 'bytesRead', 'readCalls', 'stackCount', 'entityVersionBefore',
    'entityVersionAfter', 'lastReadStatus',
)
#: Counts bound into the snapshot identity and the content digest.
BOUND_COUNT_KEYS = ('entityCapacity', 'entityValidEntries', 'entityCaptured', 'entityRejected')
#: Document keys this projection understands.  Anything else is reported in
#: ``unrecognizedDocumentKeys`` instead of being quietly ignored.
RECOGNIZED_DOCUMENT_KEYS = (
    'structureSize', 'version', 'status', 'flags', 'pointers', 'counts', 'origin', 'stack',
    'entities', 'lastReadStatusName', 'levelObservation', 'source', 'limits',
    '_fixture', 'acceptance', 'subsystems', 'geometry', 'labels',
)
#: Document keys without which there is nothing to project.
REQUIRED_DOCUMENT_KEYS = ('version', 'status', 'flags', 'counts', 'entities', 'levelObservation')

_RECEIPT_FIELDS = ('snapshotHex', 'beforeSnapshotHex', 'afterSnapshotHex')


class ObservationError(RuntimeError):
    """A refusal with a stable code.

    Raised for contract/shape violations only -- a document this layer cannot trust to
    describe, a page limit above the maximum, a cursor that does not belong to this
    snapshot.  Evidence problems (truncation, a read failure, duplicate identities) are
    NOT exceptions: they are reported in the returned document so a caller can never
    mistake a refusal for a successful empty read.
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
                      allow_nan=False).encode('utf-8')


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(value)


def _flag_names(value: int, table) -> list:
    return [name for bit, name in sorted(table.items()) if value & bit]


def _unknown_bits(value: int, table) -> int:
    return value & ~sum(table)


def _strict_equal(left, right) -> bool:
    """Type-aware equality: booleans are not numbers, ``None`` is not anything.

    ``1`` and ``1.0`` do compare equal -- a float32 read of an integral value is the same
    coordinate -- but ``None`` never equals a number, which is what keeps a null position
    from collapsing into ``0``.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if _is_number(left) and _is_number(right):
        return left == right
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def _items_bytes(items: Sequence) -> int:
    """UTF-8 bytes of the canonical JSON of an items array.

    Byte accounting is on the ENCODED form, so a Chinese label costs its real bytes and
    not its character count.  The page envelope is excluded; it is bounded by the page
    limits and carries no entity content.
    """
    return len(json.dumps(list(items), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8'))


def input_kind(document) -> str:
    """Classify an input without trusting it: see ``SUPPORTED_INPUTS``."""
    if not isinstance(document, Mapping):
        return 'not-a-mapping'
    if 'entities' in document and 'counts' in document and 'status' in document:
        return 'decoded-context-document'
    if any(field in document for field in _RECEIPT_FIELDS):
        return 'raw-probe-record'
    return 'unknown'


# --------------------------------------------------------------------------- #
# document validation
# --------------------------------------------------------------------------- #

def _require_mapping(value, code, what):
    if not isinstance(value, Mapping):
        raise ObservationError(code, '%s must be a JSON object' % what,
                               observedType=type(value).__name__)
    return value


def _require_int(mapping, key, code, what, *, minimum=None):
    value = mapping.get(key)
    if not _is_int(value):
        raise ObservationError(code, '%s.%s must be an integer' % (what, key),
                               observedType=type(value).__name__)
    if minimum is not None and value < minimum:
        raise ObservationError(code, '%s.%s must be >= %d' % (what, key, minimum), value=value)
    return value


def _validate_identity(identity):
    identity = _require_mapping(identity, 'IDENTITY_NOT_A_MAPPING', 'identity')
    handle = identity.get('targetHandle')
    if not isinstance(handle, str) or not handle.strip():
        raise ObservationError(
            'IDENTITY_HANDLE_REQUIRED',
            'targetHandle must be the opaque handle the read was performed under; this '
            'layer never mints a handle and never accepts a level id as one')
    level_id = identity.get('levelId')
    if not _is_int(level_id) or level_id <= 0:
        raise ObservationError(
            'IDENTITY_LEVEL_REQUIRED', 'identity.levelId must be a positive integer')
    observed_at = identity.get('observedAt')
    if observed_at is not None and (not isinstance(observed_at, str) or not observed_at):
        raise ObservationError('IDENTITY_OBSERVED_AT_INVALID',
                               'identity.observedAt must be a non-empty string or null')
    receipt_sha = identity.get('receiptSha256')
    if receipt_sha is not None:
        if not isinstance(receipt_sha, str) or len(receipt_sha) != 64 or \
                any(c not in '0123456789abcdef' for c in receipt_sha.lower()):
            raise ObservationError('IDENTITY_RECEIPT_SHA_INVALID',
                                   'identity.receiptSha256 must be 64 lowercase hex characters')
        receipt_sha = receipt_sha.lower()
    result = dict(identity)
    result.update({
        'targetHandle': handle,
        'levelId': level_id,
        'observedAt': observed_at,
        'observedAtSource': 'execution-layer' if observed_at else 'unavailable',
        'receiptPath': identity.get('receiptPath'),
        'receiptSha256': receipt_sha,
        'unrecognizedIdentityKeys': sorted(set(identity) - {
            'targetHandle', 'levelId', 'observedAt', 'receiptPath', 'receiptSha256',
            'sessionPid', 'sessionCreation', 'sessionSource', 'kind'}),
    })
    return result


def _validate_document(document):
    kind = input_kind(document)
    if kind == 'raw-probe-record':
        raise ObservationError(
            'INPUT_KIND_UNSUPPORTED',
            'a raw probe record cannot be projected here; decoding its snapshot hex is '
            'owned by tools/game-executor/build_readonly_profile.py, which this layer '
            'deliberately does not reimplement',
            inputKind=kind, supportedInputs=list(SUPPORTED_INPUTS))
    if kind != 'decoded-context-document':
        raise ObservationError(
            'DOCUMENT_SHAPE_UNSUPPORTED',
            'input is not a decoded context document', inputKind=kind,
            supportedInputs=list(SUPPORTED_INPUTS))
    missing = [key for key in REQUIRED_DOCUMENT_KEYS if key not in document]
    if missing:
        raise ObservationError('DOCUMENT_SHAPE_UNSUPPORTED',
                               'decoded context document is missing required keys',
                               missing=missing)
    version = document.get('version')
    if not _is_int(version) or version not in (1, 2):
        raise ObservationError('DOCUMENT_VERSION_UNSUPPORTED',
                               'document version is not the one this layer projects',
                               version=version, supportedVersions=[1, 2])
    if version == 2 and document.get('structureSize') != 262584:
        raise ObservationError('DOCUMENT_VERSION_UNSUPPORTED',
                               'v2 large snapshots must carry their exact structure size',
                               version=version, structureSize=document.get('structureSize'))
    return kind


def _project_flags(raw, table, code_prefix, what):
    raw = _require_mapping(raw, code_prefix + '_FLAGS_UNSUPPORTED', what + '.flags')
    value = _require_int(raw, 'value', code_prefix + '_FLAGS_UNSUPPORTED', what + '.flags',
                         minimum=0)
    unknown = _unknown_bits(value, table)
    if unknown:
        raise ObservationError(
            code_prefix + '_FLAGS_UNKNOWN_BITS',
            '%s.flags carries bits this layer cannot name; refusing to project a set whose '
            'semantics are partly unknown' % what, unknownBits=hex(unknown), value=value)
    names = _flag_names(value, table)
    declared = raw.get('names')
    mismatch = None
    if declared is not None:
        declared = list(declared) if isinstance(declared, (list, tuple)) else None
        if declared != names:
            mismatch = {'declared': declared, 'recomputed': names}
    return {'value': value, 'names': names}, mismatch


def _project_position(entry, flags_value, index):
    position = entry.get('position')
    if flags_value & POSITION_FLAG:
        if not (isinstance(position, (list, tuple)) and len(position) == 3 and
                all(_is_number(v) for v in position)):
            raise ObservationError(
                'DOCUMENT_ENTITY_POSITION_INVALID',
                'position_read is set but the position is not three finite numbers',
                index=index, position=position)
        return [float(v) for v in position]
    if position is not None:
        raise ObservationError(
            'DOCUMENT_ENTITY_POSITION_UNSOURCED',
            'an entity carries a position without the position_read flag; a value that no '
            'flag claims was read is not a read',
            index=index, position=position)
    return None


def _project_entity(entry, index, refusals):
    entry = _require_mapping(entry, 'DOCUMENT_ENTITY_SHAPE_UNSUPPORTED',
                             'entities[%d]' % index)
    for key in ('index', 'flags', 'dictionaryKey', 'owner', 'config', 'context'):
        if key not in entry:
            raise ObservationError('DOCUMENT_ENTITY_SHAPE_UNSUPPORTED',
                                   'entity record is missing a required field',
                                   index=index, missing=key)
    declared_index = _require_int(entry, 'index', 'DOCUMENT_ENTITY_SHAPE_UNSUPPORTED',
                                  'entities[%d]' % index, minimum=0)
    if declared_index != index:
        raise ObservationError(
            'DOCUMENT_ENTITY_INDEX_MISMATCH',
            'entity record is not at the index it declares; the array cannot be mapped to '
            'native row order', declared=declared_index, position=index)
    flags, flag_mismatch = _project_flags(entry.get('flags'), ENTITY_FLAGS, 'DOCUMENT_ENTITY',
                                          'entities[%d]' % index)
    if flag_mismatch:
        refusals.append({'code': 'FLAG_NAMES_MISMATCH', 'component': 'entity',
                         'detail': {'index': index, **flag_mismatch}})
    fv = flags['value']
    key = _require_int(entry, 'dictionaryKey', 'DOCUMENT_ENTITY_SHAPE_UNSUPPORTED',
                       'entities[%d]' % index, minimum=0)
    position = _project_position(entry, fv, index)

    id_read = bool(fv & 1)
    config_read = bool(fv & 2)
    entity_id = entry.get('id') if id_read else None
    config_id = entry.get('configId') if config_read else None
    if id_read and (not _is_int(entity_id) or entity_id <= 0):
        raise ObservationError('DOCUMENT_ENTITY_ID_INVALID',
                               'id_read is set but id is not a positive integer',
                               index=index, id=entity_id)
    if config_read and (not _is_int(config_id) or config_id < 0):
        raise ObservationError('DOCUMENT_ENTITY_ID_INVALID',
                               'config_id_read is set but configId is not a non-negative '
                               'integer', index=index, configId=config_id)

    if not id_read:
        refusals.append({'code': 'ENTITY_IDENTITY_UNREAD', 'component': 'entity',
                         'detail': {'index': index, 'entityId': None}})
    elif key != entity_id:
        refusals.append({'code': 'ENTITY_KEY_ID_MISMATCH', 'component': 'entity',
                         'detail': {'index': index, 'dictionaryKey': key, 'id': entity_id}})
    if (fv & IDENTITY_FLAGS) != IDENTITY_FLAGS:
        refusals.append({'code': 'ENTITY_OWNER_CONFIG_CONTEXT_UNVERIFIED',
                         'component': 'entity',
                         'detail': {'index': index, 'entityId': entity_id,
                                    'flags': flags['names']}})
    return {
        'index': index,
        'entityId': entity_id,
        'templateId': config_id,
        'dictionaryKey': key,
        'configId': config_id,
        'ownerRef': entry.get('owner'),
        'configRef': entry.get('config'),
        'contextRef': entry.get('context'),
        'position': position,
        'flags': flags,
        'configNull': bool(fv & 32),
    }


# --------------------------------------------------------------------------- #
# injection blocks: geometry from another source, and caller labels
# --------------------------------------------------------------------------- #

def _external_source(block, what, key):
    source = block.get('source')
    if source is None:
        return {'kind': 'unspecified-external-source', 'path': None, 'sha256': None,
                'observedAt': None, 'derived': None}
    source = _require_mapping(source, 'EXTERNAL_BLOCK_INVALID', '%s.%s.source' % (what, key))
    observed_at = source.get('observedAt')
    if observed_at is not None and (not isinstance(observed_at, str) or not observed_at):
        raise ObservationError('EXTERNAL_BLOCK_INVALID',
                               '%s.%s.source.observedAt must be a non-empty string or null'
                               % (what, key))
    return {'kind': source.get('kind') or 'unspecified-external-source',
            'path': source.get('path'), 'sha256': source.get('sha256'),
            'observedAt': observed_at,
            'derived': source.get('derived') if isinstance(source.get('derived'), bool) else None}


def _document_source_field(document):
    """The snapshot field name the decoded document was produced from, if it records one."""
    source = document.get('source')
    if isinstance(source, Mapping):
        value = source.get('snapshotField')
        if isinstance(value, str) and value:
            return value
    return None


def _project_external(document, native_rows, refusals):
    """Project the injected geometry/label blocks.

    These are the *only* way a value from outside the native entity record can enter the
    projection, they are keyed by entity id, and every one of them keeps its own source
    and its own observation time.  Neither block can add or remove an entity.
    """
    geometry, labels, unmatched = {}, {}, []
    known_ids = {row['entityId'] for row in native_rows if row['entityId'] is not None}

    raw_geometry = document.get('geometry')
    if raw_geometry is not None:
        raw_geometry = _require_mapping(raw_geometry, 'EXTERNAL_BLOCK_INVALID',
                                        'geometry')
        for key, entry in raw_geometry.items():
            entry = _require_mapping(entry, 'EXTERNAL_BLOCK_INVALID', 'geometry.%s' % key)
            reference = _reference_id(key)
            if reference is None or reference not in known_ids:
                unmatched.append({'block': 'geometry', 'key': key})
                continue
            position = entry.get('position')
            if not (isinstance(position, (list, tuple)) and len(position) == 3 and
                    all(_is_number(v) for v in position)):
                raise ObservationError(
                    'EXTERNAL_BLOCK_INVALID',
                    'geometry position must be three finite numbers',
                    key=key, position=position)
            geometry[reference] = {'position': [float(v) for v in position],
                                   'source': _external_source(entry, 'geometry', key)}

    raw_labels = document.get('labels')
    if raw_labels is not None:
        raw_labels = _require_mapping(raw_labels, 'EXTERNAL_BLOCK_INVALID', 'labels')
        for key, entry in raw_labels.items():
            entry = _require_mapping(entry, 'EXTERNAL_BLOCK_INVALID', 'labels.%s' % key)
            reference = _reference_id(key)
            if reference is None or reference not in known_ids:
                unmatched.append({'block': 'labels', 'key': key})
                continue
            text = entry.get('text')
            if not isinstance(text, str) or not text or len(text) > MAX_LABEL_CHARS:
                raise ObservationError(
                    'EXTERNAL_BLOCK_INVALID',
                    'label text must be a non-empty string of at most %d characters'
                    % MAX_LABEL_CHARS, key=key, length=len(text) if isinstance(text, str) else None)
            labels[reference] = {'text': text, 'source': _external_source(entry, 'labels', key)}

    for entry in unmatched:
        refusals.append({'code': 'EXTERNAL_BLOCK_UNKNOWN_ENTITY', 'component': 'external',
                         'detail': entry})
    return geometry, labels


def _reference_id(key):
    if not isinstance(key, str) or not key.isdigit():
        return None
    return int(key)


# --------------------------------------------------------------------------- #
# subsystem projection
# --------------------------------------------------------------------------- #

def _project_subsystems(document):
    """Project the injected read-only subsystem observations.

    The live lane reports two subsystems as *present but empty* while the level itself
    verifies: their decoders return a refusal status such as ``baseline_refused`` (the
    scheduler's own ``LIFECYCLE_STATUS_`` / ``SCHEDULER_STATUS_`` check names) together
    with an empty or null row list.  This projection reports those as ``state="unknown"``
    and marks explicitly that an empty payload under an unknown state is NOT an
    observation of an empty subsystem.  A successful read is the ONLY way to reach
    ``state="known"``, so a refusal can never be read as "the subsystem holds nothing".

    The block is the decoder's own return value (``{'ok','reasons','status','counts',
    'rows',...}``); entries are carried through rather than reinterpreted.
    """
    recognized = {'status', 'reasons', 'ok', 'counts', 'rows', 'observation',
                  'observedBounds', 'flags', 'pointers', 'source', 'observedAt'}
    injected = document.get('subsystems')
    result = {}
    unrecognized = []
    if injected is not None:
        injected = _require_mapping(injected, 'SUBSYSTEM_BLOCK_INVALID', 'subsystems')
        unrecognized = ['subsystems.%s' % name for name in sorted(set(injected) - set(SUBSYSTEM_NAMES))]
    for name in SUBSYSTEM_NAMES:
        if not isinstance(injected, Mapping) or name not in injected:
            result[name] = {
                'state': 'unavailable', 'status': None, 'reasons': [],
                'payload': None, 'counts': None, 'decoderOk': None, 'observedAt': None,
                'source': None, 'emptyResultIsNotAnObservation': True,
                'reason': 'no observation of this subsystem was supplied with this receipt',
            }
            continue
        entry = _require_mapping(injected[name], 'SUBSYSTEM_BLOCK_INVALID', 'subsystems.' + name)
        unrecognized += ['subsystems.%s.%s' % (name, key)
                         for key in sorted(set(entry) - recognized)]
        status = entry.get('status')
        if status is not None and status not in SUBSYSTEM_STATUS_NAMES[name]:
            raise ObservationError('SUBSYSTEM_STATUS_UNKNOWN',
                                   'subsystem status is not in the decoder status table',
                                   subsystem=name, status=status)
        decoder_ok = entry.get('ok')
        if decoder_ok is not None and not isinstance(decoder_ok, bool):
            raise ObservationError('SUBSYSTEM_BLOCK_INVALID',
                                   'subsystem ok must be a boolean when present',
                                   subsystem=name)
        reasons = entry.get('reasons')
        reasons = [str(r) for r in reasons] if isinstance(reasons, (list, tuple)) else \
            ([str(reasons)] if reasons else [])
        if status == 'ok' and decoder_ok is False:
            raise ObservationError(
                'SUBSYSTEM_STATUS_INCONSISTENT',
                'the subsystem decoder reports status ok while its own ok flag is false; '
                'refusing to pick one of two contradictory verdicts',
                subsystem=name, reasons=reasons)
        ok = status == 'ok' and decoder_ok is not False
        result[name] = {
            'state': 'known' if ok else 'unknown',
            'status': status,
            'reasons': reasons,
            'payload': entry.get('rows'),
            'counts': entry.get('counts'),
            'decoderOk': decoder_ok,
            'observation': entry.get('observation'),
            'observedBounds': entry.get('observedBounds'),
            'observedAt': entry.get('observedAt'),
            'source': entry.get('source'),
            'emptyResultIsNotAnObservation': not ok,
            'reason': None if ok else
                      'the subsystem decoder did not return ok; an empty or null payload '
                      'here is a refusal, not a reading of an empty subsystem',
        }
    return result, unrecognized


# --------------------------------------------------------------------------- #
# project_snapshot
# --------------------------------------------------------------------------- #

def project_snapshot(document, *, identity):
    """Project one decoded observation document into the structured form.

    ``document`` must be an already-decoded mapping -- this function performs no I/O and
    accepts no path.  ``identity`` binds the answer to the read it came from:
    ``targetHandle`` and ``levelId`` are required, ``observedAt``/``receiptPath``/
    ``receiptSha256``/session fields are carried through when the execution layer has
    them and reported as unavailable when it does not (a timestamp is never invented).
    """
    kind = _validate_document(document)
    identity = _validate_identity(identity)
    if isinstance(document, Mapping) and document.get('_fixture') is not None:
        marker = _require_mapping(document['_fixture'], 'FIXTURE_MARKER_INVALID', '_fixture')
        if marker.get('live') is not False:
            raise ObservationError(
                'FIXTURE_MARKER_INVALID',
                'a fixture marker must state live=false; a reverse-case document must not '
                'be readable as a live observation', marker=marker)

    raw_status = _require_mapping(document.get('status'), 'DOCUMENT_SHAPE_UNSUPPORTED',
                                  'document.status')
    status_value = _require_int(raw_status, 'value', 'DOCUMENT_SHAPE_UNSUPPORTED',
                                'document.status', minimum=0)
    if status_value not in STATUS_NAMES:
        raise ObservationError('DOCUMENT_STATUS_UNKNOWN', 'snapshot status value is not in '
                               'the decoder status table', status=status_value)
    status_name = raw_status.get('name')
    status_name_mismatch = None if status_name in (None, STATUS_NAMES[status_value]) else \
        {'declared': status_name, 'recomputed': STATUS_NAMES[status_value]}
    flags, flag_mismatch = _project_flags(document.get('flags'), SNAPSHOT_FLAGS,
                                          'DOCUMENT', 'document')

    counts = _require_mapping(document.get('counts'), 'DOCUMENT_SHAPE_UNSUPPORTED',
                              'document.counts')
    for key in BOUND_COUNT_KEYS:
        _require_int(counts, key, 'DOCUMENT_COUNTS_INCONSISTENT', 'document.counts',
                     minimum=0)
    capacity = counts['entityCapacity']
    valid = counts['entityValidEntries']
    captured = counts['entityCaptured']
    rejected = counts['entityRejected']
    if not (rejected <= captured <= valid <= capacity):
        raise ObservationError(
            'DOCUMENT_COUNTS_INCONSISTENT',
            'entity counts are not ordered (rejected <= captured <= valid <= capacity)',
            counts={key: counts[key] for key in BOUND_COUNT_KEYS})
    max_dictionary, max_captured = (8192, 4096) if document['version'] == 2 else (4096, 512)
    if capacity > max_dictionary or captured > max_captured:
        raise ObservationError('DOCUMENT_COUNTS_INCONSISTENT',
                               'entity capacity exceeds any known snapshot capacity',
                               capacity=capacity)

    level_observation = _require_mapping(document.get('levelObservation'),
                                         'DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
                                         'document.levelObservation')
    if 'verified' not in level_observation:
        raise ObservationError('DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
                               'levelObservation must carry a verified flag')
    level_verified = level_observation.get('verified')
    if not isinstance(level_verified, bool):
        raise ObservationError('DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
                               'levelObservation.verified must be a boolean')
    observed_level = level_observation.get('levelId')
    if level_verified:
        if not _is_int(observed_level) or observed_level <= 0:
            raise ObservationError(
                'DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
                'levelObservation is marked verified but carries no positive levelId')
    elif observed_level not in (None, 0):
        raise ObservationError(
            'DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED',
            'levelObservation is not verified but carries a level id', levelId=observed_level)
    if level_verified and observed_level != identity['levelId']:
        raise ObservationError(
            'WRONG_LEVEL',
            'the identity handle level and the level the receipt observed are different; '
            'answering for either one here would merge two reads',
            handleLevelId=identity['levelId'], observedLevelId=observed_level)

    entities_raw = document.get('entities')
    if not isinstance(entities_raw, (list, tuple)):
        raise ObservationError('DOCUMENT_SHAPE_UNSUPPORTED', 'document.entities must be an array')

    refusals = []
    if flag_mismatch:
        refusals.append({'code': 'FLAG_NAMES_MISMATCH', 'component': 'document',
                         'detail': {'kind': 'snapshot', **flag_mismatch}})
    if status_name_mismatch:
        refusals.append({'code': 'DOCUMENT_STATUS_NAME_MISMATCH', 'component': 'document',
                         'detail': status_name_mismatch})
    if len(entities_raw) != captured:
        refusals.append({'code': 'ENTITY_SET_COUNT_MISMATCH', 'component': 'document',
                         'detail': {'capturedCount': captured, 'rows': len(entities_raw)}})
    if rejected:
        refusals.append({'code': 'ENTITY_REJECTED_BY_READER', 'component': 'document',
                         'detail': {'entityRejected': rejected}})
    if flags['value'] & TRUNCATION_FLAG:
        refusals.append({'code': 'ENTITIES_TRUNCATED', 'component': 'document',
                         'detail': {'flag': SNAPSHOT_FLAGS[TRUNCATION_FLAG]}})
    if flags['value'] & READ_FAILURE_FLAG:
        refusals.append({'code': 'ENTITY_READ_FAILURE', 'component': 'document',
                         'detail': {'flag': SNAPSHOT_FLAGS[READ_FAILURE_FLAG]}})
    if captured < valid or len(entities_raw) < valid:
        refusals.append({'code': 'ENTITY_SET_SHORT_OF_VALID_ENTRIES', 'component': 'document',
                         'detail': {'capturedCount': captured, 'totalCount': valid,
                                    'rows': len(entities_raw)}})
    missing_flags = REQUIRED_SNAPSHOT_FLAGS & ~flags['value']
    if missing_flags:
        refusals.append({'code': 'SNAPSHOT_REQUIRED_FLAGS_MISSING', 'component': 'document',
                         'detail': {'missing': _flag_names(missing_flags, SNAPSHOT_FLAGS)}})
    if status_value != 0:
        refusals.append({'code': 'SNAPSHOT_STATUS_NOT_OK', 'component': 'document',
                         'detail': {'status': STATUS_NAMES[status_value]}})

    acceptance = document.get('acceptance')
    acceptance_projection = None
    if acceptance is not None:
        acceptance = _require_mapping(acceptance, 'ACCEPTANCE_BLOCK_INVALID', 'acceptance')
        ok = acceptance.get('ok')
        if not isinstance(ok, bool):
            raise ObservationError('ACCEPTANCE_BLOCK_INVALID',
                                   'acceptance.ok must be a boolean')
        reasons = acceptance.get('reasons')
        reasons = [str(r) for r in reasons] if isinstance(reasons, (list, tuple)) else []
        acceptance_projection = {'ok': ok, 'reasons': reasons,
                                'source': acceptance.get('source')}
        if not ok:
            refusals.append({'code': 'NATIVE_ACCEPTANCE_REJECTED', 'component': 'acceptance',
                             'detail': {'reasons': reasons}})

    raw_entities = [_project_entity(entry, index, refusals)
                    for index, entry in enumerate(entities_raw)]

    seen, duplicates = {}, []
    for row in raw_entities:
        entity_id = row['entityId']
        if entity_id is None:
            continue
        if entity_id in seen:
            duplicates.append(entity_id)
        seen[entity_id] = row
    for entity_id in sorted(set(duplicates)):
        refusals.append({'code': 'DUPLICATE_ENTITY_IDENTITY', 'component': 'identity',
                         'detail': {'entityId': entity_id, 'occurrences':
                                    sum(1 for r in raw_entities if r['entityId'] == entity_id)}})
    key_counts = {}
    for row in raw_entities:
        key_counts[row['dictionaryKey']] = key_counts.get(row['dictionaryKey'], 0) + 1
    for key, count in sorted(key_counts.items()):
        if count > 1:
            refusals.append({'code': 'DUPLICATE_DICTIONARY_KEY', 'component': 'identity',
                             'detail': {'dictionaryKey': key, 'occurrences': count}})

    geometry, labels = _project_external(document, raw_entities, refusals)
    subsystems, unrecognized_subsystems = _project_subsystems(document)

    unrecognized = sorted(set(unrecognized_subsystems) |
                         (set(document) - set(RECOGNIZED_DOCUMENT_KEYS)))

    entity_rows = []
    observation_times = set()
    conflicts = []
    for row in raw_entities:
        entity_rows.append(_build_entity_row(
            row, geometry.get(row['entityId']), labels.get(row['entityId']),
            identity, document, refusals, conflicts, observation_times))

    entity_digest = _digest([[row['index'], row['entityId'], row['templateId'],
                              row['dictionaryKey'], row['flags']['value'], row['position']]
                             for row in raw_entities])
    bound_counts = {key: counts[key] for key in BOUND_COUNT_KEYS}
    receipt = {'path': identity.get('receiptPath'),
               'sha256': identity.get('receiptSha256'),
               'snapshotField': _document_source_field(document)}
    binding = {'contract': CONTRACT_ID, 'schemaVersion': SCHEMA_VERSION,
               'targetHandle': identity['targetHandle'], 'levelId': identity['levelId'],
               'observedAt': identity['observedAt'], 'receipt': receipt,
               'status': status_value, 'flags': flags['value'], 'counts': bound_counts,
               'entityDigest': entity_digest}
    snapshot_id = 'so1-' + _digest(binding)
    content_digest = _digest({'contract': CONTRACT_ID, 'entityDigest': entity_digest,
                              'status': status_value, 'flags': flags['value'],
                              'counts': bound_counts})

    trust_refusals = [r for r in refusals if r['code'] in TRUST_REFUSAL_CODES]
    trusted = not trust_refusals
    invalidating = sorted({r['code'] for r in refusals
                           if r['code'] in INVALIDATING_REFUSAL_CODES})
    truncated = bool(flags['value'] & TRUNCATION_FLAG) or captured < valid or \
        len(raw_entities) < valid
    readable = status_value in READABLE_STATUSES
    complete = bool(readable and trusted and not invalidating and
                    len(raw_entities) == captured == valid and rejected == 0 and
                    (REQUIRED_SNAPSHOT_FLAGS & ~flags['value']) == 0)

    unsupported = dict(UNSOURCED_ATTRIBUTES)
    external_times = sorted({t for t in observation_times if t})
    unknown_external_times = sum(1 for t in observation_times if not t)
    return {
        'schemaVersion': SCHEMA_VERSION,
        'contract': CONTRACT_ID,
        'inputKind': kind,
        'targetHandle': identity['targetHandle'],
        'snapshotId': snapshot_id,
        'contentDigest': content_digest,
        'observedAt': identity['observedAt'],
        'observedAtSource': identity['observedAtSource'],
        'levelId': observed_level if level_verified else None,
        'levelObservation': dict(level_observation),
        'status': {'value': status_value, 'name': STATUS_NAMES[status_value]},
        'flags': flags,
        'counts': dict(counts),
        'readable': readable,
        'complete': complete,
        'truncated': truncated,
        'trusted': trusted,
        'capturedCount': captured,
        'totalCount': valid,
        'capacity': capacity,
        'rejectedCount': rejected,
        'entityIds': [row['entityId'] for row in raw_entities],
        'entities': entity_rows,
        'entityDigest': entity_digest,
        'refusals': refusals,
        'invalidatingRefusals': invalidating,
        'conflicts': conflicts,
        'unsupportedAttributes': unsupported,
        'subsystems': subsystems,
        'acceptance': acceptance_projection,
        'observationTimes': {
            'snapshot': identity['observedAt'],
            'external': external_times,
            'externalWithoutATime': unknown_external_times,
            'attributeBound': True,
        },
        'mixedObservationTimes': bool(external_times or unknown_external_times),
        'externalBlocks': {'geometry': len(geometry), 'labels': len(labels)},
        'receipt': receipt,
        'session': {key: identity.get(key) for key in
                    ('sessionPid', 'sessionCreation', 'sessionSource')},
        'fixtureMarker': dict(document['_fixture']) if isinstance(document.get('_fixture'), Mapping) else None,
        'unrecognizedDocumentKeys': unrecognized,
        'unrecognizedIdentityKeys': identity['unrecognizedIdentityKeys'],
        'limits': {
            'modelFacingTransport': 'page_entities',
            'defaultPageItems': DEFAULT_PAGE_ITEMS, 'maxPageItems': MAX_PAGE_ITEMS,
            'defaultPageBytes': DEFAULT_PAGE_BYTES, 'maxPageBytes': MAX_PAGE_BYTES,
            'note': 'project_snapshot returns the whole projection for a programmatic '
                    'consumer; page_entities is the bounded, paged surface for a model.',
        },
    }


def _build_entity_row(row, geometry, label, identity, document, refusals, conflicts,
                      observation_times):
    """Attach attribute provenance to one native entity row."""
    declared = {}
    provenance = {}

    def attach(attribute, value, *, source_kind, source, observed_at, derived,
               external=False, status='known'):
        declared[attribute] = value
        provenance[attribute] = {'status': status, 'sourceKind': source_kind,
                                 'source': source, 'observedAt': observed_at,
                                 'derived': derived}
        if external:
            observation_times.add(observed_at)

    def unattach(attribute, reason, *, status='unknown', source_kind='none'):
        provenance[attribute] = {'status': status, 'sourceKind': source_kind,
                                 'source': None, 'observedAt': None, 'derived': False}
        unknown.append({'field': attribute, 'reason': reason})

    unknown = []
    receipt_source = {'path': identity.get('receiptPath'),
                      'sha256': identity.get('receiptSha256'),
                      'snapshotField': _document_source_field(document)}
    native_at = identity['observedAt']

    if row['entityId'] is not None:
        attach('entityId', row['entityId'], source_kind='native-snapshot-entity-id',
               source=receipt_source, observed_at=native_at, derived=False)
    else:
        unattach('entityId', 'the id_read flag is absent, so no id was read for this row')
    if row['templateId'] is not None:
        attach('templateId', row['templateId'], source_kind='native-entity-config-id',
               source=receipt_source, observed_at=native_at, derived=True)
    elif row['configNull']:
        unattach('templateId', 'the reader marked the config pointer null (config_null); '
                               'the template is genuinely unknown for this entity')
    else:
        unattach('templateId', 'the config_id_read flag is absent, so no configuration id '
                               'was read for this row')
    if row['configId'] is not None:
        attach('configId', row['configId'], source_kind='native-entity-config-id',
               source=receipt_source, observed_at=native_at, derived=False)
    else:
        unattach('configId', 'the config_id_read flag is absent or the pointer is null')
    attach('dictionaryKey', row['dictionaryKey'],
           source_kind='native-entity-dictionary-key', source=receipt_source,
           observed_at=native_at, derived=False)
    for attribute, value in (('ownerRef', row['ownerRef']), ('configRef', row['configRef']),
                             ('contextRef', row['contextRef'])):
        attach(attribute, value, source_kind='native-entity-pointer', source=receipt_source,
               observed_at=native_at, derived=False)

    # position: the native read wins; an external geometry block may fill a hole, never
    # overwrite a native value.
    if row['position'] is not None:
        attach('position', row['position'], source_kind='native-snapshot-position',
               source=receipt_source, observed_at=native_at, derived=False)
        if geometry is not None:
            provenance['position']['contested'] = True
            conflicts.append({'entityId': row['entityId'], 'field': 'position',
                              'kept': {'sourceKind': 'native-snapshot-position',
                                       'observedAt': native_at, 'value': row['position']},
                              'rejected': {'sourceKind': geometry['source']['kind'],
                                           'observedAt': geometry['source']['observedAt'],
                                           'value': geometry['position']}})
            refusals.append({'code': 'ATTRIBUTE_SOURCE_CONFLICT', 'component': 'attribute',
                             'detail': {'entityId': row['entityId'], 'field': 'position',
                                        'keptSource': 'native-snapshot-position',
                                        'rejectedSource': geometry['source']['kind']}})
    elif geometry is not None:
        attach('position', geometry['position'], source_kind=geometry['source']['kind'],
               source=geometry['source'], observed_at=geometry['source']['observedAt'],
               derived=bool(geometry['source']['derived']), external=True)
    else:
        unattach('position', 'the position_read flag is absent and no external geometry '
                             'source was supplied; this is unknown, NOT zero')

    if label is not None:
        attach('label', label['text'], source_kind=label['source']['kind'],
               source=label['source'], observed_at=label['source']['observedAt'],
               derived=bool(label['source']['derived']), external=True)
    else:
        unattach('label', 'no label was supplied with this receipt; a label is never '
                          'invented and never derived from an index or a UI name')

    for attribute, reason in UNSOURCED_ATTRIBUTES.items():
        unattach(attribute, reason, source_kind='not-implemented')
        provenance[attribute]['unsupportedByContract'] = True

    return {
        'index': row['index'],
        'entityId': row['entityId'],
        'templateId': row['templateId'],
        'knownAttributes': declared,
        'unknownFields': unknown,
        'fieldProvenance': provenance,
        'flags': row['flags'],
        'identityTrusted': (row['flags']['value'] & IDENTITY_FLAGS) == IDENTITY_FLAGS and
                           row['entityId'] is not None and
                           row['dictionaryKey'] == row['entityId'],
    }


# --------------------------------------------------------------------------- #
# get_entity / page_entities
# --------------------------------------------------------------------------- #

def _require_projection(projection, what):
    projection = _require_mapping(projection, 'PROJECTION_INVALID', what)
    if projection.get('contract') != CONTRACT_ID or \
            projection.get('schemaVersion') != SCHEMA_VERSION:
        raise ObservationError('PROJECTION_INVALID',
                               '%s is not a projection of this contract/version' % what,
                               contract=projection.get('contract'),
                               schemaVersion=projection.get('schemaVersion'))
    return projection


def _require_trusted(projection, what):
    if projection['trusted'] is True:
        return
    codes = sorted({r['code'] for r in projection['refusals']
                    if r['code'] in TRUST_REFUSAL_CODES})
    raise ObservationError(
        'SNAPSHOT_UNTRUSTED',
        '%s needs a trustworthy entity identity set; this snapshot refuses that' % what,
        entitySetRefusals=codes, duplicateIds=[d['detail'].get('entityId')
                                               for d in projection['refusals']
                                               if d['code'] == 'DUPLICATE_ENTITY_IDENTITY'])


def get_entity(projection, entity_id):
    """One entity's projected attributes, keyed by the id the native read returned.

    Absence is never upgraded: when the entity is not in the set and the set is not
    proven complete, ``absenceMeaning`` says so instead of the answer reading like a
    confirmed non-existence.
    """
    projection = _require_projection(projection, 'projection')
    if not _is_int(entity_id) or entity_id <= 0:
        raise ObservationError('ENTITY_ID_INVALID', 'entity_id must be a positive integer',
                               entityId=entity_id)
    _require_trusted(projection, 'get_entity')
    matches = [row for row in projection['entities'] if row['entityId'] == entity_id]
    base = {'snapshotId': projection['snapshotId'], 'contentDigest': projection['contentDigest'],
            'levelId': projection['levelId'], 'complete': projection['complete'],
            'truncated': projection['truncated'], 'trusted': projection['trusted']}
    if matches:
        return dict(base, found=True, entity=matches[0], occurrences=len(matches))
    return dict(base, found=False, entity=None,
                absenceMeaning='not-present-in-complete-snapshot'
                if projection['complete'] else 'no-evidence-truncated-or-incomplete-snapshot',
                absenceReason=None if projection['complete'] else
                'this snapshot is not proven complete, so the entity may exist without '
                'having been captured')


def _encode_cursor(projection, offset):
    body = {'v': SCHEMA_VERSION, 'snapshotId': projection['snapshotId'],
            'contentDigest': projection['contentDigest'], 'levelId': projection['levelId'],
            'offset': offset}
    check = hashlib.sha256(
        (CURSOR_PEPPER + _canonical(body).decode('utf-8')).encode('utf-8')).hexdigest()[:32]
    body['check'] = check
    return base64.urlsafe_b64encode(_canonical(body)).decode('ascii')


def _decode_cursor(cursor, projection):
    if not isinstance(cursor, str) or not cursor:
        raise ObservationError('CURSOR_INVALID', 'cursor must be a non-empty string')
    try:
        raw = base64.urlsafe_b64decode(cursor.encode('ascii'))
        body = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ObservationError('CURSOR_INVALID', 'cursor is not decodable',
                               error='%s: %s' % (type(exc).__name__, exc))
    if not isinstance(body, dict) or tuple(sorted(body)) != tuple(sorted(CURSOR_KEYS)):
        raise ObservationError('CURSOR_TAMPERED',
                               'cursor does not carry exactly the expected fields',
                               fields=sorted(body) if isinstance(body, dict) else None)
    check = body.pop('check')
    expected = hashlib.sha256(
        (CURSOR_PEPPER + _canonical(body).decode('utf-8')).encode('utf-8')).hexdigest()[:32]
    if check != expected:
        raise ObservationError('CURSOR_TAMPERED', 'cursor integrity check failed')
    if body['v'] != SCHEMA_VERSION:
        raise ObservationError('CURSOR_VERSION_UNSUPPORTED',
                               'cursor was made by another contract version', version=body['v'])
    if body['snapshotId'] != projection['snapshotId']:
        raise ObservationError('CURSOR_SNAPSHOT_CHANGED',
                               'cursor belongs to another snapshot',
                               cursorSnapshotId=body['snapshotId'],
                               snapshotId=projection['snapshotId'])
    if body['contentDigest'] != projection['contentDigest']:
        raise ObservationError('CURSOR_CONTENT_CHANGED',
                               'the snapshot content behind this cursor changed',
                               cursorContentDigest=body['contentDigest'],
                               contentDigest=projection['contentDigest'])
    if body['levelId'] != projection['levelId']:
        raise ObservationError('CURSOR_LEVEL_CHANGED',
                               'cursor belongs to another level',
                               cursorLevelId=body['levelId'], levelId=projection['levelId'])
    offset = body['offset']
    total = len(projection['entities'])
    if not _is_int(offset) or offset < 0 or offset > total:
        raise ObservationError('CURSOR_OFFSET_OUT_OF_RANGE',
                               'cursor offset is outside this snapshot',
                               offset=offset, totalCount=total)
    return offset


def page_entities(projection, *, cursor=None, maxItems=DEFAULT_PAGE_ITEMS,
                  maxBytes=DEFAULT_PAGE_BYTES):
    """One bounded page of entities.

    Both limits count: ``maxItems`` on rows and ``maxBytes`` on the UTF-8 encoded JSON of
    the items array.  A single object is never cut apart -- if even one row exceeds the
    byte budget the page returns exactly that row, intact, with ``oversizedItems`` naming
    it and a truncation reason, so a consumer can raise the budget instead of silently
    receiving half an object.
    """
    projection = _require_projection(projection, 'projection')
    if not _is_int(maxItems) or maxItems < 1:
        raise ObservationError('PAGE_LIMIT_INVALID', 'maxItems must be a positive integer',
                               maxItems=maxItems)
    if maxItems > MAX_PAGE_ITEMS:
        raise ObservationError('PAGE_LIMIT_EXCEEDS_MAXIMUM',
                               'maxItems is above the contract maximum',
                               maxItems=maxItems, maximum=MAX_PAGE_ITEMS)
    if not _is_int(maxBytes) or maxBytes < 1:
        raise ObservationError('PAGE_LIMIT_INVALID', 'maxBytes must be a positive integer',
                               maxBytes=maxBytes)
    if maxBytes > MAX_PAGE_BYTES:
        raise ObservationError('PAGE_LIMIT_EXCEEDS_MAXIMUM',
                               'maxBytes is above the contract maximum',
                               maxBytes=maxBytes, maximum=MAX_PAGE_BYTES)

    rows = projection['entities']
    total = len(rows)
    offset = 0 if cursor is None else _decode_cursor(cursor, projection)

    items, oversized, reason = [], [], None
    while offset + len(items) < total:
        trial = items + [rows[offset + len(items)]]
        size = _items_bytes(trial)
        if size <= maxBytes and len(trial) <= maxItems:
            items = trial
            continue
        if not items:
            # Nothing fits.  Returning nothing would be indistinguishable from the end of
            # the set, so return the one row whole and say why.
            items = trial
            oversized.append(trial[0]['entityId'])
            reason = 'single-item-exceeds-max-bytes'
        else:
            reason = 'item-limit' if len(trial) > maxItems else 'byte-limit'
        break
    exhausted = offset + len(items) >= total
    if exhausted:
        reason = 'end-of-page'
    truncated = (not exhausted) or bool(oversized)
    return {
        'schemaVersion': SCHEMA_VERSION,
        'contract': CONTRACT_ID,
        'snapshotId': projection['snapshotId'],
        'contentDigest': projection['contentDigest'],
        'targetHandle': projection['targetHandle'],
        'levelId': projection['levelId'],
        'observedAt': projection['observedAt'],
        'offset': offset,
        'returnedCount': len(items),
        'rowsInSnapshot': total,
        'snapshotTotalCount': projection['totalCount'],
        'snapshotCapacity': projection['capacity'],
        'capturedCount': projection['capturedCount'],
        'complete': projection['complete'],
        'truncated': truncated,
        'truncationReason': reason,
        'note': None if total == projection['totalCount'] else
                'this snapshot holds %d of %d entries the receipt knew about; the cursor '
                'indexes only the rows that were captured'
                % (total, projection['totalCount']),
        'nextCursor': _encode_cursor(projection, offset + len(items)) if not exhausted else None,
        'items': items,
        'oversizedItems': oversized,
        'bytes': _items_bytes(items),
        'maxItems': maxItems,
        'maxBytes': maxBytes,
        'byteAccounting': 'utf-8 bytes of the canonical JSON of the items array; the page '
                          'envelope is excluded and carries no entity content',
        'loadMore': 'pass nextCursor back to page_entities; a cursor is bound to this '
                    'snapshotId, its content digest and this level',
        'rowCountMeaning': 'rowsInSnapshot is how many rows this snapshot captured and '
                           'the cursor indexes; snapshotTotalCount is what the receipt '
                           'said the level held.  They differ exactly when the set is '
                           'truncated, and the page must not be read as the whole set.',
        'refusals': projection['refusals'],
    }


# --------------------------------------------------------------------------- #
# diff_snapshots
# --------------------------------------------------------------------------- #

def _entity_index(projection):
    return {row['entityId']: row for row in projection['entities']
            if row['entityId'] is not None}


def diff_snapshots(before, after):
    """Compare two projections by entity ID and by attribute.

    Three outcomes, deliberately distinct:

    ``unknown``  one side was not readable at all -- no list is produced, because "no
                 list" and "no entities" must not look the same.
    ``refused``  a set's identity is untrustworthy, or the two sides are different levels.
    ``observed`` a difference was computed; it is ``authoritative`` only when both sides
                 are proven complete, and the caveats say which side is not.
    """
    before = _require_projection(before, 'before')
    after = _require_projection(after, 'after')
    out = {
        'schemaVersion': SCHEMA_VERSION,
        'contract': CONTRACT_ID,
        'beforeSnapshotId': before['snapshotId'],
        'afterSnapshotId': after['snapshotId'],
        'levelId': {'before': before['levelId'], 'after': after['levelId']},
        'state': None,
        'code': None,
        'reason': None,
        'authoritative': False,
        'added': None,
        'removed': None,
        'addedCount': None,
        'removedCount': None,
        'unchangedCount': None,
        'changed': [],
        'changedCount': 0,
        'changedTruncated': False,
        'sameCountDifferentObjects': None,
        'caveats': [],
        'counts': {'before': {'capturedCount': before['capturedCount'],
                              'totalCount': before['totalCount'],
                              'complete': before['complete'],
                              'readable': before['readable']},
                   'after': {'capturedCount': after['capturedCount'],
                             'totalCount': after['totalCount'],
                             'complete': after['complete'],
                             'readable': after['readable']}},
        'refusals': {'before': before['refusals'], 'after': after['refusals']},
    }
    unreadable = [name for name, side in (('before', before), ('after', after))
                  if side['readable'] is not True]
    if unreadable:
        out.update(state='unknown', code='SNAPSHOT_NOT_READABLE',
                   reason='no entity list can be compared: the receipt status on the '
                          '%s side is not one under which the reader produces rows'
                          % '/'.join(unreadable),
                   statuses={'before': before['status'], 'after': after['status']},
                   unreadableSides=unreadable)
        out['caveats'].append('an unreadable side is reported as unknown, never as an '
                              'empty set; do not read the missing lists as "nothing there"')
        return out
    untrusted = [name for name, side in (('before', before), ('after', after))
                 if side['trusted'] is not True]
    if untrusted:
        codes = sorted({r['code'] for name in untrusted
                        for r in out['refusals'][name] if r['code'] in TRUST_REFUSAL_CODES})
        out.update(state='refused', code='SNAPSHOT_UNTRUSTED',
                   reason='the entity identity set on the %s side is not trustworthy'
                          % '/'.join(untrusted), entitySetRefusals=codes)
        return out
    if before['levelId'] != after['levelId']:
        out.update(state='refused', code='SNAPSHOT_LEVEL_MISMATCH',
                   reason='the two projections are of different levels')
        return out

    left, right = _entity_index(before), _entity_index(after)
    added = sorted(set(right) - set(left))
    removed = sorted(set(left) - set(right))
    changed = []
    for entity_id in sorted(set(left) & set(right)):
        for attribute in DECLARED_ATTRIBUTES:
            pa = left[entity_id]['fieldProvenance'][attribute]
            pb = right[entity_id]['fieldProvenance'][attribute]
            if pa['status'] == 'known' and pb['status'] == 'known':
                va = left[entity_id]['knownAttributes'][attribute]
                vb = right[entity_id]['knownAttributes'][attribute]
                if not _strict_equal(va, vb):
                    changed.append({'entityId': entity_id, 'field': attribute,
                                    'kind': 'value-changed',
                                    'before': va, 'after': vb,
                                    'beforeSource': pa['sourceKind'],
                                    'afterSource': pb['sourceKind'],
                                    'beforeObservedAt': pa['observedAt'],
                                    'afterObservedAt': pb['observedAt']})
            elif pa['status'] != pb['status']:
                changed.append({'entityId': entity_id, 'field': attribute,
                                'kind': 'availability-changed',
                                'beforeStatus': pa['status'], 'afterStatus': pb['status'],
                                'before': left[entity_id]['knownAttributes'].get(attribute),
                                'after': right[entity_id]['knownAttributes'].get(attribute)})
    truncated_changes = len(changed) > MAX_DIFF_CHANGES
    out.update(
        state='observed',
        authoritative=bool(before['complete'] and after['complete']),
        added=added, removed=removed, addedCount=len(added), removedCount=len(removed),
        unchangedCount=len(set(left) & set(right)) - len({c['entityId'] for c in changed}),
        changed=changed[:MAX_DIFF_CHANGES], changedCount=len(changed),
        changedTruncated=truncated_changes,
        sameCountDifferentObjects=bool(added) and bool(removed) and
                                  len(right) == len(left))
    for name, side in (('before', before), ('after', after)):
        if not side['complete']:
            out['caveats'].append(
                'the %s entity set is not proven complete (truncated=%s, refusals=%s), so '
                'an addition or removal here may be an artifact of the capture'
                % (name, side['truncated'],
                   sorted({r['code'] for r in side['refusals']})))
    if truncated_changes:
        out['caveats'].append('the changed list is capped at %d entries; changedCount is '
                              'the real number' % MAX_DIFF_CHANGES)
    return out
