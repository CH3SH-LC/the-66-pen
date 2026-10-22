"""Validate native finish export; passing does not prove game execution."""
import argparse
import importlib.util
import json
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location('audit_helpers', Path(__file__).with_name('verify-runtime-audit.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
NAME = 'MW_Course_Finish_20260916'
TIMER = 'MW_FINISH_POLL_20260916'
DEFS = dict(enumerate([71,73,14,2,1,79,83,14,2,248,509,804,99,225,244,231,9,233,226,2,82,1,77],1))
FLOW = [(1,4),(4,5),(5,6),(7,9),(9,11),(11,20),(20,21),(21,22),(22,23)]
DATA = [(1,0,3,0),(2,0,3,1),(3,0,4,0),(2,0,6,0),
        (7,2,8,0),(8,0,9,0),(10,0,11,0),(11,0,12,0),(12,0,13,0),
        (13,0,15,0),(14,0,15,1),(15,0,16,0),(13,0,17,0),
        (17,1,18,0),(16,0,19,0),(18,0,19,1),(19,0,20,0),(2,0,21,0)]
EDGES = {((a,2,0),(b,1,0)) for a,b in FLOW} | {((a,4,i),(b,3,j)) for a,i,b,j in DATA}

def verify(path):
    r = h.inspect_graph.inspect(Path(path))
    check = h._require
    check(r['name'] == NAME, 'Wrong graph name')
    check(r['nodeCount'] == 23 and {n['id']:n['definition'] for n in r['nodes']} == DEFS, 'Wrong definitions')
    check(isinstance(r['graphId'],int) and r['graphId'] > 0, 'Missing graph id')
    actual = {(tuple(e['source']),tuple(e['target'])) for e in r['directedEdges']}
    check(len(r['directedEdges']) == 27 and actual == EDGES, 'Wrong directed edges')
    nodes = {n['id']:n for n in r['nodes']}
    def pin(n,i=0,kind='IN_PARAM'):
        return h._pins(nodes[n],kind)[i]
    def floating(n,i,expected):
        p = pin(n,i)
        check(p.get('type') == 5 and h._type_tag(p) == 'S_FLOAT', f'Float type {n}/{i}')
        value = h._actual(p)
        check('val_float' in value and math.isclose(value['val_float'].get('float',0),expected,abs_tol=1e-6), f'Float constant {n}/{i}')
    for n,i,v in [(14,0,17),(14,1,2.5),(14,2,0),(16,1,2),(18,1,2.4)]:
        floating(n,i,v)
    for n,i in [(6,2),(23,0)]:
        p = pin(n,i)
        check(p.get('type') == 4 and h._actual(p).get('val_enum',{}).get('enum') == '1', f'True bool required {n}/{i}')
    for n,i in [(6,1),(8,1),(21,1)]:
        check(h._literal(pin(n,i)) == TIMER, f'Timer identity {n}')
    check(h._literal(pin(5)) == 'MW_FINISH_MONITOR_STARTED_20260916', 'Start marker')
    check(h._literal(pin(22)) == 'MW_FINISH_REACHED_20260916', 'Reached marker')
    p = pin(6,3)
    check(p.get('type') == 10 and h._type_tag(p) == 'S_FLOAT_LIST', 'Timer sequence type')
    elements = h._actual(p)['val_list']['elements']
    check(len(elements) == 1 and elements[0].get('type_def',{}).get('server_side',{}).get('type_tag') == 'S_FLOAT'
          and elements[0]['val_float']['float'] == .25, 'Poll period')
    for n,i,code in [(4,0,4),(9,0,4),(12,0,1),(13,0,1),(15,0,12),(15,1,12),
                     (17,0,12),(19,0,4),(19,1,4),(20,0,4),(21,0,1)]:
        check(pin(n,i).get('type') == code, f'Input type {n}/{i}')
    for n,i,kind,code,tag in [(3,0,'IN_PARAM',1,'S_ENTITY'),(3,1,'IN_PARAM',1,'S_ENTITY'),
                             (11,0,'IN_PARAM',13,'S_ENTITY_LIST'),(11,0,'OUT_PARAM',1,'S_ENTITY')]:
        p = pin(n,i,kind)
        check(p.get('type') == code and h._type_tag(p) == tag, f'Resolved type {n}/{i}/{kind}')
    return dict(ok=True,name=NAME,graphId=r['graphId'],sha256=r['sha256'],nodeCount=23,edgeCount=27,
                goal=[17,2.5,0],radius=2,minimumHeight=2.4,pollSeconds=.25,runtimeVerified=False)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path',type=Path)
    p.add_argument('--output',type=Path)
    args = p.parse_args()
    result = json.dumps(verify(args.path),ensure_ascii=False,indent=2)
    if args.output:
        args.output.write_text(result+'\n',encoding='utf-8')
    print(result)
