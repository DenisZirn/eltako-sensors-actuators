"""Direct PWM output for Eltako FHK61SSR-230V.

The separate A5-38-08 direct-PWM profile is not a temperature controller.
It drives the solid-state relay duty cycle according to the manufacturer
telegram table: DB3=02, DB2=0..100%, DB1=T/10s, DB0=08/09/0A/0B.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_platform

_LOGGER = logging.getLogger(__name__)


def _is_fhk61ssr_pwm(device: dict[str, Any]) -> bool:
    if normalize_platform(device.get("platform")) != "number":
        return False
    model = str(device.get("device_type") or device.get("model") or device.get("name") or "").upper()
    return "FHK61SSR" in model and str(device.get("pwm_mode") or "").lower() == "direct"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    config = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = config.get(CONF_DEVICES) or []
    entities = [
        EltakoFhk61SsrPwm(gateway, device)
        for device in devices
        if isinstance(device, dict) and _is_fhk61ssr_pwm(device)
    ]
    _LOGGER.info("ELTAKO FHK61SSR PWM numbers created: %d", len(entities))
    async_add_entities(entities)


class EltakoFhk61SsrPwm(EltakoYamlEntity, NumberEntity):
    """Writable FHK61SSR PWM duty cycle, not a room-temperature setpoint."""

    _attr_icon = "mdi:pulse"
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "%"
    _attr_mode = "slider"

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._attr_native_value = None
        self._attr_name = "PWM-Stellwert"
        self._last_feedback_percent: int | None = None
        self._last_feedback_period: int | None = None
        self._last_feedback_time: str | None = None
        self._last_requested_percent: int | None = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)
        try:
            period = int(device.get("pwm_period_seconds") or 120)
        except (ValueError, TypeError):
            period = 120
        self._period_seconds = period
        self._attr_extra_state_attributes = {
            **(self._attr_extra_state_attributes or {}),
            "pwm_period_seconds": period,
            "pwm_mode": "direct",
        }

    def _handle_telegram(self, telegram) -> None:
        """Accept only a real device-originated FHK61SSR 4BS PWM echo."""
        if str(telegram.sender_id).upper() != str(self.device_config.get("id") or "").upper():
            return
        decoded = telegram.decoded or {}
        if decoded.get("direction") == "to_actuator" or decoded.get("tx_echo"):
            return
        if decoded.get("org") != "0x07":
            return
        raw = str(decoded.get("data_hex") or "").replace("-", "").replace(" ", "")
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            return
        if len(data) != 4 or data[0] != 0x02 or not 0 <= data[1] <= 100:
            return
        if data[3] not in (0x08, 0x09, 0x0A, 0x0B) or data[2] < 1:
            return
        self._last_feedback_percent = data[1]
        self._last_feedback_period = data[2] * 10
        self._last_feedback_time = datetime.now(timezone.utc).isoformat()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes or {})
        attrs.update({
            "requested_pwm_percent": self._last_requested_percent,
            "confirmed_pwm_percent": self._last_feedback_percent,
            "confirmed_pwm_period_seconds": self._last_feedback_period,
            "last_pwm_feedback": self._last_feedback_time,
            "pwm_feedback_confirmed": self._last_feedback_time is not None,
        })
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = await self.async_get_last_state()
        if previous is None:
            return
        try:
            last = float(previous.state)
        except (ValueError, TypeError):
            return
        if 0 <= last <= 100:
            self._attr_native_value = last

    async def async_set_native_value(self, value: float) -> None:
        percent = int(round(float(value)))
        if percent < 0 or percent > 100:
            raise HomeAssistantError("PWM-Stellwert muss zwischen 0 und 100 % liegen")
        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "fhk61ssr_pwm",
            percentage=percent,
            period_seconds=self._period_seconds,
        )
        if not ok:
            raise HomeAssistantError(
                "ELTAKO FHK61SSR PWM konnte nicht übertragen werden: "
                + (self.gateway.last_send_error or "unbekannter Fehler")
            )
        self._last_requested_percent = percent
        self._attr_native_value = float(percent)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()
