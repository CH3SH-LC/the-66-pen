"""Read-only DS port to the existing leased author.py graph lookup/inspect.

The operator-owned scope is never a tool parameter. No bridge loading, scope
minting, helper startup, queue selection, graph mutation, or retry occurs here.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import uuid

NAME = re.compile(r'MW_API_[A-Za-z0-9_]{1,48}\Z')
MAX_NODES = 128


def _fail(server, code):
    raise server.BusinessError(code, 'graph observation refused; no automatic load or retry')


def _ordinary(server, path, code, directory=False):
    """Reject every existing lexical component from fixed ROOT through target.

    resolve() must never redefine the boundary. lstat detects Windows junctions
    as well as symlinks; no target is opened before these checks.
    """
    try:
        root = server.ROOT.absolute()
        path = path.absolute()
        parts = path.relative_to(root).parts
        if any(part in ('.', '..') for part in parts):
            raise ValueError()
        current = root
        for index in range(len(parts) + 1):
            info = current.lstat()
            if getattr(info, 'st_file_attributes', 0) & 0x400 or stat.S_ISLNK(info.st_mode):
                raise ValueError()
            is_dir = index < len(parts) or directory
            matches_kind = stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode)
            if not matches_kind:
                raise ValueError()
            if index < len(parts):
                current = current / parts[index]
    except (OSError, ValueError):
        _fail(server, code)


def _json(server, path, code):
    try:
        _ordinary(server, path, code)
        if path.stat().st_size > 65536:
            _fail(server, code)
        raw = path.read_bytes()
        _ordinary(server, path, code)
        if len(raw) > 65536:
            _fail(server, code)
        body = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(body, dict):
            raise ValueError()
    except (OSError, ValueError, UnicodeError):
        _fail(server, code)
    return body, hashlib.sha256(raw).hexdigest()


def _expiry(server, text):
    try:
        expiry = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError()
        return expiry
    except (AttributeError, ValueError, TypeError):
        _fail(server, 'GRAPH_SCOPE_EXPIRED_OR_INVALID')


def load_scope(server, graph_name):
    if not isinstance(graph_name, str) or NAME.fullmatch(graph_name) is None:
        _fail(server, 'GRAPH_NAME_INVALID')
    path = server.ROOT / '.runtime/authoring/ds-graph-scope.json'
    scope, digest = _json(server, path, 'GRAPH_SCOPE_MISSING_OR_INVALID')
    if set(scope) != {'schemaVersion', 'runId', 'allowedGraphNames', 'expiresUtc'} or type(scope.get('schemaVersion')) is not int or scope['schemaVersion'] != 1:
        _fail(server, 'GRAPH_SCOPE_INVALID')
    try:
        run_id = str(uuid.UUID(scope['runId']))
        if run_id != scope['runId']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _fail(server, 'GRAPH_SCOPE_INVALID')
    names = scope['allowedGraphNames']
    if not isinstance(names, list) or not 1 <= len(names) <= 16 or any(not isinstance(n, str) or NAME.fullmatch(n) is None for n in names) or len(set(names)) != len(names):
        _fail(server, 'GRAPH_SCOPE_INVALID')
    if graph_name not in names:
        _fail(server, 'GRAPH_NOT_IN_OPERATOR_SCOPE')
    expiry = _expiry(server, scope['expiresUtc'])
    runs = server.ROOT / '.runtime/editor-bridge/runs'
    run_dir = runs / run_id
    _ordinary(server, run_dir, 'GRAPH_LEASE_CLOSED_OR_INVALID', directory=True)
    try:
        closed = (run_dir / 'lease-closed.json').lstat()
    except FileNotFoundError:
        pass
    except OSError:
        _fail(server, 'GRAPH_LEASE_CLOSED_OR_INVALID')
    else:
        _fail(server, 'GRAPH_LEASE_CLOSED_OR_INVALID')
    settings, settings_digest = _json(server, run_dir / 'bridge-settings.json', 'GRAPH_LEASE_MISSING_OR_INVALID')
    if expiry > _expiry(server, settings.get('expiresUtc')):
        _fail(server, 'GRAPH_SCOPE_EXCEEDS_LEASE')
    return {'runId': run_id, 'scopeSha256': digest, 'settingsSha256': settings_digest}


def _uint(value, nonzero=False):
    return type(value) is int and (1 if nonzero else 0) <= value < 2**32


def _read(server, scope, graph_name, action, graph_id=None):
    # Re-read all expiry, ownership and byte identities before EACH native request.
    if load_scope(server, graph_name) != scope:
        _fail(server, 'GRAPH_SCOPE_CHANGED')
    queue, _ = server.resolve_elevated_queue()
    request_id = 'mcpgraph' + uuid.uuid4().hex
    argv = [server.PYTHON, '-B', str(server.ROOT / 'tools/authoring/author.py'),
            '--elevated-queue', str(queue), 'graph', action,
            '--run-id', scope['runId'], '--name', graph_name, '--request-id', request_id]
    if graph_id is not None:
        argv += ['--graph-id', str(graph_id)]
    reply = server._run(argv)
    if not isinstance(reply, dict):
        _fail(server, 'GRAPH_AUTHOR_READ_FAILED')
    backend = reply.get('backend')
    if reply.get('ok') is not True or reply.get('requestId') != request_id or reply.get('retryAttempted') is not False or not isinstance(backend, dict) or backend.get('ok') is not True:
        _fail(server, 'GRAPH_AUTHOR_READ_FAILED')
    for receipt in (reply, backend):
        if any(key in receipt and receipt[key] is not False for key in ('pending', 'outcomeUncertain')):
            _fail(server, 'GRAPH_AUTHOR_READ_PENDING_OR_UNCERTAIN')
    if backend.get('name') != graph_name:
        _fail(server, 'GRAPH_READBACK_WRONG_NAME')
    if action == 'lookup' and backend.get('status') == 'lookup-pending':
        _fail(server, 'GRAPH_LOOKUP_PENDING')
    if backend.get('status') != 'editor-model-readback' or not _uint(backend.get('graphId'), True):
        _fail(server, 'GRAPH_READBACK_INVALID')
    if graph_id is not None and backend['graphId'] != graph_id:
        _fail(server, 'GRAPH_READBACK_WRONG_ID')
    return backend, request_id


def observe(server, graph_name):
    scope = load_scope(server, graph_name)
    found, lookup_request = _read(server, scope, graph_name, 'lookup')
    graph, inspect_request = _read(server, scope, graph_name, 'inspect', found['graphId'])
    nodes = graph.get('nodes'); count = graph.get('nodeCount'); bindings = graph.get('boundEntityIds')
    if type(count) is not int or not 0 <= count <= MAX_NODES or not isinstance(nodes, list) or len(nodes) != count or any(not isinstance(n, dict) or set(n) != {'nodeId', 'definitionId'} or not _uint(n['nodeId']) or not _uint(n['definitionId'], True) for n in nodes):
        _fail(server, 'GRAPH_NODE_READBACK_INVALID')
    if len({n['nodeId'] for n in nodes}) != count or not isinstance(bindings, list) or len(bindings) > 4096 or any(not _uint(i, True) for i in bindings) or len(set(bindings)) != len(bindings) or type(graph.get('boundToLevel')) is not bool:
        _fail(server, 'GRAPH_BINDING_READBACK_INVALID')
    return {'backendKind': 'project-editor-graph', 'graphName': graph_name, 'graphId': graph['graphId'],
            'nodeCount': count, 'nodes': nodes, 'boundEntityIds': bindings, 'boundToLevel': graph['boundToLevel'],
            'scopeSha256': scope['scopeSha256'], 'lookupRequestId': lookup_request, 'inspectRequestId': inspect_request,
            'editorReadback': server._stage('pass', detail='existing editor model fields only'),
            'liveReadback': server._stage('not-run', reason='no game runtime observation'),
            'persistence': server._stage('not-run'), 'reopen': server._stage('not-run'),
            'runtime': server._stage('not-run'), 'cleanup': server._stage('not-run'),
            'runtimeVerified': False, 'persistentSaveVerified': False, 'retryAttempted': False}
