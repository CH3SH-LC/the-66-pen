"""Replay, conflict and unknown-outcome behaviour of the entity server.

G01 decision **D19**: the business layer must consult the bottom-layer ledger *before*
it derives any execution material.  ``tools/authoring/author.py`` fingerprints the WHOLE
bound command -- the ``session``, ``review`` and ``baseline`` paths included -- and
``derive_review`` mints a fresh review file name on every call.  So "derive a review,
then dispatch" is indistinguishable, at the bottom layer, from the SAME requestId
carrying a DIFFERENT command, and the second call came back ``REQUEST_ID_CONFLICT``
instead of the original receipt.  G01 section 12.5 requires an offline reproduction of
that ordering before it may be called a reproduced defect; this suite is that
reproduction, and it is also the regression test for the fix.

The tool functions are driven directly.  The fingerprinting and the replay/conflict
decision are the production ones -- ``author.execute`` is imported, not re-implemented --
and only the transport, the review orchestrator and the native entry points are faked.
No game, editor, elevated helper, bridge or queue is contacted, and nothing is written
outside a temporary directory.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for _extra in (str(ROOT), str(ROOT / 'tools' / 'authoring')):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import author                            # noqa: E402
import backend.entity_server as server   # noqa: E402

LEVEL_ID = 1073741839
OTHER_LEVEL_ID = 1073741840
TEMPLATE_ID = 20002103
POSITION = [-12.0, 0.0, 6.0]
ENTITY_ID = 1077936133


def payload(call_result):
    """The tool payload, asserting the text body and ``structuredContent`` agree."""
    body = call_result.structuredContent
    text = json.loads(call_result.content[0].text)
    if text != body:
        raise AssertionError('text body and structuredContent disagree')
    return body


#: The ids the fake level holds before the create.  Ten of them, none of them ENTITY_ID.
BASE_ENTITY_IDS = tuple(1086324737 + offset for offset in range(10))
#: Snapshot flags asserted by the native read-only acceptance (build_readonly_profile
#: ``f & 927 == 927``): build_verified/origin_read/contexts_complete/entities_complete/
#: structure_rechecked/stack_captured/stack_verified/hotfix_default_confirmed, with the
#: truncation (32) and read-failure (64) bits CLEAR.
COMPLETE_SNAPSHOT_FLAGS = 927
#: Per-entity flags: id_read | config_id_read | context_match | key_match | context_read.
#: Deliberately WITHOUT position_read (16), which is what makes the placement unknown for
#: every row of this fake readback -- the honest state of the native record.
ENTITY_FLAGS_READ = 79


def observation_document(entity_count, level_id):
    """A minimal COMPLETE decoded observation document for the fake readback.

    W18 changed ``mw_scene_create_entity`` from "did the count go up by one" to "did the
    level gain exactly the entity the native create reported, carrying the requested
    template at the requested placement", judged against the projection of the two
    native observations.  A fake execution layer therefore has to hand the create path a
    projectable document, or the create is refused as unverified -- which is the point of
    the change.  The document is built from the constants the assertion in
    ``backend/scene_observation`` requires: complete counts, no truncation bit,
    ``levelObservation.verified`` and the rows' own declared index.
    """
    ids = list(BASE_ENTITY_IDS[:entity_count])
    if entity_count > len(BASE_ENTITY_IDS):
        ids.append(ENTITY_ID)             # the one entity the fake create placed
    rows = [{'index': index, 'id': entity_id, 'dictionaryKey': entity_id,
             'configId': TEMPLATE_ID, 'flags': {'value': ENTITY_FLAGS_READ},
             # Pointer fields the projection requires on every row.  They are opaque
             # address tokens in a real receipt; here they only have to be present.
             'owner': '0x0', 'config': '0x0', 'context': '0x0'}
            for index, entity_id in enumerate(ids)]
    return {
        'version': 1,
        'status': {'value': 0, 'name': 'ok'},
        'flags': {'value': COMPLETE_SNAPSHOT_FLAGS},
        'counts': {'entityCapacity': 512, 'entityValidEntries': len(rows),
                   'entityCaptured': len(rows), 'entityRejected': 0},
        'entities': rows,
        'levelObservation': {'verified': True, 'levelId': level_id},
    }


class ReplayCase(unittest.TestCase):
    """A throw-away journal, a fake transport, and a counter per execution step."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.review_dir = self.base / 'reviews'
        self.review_dir.mkdir(parents=True)
        self.journal = self.base / 'requests'
        self.request_id = 'replay' + uuid.uuid4().hex[:12]
        self.counts = {'dispatch': 0, 'review': 0, 'backup': 0, 'inspect': 0, 'queue': 0}
        self.transported = []
        # The level the fake native layer is showing; a dispatched create really adds one.
        self.entity_count = 10
        self.level = {'handle': 'handle-' + uuid.uuid4().hex[:8], 'run': 'run-discovery',
                      'levelId': LEVEL_ID, 'entities': 10, 'verifiedAtUtc': '2026-10-01T00:00:00+00:00',
                      'sessionPath': 'session.json', 'queue': self.base / 'queue'}

        patches = (
            patch.object(server, 'JOURNAL_ROOT', self.journal),
            patch.object(server, 'EVIDENCE_ROOT', self.base / 'evidence'),
            # 2026-10-09: supported_templates() is gone with the template whitelist; any
            # uint32 template id is accepted now, so there is nothing to patch here.
            patch.object(server, 'load_handle', self.load_handle),
            patch.object(server, 'resolve_elevated_queue', self.resolve_queue),
            patch.object(server, 'inspect_level', self.inspect_level),
            patch.object(server, 'fresh_account_backup', self.account_backup),
            patch.object(server, 'derive_review', self.derive_review),
            patch.object(server, 'dispatch_write', self.dispatch_write),
            # The version guard reads the installed game image from disk.  It is a
            # separate gate with its own tests, so it is neutralised here to keep this
            # suite hermetic and about the ordering alone.
            patch.object(author, 'require_compatible', lambda *a, **k: {'ok': True}),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    # --- the execution layer, faked ------------------------------------------- #

    def load_handle(self, handle):
        return dict(self.level, handle=handle)

    def resolve_queue(self):
        self.counts['queue'] += 1
        return self.level['queue'], {'helperPid': 4242}

    def inspect_level(self, level, request_id):
        self.counts['inspect'] += 1
        run_dir = self.base / ('run-inspect-%d' % self.counts['inspect'])
        run_dir.mkdir(parents=True, exist_ok=True)
        # W18: the create path VERIFIES the new entity against the projection of this
        # document, so the fake readback has to be a real one -- a missing document is a
        # refusal, not a fall-through to the old count comparison.
        snapshot = run_dir / 'before-context.json'
        snapshot.write_text(
            json.dumps(observation_document(self.entity_count, level['levelId'])),
            encoding='utf-8')
        return {'run': str(run_dir), 'entities': self.entity_count,
                'acceptancePath': str(run_dir / 'readonly-acceptance.json'),
                'snapshotPath': str(snapshot), 'receipt': {}, 'requestId': request_id}

    def account_backup(self, label):
        self.counts['backup'] += 1
        return {'backup': str(self.base / 'backup'),
                'manifest': str(self.base / 'backup' / 'manifest.json'),
                'fileCount': 1, 'verified': True}

    def derive_review(self, level, action, request, baseline_run, backup, workspace):
        """A FRESH review name on every call, exactly like the production orchestrator."""
        self.counts['review'] += 1
        path = self.review_dir / ('%s-review-%s.json' % (action, uuid.uuid4().hex[:12]))
        path.write_text('{}', encoding='utf-8')
        return {'reviewPath': str(path), 'reviewId': uuid.uuid4().hex,
                'validatedBy': 'native_write_review.validate_review'}

    def dispatch_write(self, level, action, request, review_path, request_id):
        """The real ``author.execute``, over a throw-away journal and a fake transport."""
        self.counts['dispatch'] += 1
        command = {'backend': 'scene', 'action': action, 'levelId': level['levelId'],
                   'mutating': True, 'review': review_path, 'session': level['sessionPath'],
                   'elevatedQueue': str(level['queue'])}
        if action == 'create':
            command.update(templateId=int(request['templateId']), position=list(request['position']),
                           rotation=list(request['rotation']), scale=list(request['scale']))

        def transport(bound_command):
            self.transported.append(bound_command)
            if action == 'create':
                self.entity_count += 1          # the native create really placed one entity
            return {'ok': True, 'action': action, 'actionStatus': 0, 'entityId': ENTITY_ID,
                    'levelId': level['levelId'], 'nativeStatus': 0, 'gilChanged': {},
                    'run': 'run-dispatch-1', 'placedCount': 1, 'outcomeUncertain': False,
                    'retryAttempted': False}

        reply = author.execute(command, request_id, journal=self.journal, transport=transport)
        backend = reply.get('backend') or {}
        return {'reply': reply, 'backend': backend, 'ok': reply.get('ok') is True,
                'outcomeUncertain': backend.get('outcomeUncertain') is True,
                'error': reply.get('error'), 'journal': reply.get('journal')}

    # --- the tools under test ------------------------------------------------- #

    def create(self, **overrides):
        arguments = {'levelHandle': self.level['handle'], 'templateId': TEMPLATE_ID,
                     'position': list(POSITION), 'requestId': self.request_id}
        arguments.update(overrides)
        return server.mw_scene_create_entity(**arguments)

    def save(self, **overrides):
        arguments = {'levelHandle': self.level['handle'], 'requestId': self.request_id}
        arguments.update(overrides)
        return server.mw_scene_save_level(**arguments)

    def write_claim(self, binding, *, receipt=None):
        """A journal entry as ``author.execute`` would have left it."""
        directory = self.journal / self.request_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'claim.json').write_text(
            json.dumps({'sha256': 'deadbeef', 'command': binding, 'startedUtc': '2026-10-01T00:00:00+00:00'}) + '\n',
            encoding='utf-8')
        if receipt is not None:
            (directory / 'result.json').write_text(json.dumps(receipt) + '\n', encoding='utf-8')
        return directory


