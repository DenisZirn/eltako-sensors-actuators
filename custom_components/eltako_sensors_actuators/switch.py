from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from .actuator_feedback import decode_actuator_feedback
from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_eep, normalize_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []
    entities = [
        EltakoSwitch(gateway, device)
        for device in devices
        if (
            isinstance(device, dict)
            and normalize_platform(device.get("platform")) == "switch"
            and normalize_eep(device.get("eep")) not in ("A5-30-01", "A5-30-03")
        )
    ]
    _LOGGER.info(
        "ELTAKO switch setup entry=%s imported_devices=%s switch_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)


class EltakoSwitch(EltakoYamlEntity, SwitchEntity):
    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._is_on = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._is_on

    def _handle_telegram(self, telegram) -> None:
        feedback = decode_actuator_feedback(
            self.device_config, telegram.decoded, telegram.sender_id
        )
        if feedback is None:
            return
        if "state" in feedback:
            self._is_on = bool(feedback["state"])
        elif "on" in feedback:
            self._is_on = bool(feedback["on"])
        else:
            return
        self.schedule_update_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send_or_raise("turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send_or_raise("turn_off")

    async def _async_send_or_raise(self, command: str) -> None:
        ok = await self.gateway.async_send_actuator_command(self.device_config, command)
        if not ok:
            raise HomeAssistantError(
                "ELTAKO Schreibfunktion ist fuer diesen Schaltaktor noch nicht implementiert. "
                "Die Entitaet wurde aus dem YAML angelegt, aber das Senden von Telegrammen wird im naechsten Schritt hardwareseitig validiert."
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
