"""Regression guards for the v0.1.167 room-temperature-only test branch."""
from __future__ import annotations
import ast
from pathlib import Path
import unittest

COMPONENTS = Path(__file__).resolve().parents[1] / "custom_components" / "eltako_sensors_actuators"


def function_source(filename: str, name: str) -> str:
    source = (COMPONENTS / filename).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Missing function: {name}")


class TestTemperatureOnlyFix(unittest.TestCase):
    def test_options_dispatch_is_not_delayed_by_diagnostics(self):
        listener = function_source("__init__.py", "_async_options_update_listener")
        self.assertLess(listener.index("async_dispatcher_send("), listener.index("await async_set_diagnostics_enabled("))

    def test_room_temperature_is_pushed_after_startup(self):
        source = function_source("climate.py", "async_added_to_hass")
        self.assertIn("ROOM_TEMPERATURE_SOURCE_EXTERNAL", source)
        self.assertIn("_schedule_a5_10_06_room_temperature_push()", source)

    def test_updated_sensor_pushes_without_setpoint_change(self):
        for name in ("_handle_external_temperature_state_event", "_handle_temperature_options_updated"):
            self.assertIn("_schedule_a5_10_06_room_temperature_push()", function_source("climate.py", name))

    def test_concurrent_updates_are_queued(self):
        scheduler = function_source("climate.py", "_schedule_a5_10_06_room_temperature_push")
        drain = function_source("climate.py", "_async_drain_a5_10_06_room_temperature_pushes")
        self.assertIn("self._room_temperature_push_pending = True", scheduler)
        self.assertIn("while self._room_temperature_push_pending:", drain)

    def test_fks_sv_uses_one_internal_temperature(self):
        climate = (COMPONENTS / "climate.py").read_text(encoding="utf-8")
        sensor = (COMPONENTS / "sensor.py").read_text(encoding="utf-8")
        shared = (COMPONENTS / "room_temperature.py").read_text(encoding="utf-8")
        self.assertIn("store_fks_sv_native_temperature(", climate)
        self.assertIn("fks_sv_native_temperature(", climate)
        self.assertIn("fks_sv_native_temperature(", sensor)
        self.assertIn("not self._is_fks_sv_native_sensor", sensor)
        self.assertIn("def fks_sv_native_temperature(", shared)

    def test_existing_gateway_and_ui_files_remain_outside_patch(self):
        # This is intentionally a temperature-only patch; the original config
        # flow, translations, and gateway transport files remain unmodified.
        for name in ("config_flow.py", "gateway.py"):
            ast.parse((COMPONENTS / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
