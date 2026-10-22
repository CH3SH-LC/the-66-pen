"""Check the real saved baseline and combined candidate without game access."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.gameplan.demo import offline_farming_bundle as bundle


class OfflineBundleTests(unittest.TestCase):
    def setUp(self):
        folder = bundle.OUTPUT_ROOT/'tests'
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)/'candidate'
        self.assertTrue(self.output.resolve().is_relative_to(bundle.OUTPUT_ROOT))

    def test_complete_candidate_round_trip_never_dispatches(self):
        with patch('subprocess.run', side_effect=AssertionError('offline cannot run processes')):
            result = bundle.write_bundle(self.output, group_index=101)
            verified = bundle.verify_bundle(self.output)
        self.assertTrue(result['ok'] and verified['ok'])
        player = json.loads((self.output/'player-interaction.json').read_text(encoding='utf-8'))
        definitions = [n['definitionId'] for n in player['batchPlan']['nodes']]
        self.assertEqual(definitions.count(316), 1)
        self.assertEqual(definitions.count(702), 1)
        self.assertNotIn(688, definitions)  # No second starting-currency grant.
        self.assertEqual(len(player['followups']), player['manifest']['shape']['values'])
        self.assertFalse(result['gameModified'])
        self.assertFalse(result['dispatchable'])

    def test_hash_rewrite_does_not_hide_changed_shop_patch(self):
        bundle.write_bundle(self.output, group_index=101)
        path = self.output/'shop-detach.json'
        altered = json.loads(path.read_text(encoding='utf-8'))
        altered['operations'].pop()
        raw = bundle.compact(altered).encode('utf-8')
        path.write_bytes(raw)
        manifest_path = self.output/'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['files'][path.name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        manifest_path.write_text(bundle.compact(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'BUNDLE_CONTENT_CHANGED'):
            bundle.verify_bundle(self.output)

    def test_no_replay_or_outside_output(self):
        bundle.write_bundle(self.output, group_index=101)
        with self.assertRaisesRegex(ValueError, 'ALREADY_EXISTS'):
            bundle.write_bundle(self.output, group_index=101)
        with self.assertRaisesRegex(ValueError, 'TASK_SUBDIRECTORY'):
            bundle.write_bundle(bundle.ROOT/'not-an-artifact', group_index=101)


if __name__ == '__main__':
    unittest.main()
