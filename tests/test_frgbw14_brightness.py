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
        "_LOGGER": SimpleNamespace(debug=lambda *_args, **_kwargs: None),
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
    def test_blue_favorite_does_not_set_brightness_to_red_channel(self):
        light = DummyLight("FRGBW14", 255)
        # Home Assistant's default blue favorite is not pure blue:
        # rgb_color=(127, 172, 255), without an explicit brightness value.
        # The red channel is about 49.8%; a misleading partial feedback
        # must not replace the independent global brightness.
        light._rgbw_color = (127, 172, 255, 0)
        light._frgbw_base_rgbw = (127, 172, 255, 0)
        for _ in range(20):
            for component, value in (
                ("red", 127), ("green", 172), ("blue", 255),
            ):
                light.receive(component, value)
            decoded = _decode_4bs(bytes.fromhex("02 31 00 09"), "07-3F-7F")
            self.assertEqual(decoded["dimmer_percent"], 49)
            light._handle_telegram(
                SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3")
            )
            self.assertEqual(light._brightness, 255)
            self.assertTrue(light._is_on)

    def test_logged_frgbw14_status_values_do_not_move_global_slider(self):
        light = DummyLight("FRGBW14", 180)
        # Actual captured packets from 18 Nov. Each reported dim level
        # follows the RED channel, even seconds after a color change.
        for raw, percent in (
            ("02 31 00 09", 49),
            ("02 2F 00 09", 47),
            ("02 60 00 09", 96),
            ("02 64 00 09", 100),
            ("02 2B 00 09", 43),
            ("02 1B 00 09", 27),
            ("02 09 00 09", 9),
            ("02 19 00 09", 25),
        ):
            decoded = _decode_4bs(bytes.fromhex(raw), "07-3F-7F")
            self.assertEqual(decoded["telegram_type"], "frgbw_dimmer_status")
            self.assertEqual(decoded["dimmer_percent"], percent)
            light._handle_telegram(
                SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3")
            )
            self.assertEqual(light._brightness, 180)
            self.assertTrue(light._is_on)
        self.assertEqual(light.updates, 0)

    def test_frgbw14_red_channel_zero_does_not_turn_blue_light_off(self):
        light = DummyLight("FRGBW14", 255)
        light._rgbw_color = (0, 0, 255, 0)
        light._frgbw_base_rgbw = (0, 0, 255, 0)
        # A hypothetical red-channel status of zero is not global OFF.
        decoded = _decode_4bs(bytes.fromhex("02 00 00 08"), "07-3F-7F")
        self.assertFalse(decoded["state"])
        light._handle_telegram(
            SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3")
        )
        self.assertEqual(light._brightness, 255)
        self.assertTrue(light._is_on)
        self.assertEqual(light.rgb_color, (0, 0, 255))

    def test_physical_rgb_channel_status_is_combined_without_dimming(self):
        light = DummyLight("FRGBW14", 255)
        light.device_config["id"] = "FF-BF-5C-A3"
        light._frgbw_channel_percent = [None, None, None]
        # White from MiniSafe: physical A3/A4/A5 each report 100%.
        for address in ("FF-BF-5C-A3", "FF-BF-5C-A4", "FF-BF-5C-A5"):
            decoded = _decode_4bs(bytes.fromhex("02 64 00 09"), "07-3F-7F")
            decoded["physical_sender_id"] = address
            light._handle_telegram(SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3"))
        self.assertEqual(light.rgb_color, (255, 255, 255))
        self.assertEqual(light._brightness, 255)
        # Physical green-only state: R=0, G=100, B=0.
        for address, raw in (
            ("FF-BF-5C-A3", "02 00 00 08"),
            ("FF-BF-5C-A4", "02 64 00 09"),
            ("FF-BF-5C-A5", "02 00 00 08"),
        ):
            decoded = _decode_4bs(bytes.fromhex(raw), "07-3F-7F")
            decoded["physical_sender_id"] = address
            light._handle_telegram(SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3"))
        self.assertEqual(light.rgb_color, (0, 255, 0))
        self.assertTrue(light._is_on)
        self.assertEqual(light._brightness, 255)

    def test_partial_channel_feedback_never_zeros_ha_brightness(self):
        light = DummyLight("FRGBW14", 175)
        light.device_config["id"] = "FF-BF-5C-A3"
        light._frgbw_channel_percent = [None, None, None]
        decoded = _decode_4bs(bytes.fromhex("02 00 00 08"), "07-3F-7F")
        decoded["physical_sender_id"] = "FF-BF-5C-A4"
        light._handle_telegram(SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3"))
        self.assertTrue(light._is_on)
        self.assertEqual(light._brightness, 175)

    def test_controller_tx_echo_does_not_override_selected_color(self):
        light = DummyLight("FRGBW14", 255)
        light.device_config["id"] = "FF-BF-5C-A3"
        light._rgbw_color = (0, 255, 0, 0)
        light._frgbw_base_rgbw = (0, 255, 0, 0)
        echo = _decode_4bs(bytes.fromhex("03 FF 12 0F"), "07-3F-7F")
        echo["physical_sender_id"] = "FF-A6-04-A3"
        light._handle_telegram(SimpleNamespace(decoded=echo, sender_id="FF-BF-5C-A3"))
        self.assertEqual(light.rgb_color, (0, 255, 0))
        self.assertEqual(light._brightness, 255)

    def test_frgbw14_other_brightness_feedback_still_supported(self):
        light = DummyLight("FRGBW14", 255)
        light._handle_telegram(
            SimpleNamespace(
                decoded={"brightness": 128, "state": True, "telegram_type": "actual_brightness"},
                sender_id="FF-BF-5C-A3",
            )
        )
        self.assertEqual(light._brightness, 128)

    def test_frgbw71l_dimmer_status_behavior_is_unchanged(self):
        light = DummyLight("FRGBW71L", 255)
        decoded = _decode_4bs(bytes.fromhex("02 31 00 09"), "07-3F-7F")
        light._handle_telegram(
            SimpleNamespace(decoded=decoded, sender_id="FF-BF-5C-A3")
        )
        self.assertEqual(light._brightness, 125)

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

    def test_generic_brightness_feedback_remains_supported(self):
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
