"""T03 / DS-07 -- the real ledger port behind ``MiliastraBusinessLedgerPort``.

WHY THIS FILE EXISTS
--------------------
``plugins/miliastra/src/lifecycle.ts`` declares one dependency, the ledger port:

    readOperation(operationId)      -> MiliastraOperationView | null
    recordObservation(observation)  -> MiliastraOperationView
    listOpenOperations()            -> MiliastraOperationView[]      (optional)

Until now nothing implemented it.  The T03 suite ran against
``fixtures/t03-fake-ledger.ts``, an in-memory stand-in, and the module was
deliberately kept out of ``src/index.ts`` so that no *invented* ledger could be
mounted.  This module is the real implementation: a thin, deterministic
projection of ``backend/operation_state.py``'s ``OperationLedger`` onto the
frozen port shape, served over newline-delimited JSON on stdio so the Cordis
(Node) process can read it.

WHAT IT IS NOT
--------------
* It is not a second ledger.  Every answer is read from ``OperationLedger``,
  which in turn reads the on-disk claim / record / receipt / dispatch-evidence
  files.  This module writes exactly one thing of its own -- an append-only
  ``observations.jsonl`` under the *existing* operation directory -- and it
  never writes a state, a verdict, a receipt or a dispatch.
* It is not a dispatcher.  There is no code path here that claims, derives
  material, publishes a receipt it was not handed, or sends anything to the
  game.  ``recordObservation`` refuses an id the ledger has never claimed
  instead of creating one.
* It is not a level- or request-id authoriser.  Attribution of a receipt to an
  operation is delegated to ``OperationLedger.late_receipt``, which already
  refuses a mismatched requestId or a mismatched level.

THE ROOT IS ALWAYS EXPLICIT
---------------------------
``OperationLedger`` deliberately carries no ROOT constant and no default path,
so it cannot reach the real author journal by accident.  This port keeps that
property: ``--root`` is required, and a run without it exits non-zero rather
than picking a directory.

PROTOCOL
--------
One JSON object per line on stdin, one JSON object per line on stdout:

    -> {"id": 7, "method": "readOperation", "params": {"operationId": "op-1"}}
    <- {"id": 7, "ok": true, "result": {"view": {...}}}
    <- {"id": 7, "ok": true, "result": {"view": null}}
    <- {"id": 7, "ok": false, "error": {"code": "...", "message": "..."}}

Methods: ``readOperation`` / ``recordObservation`` / ``listOpenOperations`` /
``ping`` (a liveness probe that reads nothing).

Error codes are stable and are *not* the lifecycle's own codes: the lifecycle
maps a transport failure to ``LIFECYCLE_LEDGER_UNAVAILABLE`` and answers
"unknown operation" from its own pre-read.  Codes here name what the *ledger*
refused:

    LEDGER_UNKNOWN_OPERATION   no claim exists; nothing may be created
    OPERATION_ID_INVALID       not the G01 ``^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$``
    REQUEST_ID_CONFLICT        the receipt belongs to a different requestId
    TARGET_HANDLE_RECEIPT_CHANGED  the receipt names a different level
    LEDGER_READ_FAILED         the ledger raised while reading

Run it as ``python -m backend.ledger_port --root <dir>`` from the project root.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Import the real ledger.  Two shapes are supported so the module works both as
# ``python -m backend.ledger_port`` (project root on sys.path) and as a bare
# script invocation from inside ``backend/``.
try:                                              # pragma: no cover - import shim
    from backend import operation_state as ops
except ImportError:                               # pragma: no cover - import shim
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from backend import operation_state as ops

CONTRACT_VERSION = ops.CONTRACT_VERSION
SCHEMA_VERSION = ops.SCHEMA_VERSION

#: The frozen view shape ``MiliastraOperationView`` in src/lifecycle.ts requires.
VIEW_FIELDS = ('operationId', 'operationState', 'ledgerRef', 'dispatchEvidence',
               'requestId', 'journalRef', 'writeExecuted')

#: Append-only observation log this port owns inside an existing operation dir.
OBSERVATIONS_NAME = 'observations.jsonl'


class PortRefusal(Exception):
    """A refusal with a stable code.  Raised before anything is written."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


