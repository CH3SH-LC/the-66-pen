"""Small, evidence-linked group -> functional cluster -> exact-node retrieval.

Clusters are an editorial navigation layer over native menu paths, not new
native categories or runtime verification. Built-ins retain their full key.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .catalog import OUTPUT, sha

# id, title, native menu leaves, use-case aliases, purpose
CLUSTERS = [
    ('flow', '执行流与通用控制', '通用', '分支 条件 判断 循环 顺序 调试 打印 开始 结束', '选择执行分支、输出调试信息、控制图开始和结束。'),
    ('math', '数值、逻辑与向量', '数学', '计算 比较 加减 乘除 随机 坐标 距离 方向 旋转 概率', '数值运算、布尔判断、向量和空间计算。'),
    ('variables', '变量、状态与信号', '自定义变量 预设状态 信号', '状态机 存储 计数 标记 自定义值 CustomValue 通信 消息', '持有实体状态，监听变化，通过信号连接功能。'),
    ('entities', '实体创建、查询与布设', '实体相关 实体布设组 预设点 挂接点', '生成 删除 销毁 物体 场景 实例 模型 可见性 位置 挂点', '寻找、创建、布设和管理实体；区分实体实例与模板。'),
    ('players', '玩家、角色与阵营', '玩家与角色相关 阵营相关', '多人 玩家实体 角色实体 所属 玩家编号 复活 传送 队伍', '转换玩家/角色身份，处理出生、离开、复活和队伍。'),
    ('timers', '定时、延时与全局计时', '定时器 全局计时器', '等待 延迟 倒计时 周期 冷却 十秒 成熟', '启动、停止定时器，接收到期事件和读取计时。'),
    ('movement', '运动、跟随与操控', '运动器 跟随运动器 操控运动器 角色扰动装置', '移动 平台 跟随 位移 速度 操控 载具', '配置实体运动和操控，监听运动状态。'),
    ('triggers', '范围、碰撞与射线', '碰撞 碰撞触发器 碰撞触发源 触发器 射线 光标碰撞盒组件', '靠近 范围 进入 离开 检测 接触 点击 射线命中', '碰撞范围与触发事件、射线检测；靠近选项菜单另见 interaction。'),
    ('interaction', '原生选项与对话交互', '选项卡 文本气泡 悬浮交互页', 'NPC 对话 菜单 交互 选项 按F 开店 打开商店 播种 收获', '原生靠近选项、选中事件、可用状态和气泡。组件配置是节点图之外的前置。'),
    ('shop', '商店、价格与买卖', '商店', '买种子 购买 出售 售卖 收购 商城 价格 货币 交易 金币', '打开商店、维护出售/收购条目、设置价格和处理交易事件。'),
    ('inventory', '道具、背包与货币数量', '道具 道具与背包', '物品 商品 种子 作物 背包 入包 扣除 奖励 货币 金币 容量', '读取与改变道具/货币数量，接收背包事件；交易价格另见 shop。'),
    ('equipment', '装备与装备栏', '装备', '武器 防具 穿戴 卸下 装备属性', '装备创建、穿脱、属性查询及装备事件。'),
    ('skills', '职业与技能能力', '职业 技能 角色技能', '玩家能力 创建能力 施放 释放 攻击技能 技能槽 冷却 职业切换', '职业、技能配置和施放；客户端技能图与服务端管理图不可混用。'),
    ('combat', '战斗、命中与投射物', '战斗 命中判定 投射物', '伤害 治疗 生命 死亡 攻击 子弹 弹道 命中', '伤害与治疗、攻击命中事件和投射物。'),
    ('status', '单位状态与标签', '单位状态 单位标签 标签 扫描标签', 'Buff 增益 减益 状态 标签 标记 筛选', '添加、移除和读取单位状态/标签及变化事件。'),
    ('ai', '造物、仇恨与战术', '造物 自定义仇恨 战术 造物预设状态', 'AI 敌人 怪物 行为 决策 仇恨 目标 战术 宠物', '造物目标、仇恨、预设状态与 AI 战术。'),
    ('navigation', '巡逻、路径与寻路', '造物巡逻 路径 寻路阻挡', '巡逻 寻路 路点 障碍 路径', '巡逻路线、路径信息和寻路阻挡。'),
    ('targeting', '扫描、预瞄准与光标', '扫描 预瞄准 光标', '瞄准 锁定 光标 鼠标 指向 扫描 搜索目标', '客户端目标选择、预瞄准和光标信息。'),
    ('ui', '界面控件与铭牌', '界面控件组 铭牌', 'UI HUD 按钮 按键 Z 操作说明 文字 提示 面板 显示 隐藏', '控制已配置的界面控件组/铭牌；创建控件和文字属于独立配置步骤。'),
    ('camera', '镜头与屏幕效果', '镜头', '摄像机 镜头 震动 注目 视角', '激活镜头、注目、屏幕震动和读取朝向。'),
    ('effects', '特效、音效与光源', '特效 音效 光源组件', '声音 音乐 粒子 光照 视觉 播放 效果', '播放和控制特效、音效、光源。'),
    ('map', '小地图与标识', '小地图标识组件', '小地图 图标 标识 导航标记', '配置地图标识及其可见性。'),
    ('level', '关卡、任务与结算', '关卡相关 关卡任务 关卡结算', '关卡 任务 目标 胜利 失败 结束 结算 流程', '关卡运行、任务进度、结束判定和结算。'),
    ('progression', '成就、段位与排行', '成就 段位 排行榜', '成就 排名 分数 段位 排行 积分', '更新和查询成就、段位、榜单。'),
    ('social', '聊天、礼盒与订阅', '聊天频道 奇域礼盒相关 作者订阅', '聊天 频道 礼盒 订阅 作者', '聊天频道、奇域礼盒及作者订阅状态。'),
    ('cards', '卡牌选择', '卡牌选择器', '卡牌 抽卡 选择器 选卡 随机奖励', '显示卡牌选择器并处理选择结果。'),
    ('lists', '列表与集合处理', '列表 列表相关', '数组 列表 遍历 排序 去重 索引 集合', '构造、查询和修改列表。'),
    ('dictionaries', '字典与键值对', '字典', '字典 键值对 映射 价格表 Dictionary map', '字典构造和查改；泛型、键值结构与动态端口需要具体化。'),
    ('structs', '结构体与自定义数据', '结构体', '结构体 数据结构 字段 struct', '构造、拆分或修改具体结构体；需已有结构体资产。'),
    ('internal', '内部与未公开入口', '', 'GM 内部 测试 不外放', '资源已注册但菜单未公开的内部入口；仅供定位，不作为普通制作入口。'),
]

GROUPS = [('execute', '执行节点', '改变游戏状态或执行动作'), ('event', '事件节点', '从实际发生的事件开始'),
          ('flow', '流程控制节点', '决定执行顺序与分支'), ('query', '查询节点', '读取状态、实体和数量'),
          ('compute', '运算节点', '计算并组合数据'), ('assets', '节点外部资产', '引用独立的外部资产'),
          ('composite', '复合节点', '封装和复用节点逻辑')]

WORKFLOWS = {
    'interaction': {'sequence': ['原生组件：范围、选项索引、文字、初始激活', '307 选中事件 → 核对宿主与索引', '259 角色转所属玩家 → 业务动作', '306 切换播种/收获等选项可用状态'],
                    'pitfalls': ['事件给出的角色不是玩家；先转换身份。', '商品与选项文字同时全空时，先查自定义外显文本权限；当前安装实读权限4按属性10074判断，要求2，未解锁会统一屏蔽文字。原文、选用语言及运行期屏蔽标记分别核对。'],
                    'code': ['tools/gameplan/demo/farming_tabs.py', 'tools/game-executor/native-options/native_tabs.cpp']},
    'shop': {'sequence': ['配置商品、背包货币、商店模板及宿主组件', '702 打开商店', '707 设置已有收购条目的价格；710 添加新的收购条目', '确认购买入包、出售扣物品并增加指定货币'],
             'pitfalls': ['710 不会替换已存在条目的价格；本 Demo 曾因此出现出售无收益。', '价格是具体键值对字典，1788 需正确内核与动态端口计数；不能把已连线输入再填空字典。'],
             'code': ['tools/gameplan/demo/shop_buyback.py', 'tools/gameplan/modules/runtime_prices.py']},
    'inventory': {'sequence': ['690 读取数量', '686 改变普通道具数量', '再次查询数量，确认扣种或入包成功后再改变田地状态'],
                  'pitfalls': ['调用成功不等于物品成功入包；容量不足要保留可收获状态。', '核对商品原文、选用语言与外显文本权限；主语言翻译为空不必然有错，运行读取有原文回退。苹果图标正常不证明名称能显示。'],
                  'code': ['tools/gameplan/modules/farm_interaction.py']},
    'timers': {'sequence': ['79 启动宿主定时器', '83 定时器触发时 → 核对宿主与定时器名', '改变状态并切换模型/选项'],
               'pitfalls': ['循环标志是枚举槽，不是随意写 bool；定时器宿主必须与事件宿主一致。'],
               'code': ['tools/gameplan/modules/farm_interaction.py']},
    'ui': {'pitfalls': ['控件布局、父级激活、玩家归属、可见条件、按键绑定和文字配置必须存在。节点图引用成功不证明画面可见。'],
           'code': ['tools/game-executor/ui-interaction/skill_button.py']},
    'skills': {'pitfalls': ['先选 graphKind 和原生菜单上下文；客户端技能节点不能直接放进服务端图。技能/职业资产创建和节点连线是两个步骤。']},
    'dictionaries': {'pitfalls': ['节点定义的模板端口不是任意可扩写的实例端口。先物化泛型并读回 slots；价格构造参考已部署写法。'],
                     'code': ['tools/gameplan/modules/runtime_prices.py']},
}

HIDDEN = {262:'camera',263:'camera',264:'camera',265:'camera',266:'camera',366:'movement',
          428:'variables',445:'variables',459:'variables',615:'ui',616:'ui',678:'progression',
          100000:'internal',200000:'flow',200036:'camera',200046:'camera',200104:'flow',
          200122:'flow',200042:'flow',200117:'internal',200126:'flow'}


def build_discovery(catalog, directory=OUTPUT):
    directory = Path(directory)
    leaf_map = {leaf: cid for cid, _, leaves, _, _ in CLUSTERS for leaf in leaves.split()}
    groups = [dict(id=gid, name=name, purpose=purpose, builtin=gid not in ('assets', 'composite')) for gid, name, purpose in GROUPS]
    clusters = {cid: dict(id=cid, name=name, purpose=purpose, aliases=aliases.split(), nativeLeaves=leaves.split(),
                         nodes=[], **WORKFLOWS.get(cid, {})) for cid, name, leaves, aliases, purpose in CLUSTERS}
    for n in catalog.nodes:
        leaves = sorted({p['path'][-1] for p in n['menuPaths']})
        unknown = set(leaves) - set(leaf_map)
        if unknown:
            raise ValueError(f'UNCLASSIFIED_NATIVE_MENU:{unknown}')
        ids = sorted({leaf_map[leaf] for leaf in leaves})
        if not ids:
            if n['definitionId'] not in HIDDEN:
                raise ValueError(f'UNCLASSIFIED_HIDDEN_NODE:{n["key"]}')
            ids = [HIDDEN[n['definitionId']]]
        row = {k: n[k] for k in ('key', 'definitionId', 'graphKind', 'name', 'family', 'menuVisibility')}
        row.update(clusters=ids, nativeLeaves=leaves,
                   evidence='native-menu' if leaves else 'explicit-name-routing; not-public-menu',
                   recipeCommand=f'python -B -m tools.node_workbench recipe {n["definitionId"]} --graph-kind {n["graphKind"]}')
        for cid in ids:
            clusters[cid]['nodes'].append(row)
    for c in clusters.values():
        c['count'] = len(c['nodes']); c['byFamily'] = dict(Counter(n['family'] for n in c['nodes']))
        c['byGraphKind'] = dict(Counter(str(n['graphKind']) for n in c['nodes']))
        c['runtimeVerified'] = False
    for group in groups:
        group['clusters'] = [dict(id=c['id'], name=c['name'], count=c['byFamily'][group['name']], purpose=c['purpose'])
                             for c in clusters.values() if group['name'] in c['byFamily']]
        group['count'] = sum(1 for n in catalog.nodes if n['family'] == group['name'])
        if not group['builtin']:
            group['mechanism'] = catalog.data['writer']['externalAssets' if group['id'] == 'assets' else 'composite']
            group['limitation'] = '不是内置节点定义；自动创建/导入尚未完成，不能虚构 definitionId。'
    # A gameplay recipe intentionally crosses native groups and functional clusters.
    farm_ids = [307,306,259,702,707,710,690,686,79,83,73,71,14,2,308,1788]
    farm = dict(id='farming', name='种田经营闭环', purpose='从买种、播种、成长、收获到出售的一条完整制作路线。',
                aliases=['种田','农场','播种','种植','收获','成熟','种子','作物','卖产品','farming'],
                related=['interaction','shop','inventory','variables','timers','entities','dictionaries'],
                sequence=['靠近选项 → 打开商店 → 购买种子', '选播种 → 核对种子和田地状态 → 扣种', '10 秒定时器 → 成熟模型与收获选项', '选收获 → 入包核验 → 空田', '商店收购条目定价 → 背包出售 → 核对货币增加'],
                pitfalls=['玩法数值、模型变化和文字显示分开验收。金额结算已确认；2026-10-14文字全空已定位为自定义外显文本权限未解锁（实际判定等级1、要求2），用户经官方升级到Lv.2后已确认文字恢复；不能再用填语言表代替权限检查。'],
                code=['tools/gameplan/demo/farming_tabs.py','tools/gameplan/demo/farming_visuals.py','tools/gameplan/demo/shop_buyback.py'],
                nodes=[dict(key=catalog.require(20000,i)['key'], definitionId=i, graphKind=20000,
                            name=catalog.require(20000,i)['name'], family=catalog.require(20000,i)['family'],
                            recipeCommand=f'python -B -m tools.node_workbench recipe {i} --graph-kind 20000') for i in farm_ids],
                runtimeVerified=False)
    farm.update(count=len(farm['nodes']), byFamily=dict(Counter(n['family'] for n in farm['nodes'])),byGraphKind={'20000':len(farm['nodes'])})
    clusters['farming'] = farm
    for g in groups[:5]:
        if g['name'] in farm['byFamily']:
            g['clusters'].insert(0,dict(id='farming', name=farm['name'], count=farm['byFamily'][g['name']],purpose=farm['purpose'], crossClusterRecipe=True))
    result = dict(schemaVersion=1, catalogSha256=sha(directory/'catalog.json'), observedUtc=catalog.data['observedUtc'],
                  groups=groups, clusters=[{k:v for k,v in c.items() if k not in ('nodes',)} for c in clusters.values()],
                  variants=len(catalog.nodes), definitions=catalog.data['stats']['definitions'],
                  identity='full category key; graphKind + definitionId are required for this snapshot',
                  limits=['分组依据原生类别；功能簇是有来源的导航整理。', '未列在原生菜单的节点会明确标记，不暗示用户可直接添加。',
                          '节点外部资产和复合节点不是第 930 个内置节点。', 'recipe/edge/value 为离线写法；实际创建、保存、玩法和文字显示另有证据。'])
    out=directory/'discovery'; (out/'clusters').mkdir(parents=True,exist_ok=True); (out/'groups').mkdir(exist_ok=True)
    def write(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=1)+'\n',encoding='utf8')
    write(out/'index.json',result)
    for g in groups:write(out/'groups'/f'{g["id"]}.json',g)
    for cid,c in clusters.items():write(out/'clusters'/f'{cid}.json',c)
    # Compact routing rows only. No port schemas/raw protobuf in the first two layers.
    write(out/'routes.json',list({n['key']:n for c in clusters.values() for n in c['nodes'] if 'clusters' in n}.values()))
    return result


class Discovery:
    def __init__(self, directory=OUTPUT/'discovery'):
        self.directory=Path(directory)
        self.index=self.read('index.json')

    def read(self,relative):return json.loads((self.directory/relative).read_text(encoding='utf8'))

    def group(self,group):
        g=next((g for g in self.index['groups'] if group in (g['id'],g['name'])),None)
        if g is None:raise ValueError(f'UNKNOWN_GROUP:{group}')
        return g

    def cluster(self,cid,graph_kind=None,group=None,offset=0,limit=30):
        c=next((c for c in self.index['clusters'] if cid in (c['id'],c['name'])),None)
        if c is None:raise ValueError(f'UNKNOWN_CLUSTER:{cid}')
        c=self.read(f'clusters/{c["id"]}.json');family=self.group(group)['name'] if group else None
        nodes=[n for n in c['nodes'] if (graph_kind is None or n['graphKind']==graph_kind) and (not family or n['family']==family)]
        count=max(1,min(limit,100));offset=max(0,offset)
        return {**c,'nodes':nodes[offset:offset+count],'matchedCount':len(nodes),'offset':offset,
                'nextOffset':offset+count if offset+count<len(nodes) else None}

    def route(self,query,graph_kind=None,group=None,limit=5):
        q=query.strip().casefold()
        if not q:return dict(query=query,matches=[],next='groups')
        family=self.group(group)['name'] if group else None
        rows=self.read('routes.json');matches=[]
        for c in self.index['clusters']:
            if family and not c['byFamily'].get(family):continue
            if graph_kind and not c['byGraphKind'].get(str(graph_kind)):continue
            # A sentence such as "靠近 NPC 打开商店" must route to shop as well
            # as interaction; the native leaf is a stable keyword even when
            # the editorial title is longer than the user's whole query.
            terms=list(dict.fromkeys([c['name'],c['id'],*c['aliases'],*c.get('nativeLeaves',[])]))
            hits=[t for t in terms if t.casefold() in q or q in t.casefold()]
            nodes=[n for n in rows if c['id'] in n['clusters'] and (not family or n['family']==family)
                   and (not graph_kind or n['graphKind']==graph_kind) and (q in n['name'].casefold() or q==str(n['definitionId']))]
            score=sum(10+len(t) for t in hits)+min(len(nodes),10)*2
            if score:matches.append(dict(id=c['id'],name=c['name'],purpose=c['purpose'],score=score,matchedTerms=hits,
                sampleNodes=[{k:n[k] for k in ('definitionId','graphKind','name','family')} for n in nodes[:5]],
                nextCommand=f'python -B -m tools.node_workbench cluster {c["id"]}'+(f' --graph-kind {graph_kind}' if graph_kind else '')+(f' --group {self.group(group)["id"]}' if group else '')))
        matches.sort(key=lambda x:(-x['score'],x['id']))
        return dict(query=query,matches=matches[:max(1,min(limit,20))],totalClustersMatched=len(matches),
                    fallback='没有匹配时使用 search 关键词；不要自行补造节点。',runtimeVerified=False)
