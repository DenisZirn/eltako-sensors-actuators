from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .entity_base import device_key, legacy_device_key
from .manager_importers import detect_import_format, parse_minisafe2, parse_pct14_xml
from .series14_writer import write_sender_entries
from .yaml_config import EltakoYamlError, parse_eedtoy_yaml

from .const import (
    CONF_DEVICES,
    CONF_RELOAD_AFTER_SAVE,
    CONF_SELECTED_YAML_GATEWAY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DATA_MANAGER = f"{DOMAIN}_manager"
PANEL_URL_PATH = "eltako-manager"
PANEL_NAME = "eltako-manager-panel"
STATIC_BASE_URL = "/eltako_sensors_actuators_manager_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"
PANEL_FILE = FRONTEND_DIR / "manager-panel.js"
CATALOG_FILE = Path(__file__).parent / "eedtoy_catalog.json"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex("-").upper()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_value(vars(value))
    return str(value)


def _load_catalog_sync() -> dict[str, Any]:
    with CATALOG_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not isinstance(data.get("devices"), list):
        raise ValueError("Invalid EEDTOY catalog")
    return data


def _panel_version_sync() -> str:
    import hashlib

    if not PANEL_FILE.is_file():
        raise FileNotFoundError(PANEL_FILE)
    digest = hashlib.sha256()
    digest.update(PANEL_FILE.read_bytes())
    digest.update(CATALOG_FILE.read_bytes())
    return digest.hexdigest()[:10]


def _normalize_id(value: Any) -> str:
    text = str(value or "").strip().upper()
    compact = re.sub(r"[^0-9A-F]", "", text)
    if len(compact) != 8:
        raise ValueError("EnOcean-ID muss aus genau 4 Hex-Bytes bestehen.")
    try:
        bytes.fromhex(compact)
    except ValueError as err:
        raise ValueError("EnOcean-ID enthält ungültige Hex-Zeichen.") from err
    return "-".join(compact[index : index + 2] for index in range(0, 8, 2))


def _id_to_int(value: Any) -> int | None:
    try:
        normalized = _normalize_id(value)
    except ValueError:
        return None
    return int(normalized.replace("-", ""), 16)


def _add_id_offset(base_id: Any, offset: int) -> str | None:
    base_value = _id_to_int(base_id)
    if base_value is None:
        return None
    value = (base_value + int(offset)) & 0xFFFFFFFF
    return "-".join(f"{(value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _pct14_payload_for_entry(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Translate one PCT14 row to the address space of the selected HA gateway."""
    if str(payload.get("source") or "") != "PCT14":
        return payload
    result = dict(payload)
    selected_gateway = data.get(CONF_SELECTED_YAML_GATEWAY)
    configured_type = str(data.get("gateway_type") or "").lower()
    selected_type = str(selected_gateway.get("device_type") or "").lower() if isinstance(selected_gateway, dict) else ""
    gateway_type = selected_type if configured_type == "auto" and selected_type else configured_type
    gateway_base_id = data.get("_runtime_base_id") or (
        selected_gateway.get("base_id")
        if isinstance(selected_gateway, dict)
        else None
    )
    bus_base_id = result.get("bus_base_id")

    def bus_offset(raw: Any) -> int | None:
        value = _id_to_int(raw)
        if value is None:
            return None
        return value

    if gateway_type == "fam-usb" and bus_base_id:
        offset = bus_offset(result.get("id"))
        device_type = str(result.get("profile_key") or "")
        # FWG14MS transmits from its dedicated radio ranges and FTS14EM has
        # its own E1 ranges; neither is a normal Series-14 bus-address mapping.
        if offset is not None and "FWG14MS" not in device_type and "FTS14EM" not in device_type:
            translated = _add_id_offset(bus_base_id, offset)
            if translated:
                result["id"] = translated

        if result.get("stage_1_id") and offset is not None:
            stage_1_offset = bus_offset(result.get("stage_1_id"))
            stage_2_offset = bus_offset(result.get("stage_2_id"))
            if stage_1_offset is not None:
                result["stage_1_id"] = _add_id_offset(bus_base_id, stage_1_offset)
            if stage_2_offset is not None:
                result["stage_2_id"] = _add_id_offset(bus_base_id, stage_2_offset)

        # PCT14 controller sender IDs use bus offsets B0xx. On a FAM-USB the
        # corresponding controller address is based on the FAM-USB base ID.
        sender_offset = bus_offset(result.get("sender_id"))
        if sender_offset is not None and gateway_base_id:
            # EEDTOY maps the actor channel offset, not the literal 0xB0xx,
            # onto the radio gateway base ID.
            actor_offset = offset
            if actor_offset is not None:
                translated_sender = _add_id_offset(gateway_base_id, actor_offset)
                if translated_sender:
                    result["sender_id"] = translated_sender
    return result


def _entry_payload(hass: HomeAssistant, entry) -> dict[str, Any]:
    data = {**entry.data, **entry.options}
    gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    last = getattr(gateway, "last_telegram", None) if gateway is not None else None
    last_payload = None
    if last is not None:
        last_payload = {
            "sender_id": getattr(last, "sender_id", None),
            "eep": getattr(last, "eep", None),
            "decoded": _json_value(getattr(last, "decoded", None)),
        }

    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "gateway_type": data.get("gateway_type"),
        "port": data.get("port"),
        "selected_gateway": _json_value(data.get(CONF_SELECTED_YAML_GATEWAY)),
        "devices": _json_value(data.get(CONF_DEVICES) or []),
        "last_telegram": last_payload,
    }



def _registry_prefixes(entry_id: str, device: dict[str, Any]) -> tuple[str, ...]:
    """Return current and legacy entity unique-id prefixes for one logical device."""
    prefix = f"{DOMAIN}_{entry_id}_"
    values = {
        f"{prefix}{device_key(device)}".lower(),
        f"{prefix}{legacy_device_key(device)}".lower(),
    }
    return tuple(sorted(values))


def _same_logical_device(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare the stable technical identity used for registry cleanup."""
    return device_key(left) == device_key(right)


def _async_cleanup_removed_devices(
    hass: HomeAssistant,
    entry_id: str,
    removed_devices: list[dict[str, Any]],
    remaining_devices: list[dict[str, Any]],
) -> dict[str, int]:
    """Remove stale entity/device registry rows after the config entry was reloaded.

    Normal devices own one HA device. Some physical devices (for example FLGTF,
    FTS14EM and F4USM61B) intentionally group several logical rows below one HA
    device. For those, remove only the deleted row's entities while any remaining
    row still references the same HA device. Shared diagnostics are removed only
    when the whole HA device has become orphaned.
    """
    if not removed_devices:
        return {"entities": 0, "devices": 0}

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entry_entities = [
        item
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
        if getattr(item, "platform", None) == DOMAIN
    ]

    removed_prefixes = {
        prefix
        for device in removed_devices
        for prefix in _registry_prefixes(entry_id, device)
    }
    remaining_prefixes = {
        prefix
        for device in remaining_devices
        for prefix in _registry_prefixes(entry_id, device)
    }

    target_device_ids: set[str] = {
        item.device_id
        for item in entry_entities
        if item.device_id
        and any(str(item.unique_id).lower().startswith(prefix) for prefix in removed_prefixes)
    }

    # Fallback for devices that currently have no ordinary entity row. The
    # normal DeviceInfo identifier is (DOMAIN, entry_id, physical_id).
    removed_ids = {
        str(device.get("id") or "").strip().upper()
        for device in removed_devices
        if str(device.get("id") or "").strip()
    }
    if removed_ids:
        for device_entry in dr.async_entries_for_config_entry(device_registry, entry_id):
            for identifier in device_entry.identifiers:
                if (
                    len(identifier) >= 3
                    and identifier[0] == DOMAIN
                    and identifier[1] == entry_id
                    and str(identifier[2]).strip().upper() in removed_ids
                ):
                    target_device_ids.add(device_entry.id)

    removed_entity_count = 0
    removed_device_count = 0

    # Remove registry entries owned by the logical rows that disappeared.
    for item in list(entry_entities):
        if any(str(item.unique_id).lower().startswith(prefix) for prefix in removed_prefixes):
            entity_registry.async_remove(item.entity_id)
            removed_entity_count += 1

    # Re-read registry data after the removals above.
    current_entries = [
        item
        for item in er.async_entries_for_config_entry(entity_registry, entry_id)
        if getattr(item, "platform", None) == DOMAIN
    ]

    for device_id in target_device_ids:
        # A remaining logical row on this same HA device means this is a grouped
        # device. Keep the device and any shared diagnostics.
        has_remaining_peer = any(
            item.device_id == device_id
            and any(str(item.unique_id).lower().startswith(prefix) for prefix in remaining_prefixes)
            for item in current_entries
        )
        if has_remaining_peer:
            continue

        # No configured row remains on this HA device. Remove shared diagnostics
        # and any older registry entries that do not use the standard device-key
        # prefix, then remove the orphaned HA device itself.
        for item in list(current_entries):
            if item.device_id != device_id:
                continue
            entity_registry.async_remove(item.entity_id)
            removed_entity_count += 1

        if device_registry.async_get(device_id) is not None:
            device_registry.async_remove_device(device_id)
            removed_device_count += 1

    return {"entities": removed_entity_count, "devices": removed_device_count}


async def _async_reload_and_cleanup(
    hass: HomeAssistant,
    entry,
    *,
    removed_devices: list[dict[str, Any]],
    remaining_devices: list[dict[str, Any]],
) -> dict[str, int]:
    """Reload one config entry, then prune stale registry objects."""
    reloaded = await hass.config_entries.async_reload(entry.entry_id)
    if not reloaded:
        raise RuntimeError("ELTAKO config entry konnte nach der Änderung nicht neu geladen werden.")
    return _async_cleanup_removed_devices(
        hass,
        entry.entry_id,
        removed_devices,
        remaining_devices,
    )



def _device_option_value(device: dict[str, Any], key: str, default: Any = None) -> Any:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    if device.get(key) not in (None, ""):
        return device.get(key)
    return raw.get(key, default)


def _series14_device(device: dict[str, Any]) -> bool:
    """Return True only when the device carries explicit Series-14 bus metadata."""
    return bool(
        _device_option_value(device, "bus_address")
        or _device_option_value(device, "bus_base_id")
    )


def _series14_bus_offset(device: dict[str, Any]) -> int | None:
    value = _id_to_int(_device_option_value(device, "bus_address"))
    if value is None:
        return None
    return value & 0xFF


def _series14_writer_entry(hass: HomeAssistant, preferred_entry_id: str | None = None):
    """Find an active FAM14/FGW14-USB entry that can own the RS485 port."""
    candidates = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if gateway is None:
            continue
        gateway_type = str(getattr(gateway, "gateway_type", "") or "").lower()
        if gateway_type not in {"fam14", "fgw14usb"}:
            continue
        candidates.append((entry, gateway))
    if preferred_entry_id:
        for entry, gateway in candidates:
            if entry.entry_id == preferred_entry_id:
                return entry, gateway
    return candidates[0] if len(candidates) == 1 else (None, None)


def _series14_program_entry(device: dict[str, Any]) -> dict[str, Any]:
    """Create the exact sender-writer row from one HA device config."""
    sender_id = str(_device_option_value(device, "sender_id") or "").strip()
    sender_eep = str(_device_option_value(device, "sender_eep") or "").strip().upper()
    bus_base_id = str(_device_option_value(device, "bus_base_id") or "").strip().upper()
    bus_offset = _series14_bus_offset(device)
    if not sender_id:
        raise ValueError("Für dieses Gerät ist keine Sender-ID konfiguriert.")
    if not sender_eep:
        raise ValueError("Für dieses Gerät ist kein Sender-EEP konfiguriert.")
    if not bus_base_id or bus_offset is None:
        raise ValueError("PCT14-Busadresse/Base-ID fehlt. Gerät zuerst über PCT14 importieren oder Busadresse ergänzen.")
    bus_device_id = _add_id_offset(bus_base_id, bus_offset)
    if not bus_device_id:
        raise ValueError("Series-14-Busadresse konnte nicht berechnet werden.")
    return {
        "device_id": bus_device_id,
        "sender_id": sender_id,
        "sender_eep": sender_eep,
        "device_eep": str(device.get("eep") or "").upper(),
        "device_type": str(device.get("device_type") or device.get("model") or ""),
        "platform": str(device.get("platform") or ""),
        "name": str(device.get("name") or ""),
        "expected_bus_base_id": bus_base_id,
        "source_gateway_type": "ha",
        "source_gateway_base_id": str((device.get("gateway") or {}).get("base_id") or ""),
        "f2l14_mode": str(_device_option_value(device, "f2l14_mode") or "exclusive"),
    }


def _teach_in_command_for_device(device: dict[str, Any]) -> str:
    eep = str(device.get("eep") or "").strip().upper()
    text = " ".join(
        str(value or "")
        for value in (
            device.get("device_type"),
            device.get("model"),
            device.get("name"),
            _device_option_value(device, "device_family"),
        )
    ).upper()
    if "FRGBW71" in text:
        return "frgbw_free_profile_teach_in"
    if eep == "A5-20-04":
        return "arm_fks_hora_teach_in"
    return "teach_in"


def _profile_map(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    manager = hass.data.get(DATA_MANAGER, {})
    catalog = manager.get("catalog") or {}
    result: dict[str, dict[str, Any]] = {}
    for profile in catalog.get("devices", []):
        if isinstance(profile, dict) and profile.get("key"):
            result[str(profile["key"])] = profile
    return result


def _build_device(
    *,
    profile: dict[str, Any],
    payload: dict[str, Any],
    selected_gateway: dict[str, Any] | None,
) -> dict[str, Any]:
    enocean_id = _normalize_id(payload.get("id"))
    name = str(payload.get("name") or profile.get("device_type") or "ELTAKO Gerät").strip()
    area = str(payload.get("area") or "").strip() or None
    sender_id = str(payload.get("sender_id") or "").strip() or None
    if sender_id:
        sender_id = _normalize_id(sender_id)

    eep = str(profile.get("eep_out") or payload.get("eep") or "").strip().upper()
    platform = str(profile.get("platform") or payload.get("platform") or "sensor").strip()
    device_class = str(
        payload.get("device_class")
        or profile.get("default_dc")
        or ""
    ).strip() or None
    sender_eep = str(profile.get("sender_eep") or payload.get("sender_eep") or "").strip().upper() or None

    raw: dict[str, Any] = {
        key: _json_value(value)
        for key, value in profile.items()
        if key not in {"group", "label", "key", "eep_out", "platform", "default_dc", "device_classes"}
    }
    raw.update(
        {
            "id": enocean_id,
            "eep": eep,
            "name": name,
            "device_type": profile.get("device_type"),
            "device_family": profile.get("device_family"),
            "profile_key": profile.get("key"),
            "device_class": device_class,
            "area": area,
            "eltako": profile.get("eltako"),
            "teach_in_telegram": profile.get("teach_in_telegram"),
        }
    )
    if sender_id or sender_eep:
        raw["sender"] = {"id": sender_id, "eep": sender_eep}

    device: dict[str, Any] = {
        "platform": platform,
        "id": enocean_id,
        "eep": eep,
        "name": name,
        "device_class": device_class,
        "area": area,
        "profile_key": profile.get("key"),
        "device_type": profile.get("device_type"),
        "model": profile.get("device_type"),
        "eltako": profile.get("eltako"),
        "sender_id": sender_id,
        "sender_eep": sender_eep,
        "meter_tariffs": payload.get("meter_tariffs") or profile.get("meter_tariffs") or [],
        "room_temperature_entity": None,
        "min_target_temperature": payload.get("min_target_temperature", profile.get("min_target_temperature")),
        "max_target_temperature": payload.get("max_target_temperature", profile.get("max_target_temperature")),
        "initial_target_temperature": profile.get("initial_target_temperature"),
        "auto_teach_in": profile.get("auto_teach_in"),
        "fbht_temperature": profile.get("fbht_temperature"),
        "ffg7b_three_state": profile.get("ffg7b_three_state"),
        "device_family": profile.get("device_family"),
        "base_id": payload.get("base_id"),
        "physical_unique_id": payload.get("physical_unique_id"),
        "operating_mode": payload.get("operating_mode", profile.get("operating_mode")),
        "id_range": payload.get("id_range") or payload.get("fwg14ms_id_range"),
        "input_number": payload.get("input_number"),
        "id_count": profile.get("id_count"),
        "id_offset_start": profile.get("id_offset_start"),
        "channel_count": payload.get("channel_count") or profile.get("channels") or profile.get("channel_count"),
        "room_controller_mode": profile.get("room_controller_mode"),
        "futh55ed_mode": profile.get("futh55ed_mode"),
        "teach_in_telegram": profile.get("teach_in_telegram"),
        "hysteresis": profile.get("hysteresis"),
        "frost_temperature": profile.get("frost_temperature"),
        "dimming_speed": profile.get("dimming_speed"),
        "bidirectional": profile.get("bidirectional"),
        "summer_mode": profile.get("summer_mode"),
        "controller_group": payload.get("controller_group"),
        "allow_shared_sender": payload.get("allow_shared_sender"),
        "stage_1_id": payload.get("stage_1_id"),
        "stage_2_id": payload.get("stage_2_id"),
        "speed_count": profile.get("speed_count"),
        "rocker_positions": profile.get("rocker_positions"),
        "f2l14_mode": payload.get("f2l14_mode") or profile.get("f2l14_mode"),
        "time_opens": payload.get("time_opens"),
        "time_closes": payload.get("time_closes"),
        "sender_id_source": payload.get("sender_id_source"),
        "bus_address": payload.get("bus_address"),
        "bus_base_id": payload.get("bus_base_id"),
        "gateway": _json_value(selected_gateway) if selected_gateway else None,
        "raw": raw,
    }
    return device


def _device_to_export_item(device: dict[str, Any]) -> dict[str, Any]:
    raw = dict(device.get("raw") or {})
    raw["id"] = device.get("id")
    raw["eep"] = device.get("eep")
    raw["name"] = device.get("name")
    for key in ("device_type", "device_family", "profile_key", "device_class", "area", "eltako", "teach_in_telegram"):
        value = device.get(key)
        if value not in (None, "", []):
            raw[key] = value
    if device.get("sender_id") or device.get("sender_eep"):
        raw["sender"] = {
            "id": device.get("sender_id"),
            "eep": device.get("sender_eep"),
        }
    return {key: value for key, value in raw.items() if value not in (None, "")}


def _export_yaml(entry) -> str:
    data = {**entry.data, **entry.options}
    gateway = dict(data.get(CONF_SELECTED_YAML_GATEWAY) or {})
    gateway.setdefault("id", 1)
    gateway.setdefault("device_type", data.get("gateway_type"))
    devices_by_platform: dict[str, list[dict[str, Any]]] = {}
    for device in data.get(CONF_DEVICES) or []:
        if not isinstance(device, dict):
            continue
        platform = str(device.get("platform") or "sensor")
        devices_by_platform.setdefault(platform, []).append(_device_to_export_item(device))
    gateway["devices"] = devices_by_platform
    return yaml.safe_dump(
        {"eltako": {"gateway": [gateway]}},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/manager/get"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_get(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    catalog = hass.data.get(DATA_MANAGER, {}).get("catalog") or {"devices": []}
    areas = [
        {"id": area.id, "name": area.name}
        for area in ar.async_get(hass).async_list_areas()
    ]
    entries = [
        _entry_payload(hass, entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(
        msg["id"],
        {
            "catalog": catalog,
            "areas": sorted(areas, key=lambda item: item["name"].casefold()),
            "entries": entries,
            "beta": "0.2.0-beta.2",
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/save_device",
        vol.Required("entry_id"): str,
        vol.Required("device"): dict,
        vol.Optional("index"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_save_device(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO config entry not found")
        return

    payload = msg["device"]
    profile_key = str(payload.get("profile_key") or "")
    profile = _profile_map(hass).get(profile_key)
    if profile is None:
        connection.send_error(msg["id"], "profile_not_found", "Geräteprofil wurde nicht gefunden")
        return

    data = {**entry.data, **entry.options}
    try:
        device = _build_device(
            profile=profile,
            payload=payload,
            selected_gateway=data.get(CONF_SELECTED_YAML_GATEWAY),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_device", str(err))
        return

    area_name = str(device.get("area") or "").strip()
    if area_name:
        ar.async_get(hass).async_get_or_create(area_name)

    devices = [
        dict(item)
        for item in data.get(CONF_DEVICES) or []
        if isinstance(item, dict)
    ]
    index = msg.get("index")
    replaced_device: dict[str, Any] | None = None
    if index is None:
        for current in devices:
            if (
                str(current.get("id") or "").upper() == device["id"]
                and str(current.get("eep") or "").upper() == device["eep"]
                and str(current.get("device_type") or "") == str(device.get("device_type") or "")
            ):
                connection.send_error(
                    msg["id"],
                    "duplicate_device",
                    "Dieses Gerät ist bereits mit demselben Profil vorhanden.",
                )
                return
        devices.append(device)
        index = len(devices) - 1
    elif index < 0 or index >= len(devices):
        connection.send_error(msg["id"], "invalid_index", "Geräteindex ist ungültig")
        return
    else:
        replaced_device = dict(devices[index])
        devices[index] = device

    options = dict(entry.options)
    options[CONF_DEVICES] = devices
    options.pop(CONF_RELOAD_AFTER_SAVE, None)
    hass.config_entries.async_update_entry(entry, options=options)

    cleanup = {"entities": 0, "devices": 0}
    if replaced_device is not None and not _same_logical_device(replaced_device, device):
        try:
            cleanup = await _async_reload_and_cleanup(
                hass,
                entry,
                removed_devices=[replaced_device],
                remaining_devices=devices,
            )
        except RuntimeError as err:
            connection.send_error(msg["id"], "reload_failed", str(err))
            return
    else:
        # New devices and name/area-only edits still need a reload so entity
        # setup reflects the updated options immediately.
        if not await hass.config_entries.async_reload(entry.entry_id):
            connection.send_error(msg["id"], "reload_failed", "ELTAKO config entry konnte nicht neu geladen werden.")
            return

    connection.send_result(
        msg["id"],
        {"saved": True, "index": index, "device": _json_value(device), "cleanup": cleanup},
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/delete_device",
        vol.Required("entry_id"): str,
        vol.Required("index"): int,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_delete_device(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO config entry not found")
        return
    data = {**entry.data, **entry.options}
    devices = [dict(item) for item in data.get(CONF_DEVICES) or [] if isinstance(item, dict)]
    index = msg["index"]
    if index < 0 or index >= len(devices):
        connection.send_error(msg["id"], "invalid_index", "Geräteindex ist ungültig")
        return
    removed = devices.pop(index)
    options = dict(entry.options)
    options[CONF_DEVICES] = devices
    options.pop(CONF_RELOAD_AFTER_SAVE, None)
    hass.config_entries.async_update_entry(entry, options=options)

    try:
        cleanup = await _async_reload_and_cleanup(
            hass,
            entry,
            removed_devices=[removed],
            remaining_devices=devices,
        )
    except RuntimeError as err:
        connection.send_error(msg["id"], "reload_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {"deleted": True, "device": _json_value(removed), "cleanup": cleanup},
    )



def _suggest_profile_keys(hass: HomeAssistant, telegram) -> list[str]:
    """Return conservative catalog suggestions for one received telegram."""
    decoded = getattr(telegram, "decoded", None) or {}
    configured_eep = str(getattr(telegram, "eep", None) or "").upper()
    detected_eep = str(decoded.get("detected_eep") or configured_eep or "").upper()
    org = decoded.get("org")
    candidates: list[str] = []
    profiles = _profile_map(hass)

    if detected_eep:
        for key, profile in profiles.items():
            if str(profile.get("eep_out") or "").upper() == detected_eep:
                candidates.append(key)
        if candidates:
            return candidates[:20]

    try:
        org_value = int(org) if org is not None else None
    except (TypeError, ValueError):
        org_value = None
    prefix = {0x05: "F6-", 0x06: "A5-", 0x07: "D5-"}.get(org_value)
    if prefix:
        for key, profile in profiles.items():
            if str(profile.get("eep_out") or "").upper().startswith(prefix):
                candidates.append(key)
    return candidates[:30]


def _yaml_preview_rows(hass: HomeAssistant, text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parsed = parse_eedtoy_yaml(text)
    profiles = _profile_map(hass)
    rows: list[dict[str, Any]] = []
    for device in parsed.devices:
        row = dict(device)
        profile_key = str(device.get("profile_key") or "")
        if not profile_key or profile_key not in profiles:
            matches = [
                key for key, profile in profiles.items()
                if str(profile.get("eep_out") or "").upper() == str(device.get("eep") or "").upper()
                and (
                    not device.get("device_type")
                    or str(profile.get("device_type") or "").upper() == str(device.get("device_type") or "").upper()
                )
            ]
            profile_key = matches[0] if len(matches) == 1 else ""
        row.update(
            {
                "selected": True,
                "source": "EEDTOY YAML",
                "profile_key": profile_key,
                "warning": "" if profile_key else "Geräteprofil prüfen/auswählen",
            }
        )
        rows.append(row)
    return rows, {
        "format": "eedtoy_yaml",
        "rows": rows,
        "unsupported": [],
        "summary": {
            "devices": len(rows),
            "gateways": parsed.gateway_count,
        },
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/import_preview",
        vol.Required("text"): str,
        vol.Optional("filename", default=""): str,
        vol.Optional("format", default="auto"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_import_preview(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Parse supported external configurations without changing HA."""
    source = msg["text"]
    selected_format = str(msg.get("format") or "auto").lower()
    if selected_format == "auto":
        selected_format = detect_import_format(source, msg.get("filename", ""))
    catalog = hass.data.get(DATA_MANAGER, {}).get("catalog") or {"devices": []}
    try:
        if selected_format == "pct14":
            result = await hass.async_add_executor_job(parse_pct14_xml, source, catalog)
        elif selected_format == "minisafe2":
            result = await hass.async_add_executor_job(parse_minisafe2, source, catalog)
        elif selected_format in {"eedtoy", "eedtoy_yaml", "yaml"}:
            _, result = _yaml_preview_rows(hass, source)
        else:
            raise ValueError(f"Unbekanntes Importformat: {selected_format}")
    except (ValueError, EltakoYamlError) as err:
        connection.send_error(msg["id"], "import_invalid", str(err))
        return
    connection.send_result(msg["id"], _json_value(result))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/apply_import",
        vol.Required("entry_id"): str,
        vol.Required("rows"): list,
        vol.Optional("replace", default=False): bool,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_apply_import(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Apply selected rows from a preview in one atomic options update."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO config entry not found")
        return

    profiles = _profile_map(hass)
    data = {**entry.data, **entry.options}
    runtime_gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime_gateway is not None and getattr(runtime_gateway, "base_id", None):
        data["_runtime_base_id"] = getattr(runtime_gateway, "base_id")
    previous_devices = [
        dict(item) for item in data.get(CONF_DEVICES) or [] if isinstance(item, dict)
    ]
    devices: list[dict[str, Any]] = [] if msg.get("replace") else list(previous_devices)
    added = 0
    skipped = 0
    errors: list[str] = []

    for row_index, raw_row in enumerate(msg["rows"]):
        if not isinstance(raw_row, dict) or raw_row.get("selected") is False:
            continue
        profile_key = str(raw_row.get("profile_key") or "")
        profile = profiles.get(profile_key)
        if profile is None:
            skipped += 1
            errors.append(f"Zeile {row_index + 1}: Geräteprofil fehlt")
            continue
        payload = _pct14_payload_for_entry(dict(raw_row), data)
        if not payload.get("area"):
            payload["area"] = ""
        try:
            device = _build_device(
                profile=profile,
                payload=payload,
                selected_gateway=data.get(CONF_SELECTED_YAML_GATEWAY),
            )
        except ValueError as err:
            skipped += 1
            errors.append(f"{raw_row.get('name') or row_index + 1}: {err}")
            continue

        duplicate = next(
            (
                current for current in devices
                if str(current.get("id") or "").upper() == str(device.get("id") or "").upper()
                and str(current.get("eep") or "").upper() == str(device.get("eep") or "").upper()
                and str(current.get("device_type") or "") == str(device.get("device_type") or "")
            ),
            None,
        )
        if duplicate is not None:
            skipped += 1
            continue

        area_name = str(device.get("area") or "").strip()
        if area_name:
            ar.async_get(hass).async_get_or_create(area_name)
        devices.append(device)
        added += 1

    options = dict(entry.options)
    options[CONF_DEVICES] = devices
    options.pop(CONF_RELOAD_AFTER_SAVE, None)
    hass.config_entries.async_update_entry(entry, options=options)

    removed_devices: list[dict[str, Any]] = []
    if msg.get("replace"):
        removed_devices = [
            old
            for old in previous_devices
            if not any(_same_logical_device(old, current) for current in devices)
        ]

    try:
        cleanup = await _async_reload_and_cleanup(
            hass,
            entry,
            removed_devices=removed_devices,
            remaining_devices=devices,
        )
    except RuntimeError as err:
        connection.send_error(msg["id"], "reload_failed", str(err))
        return

    connection.send_result(
        msg["id"],
        {
            "applied": True,
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "cleanup": cleanup,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/learn",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_learn(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Subscribe to live gateway telegrams for interactive device learning."""
    gateway = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    if gateway is None:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO gateway not active")
        return

    def on_telegram(telegram) -> None:
        sender_id = str(getattr(telegram, "sender_id", "") or "")
        if not sender_id or sender_id == "__gateway_status__":
            return
        decoded = getattr(telegram, "decoded", None) or {}
        physical_sender = str(decoded.get("physical_sender_id") or sender_id)
        connection.send_event(
            msg["id"],
            {
                "sender_id": sender_id,
                "physical_sender_id": physical_sender,
                "eep": getattr(telegram, "eep", None),
                "decoded": _json_value(decoded),
                "raw": _json_value(getattr(telegram, "raw", None)),
                "profile_suggestions": _suggest_profile_keys(hass, telegram),
            },
        )

    connection.subscriptions[msg["id"]] = gateway.register_listener(on_telegram)
    connection.send_result(msg["id"], {"subscribed": True})



@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/program_device",
        vol.Required("entry_id"): str,
        vol.Required("index"): int,
        vol.Optional("writer_entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_program_device(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Program Series-14 sender memory or send a radio teach-in telegram."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO config entry not found")
        return
    data = {**entry.data, **entry.options}
    devices = [item for item in data.get(CONF_DEVICES) or [] if isinstance(item, dict)]
    index = msg["index"]
    if index < 0 or index >= len(devices):
        connection.send_error(msg["id"], "invalid_index", "Geräteindex ist ungültig")
        return
    device = devices[index]

    if _series14_device(device):
        try:
            writer_row = _series14_program_entry(device)
        except ValueError as err:
            connection.send_error(msg["id"], "series14_invalid", str(err))
            return

        writer_entry, writer_gateway = _series14_writer_entry(
            hass,
            msg.get("writer_entry_id"),
        )
        if writer_entry is None or writer_gateway is None:
            connection.send_error(
                msg["id"],
                "series14_gateway_missing",
                "Zum Schreiben wird ein aktiver FAM14- oder FGW14-USB-Eintrag benötigt.",
            )
            return

        port = str(getattr(writer_gateway, "port", "") or "")
        gateway_type = str(getattr(writer_gateway, "gateway_type", "") or "").lower()
        if not port or gateway_type not in {"fam14", "fgw14usb"}:
            connection.send_error(msg["id"], "series14_gateway_invalid", "RS485-Gateway ist nicht bereit.")
            return

        diagnostic_event(
            hass,
            "series14_program_start",
            entry_id=entry.entry_id,
            writer_entry_id=writer_entry.entry_id,
            device_id=device.get("id"),
            bus_address=_device_option_value(device, "bus_address"),
            sender_id=_device_option_value(device, "sender_id"),
            sender_eep=_device_option_value(device, "sender_eep"),
            port=port,
        )

        # The normal ESP2 reader must release the same serial port before the
        # eltako14bus memory writer takes exclusive ownership of the RS485 bus.
        await writer_gateway.async_stop()
        try:
            result = await hass.async_add_executor_job(
                lambda: __import__("asyncio").run(
                    write_sender_entries(
                        port,
                        [writer_row],
                        baud_rate=57600,
                        gateway_type=gateway_type,
                    )
                )
            )
        except Exception as err:
            diagnostic_event(
                hass,
                "series14_program_failed",
                level="error",
                entry_id=entry.entry_id,
                writer_entry_id=writer_entry.entry_id,
                error=str(err),
            )
            connection.send_error(msg["id"], "series14_write_failed", str(err))
            return
        finally:
            try:
                await writer_gateway.async_start()
            except Exception:
                _LOGGER.exception("Could not restart ELTAKO RS485 gateway after sender programming")

        if not result.get("ok"):
            connection.send_error(
                msg["id"],
                "series14_write_failed",
                str(result.get("error") or "Sender-ID konnte nicht geschrieben werden."),
            )
            return
        diagnostic_event(
            hass,
            "series14_program_finished",
            entry_id=entry.entry_id,
            writer_entry_id=writer_entry.entry_id,
            counts=result.get("counts"),
            events=result.get("events"),
        )
        connection.send_result(
            msg["id"],
            {
                "mode": "series14",
                "result": _json_value(result),
                "writer_entry_id": writer_entry.entry_id,
            },
        )
        return

    gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if gateway is None:
        connection.send_error(msg["id"], "gateway_not_active", "ELTAKO Gateway ist nicht aktiv.")
        return
    sender_id = str(_device_option_value(device, "sender_id") or "").strip()
    if not sender_id:
        connection.send_error(
            msg["id"],
            "sender_missing",
            "Für diesen Aktor ist keine Sender-ID konfiguriert.",
        )
        return

    command = _teach_in_command_for_device(device)
    if command == "arm_fks_hora_teach_in":
        ok = gateway.arm_fks_hora_teach_in(device)
    else:
        ok = await gateway.async_send_actuator_command(device, command)
    if not ok:
        connection.send_error(
            msg["id"],
            "teach_in_failed",
            gateway.last_send_error or "Lerntelegramm konnte nicht gesendet werden.",
        )
        return
    diagnostic_event(
        hass,
        "manager_teach_in_sent",
        entry_id=entry.entry_id,
        device_id=device.get("id"),
        sender_id=sender_id,
        sender_eep=_device_option_value(device, "sender_eep"),
        command=command,
    )
    connection.send_result(
        msg["id"],
        {
            "mode": "radio_teach_in",
            "command": command,
            "sender_id": sender_id,
            "sender_eep": _device_option_value(device, "sender_eep"),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/export_yaml",
        vol.Required("entry_id"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_export_yaml(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "ELTAKO config entry not found")
        return
    connection.send_result(msg["id"], {"yaml": _export_yaml(entry)})


async def async_setup_manager(hass: HomeAssistant) -> None:
    manager = hass.data.setdefault(DATA_MANAGER, {})
    if "catalog" not in manager:
        try:
            manager["catalog"] = await hass.async_add_executor_job(_load_catalog_sync)
        except Exception:
            _LOGGER.exception("ELTAKO integrated manager catalog could not be loaded")
            return

    if not manager.get("websocket_registered"):
        websocket_api.async_register_command(hass, websocket_manager_get)
        websocket_api.async_register_command(hass, websocket_manager_save_device)
        websocket_api.async_register_command(hass, websocket_manager_delete_device)
        websocket_api.async_register_command(hass, websocket_manager_import_preview)
        websocket_api.async_register_command(hass, websocket_manager_apply_import)
        websocket_api.async_register_command(hass, websocket_manager_learn)
        websocket_api.async_register_command(hass, websocket_manager_program_device)
        websocket_api.async_register_command(hass, websocket_manager_export_yaml)
        manager["websocket_registered"] = True

    try:
        version = await hass.async_add_executor_job(_panel_version_sync)
    except Exception:
        _LOGGER.exception("ELTAKO integrated manager frontend is missing")
        return

    if not manager.get("static_registered"):
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(STATIC_BASE_URL, str(FRONTEND_DIR), False)]
            )
            manager["static_registered"] = True
        except Exception:
            _LOGGER.exception("ELTAKO integrated manager static path registration failed")
            return

    if frontend.async_panel_exists(hass, PANEL_URL_PATH):
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_NAME,
        sidebar_title="ELTAKO",
        sidebar_icon="mdi:home-automation",
        module_url=f"{STATIC_BASE_URL}/manager-panel.js?v={version}",
        require_admin=True,
    )
    manager["panel_registered"] = True
    _LOGGER.info("ELTAKO integrated device manager enabled at /%s", PANEL_URL_PATH)
