from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any
import uuid

import voluptuous as vol
import yaml

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

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
CUSTOM_PROFILE_STORAGE_VERSION = 1
CUSTOM_PROFILE_STORAGE_KEY = f"{DOMAIN}.custom_device_profiles"


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


def _combined_catalog(hass: HomeAssistant) -> dict[str, Any]:
    manager = hass.data.get(DATA_MANAGER, {})
    base = manager.get("catalog") or {"devices": []}
    custom_profiles = manager.get("custom_profiles") or []
    devices = [
        {**profile, "custom": False}
        for profile in base.get("devices", [])
        if isinstance(profile, dict)
    ]
    devices.extend(
        {**profile, "custom": True}
        for profile in custom_profiles
        if isinstance(profile, dict)
    )
    return {
        **base,
        "devices": devices,
        "custom_profile_count": len(custom_profiles),
    }


async def _async_save_custom_profiles(hass: HomeAssistant) -> None:
    manager = hass.data.setdefault(DATA_MANAGER, {})
    store: Store = manager["custom_profile_store"]
    await store.async_save({"profiles": manager.get("custom_profiles") or []})


def _custom_profile_payload(raw: dict[str, Any], *, existing_key: str | None = None) -> dict[str, Any]:
    label = str(raw.get("label") or raw.get("device_type") or "").strip()
    device_type = str(raw.get("device_type") or label or "").strip()
    eep = str(raw.get("eep_out") or raw.get("eep") or "").strip().upper()
    platform = str(raw.get("platform") or "sensor").strip().lower()
    group = str(raw.get("group") or "Sonstige").strip()
    if not label:
        raise ValueError("Name des Geräteprofils fehlt.")
    if not device_type:
        raise ValueError("Gerätetyp fehlt.")
    if not re.fullmatch(r"[A-Z0-9]{2}-[A-Z0-9]{2}-[A-Z0-9]{2}", eep):
        raise ValueError("EEP muss im Format A5-xx-xx, F6-xx-xx, D5-xx-xx usw. angegeben werden.")
    allowed_platforms = {"binary_sensor", "sensor", "light", "switch", "cover", "fan", "climate"}
    if platform not in allowed_platforms:
        raise ValueError(f"Nicht unterstützte Plattform: {platform}")
    device_classes = raw.get("device_classes")
    if isinstance(device_classes, str):
        device_classes = [item.strip() for item in device_classes.split(",") if item.strip()]
    if not isinstance(device_classes, list):
        device_classes = []
    default_dc = str(raw.get("default_dc") or "").strip() or None
    if default_dc and default_dc not in device_classes:
        device_classes = [default_dc, *device_classes]

    key = existing_key or str(raw.get("key") or "").strip()
    if not key.startswith("custom:"):
        key = f"custom:{uuid.uuid4().hex}"

    result = {
        "key": key,
        "label": label,
        "device_type": device_type,
        "group": group,
        "platform": platform,
        "eep_out": eep,
        "eltako": str(raw.get("eltako") or device_type).strip(),
        "device_family": str(raw.get("device_family") or "").strip() or None,
        "device_classes": device_classes,
        "default_dc": default_dc,
        "needs_sender": bool(raw.get("needs_sender")),
        "sender_eep": str(raw.get("sender_eep") or "").strip().upper() or None,
        "teach_in_telegram": str(raw.get("teach_in_telegram") or "").strip().upper() or None,
        "channels": int(raw.get("channels") or 0) or None,
        "custom": True,
    }
    return {key: value for key, value in result.items() if value not in (None, "", [])}


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


def _series14_type_text(device: dict[str, Any]) -> str:
    return " ".join(
        str(value or "")
        for value in (
            device.get("device_type"),
            device.get("model"),
            device.get("profile_key"),
            _device_option_value(device, "device_family"),
        )
    ).upper()


def _series14_device(device: dict[str, Any]) -> bool:
    """Detect central Series-14 devices, including legacy EEDTOY imports."""
    if (
        _device_option_value(device, "bus_address")
        or _device_option_value(device, "bus_base_id")
    ):
        return True
    # Existing EEDTOY configurations prior to the integrated manager did not
    # persist bus_address/bus_base_id. Their technical device type still
    # identifies them unambiguously as Series-14 devices.
    return bool(re.search(r"(?<![A-Z0-9])F[A-Z0-9-]*14[A-Z0-9-]*(?![A-Z0-9])", _series14_type_text(device)))


