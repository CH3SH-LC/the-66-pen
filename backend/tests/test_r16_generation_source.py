"""R16: the run generation is sourced only from records inside the observation window.

The counterexample R16 names is reproduced here as an executable case: a bundle whose only
1022 records predate the window opened.  Before the fix the module still derived a non-null
``derivedGenerationId`` from that pre-window cursor and, with a readback carrying the stale
sequence, returned ``sampleObserved.status == 'pass'`` whose ``evidenceRef`` cited the
derived generation.  The exclusion has to happen where the cursor is *chosen*, not only in
``observation_window``'s display list, because the digest and the correlation carriers are
read from the cursor.

Nothing here starts, connects to or drives Genshin, the editor, the bridge, a helper, a
queue or any live session: every input is a synthetic fixture marked ``_fixture.live=false``.

    python -B -m unittest backend.tests.test_r16_generation_source
    RO_UNDER_TEST=<path to a runtime_observation.py> python -B <this file>
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]

_UNDER_TEST = os.environ.get('RO_UNDER_TEST')
if _UNDER_TEST:
    _spec = importlib.util.spec_from_file_location('ro_under_test', _UNDER_TEST)
    ro = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ro)
else:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from backend import runtime_observation as ro  # noqa: E402

CASE = 'case-ds03-0001'
LEVEL = 1073741839
GAME = {'pid': 31584, 'tid': 4321, 'processCreation': '2026-10-03T07:55:00.0000000Z',
        'image': 'C:/Genshin/GenshinImpact.exe'}
EDITOR = {'pid': 33992, 'image': 'C:/Genshin/BeyondEditor.exe',
          'creationFileTime': '2026-10-03T07:40:00.0000000Z'}
OBSERVATION_ID = 'e9c5a4005de14a93911c648f3d099c60'
REG_TICK = 3175291430318
SAVED_ENTITY = 1077936138

W_START = '2026-10-03T09:00:00.0000000Z'
W_REG = '2026-10-03T09:00:00.5000000Z'
W_STOP = '2026-10-03T09:05:00.0000000Z'
IN_WINDOW = '2026-10-03T09:01:00.0000000Z'
IN_WINDOW_LATE = '2026-10-03T09:03:00.0000000Z'
PRE_WINDOW_EARLY = '2026-10-03T08:50:00.0000000Z'
PRE_WINDOW_NEWEST = '2026-10-03T08:55:00.0000000Z'


def _fixture(note='r16 fixtures'):
    return {'kind': 'synthetic-fixture', 'live': False, 'note': note}


def level_init(events, sequence):
    return {
        'started': True,
        'observationId': OBSERVATION_ID,
        'initStartedUtc': W_START,
        'observerTiming': {
            'scope': 'current-observer-instance-only',
            'stopwatchFrequency': 10000000,
            'startedUtc': W_START,
            'registrationCompletedUtc': W_REG,
            'registrationCompletedTick': REG_TICK,
            'stoppedUtc': W_STOP,
            'stopReason': 'observer-lease-expired',
            'lastCallbackUtc': '2026-10-03T09:04:00.0000000Z',
            'historical1022Inferred': False,
        },
        'source': 'received-1022-packet-observer',
        'sequence': sequence,
        'retainedEvents': sequence,
        'eventLimit': 16,
        'droppedEvents': 0,
        'overflow': False,
        'events': events,
        'parseErrors': 0, 'evidenceErrors': 0, 'threadErrors': 0,
    }


def _event(sequence, utc):
    return {'sequence': sequence, 'receivedUtc': utc, 'receivedTick': sequence * 100,
            'managedThreadId': 1, 'levelId': LEVEL, 'parsed': True, 'error': None}


def observer_evidence(stopped=True):
    return {
        'ok': True, 'active': False,
        'packetKinds': {'0': 118, '1022': 2, '1010': 31},
        'scenePacketSnapshots': [{'utc': '2026-10-03T09:02:00.0000000Z', 'id': 1017,
                                  'snapshot': {'type': 'x'}}],
        'observerScanLimited': False, 'observerCleanupError': None, 'callbackErrors': 0,
    }


def runtime_objects(sequence):
    return {
        'source': 'runtime-scene-object-readback',
        'levelId': LEVEL,
        'observationId': OBSERVATION_ID,
        'registrationCompletedTick': REG_TICK,
        'sequence': sequence,
        'objects': [{'entityId': SAVED_ENTITY, 'templateId': 20001034,
                     'position': [1.0, 2.0, 3.0],
                     'observedUtc': '2026-10-03T09:02:10.0000000Z'}],
    }


def bundle(events, sequence, readback_sequence, stopped=True):
    timing = dict(level_init(events, sequence)['observerTiming'])
    if not stopped:
        timing['stoppedUtc'] = None
    block = level_init(events, sequence)
    block['observerTiming'] = timing
    return {
        'kind': 'runtime-evidence-bundle',
        'schemaVersion': 1,
        'caseId': CASE,
        'session': dict(GAME),
        'editorSession': dict(EDITOR),
        'levelObservation': {'verified': True, 'levelId': LEVEL},
        'levelInitialization': block,
        'logObserverEvidence': observer_evidence(stopped),
        'runtimeObjects': runtime_objects(readback_sequence),
        '_fixture': _fixture(),
    }


def binding(**over):
    base = {
        'caseId': CASE,
        'expectedLevelId': LEVEL,
        'expectedGameSession': dict(GAME),
        'expectedEditorSession': dict(EDITOR),
        'expectedRunGeneration': None,
        'expectedEntityIds': [SAVED_ENTITY],
        'sourceSha256': None,
        'evidenceMode': 'offline',
    }
    base.update(over)
    return base


class PreWindowGenerationTests(unittest.TestCase):
    """The R16 counterexample: only pre-window 1022 records must not mint a generation."""

    def _bundle(self):
        return bundle(events=[_event(4, PRE_WINDOW_EARLY), _event(5, PRE_WINDOW_NEWEST)],
                      sequence=5, readback_sequence=5)

    def test_only_pre_window_1022_derives_no_generation(self):
        identity = ro.runtime_identity(self._bundle(), binding=binding())
        self.assertIsNone(identity['derivedGenerationId'],
                          'a pre-window 1022 record minted a generation')
        self.assertIsNone(identity['eventCursor'],
                          'the cursor was drawn from a record before the window opened')
        self.assertFalse(identity['established'])
        self.assertEqual(identity['cursorCandidatesExcludedByWindow'], [4, 5],
                         'the excluded candidates are not reported at the generation source')

    def test_the_exclusion_is_reported_as_a_source_event_not_a_display_filter(self):
        """The window's display list is unchanged; the exclusion is at the cursor source."""
        subject = self._bundle()
        identity = ro.runtime_identity(subject, binding=binding())
        window = ro.observation_window(subject, identity=identity)
        # the display list still *shows* the pre-window records, marked historical ...
        self.assertEqual(window['historicalCount'], 2)
        self.assertEqual(window['state'], 'observed')
        # ... and the generation source dropped exactly those, by sequence number.
        self.assertEqual(identity['cursorCandidatesExcludedByWindow'], [4, 5])

    def test_the_projection_cannot_reach_a_pass_by_citing_the_pre_window_generation(self):
        projection = ro.normalize_runtime_evidence(self._bundle(), binding())
        self.assertNotEqual(projection['sampleObserved']['status'], 'pass')
        self.assertEqual(projection['sampleObserved']['evidenceRef'], [],
                         'a pass evidenceRef cited the pre-window generation')
        self.assertIn('RUN_IDENTITY_EVIDENCE_INSUFFICIENT', projection['refusalCodes'])

    def test_a_readback_carrying_the_stale_sequence_no_longer_correlates(self):
        subject = self._bundle()
        identity = ro.runtime_identity(subject, binding=binding())
        correlation = ro.correlate_objects(subject, identity=identity,
                                           expectedEntityIds=[SAVED_ENTITY])
        self.assertNotEqual(correlation['status'], 'pass')
        reasons = {r['code'] for r in correlation['refusals']}
        self.assertTrue(reasons & {'RUN_IDENTITY_GENERATION_MISMATCH',
                                   'CORRELATION_GENERATION_UNBOUND'},
                        'a stale-sequence readback was accepted as this run: %s' % reasons)


