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
from .entity_base import EltakoYamlEntity, normalize_platform, normalize_eep

_LOGGER = logging.getLogger(__name__)


def _is_fhk61ssr_pwm(device: dict[str, Any]) -> bool:
    if normalize_platform(device.get("platform")) != "number":
        return False
    model = str(device.get("device_type") or device.get("model") or device.get("name") or "").upper()
    return (
        "FHK61SSR" in model
        and normalize_eep(device.get("eep")) == "A5-38-08"
        and str(device.get("pwm_mode") or "").strip().lower() == "direct"
    )


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
        self._last_send_success: bool | None = None
        self._last_send_error: str | None = None
        self._last_send_time: str | None = None
        self._last_command_confirmed = False
        self._last_feedback_pwm_enabled: bool | None = None
        self._last_feedback_repeater: bool | None = None
        self._last_feedback_sender_id: str | None = None
        self._dewpoint_input_active: bool | None = None
        self._dewpoint_last_seen: str | None = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)
        try:
            period = int(device.get("pwm_period_seconds") or 120)
        except (ValueError, TypeError):
            period = 120
        if period < 10 or period > 1000 or period % 10 != 0:
            _LOGGER.warning(
                "FHK61SSR %s: invalid PWM period %s; falling back to 120 s",
                device.get("id"), period,
            )
            period = 120
        self._period_seconds = period
        raw_repeater = device.get("pwm_repeater", False)
        self._repeater_enabled = (
            raw_repeater.strip().lower() in {"1", "true", "yes", "on", "ja"}
            if isinstance(raw_repeater, str) else bool(raw_repeater)
        )
        self._attr_extra_state_attributes = {
            **(self._attr_extra_state_attributes or {}),
            "pwm_period_seconds": period,
            "pwm_repeater": self._repeater_enabled,
            "pwm_mode": "direct",
        }

    def _handle_telegram(self, telegram) -> None:
        """Process only physical actor-originated PWM/dewpoint feedback.

        The radio gateway may map an outgoing controller echo onto the logical
        actuator ID. Consequently telegram.sender_id alone is NOT proof that
        this confirmation was transmitted by the FHK61SSR.
        """
        decoded = telegram.decoded or {}
        physical_sender = str(decoded.get("physical_sender_id") or "").upper()
        if physical_sender != str(self.device_config.get("id") or "").upper():
            return
        if decoded.get("direction") == "to_actuator" or decoded.get("tx_echo"):
            return

        if decoded.get("fhk61_feedback_type") == "dewpoint_input":
            active = decoded.get("fhk61_dewpoint_input_active")
            if isinstance(active, bool):
                self._dewpoint_input_active = active
                self._dewpoint_last_seen = datetime.now(timezone.utc).isoformat()
                self.async_write_ha_state()
            return

        if decoded.get("org") != "0x07":
            return
        raw = str(decoded.get("data_hex") or "").replace("-", "").replace(" ", "")
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            return
        if (
            len(data) != 4 or data[0] != 0x02
            or not 0 <= data[1] <= 100
            or not 1 <= data[2] <= 100
            or data[3] not in (0x08, 0x09, 0x0A, 0x0B)
        ):
            return
        self._last_feedback_percent = data[1]
        self._last_feedback_period = data[2] * 10
        self._last_feedback_pwm_enabled = bool(data[3] & 0x01)
        self._last_feedback_repeater = bool(data[3] & 0x02)
        self._last_feedback_sender_id = physical_sender
        self._last_feedback_time = datetime.now(timezone.utc).isoformat()
        self._last_command_confirmed = (
            self._last_requested_percent is not None
            and self._last_feedback_percent == self._last_requested_percent
            and self._last_feedback_period == self._period_seconds
            and self._last_feedback_pwm_enabled == (self._last_requested_percent > 0)
            and self._last_feedback_repeater == self._repeater_enabled
            and self._last_send_success is not False
        )
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes or {})
        attrs.update({
            "requested_pwm_percent": self._last_requested_percent,
            "last_send_success": self._last_send_success,
            "last_send_error": self._last_send_error,
            "last_send_time": self._last_send_time,
            "last_physical_pwm_percent": self._last_feedback_percent,
            "last_physical_pwm_period_seconds": self._last_feedback_period,
            "last_physical_pwm_enabled": self._last_feedback_pwm_enabled,
            "last_physical_pwm_repeater": self._last_feedback_repeater,
            "last_physical_sender_id": self._last_feedback_sender_id,
            "last_pwm_feedback": self._last_feedback_time,
            "pwm_feedback_confirmed": self._last_command_confirmed,
            "taumelde_eingang_aktiv": self._dewpoint_input_active,
            "taumelde_eingang_letzte_meldung": self._dewpoint_last_seen,
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
            # Last requested value, never an acknowledged physical status.
            self._attr_native_value = last
            self._last_requested_percent = int(round(last))

    async def async_set_native_value(self, value: float) -> None:
        percent = int(round(float(value)))
        if percent < 0 or percent > 100:
            raise HomeAssistantError("PWM-Stellwert muss zwischen 0 und 100 % liegen")
        self._last_requested_percent = percent
        self._last_send_time = datetime.now(timezone.utc).isoformat()
        self._last_send_success = None
        self._last_send_error = None
        self._last_command_confirmed = False
        # Record the intent BEFORE sending: the genuine echo may arrive before
        # the awaited gateway transmission finishes.
        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "fhk61ssr_pwm",
            percentage=percent,
            period_seconds=self._period_seconds,
            repeater=self._repeater_enabled,
        )
        if not ok:
            self._last_send_success = False
            self._last_command_confirmed = False
            self._last_send_error = self.gateway.last_send_error or "unbekannter Fehler"
            self.async_write_ha_state()
            raise HomeAssistantError(
                "ELTAKO FHK61SSR PWM konnte nicht übertragen werden: "
                + self._last_send_error
            )
        self._last_send_success = True
        self._attr_native_value = float(percent)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        await super().async_will_remove_from_hass()
