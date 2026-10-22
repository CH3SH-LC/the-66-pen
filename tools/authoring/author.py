"""Bounded native scene and graph authoring; no automatic bridge load or retry.

Scene dispatch is gated by the separate ``native-scene`` component of
``tools/compatibility/version_guard.py``: the pinned read-only 7.1 profile must
still describe the installed image.  That is disk evidence only -- not runtime
acceptance and not write permission.  Every native mutation therefore also
carries an explicit ``--level-id``, an explicit ``--session`` (or none, so
``scene_cli`` revalidates the project session pointer) and an internal
``--review`` evidence record; ``scene_cli`` re-validates the request hash plus a
complete snapshot, review and fresh session before it builds anything or asks
for UAC.  Graph work stays on the editor assembly baseline.  Nothing here
auto-loads a bridge or auto-retries an uncertain outcome.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
JOURNAL = ROOT / '.runtime/authoring/requests'
RUNS = ROOT / '.runtime/editor-bridge/runs'
#: Where a run-scoped dispatch receipt is allowed to land.  All four are
#: producer trees, none of them is the run under audit, and none of them is
#: chosen by the caller.  ``receiptRoot``/``nativeRoot`` are two of the
#: directories the authenticity layer already scans for corroboration.
PRODUCER_ROOTS = {
    'journalRoot': str(JOURNAL),
    'queueRoot': str(ROOT / '.runtime/editor-bridge/elevated-queue'),
    'receiptRoot': str(RUNS),
    'nativeRoot': str(ROOT / '.runtime/game-executor/scene-cli'),
}
#: The receipt producer.  Optional: an installation without it still
#: dispatches exactly as before, it just leaves no run-scoped receipt.
DISPATCH_RECEIPT = ROOT / 'backend' / 'dispatch_receipt.py'
RUN_ID_IN_PATH = re.compile(r'(?:^|[/\\])([0-9a-f]{32})(?:[/\\]|$)')
# 2026-10-09: the template whitelist is REMOVED by user directive. This CLI used to offer
# only the ids in build_scene_profile.TEMPLATES; it now accepts any uint32. Look the id up in
# the prefab catalog first -- as guidance, not as a gate.
sys.path.insert(0, str(ROOT / 'tools/game-executor'))
from native_profiles import powershell_host  # noqa: E402
#: Graph category kinds a create may request: the four the recordings carry
#: (data/node-contracts/shared/graph-kinds.json). 20000 is the server kind every proven
#: create used; the client kinds stay requestable so the native boundary is probed per
#: kind instead of hidden behind a hardcode.
GRAPH_KINDS = (20000, 20001, 20002, 20007)
#: The kind a create uses when --graph-kind is not given (the proven server kind).
DEFAULT_GRAPH_KIND = 20000
GRAPH_ACTIONS = {'create': 'create', 'lookup': 'lookup', 'add': 'add-node', 'wire': 'connect',
                 'unwire': 'disconnect', 'build-print': 'build-print', 'set': 'set-print', 'condition': 'set-condition', 'count': 'build-count-gate', 'bind': 'bind', 'inspect': 'inspect', 'export': 'export',
                 'value': 'set-value', 'values': 'set-values', 'slots': 'pin-slots', 'build-plan': 'build-plan'}
#: Pin kinds are the pinned 7.1 native enum values, not enum guesses: 1 = input
#: execution, 2 = output execution, 3 = input data, 4 = output data.  A source
#: must be an output pin, a target an input pin, and the only legal pairs are
#: execution 2 -> 1 and data 4 -> 3 (INTERFACE-INVENTORY.md:273).
EDGE_SOURCE_KINDS = (2, 4)
EDGE_TARGET_KINDS = (1, 3)
EDGE_PAIRING = {(2, 1): 'execution', (4, 3): 'data'}
#: Execution flow has a fixed fan-out: a branch exposes two flow outputs.
EDGE_FLOW_SOURCE_INDEXES = (0, 1)
EDGE_FLOW_TARGET_INDEX = 0


def validate_edge(payload):
    """Refuse a malformed edge request by name before any lease or dispatch.

    Only direction and bounds are decidable here.  The *declared port types*
    live in the editor's live node-definition registry, so type equality is
    enforced by the adapter (the write authority) and is never guessed here.
    A refusal is a ValueError, which ``main`` reports as ``{ok:false,error}``
    with no journal, no lease and no dispatch -- so a rejected edge leaves
    nothing to reconcile.
    """
    from_node = payload['fromNodeId']
    to_node = payload['toNodeId']
    from_kind = payload['fromPortKind']
    to_kind = payload['toPortKind']
    from_index = payload['fromPortIndex']
    to_index = payload['toPortIndex']
    if from_node == to_node:
        raise ValueError('AUTHOR_SELF_LINK_REFUSED')
    if from_kind not in EDGE_SOURCE_KINDS:
        raise ValueError('AUTHOR_EDGE_SOURCE_NOT_OUTPUT')
    if to_kind not in EDGE_TARGET_KINDS:
        raise ValueError('AUTHOR_EDGE_TARGET_NOT_INPUT')
    pairing = EDGE_PAIRING.get((from_kind, to_kind))
    if pairing is None:
        raise ValueError('AUTHOR_EDGE_DIRECTION_MISMATCH')
    if pairing == 'execution' and (from_index not in EDGE_FLOW_SOURCE_INDEXES
                                  or to_index != EDGE_FLOW_TARGET_INDEX):
        raise ValueError('AUTHOR_FLOW_PORT_UNSUPPORTED')
    return pairing
AUTHOR_VALUE_SLOTS = ('auto', 'int', 'uint', 'enum', 'float', 'bool', 'string', 'vector3')
AUTHOR_LIST_LIMIT = 64
AUTHOR_DICT_LIMIT = 64
AUTHOR_VALUE_BATCH_LIMIT = 32


def validate_value_batch(values):
    """Check the complete batch before a journal, lease, or bridge request exists.

    nodeId is a native receipt ID; definitionId and the declared pin signature are
    checked again against the live unbound graph by the adapter. Containers retain
    the existing append semantics. Never replay a failed batch to fill a gap.
    """
    if not isinstance(values, list) or not 1 <= len(values) <= AUTHOR_VALUE_BATCH_LIMIT:
        raise ValueError('AUTHOR_VALUES_COUNT_INVALID')
    seen = set()
    def integer(value, maximum=2**32-1, minimum=0):
        return type(value) is int and minimum <= value <= maximum
    def bounded(value):
        validate_scalar_payload(value)
        name, inner = next(iter(value.items()))
        if name == 'int' and not -2**31 <= inner < 2**31:
            raise ValueError('AUTHOR_VALUE_INT_INVALID')
        if name == 'float' and abs(inner) > 1e9:
            raise ValueError('AUTHOR_VALUE_FLOAT_INVALID')
        if name == 'string' and len(inner.encode('utf-16-le'))//2 > 1024:
            raise ValueError('AUTHOR_VALUE_STRING_INVALID')
        if name == 'list':
            for leaf in inner:
                bounded(leaf)
        if name == 'dict':
            for pair in inner:
                bounded(pair['key'])
                bounded(pair['value'])
    for item in values:
        if not isinstance(item, dict) or set(item) != {
                'nodeId', 'definitionId', 'portKind', 'portIndex', 'expect', 'value', 'slot'}:
            raise ValueError('AUTHOR_VALUES_ENTRY_INVALID')
        if not integer(item['nodeId'], minimum=1) or not integer(item['definitionId'], minimum=1):
            raise ValueError('AUTHOR_VALUES_ID_INVALID')
        if type(item['portKind']) is not int or item['portKind'] != 3:
            raise ValueError('AUTHOR_VALUE_PORT_KIND_UNSUPPORTED')
        if not integer(item['portIndex'], 2**31-1):
            raise ValueError('AUTHOR_VALUES_PORT_INDEX_INVALID')
        pin = (item['nodeId'], item['portIndex'])
        if pin in seen:
            raise ValueError('AUTHOR_VALUES_DUPLICATE_PIN')
        seen.add(pin)
        expect = item['expect']
        if not isinstance(expect, dict) or set(expect) != {'serverParamType', 'genericId'} or not all(
                integer(v, 2**31-1) for v in expect.values()):
            raise ValueError('AUTHOR_EXPECT_INVALID')
        if item['slot'] not in AUTHOR_VALUE_SLOTS:
            raise ValueError('AUTHOR_VALUE_SLOT_UNSUPPORTED')
        bounded(item['value'])
        # Literal slot/tag mismatches do not need native discovery to be refused.
        tag, inner = next(iter(item['value'].items()))
        if tag == 'vector3' or item['slot'] == 'vector3':
            if tag != 'vector3' or item['slot'] not in ('auto', 'vector3'):
                raise ValueError('AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3')
            if expect['serverParamType'] not in (0, 12):
                raise ValueError('AUTHOR_VALUE_VECTOR3_DECLARATION_MISMATCH')
        leaves = inner if tag == 'list' else [leaf for pair in inner for leaf in pair.values()] if tag == 'dict' else [item['value']]
        if item['slot'] != 'auto' and any(next(iter(leaf)) != ('uint' if item['slot'] == 'enum' else item['slot']) for leaf in leaves):
            raise ValueError('AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH')


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('AUTHOR_VALUES_DUPLICATE_JSON_FIELD:' + key)
        result[key] = value
    return result


def _canonical_dict_leaf(leaf):
    """Canonical text of one dict key leaf, for duplicate detection only.

    Re-renders the PARSED value, never the raw token, so ``{"int":1}`` and ``{"int": 1}``
    compare equal -- a raw-text compare would let a duplicate key through. Mirrors the
    adapter's ``CanonicalDictLeaf``.
    """
    name, inner = next(iter(leaf.items()))
    if name == 'string':
        return 'string:' + inner
    if name == 'bool':
        return 'bool:' + ('true' if inner else 'false')
    if name == 'float':
        return 'float:' + repr(float(inner))
    return name + ':' + str(inner)


def validate_dict_payload(entries):
    """Mirror of the adapter's ``dict`` shape check (``AuthoringGraph.cs`` case "dict").

    The adapter is the authority; this refuses everything the adapter refuses, first.
    """
    if not isinstance(entries, list) or len(entries) > AUTHOR_DICT_LIMIT:
        raise ValueError('AUTHOR_VALUE_DICT_SHAPE_INVALID')
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'key', 'value'}:
            raise ValueError('AUTHOR_VALUE_DICT_ENTRY_INVALID')
        for leaf in ('key', 'value'):
            leaf_value = entry[leaf]
            if not isinstance(leaf_value, dict) or len(leaf_value) != 1:
                raise ValueError('AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED')
            if next(iter(leaf_value)) not in ('int', 'uint', 'bool', 'float', 'string'):
                raise ValueError('AUTHOR_VALUE_DICT_LEAF_UNSUPPORTED')
            validate_scalar_payload(leaf_value)
        canonical = _canonical_dict_leaf(entry['key'])
        if canonical in seen:
            raise ValueError('AUTHOR_VALUE_DICT_DUPLICATE_KEY')
        seen.add(canonical)


def validate_scalar_payload(value):
    """Refuse a malformed value by name before the journal, the lease and the dispatch.

    Deliberately mirrors -- and is deliberately NOT the authority for -- the adapter's own
    check. The shape is a single tagged key so a value can never be a bare JSON scalar that
    the adapter would have to guess the type of. Everything the adapter refuses, this refuses
    first; nothing this accepts is thereby *placeable*, it is only *requestable*.
    """
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError('AUTHOR_VALUE_SHAPE_INVALID')
    name, inner = next(iter(value.items()))
    if name == 'int' and isinstance(inner, int) and not isinstance(inner, bool):
        return
    if name == 'uint' and isinstance(inner, int) and not isinstance(inner, bool) and 0 <= inner < 2**32:
        return
    if name == 'bool' and isinstance(inner, bool):
        return
    if name == 'float' and isinstance(inner, (int, float)) and not isinstance(inner, bool) and math.isfinite(inner):
        return
    if name == 'string' and isinstance(inner, str) and len(inner) <= 1024:
        return
    if name == 'vector3':
        # Server type 12, editable storage 7. Never confuse either with a
        # type-7 server pin (that code is not a three-dimensional vector).
        if (not isinstance(inner, list) or len(inner) != 3 or any(
                type(axis) not in (int, float) or abs(axis) > 1e9 or not math.isfinite(axis)
                for axis in inner)):
            raise ValueError('AUTHOR_VALUE_VECTOR3_INVALID')
        return
    if name == 'list':
        if not isinstance(inner, list) or len(inner) > AUTHOR_LIST_LIMIT:
            raise ValueError('AUTHOR_VALUE_LIST_INVALID')
        for element in inner:
            if not isinstance(element, dict) or next(iter(element), None) not in ('int', 'uint', 'float', 'string'):
                raise ValueError('AUTHOR_VALUE_LIST_ELEMENT_UNSUPPORTED')
            if element is not value:
                validate_scalar_payload(element)
        return
    if name == 'dict':
        # A dict is a CONTAINER, written per entry, exactly like `list` is written per
        # element -- so it is a payload NAME, not a `--slot` (AUTHOR_VALUE_SLOTS is
        # unchanged, exactly as it carries no 'list').
        validate_dict_payload(inner)
        return
    raise ValueError('AUTHOR_VALUE_TYPE_UNSUPPORTED:' + str(name))

#: creature-create is added here so it cannot be the one mutating subcommand that skips the
#: NATIVE_WRITE_REVIEW_REQUIRED gate (author.py:133) -- a new verb must fail closed.
SCENE_WRITE_ACTIONS = frozenset({'create', 'save', 'create-batch', 'creature-create'})
#: Paths an explicit session/review/baseline choice contributes to the command.
PATH_FIELDS = ('session', 'review', 'baseline')

# These workflows own their multi-step journals and review every mutation against
# its own fresh baseline. Wrapping them in the single-request journal would cache
# a whole unfinished operation and could obscure the batch that needs reconciliation.
FOUNDATION_COMMANDS = {
    'scene-scale': {
        'script': 'tools/game-executor/scene_scale.py',
        'actions': ('prepare', 'run', 'status', 'verify-save'),
        'liveActions': ('run',),
        'queueActions': ('run',),
    },
    'entity-transform': {
        'script': 'tools/entity-transform/cli.py',
        'actions': ('inspect', 'prepare', 'set', 'dispatch', 'decode', 'verify-save', 'compile-check',
                    'physics-inspect', 'physics-decode', 'physics-compile-check'),
        'liveActions': ('dispatch',),
        'queueActions': ('dispatch',),
    },
    'terrain': {
        'script': 'tools/map-terrain/terrain_cli.py',
        'actions': ('inspect', 'plan', 'prepare', 'execute', 'decode', 'verify-save', 'compile-check',
                    'batch-create', 'batch-prepare', 'batch-accept', 'batch-status',
                    'batch-abandon', 'batch-verify-save'),
        'liveActions': ('execute',),
        'queueActions': ('execute',),
    },
    'playtest-control': {
        'script': 'tools/playtest-control/cli.py',
        'actions': ('prepare', 'dispatch', 'decode', 'compile-check'),
        'liveActions': ('dispatch',),
        'queueActions': ('dispatch',),
    },
}

sys.path.insert(0, str(ROOT / 'tools/compatibility'))
from version_guard import IncompatibleVersion, require_compatible  # noqa: E402


class NativeWriteReviewRequired(ValueError):
    """A native mutation was requested without its internal review record."""

    code = 'NATIVE_WRITE_REVIEW_REQUIRED'


def guard_component(command):
    """Scene reads/writes use the native-scene disk component; graph uses the editor."""
    return {'scene': 'native-scene', 'graph': 'editor'}.get(command.get('backend'), 'all')


def missing_review(command):
    """True when a native mutation carries no --review evidence record.

    Checked before the journal, before any UAC request and before any dispatch,
    and identically for programmatic callers and the CLI.
    """
    return (command.get('backend') == 'scene' and command.get('action') in SCENE_WRITE_ACTIONS
            and not command.get('review'))


def refusal(error, request_id=None, journal=None):
    """Structured refusal: a rejected build must never look like an uncertain one."""
    result = dict(ok=False, code=error.code, error=error.code, outcomeUncertain=False,
                  retryAttempted=False, persistenceVerified=False, officialPlaytestVerified=False)
    if request_id is not None:
        result.update(requestId=request_id, journal=journal)
    report = getattr(error, 'report', None)
    if report is not None:
        result['compatibility'] = report
    return result


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def encoded(value):
    # ensure_ascii=True so EVERY file this module hands to a PowerShell child
    # (bridge-request.json, claim.json, helper-request.json, result.json) is pure
    # ASCII. The elevated reader graph-elevated-once.ps1:17,20 reads them with
    # `Get-Content -Raw` and no -Encoding flag, whose Windows PowerShell 5.1
    # default is the system ANSI codepage (GBK on zh-CN): a literal multi-byte
    # character there mis-decodes and eats the following `"`, so ConvertFrom-Json
    # throws before any transport opens. \uXXXX escapes are identical JSON after
    # ConvertFrom-Json and survive any codepage assumption. (graph-transport.ps1:47
    # already reads with -Encoding UTF8; this keeps both paths correct.)
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)


def exclusive_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(encoded(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def sanitize(value):
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()
                if k.lower() not in ('nonce', 'token', 'scope', 'pipename')}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def lease(run_id, runs=RUNS):
    run_id = str(uuid.UUID(run_id))
    directory = runs / run_id
    settings = read_json(directory / 'bridge-settings.json')
    expiry = datetime.fromisoformat(settings['expiresUtc'].replace('Z', '+00:00'))
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc) or (directory / 'lease-closed.json').exists():
        raise ValueError('SCOPE_EXPIRED_OR_CLOSED; no bridge is loaded automatically')
    return directory


def process_json(command, *, environment=None, timeout=240):
    # No shell evaluation. Child diagnostics are deliberately not echoed: they can
    # contain privileged session material. Existing native evidence stays in its run.
    result = subprocess.run(command, env=environment, capture_output=True,
                            encoding='utf-8-sig', timeout=timeout)
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError('BACKEND_NO_JSON_RECEIPT; inspect backend evidence, do not retry') from None
    if not isinstance(reply, dict):
        raise RuntimeError('BACKEND_INVALID_RECEIPT')
    if result.returncode != 0 and reply.get('ok') is True:
        reply.update(ok=False, error='BACKEND_NONZERO_EXIT', outcomeUncertain=True)
    return sanitize(reply)


def scene_call(command):
    # Gated by the separate native-scene disk component, not by the legacy
    # fixed-offset baseline: a matched read-only 7.1 profile is disk evidence and
    # grants no write permission. Raises; execute() turns it into a refusal.
    require_compatible('native-scene')
    argv = [sys.executable, str(ROOT / 'tools/game-executor/scene_cli.py'), command['action']]
    # The level is always explicit; MILIASTRA_LEVEL is kept only for compatibility.
    argv += ['--level-id', str(command['levelId'])]
    if command.get('elevatedQueue'):
        argv += ['--elevated-queue', command['elevatedQueue']]
    if command.get('largeScene'):
        argv += ['--large-scene']
    for field in PATH_FIELDS:
        if command.get(field):
            argv += ['--' + field, str(command[field])]
    if command['action'] == 'create':
        argv += ['--template-id', str(command['templateId'])]
        for key in ('position', 'rotation', 'scale'):
            argv += ['--' + key] + [str(v) for v in command[key]]
    environment = os.environ.copy()
    environment['MILIASTRA_LEVEL'] = str(command['levelId'])
    return process_json(argv, environment=environment)


def foundation_call(args):
    """Forward to a fixed workflow; its persistent ledger is the sole authority.

    Local prepare/status/verification stay usable without a running editor. The
    workflow independently gates and journals live work, including a requested
    save. No guessed session, shell command or implicit retry is introduced here.
    """
    contract = FOUNDATION_COMMANDS[args.command]
    action = args.foundation_action
    tail = list(args.foundation_args)
    live = action in contract['liveActions'] or '--direct-elevated' in tail or any(
        value == '--elevated-queue' or value.startswith('--elevated-queue=') for value in tail)
    if live:
        require_compatible('native-scene')
    queue = getattr(args, 'elevated_queue', None)
    if queue is not None:
        if action not in contract['queueActions']:
            raise ValueError('AUTHOR_QUEUE_NOT_APPLICABLE_TO_LOCAL_WORKFLOW')
        if any(value == '--direct-elevated' or value == '--elevated-queue'
               or value.startswith('--elevated-queue=') for value in tail):
            raise ValueError('AUTHOR_WORKFLOW_TRANSPORT_SPECIFIED_TWICE')
        tail += ['--elevated-queue', str(normalized_queue(queue))]
    argv = [sys.executable, str(ROOT / contract['script']), action, *tail]
    # The workflow's explicit time/batch budgets control its lifetime. An outer
    # 240-second kill would discard the response while a native batch is pending.
    try:
        return process_json(argv, timeout=None)
    except (RuntimeError, OSError):
        return dict(ok=False, error='AUTHOR_WORKFLOW_RECEIPT_UNAVAILABLE',
                    outcomeUncertain=live, retryAttempted=False,
                    reconciliation='Inspect the selected workflow operation ledger before any further dispatch')


def graph_call(command, request_id, directory):
    require_compatible('editor')  # before any lease, subprocess or bridge request
    host = powershell_host()  # explicit selection and effective policy before dispatch
    run_dir = lease(command['runId'])
    # This newly added capability must be present in the assembly actually
    # executing in this run; a successful compile on disk is insufficient.
    def has_vector(value):
        if isinstance(value, dict):
            return 'vector3' in value or value.get('slot') == 'vector3' or any(has_vector(v) for v in value.values())
        return isinstance(value, list) and any(has_vector(v) for v in value)
    if has_vector(command.get('payload')):
        spec = importlib.util.spec_from_file_location('graph_vector_release', ROOT / 'tools/graph-vector-values/release.py')
        vector_release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vector_release)
        vector_release.verify_run(run_dir)
    payload = dict(command['payload'], op=command.get('op', 'author-graph'), id=request_id)
    request_file = directory / 'bridge-request.json'
    exclusive_json(request_file, payload)  # nonce never leaves the settings file
    if command.get('elevatedQueue'):
        return elevated_graph_call(command, request_id, directory)
    shell = Path(host['path'])
    environment = os.environ.copy()
    environment['PSModulePath'] = str(shell.parent / 'Modules')
    return process_json([str(shell), '-NoProfile', '-File', str(Path(__file__).with_name('graph-launch.ps1')),
                         '-RunId', command['runId'], '-RequestId', request_id], environment=environment, timeout=150)


def elevated_graph_call(command, request_id, directory):
    """One queue request per existing journal claim; a timeout never resends it."""
    queue = normalized_queue(command['elevatedQueue'])
    spec = importlib.util.spec_from_file_location('author_elevated_transport', ROOT / 'tools/editor-bridge/elevated-request.py')
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    transport.QUEUE = queue
    queued_id = uuid.uuid4().hex
    payload = {'kind': 'author-graph', 'runId': command['runId'], 'requestId': request_id}
    exclusive_json(directory / 'helper-request.json', {'queueDir': str(queue), 'queueRequestId': queued_id,
                   'payload': payload, 'retryAttempted': False})
    try:
        reply = transport.send(payload, timeout=60.0, request_id=queued_id)
    except SystemExit as error:
        pending = str(error).startswith('timeout waiting')
        return {'ok': False, 'error': 'ELEVATED_GRAPH_PENDING' if pending else 'ELEVATED_GRAPH_REFUSED',
                'outcomeUncertain': True, 'pending': pending, 'retryAttempted': False,
                'queueRequestId': queued_id, 'queueDir': str(queue)}
    if not isinstance(reply, dict):
        return {'ok': False, 'error': 'ELEVATED_GRAPH_REPLY_INVALID', 'outcomeUncertain': True,
                'retryAttempted': False, 'queueRequestId': queued_id, 'queueDir': str(queue)}
    return dict(reply, queueRequestId=queued_id, queueDir=str(queue))


def normalized_queue(value):
    path = Path(value).absolute()
    allowed = (ROOT / '.runtime/editor-bridge').resolve()
    if not path.is_dir() or not path.resolve().is_relative_to(allowed) or path.resolve() == allowed:
        raise ValueError('ELEVATED_QUEUE_OUTSIDE_PROJECT_OR_MISSING')
    for component in [path, *path.parents]:
        info = component.lstat()
        if component.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('ELEVATED_QUEUE_REPARSE_POINT')
    return path.resolve()


def run_id_from_command(command):
    """The run a dispatch belongs to, read off the paths the command carries.

    A run is not a field of the command -- it is the directory the reviewed
    session and review records live in.  Nothing is guessed: the first 32-hex
    path component wins, or there is no run.
    """
    for field in PATH_FIELDS:
        value = command.get(field)
        if not isinstance(value, str):
            continue
        found = RUN_ID_IN_PATH.search(value)
        if found:
            return found.group(1)
    return None


def emit_run_receipt(command, request_id, result):
    """Leave a run-scoped receipt outside the run.  Best effort, never a second authority.

    Called only after the journal's own ``result.json`` has been written, so the
    receipt is a *derivative* of the journal and the journal's digest never
    depends on it.  A refusal is reported here, never raised: a missing receipt
    must not turn a completed dispatch into a failed one.
    """
    if result.get('ok') is not True or not DISPATCH_RECEIPT.is_file():
        return None
    run_id = run_id_from_command(command)
    if run_id is None:
        return {'emitted': False, 'code': 'NO_RUN_ID_IN_COMMAND'}
    try:
        # The load belongs INSIDE the guard: a producer that cannot even be
        # imported is still "a missing receipt", and a missing receipt must
        # never turn a completed dispatch into a failed one.
        spec = importlib.util.spec_from_file_location('_dispatch_receipt', DISPATCH_RECEIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        producer = module.ReceiptProducer(PRODUCER_ROOTS, run_id=run_id)
        entry = producer.write(producer.build(request_id))
    except Exception as error:                       # noqa: BLE001 - reported verbatim
        return {'emitted': False, 'code': getattr(error, 'code', type(error).__name__)}
    return {'emitted': True, 'receipt': entry['receipt'],
            'nativeSideRecord': entry['nativeSideRecord']}


def execute(command, request_id, *, journal=None, transport=None):
    """Persist a claim before any dispatch. All repeats use the same receipt or refuse."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', request_id):
        raise ValueError('request-id must be 1..80 safe letters, digits, underscore or hyphen')
    if missing_review(command):
        # Deterministic and independent of disk state, and before the journal
        # directory, the claim, any UAC request and any dispatch: a mutation
        # without its review record must leave nothing to reconcile.
        return sanitize(refusal(NativeWriteReviewRequired(), request_id))
    try:
        # Before the journal directory, the claim, any UAC request and any
        # subprocess: a rejected build must leave no trace to reconcile later.
        require_compatible(guard_component(command))
    except IncompatibleVersion as error:
        return sanitize(refusal(error, request_id))
    journal = Path(JOURNAL if journal is None else journal)
    journal.mkdir(parents=True, exist_ok=True)
    directory = journal / request_id
    fingerprint = hashlib.sha256(encoded(command).encode('utf-8')).hexdigest()
    try:
        directory.mkdir()
    except FileExistsError:
        claim = directory / 'claim.json'
        if not claim.exists():
            raise ValueError('REQUEST_INCOMPLETE_CLAIM; no retry')
        if read_json(claim)['sha256'] != fingerprint:
            raise ValueError('REQUEST_ID_CONFLICT')
        receipt = directory / 'result.json'
        if not receipt.exists():
            raise ValueError('REQUEST_OUTCOME_UNKNOWN; inspect evidence; no retry')
        return dict(read_json(receipt), replayed=True)
    exclusive_json(directory / 'claim.json', dict(sha256=fingerprint, command=command,
                   startedUtc=datetime.now(timezone.utc).isoformat()))
    try:
        if transport:
            backend = transport(command)
        elif command['backend'] == 'scene':
            backend = scene_call(command)
        else:
            backend = graph_call(command, request_id, directory)
        result = dict(ok=backend.get('ok') is True, requestId=request_id, backend=backend,
                      retryAttempted=False, replayed=False, journal=str(directory),
                      persistenceVerified=False, officialPlaytestVerified=False)
        if backend.get('ok') is not True:
            result['outcomeUncertain'] = command.get('mutating', False) and backend.get('outcomeUncertain', True)
    except IncompatibleVersion as error:
        result = refusal(error, request_id, str(directory))
    except Exception as error:
        # No exception text: backend diagnostics may expose scope material.
        result = dict(ok=False, requestId=request_id, error=type(error).__name__,
                      outcomeUncertain=command.get('mutating', False), retryAttempted=False,
                      journal=str(directory), persistenceVerified=False, officialPlaytestVerified=False)
    exclusive_json(directory / 'result.json', sanitize(result))
    receipt = emit_run_receipt(command, request_id, result)
    if receipt is not None:
        result['dispatchReceipt'] = receipt
    return sanitize(result)


