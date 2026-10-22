import unittest

import skill_button as button


class SkillButtonTests(unittest.TestCase):
    def test_independent_native_tag_fixture(self):
        # Tag bytes are independently transcribed from current writer13177580.
        data = bytes.fromhex("a81f01 b01f02 b81f03 c01f04 c81f05 d51f0000403f d81f01 e01f01 ea1f020801 f01f06 f81f07 8220020802 88201b 902008")
        expected = {501: 1, 502: 2, 503: 3, 504: 4, 505: 5, 506: 0.75, 507: True, 508: True, 509: b"\x08\x01", 510: 6, 511: 7, 512: b"\x08\x02", 513: 27, 514: 8}
        self.assertEqual(button.decode(data), expected)
        self.assertEqual(button.encode(expected), data)

    def test_signed_int32_native_sign_extension(self):
        data = bytes.fromhex("8820ffffffffffffffffff01")
        self.assertEqual(button.decode(data), {513: -1})
        self.assertEqual(button.encode({513: -1}), data)

    def test_reject_malformed_or_unproved_schema(self):
        for data in [bytes.fromhex(x) for x in ("882080", "8a2000", "882001882002", "982001", "ea1f040801", "8820ffffffff0f", "d81f02")]:
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                button.decode(data)

    def test_native_zeros_omitted_but_empty_messages_retained(self):
        self.assertEqual(button.encode({501: 0, 506: 0.0, 507: False, 509: b""}), bytes.fromhex("ea1f00"))

    def test_z_is_not_unity_keycode(self):
        for value in (0, 2, 27, 42, 60, 61, 122, True):
            with self.assertRaises(ValueError):
                button.keyboard_configuration_recipe(value, "Z", "readback.json")
        for key, source in (("F", "readback.json"), ("Z", "")):
            with self.assertRaises(ValueError):
                button.keyboard_configuration_recipe(27, key, source)
        recipe = button.z_configuration_recipe("z-selector-proof.json")
        self.assertEqual(recipe["keyboardEvidence"]["selector"], 26)
        self.assertEqual(recipe["keyboardEvidence"]["inputEventId"], 5508)
        self.assertFalse(recipe["dispatchable"])
        self.assertTrue(recipe["componentOnly"])

    def test_z_changes_only_keyboard_selector(self):
        source = {501: 1, 502: 2, 513: 27, 514: 1, 509: b"\x08\x01"}
        result = button.with_z_binding(source)
        self.assertEqual(result, {**source, 513: 26})
        self.assertEqual(source[513], 27)
        self.assertEqual(button.encode({513: 26}), bytes.fromhex("88201a"))

    def test_encode_range_type_checks(self):
        for values in ({999: 0}, {513: 2**31}, {513: True}, {504: -1}, {507: 1}, {509: "00"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                button.encode(values)

    def test_interaction_mode_and_keyboard_fixture(self):
        values = button.with_z_interaction({501: 1, 503: 3, 513: 27})
        self.assertEqual(values, {501: 1, 503: 2, 513: 26})
        self.assertEqual(button.encode({503: 2, 513: 26}), bytes.fromhex("b81f0288201a"))
        recipe = button.interaction_configuration_recipe("z-selector-proof.json", "interaction-mode-proof.json")
        self.assertEqual(recipe["nativeComponentKind"], 22)
        self.assertEqual(recipe["steps"][0]["rva"], "0x10616220")
        self.assertFalse(recipe["dispatchable"])


if __name__ == "__main__":
    unittest.main()
