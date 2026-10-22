#!/usr/bin/env python3
"""Focused tests for the offline editor-catalog pipeline guards.

Synthetic data only: every fixture is a few bytes built in a TemporaryDirectory,
with a tiny protobuf-wire encoder standing in for the editor's real resources.
No game install, no archive password and no network are touched.

The extract fixtures are plain unencrypted ZIPs written by the stdlib, which
cannot produce ZipCrypto archives. Production keeps encryption as an explicit
requirement (`extract.inspect_archive(..., require_encryption=True)`, the
default, asserted below); the fixture tests lower that flag only to exercise the
surrounding structure -- entry count, member name, inner ZIP validity, CRC,
publish ordering. Nothing in production lowers it.

Run:  python -m unittest test_catalog_inputs -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import catalog_inputs as ci  # noqa: E402


def load_script(filename: str):
    name = filename.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


decode = load_script("decode-mihoyobin.py")
extract = load_script("extract-assets-bin.py")
build_tree = load_script("build-category-tree.py")
build_nodes = load_script("build-node-catalog.py")
resolve_names = load_script("resolve-node-names.py")
summarize = load_script("summarize-catalog.py")


def run_main(main, argv):
    """Run a script's main() with argv patched; capture and return its output."""
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", argv), \
            contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        code = main()
    return code, out_buf.getvalue(), err_buf.getvalue()


# --- tiny protobuf wire encoder ------------------------------------------------

def pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_vi(field: int, value: int) -> bytes:
    return pb_varint((field << 3) | 0) + pb_varint(value)


def pb_ld(field: int, payload: bytes) -> bytes:
    return pb_varint((field << 3) | 2) + pb_varint(len(payload)) + payload


def pb_msg(*parts: bytes) -> bytes:
    return b"".join(parts)


HASH_BRANCH = 1001
HASH_LEAF = 1002
HASH_PIN = 1003
# Every fixture string starts with U+4E00 (UTF-8 lead byte 0xE4, low wire-type
# bits 4). That wire type is unsupported, so the payload reliably fails to parse
# as a submessage and the decoder records it as text rather than as a tree.
TEXT_BRANCH = "一分类"
TEXT_LEAF = "一条目"
TEXT_PIN = "一引脚"

BG_NAME = "Beyond__BeyondGlobal__18125831855067188558.mihoyobin"
NODE_NAME = "Beyond__Node__1234567.mihoyobin"
TEXTMAP_NAME = "TextMap__CHS__777.mihoyobin"


def textmap_payload(entries=None) -> bytes:
    if entries is None:
        entries = ((HASH_BRANCH, TEXT_BRANCH), (HASH_LEAF, TEXT_LEAF), (HASH_PIN, TEXT_PIN))
    recs = []
    for h, t in entries:
        recs.append(pb_ld(2, pb_msg(pb_vi(2, h), pb_ld(3, t.encode("utf-8")))))
    return pb_msg(*recs)


def beyond_global_payload() -> bytes:
    child = pb_msg(pb_vi(1, 1), pb_vi(3, HASH_LEAF))
    root = pb_msg(pb_vi(1, 0), pb_ld(2, child), pb_vi(4, HASH_BRANCH))
    return pb_ld(1, root)


def node_payload() -> bytes:
    pin = pb_msg(
        pb_ld(3, pb_msg(pb_vi(1, 1), pb_vi(2, 0))),
        pb_ld(4, pb_msg(pb_vi(1, 7), pb_vi(2, 1))),
        pb_ld(5, pb_msg(pb_vi(1, 1))),
        pb_vi(7, HASH_PIN),
    )
    return pb_msg(pb_vi(206, HASH_BRANCH), pb_ld(100, pin))


def write_mihoyobin(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(b ^ decode.XOR_KEY for b in payload))
    return path


def build_sources(root: Path) -> Path:
    src = root / "src"
    write_mihoyobin(src / TEXTMAP_NAME, textmap_payload())
    write_mihoyobin(src / BG_NAME, beyond_global_payload())
    write_mihoyobin(src / NODE_NAME, node_payload())
    return src


# --- guard helpers -------------------------------------------------------------

