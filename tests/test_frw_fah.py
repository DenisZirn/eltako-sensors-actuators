"""Regression checks for FAH/FHD60SB and legacy FRW device profiles."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "eltako_sensors_actuators"
    / "device_profiles.py"
)
SPEC = importlib.util.spec_from_file_location("eltako_device_profiles_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeviceProfilesTest(unittest.TestCase):
    def test_current_eedtoy_fah_device_type(self):
        profile = {
            "id": "01-94-65-67",
            "eep": "A5-06-01",
            "name": "Norden",
            "device_type": "FAH",
            "device_class": "illuminance",
        }
        self.assertTrue(MODULE.is_eltako_illuminance_device(profile))
        self.assertEqual(
            MODULE.decode_eltako_a5_06_01(bytes.fromhex("00 00 00 0F"))["brightness"],
            0,
        )
        self.assertEqual(
            MODULE.decode_eltako_a5_06_01(bytes.fromhex("62 00 00 0F"))["brightness"],
            98,
        )

    def test_fhd60sb_low_range(self):
        profile = {"device_type": "FHD60SB", "eep": "A5-06-01"}
        self.assertTrue(MODULE.is_eltako_illuminance_device(profile))
        result = MODULE.decode_eltako_a5_06_01(bytes.fromhex("63 00 00 09"))
        self.assertEqual(result["brightness"], 99)
        self.assertTrue(result["data_telegram"])

    def test_illuminance_legacy_fallback_is_narrow(self):
        self.assertTrue(
            MODULE.is_eltako_illuminance_device(
                {"name": "Norden", "eep": "A5-06-01", "device_class": "illuminance"}
            )
        )
        self.assertFalse(
            MODULE.is_eltako_illuminance_device(
                {"device_type": "OTHER", "eep": "A5-06-01", "device_class": "illuminance"}
            )
        )

    def test_teach_in_does_not_overwrite_brightness(self):
        for telegram in ("18 08 0D 80", "18 08 0D 87"):
            result = MODULE.decode_eltako_a5_06_01(bytes.fromhex(telegram))
            self.assertTrue(result["learn_telegram"])
            self.assertNotIn("brightness", result)

    def test_legacy_frw_states(self):
        profile = {"device_type": "FRW-ws", "eep": "F6-02-01", "device_class": "smoke"}
        self.assertTrue(MODULE.is_legacy_frw_device(profile))

        alarm = MODULE.decode_legacy_frw_rps(0x10)
        self.assertTrue(alarm["smoke_alarm"])
        self.assertNotIn("battery_low", alarm)

        low_battery = MODULE.decode_legacy_frw_rps(0x30)
        self.assertTrue(low_battery["battery_low"])
        self.assertNotIn("smoke_alarm", low_battery)

        released = MODULE.decode_legacy_frw_rps(0x00)
        self.assertEqual(released["frw_status"], "Frei")
        self.assertFalse(released["smoke_alarm"])
        self.assertFalse(released["battery_low"])

    def test_fws81_water_states(self):
        profile = {
            "id": "FE-FE-AD-C8",
            "eep": "F6-05-01",
            "device_type": "FWS81",
            "device_class": "moisture",
        }
        self.assertTrue(MODULE.is_fws81_device(profile))
        wet = MODULE.decode_fws81_rps(0x11, 0x30)
        self.assertTrue(wet["water"])
        dry = MODULE.decode_fws81_rps(0x11, 0x20)
        self.assertFalse(dry["water"])
        self.assertTrue(
            MODULE.decode_fws81_rps(0x10, 0x30).get("ignored")
        )

    def test_duplicate_frw_status_entity_is_not_created(self):
        sensor_source = (
            Path(__file__).resolve().parents[1]
            / "custom_components"
            / "eltako_sensors_actuators"
            / "sensor.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"frw_status", "Rauchmelderstatus"', sensor_source)
        self.assertIn('"Rauchmelderstatus"', sensor_source)

    def test_eedtoy_area_is_preserved_and_applied(self):
        root = Path(__file__).resolve().parents[1] / "custom_components" / "eltako_sensors_actuators"
        yaml_source = (root / "yaml_config.py").read_text(encoding="utf-8")
        entity_source = (root / "entity_base.py").read_text(encoding="utf-8")

        self.assertIn('"area": _clean_string(item.get("area"))', yaml_source)
        self.assertIn("suggested_area=suggested_area", entity_source)
        self.assertIn("ar.async_get(self.hass).async_get_or_create(area_name)", entity_source)
        self.assertIn("device_registry.async_update_device(device_entry.id, area_id=area.id)", entity_source)

    def test_frwb_and_normal_rockers_are_not_legacy_frw(self):
        self.assertFalse(MODULE.is_legacy_frw_device({"device_type": "FRWB", "eep": "A5-30-03"}))
        self.assertFalse(MODULE.is_legacy_frw_device({"device_type": "FT55", "eep": "F6-02-01"}))


if __name__ == "__main__":
    unittest.main()
