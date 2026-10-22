"""Independently check the native character-position export, not game execution."""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit_helpers', Path(__file__).with_name('verify-runtime-audit.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
NAME = 'MW_Character_Position_20260916'
TIMER = 'MW_POSITION_ONESHOT_20260916'
MARKER = 'MW_CHARACTER_POSITION_NEXT_20260916'
DEFS = dict(enumerate([71,73,14,2,79,83,14,2,248,509,258,509,99,180,1,1], 1))
EDGES = {
    ((1,4,0),(3,3,0)), ((2,4,0),(3,3,1)), ((3,4,0),(4,3,0)),
    ((1,2,0),(4,1,0)), ((4,2,0),(5,1,0)), ((2,4,0),(5,3,0)),
    ((6,4,2),(7,3,0)), ((7,4,0),(8,3,0)), ((6,2,0),(8,1,0)),
    ((8,2,0),(10,1,0)), ((9,4,0),(10,3,0)), ((10,4,0),(11,3,0)),
    ((11,4,0),(12,3,0)), ((10,2,0),(12,1,0)), ((12,4,0),(13,3,0)),
    ((13,4,0),(14,3,0)), ((14,4,0),(16,3,0)), ((12,2,0),(15,1,0)),
    ((15,2,0),(16,1,0)),
}

def verify(path):
    r = h.inspect_graph.inspect(Path(path))
    require = h._require
    require(r['name'] == NAME, 'Wrong graph name')
    require(r['nodeCount'] == 16 and {n['id']:n['definition'] for n in r['nodes']} == DEFS, 'Wrong node definitions')
    require(isinstance(r['graphId'], int) and r['graphId'] > 0, 'Missing graph id')
    edges = {(tuple(e['source']),tuple(e['target'])) for e in r['directedEdges']}
    require(len(r['directedEdges']) == 19 and edges == EDGES, 'Wrong directed edges')
    nodes = {n['id']:n for n in r['nodes']}
    def pin(n, kind, i=0):
        return h._pins(nodes[n], kind)[i]
    def typed(n, kind, i, code, tag):
        p = pin(n, kind, i)
        require(p.get('type') == code and h._type_tag(p) == tag, f'Wrong type {n}/{kind}/{i}: {p}')
    # Native exports omit fixed output pins and unmodified default values.
    # Generic resolved pins must carry their explicit selected type; fixed
    # definitions were separately read from the current native node catalog.
    for n,kind,i in [(3,'IN_PARAM',0),(3,'IN_PARAM',1),
                     (10,'OUT_PARAM',0),(12,'OUT_PARAM',0)]:
        typed(n,kind,i,1,'S_ENTITY')
    for n,kind in [(10,'IN_PARAM'),(12,'IN_PARAM')]:
        typed(n,kind,0,13,'S_ENTITY_LIST')
    typed(14,'IN_PARAM',0,12,'S_VECTOR')
    for n,kind,i in [(5,'IN_PARAM',1),(7,'IN_PARAM',0),(7,'IN_PARAM',1),
                     (14,'OUT_PARAM',0),(15,'IN_PARAM',0)]:
        typed(n,kind,i,6,'S_STRING')
    for n,i,code in [(4,0,4),(8,0,4),(5,0,1),(11,0,1),(13,0,1),(16,0,6)]:
        require(pin(n,'IN_PARAM',i).get('type') == code, f'Wrong fixed input type {n}/{i}')
    require(h._literal(pin(5,'IN_PARAM',1)) == TIMER and h._literal(pin(7,'IN_PARAM',1)) == TIMER, 'Wrong timer name')
    require(pin(5,'IN_PARAM',2).get('type') == 4, 'Timer loop input must be bool')
    require(pin(5,'IN_PARAM',2)['value'].get('val_enum') == {}, 'Timer must not loop')
    typed(5,'IN_PARAM',3,10,'S_FLOAT_LIST')
    elements = pin(5,'IN_PARAM',3)['value']['val_list']['elements']
    require(len(elements) == 1 and elements[0].get('type_def',{}).get('server_side',{}).get('type_tag') == 'S_FLOAT'
            and elements[0]['val_float']['float'] == 3.0, 'Timer must be [3.0]')
    require(h._literal(pin(15,'IN_PARAM')) == MARKER, 'Wrong diagnostic marker')
    require(h._literal(pin(16,'IN_PARAM')) == '', 'Position print must use wired value')
    return {'ok':True, 'name':NAME, 'graphId':r['graphId'], 'sha256':r['sha256'],
            'nodeCount':16, 'edgeCount':19, 'runtimeVerified':False, 'settlementEnabled':False}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = json.dumps(verify(args.path), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result+'\n', encoding='utf-8')
    print(result)
