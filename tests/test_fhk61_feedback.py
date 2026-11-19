"""Regression tests for model-specific FHK61 feedback interpretation."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "eltako_sensors_actuators"
MODULE = INTEGRATION / "bus" / "fhk61_feedback.py"
SPEC = importlib.util.spec_from_file_location("fhk61_feedback_test", MODULE)
assert SPEC is not None and SPEC.loader is not None
feedback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feedback)


class Fhk61FeedbackRegression(unittest.TestCase):
    def test_fhk61_rps_50_is_night_setback_not_relay_off(self):
        result = feedback.decode_fhk61_rps_feedback(bytes.fromhex("50 00 00 00"), "FHK61-230V")
        self.assertEqual(result["fhk61_feedback_type"], "operating_mode")
        self.assertEqual(result["fhk61_mode"], "night_setback")
        self.assertNotIn("fhk61_relay_on", result)

    def test_fhk61u_rps_50_is_relay_off(self):
        result = feedback.decode_fhk61_rps_feedback(bytes.fromhex("50 00 00 00"), "FHK61U-230V")
        self.assertEqual(result["fhk61_feedback_type"], "relay")
        self.assertFalse(result["fhk61_relay_on"])

    def test_fhk61u_rps_70_is_relay_on(self):
        result = feedback.decode_fhk61_rps_feedback(bytes.fromhex("70 00 00 00"), "FHK61U-230V")
        self.assertTrue(result["fhk61_relay_on"])

    def test_fhk61_normal_setback_and_off(self):
        for byte, mode in ((0x70, "normal"), (0x30, "setback"), (0x10, "off")):
            with self.subTest(byte=byte):
                data = bytes((byte, 0, 0, 0))
                self.assertEqual(
                    feedback.decode_fhk61_rps_feedback(data, "FHK61-230V")["fhk61_mode"],
                    mode,
                )

    def test_unrelated_devices_and_invalid_payloads(self):
        self.assertEqual(
            feedback.decode_fhk61_rps_feedback(bytes.fromhex("50 00 00 00"), "FHK14"), {},
        )
        self.assertEqual(
            feedback.decode_fhk61_rps_feedback(bytes.fromhex("50 11 00 00"), "FHK61-230V"), {},
        )

    def test_climate_does_not_erase_rps_mode_from_repeated_4bs(self):
        tree = ast.parse((INTEGRATION / "climate.py").read_text(encoding="utf-8"))
        cls = next(item for item in tree.body if isinstance(item, ast.ClassDef)
                   and item.name == "EltakoClimate")
        handler = next(item for item in cls.body if isinstance(item, ast.FunctionDef)
                       and item.name == "_handle_telegram")
        source = ast.unparse(handler)
        self.assertIn("decoded.get('fhk61_feedback_type')", source)
        self.assertIn("decoded.get('org') == '0x07'", source)
        self.assertIn("self._fhk61_reported_mode = mode", source)


if __name__ == "__main__":
    unittest.main()
