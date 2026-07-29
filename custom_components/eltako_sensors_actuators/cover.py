from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

from homeassistant.components.cover import CoverEntity
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.cover import CoverEntityFeature

    _SUPPORT_OPEN = CoverEntityFeature.OPEN
    _SUPPORT_CLOSE = CoverEntityFeature.CLOSE
    _SUPPORT_STOP = CoverEntityFeature.STOP
    _SUPPORT_SET_POSITION = CoverEntityFeature.SET_POSITION
except Exception:  # pragma: no cover
    _SUPPORT_OPEN = 1
    _SUPPORT_CLOSE = 2
    _SUPPORT_SET_POSITION = 4
    _SUPPORT_STOP = 8

from .actuator_feedback import decode_actuator_feedback
from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_platform

_LOGGER = logging.getLogger(__name__)


class _MotionOwner(Enum):
    IDLE = "idle"
    HOME_ASSISTANT = "home_assistant"
    EXTERNAL = "external"


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
        "Eltako cover setup entry=%s imported_devices=%s cover_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)


def _configured_travel_time(device: dict[str, Any], key: str, default: float = 255.0) -> float:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    value = device.get(key, raw.get(key))
    try:
        seconds = float(value) + 1.0
    except (TypeError, ValueError):
        seconds = default
    return max(1.0, min(seconds, 255.0))


