"""Isolated transport invariants. Never connect to DSH or a game process."""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('native_card_under_test', HERE / 'dispatch.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class Contracts(unittest.TestCase):
    def setUp(self):
        area = d.ROOT / '.runtime/mondstadt/rework-20261017/native-card-tests'
        area.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=area)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source/run'
        self.source.mkdir(parents=True)
        self.run = self.root / 'prepared/generalized-tabs/card'
        self.run.mkdir(parents=True)
        self.session = dict(pid=12, tid=23, processCreation=34, threadCreation=45,
                            image='D:\\fixtures\\never-executed.exe')
        self.card = dict(tool='generalized-tabs', session=self.session, nonce=81, deadline=91)
        self.header = '\n'.join('#define ' + key + ' ' + str(value) + 'ULL' for key, value in {
            'HR_ACTION':13, 'HR_NONCE':81, 'HR_DEADLINE':91, 'HR_MESSAGE_ID':50262, 'HR_TARGET_PID':12,
            'HR_TARGET_TID':23, 'HR_TARGET_CREATION':34, 'HR_TARGET_THREAD_CREATION':45}.items())
        self.header += '\n#define HR_TARGET_IMAGE L' + json.dumps(self.session['image']) + '\n'
        self.route = copy.deepcopy(d.ROUTES)
        self.route['generalized-tabs']['root'] = self.source.parent
        self.route_patch = patch.object(d, 'ROUTES', self.route)
        self.route_patch.start()

    def tearDown(self):
        self.route_patch.stop()
        self.temp.cleanup()

    def put(self, name, value):
        (self.source / name).write_text(json.dumps(value), encoding='utf-8')

    def built(self):
        files = {'target_config.h':self.header, 'baseline-snapshot.bin':'fixture',
            'hook_receipt_probe.exe':'never executed', 'hook_receipt.dll':'never executed',
            'invoke-generalized-tabs.ps1':'throw "fixture never launched"',
            'normalized-spec.json':json.dumps(dict(levelId=d.LEVEL)), 'receipt-layout.json':'{}'}
        for name, text in files.items():
            (self.source / name).write_text(text, encoding='utf-8')
        spec = self.root / 'spec.json'
        spec.write_text('{}', encoding='utf-8')
        value = dict(ok=True, kind='generalized-tabs-build-v1', compiled=True, launchable=True,
            compileOnly=False, layoutOnly=False, run=str(self.source), actionCode=13,
            componentKind=17, receiptVersion=18, levelId=d.LEVEL, session=self.session,
            wrapper=str(self.source / 'invoke-generalized-tabs.ps1'),
            wrapperSha256=d.digest(self.source / 'invoke-generalized-tabs.ps1'),
            spec=str(spec), specSha256=d.digest(spec), sourceHashes={},
            normalizedSpecSha256=d.digest(self.source / 'normalized-spec.json'),
            expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
            hashes={name:d.digest(self.source / name) for name in files})
        self.put('build-result.json', value)
        return value

    def receipt(self, **changes):
        value = dict(scope='FIXED_GENERALIZED_TABS_ACTION', selfTestOnly=False, pid=12, tid=23,
            receiptNonce='81', receiptDeadline='91', receiptProtocol=18, probeElevatedHigh=True,
            transportOk=True, unhooked=True, callbackCount=1, activeCallbacks=0, hostPostUnhookPings=0)
        value.update(changes)
        self.put('stdout.jsonl', value)
        self.put('exit.json', dict(scope=value['scope'], executed=True, exitCode=0))

    def test_duplicate_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            json.loads('{"ok":true,"ok":false}', object_pairs_hook=d.json_unique)

    def test_paths_cannot_escape_or_use_device_alias(self):
        with self.assertRaisesRegex(ValueError, 'OUTSIDE'):
            d.ordinary(self.root / 'spec.json', self.source)
        for name in ('CON.json','text.','file:stream'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'ALIAS'):
                d.ordinary(self.source / name)

    def test_header_is_bound_to_action_process_thread_and_start(self):
        file = self.source / 'target_config.h'
        file.write_text(self.header, encoding='utf-8')
        self.assertEqual(d.identity_header(file,13,self.session),dict(nonce=81,deadline=91,messageId=50262))
        with self.assertRaises(ValueError): d.identity_header(file,6,self.session)
        for key in ('pid','tid','processCreation','threadCreation','image'):
            changed = dict(self.session)
            changed[key] = 'changed' if key=='image' else 999
            with self.subTest(key=key), self.assertRaises(ValueError): d.identity_header(file,13,changed)

    def test_duplicate_header_definition_rejected(self):
        file = self.source / 'target_config.h'
        file.write_text(self.header + '#define HR_NONCE 82ULL\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'HEADER_IDENTITY'): d.identity_header(file,13,self.session)

    def test_unregistered_message_numbers_cannot_launch(self):
        file = self.source / 'target_config.h'
        for value in (0, 0xbfff, 0x10000, 0x7fffffff):
            file.write_text(self.header.replace('HR_MESSAGE_ID 50262ULL',
                'HR_MESSAGE_ID ' + str(value) + 'ULL'), encoding='utf-8')
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'REGISTERED_MESSAGE_RANGE'):
                d.identity_header(file, 13, self.session)

    def test_build_manifest_requires_complete_bound_artifacts(self):
        self.built()
        source, _, _, identity = d.source_manifest('generalized-tabs',self.source)
        self.assertEqual(source,self.source)
        self.assertEqual(identity['nonce'],81)
        (self.source/'hook_receipt_probe.exe').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'): d.source_manifest('generalized-tabs',self.source)

    def test_compile_only_or_protected_level_never_routes(self):
        for key,value in (('compileOnly',True),('launchable',False),('levelId',1073741842),('componentKind',37)):
            built=self.built();built[key]=value;self.put('build-result.json',built)
            with self.subTest(key=key), self.assertRaises(ValueError): d.source_manifest('generalized-tabs',self.source)

    def test_artifact_path_traversal_rejected(self):
        built=self.built();(self.root/'outside').write_text('outside',encoding='utf-8')
        built['hashes']['../../outside']=d.digest(self.root/'outside');self.put('build-result.json',built)
        with self.assertRaisesRegex(ValueError,'ALIAS|OUTSIDE'): d.source_manifest('generalized-tabs',self.source)

    def test_complete_cleanup_has_exact_card_identity(self):
        self.receipt()
        self.assertEqual(d.cleanup(self.run,self.card,self.source),(True,True))
        for key,value in (('receiptNonce','82'),('receiptDeadline','92'),('receiptProtocol',10),('pid',13),('tid',24),('selfTestOnly',True)):
            self.receipt(**{key:value})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'IDENTITY'): d.cleanup(self.run,self.card,self.source)

    def test_active_callbacks_and_missing_unhook_never_safe(self):
        for key,value in (('unhooked',False),('activeCallbacks',1),('callbackCount',2),('hostPostUnhookPings',1),('transportOk',False)):
            self.receipt(**{key:value})
            with self.subTest(key=key): self.assertEqual(d.cleanup(self.run,self.card,self.source),(False,True))

    def test_wrapper_refusal_only_safe_without_native_attempt(self):
        self.put('exit.json',dict(scope='FIXED_GENERALIZED_TABS_ACTION',executed=False,error='expired'))
        self.assertEqual(d.cleanup(self.run,self.card,self.source),(True,False))
        (self.source/'attempt.used').touch()
        with self.assertRaisesRegex(ValueError,'ATTEMPT'): d.cleanup(self.run,self.card,self.source)

    def test_invalid_identity_after_dispatch_stays_unknown(self):
        (self.run/'dispatch.claim').touch()
        with patch.object(d,'manifest',side_effect=ValueError('changed')):
            result=d.uncertainty(self.run)
        self.assertTrue(result['outcomeUncertain']);self.assertFalse(result['safeToRelease'])

    def test_dispatch_duplicate_does_not_invoke_wrapper(self):
        (self.source/'launch.claim').touch()
        admin=type('Admin',(),{'IsUserAnAdmin':lambda self:1})()
        windll=type('Windll',(),{'shell32':admin})()
        with patch.object(d,'manifest',return_value=(self.run,self.card,self.source)), \
             patch.object(d.ctypes,'windll',windll,create=True), patch.object(d.os,'name','nt'), \
             patch.object(d.subprocess,'run') as invoked:
            with self.assertRaisesRegex(ValueError,'ALREADY_CONSUMED'):
                d.dispatch('generalized-tabs',self.run,direct=True)
            invoked.assert_not_called()

    def test_source_can_only_be_wrapped_once(self):
        self.built()
        with patch.object(d,'OUTPUT',self.root/'prepared'), \
             patch.object(d,'source_manifest',return_value=(self.source,{},dict(sourceHashes={},levelId=d.LEVEL),dict(session=self.session,expiresUtc='future',nonce=81,deadline=91))):
            first=d.prepare('generalized-tabs',self.source)
            self.assertFalse(first['nativeCalled'])
            with self.assertRaises(FileExistsError): d.prepare('generalized-tabs',self.source)
            self.assertEqual(d.read(self.source/'native-card.claim')['run'],first['run'])


