"""Offline tests for backend/save_verification.py (T09).

Every fixture is built from real, already-recorded bytes -- the save run
``20260929-153705-save-fe06e18c`` and the two account backups that bracket it --
copied into an isolated per-run directory and then mutated.  Nothing here
touches the live game, the helper, the formal account, or any original
evidence file: sources are opened read-only, copies are written under
``.runtime/cordis-plan-work/DS-05-parallel-20261002/checks/tests/``.

Run with the project interpreter (no protobuf needed in *this* process -- the
content decoder is invoked as a subprocess on the protobuf-capable interpreter
the project records):

    .runtime/mcp-venv/Scripts/python.exe -B -m unittest backend.tests.test_save_verification
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _module_under_test():
    """Import the real module, or a mutated copy for the control runs.

    The mutation harness drops a mutated copy beside the real one (same
    directory depth, so ``ROOT`` still resolves to the project root) and points
    ``DS05_MODULE_UNDER_TEST`` at it.  Production never sets that variable.
    """
    override = os.environ.get('DS05_MODULE_UNDER_TEST')
    if not override:
        from backend import save_verification
        return save_verification
    spec = importlib.util.spec_from_file_location('ds05_mutant', override)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sv = _module_under_test()

WORK = ROOT / '.runtime/cordis-plan-work/DS-05-parallel-20261002'
FIXTURE_ROOT = WORK / 'checks/tests'

# --- read-only sources ------------------------------------------------------ #
RUN = ROOT / '.runtime/game-executor/scene-cli/20260929-153705-save-fe06e18c'
PRE = ROOT / '.runtime/editor-bridge/backups/20260929T073155Z-entitycreate-f87472fb-postcreate/files'
POST = ROOT / '.runtime/editor-bridge/backups/20260929T082011Z-mcp-mcpcreate1790669922/files'
RECEIPT = ROOT / ('.runtime/verification/entity-create-full-run/'
                  'f87472fb0a5cc2b77e1446124787e05d/save-reply.json')
OTHER_RECEIPT = ROOT / '.runtime/authoring/requests/11cd7ead44de274a8d608905f3561f3e/result.json'
GATE_DIR = ROOT / '.runtime/cordis-plan-work/G02'

LEVEL = 1073741839
PROTECTED = (1073741835, 1073741836, 1073741837, 1073741838)
ADDED_ID = 1077936132           # the entity this save persisted
WRONG_ID = 1077936999           # same varint width as ADDED_ID, not in the level
NON_TARGET_ID = 1077936129      # an entity that already existed before the save
REAL_REQUEST = 'ec1save1790667416'


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha_file(path) -> str:
    return sha256(pathlib.Path(path).read_bytes())


def load_gate():
    """The project's G02 gate module, imported for its byte walker only."""
    candidates = sorted(GATE_DIR.glob('*/checks/g02_savediff_gate.py'))
    if not candidates:
        raise unittest.SkipTest(f'no G02 gate under {GATE_DIR}')
    spec = importlib.util.spec_from_file_location('ds05_g02gate', candidates[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def walk(buf: bytes, gate):
    """Same walk as the gate's ``spans`` but keeping absolute byte offsets.

    Needed to mutate a copy in place; it walks with the gate's own varint
    reader so the mutation targets exactly what the gate will later re-read.
    """
    out, pos = [], 0
    while pos < len(buf):
        start = pos
        tag, pos = gate.varint(buf, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, pos = gate.varint(buf, pos)
            out.append((field, wire, value, start, pos))
        elif wire == 2:
            size, pos = gate.varint(buf, pos)
            out.append((field, wire, buf[pos:pos + size], start, pos + size))
            pos += size
        elif wire == 1:
            out.append((field, wire, buf[pos:pos + 8], start, pos + 8))
            pos += 8
        else:
            out.append((field, wire, buf[pos:pos + 4], start, pos + 4))
            pos += 4
    return out


def find_field(buf, gate, number, wire=2, occurrence=0):
    hits = [s for s in walk(buf, gate) if s[0] == number and s[1] == wire]
    return hits[occurrence]


def entity_id_varint_span(level_payload, gate, entity_id):
    """Absolute byte span of just the entity-id varint inside that entity's record.

    The span is the varint alone, not the enclosing tag: a same-width
    substitution must not move any other byte.
    """
    for field, wire, payload, s5, e5 in walk(level_payload, gate):
        if field != 5 or wire != 2:
            continue
        base = e5 - len(payload)          # absolute start of the field-5 payload
        for f2, w2, p2, s2, e2 in walk(payload, gate):
            if f2 != 1 or w2 != 2:
                continue
            inner = base + (e2 - len(p2))  # absolute start of the inner message
            for f3, w3, value, s3, e3 in walk(p2, gate):
                if f3 == 1 and w3 == 0 and value == entity_id:
                    width = len(varint_bytes(value))
                    return inner + e3 - width, inner + e3
    raise AssertionError(f'entity {entity_id} not found in root5')


def entity_record_span(level_payload, gate, entity_id):
    """Absolute byte span of one whole root5 record."""
    for field, wire, payload, s5, e5 in walk(level_payload, gate):
        if field != 5 or wire != 2:
            continue
        base = e5 - len(payload)
        for f2, w2, p2, s2, e2 in walk(payload, gate):
            if f2 != 1 or w2 != 2:
                continue
            for f3, w3, value, s3, e3 in walk(p2, gate):
                if f3 == 1 and w3 == 0 and value == entity_id:
                    return base + s2, base + e2
    raise AssertionError(f'entity {entity_id} not found in root5')


def varint_bytes(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


class Fixture:
    """One isolated copy of the real save case, with mutation helpers."""

    def __init__(self, root: pathlib.Path):
        self.root = root
        self.gate = load_gate()
        out = root
        out.mkdir(parents=True, exist_ok=True)
        self.files = {}

        def cp(src, name):
            dst = out / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            self.files[name] = dst
            return {'path': str(dst), 'sha256': sha_file(dst)}

        self.manifest = {
            'caseId': 't09-real-save',
            'runId': 'f87472fb0a5cc2b77e1446124787e05d',
            'operation': 'save',
            'levelId': LEVEL,
            'levelName': '自定义页签_3_存档_5',
            'requestId': REAL_REQUEST,
            'saveWallClock': 1790667431,
            'files': {
                'gilBefore': cp(RUN / f'before-{LEVEL}.gil', 'gilBefore.gil'),
                'gilAfter': cp(RUN / f'after-{LEVEL}.gil', 'gilAfter.gil'),
                'gipBefore': cp(PRE / 'Beyond_Local_Save_Player.gip', 'gipBefore.gip'),
                'gipAfter': cp(POST / 'Beyond_Local_Save_Player.gip', 'gipAfter.gip'),
            },
            'targetLevel': {
                'tempMirrorBefore': cp(PRE / f'Temp/{LEVEL}.gil', 'mirrorBefore.gil'),
                'tempMirrorAfter': cp(POST / f'Temp/{LEVEL}.gil', 'mirrorAfter.gil'),
            },
            'protectedLevels': {},
            'accountSet': {
                'before': cp(PRE.parent / 'manifest.json', 'accountBefore.json'),
                'after': cp(POST.parent / 'manifest.json', 'accountAfter.json'),
            },
            'receiptPath': cp(RECEIPT, 'receipt.json'),
            'intent': {'entityId': ADDED_ID, 'templateId': 20001034,
                       'name': '石质元素立方体',
                       'position': [-10.0, 0.0, -20.0], 'rotation': [0.0, 0.0, 0.0],
                       'scale': [1.25, 1.0, 1.0]},
            'entityDelta': {'addedIds': [ADDED_ID], 'removedIds': []},
            'declaredChangedRoots': [5, 6],
            'declaredChangedGipEntries': [],
        }
        for lvl in PROTECTED:
            self.manifest['protectedLevels'][str(lvl)] = {
                'gilBefore': cp(PRE / f'Beyond_Local_Save_Level/{lvl}/{lvl}.gil', f'p{lvl}-before.gil'),
                'gilAfter': cp(POST / f'Beyond_Local_Save_Level/{lvl}/{lvl}.gil', f'p{lvl}-after.gil'),
                'tempMirrorBefore': cp(PRE / f'Temp/{lvl}.gil', f'p{lvl}-mirrorBefore.gil'),
                'tempMirrorAfter': cp(POST / f'Temp/{lvl}.gil', f'p{lvl}-mirrorAfter.gil'),
            }

    def path(self, key):
        return pathlib.Path(self.manifest[key]['path'])

    def gil(self, which):
        return bytearray(pathlib.Path(self.manifest['files'][which]['path']).read_bytes())

    def write_gil(self, which, blob: bytes):
        p = self.manifest['files'][which]['path']
        pathlib.Path(p).write_bytes(bytes(blob))
        self.manifest['files'][which]['sha256'] = sha256(bytes(blob))
        return p

    def repin(self, key, path):
        """Point a manifest entry at a different file and re-pin its hash."""
        self.manifest[key] = {'path': str(path), 'sha256': sha_file(path)}


class SaveVerificationTest(unittest.TestCase):
    """Each test gets its own copy of the real case; nothing is shared."""

    maxDiff = None

    def setUp(self):
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='case-', dir=str(FIXTURE_ROOT)))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fx = Fixture(self.tmp)
        self.out_dir = self.tmp / 'gate'
        # The content decoder refuses to overwrite, and rightly so; a test run
        # owns nothing outside its own copies, so clear its own prior output.
        self.addCleanup(self._clear_content_output)
        self._clear_content_output()

    def _clear_content_output(self):
        m = self.fx.manifest
        out = (ROOT / sv.CONTENT_OUT_ROOT /
               f"{m['runId']}-{m['caseId']}" / 'DS-05')
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)

    def judge(self, **kwargs):
        kwargs.setdefault('out_dir', self.out_dir)
        return sv.verify_saved_case(self.fx.manifest, **kwargs)

    # ------------------------------------------------------------------ #
    # helpers for asserting a negative was actually judged negative
    # ------------------------------------------------------------------ #
    def assertStage(self, report, stage, expected):
        actual = report['stages'][stage]['status']
        self.assertEqual(actual, expected,
                         f'{stage} was {actual}, expected {expected}: ' +
                         json.dumps(report['stages'][stage], ensure_ascii=False)[:800])

    def finding(self, report, stage, finding_id):
        for f in report['stages'][stage]['findings']:
            if f['id'] == finding_id:
                return f
        raise AssertionError(f'{finding_id} not present in {stage}')

    # ------------------------------------------------------------------ #
    # the real case
    # ------------------------------------------------------------------ #
    def test_positive_real_save_is_blocked_by_root46_never_pass(self):
        """The honest verdict for a real save: three stages pass, root46 blocks it."""
        report = self.judge()
        self.assertStage(report, 'saveInvocation', sv.PASS)
        self.assertStage(report, 'savedContent', sv.PASS)
        self.assertStage(report, 'allowedDelta', sv.BLOCKED)
        self.assertStage(report, 'unrelatedUnchanged', sv.PASS)
        self.assertStage(report, 'saveDiff', sv.BLOCKED)
        self.assertFalse(report['ok'])
        self.assertEqual(report['exitCode'], 1)
        blocked = self.finding(report, 'allowedDelta', 'delta.noInheritedExemption')['detail']
        self.assertEqual([b['name'] for b in blocked['blocked']], ['root46-changed'])

    def test_root46_is_reported_named_not_ignored(self):
        """root46 must be named record-by-record, never skipped as a byte range."""
        report = self.judge()
        findings = {f['id']: f for f in
                    self.finding(report, 'allowedDelta', 'delta.gateFindings')['detail']}
        # the shape is checked and holds; it is the meaning, not the shape, that is unknown
        self.assertEqual(findings['root46.shape']['status'], 'pass')
        self.assertEqual(findings['root46.updatePattern']['status'], 'pass')
        self.assertEqual(findings['root46.arity']['status'], 'pass')
        self.assertEqual(findings['root46.shape']['detail']['before']['records'], 5)
        self.assertEqual(findings['root46.shape']['detail']['after']['records'], 5)
        # the update form is one of the accepted set; which one is a fact about the
        # bytes, so it is recorded rather than asserted to a single value
        self.assertIn(findings['root46.updatePattern']['detail'],
                      {'rewrite-head', 'prepend-and-evict-tail', 'grow-at-front',
                       'head-replaced (single-record list: the two candidate rules coincide here)',
                       'unchanged'})

    # ------------------------------------------------------------------ #
    # negative 1: same count, wrong ID
    # ------------------------------------------------------------------ #
    def test_negative_same_count_wrong_id(self):
        original = bytes(self.fx.gil('gilAfter'))
        blob = bytearray(original)
        payload_off = 20
        start, end = entity_id_varint_span(blob[payload_off:-4], self.fx.gate, ADDED_ID)
        old = bytes(blob[payload_off + start:payload_off + end])
        new = varint_bytes(WRONG_ID)
        self.assertEqual(len(old), len(new), 'the mutation must not change the byte length')
        blob[payload_off + start:payload_off + end] = new
        self.fx.write_gil('gilAfter', bytes(blob))
        # the same record count, the same file length: only the identity moved
        self.assertEqual(len(blob), len(original))
        self.assertEqual(len(walk(bytes(blob[payload_off:-4]), self.fx.gate)),
                         len(walk(original[payload_off:-4], self.fx.gate)))

        report = self.judge()
        self.assertStage(report, 'savedContent', sv.FAIL)
        self.assertNotEqual(report['stages']['saveDiff']['status'], sv.PASS)
        self.assertEqual(report['exitCode'], 1)
        delta = self.finding(report, 'allowedDelta', 'delta.gateVerdict')['detail']
        self.assertIn('gil.entitySetDelta', delta['defects'])

    # ------------------------------------------------------------------ #
    # negative 2: same length, different content
    # ------------------------------------------------------------------ #
    def test_negative_same_length_content_change(self):
        blob = self.fx.gil('gilAfter')
        before = bytes(blob)
        payload_off = 20
        start, end = entity_record_span(blob[payload_off:-4], self.fx.gate, NON_TARGET_ID)
        target = payload_off + end - 1              # the record's last byte
        blob[target] ^= 0x01                        # never bit 7: keeps varint length
        self.assertEqual(len(blob), len(before))
        self.fx.write_gil('gilAfter', bytes(blob))

        report = self.judge()
        self.assertStage(report, 'savedContent', sv.FAIL)
        self.assertEqual(report['exitCode'], 1)
        preserved = self.finding(report, 'savedContent', 'content.otherRecordsPreserved')
        self.assertEqual(preserved['status'], sv.FAIL)

    # ------------------------------------------------------------------ #
    # negative 3: an old request's receipt swapped in
    # ------------------------------------------------------------------ #
    def test_negative_old_request_receipt_swapped_in(self):
        self.assertTrue(OTHER_RECEIPT.is_file(), f'missing {OTHER_RECEIPT}')
        other = json.loads(OTHER_RECEIPT.read_text(encoding='utf-8'))
        self.assertNotEqual(other.get('requestId'), REAL_REQUEST)
        self.fx.repin('receiptPath', OTHER_RECEIPT)

        report = self.judge()
        self.assertStage(report, 'saveInvocation', sv.FAIL)
        self.assertEqual(report['exitCode'], 1)
        self.assertEqual(self.finding(report, 'saveInvocation', 'invocation.requestBound')['status'],
                         sv.FAIL)
        self.assertEqual(
            self.finding(report, 'saveInvocation', 'invocation.receiptHashesBound')['status'],
            sv.FAIL)

    def test_negative_old_snapshot_hashes_swapped_into_receipt(self):
        """Same requestId, but the receipt describes a different run's bytes."""
        receipt = json.loads((self.tmp / 'receipt.json').read_text(encoding='utf-8'))
        receipt['backend']['beforeGils'][str(LEVEL)]['sha256'] = 'de' * 32
        receipt['backend']['afterGils'][str(LEVEL)]['sha256'] = 'ad' * 32
        (self.tmp / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False),
                                               encoding='utf-8')
        self.fx.repin('receiptPath', self.tmp / 'receipt.json')

        report = self.judge()
        self.assertStage(report, 'saveInvocation', sv.FAIL)
        self.assertEqual(self.finding(report, 'saveInvocation', 'invocation.requestBound')['status'],
                         sv.PASS)
        self.assertEqual(
            self.finding(report, 'saveInvocation', 'invocation.receiptHashesBound')['status'],
            sv.FAIL)

    # ------------------------------------------------------------------ #
    # negative 4: a non-target file changed
    # ------------------------------------------------------------------ #
    def test_negative_protected_level_changed(self):
        victim = self.fx.manifest['protectedLevels']['1073741838']['gilAfter']['path']
        blob = bytearray(pathlib.Path(victim).read_bytes())
        blob[-1] ^= 0x01
        pathlib.Path(victim).write_bytes(bytes(blob))

        report = self.judge()
        self.assertStage(report, 'unrelatedUnchanged', sv.FAIL)
        self.assertEqual(report['exitCode'], 1)
        self.assertEqual(
            self.finding(report, 'unrelatedUnchanged', 'unrelated.protectedLevels')['status'],
            sv.FAIL)

    def test_negative_fifth_account_file_changed(self):
        manifest = json.loads((self.tmp / 'accountAfter.json').read_text(encoding='utf-8'))
        victim = next(f for f in manifest['files'] if f['relpath'].startswith('Beyond_Debug_Log/'))
        victim['sha256'] = 'be' * 32
        (self.tmp / 'accountAfter.json').write_text(json.dumps(manifest, ensure_ascii=False),
                                                    encoding='utf-8')
        self.fx.manifest['accountSet']['after']['sha256'] = sha_file(self.tmp / 'accountAfter.json')

        report = self.judge()
        self.assertStage(report, 'unrelatedUnchanged', sv.FAIL)
        changed = self.finding(report, 'unrelatedUnchanged', 'unrelated.accountChangedSet')
        self.assertEqual(changed['status'], sv.FAIL)
        self.assertTrue(changed['detail']['neverChangePrefixesHit'])

    # ------------------------------------------------------------------ #
    # negative 5: root46 shape broken is a defect, not an unknown
    # ------------------------------------------------------------------ #
    def test_negative_root46_shape_violation_is_fail_not_blocked(self):
        original = bytes(self.fx.gil('gilAfter'))
        blob = bytearray(original)
        payload_off = 20
        field, wire, payload, start, end = find_field(blob[payload_off:-4], self.fx.gate, 46)
        payload_start = payload_off + end - len(payload)   # past the tag and the length
        blob[payload_start] = 0x0B                         # a record no longer starts with 0x0a
        self.assertEqual(len(blob), len(original))
        self.fx.write_gil('gilAfter', bytes(blob))

        report = self.judge()
        # shape is checked, so a broken record is a contradiction, not an unknown
        self.assertStage(report, 'allowedDelta', sv.FAIL)
        delta = self.finding(report, 'allowedDelta', 'delta.gateVerdict')['detail']
        self.assertIn('root46.shape', delta['defects'])

    # ------------------------------------------------------------------ #
    # negative 6: an unstable source cannot be judged
    # ------------------------------------------------------------------ #
    def test_negative_unstable_snapshot_cannot_be_judged(self):
        victim = str(self.fx.manifest['files']['gilAfter']['path'])
        state = {'n': 0}

        def reader(path):
            if str(path) == victim:
                state['n'] += 1
                return b'A' * 10 if state['n'] % 2 else b'B' * 10
            return pathlib.Path(path).read_bytes()

        report = self.judge(reader=reader)
        self.assertStage(report, 'savedContent', sv.INSUFFICIENT)
        self.assertEqual(report['exitCode'], 2)
        self.assertNotEqual(report['stages']['saveDiff']['status'], sv.PASS)

    def test_negative_unstable_protected_snapshot_is_insufficient(self):
        """A protected file that does not hold still is unjudged, not 'changed'."""
        victim = str(self.fx.manifest['protectedLevels']['1073741838']['gilAfter']['path'])
        state = {'n': 0}

        def reader(path):
            if str(path) == victim:
                state['n'] += 1
                return b'A' * 10 if state['n'] % 2 else b'B' * 10
            return pathlib.Path(path).read_bytes()

        report = self.judge(reader=reader)
        self.assertStage(report, 'unrelatedUnchanged', sv.INSUFFICIENT)
        self.assertEqual(report['exitCode'], 2)
        unreadable = self.finding(report, 'unrelatedUnchanged',
                                  'unrelated.protectedLevelsReadable')
        self.assertEqual(unreadable['detail']['unreadable'], ['1073741838'])

    # ------------------------------------------------------------------ #
    # negative 7: the target Temp mirror desynchronised
    # ------------------------------------------------------------------ #
    def test_negative_target_mirror_desync(self):
        original = bytes(self.fx.gil('gilAfter'))
        mirror = self.fx.manifest['targetLevel']['tempMirrorAfter']['path']
        mutated = bytearray(original)
        mutated[-2] ^= 0x01
        pathlib.Path(mirror).write_bytes(bytes(mutated))
        self.fx.manifest['targetLevel']['tempMirrorAfter']['sha256'] = sha256(bytes(mutated))

        report = self.judge()
        self.assertStage(report, 'allowedDelta', sv.FAIL)
        delta = self.finding(report, 'allowedDelta', 'delta.gateVerdict')['detail']
        self.assertIn('targetTempMirror.equalsFormalAfter', delta['defects'])

    # ------------------------------------------------------------------ #
    # integrity controls on the evidence itself
    # ------------------------------------------------------------------ #
    def test_negative_receipt_replayed_is_blocked_not_pass(self):
        receipt = json.loads((self.tmp / 'receipt.json').read_text(encoding='utf-8'))
        receipt['replayed'] = True
        (self.tmp / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False),
                                               encoding='utf-8')
        self.fx.repin('receiptPath', self.tmp / 'receipt.json')
        report = self.judge()
        self.assertStage(report, 'saveInvocation', sv.BLOCKED)
        self.assertNotEqual(report['stages']['saveDiff']['status'], sv.PASS)

    def test_negative_gate_hash_not_pinned_matching(self):
        self.fx.manifest['g02Gate'] = {'sha256': 'ab' * 32}
        report = self.judge()
        self.assertStage(report, 'allowedDelta', sv.INSUFFICIENT)
        self.assertEqual(report['exitCode'], 2)

    def test_negative_manifest_file_hash_mismatch(self):
        self.fx.manifest['files']['gilBefore']['sha256'] = 'cd' * 32
        report = self.judge()
        self.assertStage(report, 'savedContent', sv.INSUFFICIENT)
        self.assertNotEqual(report['stages']['saveDiff']['status'], sv.PASS)

    def test_negative_live_account_path_is_refused(self):
        live = pathlib.Path.home() / 'AppData/LocalLow/miHoYo/x/BeyondLocal/y/1073741839.gil'
        self.fx.manifest['files']['gilAfter'] = {'path': str(live), 'sha256': 'ef' * 32}
        report = self.judge()
        self.assertStage(report, 'allowedDelta', sv.INSUFFICIENT)
        self.assertEqual(report['exitCode'], 2)
        # the refusal must be the ownership rule, not a coincidental read error
        detail = self.finding(report, 'savedContent', 'content.snapshotStable')['detail']
        self.assertIn('live game save directory', detail)

    def test_live_account_detection_is_the_path_not_the_contents(self):
        live = pathlib.Path.home() / 'AppData/LocalLow/miHoYo/x/BeyondLocal/y/z.gil'
        self.assertTrue(sv._is_inside_live_account(live))
        self.assertTrue(sv._is_inside_live_account(pathlib.Path('C:/anywhere/BeyondLocal/z.gil')))
        self.assertFalse(sv._is_inside_live_account(ROOT / 'backend/save_verification.py'))

    def test_fold_of_nothing_is_insufficient(self):
        """An empty check list must never fold to success."""
        self.assertEqual(sv._fold([]), sv.INSUFFICIENT)
        self.assertEqual(sv._fold([sv.PASS]), sv.PASS)
        self.assertEqual(sv._fold([sv.PASS, sv.PASS]), sv.PASS)
        # a contradiction outranks an unknown, which outranks a named blocked delta
        self.assertEqual(sv._fold([sv.BLOCKED, sv.INSUFFICIENT, sv.FAIL]), sv.FAIL)
        self.assertEqual(sv._fold([sv.BLOCKED, sv.INSUFFICIENT]), sv.INSUFFICIENT)
        self.assertEqual(sv._fold([sv.BLOCKED, sv.PASS]), sv.BLOCKED)

    def test_empty_manifest_is_insufficient_not_pass(self):
        report = sv.verify_saved_case({}, out_dir=self.out_dir)
        self.assertEqual(report['stages']['saveDiff']['status'], sv.INSUFFICIENT)
        self.assertFalse(report['ok'])
        self.assertEqual(report['exitCode'], 2)

    def test_verdict_follows_the_bytes_and_is_not_inherited(self):
        """Reverting root46 to its before value must move blocked -> pass.

        This is the module's version of the G02 P1 control: the same pair of
        files, with only field 46 reverted, has to change verdict.  If the
        verdict were inherited from the previous run instead of recomputed,
        this would keep reporting blocked.
        """
        blocked = self.judge()
        self.assertStage(blocked, 'allowedDelta', sv.BLOCKED)

        # a second, independent copy of the same case whose after-side root46 is
        # the before-side one
        other = pathlib.Path(tempfile.mkdtemp(prefix='revert-', dir=str(FIXTURE_ROOT)))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        fx = Fixture(other)
        fx.manifest['caseId'] = f't09-reverted-root46-{other.name}'
        self.addCleanup(shutil.rmtree,
                        ROOT / sv.CONTENT_OUT_ROOT /
                        f"{fx.manifest['runId']}-{fx.manifest['caseId']}", ignore_errors=True)
        after = bytes(fx.gil('gilAfter'))
        before = bytes(fx.gil('gilBefore'))
        off = 20
        a_raw = find_field(after[off:-4], fx.gate, 46)
        b_raw = find_field(before[off:-4], fx.gate, 46)
        a_start, a_end = off + a_raw[3], off + a_raw[4]
        b_start, b_end = off + b_raw[3], off + b_raw[4]
        payload = after[off:-4]
        payload = payload[:a_start - off] + before[b_start:b_end] + payload[a_end - off:]
        header = bytearray(after[:20])
        inner = len(payload)
        header[0:4] = (20 + inner).to_bytes(4, 'big')
        header[16:20] = inner.to_bytes(4, 'big')
        rebuilt = bytes(header) + payload + after[-4:]
        fx.write_gil('gilAfter', rebuilt)
        # the mirror rule (G4) is part of the contract, so the mirror must move too
        mirror = fx.manifest['targetLevel']['tempMirrorAfter']['path']
        pathlib.Path(mirror).write_bytes(rebuilt)
        fx.manifest['targetLevel']['tempMirrorAfter']['sha256'] = sha256(rebuilt)

        reverted = sv.verify_saved_case(fx.manifest, out_dir=other / 'gate')
        self.assertStage(reverted, 'allowedDelta', sv.PASS)
        self.assertNotEqual(blocked['stages']['allowedDelta']['status'],
                            reverted['stages']['allowedDelta']['status'])


class CliTest(unittest.TestCase):
    """The CLI contract: exit codes, refusal to overwrite, and --dry-run."""

    def setUp(self):
        FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='cli-', dir=str(FIXTURE_ROOT)))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fx = Fixture(self.tmp)
        out = ROOT / sv.CONTENT_OUT_ROOT / f"{self.fx.manifest['runId']}-{self.fx.manifest['caseId']}"
        shutil.rmtree(out, ignore_errors=True)
        self.manifest_path = self.tmp / 'manifest.json'
        self.manifest_path.write_text(json.dumps(self.fx.manifest, ensure_ascii=False),
                                      encoding='utf-8')

    def test_cli_exit_code_and_no_overwrite(self):
        out = self.tmp / 'report.json'
        code = sv.main(['--case-manifest', str(self.manifest_path), '--output', str(out)])
        self.assertEqual(code, 1)
        self.assertTrue(out.is_file())
        with self.assertRaises(SystemExit):
            sv.main(['--case-manifest', str(self.manifest_path), '--output', str(out)])

    def test_cli_dry_run_writes_nothing(self):
        out = self.tmp / 'never.json'
        code = sv.main(['--case-manifest', str(self.manifest_path), '--output', str(out),
                        '--dry-run'])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
