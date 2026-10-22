"""Bounded actual UI only. A returned click is not a completed transaction."""
import re,struct
from contract import require
import inventory_contract as inv
OPERATIONS={'shop-state':15,'shop-ui':16}
ACTIONS={'goods':1,'bag-item':2,'quantity-one':3,'buy':4,'sell-open':5,'sell':6,'back':7}
KINDS={0:'unknown',1:'inventory-page',2:'buy-confirmation',3:'item-details',4:'sell-confirmation',5:'main-hud'}
ROW_SIZE=336;UI_SIZE=43424;INVENTORY_OFFSET=96;UI_OFFSET=96+inv.SIZE;SIZE=inv.SIZE+130368
HEADER=('bytes','version','status','seh','stage','operation','nativeCalls','resourcesReleased','uiStable','actionAttempted','actionReturned','afterReadable','action','row','reserved0','reserved1')
POINTERS=('context','view','page','shopModule','bagModule','backButton','confirmButton','sellButton','slider','item','key')
NUMBERS=('kind','status','ownerId','shopId','quantity','maximum','instanceId','generation','key0','key3','rowCount','complete','backReady','confirmReady','sellReady','sliderReady','textLength','reserved')
ROW_FIELDS=('object','button','item','key','callbackTarget','role','index','instanceId','key0','key3','active','enabled','handlerVerified','textLength','reserved')
def plan(args):
    require(args.operation in OPERATIONS,'SHOP_OPERATION')
    if args.operation=='shop-state':
        require(not any(getattr(args,k,None) is not None for k in ('ui_action','ui_id','ui_row','config_id','label','ui_baseline')),'SHOP_STATE_HAS_NO_ACTION')
        return dict(action=None,id=None,row=None,configId=None,label=None)
    action=getattr(args,'ui_action',None);identifier=getattr(args,'ui_id',None);row=getattr(args,'ui_row',None);config=getattr(args,'config_id',None);label=getattr(args,'label',None)
    require(action in ACTIONS,'SHOP_ACTION');require(isinstance(identifier,str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}',identifier),'SHOP_ACTION_ID')
    require(isinstance(label,str) and '\x00' not in label and len(label.encode('utf-16-le'))<=254,'SHOP_LABEL')
    if action in ('goods','bag-item'):require(type(row) is int and 0<=row<128,'SHOP_ROW')
    else:require(row is None,'SHOP_UNEXPECTED_ROW')
    if action!='back':require(type(config) is int and 1<=config<=0xffffffff,'SHOP_CONFIG_ID')
    else:require(config is None,'SHOP_BACK_CONFIG')
    return dict(action=action,id=identifier,row=row,configId=config,label=label)
def text(raw,n):
    require(n<=127 and not any(raw[n*2:]),'SHOP_TEXT_BOUNDS');return raw[:n*2].decode('utf-16-le')
def ui(raw):
    require(len(raw)==UI_SIZE,'SHOP_UI_SIZE');o=dict(zip(POINTERS+NUMBERS,struct.unpack_from('<11Q18I',raw)))
    require(o['kind'] in KINDS and o['status'] in (0,1) and not o['reserved'] and o['rowCount']<=128,'SHOP_UI_HEADER')
    require(all(o[k] in (0,1) for k in ('complete','backReady','confirmReady','sellReady','sliderReady')),'SHOP_UI_FLAGS')
    o['text']=text(raw[160:416],o['textLength']);o['rows']=[]
    for i in range(o['rowCount']):
        start=416+i*ROW_SIZE;r=dict(zip(ROW_FIELDS,struct.unpack_from('<5Q10I',raw,start)));r['text']=text(raw[start+80:start+336],r['textLength']);r['configId']=r['key']>>32;r['resourceType']=r['key']&0xffffffff
        require(r['role'] in (1,2) and r['index']<4096 and r['object'] and r['button'] and r['configId'] and not r['reserved'],'SHOP_ROW_IDENTITY')
        require(all(r[k] in (0,1) for k in ('active','enabled','handlerVerified')),'SHOP_ROW_FLAGS')
        if r['role']==2:require(r['item'] and r['instanceId'],'SHOP_ITEM_IDENTITY')
        r['labelRole']='visible-price-text' if r['role']==1 else 'visible-item-name';o['rows'].append(r)
    require(not any(raw[416+o['rowCount']*ROW_SIZE:]),'SHOP_UNUSED_ROWS')
    require(len({(r['role'],r['index']) for r in o['rows']})==o['rowCount'],'SHOP_DUPLICATE_ROW')
    o['screen']=KINDS[o['kind']];o['labelRole']='dialog-title' if o['kind'] in (2,3,4) else 'no-dialog-title';o['configId']=o['key']>>32;o['resourceType']=o['key']&0xffffffff
    if o['complete']:
        require(not o['status'] and o['context'] and o['kind']!=0,'SHOP_COMPLETE_IDENTITY')
        if o['kind']!=5:require(o['page'] and o['view'],'SHOP_PAGE_IDENTITY')
        if o['kind'] in (2,3,4):require(o['configId'],'SHOP_SELECTED_CONFIG')
        if o['kind'] in (2,4):require(o['ownerId'] and o['shopId'] and o['quantity']<=o['maximum'],'SHOP_CONFIRM_IDENTITY')
        if o['kind'] in (3,4):require(o['item'] and o['instanceId'],'SHOP_SELECTED_ITEM')
    return o
def validate_selection(s,p):
    require(s['complete'] and not s['status'],'SHOP_UI_INCOMPLETE');a=p['action'];row=None
    if a in ('goods','bag-item'):
        require(s['kind']==1 and p['row']<len(s['rows']),'SHOP_ROW_NOT_VISIBLE');row=s['rows'][p['row']]
        require(row['role']==ACTIONS[a] and row['active']==row['enabled']==row['handlerVerified']==1 and row['configId']==p['configId'] and row['text']==p['label'],'SHOP_ROW_CHANGED')
    else:
        require(p['label']==s['text'],'SHOP_LABEL_CHANGED')
        if a!='back':require(s['configId']==p['configId'],'SHOP_CONFIG_CHANGED')
        if a=='quantity-one':require(s['kind'] in (2,4) and s['sliderReady']==1,'SHOP_SLIDER_UNAVAILABLE')
        elif a=='buy':require(s['kind']==2 and s['confirmReady']==1 and s['quantity']==1,'SHOP_BUY_QUANTITY_ONE')
        elif a=='sell-open':require(s['kind']==3 and s['sellReady']==1,'SHOP_SELL_UNAVAILABLE')
        elif a=='sell':require(s['kind']==4 and s['confirmReady']==1 and s['quantity']==1,'SHOP_SELL_QUANTITY_ONE')
        elif a=='back':require(s['backReady']==1,'SHOP_BACK_UNAVAILABLE')
    return row
def parse(raw):
    require(len(raw)==SIZE,'SHOP_ABI_SIZE');o=dict(zip(HEADER+('avatar','bag','button','callback'),struct.unpack_from('<16I4Q',raw)))
    require(o['bytes']==SIZE and o['version']==6 and o['operation'] in (15,16),'SHOP_ABI_VERSION')
    require(o['status'] in (0,1,2) and 1<=o['stage']<=3 and not o['reserved0'] and not o['reserved1'],'SHOP_ABI_HEADER')
    require(all(o[k] in (0,1) for k in ('resourcesReleased','uiStable','actionAttempted','actionReturned','afterReadable')),'SHOP_FLAGS');require(o['actionReturned']<=o['actionAttempted'],'SHOP_ACTION_ORDER')
    o['inventory']=inv.parse(raw[96:UI_OFFSET]) if struct.unpack_from('<I',raw,96)[0] else None
    for i,name in enumerate(('before','second','after')):o[name]=ui(raw[UI_OFFSET+i*UI_SIZE:UI_OFFSET+(i+1)*UI_SIZE])
    o['uiBeforeBytesHex']=raw[UI_OFFSET:UI_OFFSET+UI_SIZE].hex()
    if o['stage']==3:
        require(o['inventory'] and not o['inventory']['status'] and o['inventory']['stage']==3 and o['uiStable']==1 and o['before']==o['second'],'SHOP_BASELINE_STABILITY')
        require(o['avatar']==o['inventory']['avatar'] and o['bag']==o['inventory']['bag'],'SHOP_OWNER_BINDING')
    if o['operation']==15:require(not any(o[k] for k in ('actionAttempted','actionReturned','action','button','callback')),'SHOP_OBSERVATION_WROTE')
    else:require(o['action'] in ACTIONS.values() and o['row']<128,'SHOP_ACTION_ENUM')
    return o
def interpretation(o,card):
    result=inv.interpretation(o['inventory'],dict(card,mode='inventory-state'))
    require(o['stage']==3 and not o['status'] and o['uiStable']==1,'SHOP_STATE_UNKNOWN')
    p=card['uiPlan'];state=o['before'];state_after=o['after'] if o['afterReadable'] else None
    if card['mode']=='shop-ui':
        validate_selection(state,p);require(o['action']==ACTIONS[p['action']] and o['actionAttempted']==o['actionReturned']==1,'SHOP_ACTION_NOT_RETURNED')
        require(o['uiBeforeBytesHex']==card['uiBinding']['uiBytesHex'] and o['avatar']==card['uiBinding']['avatar'] and o['bag']==card['uiBinding']['bag'],'SHOP_NATIVE_BASELINE_BINDING')
    outcome=None
    if state_after and card['mode']=='shop-ui':
        a=p['action'];outcome=(state_after['kind']==2 and state_after['configId']==p['configId']) if a=='goods' else (state_after['kind']==3 and state_after['configId']==p['configId']) if a=='bag-item' else (state_after['kind']==state['kind'] and state_after['quantity']==1) if a=='quantity-one' else (state_after['kind']==4 and state_after['instanceId']==state['instanceId']) if a=='sell-open' else (state_after['context']!=state['context']) if a in ('back','buy','sell') else None
    result.update(operation=card['mode'],readOnly=card['mode']=='shop-state',uiState=state,uiAfter=state_after,uiStable=True,uiAction=p['action'],uiActionReturned=bool(o['actionReturned']),uiTransitionObserved=outcome,transactionVerified=False,inventoryEffectVerified=False,gameplayEffectVerified=False,naturalInteractionVerified=False,uiLimits=dict(maxVisibleRows=128,maxContainerEntries=4096,quantityOnConfirm=1),uiSemantics='Existing active native UI rows and exact bound callbacks only. Visible current category only; no arbitrary UI, synthetic dialog, direct settlement, inventory write, or implicit retry. Returned click and closed dialog do not prove purchase/sale settlement. Use separate v6 inventory-state / inventory-diff receipts.')
    return result
