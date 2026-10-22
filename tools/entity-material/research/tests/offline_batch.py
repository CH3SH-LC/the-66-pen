"""One complete, disk-only tool batch. Never reads or changes a game process."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
MODULE = HERE.parent
ROOT = MODULE.parents[2]
OUT = ROOT / '.runtime/entity-material-20261017/research-offline' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
OUT.mkdir(parents=True, exist_ok=False)
sys.path.insert(0, str(MODULE))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import and construction must not emit artifacts, even when scratch
        # directories are not writable in the calling DSH owner's sandbox.
        cls.writes = []
        cls.forbid_writes = True
        def audit(event, args):
            if event == 'open':
                path, mode, flags = args
                writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
                if writing and cls.forbid_writes:
                    cls.writes.append(str(path)); raise AssertionError('IMPLICIT_WRITE:' + str(path))
            if event in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir') and cls.forbid_writes:
                raise AssertionError('IMPLICIT_MUTATION:' + event)
            if event == 'ctypes.dlopen' and args and 'yuanshen' in str(args[0]).lower():
                raise AssertionError('GAME_CODE_LOAD_FORBIDDEN')
        sys.addaudithook(audit)
        try:
            import api
            cls.api = api
            cls.r = api.Research()
        finally:
            cls.forbid_writes = False

    def test_01_no_import_output_or_legacy_helpers(self):
        self.assertEqual(self.writes, [])
        for name in ('shop_config_probe', 'current_metadata', 'offline_pe', 'signatures'):
            self.assertNotIn(name, sys.modules)
        self.assertFalse((MODULE / '__pycache__').exists())

    def test_02_output_scope_without_creation(self):
        self.assertEqual(self.api.validate_output('.runtime-verify/tool-research'), ROOT / '.runtime-verify/tool-research')
        self.assertEqual(self.api.validate_output('.life-dropstuff-out/tool-research'), ROOT / '.life-dropstuff-out/tool-research')
        for path in (ROOT, ROOT.parent / 'outside', ROOT / '..' / 'outside'):
            with self.subTest(path=str(path)), self.assertRaises(ValueError):
                self.api.validate_output(path)

    def test_03_metadata_class_search_and_methods(self):
        rows = self.r.classes('^Renderer$', regex=True)['rows']
        self.assertIn(2297, {row['index'] for row in rows})
        methods = self.r.methods(82510)
        self.assertEqual(methods['methodCount'], 13)
        self.assertIn('0x102e05d0', {row['method']['functionRva'] for row in methods['methods']})
        self.assertEqual(self.r.method_at(0x102e05d0)[0]['method']['owner']['index'], 82510)

    def test_04_actual_material_field_offsets_and_types(self):
        data = self.r.fields(39022)
        by_offset = {row['offset']: row for row in data['fields'] if row['offset'] is not None}
        expected = {0x30:(8,17), 0x34:(2,), 0x35:(2,), 0x36:(2,), 0x37:(2,), 0x38:(9,), 0x3c:(8,17), 0x40:(8,9), 0x44:(12,)}
        for offset, kind in expected.items():
            self.assertIn(by_offset[offset]['type']['kind'], kind)
            self.assertTrue(by_offset[offset]['name']['name'])
        self.assertFalse(data['runtimeOffsetsVerified'])

    def test_05_real_protobuf_field_layout(self):
        data = self.r.fields(52132)
        by_offset = {row['offset']: row for row in data['fields'] if row['offset'] is not None}
        for offset, kind in {0x18:(12,), 0x1c:(8,17), 0x20:(8,9), 0x24:(9,), 0x28:(2,), 0x29:(2,), 0x2a:(2,), 0x2b:(2,), 0x2c:(8,17)}.items():
            self.assertIn(by_offset[offset]['type']['kind'], kind)

    def test_06_actual_property_accessor_table(self):
        data = self.r.properties(2297)
        self.assertFalse(data['inferredFromMethodNames'])
        prop = next(row for row in data['properties'] if row['name']['name'] == 'sharedMaterials')
        self.assertEqual(prop['getter']['method']['functionRva'], '0x19cd29e0')
        self.assertIsNotNone(prop['setter'])

    def test_07_vtable_and_exact_range(self):
        table = self.r.vtable(39022)
        self.assertGreater(table['vtableCount'], 0)
        body = self.r.instructions(0x102e060c, 0x102e0631)
        self.assertTrue(body['linearDecodeComplete'])
        self.assertEqual(body['instructions'][0]['ripTargets'], ['0x5a27720'])
        self.assertIn('0x1018c2b0', [row['operands'] for row in body['instructions'] if row['mnemonic'] == 'call'])

    def test_08_literal_pair_slot_and_real_rip_chain(self):
        chain = self.r.binding_xrefs(literal=39576)
        self.assertFalse(chain['literalIndexImmediateScanUsed'])
        self.assertFalse(chain['runtimeSlotValueRead'])
        self.assertTrue(any(row['slot'] == '0x5a27720' and row['usage'] == 0xceb2 for row in chain['bindings']['rows']))
        references = [row for row in chain['ripReferences'] if row['instruction']['rva'] == '0x102e060c']
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]['methods'][0]['method']['owner']['index'], 82510)
        self.assertEqual(references[0]['slots'], ['0x5a27720'])

    def test_09_explicit_usage_and_rip_xref_scope(self):
        usage = self.r.usage(0xceb2)
        literal = next(row for row in usage['entries'] if row['kind'] == 5)
        self.assertEqual(literal['source'], 39576)
        data = self.r.rip_xrefs([0x5a27720], start=0x102e05d0, end=0x102e0693)
        self.assertFalse(data['truncated'])
        self.assertEqual([row['instruction']['rva'] for row in data['rows']], ['0x102e060c'])

    def test_10_query_methods_do_not_write(self):
        self.__class__.forbid_writes = True
        try:
            self.r.fields(82510)
            self.r.properties(52132)
            self.r.dump(0x102e05d0)
            self.r.bindings(slot=0x5a27720)
        finally:
            self.__class__.forbid_writes = False

    def test_11_explicit_writer_preserves_previous_result(self):
        first = self.api.write_result(OUT / 'explicit', 'probe', {'test': 1})
        second = self.api.write_result(OUT / 'explicit', 'probe', {'test': 2})
        self.assertNotEqual(first, second)
        self.assertEqual(json.loads(first.read_text(encoding='utf-8')), {'test': 1})

    def test_12_cli_sandbox_blocks_all_other_writes(self):
        destination = OUT / 'cli-output'
        driver = OUT / 'isolated-cli.py'
        driver.write_text('''import os,sys,runpy
from pathlib import Path
sys.dont_write_bytecode=True
allowed=Path(sys.argv[1]).resolve();cli=Path(sys.argv[2]).resolve()
def audit(event,args):
    if event=='open':
        path,mode,flags=args
        writing=(isinstance(mode,str) and any(x in mode for x in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing and not Path(path).resolve().is_relative_to(allowed):raise PermissionError('ISOLATED_WRITE_DENIED:'+str(path))
    if event=='os.mkdir' and not Path(args[0]).resolve().is_relative_to(allowed):raise PermissionError('ISOLATED_MKDIR_DENIED:'+str(args[0]))
sys.addaudithook(audit)
sys.path.insert(0,str(cli.parent));sys.argv=[str(cli),'--out',str(allowed),*sys.argv[3:]]
runpy.run_path(str(cli),run_name='__main__')
''', encoding='utf-8')
        for command in (['classes', '--name', 'DKMHPPIIJNN'], ['dump', '0x102e05d0'],
                        ['method-at', '0x1355d560'], ['field', '39022', '--ordinal', '0'], ['domains']):
            run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(driver), str(destination), str(MODULE / 'cli.py'), *command], cwd=ROOT, capture_output=True, text=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            response = json.loads(run.stdout)
            self.assertTrue(response['ok'])
            self.assertTrue(Path(response['artifact']).is_relative_to(destination))

    def test_13_native_method_attributes_static_and_instance(self):
        controls = [(0x19cd29e0, 17473, 2297, 0x886, False),
                    (0x19c9de20, 19031, 2374, 0x896, True),
                    (0x19d141e0, 61696, 8451, 0x96, True),
                    (0x1355d560, 146656, 19411, 0x1886, False),
                    (0x102e05d0, 679365, 82510, 0x81, False)]
        for rva, index, owner, flags, static in controls:
            with self.subTest(rva=hex(rva)):
                row = self.r.method_at(rva)[0]
                self.assertEqual(row['methodDefinitionIndex'], index)
                self.assertEqual(row['declaringType']['typeDefinitionIndex'], owner)
                self.assertEqual(row['methodAttributes']['value'], flags)
                self.assertEqual(row['isStatic'], static)
                self.assertEqual(row['isInstance'], not static)
                self.assertFalse(row['nativeAbiResolved'])
        ctor = self.r.method(146656)
        self.assertTrue(ctor['isConstructor'])
        self.assertEqual(ctor['name']['name'], '.ctor')
        self.assertEqual(ctor['declaredParameterCount'], 0)
        self.assertEqual(ctor['parameters'], [])
        self.assertTrue(ctor['hasImplicitThis'])
        self.assertFalse(ctor['parametersIncludeImplicitThis'])

    def test_14_parameter_attribute_context_is_not_static(self):
        method = self.r.method(61696)
        parameter = method['parameters'][0]
        self.assertEqual(parameter['indexDomain'], 'ParameterDefinitionIndex')
        self.assertEqual(parameter['type']['typeIndex'], 440742)
        self.assertEqual(parameter['type']['kindName'], 'I4')
        self.assertEqual(parameter['parameterAttributes']['value'], 0x1010)
        self.assertEqual(parameter['parameterAttributes']['flags'], ['Optional', 'HasDefault'])
        self.assertNotIn('Static', parameter['parameterAttributes']['flags'])
        self.assertFalse(parameter['implicitThis'])

    def test_15_field_and_type_domains_and_bounded_selector(self):
        fields = self.r.fields(39022)
        row = fields['fields'][0]
        self.assertEqual(row['indexDomain'], 'FieldDefinitionIndex')
        self.assertEqual(row['ordinalDomain'], 'DeclaredFieldOrdinal')
        self.assertEqual(row['declaringTypeDefinitionIndex'], 39022)
        self.assertFalse(row['serializedFieldNumberKnown'])
        self.assertIsNone(row['serializedFieldNumber'])
        self.assertEqual(self.r.field(39022, ordinal=0)['field'], row)
        self.assertEqual(self.r.field(39022, index=row['fieldIndex'])['field'], row)
        for arguments in ({}, {'ordinal':0, 'index':row['fieldIndex']}, {'ordinal':-1}, {'index':fields['fieldBegin']-1}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.r.field(39022, **arguments)
        alias = self.r.m.definition_aliases(2297)[0]
        typed = self.r.type(alias['index'])
        self.assertEqual(typed['indexDomain'], 'Il2CppTypeIndex')
        self.assertEqual(typed['kind'], 18)
        self.assertEqual(typed['kindDomain'], 'Il2CppTypeEnum')
        self.assertEqual(typed['kindName'], 'CLASS')
        self.assertEqual(typed['definition']['typeDefinitionIndex'], 2297)
        self.assertFalse(typed['runtimeComponentKindKnown'])
        self.assertIsNone(typed['runtimeComponentKind'])

    def test_16_virtual_slots_and_recursive_accessor_semantics(self):
        table = self.r.vtable(39022)
        known = [row for row in table['rows'] if row['kind'] == 3 and row['method']['isVirtual']]
        self.assertTrue(known)
        for row in known:
            # A definition's primary slot must resolve to that same method in
            # this control class, but another row may reference it too.
            self.assertEqual(table['rows'][row['method']['vtableSlot']]['methodIndex'], row['methodIndex'])
        self.assertEqual(table['rows'][4]['methodIndex'], 242205)
        self.assertEqual(table['rows'][15]['methodIndex'], 242205)
        self.assertEqual(table['rows'][4]['method']['vtableSlot'], 15)
        self.assertFalse(table['rows'][4]['isMethodDefinitionSlot'])
        self.assertTrue(table['rows'][15]['isMethodDefinitionSlot'])
        self.assertFalse(table['runtimeDispatchResolved'])
        prop = next(row for row in self.r.properties(2297)['properties'] if row['name']['name'] == 'sharedMaterials')
        self.assertFalse(prop['getter']['isStatic'])
        self.assertFalse(prop['setter']['isStatic'])
        self.assertEqual(prop['setter']['declaredParameterCount'], 1)
        self.assertEqual(prop['getter']['declaringType']['typeDefinitionIndex'], 2297)
        self.assertFalse(prop['getter']['nativeWord2c']['semanticVerified'])
        self.assertIn('Il2CppTypeEnum', self.r.domains()['domains'])

    def test_17_native_instruction_evidence_matches_decoder(self):
        evidence = self.r.instructions(0x515746, 0x515757)
        self.assertEqual([(x['mnemonic'], x['operands']) for x in evidence['instructions']],
                         [('movzx', 'edx, word ptr [rbp + 0x12]'), ('sub', 'edx, r8d'),
                          ('add', 'edx, 0xffff8d97'), ('mov', 'word ptr [rbx + 0x28], dx')])
        self.assertEqual(self.r.m.get(0x3909610, 16).hex(), '9f4d81aa000000000000000000000000')
        check = self.r.instructions(0x53f255, 0x53f259)['instructions'][0]
        self.assertEqual((check['mnemonic'], check['operands']), ('test', 'byte ptr [rdi + 0x28], 0x10'))
        slot = self.r.instructions(0x517518, 0x51751c)['instructions'][0]
        self.assertEqual((slot['mnemonic'], slot['operands']), ('movzx', 'eax, word ptr [rsi + 0x2a]'))

    def test_18_semantic_queries_do_not_write(self):
        self.__class__.forbid_writes = True
        try:
            self.r.method(146656)
            self.r.field(39022, ordinal=0)
            self.r.domains()
            self.r.class_info(19411)
        finally:
            self.__class__.forbid_writes = False


def main():
    report = dict(kind='il2cpp-research-offline-batch-v2', startedUtc=datetime.now(timezone.utc).isoformat(),
                  gameConnected=False, nativeCalled=False, gameplayValidated=False)
    # Read-only pin of the previously frozen material module: new research files
    # are not allowed to silently alter its production source or specs.
    frozen_path = ROOT / '.runtime/entity-material-20261017/final-offline/20261016T233114442260Z/report.json'
    frozen = json.loads(frozen_path.read_text(encoding='utf-8'))['sourceHashes']
    preserved = {name:sha(ROOT / name) == digest for name,digest in frozen.items()}
    with (OUT / 'checks.log').open('x', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ResearchTests))
    report.update(ok=result.wasSuccessful() and all(preserved.values()), checks=result.testsRun,
                  frozenMaterialSourcesUnchanged=preserved,
                  sourceHashes={str(path.relative_to(ROOT)):sha(path) for path in sorted(MODULE.rglob('*')) if path.is_file() and '__pycache__' not in path.parts},
                  finishedUtc=datetime.now(timezone.utc).isoformat())
    path = OUT / 'report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(report=str(path), **report), ensure_ascii=False))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