# --------------------------------------------------------------------------- #
# The port: a projection of OperationLedger onto the frozen view shape
# --------------------------------------------------------------------------- #

class LedgerPort:
    """Read-only-by-contract view over one explicit ``OperationLedger`` root.

    The only write it performs is appending an observation to an operation that
    already exists.  ``readOperation`` and ``listOpenOperations`` write nothing
    at all, not even a directory.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.ledger = ops.OperationLedger(self.root)

    # -- helpers ----------------------------------------------------------- #

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _record(self, operation_id: str) -> dict:
        return self.ledger._read(operation_id, ops.RECORD_NAME) or {}

    def _view(self, operation_id: str) -> dict:
        """Project one operation onto the frozen view.  Reads only.

        ``ledgerRef`` is the operation's own directory: the same free-form
        "where the row lives" pointer ``business_contract.make_error`` accepts
        in ``error.reconcile.ledgerRef``, so a model handed a reconcile route
        can open it.  ``writeExecuted`` is the row's recorded value, or ``None``
        when the row does not say -- never a guess.
        """
        state = self.ledger.state_of(operation_id)
        record = self._record(operation_id)
        directory = self.ledger.directory(operation_id)
        write_executed = record.get('writeExecuted')
        if not isinstance(write_executed, bool):
            write_executed = None
        request_id = record.get('requestId')
        if not isinstance(request_id, str) or request_id == '':
            request_id = None
        journal_ref = record.get('journalRef')
        if not isinstance(journal_ref, str) or journal_ref == '':
            journal_ref = None
        return {
            'operationId': operation_id,
            'operationState': state,
            'ledgerRef': str(directory),
            'dispatchEvidence': list(self.ledger.dispatch_evidence(operation_id)),
            'requestId': request_id,
            'journalRef': journal_ref,
            'writeExecuted': write_executed,
        }

    # -- the three port methods ------------------------------------------- #

    def read_operation(self, operation_id: str) -> dict | None:
        """``readOperation``.  null when the ledger has never claimed the id."""
        ops.validate_operation_id(operation_id)
        if not self.ledger.directory(operation_id).is_dir():
            return None
        return self._view(operation_id)

    def list_open_operations(self) -> list:
        """``listOpenOperations``.  A fresh instance's only way to learn of the
        previous instance's unresolved writes.  Read-only; lists never claim."""
        views = []
        for row in self.ledger.list_open_operations():
            views.append(self._view(row['operationId']))
        return views

    def record_observation(self, observation: dict) -> dict:
        """``recordObservation`` -- attribute an observation to an EXISTING op.

        Two honest paths, and no third:

        * the observation carries a ``receipt`` body -- delegate to
          ``OperationLedger.late_receipt``, which refuses a mismatched
          requestId or level and otherwise publishes through the ledger's own
          ``publish``.  The verdict is the ledger's, never this port's.
        * the observation carries no receipt -- append it to
          ``observations.jsonl`` under the operation and re-read the
          authoritative state.  The state is therefore UNCHANGED; a bare
          observation cannot invent an outcome.

        An id the ledger has never claimed is refused.  A late receipt must
        never create an operation.
        """
        operation_id = observation.get('operationId')
        ops.validate_operation_id(operation_id)
        if not self.ledger.directory(operation_id).is_dir():
            raise PortRefusal('LEDGER_UNKNOWN_OPERATION',
                              'the ledger has never claimed operationId %r; an observation must '
                              'not create an operation' % operation_id)
        if not self.ledger._read(operation_id, ops.CLAIM_NAME):
            raise PortRefusal('LEDGER_UNKNOWN_OPERATION',
                              'operationId %r has no claim on disk; the observation cannot be '
                              'attributed to an operation that was never claimed' % operation_id)

        receipt = observation.get('receipt')
        if isinstance(receipt, dict):
            # ``late_receipt`` has two ways to refuse: it *returns*
            # ``attributed: False`` for a requestId/level mismatch, and it
            # *raises* OperationConflict/TargetRefused when a first receipt is
            # already published and this one differs.  Both are refusals, and
            # both must reach the caller as one shape; an escaping exception
            # would look like a transport failure instead of the ledger saying no.
            try:
                outcome = self.ledger.late_receipt(operation_id, receipt)
            except (ops.OperationConflict, ops.TargetRefused) as refused:
                raise PortRefusal(getattr(refused, 'code', 'LEDGER_OBSERVATION_REFUSED'),
                                  str(refused)) from None
            if not outcome.get('attributed'):
                raise PortRefusal(outcome.get('code') or 'LEDGER_OBSERVATION_REFUSED',
                                  outcome.get('reason') or 'the ledger refused the observation',
                                  **{k: v for k, v in outcome.items()
                                     if k in ('boundRequestId', 'incomingRequestId',
                                              'boundLevelId', 'incomingLevelId')})
            return self._view(operation_id)

        self._append_observation(operation_id, observation)
        return self._view(operation_id)

    def _append_observation(self, operation_id: str, observation: dict) -> None:
        """Append one observation record.  Append-only; never rewrites state."""
        record = {
            'schemaVersion': SCHEMA_VERSION,
            'contractVersion': CONTRACT_VERSION,
            'operationId': operation_id,
            'requestId': observation.get('requestId'),
            'receiptRef': observation.get('receiptRef'),
            'observedUtc': observation.get('observedUtc') or self._now(),
            'detail': observation.get('detail'),
            'recordedUtc': self._now(),
        }
        path = self.ledger.directory(operation_id) / OBSERVATIONS_NAME
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False) + '\n')
            stream.flush()


