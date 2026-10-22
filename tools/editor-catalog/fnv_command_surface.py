#!/usr/bin/env python3
"""Offline, read-only enumeration of the editor command dispatchers inside
``YuanShen.exe`` (the game engine the Miliastra editor drives).

Why this exists
---------------
The editor's command *names* never appear in the engine binary.  A name is
reduced to its **FNV-1a 32-bit** hash over the string's UTF-16 code units, and
dispatched through a ``cmp ecx, imm32`` binary-search chain.  Recovering the
command surface therefore means (a) decoding the dispatcher functions exactly,
(b) pulling every compared immediate out of them, and (c) turning each immediate
back into a name by hashing a candidate dictionary.

This module is deliberately dependency-light and never touches a running
process: it reads bytes from a file, nothing else.  Disassembly needs
``capstone`` (the project keeps it under ``.runtime/native-analysis/deps``); the
immediate extraction has a pure-byte fallback so the tool still runs without it.

Scope / honesty
---------------
The result is "the compared-immediate key set of these dispatcher functions",
NOT "every command the engine can ever handle".  A dispatcher that (i) uses a
different hash, (ii) is table-driven, or (iii) builds its keys at run time is
invisible here.  See docs/research/reverse-eng-20261011/COMMAND-SURFACE-FNV.md.

CLI
---
    python fnv_command_surface.py            # re-derive and print the surface
    python fnv_command_surface.py --json OUT # also write the machine-readable dump
    python fnv_command_surface.py --collision-check   # the naive-vs-filtered study

``OUT`` must live inside the project; a path outside is refused.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import sqlite3
import struct
import sys
from collections import defaultdict
from pathlib import Path

BASIS = 2166136261
PRIME = 16777619
MASK32 = 0xFFFFFFFF

# The two dispatchers, addressed by RVA in the 2026-09 build of YuanShen.exe.
# (RVA, end-exclusive RVA, owning service family).  Verified independently: the
# function is fully decoded to its .pdata end and contains no indirect jump, so
# its compared immediates are its complete key set.
DISPATCHERS = {
    "main": (0xCBA3130, 0xCBA43D7, "beyondEditObjService / beyondInstructionGraphService"),
    "export": (0xF03EB40, 0xF03F396, "beyondExportService"),
}

DEFAULT_EXE = Path(r"C:\Games\Genshin Impact Game\YuanShen.exe")

# Names confirmed by an independent source (the editor's own command
# registration literals) as well as by the hash.  Used as the positive control:
# the method must reproduce these, or it is broken.
POSITIVE_CONTROL = {
    "main": ["DeleteComponentForEditObj", "AddInstructionGraphForEditObj"],
    "export": ["DoImport", "DoExport", "ImportDebugLog"],
}

# Constants that no local corpus names, but whose FNV-1a preimage is an exact
# match for a name that is family-symmetric with a *named* sibling in the same
# dispatcher.  These are reported as INFERRED, never silently merged with the
# corpus-derived names: a hash match proves the string maps to the constant, it
# does not by itself prove the string is the one the engine was compiled with.
INFERRED = {
    0x2C4EDA76: ("DeleteInstructionGraphForEditObj",
                 "preimage; absent from every named local corpus; symmetric with "
                 "AddInstructionGraphForEditObj @0xcba34fb"),
    0x5A1A25F3: ("DeleteInstructionGraphForPrefab",
                 "preimage; absent from every named local corpus; symmetric with "
                 "AddInstructionGraphForPrefab @0xcba341c"),
    0x08AEE119: ("DoImportClientScript",
                 "preimage; date-confirmed sibling DoExportClientScript "
                 "(@0xf03ecf4/0xf03eea1) sits in the paired subtree node"),
}

# A dated machine-evidence file (2026-09-26) that already ties
# `cmp ecx, 0x26e623fe` @0xf03ecf4/0xf03eea1 to the name DoExportClientScript.
# Kept as an explicit source so the tool names it without a hand-written entry.
EVIDENCE_FILES = [".runtime/verification/docs-71-20260926/native-command-rescan-all38.json"]


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def fnv1a_utf16(name: str) -> int:
    """FNV-1a-32 over the string's 16-bit code units (the engine's loop).

    For ASCII names this is bit-for-bit the same as byte-wise FNV-1a.
    """
    h = BASIS
    for u in name.encode("utf-16-le")[::2]:  # low byte of each code unit
        h ^= u
        h = (h * PRIME) & MASK32
    return h


def fnv1a_data(data: bytes) -> int:
    """Byte-wise FNV-1a-32 (used by tests and for ASCII round-trips)."""
    h = BASIS
    for b in data:
        h ^= b
        h = (h * PRIME) & MASK32
    return h


# --------------------------------------------------------------------------- #
# PE image
# --------------------------------------------------------------------------- #
class PeImage:
    """Minimal read-only PE map: RVA <-> file offset, sections, .pdata funcs."""

    def __init__(self, path: Path = DEFAULT_EXE):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        d = self.data
        pe = struct.unpack_from("<I", d, 60)[0]
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        osz = struct.unpack_from("<H", d, pe + 20)[0]
        self.opt = pe + 24
        secs = []
        for i in range(nsec):
            off = self.opt + osz + i * 40
            nm = d[off:off + 8].rstrip(b"\0").decode("latin1")
            vs, va, rs, ra = struct.unpack_from("<IIII", d, off + 8)
            secs.append((nm, va, vs, rs, ra))
        self.secs = secs
        self.er, self.esz = struct.unpack_from("<II", d, self.opt + 136)
        # image end is derived from the section table, never a hand-written bound
        self.maxrva = max(va + max(vs, rs) for _, va, vs, rs, _ in secs)

    def offof(self, rva: int):
        for _nm, va, vs, rs, ra in self.secs:
            if va <= rva < va + max(vs, rs) and rva - va < rs:
                return ra + rva - va
        return None

    def rva_of(self, off: int):
        for nm, va, vs, rs, ra in self.secs:
            if ra <= off < ra + rs:
                return va + off - ra, nm
        return None, None

    def funcs(self):
        """RUNTIME_FUNCTION list -> sorted [(begin_rva, end_rva)]."""
        eo = self.offof(self.er)
        out = []
        for i in range(self.esz // 12):
            b, e, _u = struct.unpack_from("<III", self.data, eo + i * 12)
            if b and e > b and e <= self.maxrva:
                out.append((b, e))
        out.sort()
        return out

    def blob(self, begin: int, end: int) -> bytes:
        off = self.offof(begin)
        if off is None:
            raise ValueError(f"RVA {begin:#x} is not mapped")
        return self.data[off:off + (end - begin)]


# --------------------------------------------------------------------------- #
# disassembly / immediate extraction
# --------------------------------------------------------------------------- #
def capstone_md():
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64  # type: ignore
        return Cs(CS_ARCH_X86, CS_MODE_64), None
    except ImportError:
        here = Path(__file__).resolve()
        for parent in here.parents:
            cand = parent / ".runtime" / "native-analysis" / "deps"
            if cand.is_dir():
                sys.path.insert(0, str(cand))
                try:
                    from capstone import Cs, CS_ARCH_X86, CS_MODE_64  # type: ignore
                    return Cs(CS_ARCH_X86, CS_MODE_64), None
                except ImportError:
                    break
        return None, "capstone not importable"


def cmp_imm32_sites(blob: bytes, begin: int):
    """Every ``cmp r32, imm32`` immediate inside ``blob``.

    Encoded as opcode 0x81 with a modrm whose reg field selects a 32-bit
    register and whose mod is 11 (register operand).  Returns {imm: [rva, ...]}.

    This is the *filter* that separates a real compared constant from a value
    that merely happens to appear in the image: the value must sit at the
    immediate slot of a genuine instruction.
    """
    out = defaultdict(list)
    i = 0
    n = len(blob)
    while i + 5 < n:
        if blob[i] == 0x81 and (blob[i + 1] & 0xF8) == 0xF8:
            imm = struct.unpack_from("<I", blob, i + 2)[0]
            out[imm].append(begin + i)
            i += 6
        else:
            i += 1
    return dict(out)


def decode_function(image: PeImage, begin: int, end: int):
    """Full decode + structural checks.  Returns a dict."""
    md, err = capstone_md()
    blob = image.blob(begin, end)
    res = {
        "begin": begin, "end": end, "size": end - begin,
        "capstone": err is None, "complete": None, "indirect_jumps": None,
        "fnv_basis_sites": [], "fnv_prime_sites": [], "constants": {},
    }
    if md is None:
        # no disassembler: keep the same policy the capstone path applies
        res["constants"] = {v: s for v, s in cmp_imm32_sites(blob, begin).items()
                            if 0x10000 <= v <= MASK32}
        return res
    ins = list(md.disasm(blob, begin))
    covered = (ins[-1].address + ins[-1].size - begin) if ins else 0
    res["complete"] = covered == (end - begin)
    res["insn_count"] = len(ins)
    ind = [x.address for x in ins
           if x.mnemonic == "jmp" and ("qword" in x.op_str or x.op_str in (
               "rax", "rcx", "rdx", "rbx", "rsi", "rdi", "r8", "r9", "r10",
               "r11", "r12", "r13", "r14", "r15"))]
    res["indirect_jumps"] = ind
    res["fnv_basis_sites"] = [x.address for x in ins
                              if x.mnemonic == "mov" and x.op_str.endswith(", 0x811c9dc5")]
    res["fnv_prime_sites"] = [x.address for x in ins
                              if x.mnemonic == "imul" and "0x1000193" in x.op_str]
    consts = defaultdict(list)
    for x in ins:
        if x.mnemonic == "cmp" and "," in x.op_str:
            dst, src = x.op_str.split(",", 1)
            try:
                v = int(src.strip(), 0)
            except ValueError:
                continue
            if 0x10000 <= v <= MASK32:
                consts[v].append((x.address, dst.strip()))
    res["constants"] = {v: [a for a, _ in s] for v, s in consts.items()}
    return res


def find_hash_loop_functions(image: PeImage, funcs):
    """Functions containing an ``imul reg, reg, 0x1000193`` site."""
    prime = struct.pack("<I", PRIME)
    begins = [f[0] for f in funcs]
    by_begin = {f[0]: f for f in funcs}
    out = []
    pos = 0
    d = image.data
    while True:
        p = d.find(prime, pos)
        if p < 0:
            break
        if p - 2 >= 0 and d[p - 2] == 0x69:
            rva = image.rva_of(p - 2)[0]
            if rva is not None:
                j = bisect.bisect_right(begins, rva) - 1
                if 0 <= j < len(begins):
                    f = funcs[j]
                    if rva < f[1] and f not in out:
                        out.append(f)
        pos = p + 1
    return out


# --------------------------------------------------------------------------- #
# the candidate dictionary
# --------------------------------------------------------------------------- #
_LIT = re.compile(r'"((?:[^"\\\n]|\\.){1,200})"')
_TOK = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,80}")

# A name attested only by prose (docs_md) is weaker evidence than a name that
# appears in a decompiled literal, a registration table or a dated evidence
# file.  Such a match is reported as INFERRED, never as a dictionary hit.
WEAK_SOURCES = frozenset({"docs_md"})


def _docs_tokens(root: Path):
    """Identifier-like tokens from the project's own docs (pre-existing prose
    that names commands).  Bounded to markdown so it stays fast; the point is
    that names like DeleteInstructionGraphForEditObj already live there."""
    toks = set()
    docs = root / "docs"
    if not docs.is_dir():
        return toks
    for p in docs.rglob("*.md"):
        try:
            if p.stat().st_size > 2_000_000:
                continue
            toks.update(_TOK.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return toks


def _evidence_names(root: Path):
    """Names found in dated machine-evidence files (name -> cmp-site records)."""
    names = set()
    for rel in EVIDENCE_FILES:
        p = root / rel
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for hit in doc.get("raw_hits", []):
            names.update(hit.get("names", []))
        for cmd in doc.get("commands", []):
            if cmd.get("command"):
                names.add(cmd["command"])
    return names


def load_dictionary(root: Path):
    """name -> tuple(sorted sources).  Every source is a local, read-only file.

    Sources: the decompiled editor corpus, the editor string table, both
    research sqlite DBs, and the prior native hash index.  Missing sources are
    skipped (their absence is recorded, not silently assumed).
    """
    names = defaultdict(set)
    used = {}

    def add(src, vals):
        vals = {v for v in vals if isinstance(v, str)}
        used[src] = len(vals)
        for v in vals:
            names[v].add(src)

    corpus = root / ".runtime/editor-catalog/resolved"
    lits = set()
    if corpus.is_dir():
        for p in corpus.glob("*.cs"):
            txt = p.read_text(encoding="utf-8", errors="replace")
            lits.update(m.group(1) for m in _LIT.finditer(txt))
    add("corpus_cs", lits)

    stp = root / ".runtime/editor-catalog/string-table.json"
    if stp.exists():
        st = json.loads(stp.read_text(encoding="utf-8"))
        add("string_table", [v for v in st.values() if isinstance(v, str)])

    for src, (db, table, col) in {
        "op_frontend": ("docs/research/beyondeditor-frontend/db/frontend.db",
                        "operation", "op_name"),
        "route_backend": ("docs/research/beyondeditor-backend/db/backend.db",
                          "command_route", "command"),
        "candidate_name": ("docs/research/beyondeditor-backend/db/backend.db",
                           "candidate_name", "name"),
    }.items():
        p = root / db
        if not p.exists():
            continue
        try:
            c = sqlite3.connect(str(p))
            vals = {r[0] for r in c.execute(f"select distinct {col} from {table}")}
        except sqlite3.Error:
            continue
        add(src, vals)

    ni = root / "docs/research/beyondeditor-backend/raw/native-hash-index.json"
    if ni.exists():
        d = json.loads(ni.read_text(encoding="utf-8"))
        add("native_index", [n for v in d.values() for n in v])

    add("docs_md", _docs_tokens(root))
    add("evidence", _evidence_names(root))

    return {n: tuple(sorted(s)) for n, s in names.items()}, used


def name_constants(constants, dictionary):
    """{imm: [(name, sources), ...]} -- a list so a hash collision stays visible."""
    h2n = defaultdict(list)
    for n, ss in dictionary.items():
        h2n[fnv1a_utf16(n)].append((n, ss))
    return {imm: h2n.get(imm, []) for imm in constants}


# --------------------------------------------------------------------------- #
# whole-image surface scan (the negative's supporting half)
# --------------------------------------------------------------------------- #
def _windows(data, targets):
    """Yield (offset, value) for every 4-byte-aligned window across all 4 phases
    whose value is one of ``targets``.  numpy fast path, slow fallback."""
    try:
        import numpy as np
    except ImportError:
        tset = set(targets)
        for p in range(max(0, len(data) - 3)):
            v = struct.unpack_from("<I", data, p)[0]
            if v in tset:
                yield p, v
        return
    t = np.fromiter(targets, dtype="<u4", count=len(targets))
    for shift in range(4):
        n = (len(data) - shift) // 4
        sub = np.frombuffer(data, dtype="<u4", count=n, offset=shift)
        for i in np.nonzero(np.isin(sub, t))[0]:
            yield shift + int(i) * 4, int(sub[i])


def scan_image_sites(image: PeImage, candidate_hashes):
    """{imm: [off]} for candidate hashes that occur as the immediate of a real
    ``cmp r32, imm32`` ANYWHERE in the image.  This is the filter that keeps a
    chance 4-byte coincidence from being read as a dispatch constant."""
    d = image.data
    hits = defaultdict(list)
    for off, imm in _windows(d, candidate_hashes):
        if off - 2 >= 0 and d[off - 2] == 0x81 and (d[off - 1] & 0xF8) == 0xF8:
            hits[imm].append(off - 2)
    return dict(hits)


def naive_presence(image: PeImage, candidate_hashes):
    """The naive method: which candidate hashes appear ANYWHERE as a raw 4-byte
    value.  Kept only to demonstrate how noisy it is (see collision_check)."""
    return {imm for _off, imm in _windows(image.data, candidate_hashes)}


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def classify_constant(imm, candidates):
    """Decide a constant's identity from its candidate names.

    ``candidates`` is ``[(name, sources)]``.  Returns ``(name, source, note)``
    where ``source`` is one of ``dictionary`` / ``inferred`` / ``unnamed``.
    A name backed only by prose is demoted to ``inferred``; a name with no
    attestation falls back to the hand-curated INFERRED table.
    """
    strong = [c for c in candidates if set(c[1]) - WEAK_SOURCES]
    if len(strong) == 1:
        return strong[0][0], "dictionary", None
    if not strong and len(candidates) == 1:
        nm = candidates[0][0]
        note = INFERRED.get(imm, (nm, "attested only by project prose"))[1]
        return nm, "inferred", note
    if imm in INFERRED:
        return INFERRED[imm][0], "inferred", INFERRED[imm][1]
    if not candidates:
        return None, "unnamed", None
    return "AMBIGUOUS", "unnamed", None


def verb_census(names):
    """Leading CamelCase verb -> count.  Longest verb wins for prefixes that are
    themselves verbs (plain first-word split is enough for these command names)."""
    out = defaultdict(int)
    for n in names:
        m = re.match(r"[A-Z][a-z0-9]+", n)
        out[m.group(0) if m else n] += 1
    return dict(sorted(out.items()))


def surface(root: Path, exe: Path):
    image = PeImage(exe)
    dictionary, sources = load_dictionary(root)
    report = {"exe": str(exe), "exe_size": len(image.data),
              "dictionary": {"size": len(dictionary), "sources": sources},
              "dispatchers": {}}
    all_named = []
    for label, (b, e, service) in DISPATCHERS.items():
        dec = decode_function(image, b, e)
        named = name_constants(dec["constants"], dictionary)
        entry = {
            "service": service,
            "begin": hex(b), "end": hex(e), "size": e - b,
            "complete_decode": dec.get("complete"),
            "indirect_jumps": dec.get("indirect_jumps"),
            "fnv_basis_sites": [hex(x) for x in dec.get("fnv_basis_sites", [])],
            "fnv_prime_sites": [hex(x) for x in dec.get("fnv_prime_sites", [])],
            "constants": [],
        }
        for imm in sorted(dec["constants"]):
            nm, src, note = classify_constant(imm, named[imm])
            sites = [hex(x) for x in dec["constants"][imm]]
            if nm and src != "unnamed":
                all_named.append(nm)
            rec = {"imm": f"0x{imm:08x}", "name": nm, "name_source": src,
                   "sources": sorted({s for _n, ss in named[imm] for s in ss}),
                   "sites": sites}
            if note:
                rec["note"] = note
            if src == "unnamed":
                rec["candidates"] = [c[0] for c in named[imm]]
            entry["constants"].append(rec)
        # positive control
        ctrl = POSITIVE_CONTROL[label]
        present = {c["name"] for c in entry["constants"]}
        entry["positive_control"] = {n: (n in present) for n in ctrl}
        entry["positive_control_ok"] = all(entry["positive_control"].values())
        report["dispatchers"][label] = entry
    report["verb_census"] = verb_census(all_named)
    report["total_named"] = len(all_named)
    return report


def collision_check(root: Path, exe: Path):
    """Reproduce the naive-vs-filtered study for the add/create/terrain verbs."""
    import random
    image = PeImage(exe)
    verbs = ["Add", "Create", "Insert", "Attach", "New", "Make", "Instantiate", "Apply",
             "Register", "Build", "Generate", "Mount", "Equip", "Set", "Push", "Append"]
    tmpl = ["Component", "Components", "Template", "Asset", "Prefab", "Entity", "EditObj",
            "PrefabInstance", "Instance", "Model", "Object", "Resource", "Archetype",
            "Blueprint", "Node", "Terrain", "Tile", "Cell", "Map", "TileMap", "Region",
            "Area", "Height", "Layer", "Material", "Mesh", "Decor"]
    suf = ["", "ForEditObj", "ForPrefab", "ForEntity", "ForInstance", "ForComponent",
           "ForLevel", "InEditObj", "InPrefab", "ToEditObj", "ByIndex"]
    terr = ["SetTerrain", "ModifyTerrain", "EditTerrain", "PaintTerrain", "TerrainWrite",
            "WriteTerrain", "SetTerrainCell", "ModifyTerrainCell", "CreateTerrain",
            "AddTerrain", "SetCell", "AddCell", "CreateCell", "ModifyCell", "SetTile",
            "AddTile", "PaintCell", "BrushTerrain", "TerrainBrush", "HeightmapModify"]
    cands = set(terr)
    for v in verbs:
        for n in tmpl:
            for s in suf:
                cands.add(v + n + s)
    hashes = {fnv1a_utf16(c) for c in cands}
    d = image.data

    naive = naive_presence(image, hashes)
    rng = random.Random(1234)
    rnd = {rng.randrange(1, 2**32) for _ in range(len(hashes))}
    rnd_naive = naive_presence(image, rnd)
    filtered = scan_image_sites(image, hashes)
    control = scan_image_sites(image, {fnv1a_utf16("DeleteComponentForEditObj"),
                                       fnv1a_utf16("AddInstructionGraphForEditObj")})
    return {
        "candidates": len(cands),
        "expected_clashes": len(hashes) * len(d) / 2**32,
        "naive_names_hit": len(naive),
        "random_control_names_hit": len(rnd_naive),
        "filtered_names_hit": len(filtered),
        "positive_control_sites": {f"0x{k:08x}": [hex(o - 2) for o in v]
                                   for k, v in control.items()},
    }


def _inside_project(path: Path, root: Path) -> bool:
    try:
        p = path.resolve()
        return p == root.resolve() or root.resolve() in p.parents
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--collision-check", action="store_true")
    ap.add_argument("--root", type=Path,
                    default=Path(__file__).resolve().parents[2])
    args = ap.parse_args(argv)

    if not args.exe.exists():
        print(f"error: engine image not found: {args.exe}", file=sys.stderr)
        return 2

    if args.collision_check:
        print(json.dumps(collision_check(args.root, args.exe), indent=1))
        return 0

    rep = surface(args.root, args.exe)
    print(f"exe: {rep['exe']}  ({rep['exe_size']} bytes)")
    print(f"dictionary: {rep['dictionary']['size']} names from "
          f"{rep['dictionary']['sources']}")
    for label, e in rep["dispatchers"].items():
        print(f"\n== {label}  {e['begin']}-{e['end']}  ({e['service']})")
        print(f"   complete_decode={e['complete_decode']}  "
              f"indirect_jumps={len(e['indirect_jumps'] or [])}  "
              f"constants={len(e['constants'])}  "
              f"positive_control_ok={e['positive_control_ok']}")
        for c in e["constants"]:
            nm = c["name"] or ("<UNNAMED>" if not c.get("candidates") else
                               "<AMBIGUOUS>")
            tag = {"dictionary": "", "inferred": " (inferred)", "unnamed": ""}[
                c.get("name_source", "dictionary")]
            print(f"     {c['imm']}  {nm + tag:44s} sites={','.join(c['sites'])}")
    print(f"\nverb census: {rep['verb_census']}")
    print(f"total named: {rep['total_named']}")

    if args.json:
        if not _inside_project(args.json, args.root):
            print("error: --json must be written inside the project", file=sys.stderr)
            return 2
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
