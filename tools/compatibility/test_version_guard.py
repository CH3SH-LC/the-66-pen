"""Offline tests for the compatibility guard.

Every fixture is synthetic and lives in a temporary directory: no test opens the
installed game image or the editor assembly, reads the live save, or executes
anything.  The PE parser is exercised through ``inspect_image`` with a tiny
image whose anchors sit at small RVAs, so the real 445 MB image is never mapped.
"""
from __future__ import annotations

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import version_guard as guard  # noqa: E402

PE_OFFSET = 0x40
RAW_PTR, RAW_SIZE, VA = 0x200, 0x200, 0x1000
ANCHOR_NAMES = ("CONTEXT", "LEVEL", "PLACE", "SAVE")
LABELS = ("synthetic-baseline",)


def synthetic_image(*, timestamp=1234, image_size=0x4000, machine=0x8664,
                    anchors=None, raw_ptr=RAW_PTR, raw_size=RAW_SIZE, va=VA,
                    section_count=1, size=0x400) -> bytes:
    """A minimal but structurally valid x64 PE with the anchors written in."""
    data = bytearray(size)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 60, PE_OFFSET)
    data[PE_OFFSET:PE_OFFSET + 4] = b"PE\0\0"
    struct.pack_into("<H", data, PE_OFFSET + 4, machine)
    struct.pack_into("<H", data, PE_OFFSET + 6, section_count)
    struct.pack_into("<I", data, PE_OFFSET + 8, timestamp)
    struct.pack_into("<H", data, PE_OFFSET + 20, 0x70)
    optional = PE_OFFSET + 24
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 56, image_size)
    table = optional + 0x70
    struct.pack_into("<IIII", data, table + 8, RAW_SIZE, VA, raw_size, raw_ptr)
    for rva, payload in (anchors or {}).items():
        offset = raw_ptr + (rva - VA)
        data[offset:offset + len(payload)] = payload
    return bytes(data)


def baseline_fixture(offset=0) -> dict:
    """Synthetic baseline whose four anchors sit at small, distinct RVAs.

    Anchor values are hex strings, exactly as the real ``BASELINE`` stores them.
    """
    anchors = {}
    for index, name in enumerate(ANCHOR_NAMES):
        anchors[name] = (0x1010 + index * 0x20 + offset, bytes(range(index, index + 16)).hex())
    return {"label": LABELS[0], "machine": 0x8664, "timestamp": 1234,
            "imageSize": 0x4000, "declaredVersion": "7.0.0", "anchors": anchors}


def fixture_image(baseline: dict, **kwargs) -> bytes:
    options = dict(timestamp=baseline["timestamp"], image_size=baseline["imageSize"],
                   machine=baseline["machine"],
                   anchors={rva: bytes.fromhex(encoded)
                            for rva, encoded in baseline["anchors"].values()})
    options.update(kwargs)
    return synthetic_image(**options)


