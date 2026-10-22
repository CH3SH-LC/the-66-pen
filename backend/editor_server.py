"""Project-local MCP stdio entry point for fixed editor-bridge session launchers.

Two tools only: start one recorded request per requestId (fixed action enum,
fixed script) and read its lifecycle status. No shells or string commands, no
arbitrary paths or actions, no scope/nonce output, no automatic retries, no
process termination, no quota or global configuration edits. This is an
application capability boundary, not operating-system isolation.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Strict

from bridge import editor_sessions as sessions

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
mcp = FastMCP('miliastra-wonderland-editor', instructions=(
    'Fixed editor-bridge session tools for an already running editor: start requestId, targetPid and one '
    'action (' + ', '.join(sessions.ACTIONS) + '), then read status. Helper completion is not a game save, '
    'scene visibility or playtest acceptance. No arbitrary paths, actions, retries or termination.'))


def _error(method: str, exc: Exception) -> CallToolResult:
    error = exc.to_dict() if isinstance(exc, sessions.SessionError) else {
        'code': 'EDITOR_SESSION_ERROR', 'message': str(exc)}
    body = {'ok': False, 'method': method, 'backend': 'editor-bridge', 'error': error,
            'runtimeVerified': False}
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body, isError=True)


@mcp.tool(description='Record and launch one fixed editor-bridge session helper for an existing editor PID. '
                      'Idempotent per requestId: identical parameters never spawn twice, different ones are '
                      'rejected. Returns immediately without waiting for evidence.')
def mw_editor_start(requestId: Annotated[str, Strict()], targetPid: Annotated[int, Strict()],
                    action: Literal['observe', 'inspect-sync', 'backup-course', 'restore-route']) -> Any:
    try:
        return sessions.start(requestId, targetPid, action)
    except Exception as exc:
        return _error('mw.editor.start', exc)


@mcp.tool(description='Read-only lifecycle status for one recorded requestId, including sanitized launcher '
                      'runId. Runs only the fixed read-only status query; never repeats the editor action.')
def mw_editor_status(requestId: Annotated[str, Strict()]) -> Any:
    try:
        return sessions.status(requestId)
    except Exception as exc:
        return _error('mw.editor.status', exc)


def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
