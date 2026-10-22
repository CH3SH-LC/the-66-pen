# -*- coding: utf-8 -*-
"""Enumerate EVERY FNV-1a command-hash dispatcher inside YuanShen.exe.

What this is
------------
IL2CPP (Mono/Unity) compiles a C# ``switch (someString)`` into a *hash dispatch*:

    1. compute FNV-1a-32 of the UTF-16 string        (seed 0x811c9dc5, prime 0x1000193)
    2. ``cmp ACC, <precomputed hash>`` + ``ja`` / ``je`` -> a binary-search tree
    3. leaf = the case body

Every ``switch`` over string literals in the game therefore leaves behind a
"dispatcher": an FNV-1a loop whose accumulator feeds a tree of
``cmp ACC, imm32`` sites.  The ``imm32`` values ARE ``fnv1a(case label)``.
This module finds those dispatchers *by shape* -- never from a name list, never
from a hardcoded address -- and dumps every key.

Shape, and how false positives are avoided
------------------------------------------
A candidate function must contain, in the same RUNTIME_FUNCTION body:

  (A) the FNV seed:  ``mov r32, 0x811c9dc5``            (mov eax..edi, imm32)
  (B) the FNV prime: ``imul ACC, r/m32, 0x1000193``     (op 69 /r, imm32)
      The destination register of (B) is the ACCUMULATOR ACC.
  (C) a *reachable* tree of ``cmp ACC, imm32`` sites.  The ROOT is the first
      ``cmp ACC, imm32`` after the last prime-imul.  The tree is walked by the
      standard binary-search successors of each cmp node:

          successor#1 = the target of the jcc that immediately follows the cmp
          successor#2 = the instruction *past* that jcc  (fall-through)

      A successor is a tree node iff it is itself ``cmp ACC, imm32``; otherwise
      the edge is a leaf (a case body).

Why this is not tripped by incidental ``cmp ecx, imm``:
  * the compared register must be exactly the register that the FNV multiply
    writes -- an unrelated ``cmp ecx`` elsewhere in the function is not on the
    accumulator's def-use path after the loop;
  * the walk is *reachability-bounded*: only cmp nodes reachable from the
    loop-exit root through binary-search successors are collected, so a
    coincidental ``cmp ACC, imm`` sitting in a case body is never reached;
  * the constants must be >= 0x10000 (a hash, not a small enum/bounds value).

Known limitation (stated, not hidden): a function that legitimately owns BOTH
an FNV loop AND an unrelated string switch elsewhere can anchor on the wrong
list.  We do not claim otherwise -- the artifact records the root RVA so any
entry can be re-checked by hand.

Semantics of the hash
---------------------
The loop reads 16-bit words (``movzx esi, word ptr [...]``), i.e. it hashes the
UTF-16 code units of an IL2CPP System.String.  For the ASCII identifiers that
C# case labels are, this equals the classic byte-wise FNV-1a, so
``fnv1a("DeleteComponentForEditObj")`` computed here matches the constant in the
binary.  ``fnv1a`` below iterates code points, which is the exact loop semantics
for BMP text.

Read-only.  No process is touched.  Bytes are read from the image only.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------- constants
FNV_OFFSET_BASIS = 0x811C9DC5
FNV_PRIME = 0x01000193
KIND32 = 0xFFFFFFFF

# opcode 69 /r id -> imul r32, r/m32, imm32  (imm32 little-endian, == FNV_PRIME)
_PRIME_BYTES = struct.pack("<I", FNV_PRIME)  # 93 01 00 01
_SEED_BYTES = struct.pack("<I", FNV_OFFSET_BASIS)  # c5 9d 1c 81

_JCC = {
    "je", "jne", "ja", "jae", "jb", "jbe", "jg", "jge", "jl", "jle",
    "js", "jns", "jo", "jno", "jp", "jnp",
}


def fnv1a(s: str) -> int:
    """FNV-1a-32 over a string's code points (the IL2CPP switch semantics)."""
    h = FNV_OFFSET_BASIS
    for ch in s:
        h = ((h ^ ord(ch)) * FNV_PRIME) & KIND32
    return h


def fnv1a_bytes(b: bytes) -> int:
    """Classic byte-wise FNV-1a-32 (equals ``fnv1a`` for ASCII text)."""
    h = FNV_OFFSET_BASIS
    for byte in b:
        h = ((h ^ byte) * FNV_PRIME) & KIND32
    return h


