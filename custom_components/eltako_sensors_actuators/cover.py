from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverEntity
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.cover import CoverEntityFeature
    _SUPPORT_OPEN = CoverEntityFeature.OPEN
    _SUPPORT_CLOSE = CoverEntityFeature.CLOSE
    _SUPPORT_STOP = CoverEntityFeature.STOP
    _SUPPORT_SET_POSITION = CoverEntityFeature.SET_POSITION
except Exception:  # pragma: no cover - older HA compatibility
    _SUPPORT_OPEN = 1
    _SUPPORT_CLOSE = 2
    _SUPPORT_SET_POSITION = 4
    _SUPPORT_STOP = 8

from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []
    entities = [
        EltakoCover(gateway, device)
        for device in devices
        if isinstance(device, dict) and normalize_platform(device.get("platform")) == "cover"
    ]
    _LOGGER.info(
        "ELTAKO cover setup entry=%s imported_devices=%s cover_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)


class EltakoCover(EltakoYamlEntity, CoverEntity):
    _attr_supported_features = (
        _SUPPORT_OPEN | _SUPPORT_CLOSE | _SUPPORT_STOP | _SUPPORT_SET_POSITION
    )

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._is_closed = None
        self._position = None
        self._position_task: asyncio.Task | None = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_closed(self):
        return self._is_closed

    @property
    def current_cover_position(self):
        return self._position

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() not in {
            str(self.device_config.get("id")).upper(),
            str(self.device_config.get("sender_id")).upper(),
        }:
            return
        if "position" in telegram.decoded:
            try:
                self._position = max(0, min(100, int(round(float(telegram.decoded["position"])))))
            except (TypeError, ValueError):
                pass
        if "closed" in telegram.decoded:
            self._is_closed = bool(telegram.decoded["closed"])
            if self._is_closed:
                self._position = 0
        self.schedule_update_ha_state()

    async def async_open_cover(self, **kwargs: Any) -> None:
        self._cancel_position_task()
        await self._async_send_or_raise("open")
        self._position = 100
        self._is_closed = False
        self.schedule_update_ha_state()

    async def async_close_cover(self, **kwargs: Any) -> None:
        self._cancel_position_task()
        await self._async_send_or_raise("close")
        self._position = 0
        self._is_closed = True
        self.schedule_update_ha_state()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        self._cancel_position_task()
        await self._async_send_or_raise("stop")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = max(0, min(100, int(kwargs[ATTR_POSITION])))

        if target == 100:
            await self.async_open_cover()
            return
        if target == 0:
            await self.async_close_cover()
            return

        if self._position is None:
            raise HomeAssistantError(
                "Die aktuelle Position ist noch unbekannt. Fahre den Aktor zuerst einmal voll auf oder zu; danach sind Prozentpositionen verfuegbar."
            )

        current = max(0, min(100, int(self._position)))
        if target == current:
            return

        self._cancel_position_task()
        self._position_task = self.hass.async_create_task(
            self._async_move_to_position(current, target)
        )

    async def _async_move_to_position(self, current: int, target: int) -> None:
        opening = target > current
        command = "open" if opening else "close"
        travel_time = self._travel_time(opening)
        duration = travel_time * abs(target - current) / 100.0

        try:
            await self._async_send_or_raise(command)
            await asyncio.sleep(max(0.05, duration))
            await self._async_send_or_raise("stop")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "ELTAKO cover position movement failed: device=%s current=%s target=%s",
                self.device_config.get("name"),
                current,
                target,
            )
            return
        finally:
            self._position_task = None

        self._position = target
        self._is_closed = target == 0
        self.schedule_update_ha_state()

    def _travel_time(self, opening: bool) -> float:
        raw = self.device_config.get("raw") if isinstance(self.device_config.get("raw"), dict) else {}
        key = "time_opens" if opening else "time_closes"
        value = raw.get(key, self.device_config.get(key, 25))
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return 25.0

    def _cancel_position_task(self) -> None:
        if self._position_task is not None and not self._position_task.done():
            self._position_task.cancel()
        self._position_task = None

    async def _async_send_or_raise(self, command: str) -> None:
        ok = await self.gateway.async_send_actuator_command(self.device_config, command)
        if not ok:
            detail = getattr(self.gateway, "last_send_error", None)
            suffix = f" Technischer Fehler: {detail}" if detail else ""
            raise HomeAssistantError(
                "ELTAKO Telegramm konnte nicht gesendet werden. Pruefe Gateway-Port, sender.id/sender.eep im YAML und ob der Aktor die Sender-ID angelernt hat."
                + suffix
            )
        if command == "open":
            self._is_closed = False
        elif command == "close":
            self._is_closed = True
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_position_task()
        if self._remove_listener:
            self._remove_listener()
