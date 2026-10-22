"""Offline envelope repair for the MW static course GIA candidate.

Owned by tools/editor-bridge/repair-static-course-envelope.py.

WHY THIS EXISTS
    build-static-course-asset.py serialises the 34 static entity assets with
    auto-miliastra's `gia.proto` shape (`GIACollection { repeated Asset = 1 }`),
    which produces 34 consecutive root field-1 records and NO root metadata.
    Every native export observed in .runtime/editor-bridge/exports instead uses
    the `gia_graph.proto` shape (`AssetBundle`) and carries FOUR root records:

        field 1 (wire 2) - primary_resource
        field 3 (wire 2) - export_tag   string
        field 4 (wire 0) - varint, constant 1 in every observed native export
        field 5 (wire 2) - engine_version string ('7.0.0' observed)

    field 4 is NOT declared in the reviewed auto-miliastra proto; it is copied
    verbatim rather than synthesised.

WHAT THIS DOES
    Leaves the 34 entity records BYTE-IDENTICAL and appends the missing root
    metadata (3, 4, 5) copied verbatim from one of the project's own native
    graph exports, with only the export filename inside field 3 replaced by
    MW_Static_Course_20260916.gia.

WHAT THIS DELIBERATELY DOES NOT DO
    It does NOT restructure the 34 field-1 records. Native exports show one
    field 1 plus a separate field-2 dependency list, but multi-asset packages
    are not proven absent, so collapsing or re-homing the 34 records would be a
    guess. The repeated-root-1 question is recorded as OPEN in
    envelope-review.json with its falsifier; it is not silently "fixed".

Writes exactly one file: candidate-enveloped.gia. Never overwrites the
original candidate. Offline only: no staging, no bridge call, no game access,
no project-external write.
"""
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILDER = Path(__file__).resolve().parent / 'build-static-course-asset.py'
OUT_DIR = ROOT / '.runtime/editor-bridge/static-level-draft'
CANDIDATE = OUT_DIR / 'MW_Static_Course_20260916.gia'
OUT_GIA = OUT_DIR / 'candidate-enveloped.gia'
MANIFEST = OUT_DIR / 'asset-manifest.json'
EXPORTS = ROOT / '.runtime/editor-bridge/exports'
REPLACEMENT_FILENAME = 'MW_Static_Course_20260916.gia'

ASSET_TOTAL = 34
ROOT_FIELD_PRIMARY = 1
ROOT_FIELD_EXPORT_TAG = 3
ROOT_FIELD_UNDECLARED = 4
ROOT_FIELD_ENGINE_VERSION = 5
BS = chr(92)

sys.path.insert(0, str(ROOT / 'third_party/auto-miliastra/src'))
from miliastra_agent.core.gi_file import GI_TYPE_GIA, read_header, read_payload, wrap_payload
from miliastra_agent.core.proto_gen import asset_pb2

# Reuse the builder's strict record parser so both tools agree byte-for-byte on
# what "one entity record" means. The module name has dashes, hence importlib.
_spec = importlib.util.spec_from_file_location('build_static_course_asset', BUILDER)
_builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_builder)
records = _builder.records


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_payload_from(blob):
    """read_payload() wants a path; re-derive the payload from raw bytes.

    The GI container is a fixed 20-byte big-endian header, then content_length
    payload bytes, then a 4-byte tail magic (see gi_file.py:19-57).
    """
    header = read_header(blob)
    payload = blob[20:20 + header.content_length]
    if len(payload) != header.content_length:
        raise SystemExit('payload is truncated')
    return payload


def select_donor():
    """Newest native export that carries a complete 4-record envelope."""
    if not EXPORTS.is_dir():
        raise SystemExit(f'no native export directory at {EXPORTS}')
    candidates = []
    for path in sorted(EXPORTS.glob('*/*.gia')):
        blob = path.read_bytes()
        try:
            header = read_header(blob)
            if header.file_type != GI_TYPE_GIA:
                continue
            top = records(read_payload_from(blob))
        except Exception:
            continue
        counts = Counter(field for field, _w, _v, _r in top)
        tags = [v for f, w, v, _ in top if f == ROOT_FIELD_EXPORT_TAG and w == 2]
        vers = [v for f, w, v, _ in top if f == ROOT_FIELD_ENGINE_VERSION and w == 2]
        undeclared = [v for f, w, v, _ in top if f == ROOT_FIELD_UNDECLARED and w == 0]
        if counts.get(ROOT_FIELD_PRIMARY) == 1 and len(tags) == 1 \
                and len(vers) == 1 and len(undeclared) == 1:
            candidates.append({'path': path, 'top': top, 'tag': tags[0],
                               'version': vers[0], 'undeclared': undeclared[0]})
    if not candidates:
        raise SystemExit('no native export with a complete f1+f3+f4+f5 envelope found')
    candidates.sort(key=lambda c: (c['path'].stat().st_mtime, str(c['path'])))
    return candidates[-1]


