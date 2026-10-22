"""Real PS5 parser + temporary-file hashes; emitted wrappers never execute."""
from __future__ import annotations
import codecs
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import build_scene_profile as build
import build_readonly_profile as readonly
import scene_cli

PARSER = r"""param([string]$ScriptPath,[string]$FixtureRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'WINDOWS_POWERSHELL_5_REQUIRED' }
$fixture = [IO.Path]::GetFullPath($FixtureRoot).TrimEnd('\') + '\'
$inputPath = [IO.Path]::GetFullPath($ScriptPath)
if (-not $inputPath.StartsWith($fixture,[StringComparison]::OrdinalIgnoreCase)) { throw 'OUTSIDE_FIXTURE' }
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($inputPath,[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) { throw ($errors | Out-String) }
$literals = @($ast.FindAll({param($node) $node -is [Management.Automation.Language.StringConstantExpressionAst]},$true) | ForEach-Object {$_.Value})
$hashes = @()
foreach ($command in $ast.FindAll({param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Get-FileHash'},$true)) {
    $elements = $command.CommandElements
    if ($elements.Count -gt 2 -and $elements[1].Extent.Text -eq '-LiteralPath' -and
        $elements[2] -is [Management.Automation.Language.StringConstantExpressionAst]) {
        $path = $elements[2].Value
        $full = [IO.Path]::GetFullPath($path)
        if (-not $full.StartsWith($fixture,[StringComparison]::OrdinalIgnoreCase)) { throw 'HASH_OUTSIDE_FIXTURE' }
        $hashes += @{path=$path;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
}
# Do not invoke the AST, dot-source the wrapper, call Start-Process or any EXE.
@{version=$PSVersionTable.PSVersion.ToString();literals=$literals;hashes=$hashes;wrapperExecuted=$false} | ConvertTo-Json -Depth 5 -Compress
"""


class LaunchBlocked(RuntimeError): pass


class PowershellEncodingTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(os.name, 'nt', 'These tests require real Windows PowerShell 5')
        temp = tempfile.TemporaryDirectory(prefix='ps5-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "原神's路径"
        self.run = self.root / '运行'
        self.run.mkdir(parents=True)
        self.ps = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        self.assertTrue(self.ps.is_file())
        self.paths = {}
        for name in ['原神.exe', '审核.json', '关卡.gil', '恢复副本.gil']:
            path = self.root / name
            path.write_bytes(('synthetic-' + name).encode('utf-8'))
            self.paths[name] = path
        self.reviewed = dict(reviewPath=str(self.paths['审核.json']), reviewSha256=self.sha(self.paths['审核.json']),
                             targetGil=str(self.paths['关卡.gil']),
                             recovery=dict(backup=str(self.paths['恢复副本.gil']), sha256=self.sha(self.paths['关卡.gil'])))
        self.artifact = self.run / '中文工件.bin'
        self.artifact.write_bytes(b'synthetic-artifact')
        self.hashes = {self.artifact.name: self.sha(self.artifact)}

    @staticmethod
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def emit_fixed(self):
        with patch.object(build, 'TARGET_IMAGE', self.paths['原神.exe']), \
                patch.object(build, 'NATIVE_PROFILE', {'image': {'sha256': self.sha(self.paths['原神.exe'])}}):
            build.emit_wrapper(self.run, self.hashes, self.reviewed)
        return self.run / 'invoke-fixed-probe.ps1'

    def inspect(self, wrapper):
        self.assertTrue(wrapper.read_bytes().startswith(codecs.BOM_UTF8))
        parser = self.root / 'parse-only.ps1'
        parser.write_text(PARSER, encoding='utf-8-sig')
        env = os.environ.copy()
        env['PSModulePath'] = str(self.ps.parent / 'Modules')
        result = subprocess.run([str(self.ps), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(parser),
                                 '-ScriptPath', str(wrapper), '-FixtureRoot', str(self.root)],
                                capture_output=True, encoding='utf-8', errors='strict', env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertTrue(parsed['version'].startswith('5.1.'))
        self.assertFalse(parsed['wrapperExecuted'])
        self.assertFalse((self.run / 'launch.claim').exists())
        self.assertFalse((self.run / 'exit.json').exists())
        self.assertFalse((self.run / 'hook_receipt_probe.exe').exists())
        for item in parsed['hashes']:
            self.assertEqual(item['sha256'], self.sha(Path(item['path'])))
        return parsed

    def test_fixed_wrapper_ps5_preserves_every_chinese_path(self):
        parsed = self.inspect(self.emit_fixed())
        expected = {str(p) for p in self.paths.values()}
        self.assertEqual({h['path'] for h in parsed['hashes']}, expected)
        self.assertTrue(expected <= set(parsed['literals']))
        self.assertIn(self.artifact.name, parsed['literals'])

    def test_readonly_wrapper_ps5_preserves_chinese_image_path(self):
        image = self.paths['原神.exe']
        readonly.emit_wrapper(self.run, str(image), self.sha(image), self.hashes)
        parsed = self.inspect(self.run / 'invoke-readonly-probe.ps1')
        self.assertEqual([h['path'] for h in parsed['hashes']], [str(image)])
        self.assertIn(self.artifact.name, parsed['literals'])

    def test_launch_script_ps5_preserves_chinese_wrapper_path_without_launch(self):
        wrapper = self.emit_fixed()
        profile = dict(run=str(self.run), hashes={wrapper.name:self.sha(wrapper)}, deadlineTick=100,
                       wrapperName=wrapper.name)
        # Execute only the Python preparation prefix. The launch boundary raises,
        # before a process, UAC, probe, native call or game observation can occur.
        # ``powershell_host`` is pinned here because it probes the host with its own
        # ``subprocess.run`` (which would hit the Popen patch below); the patch surface
        # stays on the one launch site the test is about.
        host = {'path': str(self.ps), 'version': '5.1.0', 'edition': 'Desktop', 'policy': 'RemoteSigned'}
        with patch.object(scene_cli, 'windows_api', return_value=(SimpleNamespace(GetTickCount64=lambda:0), None)), \
                patch.object(scene_cli.profile_api, 'powershell_host', return_value=host), \
                patch.object(scene_cli.subprocess, 'Popen', side_effect=LaunchBlocked('blocked')) as launch:
            with self.assertRaises(LaunchBlocked): scene_cli.execute_profile(profile)
        launch.assert_called_once()
        parsed = self.inspect(self.run / 'launch-uac.ps1')
        self.assertEqual([h['path'] for h in parsed['hashes']], [str(wrapper)])
        self.assertIn(str(self.run / 'launch-result.json'), parsed['literals'])
        self.assertFalse((self.run / 'launch-result.json').exists())


if __name__ == '__main__': unittest.main()
