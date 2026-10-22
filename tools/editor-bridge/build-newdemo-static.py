"""Offline, raw-preserving transplantation of 34 native saved platform entities.

Does not write user saves or retire runtime graphs. The caller must retire the
two spawn flows and verify native loading/save/playtest separately.
"""
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('raw_draft', Path(__file__).with_name('build-static-level-draft.py'))
raw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(raw)
from miliastra_agent.core.gi_file import read_header, wrap_payload
from miliastra_agent.core.wire import get_bytes_fields, get_varint
from miliastra_agent.parsers.gil import parse_gi_file

OUT = ROOT / '.runtime/verification/newdemo-20260919'
SOURCE = OUT / 'platforms-saved.gil'
DONOR = ROOT / '.runtime/editor-bridge/static-entity-research/static-retired-saved-snapshot/level.gil'
CANDIDATE = OUT / 'newdemo-static-only-candidate.gil'
REPORT = OUT / 'newdemo-static-only-report.json'


def only(data, field):
    values = get_bytes_fields(data, field)
    assert len(values) == 1, (field, len(values))
    return values[0]


def replace(data, field, replacement):
    assert sum(f == field for f, _, _, _ in raw.spans(data)) == 1
    return b''.join(raw.rec(f, replacement) if f == field else r
                    for f, w, p, r in raw.spans(data))


def category(data):
    matches = [p for f, w, p, r in raw.spans(data)
               if f == 1 and w == 2 and get_varint(p, 1) == 3]
    assert len(matches) == 1
    return matches[0]


def replace_category(data, replacement):
    return b''.join(raw.rec(1, replacement)
                    if f == 1 and w == 2 and get_varint(p, 1) == 3 else r
                    for f, w, p, r in raw.spans(data))


def main():
    source_bytes, donor_bytes = SOURCE.read_bytes(), DONOR.read_bytes()
    h = read_header(source_bytes)
    source, donor = source_bytes[20:-4], donor_bytes[20:-4]
    assert len(source) == h.content_length and h.file_type == 2
    source_doc, donor_doc = parse_gi_file(SOURCE), parse_gi_file(DONOR)
    assert source_doc.level_name.startswith('newdemo')
    assert source_doc.entity_count == 11 and source_doc.node_graph_count == 3
    selected = [e for e in donor_doc.entities if e.name.startswith('MW_Static_P')]
    assert len(selected) == 34
    ids = {e.entity_id for e in selected}
    assert ids == set(range(1077936129, 1077936163))
    assert Counter(e.template_id for e in selected) == {20001224:8, 20001875:9, 20001876:4, 20001877:4, 20001878:9}
    assert Counter(e.name.split('_')[2] for e in selected) == {'P0':9,'P1':4,'P2':4,'P3':4,'P4':4,'P5':9}
    # Conservative whole-payload collision test includes unknown fields too.
    assert all(raw._enc_varint(i) not in source for i in ids)
    occurrences = {}
    for f, w, p, r in raw.spans(donor):
        if w == 2:
            count = sum(p.count(raw._enc_varint(i)) for i in ids)
            if count:
                occurrences[f] = count
    assert occurrences == {5:34, 6:34}, occurrences

    source5, donor5 = only(source, 5), only(donor, 5)
    additions = [r for f,w,p,r in raw.spans(donor5)
                 if f == 1 and w == 2 and get_varint(p,1) in ids]
    assert len(additions) == 34
    source6, donor6 = only(source, 6), only(donor, 6)
    sc, dc = category(source6), category(donor6)
    sl, dl = only(sc,3), only(dc,3)
    refs = [r for f,w,p,r in raw.spans(dl)
            if f == 5 and w == 2 and get_varint(p,1) == 200 and get_varint(p,2) in ids]
    assert len(refs) == 34
    # Exact inverse in the donor establishes that copied directory additions
    # share the new file's existing category shell, without copying old folders.
    assert b''.join(r for f,w,p,r in raw.spans(dl) if r not in refs) == sl
    next5 = source5 + b''.join(additions)
    next6 = replace_category(source6, replace(sc,3,sl+b''.join(refs)))
    payload = replace(replace(source,5,next5),6,next6)
    candidate = wrap_payload(payload,h.file_type,h.version)
    # Prove deleting only the additions recovers every byte of the source.
    inverse5 = b''.join(r for f,w,p,r in raw.spans(next5) if r not in additions)
    inverse6 = replace_category(next6, replace(category(next6),3,sl))
    inverse = replace(replace(payload,5,inverse5),6,inverse6)
    assert inverse == source
    assert wrap_payload(inverse,h.file_type,h.version) == source_bytes
    assert [(f,r) for f,w,p,r in raw.spans(source) if f not in (5,6)] == [(f,r) for f,w,p,r in raw.spans(payload) if f not in (5,6)]
    CANDIDATE.write_bytes(candidate)
    result = parse_gi_file(CANDIDATE)
    assert result.entity_count == 45
    added = [e for e in result.entities if e.entity_id in ids]
    assert sorted(e.model_dump_json() for e in added) == sorted(e.model_dump_json() for e in selected)
    assert result.node_graphs == source_doc.node_graphs
    report = {
        'status':'offline-verified; native load/save/playtest pending',
        'source':str(SOURCE),'donor':str(DONOR),'candidate':str(CANDIDATE),
        'sourceSha256':hashlib.sha256(source_bytes).hexdigest(),
        'donorSha256':hashlib.sha256(donor_bytes).hexdigest(),
        'candidateSha256':hashlib.sha256(candidate).hexdigest(),
        'sourceBytes':len(source_bytes),'candidateBytes':len(candidate),
        'changedRootFields':[5,6], 'fullInverseEqualsSource':True,
        'allOtherRootFieldsByteIdentical':True, 'graphsUnchanged':True,
        'runtimeSpawnRetired':False,
        'entityRecordPath':'root5/f1',
        'directoryRecordPath':'root6/f1[f1=3]/f3/f5[f1=200]',
        'donorEntityIdVarintOccurrencesByRoot':occurrences,
        'idMapping':{str(i):i for i in sorted(ids)},
        'idPolicy':'Identity mapping: all 34 IDs absent as varint bytes throughout target payload',
        'platforms':[e.model_dump(mode='json') for e in sorted(selected,key=lambda e:e.name)],
        'nextStep':'Retire runtime spawn flows using native API, merge only native-exported graph leaves, then reload and verify editable static geometry and playtest.'
    }
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['status','candidateSha256','candidateBytes','changedRootFields','fullInverseEqualsSource']},indent=2))


if __name__ == '__main__':
    main()
