import hashlib,json,struct,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
HERE=Path(__file__).resolve().parents[1];ROOT=HERE.parents[1];sys.path.insert(0,str(HERE))
import shop_contract as c
import shop_build as b
import shop_receipt as receipt
import test_inventory as inventory

CONFIG=1107296258
def args(action=None,**kw):
    value=dict(operation='shop-ui' if action else 'shop-state',ui_action=action,ui_id='once' if action else None,ui_row=0 if action in ('goods','bag-item') else None,config_id=CONFIG if action and action!='back' else None,label=('10' if action=='goods' else '苹果') if action else None,ui_baseline=None)
    value.update(kw);return SimpleNamespace(**value)

def ui_bytes(kind=1,quantity=1):
    d=bytearray(c.UI_SIZE);v={k:0 for k in c.POINTERS+c.NUMBERS};v.update(context=0x1000,view=0x2000,page=0x3000,shopModule=0x4000,bagModule=0x5000,kind=kind,ownerId=88,shopId=9,generation=23,complete=1,backReady=1)
    if kind in (2,3,4):v.update(key=(CONFIG<<32)|12,quantity=quantity,maximum=5,confirmReady=1,sliderReady=1,sellReady=1,item=0x90000,instanceId=100)
    v['textLength']=2 if kind in (2,3,4) else 0;v['rowCount']=2 if kind==1 else 0
    struct.pack_into('<11Q18I',d,0,*(v[k] for k in c.POINTERS+c.NUMBERS));d[160:160+v['textLength']*2]='苹果'.encode('utf-16-le') if v['textLength'] else b''
    if kind==1:
        for i,label in enumerate(('10','苹果')):
            at=416+i*c.ROW_SIZE;struct.pack_into('<5Q10I',d,at,0x10000+i*0x1000,0x20000+i*0x1000,0x90000 if i else 0,(CONFIG<<32)|12,0x30000+i*0x1000,i+1,0,100 if i else 0,25 if not i else 0,0,1,1,1,2,0);d[at+80:at+84]=label.encode('utf-16-le')
    return d

def raw(kind=1,quantity=1,action=None):
    d=bytearray(c.SIZE);h={k:0 for k in c.HEADER};h.update(bytes=c.SIZE,version=6,stage=3,operation=16 if action else 15,resourcesReleased=1,uiStable=1,afterReadable=1,action=c.ACTIONS.get(action,0),actionAttempted=int(bool(action)),actionReturned=int(bool(action)))
    nested=inventory.raw();owner=inventory.c.parse(nested);struct.pack_into('<16I4Q',d,0,*(h[k] for k in c.HEADER),owner['avatar'],owner['bag'],0x111 if action else 0,0x222 if action else 0);d[96:c.UI_OFFSET]=nested
    for i in range(3):d[c.UI_OFFSET+i*c.UI_SIZE:c.UI_OFFSET+(i+1)*c.UI_SIZE]=ui_bytes(kind,quantity)
    return d

def card(action=None,kind=1,quantity=1):
    p=inventory.card();a=args(action,ui_row=1 if action=='bag-item' else 0 if action=='goods' else None,label='' if action=='back' and kind==1 else ('10' if action=='goods' else '苹果') if action else None);p.update(mode='shop-ui' if action else 'shop-state',uiPlan=c.plan(a),uiBinding={})
    if action:
        v=c.parse(raw(kind,quantity,action));p['uiBinding']=dict(avatar=v['avatar'],bag=v['bag'],uiBytesHex=v['uiBeforeBytesHex'])
    return p
def header(d,**changes):
    for k,v in changes.items():struct.pack_into('<I',d,c.HEADER.index(k)*4,v)
def ui_change(d,key,value,samples=(0,1,2)):
    index=(c.POINTERS+c.NUMBERS).index(key);fmt,off=('Q',index*8) if index<11 else ('I',88+(index-11)*4)
    for sample in samples:struct.pack_into('<'+fmt,d,c.UI_OFFSET+sample*c.UI_SIZE+off,value)

