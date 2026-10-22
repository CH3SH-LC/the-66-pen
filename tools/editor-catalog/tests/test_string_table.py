"""Offline corruption, version-mixing and annotation regression checks."""
import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import string_table as st
spec = importlib.util.spec_from_file_location('annotation', TOOLS / 'annotate-strings.py')
an = importlib.util.module_from_spec(spec)
spec.loader.exec_module(an)
SHA = '565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a'
P = st.PROFILES[SHA]


class Strings(unittest.TestCase):
    def test_exact_walk_unicode_and_empty_entry(self):
        table = {0: '\u5b58\u6863', 8: '', 12: '\U0001f600'}
        self.assertEqual(st.parse_table(st.plaintext_from_table(table)), table)

    def test_corrupt_tables_do_not_return_prefix(self):
        for tail in [b'x', struct.pack('<i', -2), struct.pack('<i', 1) + b'x',
                     struct.pack('<i', 4) + b'x', struct.pack('<i', 2) + b'\x00\xd8']:
            with self.subTest(tail=tail), self.assertRaises(st.VerificationError):
                st.parse_table(b'\x00' * 4 + tail)

    def test_json_gaps_duplicates_wrong_values(self):
        for raw in [{'0': 1}, {'0': '', '00': ''}, {'-1': ''}, ['x']]:
            with self.subTest(raw=raw), self.assertRaises(st.VerificationError):
                st.parse_table_json(raw)
        with self.assertRaises(st.VerificationError):
            st.plaintext_from_table({4: 'x'})

    def test_decode_checks_resource_before_transform(self):
        with patch.object(st, 'transform', side_effect=AssertionError('must not run')):
            with self.assertRaises(st.VerificationError):
                st.decode_and_verify(b'wrong resource', P)

    def test_plaintext_count_and_anchor_are_enforced(self):
        raw = st.plaintext_from_table({0: 'ab'})
        profile = dataclasses.replace(P, resource_sha256=None, plaintext_sha256=None,
                                      entry_count=1, anchors=((0, 'ab'),))
        resource = st.transform(raw, profile.key_bytes())
        self.assertEqual(st.decode_and_verify(resource, profile).table, {0: 'ab'})
        for bad in [dataclasses.replace(profile, entry_count=2),
                    dataclasses.replace(profile, plaintext_sha256='0' * 64),
                    dataclasses.replace(profile, anchors=((0, 'wrong'),))]:
            with self.subTest(profile=bad), self.assertRaises(st.VerificationError):
                st.decode_and_verify(resource, bad)

    def test_only_known_accessor_calls_are_annotated(self):
        direct = f'{P.direct_type}.{P.direct_method}(1 ^ 1)'
        proxy = f'{P.proxy_type}.{P.proxy_method}(0, {P.proxy_type}.{P.proxy_slot_field})'
        qualified = f'global::{P.direct_namespace}.{P.direct_type}.{P.direct_method}(0)'
        text = f'var a = {direct}; var b = {proxy}; var c = {qualified}; var n = 1 ^ 1;'
        output, counts = an.annotate_text(text, {0: '\u5b58\u6863'}, P)
        self.assertEqual(counts, {'replaced': 3, 'unresolved': 0})
        self.assertIn('var n = 1 ^ 1;', output)
        self.assertEqual(output.count('/* string 0 */'), 3)

    def test_comments_strings_char_and_other_slot_untouched(self):
        call = f'{P.direct_type}.{P.direct_method}(0)'
        text = f'// {call}\n/* {call} */ var s = "{call}"; var c = \'"\';'
        text += f'{P.proxy_type}.{P.proxy_method}(0, Something.Other);'
        output, counts = an.annotate_text(text, {0: 'ab'}, P)
        self.assertEqual(output, text)
        self.assertEqual(counts, {'replaced': 0, 'unresolved': 1})

    def test_wrong_namespace_and_prefix_not_rewritten(self):
        call = f'{P.direct_type}.{P.direct_method}(0)'
        text = f'Other.{call}; Prefix{call};'
        self.assertEqual(an.annotate_text(text, {0: 'ab'}, P)[0], text)

    def test_unsupported_expression_preserved(self):
        call = f'{P.direct_type}.{P.direct_method}(unknown + 2)'
        self.assertEqual(an.annotate_text(call, {0: 'ab'}, P),
                         (call, {'replaced': 0, 'unresolved': 1}))
        self.assertEqual(an.resolve_offset('((0008 ^ 8))'), 0)
        for expression in ['9999999999', '-2147483649', '1 ^ 2 ^ 3', '1 + 2']:
            self.assertIsNone(an.resolve_offset(expression))

    def test_table_rewrite_and_sidecar_cannot_forge_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'table.json'
            table = {0: 'ab'}
            file.write_text(json.dumps(st.table_to_json_obj(table)), encoding='utf8')
            sidecar = Path(str(file) + '.source.json')
            sidecar.write_text(json.dumps({'sourceSha256': SHA, 'tableSha256':
                hashlib.sha256(st.plaintext_from_table(table)).hexdigest(), 'entryCount': 1}), encoding='utf8')
            with self.assertRaisesRegex(st.VerificationError, 'known source profile'):
                an._load_versioned_table(file, SHA, P)
            with self.assertRaisesRegex(st.VerificationError, 'different source build'):
                an._load_versioned_table(file, '0' * 64, P)

    def test_exclusive_table_output_never_replaces_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'table.json';out.write_text('preserved')
            with self.assertRaises(FileExistsError):st._exclusive_text(out,'replacement')
            self.assertEqual(out.read_text(),'preserved')

    def test_unknown_dll_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            dll = Path(tmp) / 'source.dll'; dll.write_bytes(b'unknown')
            out = Path(tmp) / 'table.json'
            with patch.object(st, 'load_resource', side_effect=AssertionError('must not run')):
                self.assertEqual(st.extract(dll, out), 2)
            self.assertFalse(out.exists())

    def test_annotation_overlap_and_unknown_source_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            src = Path(tmp) / 'src'; src.mkdir()
            (src / 'x.cs').write_text('x', encoding='utf8')
            self.assertEqual(an.main(['--src', str(src), '--out', str(src / 'out'), '--table-json', 'absent']), 2)
            out = Path(tmp) / 'out'
            self.assertEqual(an.main(['--src', str(src), '--out', str(out), '--table-json', 'absent']), 2)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
