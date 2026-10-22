"""Compile live signatures, installed resources and official prose without mutation.

The full category tuple is part of identity. Metadata is not a runtime verdict:
absent defaults stay absent, and unknown protobuf fields remain visible as raw data.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / '.runtime/verification/update-repair-20260925/catalog/decoded-7.1'
LIVE = ROOT / '.runtime/verification/node-writing-20261014/live/live-node-schema.json'
OUTPUT = ROOT / 'data/node-workbench'
FAMILIES = {1: '执行节点', 2: '事件节点', 3: '流程控制节点', 4: '查询节点', 5: '运算节点'}
PIN_FIELDS = {100: 1, 101: 2, 102: 3, 103: 4, 106: 5}
STORAGE = {0: '实体引用', 1: 'uint', 2: 'int', 3: 'bool', 4: 'float', 5: 'string',
           6: 'enum', 7: '向量', 10000: '泛型', 10002: '列表', 10003: '字典',
           10004: '结构体', 10007: '键值对'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(fields, number):
    return [r for r in fields if r['f'] == number]


def message(fields, number):
    return next((r.get('m', []) for r in rows(fields, number)), [])


def scalar(fields, number, default=0):
    return next((r.get('v', default) for r in rows(fields, number)), default)


def string(fields, number):
    return next((r.get('s', r.get('s_alt', '')) for r in rows(fields, number)), '')


def identity(fields):
    return tuple(scalar(fields, i) for i in range(1, 6))


def key(category, definition_id):
    return ':'.join(map(str, [*category, definition_id]))


def project_output(path):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT) or path == ROOT:
        raise ValueError('OUTPUT_MUST_BE_PROJECT_LOCAL')
    return path


def descriptor(fields, enums):
    """Decode proven descriptor members; retain every raw field, including unknowns."""
    kind = scalar(fields, 1)
    result = {'storageKind': kind, 'storageName': STORAGE.get(kind, f'未解释类型 {kind}'),
              'genericId': scalar(fields, 3), 'serverParamType': scalar(fields, 4),
              'declaredDefault': rows(fields, 2) or None,
              'defaultMeaning': '资源显式记录（原始 protobuf）' if rows(fields, 2) else '资源未显式记录；不推定运行时默认值',
              'raw': fields}
    if rows(fields, 101):
        group = scalar(message(fields, 101), 1)
        result['enumGroupId'] = group
        result['enumGroup'] = enums.get(str(group))
    if rows(fields, 102):
        container = message(fields, 102)
        result['containerMembers'] = [
            {'field': r['f'], 'descriptor': descriptor(r.get('m', []), enums)} for r in container]
    if rows(fields, 103):
        result['genericChoices'] = [
            {'choiceIndex': i, 'descriptor': descriptor(r.get('m', []), enums)}
            for i, r in enumerate(rows(message(fields, 103), 1))]
    result['validationMetadataRaw'] = rows(fields, 7)
    return result


def compile_enums(fields, text):
    result = {}
    for r in rows(message(fields, 1), 1):
        f = r.get('m', []); gid = scalar(f, 1)
        options = []
        for option in rows(f, 2):
            item = option.get('m', [])
            options.append({'value': scalar(item, 1), 'name': text.get(scalar(item, 3), ''), 'raw': item})
        result[str(gid)] = {'id': gid, 'name': text.get(scalar(f, 4), ''), 'options': options}
    return result


def compile_menus(fields, text):
    by_key = defaultdict(list); trees = []
    def walk(f, path, tree_id):
        label = text.get(scalar(f, 5), '')
        path = path + ([label] if label else [])
        for item in rows(f, 3):
            ident = identity(message(item.get('m', []), 1))
            record = {'treeId': tree_id, 'path': path}
            if record not in by_key[key(ident[:4], ident[4])]:
                by_key[key(ident[:4], ident[4])].append(record)
        for child in rows(f, 2):
            walk(child.get('m', []), path, tree_id)
    for r in rows(fields, 3):
        f = r.get('m', []); tree_id = scalar(f, 1)
        root = message(f, 2)
        trees.append({'treeId': tree_id, 'name': text.get(scalar(root, 5), '')})
        walk(root, [], tree_id)
    return dict(by_key), trees


class ProseParser(HTMLParser):
    """Extract node sections and table cells, never execute source HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []; self.current = None; self.heading = None
        self.buffer = []; self.cell = None; self.row = None; self.in_table = False
        self.section = ''; self.mode = ''

    def handle_starttag(self, tag, attrs):
        if tag in ('h1', 'h2'):
            self.heading = tag; self.buffer = []
        elif tag == 'table':
            self.in_table = True
        elif tag == 'tr':
            self.row = []
        elif tag in ('td', 'th'):
            self.cell = []
        elif tag == 'p' and not self.in_table and not self.heading:
            self.buffer = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif self.heading or not self.in_table:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag in ('h1', 'h2') and self.heading == tag:
            value = ''.join(self.buffer).strip(); self.heading = None; self.buffer = []
            if tag == 'h1':
                self.section = value; self.current = None
            else:
                value = re.sub(r'^\s*\d+\s*[.．、]\s*', '', value)
                self.current = {'name': value, 'section': self.section, 'function': [], 'parameterRows': []}
                self.entries.append(self.current); self.mode = ''
        elif tag in ('td', 'th') and self.cell is not None:
            if self.row is not None:
                self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.current is not None and any(self.row):
                self.current['parameterRows'].append(self.row)
            self.row = None
        elif tag == 'table':
            self.in_table = False
        elif tag == 'p' and not self.in_table and not self.heading:
            value = ''.join(self.buffer).strip(); self.buffer = []
            if value in ('节点功能', '节点参数'):
                self.mode = value
            elif self.current is not None and self.mode == '节点功能' and value:
                self.current['function'].append(value)


