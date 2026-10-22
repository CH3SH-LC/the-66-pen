# -*- coding: utf-8 -*-
"""Offline tests for tools/editor-catalog/fnv_dispatchers.py.

Groups:
  1. FNV-1a vectors (the four positive-control hashes + classic values).
  2. Pure tree-shape helpers on SYNTHETIC instruction lists (FakeInsn) -- no
     executable, no capstone, no PE.  Covers 2-way, 3-way and jmp nodes.
  3. Name-index invariant: every attached name re-hashes to its own key.
  4. Real-image integration: skipped unless YuanShen.exe is present.  Asserts
     the four positive controls and the five prior-artifact row counts.

Run:
    PYTHONIOENCODING=utf-8 python -m unittest discover -s tools/editor-catalog/tests -p "test_fnv_dispatchers.py"
"""
import importlib.util
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXE = Path(r"C:\Games\Genshin Impact Game\YuanShen.exe")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fd = _load("fnv_dispatchers")


class FakeInsn:
    """Duck-typed stand-in for a capstone insn (address/size/mnemonic/op_str)."""

    __slots__ = ("address", "size", "mnemonic", "op_str")

    def __init__(self, address, size, mnemonic, op_str):
        self.address = address
        self.size = size
        self.mnemonic = mnemonic
        self.op_str = op_str


class TestFnv(unittest.TestCase):
    def test_classic_vectors(self):
        self.assertEqual(fd.fnv1a(""), 0x811C9DC5)
        self.assertEqual(fd.fnv1a("a"), 0xE40C292C)
        self.assertEqual(fd.fnv1a("abc"), 0x1A47E90B)

    def test_positive_control_hashes(self):
        self.assertEqual(fd.fnv1a("DeleteComponentForEditObj"), 0x0B69F28D)
        self.assertEqual(fd.fnv1a("AddInstructionGraphForEditObj"), 0xA8A12EE8)
        self.assertEqual(fd.fnv1a("DoImport"), 0xC9824659)
        self.assertEqual(fd.fnv1a("DoExport"), 0xD8AAE5E2)

    def test_byte_and_char_agree_on_ascii(self):
        for s in ("Clear", "ModifySuite", "FocusLight", "ABCDEFGHIJKLMNOP"):
            self.assertEqual(fd.fnv1a(s), fd.fnv1a_bytes(s.encode("ascii")))

    def test_readme_anchor_hash(self):
        # the anchor the task fixes: our own FNV must land on the constant
        # actually present at 0xcba3428 in the image.
        self.assertEqual(fd.fnv1a("DeleteComponentForEditObj"), 0xB69F28D)


class TestCmpAccImm(unittest.TestCase):
    def test_accepts_accumulator_cmp(self):
        i = FakeInsn(0x1000, 6, "cmp", "ecx, 0x12345678")
        self.assertEqual(fd._cmp_acc_imm(i, {"ecx"}), 0x12345678)

    def test_rejects_wrong_register(self):
        i = FakeInsn(0x1000, 6, "cmp", "edx, 0x12345678")
        self.assertIsNone(fd._cmp_acc_imm(i, {"ecx"}))

    def test_rejects_small_immediate(self):
        i = FakeInsn(0x1000, 6, "cmp", "ecx, 0x40")
        self.assertIsNone(fd._cmp_acc_imm(i, {"ecx"}))

    def test_rejects_non_cmp(self):
        i = FakeInsn(0x1000, 6, "mov", "ecx, 0x12345678")
        self.assertIsNone(fd._cmp_acc_imm(i, {"ecx"}))

    def test_accepts_negative_register_op(self):
        # capstone renders immediates as unsigned hex; ensure no sign surprise
        i = FakeInsn(0x1000, 6, "cmp", "ecx, 0xffffffff")
        self.assertEqual(fd._cmp_acc_imm(i, {"ecx"}), 0xFFFFFFFF)


class TestNodeSuccessors(unittest.TestCase):
    def _by(self, insns):
        return {i.address: i for i in insns}

    def test_two_way(self):
        cmp = FakeInsn(0x1000, 6, "cmp", "ecx, 0x11111111")
        ja = FakeInsn(0x1006, 6, "ja", "0x1020")
        nxt = FakeInsn(0x100c, 6, "cmp", "ecx, 0x22222222")
        succ = fd.node_successors(cmp, self._by([cmp, ja, nxt]))
        self.assertEqual(succ, [0x1020, 0x100C])

    def test_three_way_ja_je(self):
        cmp = FakeInsn(0x1000, 6, "cmp", "ecx, 0x11111111")
        ja = FakeInsn(0x1006, 6, "ja", "0x1020")
        je = FakeInsn(0x100C, 6, "je", "0x1040")
        nxt = FakeInsn(0x1012, 6, "cmp", "ecx, 0x22222222")
        succ = fd.node_successors(cmp, self._by([cmp, ja, je, nxt]))
        self.assertEqual(succ, [0x1020, 0x1040, 0x1012])

    def test_jmp_terminates_no_fallthrough(self):
        cmp = FakeInsn(0x1000, 6, "cmp", "ecx, 0x11111111")
        jmp = FakeInsn(0x1006, 6, "jmp", "0x2000")
        succ = fd.node_successors(cmp, self._by([cmp, jmp]))
        self.assertEqual(succ, [0x2000])

    def test_plain_fallthrough(self):
        cmp = FakeInsn(0x1000, 6, "cmp", "ecx, 0x11111111")
        mv = FakeInsn(0x1006, 3, "mov", "ebx, 5")
        self.assertEqual(fd.node_successors(cmp, self._by([cmp, mv])), [0x1006])


