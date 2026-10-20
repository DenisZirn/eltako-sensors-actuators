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
_load(f"{PKG}.const", INTEGRATION / "const.py")
_load(f"{PKG}.bus.exceptions", INTEGRATION / "bus" / "exceptions.py")
_load(f"{PKG}.bus.ids", INTEGRATION / "bus" / "ids.py")
_load(f"{PKG}.bus.esp2", INTEGRATION / "bus" / "esp2.py")
fks = _load(f"{PKG}.fks_sv_temperature", INTEGRATION / "fks_sv_temperature.py")
eep = _load(f"{PKG}.bus.eep_a5_20_01", INTEGRATION / "bus" / "eep_a5_20_01.py")
const = sys.modules[f"{PKG}.const"]


class TestFksSvIdentityAndPersistence(unittest.TestCase):
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
            **self.device,
            "id": "01-02-03-05",
            "name": "Schlafzimmer",
        }

    def test_normalize_physical_id(self):
        self.assertEqual(fks.normalize_enocean_id("01:02:03:04"), "01-02-03-04")
        self.assertIsNone(fks.normalize_enocean_id("bad-id"))

    def test_only_real_fks_sv_is_selectable(self):
        self.assertTrue(fks.is_fks_sv_device(self.device))
        self.assertFalse(
            fks.is_fks_sv_device(
                {
                    **self.device,
                    "device_type": "FUTH55ED",
                    "room_controller_mode": "fks_kp",
                }
            )
        )
        self.assertFalse(fks.is_fks_sv_device({**self.device, "platform": "sensor"}))

    def test_legacy_fks_sv_without_device_type_still_works(self):
        legacy = dict(self.device)
        legacy.pop("device_type")
        self.assertTrue(fks.is_fks_sv_device(legacy))
        legacy["room_controller_mode"] = "fks_kp"
        self.assertFalse(fks.is_fks_sv_device(legacy))

    def test_priority_ui_external_over_yaml(self):
        source, entity, origin = fks.resolve_fks_sv_temperature_config(self.device, {})
        self.assertEqual(
            (source, entity, origin),
            (const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL, "sensor.yaml_temperature", "yaml"),
        )

        options = fks.set_fks_sv_override(
            {"diagnostics_enabled": True},
            self.device["id"],
            const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.ui_temperature",
        )
        source, entity, origin = fks.resolve_fks_sv_temperature_config(self.device, options)
        self.assertEqual(
            (source, entity, origin),
            (const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL, "sensor.ui_temperature", "ui"),
        )
        self.assertTrue(options["diagnostics_enabled"])

    def test_explicit_internal_overrides_yaml_external(self):
        options = fks.set_fks_sv_override(
            {},
            self.device["id"],
            const.FKS_SV_TEMPERATURE_SOURCE_INTERNAL,
        )
        source, entity, origin = fks.resolve_fks_sv_temperature_config(self.device, options)
        self.assertEqual(
            (source, entity, origin),
            (const.FKS_SV_TEMPERATURE_SOURCE_INTERNAL, None, "ui"),
        )

    def test_multiple_fks_sv_mappings_are_independent(self):
        options = fks.set_fks_sv_override(
            {},
            self.device["id"],
            const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.wohnzimmer",
        )
        options = fks.set_fks_sv_override(
            options,
            self.other["id"],
            const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.schlafzimmer",
        )
        self.assertEqual(
            fks.resolve_fks_sv_temperature_config(self.device, options)[1],
            "sensor.wohnzimmer",
        )
        self.assertEqual(
            fks.resolve_fks_sv_temperature_config(self.other, options)[1],
            "sensor.schlafzimmer",
        )

    def test_yaml_reimport_style_update_does_not_remove_override(self):
        options = fks.set_fks_sv_override(
            {"yaml_config": "old"},
            self.device["id"],
            const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
            "sensor.wohnzimmer",
        )
        # Mirrors OptionsFlow._merged_options(): current options are copied and
        # the newly parsed YAML/device list updates only its own keys.
        after_import = dict(options)
        after_import.update({"yaml_config": "new", "devices": [self.device]})
        self.assertEqual(
            fks.resolve_fks_sv_temperature_config(self.device, after_import)[1],
            "sensor.wohnzimmer",
        )