def official_entries():
    records = []; sources = []
    for p in sorted((ROOT / 'docs/official-docs/chapters').glob('*.json')):
        meta = read(p)
        if meta.get('title') not in FAMILIES.values() or '节点介绍' not in meta.get('hierarchy', []):
            continue
        source = ROOT / meta['source']['htmlPath']
        if sha(source) != meta['source']['htmlSha256']:
            raise ValueError(f'OFFICIAL_SNAPSHOT_HASH_MISMATCH:{source}')
        parser = ProseParser(); parser.feed(source.read_text(encoding='utf-8-sig'))
        sources.append({'path': source.relative_to(ROOT).as_posix(), 'sha256': sha(source), 'url': meta['url']})
        for r in parser.entries:
            r.update(chapterId=meta['pathId'], hierarchy=meta['hierarchy'], family=meta['title'],
                     url=meta['url'], source=source.relative_to(ROOT).as_posix())
            records.append(r)
    return records, sources


def official_context(menu_root):
    # These are native menu names, not an inferred equivalence between category kinds.
    for fragment, title in [('服务端', '服务器节点'), ('操控运动器', '角色操控技能节点图'),
                            ('角色技能', '角色技能节点图'), ('造物技能', '造物技能节点图'),
                            ('AI状态', '造物状态节点图'), ('AI决策', '造物状态决策节点图'),
                            ('Filter', '过滤器节点图')]:
        if fragment in menu_root:
            return title
    return None


def norm_name(value):
    return re.sub(r'\s+', '', value.replace('（', '(').replace('）', ')'))


def source_pointer(path, token):
    p = ROOT / path
    lines = p.read_text(encoding='utf-8-sig').splitlines()
    found = [i + 1 for i, line in enumerate(lines) if token in line]
    if not found:
        raise ValueError(f'SOURCE_SYMBOL_MISSING:{token}')
    return {'path': path, 'line': found[0], 'sha256': sha(p), 'symbol': token}