class TestWalkKeyTree(unittest.TestCase):
    def _tree(self):
        insns = [
            # node A
            FakeInsn(0x1000, 6, "cmp", "ecx, 0xaaaa0001"),
            FakeInsn(0x1006, 6, "ja", "0x1020"),    # -> node B
            FakeInsn(0x100C, 6, "je", "0x1040"),    # -> body1 (leaf)
            # node C (fall-through of A)
            FakeInsn(0x1012, 6, "cmp", "ecx, 0xaaaa0002"),
            FakeInsn(0x1018, 6, "ja", "0x1030"),    # -> node D
            FakeInsn(0x101E, 6, "jne", "0x1080"),   # -> default (leaf)
            FakeInsn(0x1024, 3, "mov", "ebx, 2"),   # body2 (leaf)
            # node B
            FakeInsn(0x1020, 6, "cmp", "ecx, 0xaaaa0003"),
            FakeInsn(0x1026, 6, "je", "0x1090"),    # -> body3 (leaf)
            FakeInsn(0x102C, 3, "mov", "ebx, 3"),   # default (leaf)
            # node D
            FakeInsn(0x1030, 6, "cmp", "ecx, 0xaaaa0004"),
            FakeInsn(0x1036, 6, "jne", "0x1080"),
            FakeInsn(0x103C, 3, "mov", "ebx, 4"),
            # leaf bodies
            FakeInsn(0x1040, 3, "mov", "ebx, 1"),
            FakeInsn(0x1080, 3, "mov", "ebx, 0"),
            FakeInsn(0x1090, 3, "mov", "ebx, 3"),
        ]
        return {i.address: i for i in insns}

    def test_collects_all_four_keys(self):
        nodes, leaves = fd.walk_key_tree(self._tree(), {"ecx"}, 0x1000)
        self.assertEqual(sorted(v for _a, v in nodes),
                         [0xAAAA0001, 0xAAAA0002, 0xAAAA0003, 0xAAAA0004])
        self.assertGreaterEqual(leaves, 4)

    def test_wrong_regs_yields_nothing(self):
        nodes, _ = fd.walk_key_tree(self._tree(), {"eax"}, 0x1000)
        self.assertEqual(nodes, [])

    def test_missing_root_is_empty(self):
        nodes, _ = fd.walk_key_tree(self._tree(), {"ecx"}, 0x9999)
        self.assertEqual(nodes, [])


class TestFirstSwitchRoot(unittest.TestCase):
    def test_root_is_first_cmp_after_last_imul(self):
        insns = [
            FakeInsn(0x1000, 3, "mov", "ecx, 0x811c9dc5"),
            FakeInsn(0x1003, 6, "imul", "ecx, esi, 0x1000193"),
            FakeInsn(0x1009, 2, "jne", "0x1000"),
            FakeInsn(0x100B, 3, "test", "rdx, rdx"),
            FakeInsn(0x100E, 6, "cmp", "ecx, 0xaaaa0001"),  # <- root
            FakeInsn(0x1014, 6, "ja", "0x2000"),
        ]
        self.assertEqual(fd.first_switch_root(insns, {"ecx"}), 0x100E)

    def test_no_imul_no_root(self):
        insns = [FakeInsn(0x1000, 6, "cmp", "ecx, 0xaaaa0001")]
        self.assertIsNone(fd.first_switch_root(insns, {"ecx"}))


class TestNameIndex(unittest.TestCase):
    def test_generated_names_rehash(self):
        for n in list(fd._generated_names())[:500]:
            self.assertIn(fd.fnv1a(n), fd.build_name_index(PROJECT_ROOT))

    def test_no_duplicate_name_at_a_key(self):
        # annotate() must never fabricate: each attached name re-hashes to its key.
        idx = fd.build_name_index(PROJECT_ROOT)
        for k, n in list(idx.items())[:2000]:
            self.assertEqual(fd.fnv1a(n), k)


@unittest.skipUnless(EXE.exists(), "YuanShen.exe not present")
class TestRealImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta, _pe, cls.out = fd.scan(str(EXE), min_keys=3)
        cls.by = {d["begin_rva"]: d for d in cls.out}

    def test_positive_controls(self):
        for k, ok in fd.positive_controls(self.out).items():
            self.assertTrue(ok, k)

    def test_prior_five_rows_reproduced(self):
        expected = {
            0xCBA3130: 27,
            0xF03EB40: 9,
            0xA33DED0: 319,
            0x10324250: 18,
            0xA37BE00: 479,
        }
        for begin, n in expected.items():
            self.assertIn(begin, self.by, f"{begin:#x} missing")
            self.assertEqual(self.by[begin]["key_count"], n, f"{begin:#x}")

    def test_prior_five_are_not_the_whole_surface(self):
        # the whole point of the exercise: the surface is far larger than five.
        self.assertGreater(len(self.out), 5)

    def test_every_dispatcher_has_the_seed(self):
        # every reported dispatcher must own the FNV seed mov inside its body.
        bad = [d["begin_rva"] for d in self.out if not d["has_seed"]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
