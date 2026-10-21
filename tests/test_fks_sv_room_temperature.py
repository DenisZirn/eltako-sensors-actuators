from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "eltako_sensors_actuators"
PKG = "eltako_test"


def _package(name: str, path: Path) -> None:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_package(PKG, INTEGRATION)
_package(f"{PKG}.bus", INTEGRATION / "bus")
const = _load(f"{PKG}.const", INTEGRATION / "const.py")
_load(f"{PKG}.bus.exceptions", INTEGRATION / "bus" / "exceptions.py")
_load(f"{PKG}.bus.ids", INTEGRATION / "bus" / "ids.py")
_load(f"{PKG}.bus.esp2", INTEGRATION / "bus" / "esp2.py")
room = _load(f"{PKG}.room_temperature", INTEGRATION / "room_temperature.py")
eep20 = _load(f"{PKG}.bus.eep_a5_20_01", INTEGRATION / "bus" / "eep_a5_20_01.py")
eep10 = _load(f"{PKG}.bus.eep_a5_10_06", INTEGRATION / "bus" / "eep_a5_10_06.py")


class TestAssignableClimateDevices(unittest.TestCase):
    def setUp(self):
        self.fks = {
            "platform": "climate",
            "id": "01-02-03-04",
            "eep": "A5-20-01",
            "name": "Wohnzimmer Ventil",
            "device_type": "FKS-SV",
        }

    def climate(self, device_type: str, eep: str = "A5-10-06"):
        return {
            "platform": "climate",
            "id": "01-02-03-05",
            "eep": eep,
            "name": "Frei benannter Heizkreis",
            "device_type": device_type,
        }

    def test_fks_sv_is_assignable(self):
        self.assertTrue(room.is_room_temperature_assignable_device(self.fks))
        self.assertEqual(room.room_temperature_device_kind(self.fks), "fks_sv")

    def test_fhk14_f4hk14_and_fae14_are_assignable(self):
        for device_type in ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR"):
            with self.subTest(device_type=device_type):
                device = self.climate(device_type)
                self.assertTrue(room.is_room_temperature_assignable_device(device))
                self.assertEqual(room.room_temperature_device_kind(device), "a5_10_06")

    def test_room_controllers_are_excluded(self):
        for device_type in ("FUTH55", "FUTH55ED", "FTR55ESB", "FTR65DSB"):
            with self.subTest(device_type=device_type):
                self.assertFalse(
                    room.is_room_temperature_assignable_device(
                        self.climate(device_type)
                    )
                )

    def test_wrong_platform_or_eep_is_excluded(self):
        self.assertFalse(
            room.is_room_temperature_assignable_device(
                {**self.climate("FHK14"), "platform": "sensor"}
            )
        )
        self.assertFalse(
            room.is_room_temperature_assignable_device(
                self.climate("FHK14", "A5-10-12")
            )
        )

    def test_legacy_fks_sv_without_device_type_still_works(self):
        legacy = dict(self.fks)
        legacy.pop("device_type")
        self.assertTrue(room.is_fks_sv_device(legacy))
        legacy["room_controller_mode"] = "fks_kp"
        self.assertFalse(room.is_fks_sv_device(legacy))


