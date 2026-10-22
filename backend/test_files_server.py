"""Independent SDK subprocess checks; never imports/runs legacy smoke or server."""
import asyncio
import anyio
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import threading
import tempfile
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
# The build key is content-addressed: sha256(scene.json sha + generate_mvp.py sha).  The
# pre-2026-09-15 key pointed at a build made before generate_mvp.py last changed, so
# mw_build_validate correctly reported valid=false (GENERATOR_CHANGED).  This is the key
# of the build produced by the current generator; its GIA artifact is byte-identical
# (790 B, sha256 01e167b8...) to the old one, so only the key moved.
BUILD = '53a79be516909d96ec2268c3635594fa2c1ca707ec1a8be7d9f746443d7031fd'
TOOLS = {'mw_catalog_search', 'mw_scene_build', 'mw_asset_inspect', 'mw_build_validate',
         'mw_backend_capabilities', 'mw_resource_inventory', 'mw_scene_create'}
FORBIDDEN = ['backend.server', 'bridge.ipc_discovery', 'mvp.stage_api']


def evidence(name, value):
    out = ROOT / '.runtime/backend' / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class FilesServerTests(unittest.TestCase):
    def test_create_strict_schema_and_temporary_output(self):
        from backend import files_server as server
        async def check():
            tools = await server.mcp.list_tools()
            schema = next(t.inputSchema for t in tools if t.name == 'mw_scene_create')
            self.assertEqual(schema['properties']['horizontal_gap']['type'], 'number')
            with tempfile.TemporaryDirectory() as tmp, patch.object(server.scene_recipe, 'ROOT', Path(tmp)):
                (Path(tmp)/'mvp').mkdir()
                (Path(tmp)/'mvp/scene.json').write_bytes((ROOT/'mvp/scene.json').read_bytes())
                result = await server.mcp.call_tool('mw_scene_create', {'horizontal_gap': 1.1, 'vertical_step': .37})
                self.assertEqual(len(list((Path(tmp)/'mvp/candidates').glob('recipe-*.json'))), 1)
                with self.assertRaises(Exception):
                    await server.mcp.call_tool('mw_scene_create', {'horizontal_gap': True, 'vertical_step': .37})
                error = server.mw_scene_create(.9, .37)
                self.assertTrue(error.isError)
        asyncio.run(check())

    def test_cancelled_build_holds_lock_until_worker_finishes(self):
        async def check():
            entered, release = threading.Event(), threading.Event()
            calls = []
            def blocked(method, params):
                calls.append(params['scene'])
                if len(calls) == 1:
                    entered.set()
                    release.wait(3)
                return {'reused': False}
            from backend import files_server as server
            finished = anyio.Event()
            first_scope = anyio.CancelScope()
            async def first():
                with first_scope:
                    await server.mw_scene_build('first')
                finished.set()
            with patch.object(server, '_asset', blocked), patch.object(server, '_build_lock', anyio.Lock()):
                async with anyio.create_task_group() as group:
                    group.start_soon(first)
                    await anyio.to_thread.run_sync(entered.wait)
                    first_scope.cancel()
                    group.start_soon(server.mw_scene_build, 'second')
                    await anyio.sleep(0.05)
                    self.assertEqual(calls, ['first'])
                    self.assertFalse(finished.is_set())
                    self.assertFalse(server.mw_backend_capabilities()['runtimeVerified'])
                    release.set()
                self.assertEqual(calls, ['first', 'second'])
        anyio.run(check)

    def test_build_does_not_block_event_loop(self):
        async def check():
            entered, release = threading.Event(), threading.Event()
            def blocked(method, params):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test event loop was blocked')
                return {'reused': False}
            from backend import files_server as server
            with patch.object(server, '_asset', blocked):
                task = asyncio.create_task(server.mw_scene_build())
                try:
                    await asyncio.wait_for(asyncio.to_thread(entered.wait), 1)
                    self.assertFalse(server.mw_backend_capabilities()['runtimeVerified'])
                    self.assertFalse(task.done())
                finally:
                    release.set()
                self.assertEqual(await task, {'reused': False})
        asyncio.run(check())

    def test_module_boundary_in_fresh_process(self):
        # Same import/call surface as the entry point, without the MCP event loop.
        code = ('import sys,json;from backend import files_server as s;'
                's.mw_catalog_search(limit=1);s.mw_resource_inventory();'
                'print(json.dumps([n for n in '+repr(FORBIDDEN)+' if n in sys.modules]))')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        evidence('files-modules.json', {'returncode': result.returncode,
                                      'stdout': result.stdout, 'stderr': result.stderr})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_sdk_stdio(self):
        asyncio.run(asyncio.wait_for(self.check_stdio(), timeout=60))

    async def check_stdio(self):
        params = StdioServerParameters(command=sys.executable, args=['-m', 'backend.files_server'],
            cwd=str(ROOT), env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
        report = {'entry': 'backend.files_server', 'calls': {}, 'runtimeVerified': False}
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    report['protocolVersion'] = init.protocolVersion
                    names = {t.name for t in (await session.list_tools()).tools}
                    report['tools'] = sorted(names)
                    self.assertEqual(names, TOOLS)
                    calls = [('mw_backend_capabilities', {}), ('mw_catalog_search', {'limit': 2}),
                             ('mw_resource_inventory', {}), ('mw_asset_inspect', {'buildId': BUILD}),
                             ('mw_build_validate', {'buildId': BUILD}),
                             ('mw_asset_inspect', {'buildId': 'invalid'}),
                             ('mw_ipc_discover', {}),
                             ('mw_asset_stage', {'buildId': BUILD, 'idempotencyKey': 'disabled-probe'})]
                    for index, (name, args) in enumerate(calls):
                        result = await session.call_tool(name, args)
                        report['calls'][str(index)] = {'name': name, **result.model_dump(mode='json')}
                        self.assertEqual(bool(result.isError), index >= 5, name)
                        if name == 'mw_resource_inventory':
                            self.assertEqual(result.structuredContent['counts'], {'templates': 5, 'instances': 6})
                            self.assertFalse(result.structuredContent['runtimeVerified'])
                        if name == 'mw_backend_capabilities':
                            self.assertEqual({t['name'] for t in result.structuredContent['tools']}, TOOLS)
                            self.assertFalse(result.structuredContent['operatingSystemIsolation'])
                        if name == 'mw_build_validate':
                            self.assertTrue(result.structuredContent['valid'])
                            self.assertTrue(all(c['ok'] for c in result.structuredContent['checks']))
                    report['passed'] = True
        finally:
            evidence('files-sdk.json', report)


if __name__ == '__main__':
    unittest.main()
