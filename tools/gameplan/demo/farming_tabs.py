"""Native host option cards for the existing farming demo.

The separate component installer creates the proximity region and cards. This
module binds 307 to the visible hosts, preserving the already working shop and
the original plot state consumed by the crop visualization graph.
"""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from ..nodes import Graph,NodeType,SELF,ON_CREATE
from ..builder import GraphBuilder
from ..golden import freeze
from ..contracts import DATA_INPUT,default_store
from ..modules import farm_interaction as farm,player_abilities as a,shop
from ..modules.distance_interaction import ENTITY,GUID
from .farming_manual import request_line_bytes

SELECTED=NodeType(307,'选项卡选中时',exec_outs={'then':0},outs={'host':0,'host_guid':1,'index':2,'character':3})
ACTIVE=NodeType(306,'激活/关闭选项卡',exec_in=0,exec_outs={'then':0},ins={'host':0,'index':1,'active':2})
PLAYER=NodeType(259,'获取角色归属的玩家实体',ins={'character':0},outs={'player':0})
SHOP_HOST=1077936131
FARM_HOST=1077936133
CONFIG=farm.FarmConfig(1077936130,1107296257,1107296258,'uint','enum',10.0)

def activate(g,src,host,index,enabled,alias,role='then'):
    n=g.place(ACTIVE,alias);src.flow_to(n,role);n.data_from(*host,'host')
    n.const('index',index,'int');n.const('active',int(enabled),'enum');return n

def entry(g):
    owner=g.place(SELF,'owner');event=g.place(SELECTED,'selected')
    gate=a.route_refs(g,event,left=(owner,'self'),right=(event,'host'),alias='own_host')
    return owner,event,gate

def shop_plan():
    g=Graph('MW_API_NATIVE_TAB_SHOP');owner,event,gate=entry(g)
    index=a.route_equal(g,gate,selector=(event,'index'),expected=1,value_slot='int',alias='shop_option',from_role='true')
    player=g.place(PLAYER,'player');player.data_from(event,'character','character')
    commerce=g.place(ENTITY,'commerce');commerce.const('guid',1077936129,'uint')
    shop.open_(g,index,player=(player,'player'),shop_owner=(commerce,'entity'),shop_index=1,from_role='true')
    g.validate();return g.plan

def farm_plan():
    g=Graph('MW_API_NATIVE_TAB_FARM');owner,event,gate=entry(g)
    plot=g.place(ENTITY,'plot');plot.const('guid',CONFIG.plot_id,'uint')
    guid=g.place(GUID,'plot_guid');guid.data_from(plot,'entity','entity')
    state=a.read_state(g,target=(plot,'entity'),name=CONFIG.state_name,flag_slot='enum',alias='option_stage')
    # An explicit index gate and stage gate prevent a stale harvest card from
    # planting, or a repeated plant selection from harvesting a matured crop.
    plant=a.route_equal(g,gate,selector=(event,'index'),expected=1,value_slot='int',alias='plant_option',from_role='true')
    empty=a.route_integer(g,plant,selector=(state,'value'),expected=0,alias='plant_stage',from_role='true')
    harvest=a.route_equal(g,plant,selector=(event,'index'),expected=2,value_slot='int',alias='harvest_option',from_role='false')
    ripe=a.route_integer(g,harvest,selector=(state,'value'),expected=2,alias='harvest_stage',from_role='true')
    fragment=farm.install(g,empty,character=(event,'character'),plot=(plot,'entity'),
        plot_guid=(guid,'guid'),timer_owner=(owner,'self'),config=CONFIG)
    ripe.flow_to(fragment.action,'true')
    def cards(src,plant_active,harvest_active,label,role='then'):
        n=activate(g,src,(owner,'self'),1,plant_active,label+'_plant',role)
        return activate(g,n,(owner,'self'),2,harvest_active,label+'_harvest')
    cards(fragment.planted,False,False,'growing')
    cards(fragment.ripe,False,True,'mature')
    cards(fragment.harvested,True,False,'empty')
    # Initial component state is plant active / harvest inactive. No reset of
    # the shared plot state, inventory, currency, or earlier shop graph occurs.
    g.validate();return g.plan

def package(plan,host):
    batch=GraphBuilder(plan,lambda _:None,run_id='offline').batch_plan_json()
    values=batch.pop('values');batch['values']=[];followups=[];store=default_store()
    for source,value in zip(plan.consts,values):
        port=store.require(plan.aliases()[source.alias].definition_id).port(DATA_INPUT,source.port_index)
        value=dict(value,action='set-value',nodeAlias=source.alias,portKind=3,
                   expect={'serverParamType':port.server_param_type,'genericId':port.generic_id})
        if source.alias=='farm_growth_timer' and source.port_index==3:value['slot']='float'
        followups.append(value)
    if request_line_bytes({'action':'build-plan','plan':batch})>=16384:raise ValueError('TAB_BATCH_TOO_LARGE')
    return dict(plan=freeze(plan),batchPlan=batch,followups=followups,
        manifest=dict(kind='native-farming-tabs-v1',graphName=plan.name,hostId=host,
        nodes=len(plan.nodes),edges=len(plan.edges),values=len(plan.consts),
        shape=dict(nodes=len(plan.nodes),edges=len(plan.edges),values=len(plan.consts)),
        planSha256=hashlib.sha256(json.dumps(freeze(plan),ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        config=asdict(CONFIG),runtimeVerified=False))

def write_packages(output):
    out=Path(output).resolve();root=Path(__file__).resolve().parents[3]
    if not out.is_relative_to(root/'.runtime'):raise ValueError('PROJECT_RUNTIME_REQUIRED')
    result={}
    for label,plan,host in [('shop',shop_plan(),SHOP_HOST),('farm',farm_plan(),FARM_HOST)]:
        dest=out/label;dest.mkdir(parents=True,exist_ok=True);data=package(plan,host)
        for key,value in data.items():(dest/(key+'.json')).write_text(json.dumps(value,ensure_ascii=True,indent=2),encoding='utf-8')
        result[label]=data['manifest']
    return result

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True)
    print(json.dumps(write_packages(ap.parse_args().output),ensure_ascii=False))
