"""Integration boundaries for the map workflows; no editor or native dispatch."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import author


class MapWorkflowTests(unittest.TestCase):
    def parse(self, *argv):
        return author.parser().parse_args(list(argv))

    def test_scale_prepare_and_status_do_not_require_live_version(self):
        for action, tail in (
            ('prepare', ['--plan', 'a plan.json', '--operation-id', 'map-01', '--level-id', '1073741842']),
            ('status', ['--operation', 'an operation', '--offset', '128']),
            ('verify-save', ['--operation', 'an operation', '--save-run', 'a saved run']),
        ):
            with self.subTest(action=action), patch.object(author, 'require_compatible') as guard, \
                    patch.object(author, 'process_json', return_value={'ok': True}) as child:
                args = self.parse('scene-scale', action, *tail)
                self.assertTrue(author.foundation_call(args)['ok'])
                guard.assert_not_called()
                self.assertEqual(child.call_args.args[0], [author.sys.executable,
                    str(author.ROOT / 'tools/game-executor/scene_scale.py'), action, *tail])
                self.assertIsNone(child.call_args.kwargs['timeout'])

    def test_live_workflow_uses_explicit_queue_without_outer_journal(self):
        queue = author.ROOT / '.runtime/editor-bridge/test-queue'
        with patch.object(author, 'require_compatible') as guard, \
                patch.object(author, 'normalized_queue', return_value=queue), \
                patch.object(author, 'process_json', return_value={'ok': False, 'pending': True,
                                                                 'retryAttempted': False}) as child, \
                patch.object(author, 'execute', side_effect=AssertionError('must use workflow ledger')):
            args = self.parse('--elevated-queue', str(queue), 'scene-scale', 'run',
                              '--operation', 'operation', '--session', 'session')
            reply = author.foundation_call(args)
            self.assertTrue(reply['pending'])
            self.assertEqual(child.call_args.args[0][-2:], ['--elevated-queue', str(queue)])
            guard.assert_called_once_with('native-scene')
            child.assert_called_once()

    def test_duplicate_transport_is_rejected_before_dispatch(self):
        for tail in (['--direct-elevated'], ['--elevated-queue', 'q'], ['--elevated-queue=q']):
            with self.subTest(tail=tail), patch.object(author, 'require_compatible'), \
                    patch.object(author, 'process_json') as child:
                args = self.parse('--elevated-queue', 'q', 'scene-scale', 'run', *tail)
                with self.assertRaisesRegex(ValueError, 'TRANSPORT_SPECIFIED_TWICE'):
                    author.foundation_call(args)
                child.assert_not_called()

    def test_lost_live_receipt_is_uncertain_and_never_retried(self):
        with patch.object(author, 'require_compatible'), \
                patch.object(author, 'process_json', side_effect=RuntimeError('private detail')) as child:
            result = author.foundation_call(self.parse('scene-scale', 'run', '--operation', 'operation'))
            self.assertTrue(result['outcomeUncertain'])
            self.assertFalse(result['retryAttempted'])
            self.assertNotIn('private detail', author.encoded(result))
            child.assert_called_once()

    def test_large_inspection_flag_is_bound_and_forwarded(self):
        args = self.parse('entity-inspect', '--level-id', '1073741842', '--request-id', 'large-01', '--large-scene')
        command = author.command_from_args(args)
        self.assertTrue(command['largeScene'])
        with patch.object(author, 'require_compatible'), \
                patch.object(author, 'process_json', return_value={'ok': True}) as child:
            author.scene_call(command)
            self.assertIn('--large-scene', child.call_args.args[0])
        legacy = author.command_from_args(self.parse('entity-inspect', '--level-id', '1073741842', '--request-id', 'legacy-01'))
        self.assertNotIn('largeScene', legacy)

    def test_geometry_workflows_route_only_to_their_fixed_entrypoints(self):
        for name, script, action in (
            ('entity-transform', 'tools/entity-transform/cli.py', 'verify-save'),
            ('terrain', 'tools/map-terrain/terrain_cli.py', 'decode'),
            ('entity-transform', 'tools/entity-transform/cli.py', 'physics-decode'),
            ('playtest-control', 'tools/playtest-control/cli.py', 'decode'),
        ):
            with self.subTest(name=name), patch.object(author, 'require_compatible') as guard, \
                    patch.object(author, 'process_json', return_value={'ok': True}) as child:
                author.foundation_call(self.parse(name, action, '--run', 'candidate run'))
                self.assertEqual(child.call_args.args[0], [author.sys.executable,
                    str(author.ROOT / script), action, '--run', 'candidate run'])
                guard.assert_not_called()

    def test_physics_build_and_runtime_terrain_flags_stay_offline(self):
        for name, action, tail in (
            ('entity-transform', 'physics-inspect', ['--baseline', 'snapshot', '--entity-id', '1077936129', '--reference-entity-id', '1077936134']),
            ('terrain', 'prepare', ['--baseline', 'snapshot', '--inspect-only', '--runtime-probe', '--terrain-id', '1073741825']),
            ('terrain', 'prepare', ['--baseline', 'snapshot', '--refresh-only', '--save', 'formal.gil', '--terrain-id', '1073741825']),
            ('playtest-control', 'prepare', ['--session', 'session.json', '--target-level', '1073741843']),
        ):
            with self.subTest(name=name), patch.object(author, 'require_compatible') as guard, \
                    patch.object(author, 'process_json', return_value={'ok': True}) as child:
                author.foundation_call(self.parse(name, action, *tail))
                self.assertEqual(child.call_args.args[0][-len(tail):], tail)
                guard.assert_not_called()

    def test_mode_observation_dispatch_is_guarded_and_uses_fixed_queue(self):
        queue = author.ROOT / '.runtime/editor-bridge/mode-test-queue'
        with patch.object(author, 'normalized_queue', return_value=queue), \
                patch.object(author, 'require_compatible') as guard, \
                patch.object(author, 'process_json', return_value={'ok': True}) as child:
            author.foundation_call(self.parse('--elevated-queue', str(queue), 'playtest-control', 'dispatch', '--run', 'card'))
        guard.assert_called_once_with('native-scene')
        self.assertEqual(child.call_args.args[0][-2:], ['--elevated-queue', str(queue)])

    def test_terrain_batch_bookkeeping_never_dispatches_or_inherits_queue(self):
        actions = {
            'batch-create': ['--save', 'formal.gil', '--terrain-id', '1073741843', '--edits', 'all.json'],
            'batch-prepare': ['--batch', 'batch', '--inspection', 'inspect', '--baseline', 'context'],
            'batch-accept': ['--batch', 'batch', '--run', 'applied-card'],
            'batch-status': ['--batch', 'batch'],
            'batch-abandon': ['--batch', 'batch'],
            'batch-verify-save': ['--batch', 'batch', '--save-run', 'saved'],
        }
        for action, tail in actions.items():
            with self.subTest(action=action), patch.object(author, 'require_compatible') as guard, \
                    patch.object(author, 'normalized_queue') as queue, \
                    patch.object(author, 'process_json', return_value={'ok': True}) as child:
                author.foundation_call(self.parse('terrain', action, *tail))
                self.assertEqual(child.call_args.args[0], [author.sys.executable,
                    str(author.ROOT / 'tools/map-terrain/terrain_cli.py'), action, *tail])
                guard.assert_not_called()
                queue.assert_not_called()
                child.reset_mock()
                with self.assertRaisesRegex(ValueError, 'AUTHOR_QUEUE_NOT_APPLICABLE_TO_LOCAL_WORKFLOW'):
                    author.foundation_call(self.parse('--elevated-queue', 'unused', 'terrain', action, *tail))
                child.assert_not_called()

    def test_unknown_geometry_action_never_reaches_a_child(self):
        # These paths deliberately offer no arbitrary-script dispatch verb.
        with patch.object(author, 'process_json') as child, \
                patch.object(author.argparse.ArgumentParser, 'error', side_effect=ValueError('invalid action')):
            with self.assertRaises(ValueError):
                self.parse('terrain', 'run-script', 'arbitrary.py')
            child.assert_not_called()

    def test_fixed_entrypoints_bootstrap_in_the_helpers_isolated_python(self):
        # --help exits during parsing. This exercises real isolated imports, but
        # cannot build/dispatch a candidate, inspect a process or ask for elevation.
        for contract in author.FOUNDATION_COMMANDS.values():
            with self.subTest(script=contract['script']):
                result = subprocess.run([author.sys.executable, '-B', '-I', '-S',
                    str(author.ROOT / contract['script']), '--help'], capture_output=True,
                    encoding='utf-8', timeout=30, cwd=author.ROOT)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
