"""F64 uses a room-sensor telegram, independently of F65/61 priority.

Expected fields come from ELTAKO's FTR telegram table and EEP A5-10-06.
The gateway routing and ESP2 encoder are real; no RF hardware is involved.
"""
from __future__ import annotations

import unittest

from test_fks_sv_room_temperature import eep10
from test_restore_fhk14_f4hk14_fae14 import _builder


SERIES14 = ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")


def _device(model="FHK14"):
    return {
        "platform": "climate", "eep": "A5-10-06", "sender_eep": "A5-10-06",
        "device_type": model, "id": "FF-BF-5C-9D", "sender_id": "FF-A6-04-9D",
        "operating_mode_sender_id": "FF-A6-04-9E", "priority": "ha",
    }


class Series14ExternalProfileTests(unittest.TestCase):
    def test_near_setpoint_keeps_the_reported_half_degree_switching_margin(self):
        # All these source values display as 20.3 C in HA. Truncating DB2
        # while truncating inverted DB1 turns 20.5/20.3 into equal wire
        # temperatures, and makes 21.0/20.3 fall below a 0.5 K hysteresis.
        for actual in (20.26, 20.30, 20.34):
            with self.subTest(actual=actual):
                near = eep10.encode_a5_10_06_room_control_data(
                    target_temperature=20.5, current_temperature=actual,
                    controller_profile="series14_f64",
                )
                higher = eep10.encode_a5_10_06_room_control_data(
                    target_temperature=21.0, current_temperature=actual,
                    controller_profile="series14_f64",
                )
                wire_actual = (255 - near[2]) * 40.0 / 255.0
                self.assertGreater(near[1] * 40.0 / 255.0, wire_actual)
                self.assertGreaterEqual(higher[1] * 40.0 / 255.0 - wire_actual, 0.5)

    def test_f64_equal_temperatures_use_the_same_physical_grid(self):
        # Includes 20 C: independently rounding the ascending and descending
        # scales would produce different temperatures at this half-step.
        for temperature in (0, 4, 12, 18.78, 20, 20.3, 20.5, 28, 36, 40):
            with self.subTest(temperature=temperature):
                data = eep10.encode_a5_10_06_room_control_data(
                    target_temperature=temperature, current_temperature=temperature,
                    controller_profile="series14_f64",
                )
                self.assertEqual(data[1], 255 - data[2])

    def test_f64_quantization_error_is_at_most_half_a_protocol_step(self):
        half_step = 20.0 / 255.0
        for index in range(-150, 451):
            temperature = index / 10.0
            with self.subTest(temperature=temperature):
                data = eep10.encode_a5_10_06_room_control_data(
                    target_temperature=temperature, current_temperature=temperature,
                    controller_profile="series14_f64",
                )
                bounded = min(40.0, max(0.0, temperature))
                self.assertLessEqual(abs(data[1] * 40.0 / 255.0 - bounded), half_step + 1e-12)
                self.assertLessEqual(abs((255 - data[2]) * 40.0 / 255.0 - bounded), half_step + 1e-12)

    def test_rounding_change_does_not_rewrite_native_or_fhk61_targets(self):
        native = eep10.encode_a5_10_06_room_control_data(
            target_temperature=20.5, current_temperature=None, priority="ha",
        )
        fhk61 = eep10.encode_a5_10_06_room_control_data(
            target_temperature=20.5, current_temperature=None,
            controller_profile="fhk61_230v",
        )
        self.assertEqual(native, bytes.fromhex("70 82 00 08"))
        self.assertEqual(fhk61, bytes.fromhex("00 83 00 0E"))

    def test_user_values_have_documented_ftr_day_format(self):
        frame = eep10.build_a5_10_06_room_control(
            "FF-A6-04-9D", target_temperature=25.0, current_temperature=21.6,
            controller_profile="series14_f64",
        )
        self.assertEqual(
            frame.serialize(), bytes.fromhex("A5 5A 6B 07 00 9F 75 0F FF A6 04 9D 80 5B")
        )

    def test_f64_sensor_data_is_independent_of_priority_and_rps_mode(self):
        for priority in (None, "auto", "ha", "limit", "manual", 0x08, 0x0A, 0x0E):
            for mode in ("normal", "night", "night_setback", "setback", "off"):
                with self.subTest(priority=priority, mode=mode):
                    data = eep10.encode_a5_10_06_room_control_data(
                        target_temperature=25.0, current_temperature=21.6,
                        priority=priority, hvac_mode=mode, controller_profile="series14_f64",
                    )
                    self.assertEqual(data, bytes.fromhex("00 9F 75 0F"))

    def test_gateway_honors_explicit_f64_role_for_each_series14_model(self):
        build = _builder()
        for model in SERIES14:
            with self.subTest(model=model):
                sender, encoded_args = build(
                    _device(model), "set_temperature", temperature=25.0,
                    current_temperature=21.6, controller_priority="ha",
                    controller_profile="series14_f64",
                )
                self.assertEqual(sender, "FF-A6-04-9D")
                self.assertEqual(encoded_args["controller_profile"], "series14_f64")
                self.assertEqual(
                    eep10.encode_a5_10_06_room_control_data(**encoded_args),
                    bytes.fromhex("00 9F 75 0F"),
                )

    def test_missing_measurement_cannot_switch_the_gateway_to_f65(self):
        sender, encoded_args = _builder()(
            _device(), "set_temperature", temperature=25.0,
            current_temperature=None, controller_profile="series14_f64",
        )
        self.assertEqual(sender, "FF-A6-04-9D")
        self.assertEqual(encoded_args["controller_profile"], "series14_f64")
        with self.assertRaisesRegex(ValueError, "valid external room temperature"):
            eep10.encode_a5_10_06_room_control_data(**encoded_args)

    def test_f64_does_not_invent_a_temperature_for_invalid_measurements(self):
        for measurement in (None, "unknown", "unavailable", float("nan"), float("inf")):
            with self.subTest(measurement=measurement):
                with self.assertRaisesRegex(ValueError, "valid external room temperature"):
                    eep10.encode_a5_10_06_room_control_data(
                        target_temperature=25.0, current_temperature=measurement,
                        controller_profile="series14_f64",
                    )
        self.assertEqual(
            eep10.encode_a5_10_06_room_control_data(
                target_temperature=25.0, current_temperature=0,
                controller_profile="series14_f64",
            ),
            bytes.fromhex("00 9F FF 0F"),
        )

    def test_native_priority_profiles_keep_their_existing_bytes(self):
        for priority, db0 in (("ha", 0x08), ("auto", 0x0E), ("limit", 0x0A)):
            with self.subTest(priority=priority):
                self.assertEqual(
                    eep10.encode_a5_10_06_room_control_data(
                        target_temperature=25.0, current_temperature=None,
                        hvac_mode="normal", priority=priority,
                    ),
                    bytes((0x70, 0x9F, 0x00, db0)),
                )

    def test_fhk61_profile_cannot_be_overridden_by_series14_f64(self):
        sender, encoded_args = _builder()(
            _device("FHK61-230V"), "set_temperature", temperature=25.0,
            current_temperature=21.6, controller_priority="auto",
            controller_profile="series14_f64",
        )
        self.assertEqual(encoded_args["controller_profile"], "fhk61_230v")
        self.assertIsNone(encoded_args["current_temperature"])
        frame = eep10.build_a5_10_06_room_control(sender, **encoded_args)
        self.assertEqual(frame.serialize()[4:8], bytes.fromhex("00 9F 00 0E"))
        self.assertEqual(frame.serialize()[-2], 0xB0)

    def test_operating_mode_still_uses_separately_learned_rps_sender(self):
        build = _builder()
        for command, keyword, mode in (
            ("set_hvac_mode", "hvac_mode", "heat"),
            ("set_hvac_mode", "hvac_mode", "off"),
            ("set_preset_mode", "preset_mode", "night"),
            ("set_preset_mode", "preset_mode", "setback"),
        ):
            with self.subTest(command=command, mode=mode):
                self.assertEqual(
                    build(_device(), command, controller_profile="series14_f64", **{keyword: mode}),
                    ("rps", "FF-A6-04-9E", mode),
                )


if __name__ == "__main__":
    unittest.main()