class TestPersistenceAndPriority(unittest.TestCase):
    def setUp(self):
        self.device = {
            "platform": "climate",
            "id": "01-02-03-04",
            "eep": "A5-20-01",
            "name": "Wohnzimmer",
            "device_type": "FKS-SV",
            "room_temperature_entity": "sensor.yaml_temperature",
        }
        self.other = {
            "platform": "climate",
            "id": "01-02-03-05",
            "eep": "A5-10-06",
            "name": "Heizkreis",
            "device_type": "FHK14",
        }

    def test_normalize_physical_id(self):
        self.assertEqual(room.normalize_enocean_id("01:02:03:04"), "01-02-03-04")
        self.assertIsNone(room.normalize_enocean_id("bad-id"))

    def test_ui_external_overrides_yaml(self):
        source, entity, origin = room.resolve_room_temperature_config(self.device, {})
        self.assertEqual(
            (source, entity, origin),
            (const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.yaml_temperature", "yaml"),
        )
        options = room.set_room_temperature_override(
            {"diagnostics_enabled": True},
            self.device["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.ui_temperature",
        )
        self.assertEqual(
            room.resolve_room_temperature_config(self.device, options),
            (const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.ui_temperature", "ui"),
        )
        self.assertTrue(options["diagnostics_enabled"])

    def test_explicit_native_overrides_yaml_external(self):
        options = room.set_room_temperature_override(
            {},
            self.device["id"],
            const.ROOM_TEMPERATURE_SOURCE_NATIVE,
        )
        self.assertEqual(
            room.resolve_room_temperature_config(self.device, options),
            (const.ROOM_TEMPERATURE_SOURCE_NATIVE, None, "ui"),
        )

    def test_multiple_device_mappings_are_independent(self):
        options = room.set_room_temperature_override(
            {},
            self.device["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.wohnzimmer",
        )
        options = room.set_room_temperature_override(
            options,
            self.other["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.heizkreis",
        )
        self.assertEqual(
            room.resolve_room_temperature_config(self.device, options)[1],
            "sensor.wohnzimmer",
        )
        self.assertEqual(
            room.resolve_room_temperature_config(self.other, options)[1],
            "sensor.heizkreis",
        )

    def test_mapping_survives_json_roundtrip_and_rename(self):
        options = room.set_room_temperature_override(
            {},
            self.other["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.heizkreis",
        )
        restored = json.loads(json.dumps(options))
        renamed = {**self.other, "name": "Komplett anderer Anzeigename"}
        self.assertEqual(
            room.resolve_room_temperature_config(renamed, restored),
            (const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.heizkreis", "ui"),
        )

    def test_yaml_reimport_style_update_preserves_override(self):
        options = room.set_room_temperature_override(
            {"yaml_config": "old"},
            self.other["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.heizkreis",
        )
        after_import = dict(options)
        after_import.update({"yaml_config": "new", "devices": [self.other]})
        self.assertEqual(
            room.resolve_room_temperature_config(self.other, after_import)[1],
            "sensor.heizkreis",
        )

    def test_first_fks_only_test_mapping_is_migrated(self):
        old_options = {
            "fks_sv_room_temperature_overrides": {
                "01-02-03-04": {
                    "fks_sv_temperature_source": "external",
                    "fks_sv_external_temperature_entity": "sensor.alt",
                }
            }
        }
        self.assertEqual(
            room.resolve_room_temperature_config(self.device, old_options),
            (const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.alt", "ui"),
        )
        migrated = room.set_room_temperature_override(
            old_options,
            self.device["id"],
            const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.neu",
        )
        self.assertNotIn("fks_sv_room_temperature_overrides", migrated)
        self.assertIn(const.CONF_ROOM_TEMPERATURE_OVERRIDES, migrated)


class TestTemperatureValidationAndFksFallback(unittest.TestCase):
    def test_celsius_and_fahrenheit(self):
        self.assertEqual(room.temperature_to_celsius("21.5", "°C"), 21.5)
        self.assertEqual(room.temperature_to_celsius("68", "°F"), 20.0)
        self.assertEqual(room.temperature_to_celsius(0, "°C"), 0.0)

    def test_invalid_values_are_rejected(self):
        for value, unit in [
            ("unknown", "°C"),
            ("unavailable", "°C"),
            ("nan", "°C"),
            (math.inf, "°C"),
            (-0.1, "°C"),
            (40.1, "°C"),
            (293.15, "K"),
        ]:
            with self.subTest(value=value, unit=unit):
                self.assertIsNone(room.temperature_to_celsius(value, unit))

    def test_fks_external_fallback_and_recovery(self):
        source = const.ROOM_TEMPERATURE_SOURCE_EXTERNAL
        self.assertEqual(
            room.select_numeric_room_temperature(source, 22.1, 20.0),
            (22.1, "normal", const.ROOM_TEMPERATURE_SOURCE_EXTERNAL),
        )
        self.assertEqual(
            room.select_numeric_room_temperature(source, None, 20.0),
            (20.0, "fallback", const.ROOM_TEMPERATURE_SOURCE_NATIVE),
        )
        self.assertEqual(
            room.select_numeric_room_temperature(source, 22.4, 20.0),
            (22.4, "normal", const.ROOM_TEMPERATURE_SOURCE_EXTERNAL),
        )
        self.assertEqual(
            room.select_numeric_room_temperature(source, None, None),
            (None, "error", None),
        )


class TestA52001Encoding(unittest.TestCase):
    def test_inverse_db2_encoding(self):
        data = eep20.encode_a5_20_01_temperature_setpoint_data(
            target_temperature=20.0,
            room_temperature=20.0,
        )
        self.assertEqual(data, bytes((0x80, 0x7F, 0x04, 0x08)))
        self.assertEqual(
            eep20.encode_a5_20_01_temperature_setpoint_data(
                target_temperature=20.0,
                room_temperature=40.0,
            )[1],
            0x00,
        )
        self.assertEqual(
            eep20.encode_a5_20_01_temperature_setpoint_data(
                target_temperature=20.0,
                room_temperature=0.0,
            )[1],
            0xFF,
        )

    def test_missing_room_temperature_cannot_encode(self):
        for value in (None, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    eep20.encode_a5_20_01_temperature_setpoint_data(
                        target_temperature=20.0,
                        room_temperature=value,
                    )

    def test_db2_zero_decodes_as_40_degrees(self):
        decoded = eep20.decode_a5_20_01_controller_telegram(
            bytes((0x80, 0x00, 0x04, 0x08))
        )
        self.assertEqual(decoded["room_temperature_command"], 40.0)


class TestA51006Encoding(unittest.TestCase):
    def test_external_room_temperature_is_encoded_in_db1(self):
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=20.0,
            current_temperature=20.0,
            hvac_mode="heat",
        )
        self.assertEqual(data[0], 0x70)
        self.assertEqual(data[1], 0x7F)
        self.assertEqual(data[2], 0x7F)
        self.assertEqual(data[3], 0x0E)

    def test_native_source_preserves_existing_db1_zero_path(self):
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=20.0,
            current_temperature=None,
            hvac_mode="heat",
        )
        self.assertEqual(data[2], 0x00)
        self.assertEqual(data[3], 0x0E)

    def test_existing_priority_is_not_changed_by_external_temperature(self):
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=21.0,
            current_temperature=22.0,
            hvac_mode="heat",
            priority=0x08,
        )
        self.assertEqual(data[3], 0x08)

    def test_builder_matches_pure_encoder(self):
        expected = eep10.encode_a5_10_06_room_control_data(
            target_temperature=21.0,
            current_temperature=22.0,
            hvac_mode="heat",
        )
        message = eep10.build_a5_10_06_room_control(
            "00-00-B0-01",
            target_temperature=21.0,
            current_temperature=22.0,
            hvac_mode="heat",
        )
        self.assertEqual(message.body[2:6], expected)


class TestStaticIntegrationGuards(unittest.TestCase):
    def _function_source(self, path: Path, function_name: str) -> str:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                return ast.get_source_segment(source, node) or ""
        self.fail(f"Function {function_name} not found in {path}")

    def test_manifest_is_test_version(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.1.164")

    def test_options_flow_is_generalized(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('"room_temperature_assignment"', source)
        self.assertIn("is_room_temperature_assignable_device", source)
        self.assertIn("set_room_temperature_override", source)
        self.assertIn("EntitySelector", source)

    def test_room_temperature_menu_one_click_navigation(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        source_method = self._function_source(INTEGRATION / "config_flow.py", "async_step_room_temperature_source")
        self.assertIn("self.async_show_menu(", source_method)
        self.assertIn('"room_temperature_source_native"', source_method)
        self.assertIn('"room_temperature_source_external"', source_method)
        self.assertIn('"room_temperature_back_actuators"', source_method)
        self.assertIn("✓ ", source_method)
        self.assertNotIn("self.async_show_form(", source_method)

        save_native = self._function_source(INTEGRATION / "config_flow.py", "async_step_room_temperature_source_native")
        self.assertIn("set_room_temperature_override(", save_native)
        self.assertIn("ROOM_TEMPERATURE_SOURCE_NATIVE", save_native)
        open_external = self._function_source(INTEGRATION / "config_flow.py", "async_step_room_temperature_source_external")
        self.assertIn("async_step_room_temperature_entity()", open_external)
        back = self._function_source(INTEGRATION / "config_flow.py", "async_step_room_temperature_back_actuators")
        self.assertIn("async_step_room_temperature_assignment()", back)
        sensor = self._function_source(INTEGRATION / "config_flow.py", "async_step_room_temperature_entity")
        self.assertIn("vol.In(entity_choices)", sensor)

    def test_temperature_filter_rejects_unrelated_numeric_entities(self):
        source = self._function_source(
            INTEGRATION / "config_flow.py", "_is_temperature_entity_compatible"
        )
        self.assertIn('device_class == "temperature"', source)
        self.assertIn('"°C"', source)
        self.assertIn('"°F"', source)
        self.assertNotIn('temperature_to_celsius(getattr(state', source)
        selector = self._function_source(
            INTEGRATION / "config_flow.py", "async_step_room_temperature_entity"
        )
        self.assertNotIn("entity_choices[default_entity] = default_entity", selector)
        self.assertIn("default_entity in entity_choices", selector)

    def test_yaml_import_still_preserves_legacy_room_temperature_entity(self):
        source = (INTEGRATION / "yaml_config.py").read_text(encoding="utf-8")
        self.assertIn('"room_temperature_entity"', source)

    def test_fks_source_callbacks_do_not_transmit_directly(self):
        climate = INTEGRATION / "climate.py"
        source = self._function_source(climate, "_handle_external_temperature_state_event")
        self.assertNotIn("_async_reply_fks_sv_control", source)
        self.assertIn("_schedule_a5_10_06_room_temperature_push", source)

    def test_a5_10_06_push_uses_existing_set_temperature_path(self):
        source = self._function_source(
            INTEGRATION / "climate.py",
            "_async_push_a5_10_06_room_temperature",
        )
        self.assertIn('"set_temperature"', source)
        self.assertIn("current_temperature=current_temperature", source)

    def test_gateway_passes_optional_current_temperature_to_a5_10_06_encoder(self):
        source = (INTEGRATION / "gateway.py").read_text(encoding="utf-8")
        self.assertIn("current_temperature=kwargs.get(\"current_temperature\")", source)

    def test_options_listener_dispatches_without_forcing_reload(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("SIGNAL_ROOM_TEMPERATURE_UPDATED", source)
        self.assertIn("async_dispatcher_send", source)
        self.assertIn("if not entry.options.get(CONF_RELOAD_AFTER_SAVE)", source)

    def test_fks_sleeping_valve_branch_still_precedes_normal_send(self):
        source = self._function_source(INTEGRATION / "climate.py", "async_set_temperature")
        marker = "if self._is_fks_sv or self._is_fks_hora"
        self.assertIn(marker, source)
        self.assertLess(source.index(marker), source.index("async_send_actuator_command"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
