from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoGatewayEntity, EltakoYamlEntity, normalize_eep, normalize_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    gateway = hass.data[DOMAIN][entry.entry_id]

    # Devices imported through the integration configuration are stored in
    # entry.options, not only in entry.data. All other platforms already merge
    # both dictionaries. Without this merge the button platform only created
    # the gateway reconnect button and never saw the imported actuators.
    data = {**entry.data, **entry.options}
    devices = data.get(CONF_DEVICES) or []

    entities: list[ButtonEntity] = [EltakoReconnectGatewayButton(gateway)]
    teach_in_count = 0
    seen_teach_in_keys: set[str] = set()
    for device in devices:
        if not _supports_teach_in_button(device):
            continue
        if _is_frgbw14_device(device):
            # FRGBW14 is a Series-14 bus actuator. Its controller/sensor
            # relation is configured in the actuator/PCT14 and must not be
            # represented by a radio teach-in button in Home Assistant.
            continue
        key = _teach_in_group_key(device)
        if key in seen_teach_in_keys:
            continue
        seen_teach_in_keys.add(key)
        if _is_rgbw_device(device):
            device = _normalize_rgbw_device_for_teach_in(device)
            entities.append(EltakoFrgbwFreeProfileTeachInButton(gateway, device))
            teach_in_count += 1
        else:
            for button_entity in _build_teach_in_buttons_for_device(gateway, device):
                entities.append(button_entity)
                teach_in_count += 1

    _LOGGER.info(
        "ELTAKO button platform setup: imported_devices=%s teach_in_buttons=%s total_buttons=%s",
        len(devices) if isinstance(devices, list) else 0,
        teach_in_count,
        len(entities),
    )
    async_add_entities(entities)


def _supports_teach_in_button(device: Any) -> bool:
    if not isinstance(device, dict):
        return False
    platform = normalize_platform(device.get("platform"))
    if platform not in {"light", "cover", "climate", "switch"}:
        return False
    # FKS-SV teach-in is initiated by a short press on the physical valve. The
    # integration then answers its A5-20-01 teach-in query from the configured
    # sender.id. A generic one-way "Lerntelegramm senden" button is misleading
    # and cannot replace that bidirectional handshake.
    if normalize_eep(device.get("eep")) == "A5-20-01":
        return False

    sender_id = device.get("sender_id")
    if not sender_id and isinstance(device.get("sender"), dict):
        sender_id = device["sender"].get("id")
    if not sender_id and isinstance(device.get("raw"), dict):
        raw_sender = device["raw"].get("sender")
        if isinstance(raw_sender, dict):
            sender_id = raw_sender.get("id")

    return bool(str(sender_id or "").strip())



def _device_name(device: dict[str, Any]) -> str:
    return str(device.get("name") or "")


def _is_rgbw_device(device: dict[str, Any]) -> bool:
    eep = normalize_eep(device.get("eep"))
    sender_eep = normalize_eep(device.get("sender_eep"))
    name = _device_name(device).upper()
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    raw_text = " ".join(str(raw.get(k) or "") for k in ("name", "device_type", "comment", "model")).upper()
    return (
        eep in {"07-3F-7F"}
        or sender_eep in {"07-3F-7F"}
        or "FRGBW14" in name
        or "FRGBW71" in name
        or "FRGBW14" in raw_text
        or "FRGBW71" in raw_text
    )


def _is_frgbw14_device(device: dict[str, Any]) -> bool:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("model"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("comment"),
        )
    ).upper()
    return "FRGBW14" in text and "FRGBW71" not in text


def _strip_channel_suffix(name: str) -> str:
    import re

    text = str(name or "").strip()
    text = re.sub(r"\s*\((?:\d+)\s*/\s*(?:\d+)\)\s*$", "", text)
    text = re.sub(r"\s+Kanal\s*\d+\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+Channel\s*\d+\s*$", "", text, flags=re.IGNORECASE)
    return text.strip() or str(name or "FRGBW14")


