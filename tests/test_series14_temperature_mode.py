"""Series-14 temperature commands must also leave a requested OFF mode.

Execute the production climate command and priority helpers with a fake
gateway. The gateway records call order and the state visible during each
write; no RF reception or physical relay switching is simulated.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
import unittest

from test_climate_temperature_sync import make_climate
from test_fhk61_family_feedback_runtime import _source_function
from test_fks_sv_room_temperature import INTEGRATION, PKG, _load, eep10, const


priority = _load(f"{PKG}.heating_priority", INTEGRATION / "heating_priority.py")
operating_mode = _load(
    f"{PKG}.bus.operating_mode", INTEGRATION / "bus" / "operating_mode.py"
)
SERIES14_MODELS = ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")


class _HomeAssistantError(Exception):
    """Stand-in for the framework's service error."""


_set_temperature = _source_function(
    "climate.py", "async_set_temperature", cls="EltakoClimate",
    globals={
        "HVACMode": SimpleNamespace(HEAT="heat", OFF="off"),
        "ATTR_TEMPERATURE": "temperature", "PRESET_HOME": "home",
        "HomeAssistantError": _HomeAssistantError,
        "_coerce_ha_temperature_to_celsius": _source_function(
            "climate.py", "_coerce_ha_temperature_to_celsius"
        ),
        "heating_operating_mode_family": operating_mode.heating_operating_mode_family,
        "set_priority_mode": priority.set_priority_mode,
        "encode_a5_10_06_room_control_data": eep10.encode_a5_10_06_room_control_data,
        "_now_iso": lambda: "2026-11-26T16:15:15+00:00",
    },
)
_selected_priority = _source_function(
    "climate.py", "_selected_priority", cls="EltakoClimate",
    globals={
        "supports_heating_priority": priority.supports_heating_priority,
        "is_fhk61_priority_device": priority.is_fhk61_priority_device,
        "heating_control_mode": priority.heating_control_mode,
        "priority_mode": priority.priority_mode,
    },
)


def _entity(model="FHK14", *, source="external", hvac_mode="off",
            heater_mode="off", fail_command=None):
    entity, gateway, _hass = make_climate(
        model,
        source=const.ROOM_TEMPERATURE_SOURCE_NATIVE if source == "native" else source,
        native=21.6, external=21.6,
    )
    entity.device_config["priority"] = "auto"
    entity._is_fks_hora = model == "FKS-HORA"
    entity._is_fhk61_230v = model == "FHK61-230V"
    if entity._is_fks_hora:
        entity.device_config["eep"] = "A5-20-04"
        entity._room_temperature_device_kind = None
    entity._attr_hvac_mode = hvac_mode
    entity._fhk_heater_mode = heater_mode
    entity._attr_preset_mode = "home"
    entity._target_temperature = 20.0
    entity._has_genuine_current_temperature = True
    entity.async_set_temperature = MethodType(_set_temperature, entity)
    entity._selected_priority = MethodType(_selected_priority, entity)
    gateway.states_at_send = []

    async def send(device, command, **kwargs):
        gateway.calls.append((device, command, dict(kwargs)))
        gateway.states_at_send.append((
            entity._attr_hvac_mode, entity._fhk_heater_mode,
        ))
        if command == fail_command:
            gateway.last_send_error = "simulated transport failure"
            return False
        gateway.last_send_error = None
        return True

    gateway.async_send_actuator_command = send
    return entity, gateway