def _maybe_capstone():
    """Capstone is vendored under .runtime/native-analysis/deps."""
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_64  # noqa: F401
        return Cs, CS_ARCH_X86, CS_MODE_64
    except ModuleNotFoundError:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        dep = parent / ".runtime" / "native-analysis" / "deps"
        if dep.is_dir():
            sys.path.insert(0, str(dep))
            break
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
    return Cs, CS_ARCH_X86, CS_MODE_64


# ---------------------------------------------------------------- PE layout
class PE:
    """Minimal read-only PE32+ view: sections, RVA<->file map, .pdata funcs."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        d = self.data
        pe = struct.unpack_from("<I", d, 60)[0]
        self.pe = pe
        nsec = struct.unpack_from("<H", d, pe + 6)[0]
        osz = struct.unpack_from("<H", d, pe + 20)[0]
        self.opt = pe + 24
        secs = []
        for i in range(nsec):
            off = self.opt + osz + i * 40
            name = d[off:off + 8].rstrip(b"\0").decode("latin1")
            vs, va, rs, ra = struct.unpack_from("<IIII", d, off + 8)
            secs.append((name, va, vs, rs, ra))
        self.secs = secs
        # data directory index 3 = exception table (.pdata RUNTIME_FUNCTION list)
        self.exc_rva, self.exc_size = struct.unpack_from("<II", d, self.opt + 136)
        self.max_rva = max(va + max(vs, rs) for _, va, vs, rs, _ in secs)

    def offof(self, rva):
        for _nm, va, vs, rs, ra in self.secs:
            if va <= rva < va + max(vs, rs) and rva - va < rs:
                return ra + rva - va
        return None

    def rva_of(self, off):
        for nm, va, vs, rs, ra in self.secs:
            if ra <= off < ra + rs:
                return va + off - ra, nm
        return None, None

    def sections_walked(self):
        return [nm for nm, _va, _vs, rs, _ra in self.secs if rs]

    def funcs(self):
        """RUNTIME_FUNCTION list -> sorted [(begin_rva, end_rva)]."""
        eo = self.offof(self.exc_rva)
        if eo is None:
            return []
        out = []
        for i in range(self.exc_size // 12):
            b, e, _u = struct.unpack_from("<III", self.data, eo + i * 12)
            if b and e > b and e <= self.max_rva:
                out.append((b, e))
        out.sort()
        return out


# ---------------------------------------------------------------- shape scan
def _find_seed_and_prime(pe):
    """Locate every FNV seed mov and FNV prime imul site by byte shape."""
    d = pe.data
    seeds, primes = set(), set()
    pos = 0
    while True:
        p = d.find(_SEED_BYTES, pos)
        if p < 0:
            break
        # mov r32, imm32 is B8+rd; the imm32 is the trailing 4 bytes.
        if p >= 1 and 0xB8 <= d[p - 1] <= 0xBF:
            rva, _ = pe.rva_of(p - 1)
            if rva is not None:
                seeds.add(rva)
        pos = p + 1
    pos = 0
    while True:
        p = d.find(_PRIME_BYTES, pos)
        if p < 0:
            break
        # imul r32, r/m32, imm32 is opcode 69; imm starts at +2.
        if p >= 2 and d[p - 2] == 0x69:
            rva, _ = pe.rva_of(p - 2)
            if rva is not None:
                primes.add(rva)
        pos = p + 1
    return seeds, primes


def _accumulator_regs(pe, primes, md, owner):
    """For each function, the register(s) the FNV multiply writes."""
    acc = {}
    for rva in primes:
        off = pe.offof(rva)
        for insn in md.disasm(pe.data[off:off + 8], rva):
            if insn.mnemonic != "imul":
                continue
            parts = [t.strip() for t in insn.op_str.split(",")]
            # imul ecx, esi, 0x1000193
            if len(parts) == 3 and parts[1].startswith("e") and "0x1000193" in parts[2]:
                f = owner(rva)
                if f:
                    acc.setdefault(f, set()).add(parts[0])
            break
    return acc


def first_switch_root(insns, regs):
    """Root = first ``cmp ACC, imm32`` (imm>=0x10000) after the last prime imul."""
    imuls = [i.address for i in insns if i.mnemonic == "imul" and "0x1000193" in i.op_str]
    if not imuls:
        return None
    cut = max(imuls)
    for i in insns:
        if i.address <= cut:
            continue
        v = _cmp_acc_imm(i, regs)
        if v is not None:
            return i.address
    return None


def _cmp_acc_imm(insn, regs):
    """If ``insn`` is ``cmp ACC, imm32`` (ACC in regs, imm>=0x10000) return imm."""
    if insn.mnemonic != "cmp" or "," not in insn.op_str:
        return None
    dst, src = insn.op_str.split(",", 1)
    if dst.strip() not in regs:
        return None
    try:
        v = int(src.strip(), 0)
    except ValueError:
        return None
    if 0x10000 <= v <= KIND32:
        return v
    return None


def node_successors(insn, by_addr):
    """Out-edges of one ``cmp ACC, imm`` tree node.

    The compiler emits BOTH a 2-way form  ``cmp; ja R;  <next cmp>``  and a
    3-way form  ``cmp; ja R; je E;  <next cmp>``  (conditional jumps leave the
    flags untouched, so the ``je`` re-tests the same ``cmp``).  We therefore
    consume a *run* of consecutive conditional jumps after the cmp, then add the
    fall-through past that run.  An unconditional ``jmp`` terminates the run with
    no fall-through.
    """
    succ = []
    s = insn.address + insn.size
    for _ in range(4):
        nxt = by_addr.get(s)
        if nxt is None:
            break
        if nxt.mnemonic == "jmp":
            try:
                succ.append(int(nxt.op_str, 16))
            except ValueError:
                pass
            return succ
        if nxt.mnemonic not in _JCC:
            break
        try:
            succ.append(int(nxt.op_str, 16))
        except ValueError:
            pass
        s = nxt.address + nxt.size
    succ.append(s)
    return succ


def walk_key_tree(by_addr, regs, root):
    """BFS the binary-search tree from ``root``; return [(addr, imm)], leaves."""
    seen = set()
    stack = [root]
    nodes = []
    leaves = 0
    while stack:
        a = stack.pop()
        if a in seen:
            continue
        seen.add(a)
        insn = by_addr.get(a)
        if insn is None:
            continue
        v = _cmp_acc_imm(insn, regs)
        if v is None:
            continue
        nodes.append((a, v))
        for s in node_successors(insn, by_addr):
            sx = by_addr.get(s)
            if sx is not None and _cmp_acc_imm(sx, regs) is not None:
                stack.append(s)
            else:
                leaves += 1
    return nodes, leaves


def scan(path, min_keys=3, verbose=False):
    """Return the full dispatcher inventory for an executable image."""
    Cs, CS_ARCH_X86, CS_MODE_64 = _maybe_capstone()
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    pe = PE(path)
    funcs = pe.funcs()
    begins = [f[0] for f in funcs]

    def owner(r):
        i = bisect.bisect_right(begins, r) - 1
        if 0 <= i < len(funcs) and r < funcs[i][1]:
            return funcs[i]
        return None

    seeds, primes = _find_seed_and_prime(pe)
    acc = _accumulator_regs(pe, primes, md, owner)

    out = []
    for f, regs in sorted(acc.items()):
        off = pe.offof(f[0])
        if off is None:
            continue
        insns = list(md.disasm(pe.data[off:off + (f[1] - f[0])], f[0]))
        by_addr = {i.address: i for i in insns}
        root = first_switch_root(insns, regs)
        if root is None:
            continue
        nodes, leaves = walk_key_tree(by_addr, regs, root)
        keys = sorted({v for _a, v in nodes})
        if len(keys) < min_keys:
            continue
        has_seed = any(f[0] <= r < f[1] for r in seeds)
        out.append({
            "begin_rva": f[0],
            "end_rva": f[1],
            "file_offset_begin": pe.offof(f[0]),
            "file_offset_end": pe.offof(f[1] - 1),
            "accumulator": sorted(regs),
            "root_rva": root,
            "has_seed": has_seed,
            "tree_nodes": len(nodes),
            "leaves": leaves,
            "key_count": len(keys),
            "keys": keys,
        })
    out.sort(key=lambda d: -d["key_count"])
    meta = {
        "exe": str(pe.path),
        "sha256": hashlib.sha256(pe.data).hexdigest(),
        "image_size": len(pe.data),
        "sections_walked": pe.sections_walked(),
        "func_table_entries": len(funcs),
        "fnv_seed_sites": len(seeds),
        "fnv_prime_sites": len(primes),
        "funcs_with_prime_imul": len(acc),
        "min_keys": min_keys,
    }
    return meta, pe, out


# ---------------------------------------------------------------- reporting
def positive_controls(out):
    """The four anchors the task fixes.  Returns a pass/fail record."""
    by_begin = {d["begin_rva"]: d for d in out}

    def has(begin, name):
        d = by_begin.get(begin)
        return bool(d) and fnv1a(name) in set(d["keys"])

    checks = {
        "main_DeleteComponentForEditObj@0xcba3130": has(0xCBA3130, "DeleteComponentForEditObj"),
        "main_AddInstructionGraphForEditObj@0xcba3130": has(0xCBA3130, "AddInstructionGraphForEditObj"),
        "export_DoImport@0xf03eb40": has(0xF03EB40, "DoImport"),
        "export_DoExport@0xf03eb40": has(0xF03EB40, "DoExport"),
    }
    checks["fnv1a(DeleteComponentForEditObj)==0x0b69f28d"] = fnv1a("DeleteComponentForEditObj") == 0x0B69F28D
    checks["fnv1a(AddInstructionGraphForEditObj)==0xa8a12ee8"] = fnv1a("AddInstructionGraphForEditObj") == 0xA8A12EE8
    return checks


# ---------------------------------------------------------------- annotation
#: Verbatim editor-command vocabulary (verbs x nouns x suffixes).  Used only to
#: give the dumper *candidate* names; a hit is verified by re-hashing the name
#: with the same FNV-1a.  Absence of a hit is a bound on the generator, not a
#: proof of absence -- state it that way in any report.
_VERBS = """Add Create Attach Insert New Make Instantiate Register Apply Set Push Append Mount Equip
Enable Spawn Build Generate Delete Remove Modify Reset Clear Get Query List Inspect Focus Edit Update
Destroy Load Save Import Export Rename SetActive Deactivate Activate Toggle Show Hide Open Close Play
Stop Start End Move Rotate Scale Select Deselect Copy Paste Undo Redo Do Prepare Bind Unbind Refresh
Sync Fetch Collect Parse Dump Print Log Report Notify Cancel Confirm Request Jump Switch Change Replace
Convert Encode Decode Validate Check Verify""".split()
_NOUNS = """Component Components Template Asset Prefab Entity EditObj PrefabInstance Instance Model Object
Resource Archetype Blueprint Node Graph InstructionGraph InstructionNode Terrain Tile Cell Map TileMap
Region Area Layer Material Mesh Decor Gadget Trigger Collision Widget Group Item Shop Currency Suite
Faction Tag Name Transform Position Rotation ScaleId SpawnPoint Point Course Level Scene Camera View
Character Light Esp Screenshot DropGather LocalBullet Bullet CombatSetting DebugLog PerformanceReport
Report Skill Ability Buff Monster NPC Waypoint Path Route Emitter Effect Particle Sound Music Audio Image
Texture Animation Clip Curve KeyFrame Frame Time Timeline Task Quest Condition Action Event Signal Channel
Message Packet Data Config Setting Option Profile Account Player Team Guild Inventory Bag Slot Anchor
Socket Bone Joint RigSkeleton""".split()
_SUFFIXES = ["", "s", "ForEditObj", "ForPrefab", "ForEntity", "ForInstance", "ForComponent", "ForLevel",
             "InEditObj", "InPrefab", "ToEditObj", "ByIndex", "Component", "Components", "All", "Info",
             "Data", "Id", "List", "Map", "Set"]


def _generated_names():
    out = set()
    for v in _VERBS:
        for n in _NOUNS:
            for s in _SUFFIXES:
                out.add(v + n + s)
    for n in _NOUNS:
        for s in _SUFFIXES:
            out.add(n + s)
    return out


def _corpus_names(root):
    """Names visible in the offline editor corpus / string table / local dbs."""
    import json
    import re
    import sqlite3
    root = Path(root)
    out = set()
    lit = re.compile(r'"((?:[^"\\\n]|\\.){1,200})"')
    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,80}")
    for p in (root / ".runtime/editor-catalog/resolved").glob("*.cs"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.update(m.group(1) for m in lit.finditer(t))
        out.update(m.group(0) for m in ident.finditer(t))
    st = root / ".runtime/editor-catalog/string-table.json"
    if st.exists():
        for v in json.loads(st.read_text(encoding="utf-8")).values():
            if isinstance(v, str):
                out.add(v)
    for db in ("docs/research/beyondeditor-frontend/db/frontend.db",
               "docs/research/beyondeditor-backend/db/backend.db"):
        p = root / db
        if not p.exists():
            continue
        con = sqlite3.connect(str(p))
        try:
            for (tn,) in con.execute("select name from sqlite_master where type='table'"):
                try:
                    rows = con.execute(f"select * from '{tn}'").fetchall()
                except sqlite3.Error:
                    continue
                for row in rows:
                    for v in row:
                        if isinstance(v, str):
                            out.add(v)
        finally:
            con.close()
    return out


_NAME_INDEX_CACHE = {}


def build_name_index(project_root):
    key = str(Path(project_root).resolve())
    if key not in _NAME_INDEX_CACHE:
        names = _corpus_names(project_root) | _generated_names()
        _NAME_INDEX_CACHE[key] = {fnv1a(n): n for n in names}
    return _NAME_INDEX_CACHE[key]


def annotate(out, project_root):
    """Attach a candidate name (if any) to each key.  Never invents a name."""
    idx = build_name_index(project_root)
    named_total = 0
    for d in out:
        d["named"] = {f"{k:#010x}": idx[k] for k in d["keys"] if k in idx}
        d["named_count"] = len(d["named"])
        named_total += d["named_count"]
    return {"name_index_size": len(idx), "named_key_instances": named_total}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", default=r"C:\Games\Genshin Impact Game\YuanShen.exe")
    ap.add_argument("--out", default=None, help="write full JSON here")
    ap.add_argument("--min-keys", type=int, default=3)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--annotate", action="store_true",
                    help="attach candidate names from the offline corpus + generator")
    args = ap.parse_args(argv)

    meta, _pe, out = scan(args.exe, min_keys=args.min_keys)
    naming = None
    if args.annotate:
        naming = annotate(out, Path(__file__).resolve().parents[2])
    v = meta
    print(f"exe            {v['exe']}")
    print(f"sha256         {v['sha256']}")
    print(f"sections       {', '.join(v['sections_walked'])}")
    print(f"func entries   {v['func_table_entries']}")
    print(f"seed sites     {v['fnv_seed_sites']}   prime sites {v['fnv_prime_sites']}   funcs w/ prime {v['funcs_with_prime_imul']}")
    print(f"dispatchers    {len(out)}  (min distinct keys = {args.min_keys})")
    total = sum(d["key_count"] for d in out)
    distinct = len({k for d in out for k in d["keys"]})
    print(f"key instances  {total}   distinct keys {distinct}")
    print("-- top dispatchers --")
    for d in out[:args.top]:
        print(f"  {d['begin_rva']:#010x}-{d['end_rva']:#010x} keys={d['key_count']:4d} "
              f"nodes={d['tree_nodes']:5d} acc={','.join(d['accumulator'])} seed={d['has_seed']}")
    print("-- positive controls --")
    pc = positive_controls(out)
    for k, ok in pc.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {k}")
    if not all(pc.values()):
        print("!! a positive control FAILED", file=sys.stderr)
    if args.out:
        blob = {
            "scan": v,
            "dispatcher_count": len(out),
            "key_instances": total,
            "distinct_keys": distinct,
            "positive_controls": pc,
            "naming": naming,
            "dispatchers": [
                {**{k: v2 for k, v2 in d.items() if k not in ("keys", "named")},
                 "begin_rva": f"{d['begin_rva']:#x}",
                 "end_rva": f"{d['end_rva']:#x}",
                 "file_offset_begin": d["file_offset_begin"],
                 "file_offset_end": d["file_offset_end"],
                 "root_rva": f"{d['root_rva']:#x}",
                 "keys": [f"{k:#010x}" for k in d["keys"]],
                 "named": d.get("named", {})}
                for d in out
            ],
        }
        Path(args.out).write_text(json.dumps(blob, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0 if all(positive_controls(out).values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
