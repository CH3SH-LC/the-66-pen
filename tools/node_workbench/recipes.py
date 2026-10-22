"""Produce offline requests; this module never sends an editor command."""
from __future__ import annotations

from .catalog import Catalog


def value_candidate(catalog, graph_kind, definition_id, port_index, payload):
    """Type-check a scalar candidate against this exact variant, not its label.

    This does not materialize generics or claim the live instance has this slot.
    The authoring adapter must still read the instance and enforce its own preflight.
    """
    from tools.authoring.author import validate_scalar_payload
    validate_scalar_payload(payload)
    n = catalog.require(graph_kind, definition_id)
    p = next((p for p in n['ports'] if p['kind'] == 3 and p['index'] == port_index), None)
    if p is None:
        raise ValueError('INPUT_PORT_NOT_DECLARED')
    r = parameter_recipe(p)
    if r['status'] != 'candidate-scalar-slot':
        raise ValueError('SCALAR_REQUIRES_CONCRETE_SUPPORTED_DESCRIPTOR')
    tag, value = next(iter(payload.items()))
    if tag != r['payloadTag']:
        raise ValueError('RESOURCE_STORAGE_PAYLOAD_MISMATCH')
    if tag == 'int' and not -(2 ** 31) <= value < 2 ** 31:
        raise ValueError('INT32_OVERFLOW')
    if tag == 'float' and abs(value) > 3.4028234663852886e38:
        raise ValueError('FLOAT32_OVERFLOW')
    if r.get('enumValues') and value not in {v['value'] for v in r['enumValues']}:
        raise ValueError('ENUM_VALUE_NOT_DECLARED')
    return {'definitionKey': n['key'], 'definitionId': definition_id, 'portKind': 3,
            'portIndex': port_index, 'expect': r['expect'], 'slot': r['candidateSlot'],
            'value': payload, 'mustReadInstanceSlotsBeforeWrite': True,
            'nativeMutationsPerformed': False, 'runtimeVerified': False}


def parameter_recipe(port):
    d = port['descriptor']
    result = {'portIndex': port['index'], 'name': port['name'],
              'expect': {'serverParamType': port['live']['serverParamType'],
                         'genericId': port['live']['fbGKY8GZn68']},
              'mustReadInstanceSlotsBeforeWrite': True}
    if not d:
        return {**result, 'status': 'no-resource-descriptor'}
    kind = d['storageKind']
    if kind in range(1, 7):
        slot = {1: 'uint', 2: 'int', 3: 'bool', 4: 'float', 5: 'string', 6: 'enum'}[kind]
        result.update(status='candidate-scalar-slot', candidateSlot=slot,
                      payloadTag='uint' if slot == 'enum' else slot)
        if kind == 6:
            result['enumValues'] = (d.get('enumGroup') or {}).get('options', [])
            result['enumGroupId'] = d.get('enumGroupId')
    elif kind == 10000:
        result.update(status='link-concrete-type-then-read-slots', choices=d.get('genericChoices', []),
                      warning='候选索引是资源顺序；当前 author CLI 没有直接选择泛型的端点。')
    elif kind in (10002, 10003):
        result.update(status='container-requires-leaf-descriptor-and-live-storage-check',
                      payloadTag='list' if kind == 10002 else 'dict',
                      members=d.get('containerMembers', []), limit=64,
                      warning='支持的叶子受 AuthorPreflightPinValue 限制；不将空字典当作已完成泛型实例化。')
    else:
        result.update(status='connect-from-compatible-output',
                      warning='当前通用常量写入器没有此存储类型的 setter。')
    return result


