"""Isolated runtime regressions for FKS-SV and FHK/FAE room temperatures.

Execute the actual climate methods with a fake HA state machine and gateway.
No USB devices or Home Assistant installation are required in CI.
"""
from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest

from test_fks_sv_room_temperature import INTEGRATION, room, eep10, eep20, const, _load, PKG

priority = _load(f"{PKG}.heating_priority", INTEGRATION / "heating_priority.py")


class _Base:
    async def async_added_to_hass(self):
        self.added_to_hass = True

    async def async_get_last_state(self):
        return self.last_state

    def schedule_update_ha_state(self):
        self.state_updates += 1


class _Modes:
    OFF = "off"
    HEAT = "heat"


class _States:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, unit="°C"):
        self.values[key] = None if value is None else SimpleNamespace(
            state=str(value), attributes={"unit_of_measurement": unit}
        )


class _FakeHA:
    def __init__(self, options):
        self.options = options
        self.states = _States()
        self.config_entries = SimpleNamespace(
            async_get_entry=lambda entry_id: SimpleNamespace(options=self.options)
        )
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.tasks = []
        self.trackers = []

    def async_create_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


class _FakeGateway:
    entry_id = "test-entry"
    last_send_error = None

    def __init__(self, hass):
        self.hass = hass
        self.calls = []
        self.valve_calls = []
        self.block_first = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def async_send_actuator_command(self, device, command, **kwargs):
        self.calls.append((device, command, dict(kwargs)))
        if self.block_first and len(self.calls) == 1:
            self.started.set()
            await self.release.wait()
        return True

    async def async_send_fks_sv_control_response(self, device, **kwargs):
        self.valve_calls.append((device, dict(kwargs)))
        return True


def _register_event_listener(hass, entities, handler):
    item = (tuple(entities), handler)
    hass.trackers.append(item)
    return lambda: hass.trackers.remove(item) if item in hass.trackers else None