class TestTemperatureValidationAndFallback(unittest.TestCase):
    def test_celsius_and_fahrenheit(self):
        self.assertEqual(fks.temperature_to_celsius("21.5", "°C"), 21.5)
        self.assertEqual(fks.temperature_to_celsius("68", "°F"), 20.0)
        self.assertEqual(fks.temperature_to_celsius(0, "°C"), 0.0)

    def test_invalid_values_are_rejected_not_clamped(self):
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
                self.assertIsNone(fks.temperature_to_celsius(value, unit))

    def test_external_fallback_and_recovery(self):
        source = const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL
        self.assertEqual(
            fks.select_fks_sv_room_temperature(source, 22.1, 20.0),
            (22.1, "normal", const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL),
        )
        self.assertEqual(
            fks.select_fks_sv_room_temperature(source, None, 20.0),
            (20.0, "fallback", const.FKS_SV_TEMPERATURE_SOURCE_INTERNAL),
        )
        self.assertEqual(
            fks.select_fks_sv_room_temperature(source, 22.4, 20.0),
            (22.4, "normal", const.FKS_SV_TEMPERATURE_SOURCE_EXTERNAL),
        )
        self.assertEqual(
            fks.select_fks_sv_room_temperature(source, None, None),
            (None, "error", None),
        )

    def test_internal_source_ignores_external_value(self):
        self.assertEqual(
            fks.select_fks_sv_room_temperature(
                const.FKS_SV_TEMPERATURE_SOURCE_INTERNAL,
                25.0,
                19.5,
            ),
            (19.5, "normal", const.FKS_SV_TEMPERATURE_SOURCE_INTERNAL),
        )


class TestA52001Encoding(unittest.TestCase):
    def test_inverse_db2_encoding(self):
        data = eep.encode_a5_20_01_temperature_setpoint_data(
            target_temperature=20.0,
            room_temperature=20.0,
        )
        self.assertEqual(data, bytes((0x80, 0x7F, 0x04, 0x08)))

        data_40 = eep.encode_a5_20_01_temperature_setpoint_data(
            target_temperature=20.0,
            room_temperature=40.0,
        )
        self.assertEqual(data_40[1], 0x00)

        data_0 = eep.encode_a5_20_01_temperature_setpoint_data(
            target_temperature=20.0,
            room_temperature=0.0,
        )
        self.assertEqual(data_0[1], 0xFF)

    def test_missing_or_nonfinite_room_temperature_cannot_encode(self):
        for value in (None, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    eep.encode_a5_20_01_temperature_setpoint_data(
                        target_temperature=20.0,
                        room_temperature=value,
                    )

    def test_db2_zero_decodes_as_real_40_degrees(self):
        decoded = eep.decode_a5_20_01_controller_telegram(
            bytes((0x80, 0x00, 0x04, 0x08))
        )
        self.assertEqual(decoded["room_temperature_command"], 40.0)
        self.assertTrue(decoded["temperature_control"])

    def test_builder_payload_matches_pure_encoder(self):
        expected = eep.encode_a5_20_01_temperature_setpoint_data(
            target_temperature=21.0,
            room_temperature=22.0,
        )
        message = eep.build_a5_20_01_temperature_setpoint(
            "00-00-B0-01",
            target_temperature=21.0,
            room_temperature=22.0,
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

    def test_options_flow_exposes_fks_sv_menu_and_entity_selector(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn('"fks_sv_room_temperature"', source)
        self.assertIn("EntitySelector", source)
        self.assertIn("set_fks_sv_override", source)

    def test_yaml_import_still_preserves_legacy_room_temperature_entity(self):
        source = (INTEGRATION / "yaml_config.py").read_text(encoding="utf-8")
        self.assertIn('"room_temperature_entity"', source)

    def test_live_source_callbacks_do_not_send_radio_telegrams(self):
        climate = INTEGRATION / "climate.py"
        for name in (
            "_handle_external_temperature_state_event",
            "_handle_temperature_options_updated",
        ):
            source = self._function_source(climate, name)
            self.assertNotIn("async_send", source)
            self.assertNotIn("_async_reply_fks_sv_control", source)

    def test_options_listener_dispatches_without_forcing_reload(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        self.assertIn("SIGNAL_FKS_SV_ROOM_TEMPERATURE_UPDATED", source)
        self.assertIn("async_dispatcher_send", source)
        self.assertIn("if not entry.options.get(CONF_RELOAD_AFTER_SAVE)", source)

    def test_new_room_temperature_feature_does_not_replace_protocol_routing(self):
        source = (INTEGRATION / "climate.py").read_text(encoding="utf-8")
        self.assertIn('self._is_fks_sv = self._eep == "A5-20-01"', source)
        self.assertIn(
            "self._has_fks_sv_room_temperature_source = is_fks_sv_device(device)",
            source,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
