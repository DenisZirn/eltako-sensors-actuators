"""Focused runtime regressions for FHK61U/FHK61SSR without physical devices.

The actual entity methods are compiled from the integration source, with only
the Home Assistant framework replaced by tiny test stand-ins. These tests
verify correct routing, payload validation and status attribution, not
physical RF reception or actual switching hardware.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "eltako_sensors_actuators"


def _source_function(file: str, name: str, *, cls: str | None = None, globals=None):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    body = tree.body
    if cls is not None:
        body = next(node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls)
    node = next(node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    code = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), file, "exec")
    namespace = {"Any": object, "datetime": datetime, "timezone": timezone, **(globals or {})}
    exec(code, namespace)
    return namespace[name]


class Fhk61ModelRoutingTests(unittest.TestCase):
    def test_pwm_only_exists_for_explicit_ssr_number_profile(self):
        checker = _source_function(
            "gateway.py", "_is_fhk_pwm_device",
            globals={
                "_device_name_upper": lambda d: str(d.get("device_type") or "").upper(),
                "_device_raw_option": lambda d, key: d.get(key),
            },
        )
        correct = {"device_type": "FHK61SSR-230V", "platform": "number",
                   "eep": "A5-38-08", "pwm_mode": "direct"}
        self.assertTrue(checker(correct, "A5-38-08", "A5-38-08"))
        self.assertFalse(checker({**correct, "platform": "climate"}, "A5-38-08", "A5-38-08"))
        self.assertFalse(checker({**correct, "pwm_mode": "temperature"}, "A5-38-08", "A5-38-08"))
        self.assertFalse(checker({**correct, "eep": "A5-10-06"}, "A5-10-06", "A5-10-06"))
        self.assertFalse(checker({**correct, "device_type": "FHK61U-230V"}, "A5-38-08", "A5-38-08"))

        entity_profile = _source_function(
            "number.py", "_is_fhk61ssr_pwm",
            globals={
                "normalize_platform": lambda p: str(p or "").lower(),
                "normalize_eep": lambda e: str(e or "").upper(),
            },
        )
        self.assertTrue(entity_profile(correct))
        self.assertFalse(entity_profile({**correct, "eep": "A5-10-06"}))
        self.assertFalse(entity_profile({**correct, "platform": "climate"}))


class Fhk61URelayRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = staticmethod(_source_function(
            "binary_sensor.py", "_handle_telegram", cls="EltakoFhk61URelayFeedback"
        ))

    def test_relay_ack_requires_real_actor_and_model_specific_decode(self):
        changed = []
        entity = SimpleNamespace(
            device_config={"id": "05-85-CB-83"}, _attr_is_on=None,
            async_write_ha_state=lambda: changed.append(True),
        )

        def telegram(physical, *, command_echo=False, feedback=None):
            return SimpleNamespace(
                sender_id="05-85-CB-83",  # logical ID may be misleading
                decoded={
                    "physical_sender_id": physical,
                    "tx_echo": command_echo,
                    **(feedback or {}),
                },
            )

        on = {"fhk61_feedback_type": "relay", "fhk61_relay_on": True}
        off = {"fhk61_feedback_type": "relay", "fhk61_relay_on": False}
        self.handler(entity, telegram("FF-A6-04-81", feedback=on))
        self.assertIsNone(entity._attr_is_on)
        self.handler(entity, telegram("05-85-CB-83", command_echo=True, feedback=on))
        self.assertIsNone(entity._attr_is_on)
        self.handler(entity, telegram("05-85-CB-83", feedback={"button_action": 0x70}))
        self.assertIsNone(entity._attr_is_on)
        self.handler(entity, telegram("05-85-CB-83", feedback=on))
        self.assertTrue(entity._attr_is_on)
        self.handler(entity, telegram("05-85-CB-83", feedback=off))
        self.assertFalse(entity._attr_is_on)
        self.assertEqual(len(changed), 2)


class Fhk61SSRPwmRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.handler = staticmethod(_source_function(
            "number.py", "_handle_telegram", cls="EltakoFhk61SsrPwm"
        ))

    def _entity(self, wanted=45):
        state_changes = []
        entity = SimpleNamespace(
            device_config={"id": "05-85-CB-83"},
            _period_seconds=120, _repeater_enabled=False,
            _last_requested_percent=wanted, _last_send_success=True,
            _last_command_confirmed=False,
            _last_feedback_percent=None, _last_feedback_period=None,
            _last_feedback_time=None, _last_feedback_pwm_enabled=None,
            _last_feedback_repeater=None, _last_feedback_sender_id=None,
            _dewpoint_input_active=None, _dewpoint_last_seen=None,
            async_write_ha_state=lambda: state_changes.append(True),
        )
        return entity, state_changes

    @staticmethod
    def _telegram(data="02-2D-0C-09", physical="05-85-CB-83", org="0x07",
                  feedback_type=None, **extra):
        decoded = {
            "physical_sender_id": physical, "data_hex": data,
            "org": org, **extra,
        }
        if feedback_type is not None:
            decoded["fhk61_feedback_type"] = feedback_type
        return SimpleNamespace(sender_id="05-85-CB-83", decoded=decoded)

    def test_outgoing_controller_echo_is_never_a_physical_confirmation(self):
        entity, updates = self._entity()
        self.handler(entity, self._telegram(physical="FF-A6-04-81"))
        self.assertFalse(entity._last_command_confirmed)
        self.assertIsNone(entity._last_feedback_percent)
        self.assertEqual(len(updates), 0)

    def test_actual_actor_echo_confirms_matching_pwm_and_period(self):
        entity, updates = self._entity()
        self.handler(entity, self._telegram())
        self.assertEqual(entity._last_feedback_percent, 45)
        self.assertEqual(entity._last_feedback_period, 120)
        self.assertTrue(entity._last_feedback_pwm_enabled)
        self.assertFalse(entity._last_feedback_repeater)
        self.assertTrue(entity._last_command_confirmed)
        self.assertEqual(len(updates), 1)

    def test_unrelated_reply_does_not_confirm_requested_pwm(self):
        entity, updates = self._entity()
        self.handler(entity, self._telegram(data="02-1E-0C-09"))
        self.assertEqual(entity._last_feedback_percent, 30)
        self.assertFalse(entity._last_command_confirmed)

    def test_disabled_zero_percent_is_a_valid_confirmed_command(self):
        entity, updates = self._entity(wanted=0)
        self.handler(entity, self._telegram(data="02-00-0C-08"))
        self.assertEqual(entity._last_feedback_percent, 0)
        self.assertFalse(entity._last_feedback_pwm_enabled)
        self.assertTrue(entity._last_command_confirmed)

    def test_invalid_db0_and_tx_echo_are_ignored(self):
        entity, updates = self._entity()
        self.handler(entity, self._telegram(data="02-2D-0C-0F"))
        self.handler(entity, self._telegram(tx_echo=True))
        self.assertIsNone(entity._last_feedback_percent)
        self.assertEqual(len(updates), 0)

    def test_dewpoint_rps_does_not_change_pwm(self):
        entity, updates = self._entity()
        self.handler(entity, self._telegram(
            data="70-00-00-00", org="0x05", feedback_type="dewpoint_input",
            fhk61_dewpoint_input_active=True,
        ))
        self.assertTrue(entity._dewpoint_input_active)
        self.assertIsNone(entity._last_feedback_percent)
        self.assertFalse(entity._last_command_confirmed)
        self.assertEqual(len(updates), 1)


if __name__ == "__main__":
    unittest.main()