def uint(value):
    result = int(value)
    if not 0 < result < 2**32:
        raise argparse.ArgumentTypeError('Expected a positive uint32')
    return result


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise argparse.ArgumentTypeError('Expected a finite number')
    return result


def node_uint(value):
    result = int(value)
    if not 0 <= result < 2**32:
        raise argparse.ArgumentTypeError('Expected uint32 node ID')
    return result


def definition_id(value):
    """Any positive uint32. Which ids are *placeable* is decided by the live editor
    node-definition registry (kind 6, exact server category {10001,20000,22000,0},
    exactly one model) inside the adapter -- not by a client-side list. The old
    ``choices=[1, 2, 71]`` was a third, narrower copy of a rule the write authority
    already owns, and it refused 70/373/586 before any bridge request was built.
    Loosening this changes what may be *requested*, never what may be *written*.
    """
    result = int(value)
    if not 0 < result < 2**32:
        raise argparse.ArgumentTypeError('Expected a positive uint32 definition id')
    return result


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--elevated-queue', type=Path, help='Explicit live project helper; no UAC fallback or automatic retry')
    subs = ap.add_subparsers(dest='command', required=True)
    subs.add_parser('capabilities')
    status = subs.add_parser('status', help='Local only; does not contact or load the bridge')
    status.add_argument('--run-id')
    status.add_argument('--request-id')
    for name, contract in FOUNDATION_COMMANDS.items():
        workflow = subs.add_parser(name, help='Full workflow with its own operation ledger; inspect its dedicated CLI for options')
        workflow.add_argument('foundation_action', choices=contract['actions'])
        workflow.add_argument('foundation_args', nargs=argparse.REMAINDER,
                              help='Arguments passed unchanged to the selected workflow action')
    for name in ('entity-create', 'entity-inspect', 'save'):
        child = subs.add_parser(name)
        child.add_argument('--request-id', required=True)
        child.add_argument('--level-id', type=uint, required=True,
                           help='Explicit level for scene_cli; always passed through')
        child.add_argument('--session', type=Path,
                           help='Explicit freshly discovered native session path; omit to let scene_cli '
                                'revalidate the project-local current-native-session pointer')
        if name == 'entity-inspect':
            child.add_argument('--large-scene', action='store_true',
                               help='Use the complete v2 snapshot for scenes beyond the legacy 512-entry capacity')
        if name != 'entity-inspect':
            child.add_argument('--review', type=Path,
                               help='Required for entity-create and save: internal coordinator evidence record '
                                    'binding the request hash and a complete runtime baseline. This is an '
                                    'internal evidence record, not a user permission; a missing one is refused '
                                    'as NATIVE_WRITE_REVIEW_REQUIRED before any journal or dispatch.')
            child.add_argument('--baseline', type=Path,
                               help='Optional consistency check against the reviewed, independently decoded baseline')
        if name == 'entity-create':
            child.add_argument('--template-id', type=int, required=True)
            child.add_argument('--position', type=finite, nargs=3, required=True)
            child.add_argument('--rotation', type=finite, nargs=3, default=[0, 0, 0])
            child.add_argument('--scale', type=finite, nargs=3, default=[1, 1, 1])
    graph = subs.add_parser('graph').add_subparsers(dest='graph_action', required=True)
    catalog = graph.add_parser('catalog', help='Read graph IDs after asynchronous create')
    catalog.add_argument('--request-id', required=True)
    catalog.add_argument('--run-id', required=True)
    for name in GRAPH_ACTIONS:
        child = graph.add_parser(name)
        child.add_argument('--request-id', required=True)
        child.add_argument('--run-id', required=True)
        child.add_argument('--name', required=True)
        if name == 'create':
            child.add_argument('--graph-kind', type=int, default=DEFAULT_GRAPH_KIND, choices=list(GRAPH_KINDS))
        if name not in ('create', 'lookup'):
            child.add_argument('--graph-id', type=uint, required=True)
        if name == 'add':
            child.add_argument('--expected-node-count', type=int, required=True)
            child.add_argument('--definition-id', type=definition_id, required=True)
            child.add_argument('--x', type=finite, default=0)
            child.add_argument('--y', type=finite, default=0)
        if name in ('wire', 'unwire'):
            child.add_argument('--from-node-id', type=node_uint, required=True)
            child.add_argument('--to-node-id', type=node_uint, required=True)
        if name in ('wire', 'unwire'):
            child.add_argument('--from-port-kind', type=node_uint, default=2,
                               help='Source pin kind: 2 output execution (default), 4 output data')
            child.add_argument('--to-port-kind', type=node_uint, default=1,
                               help='Target pin kind: 1 input execution (default), 3 input data')
            child.add_argument('--from-port-index', type=node_uint, default=0,
                               help='Source pin index; an execution output is 0 or 1')
            child.add_argument('--to-port-index', type=node_uint, default=0,
                               help='Target pin index; an execution input is 0')
        if name == 'count':
            child.add_argument('--limit', type=uint, required=True)
            child.add_argument('--period', type=finite, required=True)
        if name == 'condition':
            child.add_argument('--node-id', type=node_uint, required=True)
            child.add_argument('--value', choices=['true', 'false'], required=True)
        if name == 'build-print':
            child.add_argument('--expected-node-count', type=int, choices=[0], required=True)
            child.add_argument('--text', required=True)
        if name == 'build-plan':
            # One dispatch builds the whole graph. The plan is a path to a JSON object
            # {nodes:[{definitionId,x,y}], edges:[{from,to,fromKind,fromIndex,toKind,toIndex}],
            #  values:[{node,portIndex,slot,value}]} where node references are indices into
            #  `nodes`. It is read from a file rather than the command line so the request
            #  fingerprint binds the plan's BYTES, not a shell-quoted approximation of them.
            child.add_argument('--expected-node-count', type=int, choices=[0], required=True)
            child.add_argument('--plan-file', required=True)
        if name == 'set':
            child.add_argument('--node-id', type=node_uint, required=True)
            child.add_argument('--text', required=True)
        if name == 'value':
            child.add_argument('--node-id', type=node_uint, required=True)
            child.add_argument('--definition-id', type=node_uint,
                               help='Optional exact live node definition identity guard')
            # The declared signature the caller believes the pin carries, in the adapter's
            # numbering (serverParamType / genericId). Never valueTypeValueRaw.
            child.add_argument('--expect-server-param-type', type=node_uint, required=True)
            child.add_argument('--expect-generic-id', type=node_uint, required=True)
            # One tagged scalar: {"int":N} {"uint":N} {"float":F} {"bool":B} {"string":S}
            # {"list":[scalars...]}. Parsed and shape-checked locally so a malformed value
            # is refused before the journal, the lease and the dispatch.
            child.add_argument('--value-json', required=True)
            # "auto" (default) or one of the slots with an in-repo proof. Naming a slot is
            # how a caller reaches a storage kind that "auto" refuses by name.
            child.add_argument('--slot', choices=AUTHOR_VALUE_SLOTS, default='auto')
            # D2: the target pin index is REQUIRED and has no default. A value write has no
            # historical pin to preserve (unlike wire/unwire, whose omitted index keeps the
            # pre-existing execution pin 0), and the two pins this wave must write --
            # 586.3:1 and 70.3:1 -- are both index 1. An implicit 0 would silently aim the
            # write at a different pin, so the caller states it or there is no request.
            child.add_argument('--port-index', type=node_uint, required=True,
                               help='Target pin index, exact. 0 is a legal value; it is simply '
                                    'never assumed.')
        if name == 'values':
            child.add_argument('--expected-node-count', type=int, required=True)
            child.add_argument('--values-file', required=True,
                               help='Project-local JSON array of 1..32 values with native nodeId, '
                                    'definitionId, portKind=3, portIndex, expect, slot, value.')
        if name == 'slots':
            child.add_argument('--node-id', type=node_uint, required=True)
        if name == 'bind':
            child.add_argument('--expected-node-count', type=int, required=True)
            child.add_argument('--entity-id', type=uint, required=True)
    return ap