class EltakoCover(EltakoYamlEntity, CoverEntity):
    """Time-based Eltako cover with one authoritative movement state machine."""

    _attr_supported_features = (
        _SUPPORT_OPEN | _SUPPORT_CLOSE | _SUPPORT_STOP | _SUPPORT_SET_POSITION
    )

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._position: int | None = None
        self._is_closed: bool | None = None
        self._is_opening = False
        self._is_closing = False

        self._time_opens = _configured_travel_time(device, "time_opens")
        self._time_closes = _configured_travel_time(device, "time_closes")

        self._owner = _MotionOwner.IDLE
        self._movement_task: asyncio.Task | None = None
        self._movement_generation = 0
        self._movement_started_at: float | None = None
        self._movement_start_position: float | None = None
        self._movement_target_position: int | None = None
        self._movement_duration: float | None = None

        self._latched_slider_target: int | None = None
        self._latched_ha_stop_position: int | None = None
        self._command_echo_until = 0.0
        self._pending_external_pulse_task: asyncio.Task | None = None
        self._pending_external_pulse_generation = 0
        self._pending_external_previous_motion: str | None = None

        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_closed(self):
        if self._position is not None:
            return self._position <= 0
        return self._is_closed

    @property
    def current_cover_position(self):
        return self._estimated_position()

    @property
    def is_opening(self):
        return self._is_opening

    @property
    def is_closing(self):
        return self._is_closing

    def _estimated_position(self) -> int | None:
        if (
            self._movement_started_at is None
            or self._movement_start_position is None
            or self._movement_target_position is None
            or self._movement_duration is None
        ):
            return self._position

        duration = max(0.001, self._movement_duration)
        fraction = min(1.0, max(0.0, (time.monotonic() - self._movement_started_at) / duration))
        start = self._movement_start_position
        target = float(self._movement_target_position)
        return max(0, min(100, int(round(start + (target - start) * fraction))))

    def _handle_telegram(self, telegram) -> None:
        feedback = decode_actuator_feedback(
            self.device_config, telegram.decoded, telegram.sender_id
        )
        if feedback is None:
            return

        pulse = feedback.get("cover_pulse")
        if pulse in {0x01, 0x02}:
            self._handle_cover_pulse(int(pulse))
            return

        motion = feedback.get("motion")
        if motion in {"opening", "closing", "stopped"}:
            self._handle_motion_feedback(str(motion))
            return

        updated = False
        if "position" in feedback:
            try:
                self._position = max(0, min(100, int(round(float(feedback["position"])))))
                self._is_closed = self._position == 0
                updated = True
            except (TypeError, ValueError):
                pass
        if "closed" in feedback:
            self._is_closed = bool(feedback["closed"])
            if self._is_closed:
                self._position = 0
            updated = True
        if updated and self._owner is not _MotionOwner.HOME_ASSISTANT:
            self._cancel_movement_task()
            self._set_idle(clear_latch=True)
            self.schedule_update_ha_state()

    def _handle_cover_pulse(self, pulse: int) -> None:
        now = time.monotonic()
        if self._owner is _MotionOwner.HOME_ASSISTANT and now <= self._command_echo_until:
            return
        self._latched_slider_target = None
        self._latched_ha_stop_position = None
        self._cancel_pending_external_pulse()
        motion = "opening" if pulse == 0x01 else "closing"
        self._start_external_movement(motion)

    def _handle_motion_feedback(self, motion: str) -> None:
        if self._owner is _MotionOwner.HOME_ASSISTANT:
            if motion == "stopped":
                self._finish_home_assistant_target()
            else:
                self._cancel_pending_external_pulse()
                self._is_opening = motion == "opening"
                self._is_closing = motion == "closing"
                self.schedule_update_ha_state()
            return

        if self._latched_slider_target is not None:
            if motion == "stopped":
                self._position = self._latched_slider_target
                self._is_closed = self._position == 0
            self._is_opening = False
            self._is_closing = False
            self.schedule_update_ha_state()
            return

        if self._latched_ha_stop_position is not None:
            self._position = self._latched_ha_stop_position
            self._is_closed = self._position == 0
            self._is_opening = False
            self._is_closing = False
            self.schedule_update_ha_state()
            return

        if motion == "stopped":
            self._cancel_pending_external_pulse()
            self._stop_at_estimated_position(clear_latch=False)
            return

        if self._pending_external_pulse_task is not None:
            previous = self._pending_external_previous_motion
            if previous == motion:
                return
            self._cancel_pending_external_pulse()
            self._start_external_movement(motion)
            return

        if self._owner is _MotionOwner.EXTERNAL:
            current_motion = self._current_motion_direction()
            if current_motion == motion:
                return

        self._start_external_movement(motion)

    def _start_external_movement(self, motion: str) -> None:
        current = self._estimated_position()
        if current is None:
            current = 0 if motion == "opening" else 100
        target = 100 if motion == "opening" else 0
        full_time = self._time_opens if motion == "opening" else self._time_closes
        duration = full_time * abs(target - current) / 100.0

        self._begin_movement(
            owner=_MotionOwner.EXTERNAL,
            current=float(current),
            target=target,
            duration=max(0.01, duration),
        )
        generation = self._movement_generation
        self._movement_task = asyncio.create_task(
            self._track_external_movement(generation),
            name=f"eltako_cover_external_{self.entity_id or self.unique_id}",
        )
        self.schedule_update_ha_state()

    async def _track_external_movement(self, generation: int) -> None:
        try:
            while generation == self._movement_generation and self._owner is _MotionOwner.EXTERNAL:
                if self._estimated_position() == self._movement_target_position:
                    target = self._movement_target_position
                    if target is not None:
                        self._position = target
                        self._is_closed = target == 0
                    self._set_idle(clear_latch=False)
                    self.async_write_ha_state()
                    return
                await asyncio.sleep(0.25)
                self.async_write_ha_state()
        except asyncio.CancelledError:
            raise
        finally:
            if self._movement_task is asyncio.current_task():
                self._movement_task = None

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._start_home_assistant_movement(100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._start_home_assistant_movement(0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        estimated = self._estimated_position()
        stop_direction = self._current_motion_direction()
        self._invalidate_movement()
        await self._async_send_or_raise("stop", stop_direction=stop_direction)
        if estimated is not None:
            self._position = estimated
            self._is_closed = estimated == 0
            self._latched_ha_stop_position = estimated
        elif self._position is not None:
            self._latched_ha_stop_position = self._position
        self._set_idle(clear_latch=True, clear_stop_latch=False)
        self.async_write_ha_state()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        target = kwargs.get("position")
        try:
            target_position = max(0, min(100, int(round(float(target)))))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("Ungültige Rollladenposition") from err
        await self._start_home_assistant_movement(target_position)

    async def _start_home_assistant_movement(self, target_position: int) -> None:
        self._latched_slider_target = None
        self._latched_ha_stop_position = None
        self._cancel_pending_external_pulse()
        current = self._estimated_position()

        if current is None:
            if target_position == 0:
                current = 100
            elif target_position == 100:
                current = 0
            else:
                current = 0
                _LOGGER.warning(
                    "Eltako cover %s has no known position; percentage movement starts from 0%%. Drive once fully open or closed to calibrate the estimate.",
                    self.device_config.get("name") or self.device_config.get("id"),
                )

        if target_position == current:
            self._position = target_position
            self._is_closed = target_position == 0
            self._set_idle(clear_latch=False)
            self.async_write_ha_state()
            return

        command = "open" if target_position > current else "close"
        full_time = self._time_opens if command == "open" else self._time_closes
        calculated_duration = full_time * abs(target_position - current) / 100.0
        duration = float(max(1, min(255, int(round(calculated_duration)))))

        self._begin_movement(
            owner=_MotionOwner.HOME_ASSISTANT,
            current=float(current),
            target=target_position,
            duration=duration,
        )
        generation = self._movement_generation
        self._command_echo_until = time.monotonic() + min(1.0, duration * 0.4)
        self.async_write_ha_state()

        try:
            await self._async_send_or_raise(command, duration_seconds=duration)
        except Exception:
            if generation == self._movement_generation:
                self._set_idle(clear_latch=True)
                self.async_write_ha_state()
            raise

        if generation != self._movement_generation or self._owner is not _MotionOwner.HOME_ASSISTANT:
            return

        self._movement_task = asyncio.create_task(
            self._track_home_assistant_target(generation),
            name=f"eltako_cover_target_{self.entity_id or self.unique_id}",
        )

    async def _track_home_assistant_target(self, generation: int) -> None:
        try:
            while generation == self._movement_generation and self._owner is _MotionOwner.HOME_ASSISTANT:
                if self._estimated_position() == self._movement_target_position:
                    self._finish_home_assistant_target()
                    return
                await asyncio.sleep(0.2)
                self.async_write_ha_state()
        except asyncio.CancelledError:
            raise
        finally:
            if self._movement_task is asyncio.current_task():
                self._movement_task = None

    def _finish_home_assistant_target(self) -> None:
        if self._owner is not _MotionOwner.HOME_ASSISTANT:
            return
        target = self._movement_target_position
        if target is None:
            return
        self._position = target
        self._is_closed = target == 0
        self._latched_slider_target = target if 0 < target < 100 else None
        self._invalidate_movement(cancel_current=False)
        self._set_idle(clear_latch=False)
        self.async_write_ha_state()

    def _begin_movement(self, *, owner: _MotionOwner, current: float, target: int, duration: float) -> None:
        self._invalidate_movement()
        self._owner = owner
        self._movement_started_at = time.monotonic()
        self._movement_start_position = current
        self._movement_target_position = target
        self._movement_duration = max(0.01, duration)
        self._is_opening = target > current
        self._is_closing = target < current
        if self._is_opening:
            self._is_closed = False

    def _schedule_delayed_external_stop(self, only_if_moving: bool = True) -> None:
        previous_motion = self._current_motion_direction()
        self._cancel_pending_external_pulse()
        self._pending_external_previous_motion = previous_motion
        self._pending_external_pulse_generation += 1
        generation = self._pending_external_pulse_generation
        self._pending_external_pulse_task = asyncio.create_task(
            self._delayed_external_stop(generation, only_if_moving),
            name=f"eltako_cover_pulse_{self.entity_id or self.unique_id}",
        )

    async def _delayed_external_stop(self, generation: int, only_if_moving: bool) -> None:
        try:
            await asyncio.sleep(0.6)
            if generation != self._pending_external_pulse_generation:
                return
            moving = self._owner is not _MotionOwner.IDLE or self._is_opening or self._is_closing
            if only_if_moving and not moving:
                return
            if moving:
                self._stop_at_estimated_position(clear_latch=True)
        except asyncio.CancelledError:
            raise
        finally:
            if self._pending_external_pulse_task is asyncio.current_task():
                self._pending_external_pulse_task = None

    def _stop_at_estimated_position(self, clear_latch: bool) -> None:
        estimated = self._estimated_position()
        self._invalidate_movement()
        if estimated is not None:
            self._position = estimated
            self._is_closed = estimated == 0
        self._set_idle(clear_latch=clear_latch)
        self.schedule_update_ha_state()

    def _cancel_pending_external_pulse(self) -> None:
        self._pending_external_pulse_generation += 1
        task = self._pending_external_pulse_task
        self._pending_external_pulse_task = None
        self._pending_external_previous_motion = None
        if task is not None and not task.done():
            task.cancel()

    def _invalidate_movement(self, cancel_current: bool = True) -> None:
        self._movement_generation += 1
        task = self._movement_task
        self._movement_task = None
        if cancel_current and task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _cancel_movement_task(self) -> None:
        self._invalidate_movement()

    def _set_idle(self, *, clear_latch: bool, clear_stop_latch: bool = False) -> None:
        self._owner = _MotionOwner.IDLE
        self._is_opening = False
        self._is_closing = False
        self._movement_started_at = None
        self._movement_start_position = None
        self._movement_target_position = None
        self._movement_duration = None
        self._command_echo_until = 0.0
        if clear_latch:
            self._latched_slider_target = None
        if clear_stop_latch:
            self._latched_ha_stop_position = None

    def _current_motion_direction(self) -> str | None:
        if self._is_opening:
            return "opening"
        if self._is_closing:
            return "closing"
        return None

    async def _async_send_or_raise(self, command: str, **kwargs: Any) -> None:
        ok = await self.gateway.async_send_actuator_command(self.device_config, command, **kwargs)
        if not ok:
            detail = getattr(self.gateway, "last_send_error", None)
            suffix = f" Technischer Fehler: {detail}" if detail else ""
            raise HomeAssistantError(
                "Eltako-Telegramm konnte nicht gesendet werden. Prüfe Gateway-Port, sender.id/sender.eep im YAML und ob der Aktor die Sender-ID angelernt hat."
                + suffix
            )

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_pending_external_pulse()
        self._cancel_movement_task()
        if self._remove_listener:
            self._remove_listener()
