"""Hardware-independent regressions for A5-10-06 priorities and FHK61 PWM."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_fks_sv_room_temperature import INTEGRATION, eep10, _load, PKG
from test_climate_temperature_sync import make_climate, priority


class ControllerEchoRoutingTests(unittest.TestCase):
    def test_own_sender_echo_is_not_actuator_feedback(self):
        source = (INTEGRATION / "gateway.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(x for x in tree.body if isinstance(x, ast.FunctionDef)
                    and x.name == "_is_a5_10_06_controller_echo")
        ns = {
            "Any": object,
            "normalize_eep": lambda val: str(val).upper(),
            "ORG_4BS": 0x07,
            "_normalized_address_or_none": lambda val: str(val).upper() if val else None,
            "_get_sender_id": lambda d: d.get("sender_id"),
            "_effective_sender_id_for_gateway": lambda sender, *args, **kwargs: sender,
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                     str(INTEGRATION / "gateway.py"), "exec"), ns)
        classify = ns["_is_a5_10_06_controller_echo"]
        device = {"platform": "climate", "eep": "A5-10-06",
                  "id": "05-85-CB-83", "sender_id": "FF-A6-04-81"}
        self.assertTrue(classify(device, "FF-A6-04-81", "fam-usb",
                                 "FF-A6-04-80", org=0x07))
        self.assertFalse(classify(device, "05-85-CB-83", "fam-usb",
                                  "FF-A6-04-80", org=0x07))
        self.assertFalse(classify(device, "FF-A6-04-81", "fam-usb",
                                  "FF-A6-04-80", org=0x05))
        self.assertFalse(classify({**device, "eep": "A5-38-08"},
                                  "FF-A6-04-81", "fam-usb", "FF-A6-04-80", org=0x07))


class PriorityTests(unittest.TestCase):
    def device(self, device_type="F4HK14", **extra):
        return {
            "platform": "climate", "eep": "A5-10-06",
            "id": "FF-BF-5C-C0", "sender_id": "FF-A6-04-C0",
            "device_type": device_type,
            **extra,
        }

    def test_mode_is_independent_of_climate_presets(self):
        d = self.device(heating_control_mode="learned_sensor")
        options = {"heating_priority_overrides": {"FF-BF-5C-C0": "central"}}
        self.assertEqual(priority.priority_mode(d, options), "central")
        self.assertEqual(priority.PRIORITY_BYTES["central"], 0x08)
        self.assertEqual(priority.PRIORITY_BYTES["auto"], 0x0E)
        self.assertEqual(priority.PRIORITY_BYTES["limit"], 0x0A)

    def test_external_function64_keeps_standard_auto(self):
        d = self.device(heating_control_mode="ha_external", priority="ha")
        opts = {"heating_priority_overrides": {"FF-BF-5C-C0": "central"}}
        self.assertEqual(priority.priority_mode(d, opts), "auto")

    def test_priorities_exclude_fhk61_and_pwm(self):
        self.assertFalse(priority.supports_heating_priority(self.device("FHK61U-230V")))
        self.assertFalse(priority.supports_heating_priority({
            **self.device("FHK61SSR-230V"),
            "platform": "number", "eep": "A5-38-08", "pwm_mode": "direct",
        }))

    def test_a5_10_06_priority_encoder(self):
        for mode, byte in (("ha", 0x08), ("auto", 0x0E), ("limit", 0x0A)):
            data = eep10.encode_a5_10_06_room_control_data(
                target_temperature=20.0, current_temperature=None, priority=mode,
            )
            self.assertEqual(len(data), 4)
            self.assertEqual(data[3], byte)
            self.assertEqual(data[1], 127)
            self.assertEqual(data[2], 0)

    def test_manual_suppresses_temperature_push(self):
        e, gateway, hass = make_climate("F4HK14", source="internal")
        e.hass.options["heating_priority_overrides"] = {"01-02-03-04": "manual"}
        e._schedule_a5_10_06_room_temperature_push()
        self.assertFalse(e._room_temperature_push_pending)
        self.assertFalse(gateway.calls)

    def test_per_channel_priority_is_independent(self):
        d1 = self.device()
        d2 = self.device(id="FF-BF-5C-C1", sender_id="FF-A6-04-C1")
        opts = {"heating_priority_overrides": {"FF-BF-5C-C0": "central", "FF-BF-5C-C1": "limit"}}
        self.assertEqual(priority.priority_mode(d1, opts), "central")
        self.assertEqual(priority.priority_mode(d2, opts), "limit")


def _gateway_builder():
    source = (INTEGRATION / "gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(x for x in tree.body if isinstance(x, ast.FunctionDef)
                and x.name == "_build_actuator_message")
    code = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                   str(INTEGRATION / "gateway.py"), "exec")
    ns = {
        "Any": object, "UnsupportedEltakoCommand": ValueError,
        "_get_sender_id": lambda d: d.get("sender_id"),
        "_get_sender_eep": lambda d: d.get("sender_eep") or "A5-10-06",
        "_effective_sender_id_for_gateway": lambda sender, *args, **kw: sender,
        "_is_fhk_pwm_device": lambda d, s, e: "FHK61SSR" in d.get("device_type", ""),
        "parse_address": lambda sender: sender,
        "format_address": lambda sender: sender,
        "build_regular_4bs": lambda sender, data, **kw: (sender, bytes(data), kw.get("status")),
    }
    exec(code, ns)
    return ns["_build_actuator_message"]


class GatewayTelegramTests(unittest.TestCase):
    def test_manual_release_payload_sender_status(self):
        builder = _gateway_builder()
        payload = builder({
            "platform": "climate", "eep": "A5-10-06", "sender_id": "FF-A6-04-C0",
        }, "release_heating_priority")
        self.assertEqual(payload, ("FF-A6-04-C0", bytes.fromhex("00 00 00 0E"), 0x80))

    def test_pwm_remains_separate_and_validated(self):
        builder = _gateway_builder()
        d = {"platform": "number", "device_type": "FHK61SSR-230V", "eep": "A5-38-08", "sender_id": "FF-A6-04-C2"}
        self.assertEqual(
            builder(d, "fhk61ssr_pwm", percentage=38, period_seconds=120),
            ("FF-A6-04-C2", bytes.fromhex("02 26 0C 09"), 0x80),
        )
        with self.assertRaises(ValueError):
            builder(d, "fhk61ssr_pwm", percentage=101, period_seconds=120)
        with self.assertRaises(ValueError):
            builder(d, "fhk61ssr_pwm", percentage=50, period_seconds=125)


if __name__ == "__main__":
    unittest.main()
