"""Build the offline interaction upgrade; there is deliberately no execute flag.

Usage: python -B -m tools.gameplan.demo.offline_farming_bundle \
    --group-index 1 --output .runtime/scratch/offline-farming-20261014/bundle-001

The requested UI index is a candidate allocation, never proof it exists. Live
deployment requires the user's renewed authorization and current UI/player
binding evidence. The preserved successful shop stays untouched by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .offline_farming_baseline import ROOT, inspect_baseline
from . import legacy_farm_patch, shop_key_patch

OUTPUT_ROOT = ROOT/'.runtime/scratch/offline-farming-20261014'


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _output(value):
    path = Path(value)
    path = (path if path.is_absolute() else ROOT/path).resolve()
    if not path.is_relative_to(OUTPUT_ROOT) or path == OUTPUT_ROOT:
        raise ValueError('OUTPUT_MUST_BE_NEW_OFFLINE_TASK_SUBDIRECTORY')
    return path


def compile_bundle(*, group_index: int, group_combo_index=None) -> dict:
    """Build all graph pieces and recompute the saved asset identities."""
    from .farming_manual import FarmManualConfig, build_plan, package
    config = FarmManualConfig(group_index=group_index, group_combo_index=group_combo_index,
        item_slot='uint', variable_flag_slot='enum', entity_guid_slot='uint')
    baseline = inspect_baseline()
    graph = build_plan(config)
    farm = package(config, plan=graph)
    shop = shop_key_patch.prepare_patch()
    old_farm = legacy_farm_patch.prepare_patch()
    documents = {'baseline.json': baseline, 'player-interaction.json': farm,
                 'shop-detach.json': shop, 'old-farm-detach.json': old_farm}
    # The single combined graph supplies both actions. Never bind the standalone
    # shop example as well, and never create two buttons that compete for Z.
    documents['deployment-sequence.json'] = {
        'mode': 'offline-only', 'userLiveAuthorizationRequired': True,
        'requestedKey': 'Z', 'requestedGroupIndex': group_index,
        'requestedGroupComboIndex': group_combo_index,
        'graphName': graph.name, 'graphHost': 'triggering player',
        'uiBindingVerified': False, 'playerGraphBindingVerified': False,
        'gameModified': False, 'playtestVerified': False,
        'sequence': [
            'After user resumes live work, verify level, assets, process identities and fresh save backup.',
            'Configure one Z interaction-event UI control; read its actual group/combo indices.',
            'Regenerate this offline bundle with those actual indices before constructing any graph.',
            'Create the combined player graph and read back every node, edge, value and timer list.',
            'Bind UI and the graph to the triggering player; verify both serialized references.',
            'Use the separately reviewed fixed handler to detach old shop/farm auto entries exactly.',
            'Read both old graphs and compare exact expected bytes; then perform one reviewed native save.',
            'Playtest Z shop, buy seed, Z plant, wait ten seconds, Z harvest, sell crop; compare quantities.'
        ],
        'acceptanceCases': [
            'Standing near shop does not open it; Z near shop opens it; Z far away does nothing.',
            'An unrelated UI control or zero/multiple active characters performs no action.',
            'One seed is consumed only on planting; repeated Z during growth consumes no extra seed.',
            'Ten seconds makes the crop ripe; maturity and walking never grant the crop automatically.',
            'Z harvest increases crop count by exactly one, then makes the plot reusable.',
            'When a bag change is rejected, stage and inventory remain consistent; a later press can retry.',
            'The existing prices, currency, purchase and shop inventory behavior remain intact.'
        ],
        'notInferredFromOfflineTests': ['native UI Z dispatch', 'native inventory update timing',
            'native full-bag rejection', 'native timer delivery', 'save/reopen persistence']}
    return json.loads(compact(documents))


def write_bundle(output, *, group_index, group_combo_index=None):
    out = _output(output)
    if out.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    documents = compile_bundle(group_index=group_index, group_combo_index=group_combo_index)
    encoded = {name: (compact(value)+'\n').encode('utf-8') for name, value in documents.items()}
    out.mkdir(parents=True, exist_ok=False)
    for name, raw in encoded.items():
        (out/name).write_bytes(raw)
    source_paths = [Path(__file__), Path(legacy_farm_patch.__file__), Path(shop_key_patch.__file__),
        ROOT/'tools/gameplan/demo/farming_manual.py', ROOT/'tools/gameplan/modules/farm_interaction.py',
        ROOT/'tools/gameplan/modules/key_interaction.py', ROOT/'tools/gameplan/demo/offline_farming_baseline.py']
    manifest = {'schemaVersion': 1, 'kind': 'offline-farming-interaction-bundle',
        'groupIndex': group_index, 'groupComboIndex': group_combo_index,
        'files': {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                  for name, raw in encoded.items()},
        'sourceHashes': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in source_paths},
        'gameModified': False, 'nativeCalls': 0, 'dispatchable': False,
        'playtestVerified': False}
    (out/'manifest.json').write_text(compact(manifest)+'\n', encoding='utf-8')
    return {'ok': True, 'output': str(out), 'files': len(encoded), 'gameModified': False,
            'playtestVerified': False, 'dispatchable': False}


def verify_bundle(output):
    out = _output(output)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    expected = compile_bundle(group_index=manifest['groupIndex'],
                              group_combo_index=manifest['groupComboIndex'])
    if set(manifest['files']) != set(expected):
        raise ValueError('BUNDLE_FILE_SET_CHANGED')
    for name, value in expected.items():
        raw = (out/name).read_bytes()
        if (hashlib.sha256(raw).hexdigest() != manifest['files'][name]['sha256'] or
                len(raw) != manifest['files'][name]['bytes'] or json.loads(raw) != value):
            raise ValueError('BUNDLE_CONTENT_CHANGED:'+name)
    for relative, digest in manifest['sourceHashes'].items():
        source = (ROOT/relative).resolve()
        if not source.is_relative_to(ROOT) or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('BUNDLE_SOURCE_CHANGED:'+relative)
    if any(manifest[k] is not False for k in ('gameModified', 'dispatchable', 'playtestVerified')) or manifest['nativeCalls'] != 0:
        raise ValueError('BUNDLE_CLAIMS_CHANGED')
    return {'ok': True, 'filesVerified': len(expected), 'gameModified': False, 'playtestVerified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group-index', type=int)
    parser.add_argument('--group-combo-index', type=int)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        if args.group_index is not None or args.group_combo_index is not None:
            parser.error('--verify reads the recorded indices')
        result = verify_bundle(args.output)
    else:
        if args.group_index is None:
            parser.error('--group-index is required for compilation')
        result = write_bundle(args.output, group_index=args.group_index,
                              group_combo_index=args.group_combo_index)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
