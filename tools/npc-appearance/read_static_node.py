"""Acquire an explicitly indexed installed resource, without game access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/mondstadt-reference'))


def main():
    os.environ['MONDSTADT_CODEC_ISOLATE'] = '1'
    from blb3_reference import BundleReader, INSTALL
    from serialized_reference import metadata, object_identity
    p = argparse.ArgumentParser()
    p.add_argument('--index', type=Path, required=True)
    p.add_argument('--row', type=int, default=0)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    row = json.loads(a.index.read_text(encoding='utf8'))[a.row]
    source = Path(row['source']).resolve()
    out = a.out.resolve()
    if not source.is_relative_to(INSTALL):
        raise ValueError('INSTALL_SOURCE_REQUIRED')
    if not (out.is_relative_to(ROOT / 'tools/npc-appearance/evidence') or
            out.is_relative_to(ROOT / '.runtime/npc-appearance-20261017')) or out.exists():
        raise ValueError('NEW_OWNED_OUTPUT_REQUIRED')
    before = source.stat()
    reader = BundleReader(source, row['offset'])
    n = row['node']
    size = reader.meta['nodes'][n]['size']
    if size > 64 * 1024 * 1024:
        raise ValueError('NODE_READ_BUDGET')
    data = reader.read(n, 0, size)
    decoded = metadata(data)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('SOURCE_CHANGED')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'node.bin').write_bytes(data)
    for obj in decoded['objects']:
        payload = data[obj['offset']:obj['offset'] + obj['size']]
        obj['sha256'] = hashlib.sha256(payload).hexdigest()
        obj['identity'] = object_identity(obj, payload, decoded['endian'])
        if obj['classId'] == 114:
            (out / ('behaviour-' + str(obj['pathId']) + '.bin')).write_bytes(payload)
    (out / 'metadata.json').write_text(json.dumps(decoded, ensure_ascii=False, indent=2), encoding='utf8')
    receipt = dict(row, nodeSha256=hashlib.sha256(data).hexdigest(),
                   sourceSize=before.st_size, sourceMtimeNs=before.st_mtime_ns,
                   sourceWrites=False, gameConnected=False, nativeCalled=False)
    (out / 'source.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(dict(ok=True, out=str(out), bytes=len(data), objectCount=len(decoded['objects']), gameConnected=False)))


if __name__ == '__main__':
    main()
