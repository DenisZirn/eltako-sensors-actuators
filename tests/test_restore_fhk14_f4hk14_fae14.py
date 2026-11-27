"""Guard the proven Series-14 heating path against FHK61/priority changes.

These tests execute the real A5-10-06 encoder and extract the live gateway
builder. They are not physical hardware tests.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from test_fks_sv_room_temperature import INTEGRATION, eep10, const, PKG, _load

operating_mode = _load(f"{PKG}.bus.operating_mode", INTEGRATION / "bus" / "operating_mode.py")


def _builder():
    tree = ast.parse((INTEGRATION / "gateway.py").read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_build_actuator_message")
    # Exercise the actual climate branch with its exact sender/data arguments.
    # Avoid unrelated switch/cover/RGBW guards that precede it in the full
    # builder and are outside this test's purpose.
    # Only the first six assignments initialize the builder context.
    # A later sender_id re-assignment depends on unrelated gateway code.
    setup = node.body[:6]
    assert all(isinstance(stmt, ast.Assign) for stmt in setup)
    climate = next(
        stmt for stmt in node.body
        if isinstance(stmt, ast.If)
        and ast.unparse(stmt.test) == "platform == 'climate'"
    )
    isolated = ast.FunctionDef(
        name=node.name, args=node.args, body=[*setup, climate],
        decorator_list=[], returns=node.returns, type_comment=None,
    )
    ns = {
        "Any": object,
        "UnsupportedEltakoCommand": ValueError,
        "_get_sender_id": lambda d: d.get("sender_id"),
        "_get_sender_eep": lambda d: d.get("sender_eep", "A5-10-06"),
        "_effective_sender_id_for_gateway": lambda sender, *a, **kw: sender,
        "format_address": lambda addr: addr,
        "parse_address": lambda addr: addr,
        "is_fhk61_230v_temperature_profile": eep10.is_fhk61_230v_temperature_profile,
        "heating_operating_mode_family": operating_mode.heating_operating_mode_family,
        "configured_operating_mode_sender": operating_mode.configured_operating_mode_sender,
        "build_a5_10_06_room_control": lambda sender, **kwargs: (sender, kwargs),
        "build_fhk_mode_command": lambda sender, mode: ("rps", sender, mode),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])),
                 "gateway.py", "exec"), ns)
    return ns["_build_actuator_message"]


class Series14CompatibilityTests(unittest.TestCase):
    def test_select_restored_without_fhk61_priority_override(self):
        self.assertIn("select", const.PLATFORMS)
        climate_source = (INTEGRATION / "climate.py").read_text(encoding="utf-8")
        self.assertIn("_priority_manual_active", climate_source)
        self.assertNotIn("controller_priority=self._heating_controller_priority()", climate_source)

    def test_gateway_preserves_setpoint_room_temperature_and_priority_for_14_series(self):
        build = _builder()
        for model in ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR"):
            with self.subTest(model=model):
                d = {
                    "platform": "climate", "eep": "A5-10-06",
                    "sender_eep": "A5-10-06", "sender_id": "FF-A6-04-C1",
                    "id": "FF-BF-5C-C1", "device_type": model,
                    "priority": "ha",
                }
                sender, kw = build(d, "set_temperature",
                                   temperature=24, current_temperature=21.3,
                                   heater_mode="normal")
                self.assertEqual(sender, "FF-A6-04-C1")
                self.assertEqual(kw["current_temperature"], 21.3)
                self.assertEqual(kw["target_temperature"], 24)
                self.assertEqual(kw["hvac_mode"], "normal")
                self.assertEqual(kw["priority"], "ha")
                self.assertIsNone(kw["controller_profile"])
                data = eep10.encode_a5_10_06_room_control_data(
                    target_temperature=kw["target_temperature"],
                    current_temperature=kw["current_temperature"],
                    hvac_mode=kw["hvac_mode"],
                    priority=kw["priority"],
                    controller_profile=kw["controller_profile"],
                )
                self.assertEqual(data, bytes.fromhex("70 99 77 08"))

    def test_four_f4hk14_channels_remain_independent(self):
        build = _builder()
        for idx in range(4):
            d = {
                "platform": "climate", "eep": "A5-10-06",
                "sender_eep": "A5-10-06", "sender_id": f"FF-A6-04-C{idx}",
                "device_type": "F4HK14",
            }
            sender, kw = build(d, "set_temperature", temperature=20 + idx,
                               current_temperature=19 + idx, heater_mode="normal")
            self.assertEqual(sender, f"FF-A6-04-C{idx}")
            self.assertEqual(kw["target_temperature"], 20 + idx)
            self.assertEqual(kw["current_temperature"], 19 + idx)

    def test_hvac_and_preset_commands_preserve_rps_path(self):
        build = _builder()
        d = {
            "platform": "climate", "eep": "A5-10-06",
            "sender_eep": "A5-10-06", "sender_id": "FF-A6-04-C1",
            "device_type": "FHK14",
        }
        self.assertEqual(build(d, "set_hvac_mode", hvac_mode="off"),
                         ("rps", "FF-A6-04-C1", "off"))
        self.assertEqual(build(d, "set_preset_mode", preset_mode="night"),
                         ("rps", "FF-A6-04-C1", "night"))

    def test_fhk61_uses_separate_mini_safe_controller_profile(self):
        build = _builder()
        d = {
            "platform": "climate", "eep": "A5-10-06",
            "sender_eep": "A5-10-06", "sender_id": "FF-A6-04-81",
            "device_type": "FHK61-230V",
        }
        sender, kw = build(d, "set_temperature", temperature=30, current_temperature=21.3)
        self.assertEqual(kw["controller_profile"], "fhk61_230v")
        self.assertIsNone(kw["current_temperature"])
        self.assertEqual(eep10.encode_a5_10_06_room_control_data(
            target_temperature=kw["target_temperature"],
            current_temperature=kw["current_temperature"],
            controller_profile=kw["controller_profile"],
        ), bytes.fromhex("00 BF 00 0E"))


if __name__ == "__main__":
    unittest.main()
