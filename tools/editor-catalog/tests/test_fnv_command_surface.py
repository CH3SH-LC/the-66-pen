#!/usr/bin/env python3
"""Offline tests for the FNV command-surface tool.

Synthetic data only -- a handful of bytes, a stub image object, a two-name
dictionary.  Nothing here opens YuanShen.exe; the optional integration test at
the bottom is skipped unless the engine image happens to be present AND the
caller opted in with MYW_FNV_INTEGRATION=1.
"""
from __future__ import annotations

import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import fnv_command_surface as F  # noqa: E402

DEFAULT_EXE = F.DEFAULT_EXE


def encode_cmp_imm32(reg_index: int, imm: int) -> bytes:
    """`cmp r32, imm32` : opcode 81 /7, mod=11, r/m = the target register.

    modrm = 0b11_111_rrr = 0xF8 | rrr.  (The /7 is the *operation* -- cmp -- and
    is what makes every ``cmp r32, imm32`` land in 0xF8..0xFF; the r/m field
    picks eax..edi.)
    """
    assert 0 <= reg_index <= 7
    return bytes([0x81, 0xF8 | reg_index, *struct.pack("<I", imm)])


class StubImage:
    """Duck-typed stand-in for PeImage: only .data and .blob are used."""

    def __init__(self, data: bytes):
        self.data = data

    def blob(self, begin, end):
        return self.data[begin:end]


class TestHash(unittest.TestCase):
    def test_known_vectors(self):
        # values read straight off the dispatcher's compare chains
        self.assertEqual(F.fnv1a_utf16("DeleteComponentForEditObj"), 0x0B69F28D)
        self.assertEqual(F.fnv1a_utf16("AddInstructionGraphForEditObj"), 0xA8A12EE8)
        self.assertEqual(F.fnv1a_utf16("DoImport"), 0xC9824659)
        self.assertEqual(F.fnv1a_utf16("DoExport"), 0xD8AAE5E2)
        self.assertEqual(F.fnv1a_utf16("FocusEditObj"), 0x78EB3304)

    def test_ascii_equivalence(self):
        # over 16-bit code units == byte-wise, for ASCII
        for s in ("FocusLight", "ModifyEditobjTag", "x", "DeleteDebugLog"):
            self.assertEqual(F.fnv1a_utf16(s), F.fnv1a_data(s.encode("ascii")))

    def test_non_ascii_differs_and_uses_code_units(self):
        s = "é"  # e-acute, code unit 0x00E9
        h = F.BASIS ^ 0x00E9
        h = (h * F.PRIME) & F.MASK32
        self.assertEqual(F.fnv1a_utf16(s), h)
        self.assertNotEqual(F.fnv1a_utf16(s), F.fnv1a_data("é".encode("utf-8")))

    def test_offset_basis(self):
        self.assertEqual(F.fnv1a_utf16(""), F.BASIS & F.MASK32)


class TestCmpFilter(unittest.TestCase):
    def test_finds_cmp_reg_imm32(self):
        imm = 0x0B69F28D
        blob = b"\x90\x90" + encode_cmp_imm32(1, imm) + b"\xc3"
        got = F.cmp_imm32_sites(blob, 0x1000)
        self.assertEqual(got, {imm: [0x1002]})

    def test_ignores_bare_immediate(self):
        # the value present as plain data must NOT be a site (this is the whole
        # point of the filter)
        imm = 0x26E623FE
        blob = b"junk" + struct.pack("<I", imm) + b"tail"
        self.assertEqual(F.cmp_imm32_sites(blob, 0), {})

    def test_ignores_cmp_with_memory_operand(self):
        # 81 /r with mod != 11 is a memory compare, not our shape
        blob = bytes([0x81, 0x38]) + struct.pack("<I", 0x0B69F28D)  # cmp [rax],imm
        self.assertEqual(F.cmp_imm32_sites(blob, 0), {})

    def test_raw_extractor_is_faithful_small_imms_kept(self):
        # the raw extractor reports the instruction as written ...
        blob = encode_cmp_imm32(1, 0x1234)
        self.assertEqual(F.cmp_imm32_sites(blob, 0), {0x1234: [0]})

    def test_decode_drops_small_immediates(self):
        md, err = F.capstone_md()
        if md is None:
            self.skipTest(f"capstone unavailable: {err}")
        # ... but the dispatcher-level policy drops anything below 0x10000,
        # which no FNV-1a hash of a real command name can be.
        blob = encode_cmp_imm32(1, 0x1234) + b"\xc3"
        got = F.decode_function(StubImage(blob), 0, len(blob))
        self.assertEqual(got["constants"], {})

    def test_site_rva_is_begin_relative(self):
        blob = b"\x00" + encode_cmp_imm32(0, 0xA8A12EE8)  # cmp eax, imm
        got = F.cmp_imm32_sites(blob, 0x5000)
        self.assertEqual(list(got), [0xA8A12EE8])
        self.assertEqual(got[0xA8A12EE8], [0x5001])