def _channel_suffix(name: str) -> tuple[int | None, int | None]:
    import re

    match = re.search(r"\((\d+)\s*/\s*(\d+)\)\s*$", str(name or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _id_minus_channel_offset(device_id: Any, channel: int | None) -> str | None:
    if channel is None:
        return None
    text = str(device_id or "").strip().upper()
    parts = text.split("-")
    if len(parts) != 4:
        return None
    try:
        value = int("".join(parts), 16) - max(channel - 1, 0)
    except ValueError:
        return None
    if value < 0:
        return None
    return "-".join(f"{(value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _teach_in_group_key(device: dict[str, Any]) -> str:
    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    gateway_key = f"{gateway.get('id') or ''}:{gateway.get('base_id') or ''}"

    if _is_rgbw_device(device):
        raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
        for key in ("base_address", "pct14_address", "address", "entry_address"):
            value = raw.get(key)
            if value not in (None, ""):
                return f"{gateway_key}:frgbw:{value}"

        channel, _total = _channel_suffix(str(device.get("name") or ""))
        base_id = _id_minus_channel_offset(device.get("id"), channel)
        if base_id:
            return f"{gateway_key}:frgbw:{base_id}"

        name = _strip_channel_suffix(str(device.get("name") or "")).upper()
        sender_id = str(device.get("sender_id") or "").upper()
        return f"{gateway_key}:frgbw:{name or sender_id or str(device.get('id') or '').upper()}"

    return f"{gateway_key}:{normalize_platform(device.get('platform'))}:{str(device.get('id') or '').upper()}:{normalize_eep(device.get('eep'))}"


def _normalize_rgbw_device_for_teach_in(device: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(device)
    normalized["platform"] = "light"
    channel, _total = _channel_suffix(str(normalized.get("name") or ""))
    base_id = _id_minus_channel_offset(normalized.get("id"), channel)
    base_name = _strip_channel_suffix(str(normalized.get("name") or "FRGBW14"))
    if base_id and "FRGBW" in base_name.upper():
        base_name = f"FRGBW14 {base_id}"
    normalized["name"] = base_name
    if base_id:
        normalized["id"] = base_id
    normalized["eep"] = "07-3F-7F"
    normalized["sender_eep"] = "07-3F-7F"
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    raw = dict(raw)
    raw["logical_channels"] = 1
    raw["ha_color_control"] = "rgbw"
    raw["collapsed_frgbw_channels"] = True
    normalized["raw"] = raw
    return normalized




def _device_sender_eep(device: dict[str, Any]) -> str:
    value = normalize_eep(device.get("sender_eep"))
    if not value and isinstance(device.get("sender"), dict):
        value = normalize_eep(device["sender"].get("eep"))
    if not value and isinstance(device.get("raw"), dict):
        raw_sender = device["raw"].get("sender")
        if isinstance(raw_sender, dict):
            value = normalize_eep(raw_sender.get("eep"))
    return value


def _device_eep(device: dict[str, Any]) -> str:
    return normalize_eep(device.get("eep"))


def _device_text_upper(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("model"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("comment"),
        )
    ).upper()


def _is_cover_teach_in_device(device: dict[str, Any]) -> bool:
    text = _device_text_upper(device)
    return (
        normalize_platform(device.get("platform")) == "cover"
        or _device_sender_eep(device) in {"H5-3F-7F", "G5-3F-7F", "A5-3F-7F"}
        or _device_eep(device) in {"H5-3F-7F", "G5-3F-7F", "A5-3F-7F"}
        or any(model in text for model in ("FSB61", "FSB62", "FSB71", "FSB14", "FJ62", "FJ62NP", "FJ62NPN"))
    )


def _is_decentral_rocker_actor(device: dict[str, Any]) -> bool:
    text = _device_text_upper(device)
    # These decentralized 61/62/71 devices are often learned in the device's
    # normal button-learning mode as F6-02-01 rocker telegrams. Keep the
    # documented software-controller teach-in button as well, because the
    # correct choice depends on the learning function selected on the actuator.
    return any(
        model in text
        for model in (
            "FSR61", "FSR61NP", "FSR61G", "FSR61LN", "FSR62", "FSR71",
            "FLC61", "FLC61NP", "FL62", "FL62NP", "FSB61", "FSB62", "FSB71",
            "FJ62", "FJ62NP", "FJ62NPN",
        )
    ) or _device_sender_eep(device) in {"F6-02-01"}


def _build_teach_in_buttons_for_device(gateway, device: dict[str, Any]) -> list[ButtonEntity]:
    """Create exactly one teach-in button for an actuator.

    ELTAKO GFVS/controller teach-in uses the documented learn telegram for the
    device profile. For FSB/FJ cover actors this is the direct command learn
    telegram FF-F8-0D-80; no rocker-position specific buttons are required for
    this GFVS path, and adding separate AUF/AB buttons is misleading.
    """
    return [EltakoTeachInButton(gateway, device, suffix="Lerntelegramm senden", command="teach_in")]


class EltakoReconnectGatewayButton(EltakoGatewayEntity, ButtonEntity):
    """Button to close and reopen the serial gateway connection."""

    def __init__(self, gateway) -> None:
        gateway_id = None
        info = getattr(gateway, "selected_gateway", {}) or {}
        if isinstance(info, dict):
            gateway_id = info.get("id")
        label = f"Reconnect Gateway {gateway_id}" if gateway_id is not None else "Reconnect Gateway"
        super().__init__(gateway, label, "reconnect")

    async def async_press(self) -> None:
        try:
            await self.gateway.async_reconnect()
            _LOGGER.info("ELTAKO gateway reconnect completed: entry=%s port=%s", self.gateway.entry_id, self.gateway.port)
        except Exception as err:
            _LOGGER.exception("ELTAKO gateway reconnect failed: entry=%s port=%s", self.gateway.entry_id, self.gateway.port)
            raise HomeAssistantError(f"ELTAKO Gateway konnte nicht neu verbunden werden: {err}") from err


class EltakoTeachInButton(EltakoYamlEntity, ButtonEntity):
    """Button attached to an actuator device to send its HA sender learn telegram."""

    def __init__(self, gateway, device: dict[str, Any], suffix: str | None = None, command: str = "teach_in", icon: str = "mdi:cast-education") -> None:
        gateway_type = str(getattr(gateway, "gateway_type", "") or "").lower()
        label = suffix or ("Funk-Lerntelegramm senden" if gateway_type == "fam-usb" else "Lerntelegramm senden")
        super().__init__(gateway, device, suffix=label)
        self._teach_in_command = command
        self._attr_icon = icon

    async def async_press(self) -> None:
        gateway_type = str(
            getattr(self.gateway, "gateway_type", None)
            or getattr(self.gateway, "configured_gateway_type", None)
            or (getattr(self.gateway, "selected_gateway", {}) or {}).get("device_type")
            or ""
        ).strip().lower()

        # A teach-in button must always build a dedicated teach-in telegram.
        # Older builds used ``turn_on`` for FAM-USB actors. That produced a
        # normal switching command such as 01-00-00-09 and failed for 61/62
        # actuators and covers; covers even raised an unsupported ``turn_on``
        # command because their control methods are open/close/stop.
        command = self._teach_in_command

        _LOGGER.info(
            "ELTAKO teach-in button pressed: command=%s gateway_type=%s device_id=%s name=%s sender_id=%s sender_eep=%s eep=%s",
            command,
            gateway_type,
            self.device_config.get("id"),
            self.device_config.get("name"),
            self.device_config.get("sender_id"),
            self.device_config.get("sender_eep"),
            self.device_config.get("eep"),
        )
        ok = await self.gateway.async_send_actuator_command(self.device_config, command)
        if not ok:
            reason = self.gateway.last_send_error or "unbekannter Fehler"
            raise HomeAssistantError(f"ELTAKO Lern-/Anlerntelegramm konnte nicht gesendet werden: {reason}")
        _LOGGER.info(
            "ELTAKO teach-in/anlern command sent: command=%s gateway_type=%s device_id=%s sender_id=%s sender_eep=%s",
            command,
            gateway_type,
            self.device_config.get("id"),
            self.device_config.get("sender_id"),
            self.device_config.get("sender_eep"),
        )


class EltakoFrgbwFreeProfileTeachInButton(EltakoYamlEntity, ButtonEntity):
    """Button for the documented/GFA5-confirmed FRGBW free-profile teach-in.

    Sends the free RGB profile learn telegram confirmed by the GFA5 trace:
    `FF-F8-0D-87`. The actuator confirms with `FF-F8-0D-86` when accepted.
    """

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device, suffix="Lerntelegramm senden")
        self._attr_icon = "mdi:palette"

    async def async_press(self) -> None:
        _LOGGER.info(
            "ELTAKO FRGBW teach-in button pressed: device_id=%s name=%s sender_id=%s sender_eep=%s eep=%s",
            self.device_config.get("id"),
            self.device_config.get("name"),
            self.device_config.get("sender_id"),
            self.device_config.get("sender_eep"),
            self.device_config.get("eep"),
        )
        ok = await self.gateway.async_send_actuator_command(self.device_config, "frgbw_free_profile_teach_in")
        if not ok:
            reason = self.gateway.last_send_error or "unbekannter Fehler"
            raise HomeAssistantError(f"ELTAKO FRGBW-Freiprofil-Lerntelegramm konnte nicht gesendet werden: {reason}")
        _LOGGER.info(
            "ELTAKO FRGBW teach-in sent: device_id=%s sender_id=%s",
            self.device_config.get("id"),
            self.device_config.get("sender_id"),
        )
