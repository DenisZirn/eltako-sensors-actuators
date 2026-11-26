"""Series-14 regression: controller echoes must not replace climate state.

Run the integration's real decoder, encoder, RX handler and temperature-push
methods through the existing isolated runtime harness. This reproduces the
reported 25 C -> 24.9 C echo without requiring Home Assistant or RF hardware.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
import unittest

from test_climate_temperature_sync import make_climate, _wait_for_push
from test_fhk61_family_feedback_runtime import _source_function
from test_fks_sv_room_temperature import const, eep10, room


SERIES14_MODELS = ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")
ECHO_MARKERS = ({"tx_echo": True}, {"direction": "to_actuator"})

_decode_4bs = _source_function("bus/decoder.py", "_decode_4bs")
_handle_telegram = _source_function(
    "climate.py", "_handle_telegram", cls="EltakoClimate",
    globals={
        "HVACMode": SimpleNamespace(HEAT="heat", OFF="off"),
        "PRESET_HOME": "home", "PRESET_SLEEP": "sleep", "PRESET_ECO": "eco",
        "temperature_to_celsius": room.temperature_to_celsius,
        "_now_iso": lambda: "2026-11-26T16:15:15+00:00",
    },
)
_matches_physical_device = _source_function(
    "climate.py", "_matches_physical_device", cls="EltakoClimate"
)


def _entity(model="FHK14", *, source="external", native=None, target=25.0):
    configured_source = (
        const.ROOM_TEMPERATURE_SOURCE_NATIVE if source == "native"
        else const.ROOM_TEMPERATURE_SOURCE_EXTERNAL
    )
    entity, gateway, hass = make_climate(
        model, source=configured_source, native=native, external=21.6
    )
    suffix = "9D" if source == "external" else "86"
    entity.device_config.update({
        "id": f"FF-BF-5C-{suffix}",
        "sender_id": f"FF-A6-04-{suffix}",
        "priority": "auto",
    })
    hass.options = room.set_room_temperature_override(
        {}, entity.device_config["id"], configured_source,
        "sensor.room" if source == "external" else None,
    )
    entity._eep = "A5-10-06"
    entity._is_fks_hora = False
    entity._is_fhk61u = False
    entity._is_fhk61 = False
    entity._is_fhk61_230v = False
    # Match the production constructor's model classification.
    entity._is_fae14lpr = model == "FAE14LPR"
    entity._has_genuine_current_temperature = native is not None
    entity._target_temperature = target
    entity._handle_telegram = MethodType(_handle_telegram, entity)
    entity._matches_physical_device = MethodType(_matches_physical_device, entity)
    entity._refresh_room_temperature_state()
    return entity, gateway, hass


def _telegram(entity, payload, *, physical=False, **markers):
    data = bytes.fromhex(payload.replace("-", " "))
    decoded = _decode_4bs(data, "A5-10-06")
    sender = entity.device_config["id" if physical else "sender_id"]
    decoded.update({
        "org": "0x07", "data_hex": data.hex("-"),
        "physical_sender_id": sender, **markers,
    })
    return SimpleNamespace(sender_id=sender, decoded=decoded)


def _state(entity):
    return {
        name: getattr(entity, name)
        for name in (
            "_target_temperature", "_current_temperature", "_internal_temperature",
            "_has_genuine_current_temperature", "_attr_hvac_mode",
            "_fhk_heater_mode", "_attr_preset_mode", "_used_room_temperature",
        )
    }


class Series14ControllerEchoTests(unittest.TestCase):
    def test_external_user_telegram_does_not_round_trip_the_requested_setpoint(self):
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=25.0, current_temperature=21.6,
            hvac_mode="normal", priority="auto",
        )
        self.assertEqual(data.hex("-").upper(), "70-9F-75-0E")
        self.assertEqual(_decode_4bs(data, "A5-10-06")["target_temperature"], 24.9)
        for model in SERIES14_MODELS:
            for markers in ECHO_MARKERS:
                with self.subTest(model=model, markers=markers):
                    entity, _, _ = _entity(model)
                    before = _state(entity)
                    entity._handle_telegram(_telegram(entity, "70-9F-75-0E", **markers))
                    self.assertEqual(_state(entity), before)

    def test_native_user_telegram_keeps_the_genuine_room_temperature(self):
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=24.5, current_temperature=None,
            hvac_mode="normal", priority="auto",
        )
        self.assertEqual(data.hex("-").upper(), "70-9C-00-0E")
        self.assertEqual(_decode_4bs(data, "A5-10-06")["temperature"], 40.0)
        for model in SERIES14_MODELS:
            for markers in ECHO_MARKERS:
                with self.subTest(model=model, markers=markers):
                    entity, _, _ = _entity(model, source="native", native=21.6, target=24.5)
                    before = _state(entity)
                    entity._handle_telegram(_telegram(entity, "70-9C-00-0E", **markers))
                    self.assertEqual(_state(entity), before)

    def test_delayed_controller_echo_cannot_restore_an_old_target_or_mode(self):
        for model in SERIES14_MODELS:
            for source in ("native", "external"):
                for markers in ECHO_MARKERS:
                    for payload in ("50-89-00-0E", "30-89-00-0E", "10-89-00-0E"):
                        with self.subTest(model=model, source=source, markers=markers, payload=payload):
                            entity, _, _ = _entity(model, source=source, native=21.6)
                            before = _state(entity)
                            entity._handle_telegram(_telegram(entity, payload, **markers))
                            self.assertEqual(_state(entity), before)

    def test_real_fhk_feedback_still_updates_target_native_temperature_and_mode(self):
        # Constructed feedback fixture, not a captured frame from the user.
        for model in ("FHK14", "F4HK14", "FAE14LPR"):
            with self.subTest(model=model):
                entity, _, _ = _entity(model, source="native", native=20.0)
                entity._attr_hvac_mode = "off"
                entity._fhk_heater_mode = "off"
                entity._attr_preset_mode = "eco"
                telegram = _telegram(entity, "70-89-75-0F", physical=True)
                self.assertTrue(telegram.decoded["actuator_response"])
                entity._handle_telegram(telegram)
                self.assertEqual(entity._target_temperature, 21.5)
                self.assertEqual(entity._internal_temperature, 21.6)
                self.assertEqual(entity._current_temperature, 21.6)
                self.assertTrue(entity._has_genuine_current_temperature)
                self.assertEqual(entity._attr_hvac_mode, "heat")
                self.assertEqual(entity._fhk_heater_mode, "normal")
                self.assertEqual(entity._attr_preset_mode, "home")

    def test_real_fhk_feedback_does_not_replace_the_selected_external_temperature(self):
        entity, _, hass = _entity(source="external")
        hass.states.set("sensor.room", 22.3)
        entity._refresh_room_temperature_state()
        entity._handle_telegram(_telegram(entity, "70-89-75-0F", physical=True))
        self.assertEqual(entity._target_temperature, 21.5)
        self.assertEqual(entity._internal_temperature, 21.6)
        self.assertTrue(entity._has_genuine_current_temperature)
        self.assertEqual(entity._current_temperature, 22.3)
        self.assertEqual(entity._used_room_temperature, 22.3)


class Series14ControllerEchoPushTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_sensor_update_preserves_requested_target_after_echo(self):
        for model in SERIES14_MODELS:
            for markers in ECHO_MARKERS:
                with self.subTest(model=model, markers=markers):
                    entity, gateway, hass = _entity(model)
                    entity._handle_telegram(_telegram(entity, "70-9F-75-0E", **markers))
                    hass.states.set("sensor.room", 21.8)
                    entity._handle_external_temperature_state_event(None)
                    await _wait_for_push(entity)
                    self.assertEqual(len(gateway.calls), 1)
                    _, command, kwargs = gateway.calls[0]
                    self.assertEqual(command, "set_temperature")
                    self.assertEqual(kwargs["temperature"], 25.0)
                    self.assertEqual(kwargs["current_temperature"], 21.8)
                    self.assertEqual(entity._last_sent_target_temperature, 25.0)
                    self.assertEqual(entity._last_controller_telegram, "70-9F-74-0E")


if __name__ == "__main__":
    unittest.main()