# --------------------------------------------------------------------------- #
# The stdio service
# --------------------------------------------------------------------------- #

def _dispatch(port: LedgerPort, method: str, params: dict) -> dict:
    """One request -> one result object.  Raises PortRefusal / ValueError."""
    if method == 'ping':
        return {'pong': True, 'root': str(port.root), 'contractVersion': CONTRACT_VERSION}
    if method == 'readOperation':
        return {'view': port.read_operation(params['operationId'])}
    if method == 'listOpenOperations':
        return {'views': port.list_open_operations()}
    if method == 'recordObservation':
        return {'view': port.record_observation(params)}
    raise ValueError('unknown method %r' % (method,))


def _error_payload(exc: Exception) -> dict:
    if isinstance(exc, PortRefusal):
        return {'code': exc.code, 'message': exc.message, **exc.extra}
    if isinstance(exc, (ops.InputInvalid, ops.OperationConflict, ops.TargetRefused)):
        code = getattr(exc, 'code', None) or 'OPERATION_ID_INVALID'
        return {'code': code, 'message': str(exc)}
    return {'code': 'LEDGER_READ_FAILED', 'message': '%s: %s' % (type(exc).__name__, exc)}


def serve(port: LedgerPort, stdin=None, stdout=None) -> int:
    """Read requests until EOF.  One malformed line is reported, never fatal."""
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get('id')
            result = _dispatch(port, request.get('method'), request.get('params') or {})
            response = {'id': request_id, 'ok': True, 'result': result}
        except Exception as exc:                     # noqa: BLE001 - reported verbatim
            response = {'id': request_id, 'ok': False, 'error': _error_payload(exc)}
        stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n')
        stdout.flush()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='T03/DS-07 real ledger port over stdio.')
    parser.add_argument('--root', required=True,
                        help='the OperationLedger root directory. Required: this port has no '
                             'default ledger path, so it cannot reach a journal by accident.')
    arguments = parser.parse_args(argv)
    if not str(arguments.root).strip():
        sys.stderr.write('ledger_port: --root must not be blank\n')
        return 2
    port = LedgerPort(Path(arguments.root))
    return serve(port)


if __name__ == '__main__':                           # pragma: no cover - entry point
    sys.exit(main())