def _series14_bus_address(device: dict[str, Any]) -> str:
    """Return/derive the Series-14 bus address as 00-00-00-xx."""
    explicit = _optional_normalized_id(_device_option_value(device, "bus_address"))
    if explicit:
        return explicit

    sender_id = _optional_normalized_id(_device_option_value(device, "sender_id"))
    sender_value = _id_to_int(sender_id)
    if sender_value is not None and (sender_value & 0xFFFFFF00) == 0x0000B000:
        return _add_id_offset("00-00-00-00", sender_value & 0xFF) or ""

    device_id = _optional_normalized_id(device.get("id"))
    device_value = _id_to_int(device_id)
    if device_value is not None and (device_value & 0xFFFFFF00) == 0:
        return device_id

    gateway = device.get("gateway")
    gateway_base_id = (
        _optional_normalized_id(gateway.get("base_id"))
        if isinstance(gateway, dict)
        else ""
    )
    gateway_base_value = _id_to_int(gateway_base_id)
    if device_value is not None and gateway_base_value is not None:
        offset = device_value - gateway_base_value
        if 0 <= offset <= 0xFF:
            return _add_id_offset("00-00-00-00", offset) or ""

    name = str(device.get("name") or "")
    match = re.search(r"\b00-00-00-([0-9A-Fa-f]{2})\b", name)
    if match:
        return f"00-00-00-{match.group(1).upper()}"
    return ""


def _series14_bus_offset(device: dict[str, Any]) -> int | None:
    value = _id_to_int(_series14_bus_address(device))
    if value is None:
        return None
    return value & 0xFF


