"""External F64 climate routing, missing-input handling and send ordering."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import unittest

from test_climate_temperature_sync import _wait_for_push
from test_fks_sv_room_temperature import const, room
from test_series14_temperature_mode import _HomeAssistantError, _entity


class Series14ExternalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_setpoint_and_sensor_update_share_the_f64_profile(self):
        entity, gateway = _entity(source="external", hvac_mode="heat", heater_mode="normal")
        await entity.async_set_temperature(temperature=25.0)
        self.assertEqual(gateway.calls[-1][2].get("controller_profile"), "series14_f64")
        self.assertEqual(entity._last_controller_telegram, "00-9F-75-0F")
        entity.hass.states.set("sensor.room", 21.8)
        entity._handle_external_temperature_state_event(None)
        await _wait_for_push(entity)
        self.assertEqual(gateway.calls[-1][2].get("controller_profile"), "series14_f64")
        self.assertEqual(gateway.calls[-1][2]["temperature"], 25.0)
        self.assertEqual(entity._last_controller_telegram, "00-9F-74-0F")

    async def test_periodic_refresh_repeats_a_constant_value_but_not_missing_input(self):
        entity, gateway = _entity(source="external", hvac_mode="heat", heater_mode="normal")
        await entity.async_added_to_hass()
        self.assertEqual(len(entity.hass.intervals), 1)
        refresh, interval = entity.hass.intervals[0]
        self.assertEqual(interval, timedelta(minutes=15))
        refresh(None)  # No restored/user target has been transmitted yet.
        await _wait_for_push(entity)
        self.assertEqual(gateway.calls, [])
        self.assertIsNone(entity._last_f64_target_tx)
        await entity.async_set_temperature(temperature=25.0)
        refresh(None)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(gateway.calls[-1][2]["temperature"], 25.0)
        self.assertEqual(gateway.calls[-1][2]["current_temperature"], 21.6)
        self.assertEqual(entity._last_controller_telegram, "00-9F-75-0F")
        entity.hass.states.set("sensor.room", None)
        refresh(None)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 2)
        self.assertTrue(entity._last_error)

    async def test_refresh_is_removed_on_source_change_and_unload(self):
        entity, gateway = _entity(source="external", hvac_mode="heat", heater_mode="normal")
        await entity.async_added_to_hass()
        refresh, _interval = entity.hass.intervals[0]
        entity.hass.options = room.set_room_temperature_override(
            entity.hass.options, entity.device_config["id"], const.ROOM_TEMPERATURE_SOURCE_NATIVE
        )
        entity._handle_temperature_options_updated(gateway.entry_id)
        await _wait_for_push(entity)
        self.assertEqual(entity.hass.intervals, [])
        previous_calls = len(gateway.calls)
        refresh(None)  # An already queued callback must also honor the new source.
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), previous_calls)

        active, _gateway = _entity(source="external")
        await active.async_added_to_hass()
        self.assertEqual(len(active.hass.intervals), 1)
        await active.async_will_remove_from_hass()
        self.assertEqual(active.hass.intervals, [])
        self.assertEqual(active.hass.trackers, [])
        self.assertIsNone(active._remove_room_temperature_refresh_listener)

    async def test_refresh_does_not_apply_to_native_fhk_fhk61_or_battery_valves(self):
        for model, source in (("FHK14", "native"), ("FHK61-230V", "native"), ("FKS-SV", "external")):
            with self.subTest(model=model, source=source):
                entity, _gateway = _entity(model, source=source)
                await entity.async_added_to_hass()
                self.assertEqual(entity.hass.intervals, [])

    async def test_missing_external_input_rejects_target_before_any_send(self):
        entity, gateway = _entity(source="external")
        # A native reading does not mean this F64 sender is learned as F65.
        entity._internal_temperature = 21.6
        entity._has_genuine_current_temperature = True
        entity.hass.states.set("sensor.room", None)
        with self.assertRaisesRegex(_HomeAssistantError, "[Ee]xterne.*Raumtemperatur"):
            await entity.async_set_temperature(temperature=25.0)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(entity._target_temperature, 20.0)
        self.assertEqual(entity._attr_hvac_mode, "off")
        self.assertIsNone(entity._last_controller_telegram)
        self.assertIsNone(entity._current_temperature)
        self.assertIsNone(entity._actual_temperature_source)
        self.assertEqual(entity._temperature_source_status, "error")
        self.assertTrue(entity._last_error)

    async def test_background_input_loss_sends_nothing_and_recovery_resumes_f64(self):
        entity, gateway = _entity(source="external", hvac_mode="heat", heater_mode="normal")
        await entity.async_set_temperature(temperature=25.0)
        previous_telegram = entity._last_controller_telegram
        entity.hass.states.set("sensor.room", None)
        entity._handle_external_temperature_state_event(None)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(entity._last_controller_telegram, previous_telegram)
        self.assertIsNone(entity._actual_temperature_source)
        self.assertIsNone(entity._current_temperature)
        self.assertEqual(entity._temperature_source_status, "error")
        self.assertTrue(entity._last_error)
        entity.hass.states.set("sensor.room", 21.6)
        entity._handle_external_temperature_state_event(None)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(gateway.calls[-1][2].get("controller_profile"), "series14_f64")
        self.assertEqual(entity._last_controller_telegram, "00-9F-75-0F")
        self.assertIsNone(entity._last_error)

    async def test_sensor_change_during_target_send_uses_the_new_target(self):
        entity, gateway = _entity(source="external", hvac_mode="heat", heater_mode="normal")
        transport_lock = asyncio.Lock()
        started = asyncio.Event()
        release = asyncio.Event()
        queued = []
        sent = []

        async def send(device, command, **kwargs):
            queued.append((command, dict(kwargs)))
            async with transport_lock:
                if not sent:
                    started.set()
                    await release.wait()
                sent.append((command, dict(kwargs)))
                return True

        gateway.async_send_actuator_command = send
        requested = asyncio.create_task(entity.async_set_temperature(temperature=25.0))
        await asyncio.wait_for(started.wait(), 1.0)
        entity.hass.states.set("sensor.room", 21.8)
        entity._handle_external_temperature_state_event(None)
        # Let the background push reach its serialization point before TX ends.
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(requested, 1.0)
        await _wait_for_push(entity)
        self.assertEqual([kwargs["temperature"] for _, kwargs in sent], [25.0, 25.0])
        self.assertEqual([kwargs["current_temperature"] for _, kwargs in sent], [21.6, 21.8])
        self.assertEqual(entity._target_temperature, 25.0)
        self.assertEqual(entity._last_sent_target_temperature, 25.0)
        self.assertEqual(entity._last_controller_telegram, "00-9F-74-0F")


if __name__ == "__main__":
    unittest.main()
