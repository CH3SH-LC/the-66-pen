"""Read-only teaching views over the recorded catalog, never editor operations."""
from __future__ import annotations

from .recipes import parameter_recipe


ROLES = {1: '执行输入：从这里开始做事', 2: '执行输出：接下一步动作',
         3: '数据输入：需要什么值', 4: '数据输出：提供什么值',
         5: '资源辅助端口：普通 wire 不支持，含义需追踪'}
ACTIONS = {
    'candidate-scalar-slot': '有常量候选写法；创建实例后先读 slots，再按 expect 写入。',
    'link-concrete-type-then-read-slots': '类型尚未确定；接具体类型的输出，再读实例类型和 slots。choiceIndex 不是可写枚举。',
    'container-requires-leaf-descriptor-and-live-storage-check': '逐层确认列表元素或字典键值类型，再查实例容器槽；不能把空容器当作类型已确定。',
    'connect-from-compatible-output': '通用常量写入器没有此类型的 setter；从兼容的输出接入，或另行开发适配器。',
    'no-resource-descriptor': '没有已解出的存储说明；先查原始来源，不能猜常量写法。',
}


def page(items, offset=0, limit=12):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('PAGE_REQUIRES_OFFSET_GE_0_LIMIT_1_TO_100')
    return {'total': len(items), 'offset': offset, 'limit': limit,
            'nextOffset': offset + limit if offset + limit < len(items) else None,
            'items': items[offset:offset + limit]}


def describe_type(d):
    """Retain nested types without copying raw protobuf or repeated enum options."""
    if not d:
        return None
    out = {k: d.get(k) for k in ('storageKind', 'storageName', 'serverParamType', 'genericId')}
    out['default'] = '资源有显式记录；具体含义查 show 原文及实例 slots' if d.get('declaredDefault') else '资源未记录；不能推定为零或可省略'
    if 'enumGroupId' in d:
        out['enumGroupId'] = d['enumGroupId']
        out['lookup'] = f"enum {d['enumGroupId']}"
    if 'genericChoices' in d:
        out['genericChoices'] = [{'choiceIndex': x['choiceIndex'], 'type': describe_type(x['descriptor'])}
                                 for x in d['genericChoices']]
    if 'containerMembers' in d:
        out['containerMembers'] = [{'resourceField': x['field'], 'type': describe_type(x['descriptor'])}
                                  for x in d['containerMembers']]
    return out


