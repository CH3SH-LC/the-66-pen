#!/usr/bin/env python3
"""Resolve the editor's obfuscated method-proxy slots to their real targets.

The editor is protected with a method-proxy pass: an ordinary call is rewritten to
`SomeDelegateType.xyVYfsr3qg0(args..., slotField)`, where `slotField` is a static
field holding the real target. 9,289 delegate types carry such a slot.

The mapping from slot field -> target method is itself an embedded resource
(`lPRYCw3VuDtuyqlGC3.EF0pHfiGVFAML29fxc`, 277,824 bytes = 34,728 pairs of
(fieldToken, methodToken)), obfuscated with a keyless 4-byte-block stream cipher.

The cipher structure is retained from the validated legacy decoder. Resource names
and five seed constants are selected only by a known source DLL SHA-256. The 7.1
profile comes from the new decoder source recorded under
`.runtime/verification/update-repair-20260924/proxy-decoder-7.1.cs`.
Unknown builds, invalid tokens and cross-build output replacement are refused.
A decoded proxy table does not authorize live reflection or game calls.

Read-only: opens the editor assembly for reading, writes only the files named on the
command line. Nothing here executes editor code or touches a running process.

Usage:
    python resolve-proxy.py --fields A B C [--dump FILE]
    python resolve-proxy.py --all --dump FILE
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPS = ROOT / ".runtime/mvp/ipc-research/deps"
DEFAULT_DLL = Path("D:/games/Genshin Impact Game/BeyondAssets/BeyondAssistEditor/BeyondEditor.dll")
PROXY_RESOURCE = "lPRYCw3VuDtuyqlGC3.EF0pHfiGVFAML29fxc"
LEGACY_SEEDS = (571931940, 1166174991, 520322208, 1392709680, 1674875638)
# These profiles approve offline resource decoding only, never a live Adapter.
# 7.1 constants were read from OpFPXw6L1ZQ IL/decompilation and every decoded
# token was independently checked against this assembly's metadata tables.
PROFILES = {
    "d4b429a371505ff5252e5a869a8fc250cd0924440a648fdb844a0eebed083841":
        (PROXY_RESOURCE, LEGACY_SEEDS),
    "565dda11883f0220bae050438fcf52b2288f26b61ed656e2b4cd6d69b41a678a":
        ("VuZ211wIp9Ev5FRdaD.jO4p2aLMyHPvFLPR2C",
         (1691843529, 247286963, 196776378, 2064580269, 1990021690)),
}

sys.path.insert(0, str(DEPS))
import dnfile  # noqa: E402


def _u(x: int) -> int:
    return x & 0xFFFFFFFF


def decode_map(data: bytes, seeds=LEGACY_SEEDS) -> bytes:
    """Validated transcription of the project's existing proxy-map decoder."""
    s = 0
    out = bytearray()
    for pos in range(0, len(data), 4):
        n11, n12, n14, n15, n16 = seeds
        n13 = s
        n14 = _u(n12 + n15 + n15)
        n11 = _u(n11 + n12)
        signedshort = (n14 & 65535) - 65536 if n14 & 32768 else n14 & 65535
        n17 = _u(int(float(signedshort) / n12 + n12))
        n12 = _u((_u(44464 + n14) ^ n17) + 44464)
        n15 = _u(n15 * n15) % 1249685033
        n11 = _u(203431810 * (n11 & 15) + (n11 >> 4))
        n14 = _u(134061018 * (n14 & 15) - (n14 >> 4))
        n14 = _u(37936 * n14 - n11)
        n13 = _u(n13 ^ (n13 >> 19))
        n13 = _u(n13 + n12)
        n13 = _u(n13 ^ (n13 << 5))
        n13 = _u(n13 + n15)
        n13 = _u(n13 ^ (n13 >> 1))
        n13 = _u(n13 + n16)
        n13 = _u((_u((n14 << 6) - n12) ^ n15) - n13)
        s = _u(s + n13)
        block = data[pos : pos + 4]
        v = int.from_bytes(block, "little") ^ s
        out += v.to_bytes(4, "little")[: len(block)]
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll", default=str(DEFAULT_DLL))
    ap.add_argument("--fields", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dump", default=None)
    args = ap.parse_args()

    with Path(args.dll).open("rb") as source:
        source_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    profile = PROFILES.get(source_sha256)
    if profile is None:
        print("unsupported editor DLL for offline proxy decoding: " + source_sha256, file=sys.stderr)
        return 2
    resource_name, seeds = profile
    output_meta = Path(str(args.dump) + ".source.json") if args.dump else None
    if args.dump and (Path(args.dump).exists() or output_meta.exists()):
        print("output or sidecar already exists; use a new output path", file=sys.stderr)
        return 2
    pe = dnfile.dnPE(args.dll, clr_lazy_load=True)
    try:
        resource = next(r.data for r in pe.net.resources if str(r.name) == resource_name)
    except StopIteration:
        print(f"resource {resource_name} not found", file=sys.stderr)
        return 1
    if not isinstance(resource, bytes) or not resource or len(resource) % 8:
        print("invalid proxy resource shape", file=sys.stderr)
        return 2
    decoded = decode_map(resource, seeds)
    entries = list(struct.iter_unpack("<II", decoded))
    counts = {4: len(pe.net.mdtables.Field.rows), 6: len(pe.net.mdtables.MethodDef.rows),
              10: len(pe.net.mdtables.MemberRef.rows)}
    for field, target in entries:
        table = (target & 0x3FFFFFFF) >> 24
        if not (field >> 24 == 4 and 0 < (field & 0xFFFFFF) <= counts[4] and
                table in (6, 10) and 0 < (target & 0xFFFFFF) <= counts[table]):
            print("decoded proxy contains an invalid metadata token", file=sys.stderr)
            return 2
    pairs = dict(entries)
    if len(pairs) != len(entries):
        print("decoded proxy contains duplicate field tokens", file=sys.stderr)
        return 2
    with Path(args.dll).open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != source_sha256:
            print("source DLL changed while decoding", file=sys.stderr)
            return 2
    print(f"proxy map entries: {len(pairs)}", file=sys.stderr)

    # field name -> token, so a name can be looked up directly
    field_token = {}
    for i, f in enumerate(pe.net.mdtables.Field.rows, 1):
        field_token.setdefault(str(f.Name), 0x04000000 | i)

    types_by_method: dict[int, str] = {}
    for ty in pe.net.mdtables.TypeDef.rows:
        owner = f"{ty.TypeNamespace}.{ty.TypeName}".lstrip(".")
        for x in ty.MethodList:
            types_by_method[x.row_index] = owner

    def resolve(token: int) -> dict:
        tok = token & 0x3FFFFFFF
        table = tok >> 24
        idx = tok & 0xFFFFFF
        if table == 6:
            row = pe.net.mdtables.MethodDef.rows[idx - 1]
            return {"method": str(row.Name), "type": types_by_method.get(idx, "?")}
        if table == 10:
            row = pe.net.mdtables.MemberRef.rows[idx - 1]
            cls = row.Class.row
            return {
                "method": str(row.Name),
                "type": f"{getattr(cls, 'TypeNamespace', '')}.{getattr(cls, 'TypeName', '')}".lstrip("."),
            }
        return {"method": f"<unknown table {table}>", "type": "?"}

    # field token -> declaring type/member name, so the map can be keyed by the
    # fully-qualified slot name ("DeclaringType.FieldName") rather than by token.
    slot_owner: dict[int, tuple[str, str]] = {}
    for ty in pe.net.mdtables.TypeDef.rows:
        owner = f"{ty.TypeNamespace}.{ty.TypeName}".lstrip(".")
        for fh in ty.FieldList:
            # FieldList yields MDTableIndex handles; the row itself is looked up by index
            # (same access pattern the project's existing decoder uses).
            row = pe.net.mdtables.Field.rows[fh.row_index - 1]
            slot_owner[0x04000000 | fh.row_index] = (owner, str(row.Name))

    if args.all:
        rows = []
        for k, v in sorted(pairs.items()):
            owner, fname = slot_owner.get(k, ("?", None))
            rows.append({"slot": f"{owner}.{fname}" if fname else None,
                         "field": fname, "owner": owner,
                         "field_token": hex(k), **resolve(v)})
    else:
        rows = []
        for name in args.fields:
            key = field_token.get(name)
            if key is None:
                rows.append({"field": name, "error": "field not found in metadata"})
                continue
            val = pairs.get(key)
            if val is None:
                rows.append({"field": name, "field_token": hex(key), "error": "no proxy entry"})
                continue
            rows.append({"field": name, "field_token": hex(key), **resolve(val)})

    for r in rows:
        if "error" in r:
            print(f"{r['field']}: {r['error']}")
        else:
            print(f"{r.get('field') or r['field_token']}: {r['type']}::{r['method']}")

    if args.dump:
        with Path(args.dump).open("x", encoding="utf-8") as stream:
            json.dump(rows, stream, ensure_ascii=False, indent=1)
        output_sha256 = hashlib.sha256(Path(args.dump).read_bytes()).hexdigest()
        metadata = {
            "sourceDll": str(Path(args.dll).resolve()), "sourceSha256": source_sha256,
            "resource": resource_name, "decodedSha256": hashlib.sha256(decoded).hexdigest(),
            "totalPairs": len(pairs), "outputRows": len(rows),
            "outputSha256": output_sha256, "completeMap": bool(args.all and len(rows) == len(pairs)),
            "tokenValidationPassed": True, "liveAdapterCompatible": False,
        }
        with output_meta.open("x", encoding="utf-8") as stream:
            json.dump(metadata, stream, indent=2)
        print(f"wrote {args.dump}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
