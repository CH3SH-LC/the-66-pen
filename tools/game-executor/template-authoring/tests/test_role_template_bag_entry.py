"""New role-template entry: pure synthetic receipts; no probe is launched."""
import copy
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE / 'tests'))
import accept_role_template_bag as accept
import build_role_template_bag_candidate as candidate
import role_template_bag_review as reviews
import prepare_role_template_bag as prepare
import test_accept_binding as old_fixture
from test_currency_receipt import encode as catalog_hex


def owner_bytes(scene_owner, prefab_owner, classes):
    raw = bytearray(accept.OWNER_BYTES)
    role = 1090519041
    struct.pack_into('<4I9Q', raw, 0, 0, role, role, 0, scene_owner,
        prefab_owner, classes[8], 0x61000, 0x62000, 0x63000, 0x64000, 17, 17)
    struct.pack_into('<Q', raw, 88, 0x65000)
    struct.pack_into('<2Q', raw, 88+0x20, 0x63000, 0x64000)
    struct.pack_into('<I', raw, 88+0x38, 1)
    for offset, klass in ((160, classes[8]), (352, classes[7])):
        struct.pack_into('<Q', raw, offset, klass)
        struct.pack_into('<I', raw, offset+0x1c, role)
    struct.pack_into('<I', raw, 160+0xb8, 1000001)
    struct.pack_into('<Q', raw, 352+0xb8, prefab_owner)
    struct.pack_into('<iI', raw, 544, 1, 1)
    struct.pack_into('<iiI4xQ', raw, 1576, role & 0x7fffffff, -1, role, prefab_owner)
    return raw


class RoleTemplateEntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This existing fixture mocks compilation and Windows identity APIs.
        # It gives a complete positive catalogue/components/transaction raw basis.
        cls.old = old_fixture.AcceptBindingTests(); cls.old.setUp()
        cls.addClassCleanup(cls.old.doCleanups)

    def setUp(self):
        old = self.old
        self.classes = (*old.classes, 0x29000)
        self.raw = bytearray(accept.RECEIPT_BYTES)
        self.raw[:104] = old.raw[:104]
        struct.pack_into('<Q', self.raw, 104, self.classes[8])
        self.raw[112:988072] = old.raw[104:]
        struct.pack_into('<2I', self.raw, 0, accept.RECEIPT_BYTES, 1)
        struct.pack_into('<2I', self.raw, 28, 20, 20)
        a = accept.ACTION_AT
        self.prefab_owner = 0x35000
        struct.pack_into('<2I', self.raw, a+8, 1090519041, 1119879169)
        struct.pack_into('<Q', self.raw, a+24, self.prefab_owner)
        struct.pack_into('<Qi', self.raw, a+56, 0, 0)
        struct.pack_into('<Qi', self.raw, a+104, self.classes[0], 33)
        struct.pack_into('<Qi', self.raw, a+152, 0, 0)
        self.raw[a+166] = self.raw[a+167] = 0
        struct.pack_into('<Q', self.raw, accept.EDIT_AT+48, self.prefab_owner)
        struct.pack_into('<i', self.raw, accept.EDIT_AT+72, 33)
        cat = bytearray.fromhex(catalog_hex([(1119879169, 12, 0x34000, self.classes[3])], [], level=1073741842))
        struct.pack_into('<Q', cat, 16, old.global_pointer)
        for at in (accept.BEFORE_CATALOG_AT, accept.AFTER_CATALOG_AT):
            self.raw[at:at+len(cat)] = cat
        for at in (accept.BEFORE_COMPONENTS_AT, accept.AFTER_ATTACH_AT, accept.FINAL_COMPONENTS_AT):
            struct.pack_into('<2Q', self.raw, at+24, self.prefab_owner, self.classes[8])
            if at != accept.BEFORE_COMPONENTS_AT:
                struct.pack_into('<Qi', self.raw, at+1136+40+24, self.classes[0], 33)
                struct.pack_into('<i', self.raw, at+116, 33)
        struct.pack_into('<2Q2Ii', self.raw, accept.AFTER_BINDING_AT, 0x33000, 0, 1119879169, 0, 0)
        for at in (accept.BEFORE_OWNER_AT, accept.AFTER_OWNER_AT):
            self.raw[at:at+accept.OWNER_BYTES] = owner_bytes(old.owner, self.prefab_owner, self.classes)
        self.raw[accept.FINAL_EDIT_AT:accept.FINAL_EDIT_AT+accept.STATE_BYTES] = self.raw[accept.EDIT_AT+37328:accept.EDIT_AT+37328+accept.STATE_BYTES]
        self.current = copy.deepcopy(old.scene)
        self.current['entities'][0]['id'] = 1090519041
        self.request = reviews.make_request(run_id='fixture', level_id=1073741842,
            session=old.data.session, parameters={'sceneEntityId':1090519041,
                'rolePrefabId':1090519041, 'bagId':1119879169})

    def verified(self):
        raw = bytes(self.raw)
        return accept.verify_binding(raw, accept.decode_raw(raw), request=self.request, current=self.current)

    def test_complete_raw_template_binding(self):
        result = self.verified()
        self.assertTrue(result['bindingVerified'] and result['roleOwnerVerified'] and result['editTransactionClosed'])
        self.assertEqual(result['roleOwner'], self.prefab_owner)
        self.assertNotEqual(result['roleOwner'], result['sceneOwner'])

    def test_wrong_template_domain_and_scene_source_are_rejected(self):
        for offset in (accept.BEFORE_OWNER_AT+160, accept.BEFORE_OWNER_AT+352+0xb8):
            original = bytes(self.raw[offset:offset+8])
            struct.pack_into('<Q', self.raw, offset, 0x99000)
            with self.assertRaisesRegex(ValueError, 'ROLE_PREFAB_PREFIX'): self.verified()
            self.raw[offset:offset+8] = original

    def test_dictionary_link_and_dirty_record_are_verified(self):
        struct.pack_into('<i', self.raw, accept.AFTER_OWNER_AT+1576+4, 0)
        with self.assertRaisesRegex(ValueError, 'ROLE_CHAIN_LINK'): self.verified()
        struct.pack_into('<i', self.raw, accept.AFTER_OWNER_AT+1576+4, -1)
        self.raw[accept.EDIT_AT+24912+128+40] = 0
        with self.assertRaises(ValueError): self.verified()

    def test_other_prefix_cache_bytes_may_change(self):
        self.raw[accept.AFTER_OWNER_AT+160+0x50] ^= 1
        self.assertTrue(self.verified()['bindingVerified'])

    def test_fixed_request_rejects_other_ids_and_extra_fields(self):
        for key in self.request['parameters']:
            bad = copy.deepcopy(self.request); bad['parameters'][key] += 1
            with self.assertRaisesRegex(ValueError, 'FIXED_IDS'): reviews.validate_request(bad)
        bad = copy.deepcopy(self.request); bad['parameters']['owner'] = 0x35000
        with self.assertRaisesRegex(ValueError, 'CLOSED_SCHEMA'): reviews.validate_request(bad)

    def test_compiled_header_and_private_scope(self):
        root = candidate.ROOT / '.runtime/scratch/overnight-features-20261013/task-role-template-bag/peer'
        with tempfile.TemporaryDirectory(dir=root) as path:
            run = Path(path)
            runtime = candidate.read_runtime()
            candidate.emit_header(run, self.request, bytes(33208), runtime, candidate.profiles.load_profile())
            session = dict(self.request['session'], pid=1, tid=1, processCreation=1, threadCreation=1,
                           image=str(run/'compile-only-target.invalid'))
            accept.header_binding(run/'target_config.h', dict(session=session, nonce=1, deadline=1, messageId=49153), bytes(33208))
            review = dict(runtimeProfilePath=str(candidate.DEFAULT_RUNTIME_PROFILE), runtimeProfileSha256=candidate.ROLE_PROFILE_SHA256)
            accept.runtime_profile(review, {'inputs':review}, run/'target_config.h', self.request)
            candidate.source_copies(run)
            probe = (run/'candidate-source/native/hook_receipt_probe.cpp').read_text()
            self.assertIn('FIXED_ROLE_TEMPLATE_BAG_ACTION', probe)
            self.assertIn('roleTemplateBagResult', probe)
            self.assertIn('finalEditAfter.count == 0', probe)
            self.assertEqual(prepare.TTL_SECONDS, 600)


if __name__ == '__main__': unittest.main()