def writer_sources():
    path = 'tools/editor-bridge/Adapter/AuthoringGraph.cs'
    profile = 'tools/editor-bridge/Adapter/EditorBindingProfile.Generated.cs'
    aliases = dict(re.findall(r'\{ "([^"]+)", "([^"]+)" \}', (ROOT / profile).read_text(encoding='utf-8')))
    slots = {}
    for slot, storage, tag, setter, getter in [
        ('uint', 1, 'uint', 'LhkKKbraAbs', 'cPOKKedklwd'),
        ('int', 2, 'int', 'c84KKE8ihrN', 'ilqKKrw7dhN'),
        ('bool', 3, 'bool', 'CHHKK434xan', 'RJCKKnWqvLO'),
        ('float', 4, 'float', 'SH7KKvk8cxe', 'ngMKKCVBuMA'),
        ('string', 5, 'string', 'MfLKK0bLIju', 'ur7KK2NiYZ4'),
        ('enum', 6, 'uint', 'X8oKKHB87Ue', 'cPOKKedklwd')]:
        slots[slot] = {'storageKind': storage, 'payloadTag': tag,
                       'setter': aliases[setter], 'getter': aliases[getter],
                       'evidence': source_pointer(path, f'"{slot}"=>(')}
    base = '.runtime/editor-catalog/resolved-565dda11/'
    return {'slots': slots, 'profile': source_pointer(profile, '{ "BWmKmyL3bM7",'),
            'addNodeMethod': aliases['BWmKmyL3bM7'], 'definitionHandle': aliases['U0oKESVcL9L'],
            'addNode': source_pointer(path, 'if(action=="add-node")'),
            'wire': source_pointer(path, 'if(action=="connect" || action=="disconnect") {'),
            'genericLink': source_pointer(path, '// 2026-10-06: a GENERIC end'),
            'valuePreflight': source_pointer(path, 'void AuthorPreflightPinValue'),
            'composite': {
                'status': 'native-source-located-no-authoring-adapter-or-runtime-acceptance',
                'official': 'https://act-webstatic.hoyoverse.com/ugc-tutorial/knowledge/sea/zh-cn/mhty17iqeht0/content.html',
                'constructor': source_pointer(base + 'bdbYGlXPnjBEKi4qQ11X.hWfunLXP1LCpUbtnvrZ2.cs', 'internal static O6Xe5UXWOepEMsrsi0jb C2cXojsMIKF'),
                'steps': ['按资源上下文分配 definition handle', '复制 kernel handle',
                          '生成唯一名称和节点分类', '初始化关联子图 n4CXWiMUQ7t', '按参数决定注册 xAGPvIqDKrj'],
                'constraint': '官方文档：仅服务器节点图。必须同时构造子图和对外虚拟引脚，不能只增加一个内置 definitionId。'},
            'externalAssets': {
                'status': 'native-model-located-no-import-adapter-or-runtime-acceptance',
                'model': source_pointer(base + 'ERtUZqX8Rh1I3iupJUFH.PbUpWEX8ENDqoj9ZiRUR.cs', 'resourceItemTextType'),
                'kinds': ['EXTERNAL_ASSETS_PACKAGE', 'EXTERNAL_ASSETS_BP', 'EXTERNAL_ASSETS_NODE'],
                'constraint': '资源引用类别；资源身份、依赖和导入流程须成立。不是第六种内置节点算法。'}}