class Series14TemperatureModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_off_to_target_sends_setpoint_then_normal_mode(self):
        for model in SERIES14_MODELS:
            for source in ("native", "external"):
                with self.subTest(model=model, source=source):
                    entity, gateway = _entity(model, source=source)
                    await entity.async_set_temperature(temperature=25.0)
                    self.assertEqual(
                        [call[1] for call in gateway.calls],
                        ["set_temperature", "set_hvac_mode"],
                    )
                    setpoint = gateway.calls[0][2]
                    self.assertEqual(setpoint["temperature"], 25.0)
                    self.assertEqual(setpoint["heater_mode"], "normal")
                    self.assertEqual(
                        setpoint["current_temperature"],
                        21.6 if source == "external" else None,
                    )
                    self.assertEqual(gateway.calls[1][2], {"hvac_mode": "heat"})
                    self.assertEqual(gateway.states_at_send, [
                        ("off", "off"), ("off", "off"),
                    ])
                    self.assertEqual(entity._target_temperature, 25.0)
                    self.assertEqual(entity._attr_hvac_mode, "heat")
                    self.assertEqual(entity._fhk_heater_mode, "normal")
                    self.assertEqual(entity._attr_preset_mode, "home")

    async def test_either_local_off_indicator_requests_normal_mode(self):
        for hvac_mode, heater_mode in (("off", "normal"), ("heat", "off")):
            with self.subTest(hvac_mode=hvac_mode, heater_mode=heater_mode):
                entity, gateway = _entity(
                    hvac_mode=hvac_mode, heater_mode=heater_mode
                )
                await entity.async_set_temperature(temperature=24.0)
                self.assertEqual(
                    [call[1] for call in gateway.calls],
                    ["set_temperature", "set_hvac_mode"],
                )
                self.assertEqual(gateway.calls[0][2]["heater_mode"], "normal")
                self.assertEqual(entity._attr_hvac_mode, "heat")
                self.assertEqual(entity._fhk_heater_mode, "normal")

    async def test_active_modes_keep_their_existing_single_setpoint_command(self):
        for model in SERIES14_MODELS:
            for mode in ("normal", "night_setback", "setback"):
                with self.subTest(model=model, mode=mode):
                    entity, gateway = _entity(
                        model, hvac_mode="heat", heater_mode=mode
                    )
                    await entity.async_set_temperature(temperature=24.0)
                    self.assertEqual([call[1] for call in gateway.calls], ["set_temperature"])
                    self.assertEqual(gateway.calls[0][2]["heater_mode"], mode)
                    self.assertEqual(entity._fhk_heater_mode, mode)

    async def test_mode_write_failure_does_not_claim_that_off_was_left(self):
        for source in ("native", "external"):
            with self.subTest(source=source):
                entity, gateway = _entity(source=source, fail_command="set_hvac_mode")
                with self.assertRaisesRegex(_HomeAssistantError, "simulated transport failure"):
                    await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(
                    [call[1] for call in gateway.calls],
                    ["set_temperature", "set_hvac_mode"],
                )
                self.assertEqual(entity._attr_hvac_mode, "off")
                self.assertEqual(entity._fhk_heater_mode, "off")
                self.assertEqual(entity._target_temperature, 25.0)
                self.assertEqual(entity._last_sent_target_temperature, 25.0)
                self.assertEqual(
                    entity._last_sent_room_temperature,
                    21.6 if source == "external" else None,
                )
                self.assertEqual(
                    entity._last_controller_telegram,
                    "70-9F-75-0E" if source == "external" else "70-9F-00-0E",
                )
                self.assertEqual(entity._last_controller_response, "2026-11-26T16:15:15+00:00")
                self.assertGreater(entity.state_updates, 0)

    async def test_setpoint_write_failure_never_sends_a_mode_change(self):
        entity, gateway = _entity(fail_command="set_temperature")
        with self.assertRaisesRegex(_HomeAssistantError, "simulated transport failure"):
            await entity.async_set_temperature(temperature=25.0)
        self.assertEqual([call[1] for call in gateway.calls], ["set_temperature"])
        self.assertEqual(entity._attr_hvac_mode, "off")
        self.assertEqual(entity._fhk_heater_mode, "off")
        self.assertEqual(entity._target_temperature, 20.0)

    async def test_fhk61_keeps_the_existing_temperature_only_path(self):
        for model in ("FHK61-230V", "FHK61U-230V", "FHK61SSR-230V"):
            with self.subTest(model=model):
                entity, gateway = _entity(model, source="native")
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual([call[1] for call in gateway.calls], ["set_temperature"])
                self.assertEqual(entity._target_temperature, 25.0)
                self.assertEqual(entity._attr_hvac_mode, "heat")

    async def test_battery_valves_only_queue_the_requested_target(self):
        for model in ("FKS-SV", "FKS-HORA"):
            with self.subTest(model=model):
                entity, gateway = _entity(model, source="native")
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(gateway.calls, [])
                self.assertEqual(entity._target_temperature, 25.0)
                self.assertEqual(entity._attr_hvac_mode, "heat")
                self.assertTrue(entity._pending_command)


if __name__ == "__main__":
    unittest.main()