def describe_node(catalog, graph_kind, definition_id, port_key=None, offset=0, limit=12):
    n = catalog.require(graph_kind, definition_id)
    ports = n['ports']
    if port_key is not None:
        ports = [p for p in ports if p['key'] == port_key]
        if not ports:
            raise ValueError(f'PORT_NOT_DECLARED:{port_key}')
    rows = []
    for p in ports:
        d = p['descriptor'] or {}
        row = {'port': p['key'], 'name': p['name'] or '（原始名称为空，使用端口键识别）',
               'role': ROLES.get(p['kind'], '未知端口种类'),
               'signature': {'serverParamType': p['live']['serverParamType'],
                             'genericId': p['live']['fbGKY8GZn68']},
               'storage': d.get('storageName'), 'resourceKernelPin': p['resourceKernelPin']}
        if p['kind'] == 3:
            r = parameter_recipe(p)
            row.update(inputStatus=r['status'], nextStep=ACTIONS[r['status']],
                       required='未知；不能仅凭未连线推定可省略',
                       defaultRecorded=bool(d.get('declaredDefault')))
            if r.get('candidateSlot'):
                row.update(candidateSlot=r['candidateSlot'], payloadTag=r['payloadTag'])
        elif p['kind'] == 4:
            row['nextStep'] = '将输出接到兼容的数据输入；是否何时求值要看触发、消费节点和官方说明。'
        if d.get('enumGroupId') is not None:
            row.update(enumGroupId=d['enumGroupId'], enumCommand=f"enum {d['enumGroupId']}")
        if d.get('genericChoices'):
            row['genericChoiceCount'] = len(d['genericChoices'])
        if port_key is not None:
            row['typeDetail'] = describe_type(p['descriptor'])
        rows.append(row)
    purpose = list(dict.fromkeys(line for doc in n['official'] for line in doc['function']))
    return {
        'identity': {k: n[k] for k in ('key', 'definitionId', 'graphKind', 'name', 'family')},
        'purposeFromOfficialSnapshot': purpose or ['官方正文未随本发行包分发；请按来源链接阅读，节点名字不能替代运行证据。'],
        'menus': n['menuPaths'], 'menuVisibility': n['menuVisibility'],
        'ports': page(rows, offset, limit),
        'dynamicPorts': {'declaredInSource': n.get('hasDynamicPortsInSource'), 'rawExcludedFromDistribution': True, 'generalResizeEndpoint': False},
        'readingNotes': [
            '这是已采集定义的中文阅读视图，不是本次连接编辑器。',
            '端口键使用作者层索引；resourceKernelPin 仅用于追溯底层，不能替换 wire 索引。',
            '端口种类、连线类型、存储类型、枚举表编号属于不同编号空间。',
            '带 typeDetail 的 containerMembers.resourceField 是资源字段号，不是已证明的 setter 键。',
        ],
        'next': ([f"explain {definition_id} --graph-kind {graph_kind} --port {n['ports'][0]['key']}"] if n['ports'] else []) + [
                 f'recipe {definition_id} --graph-kind {graph_kind}',
                 f'show {definition_id} --graph-kind {graph_kind}'],
        'sources': {'observedUtc': catalog.data['observedUtc'], 'resource': n['resource'],
                    'official': [{'url': d.get('url'), 'name': d.get('name')} for d in n['official']],
                    'live': catalog.data['evidence'].get('live', {'state': 'historical-metadata-only', 'privateReceiptsDistributed': False})},
        'nativeMutationsPerformed': False, 'runtimeVerified': False,
    }


def enum_search(catalog, query='', offset=0, limit=12):
    q = query.casefold()
    found = [g for g in catalog.data['enumGroups'].values()
             if q in str(g['id']) or q in g['name'].casefold()
             or any(q in x['name'].casefold() for x in g['options'])]
    found.sort(key=lambda g: g['id'])
    return page([{'id': g['id'], 'name': g['name'], 'optionCount': len(g['options']),
                  'next': f"enum {g['id']}"} for g in found], offset, limit)


def enum_usage(catalog, enum_id):
    def walk(d, path):
        if not d:
            return
        if d.get('enumGroupId') == enum_id:
            yield path
        for x in d.get('genericChoices', []):
            yield from walk(x['descriptor'], f"{path}.genericChoices[{x['choiceIndex']}].descriptor")
        for i, x in enumerate(d.get('containerMembers', [])):
            yield from walk(x['descriptor'], f'{path}.containerMembers[{i}].descriptor')
    for n in catalog.nodes:
        for p in n['ports']:
            for path in walk(p['descriptor'], 'descriptor'):
                yield {'definitionId': n['definitionId'], 'graphKind': n['graphKind'],
                       'name': n['name'], 'port': p['key'], 'descriptorPath': path}


def describe_enum(catalog, enum_id, offset=0, limit=12):
    try:
        g = catalog.data['enumGroups'][str(enum_id)]
    except KeyError as exc:
        raise ValueError(f'ENUM_GROUP_NOT_RECORDED:{enum_id}') from exc
    return {'id': g['id'], 'name': g['name'],
            'options': [{k: x[k] for k in ('value', 'name')} for x in g['options']],
            'usage': page(list(enum_usage(catalog, enum_id)), offset, limit),
            'readingNotes': ['value 是真实值，不能用选项的排列位置替代。',
                             'usage 包含嵌套泛型候选中的引用，不保证实例当前已选该类型。',
                             '无引用只表示当前929变体未引用，不代表该枚举无效。',
                             '常量写法取决于精确端口；先查 recipe/slots，不把枚举表ID写成选项值。'],
            'source': 'data/node-workbench/catalog.json → enumGroups；来源清单见 evidence.installed',
            'nativeMutationsPerformed': False, 'runtimeVerified': False}
