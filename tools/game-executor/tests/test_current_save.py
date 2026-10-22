"""Tests for current-save.py.

The tool reads real save stores, so the tests do not touch the machine's data:
read_profile() is driven against a synthetic .gip built here, and render() is
driven against plain dicts.

  python -m unittest discover -s tools/game-executor/tests -p "test_current_save.py"
"""
from __future__ import annotations

import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "beyond-save"))
from gil_container import (  # noqa: E402
    Container, Field, WIRE_LENGTH, WIRE_VARINT, encode_container, encode_fields,
)

spec = importlib.util.spec_from_file_location(
    "current_save", ROOT / "tools/game-executor/current-save.py")
current_save = importlib.util.module_from_spec(spec)
spec.loader.exec_module(current_save)


def build_gip(entries: list[tuple[int, str]]) -> bytes:
    """A minimal player profile: repeated field 2 {1: level_id, 2: name}."""
    fields = []
    for level_id, name in entries:
        inner = encode_fields([
            Field(1, WIRE_VARINT, value=level_id),
            Field(2, WIRE_LENGTH, data=name.encode("utf-8")),
        ])
        fields.append(Field(2, WIRE_LENGTH, data=inner))
    return encode_container(Container(subtype=1, payload=encode_fields(fields)))


class ProfileReading(unittest.TestCase):
    def test_reads_ids_and_names_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid = pathlib.Path(tmp)
            (uid / current_save.PROFILE_FILE).write_bytes(
                build_gip([(1073741842, "自定义页签_5_存档"), (1073741841, "第66.x的笔_存档_1")]))
            rows, err = current_save.read_profile(uid)
            self.assertIsNone(err)
            self.assertEqual([r["levelId"] for r in rows], [1073741842, 1073741841])
            self.assertEqual(rows[0]["name"], "自定义页签_5_存档")
            self.assertEqual(rows[1]["name"], "第66.x的笔_存档_1")

    def test_missing_file_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows, err = current_save.read_profile(pathlib.Path(tmp))
            self.assertEqual(rows, [])
            self.assertIsNotNone(err)

    def test_unparsable_file_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            uid = pathlib.Path(tmp)
            (uid / current_save.PROFILE_FILE).write_bytes(b"\xff\xff\xff\xff not a container")
            rows, err = current_save.read_profile(uid)
            self.assertEqual(rows, [])
            self.assertIsNotNone(err)


class AgeFormatting(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(current_save.human_age(None), "unknown")
        self.assertEqual(current_save.human_age(30), "30s ago")
        self.assertEqual(current_save.human_age(600), "10min ago")
        self.assertEqual(current_save.human_age(7200), "2.0h ago")
        self.assertEqual(current_save.human_age(3 * 86400), "3.0d ago")


class Rendering(unittest.TestCase):
    def base(self) -> dict:
        return {
            "measuredAt": "2026-10-08T23:00:00+0800",
            "locallow": r"C:\x\LocalLow\miHoYo",
            "accounts": [],
            "activeUid": None,
            "skippedStoreDirs": 0,
            "lastNativeObservation": None,
            "helper": None,
            "staleMinutes": 60,
        }

    def test_no_accounts_says_so(self):
        text = current_save.render(self.base())
        self.assertIn("NONE", text)

    def test_no_native_observation_says_level_is_unknown(self):
        data = self.base()
        data["accounts"] = [{"uid": "1", "levels": [], "profileError": None,
                             "newestWrite": None, "path": "p", "game": "g"}]
        data["activeUid"] = None
        text = current_save.render(data)
        self.assertIn("UNKNOWN", text)

    def test_stale_observation_is_marked_stale(self):
        data = self.base()
        data["lastNativeObservation"] = {
            "run": "r", "levelId": 42, "entities": 3, "action": "inspect",
            "ageSeconds": 3 * 3600,
        }
        text = current_save.render(data)
        self.assertIn("STALE", text)
        self.assertIn("42", text)

    def test_fresh_observation_is_marked_fresh(self):
        data = self.base()
        data["lastNativeObservation"] = {
            "run": "r", "levelId": 7, "entities": 1, "action": "inspect",
            "ageSeconds": 5,
        }
        self.assertIn("fresh", current_save.render(data))


if __name__ == "__main__":
    unittest.main(verbosity=2)