def build(live_path=LIVE, output=OUTPUT):
    output = project_output(output)
    live = read(live_path)
    if not live.get('completeForCatalog'):
        raise ValueError('LIVE_DOMAIN_NOT_COMPLETE')
    spec = importlib.util.spec_from_file_location('node_resource_decoder', ROOT / 'tools/editor-catalog/decode-mihoyobin.py')
    decoder = importlib.util.module_from_spec(spec); spec.loader.exec_module(decoder)
    sources = []
    def fresh(frozen_path):
        pinned = read(frozen_path); path = Path(pinned['path'])
        decoded = decoder.decode(path, 32 * 1024 * 1024)
        if not decoded.get('ok') or decoded['source_sha256'] != pinned['source_sha256']:
            raise ValueError(f'INSTALLED_RESOURCE_DRIFT:{path}')
        sources.append({'path': str(path), 'sha256': decoded['source_sha256'],
                        'decodedSha256': decoded['decoded_sha256'], 'bytes': decoded['size']})
        return decoded
    t = fresh(next(FROZEN.glob('TextMap__CHS__*.json')))
    text = {scalar(r.get('m', []), 2): string(r.get('m', []), 3) for r in rows(t['fields'], 2)}
    global_data = fresh(next(FROZEN.glob('Beyond__BeyondGlobal__*.json')))
    enums = compile_enums(global_data['fields'], text)
    menus, trees = compile_menus(global_data['fields'], text)
    resource_index = {}; resources = []
    for frozen in sorted(FROZEN.glob('Beyond__Node__*.json')):
        decoded = fresh(frozen); f = decoded['fields']
        resource = {'path': decoded['path'], 'sha256': decoded['source_sha256'],
                    'decodedSha256': decoded['decoded_sha256'], 'fields': f}
        resources.append(resource)
        for variant in rows(f, 4):
            ident = identity(message(variant.get('m', []), 1)); stable = key(ident[:4], ident[4])
            if stable in resource_index:
                raise ValueError(f'RESOURCE_IDENTITY_COLLISION:{stable}')
            resource_index[stable] = (resource, variant)
    prose, doc_sources = official_entries()
    by_name = defaultdict(list)
    for record in prose:
        by_name[norm_name(record['name'])].append(record)
    nodes = []; discrepancies = []
    for entry in sorted(live['nodes'], key=lambda n: (*n['category'], n['id'])):
        stable = key(entry['category'], entry['id']); definition = entry['definition']
        if definition.get('pinsTruncated'):
            raise ValueError(f'TRUNCATED_PINS:{stable}')
        resource, native_variant = resource_index[stable]; f = resource['fields']
        raw_pins = {}
        for field in PIN_FIELDS:
            for row in rows(f, field):
                raw = row.get('m', []); sig = message(raw, 3)
                raw_pins[(scalar(sig, 1), scalar(sig, 2))] = raw
        paths = menus.get(stable, [])
        contexts = {official_context(m['path'][0]) for m in paths if m['path']}
        if entry['category'][1] == 20000:
            contexts.add('服务器节点')
        family = FAMILIES.get(scalar(f, 203), '未归类')
        docs = [r for r in by_name[norm_name(definition['name'])]
                if r['hierarchy'][-1] in contexts and r['family'] == family]
        ports = []; used_resource_pins = set()
        for pin in definition['pins']:
            sig = (pin['kind'], pin['index'])
            # Native resource f3 addresses the kernel pin. Editor UI indexes can
            # differ (e.g. client branch 200056: editor 3:0 -> kernel 3:1).
            kernel_sig = (pin['kernelKind'], pin['kernelIndex'])
            raw = raw_pins.get(kernel_sig)
            if raw is None:
                discrepancies.append({'key': stable, 'pin': sig, 'reason': 'live-pin-not-in-resource'})
            else:
                used_resource_pins.add(kernel_sig)
                resource_name = text.get(scalar(raw, 7), '')
                if resource_name != pin['name']:
                    discrepancies.append({'key': stable, 'pin': sig, 'reason': 'resource-live-name-mismatch',
                                          'resource': resource_name, 'live': pin['name']})
            desc = descriptor(message(raw or [], 4), enums) if raw is not None and pin['kind'] in (3, 4, 5) else None
            if desc and (desc['serverParamType'], desc['genericId']) != (pin['serverParamType'], pin['fbGKY8GZn68']):
                discrepancies.append({'key': stable, 'pin': sig, 'reason': 'resource-live-type-mismatch'})
            ports.append({'key': f'{sig[0]}:{sig[1]}', 'kind': sig[0], 'index': sig[1], 'name': pin['name'],
                          'resourceKernelPin': f'{kernel_sig[0]}:{kernel_sig[1]}',
                          'live': pin, 'descriptor': desc, 'resourceRaw': raw,
                          'required': None, 'requiredEvidence': '未将未解释标志推定为必填'})
        for missing in sorted(set(raw_pins) - used_resource_pins):
            discrepancies.append({'key': stable, 'pin': missing, 'reason': 'resource-pin-not-in-live'})
        nodes.append({'key': stable, 'definitionId': entry['id'], 'category': entry['category'],
                      'graphKind': entry['category'][1], 'name': definition['name'], 'family': family,
                      'description': definition['description'], 'menuPaths': paths,
                      'menuVisibility': 'listed' if paths else 'registered-but-not-in-global-menu',
                      'resource': {k: v for k, v in resource.items() if k != 'fields'},
                      'resourceName': text.get(scalar(f, 206), ''),
                      'keywords': [string(r.get('m', []), 1) for r in rows(f, 208)],
                      'kernelMappingRaw': native_variant, 'dynamicPortsRaw': rows(f, 107),
                      'classificationRaw': [r for r in f if r['f'] in (203, 204, 205)],
                      'ports': ports, 'official': docs, 'runtimeVerified': False})
    live_keys = {n['key'] for n in nodes}
    if len(live_keys) != len(nodes) or len(nodes) != live['variantCount']:
        raise ValueError('LIVE_IDENTITY_COUNT_MISMATCH')
    writers = writer_sources()
    stats = {'definitions': len({n['definitionId'] for n in nodes}), 'variants': len(nodes),
             'ports': sum(len(n['ports']) for n in nodes), 'enumGroups': len(enums),
             'byGraphKind': dict(Counter(str(n['graphKind']) for n in nodes)),
             'byFamily': dict(Counter(n['family'] for n in nodes)),
             'serverByFamily': dict(Counter(n['family'] for n in nodes if n['graphKind'] == 20000)),
             'withOfficialFunction': sum(any(d['function'] for d in n['official']) for n in nodes),
             'withDynamicPorts': sum(bool(n['dynamicPortsRaw']) for n in nodes),
             'withGenericChoices': sum(any(p['descriptor'] and p['descriptor'].get('genericChoices') for p in n['ports']) for n in nodes),
             'registeredNotInMenu': sum(not n['menuPaths'] for n in nodes),
             'pinDiscrepancies': len(discrepancies), 'installedResourcesDecoded': len(sources)}
    result = {'schemaVersion': 1, 'observedUtc': live['observedUtc'], 'stats': stats,
              'evidence': {'live': {'path': str(Path(live_path).resolve()), 'sha256': sha(live_path), 'runId': live['runId']},
                           'installed': sources, 'officialSnapshots': doc_sources},
              'nodes': nodes, 'enumGroups': enums, 'menus': trees, 'writer': writers,
              'discrepancies': discrepancies,
              'menuReferencesOutsideLive': sorted(set(menus) - live_keys),
              'resourceVariantsOutsideLive': sorted(set(resource_index) - live_keys),
              'limits': ['资源和官方文档描述不是逐节点运行验收', '未显式记录的默认值和必填规则保持未知',
                         '泛型需物化并读回；候选参数槽不能替代 live slots',
                         '外部资产与复合节点的原生入口已定位，自动创建接入尚未完成'],
              'nativeMutationsPerformed': False, 'runtimeVerified': False}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'catalog.json').write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps({k: v for k, v in result.items() if k not in ('nodes', 'enumGroups', 'evidence')}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


class Catalog:
    def __init__(self, path=OUTPUT / 'catalog.json'):
        self.data = read(path)
        self.nodes = self.data['nodes']
        self.index = {(n['graphKind'], n['definitionId']): n for n in self.nodes}
        if len(self.index) != len(self.nodes):
            raise ValueError('UNSUPPORTED_CATEGORY_COLLISION')

    def require(self, graph_kind, definition_id):
        try:
            return self.index[(graph_kind, definition_id)]
        except KeyError as exc:
            raise ValueError(f'NODE_NOT_IN_CATEGORY:{graph_kind}:{definition_id}') from exc

    def search(self, query='', graph_kind=None, family=None):
        return [n for n in self.nodes if (graph_kind is None or n['graphKind'] == graph_kind)
                and (family is None or n['family'] == family)
                and query.casefold() in json.dumps([n['name'], n['definitionId'], n['keywords'],
                    n['menuPaths'], [d['function'] for d in n['official']]], ensure_ascii=False).casefold()]

    def contract_store(self, graph_kind):
        from tools.gameplan.contracts import ContractStore, NodeDefinition, Port
        definitions = {}
        for n in self.nodes:
            if n['graphKind'] != graph_kind:
                continue
            ports = tuple(Port(p['kind'], p['index'], 'input' if p['kind'] in (1, 3) else 'output',
                               p['live']['serverParamType'], p['live']['fbGKY8GZn68'], p['name'],
                               'unmaterialized' if p['live']['serverParamType'] == 0 else 'concrete')
                          for p in n['ports'])
            definitions[n['definitionId']] = NodeDefinition(n['definitionId'], n['name'], graph_kind, ports)
        if not definitions:
            raise ValueError(f'UNKNOWN_GRAPH_KIND:{graph_kind}')
        return ContractStore(definitions, source=f'node-workbench:{graph_kind}')
