"""Route F64/0F controller echoes separately from physical FHK feedback.

Exercise the original gateway RX handler, its sender classifier, the real
ESP2/4BS decoder and the original climate handler. Home Assistant and
unrelated device-profile guards are replaced by the existing test stand-ins.
The frames are constructed fixtures, not captured hardware responses.
"""
from __future__ import annotations

import logging
import re
from types import SimpleNamespace
import unittest

from test_fhk61_family_feedback_runtime import _source_function
from test_fks_sv_room_temperature import INTEGRATION, PKG, _load, const, eep10
from test_climate_temperature_sync import _wait_for_push
from test_series14_controller_echo import SERIES14_MODELS, _entity, _state


ids = _load(f"{PKG}.bus.ids", INTEGRATION / "bus" / "ids.py")
ftr = _load(f"{PKG}.ftr_profiles", INTEGRATION / "ftr_profiles.py")


def _gateway_rx_handler():
    namespace = {
        "parse_address": ids.parse_address,
        "format_address": ids.format_address,
        "GATEWAY_TYPE_FAM_USB": const.GATEWAY_TYPE_FAM_USB,
        # These unrelated models are not used by the fixed Series-14 fixtures.
        "_is_f2l14_device": lambda device: False,
        "_is_frgbw14_device_config": lambda device: False,
    }
    for name in (
        "_normalized_address_or_none", "_get_sender_id",
        "_fam_usb_effective_sender_id", "_fam_usb_effective_sender_id_for_device",
        "_effective_sender_id_for_gateway",
    ):
        namespace[name] = _source_function("gateway.py", name, globals=namespace)
    namespace.update({
        "normalize_eep": _source_function("entity_base.py", "normalize_eep", globals={"re": re}),
        "ORG_4BS": 0x07,
    })
    namespace["_is_a5_10_06_controller_echo"] = _source_function(
        "gateway.py", "_is_a5_10_06_controller_echo", globals=namespace
    )
    decoder = _source_function(
        "bus/decoder.py", "decode_esp2_message",
        globals={
            "re": re, "format_address": ids.format_address,
            "ESP2Message": eep10.ESP2Message,
            "ORG_RPS": 0x05, "ORG_1BS": 0x06, "ORG_4BS": 0x07,
            "_decode_4bs": _source_function("bus/decoder.py", "_decode_4bs"),
        },
    )
    namespace.update({
        "ESP2Message": eep10.ESP2Message,
        "decode_esp2_message": decoder,
        "ORG_RPS": 0x05,
        "_is_f4usm61b_device": lambda device: False,
        "_futh55ed_mode": lambda device: "",
        "_is_ffg7b_device": lambda device: False,
        "is_ftr_temperature_device": ftr.is_ftr_temperature_device,
        "normalize_ftr_4bs": ftr.normalize_ftr_4bs,
        "_normalize_device_specific_decoded": _source_function(
            "gateway.py", "_normalize_device_specific_decoded"
        ),
        "EltakoTelegram": SimpleNamespace,
        "_LOGGER": logging.getLogger("eltako-f64-echo-test"),
    })
    return _source_function(
        "gateway.py", "_handle_received_frame", cls="EltakoGateway", globals=namespace
    )


_receive_frame = _gateway_rx_handler()


def _receive(entity, sender, payload="00-9F-75-0F"):
    device = entity.device_config
    dispatched = []
    gateway = SimpleNamespace(
        _fks_sv_controller_lookup={},
        _device_lookup={device["id"]: device, device["sender_id"]: device},
        gateway_type=const.GATEWAY_TYPE_FAM_USB,
        base_id="FF-A6-04-80", selected_gateway={},
        _dispatch=dispatched.append,
    )
    frame = eep10.build_regular_4bs(
        ids.parse_address(sender), bytes.fromhex(payload.replace("-", " ")),
        status=0x80, outgoing=False,
    )
    _receive_frame(gateway, frame.serialize())
    if len(dispatched) != 1:
        raise AssertionError(f"Expected one routed telegram, received {len(dispatched)}")
    telegram = dispatched[0]
    entity._handle_telegram(telegram)
    return telegram


