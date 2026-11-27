"""Regression coverage for temperature-source entity choices.

Offline entities retain device_class/unit metadata in Home Assistant; the
selection flow must require a *valid* current value as well.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from test_fks_sv_room_temperature import INTEGRATION, room


def _load_filter():
    source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {"_is_temperature_entity_compatible", "_temperature_entity_choices"}
    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in funcs} == names
    ns = {"temperature_to_celsius": room.temperature_to_celsius, "_BACK": "__back__"}
    exec(compile(ast.fix_missing_locations(ast.Module(body=funcs, type_ignores=[])),
                 "config_flow.py", "exec"), ns)
    return ns["_is_temperature_entity_compatible"], ns["_temperature_entity_choices"]


compatible, choices = _load_filter()


class _FakeStates:
    def __init__(self, records):
        self.records = records

    def get(self, entity_id):
        return self.records.get(entity_id)

    def async_all(self, domain):
        assert domain == "sensor"
        return list(self.records.values())


def _state(entity_id, value, *, unit="°C", device_class="temperature", friendly_name=None):
    return SimpleNamespace(
        entity_id=entity_id,
        state=value,
        attributes={
            "unit_of_measurement": unit,
            "device_class": device_class,
            "friendly_name": friendly_name or entity_id,
        },
    )


class TemperatureAvailabilityTests(unittest.TestCase):
    def setUp(self):
        records = {
            "sensor.ok": _state("sensor.ok", "20.1"),
            "sensor.fahrenheit": _state("sensor.fahrenheit", "68", unit="°F", device_class=None),
            "sensor.unavailable": _state("sensor.unavailable", "unavailable"),
            "sensor.unknown": _state("sensor.unknown", "unknown"),
            "sensor.none": _state("sensor.none", "None"),
            "sensor.nan": _state("sensor.nan", "nan"),
            "sensor.inf": _state("sensor.inf", "inf"),
            "sensor.empty": _state("sensor.empty", ""),
            "sensor.invalid": _state("sensor.invalid", "not-a-number"),
            "sensor.out_of_range": _state("sensor.out_of_range", "86"),
            "sensor.counter": _state("sensor.counter", "22", unit="kWh", device_class=None),
            "sensor.no_metadata": _state("sensor.no_metadata", "22", unit="", device_class=None),
            "sensor.minimum": _state("sensor.minimum", "-15"),
            "sensor.maximum": _state("sensor.maximum", "40"),
        }
        self.hass = SimpleNamespace(
            states=_FakeStates(records),
            config=SimpleNamespace(language="de"),
        )

    def test_only_usable_temperatures_are_selectable(self):
        expected = {"sensor.ok", "sensor.fahrenheit", "sensor.minimum", "sensor.maximum"}
        options = choices(self.hass)
        self.assertEqual(set(options) - {"__back__"}, expected)
        self.assertIn("Zurück", options["__back__"])
        for entity_id in expected:
            self.assertTrue(compatible(self.hass, entity_id))
        for entity_id in set(self.hass.states.records) - expected:
            self.assertFalse(compatible(self.hass, entity_id))

    def test_missing_and_non_sensor_ids_rejected(self):
        self.assertFalse(compatible(self.hass, "sensor.absent"))
        self.assertFalse(compatible(self.hass, "switch.ok"))


if __name__ == "__main__":
    unittest.main()
