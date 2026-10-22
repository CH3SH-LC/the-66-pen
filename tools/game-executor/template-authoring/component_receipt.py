"""Offline decoding of captured component sets/lists and attachment deltas.

Consumes the fixed x64 ComponentSnapshot, not native success flags. It does
not prove that a scene entity is a playable character, persistence, or play.
"""
from __future__ import annotations
import struct

from receipt import pointer, require

MAX_COMPONENTS = 256
COMPONENT_BYTES = 11376
ROW = struct.Struct('<4QiB3x')
KINDS_AT, ROWS_AT = 112, 1136


def decode_components(raw):
    require(isinstance(raw, bytes) and len(raw) == COMPONENT_BYTES, 'COMPONENT_RECEIPT_SIZE')
    status, byte_count, reads, count, set_count = struct.unpack_from('<5I', raw)
    require(status == 0, 'COMPONENT_CAPTURE_INCOMPLETE')
    require(0 < byte_count <= 128 * 1024 and 0 < reads <= 4096, 'COMPONENT_CAPTURE_BUDGET')
    require(count == set_count and count <= MAX_COMPONENTS, 'COMPONENT_SET_LIST_COUNT')
    names = ('owner', 'ownerClass', 'set', 'list', 'buckets', 'slots', 'items')
    result = dict(zip(names, struct.unpack_from('<7Q', raw, 24)))
    require(all(pointer(result[k]) for k in ('owner', 'ownerClass', 'set', 'list', 'items')) and
            result['set'] != result['list'], 'COMPONENT_ROOT_POINTERS')
    capacity, list_capacity, last, set_version, list_version, free = struct.unpack_from('<5Ii', raw, 80)
    require(count <= list_capacity <= MAX_COMPONENTS and
            count <= last <= capacity <= MAX_COMPONENTS, 'COMPONENT_CAPACITIES')
    if not capacity:
        require(result['buckets'] == result['slots'] == 0 and last == count == 0 and free == -1,
                'COMPONENT_EMPTY_SET')
    else:
        require(pointer(result['buckets']) and pointer(result['slots']) and
                -1 <= free < last, 'COMPONENT_SET_POINTERS')
    kinds = struct.unpack_from('<' + 'i' * count, raw, KINDS_AT)
    rows = [ROW.unpack_from(raw, ROWS_AT + i * ROW.size) for i in range(count)]
    require(len(set(kinds)) == count and all(k > 0 for k in kinds), 'COMPONENT_SET_KINDS')
    require(len({row[0] for row in rows}) == count and len({row[2] for row in rows}) == count and
            len({row[4] for row in rows}) == count, 'COMPONENT_DUPLICATE_ROW')
    require(all(all(pointer(v) for v in row[:4]) and row[4] > 0 and row[5] in (0, 1)
                for row in rows), 'COMPONENT_ROW_IDENTITY')
    require(set(kinds) == {row[4] for row in rows}, 'COMPONENT_SET_LIST_KINDS')
    result.update(count=count, rows=rows, kinds=kinds, ownerState=raw[104],
                  setVersion=set_version, listVersion=list_version)
    return result


def verify_component_transition(before_raw, after_raw, final_raw, *, owner,
                                kind, wrapper_class, config_class, wrapper, config,
                                attach_called, allow_target_enable_change=False):
    require(kind in (33, 35) and type(attach_called) is bool, 'COMPONENT_REQUEST_KIND')
    require(all(pointer(value) for value in (owner, wrapper_class, config_class, wrapper, config)),
            'COMPONENT_REQUEST_POINTER')
    before, final = decode_components(before_raw), decode_components(final_raw)
    after = decode_components(after_raw) if attach_called else before
    root_keys = ('owner', 'ownerClass', 'set', 'list', 'ownerState')
    require(before['owner'] == owner and
            all(before[key] == after[key] == final[key] for key in root_keys), 'COMPONENT_OWNER_CHANGED')
    selected = [row for row in before['rows'] if row[4] == kind]
    if attach_called:
        require(not selected and after['count'] == before['count'] + 1 and
                after['rows'][:-1] == before['rows'], 'COMPONENT_ATTACH_DELTA')
        row = after['rows'][-1]
    else:
        require(len(selected) == 1, 'COMPONENT_REUSED_KIND_MISSING')
        row = selected[0]
    require(row[:5] == (wrapper, wrapper_class, config, config_class, kind),
            'COMPONENT_TARGET_IDENTITY')
    require(final['count'] == after['count'], 'COMPONENT_POST_BINDING_CHANGED')
    enable_changed = False
    for old, new in zip(after['rows'], final['rows']):
        if allow_target_enable_change and old[0] == wrapper:
            require(old[:5] == new[:5], 'COMPONENT_POST_BINDING_CHANGED')
            enable_changed = old[5] != new[5]
        else:
            require(old == new, 'COMPONENT_POST_BINDING_CHANGED')
    return {'componentDeltaVerified': True, 'componentCountBefore': before['count'],
            'componentCountAfter': final['count'], 'attached': attach_called,
            'targetEnabledBefore': row[5],
            'targetEnabledAfter': next(r[5] for r in final['rows'] if r[0] == wrapper),
            'targetEnableChanged': enable_changed,
            'playerCharacterVerified': False, 'persistentSaveVerified': False}
