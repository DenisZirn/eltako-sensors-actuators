from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_platform

_LOGGER = logging.getLogger(__name__)


def _address(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch in "0123456789ABCDEF")


def _is_f2l14(device: dict[str, Any]) -> bool:
    family = str(device.get("device_family") or "").strip().upper()
    if family == "F2L14":
        return True
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("model"),
            device.get("device_type"),
            raw.get("name"),
            raw.get("model"),
            raw.get("device_type"),
            raw.get("device_family"),
        )
    ).upper()
    return "F2L14" in text


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []

    entities = [
        EltakoF2L14Fan(gateway, device)
        for device in devices
        if (
            isinstance(device, dict)
            and normalize_platform(device.get("platform")) == "fan"
            and _is_f2l14(device)
        )
    ]

    _LOGGER.info(
        "ELTAKO fan setup entry=%s imported_devices=%s fan_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)


class EltakoF2L14Fan(EltakoYamlEntity, FanEntity):
    """Two-stage ELTAKO F2L14 fan actor."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = 2

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._attr_translation_key = "f2l14"
        if hasattr(self, "_attr_name"):
            del self._attr_name

        self._stage_1_id = _address(
            device.get("stage_1_id")
            or (device.get("raw") or {}).get("stage_1_id")
            or device.get("id")
        )
        self._stage_2_id = _address(
            device.get("stage_2_id")
            or (device.get("raw") or {}).get("stage_2_id")
        )
        self._mode = str(
            device.get("f2l14_mode")
            or (device.get("raw") or {}).get("f2l14_mode")
            or "exclusive"
        ).strip().lower()
        self._stage_1_on: bool | None = None
        self._stage_2_on: bool | None = None
        self._percentage: int | None = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self) -> bool | None:
        if self._percentage is None:
            return None
        return self._percentage > 0

    @property
    def percentage(self) -> int | None:
        return self._percentage

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self.async_set_percentage(percentage or self._percentage or 50)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_stage(0)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            stage = 0
        elif percentage <= 50:
            stage = 1
        else:
            stage = 2
        await self._async_set_stage(stage)

    async def _async_set_stage(self, stage: int) -> None:
        ok = await self.gateway.async_send_actuator_command(
            self.device_config,
            "f2l14_set_stage",
            stage=stage,
            f2l14_mode=self._mode,
        )
        if not ok:
            raise HomeAssistantError(
                self.gateway.last_send_error
                or "F2L14 command could not be sent."
            )

        # Optimistic update. A physical actuator feedback telegram will confirm
        # and, if necessary, correct this state afterwards.
        if stage == 0:
            self._stage_1_on = False
            self._stage_2_on = False
            self._percentage = 0
        elif stage == 1:
            self._stage_1_on = True
            self._stage_2_on = False
            self._percentage = 50
        else:
            self._stage_1_on = self._mode == "additive"
            self._stage_2_on = True
            self._percentage = 100
        self.async_write_ha_state()

    def _handle_telegram(self, telegram) -> None:
        sender = _address(getattr(telegram, "sender_id", ""))
        if sender not in {self._stage_1_id, self._stage_2_id}:
            return

        decoded = getattr(telegram, "decoded", {}) or {}
        action = decoded.get("button_action", decoded.get("value"))
        try:
            action_value = int(action)
        except (TypeError, ValueError):
            return

        # Series-14 actuator status telegram:
        #   0x70 = relay ON
        #   0x50 = relay OFF
        if action_value not in {0x70, 0x50}:
            return
        state = action_value == 0x70

        if sender == self._stage_1_id:
            self._stage_1_on = state
        if sender == self._stage_2_id:
            self._stage_2_on = state

        if self._stage_2_on:
            self._percentage = 100
        elif self._stage_1_on:
            self._percentage = 50
        elif self._stage_1_on is False and self._stage_2_on is False:
            self._percentage = 0

        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
