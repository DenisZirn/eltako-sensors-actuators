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
from homeassistant.helpers import area_registry as ar

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
        "meter_tariffs": profile.get("meter_tariffs") or [],
        "room_temperature_entity": None,
        "min_target_temperature": profile.get("min_target_temperature"),
        "max_target_temperature": profile.get("max_target_temperature"),
        "initial_target_temperature": profile.get("initial_target_temperature"),
        "auto_teach_in": profile.get("auto_teach_in"),
        "fbht_temperature": profile.get("fbht_temperature"),
        "ffg7b_three_state": profile.get("ffg7b_three_state"),
        "device_family": profile.get("device_family"),
        "base_id": payload.get("base_id"),
        "physical_unique_id": payload.get("physical_unique_id"),
        "operating_mode": profile.get("operating_mode"),
        "id_range": payload.get("id_range"),
        "input_number": payload.get("input_number"),
        "id_count": profile.get("id_count"),
        "id_offset_start": profile.get("id_offset_start"),
        "channel_count": profile.get("channels") or profile.get("channel_count"),
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
        "f2l14_mode": profile.get("f2l14_mode"),
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
            "beta": "0.2.0-beta.1",
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
        devices[index] = device

    options = dict(entry.options)
    options[CONF_DEVICES] = devices
    options[CONF_RELOAD_AFTER_SAVE] = True
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"saved": True, "index": index, "device": _json_value(device)})


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
    options[CONF_RELOAD_AFTER_SAVE] = True
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"deleted": True, "device": _json_value(removed)})


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