class PeInspectionTests(unittest.TestCase):
    def setUp(self):
        self.baseline = baseline_fixture()
        self.image = fixture_image(self.baseline)

    def test_matched_baseline(self):
        report = guard.inspect_image(self.image, self.baseline)
        self.assertTrue(report["matched"], report["reasons"])
        self.assertEqual([c["check"] for c in report["checks"]],
                         ["dosSignature", "peSignature", "machine", "timestamp", "optionalMagic", "imageSize"] + list(ANCHOR_NAMES))

    def test_unknown_timestamp_and_image_size(self):
        for changed in ({"timestamp": 99}, {"image_size": 0x8000}):
            with self.subTest(changed=changed):
                report = guard.inspect_image(fixture_image(self.baseline, **changed), self.baseline)
                self.assertFalse(report["matched"])
                self.assertEqual(len(report["reasons"]), 1)
                self.assertIn("expected %r" % self.baseline["imageSize" if "image_size" in changed else "timestamp"],
                              report["reasons"][0])

    def test_unknown_machine(self):
        report = guard.inspect_image(fixture_image(self.baseline, machine=0x14C), self.baseline)
        self.assertFalse(report["matched"])
        self.assertTrue(report["reasons"][0].startswith("machine:"), report["reasons"])

    def test_each_anchor_individually_changed(self):
        for name in ANCHOR_NAMES:
            with self.subTest(anchor=name):
                damaged = dict(self.baseline)
                anchors = dict(self.baseline["anchors"])
                rva, encoded = anchors[name]
                anchors[name] = (rva, bytes(b ^ 0xFF for b in bytes.fromhex(encoded)).hex())
                damaged["anchors"] = anchors
                report = guard.inspect_image(fixture_image(damaged), self.baseline)
                self.assertFalse(report["matched"])
                self.assertEqual([r for r in report["reasons"] if r.startswith(name + ":")], report["reasons"])
                self.assertIn("expected %r" % encoded, report["reasons"][0])

    def test_anchor_rva_outside_every_section(self):
        baseline = baseline_fixture(offset=0x4000)
        report = guard.inspect_image(fixture_image(self.baseline), baseline)
        self.assertFalse(report["matched"])
        self.assertEqual(len(report["reasons"]), 4)
        self.assertTrue(all("maps RVA" in reason for reason in report["reasons"]))

    def test_wrong_optional_header_magic(self):
        blob = bytearray(self.image)
        struct.pack_into("<H", blob, PE_OFFSET + 24, 0x10B)
        report = guard.inspect_image(blob, self.baseline)
        self.assertFalse(report["matched"])
        self.assertTrue(any(r.startswith("optionalMagic:") for r in report["reasons"]))

    def test_malformed_or_truncated_images(self):
        cases = {"empty": b"", "not-pe": b"ZZ" + bytes(70),
                 "lost-section-table": self.image[:PE_OFFSET + 24 + 0x70 + 16],
                 "short-optional-header": synthetic_image()[:PE_OFFSET + 24 + 4]}
        for label, blob in cases.items():
            with self.subTest(case=label):
                report = guard.inspect_image(blob, self.baseline)
                self.assertFalse(report["matched"])
                self.assertTrue(report["reasons"])
                self.assertTrue(any(r.startswith(("pe-header", "malformed-pe", "optionalHeader",
                                                   "sectionTable", "peSignature", "dosSignature"))
                                    for r in report["reasons"]), report["reasons"])