class CreateReplay(ReplayCase):
    def first_create_binding(self):
        return {'backend': 'scene', 'action': 'create', 'levelId': LEVEL_ID, 'mutating': True,
                'review': 'review-of-the-first-attempt.json', 'session': 'session.json',
                'elevatedQueue': str(self.level['queue']), 'templateId': TEMPLATE_ID,
                'position': list(POSITION), 'rotation': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0]}

    def test_same_payload_returns_the_original_receipt_with_one_dispatch(self):
        first_call = self.create()
        first = payload(first_call)
        self.assertFalse(first_call.isError)
        self.assertIs(first['created'], True)
        self.assertIsNotNone(first['entityId'])
        self.assertIsNot(first.get('replayed'), True, 'the first attempt is not a replay')
        self.assertEqual(self.counts['dispatch'], 1)
        self.assertEqual(len(self.transported), 1)

        second_call = self.create()
        second = payload(second_call)
        self.assertFalse(second_call.isError, 'a replay is not an error: %r' % (second.get('error'),))
        self.assertIs(second['created'], True)
        self.assertIs(second['replayed'], True, 'the replay must say so')
        self.assertEqual(second['entityId'], first['entityId'], 'the ORIGINAL receipt, not a new one')
        self.assertEqual(second['requestId'], self.request_id)

        self.assertEqual(self.counts['dispatch'], 1, 'the replay must not dispatch a second time')
        self.assertEqual(len(self.transported), 1)

    def test_replay_derives_no_review_and_takes_no_backup_or_baseline(self):
        payload(self.create())
        after_first = dict(self.counts)
        payload(self.create())
        self.assertEqual(self.counts, after_first,
                         'the replay path must not derive a review, take a backup, resolve the '
                         'queue or inspect the level again')

    def test_same_id_different_payload_is_refused_before_any_new_material(self):
        payload(self.create())
        after_first = dict(self.counts)

        conflict_call = self.create(position=[1.0, 2.0, 3.0])
        conflict = payload(conflict_call)
        self.assertTrue(conflict_call.isError)
        self.assertIs(conflict['ok'], False)
        self.assertEqual(conflict['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.counts, after_first, 'a conflict must build nothing at all')

    def test_same_id_different_template_is_refused(self):
        payload(self.create())
        conflict = payload(self.create(templateId=TEMPLATE_ID + 1))
        self.assertEqual(conflict['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.counts['dispatch'], 1)

    def test_same_id_different_target_is_refused(self):
        payload(self.create())
        self.level['levelId'] = OTHER_LEVEL_ID
        conflict = payload(self.create())
        self.assertEqual(conflict['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.counts['dispatch'], 1)

    def test_a_signed_zero_is_the_same_placement_not_a_conflict(self):
        """The comparison is numeric: -0.0 and 0.0 are one placement, not two commands."""
        payload(self.create())
        replay = payload(self.create(position=[-12.0, -0.0, 6.0]))
        self.assertIs(replay.get('replayed'), True)
        self.assertNotIn('error', replay)
        self.assertEqual(self.counts['dispatch'], 1)

    def test_a_claim_without_a_result_is_unknown_and_never_resent(self):
        self.write_claim(self.first_create_binding())
        outcome_call = self.create()
        outcome = payload(outcome_call)
        self.assertTrue(outcome_call.isError)
        self.assertEqual(outcome['error']['code'], 'REQUEST_OUTCOME_UNKNOWN')
        self.assertEqual(self.counts['dispatch'], 0, 'an unknown outcome is never resent')

    def test_a_claim_directory_without_a_claim_is_refused(self):
        (self.journal / self.request_id).mkdir(parents=True)
        outcome = payload(self.create())
        self.assertEqual(outcome['error']['code'], 'REQUEST_INCOMPLETE_CLAIM')
        self.assertEqual(self.counts['dispatch'], 0)

    def test_a_partial_dispatch_raw_failure_is_still_conflicting(self):
        """A third-party journal entry is replayed only if it is the SAME request."""
        binding = self.first_create_binding()
        binding['position'] = [-1.0, -2.0, -3.0]
        self.write_claim(binding)
        conflict = payload(self.create())
        self.assertEqual(conflict['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.counts['dispatch'], 0)


class SaveReplay(ReplayCase):
    def test_same_payload_returns_the_original_receipt_with_one_dispatch(self):
        first = payload(self.save())
        # R19: the offline fake records no differential, so `saved` is NOT established.
        # The dispatch fact is reported under its own name instead.
        self.assertIsNone(first['saved'])
        self.assertIs(first['nativeDispatched'], True)
        self.assertIsNot(first.get('replayed'), True)

        second_call = self.save()
        second = payload(second_call)
        self.assertFalse(second_call.isError, 'a replay is not an error: %r' % (second.get('error'),))
        self.assertIsNone(second['saved'])
        self.assertIs(second['nativeDispatched'], True)
        self.assertIs(second['replayed'], True)
        self.assertEqual(second['nativeSaveStatus'], 0)
        self.assertEqual(second['requestId'], self.request_id)

        self.assertEqual(self.counts['dispatch'], 1)
        self.assertEqual(len(self.transported), 1)
        self.assertEqual(self.counts['review'], 1)
        self.assertEqual(self.counts['queue'], 1)

    def test_same_id_different_target_is_refused(self):
        payload(self.save())
        self.level['levelId'] = OTHER_LEVEL_ID
        conflict = payload(self.save())
        self.assertEqual(conflict['error']['code'], 'REQUEST_ID_CONFLICT')
        self.assertEqual(self.counts['dispatch'], 1)

    def test_save_replay_reports_the_recorded_protected_level_change(self):
        """A recorded failure of the original dispatch is not hidden by a replay frame."""
        receipt = {'ok': True, 'requestId': self.request_id,
                   'journal': str(self.journal / self.request_id),
                   'backend': {'ok': True, 'action': 'save', 'levelId': LEVEL_ID,
                               'nativeStatus': 0, 'run': 'run-dispatch-1',
                               'gilChanged': {str(OTHER_LEVEL_ID): True}}}
        self.write_claim({'backend': 'scene', 'action': 'save', 'levelId': LEVEL_ID,
                          'mutating': True, 'review': 'review-1.json', 'session': 'session.json'}, receipt=receipt)
        outcome = payload(self.save())
        self.assertEqual(outcome['error']['code'], 'SAVE_TOUCHED_ANOTHER_LEVEL')
        self.assertEqual(self.counts['dispatch'], 0)


class FingerprintSensitivity(unittest.TestCase):
    """Why D19 exists, stated against the production encoder."""

    def test_the_review_path_is_part_of_the_bound_command(self):
        base = {'backend': 'scene', 'action': 'create', 'levelId': LEVEL_ID, 'mutating': True,
                'session': 'session.json', 'templateId': TEMPLATE_ID, 'position': list(POSITION),
                'rotation': [0.0, 0.0, 0.0], 'scale': [1.0, 1.0, 1.0]}
        one = dict(base, review='review-aaaaaaaaaaaa.json')
        two = dict(base, review='review-bbbbbbbbbbbb.json')
        self.assertNotEqual(author.encoded(one), author.encoded(two),
                            'a freshly derived review path is a DIFFERENT command, so deriving '
                            'one before looking at the ledger turns a replay into a conflict')

    def test_a_non_finite_transform_cannot_even_be_fingerprinted(self):
        with self.assertRaises(ValueError):
            author.encoded({'scale': [float('nan'), 1.0, 1.0]})


if __name__ == '__main__':
    unittest.main()
