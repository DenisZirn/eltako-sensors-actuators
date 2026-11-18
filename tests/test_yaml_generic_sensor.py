"""Regression checks for generic YAML sensors without a Home Assistant runtime."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest


SENSOR_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "eltako_sensors_actuators"
    / "sensor.py"
)


class _EntityStub:
    def __init__(self, gateway, device: dict[str, Any]) -> None:
        self.device_config = device
        self._attr_extra_state_attributes = {}
        self.last_state = None
        self.added_to_hass = False
        self.state_updates = 0

    async def async_added_to_hass(self) -> None:
        self.added_to_hass = True

    async def async_get_last_state(self):
        return self.last_state

    def schedule_update_ha_state(self) -> None:
        self.state_updates += 1


class _GatewayStub:
    def __init__(self) -> None:
        self.listener = None

    def register_listener(self, listener):
        self.listener = listener
        return lambda: setattr(self, "listener", None)


def _load_generic_sensor_class():
    """Execute only the generic sensor class with minimal dependency stubs."""
    source = SENSOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SENSOR_PATH))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EltakoYamlGenericSensor"
    )
    module = ast.Module(body=[cls], type_ignores=[])
    context = {
        "Any": Any,
        "EltakoYamlEntity": _EntityStub,
        "SensorEntity": type("SensorEntity", (), {}),
    }
    exec(compile(ast.fix_missing_locations(module), str(SENSOR_PATH), "exec"), context)
    return context["EltakoYamlGenericSensor"]


class GenericYamlSensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor_class = _load_generic_sensor_class()

    def make_sensor(self):
        gateway = _GatewayStub()
        sensor = self.sensor_class(gateway, {"id": "01-02-03-04", "eep": "A5-00-00"})
        return sensor, gateway

    def send(self, sensor, decoded):
        telegram = SimpleNamespace(sender_id="01-02-03-04", decoded=decoded)
        sensor._handle_telegram(telegram)

    def test_restoring_generic_sensor_does_not_need_temperature_state(self):
        sensor, _ = self.make_sensor()
        sensor.last_state = SimpleNamespace(state="42")
        self.assertFalse(hasattr(sensor, "_smooth_temperature"))
        asyncio.run(sensor.async_added_to_hass())
        self.assertTrue(sensor.added_to_hass)
        self.assertEqual(sensor.native_value, "42")

    def test_unknown_restored_state_is_ignored(self):
        for old_state in ("unknown", "unavailable", ""):
            with self.subTest(old_state=old_state):
                sensor, _ = self.make_sensor()
                sensor.last_state = SimpleNamespace(state=old_state)
                asyncio.run(sensor.async_added_to_hass())
                self.assertIsNone(sensor.native_value)

    def test_valid_zero_does_not_fall_back_to_raw(self):
        sensor, _ = self.make_sensor()
        self.send(sensor, {"value": 0, "raw": "00-00-00-00"})
        self.assertEqual(sensor.native_value, 0)
        self.assertIs(type(sensor.native_value), int)
        self.assertEqual(sensor.state_updates, 1)

    def test_false_value_does_not_fall_back_to_raw(self):
        sensor, _ = self.make_sensor()
        self.send(sensor, {"value": False, "raw": "00"})
        self.assertIs(sensor.native_value, False)

    def test_raw_fallback_is_only_for_missing_or_none_value(self):
        for decoded in (
            {"raw": "AA-BB"},
            {"value": None, "raw": "AA-BB"},
        ):
            with self.subTest(decoded=decoded):
                sensor, _ = self.make_sensor()
                self.send(sensor, decoded)
                self.assertEqual(sensor.native_value, "AA-BB")

    def test_unrelated_telegram_does_not_change_value(self):
        sensor, _ = self.make_sensor()
        self.send(sensor, {"value": 3})
        sensor._handle_telegram(
            SimpleNamespace(sender_id="AA-BB-CC-DD", decoded={"value": 7})
        )
        self.assertEqual(sensor.native_value, 3)
        self.assertEqual(sensor.state_updates, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
