"""Semantic attribution of a save's allowed delta (W5-SAVE candidate, T09).

Why this file exists
--------------------
The pinned G02 gate (``g02_savediff_gate.py``) answers *"is the shape of the
delta legal?"*.  It does not answer *"why is this delta allowed?"*, and in one
place the difference matters: the gate's ``allowed_shape = {5, 6, 46}`` lets
root 5 and root 6 change **without any declaration**.  A save that rewrites an
*existing* entity record in place -- same id set, same record count, same byte
count -- therefore passes every gate check:

  * ``gil.changedRootsDeclared``  -> changed=[5], declared=[], 5 in allowed_shape -> pass
  * ``gil.entitySetDelta``        -> added/removed empty, expected empty         -> pass
  * ``gil.byteDeltaAccountedPerRoot`` -> payload delta 0, per-root delta 0       -> pass

and with root46 reverted to its before value the gate returns ``pass`` for a
save that silently edited content the request never declared.  That is exactly
the failure mode "do not relax a whole root into a blanket ignore" names.

What this module does about it
------------------------------
Every changed root must carry an **attested semantic source**, checked against
the bytes, not against a shape:

  root 5   entity records.  Every retained record must be byte identical; the
           added records must be exactly the declared ``addedIds`` and the
           removed records exactly the declared ``removedIds``.  Source:
           the request's own entity delta.
  root 6   the directory tree.  Parsed to its leaf references ``(f1, f2)``;
           the leaf-reference set may change only by removing declared
           ``removedIds`` and adding declared ``addedIds``.  Source: the
           directory entry that *names* the entity the request created.
  root 46  the level's save-history head (field 46).  **No semantic source
           exists** in this repository: its 32-bit word ``R`` is characterised
           byte-wise but not named.  It is carried as a named blocked delta with
           the missing evidence enumerated; it is never quietly allowed and the
           whole root is never ignored.
  .gip     profile field 2 -> the target level entry -> field 3 must equal the
           save wall clock.  Source: the moment of the save.
  mirrors  ``Temp/<level>.gil`` and ``Temp/Beyond_Local_Save_Player.gip`` must
           be byte identical to their formal file.

An unattested changed root is ``fail``.  A named-but-unexplained delta is
``blocked``.  The verdict is never ``pass`` while root 46 moved.

Read-only: every input is opened read-only; nothing is written outside the
caller-supplied ``out_dir``.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

PASS = 'pass'
FAIL = 'fail'
BLOCKED = 'blocked'

#: roots the delta contract asserts unchanged unless the intent declares them
ALWAYS_STABLE_ROOTS = (1, 2, 10, 27, 39, 40, 41, 52, 53)
#: roots the delta contract lets change *only* under an attested source
SOURCE_BEARING_ROOTS = (5, 6)
#: the save-history root, whose source is not established
ROOT46 = 46
#: measured cap on the save-history list (G02 section 10.4)
ROOT46_MAX_RECORDS = 5
#: the field of a profile level entry that carries the save wall clock
GIP_CLOCK_FIELD = 3
GIP_CLOCK_TOLERANCE_S = 2

MISSING_ROOT46_EVIDENCE = [
    'A live discriminating experiment has not been run: two consecutive saves of one level '
    'inside one session with unchanged content, then a third save after changing one field, '
    'comparing R against the save wall clock, against an entity/graph digest, and against a '
    'save sequence number (G02 section 8 U1).  No offline byte set can substitute for it.',
    'The provenance of the 32-second granularity is unestablished (G02 R-3): the observed '
    'coupling is (R + t) mod 32 is constant per level, which is a relation, not a name.',
    'The meaning of the 0x28 high byte of R and of the constants '
    '(0x3CF25440, 0x4265796F "Beyo", 0x2C013519) is unestablished.',
    'The rule that decides "head rewritten in place" vs "prepend and evict tail" is '
    'unestablished (G02 R-5), so the update form is checked but not explained.',
]


# --------------------------------------------------------------------------- #
# protobuf walking (same wire semantics as the pinned G02 gate; re-implemented
# here so this module never has to hash-match or overwrite a pinned artefact)
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
    """[(field, wire, payload, raw)] or ValueError when the buffer is not protobuf."""
    out, pos = [], 0
    while pos < len(data):
        start = pos
        tag, pos = varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field == 0 or wire not in (0, 1, 2, 5):
            raise ValueError(f'field {field} wire {wire}')
        if wire == 0:
            _, pos = varint(data, pos)
            payload = data[start:pos]
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


def container_payload(raw, expect_subtype, label):
    """Unwrap the .gil/.gip container; returns (payload, finding-detail)."""
    if len(raw) < 24:
        raise ValueError(f'{label}: {len(raw)} bytes is below the container minimum')
    total = int.from_bytes(raw[0:4], 'big')
    version = int.from_bytes(raw[4:8], 'big')
    magic = int.from_bytes(raw[8:12], 'big')
    subtype = int.from_bytes(raw[12:16], 'big')
    inner = int.from_bytes(raw[16:20], 'big')
    trailer = int.from_bytes(raw[20 + inner:24 + inner], 'big')
    if not (total == len(raw) - 4 and version == 1 and magic == 0x326
            and 20 + inner == total and trailer == 0x679 and subtype == expect_subtype):
        raise ValueError(f'{label}: container framing does not hold')
    return raw[20:20 + inner]


def roots(payload):
    """field number -> list of raw records."""
    out = {}
    for field, _wire, _payload, raw in spans(payload):
        out.setdefault(field, []).append(raw)
    return out


def root_payloads(payload, number):
    """field number -> list of the sub-message payloads (wire-2 occurrences)."""
    return [body for field, wire, body, _raw in spans(payload)
            if field == number and wire == 2]


def entity_records(payload):
    """root5 -> [(entity_id, raw_sub_record)] for the repeated field-1 records.

    root5's payload is a repeated ``field 1 wire 2`` record; each record's own
    ``field 1 varint`` is the entity id.
    """
    out = []
    for field, wire, body, raw in spans(payload):
        if field != 1 or wire != 2 or not body:
            continue
        if body[0] != 0x08:
            raise ValueError(f'entity record starts {body[0]:#x}, not 0x08')
        ent_id, _ = varint(body, 1)
        out.append((ent_id, raw))
    return out


def registry_leaf_refs(payload):
    """Every ``field 5 -> (field 1, field 2)`` leaf reference in the root6 tree.

    The directory tree nests, so the walk is recursive over every length
    delimited sub-message.  A leaf is a ``field 5`` message whose body is
    ``08 <varint f1> 10 <varint f2>``; ``f2`` is the id the entry points at.
    """
    out, stack = [], [payload]
    while stack:
        blob = stack.pop()
        try:
            walked = spans(blob)
        except (IndexError, ValueError):
            continue
        for field, wire, body, _raw in walked:
            if wire != 2:
                continue
            if field == 5:
                try:
                    if body[0] != 0x08:
                        continue
                    v1, end1 = varint(body, 1)
                    if body[end1] != 0x10:
                        continue
                    v2, _ = varint(body, end1 + 1)
                except (IndexError, ValueError):
                    continue
                out.append((v1, v2))
            else:
                stack.append(body)
    return out


def level_content_view(raw):
    """The level container's SEMANTIC content: root5 records + root6 registry.

    This is the view that answers *"did this save change any content at all?"* --
    the one judgement a save that declares no entity delta needs, and the one the
    create-shaped decoder cannot supply.

    root46 (the save-history head) is deliberately EXCLUDED.  Its meaning is not
    established in this repository (G02 U1), so ``attribute_save_delta`` carries
    its movement as a named blocked delta; it is never folded into a statement
    about the level's *content*.  Two saves whose root5/root6 are identical have
    the same content here even if the save-history head was rewritten.

    Raises ``ValueError``/``IndexError`` when the bytes do not read as this
    format, so a caller must decide what an unreadable container means rather
    than read it as "no change".
    """
    payload = container_payload(raw, 2, 'level')
    records = sorted(r for body in root_payloads(payload, 5)
                     for _entity_id, r in entity_records(body))
    refs = sorted(tuple(x) for p in root_payloads(payload, 6)
                  for x in registry_leaf_refs(p))
    return {'entityRecords': records, 'registryRefs': refs}


def level_content_digest(view):
    """A stable sha256 over a :func:`level_content_view`, for a report to name."""
    blob = json.dumps({'entityRecords': [r.hex() for r in view['entityRecords']],
                       'registryRefs': view['registryRefs']},
                      sort_keys=True, separators=(',', ':')).encode('utf-8')
    return _sha(blob)


def save_history_records(payload):
    """root46 -> [(R, raw)] where R = f1 >> 32, or None when the root is absent."""
    group = [raw for field, _w, _p, raw in spans(payload) if field == ROOT46]
    if not group:
        return None
    if len(group) > 1:
        raise ValueError(f'field {ROOT46} occurs {len(group)} times on one side')
    _key_len, pos = varint(group[0], 0)
    size, pos = varint(group[0], pos)
    body = group[0][pos:pos + size]
    out, p = [], 0
    while p < len(body):
        if body[p] != 0x0A:
            raise ValueError(f'history record starts {body[p]:#x}, not 0x0a')
        n = body[p + 1]
        rec = body[p + 2:p + 2 + n]
        p += 2 + n
        if len(rec) != n or rec[0] != 0x08:
            raise ValueError('history record body malformed')
        v1, e1 = varint(rec, 1)
        if rec[e1] != 0x10:
            raise ValueError('history record second tag is not 0x10')
        v2, _ = varint(rec, e1 + 1)
        out.append({'R': v1 >> 32, 'f2': v2})
    return out


def gip_level_entries(payload):
    """profile field 2 -> [{level_id, name, timestamp, raw}]."""
    out = []
    for field, wire, body, raw in spans(payload):
        if wire != 2 or field != 2:
            continue
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
        out.append({'level_id': entry.get(1), 'name': entry.get(2),
                    'timestamp': entry.get(GIP_CLOCK_FIELD), 'raw': raw})
    return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _read(path):
    return pathlib.Path(path).read_bytes()


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _item(check_id, ok, semantic_source, detail, status=None):
    return {'id': check_id,
            'status': status or (PASS if ok else FAIL),
            'semanticSource': semantic_source,
            'detail': detail}


def _verify_multiset(before, after, declared_added, declared_removed):
    """Itemise a multiset delta with byte identity, not just set membership."""
    from collections import Counter
    cb, ca = Counter(before), Counter(after)
    added = sorted((ca - cb).elements())
    removed = sorted((cb - ca).elements())
    return {
        'added': sorted(added), 'removed': sorted(removed),
        'declaredAdded': sorted(declared_added), 'declaredRemoved': sorted(declared_removed),
        'addedMatches': added == sorted(declared_added),
        'removedMatches': removed == sorted(declared_removed),
    }


# --------------------------------------------------------------------------- #
# the attribution itself
# --------------------------------------------------------------------------- #

def attribute_save_delta(case):
    """Attribute every allowed delta in `case` to a semantic source.

    `case` keys: caseId, operation, levelId, gilBefore, gilAfter, gipBefore,
    gipAfter, declaredChangedRoots, entityDelta {addedIds, removedIds}, intent,
    saveWallClock, and optionally targetTempMirrorBefore/After, protectedLevels,
    accountSet {before, after}.
    """
    findings = []
    blocked = []
    attested_roots = set()

    level_id = str(case.get('levelId'))
    declared_added = list((case.get('entityDelta') or {}).get('addedIds') or [])
    declared_removed = list((case.get('entityDelta') or {}).get('removedIds') or [])
    intent = case.get('intent') or {}

    gil_before = _read(case['gilBefore'])
    gil_after = _read(case['gilAfter'])
    pay_before = container_payload(gil_before, 2, 'gilBefore')
    pay_after = container_payload(gil_after, 2, 'gilAfter')

    # ---- root 5: entity records -------------------------------------------
    rec_before = [r for body in root_payloads(pay_before, 5) for r in entity_records(body)]
    rec_after = [r for body in root_payloads(pay_after, 5) for r in entity_records(body)]
    id_before = [i for i, _ in rec_before]
    id_after = [i for i, _ in rec_after]
    retained = sorted(set(id_before) & set(id_after))
    retained_moved = sorted(i for i in retained
                            if dict(rec_before)[i] != dict(rec_after)[i])
    delta5 = _verify_multiset(id_before, id_after, declared_added, declared_removed)
    ok5 = (delta5['addedMatches'] and delta5['removedMatches'] and not retained_moved
           and len(id_after) == len(set(id_after)))
    findings.append(_item(
        'delta.root5.recordsAttributed', ok5,
        {'kind': 'declared-entity-delta',
         'attestedTo': {'addedIds': sorted(declared_added), 'removedIds': sorted(declared_removed),
                        'intentEntityId': intent.get('entityId')},
         'rule': 'root5 may change only by gaining exactly the declared entities and losing exactly '
                 'the declared ones; every retained entity record must stay byte identical, so an '
                 'in-place rewrite of an existing entity is a defect and not an allowed shape'},
        {'entityRecordsBefore': len(id_before), 'entityRecordsAfter': len(id_after),
         'added': delta5['added'], 'removed': delta5['removed'],
         'declaredAdded': delta5['declaredAdded'], 'declaredRemoved': delta5['declaredRemoved'],
         'retainedRecordsRewritten': retained_moved}))
    if ok5:
        attested_roots.add(5)

    # ---- root 6: directory tree -------------------------------------------
    r6_before = [p for f, w, p, _ in spans(pay_before) if f == 6]
    r6_after = [p for f, w, p, _ in spans(pay_after) if f == 6]
    ref_before = sorted([tuple(x) for p in r6_before for x in registry_leaf_refs(p)])
    ref_after = sorted([tuple(x) for p in r6_after for x in registry_leaf_refs(p)])
    delta6 = _verify_multiset([b for _a, b in ref_before], [b for _a, b in ref_after],
                              declared_added, declared_removed)
    # the ref must be unique on the after side and its target must be declared
    ok6 = (delta6['addedMatches'] and delta6['removedMatches']
           and len(ref_after) == len(set(ref_after)))
    findings.append(_item(
        'delta.root6.registryAttributed', ok6,
        {'kind': 'declared-entity-delta',
         'attestedTo': {'addedRefs': delta6['added'], 'removedRefs': delta6['removed'],
                        'intentEntityId': intent.get('entityId')},
         'rule': 'the directory tree may gain or lose leaf references only for the declared entity '
                 'ids; the added leaf names the entity the request created, which is what makes the '
                 'byte growth an attributed delta instead of an allowed shape'},
        {'addedRefs': delta6['added'], 'removedRefs': delta6['removed'],
         'leavesBefore': len(ref_before), 'leavesAfter': len(ref_after)}))
    if ok6:
        attested_roots.add(6)

    # ---- root 46: the save-history head ------------------------------------
    try:
        hist_before = save_history_records(pay_before)
        hist_after = save_history_records(pay_after)
        parse_error = None
    except (ValueError, IndexError) as exc:
        hist_before = hist_after = None
        parse_error = str(exc)
    root46_moved = (hist_before != hist_after)
    if parse_error is not None:
        findings.append(_item('delta.root46.parse', False, None,
                              {'error': parse_error, 'rule': 'a root that cannot be parsed cannot be '
                                                             'attributed'}, FAIL))
    elif root46_moved:
        n_before = len(hist_before or [])
        n_after = len(hist_after or [])
        grew = n_after > n_before
        growth_ok = (not grew) or (n_before < ROOT46_MAX_RECORDS)
        findings.append(_item(
            'delta.root46.growthRule', growth_ok, None,
            {'recordsBefore': n_before, 'recordsAfter': n_after,
             'measuredCap': ROOT46_MAX_RECORDS,
             'rule': 'growth is legal only while the list is below its measured cap (G02 section '
                     '10.8: 3 growths, all at n_before in {2,3,4}; 0 growths in 62 samples at '
                     'n_before = 5)'},
            FAIL if not growth_ok else PASS))
        findings.append(_item(
            'delta.root46.semanticSource', False, None,
            {'recordsBefore': [f'{r["R"]:08x}' for r in (hist_before or [])],
             'recordsAfter': [f'{r["R"]:08x}' for r in (hist_after or [])],
             'missingEvidence': MISSING_ROOT46_EVIDENCE,
             'rule': 'the save-history root moved and no semantic source for its 32-bit word exists '
                     'in this repository; it is carried as a named blocked delta, never as a '
                     'blanket ignore of the whole root'},
            BLOCKED))
        blocked.append({
            'name': 'root46-changed',
            'status': 'semantically-unattributed',
            'semanticSource': None,
            'detail': f'root46 moved ({len(hist_before or [])} -> {len(hist_after or [])} records); '
                      f'R values {[f"{r["R"]:08x}" for r in (hist_after or [])][:2]}',
            'missingEvidence': MISSING_ROOT46_EVIDENCE,
        })
    else:
        findings.append(_item('delta.root46.semanticSource', True,
                              {'kind': 'not-a-delta'}, {'records': hist_after}))

    # ---- every other changed root must be stable, or nothing --------------
    rb = roots(pay_before)
    ra = roots(pay_after)
    changed = sorted({f for f in set(rb) | set(ra) if rb.get(f) != ra.get(f)})
    undeclared_shape = [f for f in changed
                        if f not in attested_roots and f != ROOT46
                        and f not in (case.get('declaredChangedRoots') or [])]
    stable_violations = [f for f in ALWAYS_STABLE_ROOTS
                         if rb.get(f) != ra.get(f)
                         and f not in (case.get('declaredChangedRoots') or [])]
    findings.append(_item(
        'delta.noUnattestedChangedRoot',
        not undeclared_shape and not stable_violations,
        {'kind': 'attribution-coverage'},
        {'changedRoots': changed, 'attestedRoots': sorted(attested_roots),
         'root46CarriedAsBlocked': ROOT46 in changed,
         'unattestedChangedRoots': undeclared_shape,
         'stableRootsViolated': stable_violations,
         'rule': 'a changed root that is neither attested by the declared intent nor carried as a '
                 'named blocked delta is a defect -- this is the rule that refuses to relax a whole '
                 'root into a blanket ignore'}))

    # ---- .gip --------------------------------------------------------------
    gip_before = _read(case['gipBefore'])
    gip_after = _read(case['gipAfter'])
    prof_before = container_payload(gip_before, 1, 'gipBefore')
    prof_after = container_payload(gip_after, 1, 'gipAfter')
    eb = {e['level_id']: e for e in gip_level_entries(prof_before)}
    ea = {e['level_id']: e for e in gip_level_entries(prof_after)}
    target = int(level_id)
    moved_entries = sorted(k for k in eb if k in ea and eb[k]['raw'] != ea[k]['raw'])
    other_fields_ok = True
    detail_gip = {'movedEntries': moved_entries, 'target': target}
    if target in eb and target in ea:
        b = {fn: v for fn, v in _fields_of(eb[target]) if fn != GIP_CLOCK_FIELD}
        a = {fn: v for fn, v in _fields_of(ea[target]) if fn != GIP_CLOCK_FIELD}
        other_fields_ok = b == a
        detail_gip['targetEntryOtherFieldsIntact'] = other_fields_ok
        # A save may either move the target entry's last-save clock to this save's
        # moment, or leave the entry entirely untouched.  The second is a LEGAL
        # NO-OP (leaf D23.01.02): nothing about the content changed, so there is
        # no clock to compare, and demanding that the entry "moved" reports a
        # non-event as a defect.  A clock that moved to anything but this save's
        # moment is still refused, and another level's entry moving is still
        # neither of the two allowed shapes.
        entry_moved = eb[target]['raw'] != ea[target]['raw']
        detail_gip['targetEntryMoved'] = entry_moved
        if not entry_moved:
            detail_gip['clockComparable'] = ('the target entry did not move: a legal no-op has no '
                                             'clock to compare')
            ok_gip = True
        elif case.get('saveWallClock') is None:
            detail_gip['clockComparable'] = 'no saveWallClock supplied'
            ok_gip = False
        else:
            clock = int(case['saveWallClock'])
            delta_s = abs((ea[target]['timestamp'] or 0) - clock)
            detail_gip.update({'clockInFile': ea[target]['timestamp'], 'saveWallClock': clock,
                               'deltaSeconds': delta_s})
            ok_gip = delta_s <= GIP_CLOCK_TOLERANCE_S
    else:
        ok_gip = False
    # The profile movement a save is allowed is exactly "the target entry" (its
    # last-save clock) or "nothing at all" (a legal no-op).  The entry-set rule
    # itself (a level entry appearing/disappearing) stays with the gate
    # (gip.levelEntrySet); the no-op flag additionally records that set stability,
    # so it can never call a save that added or dropped a profile entry a no-op.
    entries_stable = set(eb) == set(ea)
    detail_gip['profileEntrySetStable'] = entries_stable
    detail_gip['legalNoOp'] = bool(not moved_entries and entries_stable and ok_gip
                                   and other_fields_ok)
    ok_gip = ok_gip and other_fields_ok and moved_entries in ([], [target])
    findings.append(_item(
        'delta.gip.targetEntryIsSaveClock', ok_gip,
        {'kind': 'save-moment',
         'attestedTo': {'field': f'profile.field2[level={level_id}].field{GIP_CLOCK_FIELD}',
                        'saveWallClock': case.get('saveWallClock'),
                        'toleranceSeconds': GIP_CLOCK_TOLERANCE_S},
         'rule': 'the only profile field a save may move is the target level entry last-save '
                 'timestamp, and its value must be the wall clock of this save; a save that moves '
                 'no profile entry at all is a legal no-op and is admitted, but another level entry '
                 'moving is a defect'},
        detail_gip))

    # ---- mirrors -----------------------------------------------------------
    if case.get('targetTempMirrorBefore') and case.get('targetTempMirrorAfter'):
        mirror = _read(case['targetTempMirrorAfter'])
        findings.append(_item(
            'delta.tempMirror.isByteIdenticalMirror', mirror == gil_after,
            {'kind': 'container-mirror',
             'attestedTo': {'mirror': str(case['targetTempMirrorAfter'])},
             'rule': 'the Temp mirror is the formal file byte for byte; the mirror relation is '
                     'itself the checked object, not noise to be ignored'},
            {'mirrorSha256': _sha(mirror), 'formalSha256': _sha(gil_after)}))
    if case.get('gipTempMirrorAfter'):
        findings.append(_item(
            'delta.gipTempMirror.isByteIdenticalMirror',
            _read(case['gipTempMirrorAfter']) == gip_after,
            {'kind': 'container-mirror'},
            {'mirrorSha256': _sha(_read(case['gipTempMirrorAfter'])),
             'formalSha256': _sha(gip_after)}))

    # ---- protected siblings ------------------------------------------------
    protected = case.get('protectedLevels') or {}
    if protected:
        bad = []
        detail = {}
        for lv, pair in protected.items():
            same = (_read(pair['gilBefore']) == _read(pair['gilAfter'])
                    and _read(pair['tempMirrorBefore']) == _read(pair['tempMirrorAfter']))
            detail[lv] = same
            if not same:
                bad.append(lv)
        findings.append(_item(
            'delta.protectedLevelsUnchanged', not bad,
            {'kind': 'no-delta', 'attestedTo': {'levels': sorted(protected)},
             'rule': 'every level other than the target must be byte identical, formal file and '
                     'mirror alike'},
            {'unchanged': detail, 'violations': bad}))

    # ---- account set -------------------------------------------------------
    acct = case.get('accountSet')
    if acct:
        before = {f['relpath']: f['sha256'] for f in json.loads(_read(acct['before']))['files']}
        after = {f['relpath']: f['sha256'] for f in json.loads(_read(acct['after']))['files']}
        allowed = {p.format(level=level_id) for p in ALLOWED_ACCOUNT_FILES}
        moved = sorted(k for k in before if before[k] != after.get(k))
        extra = [k for k in moved if k not in allowed]
        findings.append(_item(
            'delta.accountSetExactlyAllowedFiles', not extra,
            {'kind': 'operation-scope', 'attestedTo': {'allowed': sorted(allowed)}},
            {'changed': moved, 'allowed': sorted(allowed), 'unexpected': extra}))

    # ---- verdict -----------------------------------------------------------
    statuses = [f['status'] for f in findings]
    if FAIL in statuses:
        verdict = FAIL
    elif BLOCKED in statuses or blocked:
        verdict = BLOCKED
    else:
        verdict = PASS
    return {
        'scope': 'save_delta_attribution',
        'caseId': case.get('caseId'),
        'operation': case.get('operation', 'save'),
        'levelId': case.get('levelId'),
        'verdict': verdict,
        'findings': findings,
        'blockedNamedDeltas': blocked,
        'attestedChangedRoots': sorted(attested_roots),
        'rule': 'every allowed delta must name a semantic source; an unattested change is a defect, '
                'a named but unexplained change is blocked, and the whole-root ignore is never '
                'available',
    }


#: the account file set one save may change (G02 section 2.1)
ALLOWED_ACCOUNT_FILES = (
    'Beyond_Local_Save_Level/{level}/{level}.gil',
    'Temp/{level}.gil',
    'Beyond_Local_Save_Player.gip',
    'Temp/Beyond_Local_Save_Player.gip',
)


def _fields_of(entry):
    """Re-expose a gip entry's (field, value) pairs from its raw record."""
    out = []
    p = 0
    inner = entry['raw']
    # raw = key + length + body; unwrap
    _tag, p = varint(inner, 0)
    size, p = varint(inner, p)
    body = inner[p:p + size]
    q = 0
    while q < len(body):
        t, q = varint(body, q)
        fn, fw = t >> 3, t & 7
        if fw == 0:
            v, q = varint(body, q)
            out.append((fn, v))
        elif fw == 2:
            n, q = varint(body, q)
            out.append((fn, body[q:q + n]))
            q += n
        else:
            raise ValueError(f'gip entry wire {fw}')
    return out
