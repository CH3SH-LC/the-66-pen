"""Offline tests for the structured scene-observation projection.

Nothing here starts, connects to or drives Genshin, the Miliastra editor, the elevated
helper, the bridge, UAC or any live MCP session.  Nothing here performs a native read:
every input is either a *captured receipt copy* under ``fixtures/scene_observation/
captured/`` or a *reverse-case document* derived from one of those copies by the
mutation functions in this file.

    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.test_scene_observation

Re-derive the reverse-case fixtures and the provenance index from the captured receipts
(they must stay exactly these mutations):

    .runtime/mcp-venv/Scripts/python.exe -B backend/test_scene_observation.py --write-fixtures

The captured copies are byte copies of real receipts produced by the coordinator's live
lane on 2026-09-29; ``PROVENANCE.json`` records each one's origin path and digest, and
``ProvenanceTests`` re-checks those digests against the origin files on disk when they are
still present (read-only).  No fixture is ever labelled live, and every derived document
carries a ``_fixture`` marker with ``live: false`` so it cannot be read as an observation.
"""
from __future__ import annotations

import ast
import base64
import copy
import hashlib
import json
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import scene_observation as so  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'scene_observation'
CAPTURED = FIXTURES / 'captured'
DERIVED = FIXTURES / 'derived'
PROVENANCE = FIXTURES / 'PROVENANCE.json'

INSPECT = 'inspect-20260929-153108.before-context.json'
CREATE_BEFORE = 'create-20260929-152943.before-context.json'
CREATE_AFTER = 'create-20260929-152943.after-context.json'
CREATE_PROBE = 'create-20260929-152943.stdout.jsonl'

#: Real receipt files the captured copies came from, as recorded on 2026-09-29.
CAPTURED_ORIGINS = {
    INSPECT: '.runtime/game-executor/scene-cli/inspect/20260929-153108-edb0fcdf3e/'
             'before-context.json',
    CREATE_BEFORE: '.runtime/game-executor/scene-cli/20260929-152943-create-fec8fb05/'
                   'before-context.json',
    CREATE_AFTER: '.runtime/game-executor/scene-cli/20260929-152943-create-fec8fb05/'
                  'after-context.json',
    CREATE_PROBE: '.runtime/game-executor/scene-cli/20260929-152943-create-fec8fb05/'
                  'stdout.jsonl',
}

#: session identity from prepared.json of the inspect run (pid/tid/creation), and the
#: record's own two snapshots.  ``observedAt`` is that run's ``createdUtc``: it is the
#: closest recorded time for that read (the profile that was built for it), it is the
#: execution layer's claim and NOT something the decoded document can corroborate, which
#: is exactly why the projection labels its source instead of presenting it as read data.
INSPECT_SESSION = {
    'sessionPid': 16888,
    'sessionCreation': 134350619827987266,
    'sessionSource': 'query-only-window-process-thread-identity',
}
CREATE_SESSION = {
    'sessionPid': 16888,
    'sessionCreation': 134350619827987266,
    'sessionSource': 'query-only-window-process-thread-identity',
}
#: The create run's prepared.json records no createdUtc, so its fixtures are projected
#: with no observation time at all -- the honest answer for material with no timestamp.
CREATE_OBSERVED_AT = None
INSPECT_OBSERVED_AT = '2026-09-29T07:31:08.354049+00:00'