def retag(tag_bytes):
    """Replace only the export filename; keep UID/time/file-id copied exactly."""
    text = tag_bytes.decode('utf-8')
    if BS not in text:
        raise SystemExit(f'export_tag has no path separator: {text!r}')
    prefix = text.rsplit(BS, 1)[0]
    if prefix.count('-') < 2:
        raise SystemExit(f'export_tag does not match {{UID}}-{{TIME}}-{{FILE_ID}}: {text!r}')
    return (prefix + BS + REPLACEMENT_FILENAME).encode('utf-8')


def encode_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_len_field(field, payload):
    return encode_varint((field << 3) | 2) + encode_varint(len(payload)) + payload


def build_envelope(entity_spans, donor):
    body = b''.join(entity_spans)
    meta = (
        encode_len_field(ROOT_FIELD_EXPORT_TAG, retag(donor['tag']))
        + encode_varint((ROOT_FIELD_UNDECLARED << 3) | 0) + encode_varint(donor['undeclared'])
        + encode_len_field(ROOT_FIELD_ENGINE_VERSION, donor['version'])
    )
    return body, meta


def strict_envelope(blob, donor, expected_spans):
    """Assert the observed native envelope shape, not an invented one."""
    header = read_header(blob)
    if header.file_type != GI_TYPE_GIA:
        raise SystemExit(f'output file_type {header.file_type} is not GIA')
    payload = read_payload_from(blob)
    if len(payload) != header.content_length:
        raise SystemExit('output payload length disagrees with header')

    top = records(payload)
    counts = Counter(field for field, _w, _v, _r in top)
    if counts.get(ROOT_FIELD_PRIMARY) != ASSET_TOTAL:
        raise SystemExit(f'expected {ASSET_TOTAL} root field-1 records, got {counts.get(ROOT_FIELD_PRIMARY)}')
    for field, wire in ((ROOT_FIELD_EXPORT_TAG, 2), (ROOT_FIELD_UNDECLARED, 0),
                        (ROOT_FIELD_ENGINE_VERSION, 2)):
        if counts.get(field) != 1:
            raise SystemExit(f'root field {field} count {counts.get(field)}, expected 1')
    if counts != Counter({ROOT_FIELD_PRIMARY: ASSET_TOTAL, ROOT_FIELD_EXPORT_TAG: 1,
                          ROOT_FIELD_UNDECLARED: 1, ROOT_FIELD_ENGINE_VERSION: 1}):
        raise SystemExit(f'unexpected root fields: {dict(counts)}')

    order = [field for field, _w, _v, _r in top]
    if order != [ROOT_FIELD_PRIMARY] * ASSET_TOTAL + [ROOT_FIELD_EXPORT_TAG,
                                                      ROOT_FIELD_UNDECLARED,
                                                      ROOT_FIELD_ENGINE_VERSION]:
        raise SystemExit(f'unexpected root field order: {order[:6]}...')

    spans = [raw for field, _w, _v, raw in top if field == ROOT_FIELD_PRIMARY]
    if spans != expected_spans:
        raise SystemExit('entity records are not byte-identical to the candidate')

    tag = [v for f, _w, v, _r in top if f == ROOT_FIELD_EXPORT_TAG][0].decode('utf-8')
    if not tag.endswith(BS + REPLACEMENT_FILENAME):
        raise SystemExit(f'export_tag filename not replaced: {tag!r}')
    if [v for f, _w, v, _r in top if f == ROOT_FIELD_UNDECLARED][0] != donor['undeclared']:
        raise SystemExit('undeclared root field 4 value was not copied verbatim')
    if [v for f, _w, v, _r in top if f == ROOT_FIELD_ENGINE_VERSION][0] != donor['version']:
        raise SystemExit('engine_version was not copied verbatim')
    return payload, tag


