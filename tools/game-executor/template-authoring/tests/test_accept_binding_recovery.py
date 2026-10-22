"""Offline producer/acceptor seams; no preparation, process access or dispatch."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import accept_binding_recovery as api
import build_binding_recovery_candidate as candidate
import prepare_binding_recovery as prepare
import binding_recovery_receipt as raw_api
import binding_receipt as prior_api
from test_binding_recovery_receipt import fixture, refusal_fixture, pending_fixture


def record(raw):
    decoded = raw_api.decode(bytes(raw))
    return dict(bindingRecoveryResultBytes=len(raw), bindingRecoveryResultHex=bytes(raw).hex(),
        bindingRecoveryResult={**decoded['native'], **decoded['result']}, **{
            key + suffix: value
            for key, at, size in (('afterSnapshot', raw_api.AFTER_AT, raw_api.SNAPSHOT_BYTES),
                ('beforeComponents', raw_api.BEFORE_COMPONENTS_AT, 11376),
                ('afterComponents', raw_api.AFTER_COMPONENTS_AT, 11376),
                ('editResult', raw_api.EDIT_AT, prior_api.EDIT_BYTES))
            for suffix, value in (('Bytes', size), ('Hex', bytes(raw[at:at + size]).hex()))})


class RecoveryAcceptorTests(unittest.TestCase):
    def test_generated_header_binds_original_raw_exact_identity_and_old_profile(self):
        prior, _ = fixture()
        refusal = refusal_fixture(prior)
        pending = pending_fixture(prior)
        d = raw_api.verify_prior(prior)
        identity = {key: d['action'][key] for key in ('entityId', 'templateId', 'componentId', 'owner', 'wrapper', 'config')}
        identity['transaction'] = d['edit']['transaction']
        session = dict(pid=1234, tid=5678, processCreation=123456, threadCreation=123459,
            image=str(api.profiles.TARGET_IMAGE))
        prepared = dict(session=session, identity=identity, nonce=991, deadline=999999, messageId=0xc123)
        raw = bytes(raw_api.SNAPSHOT_BYTES)
        runtime = json.loads(candidate.DEFAULT_RUNTIME_PROFILE.read_text())
        # This producer call only writes a header. The synthetic raw hash is local to the fixture.
        with tempfile.TemporaryDirectory(dir=api.ROOT / '.runtime') as directory:
            run = Path(directory)
            with patch.object(candidate, 'PRIOR_RAW_SHA256', hashlib.sha256(prior).hexdigest()), \
                 patch.object(candidate, 'TOKEN_REFUSAL_RAW_SHA256', hashlib.sha256(refusal).hexdigest()), \
                 patch.object(candidate, 'PENDING_DIAGNOSTIC_RAW_SHA256', hashlib.sha256(pending).hexdigest()):
                prepare.emit_header(run, dict(identity=identity), raw, runtime, api.profiles.load_profile(), prior,
                    refusal, pending, session, prepared['deadline'], prepared['messageId'], prepared['nonce'])
            header = run / 'target_config.h'
            api.compiled_header(header, prepared, raw, prior, runtime, refusal, pending)
            original = header.read_text()
            header.write_text(original.replace('#define TA_RECOVERY_TOKEN ' + str(identity['transaction']) + 'ULL',
                '#define TA_RECOVERY_TOKEN 1ULL'))
            with self.assertRaisesRegex(ValueError, 'RECOVERY_COMPILED_IDENTITY:TA_RECOVERY_TOKEN'):
                api.compiled_header(header, prepared, raw, prior, runtime, refusal)
            header.write_text(original)
            with self.assertRaisesRegex(ValueError, 'RECOVERY_COMPILED_ARRAY:TA_RECOVERY_PRIOR'):
                api.compiled_header(header, prepared, raw, prior[:-1] + b'\x01', runtime, refusal)
            with self.assertRaisesRegex(ValueError, 'RECOVERY_COMPILED_ARRAY:TA_RECOVERY_TOKEN_REFUSAL'):
                api.compiled_header(header, prepared, raw, prior, runtime, refusal[:-1] + b'\x01')

    def test_raw_summary_and_duplicate_are_not_independent_truth(self):
        _, raw = fixture(); row = record(raw)
        self.assertEqual(api.decode_native(row)[1], bytes(raw))
        row['bindingRecoveryResult']['transactionClosed'] = False
        with self.assertRaisesRegex(ValueError, 'RECOVERY_SUMMARY:transactionClosed'): api.decode_native(row)
        row = record(raw); row['editResultHex'] = '00' + row['editResultHex'][2:]
        with self.assertRaisesRegex(ValueError, 'RECOVERY_DUPLICATE_RAW:editResult'): api.decode_native(row)

    def test_transport_failure_cannot_become_transaction_closed(self):
        row = dict(scope=api.SCOPE, selfTestOnly=False, ok=True, probeElevatedHigh=True, transportOk=True,
            pid=4, tid=5, callbackCount=1, activeCallbacks=0, unhooked=True, hostPostUnhookPings=0,
            snapshotStatus=0, snapshotBytes=raw_api.SNAPSHOT_BYTES)
        api.transport(row, dict(pid=4, tid=5), api.SCOPE, successful=True)
        for key, value in (('callbackCount', 2), ('unhooked', False), ('ok', False)):
            changed = dict(row); changed[key] = value
            with self.assertRaisesRegex(ValueError, 'RECOVERY_NATIVE_TRANSPORT'):
                api.transport(changed, dict(pid=4, tid=5), api.SCOPE, successful=True)

    def test_real_prior_uses_frozen_sources_not_current_binding_source(self):
        run = api.ROOT / '.runtime/template-authoring/prepared-binding/20261013-102256-7dc1ea2e2b'
        if not (run / 'stdout.jsonl').exists(): self.skipTest('historical evidence absent')
        prepared = json.loads((run / 'prepared.json').read_text())
        review = dict(priorRun=str(run), priorEvidenceHashes=candidate.prior_evidence_hashes(run),
            priorStdoutSha256=candidate.PRIOR_STDOUT_SHA256, priorRawSha256=candidate.PRIOR_RAW_SHA256,
            session={key: prepared['session'][key] for key in api.requests.SESSION_FIELDS}, levelId=prepared['levelId'])
        with patch.object(candidate, 'source_hashes', side_effect=AssertionError('current-source must not validate history')):
            raw, _ = api.historical_prior(review)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), candidate.PRIOR_RAW_SHA256)
        if candidate.TOKEN_REFUSAL_RUN.exists():
            review['tokenRefusalRun'] = str(candidate.TOKEN_REFUSAL_RUN)
            review['tokenRefusalEvidenceHashes'] = candidate.token_refusal_evidence_hashes(candidate.TOKEN_REFUSAL_RUN)
            refusal = api.historical_token_refusal(review, raw, candidate)
            self.assertEqual(hashlib.sha256(refusal).hexdigest(), candidate.TOKEN_REFUSAL_RAW_SHA256)
            review['pendingDiagnosticRun'] = str(candidate.PENDING_DIAGNOSTIC_RUN)
            review['pendingDiagnosticEvidenceHashes'] = candidate.pending_diagnostic_evidence_hashes(candidate.PENDING_DIAGNOSTIC_RUN)
            pending = api.historical_pending_diagnostic(review, raw, refusal, candidate)
            self.assertEqual(hashlib.sha256(pending).hexdigest(), candidate.PENDING_DIAGNOSTIC_RAW_SHA256)
        review['priorRawSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'RECOVERY_PRIOR_RAW_SHA'): api.historical_prior(review)


if __name__ == '__main__': unittest.main()
