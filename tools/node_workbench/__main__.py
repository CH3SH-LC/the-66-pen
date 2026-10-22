"""本地节点导航：route/cluster → explain → recipe；枚举查询：enums → enum。"""
import argparse
import json

from .catalog import Catalog, FAMILIES, LIVE, OUTPUT, build, project_output
from .recipes import compatible_edge, recipe, tab_shop_example, value_candidate
from .render import render
from .discovery import Discovery, build_discovery
from .explain import describe_node, describe_enum, enum_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', default=str(OUTPUT / 'catalog.json'))
    commands = parser.add_subparsers(dest='command', required=True)
    b = commands.add_parser('build'); b.add_argument('--live', default=str(LIVE)); b.add_argument('--out', default=str(OUTPUT))
    s = commands.add_parser('search'); s.add_argument('query', nargs='?', default=''); s.add_argument('--graph-kind', type=int)
    s.add_argument('--family', choices=list(FAMILIES.values())); s.add_argument('--limit', type=int, default=30)
    for name in ('show', 'recipe'):
        p = commands.add_parser(name); p.add_argument('definition_id', type=int); p.add_argument('--graph-kind', type=int, required=True)
    p = commands.add_parser('explain', help='中文说明、端口阅读和下一步；不发送编辑器命令')
    p.add_argument('definition_id', type=int); p.add_argument('--graph-kind', type=int, required=True)
    p.add_argument('--port'); p.add_argument('--offset', type=int, default=0); p.add_argument('--limit', type=int, default=12)
    for name in ('enums', 'enum'):
        p = commands.add_parser(name, help='查询枚举表及其真实选项值')
        if name == 'enums':
            p.add_argument('query', nargs='?', default='')
        else:
            p.add_argument('enum_id', type=int)
        p.add_argument('--offset', type=int, default=0); p.add_argument('--limit', type=int, default=12)
    e = commands.add_parser('edge'); e.add_argument('--graph-kind', type=int, required=True)
    e.add_argument('--from-id', type=int, required=True); e.add_argument('--from-port', required=True)
    e.add_argument('--to-id', type=int, required=True); e.add_argument('--to-port', required=True)
    v = commands.add_parser('value'); v.add_argument('definition_id', type=int)
    v.add_argument('--graph-kind', type=int, required=True); v.add_argument('--port-index', type=int, required=True)
    v.add_argument('--value-json', required=True)
    commands.add_parser('example')
    commands.add_parser('organize', help='从已实读的目录重建两层导航，不连接游戏')
    commands.add_parser('groups', help='第一层：原生分组摘要')
    g=commands.add_parser('group');g.add_argument('group')
    for name in ('route','cluster'):
        c=commands.add_parser(name);c.add_argument('query' if name=='route' else 'cluster')
        c.add_argument('--graph-kind',type=int);c.add_argument('--group')
        c.add_argument('--limit',type=int,default=5 if name=='route' else 30)
        if name=='cluster':c.add_argument('--offset',type=int,default=0)
    a = parser.parse_args()
    if a.command in ('groups','group','route','cluster'):
        from pathlib import Path
        d=Discovery(Path(a.catalog).parent/'discovery')
        if a.command=='groups':result={'groups':[{k:v for k,v in g.items() if k not in ('clusters','mechanism')} for g in d.index['groups']], 'next':'group <id> → cluster <id> → recipe <definitionId> --graph-kind <kind>', 'variants':d.index['variants']}
        elif a.command=='group':result=d.group(a.group)
        elif a.command=='route':result=d.route(a.query,a.graph_kind,a.group,a.limit)
        else:result=d.cluster(a.cluster,a.graph_kind,a.group,a.offset,a.limit)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if a.command == 'build':
        data = build(a.live, a.out); directory = project_output(a.out)
        catalog = Catalog(directory / 'catalog.json')
        recipes = [recipe(catalog, n['graphKind'], n['definitionId']) for n in catalog.nodes]
        (directory / 'recipes.json').write_text(json.dumps(recipes, ensure_ascii=False, indent=1), encoding='utf-8')
        example = tab_shop_example(catalog)
        (directory / 'tab-shop-example.json').write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding='utf-8')
        data['discovery']=build_discovery(catalog,directory)
        render(data, directory / 'index.html')
        result = {'ok': True, 'output': str(directory), **data['stats']}
    else:
        catalog = Catalog(a.catalog)
        if a.command == 'organize':
            from pathlib import Path
            directory=project_output(Path(a.catalog).resolve().parent)
            data=catalog.data;data['discovery']=build_discovery(catalog,directory)
            render(data,directory/'index.html')
            result={'ok':True,'groups':len(data['discovery']['groups']),'clusters':len(data['discovery']['clusters']),'variants':len(catalog.nodes),'index':str(directory/'discovery/index.json')}
        elif a.command == 'search':
            found = catalog.search(a.query, a.graph_kind, a.family)
            result = {'total': len(found), 'nodes': [{k: n[k] for k in ('key', 'definitionId', 'name', 'family', 'graphKind', 'menuPaths')} for n in found[:max(0, a.limit)]]}
        elif a.command == 'show':
            result = catalog.require(a.graph_kind, a.definition_id)
        elif a.command == 'explain':
            result = describe_node(catalog, a.graph_kind, a.definition_id, a.port, a.offset, a.limit)
        elif a.command == 'enums':
            result = enum_search(catalog, a.query, a.offset, a.limit)
        elif a.command == 'enum':
            result = describe_enum(catalog, a.enum_id, a.offset, a.limit)
        elif a.command == 'recipe':
            result = recipe(catalog, a.graph_kind, a.definition_id)
        elif a.command == 'edge':
            result = compatible_edge(catalog, a.graph_kind, a.from_id, a.from_port, a.to_id, a.to_port)
        elif a.command == 'value':
            result = value_candidate(catalog, a.graph_kind, a.definition_id, a.port_index, json.loads(a.value_json))
        else:
            result = tab_shop_example(catalog)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
