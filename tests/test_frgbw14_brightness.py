"""Regression tests: Series-14 RGBW brightness must not decay on color changes.

The tests execute the real feedback method and decoder using stdlib-only AST
extraction. This keeps them runnable without a Home Assistant installation.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "eltako_sensors_actuators"


def _load_method(module_name: str, class_name: str, method_name: str, globals_: dict):
    tree = ast.parse((ROOT / module_name).read_text(encoding="utf-8"))
    parent = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in parent.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    namespace = dict(globals_)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), module_name, "exec"), namespace)
    method = namespace[method_name]
    return method.fget if isinstance(method, property) else method


def _load_function(module_name: str, function_name: str, globals_: dict):
    tree = ast.parse((ROOT / module_name).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function_name)
    namespace = dict(globals_)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), module_name, "exec"), namespace)
    return namespace[function_name]


_is_frgbw14 = _load_function("light.py", "_is_frgbw14_device", {"Any": Any})
_feedback_handler = _load_method(
    "light.py",
    "EltakoLight",
    "_handle_telegram",
    {
        "decode_actuator_feedback": lambda _device, decoded, _sender: decoded,
        "_is_rgbw_device": lambda d: d.get("eep") == "07-3F-7F",
        "_is_frgbw14_device": _is_frgbw14,
    },
)
_decode_4bs = _load_function("bus/decoder.py", "_decode_4bs", {"Any": Any})
_rgb_color = _load_method("light.py", "EltakoLight", "rgb_color", {"_is_frgbw14_device": _is_frgbw14})


class DummyLight:
    _handle_telegram = _feedback_handler
    rgb_color = property(_rgb_color)

    def __init__(self, device_type: str, brightness: int = 240):
        self.device_config = {"device_type": device_type, "eep": "07-3F-7F"}
        self._rgbw_color = (255, 0, 0, 0)
        self._frgbw_base_rgbw = (255, 0, 0, 0)
        self._brightness = brightness
        self._is_on = True
        self.updates = 0

    def schedule_update_ha_state(self):
        self.updates += 1

    def receive(self, component: str, value: int):
        self._handle_telegram(
            SimpleNamespace(decoded={"component": component, "component_value": value}, sender_id="FF-BF-5C-A3")
        )


class FRGBW14BrightnessTests(unittest.TestCase):
    def test_frgbw14_color_is_not_scaled_twice_in_ha(self):
        light = DummyLight("FRGBW14", 128)
        light._rgbw_color = (128, 0, 0, 0)  # actual visible channel value
        light._frgbw_base_rgbw = (255, 0, 0, 0)  # unscaled HA color
        self.assertEqual(light.rgb_color, (255, 0, 0))
        self.assertEqual(light._brightness, 128)

    def test_frgbw14_color_feedback_cannot_override_ha_base_color(self):
        light = DummyLight("FRGBW14", 128)
        light._rgbw_color = (128, 0, 0, 0)
        light._frgbw_base_rgbw = (255, 0, 0, 0)
        light.receive("red", 0)
        light.receive("green", 128)
        light.receive("blue", 0)
        self.assertEqual(light.rgb_color, (255, 0, 0))
        self.assertEqual(light._brightness, 128)

    def test_frgbw71l_still_reports_visible_color(self):
        light = DummyLight("FRGBW71L", 128)
        light._rgbw_color = (128, 0, 0, 0)
        self.assertEqual(light.rgb_color, (128, 0, 0))

    def test_component_feedback_does_not_dim_global_brightness(self):
        light = DummyLight("FRGBW14", 240)
        for _ in range(3):
            # Change from red to green, then to blue. A 0 value from the first
            # channel is not a global dimmer command.
            for component, value in (
                ("red", 0), ("green", 190), ("blue", 0),
                ("green", 0), ("blue", 255), ("red", 0),
                ("blue", 0), ("red", 240), ("green", 0),
            ):
                light.receive(component, value)
                self.assertEqual(light._brightness, 240)
                self.assertTrue(light._is_on)
        self.assertEqual(light.updates, 27)

    def test_real_dimmer_brightness_feedback_remains_supported(self):
        light = DummyLight("FRGBW14", 240)
        light._handle_telegram(
            SimpleNamespace(decoded={"brightness": 128, "state": True}, sender_id="FF-BF-5C-A3")
        )
        self.assertEqual(light._brightness, 128)

    def test_frgbw71l_existing_component_behavior_is_unchanged(self):
        light = DummyLight("FRGBW71L", 240)
        light.receive("red", 0)
        self.assertEqual(light._brightness, 0)

    def test_identification_uses_device_type_without_name(self):
        self.assertTrue(_is_frgbw14({"device_type": "FRGBW14", "name": "Wohnzimmer"}))
        self.assertFalse(_is_frgbw14({"device_type": "FRGBW71L", "name": "Wohnzimmer"}))

    def test_free_profile_controller_is_not_misdecoded_as_dimmer_status(self):
        packet = bytes.fromhex("02 00 10 0F")
        decoded = _decode_4bs(packet, "07-3F-7F")
        self.assertEqual(decoded["telegram_type"], "frgbw_controller")
        self.assertEqual(decoded["component"], "red")
        self.assertNotIn("brightness", decoded)

    def test_free_profile_confirmation_is_not_misdecoded_as_dimmer_status(self):
        packet = bytes.fromhex("02 00 11 0E")
        decoded = _decode_4bs(packet, "07-3F-7F")
        self.assertEqual(decoded["telegram_type"], "frgbw_confirmation")
        self.assertEqual(decoded["component"], "green")
        self.assertNotIn("brightness", decoded)

    def test_func38_dimmer_feedback_still_decodes(self):
        packet = bytes.fromhex("02 32 00 09")
        decoded = _decode_4bs(packet, "07-3F-7F")
        self.assertEqual(decoded["telegram_type"], "frgbw_dimmer_status")
        self.assertEqual(decoded["dimmer_percent"], 50)


if __name__ == "__main__":
    unittest.main()