class GuardTests(unittest.TestCase):
    def test_overlap_detected_both_directions(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "base"
            base.mkdir()
            with self.assertRaises(ci.CatalogError):
                ci.ensure_no_overlap(base, base / "out")
            with self.assertRaises(ci.CatalogError):
                ci.ensure_no_overlap(base / "out", base)
            ci.ensure_no_overlap(base, Path(d) / "sibling")

    def test_fresh_dir_rejects_nonempty_but_accepts_empty(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "empty"
            empty.mkdir()
            self.assertEqual(ci.ensure_fresh_dir(empty), empty.resolve())
            (empty / "x").write_text("x", encoding="utf-8")
            with self.assertRaises(ci.CatalogError):
                ci.ensure_fresh_dir(empty)
            afile = Path(d) / "afile"
            afile.write_text("x", encoding="utf-8")
            with self.assertRaises(ci.CatalogError):
                ci.ensure_fresh_dir(afile)

    def test_exclusive_write_refuses_existing_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keep.json"
            p.write_text("PRESERVE", encoding="utf-8")
            with self.assertRaises(ci.CatalogError):
                ci.exclusive_write_text(p, "overwritten")
            self.assertEqual(p.read_text(encoding="utf-8"), "PRESERVE")

    def test_source_set_id_is_stable_and_content_sensitive(self):
        a = ci.source_set_id([("a.bin", "1" * 64), ("b.bin", "2" * 64)])
        b = ci.source_set_id([("b.bin", "2" * 64), ("a.bin", "1" * 64)])
        self.assertEqual(a, b)
        self.assertNotEqual(a, ci.source_set_id([("a.bin", "3" * 64), ("b.bin", "2" * 64)]))


# --- wire parser ---------------------------------------------------------------

class WireParserTests(unittest.TestCase):
    def test_field_number_zero_rejected(self):
        with self.assertRaises(decode.WireError):
            decode.parse_message(b"\x00")

    def test_field_number_above_max_rejected(self):
        tag = (decode.FIELD_NUMBER_MAX + 1) << 3
        with self.assertRaises(decode.WireError):
            decode.parse_message(pb_varint(tag) + pb_varint(0))

    def test_64bit_varint_upper_bits_rejected(self):
        with self.assertRaises(decode.WireError):
            decode.read_varint(b"\x80" * 9 + b"\x02", 0)

    def test_varint_wider_than_64_bits_rejected(self):
        with self.assertRaises(decode.WireError):
            decode.read_varint(b"\x80" * 10 + b"\x01", 0)

    def test_length_delimited_overrun_rejected(self):
        with self.assertRaises(decode.WireError):
            decode.parse_message(pb_ld(1, b"abcd")[:3])

    def test_unsupported_wire_type_rejected(self):
        with self.assertRaises(decode.WireError):
            decode.parse_message(bytes([(1 << 3) | 3]))

    def test_valid_small_message_round_trips(self):
        self.assertEqual(
            decode.parse_message(pb_vi(206, 1001) + pb_ld(3, TEXT_LEAF.encode("utf-8"))),
            [
                {"f": 206, "w": 0, "v": 1001},
                {"f": 3, "w": 2, "s": TEXT_LEAF},
            ],
        )


# --- decoder rejections --------------------------------------------------------

class DecodeRejectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_target_rejected(self):
        code, _, err = run_main(decode.main, ["decode", str(self.tmp / "nope")])
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_empty_directory_rejected(self):
        (self.tmp / "empty").mkdir()
        code, _, err = run_main(decode.main, ["decode", str(self.tmp / "empty")])
        self.assertEqual(code, 1)
        self.assertIn("no .mihoyobin files", err)

    def test_empty_file_rejected(self):
        target = self.tmp / "a.mihoyobin"
        target.write_bytes(b"")
        code, _, err = run_main(decode.main, ["decode", str(target)])
        self.assertEqual(code, 1)
        self.assertIn("empty file", err)

    def test_max_bytes_must_be_positive(self):
        src = build_sources(self.tmp)
        code, _, err = run_main(decode.main, ["decode", str(src), "--max-bytes", "0"])
        self.assertEqual(code, 2)
        self.assertIn("positive", err)

    def test_oversized_file_fails_without_reading(self):
        src = build_sources(self.tmp)
        out = self.tmp / "out"
        code, _, err = run_main(
            decode.main, ["decode", str(src), "--out", str(out), "--max-bytes", "1"]
        )
        self.assertEqual(code, 1)
        self.assertIn("larger than --max-bytes", err)
        self.assertIn("failed=3", err)

    def test_source_output_overlap_rejected(self):
        src = build_sources(self.tmp)
        code, _, err = run_main(decode.main, ["decode", str(src), "--out", str(src / "decoded")])
        self.assertEqual(code, 1)
        self.assertIn("overlap", err)

    def test_index_inside_source_rejected(self):
        src = build_sources(self.tmp)
        code, _, err = run_main(
            decode.main, ["decode", str(src), "--index", str(src / "index.jsonl")]
        )
        self.assertEqual(code, 1)
        self.assertIn("overlap", err)

    def test_index_inside_output_rejected(self):
        src = build_sources(self.tmp)
        out = self.tmp / "out"
        code, _, err = run_main(
            decode.main, ["decode", str(src), "--out", str(out), "--index", str(out / "i.jsonl")]
        )
        self.assertEqual(code, 1)
        self.assertIn("conflicts with output directory", err)

    def test_nonempty_output_refused_and_unchanged(self):
        src = build_sources(self.tmp)
        out = self.tmp / "out"
        out.mkdir()
        marker = out / "keep.txt"
        marker.write_text("PRESERVE", encoding="utf-8")
        code, _, err = run_main(decode.main, ["decode", str(src), "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertIn("not empty", err)
        self.assertEqual(marker.read_text(encoding="utf-8"), "PRESERVE")

    def test_existing_index_refused_and_unchanged(self):
        src = build_sources(self.tmp)
        index = self.tmp / "index.jsonl"
        index.write_text("PRESERVE", encoding="utf-8")
        code, _, err = run_main(
            decode.main, ["decode", str(src), "--out", str(self.tmp / "out"), "--index", str(index)]
        )
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(index.read_text(encoding="utf-8"), "PRESERVE")

    def test_duplicate_flattened_names_rejected(self):
        src = self.tmp / "dup"
        write_mihoyobin(src / "a__b.mihoyobin", textmap_payload())
        write_mihoyobin(src / "a" / "b.mihoyobin", textmap_payload())
        code, _, err = run_main(
            decode.main, ["decode", str(src), "--out", str(self.tmp / "out")]
        )
        self.assertEqual(code, 1)
        self.assertIn("duplicate flattened", err)


# --- pipeline happy path and consumer refusals ---------------------------------

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src = build_sources(self.tmp)
        self.out = self.tmp / "decoded"
        self.index = self.tmp / "index.jsonl"
        code, _, err = run_main(
            decode.main,
            ["decode", str(self.src), "--out", str(self.out), "--index", str(self.index)],
        )
        self.assertEqual(code, 0, err)
        self.prov = json.loads((self.out / ci.PROVENANCE_NAME).read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def _copy_decoded(self, name: str) -> Path:
        dst = self.tmp / name
        shutil.copytree(self.out, dst)
        return dst

    def test_decoded_provenance_is_complete(self):
        self.assertEqual(self.prov["tool"], "decode-mihoyobin.py")
        self.assertEqual(self.prov["counts"], {"files": 3, "ok": 3, "failed": 0})
        self.assertEqual(len(self.prov["source_set_sha256"]), 64)
        outputs = [r["output"] for r in self.prov["files"]]
        self.assertEqual(len(set(outputs)), len(outputs))
        self.assertIn("Beyond__Node__1234567.mihoyobin.json", outputs)
        for r in self.prov["files"]:
            self.assertTrue(r["ok"], r)
            self.assertEqual(len(r["source_sha256"]), 64)
            self.assertEqual(len(r["decoded_sha256"]), 64)
            self.assertEqual(r["source_set_sha256"], self.prov["source_set_sha256"])
            self.assertEqual(ci.sha256_file(self.out / r["output"]), r["output_sha256"])

    def test_category_tree_and_node_catalog_and_resolver(self):
        tree = self.tmp / "tree.md"
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(self.out), "--out", str(tree)]
        )
        self.assertEqual(code, 0, err)
        body = tree.read_text(encoding="utf-8")
        self.assertIn(TEXT_BRANCH, body)
        self.assertIn(TEXT_LEAF, body)
        self.assertIn("未解析 0", body)
        sidecar = json.loads(
            Path(str(tree) + ".provenance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sidecar["source_set_id"], self.prov["source_set_sha256"])
        self.assertEqual(sidecar["counts"]["nodes"], 2)
        self.assertEqual(sidecar["counts"]["resolved"], 2)
        self.assertEqual(sidecar["output_sha256"], ci.sha256_file(tree))
        self.assertEqual(len(sidecar["selected_inputs"]), 2)

        nodes_path = self.tmp / "nodes.json"
        code, _, err = run_main(
            build_nodes.main, ["bn", "--decoded", str(self.out), "--json", str(nodes_path)]
        )
        self.assertEqual(code, 0, err)
        nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["id"], 1234567)
        self.assertEqual(nodes[0]["name"], TEXT_BRANCH)
        self.assertEqual(nodes[0]["pins"][0]["name"], TEXT_PIN)
        self.assertEqual(nodes[0]["pins"][0]["class"], 1)

        rows_path = self.tmp / "rows.json"
        code, _, err = run_main(
            resolve_names.main, ["rn", "--decoded", str(self.out), "--out", str(rows_path)]
        )
        self.assertEqual(code, 0, err)
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["f206"], HASH_BRANCH)
        self.assertEqual(rows[0]["text206"], TEXT_BRANCH)
        self.assertTrue(Path(str(rows_path) + ".provenance.json").is_file())

    def test_resolver_without_out_is_stdout_only(self):
        code, out, _ = run_main(resolve_names.main, ["rn", "--decoded", str(self.out)])
        self.assertEqual(code, 0)
        self.assertIn("f206-resolved=1", out)

    def test_summarize_from_index_and_provenance(self):
        code, out, err = run_main(summarize.main, ["sum", str(self.index)])
        self.assertEqual(code, 0, err)
        self.assertIn("### (root)", out)
        self.assertIn("files=3", out)

    def test_missing_provenance_refused(self):
        dst = self._copy_decoded("d_noprov")
        (dst / ci.PROVENANCE_NAME).unlink()
        tree = self.tmp / "t1.md"
        code, _, err = run_main(build_tree.main, ["bt", "--decoded", str(dst), "--out", str(tree)])
        self.assertEqual(code, 1)
        self.assertIn("provenance missing", err)
        self.assertFalse(tree.exists())

    def test_tampered_decoded_output_refused(self):
        dst = self._copy_decoded("d_tampered")
        victim = dst / f"{TEXTMAP_NAME}.json"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(dst), "--out", str(self.tmp / "t2.md")]
        )
        self.assertEqual(code, 1)
        self.assertIn("sha256 mismatch", err)

    def test_mixed_source_set_ids_refused(self):
        dst = self._copy_decoded("d_mixed")
        prov = json.loads((dst / ci.PROVENANCE_NAME).read_text(encoding="utf-8"))
        for rec in prov["files"]:
            if rec["output"].startswith("Beyond__BeyondGlobal__"):
                rec["source_set_sha256"] = "0" * 64
        (dst / ci.PROVENANCE_NAME).write_text(json.dumps(prov), encoding="utf-8")
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(dst), "--out", str(self.tmp / "t3.md")]
        )
        self.assertEqual(code, 1)
        self.assertIn("mixed source-set", err)

    def test_missing_required_sample_refused(self):
        # The provenance still lists the sample, but its decoded file is gone.
        dst = self._copy_decoded("d_missing")
        (dst / f"{TEXTMAP_NAME}.json").unlink()
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(dst), "--out", str(self.tmp / "t4.md")]
        )
        self.assertEqual(code, 1)
        self.assertIn("output missing", err)

    def test_missing_beyond_global_sample_refused(self):
        dst = self._copy_decoded("d_missing_bg")
        (dst / f"{BG_NAME}.json").unlink()
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(dst), "--out", str(self.tmp / "t4b.md")]
        )
        self.assertEqual(code, 1)
        self.assertIn("BeyondGlobal", err)

    def test_stale_source_refused(self):
        (self.src / NODE_NAME).write_bytes((self.src / NODE_NAME).read_bytes() + b"\x00")
        code, _, err = run_main(
            build_nodes.main,
            ["bn", "--decoded", str(self.out), "--json", str(self.tmp / "n1.json")],
        )
        self.assertEqual(code, 1)
        self.assertIn("stale", err)
        self.assertFalse((self.tmp / "n1.json").exists())

    def test_existing_consumer_output_refused_and_unchanged(self):
        tree = self.tmp / "t5.md"
        tree.write_text("PRESERVE", encoding="utf-8")
        code, _, err = run_main(build_tree.main, ["bt", "--decoded", str(self.out), "--out", str(tree)])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(tree.read_text(encoding="utf-8"), "PRESERVE")

    def test_unique_beyond_global_selection(self):
        two = self.tmp / "src_two"
        write_mihoyobin(two / TEXTMAP_NAME, textmap_payload())
        write_mihoyobin(two / BG_NAME, beyond_global_payload())
        write_mihoyobin(two / "Beyond__BeyondGlobal__2.mihoyobin", beyond_global_payload())
        out_two = self.tmp / "decoded_two"
        code, _, err = run_main(decode.main, ["decode", str(two), "--out", str(out_two)])
        self.assertEqual(code, 0, err)
        code, _, err = run_main(
            build_tree.main, ["bt", "--decoded", str(out_two), "--out", str(self.tmp / "t6.md")]
        )
        self.assertEqual(code, 1)
        self.assertIn("exactly one decoded BeyondGlobal", err)
        # an explicit filename disambiguates it
        code, _, err = run_main(
            build_tree.main,
            ["bt", "--decoded", str(out_two), "--out", str(self.tmp / "t7.md"),
             "--beyond-global", f"{BG_NAME}.json"],
        )
        self.assertEqual(code, 0, err)
        # but an explicit path may not escape --decoded
        code, _, err = run_main(
            build_tree.main,
            ["bt", "--decoded", str(out_two), "--out", str(self.tmp / "t9.md"),
             "--beyond-global", "../elsewhere.json"],
        )
        self.assertEqual(code, 1)
        self.assertIn("plain filename", err)

    def test_zero_name_hits_refused(self):
        src = self.tmp / "src_zero"
        write_mihoyobin(src / TEXTMAP_NAME, textmap_payload(((999999, TEXT_BRANCH),)))
        write_mihoyobin(src / BG_NAME, beyond_global_payload())
        out = self.tmp / "decoded_zero"
        code, _, err = run_main(decode.main, ["decode", str(src), "--out", str(out)])
        self.assertEqual(code, 0, err)
        tree = self.tmp / "t8.md"
        code, _, err = run_main(build_tree.main, ["bt", "--decoded", str(out), "--out", str(tree)])
        self.assertEqual(code, 1)
        self.assertIn("zero of", err)
        self.assertFalse(tree.exists())

    def test_summarize_rejects_malformed_empty_and_mixed(self):
        sidecar_src = Path(str(self.index) + ".provenance.json")

        empty = self.tmp / "e.jsonl"
        empty.write_text("\n", encoding="utf-8")
        shutil.copy(sidecar_src, Path(str(empty) + ".provenance.json"))
        code, _, err = run_main(summarize.main, ["sum", str(empty)])
        self.assertEqual(code, 1)
        self.assertIn("no usable records", err)

        malformed = self.tmp / "m.jsonl"
        malformed.write_text("{not json}\n", encoding="utf-8")
        shutil.copy(sidecar_src, Path(str(malformed) + ".provenance.json"))
        code, _, err = run_main(summarize.main, ["sum", str(malformed)])
        self.assertEqual(code, 1)
        self.assertIn("malformed index line", err)

        mixed = self.tmp / "x.jsonl"
        entries = [json.loads(line) for line in self.index.read_text(encoding="utf-8").splitlines()]
        entries[0]["source_set_sha256"] = "0" * 64
        mixed.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        shutil.copy(sidecar_src, Path(str(mixed) + ".provenance.json"))
        code, _, err = run_main(summarize.main, ["sum", str(mixed)])
        self.assertEqual(code, 1)
        self.assertIn("source-set id mismatch", err)

        dup = self.tmp / "d.jsonl"
        dup.write_text(
            "\n".join(json.dumps(e) for e in entries + [entries[0]]) + "\n", encoding="utf-8"
        )
        shutil.copy(sidecar_src, Path(str(dup) + ".provenance.json"))
        code, _, err = run_main(summarize.main, ["sum", str(dup)])
        self.assertEqual(code, 1)
        self.assertIn("duplicate source_relative_path", err)

    def test_summarize_rejects_missing_provenance(self):
        code, _, err = run_main(summarize.main, ["sum", str(self.index), "--provenance", str(self.tmp / "no.json")])
        self.assertEqual(code, 1)
        self.assertIn("provenance missing", err)


    def test_source_fingerprint_must_match_members(self):
        dst = self._copy_decoded("d_bad_fingerprint")
        p = dst / ci.PROVENANCE_NAME
        prov = json.loads(p.read_text(encoding="utf-8"))
        prov["files"][0]["source_sha256"] = "0" * 64
        p.write_text(json.dumps(prov), encoding="utf-8")
        code, _, err = run_main(build_nodes.main, ["bn", "--decoded", str(dst), "--json", str(self.tmp / "bad.json")])
        self.assertEqual(code, 1)
        self.assertIn("fingerprint mismatch", err)

    def test_index_content_hash_detects_changed_fields(self):
        entries = [json.loads(line) for line in self.index.read_text(encoding="utf-8").splitlines()]
        entries[0]["strings"] = [".1\tchanged"]
        self.index.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        code, _, err = run_main(summarize.main, ["sum", str(self.index)])
        self.assertEqual(code, 1)
        self.assertIn("index sha256", err)

    def test_consumer_output_bundle_preflight(self):
        for name, main, option in [("resolver", resolve_names.main, "--out"), ("tree", build_tree.main, "--out"), ("nodes", build_nodes.main, "--json")]:
            with self.subTest(name=name):
                out = self.tmp / (name + ".json")
                sidecar = Path(str(out) + ".provenance.json")
                sidecar.write_text("preserve", encoding="utf-8")
                code, _, err = run_main(main, [name, "--decoded", str(self.out), option, str(out)])
                self.assertEqual(code, 1, err)
                self.assertFalse(out.exists())
                self.assertEqual(sidecar.read_text(encoding="utf-8"), "preserve")
                for root in [self.src, self.out]:
                    output = root / (name + "-new.json")
                    code, _, err = run_main(main, [name, "--decoded", str(self.out), option, str(output)])
                    self.assertEqual(code, 1, err)
                    self.assertFalse(output.exists())

    def test_decoder_index_sidecar_preflight(self):
        target = self.tmp / "next-index.jsonl"
        Path(str(target) + ".provenance.json").write_text("preserve", encoding="utf-8")
        out = self.tmp / "next-decoded"
        code, _, err = run_main(decode.main, ["decode", str(self.src), "--out", str(out), "--index", str(target)])
        self.assertEqual(code, 1, err)
        self.assertFalse(target.exists())
        self.assertFalse(out.exists())

    def test_decoder_detects_source_change_between_hash_and_read(self):
        out = self.tmp / "changed-decoded"
        original = decode.decode
        def changed(path, max_bytes):
            data = path.read_bytes()
            path.write_bytes(data + bytes([decode.XOR_KEY ^ 8, decode.XOR_KEY ^ 1]))
            return original(path, max_bytes)
        with mock.patch.object(decode, "decode", side_effect=changed):
            code, _, err = run_main(decode.main, ["decode", str(self.src), "--out", str(out)])
        self.assertEqual(code, 1, err)
        self.assertIn("source changed", err)