GEOMETRY_OBSERVED_AT = '2026-09-29T07:40:00.000000+00:00'
LABEL_TEXT = '石质元素立方体·测试标签'


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: pathlib.Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def items_bytes(items) -> int:
    """Independent re-implementation of the page byte accounting, for cross-checking."""
    return len(json.dumps(list(items), sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8'))


def flag_names(value: int, table) -> list:
    return [name for bit, name in sorted(table.items()) if value & bit]


def text_with_lf(text: str) -> bytes:
    """Serialise text with LF endings, as the repository .editorconfig requires."""
    return text.replace('\r\n', '\n').encode('utf-8')


def write_text_lf(path: pathlib.Path, text: str):
    """Write text without letting the platform translate newlines.

    ``Path.write_text`` opens in text mode, which on Windows turns every ``\\n`` into
    ``\\r\\n``.  That silently rewrote this module's own fixtures to CRLF once, against the
    repository's ``end_of_line = lf`` -- and the digest check that was supposed to catch it
    read the file back through the same translation, so it reported "identical" while the
    bytes had changed.  Both halves of that are fixed here: this writer never translates,
    and the fixture tests compare raw bytes rather than re-parsed text.
    """
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(text)


def serialised_document(document) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + '\n'


# --------------------------------------------------------------------------- #
# mutation recipes: the reverse cases, each derived from a captured receipt copy
# --------------------------------------------------------------------------- #

def _set_snapshot_flags(document, *, add=0, clear=0):
    document['flags']['value'] = (document['flags']['value'] | add) & ~clear
    document['flags']['names'] = flag_names(document['flags']['value'], so.SNAPSHOT_FLAGS)


def _set_entity_flags(document, index, *, add=0, clear=0):
    row = document['entities'][index]
    row['flags']['value'] = (row['flags']['value'] | add) & ~clear
    row['flags']['names'] = flag_names(row['flags']['value'], so.ENTITY_FLAGS)


def mutation_truncated(document):
    """A capture that stopped short: 15 rows read out of 512 known-valid entries.

    Uses the receipt's own two signals for this -- the ``entities_truncated`` snapshot
    flag (bit 32 of build_readonly_profile.SNAPSHOT_FLAGS) and ``captured < valid`` --
    plus the matching non-ok status (8, partial_entities).
    """
    document['counts'].update(entityCapacity=512, entityValidEntries=512, entityCaptured=15,
                              entityRejected=0)
    _set_snapshot_flags(document, add=so.TRUNCATION_FLAG, clear=8)
    document['status'] = {'value': 8, 'name': 'partial_entities'}
    return document


def mutation_entity_read_failure(document):
    """One or more entity rows failed to read while the overall status stayed ok.

    Bit 64 of the snapshot flags.  The set may look whole and is not.
    """
    _set_snapshot_flags(document, add=so.READ_FAILURE_FLAG)
    return document


def mutation_duplicate_identity(document):
    """Two rows carry the same entity id and the same dictionary key.

    Built by copying row 12's id/key onto row 13, i.e. the shape a mis-read or a lost row
    would produce.  A projection that de-duplicated this would hide a read error.
    """
    row, source = document['entities'][13], document['entities'][12]
    row['id'] = source['id']
    row['dictionaryKey'] = source['dictionaryKey']
    return document


def mutation_key_id_mismatch(document):
    """A row whose dictionary key is not its id, with both still present."""
    document['entities'][5]['dictionaryKey'] = 999999999
    return document


def mutation_wrong_level(document):
    """The receipt observed a different level than the handle it is projected under.

    Built by changing only levelObservation.levelId, so projecting it under the real
    handle level (1073741839) must refuse while projecting it under 1073741834 must work.
    """
    document['levelObservation']['levelId'] = 1073741834
    return document


def mutation_position_known(document):
    """Two rows carry a read position; one of them is exactly the origin.

    A real receipt in this project reads ``position: null`` for every entity, so this is a
    derived case -- it exists to prove the non-null path is not dead code and that a real
    (0, 0, 0) is distinguishable from an unknown position.
    """
    for index in (0, 13):
        _set_entity_flags(document, index, add=so.POSITION_FLAG)
    document['entities'][0]['position'] = [0.0, 0.0, 0.0]
    document['entities'][13]['position'] = [-20.5, 3.25, 8.0]
    return document


def mutation_labels_and_geometry(document):
    """Caller labels (multi-byte) plus geometry from a different source and time.

    Geometry keyed by entity id with its own source kind and observation time; labels the
    same.  One key matches no entity, so the unmatched-key path is exercised too.
    """
    document['labels'] = {
        '1077936132': {
            'text': LABEL_TEXT,
            'source': {'kind': 'caller-label', 'observedAt': None, 'derived': True,
                       'note': 'a label a caller attached; it is not a read'},
        },
    }
    document['geometry'] = {
        '1086324737': {
            'position': [12.5, -3.0, 40.25],
            'source': {'kind': 'formal-save-gil-parse',
                       'path': 'external/formal-save-parse.json', 'sha256': '0' * 64,
                       'observedAt': GEOMETRY_OBSERVED_AT, 'derived': False},
        },
        '4242424242': {'position': [1.0, 2.0, 3.0],
                       'source': {'kind': 'formal-save-gil-parse', 'observedAt': None}},
    }
    return document


def mutation_subsystems_refused(document):
    """Both subsystems present but refused, with the decoders' own refusal names.

    The reason strings are the ones the decoders produce: native_lifecycle_type.py builds
    ``'LIFECYCLE_STATUS_' + STATUS[status]`` and also reports ``LIFECYCLE_FLAGS_OR_PARSER``
    and ``LIFECYCLE_INITIALIZATION``; the scheduler uses the same ``SCHEDULER_STATUS_``
    shape.  ``levelCatalog`` is not a subsystem this projection knows, so it must show up
    as unrecognised rather than being dropped.
    """
    document['subsystems'] = {
        'lifecycleType': {
            'ok': False, 'status': 'baseline_refused',
            'reasons': ['LIFECYCLE_STATUS_baseline_refused', 'LIFECYCLE_FLAGS_OR_PARSER',
                        'LIFECYCLE_INITIALIZATION'],
            'counts': {'slotCountBefore': 0, 'slotCountAfter': 0, 'initializedBefore': 0,
                       'initializedAfter': 0},
            'rows': [],
        },
        'schedulerCoroutines': {
            'ok': False, 'status': 'baseline_refused',
            'reasons': ['SCHEDULER_STATUS_baseline_refused'],
            'counts': {'listCountBefore': 0, 'listCountAfter': 0, 'targetCount': 0},
            'rows': [],
        },
        'levelCatalog': {'ok': True, 'status': 'ok', 'rows': [], 'counts': {}},
    }
    return document


def mutation_subsystems_ok(document):
    """One subsystem read successfully, the other not supplied at all."""
    document['subsystems'] = {
        'lifecycleType': {
            'ok': True, 'status': 'ok', 'reasons': [],
            'counts': {'slotCountBefore': 9, 'slotCountAfter': 9, 'initializedBefore': 1,
                       'initializedAfter': 1},
            'rows': [{'index': 6, 'slot': '0x9037840'}],
            'observation': {'note': 'row list is a decoder product, carried verbatim'},
        },
    }
    return document


def mutation_acceptance_rejected(document):
    """The native read-only acceptance rejected the receipt's own claims.

    The read itself succeeded, so ``readable`` stays true; what the acceptance rejects is
    the completeness claim, and its reasons must come through verbatim.
    """
    document['acceptance'] = {
        'ok': False,
        'reasons': ['SNAPSHOT_REQUIRED_FLAGS', 'COMPLETE_ENTITY_SET'],
        'source': 'inspect/20260929-153108-edb0fcdf3e/readonly-acceptance.json',
    }
    return document


def mutation_count_mismatch(document):
    """The counts claim 16 captured rows while the array holds 15."""
    document['counts'].update(entityCaptured=16, entityValidEntries=16, entityCapacity=17)
    return document


def mutation_unreadable_empty(document):
    """A receipt whose read failed and which therefore carries no rows at all.

    Status 3 (unreadable) with the entity counts zeroed and the entity flags cleared.
    Both a failed read and an empty array -- the shape that most easily gets mistaken for
    "there are no entities".
    """
    document['status'] = {'value': 3, 'name': 'unreadable'}
    document['counts'].update(entityCapacity=17, entityValidEntries=0, entityCaptured=0,
                             entityRejected=0)
    document['entities'] = []
    document['flags']['value'] = 1024          # only level_observed survives
    document['flags']['names'] = flag_names(document['flags']['value'], so.SNAPSHOT_FLAGS)
    return document


#: name -> (base captured fixture, mutation function, one-line description)
MUTATIONS = {
    'truncated': (CREATE_AFTER, mutation_truncated,
                  'capture stopped at 15 of 512 known-valid rows; entities_truncated set'),
    'entity-read-failure': (CREATE_AFTER, mutation_entity_read_failure,
                            'entity_read_failure flag set while the status still reads ok'),
    'duplicate-identity': (CREATE_AFTER, mutation_duplicate_identity,
                           'two rows carry the same id and dictionary key'),
    'key-id-mismatch': (CREATE_AFTER, mutation_key_id_mismatch,
                        'a row whose dictionary key is not its id'),
    'wrong-level': (CREATE_AFTER, mutation_wrong_level,
                    'levelObservation.levelId differs from the handle level'),
    'position-known': (CREATE_AFTER, mutation_position_known,
                       'two rows carry a read position, one exactly (0, 0, 0)'),
    'labels-geometry-multibyte': (CREATE_AFTER, mutation_labels_and_geometry,
                                  'multi-byte caller label plus geometry from another '
                                  'source and time, one key matching no entity'),
    'subsystems-refused': (INSPECT, mutation_subsystems_refused,
                           'both subsystems present with a refusal status, plus an '
                           'unrecognised subsystem name'),
    'subsystems-ok': (INSPECT, mutation_subsystems_ok,
                      'one subsystem read ok, the other not supplied'),
    'acceptance-rejected': (CREATE_AFTER, mutation_acceptance_rejected,
                            'native acceptance rejects the completeness claim'),
    'count-mismatch': (CREATE_AFTER, mutation_count_mismatch,
                       'counts claim 16 captured rows while the array holds 15'),
    'unreadable-empty': (CREATE_AFTER, mutation_unreadable_empty,
                         'a failed read with an empty entity array'),
}

CAPTURED_NOTES = {
    INSPECT: 'decoded read-only context snapshot of the current level, 15 entities, '
             'flags 1951, taken by the coordinator\'s live lane',
    CREATE_BEFORE: 'decoded context snapshot before the reviewed create of 2026-09-29 '
                   '15:29:43, 14 entities',
    CREATE_AFTER: 'decoded context snapshot after that create, 15 entities; the added '
                  'entity is 1077936132 (template 20001034)',
    CREATE_PROBE: 'the raw probe receipt for that create: one JSON object carrying '
                  'snapshotHex (before) and afterSnapshotHex',
}


def build_derived_document(name):
    base, mutation, description = MUTATIONS[name]
    document = load_json(CAPTURED / base)
    document = mutation(copy.deepcopy(document))
    marker = {
        'kind': 'derived-reverse-case',
        'live': False,
        'notARealObservation': True,
        'derivedFrom': 'captured/%s' % base,
        'derivedFromSha256': sha256_file(CAPTURED / base),
        'mutation': name,
        'mutationDescription': description,
        'note': 'produced by backend/test_scene_observation.py --write-fixtures; a '
                'reverse case, not something any read returned',
    }
    return {'_fixture': marker, **document}


def derived_file_name(name) -> str:
    return '%s.derived.json' % name


def build_provenance():
    fixtures = {}
    for name, origin in CAPTURED_ORIGINS.items():
        fixtures['captured/%s' % name] = {
            'kind': 'captured-receipt-copy',
            'live': False,
            'originPath': origin,
            'originSha256': sha256_file(CAPTURED / name),
            'fixtureSha256': sha256_file(CAPTURED / name),
            'note': CAPTURED_NOTES[name],
        }
    for name, (base, _mutation, description) in MUTATIONS.items():
        relative = 'derived/%s' % derived_file_name(name)
        fixtures[relative] = {
            'kind': 'derived-reverse-case',
            'live': False,
            'notARealObservation': True,
            'derivedFrom': 'captured/%s' % base,
            'derivedFromSha256': sha256_file(CAPTURED / base),
            'mutation': name,
            'mutationDescription': description,
            'fixtureSha256': sha256_file(DERIVED / derived_file_name(name)),
        }
    return {
        'schemaVersion': 1,
        'live': False,
        'generatedBy': 'backend/test_scene_observation.py --write-fixtures',
        'note': 'no fixture here is a live observation; captured entries are byte copies '
                'of receipts the coordinator\'s live lane produced on 2026-09-29 and '
                'derived entries are documented mutations of those copies',
        'fixtures': fixtures,
    }


def write_fixtures():
    DERIVED.mkdir(parents=True, exist_ok=True)
    for name in MUTATIONS:
        path = DERIVED / derived_file_name(name)
        write_text_lf(path, serialised_document(build_derived_document(name)))
    write_text_lf(PROVENANCE, serialised_document(build_provenance()))
    return len(MUTATIONS) + 1


# --------------------------------------------------------------------------- #
# projections used by the tests
# --------------------------------------------------------------------------- #

IDENTITY_BY_FIXTURE = {
    INSPECT: {'targetHandle': 'fixture-handle:inspect-20260929-153108',
              'levelId': 1073741839, 'observedAt': INSPECT_OBSERVED_AT,
              'sessionPid': INSPECT_SESSION['sessionPid'],
              'sessionCreation': INSPECT_SESSION['sessionCreation'],
              'sessionSource': INSPECT_SESSION['sessionSource']},
    CREATE_BEFORE: {'targetHandle': 'fixture-handle:create-20260929-152943',
                    'levelId': 1073741839, 'observedAt': CREATE_OBSERVED_AT,
                    'sessionPid': CREATE_SESSION['sessionPid'],
                    'sessionCreation': CREATE_SESSION['sessionCreation'],
                    'sessionSource': CREATE_SESSION['sessionSource']},
    CREATE_AFTER: {'targetHandle': 'fixture-handle:create-20260929-152943',
                   'levelId': 1073741839, 'observedAt': CREATE_OBSERVED_AT,
                   'sessionPid': CREATE_SESSION['sessionPid'],
                   'sessionCreation': CREATE_SESSION['sessionCreation'],
                   'sessionSource': CREATE_SESSION['sessionSource']},
}


def identity_for(name, **overrides):
    """Identity for a captured or derived fixture.

    A derived document has no receipt of its own, so it is projected with no receipt path
    and no digest rather than borrowing the base receipt's -- that would claim the derived
    file had been read.
    """
    if name in IDENTITY_BY_FIXTURE:
        identity = dict(IDENTITY_BY_FIXTURE[name])
        identity['receiptPath'] = 'captured/%s' % name
        identity['receiptSha256'] = sha256_file(CAPTURED / name)
    else:
        base = MUTATIONS[name][0]
        identity = dict(IDENTITY_BY_FIXTURE[base])
        identity['receiptPath'] = None
        identity['receiptSha256'] = None
    identity.update(overrides)
    return identity


def document_for(name):
    path = CAPTURED / name if name in CAPTURED_ORIGINS else DERIVED / derived_file_name(name)
    return load_json(path)


def project(name, **overrides):
    return so.project_snapshot(document_for(name), identity=identity_for(name, **overrides))


def project_document(document, name, **overrides):
    return so.project_snapshot(document, identity=identity_for(name, **overrides))


def refusal_codes(projection) -> set:
    return {entry['code'] for entry in projection['refusals']}


def entity_by_id(projection, entity_id):
    for row in projection['entities']:
        if row['entityId'] == entity_id:
            return row
    raise AssertionError('entity %s not in projection' % entity_id)


# --------------------------------------------------------------------------- #
# fixture provenance
# --------------------------------------------------------------------------- #

class ProvenanceTests(unittest.TestCase):
    def test_no_fixture_is_labelled_live(self):
        recorded = load_json(PROVENANCE)
        self.assertIs(recorded['live'], False)
        self.assertTrue(recorded['fixtures'])
        for name, entry in recorded['fixtures'].items():
            self.assertIs(entry['live'], False, name)

    def test_every_fixture_file_is_accounted_for(self):
        recorded = load_json(PROVENANCE)['fixtures']
        on_disk = {'captured/%s' % path.name for path in CAPTURED.glob('*')}
        on_disk |= {'derived/%s' % path.name for path in DERIVED.glob('*')}
        self.assertEqual(sorted(on_disk - set(recorded)), [])
        self.assertEqual(sorted(set(recorded) - on_disk), [])

    def test_recorded_digests_match_the_files_on_disk(self):
        for name, entry in load_json(PROVENANCE)['fixtures'].items():
            path = FIXTURES / name
            self.assertEqual(sha256_file(path), entry['fixtureSha256'], name)

    def test_captured_copies_are_byte_copies_of_a_recorded_origin(self):
        recorded = load_json(PROVENANCE)['fixtures']
        for name, entry in sorted(recorded.items()):
            if entry['kind'] != 'captured-receipt-copy':
                continue
            self.assertTrue(entry['originPath'], name)
            self.assertEqual(entry['fixtureSha256'], entry['originSha256'],
                             '%s claims to be a byte copy' % name)

    def test_captured_origin_digests_still_match_the_live_lane_when_present(self):
        """Read-only cross-check against the coordinator's evidence, when it is still there."""
        captured = {name: entry for name, entry in
                    sorted(load_json(PROVENANCE)['fixtures'].items())
                    if entry['kind'] == 'captured-receipt-copy'}
        present = {name: entry for name, entry in captured.items()
                   if (ROOT / entry['originPath']).is_file()}
        if not present:
            self.skipTest('none of the receipt origins are still present in this checkout')
        for name, entry in present.items():
            self.assertEqual(sha256_file(ROOT / entry['originPath']),
                             entry['originSha256'], entry['originPath'])
        self.assertLessEqual(len(present), len(captured))

    def test_derived_fixtures_are_exact_declared_mutations_of_a_captured_copy(self):
        recorded = load_json(PROVENANCE)['fixtures']
        for name in MUTATIONS:
            relative = 'derived/%s' % derived_file_name(name)
            entry = recorded[relative]
            self.assertEqual(entry['kind'], 'derived-reverse-case')
            self.assertIs(entry['notARealObservation'], True)
            self.assertEqual(entry['derivedFrom'], 'captured/%s' % MUTATIONS[name][0])
            on_disk = load_json(DERIVED / derived_file_name(name))
            self.assertEqual(canonical_bytes(on_disk),
                             canonical_bytes(build_derived_document(name)),
                             '%s is not exactly the declared mutation' % name)
            self.assertEqual(on_disk['_fixture']['live'], False)
            # Byte level too, so a line-ending or serialisation drift cannot pass.
            self.assertEqual((DERIVED / derived_file_name(name)).read_bytes(),
                             text_with_lf(serialised_document(build_derived_document(name))),
                             '%s differs at the byte level' % name)

    def test_provenance_index_is_reproducible(self):
        self.assertEqual(canonical_bytes(load_json(PROVENANCE)), canonical_bytes(build_provenance()))
        self.assertEqual(PROVENANCE.read_bytes(),
                         text_with_lf(serialised_document(build_provenance())))

    def test_the_delivered_text_files_follow_the_repository_line_ending(self):
        """The repository .editorconfig asks for LF, and backend/*.py already is LF.

        This test exists because it was a real defect found while writing this task: a
        scratch script rewrote this module's own fixtures through text mode on Windows
        (every ``\\n`` becoming ``\\r\\n``), and the digest check that was supposed to catch
        it read the file back through the same translation, so it reported "identical"
        while the bytes had changed.
        """
        self.assertNotIn(b'\r\n', pathlib.Path(so.__file__).read_bytes())
        self.assertNotIn(b'\r\n', pathlib.Path(__file__).read_bytes())
        for path in sorted(DERIVED.iterdir()):
            self.assertNotIn(b'\r\n', path.read_bytes(), path.name)
        self.assertNotIn(b'\r\n', PROVENANCE.read_bytes())
        self.assertNotIn(b'\r\n', (CAPTURED / INSPECT).read_bytes())

    def test_captured_fixtures_carry_no_fixture_marker(self):
        for name in CAPTURED_ORIGINS:
            self.assertNotIn('_fixture', load_json(CAPTURED / name), name)
        self.assertIsNone(project(INSPECT)['fixtureMarker'])

    def test_derived_marker_is_surfaced_on_the_projection(self):
        projection = project('truncated')
        self.assertEqual(projection['fixtureMarker']['kind'], 'derived-reverse-case')
        self.assertIs(projection['fixtureMarker']['live'], False)

    def test_a_derived_marker_claiming_to_be_live_is_refused(self):
        document = document_for('truncated')
        document['_fixture']['live'] = True
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, 'truncated')
        self.assertEqual(caught.exception.code, 'FIXTURE_MARKER_INVALID')


# --------------------------------------------------------------------------- #
# the module's own surface
# --------------------------------------------------------------------------- #

class ContractSurfaceTests(unittest.TestCase):
    EXPECTED_API = {
        'SCHEMA_VERSION', 'CONTRACT_ID', 'SUPPORTED_INPUTS', 'EXECUTION_SURFACE',
        'STATUS_NAMES', 'SNAPSHOT_FLAGS', 'ENTITY_FLAGS', 'REQUIRED_SNAPSHOT_FLAGS',
        'IDENTITY_FLAGS', 'DECLARED_ATTRIBUTES', 'UNSOURCED_ATTRIBUTES',
        'SUBSYSTEM_NAMES', 'SUBSYSTEM_STATUS_NAMES', 'ObservationError', 'input_kind',
        'project_snapshot', 'get_entity', 'page_entities', 'diff_snapshots',
    }

    def test_public_api_is_the_declared_closed_set(self):
        self.assertEqual(set(so.__all__), self.EXPECTED_API)
        for name in so.__all__:
            self.assertTrue(hasattr(so, name), name)

    def test_module_contains_no_execution_surface(self):
        """Structural check, not a grep: no import or call that could reach the outside."""
        tree = ast.parse(pathlib.Path(so.__file__).read_text(encoding='utf-8'))
        forbidden_modules = {
            'subprocess', 'os', 'socket', 'shutil', 'ctypes', 'importlib', 'sys',
            'pathlib', 'urllib', 'http', 'requests', 'asyncio', 'multiprocessing',
            'winreg', 'signal', 'atexit', 'tempfile',
        }
        forbidden_names = {'eval', 'exec', 'compile', '__import__', 'open', 'input',
                           'breakpoint'}
        forbidden_attributes = {'system', 'popen', 'run', 'call', 'check_output',
                                'spawn', 'fork', 'connect'}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names
                          if a.name.split('.')[0] in forbidden_modules]
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or '').split('.')[0]
                if root in forbidden_modules:
                    found.append(root)
            elif isinstance(node, ast.Name) and node.id in forbidden_names:
                found.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                found.append('.' + node.attr)
        self.assertEqual(found, [], 'execution surface found in scene_observation.py: %s'
                                    % sorted(set(found)))

    def test_the_declared_execution_surface_is_all_false(self):
        self.assertTrue(so.EXECUTION_SURFACE)
        for key, value in so.EXECUTION_SURFACE.items():
            self.assertIs(value, False, key)

    def test_no_public_function_takes_a_path_or_a_command(self):
        forbidden = {'path', 'paths', 'command', 'cmd', 'argv', 'script', 'exe',
                     'executable', 'queue', 'helper', 'request', 'plan'}
        import inspect
        for name in ('input_kind', 'project_snapshot', 'get_entity', 'page_entities',
                     'diff_snapshots'):
            parameters = set(inspect.signature(getattr(so, name)).parameters)
            self.assertEqual(parameters & forbidden, set(), name)

    def test_a_file_path_is_refused_rather_than_read(self):
        """A path is not an input: the module must not open it, and says so."""
        for value in ('fixtures/scene_observation/captured/x.json',
                      pathlib.Path('fixtures/scene_observation/captured/x.json')):
            with self.assertRaises(so.ObservationError) as caught:
                so.project_snapshot(value, identity=identity_for(INSPECT))
            self.assertEqual(caught.exception.code, 'DOCUMENT_SHAPE_UNSUPPORTED')
            self.assertEqual(caught.exception.detail['inputKind'], 'not-a-mapping')

    def test_supported_inputs_name_only_the_decoded_document(self):
        self.assertEqual(so.SUPPORTED_INPUTS, ('decoded-context-document',))

    def test_the_raw_probe_receipt_is_refused_with_a_reason(self):
        """The module does not decode the probe hex; it must say so, not half-read it."""
        record = json.loads((CAPTURED / CREATE_PROBE).read_text(encoding='utf-8').strip())
        self.assertEqual(so.input_kind(record), 'raw-probe-record')
        self.assertEqual(record['pid'], INSPECT_SESSION['sessionPid'])
        self.assertEqual(len(record['snapshotHex']), record['snapshotBytes'] * 2)
        self.assertEqual(len(record['afterSnapshotHex']), record['snapshotBytes'] * 2)
        with self.assertRaises(so.ObservationError) as caught:
            so.project_snapshot(record, identity=identity_for(CREATE_AFTER))
        self.assertEqual(caught.exception.code, 'INPUT_KIND_UNSUPPORTED')
        self.assertEqual(caught.exception.detail['supportedInputs'],
                         list(so.SUPPORTED_INPUTS))

    def test_an_unimplemented_document_version_is_refused(self):
        document = document_for(INSPECT)
        document['version'] = 3
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, INSPECT)
        self.assertEqual(caught.exception.code, 'DOCUMENT_VERSION_UNSUPPORTED')

    def test_unknown_flag_bits_and_status_values_are_refused(self):
        document = document_for(INSPECT)
        document['flags']['value'] |= 4096
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, INSPECT)
        self.assertEqual(caught.exception.code, 'DOCUMENT_FLAGS_UNKNOWN_BITS')
        document = document_for(INSPECT)
        document['status'] = {'value': 99, 'name': 'invented'}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, INSPECT)
        self.assertEqual(caught.exception.code, 'DOCUMENT_STATUS_UNKNOWN')


