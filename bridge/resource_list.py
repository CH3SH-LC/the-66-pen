"""Bounded offline observer of message 1020 plaintext protobuf payloads."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

MAX_BYTES = 1 << 20
MAX_ENTRIES = 4096
MAX_FIELDS = 20000


class ResourceListError(ValueError):
    pass


def _varint(data, pos, end):
    value = 0
    for i in range(10):
        if pos >= end:
            raise ResourceListError('truncated varint')
        byte = data[pos]; pos += 1
        if i == 9 and byte > 1:
            raise ResourceListError('varint exceeds uint64 or ten bytes')
        value |= (byte & 127) << (7*i)
        if byte < 128:
            return value, pos
    raise ResourceListError('varint exceeds ten bytes')


def _fields(data, start, end, budget):
    pos = start
    count = 0
    while pos < end:
        count += 1
        budget[0] += 1
        if count > MAX_FIELDS or budget[0] > MAX_FIELDS:
            raise ResourceListError('field count exceeds observer limit')
        offset = pos
        key, pos = _varint(data, pos, end)
        field, wire = key >> 3, key & 7
        if not 1 <= field <= 0x1fffffff:
            raise ResourceListError('invalid field number')
        value_start = pos
        if wire == 0:
            value, pos = _varint(data, pos, end)
        elif wire in (1, 5):
            pos += 8 if wire == 1 else 4
            value = None
        elif wire == 2:
            length, pos = _varint(data, pos, end)
            value_start = pos
            pos += length
            value = None
        else:
            raise ResourceListError('unsupported wire type; only 0/1/2/5 accepted')
        if pos > end:
            raise ResourceListError('field exceeds enclosing message')
        yield field, wire, value, offset, value_start, pos


def _unknown(data, field, wire, offset, end):
    return {'fieldNumber': field, 'wireType': wire, 'offset': offset,
            'rawHex': data[offset:end].hex()}


def parse_resource_list(payload: bytes, *, source='unverified') -> dict:
    """Offsets are absolute within the supplied plaintext payload, not a frame."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise ResourceListError('payload must be bytes-like')
    if source not in ('unverified', 'synthetic'):
        raise ResourceListError('source must be unverified or synthetic; no automatic live provenance')
    byte_count = payload.nbytes if isinstance(payload, memoryview) else len(payload)
    if byte_count > MAX_BYTES:
        raise ResourceListError('payload exceeds 1 MiB observer limit')
    data = bytes(payload)
    entries, unknown = [], []
    budget = [0]
    for field, wire, _, outer_offset, start, end in _fields(data, 0, len(data), budget):
        if field != 1:
            unknown.append(_unknown(data, field, wire, outer_offset, end))
            continue
        if wire != 2:
            raise ResourceListError('outer field 1 requires wire 2')
        if len(entries) >= MAX_ENTRIES:
            raise ResourceListError('entry count exceeds 4096 observer limit')
        present = {'opaque': False, 'uintValue': False, 'display': False}
        opaque_parts, extras, occurrences = [], [], []
        uint_value, display = 0, ''
        for number, kind, value, offset, content, finish in _fields(data, start, end, budget):
            expected = {1: 2, 2: 0, 3: 2}.get(number)
            if expected is None:
                extras.append(_unknown(data, number, kind, offset, finish))
                continue
            if kind != expected:
                raise ResourceListError(f'entry field {number} has wrong wire type')
            occurrences.append(_unknown(data, number, kind, offset, finish))
            if number == 1:
                present['opaque'] = True
                opaque_parts.append(data[content:finish])
            elif number == 2:
                if value > 0xffffffff:
                    raise ResourceListError('entry uint field exceeds uint32')
                present['uintValue'] = True
                uint_value = value
            else:
                present['display'] = True
                try:
                    display = data[content:finish].decode('utf-8', errors='strict')
                except UnicodeDecodeError as exc:
                    raise ResourceListError('entry display is not strict UTF-8') from exc
        raw = data[start:end]
        entries.append({'originalIndex': len(entries), 'fieldOffset': outer_offset,
                        'payloadOffset': start, 'payloadBytes': len(raw),
                        'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawHex': raw.hex(),
                        'present': present, 'opaqueHex': opaque_parts[0].hex() if len(opaque_parts)==1 else None,
                        'opaqueOccurrencesHex': [p.hex() for p in opaque_parts],
                        'knownFieldOccurrences': occurrences,
                        'uintValue': uint_value, 'display': display, 'unknownFields': extras})
    return {'messageId': 1020, 'source': source, 'runtimeVerified': False, 'gameVerified': False,
            'payloadBytes': len(data), 'rawSha256': hashlib.sha256(data).hexdigest(),
            'entryCount': len(entries), 'entries': entries, 'unknownFields': unknown,
            'notes': ['Display is not a file path; uintValue is not an import ID.',
                      'originalIndex belongs only to this payload; refresh can change it.',
                      'Opaque nested bytes are not decoded or validated.',
                      'Parsing does not establish live game provenance.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='explicit plaintext payload file, not a framed capture')
    parser.add_argument('--source', choices=['unverified', 'synthetic'], default='unverified')
    args = parser.parse_args()
    try:
        with args.file.open('rb') as stream:
            payload = stream.read(MAX_BYTES + 1)
        result = parse_resource_list(payload, source=args.source)
    except (OSError, ResourceListError) as exc:
        print(json.dumps({'ok': False, 'error': {'code': 'RESOURCE_LIST_INVALID', 'message': str(exc)}}))
        return 1
    print(json.dumps({'ok': True, **result}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