class ComponentContracts(unittest.TestCase):
    """Component transport only: fixture bytes are never native candidates."""
    setUp = Contracts.setUp
    tearDown = Contracts.tearDown
    put = Contracts.put
    def component(self, tool='mondstadt-combat'):
        route = self.route[tool]
        route['root'] = self.source.parent
        route['componentFolder'] = self.root / 'owner'
        route['componentFolder'].mkdir(exist_ok=True)
        decoder = route['componentFolder'] / 'native_acceptance.py'
        decoder.write_text('def validate_run(run):\n    return {}\n', encoding='utf-8')
        self.session['window'] = 56
        baseline = self.root / 'baseline'
        baseline.mkdir(exist_ok=True)
        (baseline / 'prepared.json').write_text(json.dumps(dict(session=self.session)), encoding='utf-8')
        (baseline / 'exit.json').write_text(json.dumps(dict(finishedUtc=datetime.now(timezone.utc).isoformat())), encoding='utf-8')
        files = {'target_config.h':self.header.replace('HR_ACTION 13ULL', 'HR_ACTION '+str(route['action'])+'ULL'),
            'baseline-snapshot.bin':'fixture', 'normalized-spec.json':json.dumps(dict(levelId=d.LEVEL)),
            'receipt-layout.json':'{}', 'hook_receipt.dll':'never executed',
            'hook_receipt_probe.exe':'never executed', route['wrapper']:'throw "fixture never launched"'}
        for name,text in files.items(): (self.source/name).write_text(text,encoding='utf-8')
        prepared = dict(kind=route['kind'].replace('-build-','-prepared-'), levelId=d.LEVEL,
            launchable=True, compileOnly=False, reviewed=True, allowWrites=True,
            actionCode=route['action'], receiptVersion=route['protocol'], scope=route['scope'],
            wrapperName=route['wrapper'], session=dict(self.session), nonce=81, deadline=91, messageId=50262,
            expiresUtc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
            baselineRun=str(baseline), baselineSha256=d.digest(self.source/'baseline-snapshot.bin'),
            normalizedSpecSha256=d.digest(self.source/'normalized-spec.json'),
            sourceHashes={decoder.relative_to(d.ROOT).as_posix():d.digest(decoder)})
        self.put('prepared.json',prepared)
        built=dict(prepared, kind=route['kind'],ok=True,compiled=True,run=str(self.source),
            hashes={name:d.digest(self.source/name) for name in (*files,'prepared.json')})
        self.put('build-result.json',built)
        ro=SimpleNamespace(decode_run=lambda path:dict(ok=True,levelObservation=dict(verified=True,levelId=d.LEVEL)),
            load_decoder=lambda:SimpleNamespace(read_probe=lambda path:(dict(snapshotHex=b'fixture'.hex()),'utf-8')))
        return prepared,built,ro

    def test_component_admission_binds_each_fixed_route(self):
        for tool in ('mondstadt-combat','mondstadt-dropstuff'):
            prepared,built,ro=self.component(tool)
            with patch.object(d,'load_module',return_value=ro):
                source,_,actual,identity=d.source_manifest(tool,self.source)
                self.assertEqual(actual,prepared);self.assertEqual(identity['nonce'],81)

    def test_component_compile_only_and_wrong_action_rejected(self):
        for key,value in (('compileOnly',True),('launchable',False),('actionCode',20)):
            prepared,built,ro=self.component();built[key]=value;self.put('build-result.json',built)
            with patch.object(d,'load_module',return_value=ro),self.assertRaises(ValueError):
                d.source_manifest('mondstadt-combat',self.source)

    def test_component_message_id_must_match_build_prepared_and_native_header(self):
        for mismatch in ('missing', 'build', 'header'):
            prepared,built,ro=self.component()
            if mismatch == 'missing':
                del prepared['messageId'];del built['messageId']
            elif mismatch == 'build':
                built['messageId'] = 50263
            else:
                file = self.source / 'target_config.h'
                file.write_text(file.read_text(encoding='utf-8').replace(
                    'HR_MESSAGE_ID 50262ULL', 'HR_MESSAGE_ID 50263ULL'), encoding='utf-8')
                built['hashes']['target_config.h'] = d.digest(file)
            self.put('prepared.json',prepared)
            built['hashes']['prepared.json'] = d.digest(self.source/'prepared.json')
            self.put('build-result.json',built)
            with self.subTest(mismatch=mismatch), patch.object(d,'load_module',return_value=ro), \
                 self.assertRaisesRegex(ValueError,'COMPONENT_(BUILD_BINDING:messageId|HEADER_BINDING)'):
                d.source_manifest('mondstadt-combat',self.source)

    def test_component_needs_baseline_raw_identity_and_observed_level(self):
        prepared,built,ro=self.component()
        with patch.object(d,'load_module',return_value=ro):
            ro.decode_run=lambda path:dict(ok=True,levelObservation=dict(verified=True,levelId=1073741842))
            with self.assertRaisesRegex(ValueError,'BASELINE_NOT_ACCEPTED'):
                d.component_prepared('mondstadt-combat',self.source,built)
            ro.decode_run=lambda path:dict(ok=True,levelObservation=dict(verified=True,levelId=d.LEVEL))
            ro.load_decoder=lambda:SimpleNamespace(read_probe=lambda path:(dict(snapshotHex=b'changed'.hex()),'utf-8'))
            with self.assertRaisesRegex(ValueError,'BASELINE_RAW_MISMATCH'):
                d.component_prepared('mondstadt-combat',self.source,built)

    def test_component_rejects_freshness_and_session_mismatch(self):
        prepared,built,ro=self.component();base=Path(prepared['baselineRun'])
        (base/'exit.json').write_text(json.dumps(dict(finishedUtc=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())),encoding='utf-8')
        with patch.object(d,'load_module',return_value=ro):
            with self.assertRaisesRegex(ValueError,'BASELINE_STALE'):
                d.component_prepared('mondstadt-combat',self.source,built,fresh=True)
            (base/'prepared.json').write_text(json.dumps(dict(session=dict(self.session,processCreation=999))),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'SESSION_MISMATCH'):
                d.component_prepared('mondstadt-combat',self.source,built)

    def test_component_acceptor_and_spec_are_pinned(self):
        prepared,built,ro=self.component()
        with patch.object(d,'load_module',return_value=ro):
            (self.route['mondstadt-combat']['componentFolder']/'native_acceptance.py').write_text('# changed',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'ACCEPTOR_NOT_PINNED'):
                d.component_prepared('mondstadt-combat',self.source,built)

    def test_component_raw_acceptance_must_verify_config_and_prefix(self):
        prepared,built,ro=self.component();self.put('stdout.jsonl',dict(fixture=True))
        valid=dict(ok=True,mutationVerified=True,prefixPreserved=True,configurationVerified=True,
            levelId=d.LEVEL,actionCode=21,receiptVersion=26,
            specSha256=prepared['normalizedSpecSha256'],rawSha256=d.digest(self.source/'stdout.jsonl'))
        decoder=self.route['mondstadt-combat']['componentFolder']/'native_acceptance.py'
        for key,value in ((None,None),('configurationVerified',False),('prefixPreserved',False),('rawSha256','0'*64),('actionCode',20)):
            result=dict(valid)
            if key: result[key]=value
            decoder.write_text('def validate_run(run):\n    return '+repr(result)+'\n',encoding='utf-8')
            prepared['sourceHashes'][decoder.relative_to(d.ROOT).as_posix()]=d.digest(decoder)
            if key:
                with self.assertRaises(ValueError): d.component_acceptance('mondstadt-combat',self.source,prepared)
            else:self.assertEqual(d.component_acceptance('mondstadt-combat',self.source,prepared),valid)


if __name__=='__main__': unittest.main()