# --------------------------------------------------------------------------- #
# the real receipts
# --------------------------------------------------------------------------- #

class RealReceiptProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inspect = project(INSPECT)
        cls.before = project(CREATE_BEFORE)
        cls.after = project(CREATE_AFTER)

    def test_inspect_receipt_projects_every_entity_and_field(self):
        projection = self.inspect
        self.assertEqual(projection['status'], {'value': 0, 'name': 'ok'})
        self.assertEqual(projection['levelId'], 1073741839)
        self.assertEqual(projection['levelObservation']['verified'], True)
        self.assertEqual(projection['counts']['entityCapacity'], 17)
        self.assertEqual(projection['counts']['entityValidEntries'], 15)
        self.assertEqual(projection['counts']['entityCaptured'], 15)
        self.assertEqual(projection['counts']['entityRejected'], 0)
        self.assertEqual(projection['capturedCount'], 15)
        self.assertEqual(projection['totalCount'], 15)
        self.assertEqual(projection['capacity'], 17)
        self.assertEqual(len(projection['entities']), 15)
        self.assertEqual(projection['entityIds'],
                         [1086324737, 1086324738, 1086324739, 1086324740, 1086324741,
                          1086324742, 1086324743, 1086324744, 1077936129, 1086324745,
                          1077936130, 1094713345, 1077936131, 1077936132, 1090519041])
        self.assertEqual(projection['entityIds'],
                         [row['id'] for row in load_json(CAPTURED / INSPECT)['entities']])

    def test_the_projection_reports_the_receipts_own_completeness(self):
        for projection in (self.inspect, self.after):
            self.assertIs(projection['readable'], True)
            self.assertIs(projection['complete'], True)
            self.assertIs(projection['trusted'], True)
            self.assertIs(projection['truncated'], False)
            self.assertEqual(projection['refusals'], [])
            self.assertEqual(projection['invalidatingRefusals'], [])

    def test_flag_and_status_names_are_recomputed_from_the_bit_tables(self):
        projection = self.inspect
        self.assertEqual(projection['flags']['value'], 1951)
        self.assertEqual(projection['flags']['names'],
                         ['build_verified', 'origin_read', 'contexts_complete',
                          'entities_complete', 'structure_rechecked', 'stack_captured',
                          'stack_verified', 'hotfix_default_confirmed', 'level_observed'])
        self.assertEqual(projection['flags']['names'],
                         flag_names(1951, so.SNAPSHOT_FLAGS))
        self.assertNotIn('FLAG_NAMES_MISMATCH', refusal_codes(projection))
        self.assertNotIn('DOCUMENT_STATUS_NAME_MISMATCH', refusal_codes(projection))
        for row in projection['entities']:
            self.assertEqual(row['flags']['value'], 79)
            self.assertEqual(row['flags']['names'],
                             ['id_read', 'config_id_read', 'context_match', 'key_match',
                              'context_read'])

    def test_a_receipt_whose_labels_contradict_its_bits_is_untrusted(self):
        document = document_for(INSPECT)
        document['flags']['names'] = ['build_verified']
        projection = project_document(document, INSPECT)
        self.assertIs(projection['trusted'], False)
        self.assertEqual(
            [r['detail'] for r in projection['refusals']
             if r['code'] == 'FLAG_NAMES_MISMATCH'][0]['recomputed'],
            flag_names(1951, so.SNAPSHOT_FLAGS))

    def test_every_entity_carries_provenance_for_every_declared_attribute(self):
        for projection in (self.inspect, self.before, self.after):
            for row in projection['entities']:
                self.assertEqual(sorted(row['fieldProvenance']),
                                 sorted(so.DECLARED_ATTRIBUTES), row['index'])
                for attribute, entry in row['fieldProvenance'].items():
                    self.assertIn(entry['status'], ('known', 'unknown', 'unavailable'))
                    self.assertIn('sourceKind', entry)
                    self.assertIn('observedAt', entry)
                    self.assertIsInstance(entry['derived'], bool)
                    if entry['status'] == 'known':
                        self.assertIn(attribute, row['knownAttributes'], attribute)
                    else:
                        self.assertNotIn(attribute, row['knownAttributes'], attribute)
                self.assertEqual(sorted(u['field'] for u in row['unknownFields']),
                                 sorted(a for a, e in row['fieldProvenance'].items()
                                        if e['status'] != 'known'))

    def test_null_native_position_stays_unknown_and_is_never_zero(self):
        """Every real entity reads position: null -- all 15 must be unknown, none 0."""
        for projection in (self.inspect, self.before, self.after):
            for row in projection['entities']:
                self.assertNotIn('position', row['knownAttributes'], row['entityId'])
                entry = row['fieldProvenance']['position']
                self.assertEqual(entry['status'], 'unknown')
                self.assertIsNone(entry['source'])
                self.assertIs(entry['derived'], False)
                reasons = {u['field']: u['reason'] for u in row['unknownFields']}
                self.assertIn('NOT zero', reasons['position'])

    def test_unsourced_attributes_are_declared_not_guessed(self):
        projection = self.inspect
        self.assertEqual(sorted(projection['unsupportedAttributes']),
                         sorted(so.UNSOURCED_ATTRIBUTES))
        for attribute in so.UNSOURCED_ATTRIBUTES:
            row = projection['entities'][0]
            self.assertEqual(row['fieldProvenance'][attribute]['status'], 'unknown')
            self.assertEqual(row['fieldProvenance'][attribute]['sourceKind'],
                             'not-implemented')
            self.assertIs(row['fieldProvenance'][attribute]['unsupportedByContract'], True)

    def test_the_template_id_is_marked_derived_and_the_config_id_is_not(self):
        row = entity_by_id(self.after, 1077936132)
        self.assertEqual(row['templateId'], 20001034)
        self.assertEqual(row['knownAttributes']['configId'], 20001034)
        self.assertIs(row['fieldProvenance']['templateId']['derived'], True)
        self.assertEqual(row['fieldProvenance']['templateId']['sourceKind'],
                         'native-entity-config-id')
        self.assertIs(row['fieldProvenance']['configId']['derived'], False)

    def test_snapshot_identity_is_bound_to_the_handle_not_only_to_the_content(self):
        baseline = project(INSPECT)
        renamed = project(INSPECT, targetHandle='fixture-handle:other')
        self.assertNotEqual(baseline['snapshotId'], renamed['snapshotId'])
        self.assertEqual(baseline['contentDigest'], renamed['contentDigest'])

    def test_content_digest_ignores_the_observation_time_but_the_snapshot_id_does_not(self):
        baseline = project(INSPECT)
        later = project(INSPECT, observedAt='2026-09-29T08:00:00.000000+00:00')
        self.assertEqual(baseline['contentDigest'], later['contentDigest'])
        self.assertNotEqual(baseline['snapshotId'], later['snapshotId'])

    def test_projection_is_deterministic_and_json_serializable(self):
        first, second = project(INSPECT), project(INSPECT)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        text = json.dumps(first, ensure_ascii=False, allow_nan=False)
        self.assertEqual(json.loads(text)['snapshotId'], first['snapshotId'])

    def test_receipt_field_names_and_session_come_from_where_they_claim(self):
        projection = self.inspect
        self.assertEqual(projection['receipt']['snapshotField'], 'snapshotHex')
        self.assertTrue(projection['receipt']['path'].endswith(INSPECT))
        self.assertEqual(projection['receipt']['sha256'], sha256_file(CAPTURED / INSPECT))
        self.assertEqual(projection['session'],
                         {'sessionPid': 16888, 'sessionCreation': 134350619827987266,
                          'sessionSource': 'query-only-window-process-thread-identity'})
        self.assertEqual(projection['observedAtSource'], 'execution-layer')
        self.assertEqual(projection['unrecognizedDocumentKeys'], [])
        self.assertEqual(projection['unrecognizedIdentityKeys'], [])


