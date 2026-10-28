"""Exact, disk-only template -> native base table -> model handle lookup.

No process attachment, implicit resource loading, name matching or appearance
approval occurs here. The contract pins captured table bytes; decoded JSON is
never trusted in place of decoding those bytes again.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'tools/game-executor'))
from asset_inspection_templates import official_index, wire_one
from gadget_catalog import decode_beyond_gadgets
from gadget_models import record as gadget_record
from monster_catalog import decode_monsters
from native_catalog import beyond_monsters
from npc_registry import prefix as npc_prefix
from primary_index import decode as decode_index

CONTRACT = HERE / 'source_contract.json'
FACTORY_TYPES = {1401: 'Level', 1402: 'Gadget', 1403: 'Player',
                 1404: 'Avatar', 1405: 'Monster'}


def require(value, code):
    if not value:
        raise ValueError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique(rows, key):
    result = {}
    for row in rows:
        identifier = row[key]
        require(type(identifier) is int and 0 <= identifier <= 0xffffffff,
                'SOURCE_ID_DOMAIN')
        require(identifier not in result, 'SOURCE_DUPLICATE_ID')
        result[identifier] = row
    return result


def indexed_records(data, index, decoder, id_key):
    entries = decode_index(index)
    require(entries[0]['offset'] == 4 and
            entries[-1]['offset'] + entries[-1]['size'] == len(data),
            'INDEX_DATA_SPAN_MISMATCH')
    result = []
    for entry in entries:
        payload = data[entry['offset']:entry['offset'] + entry['size']]
        row = decoder(payload, entry)
        require(row[id_key] == entry['id'], 'INDEX_RECORD_ID_MISMATCH')
        row.update(offset=entry['offset'], size=entry['size'])
        result.append(row)
    return unique(result, id_key)


def nested_id(fields, oneof):
    node = wire_one(fields, oneof, 2)
    require('m' in node, 'BASE_ONEOF_NOT_MESSAGE')
    child = wire_one(node['m'], 1, 2)
    require('m' in child, 'BASE_REFERENCE_NOT_MESSAGE')
    identifier = wire_one(child['m'], 1, 0)['v']
    require(type(identifier) is int and 0 < identifier <= 0xffffffff,
            'BASE_REFERENCE_ID_DOMAIN')
    return identifier


class Catalog:
    """Reusable exact lookup. Construction reads seven pinned static captures."""
    def __init__(self, contract_path=CONTRACT):
        contract_path = Path(contract_path).resolve()
        self.contract = json.loads(contract_path.read_text(encoding='utf8'))
        require(self.contract['kind'] == 'npc-appearance-source-contract-v1',
                'SOURCE_CONTRACT_KIND')
        self.contract_evidence = dict(path=str(contract_path),
                                     sha256=sha(contract_path.read_bytes()))
        self.sources = {}
        installed = self.contract['installedTableContainer']
        installed_path = Path(installed['path'])
        require(installed_path.is_file() and installed_path.stat().st_size == installed['bytes']
                and sha(installed_path.read_bytes()) == installed['sha256'],
                'INSTALLED_TABLE_CONTAINER_CHANGED')
        def read(key):
            entry = self.contract['captures'][key]
            path = (ROOT / entry['path']).resolve()
            require(path.is_relative_to(ROOT) and path.is_file(),
                    'CAPTURE_PATH_INVALID')
            for parent in (path, *path.parents):
                require(not parent.is_symlink() and not
                        (getattr(parent.stat(), 'st_file_attributes', 0) & 0x400),
                        'CAPTURE_REPARSE_REFUSED')
            require(path.stat().st_size == entry['bytes'], 'CAPTURE_SIZE_CHANGED')
            raw = path.read_bytes()
            require(sha(raw) == entry['sha256'], 'CAPTURE_HASH_CHANGED:' + key)
            self.sources[key] = dict(path=str(path), sha256=entry['sha256'],
                                     bytes=len(raw))
            return raw
        self.beyond_gadgets = unique(decode_beyond_gadgets(read('beyondGadgets')),
                                     'beyondGadgetBaseId')
        self.gadgets = indexed_records(read('gadgets'), read('gadgetIndex'),
            lambda payload, _: gadget_record(payload), 'gadgetConfigId')
        self.beyond_monsters = unique(beyond_monsters(read('beyondMonsters')),
                                      'beyondMonsterBaseId')
        self.monsters = unique(decode_monsters(read('monsters')), 'monsterConfigId')
        self.npcs = indexed_records(read('npcs'), read('npcIndex'), npc_prefix,
                                   'npcConfigId')
        require(all(not x['gadgetConfigId'] or x['gadgetConfigId'] in self.gadgets
                    for x in self.beyond_gadgets.values()), 'GADGET_JOIN_MISSING')
        require(all(not x['monsterConfigId'] or x['monsterConfigId'] in self.monsters
                    for x in self.beyond_monsters.values()), 'MONSTER_JOIN_MISSING')

    def resolve_fields(self, template_id, fields, source):
        require(type(template_id) is int and 0 < template_id <= 0xffffffff,
                'TEMPLATE_ID_DOMAIN')
        require(wire_one(fields, 1, 0)['v'] == template_id,
                'OFFICIAL_TEMPLATE_ID_MISMATCH')
        proto = wire_one(fields, 2, 2)
        require('m' in proto, 'OFFICIAL_BASE_NOT_MESSAGE')
        fields = proto['m']
        native_type = wire_one(fields, 1, 0)['v']
        oneofs = [x['f'] for x in fields if 21 <= x['f'] <= 25]
        require(len(oneofs) <= 1, 'OFFICIAL_ONEOF_AMBIGUOUS')
        expected = native_type - 1380
        # The actual Player/Avatar defaults omit an empty oneof entirely.
        # Their type still selects a real factory branch; they do not acquire
        # a free base-model route merely because the empty arm is absent.
        require(native_type in FACTORY_TYPES and
                (oneofs == [expected] or
                 (not oneofs and native_type in (1401,1403,1404))),
                'OFFICIAL_NATIVE_TYPE_ONEOF_MISMATCH')
        output = dict(templateId=template_id, nativeType=native_type,
            nativeClass=FACTORY_TYPES[native_type], officialSource=source,
            persistedBaseReference=None, configId=None, modelResourceHandle=None,
            modelRow=None, modelIdentityVerified=False, resourceObjectResolved=False,
            modelAppearanceVerified=False, ordinaryResidentVerified=False,
            savedAppearanceSetterAvailable=False, identityUsesNames=False,
            sourceContract=self.contract_evidence)
        if native_type not in (1402, 1405):
            output['status'] = 'native-type-has-no-base-model-handle-route'
            output['limitation'] = ('Player/Avatar use a separate preview/player '
                'route; they are not ordinary NPC templates.' if native_type in
                (1403, 1404) else 'Level is not an appearance model.')
            return output
        base_id = nested_id(fields, expected)
        if native_type == 1402:
            require(base_id in self.beyond_gadgets, 'BEYOND_GADGET_ID_MISSING')
            base = self.beyond_gadgets[base_id]
            config_id = base['gadgetConfigId']
            model = self.gadgets.get(config_id)
            sources = ('beyondGadgets', 'gadgets', 'gadgetIndex')
        else:
            require(base_id in self.beyond_monsters, 'BEYOND_MONSTER_ID_MISSING')
            base = self.beyond_monsters[base_id]
            config_id = base['monsterConfigId']
            model = self.monsters.get(config_id)
            sources = ('beyondMonsters', 'monsters')
        handle = model['modelResourceHandle'] if model else '0'
        require(isinstance(handle, str) and handle.isdecimal() and
                0 <= int(handle) <= 0xffffffffffffffff, 'MODEL_HANDLE_DOMAIN')
        output.update(persistedBaseReference=base_id, configId=config_id,
            persistedReferenceField=f'2.{expected}.1.1', modelResourceHandle=handle,
            modelRow=model, nativeBaseRow=base, modelIdentityVerified=bool(int(handle)),
            status='resolved-native-model-handle' if int(handle) else 'native-model-handle-empty',
            sources={key:self.sources[key] for key in sources},
            interpretation='U64 resource path hash; not CAB ID, model name, or approval')
        return output

    def resolve(self, template_ids):
        require(template_ids and len(template_ids) <= 4096 and
                len(template_ids) == len(set(template_ids)), 'TEMPLATE_SELECTION_INVALID')
        indexed, inventory = official_index()
        rows = []
        for template_id in template_ids:
            require(template_id in indexed, 'OFFICIAL_TEMPLATE_NOT_FOUND:' + str(template_id))
            value = indexed[template_id]
            rows.append(self.resolve_fields(template_id, value['wireFields'], value['source']))
        return dict(kind='npc-appearance-official-models-v1', ok=True, rows=rows,
            officialInventory=inventory, sourceContract=self.contract_evidence,
            installedTableContainer=self.contract['installedTableContainer'],
            gameProcessAccessed=False, nativeCalled=False, gameWritesPerformed=False,
            liveModelReadbackPerformed=False, allAppearancesVerified=False)

    def npc_coverage(self):
        def handles(rows):
            return {row['modelResourceHandle'] for row in rows if int(row['modelResourceHandle'])}
        npc = handles(self.npcs.values())
        gadgets = handles(self.gadgets[x['gadgetConfigId']] for x in
            self.beyond_gadgets.values() if x['gadgetConfigId'])
        monsters = handles(self.monsters[x['monsterConfigId']] for x in
            self.beyond_monsters.values() if x['monsterConfigId'])
        return dict(kind='npc-appearance-source-coverage-v1', ok=True,
            npcRecordCount=len(self.npcs), npcUniqueHandleCount=len(npc),
            beyondGadgetCount=len(self.beyond_gadgets), beyondMonsterCount=len(self.beyond_monsters),
            beyondGadgetUniqueHandleCount=len(gadgets), beyondMonsterUniqueHandleCount=len(monsters),
            npcHandlesInBeyondGadgets=sorted(npc & gadgets, key=int),
            npcHandlesInBeyondMonsters=sorted(npc & monsters, key=int),
            comparison='Exact nonzero U64 native modelResourceHandle equality',
            fullNpcRecordDecoded=False, allNpcIdentitiesDecoded=True,
            ordinaryResidentPlacementAvailable=False, saveableResidentSetterProven=False,
            globalPlatformImpossibilityProven=False,
            sources=self.sources, sourceContract=self.contract_evidence,
            gameProcessAccessed=False, nativeCalled=False, gameWritesPerformed=False)
