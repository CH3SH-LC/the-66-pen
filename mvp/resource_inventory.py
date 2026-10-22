"""Deterministic internal inventory; never imports upstream code or verifies a game."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = {
    'scene': 'mvp/scene.json',
    'bindings': 'mvp/finish/bindings.pending.json',
    'finish': 'mvp/finish/finish.unbound.ir.json',
    'catalog': 'third_party/UGC-File-Generate-Utils/config/block_config.py',
}


class InventoryError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InventoryError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def vector(value, field, positive=False):
    require(isinstance(value, list) and len(value) == 3, field + ': expected three numbers')
    require(all(number(v) for v in value), field + ': numbers must be finite, not bool')
    require(not positive or all(v > 0 for v in value), field + ': scale must be positive')
    return value


def build_inventory(root=ROOT):
    root = Path(root).resolve()
    sources, docs = {}, {}
    for name, rel in SOURCE_PATHS.items():
        data = (root / rel).read_bytes()
        sources[name] = {'path': rel, 'sha256': hashlib.sha256(data).hexdigest()}
        if name != 'catalog':
            docs[name] = json.loads(data)
            require(isinstance(docs[name], dict), name + ': expected object')
    scene, bindings, finish = docs['scene'], docs['bindings'], docs['finish']
    templates, entities = scene.get('templates'), scene.get('entities')
    require(isinstance(templates, dict) and templates, 'scene.templates: expected nonempty object')
    require(isinstance(entities, list) and entities, 'scene.entities: expected nonempty list')
    catalog = {}
    for key, value in templates.items():
        require(key.isdecimal() and str(int(key)) == key and int(key) > 0, 'template key must be canonical positive integer')
        require(isinstance(value, dict), 'template record must be object')
        size = value.get('size_units')
        require(number(size) and size > 0, 'template size_units must be positive finite number')
        catalog[key] = {'logicalId': 'builtin:' + key, 'templateId': int(key),
                        'name': value.get('name'), 'declaredSizeUnits': size,
                        'declarationSource': sources['scene'], 'referenceCatalog': sources['catalog'],
                        'catalogContentValidated': False, 'usedBy': [],
                        'measuredBounds': None, 'collision': None, 'materialEffect': None}
    names, indices, instances = set(), set(), []
    for entity in entities:
        require(isinstance(entity, dict), 'entity must be object')
        name, index, tid = entity.get('name'), entity.get('index'), entity.get('template_id')
        require(isinstance(name, str) and bool(name.strip()), 'entity.name must be nonempty')
        require(name not in names, 'duplicate entity name: ' + name)
        require(type(index) is int and index >= 0, 'entity.index must be nonnegative integer, not bool')
        require(index not in indices, 'duplicate entity index: ' + str(index))
        require(type(tid) is int and str(tid) in catalog, 'missing or invalid template reference: ' + str(tid))
        names.add(name); indices.add(index)
        transform = {field: vector(entity.get(field), name + '.' + field, field == 'scale')
                     for field in ('position', 'rotation', 'scale')}
        catalog[str(tid)]['usedBy'].append(name)
        instances.append({'logicalId': name, 'index': index, 'role': entity.get('role'),
                          'templateId': tid, 'requires': ['builtin:' + str(tid)],
                          'transform': transform, 'measuredBounds': None,
                          'collision': None, 'materialEffect': None})
    for item in catalog.values():
        item['usedBy'].sort()
    require(isinstance(finish.get('nodes'), list), 'finish.nodes must be a list')
    require(all(isinstance(n, dict) for n in finish['nodes']), 'finish nodes must be objects')
    required = ('graphId', 'graphMode', 'goalEntityGuid', 'triggerId')
    guards = ('runtimeTypeGuardImplemented', 'triggerIdGuardImplemented', 'repeatEntryGuardImplemented')
    return {
        'schema': 'internal-resource-inventory/1',
        'scope': 'offline inventory only; not official schema or deployable package',
        'sceneId': scene.get('scene_id'), 'sources': sources,
        'templates': [catalog[k] for k in sorted(catalog, key=int)],
        'instances': sorted(instances, key=lambda e: e['index']),
        'counts': {'templates': len(catalog), 'instances': len(instances)},
        'nominalLayoutAssumptions': {'status': 'declared-not-measured',
            'coordinateSystem': scene.get('coordinate_system'), 'layoutIntent': scene.get('layout_intent'),
            'constraints': scene.get('constraints'),
            'warning': 'size_units and scale do not establish actual bounds, collision, or jump feasibility'},
        'finish': {'sourceStatus': bindings.get('status'),
            'declaredBindings': {k: bindings.get(k) for k in required},
            'missingBindings': [k for k in required if bindings.get(k) in (None, '')],
            'guardDeclarations': {k: bindings.get(k) for k in guards},
            'missingGuardDeclarations': [k for k in guards if bindings.get(k) is not True],
            'nodeTypes': [n.get('type') for n in finish['nodes']],
            'requiredConditions': bindings.get('requiredConditions'),
            'conditionEvidenceDeclaration': bindings.get('conditionEvidence'),
            'verifiedBindingEvidence': None, 'verifiedGuardEvidence': None,
            'deploymentAllowed': False,
            'warning': 'Filled IDs, true flags, or evidence labels are declarations, never runtime proof'},
        'gameLoop': {'unprovidedConfiguration': ['spawn', 'failureRecovery', 'feedback'],
            'basis': 'These three source JSON files do not define a complete spawn/failure/feedback contract',
            'runtimeVerified': False},
        'runtimeVerified': False, 'runtimeEvidence': None,
    }


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InventoryError(message)


def main(argv=None, root=ROOT):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--output', help='New .json under .runtime/mvp/resource-inventory/; default stdout')
        args = parser.parse_args(argv)
        root = Path(root).resolve()
        result = build_inventory(root)
        text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
        if args.output:
            target = Path(args.output)
            target = (root / target).resolve() if not target.is_absolute() else target.resolve()
            output_root = (root / '.runtime/mvp/resource-inventory').resolve()
            require(output_root.is_relative_to(root) and target.is_relative_to(output_root)
                    and target.suffix.lower() == '.json',
                    'output must be a .json file under .runtime/mvp/resource-inventory/')
            require(target not in {(root / p).resolve() for p in SOURCE_PATHS.values()}, 'output cannot overwrite source')
            # Exclusive create also protects other project artifacts and symlink targets.
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8', newline='\n') as output:
                output.write(text)
        else:
            print(text, end='')
        return 0
    except (InventoryError, OSError, ValueError, TypeError, OverflowError) as exc:
        print(json.dumps({'ok': False, 'error': {'code': 'RESOURCE_INVENTORY_ERROR', 'message': str(exc)}},
                         ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