class PlanTests(unittest.TestCase):
    def test_readonly(self):self.assertIsNone(c.plan(args())['action'])
    def test_all_bounded_actions(self):
        for action in c.ACTIONS:self.assertEqual(c.plan(args(action))['action'],action)
    def test_unknown_action(self):
        with self.assertRaisesRegex(ValueError,'SHOP_ACTION'):c.plan(args('execute'))
    def test_state_cannot_carry_action(self):
        with self.assertRaisesRegex(ValueError,'NO_ACTION'):c.plan(args(label='x'))
    def test_no_arbitrary_id(self):
        for identifier in ('../x','x'*65,'',None):
            with self.assertRaisesRegex(ValueError,'ACTION_ID'):c.plan(args('buy',ui_id=identifier))
    def test_label_required(self):
        with self.assertRaisesRegex(ValueError,'LABEL'):c.plan(args('buy',label=None))
    def test_label_bound_utf16(self):
        for value in ('x\0y','字'*128,'🍎'*64):
            with self.assertRaisesRegex(ValueError,'LABEL'):c.plan(args('buy',label=value))
    def test_row_bound(self):
        for value in (-1,128,True,None):
            with self.assertRaisesRegex(ValueError,'ROW'):c.plan(args('goods',ui_row=value))
    def test_confirm_not_row(self):
        with self.assertRaisesRegex(ValueError,'ROW'):c.plan(args('buy',ui_row=0))
    def test_config_bound(self):
        for value in (0,2**32,True,None):
            with self.assertRaisesRegex(ValueError,'CONFIG'):c.plan(args('buy',config_id=value))
    def test_back_not_config(self):
        with self.assertRaisesRegex(ValueError,'BACK_CONFIG'):c.plan(args('back',config_id=CONFIG))

class BinaryTests(unittest.TestCase):
    def refuse(self,f,pattern):
        d=raw();f(d)
        with self.assertRaisesRegex(ValueError,pattern):c.parse(d)
    def test_raw_current_ui(self):
        p=c.parse(raw());self.assertEqual(p['before']['rows'][0]['labelRole'],'visible-price-text');self.assertEqual(p['before']['rows'][1]['text'],'苹果')
    def test_size(self):
        with self.assertRaisesRegex(ValueError,'SIZE'):c.parse(bytes(20))
    def test_version(self):self.refuse(lambda d:header(d,version=5),'VERSION')
    def test_operation(self):self.refuse(lambda d:header(d,operation=14),'VERSION')
    def test_reserved(self):self.refuse(lambda d:header(d,reserved0=1),'HEADER')
    def test_unknown_kind(self):self.refuse(lambda d:ui_change(d,'kind',9),'HEADER')
    def test_row_limit(self):self.refuse(lambda d:ui_change(d,'rowCount',129),'HEADER')
    def test_flag(self):self.refuse(lambda d:ui_change(d,'complete',2),'FLAGS')
    def test_text_bounds(self):self.refuse(lambda d:ui_change(d,'textLength',128),'TEXT_BOUNDS')
    def test_unused_rows(self):self.refuse(lambda d:d.__setitem__(-1,1),'UNUSED_ROWS')
    def test_duplicate_rows(self):
        def f(d):
            for sample in range(3):struct.pack_into('<I',d,c.UI_OFFSET+sample*c.UI_SIZE+416+c.ROW_SIZE+40,1)
        self.refuse(f,'DUPLICATE_ROW')
    def test_incomplete_not_complete(self):self.refuse(lambda d:ui_change(d,'status',1),'COMPLETE_IDENTITY')
    def test_owner_pointer(self):self.refuse(lambda d:struct.pack_into('<Q',d,64,999),'OWNER_BINDING')
    def test_changed_second_snapshot(self):self.refuse(lambda d:ui_change(d,'shopId',10,(1,)),'STABILITY')
    def test_readonly_not_click(self):self.refuse(lambda d:header(d,actionAttempted=1),'OBSERVATION_WROTE')
    def test_return_before_attempt(self):self.refuse(lambda d:header(d,actionReturned=1),'ACTION_ORDER')
    def test_no_gameplay_promotion(self):
        r=c.interpretation(c.parse(raw()),card());self.assertFalse(r['transactionVerified']);self.assertFalse(r['inventoryEffectVerified']);self.assertTrue(r['readOnly']);self.assertTrue(r['trialIdentityBound'])
    def test_main_hud_is_observation_only(self):
        d=ui_bytes(5);struct.pack_into('<I',d,88+12*4,0);s=c.ui(d)
        with self.assertRaisesRegex(ValueError,'BACK_UNAVAILABLE'):c.validate_selection(s,c.plan(args('back',label='')))
    def test_unknown_early_refusal(self):
        d=bytearray(c.SIZE);struct.pack_into('<8I',d,0,c.SIZE,6,1,0,1,15,0,1);p=c.parse(d);self.assertIsNone(p['inventory']);self.assertEqual(p['before']['screen'],'unknown')

