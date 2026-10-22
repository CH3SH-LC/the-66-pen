"""Real pinned disassembly regressions; never read a live process."""
import hashlib,json
from pathlib import Path
import sys,tempfile,unittest
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import terrain_guard_profile as guards
import terrain_native as native


class GuardProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=HERE/'tests/fixtures/runtime-guards.json'
        cls.fixture=json.loads(cls.path.read_text('utf-8'))
        cls.functions={row['rva']:row for row in cls.fixture['functions']}

    def test_complete_pinned_function_guard_classification(self):
        actual=guards.classify_profile(self.fixture['functions'])
        profile=json.loads((HERE/'runtime-profile.json').read_text('utf-8'))
        self.assertEqual(len(actual['uses']),98)
        self.assertEqual(len(actual['hotfixZeroRvas']),35)
        self.assertEqual(len(actual['initializationBooleanRvas']),17)
        for key in ('hotfixZeroRvas','initializationBooleanRvas'):
            self.assertEqual(actual[key],profile[key])
        self.assertEqual(profile['guardEvidence']['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(profile['imageSha256'],self.fixture['imageSha256'])

    def test_real_repeated_initialization_check_is_not_hotfix(self):
        uses=guards.classify_function(self.functions['0xafb8060']['assembly'])
        init=[row for row in uses if row['flagRva']=='0x5a9359e']
        self.assertEqual({row['compareRva'] for row in init},{'0xafb81c7','0xafb8327'})
        self.assertTrue(all(row['kind']=='metadata-initialized' and row['usage']==0xbfde for row in init))
        hotfix=[row for row in uses if row['flagRva']=='0x576c86a']
        self.assertTrue(hotfix)
        self.assertTrue(all(row['kind']=='hotfix-dispatch' and row['dispatchSlot']=='0x4ddcf0' for row in hotfix))

    def test_real_mov_between_compare_and_branch_keeps_guard(self):
        actual=guards.classify_profile([self.functions[r] for r in ('0xe827750','0xc7bab90')])
        self.assertIn('0x5715608',actual['hotfixZeroRvas'])
        self.assertIn('0x5715609',actual['hotfixZeroRvas'])

    def test_unknown_initializer_is_never_silently_exempted(self):
        assembly=self.functions['0xafb8060']['assembly'].replace('call 0x524250','call 0x524251')
        with self.assertRaisesRegex(ValueError,'UNCLASSIFIED_BYTE_GUARD'):
            guards.classify_function(assembly)

    def test_flags_clobbered_before_jump_are_not_ignored(self):
        assembly=self.functions['0xc7bab90']['assembly']
        line=next(line for line in assembly.splitlines() if line.startswith('c7bab9f: '))
        with self.assertRaisesRegex(ValueError,'UNCLASSIFIED_BYTE_GUARD'):
            guards.classify_function(assembly.replace(line,'c7bab9f: test rax, rax'))

    def test_generated_runtime_header_separates_real_flag_kinds(self):
        runtime=json.loads((HERE/'runtime-profile.json').read_text('utf-8'))
        profile=native.profiles.load_profile()
        session={'pid':1,'tid':1,'processCreation':1,'threadCreation':1,'image':'offline.invalid'}
        with tempfile.TemporaryDirectory(dir=native.ROOT/'.runtime') as directory:
            run=Path(directory)
            native.action_header(run,profile,runtime,session,bytes(33208),1,0xc001,1,False)
            text=(run/'target_config.h').read_text('utf-8')
            hotfix=next(line for line in text.splitlines() if line.startswith('#define TERRAIN_HOTFIX_RVAS '))
            initialized=next(line for line in text.splitlines() if line.startswith('#define TERRAIN_INITIALIZATION_RVAS '))
            self.assertNotIn('0x5a9359e',hotfix);self.assertIn('0x5a9359e',initialized)
            self.assertIn('0x576c86a',hotfix);self.assertIn('0x5715608',hotfix);self.assertIn('0x5715609',hotfix)

    def test_rebuild_profile_classifies_every_pinned_branch(self):
        path=HERE/'tests/fixtures/rebuild-guards.json';fixture=json.loads(path.read_text())
        profile=json.loads((HERE/'rebuild-profile.json').read_text());actual=guards.classify_profile(fixture['functions'])
        self.assertEqual(len(fixture['functions']),17)
        self.assertEqual(len(actual['hotfixZeroRvas']),28);self.assertEqual(len(actual['initializationBooleanRvas']),10)
        for key in ('hotfixZeroRvas','initializationBooleanRvas'):self.assertEqual(actual[key],profile[key])
        self.assertEqual(profile['evidenceSha256'],hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(profile['functions'],[{key:f[key] for key in ('rva','head32')} for f in fixture['functions']])

    def test_rebuild_preserved_global_and_argument_shuffle_are_real_hotfix(self):
        fixture=json.loads((HERE/'tests/fixtures/rebuild-guards.json').read_text())
        functions={f['rva']:f['assembly'] for f in fixture['functions']}
        for rva,compare,slot in [('0x119df7a0','0x119df805','0x4dee38'),('0x119df6a0','0x119df6aa','0x4dee38')]:
            row=next(row for row in guards.classify_function(functions[rva]) if row['compareRva']==compare)
            self.assertEqual(row['kind'],'hotfix-dispatch');self.assertEqual(row['dispatchSlot'],slot)

    def test_rebuild_clobbered_global_is_not_a_permitted_guard(self):
        fixture=json.loads((HERE/'tests/fixtures/rebuild-guards.json').read_text())
        assembly=next(f['assembly'] for f in fixture['functions'] if f['rva']=='0x119df7a0')
        for clobber in ('xor eax, eax','call 0x123456','mov rax, rdx'):
            changed=assembly.replace('119df801: mov r8, qword ptr [rdx + 0x10]','119df801: '+clobber)
            with self.subTest(clobber=clobber),self.assertRaisesRegex(ValueError,'UNCLASSIFIED_BYTE_GUARD'):
                guards.classify_function(changed)


if __name__=='__main__':unittest.main()
