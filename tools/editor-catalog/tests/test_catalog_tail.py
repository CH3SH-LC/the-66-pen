import contextlib
import importlib.util
import io
import json
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), TOOLS / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


pe = module('extract-user-strings')
idx = module('index-types')
proxy = module('annotate-proxies')
cats = module('categorize-strings')
SHA = '565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a'


def tree_metadata(src, **extra):
    value={'annotationOnly':True,'sourceSha256':SHA,**extra}
    value['outputSetSha256']=idx.source_set_id((p.relative_to(src).as_posix(),hashlib.sha256(p.read_bytes()).hexdigest()) for p in src.rglob('*.cs'))
    (src/'.source.json').write_text(json.dumps(value))


def map_metadata(path, count=1):
    value={'sourceSha256':SHA,'tokenValidationPassed':True,'outputSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'completeMap':True,'outputRows':count,'totalPairs':count}
    Path(str(path)+'.source.json').write_text(json.dumps(value))


def fixture(magic):
    data = bytearray(2048)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    opt = 0x98
    optsize = 0xe0 if magic == 0x10b else 0xf0
    struct.pack_into('<H', data, 0x86, 1)
    struct.pack_into('<H', data, 0x94, optsize)
    struct.pack_into('<H', data, opt, magic)
    struct.pack_into('<I', data, opt + (0x5c if magic == 0x10b else 0x6c), 16)
    struct.pack_into('<II', data, opt + (0x60 if magic == 0x10b else 0x70) + 14 * 8, 0x2000, 72)
    struct.pack_into('<IIII', data, opt + optsize + 8, 1536, 0x2000, 1536, 512)
    struct.pack_into('<I', data, 512, 72)
    struct.pack_into('<II', data, 520, 0x2100, 256)
    md = 768
    data[md:md + 4] = b'BSJB'
    struct.pack_into('<I', data, md + 12, 12)
    data[md + 16:md + 28] = b'v4.0.30319\0\0'
    struct.pack_into('<HHII', data, md + 28, 0, 1, 64, 8)
    data[md + 40:md + 44] = b'#US\0'
    # flag follows UTF-16, not before it. Trailing zeros are alignment padding.
    data[md + 64:md + 72] = b'\0\x05A\0B\0\0\0'
    return data


class CatalogTail(unittest.TestCase):
    def test_pe32_and_pe64_actual_directory_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'a.dll'
            for magic in (0x10b, 0x20b):
                file.write_bytes(fixture(magic))
                data, cli, size, sections = pe.read_pe_metadata(file)
                self.assertEqual(cli, 0x2000)
                self.assertEqual(list(pe.iter_us_strings(pe.find_us_heap(data, cli, sections))), ['AB'])

    def test_heap_unicode_and_corruption(self):
        text = '\u5b58\u6863\U0001f600'
        raw = text.encode('utf-16-le')
        self.assertEqual(list(pe.iter_us_strings(b'\0' + bytes([len(raw) + 1]) + raw + b'\1')), [text])
        for heap in [b'\0\x80', b'\0\xc0\0', b'\0\xff', b'\0\5a', b'\0\3\0\xd8\0', b'\0\3a\0\2']:
            with self.subTest(heap=heap), self.assertRaises(pe.PEError):
                list(pe.iter_us_strings(heap))

    def test_metadata_root_rejects_ambiguous_or_overlapping_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'bad.dll'
            for case in ('duplicate','overlap','version_outside'):
                data=fixture(0x20b);md=768
                if case=='version_outside':struct.pack_into('<I',data,524,28)
                else:
                    struct.pack_into('<H',data,md+30,2)
                    struct.pack_into('<II',data,md+44,64,8)
                    data[md+52:md+56]=b'#US\0' if case=='duplicate' else b'#~\0\0'
                file.write_bytes(data)
                parsed,cli,_,sections=pe.read_pe_metadata(file)
                with self.subTest(case=case),self.assertRaises(pe.PEError):pe.find_us_heap(parsed,cli,sections)

    def test_index_preserves_same_name_in_different_namespaces(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);src=root/'src';src.mkdir()
            (src/'.source.json').write_text(json.dumps({'annotationOnly':True,'sourceSha256':SHA}))
            for namespace,literal in [('A','one'),('B','two')]:
                folder=src/namespace;folder.mkdir();(folder/'Type.cs').write_text('var a="'+literal+'" /* string 0 */;')
            args=['--src',str(src),'--json',str(root/'types.json'),'--tsv',str(root/'types.tsv'),'--reverse',str(root/'reverse.json')]
            tree_metadata(src)
            self.assertEqual(idx.main(args),0)
            self.assertEqual(json.loads((root/'types.json').read_text()),{'A/Type':['one'],'B/Type':['two']})

    def test_category_malformed_table_returns_refusal_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()):
            root=Path(tmp);table=root/'table.json';table.write_text('{"0":123}')
            Path(str(table)+'.source.json').write_text(json.dumps({'sourceSha256':SHA,'tableSha256':'0'*64}))
            self.assertEqual(cats.main(['--table',str(table),'--out',str(root/'out')]),2)
            self.assertFalse((root/'out').exists())

    def test_truncated_or_bad_pe_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / 'a.dll'
            for blob in [b'MZ', fixture(0x20b)[:1000], bytes(2048)]:
                file.write_bytes(blob)
                with self.assertRaises(pe.PEError):
                    pe.read_pe_metadata(file)

    def test_extract_never_overwrites_sidecar_or_source(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            file = Path(tmp) / 'a.dll'; file.write_bytes(fixture(0x20b))
            out = Path(tmp) / 'strings.txt'
            sidecar = Path(str(out) + '.source.json'); sidecar.write_text('old')
            self.assertEqual(pe.main([str(file), '--out', str(out)]), 2)
            self.assertFalse(out.exists())
            self.assertEqual(pe.main([str(file), '--out', str(file)]), 2)

    def test_index_outputs_are_explicit_fresh_and_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp); src = root / 'src'; src.mkdir()
            (src / '.source.json').write_text(json.dumps({'annotationOnly': True, 'sourceSha256': SHA}))
            (src / 'Type.cs').write_text('var n = 1;')
            args = ['--src', str(src), '--json', str(root / 'out.json'), '--tsv', str(root / 'out.tsv'), '--reverse', str(root / 'rev.json')]
            self.assertEqual(idx.main(args), 2)
            self.assertFalse((root / 'out.json').exists())
            (src / 'Type.cs').write_text('var s = "hello" /* string 0 */;')
            tree_metadata(src)
            self.assertEqual(idx.main(args), 0)
            self.assertEqual(json.loads((root / 'rev.json').read_text()), {'hello': ['Type']})
            self.assertEqual(idx.main(args), 2)

    def test_index_and_proxy_refuse_tampered_inputs_before_output(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);src=root/'src';src.mkdir();source=src/'T.cs'
            source.write_text('Owner.Field; var n="one" /* string 0 */;')
            tree_metadata(src,inputCompleteness={'complete':False,'failedTypes':5})
            mapping=root/'map.json';rows=[{'owner':'Owner','field':'Field','slot':'Owner.Field','type':'Target','method':'Method'}];mapping.write_text(json.dumps(rows));map_metadata(mapping)
            args=['--src',str(src),'--out',str(root/'proxy'),'--map',str(mapping)]
            rows[0]['method']='Edited';mapping.write_text(json.dumps(rows))
            self.assertEqual(proxy.main(args),2);self.assertFalse((root/'proxy').exists())
            map_metadata(mapping);source.write_text('Owner.Field; var n="changed" /* string 0 */;')
            self.assertEqual(proxy.main(args),2);self.assertFalse((root/'proxy').exists())
            self.assertEqual(idx.main(['--src',str(src),'--json',str(root/'types'),'--tsv',str(root/'tsv'),'--reverse',str(root/'reverse')]),2)
            self.assertFalse((root/'types').exists())
            tree_metadata(src,inputCompleteness={'complete':False,'failedTypes':5})
            self.assertEqual(proxy.main(args),0)
            meta=json.loads((root/'proxy/.source.json').read_text())
            self.assertEqual(meta['inputCompleteness'],{'complete':False,'failedTypes':5})
            self.assertTrue(meta['outputSetSha256'])

    def test_proxy_owner_prefilter_matches_original_reference_results(self):
        owners={'A':{'B':('One','Call')},'A.B':{'Field':('Two','Call')},'Owner':{'Field':('Three','Call')},'Ns.Owner':{'Field':('Four','Call')}}
        cases=['A.B.Field; Owner.Field;', 'PrefixOwner.Field; x.Owner.Field; Owner.Field.More;', 'global::Ns.Owner.Field; A.B;', '// Owner.Field\n var s="A.B.Field"; Owner.Field;', 'Other.A.B.Field; OtherNs.Owner.Field; @"Owner.Field";', 'Ns.Owner.Field; Owner.FieldX; Owner.Field;']
        lexical=proxy._lexical()
        for text in cases:
            old=sorted((o for o in owners if o in text),key=len,reverse=True)
            expected=proxy.annotate_text(text,proxy.build_matcher(old),owners,lexical) if old else (text,0)
            new=proxy.referenced_owners(text,owners)
            actual=proxy.annotate_text(text,proxy.build_matcher(new),owners,lexical) if new else (text,0)
            with self.subTest(text=text):self.assertEqual(actual,expected)

    def test_proxy_rejects_partial_map_with_fresh_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            mapping=Path(tmp)/'map.json';mapping.write_text(json.dumps([{'owner':'Owner','field':'Field','slot':'Owner.Field','type':'Target','method':'Method'}]))
            map_metadata(mapping,count=2)
            with self.assertRaisesRegex(proxy.CatalogError,'complete'):proxy.load_map(mapping)

    def test_proxy_map_unknown_and_cross_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            root = Path(tmp); src = root / 'src'; src.mkdir()
            (src / '.source.json').write_text(json.dumps({'sourceSha256': SHA}))
            (src / 'T.cs').write_text('Owner.Field;')
            mapping = root / 'map.json'
            mapping.write_text(json.dumps([{'owner': 'Owner', 'field': 'Field', 'slot': 'Owner.Field', 'type': 'Target', 'method': 'Method'}]))
            sidecar = Path(str(mapping) + '.source.json')
            for identity in ['0' * 64, 'd4b429a371505ff5252e5a869a8fc250cd0924440a648fdb844a0eebed083841']:
                sidecar.write_text(json.dumps({'sourceSha256': identity, 'tokenValidationPassed': True}))
                self.assertEqual(proxy.main(['--src', str(src), '--out', str(root / 'out'), '--map', str(mapping)]), 2)
                self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