def _command_from_args(args):
    if args.command != 'graph':
        action = {'entity-create': 'create', 'entity-inspect': 'inspect', 'save': 'save'}[args.command]
        command = dict(backend='scene', action=action, levelId=args.level_id, mutating=action != 'inspect')
        # Supplied paths are part of the command, so the journal fingerprint binds
        # them: replaying the same request id with a different session, review or
        # baseline is a conflict, not a replay.
        for field in PATH_FIELDS:
            value = getattr(args, field, None)
            if value:
                command[field] = str(value)
        if action == 'inspect' and args.large_scene:
            command['largeScene'] = True
        if action == 'create':
            if any(v <= 0 for v in args.scale):
                raise ValueError('Scale must be positive')
            command.update(templateId=args.template_id, position=args.position,
                           rotation=args.rotation, scale=args.scale)
        return command
    if args.graph_action == 'catalog':
        return dict(backend='graph', runId=str(uuid.UUID(args.run_id)), op='catalog', payload={}, mutating=False)
    if not re.fullmatch(r'MW_API_[A-Za-z0-9_]{1,48}', args.name):
        raise ValueError('Graph name must match MW_API_[A-Za-z0-9_]{1,48}')
    payload = dict(action=GRAPH_ACTIONS[args.graph_action], name=args.name)
    fields = {'graph_id': 'graphId', 'graph_kind': 'graphKind', 'definition_id': 'definitionId', 'x': 'x', 'y': 'y',
              'from_node_id': 'fromNodeId', 'to_node_id': 'toNodeId', 'node_id': 'nodeId',
              'text': 'text', 'limit': 'limit', 'period': 'period', 'from_port_index': 'fromPortIndex',
              'from_port_kind': 'fromPortKind', 'to_port_kind': 'toPortKind', 'to_port_index': 'toPortIndex',
              'expected_node_count': 'expectedNodeCount', 'entity_id': 'entityId'}
    for attr, key in fields.items():
        if hasattr(args, attr) and getattr(args, attr) is not None:
            payload[key] = getattr(args, attr)
    # A value write carries structured fields and never a path-shaped one. They are added
    # after the flat mapping above so the generic loop cannot flatten them.
    if args.graph_action == 'value':
        payload['portKind'] = 3      # data input; the adapter re-checks it
        payload['portIndex'] = args.port_index
        payload['expect'] = {'serverParamType': args.expect_server_param_type,
                             'genericId': args.expect_generic_id}
        payload['value'] = json.loads(args.value_json, object_pairs_hook=_unique_json_object)
        payload['slot'] = args.slot
        validate_scalar_payload(payload['value'])
        if args.slot == 'vector3' or 'vector3' in payload['value']:
            if args.slot not in ('auto', 'vector3') or 'vector3' not in payload['value']:
                raise ValueError('AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3')
            if args.expect_server_param_type not in (0, 12):
                raise ValueError('AUTHOR_VALUE_VECTOR3_DECLARATION_MISMATCH')
    if args.graph_action == 'values':
        source = Path(args.values_file).resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError('AUTHOR_VALUES_FILE_OUTSIDE_PROJECT')
        try:
            payload['values'] = json.loads(source.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_json_object)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'AUTHOR_VALUES_FILE_UNREADABLE:{type(error).__name__}') from error
        validate_value_batch(payload['values'])
        if not args.request_id or len(args.request_id) > 128:
            raise ValueError('AUTHOR_VALUES_REQUEST_ID_INVALID')
        # Reserve a conservative nonce envelope within the bridge's 16 KiB cap.
        # Batch count alone cannot bound 32 large string/container payloads.
        envelope = dict(payload, op='author-graph', id=args.request_id, nonce='0'*128)
        if len(encoded(envelope).encode('utf-8')) > 16384:
            raise ValueError('AUTHOR_VALUES_REQUEST_TOO_LARGE')
    if args.graph_action == 'build-plan':
        # The plan travels as a nested object. Read from a file and re-serialise through
        # the same encoder the fingerprint uses, so what is journalled is exactly what is
        # dispatched -- a plan that changed on disk between two runs is a NEW request, and
        # the request id (a function of this command) makes that a conflict, not a replay.
        try:
            plan = json.loads(Path(args.plan_file).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f'build-plan: plan file unreadable: {type(error).__name__}')
        if not isinstance(plan, dict) or not isinstance(plan.get('nodes'), list) or not plan['nodes']:
            raise ValueError('build-plan: plan needs a non-empty nodes array')
        for item in plan.get('values', []):
            if isinstance(item, dict) and (item.get('slot') == 'vector3' or
                    isinstance(item.get('value'), dict) and 'vector3' in item['value']):
                validate_scalar_payload(item.get('value'))
                if item.get('slot') not in ('auto', 'vector3') or 'vector3' not in item['value']:
                    raise ValueError('AUTHOR_VALUE_SLOT_PAYLOAD_MISMATCH:vector3')
        payload['plan'] = plan
    # D3: `slots` deliberately adds NOTHING beyond the flat mapping. The adapter's field set
    # for `pin-slots` is the closed {graphId, nodeId} (AuthoringGraph.cs:26-41 -- the per-action
    # table at :26-36, the `allowed` set built from it at :38, the refusal at :40-41), and
    # pin-slots is read-only -- it enumerates every declared pin itself, so a caller-supplied
    # portKind would be a field the whitelist refuses AND a value nothing reads. Not sending it
    # keeps the instrument alive without widening a closed set.
    if args.graph_action in ('wire', 'unwire'):
        # Direction and bounds are refused here, before the journal and the lease.
        validate_edge(payload)
    if args.graph_action == 'build-print':
        match = re.fullmatch(r'MW_API_SOL_L10_([a-z0-9]{6,16})_print', args.name)
        if not match or args.text != 'SOL_L10_' + match.group(1) + '_PRINT_ONCE':
            raise ValueError('Fixed print name/text contract mismatch')
    if args.graph_action == 'count' and (args.limit > 1000000 or not 0.1 <= args.period <= 3600):
        raise ValueError('Count gate requires limit 1..1000000 and period 0.1..3600 seconds')
    if args.graph_action == 'condition':
        payload['value'] = args.value == 'true'
    if len(payload.get('text', '')) > 1024:
        raise ValueError('Print text exceeds 1024 characters')
    if any(abs(payload.get(k, 0)) > 10000 for k in ('x', 'y')):
        raise ValueError('Node layout coordinates exceed 10000')
    if 'expectedNodeCount' in payload:
        # build-print and build-plan both REQUIRE an empty graph, so their count is
        # exactly 0; add runs 0..127; everything else is a non-empty graph.
        low, high = (0, 0) if args.graph_action in ('build-print', 'build-plan') else (0, 127) if args.graph_action == 'add' else (1, 128)
        if not low <= payload['expectedNodeCount'] <= high:
            raise ValueError(f'Expected node count must be {low}..{high}')
    return dict(backend='graph', runId=str(uuid.UUID(args.run_id)), payload=payload,
                # `slots` is read-only and must not consume a mutation attempt; `value`
                # mutates and must not be treated as a read, or an uncertain outcome
                # would be reported as a known one.
                mutating=args.graph_action not in ('inspect', 'lookup', 'slots'))


