"""Read-only acceptance check for a new test entity, rename, then deletion.

Checks three native-save snapshots. It does not create entities, save the game,
or establish who performed an action; those need separate runtime evidence.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('renamed', type=Path)
    parser.add_argument('deleted', type=Path)
    parser.add_argument('--entity-id', type=int, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Refusing to overwrite: ' + str(args.out))
    if not 0 < args.entity_id <= 0xffffffff:
        parser.error('Entity id must be a nonzero uint32')
    spec = importlib.util.spec_from_file_location(
        'native_save_builder', Path(__file__).with_name('build-newdemo-static.py'))
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    paths = [args.before, args.renamed, args.deleted]
    raw = [p.read_bytes() for p in paths]
    docs = [builder.parse_gi_file(p) for p in paths]

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    maps = []
    for doc in docs:
        entities = {e.entity_id: e.model_dump() for e in doc.entities}
        require(len(entities) == len(doc.entities), 'Duplicate entity ids in snapshot')
        maps.append(entities)
    initial, renamed, deleted = maps
    target = args.entity_id
    require(len({doc.level_name for doc in docs}) == 1, 'Level names differ')
    require(target not in initial, 'Test entity already existed before experiment')
    require(target in renamed, 'Renamed entity is absent')
    require(renamed[target]['name'] == args.name, 'Renamed entity name mismatch')
    require({k: v for k, v in renamed.items() if k != target} == initial,
            'Other entities changed during creation/rename')
    require(deleted == initial, 'Deletion did not exactly restore original entities')
    require(docs[0].node_graphs == docs[1].node_graphs == docs[2].node_graphs,
            'Node graphs changed')
    middle5 = builder.only(raw[1][20:-4], 5)
    final5 = builder.only(raw[2][20:-4], 5)
    is_target = lambda f, w, p: f == 1 and w == 2 and builder.get_varint(p, 1) == target
    spans = list(builder.raw.spans(middle5))
    require(sum(is_target(f, w, p) for f, w, p, _ in spans) == 1,
            'Expected one raw target entity record')
    require(b''.join(record for f, w, p, record in spans if not is_target(f, w, p)) == final5,
            'Root5 differs beyond removal of the target record')
    # This is a conservative encoded-id absence check, not a generic root6 schema.
    require(builder.raw._enc_varint(target) not in builder.only(raw[2][20:-4], 6),
            'Target id bytes remain in directory field')
    report = dict(ok=True, levelName=docs[0].level_name, entityId=target,
                  renamedName=args.name, entityCounts=[len(m) for m in maps],
                  otherEntitiesPreserved=True, graphsPreserved=True,
                  root5SingleRecordDeletion=True, directoryTargetIdBytesAbsent=True,
                  inputs=[dict(path=str(p.resolve()), sha256=hashlib.sha256(data).hexdigest())
                          for p, data in zip(paths, raw)],
                  runtimeActionSourceVerified=False, backendSaveImplemented=False)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