class IdentityTests(unittest.TestCase):
    def test_a_handle_is_required_and_never_minted(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.project_snapshot(document_for(INSPECT), identity={'levelId': 1073741839})
        self.assertEqual(caught.exception.code, 'IDENTITY_HANDLE_REQUIRED')

    def test_a_level_is_required(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.project_snapshot(document_for(INSPECT), identity={'targetHandle': 'h'})
        self.assertEqual(caught.exception.code, 'IDENTITY_LEVEL_REQUIRED')
        with self.assertRaises(so.ObservationError) as caught:
            so.project_snapshot(document_for(INSPECT),
                                identity={'targetHandle': 'h', 'levelId': '1073741839'})
        self.assertEqual(caught.exception.code, 'IDENTITY_LEVEL_REQUIRED')

    def test_an_observation_time_is_never_invented(self):
        projection = project(CREATE_AFTER)
        self.assertIsNone(projection['observedAt'])
        self.assertEqual(projection['observedAtSource'], 'unavailable')
        self.assertIsNone(projection['observationTimes']['snapshot'])

    def test_unrecognised_document_and_identity_keys_are_surfaced(self):
        document = document_for(INSPECT)
        document['somethingNew'] = {'value': 1}
        projection = project_document(document, INSPECT, somethingNew='x')
        self.assertEqual(projection['unrecognizedDocumentKeys'], ['somethingNew'])
        self.assertEqual(projection['unrecognizedIdentityKeys'], ['somethingNew'])

    def test_a_receipt_with_no_verified_level_is_not_given_one(self):
        document = document_for(INSPECT)
        document['levelObservation'] = {'verified': False, 'levelId': None, 'method': None}
        projection = project_document(document, INSPECT)
        self.assertIsNone(projection['levelId'])
        self.assertIs(projection['trusted'], True)

    def test_a_verified_level_with_no_id_is_refused(self):
        document = document_for(INSPECT)
        document['levelObservation'] = {'verified': True, 'levelId': None}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, INSPECT)
        self.assertEqual(caught.exception.code, 'DOCUMENT_LEVEL_OBSERVATION_UNSUPPORTED')

    def test_the_handle_level_and_the_observed_level_must_be_the_same(self):
        with self.assertRaises(so.ObservationError) as caught:
            project('wrong-level')
        self.assertEqual(caught.exception.code, 'WRONG_LEVEL')
        self.assertEqual(caught.exception.detail['handleLevelId'], 1073741839)
        self.assertEqual(caught.exception.detail['observedLevelId'], 1073741834)
        same = project('wrong-level', levelId=1073741834)
        self.assertEqual(same['levelId'], 1073741834)
        self.assertIs(same['trusted'], True)


# --------------------------------------------------------------------------- #
# reverse cases
# --------------------------------------------------------------------------- #

class ReverseCaseTests(unittest.TestCase):
    def test_truncated_capture_is_incomplete_and_says_why(self):
        projection = project('truncated')
        self.assertIs(projection['truncated'], True)
        self.assertIs(projection['complete'], False)
        self.assertIs(projection['readable'], True)
        self.assertIs(projection['trusted'], True)
        self.assertEqual(projection['capturedCount'], 15)
        self.assertEqual(projection['totalCount'], 512)
        self.assertEqual(projection['capacity'], 512)
        self.assertIn('ENTITIES_TRUNCATED', refusal_codes(projection))
        detail = [r for r in projection['refusals'] if r['code'] == 'ENTITIES_TRUNCATED'][0]
        self.assertEqual(detail['detail']['flag'], 'entities_truncated')
        self.assertIn('ENTITY_SET_SHORT_OF_VALID_ENTRIES', refusal_codes(projection))

    def test_an_entity_read_failure_is_surfaced_even_when_the_set_looks_whole(self):
        projection = project('entity-read-failure')
        self.assertEqual(len(projection['entities']), 15)
        self.assertEqual(projection['capturedCount'], projection['totalCount'], 15)
        self.assertIs(projection['truncated'], False)
        self.assertIs(projection['trusted'], True)
        self.assertIs(projection['complete'], False)
        self.assertIn('ENTITY_READ_FAILURE', refusal_codes(projection))

    def test_duplicate_identity_refuses_the_sets_trust_and_hides_nothing(self):
        projection = project('duplicate-identity')
        self.assertIs(projection['trusted'], False)
        self.assertIs(projection['complete'], False)
        self.assertIn('DUPLICATE_ENTITY_IDENTITY', refusal_codes(projection))
        self.assertIn('DUPLICATE_DICTIONARY_KEY', refusal_codes(projection))
        self.assertEqual(len(projection['entityIds']), 15)
        self.assertEqual(projection['entityIds'].count(1077936131), 2)
        with self.assertRaises(so.ObservationError) as caught:
            so.get_entity(projection, 1077936131)
        self.assertEqual(caught.exception.code, 'SNAPSHOT_UNTRUSTED')
        self.assertEqual(caught.exception.detail['duplicateIds'], [1077936131])

    def test_dictionary_key_id_mismatch_refuses_the_sets_trust(self):
        projection = project('key-id-mismatch')
        self.assertIs(projection['trusted'], False)
        self.assertIn('ENTITY_KEY_ID_MISMATCH', refusal_codes(projection))
        self.assertEqual(len(projection['entityIds']), 15)
        with self.assertRaises(so.ObservationError) as caught:
            so.get_entity(projection, 1086324742)
        self.assertEqual(caught.exception.code, 'SNAPSHOT_UNTRUSTED')

    def test_an_unreadable_empty_receipt_is_unknown_not_an_empty_success(self):
        """The case that matters most: a failed read must not read as "no entities"."""
        projection = project('unreadable-empty')
        self.assertEqual(projection['entities'], [])
        self.assertEqual(projection['entityIds'], [])
        self.assertIs(projection['readable'], False)
        self.assertIs(projection['complete'], False)
        self.assertIn('SNAPSHOT_STATUS_NOT_OK', refusal_codes(projection))
        self.assertIn('SNAPSHOT_REQUIRED_FLAGS_MISSING', refusal_codes(projection))
        self.assertEqual(projection['status']['name'], 'unreadable')

        diff = so.diff_snapshots(project('acceptance-rejected'), projection)
        self.assertEqual(diff['state'], 'unknown')
        self.assertEqual(diff['code'], 'SNAPSHOT_NOT_READABLE')
        self.assertIsNone(diff['added'])
        self.assertIsNone(diff['removed'])
        self.assertEqual(diff['unreadableSides'], ['after'])

        diff = so.diff_snapshots(project(CREATE_AFTER), projection)
        self.assertEqual(diff['state'], 'unknown')
        self.assertIsNone(diff['added'])
        self.assertIsNone(diff['removed'])
        self.assertEqual(diff['unreadableSides'], ['after'])
        self.assertIn('never as an empty set', ' '.join(diff['caveats']))

    def test_the_unreadable_guard_is_load_bearing(self):
        """A sensitivity control: widen the status set and the same receipt turns into a lie.

        ``unreadable-empty`` carries status 3 (unreadable) and no rows.  With the guard in
        place the diff says unknown.  Widen ``READABLE_STATUSES`` to admit status 3 and the
        identical code path reports "15 entities removed" against a complete snapshot --
        which is exactly the false reading the guard exists to prevent.  If this assertion
        ever stops holding, the guard has been bypassed somewhere else and the test above
        is no longer proof of anything.
        """
        projection = project('unreadable-empty')
        with mock.patch.object(so, 'READABLE_STATUSES', (0, 3, 5, 8)):
            widened = project_document(document_for('unreadable-empty'), 'unreadable-empty')
            self.assertIs(widened['readable'], True)
            diff = so.diff_snapshots(project(CREATE_AFTER), widened)
            self.assertEqual(diff['state'], 'observed')
            self.assertEqual(len(diff['removed']), 15)
        self.assertIs(projection['readable'], False)

    def test_a_rejected_acceptance_keeps_its_own_reasons_verbatim(self):
        projection = project('acceptance-rejected')
        self.assertIs(projection['readable'], True)
        self.assertIs(projection['trusted'], True)
        self.assertIs(projection['complete'], False)
        self.assertEqual(projection['acceptance']['ok'], False)
        self.assertEqual(projection['acceptance']['reasons'],
                         ['SNAPSHOT_REQUIRED_FLAGS', 'COMPLETE_ENTITY_SET'])
        entry = [r for r in projection['refusals']
                 if r['code'] == 'NATIVE_ACCEPTANCE_REJECTED'][0]
        self.assertEqual(entry['detail']['reasons'],
                         ['SNAPSHOT_REQUIRED_FLAGS', 'COMPLETE_ENTITY_SET'])

    def test_a_row_count_that_contradicts_the_counts_is_surfaced(self):
        projection = project('count-mismatch')
        self.assertEqual(len(projection['entities']), 15)
        self.assertEqual(projection['capturedCount'], 16)
        self.assertIs(projection['complete'], False)
        self.assertIn('ENTITY_SET_COUNT_MISMATCH', refusal_codes(projection))
        found = so.get_entity(projection, 1077936132)
        self.assertIs(found['found'], True)
        missing = so.get_entity(projection, 4242)
        self.assertIs(missing['found'], False)
        self.assertEqual(missing['absenceMeaning'],
                         'no-evidence-truncated-or-incomplete-snapshot')
        self.assertIsNotNone(missing['absenceReason'])

    def test_a_known_position_and_a_real_zero_are_distinguishable_from_unknown(self):
        projection = project('position-known')
        zero = entity_by_id(projection, 1086324737)
        self.assertEqual(zero['knownAttributes']['position'], [0.0, 0.0, 0.0])
        self.assertEqual(zero['fieldProvenance']['position']['sourceKind'],
                         'native-snapshot-position')
        self.assertIs(zero['fieldProvenance']['position']['derived'], False)
        self.assertNotIn('position', [u['field'] for u in zero['unknownFields']])

        unread = entity_by_id(projection, 1086324738)
        self.assertNotIn('position', unread['knownAttributes'])
        self.assertIn('position', [u['field'] for u in unread['unknownFields']])

        real = entity_by_id(projection, 1077936132)
        self.assertEqual(real['knownAttributes']['position'], [-20.5, 3.25, 8.0])

    def test_a_position_without_its_read_flag_is_refused_outright(self):
        document = document_for('position-known')
        document['entities'][0]['position'] = [1.0, 2.0, 3.0]      # position_read cleared
        _set_entity_flags(document, 0, clear=so.POSITION_FLAG)
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, 'position-known')
        self.assertEqual(caught.exception.code, 'DOCUMENT_ENTITY_POSITION_UNSOURCED')

    def test_a_position_marked_read_but_not_three_numbers_is_refused(self):
        document = document_for('position-known')
        document['entities'][0]['position'] = [0.0, None, 0.0]
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, 'position-known')
        self.assertEqual(caught.exception.code, 'DOCUMENT_ENTITY_POSITION_INVALID')

    def test_geometry_from_another_source_keeps_its_own_source_and_time(self):
        projection = project('labels-geometry-multibyte')
        row = entity_by_id(projection, 1086324737)
        self.assertEqual(row['knownAttributes']['position'], [12.5, -3.0, 40.25])
        entry = row['fieldProvenance']['position']
        self.assertEqual(entry['sourceKind'], 'formal-save-gil-parse')
        self.assertEqual(entry['observedAt'], GEOMETRY_OBSERVED_AT)
        self.assertNotEqual(entry['observedAt'], projection['observedAt'])
        self.assertEqual(entry['source']['path'], 'external/formal-save-parse.json')
        self.assertIs(projection['observationTimes']['attributeBound'], True)
        self.assertEqual(projection['observationTimes']['snapshot'], CREATE_OBSERVED_AT)
        self.assertEqual(projection['observationTimes']['external'], [GEOMETRY_OBSERVED_AT])
        self.assertIs(projection['mixedObservationTimes'], True)
        self.assertEqual(projection['externalBlocks'],
                         {'geometry': 1, 'labels': 1})

    def test_the_native_value_wins_and_the_conflict_is_surfaced(self):
        document = document_for('labels-geometry-multibyte')
        document['entities'][13]['position'] = [-20.5, 3.25, 8.0]
        _set_entity_flags(document, 13, add=so.POSITION_FLAG)
        document['geometry']['1077936132'] = {
            'position': [99.0, 99.0, 99.0],
            'source': {'kind': 'formal-save-gil-parse', 'observedAt': GEOMETRY_OBSERVED_AT},
        }
        projection = project_document(document, 'labels-geometry-multibyte')
        row = entity_by_id(projection, 1077936132)
        self.assertEqual(row['knownAttributes']['position'], [-20.5, 3.25, 8.0])
        self.assertIs(row['fieldProvenance']['position']['contested'], True)
        self.assertIn('ATTRIBUTE_SOURCE_CONFLICT', refusal_codes(projection))
        conflict = [c for c in projection['conflicts']
                    if c['entityId'] == 1077936132][0]
        self.assertEqual(conflict['rejected']['value'], [99.0, 99.0, 99.0])
        self.assertEqual(conflict['kept']['sourceKind'], 'native-snapshot-position')
        self.assertIs(projection['complete'], True, 'a contested attribute is not an '
                                                    'incomplete entity set')

    def test_a_label_is_multi_byte_and_never_confused_with_a_native_name(self):
        projection = project('labels-geometry-multibyte')
        row = entity_by_id(projection, 1077936132)
        self.assertEqual(row['knownAttributes']['label'], LABEL_TEXT)
        self.assertGreater(len(LABEL_TEXT.encode('utf-8')), len(LABEL_TEXT))
        self.assertIs(row['fieldProvenance']['label']['derived'], True)
        self.assertIsNone(row['fieldProvenance']['label']['observedAt'])
        self.assertEqual(row['fieldProvenance']['label']['sourceKind'], 'caller-label')
        self.assertNotIn('label', [u['field'] for u in row['unknownFields']])
        plain = entity_by_id(projection, 1086324739)
        self.assertNotIn('label', plain['knownAttributes'])
        self.assertIn('label', [u['field'] for u in plain['unknownFields']])
        self.assertIn('name', [u['field'] for u in plain['unknownFields']])
        self.assertNotIn('name', plain['knownAttributes'])

    def test_an_external_block_naming_no_entity_is_surfaced(self):
        projection = project('labels-geometry-multibyte')
        self.assertIn('EXTERNAL_BLOCK_UNKNOWN_ENTITY', refusal_codes(projection))
        unmatched = [r['detail'] for r in projection['refusals']
                     if r['code'] == 'EXTERNAL_BLOCK_UNKNOWN_ENTITY']
        self.assertEqual(unmatched, [{'block': 'geometry', 'key': '4242424242'}])

    def test_an_external_block_can_never_add_an_entity(self):
        projection = project('labels-geometry-multibyte')
        self.assertEqual(len(projection['entities']), 15)
        self.assertEqual(len(projection['entityIds']), 15)

    def test_a_malformed_external_block_is_refused(self):
        document = document_for(CREATE_AFTER)
        document['geometry'] = {'1077936132': {'position': [1.0, 2.0]}}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, CREATE_AFTER)
        self.assertEqual(caught.exception.code, 'EXTERNAL_BLOCK_INVALID')
        document = document_for(CREATE_AFTER)
        document['labels'] = {'1077936132': {'text': 'x' * (so.MAX_LABEL_CHARS + 1)}}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, CREATE_AFTER)
        self.assertEqual(caught.exception.code, 'EXTERNAL_BLOCK_INVALID')