def command_from_args(args):
    command = _command_from_args(args)
    if getattr(args, 'elevated_queue', None) is not None:
        command['elevatedQueue'] = str(normalized_queue(args.elevated_queue))
    return command


def capabilities():
    return dict(ok=True, elevatedSession='explicit global --elevated-queue; one request, no UAC fallback, pending evidence preserved',
                sceneBackend='tools/game-executor/scene_cli.py',
                mapFoundationWorkflows={name: {'entrypoint': value['script'], 'actions': list(value['actions']),
                    'journal': 'owned by the workflow; uncertain dispatch is never automatically repeated',
                    'liveAcceptance': 'separate evidence required'} for name, value in FOUNDATION_COMMANDS.items()},
                largeSceneInspection='entity-inspect --large-scene selects a complete v2 snapshot; it does not raise game limits',
                templateIds=None,  # 2026-10-09: whitelist removed; any uint32 is accepted
                sceneSession='explicit --session path, or omitted so scene_cli revalidates the project-local '
                             'current-native-session pointer; a stale or replaced session fails closed',
                sceneLevel='explicit --level-id (uint32) is always passed to scene_cli; MILIASTRA_LEVEL is '
                           'retained for compatibility only and is not the authority',
                sceneReview='--review is required for entity-create and save: an internal coordinator evidence '
                            'record (not a user permission). The native agent independently re-validates the '
                            'request hash plus a complete snapshot, that review and a fresh session before any '
                            'build or UAC; a missing review is refused as NATIVE_WRITE_REVIEW_REQUIRED before any '
                            'journal or dispatch.',
                sceneBaseline='--baseline is optional for writes and only adds a consistency check',
                graphBackend='existing explicit leased bridge; author-graph adapter must already be loaded',
                # Not a whitelist any more, and deliberately not a claim: membership still means
                # "permitted to be requested", never "proven to place, save and reload". Each id
                # needs its own live case, so this field states the rule instead of a list.
                graphDefinitions='resolved by the live editor node-definition registry (kind 6, '
                                 'category derived from the actual graphKind, exactly one model); the client no longer '
                                 'narrows the set. Placeability is not placement: every definition needs '
                                 'its own live case before any behaviour is claimed.',
                graphBinding='explicit entity ID; native model identity checked', graphActions=list(GRAPH_ACTIONS) + ['catalog'],
                graphKinds=list(GRAPH_KINDS), graphKindAcceptance='20000 has farming-demo playtest evidence; '
                            'requestable client kinds are not declared runtime-verified',
                graphLimits={'nodes': 128, 'valueBatch': AUTHOR_VALUE_BATCH_LIMIT,
                             'containerEntries': AUTHOR_LIST_LIMIT, 'requestBytes': 16384},
                boundGraphEditing=False, generalDynamicPortResize=False,
                graphEdgePorts='wire/unwire take explicit --from-port-kind/--to-port-kind and --from-port-index/'
                               '--to-port-index (source 2 execution or 4 data, target 1 execution or 3 data). Direction '
                               'and bounds are refused locally by name; the declared port types are checked by the editor '
                               'adapter, which holds the live node-definition registry. Nothing about a port is guessed.',
                boundsValidation='unknown: finite coordinates are not proof of scene bounds',
                sceneBoundsEditable=False, officialPlaytestVerified=False,
                bridgeAutomaticallyLoaded=False, runtimeCapabilityProbed=False,
                nativeSceneDiskOnly='native-scene verifies the pinned read-only profile against the bytes on disk; '
                                    'it is not runtime acceptance and not write permission',
                liveWriteVerified=False, nativeWriteVerified=False,
                liveGate='tools/compatibility/version_guard.py; scene dispatch is gated by the native-scene disk '
                         'component (pinned read-only profile), graph dispatch by the legacy editor assembly '
                         'baseline. The installed 7.1 build is not adapted for the legacy fixed-offset game '
                         'writers, so game/all still refuse it. Local reads are unaffected.')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    args = parser().parse_args()
    try:
        if args.command == 'capabilities':
            result = capabilities()
        elif args.command in FOUNDATION_COMMANDS:
            result = foundation_call(args)
        elif args.command == 'status':
            result = capabilities()
            if args.run_id:
                lease(args.run_id)
                result['leaseLocallyValid'] = True
            if args.request_id:
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.request_id):
                    raise ValueError('Invalid request-id')
                path = JOURNAL / args.request_id
                result['request'] = read_json(path / 'result.json') if (path / 'result.json').exists() else {
                    'claimed': path.exists(), 'outcomeKnown': False}
        else:
            command = command_from_args(args)
            if missing_review(command):
                # Same deterministic refusal as execute(), reached before the
                # compatibility gate so it never depends on disk state.
                result = refusal(NativeWriteReviewRequired(), args.request_id)
            else:
                require_compatible(guard_component(command))
                if command['backend'] == 'graph':
                    lease(command['runId'])  # reject stale scopes before claiming a new operation
                result = execute(command, args.request_id)
    except IncompatibleVersion as error:
        result = refusal(error)
    except (ValueError, OSError, KeyError) as error:
        result = dict(ok=False, error=str(error) if isinstance(error, ValueError) else type(error).__name__,
                      retryAttempted=False)
    print(encoded(sanitize(result)))
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