def _extract_method_class():
    source = (INTEGRATION / "climate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    original = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EltakoClimate"
    )
    needed = {
        "async_added_to_hass",
        "_entry_options",
        "_selected_priority",
        "_priority_send_keyword",
        "_priority_manual_active",
        "_on_heating_priority_changed",
        "_read_external_temperature",
        "_native_a5_10_06_display_temperature",
        "_refresh_room_temperature_state",
        "_a5_10_06_outgoing_room_temperature",
        "_schedule_a5_10_06_room_temperature_push",
        "_async_flush_a5_10_06_room_temperature_push",
        "_async_push_a5_10_06_room_temperature",
        "_rebind_external_temperature_listener",
        "_handle_external_temperature_state_event",
        "_handle_temperature_options_updated",
        "_fks_sv_controller_data",
        "_async_reply_fks_sv_control",
    }
    selected = [
        node for node in original.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in needed
    ]
    if {x.name for x in selected} != needed:
        raise AssertionError("Missing an expected climate method")
    cls = ast.ClassDef(
        name="ClimateUnderTest",
        bases=[ast.Name(id="_Base", ctx=ast.Load())],
        keywords=[],
        body=selected,
        decorator_list=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    ns = {
        "_Base": _Base,
        "Any": Any,
        "HVACMode": _Modes,
        "PRESET_HOME": "home",
        "PRESET_SLEEP": "sleep",
        "PRESET_ECO": "eco",
        "ROOM_TEMPERATURE_SOURCE_EXTERNAL": const.ROOM_TEMPERATURE_SOURCE_EXTERNAL,
        "ROOM_TEMPERATURE_SOURCE_NATIVE": const.ROOM_TEMPERATURE_SOURCE_NATIVE,
        "SIGNAL_ROOM_TEMPERATURE_UPDATED": const.SIGNAL_ROOM_TEMPERATURE_UPDATED,
        "SIGNAL_HEATING_PRIORITY_TX": priority.SIGNAL_HEATING_PRIORITY_TX,
        "supports_heating_priority": priority.supports_heating_priority,
        "heating_control_mode": priority.heating_control_mode,
        "priority_mode": priority.priority_mode,
        "set_priority_mode": priority.set_priority_mode,
        "resolve_room_temperature_config": room.resolve_room_temperature_config,
        "select_numeric_room_temperature": room.select_numeric_room_temperature,
        "temperature_to_celsius": room.temperature_to_celsius,
        "encode_a5_10_06_room_control_data": eep10.encode_a5_10_06_room_control_data,
        "encode_a5_20_01_temperature_setpoint_data": eep20.encode_a5_20_01_temperature_setpoint_data,
        "encode_a5_20_01_valve_position_data": eep20.encode_a5_20_01_valve_position_data,
        "_device_option": lambda device, key, default=None: device.get(key, default),
        "_now_iso": lambda: "2026-11-17T07:00:00+00:00",
        "_LOGGER": logging.getLogger("eltako-room-temp-test"),
        "async_track_state_change_event": _register_event_listener,
        "async_dispatcher_connect": lambda *args: lambda: None,
        # Match homeassistant.core.callback: dispatcher and state event handlers
        # must be explicitly marked as safe to execute on HA's event loop.
        "callback": lambda func: setattr(func, "_hass_callback", True) or func,
    }
    exec(compile(module, str(INTEGRATION / "climate.py"), "exec"), ns)
    return ns["ClimateUnderTest"]


CLIMATE = _extract_method_class()


def make_climate(kind, *, native=None, external=20.0, source="external", restored=None):
    device = {
        "platform": "climate",
        "id": "01-02-03-04",
        "sender_id": "00-00-B0-01",
        "eep": "A5-20-01" if kind == "FKS-SV" else "A5-10-06",
        "device_type": kind,
        "name": kind + " Test",
        "priority": "ha",
    }
    options = room.set_room_temperature_override(
        {}, device["id"], source,
        "sensor.room" if source == "external" else None,
    )
    hass = _FakeHA(options)
    hass.states.set("sensor.room", external)
    gateway = _FakeGateway(hass)
    e = CLIMATE()
    e.hass = hass
    e.gateway = gateway
    e.device_config = device
    e.last_state = restored
    e.added_to_hass = False
    e.state_updates = 0
    e._has_room_temperature_assignment = True
    e._room_temperature_device_kind = room.room_temperature_device_kind(device)
    e._is_fks_sv = kind == "FKS-SV"
    e._is_fhk14 = kind in ("FHK14", "F4HK14")
    e._is_fae14lpr = kind in ("FAE14LPR", "FAE14SSR")
    e._target_temperature = 21.0
    e._attr_min_temp = 8.0 if e._is_fks_sv else 16.0
    e._attr_max_temp = 28.0 if e._is_fks_sv else 25.0
    e._attr_hvac_mode = "heat"
    e._attr_preset_mode = "home"
    e._attr_preset_modes = ["home", "sleep", "eco"]
    e._fhk_heater_mode = "normal"
    e._has_genuine_current_temperature = False
    e._internal_temperature = native
    e._current_temperature = None
    e._external_temperature = None
    e._configured_temperature_source = "native"
    e._temperature_source_status = "error"
    e._temperature_config_origin = "default"
    e._actual_temperature_source = None
    e._external_temperature_entity = None
    e._used_room_temperature = None
    e._last_sent_room_temperature = None
    e._last_sent_target_temperature = None
    e._last_controller_telegram = None
    e._last_controller_response = None
    e._last_error = None
    e._last_tx = None
    e._pending_command = False
    e._successful_replies = 0
    e._room_temperature_push_task = None
    e._room_temperature_push_pending = False
    e._remove_temperature_options_listener = None
    e._remove_external_temperature_listener = None
    e._remove_heating_priority_listener = None
    return e, gateway, hass


async def _wait_for_push(e):
    task = e._room_temperature_push_task
    if task is not None:
        await asyncio.wait_for(task, 2.0)


class RoomTemperatureRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_source_change_pushes_without_target_change(self):
        for kind in ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR"):
            with self.subTest(kind=kind):
                e, gateway, hass = make_climate(kind, external=20.0)
                await e.async_added_to_hass()
                self.assertEqual(len(gateway.calls), 0)
                hass.states.set("sensor.room", 22.5)
                e._handle_external_temperature_state_event(None)
                await _wait_for_push(e)
                self.assertEqual(len(gateway.calls), 1)
                _, command, kwargs = gateway.calls[0]
                self.assertEqual(command, "set_temperature")
                self.assertEqual(kwargs["temperature"], 21.0)
                self.assertEqual(kwargs["current_temperature"], 22.5)
                self.assertEqual(e._current_temperature, 22.5)
                self.assertEqual(e._last_sent_room_temperature, 22.5)

    async def test_rapid_changes_replay_last_update_after_busy_send(self):
        e, gateway, hass = make_climate("FHK14", external=20.0)
        await e.async_added_to_hass()
        gateway.block_first = True
        e._handle_temperature_options_updated(gateway.entry_id)
        await asyncio.wait_for(gateway.started.wait(), 1.0)
        for value in (21.0, 22.0, 23.5):
            hass.states.set("sensor.room", value)
            e._handle_external_temperature_state_event(None)
        gateway.release.set()
        await _wait_for_push(e)
        self.assertEqual(len(gateway.calls), 2)
        self.assertEqual(gateway.calls[-1][2]["current_temperature"], 23.5)
        self.assertEqual(gateway.calls[-1][2]["temperature"], 21.0)
        self.assertFalse(e._room_temperature_push_pending)

    async def test_repeated_unchanged_state_does_not_trigger_send(self):
        e, gateway, hass = make_climate("FAE14LPR", external=19.5)
        await e.async_added_to_hass()
        e._handle_external_temperature_state_event(None)
        self.assertEqual(len(gateway.calls), 0)
        self.assertIsNone(e._room_temperature_push_task)

    async def test_restart_restores_mode_and_syncs_valid_external_temperature(self):
        for state, preset, expected_mode in (
            ("heat", "sleep", "night_setback"),
            ("heat", "eco", "setback"),
            ("off", "home", "off"),
        ):
            with self.subTest(mode=state, preset=preset):
                restored = SimpleNamespace(
                    state=state,
                    attributes={
                        "temperature": 21.0,
                        "preset_mode": preset,
                        "current_temperature": None,
                    },
                )
                e, gateway, hass = make_climate(
                    "FHK14", external=21.5, restored=restored
                )
                await e.async_added_to_hass()
                await _wait_for_push(e)
                self.assertEqual(len(gateway.calls), 1)
                self.assertEqual(gateway.calls[0][2]["heater_mode"], expected_mode)
                self.assertEqual(gateway.calls[0][2]["temperature"], 21.0)
                self.assertEqual(gateway.calls[0][2]["current_temperature"], 21.5)

    async def test_missing_external_source_switches_to_native_control_without_fake_temp(self):
        e, gateway, hass = make_climate("FHK14", external=22.0)
        await e.async_added_to_hass()
        hass.states.set("sensor.room", None)
        e._handle_external_temperature_state_event(None)
        await _wait_for_push(e)
        self.assertIsNone(e._current_temperature)
        self.assertEqual(e._temperature_source_status, "fallback")
        self.assertIsNone(gateway.calls[-1][2]["current_temperature"])

    async def test_negative_external_sensor_is_not_shown_as_protocol_clamp(self):
        e, gateway, hass = make_climate("FAE14LPR", external=-5.0)
        await e.async_added_to_hass()
        e._handle_temperature_options_updated(gateway.entry_id)
        await _wait_for_push(e)
        self.assertEqual(e._current_temperature, -5.0)
        self.assertEqual(gateway.calls[-1][2]["current_temperature"], 0.0)

    async def test_fks_sv_uses_selected_temperature_only_on_receive_window(self):
        e, gateway, hass = make_climate("FKS-SV", native=19.0, external=22.0)
        await e.async_added_to_hass()
        self.assertEqual(e._current_temperature, 22.0)
        hass.states.set("sensor.room", 23.0)
        e._handle_external_temperature_state_event(None)
        self.assertEqual(len(gateway.calls), 0)
        self.assertEqual(len(gateway.valve_calls), 0)
        await e._async_reply_fks_sv_control()
        self.assertEqual(len(gateway.valve_calls), 1)
        self.assertEqual(gateway.valve_calls[0][1]["room_temperature"], 23.0)
        self.assertEqual(gateway.valve_calls[0][1]["target_temperature"], 21.0)
        self.assertEqual(e._current_temperature, 23.0)
        self.assertEqual(e._last_sent_room_temperature, 23.0)

    async def test_fks_sv_invalid_external_falls_back_to_physical_valve(self):
        e, gateway, hass = make_climate("FKS-SV", native=18.5, external=21.0)
        await e.async_added_to_hass()
        hass.states.set("sensor.room", None)
        e._handle_external_temperature_state_event(None)
        self.assertEqual(e._current_temperature, 18.5)
        self.assertEqual(e._temperature_source_status, "fallback")
        await e._async_reply_fks_sv_control()
        self.assertEqual(gateway.valve_calls[0][1]["room_temperature"], 18.5)

    async def test_native_a5_10_06_unmeasured_value_is_not_40_or_0(self):
        for kind in ("FHK14", "FAE14LPR"):
            with self.subTest(kind=kind):
                e, _, _ = make_climate(kind, source=const.ROOM_TEMPERATURE_SOURCE_NATIVE)
                await e.async_added_to_hass()
                self.assertIsNone(e._native_a5_10_06_display_temperature())
                self.assertIsNone(e._current_temperature)
                e._internal_temperature = 19.0
                e._has_genuine_current_temperature = True
                self.assertEqual(e._native_a5_10_06_display_temperature(), 19.0)


class OptionsFlowTemperaturePropagationTests(unittest.IsolatedAsyncioTestCase):
    """The actual options-update listener must not await diagnostics first."""

    async def test_switch_to_external_sends_without_setpoint_change_even_if_diagnostics_fails(self):
        source = (INTEGRATION / "__init__.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(INTEGRATION / "__init__.py"))
        method = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_async_options_update_listener"
        )
        module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
        propagated = []
        diagnostics_started = []
        async def failing_diagnostics(hass, enabled):
            diagnostics_started.append(enabled)
            raise RuntimeError("diagnostics service unavailable")
        context = {
            "DOMAIN": "eltako_sensors_actuators",
            "CONF_DIAGNOSTICS_ENABLED": "diagnostics_enabled",
            "CONF_RELOAD_AFTER_SAVE": "reload_after_save",
            "SIGNAL_ROOM_TEMPERATURE_UPDATED": "eltako_room_temperature_updated",
            "async_dispatcher_send": lambda hass, signal, entry: propagated.append((signal, entry)),
            "async_set_diagnostics_enabled": failing_diagnostics,
            "_LOGGER": logging.getLogger("eltako-options-test"),
        }
        exec(compile(module, str(INTEGRATION / "__init__.py"), "exec"), context)
        entry = SimpleNamespace(entry_id="test-entry", options={})
        hass = SimpleNamespace(config_entries=SimpleNamespace(
            async_entries=lambda domain: [entry],
        ))
        await context["_async_options_update_listener"](hass, entry)
        self.assertEqual(propagated, [("eltako_room_temperature_updated", "test-entry")])
        self.assertEqual(diagnostics_started, [True])

    async def test_switch_internal_to_external_pushes_new_sensor_immediately(self):
        for kind in ("FHK14", "FAE14LPR"):
            with self.subTest(kind=kind):
                e, gateway, hass = make_climate(
                    kind,
                    external=19.25,
                    source=const.ROOM_TEMPERATURE_SOURCE_NATIVE,
                )
                await e.async_added_to_hass()
                self.assertIsNone(e._current_temperature)
                self.assertEqual(len(gateway.calls), 0)

                hass.options = room.set_room_temperature_override(
                    hass.options, e.device_config["id"],
                    const.ROOM_TEMPERATURE_SOURCE_EXTERNAL, "sensor.room"
                )
                e._handle_temperature_options_updated(gateway.entry_id)
                self.assertEqual(e._current_temperature, 19.25)
                await _wait_for_push(e)
                self.assertEqual(len(gateway.calls), 1)
                self.assertEqual(gateway.calls[0][1], "set_temperature")
                self.assertEqual(gateway.calls[0][2]["temperature"], 21.0)
                self.assertEqual(gateway.calls[0][2]["current_temperature"], 19.25)
                self.assertEqual(e._last_sent_room_temperature, 19.25)


class ClimateEventLoopCallbackTests(unittest.TestCase):
    """Regression: Home Assistant must not route temperature callbacks to an executor."""

    def test_temperature_handlers_are_marked_as_ha_callbacks(self):
        self.assertTrue(
            getattr(CLIMATE._handle_temperature_options_updated, "_hass_callback", False),
            "Dispatcher callback must run on the Home Assistant event loop",
        )
        self.assertTrue(
            getattr(CLIMATE._handle_external_temperature_state_event, "_hass_callback", False),
            "State change callback must run on the Home Assistant event loop",
        )

    def test_live_entity_updates_do_not_require_setpoint_changes(self):
        source = (INTEGRATION / "climate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        climate_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "EltakoClimate"
        )
        handlers = {
            node.name: node for node in climate_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name in {
                "_handle_temperature_options_updated",
                "_handle_external_temperature_state_event",
            }
        }
        self.assertEqual(len(handlers), 2)
        for name, method in handlers.items():
            self.assertTrue(
                any(isinstance(d, ast.Name) and d.id == "callback" for d in method.decorator_list),
                f"{name} must use @callback; otherwise HA dispatches it via executor",
            )


class RoomTemperatureMenuTests(unittest.TestCase):
    """Ensure all dynamic menu slots are translated and directly clickable."""

    def test_actuator_selector_is_a_menu_not_a_radio_form(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        flow = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "EltakoSensorsActuatorsOptionsFlow"
        )
        method = next(
            node for node in flow.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_step_room_temperature_assignment"
        )
        method_source = ast.get_source_segment(source, method)
        self.assertIn("self.async_show_menu(", method_source)
        self.assertNotIn("self.async_show_form(", method_source)
        self.assertIn("room_temperature_device_", method_source)

    def test_menu_device_selection_uses_direct_step_callback(self):
        source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
        self.assertIn("async def _async_select_room_temperature_menu_device(", source)
        self.assertIn('if name.startswith("async_step_room_temperature_device_"):', source)
        self.assertIn("return await self.async_step_room_temperature_source()", source)

    def test_all_slot_and_page_labels_have_translations(self):
        import json
        for filename in ("strings.json", "translations/de.json", "translations/en.json"):
            with self.subTest(filename=filename):
                data = json.loads((INTEGRATION / filename).read_text(encoding="utf-8"))
                menu = data["options"]["step"]["room_temperature_assignment"]["menu_options"]
                for slot in range(12):
                    key = f"room_temperature_device_{slot}"
                    self.assertEqual(menu[key], "{device_" + str(slot) + "}")
                for key in ("room_temperature_page_previous", "room_temperature_page_next", "room_temperature_back_main"):
                    self.assertTrue(menu[key])


class FksSvSingleTemperatureEntityTests(unittest.TestCase):
    def test_real_fks_sv_creates_no_duplicate_temperature_sensor(self):
        source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_a5_20_01_entities"
        )
        mod = ast.fix_missing_locations(
            ast.Module(body=[func], type_ignores=[])
        )
        class StubSensor:
            def __init__(self, gateway, device, key, suffix, cls, unit, **kwargs):
                self.key = key

        scope = {
            "Any": Any,
            "SensorEntity": StubSensor,
            "EltakoYamlValueSensor": StubSensor,
            "SensorDeviceClass": SimpleNamespace(TEMPERATURE="temperature"),
            "UnitOfTemperature": SimpleNamespace(CELSIUS="°C"),
            "PERCENTAGE": "%",
            "is_fks_sv_device": room.is_fks_sv_device,
        }
        exec(compile(mod, str(INTEGRATION / "sensor.py"), "exec"), scope)
        factory = scope["_a5_20_01_entities"]
        fks = {"platform": "climate", "id": "01-02-03-04", "eep": "A5-20-01", "device_type": "FKS-SV"}
        other = {**fks, "device_type": "OTHER"}
        self.assertEqual([x.key for x in factory(None, fks)], ["valve_position", "last_seen"])
        self.assertEqual(
            [x.key for x in factory(None, other)],
            ["temperature", "valve_position", "last_seen"],
        )

    def test_duplicate_removal_is_scoped_to_owned_fks_sv_only(self):
        source = (INTEGRATION / "sensor.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        func = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_remove_obsolete_fks_sv_temperature_entities"
        )
        mod = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))
        received = []
        scope = {
            "Any": Any,
            "er": SimpleNamespace(async_get=lambda hass: "registry"),
            "_yaml_entity_unique_id": lambda entry_id, device, suffix: f"{entry_id}:{device['id']}:{suffix}",
            "is_fks_sv_device": room.is_fks_sv_device,
            "_remove_owned_legacy_sensor_entities": lambda registry, entry, ids, label: received.append((registry, ids, label)),
        }
        exec(compile(mod, str(INTEGRATION / "sensor.py"), "exec"), scope)
        fks = {"platform": "climate", "id": "01-02-03-04", "eep": "A5-20-01", "device_type": "FKS-SV"}
        other = {**fks, "id": "01-02-03-05", "device_type": "OTHER"}
        scope["_remove_obsolete_fks_sv_temperature_entities"](None, SimpleNamespace(entry_id="test-entry"), [fks, other])
        self.assertEqual(received[0][1], {"test-entry:01-02-03-04:Temperatur"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