class TestDecodeAndName(unittest.TestCase):
    def test_decode_detects_indirect_jump(self):
        md, err = F.capstone_md()
        if md is None:
            self.skipTest(f"capstone unavailable: {err}")
        blob = b"\xff\xe0"  # jmp rax
        got = F.decode_function(StubImage(blob), 0, len(blob))
        self.assertTrue(got["complete"])
        self.assertEqual(len(got["indirect_jumps"]), 1)

    def test_decode_complete_flag(self):
        md, err = F.capstone_md()
        if md is None:
            self.skipTest(f"capstone unavailable: {err}")
        blob = encode_cmp_imm32(1, 0x0B69F28D) + b"\xc3"
        got = F.decode_function(StubImage(blob), 0, len(blob))
        self.assertTrue(got["complete"])
        self.assertEqual(got["constants"], {0x0B69F28D: [0]})

    def test_decode_flags_truncated_tail(self):
        md, err = F.capstone_md()
        if md is None:
            self.skipTest(f"capstone unavailable: {err}")
        # 0x48 alone is an incomplete instruction -> decode stops short of end
        blob = b"\x48\x01\xc0" + b"\x48"
        got = F.decode_function(StubImage(blob), 0, len(blob))
        self.assertFalse(got["complete"])

    def test_name_constants(self):
        dictionary = {"FooBar": ("unit",), "Alpha": ("unit",)}
        named = F.name_constants([F.fnv1a_utf16("FooBar"), 0xDEADBEEF], dictionary)
        self.assertEqual(named[F.fnv1a_utf16("FooBar")], [("FooBar", ("unit",))])
        self.assertEqual(named[0xDEADBEEF], [])

    def test_name_constants_collision_visible(self):
        # a synthetic dictionary in which two names share one hash: both must be
        # reported, so a real collision can never be silently mis-resolved.
        orig = F.fnv1a_utf16
        try:
            F.fnv1a_utf16 = lambda s: 0x1234ABCD  # noqa: E731
            named = F.name_constants([0x1234ABCD], {"One": ("a",), "Two": ("b",)})
        finally:
            F.fnv1a_utf16 = orig
        self.assertEqual({n for n, _ in named[0x1234ABCD]}, {"One", "Two"})

    def test_verb_census(self):
        census = F.verb_census(["FocusLight", "FocusEditObj", "DeletePrefab",
                                "ModifySuite"])
        self.assertEqual(census, {"Focus": 2, "Delete": 1, "Modify": 1})


class TestImageScan(unittest.TestCase):
    def test_windows_and_filter(self):
        imm = 0x26E623FE
        data = (b"\x00\x00" + encode_cmp_imm32(1, imm) + b"\x00\x00" +
                struct.pack("<I", imm))  # one real site, one bare copy
        img = StubImage(data)
        naive = F.naive_presence(img, {imm})
        self.assertEqual(naive, {imm})           # naive sees the bare copy too
        filt = F.scan_image_sites(img, {imm})
        self.assertEqual(sorted(filt), [imm])    # filter keeps only the site
        self.assertEqual(filt[imm], [2])


class TestClassify(unittest.TestCase):
    def test_strong_source_is_dictionary(self):
        nm, src, _ = F.classify_constant(0x1111, [("Foo", ("corpus_cs",))])
        self.assertEqual((nm, src), ("Foo", "dictionary"))

    def test_prose_only_is_demoted_to_inferred(self):
        nm, src, note = F.classify_constant(0x1111, [("Foo", ("docs_md",))])
        self.assertEqual((nm, src), ("Foo", "inferred"))
        self.assertTrue(note)

    def test_mixed_sources_stay_dictionary(self):
        nm, src, _ = F.classify_constant(0x1111, [("Foo", ("docs_md", "evidence"))])
        self.assertEqual((nm, src), ("Foo", "dictionary"))

    def test_no_candidate_falls_back_to_inferred_table(self):
        nm, src, _ = F.classify_constant(0x2C4EDA76, [])
        self.assertEqual((nm, src), ("DeleteInstructionGraphForEditObj", "inferred"))

    def test_truly_unknown_is_unnamed(self):
        nm, src, _ = F.classify_constant(0xDEADBEEF, [])
        self.assertEqual((nm, src), (None, "unnamed"))


class TestSources(unittest.TestCase):
    def test_docs_tokens_reads_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs" / "sub").mkdir(parents=True)
            (root / "docs" / "a.md").write_text("name DeleteFooForEditObj x", encoding="utf-8")
            (root / "docs" / "sub" / "b.md").write_text("AddBarForPrefab", encoding="utf-8")
            toks = F._docs_tokens(root)
        self.assertIn("DeleteFooForEditObj", toks)
        self.assertIn("AddBarForPrefab", toks)

    def test_evidence_names_reads_rescan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rel = "ev/scan.json"
            p = root / rel
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({
                "raw_hits": [{"names": ["DoExportClientScript"], "rva": "0x1"}],
                "commands": [{"command": "DoImport", "new_instruction_hits": []}],
            }), encoding="utf-8")
            orig = F.EVIDENCE_FILES
            try:
                F.EVIDENCE_FILES = [rel]
                names = F._evidence_names(root)
            finally:
                F.EVIDENCE_FILES = orig
        self.assertEqual(names, {"DoExportClientScript", "DoImport"})

    def test_load_dictionary_union_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir()
            (root / "docs" / "a.md").write_text("SomeCommandName", encoding="utf-8")
            names, used = F.load_dictionary(root)
        self.assertIn("SomeCommandName", names)
        self.assertIn("docs_md", names["SomeCommandName"])


@unittest.skipUnless(os.environ.get("MYW_FNV_INTEGRATION") == "1"
                     and DEFAULT_EXE.exists(),
                     "set MYW_FNV_INTEGRATION=1 with the engine image present")
class TestIntegration(unittest.TestCase):
    def test_positive_controls_and_bounds(self):
        img = F.PeImage(DEFAULT_EXE)
        for label, (b, e, _svc) in F.DISPATCHERS.items():
            dec = F.decode_function(img, b, e)
            self.assertTrue(dec["complete"])
            self.assertEqual(dec["indirect_jumps"], [])
            self.assertTrue(dec["fnv_basis_sites"])
            self.assertTrue(dec["fnv_prime_sites"])
            self.assertIn(F.fnv1a_utf16(F.POSITIVE_CONTROL[label][0]),
                          dec["constants"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