# --- extract fixtures (unencrypted, fixture-only) -------------------------------

class ExtractFixtureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.src = self.tmp / "install"
        self.src.mkdir()
        self.inner = self._inner_zip_bytes()

    def tearDown(self):
        self._tmp.cleanup()

    def _inner_zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("nested/a.txt", b"hello-a")
            zf.writestr("nested/b.txt", b"hello-b")
        return buf.getvalue()

    def _outer(self, name: str, payload: bytes, member: str | None = None) -> Path:
        path = self.src / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(member if member is not None else name, payload)
        return path

    def _both_outers(self):
        self._outer("beyondeditorassets.bin", self.inner)
        self._outer("assets.bin", self.inner)

    def test_production_default_requires_encryption(self):
        self._outer("beyondeditorassets.bin", self.inner)
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.inspect_archive(
                self.src / "beyondeditorassets.bin", self.tmp / "stage"
            )
        self.assertIn("not encrypted", str(ctx.exception))
        self.assertTrue(extract.inspect_archive.__defaults__[0])

    def test_fixture_happy_path_publishes_both_archives(self):
        self._both_outers()
        out = self.tmp / "out"
        manifest = extract.extract_archives(
            self.src, out, None, require_encryption=False
        )
        self.assertTrue((out / "beyondeditorassets.dec").is_file())
        self.assertTrue((out / "assets.dec").is_file())
        self.assertEqual((out / "assets.dec").read_bytes(), self.inner)
        self.assertEqual((out / "assets-manifest.json").is_file(), True)
        self.assertEqual(manifest["source_root"], str(self.src.resolve()))
        self.assertEqual(len(manifest["source_set_id"]), 64)
        self.assertFalse(manifest["encryption_required"])
        for rec in manifest["archives"]:
            self.assertEqual(rec["outer_entries"], 1)
            self.assertEqual(rec["outer_member"], Path(rec["source_path"]).name)
            self.assertEqual(rec["inner"]["entries"], 2)
            self.assertEqual(rec["inner"]["crc_checked_unencrypted"], 2)
            self.assertEqual(
                {m["name"] for m in rec["inner"]["members"]},
                {"nested/a.txt", "nested/b.txt"},
            )
            for member in rec["inner"]["members"]:
                self.assertEqual(set(member), {"name", "size", "crc", "encrypted", "sha256"})
            self.assertFalse(rec["encrypted"])

    def test_missing_archive_rejected_and_nothing_published(self):
        self._outer("beyondeditorassets.bin", self.inner)
        out = self.tmp / "out"
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.extract_archives(self.src, out, None, require_encryption=False)
        self.assertIn("missing", str(ctx.exception))
        self.assertFalse((out / "assets-manifest.json").exists())
        self.assertEqual([p.name for p in out.glob("*.dec")], [])

    def test_zero_byte_archive_rejected(self):
        self._outer("beyondeditorassets.bin", self.inner)
        (self.src / "assets.bin").write_bytes(b"")
        with self.assertRaises(ci.CatalogError):
            extract.extract_archives(
                self.src, self.tmp / "out", None, require_encryption=False
            )

    def test_multiple_outer_entries_rejected(self):
        path = self.src / "beyondeditorassets.bin"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("beyondeditorassets.bin", self.inner)
            zf.writestr("extra", b"x")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.inspect_archive(path, self.tmp, require_encryption=False)
        self.assertIn("exactly one outer entry", str(ctx.exception))

    def test_unexpected_member_name_rejected(self):
        path = self._outer("beyondeditorassets.bin", self.inner, member="somewhere/else.bin")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.inspect_archive(path, self.tmp, require_encryption=False)
        self.assertIn("unexpected outer member name", str(ctx.exception))

    def test_non_zip_payload_rejected(self):
        path = self._outer("beyondeditorassets.bin", b"not a zip at all")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.inspect_archive(path, self.tmp, require_encryption=False)
        self.assertIn("not a ZIP archive", str(ctx.exception))

    def test_empty_payload_rejected(self):
        path = self._outer("beyondeditorassets.bin", b"")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.inspect_archive(path, self.tmp, require_encryption=False)
        self.assertIn("empty", str(ctx.exception))

    def test_out_inside_source_rejected(self):
        self._both_outers()
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.extract_archives(
                self.src, self.src / "sub", None, require_encryption=False
            )
        self.assertIn("overlap", str(ctx.exception))

    def test_nonempty_output_rejected(self):
        self._both_outers()
        out = self.tmp / "out"
        out.mkdir()
        (out / "keep.txt").write_text("PRESERVE", encoding="utf-8")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.extract_archives(self.src, out, None, require_encryption=False)
        self.assertIn("not empty", str(ctx.exception))
        self.assertEqual((out / "keep.txt").read_text(encoding="utf-8"), "PRESERVE")

    def test_existing_manifest_rejected(self):
        self._both_outers()
        manifest = self.tmp / "manifest.json"
        manifest.write_text("PRESERVE", encoding="utf-8")
        with self.assertRaises(ci.CatalogError) as ctx:
            extract.extract_archives(
                self.src, self.tmp / "out", manifest, require_encryption=False
            )
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(manifest.read_text(encoding="utf-8"), "PRESERVE")


if __name__ == "__main__":
    unittest.main()
