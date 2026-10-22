"""Inspect the preserved successful demo save; never open a live game session."""
import hashlib
import importlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
BASELINE_GIL = ROOT/'.runtime/game-executor/scene-cli/20261014-013620-save-aebbabd5/after-1073741842.gil'
BASELINE_SHA = 'b8a49d0e3fb0befd84ee5c3b6ea412e247fcd740e4d563f49e197ad1f942608b'
LEVEL = 1073741842


def _module(directory, name):
    location = ROOT/directory
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))
    module = importlib.import_module(name)
    if Path(module.__file__).resolve() != location/(name+'.py'):
        raise ValueError('OFFLINE_READER_MODULE_COLLISION:'+name)
    return module


def inspect_baseline(path=BASELINE_GIL):
    """Recompute named asset identities and geometry in an immutable copy."""
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT/'.runtime'):
        raise ValueError('BASELINE_MUST_BE_PROJECT_COPY')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != BASELINE_SHA:
        raise ValueError('SUCCESSFUL_R7_BASELINE_CHANGED')
    directory = 'tools/game-executor/template-authoring'
    saved = _module(directory, 'saved_farming_bindings')
    items = _module(directory, 'saved_item_properties').read_saved_item_properties(
        path, level_id=LEVEL, expected_items={1107296257: '田园种子', 1107296258: '新鲜作物'})
    bindings = saved.validate_saved_bindings(path, level_id=LEVEL, character_id=1090519041,
        plot_id=1077936129, bag_template_id=1119879169, shop_template_id=1136656385)
    shop = _module(directory, 'saved_shop_source').read_saved_shop_source(
        path, level_id=LEVEL, shop_template_id=1136656385)
    container = saved.gil.decode_container(raw)
    root = saved.gil.parse_fields(container.payload)
    where, row = saved._record(root, 15, 1115684865)
    if row is None or saved._scalar(row, 2, where) != 11:
        raise ValueError('CURRENCY_RESOURCE_MISMATCH')
    prop = saved._component(row, 4, 1, where)
    name = saved._message(prop, 11, where+'.name', required=True)
    field = saved._one(name, 1, saved.gil.WIRE_LENGTH, where+'.name', required=True)
    if field.data.decode('utf-8') != '田园币':
        raise ValueError('CURRENCY_NAME_MISMATCH')
    geometry = _module('tools/beyond-save', 'entity_geometry')
    records = geometry.read_entity_records_blob(raw)
    positions = []
    for entity_id, wanted in ((1077936129, (0.0, 0.0, 0.0)),
                              (1077936130, (4.0, 0.0, 0.0))):
        matches = [r for r in records if r.entity_id == entity_id]
        if len(matches) != 1 or matches[0].transform is None:
            raise ValueError('INTERACTION_HOST_GEOMETRY_MISSING')
        actual = matches[0].transform.position.triple()
        if actual != wanted:
            raise ValueError('INTERACTION_HOST_GEOMETRY_CHANGED')
        positions.append({'entityId': entity_id, 'position': list(actual)})
    if not (items['savedPropertiesVerified'] and bindings['savedBindingsVerified']
            and shop['customListVerified'] and bindings['plotShop']['matchingShopIndices'] == [1]):
        raise ValueError('SUCCESSFUL_ASSET_BINDINGS_MISMATCH')
    if path.read_bytes() != raw:
        raise ValueError('BASELINE_CHANGED_DURING_READ')
    return {'ok': True, 'mode': 'saved-copy-only', 'levelId': LEVEL,
            'baseline': {'path': str(path), 'sha256': digest, 'bytes': len(raw)},
            'currencyId': 1115684865, 'seedId': 1107296257, 'cropId': 1107296258,
            'bagTemplateId': 1119879169, 'shopTemplateId': 1136656385,
            'shopIndex': 1, 'interactionHosts': positions,
            'items': items, 'bindings': bindings, 'shop': shop,
            'userAcceptance': {'source': '2026-10-14 direct user message',
                               'confirmed': ['shop', 'purchase', 'currency']},
            'liveSessionVerified': False, 'newInteractionDeployed': False,
            'newInteractionPlaytestVerified': False}