def decode_entities(values):
    """Decode each preserved root field-1 record as an asset_pb2.Asset.

    `records()` returns raw spans (tag+length+value); protobuf needs the value
    bytes alone, so callers pass the wire-2 payloads, not the spans.
    """
    out = []
    for index, raw in enumerate(values):
        asset = asset_pb2.Asset()
        asset.ParseFromString(bytes(raw))
        if asset.WhichOneof('value') != 'entity_data':
            raise SystemExit(f'entity record {index} is not entity_data')
        data = asset.entity_data.data
        comp = data.components[0]
        if comp.WhichOneof('component_data') != 'transform':
            raise SystemExit(f'entity record {index} has no transform')
        out.append({
            'assetId': asset.meta.asset_id,
            'entityId': data.entity_id,
            'name': asset.name,
            'templateId': asset.entity_data.template_id,
            'templateRef': data.template_id_ref,
            'position': [comp.transform.position.x, comp.transform.position.y,
                         comp.transform.position.z],
            'rotation': [comp.transform.rotation.x, comp.transform.rotation.y,
                         comp.transform.rotation.z],
            'scale': [comp.transform.scale.x, comp.transform.scale.y,
                      comp.transform.scale.z],
            'transformBytes': comp.transform.SerializeToString(),
            'nameStaticBlock': data.properties[0].name.static_block,
        })
    return out


def main():
    if not OUT_GIA.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit('refusing to write outside the project')
    if OUT_GIA.resolve() == CANDIDATE.resolve():
        raise SystemExit('refusing to overwrite the original candidate')

    candidate_blob = CANDIDATE.read_bytes()
    if read_header(candidate_blob).file_type != GI_TYPE_GIA:
        raise SystemExit('candidate is not a GIA')

    top = records(read_payload_from(candidate_blob))
    entity_spans = [raw for field, wire, _v, raw in top if field == ROOT_FIELD_PRIMARY and wire == 2]
    if len(entity_spans) != ASSET_TOTAL:
        raise SystemExit(f'candidate has {len(entity_spans)} field-1 records, expected {ASSET_TOTAL}')
    leftover = [field for field, _w, _v, _r in top if field != ROOT_FIELD_PRIMARY]
    if leftover:
        raise SystemExit(f'candidate already has non-field-1 root records: {leftover}')

    before = decode_entities([v for f,w,v,r in top if f == 1 and w == 2])

    donor = select_donor()
    body, meta = build_envelope(entity_spans, donor)
    payload = body + meta
    output = wrap_payload(payload, GI_TYPE_GIA, read_header(candidate_blob).version)
    OUT_GIA.write_bytes(output)

    readback = OUT_GIA.read_bytes()
    _, tag = strict_envelope(readback, donor, entity_spans)
    after_top = records(read_payload_from(readback))
    after = decode_entities([v for f,w,v,r in after_top if f == 1 and w == 2])

    if before != after:
        raise SystemExit('entity decode changed after enveloping')
    if [a['transformBytes'] for a in before] != [a['transformBytes'] for a in after]:
        raise SystemExit('geometry bytes changed after enveloping')

    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
        expected = manifest.get('assets')
        if expected:
            if len(expected) != ASSET_TOTAL:
                raise SystemExit(f'manifest lists {len(expected)} assets, expected {ASSET_TOTAL}')
            for index, (want, got) in enumerate(zip(expected, after)):
                for key in ('assetId', 'entityId', 'name', 'templateId'):
                    if want[key] != got[key]:
                        raise SystemExit(f'asset {index} {key}: {got[key]} != manifest {want[key]}')
                for key in ('position', 'rotation', 'scale'):
                    if [round(float(x), 6) for x in want[key]] != [round(float(x), 6) for x in got[key]]:
                        raise SystemExit(f'asset {index} {key} differs from manifest')

    print(json.dumps({
        'output': str(OUT_GIA.relative_to(ROOT)),
        'outputSha256': sha256(readback),
        'outputBytes': len(readback),
        'payloadBytes': len(payload),
        'entityRecordsPreservedByteIdentical': len(entity_spans),
        'rootFieldOrder': [ROOT_FIELD_PRIMARY] * ASSET_TOTAL
                          + [ROOT_FIELD_EXPORT_TAG, ROOT_FIELD_UNDECLARED, ROOT_FIELD_ENGINE_VERSION],
        'donor': str(donor['path'].relative_to(ROOT)),
        'copiedRootField4Varint': donor['undeclared'],
        'copiedEngineVersion': donor['version'].decode('utf-8'),
        'candidateSha256': sha256(candidate_blob),
        'candidateUnmodified': sha256(CANDIDATE.read_bytes()) == sha256(candidate_blob),
        'repeatedRootField1Restructured': False,
        'geometryDecodedAndUnchanged': True,
        'gameAccepted': False,
        'staged': False,
        'imported': False,
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