class SubsystemTests(unittest.TestCase):
    def test_a_refused_subsystem_is_unknown_not_an_empty_subsystem(self):
        projection = project('subsystems-refused')
        for name in so.SUBSYSTEM_NAMES:
            entry = projection['subsystems'][name]
            self.assertEqual(entry['state'], 'unknown', name)
            self.assertEqual(entry['status'], 'baseline_refused', name)
            self.assertIs(entry['emptyResultIsNotAnObservation'], True, name)
            self.assertEqual(entry['payload'], [])
            self.assertIsNotNone(entry['reason'])
            self.assertIn('refusal, not a reading of an empty subsystem', entry['reason'])
        lifecycle = projection['subsystems']['lifecycleType']
        self.assertEqual(lifecycle['reasons'],
                         ['LIFECYCLE_STATUS_baseline_refused', 'LIFECYCLE_FLAGS_OR_PARSER',
                          'LIFECYCLE_INITIALIZATION'])
        self.assertEqual(lifecycle['decoderOk'], False)
        self.assertIn('SCHEDULER_STATUS_baseline_refused',
                      projection['subsystems']['schedulerCoroutines']['reasons'])

    def test_the_level_still_verifies_while_the_subsystems_do_not(self):
        """The live shape: the level reads fine and both subsystems are empty-and-refused."""
        projection = project('subsystems-refused')
        self.assertIs(projection['complete'], True)
        self.assertIs(projection['levelObservation']['verified'], True)
        self.assertEqual(len(projection['entities']), 15)

    def test_an_ok_subsystem_is_known_and_a_missing_one_is_unavailable(self):
        projection = project('subsystems-ok')
        known = projection['subsystems']['lifecycleType']
        self.assertEqual(known['state'], 'known')
        self.assertEqual(known['status'], 'ok')
        self.assertIs(known['emptyResultIsNotAnObservation'], False)
        self.assertEqual(known['payload'], [{'index': 6, 'slot': '0x9037840'}])
        absent = projection['subsystems']['schedulerCoroutines']
        self.assertEqual(absent['state'], 'unavailable')
        self.assertIsNone(absent['status'])
        self.assertIs(absent['emptyResultIsNotAnObservation'], True)

    def test_only_ok_reaches_known(self):
        for fixture in ('subsystems-refused', 'subsystems-ok'):
            projection = project(fixture)
            for name, entry in projection['subsystems'].items():
                self.assertEqual(entry['state'] == 'known', entry['status'] == 'ok',
                                 '%s/%s' % (fixture, name))

    def test_an_unknown_subsystem_name_is_not_silently_dropped(self):
        projection = project('subsystems-refused')
        self.assertIn('subsystems.levelCatalog', projection['unrecognizedDocumentKeys'])
        self.assertNotIn('levelCatalog', projection['subsystems'])

    def test_a_status_outside_the_decoder_table_is_refused(self):
        document = document_for('subsystems-refused')
        document['subsystems'] = {'lifecycleType': {'status': 'invented_status'}}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, 'subsystems-refused')
        self.assertEqual(caught.exception.code, 'SUBSYSTEM_STATUS_UNKNOWN')

    def test_a_contradictory_subsystem_verdict_is_refused(self):
        document = document_for('subsystems-refused')
        document['subsystems']['lifecycleType'] = {
            'ok': False, 'status': 'ok', 'reasons': ['LIFECYCLE_INITIALIZATION'], 'rows': []}
        with self.assertRaises(so.ObservationError) as caught:
            project_document(document, 'subsystems-refused')
        self.assertEqual(caught.exception.code, 'SUBSYSTEM_STATUS_INCONSISTENT')


