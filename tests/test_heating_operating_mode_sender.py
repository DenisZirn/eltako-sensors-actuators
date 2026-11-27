"""Series-14 FG4/F30 and 61-series separately taught RPS operating modes.

All tests use the actual integration encoder. The isolated gateway-builder
harness checks source-code routing without requiring a Home Assistant runtime.
"""
from __future__ import annotations

import unittest
import ast

from test_fks_sv_room_temperature import INTEGRATION, PKG, _load, eep10
from test_restore_fhk14_f4hk14_fae14 import _builder

operating_mode = _load(
    f"{PKG}.bus.operating_mode", INTEGRATION / "bus" / "operating_mode.py"
)


class OperatingModeSenderRegressionTests(unittest.TestCase):
    def test_mode_sender_is_independent_of_a5_temperature_sender(self):
        build = _builder()
        for model in ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR"):
            with self.subTest(model=model):
                device = {
                    "id": "FF-BF-5C-C0", "platform": "climate", "eep": "A5-10-06",
                    "sender_eep": "A5-10-06", "device_type": model,
                    "sender_id": "FF-A6-04-C0",
                    "operating_mode_sender_id": "FF-A6-04-C1",
                }
                sender, data = build(
                    device, "set_temperature", temperature=22.5,
                    current_temperature=20.5, heater_mode="normal"
                )
                self.assertEqual(sender, "FF-A6-04-C0")
                self.assertEqual(data["target_temperature"], 22.5)
                self.assertEqual(data["current_temperature"], 20.5)
                self.assertEqual(
                    build(device, "set_preset_mode", preset_mode="night"),
                    ("rps", "FF-A6-04-C1", "night"),
                )
                self.assertEqual(
                    build(device, "set_hvac_mode", hvac_mode="off"),
                    ("rps", "FF-A6-04-C1", "off"),
                )

    def test_legacy_yaml_without_separate_mode_sender_keeps_old_sender(self):
        build = _builder()
        device = {
            "id": "FF-BF-5C-C0", "platform": "climate", "eep": "A5-10-06",
            "sender_eep": "A5-10-06", "device_type": "F4HK14",
            "sender_id": "FF-A6-04-C0",
        }
        self.assertEqual(
            build(device, "set_preset_mode", preset_mode="setback"),
            ("rps", "FF-A6-04-C0", "setback")
        )

    def test_raw_yaml_operating_sender_supported(self):
        device = {
            "platform": "climate", "eep": "A5-10-06",
            "device_type": "FHK14", "raw": {
                "operating_mode_sender_id": "ff-a6-04-88"
            }
        }
        self.assertEqual(
            operating_mode.configured_operating_mode_sender(device, "FF-A6-04-C0"),
            "FF-A6-04-88",
        )

    def test_fhk61_temperature_variants_have_separate_mode_learning(self):
        for model in ("FHK61-230V", "FHK61U-230V", "FHK61SSR-230V"):
            with self.subTest(model=model):
                device = {
                    "platform": "climate", "eep": "A5-10-06",
                    "device_type": model, "control_mode": "temperature",
                    "sender_id": "FF-A6-04-81",
                }
                self.assertEqual(
                    operating_mode.heating_operating_mode_family(device), "fhk61"
                )
                self.assertEqual(
                    operating_mode.configured_operating_mode_sender(
                        device, device["sender_id"]
                    ), "FF-A6-04-81"
                )

    def test_fhk61_operating_mode_learn_uses_separate_sender(self):
        tree = ast.parse((INTEGRATION / "gateway.py").read_text(encoding="utf-8"))
        full = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name == "_build_actuator_message"
        )
        learn = next(
            node for node in full.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "command == 'fhk61_teach_in_operating_mode'"
        )
        isolated = ast.FunctionDef(
            name=full.name, args=full.args, body=[*full.body[:6], learn],
            decorator_list=[], returns=full.returns, type_comment=None,
        )
        ns = {
            "Any": object,
            "_get_sender_id": lambda d: d.get("sender_id"),
            "_get_sender_eep": lambda d: d.get("sender_eep", "A5-10-06"),
            "heating_operating_mode_family": operating_mode.heating_operating_mode_family,
            "configured_operating_mode_sender": operating_mode.configured_operating_mode_sender,
            "_effective_sender_id_for_gateway": lambda sender, *a, **kw: sender,
            "build_fhk_mode_command": eep10.build_fhk_mode_command,
            "build_rps": eep10.build_rps,
            "parse_address": eep10.parse_address,
            "UnsupportedEltakoCommand": ValueError,
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])),
                     "gateway.py", "exec"), ns)
        for model in ("FHK61-230V", "FHK61U-230V", "FHK61SSR-230V"):
            with self.subTest(model=model):
                d = {
                    "platform": "climate", "eep": "A5-10-06",
                    "device_type": model, "sender_id": "FF-A6-04-81",
                    "operating_mode_sender_id": "FF-A6-04-82",
                    "control_mode": "temperature",
                }
                telegrams = ns["_build_actuator_message"](
                    d, "fhk61_teach_in_operating_mode"
                )
                self.assertEqual(len(telegrams), 2)
                for telegram, data_byte, status in zip(
                    telegrams, (0x70, 0x00), (0x30, 0x20)
                ):
                    self.assertEqual(telegram.body[0], 0x6B)
                    self.assertEqual(telegram.body[1], 0x05)
                    self.assertEqual(telegram.body[2:6], bytes((data_byte, 0, 0, 0)))
                    self.assertEqual(telegram.body[6:10], bytes.fromhex("FF A6 04 82"))
                    self.assertEqual(telegram.body[10], status)

    def test_ssr_direct_pwm_excluded_from_rps_temperature_mode(self):
        device = {
            "platform": "climate", "eep": "A5-10-06",
            "device_type": "FHK61SSR-230V",
            "control_mode": "direct_pwm",
        }
        self.assertIsNone(operating_mode.heating_operating_mode_family(device))

    def test_exact_rps_operating_codes_and_no_4bs_priority_overlap(self):
        for mode, code in (
            ("normal", 0x70),
            ("night", 0x50),
            ("setback", 0x30),
            ("off", 0x10),
        ):
            with self.subTest(mode=mode):
                telegram = eep10.build_fhk_mode_command("FF-A6-04-C0", mode)
                body = telegram.body
                self.assertEqual(body[1], 0x05)  # RPS
                self.assertEqual(body[2], code)
                self.assertEqual(body[3:6], bytes(3))
                self.assertEqual(body[6:10], bytes.fromhex("FF A6 04 C0"))
                self.assertEqual(body[10], 0x30)

    def test_unrelated_climate_actors_are_not_reclassified(self):
        for model in ("FKS-SV", "FTR55", "FRGBW14", "FHK61SSR-230V"):
            device = {"platform": "light" if model == "FRGBW14" else "climate",
                      "eep": "A5-20-01" if model == "FKS-SV" else "A5-10-06",
                      "device_type": model}
            if model == "FHK61SSR-230V":
                device["control_mode"] = "direct_pwm"
            self.assertIsNone(operating_mode.heating_operating_mode_family(device))


if __name__ == "__main__":
    unittest.main()
