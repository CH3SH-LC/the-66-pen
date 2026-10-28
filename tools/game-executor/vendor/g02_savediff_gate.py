"""G02 save-delta gate: the machine-checkable rule set from decisions/G02-save-delta.md.

Read-only on every input. All mutation happens on copies under this taskRunRoot.

  python g02_savediff_gate.py --case <case.json> --out <findings.json>

Case json (paths are absolute; all must already exist):
{
  "caseId": "...", "operation": "create|save|delete", "levelId": "1073741839",
  "gilBefore": "...", "gilAfter": "...",
  "gipBefore": "...", "gipAfter": "...",
  "protectedLevels": {"1073741835": {"gil": "...", "tempMirror": "..."}, ...},
  "targetLevel": {"tempMirrorBefore": "...", "tempMirrorAfter": "..."},
  "declaredChangedRoots": [46],
  "declaredChangedGipEntries": [],
  "entityDelta": {"addedIds": [..], "removedIds": [..]}
}

Exit 0 only when every finding is 'pass'. Exit 1 on any 'defect'. Exit 2 on bad usage.
A finding of 'blocked' (named unexplained delta) also exits 1: an unexplained delta is
a findable defect, not a benchmark to be inherited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

LEVEL_TRAILER = 0x679
PROFILE_TRAILER = 0x679
K_F1 = 0x3CF25440
K_F2HI = 0x4265796F
K_F2LO = 0x2C013519
# roots the contract asserts unchanged for every operation unless declared
ALWAYS_STABLE_ROOTS = (1, 2, 10, 27, 39, 40, 41, 52, 53)
ROOT46_MAX_RECORDS = 5


# --------------------------------------------------------------------------- #
def varint(buf, pos=0):
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def spans(data):
    out, pos = [], 0
    while pos < len(data):
        start = pos
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            raise ValueError(f'field {field} wire {wire}')
        if wire == 0:
            value, pos = varint(data, pos)
            payload = value
        elif wire == 2:
            size, pos = varint(data, pos)
            payload = data[pos:pos + size]
            pos += size
        elif wire == 1:
            payload, pos = data[pos:pos + 8], pos + 8
        else:
            payload, pos = data[pos:pos + 4], pos + 4
        if pos > len(data):
            raise ValueError('truncated record')
        out.append((field, wire, payload, data[start:pos]))
    return out


def root46_records(payload):
    out, pos = [], 0
    while pos < len(payload):
        if payload[pos] != 0x0A:
            raise ValueError(f'record starts with {payload[pos]:#x}, not 0x0a')
        length = payload[pos + 1]
        body = payload[pos + 2:pos + 2 + length]
        if len(body) != length:
            raise ValueError('record runs off the end')
        pos += 2 + length
        if body[0] != 0x08:
            raise ValueError(f'record body starts with {body[0]:#x}, not 0x08')
        v1, end1 = varint(body, 1)
        if body[end1] != 0x10:
            raise ValueError(f'second tag {body[end1]:#x}, not 0x10')
        v2, end2 = varint(body, end1 + 1)
        if end2 != length:
            raise ValueError(f'record body is {length} bytes, parsed {end2}')
        out.append((v1, v2))
    return out


def root_of(payload, number):
    return [record for record in spans(payload) if record[0] == number]


def container_checks(raw, expect_subtype, label, findings):
    def check(name, ok, detail):
        findings.append({'id': f'{label}.{name}', 'status': 'pass' if ok else 'defect', 'detail': detail})

    if len(raw) < 24:
        check('framing', False, f'{len(raw)} bytes is below the container minimum')
        return None
    total = int.from_bytes(raw[0:4], 'big')
    version = int.from_bytes(raw[4:8], 'big')
    magic = int.from_bytes(raw[8:12], 'big')
    subtype = int.from_bytes(raw[12:16], 'big')
    inner = int.from_bytes(raw[16:20], 'big')
    trailer = int.from_bytes(raw[20 + inner:24 + inner], 'big') if len(raw) >= 24 + inner else None
    check('framing', total == len(raw) - 4 and version == 1 and magic == 0x326
          and 20 + inner == total and trailer == LEVEL_TRAILER and subtype == expect_subtype,
          {'total': total, 'actual_len_minus_4': len(raw) - 4, 'version': version,
           'magic': hex(magic), 'subtype': subtype, 'inner': inner, 'trailer': trailer})
    return raw[20:20 + inner]


def entity_ids(level_payload):
    """root5 = repeated field 1{ field 1 = entity id (varint) }."""
    ids = set()
    for field, wire, payload, _ in spans(level_payload):
        if field == 5 and wire == 2:
            for f2, w2, p2, _r2 in spans(payload):
                if f2 != 1 or w2 != 2:
                    continue
                for f3, w3, p3, _r3 in spans(p2):
                    if f3 == 1 and w3 == 0:
                        ids.add(p3)
    return ids


def gip_level_entries(payload):
    """profile field 2 -> flat level list entries."""
    out = []
    pos = 0
    while pos < len(payload):
        start = pos
        tag, pos = varint(payload, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            _, pos = varint(payload, pos)
            continue
        if wire == 2:
            size, pos = varint(payload, pos)
            body = payload[pos:pos + size]
            pos += size
            if field == 2:
                inner, p, fields = body, 0, []
                while p < len(inner):
                    t, p = varint(inner, p)
                    fn, fw = t >> 3, t & 7
                    if fw == 0:
                        v, p = varint(inner, p)
                        fields.append(('varint', fn, v))
                    elif fw == 2:
                        n, p = varint(inner, p)
                        fields.append(('bytes', fn, inner[p:p + n]))
                        p += n
                    else:
                        raise ValueError(f'entry wire {fw}')
                entry = {fn: v for kind, fn, v in fields}
                out.append({'file_off': [20 + start, 20 + pos], 'fields': fields,
                            'level_id': entry.get(1), 'name': entry.get(2),
                            'timestamp': entry.get(3), 'raw': payload[start:pos]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', type=pathlib.Path, required=True)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    args = ap.parse_args()
    case = json.loads(args.case.read_text(encoding='utf-8'))
    findings = []
    blocked = []

    # ---- 1. containers -----------------------------------------------------
    gil_before = pathlib.Path(case['gilBefore']).read_bytes()
    gil_after = pathlib.Path(case['gilAfter']).read_bytes()
    payload_before = container_checks(gil_before, 2, 'gilBefore', findings)
    payload_after = container_checks(gil_after, 2, 'gilAfter', findings)
    gip_before = pathlib.Path(case['gipBefore']).read_bytes()
    gip_after = pathlib.Path(case['gipAfter']).read_bytes()
    profile_before = container_checks(gip_before, 1, 'gipBefore', findings)
    profile_after = container_checks(gip_after, 1, 'gipAfter', findings)

    findings.append({'id': 'container.lengthsReported', 'status': 'pass',
                     'detail': f'{len(gil_before)} -> {len(gil_after)} bytes in the level container'})

    def finish(case, findings, blocked, args):
        defects = [f for f in findings if f['status'] != 'pass']
        verdict = 'pass' if not defects and not blocked else ('blocked' if not defects else 'fail')
        report = {'caseId': case.get('caseId'), 'operation': case.get('operation'),
                  'verdict': verdict, 'findings': findings, 'blockedNamedDeltas': blocked,
                  'inputs': {k: hashlib.sha256(pathlib.Path(case[k]).read_bytes()).hexdigest()
                             for k in ('gilBefore', 'gilAfter', 'gipBefore', 'gipAfter')
                             if case.get(k)},
                  'rule': 'a named unexplained delta is a defect: verdict cannot be pass while it stands'}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'verdict': verdict,
                          'defects': [f['id'] for f in defects],
                          'blocked': [b['name'] for b in blocked],
                          'out': str(args.out)}, ensure_ascii=False))
        return 0 if verdict == 'pass' else 1

    # ---- 2. protected siblings --------------------------------------------
    for level, pair in (case.get('protectedLevels') or {}).items():
        gil_same = pathlib.Path(pair['gilBefore']).read_bytes() == pathlib.Path(pair['gilAfter']).read_bytes()
        mirror_same = pathlib.Path(pair['tempMirrorBefore']).read_bytes() == pathlib.Path(pair['tempMirrorAfter']).read_bytes()
        findings.append({'id': f'protectedLevel.{level}.unchanged',
                         'status': 'pass' if gil_same and mirror_same else 'defect',
                         'detail': {'gil': gil_same, 'tempMirror': mirror_same}})

    if case.get('targetLevel'):
        tl = case['targetLevel']
        same = pathlib.Path(tl['tempMirrorBefore']).read_bytes() == pathlib.Path(tl['tempMirrorAfter']).read_bytes()
        formal_after_same = pathlib.Path(tl['tempMirrorAfter']).read_bytes() == gil_after
        findings.append({'id': 'targetTempMirror.equalsFormalAfter',
                         'status': 'pass' if formal_after_same else 'defect',
                         'detail': {'mirror_equals_formal': formal_after_same,
                                    'mirror_unchanged': same}})

    # ---- 3. changed roots --------------------------------------------------
    def parse_level(payload, label):
        try:
            return spans(payload), None
        except (ValueError, IndexError) as exc:
            findings.append({'id': f'{label}.parse', 'status': 'defect', 'detail': f'payload does not walk as protobuf: {exc}'})
            return None, exc

    if payload_before is None or payload_after is None:
        findings.append({'id': 'gil.skipped', 'status': 'defect', 'detail': 'container framing failed'})
        return finish(case, findings, blocked, args)

    walk_before, err = parse_level(payload_before, 'gilBefore')
    walk_after, err2 = parse_level(payload_after, 'gilAfter')
    if walk_before is None or walk_after is None:
        return finish(case, findings, blocked, args)

    roots_before, roots_after = {}, {}
    for field, wire, payload, raw in walk_before:
        roots_before.setdefault(field, []).append(raw)
    for field, wire, payload, raw in walk_after:
        roots_after.setdefault(field, []).append(raw)
    if set(roots_before) != set(roots_after):
        findings.append({'id': 'gil.rootSet', 'status': 'defect',
                         'detail': {'onlyBefore': sorted(set(roots_before) - set(roots_after)),
                                    'onlyAfter': sorted(set(roots_after) - set(roots_before))}})
    else:
        findings.append({'id': 'gil.rootSet', 'status': 'pass', 'detail': {'roots': len(roots_before)}})
    by_root_delta = {str(f): sum(len(r) for r in roots_after.get(f, [])) - sum(len(r) for r in roots_before.get(f, []))
                     for f in sorted(set(roots_before) | set(roots_after))}
    accounted = sum(by_root_delta.values())
    findings.append({'id': 'gil.byteDeltaAccountedPerRoot',
                     'status': 'pass' if accounted == len(payload_after) - len(payload_before) else 'defect',
                     'detail': {'payload_delta': len(payload_after) - len(payload_before),
                                'sum_of_root_deltas': accounted,
                                'per_root': {k: v for k, v in by_root_delta.items() if v}}})
    changed = sorted({f for f in set(roots_before) | set(roots_after)
                      if roots_before.get(f) != roots_after.get(f)})
    declared = set(case.get('declaredChangedRoots') or [])
    allowed_shape = {5, 6, 46}
    undeclared = [f for f in changed if f not in declared and f not in allowed_shape]
    findings.append({'id': 'gil.changedRootsDeclared',
                     'status': 'pass' if not undeclared else 'defect',
                     'detail': {'changed': changed, 'declared': sorted(declared),
                                'undeclared': undeclared}})
    for field in ALWAYS_STABLE_ROOTS:
        ok = roots_before.get(field) == roots_after.get(field)
        findings.append({'id': f'gil.root{field}.unchanged', 'status': 'pass' if ok else 'defect',
                         'detail': {'before_items': len(roots_before.get(field, [])),
                                    'after_items': len(roots_after.get(field, []))}})

    # ---- 4. entity set delta ----------------------------------------------
    ids_before, ids_after = entity_ids(payload_before), entity_ids(payload_after)
    delta = case.get('entityDelta') or {}
    added = sorted(ids_after - ids_before)
    removed = sorted(ids_before - ids_after)
    expected_added = sorted(delta.get('addedIds') or [])
    expected_removed = sorted(delta.get('removedIds') or [])
    findings.append({'id': 'gil.entitySetDelta',
                     'status': 'pass' if added == expected_added and removed == expected_removed else 'defect',
                     'detail': {'added': added, 'removed': removed,
                                'expectedAdded': expected_added, 'expectedRemoved': expected_removed}})

    # ---- 5. root46 shape + update pattern ---------------------------------
    r46_before = [p for f, w, p, _ in walk_before if f == 46]
    r46_after = [p for f, w, p, _ in walk_after if f == 46]
    if len(r46_before) > 1 or len(r46_after) > 1:
        findings.append({'id': 'root46.arity', 'status': 'defect',
                         'detail': {'before': len(r46_before), 'after': len(r46_after),
                                    'rule': 'field 46 may occur at most once on each side; absent is a legal before-state'}})
    else:
        findings.append({'id': 'root46.arity', 'status': 'pass',
                         'detail': {'before': len(r46_before), 'after': len(r46_after)}})
    shape_ok, shape_detail = True, {}
    for tag, group in (('before', r46_before), ('after', r46_after)):
        for payload in group:
            n, err = None, None
            try:
                recs = root46_records(payload)
                n = len(recs)
                if len(payload) != 22 * n:
                    err = f'payload {len(payload)} bytes is not 22*{n}'
                elif not 1 <= n <= ROOT46_MAX_RECORDS:
                    err = f'{n} records exceeds the measured maximum {ROOT46_MAX_RECORDS}'
                else:
                    for v1, v2 in recs:
                        r = v1 >> 32
                        if v1 != ((r << 32) | (r ^ K_F1)):
                            err = f'f1 {v1:016x} violates f1=(R<<32)|(R^K_F1)'
                        elif (v2 >> 32) != K_F2HI:
                            err = f'f2 {v2:016x} violates f2_hi32=={K_F2HI:08x}'
                        elif (v2 & 0xFFFFFFFF) != (r ^ K_F2LO):
                            err = f'f2 {v2:016x} violates f2_lo32==R^K_F2LO'
            except (ValueError, IndexError) as exc:
                err = f'parse: {exc}'
            shape_detail[tag] = {'records': n, 'error': err}
            if err:
                shape_ok = False
    findings.append({'id': 'root46.shape', 'status': 'pass' if shape_ok else 'defect',
                     'detail': shape_detail})
    # update pattern
    pat_ok, pat = True, 'n/a'
    if len(r46_before) <= 1 and len(r46_after) <= 1 and shape_ok:
        b = root46_records(r46_before[0]) if r46_before else []
        a = root46_records(r46_after[0]) if r46_after else []
        if not r46_before and not r46_after:
            pat = 'absent-both-sides'
        elif not r46_before and len(a) == 1:
            pat = 'first-record (the field was absent before)'
        elif r46_before and not r46_after:
            pat_ok, pat = False, 'the field disappeared'
        elif r46_before[0] == r46_after[0]:
            pat = 'unchanged'
        elif len(a) == len(b) == 1:
            pat = 'head-replaced (single-record list: the two candidate rules coincide here)'
        elif len(a) == len(b) + 1 and a[1:] == b:
            pat = 'grow-at-front'
        elif len(a) == len(b) and a[1:] == b[1:]:
            pat = 'rewrite-head'
        elif len(a) == len(b) and a[1:] == b[:-1]:
            pat = 'prepend-and-evict-tail'
        else:
            pat_ok, pat = False, f'unrecognised update: {len(b)} -> {len(a)}'
    findings.append({'id': 'root46.updatePattern', 'status': 'pass' if pat_ok else 'defect',
                     'detail': pat})
    # the semantics are NOT established: any root46 change is a named, blocked delta
    if (r46_before or r46_after) and r46_before != r46_after:
        blocked.append({
            'name': 'root46-changed', 'status': 'structurally-characterised-but-unexplained',
            'detail': 'root46 (field 46) content changed; shape and update rule are checked, '
                      'the meaning of the (f1,f2) pair is not established by any stored evidence.',
        })

    # ---- 6. the .gip -------------------------------------------------------
    level_id = str(case['levelId'])
    try:
        eb = {e['level_id']: e for e in gip_level_entries(profile_before)}
        ea = {e['level_id']: e for e in gip_level_entries(profile_after)}
    except (ValueError, IndexError, TypeError) as exc:
        findings.append({'id': 'gip.parse', 'status': 'defect',
                         'detail': f'the profile payload does not walk as protobuf: {exc}'})
        return finish(case, findings, blocked, args)
    if set(eb) != set(ea):
        findings.append({'id': 'gip.levelEntrySet', 'status': 'defect',
                         'detail': {'before': sorted(eb), 'after': sorted(ea)}})
    else:
        findings.append({'id': 'gip.levelEntrySet', 'status': 'pass', 'detail': {'levels': len(eb)}})
    changed_entries = sorted(k for k in eb if k in ea and eb[k]['raw'] != ea[k]['raw'])
    declared_entries = set(case.get('declaredChangedGipEntries') or [])
    unexpected = [k for k in changed_entries if k != int(level_id) and k not in declared_entries]
    findings.append({'id': 'gip.onlyTargetEntryChanged',
                     'status': 'pass' if not unexpected else 'defect',
                     'detail': {'changed': changed_entries, 'target': int(level_id),
                                'unexpected': unexpected}})
    # the target entry may change only in field 3, and only to the save wall clock
    if int(level_id) in eb and int(level_id) in ea:
        b, a = eb[int(level_id)], ea[int(level_id)]
        bf = [v for kind, fn, v in b['fields'] if fn != 3]
        af = [v for kind, fn, v in a['fields'] if fn != 3]
        findings.append({'id': 'gip.targetEntryOtherFields',
                         'status': 'pass' if bf == af else 'defect',
                         'detail': {'before': repr(bf)[:120], 'after': repr(af)[:120]}})
        if case.get('saveWallClock'):
            clock = int(case['saveWallClock'])
            delta = abs((a['timestamp'] or 0) - clock)
            findings.append({'id': 'gip.targetEntryTimestampIsSaveClock',
                             'status': 'pass' if delta <= 2 else 'defect',
                             'detail': {'value': a['timestamp'], 'gilMtime': clock, 'deltaSeconds': delta}})
        else:
            blocked.append({'name': 'gip-timestamp-no-clock-supplied',
                            'status': 'unmeasured',
                            'detail': 'no saveWallClock given: the field changed but its value could not be '
                                      'compared to the save moment in this case file.'})

    # ---- 7. verdict --------------------------------------------------------
    return finish(case, findings, blocked, args)


if __name__ == '__main__':
    raise SystemExit(main())
