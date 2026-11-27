"""Native Series-14 HA setpoints default to central controller priority.

Exercise the real priority policy, climate service, restore/update methods,
encoder and option persistence. Framework and gateway stand-ins do not model
RF reception or physical relay switching.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
import unittest

from test_climate_temperature_sync import _wait_for_push
from test_fhk61_family_feedback_runtime import _source_function
from test_fks_sv_room_temperature import INTEGRATION, PKG, _load, const, eep10, room
from test_series14_temperature_mode import (
    _HomeAssistantError, _entity as _mode_entity, _set_temperature as _mode_set_temperature,
)


priority = _load(f"{PKG}.heating_priority", INTEGRATION / "heating_priority.py")
SERIES14_MODELS = ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")
OVERRIDES = priority.CONF_HEATING_PRIORITY_OVERRIDES

_set_temperature = _source_function(
    "climate.py", "async_set_temperature", cls="EltakoClimate",
    globals={
        **_mode_set_temperature.__globals__,
        "default_priority_mode": getattr(priority, "default_priority_mode", None),
        "set_priority_mode": priority.set_priority_mode,
    },
)


def _device(model="FHK14", *, physical="FF-BF-5C-86", **extra):
    return {
        "platform": "climate", "eep": "A5-10-06", "sender_eep": "A5-10-06",
        "id": physical, "sender_id": "FF-A6-04-86", "device_type": model,
        **extra,
    }


def _entity(model="FHK14", *, source="native", selected=None,
            hvac_mode="heat", fail_command=None, restored=None):
    entity, gateway = _mode_entity(
        model, source=source, hvac_mode=hvac_mode,
        heater_mode="off" if hvac_mode == "off" else "normal",
        fail_command=fail_command,
    )
    entity.device_config.pop("priority")
    entity.last_state = restored
    entity.async_set_temperature = MethodType(_set_temperature, entity)
    hass = entity.hass
    if selected is not None:
        hass.options[OVERRIDES] = {entity.device_config["id"]: selected}
    entry = SimpleNamespace(options=dict(hass.options))
    writes = []

    def update_entry(updated_entry, *, options):
        assert updated_entry is entry
        entry.options = options
        hass.options = options
        writes.append(options)

    hass.config_entries = SimpleNamespace(
        async_get_entry=lambda entry_id: entry,
        async_update_entry=update_entry,
    )
    return entity, gateway, entry, writes


class Series14DefaultPriorityPolicyTests(unittest.TestCase):
    def test_default_helper_distinguishes_native_external_and_61_series(self):
        default = getattr(priority, "default_priority_mode", None)
        self.assertTrue(callable(default), "The shared default-priority policy is required")
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                device = _device(model)
                self.assertEqual(default(device, {}), "central")
                self.assertEqual(default({**device, "heating_control_mode": "learned_sensor"}, {}), "central")
                self.assertEqual(default({**device, "heating_control_mode": "ha_external"}, {}), "auto")
                external = room.set_room_temperature_override(
                    {}, device["id"], const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.room"
                )
                self.assertEqual(default(device, external), "auto")
                self.assertEqual(
                    default({**device, "heating_control_mode": "learned_sensor"}, external),
                    "auto",
                )
        for model in ("FHK61-230V", "FHK61U-230V", "FHK61SSR-230V", "FTR55ESB"):
            with self.subTest(model=model):
                self.assertEqual(default(_device(model), {}), "auto")
        self.assertEqual(default({**_device(), "platform": "sensor"}, {}), "auto")

    def test_native_missing_or_empty_priority_uses_central(self):
        for model in SERIES14_MODELS:
            for extra in ({}, {"priority": None}, {"priority": ""}, {"priority": "  "}):
                with self.subTest(model=model, config=extra):
                    self.assertEqual(priority.priority_mode(_device(model, **extra), {}), "central")

    def test_unrecognized_existing_yaml_priority_keeps_the_automatic_fallback(self):
        for model in (*SERIES14_MODELS, "FHK61-230V"):
            for invalid in ("invalid", "central", 0, False):
                for extra in ({"priority": invalid}, {"raw": {"priority": invalid}}):
                    with self.subTest(model=model, config=extra):
                        self.assertEqual(priority.priority_mode(_device(model, **extra), {}), "auto")

    def test_explicit_ui_choices_override_yaml_and_survive_default_change(self):
        device = _device(priority="ha")
        for selected in ("auto", "manual", "limit", "central"):
            with self.subTest(selected=selected):
                options = {OVERRIDES: {device["id"]: selected}}
                self.assertEqual(priority.priority_mode(device, options), selected)

    def test_explicit_yaml_priority_is_kept_in_top_level_and_raw_config(self):
        for configured, expected in (("auto", "auto"), ("ha", "central"), ("limit", "limit"), ("manual", "manual")):
            for location in ("top", "raw"):
                with self.subTest(configured=configured, location=location):
                    extra = {"priority": configured} if location == "top" else {"raw": {"priority": configured}}
                    device = _device(**extra)
                    self.assertEqual(priority.priority_mode(device, {}), expected)
                    self.assertEqual(
                        priority.priority_mode(device, {OVERRIDES: {device["id"]: "invalid"}}),
                        expected,
                    )

    def test_external_and_fhk61_without_explicit_choice_stay_automatic(self):
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                device = _device(model)
                options = room.set_room_temperature_override(
                    {}, device["id"], const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.room"
                )
                self.assertEqual(priority.priority_mode(device, options), "auto")
        self.assertEqual(priority.priority_mode(_device("FHK61-230V"), {}), "auto")

    def test_priority_lookup_uses_physical_id_and_keeps_channels_independent(self):
        modes = ("central", "auto", "manual", "limit")
        devices = [_device("F4HK14", physical=f"FF-BF-5C-C{i}", sender_id=f"FF-A6-04-C{i}") for i in range(4)]
        options = {OVERRIDES: {device["id"]: selected for device, selected in zip(devices, modes)}}
        options[OVERRIDES][devices[0]["sender_id"]] = "manual"
        for device, selected in zip(devices, modes):
            with self.subTest(physical=device["id"]):
                self.assertEqual(priority.priority_mode(device, options), selected)
        self.assertEqual(priority.priority_mode({**devices[0], "id": "ff:bf:5c:c0"}, options), "central")


class Series14DefaultPriorityRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_without_selection_sends_central_db0(self):
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                entity, gateway, _entry, writes = _entity(model)
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(gateway.calls[0][2]["controller_priority"], "ha")
                self.assertEqual(entity._last_controller_telegram, "70-9F-00-08")
                self.assertEqual(writes, [])

    async def test_manual_to_new_native_target_sends_and_persists_central(self):
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                entity, gateway, entry, writes = _entity(model, selected="manual")
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(gateway.calls[0][2]["controller_priority"], "ha")
                self.assertEqual(entity._last_controller_telegram, "70-9F-00-08")
                self.assertEqual(entry.options[OVERRIDES][entity.device_config["id"]], "central")
                self.assertEqual(len(writes), 1)

    async def test_manual_to_new_fhk61_target_still_resumes_auto(self):
        entity, gateway, entry, writes = _entity("FHK61-230V", selected="manual")
        await entity.async_set_temperature(temperature=25.0)
        command = gateway.calls[0][2]
        self.assertEqual(command["controller_priority"], "auto")
        data = eep10.encode_a5_10_06_room_control_data(
            target_temperature=command["temperature"], priority=command["controller_priority"],
            controller_profile="fhk61_230v",
        )
        self.assertEqual(data[-1], 0x0E)
        self.assertEqual(entry.options[OVERRIDES][entity.device_config["id"]], "auto")
        self.assertEqual(len(writes), 1)

    async def test_external_path_keeps_auto_with_stale_native_choice(self):
        for selected in (None, "central", "manual"):
            with self.subTest(selected=selected):
                entity, gateway, _entry, writes = _entity(source="external", selected=selected)
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(gateway.calls[0][2]["controller_priority"], "auto")
                self.assertEqual(gateway.calls[0][2]["controller_profile"], "series14_f64")
                self.assertEqual(entity._last_controller_telegram, "00-9F-75-0F")
                self.assertEqual(writes, [])

    async def test_ui_external_overrides_stale_eedtoy_mode_and_never_sends_native_fallback(self):
        for external in (21.6, None):
            with self.subTest(external=external):
                entity, gateway, _entry, writes = _entity(source="external", selected="central")
                entity.device_config["heating_control_mode"] = "learned_sensor"
                entity.hass.states.set("sensor.room", external)
                if external is None:
                    with self.assertRaisesRegex(_HomeAssistantError, "[Ee]xterne.*Raumtemperatur"):
                        await entity.async_set_temperature(temperature=25.0)
                    self.assertEqual(gateway.calls, [])
                    self.assertIsNone(entity._last_controller_telegram)
                    self.assertIsNone(entity._actual_temperature_source)
                else:
                    await entity.async_set_temperature(temperature=25.0)
                    command = gateway.calls[0][2]
                    self.assertEqual(command["controller_priority"], "auto")
                    self.assertEqual(command["controller_profile"], "series14_f64")
                    self.assertEqual(command["current_temperature"], external)
                    self.assertEqual(entity._last_controller_telegram, "00-9F-75-0F")
                self.assertEqual(writes, [])

    async def test_ui_native_overrides_stale_eedtoy_external_mode(self):
        for model in SERIES14_MODELS:
            with self.subTest(model=model):
                entity, gateway, entry, writes = _entity(model, source="native")
                entity.device_config["heating_control_mode"] = "ha_external"
                self.assertEqual(
                    priority.heating_control_mode(entity.device_config, entry.options),
                    "learned_sensor",
                )
                await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(gateway.calls[0][2]["controller_priority"], "ha")
                self.assertIsNone(gateway.calls[0][2]["current_temperature"])
                self.assertEqual(entity._last_controller_telegram, "70-9F-00-08")
                self.assertEqual(writes, [])

    async def test_failed_target_or_mode_send_does_not_persist_central(self):
        for command in ("set_temperature", "set_hvac_mode"):
            with self.subTest(failed_command=command):
                entity, _gateway, entry, writes = _entity(
                    selected="manual", hvac_mode="off", fail_command=command
                )
                with self.assertRaisesRegex(_HomeAssistantError, "simulated transport failure"):
                    await entity.async_set_temperature(temperature=25.0)
                self.assertEqual(entry.options[OVERRIDES][entity.device_config["id"]], "manual")
                self.assertEqual(writes, [])

    async def test_selected_central_survives_restore_and_native_temperature_refresh(self):
        restored = SimpleNamespace(state="heat", attributes={
            "temperature": 24.5, "preset_mode": "home",
            "interne_aktor_temperatur": 21.6, "genuine_current_temperature": True,
        })
        entity, gateway, entry, writes = _entity(selected="central", restored=restored)
        await entity.async_added_to_hass()
        self.assertEqual(entity._target_temperature, 24.5)
        self.assertEqual(entity._priority_send_keyword(), "ha")
        entity._internal_temperature = 22.0
        entity._handle_temperature_options_updated(gateway.entry_id)
        await _wait_for_push(entity)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(gateway.calls[0][2]["controller_priority"], "ha")
        self.assertEqual(entity._last_controller_telegram, "70-9C-00-08")
        self.assertEqual(entry.options[OVERRIDES][entity.device_config["id"]], "central")
        self.assertEqual(writes, [])

    async def test_manual_resume_persistence_does_not_change_another_channel(self):
        entity, _gateway, entry, writes = _entity("F4HK14", selected="manual")
        other_id = "FF-BF-5C-C1"
        entry.options[OVERRIDES][other_id] = "auto"
        await entity.async_set_temperature(temperature=25.0)
        self.assertEqual(entry.options[OVERRIDES][entity.device_config["id"]], "central")
        self.assertEqual(entry.options[OVERRIDES][other_id], "auto")
        self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