class InWindowGenerationTests(unittest.TestCase):
    """Positive control: in-window 1022 records still carry the generation."""

    def test_in_window_1022_still_mints_the_generation(self):
        subject = bundle(events=[_event(1, IN_WINDOW), _event(2, IN_WINDOW_LATE)],
                         sequence=2, readback_sequence=2)
        identity = ro.runtime_identity(subject, binding=binding())
        self.assertTrue(identity['established'])
        self.assertEqual(identity['eventCursor']['sequence'], 2)
        self.assertIsNotNone(identity['derivedGenerationId'])
        self.assertEqual(identity['cursorCandidatesExcludedByWindow'], [])

    def test_the_generation_source_picks_the_in_window_record_not_the_newest_pre_window_one(self):
        """A pre-window record with a *higher* sequence may not outrank an in-window one."""
        subject = bundle(events=[_event(1, IN_WINDOW), _event(99, PRE_WINDOW_NEWEST)],
                         sequence=99, readback_sequence=1)
        identity = ro.runtime_identity(subject, binding=binding())
        self.assertEqual(identity['eventCursor']['sequence'], 1,
                         'the cursor is still the globally newest 1022, not the in-window one')
        self.assertEqual(identity['cursorCandidatesExcludedByWindow'], [99])

    def test_an_open_window_keeps_its_in_window_cursor(self):
        """Regression guard: the fix must not starve an open (never-stopped) window."""
        subject = bundle(events=[_event(1, IN_WINDOW)], sequence=1, readback_sequence=1,
                         stopped=False)
        identity = ro.runtime_identity(subject, binding=binding())
        self.assertEqual(identity['eventCursor']['sequence'], 1)
        self.assertEqual(identity['cursorCandidatesExcludedByWindow'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