class SelectionTests(unittest.TestCase):
    def test_all_current_selection_types(self):
        for a,k in [('goods',1),('bag-item',1),('quantity-one',2),('buy',2),('sell-open',3),('sell',4),('back',1)]:c.validate_selection(c.ui(ui_bytes(k)),card(a,k)['uiPlan'])
    def test_sale_quantity_slider(self):c.validate_selection(c.ui(ui_bytes(4,3)),card('quantity-one',4,3)['uiPlan'])
    def test_current_label_required(self):
        p=card('goods')['uiPlan'];p['label']='苹果'
        with self.assertRaisesRegex(ValueError,'ROW_CHANGED'):c.validate_selection(c.ui(ui_bytes()),p)
    def test_current_config_required(self):
        p=card('buy',2)['uiPlan'];p['configId']+=1
        with self.assertRaisesRegex(ValueError,'CONFIG_CHANGED'):c.validate_selection(c.ui(ui_bytes(2)),p)
    def test_quantity_two_not_buy(self):
        with self.assertRaisesRegex(ValueError,'QUANTITY_ONE'):c.validate_selection(c.ui(ui_bytes(2,2)),card('buy',2)['uiPlan'])
    def test_quantity_two_not_sell(self):
        with self.assertRaisesRegex(ValueError,'QUANTITY_ONE'):c.validate_selection(c.ui(ui_bytes(4,2)),card('sell',4)['uiPlan'])
    def test_wrong_screen(self):
        with self.assertRaisesRegex(ValueError,'QUANTITY_ONE'):c.validate_selection(c.ui(ui_bytes(3)),card('buy',2)['uiPlan'])
    def test_handler_changed(self):
        s=c.ui(ui_bytes());s['rows'][0]['handlerVerified']=0
        with self.assertRaisesRegex(ValueError,'ROW_CHANGED'):c.validate_selection(s,card('goods')['uiPlan'])
    def test_no_current_visible_row(self):
        p=card('goods')['uiPlan'];p['row']=2
        with self.assertRaisesRegex(ValueError,'NOT_VISIBLE'):c.validate_selection(c.ui(ui_bytes()),p)
    def test_click_not_transaction(self):
        d=raw(2,1,'buy');ui_change(d,'context',0x6000,(2,));r=c.interpretation(c.parse(d),card('buy',2));self.assertTrue(r['uiTransitionObserved']);self.assertFalse(r['transactionVerified']);self.assertFalse(r['inventoryEffectVerified'])
    def test_no_transition_does_not_invent_completion(self):self.assertFalse(c.interpretation(c.parse(raw(2,1,'buy')),card('buy',2))['uiTransitionObserved'])
    def test_baseline_bytes_must_match(self):
        p=card('buy',2);p['uiBinding']['uiBytesHex']='00'*c.UI_SIZE
        with self.assertRaisesRegex(ValueError,'BASELINE_BINDING'):c.interpretation(c.parse(raw(2,1,'buy')),p)
    def test_action_kind_must_match(self):
        with self.assertRaisesRegex(ValueError,'NOT_RETURNED'):c.interpretation(c.parse(raw(2,1,'back')),card('buy',2))

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';base.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=base);self.run=Path(self.temp.name);self.data=raw();self.card=card();self.card.update(session=dict(pid=123,tid=456),nonce='99',deadlineTick=999);self.exit=dict(scope='FIXED_PLAYTEST_SHOP',executed=True,exitCode=0,error=None)
    def tearDown(self):self.temp.cleanup()
    def decode(self,**changes):
        r=dict(scope='FIXED_PLAYTEST_SHOP',selfTestOnly=False,pid=123,tid=456,receiptNonce='99',receiptDeadline='999',receiptProtocol=24,evidenceWritten=True,acceptanceBytes=c.SIZE,acceptanceHeaderHex=self.data[:96].hex(),acceptanceSha256=hashlib.sha256(self.data).hexdigest(),callbackCount=1,activeCallbacks=0,unhooked=True,transportOk=True,probeElevatedHigh=True,ok=True);r.update(changes)
        for name,value in [('exit.json',self.exit),('stdout.jsonl',r)]:(self.run/name).write_text(json.dumps(value),encoding='utf-8')
        (self.run/'acceptance.bin').write_bytes(self.data);return receipt.decode_bound(self.run,self.card)
    def test_bound_success(self):self.assertTrue(self.decode()['ok'])
    def test_nonce(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptNonce='100')
    def test_deadline(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptDeadline='100')
    def test_protocol(self):
        with self.assertRaisesRegex(ValueError,'CARD_IDENTITY'):self.decode(receiptProtocol=21)
    def test_target(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_TARGET'):self.decode(pid=124)
    def test_binary_hash(self):
        with self.assertRaisesRegex(ValueError,'BINARY_RECEIPT'):self.decode(acceptanceSha256='0'*64)
    def test_different_operation(self):
        self.card['mode']='shop-ui'
        with self.assertRaisesRegex(ValueError,'OPERATION_BINDING'):self.decode()
    def test_unhook_failure(self):self.assertTrue(self.decode(unhooked=False)['outcomeUncertain'])
    def test_active_callback(self):self.assertFalse(self.decode(activeCallbacks=1)['safeToRelease'])
    def test_multiple_callback(self):self.assertFalse(self.decode(callbackCount=2)['safeToRelease'])
    def test_embedded_seh_is_not_success(self):
        struct.pack_into('<I',self.data,96+12,0xc0000005);self.assertFalse(self.decode()['ok'])
    def test_action_exception_is_uncertain(self):
        self.data=raw(2,1,'buy');self.card.update(card('buy',2));header(self.data,status=2,seh=0xc0000005,actionReturned=0);self.assertTrue(self.decode()['outcomeUncertain'])
    def test_clean_early_refusal(self):self.exit.update(executed=False,error='SOURCE_CHANGED');self.assertTrue(self.decode()['safeToRelease'])
    def test_refusal_must_not_hide_attempt(self):
        self.exit['executed']=False;(self.run/'attempt.used').write_text('')
        with self.assertRaisesRegex(ValueError,'ATTEMPT_DESPITE'):self.decode()

class CandidateTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'.runtime/mondstadt/rework-20261017/playtest-control/test-scratch';base.mkdir(parents=True,exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=base);self.run=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_fixed_production_candidate(self):
        b.copy_sources(self.run);src=self.run/'candidate-source/native';self.assertIn('ShopReceipt acceptance;',(src/'hook_receipt_protocol.h').read_text());hook=(src/'hook_receipt.cpp').read_text();self.assertIn('ExecuteShop(&receipt->acceptance);',hook);self.assertIn('InterlockedCompareExchange(&receipt->claim,0,0)==0',hook);self.assertIn('FIXED_PLAYTEST_SHOP',(src/'hook_receipt_probe.cpp').read_text())
    def test_same_baseline_one_use(self):
        baseline=self.run/'state';baseline.mkdir();(self.run/'prepared.json').write_text('{}');p=dict(mode='shop-ui',lineage=dict(rootRun=str(self.run)),uiBaseline=dict(run=str(baseline)),uiPlan=dict(id='once'));b.claim_write(self.run,p);p['uiPlan']['id']='another'
        with self.assertRaises(FileExistsError):b.claim_write(self.run,p)
        self.assertTrue((self.run/'shop-another.claim').exists());self.assertTrue((baseline/'shop-consumed.claim').exists())
    def test_id_one_use_even_fresh_baseline(self):
        baseline=self.run/'state';baseline.mkdir();(self.run/'prepared.json').write_text('{}');p=dict(mode='shop-ui',lineage=dict(rootRun=str(self.run)),uiBaseline=dict(run=str(baseline)),uiPlan=dict(id='once'));b.claim_write(self.run,p)
        with self.assertRaises(FileExistsError):b.claim_write(self.run,p)
    def test_readonly_claim_does_nothing(self):b.claim_write(self.run,dict(mode='shop-state'));self.assertEqual(list(self.run.iterdir()),[])
    def test_compileonly_cannot_launch(self):
        p=dict(mode='shop-state',uiPlan=c.plan(args()),pageStart=0,compileOnly=True,launchable=True,lineage={},uiBaseline=None)
        with self.assertRaisesRegex(ValueError,'COMPILE_ONLY'):b.validate_card(p)
    def test_changed_anchor(self):
        with patch.object(b.c,'previous',return_value=({},{})),self.assertRaisesRegex(ValueError,'ANCHOR_CHANGED'):b.revalidate_proofs(dict(anchorRun='a',session={},targetLevelId=1843,lineage={'x':1},binding={}))

if __name__=='__main__':unittest.main()
