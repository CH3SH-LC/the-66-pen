"""Offline regression tests. No process discovery, hook, elevation or game access."""
from pathlib import Path
import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_profiles as profiles
import build_readonly_profile as builder

class NativeProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile=profiles.load_profile()

    def test_profile_edit_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'profile.json';v=copy.deepcopy(self.profile);v['layout']['GS_OWNER_CONTEXT_OFFSET']='0xb0';p.write_text(json.dumps(v))
            with self.assertRaisesRegex(profiles.ProfileError,'PROFILE_SOURCE_HASH_MISMATCH'):profiles.load_profile(p)

    def test_writes_never_accepted(self):
        for action in ('create','create-batch','save','delete','rename'):
            with self.subTest(action=action),self.assertRaisesRegex(profiles.ProfileError,'NATIVE_WRITES_NOT_VALIDATED'):
                profiles.require_action(self.profile,action)

    def test_session_recycled_identity_is_rejected(self):
        session={'schemaVersion':1,'pid':9,'tid':8,'window':7,'windowClass':'UnityWndClass','processCreation':6,'threadCreation':5,'image':'x'}
        for key in ('pid','tid','window','processCreation','threadCreation'):
            changed=dict(session);changed[key]+=1
            with self.subTest(key=key),patch.object(profiles,'query_identity',return_value=changed),self.assertRaisesRegex(profiles.ProfileError,'SESSION_CHANGED'):
                profiles.validate_session(session)

    def fake_pe(self):
        data=bytearray(4096);data[:2]=b'MZ';struct.pack_into('<I',data,60,0x80);pe=0x80;opt=pe+24
        data[pe:pe+4]=b'PE\0\0';struct.pack_into('<HHI',data,pe+4,0x8664,1,123);struct.pack_into('<H',data,pe+20,240)
        struct.pack_into('<H',data,opt,0x20b);struct.pack_into('<I',data,opt+56,8192)
        struct.pack_into('<IIII',data,opt+240+8,512,0x1000,512,512)
        p=copy.deepcopy(self.profile);p['image'].update(fileBytes=len(data),timestamp=123,sizeOfImage=8192)
        for i,name in enumerate(profiles.ANCHOR_NAMES):
            pos=512+i*64;b=bytes.fromhex(p['anchors'][name]['bytes']);data[pos:pos+32]=b;p['anchors'][name]['rva']=hex(0x1000+i*64)
        p['image']['sha256']=hashlib.sha256(data).hexdigest()
        return data,p

    def test_disk_hash_pe_and_anchors_independent(self):
        data,p=self.fake_pe()
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/'fake.exe';target.write_bytes(data);self.assertFalse(profiles.verify_disk(p,target)['allowWrites'])
            edited=bytearray(data);edited[1000]^=1;target.write_bytes(edited)
            with self.assertRaisesRegex(profiles.ProfileError,'GAME_SOURCE_HASH_MISMATCH'):profiles.verify_disk(p,target)
            edited=bytearray(data);edited[512]^=1;p2=copy.deepcopy(p);p2['image']['sha256']=hashlib.sha256(edited).hexdigest();target.write_bytes(edited)
            with self.assertRaisesRegex(profiles.ProfileError,'GAME_ANCHOR_MISMATCH:CONTEXT'):profiles.verify_disk(p2,target)
            edited=bytearray(data);struct.pack_into('<I',edited,0x80+8,999);target.write_bytes(edited)
            with self.assertRaisesRegex(profiles.ProfileError,'GAME_PE_MISMATCH:timestamp'):profiles.verify_disk(p,target)

    def test_malformed_pe_sections_refused(self):
        data,_=self.fake_pe();struct.pack_into('<H',data,0x80+6,65535)
        with self.assertRaisesRegex(profiles.ProfileError,'INVALID_PE_SECTIONS'):profiles.inspect_pe(data)

    def test_header_has_no_write_action(self):
        with tempfile.TemporaryDirectory() as t:
            run=Path(t);session={'pid':1,'tid':2,'processCreation':3,'threadCreation':4,'image':'fixture.invalid'}
            values=builder.emit_header(self.profile,session,run,deadline=0,message_id=0xc001,nonce=5)
            self.assertEqual(values['HR_ACTION'],0);self.assertEqual(values['HR_TARGET_THREAD_CREATION'],4)
            text=(run/'target_config.h').read_text();self.assertIn('#define GS_BOOTSTRAP_READONLY 1ULL',text)
            self.assertIn('#define GS_CONTEXT_VERSION_OFFSET 0x38ULL',text)
            self.assertIn('#define GS_PROFILE_STACK_RVAS 0xabaa78,0xac18fa',text)

    def fixture_receipt(self):
        decoder=builder.load_decoder();b=bytearray(decoder.SNAPSHOT_BYTES);base=0x140000000
        struct.pack_into('<4I',b,0,len(b),1,0,927)
        pointers=[base,0x20000,0x30000,0x40000,0x50000,0x60000,0x70000,0x80000,0x90000,0xa0000,0xb0000]
        struct.pack_into('<11Q',b,16,*pointers)
        counts=[self.profile['image']['timestamp'],self.profile['image']['sizeOfImage'],0,1,1,1,1,1,1,0,1000,30,2,4,4,0]
        struct.pack_into('<16I',b,104,*counts)
        struct.pack_into('<2Q',b,184,*(base+int(x,16) for x in self.profile['callbackStackRvas']))
        struct.pack_into('<QQQIIIIfffIQ',b,decoder.ENTITIES_OFFSET,0xc0000,0xd0000,0x80000,123,123,20001034,79,0,0,0,0,0)
        record={'ok':True,'transportOk':True,'snapshotStatus':0,'scope':'READ_ONLY_CONTEXT_RECEIPT',
            'selfTestOnly':False,'pid':9,'tid':8,'callbackCount':1,'activeCallbacks':0,'unhooked':True,
            'probeElevatedHigh':True,'snapshotBytes':len(b),'snapshotHex':b.hex()}
        prepared={'session':{'pid':9,'tid':8},'launchable':True,'compileOnly':False,'profileSha256':profiles.PROFILE_SHA256}
        return record,decoder.decode_snapshot(record),prepared

    def test_complete_readonly_receipt_remains_write_blocked(self):
        rec,snap,prep=self.fixture_receipt();v=builder.validate_receipt(rec,snap,prep,self.profile)
        self.assertTrue(v['ok']);self.assertFalse(v['allowWrites'])

    def test_transport_only_not_business_success(self):
        for field,value in [('ok',False),('transportOk',False),('snapshotStatus',9),('pid',10),('callbackCount',2),('unhooked',False)]:
            rec,snap,prep=self.fixture_receipt();rec[field]=value
            with self.subTest(field=field):self.assertFalse(builder.validate_receipt(rec,snap,prep,self.profile)['ok'])

    def test_incomplete_or_unverified_snapshot_rejected(self):
        for case in ('stack','hotfix','truncated','rejected','version','activeKey','owner'):
            rec,snap,prep=self.fixture_receipt()
            if case=='stack':snap['stack']=[]
            elif case=='hotfix':snap['flags']['value']&=~512
            elif case=='truncated':snap['flags']['value']|=32
            elif case=='rejected':snap['counts']['entityRejected']=1
            elif case=='version':snap['counts']['entityVersionAfter']=5
            elif case=='activeKey':snap['counts']['activeKey']=1
            else:snap['entities'][0]['flags']['value']&=~4
            with self.subTest(case=case):self.assertFalse(builder.validate_receipt(rec,snap,prep,self.profile)['ok'])

    def test_refused_snapshot_still_decodes(self):
        record,_,_=self.fixture_receipt();b=bytearray.fromhex(record['snapshotHex']);struct.pack_into('<I',b,8,10)
        record['snapshotHex']=b.hex();snapshot=builder.load_decoder().decode_snapshot(record)
        self.assertEqual(snapshot['status']['name'],'hotfix_active')

if __name__=='__main__':unittest.main(verbosity=2)
