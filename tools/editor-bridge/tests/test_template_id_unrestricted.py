#!/usr/bin/env python3
"""A create accepts any uint32 templateId -- and no whitelist may creep back.

Replaces test_template_whitelist_agrees.py and test_creature_whitelist_agrees.py, which
asserted that three hand-maintained 51-id copies stayed identical. The user removed that
mechanism on 2026-10-09: the editor's catalog reports 2722 prefabs, and 693 CLI journal
claims (109 creates, 51 distinct ids) show nothing outside those 51 had ever been sent --
the list measured itself, not the sandbox.

What has to stay true now:

  1. the three files that used to hold a copy hold NO copy any more;
  2. an id that was never in any whitelist is ACCEPTED at every layer that used to refuse
     it -- the queue client, the compiler and the CLI's placement normaliser;
  3. a value that is not a uint32 is still REFUSED.  A guard that accepts everything is not
     the same as no guard, and this file would be worthless if it could not tell them apart.

Usage:  python -B -m unittest tools.editor-bridge.tests.test_template_id_unrestricted
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PROFILE = ROOT / "tools/game-executor/build_scene_profile.py"
CLIENT = ROOT / "tools/editor-bridge/elevated-request.py"
RUNNER = ROOT / "tools/editor-bridge/elevated-runner.ps1"

#: 20001965 土田 -- a real catalogue entry that was never in any whitelist copy.
NEVER_WHITELISTED = 20001965
#: 20001001 乔木 -- a real catalogue entry that WAS in the old list.
FORMERLY_WHITELISTED = 20001001

#: The assignment forms that must not reappear in any of the three files.
FORBIDDEN = (
    ("elevated-request.py", CLIENT, "NATIVE_TEMPLATES = frozenset(("),
    ("elevated-request.py", CLIENT, "NATIVE_CREATURE_TEMPLATES = frozenset(("),
    ("build_scene_profile.py", PROFILE, "TEMPLATES = frozenset(("),
    ("build_scene_profile.py", PROFILE, "CATALOGUE_SAMPLE_20260928 = frozenset(("),
    ("build_scene_profile.py", PROFILE, "CREATURE_TEMPLATES = "),
    ("elevated-runner.ps1", RUNNER, "$templateWhitelist = [uint32[]]@("),
    ("elevated-runner.ps1", RUNNER, "$creatureTemplateWhitelist = [uint32[]]@("),
)


def _load(name: str, relpath: pathlib.Path):
    sibling = str(relpath.parent)
    if sibling not in sys.path:
        sys.path.insert(0, sibling)
    spec = importlib.util.spec_from_file_location(name, relpath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class NoWhitelistCopyRemains(unittest.TestCase):
    def test_no_assignment_survives_in_any_layer(self):
        for label, path, needle in FORBIDDEN:
            self.assertNotIn(needle, path.read_text(encoding="utf-8"),
                             f"{label} still assigns a template whitelist: {needle}")

    def test_no_membership_test_survives(self):
        """The refusal codes the whitelist threw must be gone too."""
        for label, path, needle in (("client", CLIENT, "NATIVE_SCENE_TEMPLATE_INVALID"),
                                    ("runner", RUNNER, "NATIVE_SCENE_TEMPLATE_NOT_ALLOWED")):
            self.assertNotIn(needle, path.read_text(encoding="utf-8"),
                             f"{label} still refuses on template membership: {needle}")

    def test_the_profile_still_exposes_a_range_check(self):
        profile = _load("_t_tid_profile", PROFILE)
        self.assertTrue(callable(profile.is_template_id))
        self.assertTrue(profile.is_template_id(FORMERLY_WHITELISTED))
        self.assertTrue(profile.is_template_id(NEVER_WHITELISTED))


class PlacementNormaliser(unittest.TestCase):
    def setUp(self):
        self.scene_cli = _load("_t_tid_cli", ROOT / "tools/game-executor/scene_cli.py")

    def _spec(self, template_id):
        return {"template_id": template_id, "position": [1, 2, 3], "scale": [1, 1, 1]}

    def test_an_id_never_in_any_whitelist_is_accepted(self):
        row = self.scene_cli.normalize_placement(self._spec(NEVER_WHITELISTED), 0)
        self.assertEqual(row["template_id"], NEVER_WHITELISTED)

    def test_a_formerly_whitelisted_id_is_still_accepted(self):
        row = self.scene_cli.normalize_placement(self._spec(FORMERLY_WHITELISTED), 0)
        self.assertEqual(row["template_id"], FORMERLY_WHITELISTED)

    def test_non_uint32_values_are_still_refused(self):
        for bad in (0, -1, 2 ** 32, True, 1.5, "20001965", None):
            with self.assertRaises(ValueError, msg=f"{bad!r} should be refused"):
                self.scene_cli.normalize_placement(self._spec(bad), 0)


class QueueClientAcceptance(unittest.TestCase):
    """The queue client gates a create on the wire; it must accept the same ids."""

    @classmethod
    def setUpClass(cls):
        cls.client = _load("_t_tid_client", CLIENT)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.runtime_root = ROOT / ".runtime/_tid_test_evidence"
        cls.runtime_root.mkdir(parents=True, exist_ok=True)
        cls.session = cls.runtime_root / "session.json"
        cls.review = cls.runtime_root / "review.json"
        cls.session.write_text(json.dumps({"fixture": "session"}), encoding="utf-8")
        cls.review.write_text(json.dumps({"fixture": "review"}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        for path in (cls.session, cls.review):
            path.unlink(missing_ok=True)
        try:
            cls.runtime_root.rmdir()
        except OSError:
            pass

    def _payload(self, action, template_id):
        return {"kind": "native-scene", "action": action,
                "sessionPath": str(self.session), "levelId": 1073741842,
                "reviewPath": str(self.review), "templateId": template_id,
                "position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}

    def test_create_accepts_an_id_never_in_any_whitelist(self):
        out = self.client.validate_native_scene_request(self._payload("create", NEVER_WHITELISTED))
        self.assertEqual(out["templateId"], NEVER_WHITELISTED)

    def test_creature_create_accepts_the_same_id(self):
        out = self.client.validate_native_scene_request(
            self._payload("creature-create", NEVER_WHITELISTED))
        self.assertEqual(out["templateId"], NEVER_WHITELISTED)

    def test_a_non_uint32_is_still_refused_on_the_wire(self):
        for bad in (0, -1, 2 ** 32, True, 1.5):
            with self.assertRaises(ValueError, msg=f"{bad!r} should be refused"):
                self.client.validate_native_scene_request(self._payload("create", bad))


if __name__ == "__main__":
    unittest.main(verbosity=2)