# --------------------------------------------------------------------------- #
# paging and cursors
# --------------------------------------------------------------------------- #

class PaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projection = project(INSPECT)

    def walk(self, projection, **kwargs):
        pages, cursor, guard = [], None, 0
        while True:
            page = so.page_entities(projection, cursor=cursor, **kwargs)
            pages.append(page)
            guard += 1
            self.assertLess(guard, 500, 'paging did not terminate')
            if page['nextCursor'] is None:
                return pages
            cursor = page['nextCursor']

    def test_paging_walks_every_entity_exactly_once(self):
        pages = self.walk(self.projection, maxItems=4)
        seen = [row['entityId'] for page in pages for row in page['items']]
        self.assertEqual(seen, self.projection['entityIds'])
        self.assertEqual(pages[-1]['truncationReason'], 'end-of-page')
        self.assertIsNone(pages[-1]['nextCursor'])
        self.assertTrue(all(page['truncated'] for page in pages[:-1]))
        for page in pages:
            self.assertEqual(page['rowsInSnapshot'], 15)
            self.assertEqual(page['snapshotTotalCount'], 15)
            self.assertIsNone(page['note'])
            self.assertEqual(page['snapshotId'], self.projection['snapshotId'])
            self.assertEqual(page['levelId'], 1073741839)
            self.assertIs(page['complete'], True)
            self.assertEqual(page['refusals'], [])

    def test_the_page_reports_its_own_offsets(self):
        pages = self.walk(self.projection, maxItems=4, maxBytes=so.MAX_PAGE_BYTES)
        self.assertEqual([page['offset'] for page in pages], [0, 4, 8, 12])
        self.assertEqual([page['returnedCount'] for page in pages], [4, 4, 4, 3])
        self.assertEqual({page['truncationReason'] for page in pages[:-1]}, {'item-limit'})

    def test_the_byte_limit_pages_by_encoded_size_and_never_cuts_an_object(self):
        budget = max(items_bytes([row]) for row in self.projection['entities'])
        pages = self.walk(self.projection, maxItems=50, maxBytes=budget)
        self.assertEqual(len(pages), 15)
        seen = []
        for page in pages:
            self.assertEqual(page['returnedCount'], 1)
            page_items = [dict(item) for item in page['items']]
            self.assertEqual(page['bytes'], items_bytes(page_items))
            self.assertLessEqual(page['bytes'], budget)
            expected = [row for row in self.projection['entities']
                        if row['entityId'] == page_items[0]['entityId']]
            self.assertEqual(canonical_bytes(page_items), canonical_bytes(expected))
            seen += [row['entityId'] for row in page_items]
        self.assertEqual(seen, self.projection['entityIds'])
        self.assertEqual({page['truncationReason'] for page in pages[:-1]}, {'byte-limit'})

    def test_the_byte_budget_counts_encoded_multi_byte_characters(self):
        projection = project('labels-geometry-multibyte')
        row = entity_by_id(projection, 1077936132)
        self.assertGreater(len(json.dumps(row, ensure_ascii=False).encode('utf-8')),
                           len(json.dumps(row, ensure_ascii=False)))
        first = projection['entities'][0]
        one = items_bytes([first])
        page = so.page_entities(projection, maxItems=1, maxBytes=so.MAX_PAGE_BYTES)
        self.assertEqual(page['bytes'], items_bytes(page['items']))
        self.assertEqual(page['byteAccounting'],
                         'utf-8 bytes of the canonical JSON of the items array; the page '
                         'envelope is excluded and carries no entity content')
        tight = so.page_entities(projection, maxItems=1, maxBytes=one)
        self.assertEqual(canonical_bytes(tight['items'][0]), canonical_bytes(first))

    def test_a_single_row_over_the_budget_is_returned_whole_and_named(self):
        row = self.projection['entities'][0]
        budget = items_bytes([row]) - 1
        page = so.page_entities(self.projection, maxBytes=budget)
        self.assertEqual(page['returnedCount'], 1)
        self.assertEqual(page['oversizedItems'], [row['entityId']])
        self.assertEqual(page['truncationReason'], 'single-item-exceeds-max-bytes')
        self.assertIs(page['truncated'], True)
        self.assertGreater(page['bytes'], budget)
        self.assertEqual(canonical_bytes(page['items'][0]), canonical_bytes(row))
        self.assertIsNotNone(page['nextCursor'])

    def test_page_limits_above_the_contract_maximum_are_refused(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, maxItems=so.MAX_PAGE_ITEMS + 1)
        self.assertEqual(caught.exception.code, 'PAGE_LIMIT_EXCEEDS_MAXIMUM')
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, maxBytes=so.MAX_PAGE_BYTES + 1)
        self.assertEqual(caught.exception.code, 'PAGE_LIMIT_EXCEEDS_MAXIMUM')
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, maxItems=0)
        self.assertEqual(caught.exception.code, 'PAGE_LIMIT_INVALID')

    def test_a_cursor_from_another_snapshot_is_refused(self):
        other = project(CREATE_AFTER)
        cursor = so.page_entities(other, maxItems=1)['nextCursor']
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=cursor)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')

    def test_the_same_snapshot_content_read_at_another_time_is_still_another_cursor(self):
        other = project(INSPECT, observedAt='2026-09-29T09:00:00.000000+00:00')
        cursor = so.page_entities(other, maxItems=1)['nextCursor']
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=cursor)
        self.assertEqual(caught.exception.code, 'CURSOR_SNAPSHOT_CHANGED')
        self.assertEqual(caught.exception.detail['cursorSnapshotId'], other['snapshotId'])

    def _rewrite_cursor(self, cursor, **changes):
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8'))
        raw.update(changes)
        raw.pop('check', None)
        check = hashlib.sha256(
            (so.CURSOR_PEPPER + json.dumps(raw, sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False)).encode('utf-8')
        ).hexdigest()[:32]
        raw['check'] = check
        return base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False).encode('utf-8')).decode('ascii')

    def test_an_edited_cursor_is_refused(self):
        cursor = so.page_entities(self.projection, maxItems=1)['nextCursor']
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8'))
        raw['offset'] = raw['offset'] + 5
        tampered = base64.urlsafe_b64encode(
            json.dumps(raw, sort_keys=True, separators=(',', ':')).encode('utf-8')).decode('ascii')
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=tampered)
        self.assertEqual(caught.exception.code, 'CURSOR_TAMPERED')

        raw = json.loads(base64.urlsafe_b64decode(cursor.encode('ascii')).decode('utf-8'))
        raw['extra'] = 'injected'
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection,
                             cursor=base64.urlsafe_b64encode(
                                 json.dumps(raw).encode('utf-8')).decode('ascii'))
        self.assertEqual(caught.exception.code, 'CURSOR_TAMPERED')

        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor='not-a-cursor')
        self.assertEqual(caught.exception.code, 'CURSOR_INVALID')

    def test_the_cursor_level_binding_is_enforced_on_its_own(self):
        cursor = so.page_entities(self.projection, maxItems=1)['nextCursor']
        moved = self._rewrite_cursor(cursor, levelId=1073741834)
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=moved)
        self.assertEqual(caught.exception.code, 'CURSOR_LEVEL_CHANGED')
        self.assertEqual(caught.exception.detail['cursorLevelId'], 1073741834)

    def test_the_cursor_content_binding_is_enforced_on_its_own(self):
        cursor = so.page_entities(self.projection, maxItems=1)['nextCursor']
        moved = self._rewrite_cursor(cursor, contentDigest='0' * 64)
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=moved)
        self.assertEqual(caught.exception.code, 'CURSOR_CONTENT_CHANGED')

    def test_a_cursor_offset_past_the_end_is_refused(self):
        cursor = so.page_entities(self.projection, maxItems=1)['nextCursor']
        moved = self._rewrite_cursor(cursor, offset=99)
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=moved)
        self.assertEqual(caught.exception.code, 'CURSOR_OFFSET_OUT_OF_RANGE')

    def test_a_cursor_from_another_contract_version_is_refused(self):
        cursor = so.page_entities(self.projection, maxItems=1)['nextCursor']
        moved = self._rewrite_cursor(cursor, v=99)
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities(self.projection, cursor=moved)
        self.assertEqual(caught.exception.code, 'CURSOR_VERSION_UNSUPPORTED')

    def test_paging_a_truncated_projection_still_reports_it_is_truncated(self):
        projection = project('truncated')
        page = so.page_entities(projection, maxItems=100, maxBytes=so.MAX_PAGE_BYTES)
        self.assertEqual(page['returnedCount'], 15)
        self.assertIs(page['complete'], False)
        self.assertIs(page['truncated'], False)          # this page holds everything ...
        self.assertEqual(page['capturedCount'], 15)      # ... the snapshot does not
        self.assertEqual(page['rowsInSnapshot'], 15)
        self.assertEqual(page['snapshotTotalCount'], 512)
        self.assertIn('of 512 entries', page['note'])
        self.assertIn('ENTITIES_TRUNCATED', {r['code'] for r in page['refusals']})

    def test_get_entity_refuses_an_untrusted_or_invalid_id(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.get_entity(self.projection, 0)
        self.assertEqual(caught.exception.code, 'ENTITY_ID_INVALID')
        with self.assertRaises(so.ObservationError) as caught:
            so.get_entity(self.projection, '1077936132')
        self.assertEqual(caught.exception.code, 'ENTITY_ID_INVALID')

    def test_a_missing_entity_says_which_kind_of_absence_it_is(self):
        found = so.get_entity(self.projection, 1077936132)
        self.assertIs(found['found'], True)
        self.assertEqual(found['entity']['templateId'], 20001034)
        self.assertEqual(found['occurrences'], 1)
        missing = so.get_entity(self.projection, 4242)
        self.assertIs(missing['found'], False)
        self.assertEqual(missing['absenceMeaning'], 'not-present-in-complete-snapshot')
        self.assertIsNone(missing['absenceReason'])

    def test_a_page_of_a_projection_from_another_contract_is_refused(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.page_entities({'contract': 'something-else', 'schemaVersion': 1})
        self.assertEqual(caught.exception.code, 'PROJECTION_INVALID')


# --------------------------------------------------------------------------- #
# diffs
# --------------------------------------------------------------------------- #

class DiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = project(CREATE_BEFORE)
        cls.after = project(CREATE_AFTER)

    def test_the_real_create_pair_shows_exactly_the_created_entity(self):
        diff = so.diff_snapshots(self.before, self.after)
        self.assertEqual(diff['state'], 'observed')
        self.assertEqual(diff['added'], [1077936132])
        self.assertEqual(diff['removed'], [])
        self.assertEqual(diff['changed'], [])
        self.assertEqual(diff['changedCount'], 0)
        self.assertIs(diff['authoritative'], True)
        self.assertIs(diff['sameCountDifferentObjects'], False)
        self.assertEqual(diff['caveats'], [])
        self.assertEqual(diff['counts']['before']['capturedCount'], 14)
        self.assertEqual(diff['counts']['after']['capturedCount'], 15)

    def test_swapping_the_sides_swaps_added_and_removed(self):
        forward = so.diff_snapshots(self.before, self.after)
        backward = so.diff_snapshots(self.after, self.before)
        self.assertEqual(backward['added'], forward['removed'])
        self.assertEqual(backward['removed'], forward['added'])
        self.assertEqual(backward['state'], forward['state'])

    def test_the_same_count_with_a_different_object_is_not_reported_as_no_change(self):
        document = document_for(CREATE_AFTER)
        document['entities'][13]['id'] = 1077936199
        document['entities'][13]['dictionaryKey'] = 1077936199
        swapped = project_document(document, CREATE_AFTER)
        diff = so.diff_snapshots(self.after, swapped)
        self.assertEqual(diff['state'], 'observed')
        self.assertEqual(diff['added'], [1077936199])
        self.assertEqual(diff['removed'], [1077936132])
        self.assertIs(diff['sameCountDifferentObjects'], True)
        self.assertEqual(diff['counts']['before']['capturedCount'],
                         diff['counts']['after']['capturedCount'])

    def test_a_null_position_and_a_zero_position_are_a_change_of_availability(self):
        known = project('position-known')
        diff = so.diff_snapshots(self.after, known)
        zero = [c for c in diff['changed']
                if c['entityId'] == 1086324737 and c['field'] == 'position']
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0]['kind'], 'availability-changed')
        self.assertEqual(zero[0]['beforeStatus'], 'unknown')
        self.assertEqual(zero[0]['afterStatus'], 'known')
        self.assertIsNone(zero[0]['before'])
        self.assertEqual(zero[0]['after'], [0.0, 0.0, 0.0])
        self.assertNotIn('value-changed', {c['kind'] for c in diff['changed']})

    def test_a_changed_position_is_reported_as_a_value_change_with_both_sides(self):
        document = document_for('position-known')
        document['entities'][13]['position'] = [1.0, 2.0, 3.0]
        moved = project_document(document, 'position-known')
        diff = so.diff_snapshots(project('position-known'), moved)
        entry = [c for c in diff['changed'] if c['entityId'] == 1077936132][0]
        self.assertEqual(entry['kind'], 'value-changed')
        self.assertEqual(entry['before'], [-20.5, 3.25, 8.0])
        self.assertEqual(entry['after'], [1.0, 2.0, 3.0])

    def test_a_truncated_side_makes_the_diff_unauthoritative_but_still_reported(self):
        diff = so.diff_snapshots(self.after, project('truncated'))
        self.assertEqual(diff['state'], 'observed')
        self.assertIs(diff['authoritative'], False)
        self.assertIn('not proven complete', ' '.join(diff['caveats']))
        self.assertIn('ENTITY_SET_SHORT_OF_VALID_ENTRIES',
                      ' '.join(diff['caveats']))

    def test_an_untrusted_side_refuses_the_diff_instead_of_guessing(self):
        diff = so.diff_snapshots(self.after, project('duplicate-identity'))
        self.assertEqual(diff['state'], 'refused')
        self.assertEqual(diff['code'], 'SNAPSHOT_UNTRUSTED')
        self.assertIsNone(diff['added'])
        self.assertIsNone(diff['removed'])
        self.assertIn('DUPLICATE_ENTITY_IDENTITY', diff['entitySetRefusals'])

    def test_two_different_levels_are_refused(self):
        diff = so.diff_snapshots(self.after, project('wrong-level', levelId=1073741834))
        self.assertEqual(diff['state'], 'refused')
        self.assertEqual(diff['code'], 'SNAPSHOT_LEVEL_MISMATCH')
        self.assertIsNone(diff['added'])

    def test_a_receipt_with_no_verified_level_refuses_a_diff_against_a_levelled_one(self):
        document = document_for(CREATE_AFTER)
        document['levelObservation'] = {'verified': False, 'levelId': None}
        diff = so.diff_snapshots(self.after, project_document(document, CREATE_AFTER))
        self.assertEqual(diff['state'], 'refused')
        self.assertEqual(diff['code'], 'SNAPSHOT_LEVEL_MISMATCH')

    def test_a_created_entity_is_not_reported_as_changed(self):
        """A newly added entity has no attribute changes to report."""
        diff = so.diff_snapshots(self.before, self.after)
        self.assertEqual([c for c in diff['changed'] if c['entityId'] == 1077936132], [])
        self.assertEqual(diff['unchangedCount'], 14)

    def test_the_diff_caps_its_changed_list_and_says_so(self):
        first = document_for('position-known')
        second = copy.deepcopy(first)
        for document, shift in ((first, 0.0), (second, 100.0)):
            for index, row in enumerate(document['entities']):
                row['flags']['value'] |= so.POSITION_FLAG
                row['flags']['names'] = flag_names(row['flags']['value'], so.ENTITY_FLAGS)
                row['position'] = [float(index) + shift, 1.0, 2.0]
        moved, moved_again = (project_document(first, 'position-known'),
                              project_document(second, 'position-known'))
        full = so.diff_snapshots(moved, moved_again)
        self.assertEqual(full['changedCount'], 15)
        self.assertIs(full['changedTruncated'], False)
        with mock.patch.object(so, 'MAX_DIFF_CHANGES', 3):
            capped = so.diff_snapshots(moved, moved_again)
        self.assertEqual(capped['changedCount'], 15)
        self.assertEqual(len(capped['changed']), 3)
        self.assertIs(capped['changedTruncated'], True)
        self.assertIn('capped at 3', ' '.join(capped['caveats']))

    def test_a_foreign_projection_is_refused_by_the_diff(self):
        with self.assertRaises(so.ObservationError) as caught:
            so.diff_snapshots(self.before, {'contract': 'nope'})
        self.assertEqual(caught.exception.code, 'PROJECTION_INVALID')

    def test_the_diff_is_json_safe(self):
        diff = so.diff_snapshots(self.before, self.after)
        self.assertEqual(json.loads(json.dumps(diff, ensure_ascii=False,
                                              allow_nan=False))['added'], [1077936132])


if __name__ == '__main__':
    if '--write-fixtures' in sys.argv[1:]:
        written = write_fixtures()
        print(json.dumps({'wrote': str(FIXTURES), 'files': written}, ensure_ascii=False))
        raise SystemExit(0)
    unittest.main()
