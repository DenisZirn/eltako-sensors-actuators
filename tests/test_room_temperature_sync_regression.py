"""Static regression checks for room-temperature synchronization.

These guards deliberately avoid importing Home Assistant so they can run with
the repository's existing unittest test environment.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "custom_components" / "eltako_sensors_actuators"


def method(name: str, source_file: str = "climate.py") -> str:
    source = (COMPONENTS / source_file).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{name} not found")


class TestRoomTemperatureSync(unittest.TestCase):
    def test_initial_external_temperature_is_transmitted(self):
        source = method("async_added_to_hass")
        self.assertIn("ROOM_TEMPERATURE_SOURCE_EXTERNAL", source)
        self.assertIn("_schedule_a5_10_06_room_temperature_push()", source)

    def test_external_source_updates_schedule_push_without_setpoint_change(self):
        for name in (
            "_handle_external_temperature_state_event",
            "_handle_temperature_options_updated",
        ):
            self.assertIn(
                "_schedule_a5_10_06_room_temperature_push()",
                method(name),
            )

    def test_inflight_updates_are_not_dropped(self):
        scheduler = method("_schedule_a5_10_06_room_temperature_push")
        drain = method("_async_drain_a5_10_06_room_temperature_pushes")
        self.assertIn("self._room_temperature_push_pending = True", scheduler)
        self.assertIn("while self._room_temperature_push_pending", drain)
        self.assertIn("self._room_temperature_push_pending = False", drain)
        self.assertIn("await self._async_push_a5_10_06_room_temperature()", drain)

    def test_shared_fks_native_value_between_climate_and_sensor(self):
        climate = (COMPONENTS / "climate.py").read_text(encoding="utf-8")
        sensor = (COMPONENTS / "sensor.py").read_text(encoding="utf-8")
        shared = (COMPONENTS / "room_temperature.py").read_text(encoding="utf-8")
        self.assertIn("store_fks_sv_native_temperature(", climate)
        self.assertIn("fks_sv_native_temperature(", climate)
        self.assertIn("fks_sv_native_temperature(", sensor)
        self.assertIn("fks_sv_native_temperature_signal(", sensor)
        self.assertIn("def store_fks_sv_native_temperature(", shared)

    def test_native_fks_sensor_does_not_use_ema(self):
        source = method("__init__", "sensor.py")
        # Find the value sensor's constructor, not another sensor subclass.
        tree = ast.parse((COMPONENTS / "sensor.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "EltakoYamlValueSensor")
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name == "__init__")
        text = ast.get_source_segment(
            (COMPONENTS / "sensor.py").read_text(encoding="utf-8"), init
        ) or ""
        self.assertIn("not is_fks_sv_device(device)", text)


if __name__ == "__main__":
    unittest.main()
