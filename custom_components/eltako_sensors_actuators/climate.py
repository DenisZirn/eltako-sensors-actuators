from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
try:
    from homeassistant.components.climate.const import HVACAction
except Exception:  # pragma: no cover - older HA compatibility
    HVACAction = None
try:
    from homeassistant.components.climate.const import PRESET_ECO, PRESET_HOME, PRESET_SLEEP
except Exception:  # pragma: no cover - older HA compatibility
    PRESET_HOME = "home"
    PRESET_SLEEP = "sleep"
    PRESET_ECO = "eco"
try:
    from homeassistant.const import PRECISION_TENTHS
except Exception:  # pragma: no cover - older HA compatibility
    PRECISION_TENTHS = 0.1
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.climate import ClimateEntityFeature
    _SUPPORT_TARGET_TEMPERATURE = ClimateEntityFeature.TARGET_TEMPERATURE
    _SUPPORT_PRESET_MODE = ClimateEntityFeature.PRESET_MODE
except Exception:  # pragma: no cover - older HA compatibility
    _SUPPORT_TARGET_TEMPERATURE = 1
    _SUPPORT_PRESET_MODE = 16

from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_platform

_LOGGER = logging.getLogger(__name__)


def _coerce_ha_temperature_to_celsius(
    value: Any,
    *,
    min_c: float = 0.0,
    max_c: float = 40.0,
) -> float | None:
    """Validate the Celsius value handed to the entity by Home Assistant.

    Home Assistant's climate service converts from the installation's display
    unit to ``temperature_unit`` before calling ``async_set_temperature``.
    Because this entity declares Celsius, the value received here is already
    Celsius. A second Fahrenheit heuristic would corrupt legitimate service
    values and is therefore intentionally not performed.
    """
    if value is None:
        return None
    try:
        temp = float(value)
    except (TypeError, ValueError):
        return None
    return max(min_c, min(max_c, temp))


