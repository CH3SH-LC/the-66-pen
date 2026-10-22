"""File-only MCP stdio entry point. No IPC discovery, staging, or game controls."""
from __future__ import annotations

import json
import anyio
import logging
import sys
from typing import Any, Annotated
from pydantic import Strict

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from mvp import asset_api, resource_inventory, scene_recipe

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
mcp = FastMCP('miliastra-wonderland-files', instructions=(
    'Seven project-file tools only. Offline output does not prove game acceptance. '
    'No IPC, staging, game launch/import/save/playtest. This is an application capability boundary, '
    'not operating-system isolation.'))

TOOL_NAMES = ('mw_catalog_search', 'mw_scene_build', 'mw_asset_inspect',
              'mw_build_validate', 'mw_backend_capabilities', 'mw_resource_inventory', 'mw_scene_create')
_build_lock = anyio.Lock()


def _error(method: str, exc: Exception) -> CallToolResult:
    error = exc.to_dict() if isinstance(exc, asset_api.AssetApiError) else {
        'code': 'FILES_BACKEND_ERROR', 'message': str(exc)}
    body = {'ok': False, 'method': method, 'backend': 'file', 'error': error,
            'runtimeVerified': False}
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(body, ensure_ascii=False))],
                          structuredContent=body, isError=True)


def _asset(method: str, params: dict[str, Any]) -> Any:
    try:
        return asset_api.dispatch(method, {k: v for k, v in params.items() if v is not None})
    except Exception as exc:
        return _error(method, exc)


@mcp.tool(description='Read literal block catalog declarations, paged by derived category; '
                      'no upstream execution or game verification.')
def mw_catalog_search(query: str | None = None, templateId: int | None = None,
                      category: str | None = None, limit: int | None = None,
                      offset: int | None = None) -> dict[str, Any]:
    return _asset('mw.catalog.search', {'query': query, 'templateId': templateId,
                                        'category': category, 'limit': limit,
                                        'offset': offset})


@mcp.tool(description='Build fixed project scene assets in .runtime/mvp/builds only; not game import.')
async def mw_scene_build(scene: str | None = None, overwrite: bool | None = None) -> dict[str, Any]:
    async with _build_lock:
        # MCP uses AnyIO cancellation scopes. Keep the host task and build lock
        # alive until the worker finishes; never abandon staging on cancellation.
        return await anyio.to_thread.run_sync(
            _asset, 'mw.scene.build', {'scene': scene, 'overwrite': overwrite},
            abandon_on_cancel=False)


@mcp.tool(description='Read and decode an existing project build; explicit buildId required.')
def mw_asset_inspect(buildId: str) -> dict[str, Any]:
    return _asset('mw.asset.inspect', {'buildId': buildId})


@mcp.tool(description='Compare an existing build with its source scene; offline verification only.')
def mw_build_validate(buildId: str, scene: str | None = None) -> dict[str, Any]:
    return _asset('mw.build.validate', {'buildId': buildId, 'scene': scene})


@mcp.tool(description='Read fixed scene/finish files and hash reference catalog; no runtime evidence.')
def mw_resource_inventory() -> dict[str, Any]:
    try:
        return resource_inventory.build_inventory()
    except Exception as exc:
        return _error('mw.resource.inventory', exc)


@mcp.tool(description='Create a six-entity JSON candidate using nominal gap and vertical step; not a game import.')
def mw_scene_create(horizontal_gap: Annotated[float, Strict()],
                    vertical_step: Annotated[float, Strict()]) -> dict[str, Any]:
    try:
        return scene_recipe.create_candidate(horizontal_gap, vertical_step)
    except Exception as exc:
        return _error('mw.scene.create', exc)


@mcp.tool(description='Report exactly this file-only server capability boundary, not OS isolation.')
def mw_backend_capabilities() -> dict[str, Any]:
    parameters = {
        'mw_catalog_search': ['query', 'templateId', 'limit'],
        'mw_scene_build': ['scene', 'overwrite'], 'mw_asset_inspect': ['buildId'],
        'mw_build_validate': ['buildId', 'scene'], 'mw_backend_capabilities': [],
        'mw_resource_inventory': [],
        'mw_scene_create': ['horizontal_gap', 'vertical_step'],
    }
    return {'server': 'miliastra-wonderland-files', 'transport': 'stdio', 'backend': 'file',
            'tools': [{'name': name, 'params': parameters[name],
                       'effect': 'writes project build directory' if name == 'mw_scene_build' else
                                 'writes project candidate scene JSON' if name == 'mw_scene_create' else 'read-only'}
                      for name in TOOL_NAMES],
            'disabled': ['mw_ipc_discover', 'mw_asset_stage'],
            'unavailable': ['gameLaunch', 'gameImport', 'gameSave', 'gamePlaytest', 'runtimeObservation'],
            'runtimeVerified': False, 'gameAccepted': 'unknown', 'operatingSystemIsolation': False,
            'notes': ['No generic dispatch tool.', 'File operations are not game acceptance.',
                      'Scene build runs the fixed project generator, not arbitrary programs.']}


def main():
    mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