class Series14ExternalEchoRoutingTests(unittest.TestCase):
    def test_f64_controller_sender_0f_does_not_confirm_or_replace_climate_state(self):
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                entity, _, _ = _entity(model)
                # A delayed day-mode echo must also leave a newer OFF state alone.
                entity._attr_hvac_mode = "off"
                entity._fhk_heater_mode = "off"
                entity._attr_preset_mode = "eco"
                before = _state(entity)
                telegram = _receive(entity, "FF-A6-04-9D")
                self.assertEqual(telegram.sender_id, "FF-A6-04-9D")
                self.assertEqual(telegram.decoded["physical_sender_id"], "FF-A6-04-9D")
                self.assertEqual(telegram.decoded["data_hex"], "00-9f-75-0f")
                self.assertTrue(telegram.decoded["tx_echo"])
                self.assertEqual(telegram.decoded["direction"], "to_actuator")
                self.assertFalse(telegram.decoded["actuator_response"])
                self.assertEqual(_state(entity), before)
                self.assertEqual(entity._target_temperature, 25.0)
                self.assertIsNone(entity._internal_temperature)
                self.assertFalse(entity._has_genuine_current_temperature)

    def test_same_0f_bytes_from_physical_fhk_are_still_valid_feedback(self):
        for model in ("FHK14", "F4HK14", "FAE14LPR"):
            with self.subTest(model=model):
                entity, _, _ = _entity(model)
                # No successful local send is recorded in this fixture.
                self.assertIsNone(entity._last_sent_target_temperature)
                self.assertIsNone(entity._last_f64_target_tx)
                telegram = _receive(entity, "FF-BF-5C-9D")
                self.assertEqual(telegram.sender_id, "FF-BF-5C-9D")
                self.assertEqual(telegram.decoded["physical_sender_id"], "FF-BF-5C-9D")
                self.assertFalse(telegram.decoded.get("tx_echo", False))
                self.assertNotEqual(telegram.decoded.get("direction"), "to_actuator")
                self.assertTrue(telegram.decoded["actuator_response"])
                self.assertEqual(entity._target_temperature, 24.9)
                self.assertEqual(entity._internal_temperature, 21.6)
                self.assertTrue(entity._has_genuine_current_temperature)

    def test_matching_fresh_f64_feedback_keeps_requested_target_but_updates_other_state(self):
        entity, _, _ = _entity()
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        # DB2 matches the actual transmission, while the actuator reports a
        # different native temperature and mode. Only target precision is kept.
        telegram = _receive(entity, "FF-BF-5C-9D", "50-9F-78-0F")
        self.assertTrue(telegram.decoded["actuator_response"])
        self.assertEqual(telegram.decoded["target_temperature"], 24.9)
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._internal_temperature, 21.2)
        self.assertTrue(entity._has_genuine_current_temperature)
        self.assertEqual(entity._current_temperature, 21.6)
        self.assertEqual(entity._used_room_temperature, 21.6)
        self.assertEqual(entity._attr_hvac_mode, "heat")
        self.assertEqual(entity._fhk_heater_mode, "night_setback")
        self.assertEqual(entity._attr_preset_mode, "sleep")

    def test_unused_f64_db3_in_physical_feedback_does_not_resume_an_off_entity(self):
        entity, _, _ = _entity()
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        entity._attr_hvac_mode = "off"
        entity._fhk_heater_mode = "off"
        entity._attr_preset_mode = "eco"
        telegram = _receive(entity, "FF-BF-5C-9D", "00-9F-75-0F")
        self.assertTrue(telegram.decoded["actuator_response"])
        self.assertEqual(telegram.decoded["heater_mode_code"], 0x00)
        self.assertEqual(entity._attr_hvac_mode, "off")
        self.assertEqual(entity._fhk_heater_mode, "off")
        self.assertEqual(entity._attr_preset_mode, "eco")
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._internal_temperature, 21.6)
        self.assertTrue(entity._has_genuine_current_temperature)

    def test_known_f64_physical_mode_still_resumes_heat(self):
        entity, _, _ = _entity()
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        entity._attr_hvac_mode = "off"
        entity._fhk_heater_mode = "off"
        entity._attr_preset_mode = "eco"
        telegram = _receive(entity, "FF-BF-5C-9D", "70-9F-75-0F")
        self.assertTrue(telegram.decoded["actuator_response"])
        self.assertEqual(telegram.decoded["heater_mode_code"], 0x70)
        self.assertEqual(entity._attr_hvac_mode, "heat")
        self.assertEqual(entity._fhk_heater_mode, "normal")
        self.assertEqual(entity._attr_preset_mode, "home")
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._internal_temperature, 21.6)
        self.assertTrue(entity._has_genuine_current_temperature)

    def test_different_physical_target_after_echo_is_not_suppressed(self):
        entity, _, hass = _entity()
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        hass.states.set("sensor.room", 22.3)
        entity._refresh_room_temperature_state()
        _receive(entity, "FF-A6-04-9D")
        self.assertEqual(entity._target_temperature, 25.0)
        telegram = _receive(entity, "FF-BF-5C-9D", "70-89-75-0F")
        self.assertTrue(telegram.decoded["actuator_response"])
        self.assertEqual(entity._target_temperature, 21.5)
        self.assertEqual(entity._internal_temperature, 21.6)
        self.assertTrue(entity._has_genuine_current_temperature)
        self.assertEqual(entity._current_temperature, 22.3)
        self.assertEqual(entity._used_room_temperature, 22.3)

    def test_old_f64_transmission_does_not_hide_feedback_after_another_target_was_selected(self):
        entity, _, _ = _entity(target=22.0)
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        _receive(entity, "FF-BF-5C-9D")
        self.assertEqual(entity._target_temperature, 24.9)
        self.assertEqual(entity._internal_temperature, 21.6)

    def test_restored_telemetry_is_not_a_fresh_f64_transmission(self):
        entity, _, _ = _entity()
        entity._last_sent_target_temperature = 25.0
        entity._last_sent_room_temperature = 21.6
        entity._last_controller_telegram = "00-9F-75-0F"
        entity._last_controller_response = "2026-11-25T16:15:15+00:00"
        self.assertIsNone(entity._last_f64_target_tx)
        _receive(entity, "FF-BF-5C-9D")
        self.assertEqual(entity._target_temperature, 24.9)
        self.assertTrue(entity._has_genuine_current_temperature)

    def test_f64_record_cannot_suppress_native_central_feedback(self):
        entity, _, _ = _entity(source="native", native=20.0)
        entity.device_config["priority"] = "ha"
        # A record from an earlier external-source configuration must not
        # change the native controller's physical feedback behavior.
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        telegram = _receive(entity, "FF-BF-5C-86", "70-9F-75-0F")
        self.assertFalse(entity._matches_sent_f64_target(telegram))
        self.assertEqual(entity._target_temperature, 24.9)
        self.assertEqual(entity._internal_temperature, 21.6)
        self.assertEqual(entity._current_temperature, 21.6)

    def test_fhk61_feedback_keeps_its_own_handling_despite_an_f64_record(self):
        entity, _, _ = _entity("FHK61-230V", source="native")
        entity._is_fhk61 = True
        entity._is_fhk61_230v = True
        entity._has_room_temperature_assignment = False
        entity._room_temperature_device_kind = None
        entity._last_f64_target_tx = (25.0, bytes.fromhex("00 9F 75 0F"))
        entity._fhk_heater_mode = "setback"
        entity._attr_preset_mode = "eco"
        telegram = _receive(entity, "FF-BF-5C-86", "00-9F-75-0F")
        self.assertFalse(entity._matches_sent_f64_target(telegram))
        # The existing FHK61 telemetry branch ignores 4BS target/mode fields.
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._current_temperature, 21.6)
        self.assertEqual(entity._fhk_heater_mode, "setback")
        self.assertEqual(entity._attr_preset_mode, "eco")


class Series14ExternalFeedbackPushTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_transmission_feedback_and_sensor_update_do_not_lower_the_target(self):
        entity, gateway, hass = _entity()
        await entity._async_push_a5_10_06_room_temperature()
        self.assertEqual(entity._last_f64_target_tx, (25.0, bytes.fromhex("00 9F 75 0F")))
        _receive(entity, "FF-BF-5C-9D")
        self.assertEqual(entity._target_temperature, 25.0)

        hass.states.set("sensor.room", 22.0)
        entity._handle_external_temperature_state_event(None)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(gateway.calls[-1][2]["temperature"], 25.0)
        self.assertEqual(gateway.calls[-1][2]["current_temperature"], 22.0)
        # F64 rounds 22.0 C to the nearest common temperature step.
        self.assertEqual(entity._last_controller_telegram, "00-9F-73-0F")
        _receive(entity, "FF-BF-5C-9D", "00-9F-73-0F")
        self.assertEqual(entity._target_temperature, 25.0)


if __name__ == "__main__":
    unittest.main()
