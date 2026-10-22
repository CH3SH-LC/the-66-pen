from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cli

class OfflineErrorTests(unittest.TestCase):
    def test_save_validation_error_retains_proven_historical_cleanup(self):
        observed=dict(called=True,nativeStarted=True,outcomeUncertain=False,cleanupVerified=True,safeToRelease=True)
        with patch.object(cli,'decode',return_value=observed):
            state=cli.failure_state('old-run','verify-save')
        self.assertFalse(state['called'])
        self.assertFalse(state['nativeStarted'])
        self.assertFalse(state['outcomeUncertain'])
        self.assertTrue(state['cleanupVerified'])
        self.assertTrue(state['historicalTransformExecution']['called'])

    def test_unreadable_prior_receipt_does_not_invent_cleanup(self):
        uncertain=dict(called=True,nativeStarted=True,outcomeUncertain=True,cleanupVerified=False,safeToRelease=False,replayForbidden=True)
        with patch.object(cli,'decode',side_effect=ValueError('missing')),patch.object(cli,'uncertainty',return_value=uncertain):
            state=cli.failure_state('old-run','verify-save')
        self.assertFalse(state['called'])
        self.assertTrue(state['outcomeUncertain'])
        self.assertFalse(state['cleanupVerified'])