class ComponentCheckTests(unittest.TestCase):
    """The component functions are driven with fixture paths only."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = Path(self.folder.name)
        self.baseline = baseline_fixture()
        self.image_path = self.dir / "fixture.exe"
        self.image_path.write_bytes(fixture_image(self.baseline))
        self.ini_path = self.dir / "config.ini"
        self.ini_path.write_text("[General]\ngame_version=7.0.0\n", encoding="utf-8")
        patcher = patch.dict(guard.BASELINE["game"], self.baseline)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_game_accepts_matching_fixture(self):
        entry = guard.check_game(self.image_path, self.ini_path)
        self.assertTrue(entry["matched"], entry["reasons"])
        self.assertFalse(entry["runtimeCompatible"])
        self.assertEqual(entry["declaredVersion"], "7.0.0")
        self.assertEqual(entry["fileBytes"], self.image_path.stat().st_size)

    def test_game_declared_version_is_supplemental_only(self):
        self.ini_path.write_text("game_version=7.1.0\n", encoding="utf-8")
        entry = guard.check_game(self.image_path, self.ini_path)
        self.assertTrue(entry["matched"])
        self.assertEqual(entry["reasons"], [])
        self.assertEqual(entry["declaredVersion"], "7.1.0")
        self.assertIn("supplemental", entry["declaredVersionEvidence"])

    def test_game_missing_files_fail_closed(self):
        entry = guard.check_game(self.dir / "absent.exe", self.ini_path)
        self.assertFalse(entry["matched"])
        self.assertEqual(entry["checks"], [])
        self.assertIn("unreadable", entry["reasons"][0])

    def test_editor_hash_match_and_mismatch(self):
        dll = self.dir / "BeyondEditor.dll"
        dll.write_bytes(b"not the real assembly")
        digest = guard.digest_file(dll)
        with patch.dict(guard.BASELINE["editor"], {"label": "synthetic", "sha256": digest.upper()}):
            entry = guard.check_editor(dll)
            self.assertTrue(entry["matched"], entry["reasons"])
            self.assertEqual(entry["runtimeCompatible"], "unknown")
            self.assertFalse(entry["runtimeVerified"])
        with patch.dict(guard.BASELINE["editor"], {"sha256": "00" * 32}):
            entry = guard.check_editor(dll)
            self.assertFalse(entry["matched"])
            self.assertTrue(entry["reasons"][0].startswith("sha256:"))

    def test_editor_missing_file_fails_closed(self):
        entry = guard.check_editor(self.dir / "absent.dll")
        self.assertFalse(entry["matched"])
        self.assertIn("unreadable", entry["reasons"][0])

    def test_check_compatibility_requires_known_component(self):
        with self.assertRaises(ValueError):
            guard.check_compatibility("everything")


class RefusalTests(unittest.TestCase):
    """require_compatible and the CLI boundary, both against fixture paths."""

    def setUp(self):
        ctx = tempfile.TemporaryDirectory()
        self.addCleanup(ctx.cleanup)
        self.dir = Path(ctx.name)
        self.baseline = baseline_fixture()
        image = self.dir / "fixture.exe"
        image.write_bytes(fixture_image(self.baseline))
        ini = self.dir / "config.ini"
        ini.write_text("game_version=7.0.0\n", encoding="utf-8")
        dll = self.dir / "BeyondEditor.dll"
        dll.write_bytes(b"synthetic assembly")
        digest = guard.digest_file(dll)
        self.enter = [
            patch.object(guard, "GAME_IMAGE", image),
            patch.object(guard, "GAME_CONFIG", ini),
            patch.object(guard, "EDITOR_DLL", dll),
            patch.dict(guard.BASELINE["game"], self.baseline),
            patch.dict(guard.BASELINE["editor"], {"label": "synthetic", "sha256": digest}),
        ]
        for patcher in self.enter:
            patcher.start()
            self.addCleanup(patcher.stop)

    def break_anchor(self):
        anchors = dict(self.baseline["anchors"])
        rva, encoded = anchors["SAVE"]
        anchors["SAVE"] = (rva, bytes(b ^ 0xFF for b in bytes.fromhex(encoded)).hex())
        patcher = patch.dict(guard.BASELINE["game"], {"anchors": anchors})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_require_compatible_returns_report_for_matched_baseline(self):
        report = guard.require_compatible("all")
        self.assertTrue(report["ok"])
        self.assertEqual(report["code"], "compatible")
        self.assertEqual(set(report["components"]), {"game", "editor"})

    def test_require_compatible_raises_with_report(self):
        self.break_anchor()
        with self.assertRaises(guard.IncompatibleVersion) as caught:
            guard.require_compatible("all")
        self.assertEqual(caught.exception.code, "incompatible-version")
        self.assertEqual(caught.exception.report["code"], "incompatible-version")
        self.assertTrue(any("SAVE" in reason for reason in caught.exception.report["reasons"]))
        self.assertFalse(caught.exception.report["runtimeCompatible"])

    def test_cli_exit_codes_and_structured_json(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(guard.main(["--component", "all"]), 0)
        self.assertTrue(json.loads(stream.getvalue())["ok"])

        self.break_anchor()
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(guard.main(["--component", "all"]), 2)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["code"], "incompatible-version")
        self.assertFalse(payload["ok"])
        self.assertNotIn("Traceback", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