def _device_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in device and device.get(key) is not None:
        return device.get(key)
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return raw.get(key, default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []
    entities = [
        EltakoClimate(gateway, device)
        for device in devices
        if isinstance(device, dict) and normalize_platform(device.get("platform")) == "climate"
    ]
    _LOGGER.info(
        "ELTAKO climate setup entry=%s imported_devices=%s climate_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)


class EltakoClimate(EltakoYamlEntity, ClimateEntity):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.OFF
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 0.5
    _attr_supported_features = _SUPPORT_TARGET_TEMPERATURE

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def precision(self):
        return PRECISION_TENTHS

    @property
    def target_temperature_step(self):
        return 0.5

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._eep = str(device.get("eep") or "").strip().upper()
        self._is_fks_sv = self._eep == "A5-20-01"
        # ELTAKO setpoints and feedback are natively Celsius. Keep this explicit
        # on every instance so no legacy YAML temperature_unit value can replace it.
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS

        if self._is_fks_sv:
            self._attr_min_temp = float(_device_option(device, "min_target_temperature", 8.0) or 8.0)
            self._attr_max_temp = float(_device_option(device, "max_target_temperature", 28.0) or 28.0)
            initial_target = _device_option(
                device,
                "initial_target_temperature",
                _device_option(device, "target_temperature", 20.0),
            )
            try:
                self._target_temperature = float(initial_target)
            except (TypeError, ValueError):
                self._target_temperature = 20.0
            self._target_temperature = max(self._attr_min_temp, min(self._attr_max_temp, self._target_temperature))
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            self._attr_supported_features = _SUPPORT_TARGET_TEMPERATURE | _SUPPORT_PRESET_MODE
            self._attr_preset_modes = [PRESET_HOME, PRESET_SLEEP, PRESET_ECO]
            self._attr_preset_mode = PRESET_HOME
            self._attr_min_temp = float(_device_option(device, "min_target_temperature", 16.0) or 16.0)
            self._attr_max_temp = float(_device_option(device, "max_target_temperature", 25.0) or 25.0)
            # Home Assistant hides the temperature control when a climate
            # entity reports target_temperature=None.  Do not wait for the
            # first FHK actuator response: expose a usable setpoint immediately
            # and replace it later when valid feedback is received.
            initial_target = _device_option(
                device,
                "initial_target_temperature",
                _device_option(device, "target_temperature", 20.0),
            )
            try:
                self._target_temperature = float(initial_target)
            except (TypeError, ValueError):
                self._target_temperature = 20.0
            self._target_temperature = max(
                self._attr_min_temp,
                min(self._attr_max_temp, self._target_temperature),
            )

        self._fhk_heater_mode = "normal"
        self._current_temperature = None
        self._valve_position: int | None = None
        self._pending_command = bool(self._is_fks_sv)
        self._actuator_obstructed: bool | None = None
        self._window_open: bool | None = None
        self._contact_open: bool | None = None
        self._battery_low: bool | None = None
        self._temperature_sensor_failure: bool | None = None
        self._energy_storage_charged: bool | None = None
        self._energy_storage_capacity_sufficient: bool | None = None
        self._last_rx: str | None = None
        self._last_tx: str | None = None
        self._last_teach_in: str | None = None
        self._last_error: str | None = None
        self._successful_replies = 0
        self._control_reply_task = None
        self._teach_in_reply_task = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def current_temperature(self):
        return self._current_temperature

    @property
    def target_temperature(self):
        return self._target_temperature

    @property
    def min_temp(self):
        return self._attr_min_temp

    @property
    def max_temp(self):
        return self._attr_max_temp

    @property
    def hvac_action(self):
        if not self._is_fks_sv or HVACAction is None:
            return None
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._valve_position is not None and self._valve_position > 0:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def extra_state_attributes(self):
        base = dict(super().extra_state_attributes or {})
        fhk_mode_labels = {
            "normal": "Normalbetrieb",
            "night_setback": "Nachtabsenkung",
            "setback": "Absenkbetrieb",
            "off": "Aus / Frostschutz",
        }
        base["betriebsart_de"] = (
            "Heizbetrieb" if self._is_fks_sv and self._attr_hvac_mode == HVACMode.HEAT
            else "Aus" if self._is_fks_sv
            else fhk_mode_labels.get(self._fhk_heater_mode, "Unbekannt")
        )
        base["protokoll_temperatureinheit"] = UnitOfTemperature.CELSIUS
        base["ha_temperatureinheit"] = str(self.hass.config.units.temperature_unit)
        if self._is_fks_sv:
            base.update(
                {
                    "controller_sender_id": self.device_config.get("sender_id"),
                    "room_temperature_entity": _device_option(self.device_config, "room_temperature_entity"),
                    "ventilstellung": self._valve_position,
                    "befehl_ausstehend": self._pending_command,
                    "ventil_blockiert": self._actuator_obstructed,
                    "fenster_offen": self._window_open,
                    "kontakt_offen": self._contact_open,
                    "batterie_niedrig": self._battery_low,
                    "temperaturfehler": self._temperature_sensor_failure,
                    "energiespeicher_geladen": self._energy_storage_charged,
                    "energiereserve_ausreichend": self._energy_storage_capacity_sufficient,
                    "letzter_empfang": self._last_rx,
                    "letzte_antwort": self._last_tx,
                    "letztes_einlernen": self._last_teach_in,
                    "letzter_fehler": self._last_error,
                    "erfolgreiche_antworten": self._successful_replies,
                    "kommunikationsstatus": "verbunden" if self._last_rx else "Warten auf erstes FKS-SV-Telegramm",
                }
            )
        return base

    def _matches_physical_device(self, telegram) -> bool:
        return str(telegram.sender_id).upper() == str(self.device_config.get("id") or "").upper()

    def _handle_telegram(self, telegram) -> None:
        if self._is_fks_sv:
            self._handle_fks_sv_telegram(telegram)
            return

        if str(telegram.sender_id).upper() not in {
            str(self.device_config.get("id")).upper(),
            str(self.device_config.get("sender_id")).upper(),
        }:
            return
        if "temperature" in telegram.decoded:
            self._current_temperature = telegram.decoded["temperature"]
        if "target_temperature" in telegram.decoded:
            try:
                decoded_target = float(telegram.decoded["target_temperature"])
            except (TypeError, ValueError):
                decoded_target = None
            if decoded_target is not None and self._attr_min_temp <= decoded_target <= self._attr_max_temp:
                self._target_temperature = decoded_target
            elif self._target_temperature is None:
                self._target_temperature = self._attr_min_temp
        if "hvac_mode" in telegram.decoded:
            mode = str(telegram.decoded["hvac_mode"]).lower()
            self._attr_hvac_mode = HVACMode.HEAT if mode == "heat" else HVACMode.OFF
        heater_mode = telegram.decoded.get("heater_mode")
        if heater_mode is None:
            heating_mode = str(telegram.decoded.get("heating_mode") or "").lower()
            heater_mode = {
                "normal": "normal",
                "night_reduction": "night_setback",
                "reduced": "setback",
                "frost_protection": "off",
            }.get(heating_mode)
        if heater_mode in {"normal", "night_setback", "setback", "off"}:
            self._fhk_heater_mode = str(heater_mode)
            self._attr_hvac_mode = HVACMode.OFF if heater_mode == "off" else HVACMode.HEAT
            self._attr_preset_mode = {
                "normal": PRESET_HOME,
                "night_setback": PRESET_SLEEP,
                "setback": PRESET_ECO,
            }.get(str(heater_mode), self._attr_preset_mode)
        self.schedule_update_ha_state()

    def _handle_fks_sv_telegram(self, telegram) -> None:
        # TX echoes keep their controller sender ID in gateway.py and are also
        # explicitly marked direction=to_actuator. Never interpret them as valve
        # status, especially not DB2.0 as "Ventil blockiert".
        if not self._matches_physical_device(telegram):
            return
        decoded = telegram.decoded or {}
        if decoded.get("direction") == "to_actuator" or decoded.get("tx_echo"):
            return

        self._last_rx = _now_iso()
        if decoded.get("learn_telegram") or decoded.get("learn"):
            # Only answer a genuine bidirectional teach-in query. A response
            # telegram must never trigger another response loop.
            if decoded.get("learn_response"):
                self.schedule_update_ha_state()
                return
            if bool(_device_option(self.device_config, "auto_teach_in", True)):
                query = decoded.get("teach_in_query_data")
                if query is None:
                    data_hex = decoded.get("data_hex")
                    if data_hex:
                        try:
                            query = bytes.fromhex(str(data_hex).replace("-", ""))
                        except ValueError:
                            query = None
                if query is not None and (self._teach_in_reply_task is None or self._teach_in_reply_task.done()):
                    self._teach_in_reply_task = self.gateway.hass.async_create_task(
                        self._async_reply_fks_sv_teach_in(bytes(query))
                    )
            self.schedule_update_ha_state()
            return

        if "temperature" in decoded:
            self._current_temperature = decoded.get("temperature")
        if "valve_position" in decoded:
            try:
                self._valve_position = int(decoded.get("valve_position"))
            except (TypeError, ValueError):
                self._valve_position = None
        for key, attr in (
            ("actuator_obstructed", "_actuator_obstructed"),
            ("window_open", "_window_open"),
            ("contact_open", "_contact_open"),
            ("battery_low", "_battery_low"),
            ("temperature_sensor_failure", "_temperature_sensor_failure"),
            ("energy_storage_charged", "_energy_storage_charged"),
            ("energy_storage_capacity_sufficient", "_energy_storage_capacity_sufficient"),
        ):
            if key in decoded:
                setattr(self, attr, bool(decoded.get(key)))

        self.schedule_update_ha_state()
        # Every genuine valve telegram opens the receive window. The controller
        # must answer every cycle, even when the HA target did not just change.
        if self._control_reply_task is None or self._control_reply_task.done():
            self._control_reply_task = self.gateway.hass.async_create_task(
                self._async_reply_fks_sv_control()
            )

    def _external_room_temperature(self) -> float | None:
        entity_id = _device_option(self.device_config, "room_temperature_entity")
        if not entity_id:
            return None
        state = self.gateway.hass.states.get(str(entity_id))
        if state is None:
            return None
        try:
            temperature = float(state.state)
        except (TypeError, ValueError):
            return None

        attributes = getattr(state, "attributes", {}) or {}
        unit = str(attributes.get("unit_of_measurement") or "").strip().upper()
        if unit in {"°F", "F", "FAHRENHEIT"}:
            temperature = (temperature - 32.0) * 5.0 / 9.0
        elif 40.0 < temperature <= 104.0:
            # Compatibility fallback for older/custom sensors that expose a
            # Fahrenheit value without a unit attribute.
            temperature = (temperature - 32.0) * 5.0 / 9.0
        return max(0.0, min(40.0, temperature))

    async def _async_reply_fks_sv_control(self) -> None:
        ok = await self.gateway.async_send_fks_sv_control_response(
            self.device_config,
            target_temperature=float(self._target_temperature or 20.0),
            room_temperature=self._external_room_temperature(),
            hvac_mode=str(self._attr_hvac_mode),
        )
        if ok:
            self._last_tx = _now_iso()
            self._last_error = None
            self._pending_command = False
            self._successful_replies += 1
        else:
            self._last_error = self.gateway.last_send_error or "unbekannter Fehler"
            self._pending_command = True
        self.schedule_update_ha_state()

    async def _async_reply_fks_sv_teach_in(self, query_data: bytes) -> None:
        ok = await self.gateway.async_send_fks_sv_teach_in_response(
            self.device_config,
            query_data=query_data,
            target_temperature=float(self._target_temperature or 20.0),
            room_temperature=self._external_room_temperature(),
            hvac_mode=str(self._attr_hvac_mode),
        )
        if ok:
            timestamp = _now_iso()
            self._last_teach_in = timestamp
            self._last_tx = timestamp
            self._last_error = None
            self._pending_command = False
            self._successful_replies += 1
        else:
            self._last_error = self.gateway.last_send_error or "unbekannter Fehler"
            self._pending_command = True
        self.schedule_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in self._attr_hvac_modes:
            raise HomeAssistantError(f"Nicht unterstuetzter HVAC-Modus: {hvac_mode}")
        if self._is_fks_sv:
            # Do not transmit blindly: the battery-powered valve may be asleep.
            self._attr_hvac_mode = hvac_mode
            self._pending_command = True
            self.schedule_update_ha_state()
            return

        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "set_hvac_mode",
            hvac_mode=str(hvac_mode),
        )
        if not ok:
            detail = self.gateway.last_send_error or "unbekannter Fehler"
            raise HomeAssistantError(f"ELTAKO Klima-Telegramm konnte nicht gesendet werden: {detail}")
        self._attr_hvac_mode = hvac_mode
        if not self._is_fks_sv:
            self._fhk_heater_mode = "off" if hvac_mode == HVACMode.OFF else "normal"
            if hvac_mode == HVACMode.HEAT:
                self._attr_preset_mode = PRESET_HOME
        self.schedule_update_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if self._is_fks_sv or preset_mode not in (self._attr_preset_modes or []):
            raise HomeAssistantError(f"Nicht unterstuetzte ELTAKO-Betriebsart: {preset_mode}")

        command_mode = {
            PRESET_HOME: "normal",
            PRESET_SLEEP: "night",
            PRESET_ECO: "setback",
        }[preset_mode]
        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "set_preset_mode",
            preset_mode=command_mode,
        )
        if not ok:
            detail = self.gateway.last_send_error or "unbekannter Fehler"
            raise HomeAssistantError(f"ELTAKO Betriebsart-Telegramm konnte nicht gesendet werden: {detail}")
        self._attr_preset_mode = preset_mode
        self._attr_hvac_mode = HVACMode.HEAT
        self._fhk_heater_mode = {
            PRESET_HOME: "normal",
            PRESET_SLEEP: "night_setback",
            PRESET_ECO: "setback",
        }[preset_mode]
        self.schedule_update_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = _coerce_ha_temperature_to_celsius(
            kwargs.get(ATTR_TEMPERATURE),
            min_c=float(self._attr_min_temp or 0),
            max_c=float(self._attr_max_temp or 40),
        )
        if temperature is None:
            raise HomeAssistantError("Keine gueltige Zieltemperatur uebergeben")

        if self._is_fks_sv:
            # Store only. The value is sent after the next physical FKS-SV
            # telegram (or a short button press) opens its receive window.
            self._target_temperature = temperature
            self._attr_hvac_mode = HVACMode.HEAT
            self._pending_command = True
            self.schedule_update_ha_state()
            return

        heater_mode = self._fhk_heater_mode
        if not self._is_fks_sv and heater_mode == "off":
            # Grimm switches an OFF actuator back to NORMAL when the user
            # chooses a new target temperature.
            heater_mode = "normal"

        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "set_temperature",
            temperature=temperature,
            current_temperature=self._current_temperature,
            heater_mode=heater_mode,
        )
        if not ok:
            detail = self.gateway.last_send_error or "unbekannter Fehler"
            raise HomeAssistantError(f"ELTAKO Temperatur-Telegramm konnte nicht gesendet werden: {detail}")
        self._target_temperature = temperature
        self._attr_hvac_mode = HVACMode.HEAT
        if not self._is_fks_sv:
            self._fhk_heater_mode = heater_mode
            if heater_mode == "normal":
                self._attr_preset_mode = PRESET_HOME
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        for task in (self._control_reply_task, self._teach_in_reply_task):
            if task is not None and not task.done():
                task.cancel()
        if self._remove_listener:
            self._remove_listener()