def recipe(catalog: Catalog, graph_kind: int, definition_id: int):
    n = catalog.require(graph_kind, definition_id)
    base = ['python', '-B', 'tools/authoring/author.py', '--elevated-queue', '<active-project-queue>', 'graph']
    common = ['--request-id', '<unique-request-id>', '--run-id', '<active-run-id>', '--name', '<MW_API_name>']
    return {'definitionKey': n['key'], 'name': n['name'], 'graphKind': graph_kind,
            'nativeAddMethod': catalog.data['writer']['addNodeMethod'],
            'createGraphArgvTemplate': base + ['create', *common, '--graph-kind', str(graph_kind)],
            'lookupGraphArgvTemplate': base + ['lookup', *common],
            'addNodeArgvTemplate': base + ['add', *common, '--graph-id', '<lookup-result-graph-id>',
                '--expected-node-count', '<fresh-node-count>', '--definition-id', str(definition_id), '--x', '0', '--y', '0'],
            'buildPlanNode': {'definitionId': definition_id, 'x': 0, 'y': 0},
            'ports': [{'key': p['key'], 'name': p['name'], 'signature': {
                'serverParamType': p['live']['serverParamType'], 'genericId': p['live']['fbGKY8GZn68']}}
                      for p in n['ports']],
            'inputs': [parameter_recipe(p) for p in n['ports'] if p['kind'] == 3],
            'wireRules': {'execution': '2:index -> 1:index', 'data': '4:index -> 3:index',
                          'adapterExecutionRestriction': '当前独立 wire 端点：执行输出 index 0/1，输入 index 0；超出须扩展适配器',
                          'concreteTypes': 'serverParamType 和 genericId 同时匹配',
                          'generic': '连接后检查原生类型物化结果；不能只用 definition 默认值证明'},
            'dynamicPorts': {'rawExcludedFromDistribution': True, 'presentInSource': n.get('hasDynamicPortsInSource'), 'generalResizeEndpoint': False},
            'sequence': ['create 为异步请求；lookup 后取实际 graphId', 'add 后用读回取得实际 nodeId',
                         '按实际端口连接；读 slots 后写值；每次变更只派发一次',
                         'export 核对节点、边和参数；关卡保存和试玩另行验收'],
            'availableInMenus': n['menuPaths'], 'nativeMutationsPerformed': False, 'runtimeVerified': False}


def compatible_edge(catalog, graph_kind, source_id, source_port, target_id, target_port):
    def pin(node_id, sig):
        node = catalog.require(graph_kind, node_id)
        return next((p for p in node['ports'] if p['key'] == sig), None)
    src = pin(source_id, source_port); dst = pin(target_id, target_port)
    if src is None or dst is None:
        raise ValueError('PORT_NOT_DECLARED')
    if (src['kind'], dst['kind']) not in ((2, 1), (4, 3)):
        raise ValueError('EDGE_DIRECTION_MISMATCH')
    a, b = src['live'], dst['live']
    if src['kind'] == 4 and a['serverParamType'] and b['serverParamType']:
        if (a['serverParamType'], a['fbGKY8GZn68']) != (b['serverParamType'], b['fbGKY8GZn68']):
            raise ValueError('CONCRETE_TYPE_MISMATCH')
    generic = src['kind'] == 4 and (a['serverParamType'] == 0 or b['serverParamType'] == 0)
    return {'declaredCompatible': True, 'requiresNativeGenericResolution': bool(generic),
            'runtimeVerified': False}


def tab_shop_example(catalog):
    """Host event -> character's player -> native shop; component setup stays explicit."""
    links = [(0, 2, 0, 2, 1, 0), (0, 4, 3, 1, 3, 0), (1, 4, 0, 2, 3, 0), (0, 4, 0, 2, 3, 1)]
    ids = [307, 259, 702]
    for a, ak, ai, b, bk, bi in links:
        compatible_edge(catalog, 20000, ids[a], f'{ak}:{ai}', ids[b], f'{bk}:{bi}')
    return {'graphKind': 20000, 'name': 'MW_API_TabShop_Example',
            'preconditions': ['图绑定商店归属实体；该实体配置选项卡组件和可见触发范围',
                              '示例仅配置一个商店选项；多选项必须按 307 的 4:2 选项卡序号分支',
                              '商店序号示例为 1，写入前必须核对实际配置'],
            'plan': {'nodes': [{'definitionId': n, 'x': i * 340, 'y': 0} for i, n in enumerate(ids)],
                     'edges': [dict(zip(('from', 'fromKind', 'fromIndex', 'to', 'toKind', 'toIndex'), link)) for link in links],
                     'values': [{'node': 2, 'portIndex': 2, 'slot': 'int', 'value': {'int': 1}}]},
            'explanation': '307 的事件源是商店宿主，选择者是角色；经 259 转成玩家实体，再交给 702。',
            'nativeMutationsPerformed': False, 'runtimeVerified': False}
