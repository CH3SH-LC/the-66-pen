"""W15 / T06 -- the business ledger the write path now produces, and nothing else.

WHY THIS FILE EXISTS
--------------------
``backend/operation_state.py`` (T06 / DS-08) was delivered and tested, and
``plugins/miliastra/src/ledger-port.ts`` reads it, but between the two there was no
producer: ``.runtime/business-ledger`` did not exist and nothing in the repository ever
wrote a row into it.  The result was not a failure but a silent bypass -- the Cordis
permit's ``beginOperation`` read an empty ledger, answered ``never-claimed`` and granted
every dispatch, so its ``existing`` and ``refused`` outcomes were dead code on the
production path.  ``backend/entity_server.py``'s ``dispatch_write`` is now that producer.

WHAT THE DISPATCHER IS HERE
---------------------------
FAKE, and deliberately so: T06 section 6 requires the fake dispatcher for the crash and
concurrency cases, and T06 section 3 requires a new isolated directory for tests.  No
game, no editor, no elevated helper, no bridge, no ``author.py`` and no journal is
touched; every ledger root below is a fresh temporary directory.

Run:
    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.test_entity_ledger_wiring
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import entity_server as server        # noqa: E402
from backend import ledger_port as lp              # noqa: E402

LEVEL = {'levelId': 1073741839, 'queue': 'queue-dir', 'sessionPath': 'session.json'}
REQUEST_ID = 'w15ledger0001'


def receipt(request_id=REQUEST_ID, ok=True, action='save'):
    """The envelope ``tools/authoring/author.py`` returns for one dispatch."""
    return {'ok': ok, 'method': 'mw.scene.saveLevel', 'requestId': request_id,
            'backend': {'action': action, 'levelId': LEVEL['levelId'], 'ok': ok,
                        'nativeStatus': 0 if ok else 7, 'run': 'run-dir'},
            'journal': 'journal-dir'}


class LedgerWiringTest(unittest.TestCase):
    """The producer writes the row the permit reads, or it refuses to dispatch."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='w15-ledger-'))
        self.patch = mock.patch.object(server, 'LEDGER_ROOT', self.root)
        self.patch.start()
        self.dispatches = []

        def fake_run(argv, **kwargs):
            self.dispatches.append(list(argv))
            return receipt()

        self.run_patch = mock.patch.object(server, '_run', side_effect=fake_run)
        self.run_patch.start()

    def tearDown(self):
        self.run_patch.stop()
        self.patch.stop()
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def test_the_dispatch_writes_a_row_the_permit_can_read(self):
        """The row exists, and the port the Cordis plugin mounts projects it correctly."""
        server.dispatch_write(LEVEL, 'save', {}, 'review.json', REQUEST_ID)
        self.assertEqual(len(self.dispatches), 1, 'the native dispatch must still happen once')

        view = lp.LedgerPort(self.root).read_operation(REQUEST_ID)
        self.assertIsNotNone(view, 'the permit reads readOperation(); it must find this row')
        self.assertEqual(view['operationState'], 'known-complete')
        self.assertTrue(view['writeExecuted'])
        self.assertEqual(view['requestId'], REQUEST_ID)

    def test_a_second_write_for_the_same_id_is_refused_before_the_dispatch(self):
        """IDEM-1: the same operationId is a replay, and a replay dispatches nothing."""
        server.dispatch_write(LEVEL, 'save', {}, 'review.json', REQUEST_ID)
        with self.assertRaises(server.BusinessError) as caught:
            server.dispatch_write(LEVEL, 'save', {}, 'review.json', REQUEST_ID)
        self.assertEqual(caught.exception.code, 'REQUEST_ALREADY_CLAIMED')
        self.assertEqual(len(self.dispatches), 1,
                         'the second attempt must not reach the native layer')

    def test_an_unwritable_ledger_refuses_the_dispatch_instead_of_bypassing_it(self):
        """A row that cannot be written is a refusal: nothing may be dispatched."""
        self.patch.stop()
        blocker = self.root / REQUEST_ID
        blocker.write_text('{}', encoding='utf-8')
        self.patch = mock.patch.object(server, 'LEDGER_ROOT', self.root)
        self.patch.start()

        with self.assertRaises(server.BusinessError) as caught:
            server.dispatch_write(LEVEL, 'save', {}, 'review.json', REQUEST_ID)
        self.assertEqual(caught.exception.code, 'BUSINESS_LEDGER_UNAVAILABLE')
        self.assertEqual(self.dispatches, [],
                         'a write whose ledger row cannot exist must never reach the game')

    def test_a_refused_native_write_is_published_as_known_failed(self):
        """A dispatch that came back not-ok is a recorded failure, not silence."""
        self.run_patch.stop()
        self.run_patch = mock.patch.object(server, '_run', side_effect=lambda argv, **kw: receipt(ok=False))
        self.run_patch.start()
        server.dispatch_write(LEVEL, 'save', {}, 'review.json', REQUEST_ID)
        view = lp.LedgerPort(self.root).read_operation(REQUEST_ID)
        self.assertEqual(view['operationState'], 'known-failed')

    def test_the_producer_and_the_permit_name_the_same_root(self):
        """One row set, two readers: the two sides must not drift apart.

        Both are literals under the project root, so the invariant is read out of the
        two sources rather than asserted against a value this test has already patched.
        """
        entity = (ROOT / 'backend' / 'entity_server.py').read_text(encoding='utf-8')
        self.assertIn("LEDGER_ROOT = ROOT / '.runtime/business-ledger'", entity,
                      'the producer must name the plugin\'s ledger directory')
        plugin = (ROOT / 'plugins' / 'miliastra' / 'src' / 'ledger-port.ts').read_text(encoding='utf-8')
        self.assertIn("join(projectRoot, '.runtime', 'business-ledger')", plugin,
                      'the plugin\'s defaultLedgerRoot must name the same directory')


if __name__ == '__main__':
    unittest.main()
