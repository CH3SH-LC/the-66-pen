"""Compile shop prices to runtime dictionaries; pure data, no editor access.

The 7.1 game converter rejects the old statically populated price dictionary.
The real R7 shop uses shell 1788 / kernel 1890 with config-ID keys and integer
amounts. Its count is the number of input slots: one pair requires TWO slots.
This compiler is for a NEW graph. It never claims to unset an existing default;
an existing graph needs the separately reviewed native initializer and readback.
"""
from copy import deepcopy

PRICE_INPUTS = {704: 4, 706: 3, 708: 3, 709: 3, 710: 3}
CONSTRUCTOR_ID = 1788
KERNEL_ID = 1890


def _uint(value, name):
    if type(value) is not int or not 1 <= value <= 0xFFFFFFFF:
        raise ValueError(name + ' must be a nonzero uint32')
    return value


def _price(value):
    if not isinstance(value, dict) or set(value) != {'dict'}:
        raise ValueError('price must be an explicit dictionary')
    entries = value['dict']
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError('only the verified single-currency price is supported')
    entry = entries[0]
    if (not isinstance(entry, dict) or set(entry) != {'key', 'value'} or
            not isinstance(entry['key'], dict) or set(entry['key']) != {'uint'} or
            not isinstance(entry['value'], dict) or set(entry['value']) != {'int'}):
        raise ValueError('price requires a config-ID uint key and integer amount')
    currency = _uint(entry['key']['uint'], 'currency')
    amount = entry['value']['int']
    if type(amount) is not int or not 1 <= amount <= 0x7FFFFFFF:
        raise ValueError('price amount must be a positive int32')
    return currency, amount


def compile_new_graph_prices(batch: dict) -> dict:
    """Return a deep copy with static shop price constants replaced by 1788.

    Node indices remain zero-based batch indices. Existing nodes, edges and
    non-price values are preserved in order. Validate every replacement before
    producing any output. This is an offline candidate, not a write operation.
    """
    if not isinstance(batch, dict) or set(batch) != {'nodes', 'edges', 'values'}:
        raise ValueError('expected a complete nodes/edges/values batch')
    if any(not isinstance(batch[k], list) for k in batch):
        raise ValueError('batch fields must be lists')
    nodes, edges, values = batch['nodes'], batch['edges'], batch['values']
    targets = []
    seen = set()
    for row in values:
        if not isinstance(row, dict) or not {'node', 'portIndex', 'slot', 'value'} <= set(row):
            raise ValueError('malformed value row')
        index, port = row['node'], row['portIndex']
        if type(index) is not int or not 0 <= index < len(nodes) or type(port) is not int:
            raise ValueError('value target outside batch')
        target = (index, port)
        if target in seen:
            raise ValueError('duplicate constant target')
        seen.add(target)
        definition = nodes[index]['definitionId']
        if PRICE_INPUTS.get(definition) != port:
            continue
        currency, amount = _price(row['value'])
        if any((e.get('to'), e.get('toKind'), e.get('toIndex')) == (index, 3, port) for e in edges):
            raise ValueError('price target already connected')
        targets.append((index, port, currency, amount))
    if not targets:
        raise ValueError('no static shop prices to compile')
    if len(nodes) + len(targets) > 128:
        raise ValueError('runtime price constructors exceed graph node limit')
    result = deepcopy(batch)
    replaced = {(n, p) for n, p, _, _ in targets}
    result['values'] = [r for r in result['values'] if (r['node'], r['portIndex']) not in replaced]
    constructors = []
    for target, port, currency, amount in targets:
        index = len(result['nodes'])
        result['nodes'].append({'definitionId': CONSTRUCTOR_ID, 'x': 0, 'y': 0})
        result['edges'].append({'from': index, 'to': target, 'fromKind': 4,
                                'fromIndex': 0, 'toKind': 3, 'toIndex': port})
        for number, slot, value in ((0, 'int', 2), (1, 'uint', currency), (2, 'int', amount)):
            result['values'].append({'node': index, 'portIndex': number,
                                     'slot': slot, 'value': {slot: value}})
        constructors.append({'node': index, 'consumer': target, 'consumerPort': port,
                             'currencyId': currency, 'amount': amount})
    return {'batch': result, 'constructors': constructors,
            'mode': 'offline-new-graph-candidate', 'dispatchable': False,
            'runtimeVerified': False,
            'requiredReadback': {'kernelId': KERNEL_ID, 'parameterSlotCount': 2,
                'keyType': 20, 'valueType': 3, 'outputType': 27,
                'consumerDefault': 'absent or unset; no residual static map',
                'physicalPinCount': 102},
            'existingGraphMigrationSupported': False}