def _series14_bus_base_id(device: dict[str, Any]) -> str:
    """Return/derive the PCT14/FAM14 base ID used by a Series-14 device."""
    explicit = _optional_normalized_id(_device_option_value(device, "bus_base_id"))
    if explicit:
        return explicit

    offset = _series14_bus_offset(device)
    device_value = _id_to_int(device.get("id"))
    if offset is None or device_value is None:
        return ""

    # A direct FGW14/FAM14 bus entity uses 00-00-00-xx and does not encode the
    # FAM14 base ID. A radio-visible PCT14 device (FAM-USB) does: ID=base+address.
    if (device_value & 0xFFFFFF00) == 0:
        return ""
    base_value = (device_value - offset) & 0xFFFFFFFF
    return "-".join(f"{(base_value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _canonicalize_series14_metadata(device: dict[str, Any]) -> dict[str, Any]:
    """Ensure every Series-14 ingress path produces the same bus metadata."""
    if not _series14_device(device):
        return device

    result = dict(device)
    raw = dict(result.get("raw") or {})

    bus_address = _series14_bus_address(result)
    bus_base_id = _series14_bus_base_id(result)

    # Direct FAM14/FGW14 imports may expose the bus address as the device ID.
    # In that case the selected gateway can still carry the PCT14/FAM14 base ID.
    if not bus_base_id:
        gateway = result.get("gateway")
        if isinstance(gateway, dict):
            bus_base_id = _optional_normalized_id(gateway.get("base_id"))

    if bus_address:
        result["bus_address"] = bus_address
        raw["bus_address"] = bus_address
    if bus_base_id:
        result["bus_base_id"] = bus_base_id
        raw["bus_base_id"] = bus_base_id

    result["raw"] = raw
    return result


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



def _optional_normalized_id(value: Any) -> str:
    try:
        return _normalize_id(value)
    except ValueError:
        return ""


def _series14_writer_payloads(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return active RS485 gateways that can program Series-14 actor memory."""
    result: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        gateway = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if gateway is None:
            continue
        gateway_type = str(getattr(gateway, "gateway_type", "") or "").lower()
        if gateway_type not in {"fam14", "fgw14usb"}:
            continue
        data = {**entry.data, **entry.options}
        selected_gateway = data.get(CONF_SELECTED_YAML_GATEWAY)
        base_id = (
            getattr(gateway, "base_id", None)
            or (
                selected_gateway.get("base_id")
                if isinstance(selected_gateway, dict)
                else None
            )
        )
        result.append(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "gateway_type": gateway_type,
                "base_id": _optional_normalized_id(base_id),
                "active": True,
            }
        )
    return result


def _series14_programmable_platform(device: dict[str, Any]) -> bool:
    return str(device.get("platform") or "").lower() in {
        "light",
        "switch",
        "cover",
        "fan",
        "climate",
    }


def _series14_candidate_rows(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Build the central-actor programming list shown in the manager dialog."""
    rows: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        data = {**entry.data, **entry.options}
        devices = [
            item
            for item in data.get(CONF_DEVICES) or []
            if isinstance(item, dict)
        ]
        for index, device in enumerate(devices):
            if not _series14_device(device) or not _series14_programmable_platform(device):
                continue
            sender_id = str(_device_option_value(device, "sender_id") or "").strip()
            sender_eep = str(_device_option_value(device, "sender_eep") or "").strip().upper()
            bus_base_id = _series14_bus_base_id(device)
            bus_address = _series14_bus_address(device)
            issues: list[str] = []
            if not bus_base_id:
                issues.append("PCT14-Basis-ID fehlt")
            if not bus_address:
                issues.append("Busadresse fehlt")
            if not sender_id:
                issues.append("Sender-ID fehlt")
            if not sender_eep:
                issues.append("Sender-EEP fehlt")
            rows.append(
                {
                    "source_entry_id": entry.entry_id,
                    "source_entry_title": entry.title,
                    "index": index,
                    "name": str(device.get("name") or device.get("device_type") or "Series-14-Aktor"),
                    "device_type": str(device.get("device_type") or device.get("model") or ""),
                    "platform": str(device.get("platform") or ""),
                    "eep": str(device.get("eep") or "").upper(),
                    "bus_address": bus_address,
                    "bus_base_id": bus_base_id,
                    "sender_id": sender_id,
                    "sender_eep": sender_eep,
                    "valid": not issues,
                    "issues": issues,
                }
            )
    return rows


def _series14_program_entry(device: dict[str, Any]) -> dict[str, Any]:
    """Create the exact sender-writer row from one HA device config."""
    sender_id = str(_device_option_value(device, "sender_id") or "").strip()
    sender_eep = str(_device_option_value(device, "sender_eep") or "").strip().upper()
    bus_base_id = _series14_bus_base_id(device)
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
    catalog = _combined_catalog(hass)
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
    device = _canonicalize_series14_metadata(device)
    if (
        _series14_device(device)
        and bool(profile.get("needs_sender"))
        and not device.get("sender_id")
    ):
        bus_offset = _series14_bus_offset(device)
        if bus_offset is not None:
            auto_sender = _add_id_offset("00-00-B0-00", bus_offset)
            if auto_sender:
                device["sender_id"] = auto_sender
                device["sender_id_source"] = "auto_series14"
                raw = dict(device.get("raw") or {})
                raw["sender"] = {
                    "id": auto_sender,
                    "eep": device.get("sender_eep"),
                }
                raw["sender_id_source"] = "auto_series14"
                device["raw"] = raw
    return _canonicalize_series14_metadata(device)


def _device_to_export_item(device: dict[str, Any]) -> dict[str, Any]:
    raw = dict(device.get("raw") or {})
    raw["id"] = device.get("id")
    raw["eep"] = device.get("eep")
    raw["name"] = device.get("name")
    canonical = _canonicalize_series14_metadata(device)
    for key in (
        "device_type",
        "device_family",
        "profile_key",
        "device_class",
        "area",
        "eltako",
        "teach_in_telegram",
        "bus_address",
        "bus_base_id",
        "sender_id_source",
        "time_opens",
        "time_closes",
        "stage_1_id",
        "stage_2_id",
        "f2l14_mode",
        "operating_mode",
        "id_range",
        "channel_count",
    ):
        value = canonical.get(key)
        if value not in (None, "", []):
            raw[key] = value
    if canonical.get("sender_id") or canonical.get("sender_eep"):
        raw["sender"] = {
            "id": canonical.get("sender_id"),
            "eep": canonical.get("sender_eep"),
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
    catalog = _combined_catalog(hass)
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
            "series14_writers": _series14_writer_payloads(hass),
            "series14_candidates": _series14_candidate_rows(hass),
            "beta": "0.2.0-beta.6",
        },
    )



@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/save_profile",
        vol.Required("profile"): dict,
        vol.Optional("key"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_save_profile(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    manager = hass.data.setdefault(DATA_MANAGER, {})
    profiles = [dict(item) for item in manager.get("custom_profiles") or [] if isinstance(item, dict)]
    existing_key = str(msg.get("key") or "").strip() or None
    if existing_key and not existing_key.startswith("custom:"):
        connection.send_error(msg["id"], "system_profile_readonly", "Mitgelieferte Geräteprofile können nicht überschrieben werden. Bitte duplizieren.")
        return
    try:
        profile = _custom_profile_payload(msg["profile"], existing_key=existing_key)
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_profile", str(err))
        return

    if existing_key:
        index = next((i for i, item in enumerate(profiles) if str(item.get("key")) == existing_key), None)
        if index is None:
            connection.send_error(msg["id"], "profile_not_found", "Eigenes Geräteprofil wurde nicht gefunden.")
            return
        profiles[index] = profile
    else:
        profiles.append(profile)

    manager["custom_profiles"] = profiles
    await _async_save_custom_profiles(hass)
    connection.send_result(msg["id"], {"saved": True, "profile": _json_value(profile)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/manager/delete_profile",
        vol.Required("key"): str,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_delete_profile(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    key = str(msg["key"] or "")
    if not key.startswith("custom:"):
        connection.send_error(msg["id"], "system_profile_readonly", "Mitgelieferte Geräteprofile können nicht gelöscht werden.")
        return
    for entry in hass.config_entries.async_entries(DOMAIN):
        data = {**entry.data, **entry.options}
        if any(str(device.get("profile_key") or "") == key for device in data.get(CONF_DEVICES) or [] if isinstance(device, dict)):
            connection.send_error(
                msg["id"],
                "profile_in_use",
                "Dieses Geräteprofil wird noch von mindestens einem konfigurierten Gerät verwendet.",
            )
            return
    manager = hass.data.setdefault(DATA_MANAGER, {})
    profiles = [dict(item) for item in manager.get("custom_profiles") or [] if isinstance(item, dict)]
    new_profiles = [item for item in profiles if str(item.get("key") or "") != key]
    if len(new_profiles) == len(profiles):
        connection.send_error(msg["id"], "profile_not_found", "Eigenes Geräteprofil wurde nicht gefunden.")
        return
    manager["custom_profiles"] = new_profiles
    await _async_save_custom_profiles(hass)
    connection.send_result(msg["id"], {"deleted": True})


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
        vol.Required("type"): f"{DOMAIN}/manager/program_series14_bulk",
        vol.Required("writer_entry_id"): str,
        vol.Required("targets"): list,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_manager_program_series14_bulk(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Program selected PCT14 actors through one associated FAM14/FGW14-USB."""
    writer_entry, writer_gateway = _series14_writer_entry(
        hass,
        msg["writer_entry_id"],
    )
    if writer_entry is None or writer_gateway is None:
        connection.send_error(
            msg["id"],
            "series14_gateway_missing",
            "Das ausgewählte FAM14/FGW14-USB ist nicht aktiv.",
        )
        return

    port = str(getattr(writer_gateway, "port", "") or "")
    gateway_type = str(getattr(writer_gateway, "gateway_type", "") or "").lower()
    if not port or gateway_type not in {"fam14", "fgw14usb"}:
        connection.send_error(
            msg["id"],
            "series14_gateway_invalid",
            "Das ausgewählte RS485-Gateway ist nicht bereit.",
        )
        return

    writer_base_id = _optional_normalized_id(getattr(writer_gateway, "base_id", None))
    writer_rows: list[dict[str, Any]] = []
    selected_devices: list[dict[str, Any]] = []
    validation_errors: list[str] = []

    for target in msg["targets"]:
        if not isinstance(target, dict):
            continue
        source_entry = hass.config_entries.async_get_entry(
            str(target.get("source_entry_id") or "")
        )
        if source_entry is None or source_entry.domain != DOMAIN:
            validation_errors.append("Quell-Gateway wurde nicht gefunden.")
            continue
        source_data = {**source_entry.data, **source_entry.options}
        devices = [
            item
            for item in source_data.get(CONF_DEVICES) or []
            if isinstance(item, dict)
        ]
        try:
            index = int(target.get("index"))
        except (TypeError, ValueError):
            validation_errors.append(f"{source_entry.title}: ungültiger Geräteindex")
            continue
        if index < 0 or index >= len(devices):
            validation_errors.append(f"{source_entry.title}: Geräteindex {index} nicht vorhanden")
            continue
        device = devices[index]
        if not _series14_device(device) or not _series14_programmable_platform(device):
            validation_errors.append(
                f"{device.get('name') or index}: kein programmierbarer Series-14-Aktor"
            )
            continue
        try:
            row = _series14_program_entry(device)
        except ValueError as err:
            validation_errors.append(
                f"{device.get('name') or index}: {err}"
            )
            continue

        expected_base = _optional_normalized_id(row.get("expected_bus_base_id"))
        if writer_base_id and expected_base and writer_base_id != expected_base:
            validation_errors.append(
                f"{device.get('name') or index}: gehört zu FAM14 {expected_base}, ausgewählt ist {writer_base_id}"
            )
            continue

        writer_rows.append(row)
        selected_devices.append(
            {
                "source_entry_id": source_entry.entry_id,
                "source_entry_title": source_entry.title,
                "index": index,
                "name": str(device.get("name") or device.get("device_type") or "Series-14-Aktor"),
                "bus_address": _series14_bus_address(device),
                "bus_base_id": expected_base,
                "sender_id": str(_device_option_value(device, "sender_id") or ""),
                "sender_eep": str(_device_option_value(device, "sender_eep") or ""),
                "writer_device_id": row.get("device_id"),
            }
        )

    if validation_errors:
        connection.send_error(
            msg["id"],
            "series14_validation_failed",
            " | ".join(validation_errors),
        )
        return
    if not writer_rows:
        connection.send_error(
            msg["id"],
            "series14_no_targets",
            "Keine gültigen Series-14-Aktoren ausgewählt.",
        )
        return

    diagnostic_event(
        hass,
        "series14_bulk_program_start",
        writer_entry_id=writer_entry.entry_id,
        writer_title=writer_entry.title,
        writer_base_id=writer_base_id,
        target_count=len(writer_rows),
        targets=selected_devices,
    )

    await writer_gateway.async_stop()
    try:
        result = await hass.async_add_executor_job(
            lambda: __import__("asyncio").run(
                write_sender_entries(
                    port,
                    writer_rows,
                    baud_rate=57600,
                    gateway_type=gateway_type,
                )
            )
        )
    except Exception as err:
        diagnostic_event(
            hass,
            "series14_bulk_program_failed",
            level="error",
            writer_entry_id=writer_entry.entry_id,
            error=str(err),
        )
        connection.send_error(
            msg["id"],
            "series14_write_failed",
            str(err),
        )
        return
    finally:
        try:
            await writer_gateway.async_start()
        except Exception:
            _LOGGER.exception(
                "Could not restart ELTAKO RS485 gateway after bulk sender programming"
            )

    if not result.get("ok"):
        connection.send_error(
            msg["id"],
            "series14_write_failed",
            str(result.get("error") or "Sender-IDs konnten nicht geschrieben werden."),
        )
        return

    by_device_id: dict[str, list[dict[str, Any]]] = {}
    for event in result.get("events") or []:
        by_device_id.setdefault(str(event.get("device_id") or ""), []).append(event)
    device_results: list[dict[str, Any]] = []
    for selected in selected_devices:
        events = by_device_id.get(str(selected.get("writer_device_id") or ""), [])
        statuses = [str(event.get("status") or "") for event in events]
        if "error" in statuses:
            status = "error"
        elif "updated" in statuses:
            status = "updated"
        elif statuses and all(item == "exists" for item in statuses):
            status = "exists"
        elif "unsupported" in statuses:
            status = "unsupported"
        else:
            status = statuses[0] if statuses else "unknown"
        device_results.append(
            {
                **selected,
                "status": status,
                "events": _json_value(events),
            }
        )

    diagnostic_event(
        hass,
        "series14_bulk_program_finished",
        writer_entry_id=writer_entry.entry_id,
        counts=result.get("counts"),
        results=device_results,
    )
    connection.send_result(
        msg["id"],
        {
            "ok": True,
            "writer_entry_id": writer_entry.entry_id,
            "writer_title": writer_entry.title,
            "fam14_base_id": result.get("fam14_base_id"),
            "counts": _json_value(result.get("counts") or {}),
            "results": _json_value(device_results),
        },
    )


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
    if "custom_profile_store" not in manager:
        manager["custom_profile_store"] = Store(
            hass,
            CUSTOM_PROFILE_STORAGE_VERSION,
            CUSTOM_PROFILE_STORAGE_KEY,
        )
        stored = await manager["custom_profile_store"].async_load() or {}
        profiles = stored.get("profiles", []) if isinstance(stored, dict) else []
        manager["custom_profiles"] = [
            item for item in profiles if isinstance(item, dict) and str(item.get("key") or "").startswith("custom:")
        ]
    if "catalog" not in manager:
        try:
            manager["catalog"] = await hass.async_add_executor_job(_load_catalog_sync)
        except Exception:
            _LOGGER.exception("ELTAKO integrated manager catalog could not be loaded")
            return

    if not manager.get("websocket_registered"):
        websocket_api.async_register_command(hass, websocket_manager_get)
        websocket_api.async_register_command(hass, websocket_manager_save_profile)
        websocket_api.async_register_command(hass, websocket_manager_delete_profile)
        websocket_api.async_register_command(hass, websocket_manager_save_device)
        websocket_api.async_register_command(hass, websocket_manager_delete_device)
        websocket_api.async_register_command(hass, websocket_manager_import_preview)
        websocket_api.async_register_command(hass, websocket_manager_apply_import)
        websocket_api.async_register_command(hass, websocket_manager_learn)
        websocket_api.async_register_command(hass, websocket_manager_program_series14_bulk)
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
